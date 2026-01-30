# Cisco SD-WAN Certificate Automation

Automate first-boot configuration and enterprise certificate enrollment for a
Cisco SD-WAN lab (vManage, vBond, vSmart). The workflow uses Netmiko for CLI
tasks and the Sastre SDK for Manager API interactions.

## Features

- Manager (vManage) first-boot config push and enterprise root certificate setup
- Validator (vBond) first-boot config push and pulls cert from Manager
- Controller (vSmart) first-boot config push and pulls cert from Manager
- Edge (cEdge) first-boot config and certificate automation (edge1/edge2/edge3)
- Optional extra routing for edges from the sdwan_variables.yml file (OSPF/BGP)
- Optional config file push for each component
- Structured console output and rotating log files
- Sastre SDK CLI passthrough via `sdk` subcommand

## Requirements

- Python 3.10+
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

### Variables guide (what to edit)

- `shared`: org name, default/updated passwords, API port
- `timing`: waits and retry timers used by Netmiko and automation sequencing
- `certificates`: file names for RSA key, root cert, and signed cert
- `network`: shared network values (validator/controller system IPs)
- `devices.manager|validator|controller`: management IPs and initial config
  fields used to build the first-boot CLI
- `devices.edges.edge1|edge2|edge3`: per-edge values for initial config and
  optional extra routing config (OSPF/BGP) (used by `--extra-routing`)

Edge targets must match the keys under `devices.edges` (edge1/edge2/edge3).
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
./sdwan_automation.py [manager|validator|controller] --first-boot
./sdwan_automation.py [manager|validator|controller] --cert
./sdwan_automation.py [manager|validator|controller] --initial-config
./sdwan_automation.py [manager|validator|controller] --config-file myconfig.txt
```

### Edges (cEdge)

Targets are required and can be a comma-separated list or `all`:

```bash
./sdwan_automation.py edges edge1 --first-boot
./sdwan_automation.py edges edge1,edge2 --initial-config
./sdwan_automation.py edges edge3 --cert
./sdwan_automation.py edges all --cert
./sdwan_automation.py edges edge2 --config-file myconfig.txt
./sdwan_automation.py edges edge1 --extra-routing
```

Edge options:

- `--first-boot` (implies `--initial-config` and `--cert`)
- `--initial-config`
- `--cert`
- `--config-file <file>`
- `--extra-routing` (pushes routing config built from `sdwan_variables.yml`)

### All Components (First-Boot)

```bash
./sdwan_automation.py all
```

### Show Devices Status

```bash
./sdwan_automation.py show devices
```

### SDK passthrough

Run any Sastre SDK CLI command without retyping credentials:

```bash
./sdwan_automation.py sdk show dev
./sdwan_automation.py sdk backup all --workdir backups
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
