"""
utils/generate_sdwan_vars.py

Generates an sdwan_variables YAML file by combining:
  - sdwan_variables-base.yml  (static values you maintain manually)
  - host_vars/<device>/topology.json  (dynamic values produced by netlab)

Invoked via:
  python sdwan_automation.py generate [options]

Device identification:
  sdwan-manager    → devices.manager   (clab kind: linux, type: manager)
  sdwan-controller → devices.controller (clab kind: linux, type: controller)
  sdwan-validator  → devices.validator  (clab kind: linux, type: validator)
  edge*            → devices.edges.<name> (clab kind: cisco_c8000v)
  everything else  → skipped
"""

import ipaddress
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ── IP helpers ────────────────────────────────────────────────────────────────


def split_cidr(cidr: str) -> tuple:
    """Return (ip_str, prefix_len, mask_str) from a CIDR like '10.1.0.2/30'."""
    iface = ipaddress.IPv4Interface(cidr)
    return str(iface.ip), iface.network.prefixlen, str(iface.netmask)


def strip_prefix(cidr: str) -> str:
    """Return just the IP from a CIDR string ('10.1.0.2/30' → '10.1.0.2')."""
    return str(ipaddress.IPv4Interface(cidr).ip)


# ── Name helpers ──────────────────────────────────────────────────────────────


def eth_to_ge(ifname: str) -> str:
    """Translate a Linux eth interface name to the vBond ge notation.

    eth1 → ge0/0
    eth2 → ge0/1
    ...
    """
    if ifname.startswith("eth"):
        try:
            n = int(ifname[3:])
            return f"ge0/{n - 1}"
        except ValueError:
            pass
    return ifname  # fallback: return unchanged


def fix_desc(link_name: str) -> str:
    """
    Replace ' -> ' with ' to ' in netlab link names.
    As there was an issue with the Edge devices with the '->' in the description
    """
    return link_name.replace(" -> ", " to ")


# ── Device processors ─────────────────────────────────────────────────────────


def process_linux_device(topo: dict) -> dict:
    """Extract dynamic fields for manager, controller, or validator."""
    iface = topo["interfaces"][0]
    ip, prefix, _ = split_cidr(iface["ipv4"])
    gw = strip_prefix(iface["gateway"]["ipv4"])

    return {
        "mgmt_ip": topo["mgmt"]["ipv4"],
        "system_ip": topo["mgmt"]["ipv4"],
        "interface_name": iface["ifname"],
        "interface_ip": ip,
        "interface_prefix": prefix,
        "route_gw": gw,
        "interface_desc": fix_desc(iface["name"]),
    }


def process_validator(topo: dict) -> dict:
    """Like process_linux_device but maps the Linux ifname to vBond ge notation."""
    result = process_linux_device(topo)
    result["interface_name"] = eth_to_ge(result["interface_name"])
    return result


def process_edge(topo: dict, mpls_node: str = "mpls", inet_node: str = "inet") -> dict:
    """Extract dynamic fields for a C8000v edge device.

    mpls_node / inet_node are regex patterns matched against neighbor node names.
    Any interface whose neighbor does not match either pattern is treated as LAN.
    """
    result = {
        "mgmt_ip": topo["mgmt"]["ipv4"],
        "system_ip": topo["mgmt"]["ipv4"],
        "bgp_local_as": topo["bgp"]["as"],
    }

    # BGP neighbor ASNs (regex match against neighbor node name)
    for nbr in topo["bgp"]["neighbors"]:
        if re.search(mpls_node, nbr["name"]):
            result["bgp_mpls_as"] = nbr["as"]
        elif re.search(inet_node, nbr["name"]):
            result["bgp_inet_as"] = nbr["as"]

    # Classify data-plane interfaces by neighbor node name (regex match)
    lan_ifaces = []
    for iface in topo["interfaces"]:
        neighbor_nodes = [n["node"] for n in iface.get("neighbors", [])]

        if any(re.search(mpls_node, node) for node in neighbor_nodes):
            ip, _, mask = split_cidr(iface["ipv4"])
            gw = strip_prefix(iface["neighbors"][0]["ipv4"])
            result.update(
                {
                    "mpls_interface": iface["ifname"],
                    "mpls_ip": ip,
                    "mpls_mask": mask,
                    "mpls_gw": gw,
                    "mpls_desc": fix_desc(iface["name"]),
                }
            )

        elif any(re.search(inet_node, node) for node in neighbor_nodes):
            ip, _, mask = split_cidr(iface["ipv4"])
            gw = strip_prefix(iface["neighbors"][0]["ipv4"])
            result.update(
                {
                    "inet_interface": iface["ifname"],
                    "inet_ip": ip,
                    "inet_mask": mask,
                    "inet_gw": gw,
                    "inet_desc": fix_desc(iface["name"]),
                }
            )

        else:
            lan_ifaces.append(iface)

    # LAN interfaces — collected as a list, supports any number of LANs
    lan_interfaces = []
    for iface in lan_ifaces:
        ip, _, mask = split_cidr(iface["ipv4"])
        gw = strip_prefix(iface["neighbors"][0]["ipv4"])
        lan_interfaces.append(
            {
                "lan_interface": iface["ifname"],
                "lan_ip": ip,
                "lan_mask": mask,
                "lan_gw": gw,
                "lan_desc": fix_desc(iface["name"]),
            }
        )
    result["lan_interfaces"] = lan_interfaces

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

# Parent of utils/ = automate_sdwan/ — where base YAML and host_vars live by default
HERE = Path(__file__).parent.parent


def run(base_path: Path, host_vars_path: Path, output_path: Path) -> None:
    """Generate sdwan_variables YAML by merging base YAML with topology files."""

    # Load base YAML ──────────────────────────────────────────────────────────
    if not base_path.exists():
        print(f"ERROR: base file not found: {base_path}", file=sys.stderr)
        sys.exit(1)

    with base_path.open() as f:
        config = yaml.safe_load(f)

    config.setdefault("devices", {})
    config["devices"].setdefault("edges", {})

    # Read generator config — stripped before writing output
    gen_cfg = config.pop("generate", {})
    mpls_node = gen_cfg.get("mpls_node", "mpls")
    inet_node = gen_cfg.get("inet_node", "inet")

    # Read shared component values — consumed here, not written to output
    component_site_id = config["devices"].pop("component_site_id", None)
    vpn_id = config["devices"].pop("vpn_id", None)
    _api_ready_secs = config.get("timing", {}).pop(
        "manager_api_ready_timeout_seconds", None
    )
    api_ready_minutes = (
        int(_api_ready_secs) // 60 if _api_ready_secs is not None else None
    )

    # Process topology files ──────────────────────────────────────────────────
    print(f"Base     → {base_path}")
    print(f"Scanning {host_vars_path}/*/topology.json ...")
    print(f"  Transport node matching: MPLS='{mpls_node}', inet='{inet_node}' (regex)")

    for topo_file in sorted(host_vars_path.glob("*/topology.json")):
        device_name = topo_file.parent.name

        with topo_file.open() as f:
            topo = json.load(f)

        clab = topo.get("clab", {})
        kind = clab.get("kind", "")

        try:
            if device_name == "sdwan-manager":
                dynamic = process_linux_device(topo)
                if component_site_id is not None:
                    dynamic["site_id"] = component_site_id
                if api_ready_minutes is not None:
                    dynamic["api_ready_timeout_minutes"] = api_ready_minutes
                # base values win over dynamic (base has csr_file, etc.)
                config["devices"]["manager"] = {
                    **dynamic,
                    **config["devices"].get("manager", {}),
                }
                print(f"  [ok] {device_name} → devices.manager")

            elif device_name == "sdwan-controller":
                dynamic = process_linux_device(topo)
                if component_site_id is not None:
                    dynamic["site_id"] = component_site_id
                config["devices"]["controller"] = {
                    **dynamic,
                    **config["devices"].get("controller", {}),
                }
                print(f"  [ok] {device_name} → devices.controller")

            elif device_name == "sdwan-validator":
                dynamic = process_validator(topo)
                if component_site_id is not None:
                    dynamic["site_id"] = component_site_id
                config["devices"]["validator"] = {
                    **dynamic,
                    **config["devices"].get("validator", {}),
                }
                print(f"  [ok] {device_name} → devices.validator")

            elif kind == "cisco_c8000v":
                dynamic = process_edge(topo, mpls_node=mpls_node, inet_node=inet_node)
                if vpn_id is not None:
                    dynamic.setdefault("vrf_id", vpn_id)
                    dynamic.setdefault("ospf_instance", vpn_id)
                base_edge = config["devices"]["edges"].get(device_name, {})
                config["devices"]["edges"][device_name] = {
                    **dynamic,
                    **base_edge,
                }
                print(f"  [ok] {device_name} → devices.edges.{device_name}")

            else:
                # Not an SD-WAN device (hosts, distribution switches, etc.) — skip
                continue

        except (KeyError, IndexError, ValueError) as exc:
            print(f"  [WARN] skipping {device_name}: {exc}", file=sys.stderr)

    # Write output ────────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    banner = (
        "# " + "─" * 77 + "\n"
        "# AUTO-GENERATED FILE — DO NOT EDIT MANUALLY\n"
        "#\n"
        f"# Generated : {generated_at}\n"
        f"# Source    : {base_path}\n"
        "#\n"
        "# This file is rebuilt every time the following command is run:\n"
        "#   python sdwan_automation.py generate\n"
        "#\n"
        "# To make permanent changes, update the base variables file instead:\n"
        f"#   {base_path}\n"
        "# " + "─" * 77 + "\n\n"
    )
    with output_path.open("w") as f:
        f.write(banner)
        yaml.dump(
            config,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    print(f"\nWritten → {output_path}")
