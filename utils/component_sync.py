import time

import sdwan_config as settings
from utils.manager_api_status import (
    get_out_of_sync_controllers,
    show_controller_status,
)
from utils.netmiko import reboot_device
from utils.output import Output


def _format_component_label(item: dict) -> str:
    device_type = item.get("deviceType") or "unknown"
    host = item.get("host-name") or item.get("system-ip") or "unknown"
    return f"{device_type} ({host})"


def reboot_out_of_sync_components(
    manager_config,
    out: Output,
    initial_wait: int = 30,
    retry_wait: int = 120,
) -> None:
    out.wait("Waiting to ensure all components are synced...")
    time.sleep(initial_wait)
    show_controller_status(manager_config, out=out)

    out_of_sync = get_out_of_sync_controllers(manager_config, out=out)
    if not out_of_sync:
        out.success("All components are in sync.")
        return

    out.warning(
        "Detected out-of-sync components: "
        + ", ".join(_format_component_label(item) for item in out_of_sync)
    )
    out.wait(f"Rechecking controller sync status in {retry_wait}s...")
    time.sleep(retry_wait)
    show_controller_status(manager_config, out=out)

    still_out_of_sync = get_out_of_sync_controllers(manager_config, out=out)
    if not still_out_of_sync:
        out.success("Components recovered and are now in sync.")
        return

    out.warning("Components remain out of sync; sending reboot commands (skipped for now whils investigating...)")
    # for item in still_out_of_sync:
    #     system_ip = item.get("system-ip")
    #     if not system_ip:
    #         out.warning(
    #             f"Skipping reboot for {_format_component_label(item)}: missing system-ip."
    #         )
    #         continue
    #     reboot_device(
    #         system_ip,
    #         settings.USERNAME,
    #         settings.PASSWORD,
    #         out_override=out,
    #     )
