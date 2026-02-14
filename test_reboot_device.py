import argparse
from types import SimpleNamespace

from utils import component_sync


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Trigger reboot_out_of_sync_components by forcing out-of-sync "
            "results so it calls reboot_device on a real device."
        )
    )
    parser.add_argument("--system-ip", required=True, help="Device system-ip to reboot")
    args = parser.parse_args()

    # Build a fake "out-of-sync" controller record. This matches the
    # fields reboot_out_of_sync_components expects from the real API.
    fake_items = [
        {
            "system-ip": args.system_ip,
            "deviceType": "controller",
            "host-name": args.system_ip,
        }
    ]

    # Monkeypatch the status helpers so reboot_out_of_sync_components
    # always "sees" an out-of-sync controller and proceeds to reboot.
    component_sync.get_out_of_sync_controllers = lambda *_, **__: list(fake_items)
    component_sync.show_controller_status = lambda *_, **__: None

    component_sync.reboot_out_of_sync_components(
        manager_config=SimpleNamespace(),
        initial_wait=0,
        retry_wait=0,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
