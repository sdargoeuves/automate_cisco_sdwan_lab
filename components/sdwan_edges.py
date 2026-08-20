"""
Edge (vEdge/C8000V) automation workflow:
- Create PAYG licenses via Manager API.
- Configure Edge using configure-transaction.
- Copy root cert via SCP, install it, and activate using PAYG token.
"""

import contextlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import sdwan_config as settings
from utils.manager_api_status import get_edge_health_items
from utils.netmiko import (
    bootstrap_initial_config,
    connect_to_device,
    ensure_connection,
    push_cli_config,
    push_config_from_file,
    scp_copy_file,
)
from utils.output import Output, thread_label
from utils.run_stats import increment as increment_run_stat
from utils.run_stats import phase
from utils.sdwan_sdk import SdkCallError, sdk_call_json

out = Output(__name__)

# Serializes the `vedge_cloud activate` step across edge worker threads. Only
# one edge runs activation at a time; a configurable gap is observed after each
# activation so vManage can start processing the resulting CSR before the next
# edge submits its own. Everything outside the lock (initial config, root cert
# install, waiting for the device cert) stays parallel.
_ACTIVATION_LOCK = threading.Lock()
_LATEST_CHASSIS_BY_EDGE: dict[str, str] = {}
_LATEST_CHASSIS_LOCK = threading.Lock()
_LAST_REPORTED_CERT_STATE_BY_EDGE: dict[str, str] = {}
# Last control_connections_up value logged per edge, so we only emit the
# in-window control-plane trace on change (a flap shows up as a transition).
_LAST_REPORTED_CONNS_BY_EDGE: dict[str, int | None] = {}
# Edges whose SDWAN root CA chain we've already installed this process. The root
# chain is per-edge and persists across chassis regenerations, so we install it
# once per edge instead of re-doing SCP + install + poll on every cert retry.
_ROOT_CERT_INSTALLED: set[str] = set()
# Whether any edge has activated yet this process. Guards the one-off
# pre-first-activation pause; only ever touched while holding _ACTIVATION_LOCK.
_FIRST_ACTIVATION_DONE = False
# Edges whose latest chassis stalled at `tokengenerated` — vManage never started
# signing it, so it needs a fresh chassis. Set by the activation hold, consumed by
# the fabric gate so it can regenerate immediately instead of waiting out its own
# timeout on a chassis that is already known to be dead.
_TOKEN_STALLED_EDGES: set[str] = set()
_TOKEN_STALLED_LOCK = threading.Lock()


def _mark_token_stalled(edge_name: str) -> None:
    with _TOKEN_STALLED_LOCK:
        _TOKEN_STALLED_EDGES.add(edge_name)


def _consume_token_stalled(edge_name: str) -> bool:
    """Return True (once) if this edge's chassis stalled at ``tokengenerated``.

    Consuming the mark matters: the gate regenerates on the strength of it, and a
    stale mark would send the replacement chassis straight back for regeneration.
    """
    with _TOKEN_STALLED_LOCK:
        if edge_name in _TOKEN_STALLED_EDGES:
            _TOKEN_STALLED_EDGES.remove(edge_name)
            return True
        return False


def _record_latest_edge_chassis(edge_name: str, chassis_id: str) -> None:
    with _LATEST_CHASSIS_LOCK:
        _LATEST_CHASSIS_BY_EDGE[edge_name] = chassis_id
        _LAST_REPORTED_CERT_STATE_BY_EDGE.pop(edge_name, None)
        # Reset the conns trace so each new chassis attempt starts fresh.
        _LAST_REPORTED_CONNS_BY_EDGE.pop(edge_name, None)


def _get_latest_edge_chassis(edge_name: str) -> str | None:
    with _LATEST_CHASSIS_LOCK:
        return _LATEST_CHASSIS_BY_EDGE.get(edge_name)


def _parse_payg_activity(activity_list: str) -> list[dict]:
    if not activity_list:
        return []

    matches = re.findall(r"-\s+([^,]+),\s*([0-9a-fA-F]+)", activity_list)
    licenses = []
    for chassis, token in matches:
        licenses.append({"chassis": chassis.strip(), "token": token.strip()})
    return licenses


def generate_payg_licenses(
    manager_config,
    count: int,
    wait_seconds: int = None,
) -> list[dict]:
    if wait_seconds is None:
        wait_seconds = settings.waits.after_payg_license
    out.header("EDGE - Generate PAYG Licenses")
    try:
        response = sdk_call_json(
            manager_config,
            "POST",
            "/dataservice/system/device/generate-payg",
            data={
                "numPaygDevices": count,
                "validity": "valid",
                "organization": manager_config.org,
            },
        )
    except SdkCallError as exc:
        out.error(str(exc))
        return []

    activity_list = ""
    if response:
        activity_list = str(response.get("activityList", "") or "")
    licenses = _parse_payg_activity(activity_list)
    if not licenses:
        out.warning("No PAYG licenses were parsed from the Manager response.")
        out.detail(activity_list)
        return []

    out.success(f"Generated {len(licenses)} PAYG license(s)")
    out.spinner_wait(
        f"Waiting {wait_seconds}s for Manager to process license...",
        wait_seconds,
    )
    return licenses


def _clear_logs(net_connect) -> None:
    # Clear logs once
    out.step("Clearing device logging buffer...")
    net_connect.send_command_timing("clear logging")
    net_connect.send_command_timing("")  # Send enter to confirm
    time.sleep(1)  # Wait for clear to complete


def _install_root_cert(net_connect, use_new_roots: bool = False) -> None:
    _clear_logs(net_connect)
    out.step("Installing root certificate on edge...")

    cmd = f"request platform software sdwan root-cert-chain install bootflash:sdwan/{settings.ROOT_CERT}"
    if use_new_roots:
        cmd += " new-roots"
        out.info("Using 'new-roots' option for certificate installation")

    output = net_connect.send_command_timing(
        cmd,
        strip_prompt=False,
        strip_command=False,
    )
    out.log_only(output)
    if "Password:" in output:
        out.warning("Unexpected password prompt during root cert install.")
    out.info("Root certificate installation in progress...")


def _wait_for_edge_cert(
    net_connect,
    poll_interval_seconds: int = None,
    timeout_seconds: int = None,
) -> bool:
    if poll_interval_seconds is None:
        poll_interval_seconds = settings.root_ca_install.poll
    if timeout_seconds is None:
        timeout_seconds = settings.root_ca_install.timeout
    out.step(
        "Waiting for root CA chain to be installed "
        f"(poll {poll_interval_seconds}s, timeout {timeout_seconds}s)..."
    )

    start = time.time()
    while True:
        output = net_connect.send_command_timing(
            "show logging | include ROOT_CERT_CHAIN_INSTALLED"
        )

        # Check for new-roots requirement
        if "new-roots" in output.lower():
            out.warning("Certificate installation requires 'new-roots' option")
            return False

        if "%CERT-5-ROOT_CERT_CHAIN_INSTALLED" in output:
            out.success("Root CA chain status is Installed.")
            return True

        if time.time() - start >= timeout_seconds:
            out.warning("Root CA chain did not reach Installed before timeout.")
            return False

        out.spinner_wait("Next root CA chain check", poll_interval_seconds)


def _clear_sdwan_control_connections(net_connect) -> None:
    """Force a control-plane re-handshake. Useful when vManage has signed the
    device cert but isn't pushing it — the clear forces a fresh handshake during
    which vManage delivers the cert. Harmful while vManage is still signing, so
    we only invoke this on a retry attempt, never during the first wait."""
    out.step("Sending: clear sdwan control connections")
    output = net_connect.send_command_timing("clear sdwan control connections")
    out.log_only(output)


_EDGE_SYSLOG_COMMAND = (
    "show logging | include CERT|VDAEMON|SYSTEM_LICENSE|CONTROL_CONN|CSR|ROOT_CERT"
)

_CERT_DIAGNOSTIC_COMMANDS = [
    "show sdwan control connections",
    "show sdwan control connection-history",
    "show sdwan certificate installed",
    "show sdwan certificate validity",
    _EDGE_SYSLOG_COMMAND,
]


def _run_edge_diagnostic_commands(net_connect, commands: list[str]) -> None:
    """Run diagnostic commands and log each one's output under its own header.

    Uses ``send_command`` (waits for the device prompt) rather than
    ``send_command_timing`` (returns once output goes briefly idle). With
    ``send_command_timing`` a slow command returns only its echo, and the real
    output is then picked up by the *next* command's read — which silently
    shifted every diagnostic block one header out of place in the log.
    """
    for command in commands:
        try:
            output = net_connect.send_command(
                command,
                strip_prompt=False,
                strip_command=False,
                read_timeout=settings.waits.diagnostic_read_timeout,
            )
        except Exception as exc:  # pragma: no cover - defensive diagnostic path
            out.log_only(
                f"Diagnostic command failed: {command}: {exc}",
                level="warning",
            )
            continue
        out.log_only(f"=== Edge cert diagnostic: {command} ===\n{output}")


def _capture_edge_cert_diagnostics(
    net_connect,
    chassis_id: str,
    cert_state: str | None,
) -> None:
    """Log a compact edge-side snapshot when certificate onboarding fails."""
    out.warning(
        "Capturing edge certificate diagnostics in the log "
        f"(chassis {chassis_id}, vManage state {cert_state!r})."
    )
    _run_edge_diagnostic_commands(net_connect, _CERT_DIAGNOSTIC_COMMANDS)


def _capture_post_activation_syslog(net_connect, chassis_id: str) -> None:
    """Log the edge's cert/licence syslog right after activation, always.

    Captured for every edge whether it goes on to succeed or fail, so failures
    have a successful run to be compared against. Without this baseline, signals
    like ``SYSTEM_LICENSE_MISMATCH`` only ever appear in failure logs and look
    causal when they may just be normal activation noise.
    """
    out.log_only(f"Post-activation syslog snapshot for chassis {chassis_id}:")
    _run_edge_diagnostic_commands(net_connect, [_EDGE_SYSLOG_COMMAND])


def _is_edge_in_fabric(manager_config, system_ip: str) -> bool:
    """Has this edge joined the SD-WAN fabric, per vManage?

    Threshold is ``control_connections_up >= 2`` (vBond + vSmart). Just ``> 0``
    matches the vBond-only bootstrap state, which an edge has BEFORE its device
    cert is installed — vBond's DTLS uses the root chain, not the device cert.
    The vSmart connection specifically requires the signed device cert, so
    reaching 2 control connections is the cleanest "cert installed and edge
    authenticated" signal vManage exposes.

    Why not poll ``show sdwan certificate validity`` on the edge CLI? Because
    that command shares a daemon lock with the cert/CSR subsystem and routinely
    returns ``Error: already running by ...`` while vmanage-admin is doing
    NETCONF — which is exactly when we need to read it. vManage's health API
    has no such lock contention.
    """
    items = get_edge_health_items(manager_config)
    for item in items:
        if item.get("system_ip") == system_ip:
            return (item.get("control_connections_up") or 0) >= 2
    return False


def _edge_control_conns(manager_config, system_ip: str) -> int | None:
    """vManage's current ``control_connections_up`` count for ``system_ip``, or
    ``None`` if the edge is absent from the health API.

    Used to log the in-window control-plane trace during cert install. Fabric
    membership is ``>= 2`` (see :func:`_is_edge_in_fabric`); watching the raw
    count reveals whether a failing attempt's DTLS connections flap (e.g.
    ``0 -> 1 -> 0``) while vManage tries to push the signed cert.
    """
    for item in get_edge_health_items(manager_config):
        if item.get("system_ip") == system_ip:
            return _safe_int(item.get("control_connections_up"))
    return None


def _edge_health_trace(item: dict | None) -> tuple:
    """Compact (control_conns_up, bfd_up, reachability) trace from a health item.

    Used to log the in-window control-plane + data-plane state on every change
    during cert install, so we can correlate the DTLS flap (e.g. 0->1->0->2)
    and BFD coming up against the vManage cert-state transitions.
    """
    if not item:
        return (None, None, None)
    return (
        _safe_int(item.get("control_connections_up")),
        _safe_int(item.get("bfd_sessions_up")),
        item.get("reachability"),
    )


def _wait_for_edge_in_fabric(
    manager_config,
    system_ip: str,
    chassis_id: str | None = None,
    poll_interval_seconds: int = None,
    timeout_seconds: int = None,
) -> tuple[bool, str | None]:
    if poll_interval_seconds is None:
        poll_interval_seconds = settings.fabric_gate.poll
    if timeout_seconds is None:
        timeout_seconds = settings.fabric_gate.timeout
    out.step(
        "Waiting for edge to join the SD-WAN fabric per vManage "
        f"(poll {poll_interval_seconds}s, timeout {timeout_seconds}s)..."
    )

    start = time.time()
    last_cert_state = None
    last_trace: object = "unset"
    while True:
        item = next(
            (
                it
                for it in get_edge_health_items(manager_config)
                if it.get("system_ip") == system_ip
            ),
            None,
        )
        conns, bfd, reach = _edge_health_trace(item)
        trace = (conns, bfd, reach)
        if trace != last_trace:
            elapsed = int(time.time() - start)
            out.info(
                f"[+{elapsed}s] control conns up: {conns}, bfd up: {bfd}, "
                f"reachability: {reach}"
            )
            last_trace = trace
        if conns is not None and conns >= 2:
            out.success("Edge has joined the SD-WAN fabric.")
            return True, None

        if chassis_id:
            cert_state = _get_chassis_cert_state(manager_config, chassis_id)
            if cert_state != last_cert_state:
                elapsed = int(time.time() - start)
                out.info(f"[+{elapsed}s] vManage chassis cert state: {cert_state!r}")
                last_cert_state = cert_state
            if cert_state in _CERT_STATES_WHERE_EARLY_RETRY_MAY_HELP:
                increment_run_stat("edge_cert_early_retries")
                out.warning(
                    f"vManage reports {cert_state!r}; retrying without waiting "
                    "for the full fabric timeout."
                )
                return False, cert_state

        if time.time() - start >= timeout_seconds:
            out.warning("Edge did not join the fabric before timeout.")
            return False, last_cert_state

        out.spinner_wait("Next fabric-membership check", poll_interval_seconds)


# vManage's `vedgeCertificateState` values where re-handshaking via `clear` can
# plausibly unblock the cert delivery after a wait timeout. ``certinstalled`` =
# vManage believes the cert is on the edge but control connections may still be
# converging; do not treat it as an immediate failure. ``certinstallfailed`` =
# vManage tried to push and the push failed, so we can retry immediately.
# Any other state ("CSR Generated", "Pending", None, etc.) means vManage hasn't
# actually pushed yet, so `clear` would only disrupt the in-progress signing.
_CERT_STATES_WHERE_CLEAR_MAY_HELP = {"certinstalled", "certinstallfailed"}
_CERT_STATES_WHERE_EARLY_RETRY_MAY_HELP = {"certinstallfailed"}

# vManage is done with a chassis once it reaches one of these; anything else
# (tokengenerated, csrgenerated, ...) means it is still working on it.
_TERMINAL_CERT_STATES = {"certinstalled", "certinstallfailed"}


def _get_chassis_cert_state(manager_config, chassis_id: str) -> str | None:
    """Query vManage's per-chassis ``vedgeCertificateState`` from
    ``/dataservice/system/device/vedges``. Returns the state string (e.g.
    ``"certinstalled"``, ``"certinstallfailed"``, ``"CSR Generated"``) or
    ``None`` if the chassis is missing from the inventory or the call errors.
    """
    try:
        response = sdk_call_json(
            manager_config, "GET", "/dataservice/system/device/vedges"
        )
    except SdkCallError as exc:
        out.log_only(f"vManage cert state query failed: {exc}", level="warning")
        return None
    devices = (response.get("data") or []) if response else []
    for dev in devices:
        if dev.get("chasisNumber") == chassis_id:
            return dev.get("vedgeCertificateState")
    return None


def _wait_for_chassis_cert_settled(
    manager_config,
    chassis_id: str,
    edge_name: str | None = None,
    poll_interval_seconds: int = None,
    timeout_seconds: int = None,
    token_stall_seconds: int = None,
) -> str | None:
    """Block until vManage reaches a terminal cert state for ``chassis_id``.

    Called while holding ``_ACTIVATION_LOCK`` so that only one chassis is ever in
    vManage's signing pipeline.

    Two timeouts, because "not finished yet" and "never started" need different
    patience. A chassis that has reached ``csrgenerated`` gets the full
    ``timeout_seconds`` — a real install has been measured taking up to 392s. One
    still at ``tokengenerated`` after ``token_stall_seconds`` is abandoned early:
    that transition took 45-180s across 30+ measured activations, so past ~300s it
    is not coming. Such an edge is marked so the fabric gate regenerates it at
    once rather than waiting out its own timeout too (that double wait cost one run
    20 minutes).

    Returns the terminal state, or the last observed state on either timeout.
    Timing out is not fatal: we release the lock rather than stall every edge
    queued behind us.
    """
    if poll_interval_seconds is None:
        poll_interval_seconds = settings.cert_install_hold.poll
    if timeout_seconds is None:
        timeout_seconds = settings.cert_install_hold.timeout
    if token_stall_seconds is None:
        token_stall_seconds = settings.waits.token_stall_timeout
    out.step(
        "Holding activation lock until vManage settles this chassis "
        f"(poll {poll_interval_seconds}s, timeout {timeout_seconds}s)..."
    )

    start = time.time()
    last_state: object = "unset"
    state = None
    while True:
        state = _get_chassis_cert_state(manager_config, chassis_id)
        elapsed = time.time() - start
        if state != last_state:
            out.info(f"[+{int(elapsed)}s] chassis cert state: {state!r}")
            last_state = state
        if state in _TERMINAL_CERT_STATES:
            out.success(f"vManage settled this chassis: {state!r}")
            return state
        if (
            token_stall_seconds
            and state == "tokengenerated"
            and elapsed >= token_stall_seconds
        ):
            out.warning(
                f"Chassis never progressed past 'tokengenerated' in "
                f"{token_stall_seconds}s; vManage has not begun signing it, so it "
                "will not recover. Marking for immediate regeneration."
            )
            if edge_name:
                _mark_token_stalled(edge_name)
            return state
        if elapsed >= timeout_seconds:
            out.warning(
                f"vManage did not settle this chassis within {timeout_seconds}s "
                f"(last state {state!r}); releasing the lock and deferring to the "
                "fabric gate."
            )
            return state
        time.sleep(poll_interval_seconds)


# Fields on a `/dataservice/system/device/vedges` entry that indicate whether a
# freshly generated PAYG chassis has been recorded, authorized, and pushed to
# the controllers by vManage. A vBond `SERNTPRES` ("Serial Number not present")
# teardown means the edge tried to connect before its serial reached vBond's
# authorized list — so we snapshot vManage's view right at activation time to
# measure that propagation lag against the cert-install outcome.
_CHASSIS_SNAPSHOT_KEYS = (
    "chasisNumber",
    "serialNumber",
    "validity",
    "state",
    "vedgeCertificateState",
    "vbondSyncStatus",
    "configuredSystemIP",
    "managementSystemIP",
    "expirationDate",
    "uuid",
)


def _log_chassis_authorization_snapshot(
    manager_config, chassis_id: str, label: str
) -> None:
    """Diagnostic: log what vManage knows about ``chassis_id`` at ``label``.

    Used to confirm/refute the theory that ``certinstallfailed`` is driven by
    the chassis serial not having propagated to the controllers (vBond
    ``SERNTPRES``) by activation time. A curated summary goes to the main log
    and the full record to the debug log (so any sync field we did not
    anticipate is still captured). Never raises.
    """
    try:
        response = sdk_call_json(
            manager_config, "GET", "/dataservice/system/device/vedges"
        )
    except SdkCallError as exc:
        out.log_only(
            f"Chassis snapshot ({label}) query failed for {chassis_id}: {exc}",
            level="warning",
        )
        return
    devices = (response.get("data") or []) if response else []
    entry = next((d for d in devices if d.get("chasisNumber") == chassis_id), None)
    if entry is None:
        out.log_only(
            f"Chassis snapshot ({label}): {chassis_id} NOT PRESENT in vManage "
            f"inventory ({len(devices)} vedges total) — serial has not "
            "propagated yet.",
            level="warning",
        )
        return
    summary = {k: entry.get(k) for k in _CHASSIS_SNAPSHOT_KEYS if k in entry}
    out.log_only(f"Chassis snapshot ({label}) for {chassis_id}: {summary}")
    out.log_only(f"Chassis snapshot ({label}) full record: {entry}", level="debug")


def _try_install_device_cert(
    net_connect,
    manager_config,
    config: settings.EdgeConfig,
    chassis_id: str,
    max_attempts: int,
    device_type: str,
):
    """Wait for the edge to join the SD-WAN fabric, with a vManage-informed
    retry strategy.

    Success signal: vManage shows ``control_connections_up >= 2`` for this
    edge's ``system_ip`` (means cert installed and authentication succeeded).
    The signal is read from vManage's health API rather than the edge CLI —
    that CLI is locked by ``vmanage-admin`` NETCONF activity during exactly
    the window we need to read it.

    Strategy on timeout of each attempt (except the last):
      1. Query vManage for the chassis's ``vedgeCertificateState``.
      2. If the state suggests delivery is the missing step (``certinstalled``
         or ``certinstallfailed``), send ``clear sdwan control connections`` to
         force a fresh handshake and retry.
      3. Otherwise (``"CSR Generated"``, ``None``, …) abort early — `clear`
         can't help and would only disrupt vManage if it is still signing.

    Returns True on success, False on timeout/abort.
    """
    for attempt in range(1, max_attempts + 1):
        joined, cert_state = _wait_for_edge_in_fabric(
            manager_config,
            config.system_ip,
            chassis_id=chassis_id,
        )
        if joined:
            return True

        if attempt >= max_attempts:
            _capture_edge_cert_diagnostics(net_connect, chassis_id, cert_state)
            return False

        out.info(
            f"vManage chassis cert state: {cert_state!r} "
            f"(attempt {attempt}/{max_attempts})"
        )

        if cert_state in _CERT_STATES_WHERE_CLEAR_MAY_HELP:
            out.warning(
                f"vManage reports {cert_state!r}; clearing SD-WAN control "
                "connections to force re-delivery..."
            )
            net_connect = ensure_connection(
                net_connect,
                device_type,
                config.mgmt_ip,
                config.username,
                config.password,
            )
            _clear_sdwan_control_connections(net_connect)
            continue

        out.error(
            f"vManage reports cert state {cert_state!r}; clearing would not "
            "help — vManage hasn't completed signing/pushing yet. Investigate "
            "vManage cert config (Administration → Settings → Certificate "
            "Authorization, or check pending CSRs)."
        )
        _capture_edge_cert_diagnostics(net_connect, chassis_id, cert_state)
        return False

    return False


def _activate_edge_license(
    net_connect,
    license_entry: dict,
    retry_wait_seconds: int = None,
    max_attempts: int = None,
) -> bool:
    if retry_wait_seconds is None:
        retry_wait_seconds = settings.payg_activate.wait
    if max_attempts is None:
        max_attempts = settings.payg_activate.max_attempts
    chassis = license_entry.get("chassis")
    token = license_entry.get("token")
    if not chassis or not token:
        raise ValueError("Missing chassis or token for PAYG activation")

    for attempt in range(1, max_attempts + 1):
        out.step(
            f"Activating PAYG license for chassis {chassis} "
            f"(attempt {attempt}/{max_attempts})..."
        )
        output = net_connect.send_command_timing(
            "request platform software sdwan vedge_cloud activate "
            f"chassis-number {chassis} token {token}",
            strip_prompt=False,
            strip_command=False,
        )
        out.log_only(output)
        lower = output.lower()
        if "failed to attach" in lower or "internal error" in lower:
            if attempt < max_attempts:
                out.warning(
                    f"PAYG activation failed; retrying in {retry_wait_seconds}s..."
                )
                increment_run_stat("edge_payg_activation_retries")
                out.spinner_wait(
                    "Waiting to retry PAYG activation",
                    retry_wait_seconds,
                )
                out.step("Re-installing root certificate before retrying activation...")
                _install_root_cert(net_connect)
                out.spinner_wait(
                    f"Waiting {settings.waits.before_edge_activation}s before retrying activation...",
                    settings.waits.before_edge_activation,
                )
                continue
            out.error("PAYG activation failed after retries.")
            return False
        out.success("PAYG license activated")
        return True
    return False


def _get_edge_extra_routing_config(edge_name: str | None) -> str | None:
    if not edge_name:
        return None
    return settings.EDGE_EXTRA_ROUTING_CONFIGS.get(edge_name)


def run_edge_automation(
    config: settings.EdgeConfig,
    initial_config: bool = False,
    config_file: str | None = None,
    cert: bool = False,
    extra_routing: bool = False,
    device_type: str = "cisco_viptela",
    edge_name: str | None = None,
    defer_cert_result: bool = False,
) -> None:
    label = edge_name or "edge"
    # Set a thread-local label so every Output() in this worker — including
    # shared helpers in utils/netmiko — automatically prefixes its lines.
    with thread_label(f"[{label}]"):
        _run_edge_automation_body(
            config,
            initial_config,
            config_file,
            cert,
            extra_routing,
            device_type,
            label,
            defer_cert_result,
        )


def _run_edge_automation_body(
    config: settings.EdgeConfig,
    initial_config: bool,
    config_file: str | None,
    cert: bool,
    extra_routing: bool,
    device_type: str,
    label: str,
    defer_cert_result: bool,
) -> None:
    out.log_only(
        f"Edge run start initial_config={initial_config} cert={cert} "
        f"extra_routing={extra_routing} "
        f"config_file={config_file} label={label}",
    )
    out.header(f"Automation: EDGE - {label}", f"Target: {config.mgmt_ip}")

    net_connect = None

    if initial_config:
        out.header(f"EDGE - {label}: Initial Configuration")
        net_connect = bootstrap_initial_config(
            device_label=label,
            device_type=device_type,
            host=config.mgmt_ip,
            username=config.username,
            default_password=config.default_password,
            updated_password=config.password,
            initial_config=config.initial_config,
            config_mode_command="config-transaction",
            commit_command="commit",
            read_timeout=settings.waits.netmiko_read_timeout,
            config_ready_timeout=settings.config_ready.timeout,
            config_ready_poll_interval=settings.config_ready.poll,
        )
    else:
        # Try configured password first, then default if it fails
        net_connect = connect_to_device(
            device_type,
            config.mgmt_ip,
            config.username,
            config.password,
            exit_on_failure=False,
        )

        if not net_connect:
            out.warning(
                f"Configured password failed for {label}, trying default password..."
            )
            net_connect = connect_to_device(
                device_type,
                config.mgmt_ip,
                config.username,
                config.default_password,
                exit_on_failure=True,  # Exit if both passwords fail
            )

    if config_file:
        out.header(f"EDGE - {label}: Config File")
        net_connect = ensure_connection(
            net_connect,
            device_type,
            config.mgmt_ip,
            config.username,
            config.password,
        )
        push_config_from_file(
            net_connect,
            config_file,
            config_mode_command="config-transaction",
            commit_command="commit",
            read_timeout=settings.waits.netmiko_read_timeout,
        )

    if extra_routing:
        out.header(f"EDGE - {label}: Extra Routing Configuration")
        net_connect = ensure_connection(
            net_connect,
            device_type,
            config.mgmt_ip,
            config.username,
            config.password,
        )
        extra_routing_config = _get_edge_extra_routing_config(label)
        if not extra_routing_config:
            out.error(f"No extra routing config available for {label}.")
            net_connect.disconnect()
            raise SystemExit(1)
        push_cli_config(
            net_connect,
            extra_routing_config,
            config_mode_command="config-transaction",
            commit_command="commit",
            read_timeout=settings.waits.netmiko_read_timeout,
        )

    if cert:
        out.header(f"EDGE: {label} - Certificate and License")
        net_connect = ensure_connection(
            net_connect,
            device_type,
            config.mgmt_ip,
            config.username,
            config.password,
        )
        # Pre-check: if vManage already sees this edge in the fabric (control
        # connections up), skip the full PAYG flow and just send `clear sdwan
        # control connections` to refresh the control plane. Makes `edges
        # --cert` cheap and idempotent on healthy edges; on first-boot the
        # check returns false instantly because the edge isn't in vManage yet.
        if _is_edge_in_fabric(settings.manager, config.system_ip):
            out.info(
                "Edge is already in the fabric per vManage; "
                "refreshing control connections."
            )
            _clear_sdwan_control_connections(net_connect)
            net_connect.disconnect()
            out.success("Disconnected from Edge")
            return
        # The root CA chain is per-edge and persists across chassis regenerations,
        # so only install it once per edge per run — retries just need a fresh
        # PAYG chassis + activation, not another ~2 min SCP + install + poll.
        if label not in _ROOT_CERT_INSTALLED:
            if not scp_copy_file(
                net_connect,
                host=config.validator_ip,
                username=settings.validator.username,
                password=settings.validator.password,
                remote_file=settings.ROOT_CERT,
                destination="bootflash:/sdwan/",
                description="Copying root certificate from validator via SCP...",
            ):
                net_connect.disconnect()
                raise SystemExit(1)
            _install_root_cert(net_connect)
            if not _wait_for_edge_cert(net_connect):
                out.step("Re-installing root certificate with 'new-roots' option...")
                _install_root_cert(net_connect, use_new_roots=True)
                if not _wait_for_edge_cert(net_connect):
                    out.error(
                        "Device certificate still not installed; aborting activation."
                    )
                    net_connect.disconnect()
                    raise SystemExit(1)
            _ROOT_CERT_INSTALLED.add(label)
        else:
            out.info(
                "Root CA chain already installed this run; skipping SCP + install."
            )
        # Serialize the whole PAYG license -> activate -> cert-install cycle across
        # worker threads, so only one chassis is ever in vManage's signing pipeline.
        # A fixed post-activate gap is not enough: the CSR only reaches vManage
        # 1m50s-3m after activation, and that lag varies by more than any sane gap
        # value, so concurrent CSRs still collided and lost. Measured over a 3-edge
        # run, every chassis with the pipeline to itself installed (3/3) and every
        # chassis whose CSR overlapped another in-flight CSR failed (3/3).
        with _ACTIVATION_LOCK:
            # Waiting for this lock can take many minutes (each holder keeps it
            # until vManage settles its chassis), which is long enough for an idle
            # SSH session to be dropped. Revalidate before touching the device:
            # activating on a dead socket loses the whole cycle, and the generated
            # chassis is left stuck at `tokengenerated` — which the missing-chassis
            # fast-bail cannot detect, so the fabric gate then burns its full
            # timeout on it.
            net_connect = ensure_connection(
                net_connect,
                device_type,
                config.mgmt_ip,
                config.username,
                config.password,
            )
            # vManage appears to reject the first cert install of a run if it comes
            # too soon after the controllers sync (see the config comment). Pause
            # once, before generating a licence, so the token isn't ageing while we
            # wait. Retries are deliberately exempt — by then the pipeline is warm.
            global _FIRST_ACTIVATION_DONE
            if not _FIRST_ACTIVATION_DONE:
                _FIRST_ACTIVATION_DONE = True
                if settings.waits.before_first_activation:
                    out.spinner_wait(
                        "First activation of this run: letting vManage settle "
                        f"({settings.waits.before_first_activation}s)...",
                        settings.waits.before_first_activation,
                    )
            licenses = generate_payg_licenses(settings.manager, 1)
            if not licenses:
                out.error("Failed to generate PAYG license; aborting edge automation.")
                net_connect.disconnect()
                raise SystemExit(1)
            license_entry = licenses[0]
            _record_latest_edge_chassis(label, license_entry["chassis"])
            _log_chassis_authorization_snapshot(
                settings.manager, license_entry["chassis"], "pre-activate"
            )
            if not _activate_edge_license(net_connect, license_entry):
                net_connect.disconnect()
                raise SystemExit(1)
            out.spinner_wait(
                "Settling after activation before polling vManage "
                f"({settings.waits.activation_gap}s)...",
                settings.waits.activation_gap,
            )
            _log_chassis_authorization_snapshot(
                settings.manager, license_entry["chassis"], "post-activate-gap"
            )
            _wait_for_chassis_cert_settled(
                settings.manager, license_entry["chassis"], edge_name=label
            )

        # Outside the lock: this is a read-only capture, so it must not extend the
        # serialized activation window for the edges queued behind us. The cert-install
        # hold above can leave this session idle for minutes, so re-establish it first
        # rather than losing the capture to a stale socket.
        net_connect = ensure_connection(
            net_connect,
            device_type,
            config.mgmt_ip,
            config.username,
            config.password,
        )
        _capture_post_activation_syslog(net_connect, license_entry["chassis"])

        if defer_cert_result:
            out.info(
                "PAYG activation completed; deferring final success check to "
                "the multi-edge BFD convergence gate."
            )
        else:
            # Single-edge runs do not have a useful BFD convergence gate, so wait
            # here for vManage to prove fabric membership.
            if not _try_install_device_cert(
                net_connect,
                settings.manager,
                config,
                license_entry["chassis"],
                settings.fabric_gate.max_attempts,
                device_type,
            ):
                out.error("Edge did not join the fabric after PAYG activation.")
                net_connect.disconnect()
                raise SystemExit(1)

    net_connect.disconnect()
    out.success("Disconnected from Edge")


def _run_edges_worker_phase(
    edge_configs: list[settings.EdgeConfig],
    edge_name_by_id: dict[int, str],
    initial_config: bool,
    config_file: str | None,
    cert: bool,
    extra_routing: bool,
    stagger_seconds: float,
    defer_cert_result: bool,
) -> list[str]:
    increment_run_stat("edge_worker_phases")
    failed = []
    with (
        phase("edge_worker_phase"),
        ThreadPoolExecutor(max_workers=len(edge_configs)) as pool,
    ):
        futures = {}
        for i, edge_config in enumerate(edge_configs):
            if i > 0:
                time.sleep(stagger_seconds)
            edge_name = edge_name_by_id.get(id(edge_config), "edge")
            out.step(f"[{edge_name}] Starting...")
            futures[
                pool.submit(
                    run_edge_automation,
                    edge_config,
                    initial_config=initial_config,
                    config_file=config_file,
                    cert=cert,
                    extra_routing=extra_routing,
                    device_type=settings.EDGE_DEVICE_TYPE,
                    edge_name=edge_name,
                    defer_cert_result=defer_cert_result,
                )
            ] = edge_name
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except (SystemExit, Exception) as exc:
                failed.append(name)
                out.error(f"[{name}] failed: {exc}")
    return failed


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _edges_without_bfd(
    edge_configs: list[settings.EdgeConfig],
    edge_name_by_id: dict[int, str],
) -> list[str]:
    health_by_system_ip = {
        item.get("system_ip"): item for item in get_edge_health_items(settings.manager)
    }
    missing_or_down = []
    for edge_config in edge_configs:
        edge_name = edge_name_by_id.get(id(edge_config), edge_config.system_ip)
        item = health_by_system_ip.get(edge_config.system_ip)
        if not item:
            missing_or_down.append(edge_name)
            continue
        if _safe_int(item.get("bfd_sessions_up")) <= 0:
            missing_or_down.append(edge_name)
    return missing_or_down


def _edges_not_in_fabric(
    edge_configs: list[settings.EdgeConfig],
    edge_name_by_id: dict[int, str],
) -> list[str]:
    health_by_system_ip = {
        item.get("system_ip"): item for item in get_edge_health_items(settings.manager)
    }
    missing_or_down = []
    for edge_config in edge_configs:
        edge_name = edge_name_by_id.get(id(edge_config), edge_config.system_ip)
        item = health_by_system_ip.get(edge_config.system_ip)
        if not item:
            missing_or_down.append(edge_name)
            continue
        if _safe_int(item.get("control_connections_up")) < 2:
            missing_or_down.append(edge_name)
    return missing_or_down


def _log_edge_control_conns(
    edge_configs: list[settings.EdgeConfig],
    edge_name_by_id: dict[int, str],
    start: float,
) -> None:
    """Emit each edge's control/BFD/reachability trace on change during the gate.

    The multi-edge convergence gate polls vManage, not the edge, so this is our
    only in-window view of control-plane stability. Logging on change keeps the
    trace compact while still capturing every flap as a transition; the elapsed
    stamp lets us line the flap up against the vManage cert-state transitions.
    """
    health = {
        item.get("system_ip"): item for item in get_edge_health_items(settings.manager)
    }
    elapsed = int(time.time() - start)
    for edge_config in edge_configs:
        name = edge_name_by_id.get(id(edge_config), edge_config.system_ip)
        trace = _edge_health_trace(health.get(edge_config.system_ip))
        if _LAST_REPORTED_CONNS_BY_EDGE.get(name, "unset") != trace:
            conns, bfd, reach = trace
            out.info(
                f"{name}: [+{elapsed}s] control conns up: {conns}, bfd up: {bfd}, "
                f"reachability: {reach}"
            )
            _LAST_REPORTED_CONNS_BY_EDGE[name] = trace


def _dump_gate_failure_diagnostics(
    edge_configs: list[settings.EdgeConfig],
    edge_name_by_id: dict[int, str],
    failed_edges: list[str],
) -> None:
    """Reconnect to each cert-install-failed edge and log a one-shot edge-side
    diagnostic (control connections + history + cert + syslog).

    The convergence gate would otherwise regenerate a new chassis without ever
    looking at *why* the attempt failed, since it only reads vManage. This is
    best-effort and never raises: a failed reconnect just logs a note.
    """
    config_by_name = {edge_name_by_id.get(id(cfg), "edge"): cfg for cfg in edge_configs}
    for name in failed_edges:
        edge_config = config_by_name.get(name)
        if not edge_config:
            continue
        chassis_id = _get_latest_edge_chassis(name) or "unknown"
        with thread_label(f"[{name}]"):
            net_connect = None
            try:
                net_connect = connect_to_device(
                    settings.EDGE_DEVICE_TYPE,
                    edge_config.mgmt_ip,
                    edge_config.username,
                    edge_config.password,
                    exit_on_failure=False,
                )
                if not net_connect:
                    net_connect = connect_to_device(
                        settings.EDGE_DEVICE_TYPE,
                        edge_config.mgmt_ip,
                        edge_config.username,
                        edge_config.default_password,
                        exit_on_failure=False,
                    )
                if not net_connect:
                    out.log_only(
                        "Gate diagnostics: could not connect to edge to capture "
                        "cert-failure diagnostics.",
                        level="warning",
                    )
                    continue
                _capture_edge_cert_diagnostics(
                    net_connect, chassis_id, "certinstallfailed"
                )
            except Exception as exc:  # pragma: no cover - diagnostic path
                out.log_only(f"Gate diagnostics capture failed: {exc}", level="warning")
            finally:
                if net_connect:
                    with contextlib.suppress(Exception):  # pragma: no cover - defensive
                        net_connect.disconnect()


def _wait_for_edges_in_fabric(
    edge_configs: list[settings.EdgeConfig],
    edge_name_by_id: dict[int, str],
) -> list[str]:
    """Wait until every edge reaches >=2 control connections.

    Returns the edges that need a FRESH chassis (regeneration): those whose cert
    genuinely failed (`certinstallfailed`) or never installed within the timeout.
    An edge whose latest chassis is already `certinstalled` is never returned —
    its cert works, so control still <2 is a convergence/data-plane matter, and a
    new chassis would only tear down the working identity. Raises SystemExit if a
    `certinstalled` edge still can't converge control (data-plane/TLOC issue).
    """
    if len(edge_configs) <= 1:
        out.info("Skipping shared fabric-membership gate for a single edge target.")
        return []

    poll_interval_seconds = settings.fabric_gate.poll
    timeout_seconds = settings.fabric_gate.timeout
    out.step(
        "Waiting for all targeted edges to join the SD-WAN fabric per vManage "
        f"(poll {poll_interval_seconds}s, timeout {timeout_seconds}s)..."
    )

    start = time.time()
    # Per-edge deadline: each edge gets `timeout` to install its cert, then a
    # fresh `timeout` (reset the moment it installs) for its control plane to
    # converge. A chassis whose cert is already `certinstalled` is NEVER
    # regenerated — regenerating a working identity is what caused edges to churn
    # and never settle.
    all_names = [edge_name_by_id.get(id(c), c.system_ip) for c in edge_configs]
    deadline = {name: start + timeout_seconds for name in all_names}
    cert_installed: set[str] = set()

    with phase("edge_fabric_gate"):
        while True:
            _log_edge_control_conns(edge_configs, edge_name_by_id, start)
            down_edges = _edges_not_in_fabric(edge_configs, edge_name_by_id)
            if not down_edges:
                out.success("All targeted edges have joined the SD-WAN fabric.")
                return []

            now = time.time()
            regen: list[str] = []  # genuine cert failures -> fresh chassis now
            for edge_name in down_edges:
                chassis_id = _get_latest_edge_chassis(edge_name)

                if not chassis_id:
                    out.warning(
                        f"{edge_name} has no chassis ID; never reached activation phase. "
                        "Regenerating with a fresh chassis."
                    )
                    regen.append(edge_name)
                    continue

                cert_state = _get_chassis_cert_state(settings.manager, chassis_id)
                last_state = _LAST_REPORTED_CERT_STATE_BY_EDGE.get(edge_name)
                if cert_state and cert_state != last_state:
                    out.info(
                        f"{edge_name} vManage cert state for latest chassis "
                        f"{chassis_id}: {cert_state!r}"
                    )
                    _LAST_REPORTED_CERT_STATE_BY_EDGE[edge_name] = cert_state

                if cert_state == "certinstalled":
                    # Cert works; never regenerate. Give control its own window.
                    if edge_name not in cert_installed:
                        cert_installed.add(edge_name)
                        deadline[edge_name] = now + timeout_seconds
                elif cert_state in _CERT_STATES_WHERE_EARLY_RETRY_MAY_HELP:
                    regen.append(edge_name)
                elif _consume_token_stalled(edge_name):
                    # The activation hold already established that vManage never
                    # started signing this chassis. Waiting out this gate's timeout
                    # as well would just double the delay.
                    out.warning(
                        f"{edge_name} stalled at 'tokengenerated' during activation; "
                        "regenerating with a fresh chassis."
                    )
                    regen.append(edge_name)

            # Fast-bail: chassis known to be dead (cert install failed, or vManage
            # never started signing) get a fresh chassis now.
            if regen:
                increment_run_stat("edge_cert_early_retries", len(regen))
                out.warning(
                    "Regenerating a fresh chassis for: "
                    + ", ".join(sorted(regen))
                )
                _dump_gate_failure_diagnostics(
                    edge_configs, edge_name_by_id, sorted(regen)
                )
                return sorted(regen)

            expired = [name for name in down_edges if now >= deadline[name]]
            if expired:
                installed_stuck = sorted(n for n in expired if n in cert_installed)
                never_installed = sorted(n for n in expired if n not in cert_installed)
                if installed_stuck:
                    # Cert is good but control never converged -> data-plane/TLOC,
                    # not a certificate problem. Do NOT regenerate a working
                    # identity (mirrors the BFD-convergence handling below).
                    out.error(
                        "Cert is installed but the control plane did not converge "
                        "for: "
                        + ", ".join(installed_stuck)
                        + ". This is a data-plane/TLOC issue, not a certificate "
                        "issue; not regenerating."
                    )
                    raise SystemExit(1)
                # CSR never completed for these -> a fresh chassis is warranted.
                out.warning(
                    "Cert did not install before timeout for: "
                    + ", ".join(never_installed)
                    + "; regenerating with a fresh chassis."
                )
                return never_installed

            out.spinner_wait(
                "Next fabric-membership check for: " + ", ".join(sorted(down_edges)),
                poll_interval_seconds,
            )


def _wait_for_edges_bfd_converged(
    edge_configs: list[settings.EdgeConfig],
    edge_name_by_id: dict[int, str],
) -> list[str]:
    if len(edge_configs) <= 1:
        out.info("Skipping BFD convergence gate for a single edge target.")
        return []

    poll_interval_seconds = settings.bfd_gate.poll
    timeout_seconds = settings.bfd_gate.timeout
    out.step(
        "Waiting for all targeted edges to report BFD sessions in vManage "
        f"(poll {poll_interval_seconds}s, timeout {timeout_seconds}s)..."
    )

    start = time.time()
    with phase("edge_bfd_gate"):
        while True:
            down_edges = _edges_without_bfd(edge_configs, edge_name_by_id)
            if not down_edges:
                out.success("All targeted edges have BFD sessions up.")
                return []

            if time.time() - start >= timeout_seconds:
                increment_run_stat("edge_bfd_convergence_failures", len(down_edges))
                out.warning(
                    "BFD did not converge before timeout for: "
                    + ", ".join(sorted(down_edges))
                )
                return down_edges

            out.spinner_wait(
                "Next BFD convergence check for: " + ", ".join(sorted(down_edges)),
                poll_interval_seconds,
            )


def run_edges_automation(
    edge_configs: list[settings.EdgeConfig],
    initial_config: bool = False,
    config_file: str | None = None,
    cert: bool = False,
    extra_routing: bool = False,
    stagger_seconds: float = 2.0,
) -> None:
    out.header("Automation: EDGES")

    if not edge_configs:
        out.warning("No edge configs provided; nothing to do.")
        return

    edge_name_by_id = {id(cfg): name for name, cfg in settings.EDGES.items()}
    edge_config_by_name = {
        edge_name_by_id.get(id(cfg), "edge"): cfg for cfg in edge_configs
    }

    use_bfd_convergence_gate = cert and len(edge_configs) > 1
    max_attempts = settings.edge_retry_budget if cert else 1
    phase_edge_configs = edge_configs
    phase_initial_config = initial_config
    phase_config_file = config_file
    phase_extra_routing = extra_routing
    edge_attempts = {edge_name_by_id.get(id(cfg), "edge"): 0 for cfg in edge_configs}
    round_number = 0

    while phase_edge_configs:
        round_number += 1
        phase_names = [
            edge_name_by_id.get(id(cfg), "edge") for cfg in phase_edge_configs
        ]
        for name in phase_names:
            edge_attempts[name] = edge_attempts.get(name, 0) + 1

        if cert and round_number > 1:
            increment_run_stat("edge_retry_rounds")
            retry_names_display = ", ".join(sorted(phase_names))
            attempt_display = ", ".join(
                f"{name} {edge_attempts[name]}/{max_attempts}"
                for name in sorted(phase_names)
            )
            out.header(
                "Retrying edge cert flow for fabric convergence",
                f"Targets: {retry_names_display} (attempts: {attempt_display})",
            )

        failed = _run_edges_worker_phase(
            phase_edge_configs,
            edge_name_by_id,
            initial_config=phase_initial_config,
            config_file=phase_config_file,
            cert=cert,
            extra_routing=phase_extra_routing,
            stagger_seconds=stagger_seconds,
            defer_cert_result=use_bfd_convergence_gate,
        )

        if not cert:
            if failed:
                out.error(f"Edge automation failed for: {', '.join(sorted(failed))}")
                raise SystemExit(1)
            return

        if failed:
            out.warning(
                "Edge worker phase failed for: "
                + ", ".join(sorted(failed))
                + "; checking final fabric state before deciding retry targets."
            )

        if use_bfd_convergence_gate:
            # First prove every edge has both control connections. The gate only
            # returns edges that need a fresh chassis (cert failed / never
            # installed); it never returns already-authenticated (certinstalled)
            # edges — those are waited out or flagged as data-plane issues, not
            # regenerated.
            retry_names = sorted(
                _wait_for_edges_in_fabric(edge_configs, edge_name_by_id)
            )
            if not retry_names:
                bfd_down = _wait_for_edges_bfd_converged(
                    edge_configs,
                    edge_name_by_id,
                )
                if bfd_down:
                    out.error(
                        "All targeted edges joined the fabric, but BFD did not "
                        "converge for: "
                        + ", ".join(sorted(bfd_down))
                        + ". This is likely a data-plane/TLOC issue, not a "
                        "certificate install issue."
                    )
                    raise SystemExit(1)
                return
        else:
            bfd_down = _wait_for_edges_bfd_converged(edge_configs, edge_name_by_id)
            retry_names = sorted(set(failed) | set(bfd_down))
        if not retry_names:
            return

        exhausted_retry_names = [
            name for name in retry_names if edge_attempts.get(name, 0) >= max_attempts
        ]
        if exhausted_retry_names:
            out.error(
                "Edge fabric convergence failed after per-edge retry budget "
                "was exhausted for: " + ", ".join(sorted(exhausted_retry_names))
            )
            raise SystemExit(1)

        phase_edge_configs = [
            edge_config_by_name[name]
            for name in retry_names
            if name in edge_config_by_name
        ]
        if not phase_edge_configs:
            out.error("Unable to map retry target names back to edge configs.")
            raise SystemExit(1)

        # Retry only the certificate/license flow. Initial config, config-file,
        # and extra routing are not repeated because they are not what fixes a
        # stale or failed vManage certificate delivery. A fresh PAYG activation
        # generates a new chassis ID for the retry.
        phase_initial_config = False
        phase_config_file = None
        phase_extra_routing = False
