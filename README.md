# Cisco SD-WAN Certificate Automation

Automate first-boot configuration and certificate enrollment for a Cisco SD-WAN lab
(Manager, Validator, Controller, Edges). Primarily aimed at [netlab](https://netlab.tools)
users, but works for any SD-WAN deployment where management IPs are reachable.

![SD-WAN lab topology](img/Cisco%20SD-WAN%20-%20IPF%20Lab%20-%20whiteTR.drawio.png#gh-light-mode-only)
![SD-WAN lab topology](img/Cisco%20SD-WAN%20-%20IPF%20Lab%20-%20darkTR.drawio.png#gh-dark-mode-only)

## Credits

This project is heavily based on the video series
[Exploring SDWAN 20.15: A Student Driven Video Series](https://www.youtube.com/playlist?list=PLlJgzlAyjsjMfZI4SVoX7bY8f9X-PrSnY)
by **Terry Vinson**. The goal of this script is to automate the manual configuration steps
demonstrated in those videos, so you can get a working SD-WAN lab without going through
each step by hand.

In the video series, IP addressing and interface configuration are done manually. In this
project, that work is handled by netlab — though you can also specify it directly in the
[variables file](#configuration) if you are not using netlab.

---

## TL;DR — Quick Start with `netlab`

An example netlab topology is
provided in [`topology.example.yml`](topology.example.yml) — copy and adapt it as your
starting point, then start the lab with `netlab up`.

> **Prerequisites:** you will need [netlab](https://netlab.tools) and
> [containerlab](https://containerlab.dev) installed, plus the vrnetlab images for
> `cisco_sdwan-manager`, `cisco_sdwan-controller`, `cisco_sdwan-validator`, and
> `cisco_c8000v` built and available to Docker.

### 1. Install

```bash
pip install git+https://github.com/sdargoeuves/automate_cisco_sdwan_lab.git
# or with uv:
#uv pip install git+https://github.com/sdargoeuves/automate_cisco_sdwan_lab.git
```

See [Installation](#installation) for details.

### 2. Initialise your config

```bash
sdwan-automation init
```

This copies the bundled template
[`utils/templates/sdwan_base_variables.yml`](utils/templates/sdwan_base_variables.yml)
to `~/.config/sdwan-automation/base.yml` (or
`$XDG_CONFIG_HOME/sdwan-automation/base.yml` if set). Open the file and review
the static values that netlab cannot derive: credentials, VPN ID, and timing.
Edge devices are auto-discovered from the topology and site IDs are
auto-assigned (`edge_site_id_start + n`, sorted alphabetically — default gives
101, 102, 103, …). No need to list your edge device names manually.

### 3. Run `deploy` — generate variables and run first-boot

```bash
sdwan-automation deploy --host-vars /path/to/netlab/host_vars
```

This reads `~/.config/sdwan-automation/base.yml`, generates
`~/.config/sdwan-automation/variables.yml` from the netlab topology, and
immediately runs first-boot automation on Manager, Validator, Controller, and
Edges in sequence.

Alternatively, run the two steps separately:

```bash
# Generate the variables file (writes ~/.config/sdwan-automation/variables.yml)
sdwan-automation generate --host-vars /path/to/netlab/host_vars

# Run first-boot on all SD-WAN components
sdwan-automation first-boot
```

### 4. Apply edge routing

```bash
sdwan-automation edges all --extra-routing
```

This pushes OSPF and BGP routing config to each edge, enabling communication between
the SD-WAN fabric, transport, and LAN devices.

> **Netlab topology requirement:** LAN-side neighbors connected to edges must run OSPF
> in **area 0.0.0.0**. The edge automation always configures LAN interfaces with
> `ip ospf <instance> area 0.0.0.0`.

---

## Installation

- Python 3.11+
- Network reachability to Manager/Validator/Controller management IPs
- Manager API reachable on HTTPS (default port 443)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
# or:
uv pip install -e .
```

This installs `sdwan-automation` as a CLI command available anywhere in the venv.

### Install directly from GitHub

```bash
pip install git+https://github.com/sdargoeuves/automate_cisco_sdwan_lab.git
# or with uv:
uv pip install git+https://github.com/sdargoeuves/automate_cisco_sdwan_lab.git
```

Pin to a specific release tag:

```bash
pip install git+https://github.com/sdargoeuves/automate_cisco_sdwan_lab.git@v1.0.1
```

## Configuration

The automation reads from:

- `~/.config/sdwan-automation/base.yml`: editable template with static values.
- `~/.config/sdwan-automation/variables.yml`: generated runtime variables.

If `$XDG_CONFIG_HOME` is set, that directory is used instead of `~/.config`.

Run `sdwan-automation init` once to create `base.yml`, then edit the static values
that netlab cannot derive: organization name, credentials, site/VRF defaults,
transport matching patterns, and timing.

If you use netlab, do not normally edit `variables.yml` by hand. It is produced
by `generate` or `deploy` and combines `base.yml` with topology data.

If you are not using netlab, create your own variables file from
[`sdwan_variables.example.yml`](sdwan_variables.example.yml). Fill in the
management IPs, system IPs, interface names, transport gateways, LAN interfaces,
site IDs, and BGP ASNs manually. Then pass that file with `-f`:

```bash
cp sdwan_variables.example.yml ~/my-sdwan-variables.yml
vi ~/my-sdwan-variables.yml
sdwan-automation -f ~/my-sdwan-variables.yml first-boot
sdwan-automation -f ~/my-sdwan-variables.yml edges all --extra-routing
```

With a manual variables file, skip `generate` and `deploy`; those commands are
for netlab-derived topology data.

For details on topology mapping, edge site ID assignment, and interface
classification, see [`docs/topology-generation.md`](docs/topology-generation.md).

## Usage

All subcommands read `~/.config/sdwan-automation/variables.yml` by default. Use
`--variables-file <file>` (or `-f` for short) before any subcommand to load a
different file instead.

### Initialise Config (`init`)

```bash
sdwan-automation init
sdwan-automation init --force   # overwrite an existing base.yml
```

Copies the bundled `base.yml` template into `~/.config/sdwan-automation/`.
Run once after install, then edit the file to set org name, passwords, and timing.

### Generate Variables from Netlab Topology

Merges `base.yml` with IPs and interfaces from netlab. Run after every `netlab up`.

```bash
sdwan-automation generate --host-vars ../host_vars
sdwan-automation generate --host-vars ../host_vars -o /tmp/sdwan_variables-test.yml
```

### Deploy (Generate + First-Boot in one step)

```bash
sdwan-automation deploy --host-vars ../host_vars
sdwan-automation deploy --host-vars ../host_vars -b /tmp/sdwan_base_netlab.yml -o /tmp/sdwan_variables-netlab.yml
```

If you override `-o`, pass the same path to subsequent subcommands with `--variables-file` to re-run individual steps.

### First-Boot (all components)

Runs first-boot in sequence: Manager → Validator → Controller → Edges. Use this when
you have already run `generate` separately, or to re-run first-boot on an existing
variables file. Does not push edge `--extra-routing`; run that separately afterwards
if needed.

```bash
sdwan-automation first-boot
```

### Manager | Validator | Controller

```bash
sdwan-automation [manager|validator|controller] --first-boot
sdwan-automation [manager|validator|controller] --cert
sdwan-automation [manager|validator|controller] --initial-config
sdwan-automation [manager|validator|controller] --config-file myconfig.txt
```

### Edges (cEdge)

Targets are required and can be a comma-separated list or `all`:

```bash
sdwan-automation edges all --first-boot
sdwan-automation edges all --extra-routing
sdwan-automation edges edge1,edge2 --initial-config
sdwan-automation edges edge1 --cert
sdwan-automation edges failed --cert
sdwan-automation edges edge1 --config-file myconfig.txt
```

Edge options:

- `--first-boot` — implies `--initial-config` and `--cert`
- `--initial-config` — push initial edge configuration
- `--cert` — run certificate automation
- `--config-file <file>` — push an additional config file
- `--extra-routing` — push OSPF and BGP routing config. LAN interfaces are placed in
  **OSPF area 0.0.0.0** — LAN-side neighbors must also be configured for area 0.0.0.0.

Edge targets must match the keys under `devices.edges`. Using `edges all` selects every
edge in the variables file. `edges failed --cert` selects configured edges that
currently have fewer than two vManage control connections, which is the repair
path for edges that did not complete certificate onboarding.

When `--cert` is used for multiple edges, the command first waits for every
targeted edge to join the control fabric (`control_connections_up >= 2`). Only
edges that fail that control-plane gate are retried with a fresh
certificate/license flow. BFD is checked only after all targeted edges have
joined the fabric; if BFD still fails, the tool treats that as a data-plane/TLOC
issue rather than continuing to regenerate certificates.

### Show Devices Status

```bash
sdwan-automation show devices
sdwan-automation show licenses
```

### Version

```bash
sdwan-automation version
```

### SDK passthrough

Run any [Sastre](https://github.com/CiscoDevNet/sastre) SDK CLI command without retyping credentials:

```bash
sdwan-automation sdk show dev
sdwan-automation sdk backup all --workdir backups
```

Add `-v` to most subcommands for verbose output.

## Tests

Install the optional test dependency and run pytest:

```bash
pip install -e ".[test]"
pytest
```

## Logs

Written under the user config directory (`$XDG_CONFIG_HOME/sdwan-automation/logs/`
or `~/.config/sdwan-automation/logs/` by default):

- `sdwan_automation.log` (INFO+, rotated at 2 MB, 5 backups gzipped)
- `sdwan_automation.debug.log` (DEBUG, same rotation policy)

## Project Layout

- `sdwan_automation.py`: CLI entry point
- `docs/architecture.md`: maintainer guide explaining internal flow, retry logic,
  and component responsibilities
- `docs/llm-context.md`: compact handoff for future LLM/debugging sessions
- `utils/templates/sdwan_base_variables.yml`: bundled base template — copied to
  `~/.config/sdwan-automation/base.yml` by `sdwan-automation init`
- `sdwan_variables.example.yml`: example of a generated variables file (reference for structure)
- `topology.example.yml`: example netlab topology used in this README
- `components/`: automation flows per component
- `utils/config_paths.py`: resolves the user config directory (`$XDG_CONFIG_HOME` or `~/.config`)
- `utils/generate_sdwan_vars.py`: netlab topology → YAML generator
- `utils/sdwan_config.py`: config assembly and variable loader
- `utils/`: SDK, Netmiko, logging, and console helpers
