import time
from typing import Optional

import sdwan_config as settings
from utils.netmiko import (
    connect_to_device,
    push_config_from_file,
    push_initial_config,
)
from utils.output import Output
from utils.sdwan_sdk import SdkCallError, sdk_call_json, sdk_call_raw
from utils.vshell import read_file_vshell, run_vshell_cmd, write_file_vshell


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
    out.header("Automation: VALIDATOR (vBond)", f"Target: {config.ip}:{config.port}")

    net_connect = None

    if initial_config:
        out.header("VALIDATOR: Initial Configuration")

        out.step("Attempting to connect with default credentials...")
        net_connect = connect_to_device(
            "cisco_viptela",
            config.ip,
            config.username,
            config.username,
            exit_on_failure=False,
        )

        if net_connect:
            if not config.initial_config.strip():
                out.warning("Validator initial config is empty; skipping.")
            else:
                push_initial_config(net_connect, config.initial_config)

            net_connect.disconnect()
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
            )
        else:
            out.warning("Default credentials failed, trying configured password...")
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
            )
            out.info(
                "Already configured with updated password - skipping initial config push"
            )

    if config_file:
        if not net_connect:
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
            )
        push_config_from_file(net_connect, config_file)

    if cert:
        out.header("VALIDATOR: Certificate Configuration")
        if not net_connect:
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
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
    out.step("Reading RSA key and root certificate from Manager...")
    manager_conn = connect_to_device(
        "cisco_viptela",
        settings.manager.ip,
        settings.manager.username,
        settings.manager.password,
    )
    rsa_key_content = read_file_vshell(manager_conn, settings.manager.rsa_key)
    root_cert_content = read_file_vshell(manager_conn, settings.manager.root_cert)
    manager_conn.disconnect()

    if not net_connect:
        net_connect = connect_to_device(
            "cisco_viptela", config.ip, config.username, config.password
        )
    out.step("Writing RSA key and root certificate to Validator...")
    write_file_vshell(net_connect, settings.manager.rsa_key, rsa_key_content)
    write_file_vshell(net_connect, settings.manager.root_cert, root_cert_content)
    out.success("RSA key and root certificate copied to validator")

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
    out.wait("Waiting Validator to be added and CSR to be generated (30 seconds)...")
    time.sleep(30)

    out.step("Signing CSR...")
    run_vshell_cmd(
        net_connect,
        f"openssl x509 -req -in {config.csr_file} -CA {config.root_cert} "
        f"-CAkey {config.rsa_key} -CAcreateserial -out {config.signed_cert} "
        "-days 2000 -sha256",
    )
    signed_cert_content = read_file_vshell(net_connect, config.signed_cert)
    out.success("CSR signed")

    out.subheader("PART 3: Install Certificate")

    out.step("Installing certificate on Manager...")
    try:
        sdk_call_raw(
            settings.manager,
            "POST",
            "/dataservice/certificate/install/signedCert",
            raw_data=signed_cert_content,
        )
    except SdkCallError as exc:
        out.error(str(exc))
        return False

    out.success("Certificate installed!")

    return True
