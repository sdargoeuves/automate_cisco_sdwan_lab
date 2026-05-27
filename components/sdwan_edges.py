"""
Edge (vEdge/C8000V) automation workflow:
- Create PAYG licenses via Manager API.
- Configure Edge using configure-transaction.
- Copy root cert via SCP, install it, and activate using PAYG token.
"""

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from utils import sdwan_config as settings
from utils.netmiko import (
    bootstrap_initial_config,
    connect_to_device,
    ensure_connection,
    push_cli_config,
    push_config_from_file,
    scp_copy_file,
)
from utils.manager_api_status import get_edge_health_items
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


def _record_latest_edge_chassis(edge_name: str, chassis_id: str) -> None:
    with _LATEST_CHASSIS_LOCK:
        _LATEST_CHASSIS_BY_EDGE[edge_name] = chassis_id
        _LAST_REPORTED_CERT_STATE_BY_EDGE.pop(edge_name, None)


def _get_latest_edge_chassis(edge_name: str) -> Optional[str]:
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
        wait_seconds = settings.WAIT_AFTER_GENERATING_PAYG_LICENSE_SECONDS
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
        poll_interval_seconds = settings.EDGE_CERT_POLL_INTERVAL_SECONDS
    if timeout_seconds is None:
        timeout_seconds = settings.EDGE_CERT_POLL_TIMEOUT_SECONDS
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
    commands = [
        "show sdwan control connections",
        "show sdwan control connections-history",
        "show sdwan certificate installed",
        "show sdwan certificate validity",
        (
            "show logging | include "
            "CERT|VDAEMON|SYSTEM_LICENSE|CONTROL_CONN|CSR|ROOT_CERT"
        ),
    ]
    for command in commands:
        try:
            output = net_connect.send_command_timing(
                command,
                strip_prompt=False,
                strip_command=False,
            )
        except Exception as exc:  # pragma: no cover - defensive diagnostic path
            out.log_only(
                f"Diagnostic command failed: {command}: {exc}",
                level="warning",
            )
            continue
        out.log_only(f"=== Edge cert diagnostic: {command} ===\n{output}")


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


def _wait_for_edge_in_fabric(
    manager_config,
    system_ip: str,
    chassis_id: str | None = None,
    poll_interval_seconds: int = None,
    timeout_seconds: int = None,
) -> tuple[bool, str | None]:
    if poll_interval_seconds is None:
        poll_interval_seconds = settings.EDGE_CERT_VALIDITY_POLL_INTERVAL_SECONDS
    if timeout_seconds is None:
        timeout_seconds = settings.EDGE_CERT_VALIDITY_TIMEOUT_SECONDS
    out.step(
        "Waiting for edge to join the SD-WAN fabric per vManage "
        f"(poll {poll_interval_seconds}s, timeout {timeout_seconds}s)..."
    )

    start = time.time()
    last_cert_state = None
    while True:
        if _is_edge_in_fabric(manager_config, system_ip):
            out.success("Edge has joined the SD-WAN fabric.")
            return True, None

        if chassis_id:
            cert_state = _get_chassis_cert_state(manager_config, chassis_id)
            if cert_state != last_cert_state:
                out.info(f"vManage chassis cert state: {cert_state!r}")
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


def _get_chassis_cert_state(manager_config, chassis_id: str) -> Optional[str]:
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
        retry_wait_seconds = settings.EDGE_PAYG_ACTIVATE_RETRY_WAIT_SECONDS
    if max_attempts is None:
        max_attempts = settings.EDGE_PAYG_ACTIVATE_MAX_ATTEMPTS
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
                    f"Waiting {settings.WAIT_BEFORE_ACTIVATING_EDGE_SECONDS}s before retrying activation...",
                    settings.WAIT_BEFORE_ACTIVATING_EDGE_SECONDS,
                )
                continue
            out.error("PAYG activation failed after retries.")
            return False
        out.success("PAYG license activated")
        return True
    return False


def _get_edge_extra_routing_config(edge_name: Optional[str]) -> Optional[str]:
    if not edge_name:
        return None
    return settings.EDGE_EXTRA_ROUTING_CONFIGS.get(edge_name)


def run_edge_automation(
    config: settings.EdgeConfig,
    initial_config: bool = False,
    config_file: Optional[str] = None,
    cert: bool = False,
    extra_routing: bool = False,
    device_type: str = "cisco_ios",
    edge_name: Optional[str] = None,
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
    config_file: Optional[str],
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
            read_timeout=settings.NETMIKO_INCREASED_READ_TIMEOUT_SECONDS,
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
            read_timeout=settings.NETMIKO_INCREASED_READ_TIMEOUT_SECONDS,
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
            read_timeout=settings.NETMIKO_INCREASED_READ_TIMEOUT_SECONDS,
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
        licenses = generate_payg_licenses(settings.manager, 1)
        if not licenses:
            out.error("Failed to generate PAYG license; aborting edge automation.")
            net_connect.disconnect()
            raise SystemExit(1)
        license_entry = licenses[0]
        _record_latest_edge_chassis(label, license_entry["chassis"])
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
        # Serialize activation across worker threads so vManage doesn't receive
        # multiple CSRs concurrently — concurrent CSRs from PAYG-generated
        # chassis trigger BYOL/PAYG mismatch races that leave edges in
        # `certinstallfailed`. The gap after the activate command gives vManage
        # time to start processing this CSR before the next edge submits.
        with _ACTIVATION_LOCK:
            if not _activate_edge_license(net_connect, license_entry):
                net_connect.disconnect()
                raise SystemExit(1)
            out.spinner_wait(
                "Holding lock to let vManage pick up this CSR before the next edge "
                f"activates ({settings.EDGE_ACTIVATION_GAP_SECONDS}s)...",
                settings.EDGE_ACTIVATION_GAP_SECONDS,
            )
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
                settings.EDGE_CERT_VALIDITY_MAX_ATTEMPTS,
                device_type,
            ):
                out.error(
                    "Edge did not join the fabric after PAYG activation."
                )
                net_connect.disconnect()
                raise SystemExit(1)

    net_connect.disconnect()
    out.success("Disconnected from Edge")


def _run_edges_worker_phase(
    edge_configs: list[settings.EdgeConfig],
    edge_name_by_id: dict[int, str],
    initial_config: bool,
    config_file: Optional[str],
    cert: bool,
    extra_routing: bool,
    stagger_seconds: float,
    defer_cert_result: bool,
) -> list[str]:
    increment_run_stat("edge_worker_phases")
    failed = []
    with phase("edge_worker_phase"):
        with ThreadPoolExecutor(max_workers=len(edge_configs)) as pool:
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


def _wait_for_edges_in_fabric(
    edge_configs: list[settings.EdgeConfig],
    edge_name_by_id: dict[int, str],
) -> list[str]:
    if len(edge_configs) <= 1:
        out.info("Skipping shared fabric-membership gate for a single edge target.")
        return []

    poll_interval_seconds = settings.EDGE_CERT_VALIDITY_POLL_INTERVAL_SECONDS
    timeout_seconds = settings.EDGE_CERT_VALIDITY_TIMEOUT_SECONDS
    out.step(
        "Waiting for all targeted edges to join the SD-WAN fabric per vManage "
        f"(poll {poll_interval_seconds}s, timeout {timeout_seconds}s)..."
    )

    start = time.time()
    with phase("edge_fabric_gate"):
        while True:
            down_edges = _edges_not_in_fabric(edge_configs, edge_name_by_id)
            if not down_edges:
                out.success("All targeted edges have joined the SD-WAN fabric.")
                return []

            failed_cert_edges = []
            for edge_name in down_edges:
                chassis_id = _get_latest_edge_chassis(edge_name)
                if not chassis_id:
                    continue
                cert_state = _get_chassis_cert_state(settings.manager, chassis_id)
                last_state = _LAST_REPORTED_CERT_STATE_BY_EDGE.get(edge_name)
                if cert_state and cert_state != last_state:
                    out.info(
                        f"{edge_name} vManage cert state for latest chassis "
                        f"{chassis_id}: {cert_state!r}"
                    )
                    _LAST_REPORTED_CERT_STATE_BY_EDGE[edge_name] = cert_state
                if cert_state in _CERT_STATES_WHERE_EARLY_RETRY_MAY_HELP:
                    failed_cert_edges.append(edge_name)

            if failed_cert_edges:
                increment_run_stat("edge_cert_early_retries", len(failed_cert_edges))
                out.warning(
                    "vManage reported cert install failure for: "
                    + ", ".join(sorted(failed_cert_edges))
                    + "; retrying those edges without waiting for the full fabric timeout."
                )
                return sorted(failed_cert_edges)

            if time.time() - start >= timeout_seconds:
                out.warning(
                    "Fabric membership did not converge before timeout for: "
                    + ", ".join(sorted(down_edges))
                )
                return down_edges

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

    poll_interval_seconds = settings.EDGE_BFD_CONVERGENCE_POLL_INTERVAL_SECONDS
    timeout_seconds = settings.EDGE_BFD_CONVERGENCE_TIMEOUT_SECONDS
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
    config_file: Optional[str] = None,
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
    max_attempts = settings.EDGE_BFD_CONVERGENCE_MAX_ATTEMPTS if cert else 1
    phase_edge_configs = edge_configs
    phase_initial_config = initial_config
    phase_config_file = config_file
    phase_extra_routing = extra_routing
    edge_attempts = {
        edge_name_by_id.get(id(cfg), "edge"): 0 for cfg in edge_configs
    }
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
                "Edge worker phase failed for: " + ", ".join(sorted(failed))
                + "; checking final fabric state before deciding retry targets."
            )

        if use_bfd_convergence_gate:
            # First prove every edge has both control connections. If a peer is
            # missing control, BFD on the healthy peers cannot fully converge;
            # retry only the control-down edges instead of regenerating certs
            # for already-authenticated edges.
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
                "was exhausted for: "
                + ", ".join(sorted(exhausted_retry_names))
            )
            raise SystemExit(1)

        phase_edge_configs = [
            edge_config_by_name[name] for name in retry_names if name in edge_config_by_name
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
