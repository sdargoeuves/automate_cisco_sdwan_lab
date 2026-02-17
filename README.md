# Cisco SD-WAN Certificate Automation

Automate first-boot configuration and enterprise certificate enrollment for a
Cisco SD-WAN lab (vManage, vBond, vSmart). The workflow uses Netmiko for CLI
tasks and the Sastre SDK for Manager API interactions.

## Features

- Manager (vManage) first-boot config push and enterprise root certificate setup
- Validator (vBond) first-boot config push and pulls cert from Manager
- Controller (vSmart) first-boot config push and pulls cert from Manager
- Edge (cEdge) first-boot config and certificate automation (per-edge keys under `devices.edges`)
- Optional extra routing for edges from the sdwan_variables.yml file (OSPF/BGP)
- Optional config file push for each component
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

Edit `sdwan_variables.yml` to match your lab:

- `shared`, `timing`, and `network` values
- Device IPs and interface settings under `devices`
- Certificate file names and CSR defaults

No code changes are required for normal lab updates. The script reads
`sdwan_variables.yml` via `utils/sdwan_config.py` and builds the config objects
at runtime. If a required key is missing, the script will fail fast with a clear
error that includes the missing key name.

### How to set up `sdwan_variables.yml`

Use the existing file as a template. The keys under `devices` are the source of
truth for what the automation will manage.

1) Set shared/global values
- `shared`: org name, usernames, passwords, API port
- `timing`: wait/retry timers
- `certificates`: file names for RSA key, root cert, signed cert

2) Define the control-plane devices
- `devices.manager|validator|controller`: management IPs and the first-boot
  CLI inputs (system IP, site ID, gateway, interface details)

3) Define edges using your real device names
- `devices.edges.<edge_name>`: each edge is keyed by its real name. Those keys
  are what you pass to the CLI (`./sdwan_automation.py edges <edge_name> ...`).

Example (edges):

```yaml
devices:
  edges:
    edge1x01:
      mgmt_ip: 10.194.58.21
      system_ip: 10.30.0.7
      site_id: 101
      vrf_id: 1
      inet_interface: GigabitEthernet2
      inet_ip: 10.10.0.13
      inet_mask: 255.255.255.0
      inet_gw: 10.10.0.1
      inet_desc: edge1x01 to inet0
      mpls_interface: GigabitEthernet3
      mpls_ip: 10.1.0.2
      mpls_mask: 255.255.255.0
      mpls_gw: 10.1.0.1
      mpls_desc: edge1x01 to mpls0
      lan_interface: GigabitEthernet4
      lan_ip: 192.168.10.1
      lan_mask: 255.255.255.0
      lan_desc: edge1x01 to LAN
      ospf_instance: 1
      ospf_area: 0
      bgp_local_as: 65010
      bgp_mpls_as: 65000
      bgp_inet_as: 65001
```

Notes:
- Optional `lan2_*` keys can be omitted unless you want a second LAN interface.
- If a required key is missing, the script exits with a clear error and the
  edge name that failed.

### Variables guide (what to edit)

- `shared`: org name, default/updated passwords, API port
- `timing`: waits and retry timers used by Netmiko and automation sequencing
- `certificates`: file names for RSA key, root cert, and signed cert
- `network`: shared network values (validator/controller system IPs)
- `devices.manager|validator|controller`: management IPs and initial config
  fields used to build the first-boot CLI
- `devices.edges.<edge_name>`: per-edge values for initial config and
  optional extra routing config (OSPF/BGP) (used by `--extra-routing`)

Edge targets must match the keys under `devices.edges` (for example: edge1x01/edge2x01/edge3x01).
Using `edges all` selects every edge defined there.

The defaults assume:

- Manager (vManage) at `10.194.58.14`
- Validator (vBond) at `10.194.58.16`
- Controller (vSmart) at `10.194.58.15`
- Validator IP at `10.10.0.6` (interface facing the internet router)

## Usage

Run from the `automate_sdwan` directory.

### Manager|Validator|Controller

```bash
python sdwan_automation.py [manager|validator|controller] --first-boot
python sdwan_automation.py [manager|validator|controller] --cert
python sdwan_automation.py [manager|validator|controller] --initial-config
python sdwan_automation.py [manager|validator|controller] --config-file myconfig.txt
```

### Edges (cEdge)

Targets are required and can be a comma-separated list or `all`:

```bash
python sdwan_automation.py edges edge1x01 --first-boot
python sdwan_automation.py edges edge1x01,edge2x01 --initial-config
python sdwan_automation.py edges edge3x01 --cert
python sdwan_automation.py edges all --cert
python sdwan_automation.py edges edge2x01 --config-file myconfig.txt
python sdwan_automation.py edges edge1x01 --extra-routing
```

Edge options:

- `--first-boot` (implies `--initial-config` and `--cert`)
- `--initial-config`
- `--cert`
- `--config-file <file>`
- `--extra-routing` (pushes routing config built from `sdwan_variables.yml`)

### All Components (First-Boot)

```bash
python sdwan_automation.py all
```

### Show Devices Status

```bash
python sdwan_automation.py show devices
```

### SDK passthrough

Run any Sastre SDK CLI command without retyping credentials:

```bash
python sdwan_automation.py sdk show dev
python sdwan_automation.py sdk backup all --workdir backups
```

Add `-v` to any command for verbose console output.

## Logs

- `logs/sdwan_automation.log` (INFO+)
- `logs/sdwan_automation.debug.log` (DEBUG)

## Project Layout

- `sdwan_automation.py`: CLI entry point
- `utils/sdwan_config.py`: config assembly (loads `sdwan_variables.yml`)
- `sdwan_variables.yml`: site-specific variables
- `components/`: automation flows per component
- `utils/`: SDK, Netmiko, logging, and console helpers
