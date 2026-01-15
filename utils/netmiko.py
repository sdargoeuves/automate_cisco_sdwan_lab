import sys
from pathlib import Path

from netmiko import ConnectHandler

from utils.logging import get_logger

logger = get_logger(__name__)


def connect_to_device(device_type, host, username, password, exit_on_failure=True):
    """
    Connect to a device using Netmiko.

    Args:
        device_type: Netmiko device type string
        host: IP or hostname
        username: Username for authentication
        password: Password for authentication
        exit_on_failure: If True, exit on connection failure. If False, return None
    """
    device = {
        "device_type": device_type,
        "host": host,
        "username": username,
        "password": password,
        "session_log": "netmiko_session.log",
    }

    try:
        net_connect = ConnectHandler(**device)
        # print(f"✓ Connected to {host} as {username}")
        logger.info(f"Connected to {host} as {username}")
        return net_connect
    except Exception as e:
        if exit_on_failure:
            print(f"✗ Failed to connect to {host}: {e}")
            logger.error(f"Failed to connect to {host}: {e}")
            sys.exit(1)
        return None


def push_cli_config(net_connect, config_commands):
    """
    Push CLI configuration using Netmiko

    Args:
        net_connect: Netmiko connection object
        config_commands: List of config commands or multi-line string

    Returns:
        str: Command output
    """
    print("Pushing CLI configuration...")
    if isinstance(config_commands, str):
        logger.info(
            f"\n--- Config to push ---\n{config_commands.strip()}\n--- End config ---",
        )

    if isinstance(config_commands, str):
        config_commands = [
            line.strip() for line in config_commands.strip().split("\n") if line.strip()
        ]

    output = net_connect.send_config_set(config_commands)

    print("Committing configuration...")
    commit_output = net_connect.commit()

    print("✓ Configuration pushed and committed")
    logger.info("Configuration pushed and committed")
    return output + "\n" + commit_output


def push_initial_config(net_connect, initial_config):
    """Push initial device configuration."""
    print("\n" + "=" * 50)
    print("Pushing Initial Configuration")
    print("=" * 50)

    push_cli_config(net_connect, initial_config)
    print("✓ Initial configuration complete")


def push_config_from_file(net_connect, filepath):
    """
    Read configuration from file and push to device

    Args:
        net_connect: Active Netmiko connection
        filepath: Path to configuration file
    """
    config_file = Path(filepath)

    if not config_file.exists():
        print(f"✗ Configuration file not found: {filepath}")
        logger.error(f"Configuration file not found: {filepath}")
        sys.exit(1)

    print(f"\n{'=' * 50}")
    print(f"Pushing configuration from: {config_file.name}")
    print("=" * 50)

    config_content = config_file.read_text()

    if not config_content.strip():
        print("✗ Configuration file is empty")
        logger.error(f"Configuration file is empty: {filepath}")
        sys.exit(1)

    try:
        push_cli_config(net_connect, config_content)
        print(f"✓ Successfully applied configuration from {config_file.name}")
    except Exception as e:
        print(f"✗ Failed to push configuration: {e}")
        logger.error(f"Failed to push configuration from {filepath}: {e}")
        sys.exit(1)
