# Cisco SD-WAN Certificate Automation

Automate first-boot configuration and certificate enrollment for a
Cisco SD-WAN lab (Manager, Validator, Controller). The workflow uses Netmiko for CLI
tasks and the Sastre SDK for Manager API interactions.

## TL;DR — Quick Start

After `netlab up`, from the `automate_sdwan` directory:

### 1. Review `sdwan_variables-base.yml`

Check the static values that netlab cannot derive: site IDs, OSPF areas, VRF ID,
credentials, and timing. Edit to match your lab before generating.

### 2. Generate the variables file from the netlab topology

```bash
python sdwan_automation.py generate -t ../host_vars -o sdwan_variables-test.yml
```

This merges `sdwan_variables-base.yml` with the IPs and interfaces netlab assigned.

### 3. Run first-boot on all SD-WAN components

```bash
python sdwan_automation.py -f sdwan_variables-test.yml all
```

This configures Manager, Validator, Controller, and Edges in sequence and enrolls
all certificates.

### 4. Apply edge routing

```bash
python sdwan_automation.py -f sdwan_variables-test.yml edges all --extra-routing
```

This pushes the OSPF and BGP routing configuration to each edge, enabling
communication between the SD-WAN fabric and the LAN devices connected to each edge.

---

## Features

- Manager (vManage) first-boot config push and enterprise root certificate setup
- Validator (vBond) first-boot config push and pulls cert from Manager
- Controller (vSmart) first-boot config push and pulls cert from Manager
- Edge (cEdge) first-boot config and certificate automation (per-edge keys under `devices.edges`)
- OSPF/BGP extra routing config for edges (`--extra-routing`)
- Optional config file push for each component
- `generate` subcommand to produce the variables file from netlab topology files
- Structured console output and rotating log files
- Sastre SDK CLI passthrough via `sdk` subcommand

## Requirements

- Python 3.11+
- Network reachability to Manager/Validator/Controller management IPs
- Manager API reachable on HTTPS (default port 443)
- Python deps: `netmiko`, `requests`, `cisco-sdwan`, `PyYAML`

Example install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

The automation is driven by a single YAML variables file. When working with a
netlab topology, this file is generated automatically (see [Generate Variables](#generate-variables-from-netlab-topology)).
For non-netlab setups, use `sdwan_variables.yml` as a starting template and edit
it manually.

### sdwan_variables-base.yml

This file contains the **static values** that cannot be derived from the netlab
topology. It is the only file you need to edit before running `generate`.

The `generate` subcommand reads both this file and the netlab `host_vars/*/topology.json`
files, then merges them into a single output file. **Values in this file always
win** — if a key exists here, it will not be overwritten by the topology data.

#### What to set here

| Section | Keys | Description |
| --- | --- | --- |
| `shared` | `org`, `username`, `default_password`, `updated_password`, `port` | Organisation name, credentials, Manager API port |
| `timing` | various | Startup sequencing delays, Netmiko and CSR timeouts |
| `certificates` | `rsa_key`, `root_cert`, `signed_cert` | File names for the RSA key and certificate files |
| `devices.manager` | `site_id`, `csr_file`, `country`, `state`, `city`, `api_ready_timeout_minutes` | Manager-specific static config |
| `devices.controller` | `site_id`, `csr_file` | Controller-specific static config |
| `devices.validator` | `site_id`, `csr_file` | Validator-specific static config |
| `devices.edges.<name>` | `site_id`, `vrf_id`, `ospf_instance` | Per-edge static routing config |
| `generate` *(optional)* | `mpls_node`, `inet_node` | Regex patterns matched against neighbor node name to identify MPLS/internet transport interfaces (defaults: `mpls`, `inet`) |

#### What NOT to set here

Do not put IPs, interface names, or BGP ASNs here — those are all read from the
netlab topology files and filled in automatically by `generate`.

### sdwan_variables.yml (generated output)

This is the file consumed by all automation subcommands. When using netlab, it
is produced by `generate` and should not be edited manually (changes will be lost
on the next `generate` run).

The file combines everything from `sdwan_variables-base.yml` with the dynamic
values extracted from the topology:

- Management IPs and system IPs
- Data-plane interface names, IPs, and gateways (MPLS, internet, LAN)
- BGP ASNs (local, MPLS peer, internet peer)

#### Edge device structure

Each edge is keyed by its netlab device name under `devices.edges`:

```yaml
devices:
  edges:
    edge1:
      # --- from topology (generated) ---
      mgmt_ip: 10.x.x.x
      system_ip: 10.x.x.x
      bgp_local_as: 65591
      bgp_mpls_as: 65000
      bgp_inet_as: 65001
      mpls_interface: GigabitEthernet2
      mpls_ip: 10.1.0.2
      mpls_mask: 255.255.255.252
      mpls_gw: 10.1.0.1
      mpls_desc: edge1 to mpls0
      inet_interface: GigabitEthernet3
      inet_ip: 10.10.0.2
      inet_mask: 255.255.255.252
      inet_gw: 10.10.0.1
      inet_desc: edge1 to inet0
      lan_interfaces:
      - lan_interface: GigabitEthernet4
        lan_ip: 192.168.10.1
        lan_mask: 255.255.255.0
        lan_gw: 192.168.10.254
        lan_desc: edge1 to LAN
      # --- from sdwan_variables-base.yml (static) ---
      site_id: 591
      vrf_id: 200
      ospf_instance: 200
```

Add more items to `lan_interfaces` for additional LAN interfaces.

#### Control-plane device structure

Manager, Validator, and Controller share a common structure:

```yaml
devices:
  manager:
    mgmt_ip: 10.x.x.x
    system_ip: 10.x.x.x
    interface_name: eth1
    interface_ip: 10.x.x.x
    interface_prefix: 24
    route_gw: 10.x.x.1
    interface_desc: sdwan-manager to inet0
    site_id: 255
    csr_file: vmanage_csr
    country: FI
    state: Finland
    city: Helsinki
    api_ready_timeout_minutes: 15
```

## Usage

Run from the `automate_sdwan` directory.

### Generate Variables from Netlab Topology

Produces the variables file by merging `sdwan_variables-base.yml` with the IPs
and interfaces assigned by netlab. Run this after every `netlab up`.

```bash
python sdwan_automation.py generate -t ../host_vars
python sdwan_automation.py generate -t ../host_vars -o sdwan_variables-test.yml
```

Options:

| Short | Long | Default | Description |
| --- | --- | --- | --- |
| `-t` | `--host-vars` | *(required)* | Path to the host_vars (topology) directory |
| `-b` | `--base` | `<script dir>/sdwan_variables-base.yml` | Base YAML with static values |
| `-o` | `--output` | `sdwan_variables-test.yml` in current directory | Output file |

#### How device and interface mapping works

The generator scans every `host_vars/<device>/topology.json` file and identifies
SD-WAN devices as follows:

| Directory name | Mapped to | Detection method |
| --- | --- | --- |
| `sdwan-manager` | `devices.manager` | directory name |
| `sdwan-controller` | `devices.controller` | directory name |
| `sdwan-validator` | `devices.validator` | directory name |
| any other dir | `devices.edges.<name>` | `clab.kind == cisco_c8000v` |
| everything else | skipped | — |

**Control-plane devices (Manager, Controller)** — the generator reads the first
interface (`interfaces[0]`) to extract the transport IP, prefix, and gateway.

**Validator** — same as above, but the Linux interface name is translated to the
vBond `ge0/x` notation used in the SD-WAN CLI:

```text
eth1 → ge0/0
eth2 → ge0/1
...
```

**Edge devices (C8000v)** — each interface is classified by looking at the
**neighbor node name** recorded in the topology, not by any description or interface
name. The match is a **regex search**: the configured pattern is tested against
the neighbor node name, and the first match wins.

| Pattern (regex, default) | Mapped to | Output keys |
| --- | --- | --- |
| `mpls` | MPLS transport | `mpls_interface`, `mpls_ip`, `mpls_mask`, `mpls_gw`, `mpls_desc` |
| `inet` | Internet transport | `inet_interface`, `inet_ip`, `inet_mask`, `inet_gw`, `inet_desc` |
| no match | LAN | entry added to `lan_interfaces` list |

Any interface whose neighbor name matches neither pattern is treated as a LAN
interface. You can have any number of LAN interfaces — each becomes a separate
entry in the `lan_interfaces` list.

BGP ASNs are resolved the same way, using the same regex patterns against
`bgp.neighbors[].name`:

| BGP neighbor node | Output key |
| --- | --- |
| matches `mpls` *(default)* | `bgp_mpls_as` |
| matches `inet` *(default)* | `bgp_inet_as` |
| (local device) | `bgp_local_as` (from `bgp.as`) |

The patterns can be overridden in `sdwan_variables-base.yml` under `generate:`.
Any valid Python regex is accepted. **YAML quoting rules apply**: use single quotes
whenever the pattern contains `|`, `\`, or starts with `^` — these characters have
special meaning in YAML and will cause a parse error if left unquoted.

```yaml
generate:
  # Simple substring — no quoting needed
  mpls_node: mpls               # matches mpls0, mpls1, mpls-provider, ...

  # Anchored match — quotes required because ^ starts the value
  mpls_node: '^mpls\d'          # matches mpls0, mpls1, ... but NOT mpls-provider

  # Alternation — quotes required because | is a YAML block-scalar indicator
  inet_node: 'inet|internet'    # matches either "inet" or "internet"

  # Anchored alternation
  inet_node: '^(inet|internet)' # matches names starting with "inet" or "internet"
```

This section is consumed by `generate` and stripped from the output file.

### Custom variables file

Use `-f` / `--variables-file` before the subcommand to load a specific YAML file.
This must come **before** the subcommand:

```bash
python sdwan_automation.py -f sdwan_variables-test.yml all
python sdwan_automation.py -f sdwan_variables-test.yml edges all --extra-routing
python sdwan_automation.py -f sdwan_variables-test.yml manager --first-boot
```

### All Components (First-Boot)

Runs first-boot in sequence: Manager → Validator → Controller → Edges.

```bash
python sdwan_automation.py -f sdwan_variables-test.yml all
```

### Manager | Validator | Controller

```bash
python sdwan_automation.py -f sdwan_variables-test.yml [manager|validator|controller] --first-boot
python sdwan_automation.py -f sdwan_variables-test.yml [manager|validator|controller] --cert
python sdwan_automation.py -f sdwan_variables-test.yml [manager|validator|controller] --initial-config
python sdwan_automation.py -f sdwan_variables-test.yml [manager|validator|controller] --config-file myconfig.txt
```

### Edges (cEdge)

Targets are required and can be a comma-separated list or `all`:

```bash
python sdwan_automation.py -f sdwan_variables-test.yml edges all --first-boot
python sdwan_automation.py -f sdwan_variables-test.yml edges all --extra-routing
python sdwan_automation.py -f sdwan_variables-test.yml edges edge1,edge2 --initial-config
python sdwan_automation.py -f sdwan_variables-test.yml edges edge1 --cert
python sdwan_automation.py -f sdwan_variables-test.yml edges edge1 --config-file myconfig.txt
```

Edge options:

- `--first-boot` — implies `--initial-config` and `--cert`
- `--initial-config` — push initial edge configuration
- `--cert` — run certificate automation
- `--config-file <file>` — push an additional config file
- `--extra-routing` — push OSPF and BGP routing config (built from `lan_interfaces`,
  `vrf_id`, `ospf_instance` in the variables file)

Edge targets must match the keys under `devices.edges`. Using `edges all` selects
every edge defined in the variables file.

### Show Devices Status

```bash
python sdwan_automation.py -f sdwan_variables-test.yml show devices
```

### SDK passthrough

Run any Sastre SDK CLI command without retyping credentials:

```bash
python sdwan_automation.py -f sdwan_variables-test.yml sdk show dev
python sdwan_automation.py -f sdwan_variables-test.yml sdk backup all --workdir backups
```

Add `-v` to any subcommand for verbose console output.

## Logs

- `logs/sdwan_automation.log` (INFO+)
- `logs/sdwan_automation.debug.log` (DEBUG)

## Project Layout

- `sdwan_automation.py`: CLI entry point
- `sdwan_variables-base.yml`: static values you maintain manually (edited before each lab run)
- `sdwan_variables.yml`: production variables file (edit manually for non-netlab setups)
- `components/`: automation flows per component
- `utils/generate_sdwan_vars.py`: netlab topology → YAML generator (used by `generate` subcommand)
- `utils/sdwan_config.py`: config assembly (loads the variables file at runtime)
- `utils/`: SDK, Netmiko, logging, and console helpers
