# Netlab Topology Generation

This document describes how `sdwan-automation generate` maps netlab `host_vars`
into `variables.yml`.

If you are not using netlab, skip `generate` entirely. Start from
`sdwan_variables.example.yml`, fill in the values manually, and run commands with
`-f /path/to/your-variables.yml`.

## Inputs And Outputs

Input:

```text
host_vars/<device>/topology.json
```

Output:

```text
~/.config/sdwan-automation/variables.yml
```

The generated file combines:

- Static values from `~/.config/sdwan-automation/base.yml`
- Management IPs from netlab
- System IPs from netlab
- Transport and LAN interface data from netlab links
- BGP ASNs from netlab

The generated `variables.yml` is consumed by all automation commands.

## Device Mapping

The generator scans every `host_vars/<device>/topology.json` and maps devices as
follows:

| Directory name | Mapped to | Detection method |
| --- | --- | --- |
| `sdwan-manager` | `devices.manager` | directory name |
| `sdwan-controller` | `devices.controller` | directory name |
| `sdwan-validator` | `devices.validator` | directory name |
| any other dir | `devices.edges.<name>` | `clab.kind == cisco_c8000v` |
| everything else | skipped | - |

## Site IDs

Edge site IDs are auto-assigned as:

```text
edge_site_id_start + n
```

Edges are sorted alphabetically and counted from 1. With the default
`edge_site_id_start: 100`, three edges get:

```text
edge1 -> 101
edge2 -> 102
edge3 -> 103
```

Per-edge overrides in `base.yml` under `devices.edges.<name>.site_id` take
precedence. Any `devices.edges` entries in `base.yml` that do not match a
topology device are pruned from the generated output.

Control-plane devices use `interfaces[0]` for transport IP, prefix, and gateway.
Validator interface names are translated from Linux `ethX` to vBond `ge0/X`
notation.

## Edge Interface Classification

Edge interfaces are classified by matching the neighbor node name against regex
patterns configured under `generate:` in `base.yml`.

The bundled template uses:

| Pattern | Mapped to | Output keys |
| --- | --- | --- |
| `^mpls\d` | MPLS transport | `mpls_interface`, `mpls_ip`, `mpls_mask`, `mpls_gw`, `mpls_desc` |
| `^inet\d` | Internet transport | `inet_interface`, `inet_ip`, `inet_mask`, `inet_gw`, `inet_desc` |
| no match | LAN | entry in `lan_interfaces` list |

BGP ASNs follow the same interface classification:

- `bgp_mpls_as`
- `bgp_inet_as`
- `bgp_local_as` from `bgp.as`

Any valid Python regex is accepted. Quote values that start with `^` or contain
special YAML characters such as `|` or `\`.

Example:

```yaml
generate:
  mpls_node: '^mpls\d'
  inet_node: 'inet|internet'
```

The `generate:` section is used only during generation and is stripped from the
output file.
