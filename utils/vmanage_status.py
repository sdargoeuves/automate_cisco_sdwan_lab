from utils.api import api_call_with_session
from utils.output import Output


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


def show_controller_status(manager_config, out: Output | None = None) -> None:
    out = out or Output(__name__)
    out.header("Controller GUI: Configuration > Devices > Control Components")

    response = api_call_with_session(
        manager_config,
        "GET",
        "/dataservice/system/device/controllers",
    )
    if not response:
        out.warning("vManage API is not ready; skipping status table.")
        return
    if response.status_code != 200:
        out.warning(
            f"Failed to fetch controller status: HTTP {response.status_code}"
        )
        out.detail(response.text)
        return

    try:
        response_json = response.json()
    except ValueError:
        out.warning("Failed to parse controller status response as JSON.")
        out.detail(response.text)
        return

    items = response_json.get("data", [])
    if not items:
        out.info("No controller entries returned.")
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


def show_devices_status_mock(manager_config, out: Output | None = None) -> None:
    out = out or Output(__name__)
    out.header("Device Inventory (Mock)")

    headers = ["Section", "Status", "Notes"]
    rows = [
        [
            "devices",
            "not-implemented",
            "Add endpoint mapping for device inventory status.",
        ]
    ]

    for line in _build_table(headers, rows):
        print(line)
        out.log_only(line)
