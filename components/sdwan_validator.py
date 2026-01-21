import time
from typing import Optional

import sdwan_config as settings
from utils.netmiko import (
    bootstrap_initial_config,
    ensure_connection,
    push_config_from_file,
)
from utils.output import Output
from utils.sdwan_cert import (
    fetch_root_material_from_manager,
    install_signed_cert_on_manager,
    sign_csr,
    write_root_material_to_device,
)
from utils.sdwan_sdk import SdkCallError, sdk_call_json


def run_validator_automation(
    config: settings.ValidatorConfig,
    initial_config: bool = False,
    cert: bool = False,
    config_file: Optional[str] = None,
):
    """
    Orchestrate Validator/vBond actions.
    """
    out = Output(__name__)
    out.log_only(
        f"Validator run start initial_config={initial_config} cert={cert} config_file={config_file}",
    )
    out.header("Automation: VALIDATOR (vBond)", f"Target: {config.mgmt_ip}")

    net_connect = None

    if initial_config:
        out.header("VALIDATOR: Initial Configuration")
        net_connect = bootstrap_initial_config(
            device_label="Validator",
            device_type="cisco_viptela",
            host=config.mgmt_ip,
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
                config.mgmt_ip,
                config.username,
                config.password,
            )
        push_config_from_file(
            net_connect,
            config_file,
            commit_command="commit",
        )

    if cert:
        out.header("VALIDATOR: Certificate Configuration")
        net_connect = ensure_connection(
            net_connect,
            "cisco_viptela",
            config.mgmt_ip,
            config.username,
            config.password,
        )
        run_certificate_automation(net_connect, config)

    if net_connect:
        net_connect.disconnect()
        out.success("Disconnected from Validator")


def run_certificate_automation(net_connect, config: settings.ValidatorConfig) -> bool:
    """
    Run certificate automation for Validator/vBond.
    """
    out = Output(__name__)

    out.subheader("PART 1: Install RSA Key and Root Certificate")
    rsa_key_content, root_cert_content = fetch_root_material_from_manager()
    net_connect = ensure_connection(
        net_connect,
        "cisco_viptela",
        config.mgmt_ip,
        config.username,
        config.password,
    )
    write_root_material_to_device(
        net_connect,
        rsa_key_content,
        root_cert_content,
        device_label="Validator",
    )

    out.subheader("PART 2: Add Validator and Sign CSR")
    out.step("Add Validator in Manager GUI via API")

    # Add validator device to Manager
    out.step("Adding validator device to Manager...")
    try:
        sdk_call_json(
            settings.manager,
            "POST",
            "/dataservice/system/device",
            data={
                "deviceIP": config.validator_ip,
                "username": config.username,
                "password": config.password,
                "generateCSR": True,
                "personality": "vbond",
            },
        )
    except SdkCallError as exc:
        out.error(str(exc))
        return False

    out.success("Validator added to Manager successfully")

    # Wait for CSR to be generated on the validator
    out.spinner_wait(
        f"Waiting Validator to be added and CSR to be generated ({settings.WAIT_CSR_GENERATION} seconds)...",
        settings.WAIT_CSR_GENERATION,
    )

    signed_cert_content = sign_csr(net_connect, config)

    out.subheader("PART 3: Install Certificate")

    return install_signed_cert_on_manager(signed_cert_content)
