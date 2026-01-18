from utils.output import Output
from utils.sdwan_sdk import SdkCallError, sdk_call_json


def _format_cell(value: object) -> str:
    if value is None:
        return "-"
    text = str(value)
    return text if text else "-"


def _build_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def format_row(row_cells: list[str]) -> str:
        padded = [cell.ljust(widths[idx]) for idx, cell in enumerate(row_cells)]
        return "| " + " | ".join(padded) + " |"

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"

    lines = [separator, format_row(headers), separator]
    for row in rows:
        lines.append(format_row(row))
    lines.append(separator)
    return lines


def get_controller_status_items(
    manager_config, out: Output | None = None
) -> list[dict]:
    out = out or Output(__name__)
    try:
        response = sdk_call_json(
            manager_config,
            "GET",
            "/dataservice/system/device/controllers",
        )
    except SdkCallError as exc:
        out.warning(str(exc))
        return []

    try:
        items = response.get("data", [])
    except AttributeError:
        out.warning("Failed to parse controller status response as JSON.")
        out.detail(str(response))
        return []

    if not items:
        out.info("No controller entries returned.")
        return []

    return items


def _is_out_of_sync(item: dict) -> bool:
    status = str(item.get("configStatusMessage", "")).strip().lower()
    return "out of sync" in status


def get_out_of_sync_controllers(
    manager_config, out: Output | None = None
) -> list[dict]:
    items = get_controller_status_items(manager_config, out=out)
    return [item for item in items if _is_out_of_sync(item)]


def show_controller_status(manager_config, out: Output | None = None) -> None:
    out = out or Output(__name__)
    out.header("Controller GUI: Configuration > Devices > Control Components")

    items = get_controller_status_items(manager_config, out=out)
    if not items:
        return

    device_type_labels = {
        "vsmart": "vSmart",
        "vbond": "vBond",
        "vmanage": "vManage",
        "vedge": "WAN Edge",
    }
    mode_labels = {
        "cli": "CLI",
        "vmanage": "vManage",
    }

    headers = [
        "Controller Type",
        "Site Name",
        "Hostname",
        "Config Locked",
        "Managed By",
        "Device Status",
        "System-ip",
        "Mode",
        "Certificate Status",
    ]
    rows: list[list[str]] = []
    for item in items:
        device_type = device_type_labels.get(
            _format_cell(item.get("deviceType")), _format_cell(item.get("deviceType"))
        )
        mode = mode_labels.get(
            _format_cell(item.get("configOperationMode")),
            _format_cell(item.get("configOperationMode")),
        )
        rows.append(
            [
                _format_cell(device_type),
                _format_cell(item.get("site-name")),
                _format_cell(item.get("host-name")),
                _format_cell(item.get("device-lock")),
                _format_cell(item.get("managed-by")),
                _format_cell(item.get("configStatusMessage")),
                _format_cell(item.get("system-ip")),
                _format_cell(mode),
                _format_cell(item.get("certInstallStatus")),
            ]
        )

    for line in _build_table(headers, rows):
        print(line)
        out.log_only(line)
