from typing import Optional

from sdwan_config import CONFIG, ValidatorConfig
from utils.logging import get_logger
from utils.netmiko import (
    connect_to_device,
    push_config_from_file,
    push_initial_config,
)
from utils.vshell import read_file_vshell, write_file_vshell


def run_validator_automation(
    config: ValidatorConfig,
    initial_config: bool = False,
    cert: bool = False,
    config_file: Optional[str] = None,
):
    """
    Placeholder for vBond/validator automation.
    """
    logger = get_logger(__name__)
    logger.info(
        f"Validator run start initial_config={initial_config} cert={cert} config_file={config_file}",
    )
    print("\n" + "=" * 50)
    print("Validator Automation (vBond)")
    print("=" * 50)
    print(f"Target validator IP: {config.ip}:{config.port}")

    net_connect = None

    if initial_config:
        print("\n" + "=" * 50)
        print("Mode: Initial Configuration")
        print("=" * 50)

        print("Attempting to connect with default credentials...")
        net_connect = connect_to_device(
            "cisco_viptela",
            config.ip,
            config.username,
            config.username,
            exit_on_failure=False,
        )

        if net_connect:
            if not config.initial_config.strip():
                print("⚠ Validator initial config is empty; skipping.")
                logger.error("Validator initial config is empty; skipping")
            else:
                push_initial_config(net_connect, config.initial_config)

            net_connect.disconnect()
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
            )
        else:
            print("⚠ Default credentials failed, trying configured password...")
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
            )
            print("✓ Already configured with updated password - skipping initial config push")

    if config_file:
        if not net_connect:
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
            )
        push_config_from_file(net_connect, config_file)

    if cert:
        print("Reading RSA key and root certificate from Manager...")
        logger.info("Reading RSA key and root certificate from Manager")
        manager_conn = connect_to_device(
            "cisco_viptela",
            CONFIG.manager.ip,
            CONFIG.manager.username,
            CONFIG.manager.password,
        )
        rsa_key_content = read_file_vshell(manager_conn, CONFIG.manager.rsa_key)
        root_cert_content = read_file_vshell(manager_conn, CONFIG.manager.root_cert)
        manager_conn.disconnect()

        if not net_connect:
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
            )
        print("Writing RSA key and root certificate to Validator...")
        logger.info("Writing RSA key and root certificate to Validator")
        write_file_vshell(net_connect, CONFIG.manager.rsa_key, rsa_key_content)
        write_file_vshell(net_connect, CONFIG.manager.root_cert, root_cert_content)
        print("✓ RSA key and root certificate copied to validator")
        logger.info("RSA key and root certificate copied to validator")

    if net_connect:
        net_connect.disconnect()
        print("\n✓ Disconnected from Validator")
