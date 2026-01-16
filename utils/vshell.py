from utils.output import Output

out = Output(__name__)


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
        out.error(f"Error executing vshell command: {e}")
        raise


def read_file_vshell(net_connect, filename):
    """Read file content via vshell."""
    content = run_vshell_cmd(net_connect, f"cat {filename}")
    out.log_only(
        f"\n--- Read file {filename} ---\n{content}\n--- End file ---",
        level="debug",
    )
    return content


def write_file_vshell(net_connect, filename, content):
    """
    Write file content via vshell using timing-based sends to avoid prompt issues.
    """
    try:
        net_connect.send_command("vshell", expect_string=r"\$")
        out.log_only(
            f"\n--- Write file {filename} ---\n{content}\n--- End file ---",
            level="debug",
        )
        net_connect.send_command_timing(f"cat > {filename} << 'EOF'")
        net_connect.send_command_timing(content)
        net_connect.send_command_timing("EOF")
        net_connect.send_command("exit", expect_string=r"#")
    except Exception as e:
        out.error(f"Error writing file in vshell: {e}")
        raise
