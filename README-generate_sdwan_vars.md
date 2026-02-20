# generate_sdwan_vars.py

Generates an `sdwan_variables` YAML file by combining two sources:

| Source | Contains |
| --- | --- |
| `sdwan_variables-base.yml` | Static values you maintain manually (site IDs, loopbacks, timers, certs) |
| `host_vars/<device>/topology.json` | Dynamic values produced by netlab (IPs, interfaces, BGP ASNs) |

Run this script after every `netlab up` to regenerate the variables file with
the current topology IPs. No manual editing of device IPs or interface names is
needed.

## Requirements

- Python 3.9+
- PyYAML (`pip install pyyaml`)

## Usage

```bash
python3 generate_sdwan_vars.py
```

By default, reads `sdwan_variables-base.yml` and `host_vars/*/topology.json`
from the script's own directory, and writes `sdwan_variables-test.yml` to the
current working directory.

### Options

| Argument | Default | Description |
| --- | --- | --- |
| `--base` | `<script dir>/sdwan_variables-base.yml` | Base YAML with static values |
| `--host-vars` | `<script dir>/host_vars` | Path to the host_vars directory |
| `--output` | `sdwan_variables-test.yml` in current directory | Output file (folder + filename) |

`--base` and `--host-vars` default to paths relative to the script itself, so
they work correctly regardless of where you run the script from.

`--output` defaults to the current working directory, so the generated file
lands wherever you are when you run the script.

```bash
# Run from anywhere — inputs come from the script's directory,
# output goes to the current working directory
cd /some/netlab/project
python3 /path/to/generate_sdwan_vars.py

# Custom output filename and/or folder
python3 /path/to/generate_sdwan_vars.py --output my_vars.yml
python3 /path/to/generate_sdwan_vars.py --output automate_sdwan/sdwan_variables-test.yml

# Override inputs too (e.g. a different netlab project)
python3 /path/to/generate_sdwan_vars.py \
  --host-vars /other/netlab/project/host_vars \
  --output /other/netlab/project/automate_sdwan/sdwan_variables-test.yml
```

The output folder is created automatically if it does not exist.

## How it works

The script scans all `host_vars/*/topology.json` files and identifies SD-WAN
devices by directory name or `clab.kind`:

| Directory name | Mapped to | Detection |
| --- | --- | --- |
| `sdwan-manager` | `devices.manager` | directory name |
| `sdwan-controller` | `devices.controller` | directory name |
| `sdwan-validator` | `devices.validator` | directory name |
| `edge*` | `devices.edges.<name>` | `clab.kind: cisco_c8000v` |
| everything else | skipped | — |

For each recognised device, the script extracts dynamic fields and merges them
with the matching entry in the base YAML. **Base values always win** — if the
same key exists in both, the base YAML value is kept. This ensures your
manually-set fields (site IDs, loopbacks, timers) are never overwritten.

### Fields derived from topology.json

#### Manager / Controller

| Output key | Source in topology.json |
| --- | --- |
| `mgmt_ip`, `system_ip` | `mgmt.ipv4` |
| `interface_name` | `interfaces[0].ifname` |
| `interface_ip` | `interfaces[0].ipv4` (IP part) |
| `interface_prefix` | `interfaces[0].ipv4` (prefix length) |
| `route_gw` | `interfaces[0].gateway.ipv4` (IP part) |
| `interface_desc` | `interfaces[0].name` (`->` replaced with `to`) |

#### Validator

Same as above, with one addition: the Linux interface name (`eth1`, `eth2`, ...)
is automatically translated to the vBond `ge0/x` notation used in the SD-WAN
CLI:

```text
eth1 → ge0/0
eth2 → ge0/1
...
```

#### Edges (C8000v)

Interfaces are classified by their neighbor node name in the topology:

| Neighbor node | Maps to | Keys generated |
| --- | --- | --- |
| `mpls0` | MPLS transport | `mpls_interface`, `mpls_ip`, `mpls_mask`, `mpls_gw`, `mpls_desc` |
| `inet0` | Internet transport | `inet_interface`, `inet_ip`, `inet_mask`, `inet_gw`, `inet_desc` |
| anything else | LAN (first=`lan`, second=`lan2`, …) | `lan_interface`, `lan_ip`, `lan_mask`, `lan_gw`, `lan_desc` |

BGP fields are read from `bgp.as` and `bgp.neighbors`:

| Output key | Source |
| --- | --- |
| `bgp_local_as` | `bgp.as` |
| `bgp_mpls_as` | `bgp.neighbors[name=mpls0].as` |
| `bgp_inet_as` | `bgp.neighbors[name=inet0].as` |

### Fields that must stay in sdwan_variables-base.yml

These are not present in the netlab topology and must be set manually:

| Device | Keys |
| --- | --- |
| manager | `site_id`, `country`, `state`, `city`, `csr_file`, `api_ready_timeout_minutes` |
| controller | `site_id`, `csr_file` |
| validator | `site_id`, `csr_file` |
| edges | `site_id`, `vrf_id`, `ospf_instance`, `ospf_area`, `loopback100_*`, `loopback200_*` |
| all | `shared`, `timing`, `certificates` sections |

## Files

```text
cisco-sdwan-lab/
├── generate_sdwan_vars.py        # this script
├── sdwan_variables-base.yml      # static values — edit this for your lab
└── automate_sdwan/
    └── sdwan_variables-test.yml  # example generated output
```
