import time
from typing import Optional

import sdwan_config as settings
from utils.netmiko import (
    bootstrap_initial_config,
    ensure_connection,
    push_config_from_file,
)
from utils.output import Output
from utils.sdwan_sdk import SdkCallError, sdk_call_json
from utils.sdwan_cert import (
    fetch_root_material_from_manager,
    install_signed_cert_on_manager,
    sign_csr,
    write_root_material_to_device,
)


def run_controller_automation(
    config: settings.ControllerConfig,
    initial_config: bool = False,
    cert: bool = False,
    config_file: Optional[str] = None,
):
    """
    Orchestrate Controller/vSmart actions.
    """
    out = Output(__name__)
    out.log_only(
        f"Controller run start initial_config={initial_config} cert={cert} config_file={config_file}",
    )
    out.header("Automation: CONTROLLER (vSmart)", f"Target: {config.ip}")

    net_connect = None

    if initial_config:
        out.header("CONTROLLER: Initial Configuration")
        net_connect = bootstrap_initial_config(
            device_label="Controller",
            device_type="cisco_viptela",
            host=config.ip,
            username=config.username,
            default_password=config.default_password,
            updated_password=config.password,
            initial_config=config.initial_config,
            commit_command="commit",
        )

    if config_file:
        if not net_connect:
            net_connect = ensure_connection(
                net_connect,
                "cisco_viptela",
                config.ip,
                config.username,
                config.password,
            )
        push_config_from_file(
            net_connect,
            config_file,
            commit_command="commit",
        )

    if cert:
        out.header("CONTROLLER: Certificate Configuration")
        net_connect = ensure_connection(
            net_connect,
            "cisco_viptela",
            config.ip,
            config.username,
            config.password,
        )
        run_certificate_automation(net_connect, config)

    if net_connect:
        net_connect.disconnect()
        out.success("Disconnected from Controller")


def run_certificate_automation(net_connect, config: settings.ControllerConfig) -> bool:
    """
    Run certificate automation for Controller/vSmart.
    """
    out = Output(__name__)

    out.subheader("PART 1: Install RSA Key and Root Certificate")
    rsa_key_content, root_cert_content = fetch_root_material_from_manager()
    net_connect = ensure_connection(
        net_connect,
        "cisco_viptela",
        config.ip,
        config.username,
        config.password,
    )
    write_root_material_to_device(
        net_connect,
        rsa_key_content,
        root_cert_content,
        device_label="Controller",
    )

    out.subheader("PART 2: Add Controller and Sign CSR")
    out.step("Add Controller in Manager GUI via API")

    # Add controller device to Manager
    out.step("Adding controller device to Manager...")
    try:
        sdk_call_json(
            settings.manager,
            "POST",
            "/dataservice/system/device",
            data={
                "deviceIP": config.controller_ip,
                "username": config.username,
                "password": config.password,
                "generateCSR": True,
                "personality": "vsmart",
                "port": "",
                "protocol": "DTLS",
            },
        )
    except SdkCallError as exc:
        out.error(str(exc))
        return False

    out.success("Controller added to Manager successfully")

    # Wait for CSR to be generated on the controller
    out.wait(
        f"Waiting Controller to be added and CSR to be generated ({settings.WAIT_CSR_GENERATION} seconds)..."
    )
    time.sleep(settings.WAIT_CSR_GENERATION)

    signed_cert_content = sign_csr(net_connect, config)

    out.subheader("PART 3: Install Certificate")

    return install_signed_cert_on_manager(signed_cert_content)
