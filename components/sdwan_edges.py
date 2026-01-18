"""
Edge (vEdge/C8000V) automation workflow:
- Create PAYG licenses via Manager API.
- Configure Edge using configure-transaction.
- Copy root cert via SCP, install it, and activate using PAYG token.
"""

import re
import time
from pathlib import Path
from typing import Optional

import sdwan_config as settings
from utils.netmiko import connect_to_device
from utils.output import Output
from utils.sdwan_sdk import SdkCallError, sdk_call_json


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
    out: Output,
    wait_seconds: int = 30,
) -> list[dict]:
    out.header("EDGE: Generate PAYG Licenses")
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
    out.wait(f"Waiting {wait_seconds}s for Manager to process license...")
    time.sleep(wait_seconds)
    return licenses


def _send_edge_config(net_connect, config_text: str, out: Output) -> None:
    if not config_text.strip():
        out.warning("Edge initial config is empty; skipping.")
        return

    lines = [
        line.strip()
        for line in config_text.strip().splitlines()
        if line.strip()
    ]
    config_lines = []
    for line in lines:
        lower = line.lower()
        if lower in ("config-t",):
            continue
        config_lines.append(line)

    out.step("Pushing config using send_config_set (config-transaction)...")
    try:
        output = net_connect.send_config_set(
            config_lines,
            config_mode_command="config-transaction",
            strip_prompt=False,
            strip_command=False,
        )
        out.log_only(output, level="debug")
        out.success("Edge configuration applied")
        return
    except Exception as exc:
        out.warning(
            "send_config_set failed in config-transaction mode; "
            f"falling back to block send. Error: {exc}"
        )

    out.step("Entering configure-transaction mode for block send...")
    entered = False
    output = ""
    for cmd in ("config-transaction", "config-tr"):
        output += net_connect.send_command_timing(
            cmd, strip_prompt=False, strip_command=False
        )
        time.sleep(1)
        try:
            prompt = net_connect.find_prompt()
        except Exception as exc:
            out.detail(f"Prompt check failed after {cmd}: {exc}")
            prompt = ""
        if "(config)#" in prompt:
            entered = True
            break
        output += net_connect.send_command_timing(
            "", strip_prompt=False, strip_command=False
        )
        time.sleep(1)
        try:
            prompt = net_connect.find_prompt()
        except Exception:
            prompt = ""
        if "(config)#" in prompt:
            entered = True
            break

    if not entered:
        out.warning("Failed to enter config-transaction mode; config may not apply.")

    config_block = "\n".join(config_lines) + "\n"
    output += net_connect.send_command_timing(
        config_block, strip_prompt=False, strip_command=False
    )
    output += net_connect.send_command_timing(
        "end", strip_prompt=False, strip_command=False
    )
    out.log_only(output, level="debug")
    out.success("Edge configuration applied")


def _load_config_from_file(filepath: str) -> str:
    config_file = Path(filepath)
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {filepath}")

    content = config_file.read_text()
    if not content.strip():
        raise ValueError(f"Configuration file is empty: {filepath}")
    return content


def _copy_root_cert_from_validator(
    net_connect,
    config: settings.EdgeConfig,
    out: Output,
) -> bool:
    out.step("Copying root certificate from validator via SCP...")
    outputs = []
    outputs.append(
        net_connect.send_command_timing(
            "copy scp: bootflash:/sdwan/", strip_prompt=False, strip_command=False
        )
    )
    outputs.append(
        net_connect.send_command_timing(
            config.validator_ip, strip_prompt=False, strip_command=False
        )
    )
    outputs.append(
        net_connect.send_command_timing(
            settings.validator.username, strip_prompt=False, strip_command=False
        )
    )
    outputs.append(
        net_connect.send_command_timing(
            settings.ROOT_CERT, strip_prompt=False, strip_command=False
        )
    )
    outputs.append(
        net_connect.send_command_timing("", strip_prompt=False, strip_command=False)
    )
    outputs.append(
        net_connect.send_command_timing(
            settings.validator.password, strip_prompt=False, strip_command=False
        )
    )
    out.log_only("\n".join(outputs), level="debug")
    _wait_for_prompt(net_connect, out)

    output_text = "\n".join(outputs)
    if "Authentication failed" in output_text or "%Error" in output_text:
        out.error("Failed to copy root certificate via SCP.")
        return False
    if "bytes copied" not in output_text and "copied" not in output_text:
        out.warning("SCP copy did not confirm success; check logs if needed.")
    else:
        out.success("Root certificate copied to edge")
    return True


def _wait_for_prompt(net_connect, out: Output, timeout: int = 30) -> str:
    deadline = time.monotonic() + timeout
    prompt = ""
    while time.monotonic() < deadline:
        try:
            prompt = net_connect.find_prompt()
            if prompt:
                return prompt
        except Exception as exc:
            out.detail(f"Prompt check failed: {exc}")
        time.sleep(1)
    out.warning("Timed out waiting for device prompt.")
    return prompt

def _install_root_cert(net_connect, out: Output) -> None:
    out.step("Installing root certificate on edge...")
    output = net_connect.send_command_timing(
        f"request platform software sdwan root-cert-chain install "
        f"bootflash:sdwan/{settings.ROOT_CERT}",
        strip_prompt=False,
        strip_command=False,
    )
    out.log_only(output, level="debug")
    if "Password:" in output:
        out.warning("Unexpected password prompt during root cert install.")
    out.success("Root certificate installed")


def _activate_edge_license(
    net_connect,
    license_entry: dict,
    out: Output,
) -> None:
    chassis = license_entry.get("chassis")
    token = license_entry.get("token")
    if not chassis or not token:
        raise ValueError("Missing chassis or token for PAYG activation")

    out.step(f"Activating PAYG license for chassis {chassis}...")
    output = net_connect.send_command_timing(
        "request platform software sdwan vedge_cloud activate "
        f"chassis-number {chassis} token {token}",
        strip_prompt=False,
        strip_command=False,
    )
    out.log_only(output, level="debug")
    out.success("PAYG license activated")


def run_edge_automation(
    config: settings.EdgeConfig,
    initial_config: bool = False,
    config_file: Optional[str] = None,
    cert: bool = False,
    device_type: str = "cisco_ios",
) -> None:
    out = Output(__name__)
    out.log_only(
        f"Edge run start initial_config={initial_config} cert={cert} "
        f"config_file={config_file}",
    )
    out.header("Automation: EDGE", f"Target: {config.ip}")

    net_connect = connect_to_device(
        device_type,
        config.ip,
        config.username,
        config.password,
    )

    if initial_config:
        out.header("EDGE: Initial Configuration")
        _send_edge_config(net_connect, config.initial_config, out)

    if config_file:
        out.header("EDGE: Config File")
        try:
            content = _load_config_from_file(config_file)
        except (FileNotFoundError, ValueError) as exc:
            out.error(str(exc))
            net_connect.disconnect()
            raise SystemExit(1)
        _send_edge_config(net_connect, content, out)

    if cert:
        out.header("EDGE: Certificate and License")
        licenses = generate_payg_licenses(settings.manager, 1, out)
        if not licenses:
            out.error("Failed to generate PAYG license; aborting edge automation.")
            net_connect.disconnect()
            raise SystemExit(1)
        license_entry = licenses[0]
        if not _copy_root_cert_from_validator(net_connect, config, out):
            net_connect.disconnect()
            raise SystemExit(1)
        _install_root_cert(net_connect, out)
        _activate_edge_license(net_connect, license_entry, out)

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

    for edge_config in edge_configs:
        run_edge_automation(
            edge_config,
            initial_config=initial_config,
            config_file=config_file,
            cert=cert,
        )
