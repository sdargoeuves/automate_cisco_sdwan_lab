#!/usr/bin/env python3
"""
generate_sdwan_vars.py

Generates an sdwan_variables YAML file by combining:
  - sdwan_variables-base.yml  (static values you maintain manually)
  - host_vars/<device>/topology.json  (dynamic values produced by netlab)

Usage:
  python generate_sdwan_vars.py
  python generate_sdwan_vars.py --output automate_sdwan/sdwan_variables-test.yml
  python generate_sdwan_vars.py --base sdwan_variables-base.yml --host-vars host_vars

Device identification:
  sdwan-manager    → devices.manager   (clab kind: linux, type: manager)
  sdwan-controller → devices.controller (clab kind: linux, type: controller)
  sdwan-validator  → devices.validator  (clab kind: linux, type: validator)
  edge*            → devices.edges.<name> (clab kind: cisco_c8000v)
  everything else  → skipped
"""

import argparse
import ipaddress
import json
import sys
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
    """Replace ' -> ' with ' to ' in netlab link names."""
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


def process_edge(topo: dict) -> dict:
    """Extract dynamic fields for a C8000v edge device."""
    result = {
        "mgmt_ip": topo["mgmt"]["ipv4"],
        "system_ip": topo["mgmt"]["ipv4"],
        "bgp_local_as": topo["bgp"]["as"],
    }

    # BGP neighbor ASNs (identify by neighbor node name)
    for nbr in topo["bgp"]["neighbors"]:
        if nbr["name"] == "mpls0":
            result["bgp_mpls_as"] = nbr["as"]
        elif nbr["name"] == "inet0":
            result["bgp_inet_as"] = nbr["as"]

    # Classify data-plane interfaces by neighbor node name
    lan_ifaces = []
    for iface in topo["interfaces"]:
        neighbor_nodes = [n["node"] for n in iface.get("neighbors", [])]

        if "mpls0" in neighbor_nodes:
            ip, _, mask = split_cidr(iface["ipv4"])
            gw = strip_prefix(iface["neighbors"][0]["ipv4"])
            result.update({
                "mpls_interface": iface["ifname"],
                "mpls_ip": ip,
                "mpls_mask": mask,
                "mpls_gw": gw,
                "mpls_desc": fix_desc(iface["name"]),
            })

        elif "inet0" in neighbor_nodes:
            ip, _, mask = split_cidr(iface["ipv4"])
            gw = strip_prefix(iface["neighbors"][0]["ipv4"])
            result.update({
                "inet_interface": iface["ifname"],
                "inet_ip": ip,
                "inet_mask": mask,
                "inet_gw": gw,
                "inet_desc": fix_desc(iface["name"]),
            })

        else:
            lan_ifaces.append(iface)

    # LAN interfaces — lan, lan2, lan3, ... depending on how many there are
    for i, iface in enumerate(lan_ifaces):
        key = "lan" if i == 0 else f"lan{i + 1}"
        ip, _, mask = split_cidr(iface["ipv4"])
        gw = strip_prefix(iface["neighbors"][0]["ipv4"])
        result.update({
            f"{key}_interface": iface["ifname"],
            f"{key}_ip": ip,
            f"{key}_mask": mask,
            f"{key}_gw": gw,
            f"{key}_desc": fix_desc(iface["name"]),
        })

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

HERE = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(
        description="Generate an sdwan_variables YAML from netlab topology files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-b", "--base",
        default=HERE / "sdwan_variables-base.yml",
        help="Base YAML with static values",
    )
    parser.add_argument(
        "-t", "--host-vars",
        default=HERE / "host_vars",
        help="Path to the host_vars (topology) directory",
    )
    parser.add_argument(
        "-o", "--output",
        default="sdwan_variables-test.yml",
        help="Output YAML file (default: sdwan_variables-test.yml in current directory)",
    )
    args = parser.parse_args()

    base_path = Path(args.base)
    host_vars_path = Path(args.host_vars)
    output_path = Path(args.output)

    # Load base YAML ──────────────────────────────────────────────────────────
    if not base_path.exists():
        print(f"ERROR: base file not found: {base_path}", file=sys.stderr)
        sys.exit(1)

    with base_path.open() as f:
        config = yaml.safe_load(f)

    config.setdefault("devices", {})
    config["devices"].setdefault("edges", {})

    # Process topology files ──────────────────────────────────────────────────
    print(f"Scanning {host_vars_path}/*/topology.json ...")

    for topo_file in sorted(host_vars_path.glob("*/topology.json")):
        device_name = topo_file.parent.name

        with topo_file.open() as f:
            topo = json.load(f)

        clab = topo.get("clab", {})
        kind = clab.get("kind", "")

        try:
            if device_name == "sdwan-manager":
                dynamic = process_linux_device(topo)
                # base values win over dynamic (base has site_id, csr_file, etc.)
                config["devices"]["manager"] = {
                    **dynamic,
                    **config["devices"].get("manager", {}),
                }
                print(f"  [ok] {device_name} → devices.manager")

            elif device_name == "sdwan-controller":
                dynamic = process_linux_device(topo)
                config["devices"]["controller"] = {
                    **dynamic,
                    **config["devices"].get("controller", {}),
                }
                print(f"  [ok] {device_name} → devices.controller")

            elif device_name == "sdwan-validator":
                dynamic = process_validator(topo)
                config["devices"]["validator"] = {
                    **dynamic,
                    **config["devices"].get("validator", {}),
                }
                print(f"  [ok] {device_name} → devices.validator")

            elif kind == "cisco_c8000v":
                dynamic = process_edge(topo)
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
    with output_path.open("w") as f:
        yaml.dump(
            config,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    print(f"\nWritten → {output_path}")


if __name__ == "__main__":
    main()
