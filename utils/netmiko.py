import sys
import time
from pathlib import Path

from netmiko import ConnectHandler

from utils import sdwan_config as settings
from utils.output import Output

out = Output(__name__)


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
    }

    try:
        net_connect = ConnectHandler(**device)
        out.log_only(f"Connected to {host} as {username}")
        return net_connect
    except Exception as e:
        if exit_on_failure:
            out.error(f"Failed to connect to {host}: {e}")
            sys.exit(1)
        return None


def push_cli_config(
    net_connect,
    config_commands,
    config_mode_command=None,
    commit_command: str | None = None,
    read_timeout: float | None = None,
):
    """
    Push CLI configuration using Netmiko

    Args:
        net_connect: Netmiko connection object
        config_commands: List of config commands or multi-line string
        config_mode_command: Optional config mode entry command
        commit_command: Optional commit command to run after config is sent
        read_timeout: Optional Netmiko read timeout for config mode entry

    Returns:
        str: Command output
    """
    out.step("Pushing CLI configuration...")
    if isinstance(config_commands, str):
        out.log_only(
            f"\n--- Config to push ---\n{config_commands.strip()}\n--- End config ---",
            level="debug",
        )
        config_commands = [
            line.strip() for line in config_commands.strip().split("\n") if line.strip()
        ]

    output = net_connect.send_config_set(
        config_commands,
        config_mode_command=config_mode_command,
        read_timeout=read_timeout,
        exit_config_mode=False if commit_command else True,
    )

    out.step("Committing configuration...")
    if commit_command:
        commit_output = net_connect.send_command_timing(
            commit_command, strip_prompt=False, strip_command=False
        )
        output += "\n" + commit_output
        output += "\n" + net_connect.send_command_timing(
            "end", strip_prompt=False, strip_command=False
        )
    else:
        try:
            commit_output = net_connect.commit()
            output += "\n" + commit_output
        except AttributeError:
            out.warning("Device does not support commit(); skipping.")

    out.success("Configuration pushed and committed")
    return output


def push_initial_config(
    net_connect,
    initial_config,
    config_mode_command=None,
    commit_command: str | None = None,
    read_timeout: float | None = None,
):
    """Push initial device configuration."""
    out.header("Pushing Initial Configuration")

    push_cli_config(
        net_connect,
        initial_config,
        config_mode_command=config_mode_command,
        commit_command=commit_command,
        read_timeout=read_timeout,
    )
    out.success("Initial configuration complete")


def push_config_from_file(
    net_connect,
    filepath,
    config_mode_command=None,
    commit_command: str | None = None,
    read_timeout: float | None = None,
):
    """
    Read configuration from file and push to device

    Args:
        net_connect: Active Netmiko connection
        filepath: Path to configuration file
    """
    config_file = Path(filepath)

    if not config_file.exists():
        out.error(f"Configuration file not found: {filepath}")
        sys.exit(1)

    out.header(f"Pushing configuration from: {config_file.name}")

    config_content = config_file.read_text()

    if not config_content.strip():
        out.error(f"Configuration file is empty: {filepath}")
        sys.exit(1)

    try:
        push_cli_config(
            net_connect,
            config_content,
            config_mode_command=config_mode_command,
            commit_command=commit_command,
            read_timeout=read_timeout,
        )
        out.success(f"Successfully applied configuration from {config_file.name}")
    except Exception as e:
        out.error(f"Failed to push configuration: {e}")
        sys.exit(1)


def ensure_connection(net_connect, device_type, host, username, password):
    if net_connect:
        return net_connect
    return connect_to_device(device_type, host, username, password)


def bootstrap_initial_config(
    device_label: str,
    device_type: str,
    host: str,
    username: str,
    default_password: str,
    updated_password: str,
    initial_config: str,
    config_mode_command: str | None = None,
    commit_command: str | None = None,
    read_timeout: float | None = None,
):
    out.step("Attempting to connect with default credentials...")
    net_connect = connect_to_device(
        device_type,
        host,
        username,
        default_password,
        exit_on_failure=False,
    )

    if net_connect:
        if not initial_config.strip():
            out.warning(f"{device_label} initial config is empty; skipping.")
        else:
            push_initial_config(
                net_connect,
                initial_config,
                config_mode_command=config_mode_command,
                commit_command=commit_command,
                read_timeout=read_timeout,
            )

        net_connect.disconnect()
        net_connect = connect_to_device(device_type, host, username, updated_password)
        return net_connect

    out.warning("Default credentials failed, trying configured password...")
    net_connect = connect_to_device(device_type, host, username, updated_password)
    if not net_connect:
        out.error("Failed to connect with both default and updated passwords.")
        return None
    if not initial_config.strip():
        out.warning(f"{device_label} initial config is empty; skipping.")
        return net_connect
    out.step("Re-applying initial configuration...")
    push_initial_config(
        net_connect,
        initial_config,
        config_mode_command=config_mode_command,
        commit_command=commit_command,
        read_timeout=read_timeout,
    )
    return net_connect


def wait_for_prompt(net_connect, timeout: int = 30) -> str:
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


def scp_copy_file(
    net_connect,
    host: str,
    username: str,
    password: str,
    remote_file: str,
    destination: str,
    description: str | None = None,
) -> bool:
    if description:
        out.step(description)
    else:
        out.step("Copying file via SCP...")
    outputs = []
    outputs.append(
        net_connect.send_command_timing(
            f"copy scp: {destination}", strip_prompt=False, strip_command=False
        )
    )
    outputs.append(
        net_connect.send_command_timing(host, strip_prompt=False, strip_command=False)
    )
    outputs.append(
        net_connect.send_command_timing(
            username, strip_prompt=False, strip_command=False
        )
    )
    outputs.append(
        net_connect.send_command_timing(
            remote_file, strip_prompt=False, strip_command=False
        )
    )
    outputs.append(
        net_connect.send_command_timing("", strip_prompt=False, strip_command=False)
    )
    if "over write" in outputs[-1].lower() or "overwrite" in outputs[-1].lower():
        outputs.append(
            net_connect.send_command_timing("", strip_prompt=False, strip_command=False)
        )
    outputs.append(
        net_connect.send_command_timing(
            password, strip_prompt=False, strip_command=False
        )
    )
    out.log_only("\n".join(outputs), level="debug")
    wait_for_prompt(net_connect)

    output_text = "\n".join(outputs)
    if "Authentication failed" in output_text or "%Error" in output_text:
        out.error("Failed to copy root certificate via SCP.")
        return False
    if "bytes copied" not in output_text and "copied" not in output_text:
        out.warning("SCP copy did not confirm success; check logs if needed.")
    else:
        out.success("SCP copy completed")
    return True


def reboot_device(
    host: str,
    username: str,
    password: str,
    device_type: str = "cisco_viptela",
) -> bool:
    out.step(f"Sending reboot command to {host}...")
    net_connect = connect_to_device(
        device_type,
        host,
        username,
        password,
        exit_on_failure=False,
    )
    if not net_connect:
        out.warning(f"Failed to connect to {host} for reboot.")
        return False

    try:
        output = net_connect.send_command_timing(
            "reboot", strip_prompt=False, strip_command=False
        )
        if "are you sure" in output.lower():
            output += net_connect.send_command_timing(
                "yes", strip_prompt=False, strip_command=False
            )
        out.log_only(output, level="debug")
        out.success(f"Reboot command sent to {host}")
        return True
    except Exception as exc:
        out.warning(f"Failed to reboot {host}: {exc}")
        return False
    finally:
        try:
            net_connect.disconnect()
        except Exception:
            pass
