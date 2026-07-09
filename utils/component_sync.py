import time

from utils import sdwan_config as settings
from utils.manager_api_status import (
    get_out_of_sync_controllers,
    show_controller_status,
)
from utils.netmiko import reboot_device
from utils.output import Output

out = Output(__name__)


def _format_component_label(item: dict) -> str:
    device_type = item.get("deviceType") or "unknown"
    host = item.get("host-name") or item.get("system-ip") or "unknown"
    return f"{device_type} ({host})"


def _wait_for_controllers_in_sync(
    manager_config,
    poll_interval: int,
    timeout: int,
) -> bool:
    """Poll until all controllers are in sync, or timeout elapses.

    Returns True if everything came back in sync within the timeout, False otherwise.
    """
    out.step(
        f"Waiting for rebooted controllers to come back in sync "
        f"(poll {poll_interval}s, timeout {timeout}s)..."
    )
    start = time.time()
    while True:
        time.sleep(poll_interval)
        still_out_of_sync = get_out_of_sync_controllers(manager_config, out=out)
        if not still_out_of_sync:
            out.success("Rebooted controllers are back in sync.")
            return True
        elapsed = int(time.time() - start)
        if elapsed >= timeout:
            out.error(
                f"Controllers still out of sync after {timeout}s: "
                + ", ".join(_format_component_label(item) for item in still_out_of_sync)
            )
            return False
        out.info(
            f"Still out of sync after {elapsed}s; continuing to wait — "
            + ", ".join(_format_component_label(item) for item in still_out_of_sync)
        )


def reboot_out_of_sync_components(
    manager_config,
    initial_wait: int = 30,
    retry_wait: int = 120,
) -> None:
    out.spinner_wait("Waiting to ensure all components are synced...", initial_wait)
    show_controller_status(manager_config, out=out)

    out_of_sync = get_out_of_sync_controllers(manager_config, out=out)
    if not out_of_sync:
        out.success("All components are in sync.")
        return

    out.warning(
        "Detected out-of-sync components: "
        + ", ".join(_format_component_label(item) for item in out_of_sync)
    )
    out.spinner_wait(
        f"Rechecking controller sync status in {retry_wait}s...",
        retry_wait,
    )
    show_controller_status(manager_config, out=out)

    still_out_of_sync = get_out_of_sync_controllers(manager_config, out=out)
    if not still_out_of_sync:
        out.success("Components recovered and are now in sync.")
        return

    out.warning(
        "Components remain out of sync; we will attempt a reboot of: "
        + ", ".join(_format_component_label(item) for item in still_out_of_sync)
    )
    rebooted_any = False
    for item in still_out_of_sync:
        system_ip = item.get("system-ip")
        if not system_ip:
            out.warning(
                f"Skipping reboot for {_format_component_label(item)}: missing system-ip."
            )
            continue
        reboot_device(
            system_ip,
            settings.USERNAME,
            settings.UPDATED_PASSWORD,
        )
        rebooted_any = True

    if rebooted_any:
        _wait_for_controllers_in_sync(
            manager_config,
            poll_interval=settings.controller_reboot.poll,
            timeout=settings.controller_reboot.timeout,
        )
