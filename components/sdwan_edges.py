"""
Edge (vEdge/C8000V) automation workflow:
- Create PAYG licenses via Manager API.
- Configure Edge using configure-transaction.
- Copy root cert via SCP, install it, and activate using PAYG token.
"""

import re
import time
from typing import Optional

import sdwan_config as settings
from utils.netmiko import (
    bootstrap_initial_config,
    connect_to_device,
    ensure_connection,
    push_config_from_file,
    scp_copy_file,
)
from utils.output import Output
from utils.sdwan_sdk import SdkCallError, sdk_call_json

out = Output(__name__)


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
    wait_seconds: int = settings.WAIT_AFTER_GENERATING_PAYG_LICENSE,
) -> list[dict]:
    out.header(f"EDGE - Generate PAYG Licenses")
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


def _install_root_cert(net_connect) -> None:
    out.step("Installing root certificate on edge...")
    output = net_connect.send_command_timing(
        f"request platform software sdwan root-cert-chain install "
        f"bootflash:sdwan/{settings.ROOT_CERT}",
        strip_prompt=False,
        strip_command=False,
    )
    out.log_only(output)
    if "Password:" in output:
        out.warning("Unexpected password prompt during root cert install.")
    out.info("Root certificate installation in progress...")


def _get_edge_cert_status(net_connect) -> str | None:
    output = net_connect.send_command_timing(
        "show sdwan control local-properties | i root-ca-chain-status",
        strip_prompt=False,
        strip_command=False,
    )
    out.log_only(output)
    match = re.search(r"root-ca-chain-status\s+(\S+)", output, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip().lower()


def _wait_for_edge_cert(
    net_connect,
    poll_interval_seconds: int = settings.EDGE_CERT_POLL_INTERVAL_SECONDS,
    timeout_seconds: int = settings.EDGE_CERT_POLL_TIMEOUT_SECONDS,
) -> bool:
    out.step(
        "Waiting for root CA chain to be installed "
        f"(poll {poll_interval_seconds}s, timeout {timeout_seconds}s)..."
    )
    start = time.time()
    while True:
        status = _get_edge_cert_status(net_connect)
        if status == "installed":
            out.success("Root CA chain status is Installed.")
            return True
        if time.time() - start >= timeout_seconds:
            out.warning("Root CA chain did not reach Installed before timeout.")
            return False
        out.spinner_wait(
            "Next root CA chain check",
            poll_interval_seconds,
        )


def _activate_edge_license(
    net_connect,
    license_entry: dict,
    retry_wait_seconds: int = 30,
    max_attempts: int = 2,
) -> bool:
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
                out.spinner_wait(
                    "Waiting to retry PAYG activation",
                    retry_wait_seconds,
                )
                out.step("Re-installing root certificate before retrying activation...")
                _install_root_cert(net_connect)
                out.spinner_wait(
                    f"Waiting {settings.WAIT_BEFORE_ACTIVATING_EDGE}s before retrying activation...",
                    settings.WAIT_BEFORE_ACTIVATING_EDGE,
                )
                continue
            out.error("PAYG activation failed after retries.")
            return False
        out.success("PAYG license activated")
        return True
    return False


def run_edge_automation(
    config: settings.EdgeConfig,
    initial_config: bool = False,
    config_file: Optional[str] = None,
    cert: bool = False,
    device_type: str = "cisco_ios",
    edge_name: Optional[str] = None,
) -> None:
    out = Output(__name__)
    label = edge_name or "edge"
    out.log_only(
        f"Edge run start initial_config={initial_config} cert={cert} "
        f"config_file={config_file} label={label}",
    )
    out.header(f"Automation: EDGE - {label}", f"Target: {config.ip}")

    net_connect = None

    if initial_config:
        out.header(f"EDGE - {label}: Initial Configuration")
        net_connect = bootstrap_initial_config(
            device_label=label,
            device_type=device_type,
            host=config.ip,
            username=config.username,
            default_password=config.default_password,
            updated_password=config.password,
            initial_config=config.initial_config,
            config_mode_command="config-transaction",
            commit_command="commit",
            read_timeout=settings.NETMIKO_INCREASED_READ_TIMEOUT,
        )
    else:
        net_connect = connect_to_device(
            device_type,
            config.ip,
            config.username,
            config.password,
        )

    if config_file:
        out.header(f"EDGE - {label}: Config File")
        net_connect = ensure_connection(
            net_connect,
            device_type,
            config.ip,
            config.username,
            config.password,
        )
        push_config_from_file(
            net_connect,
            config_file,
            config_mode_command="config-transaction",
            commit_command="commit",
            read_timeout=settings.NETMIKO_INCREASED_READ_TIMEOUT,
        )

    if cert:
        out.header(f"EDGE: {label} - Certificate and License")
        net_connect = ensure_connection(
            net_connect,
            device_type,
            config.ip,
            config.username,
            config.password,
        )
        licenses = generate_payg_licenses(settings.manager, 1)
        if not licenses:
            out.error("Failed to generate PAYG license; aborting edge automation.")
            net_connect.disconnect()
            raise SystemExit(1)
        license_entry = licenses[0]
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
            out.step("Re-installing root certificate after timeout...")
            _install_root_cert(net_connect)
            if not _wait_for_edge_cert(net_connect):
                out.error("Device certificate still not installed; aborting activation.")
                net_connect.disconnect()
                raise SystemExit(1)
        if not _activate_edge_license(net_connect, license_entry):
            net_connect.disconnect()
            raise SystemExit(1)

    net_connect.disconnect()
    out.success("Disconnected from Edge")


def run_edges_automation(
    edge_configs: list[settings.EdgeConfig],
    initial_config: bool = False,
    config_file: Optional[str] = None,
    cert: bool = False,
) -> None:
    out = Output(__name__)
    out.header("Automation: EDGES")

    if not edge_configs:
        out.warning("No edge configs provided; nothing to do.")
        return

    edge_name_by_id = {
        id(cfg): name
        for name, cfg in vars(settings).items()
        if isinstance(cfg, settings.EdgeConfig)
    }
    for edge_config in edge_configs:
        edge_name = edge_name_by_id.get(id(edge_config), "edge")
        run_edge_automation(
            edge_config,
            initial_config=initial_config,
            config_file=config_file,
            cert=cert,
            edge_name=edge_name,
        )
