from utils.logging import get_logger

logger = get_logger(__name__)


def run_vshell_cmd(net_connect, command):
    """
    Execute a command in vshell

    1. Enter vshell mode
    2. Execute the command
    3. Exit vshell
    """
    try:
        net_connect.send_command("vshell", expect_string=r"\$")
        output = net_connect.send_command(command, expect_string=r"\$")
        net_connect.send_command("exit", expect_string=r"#")
        return output
    except Exception as e:
        print(f"Error executing vshell command: {e}")
        raise


def read_file_vshell(net_connect, filename):
    """Read file content via vshell."""
    content = run_vshell_cmd(net_connect, f"cat {filename}")
    logger.debug(
        "\n--- Read file %s ---\n%s\n--- End file ---",
        filename,
        content,
    )
    logger.info(f"Read file {filename} via vshell")
    return content


def write_file_vshell(net_connect, filename, content):
    """
    Write file content via vshell using timing-based sends to avoid prompt issues.
    """
    try:
        net_connect.send_command("vshell", expect_string=r"\$")
        logger.debug(
            "\n--- Write file %s ---\n%s\n--- End file ---",
            filename,
            content,
        )
        logger.info(f"Writing file {filename} via vshell")
        net_connect.send_command_timing(f"cat > {filename} << 'EOF'")
        net_connect.send_command_timing(content)
        net_connect.send_command_timing("EOF")
        net_connect.send_command("exit", expect_string=r"#")
    except Exception as e:
        print(f"Error writing file in vshell: {e}")
        raise
