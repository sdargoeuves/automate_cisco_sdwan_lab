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

### 1. Review `sdwan_base_variables.yml`

Check the static values that netlab cannot derive: credentials, VPN ID, and timing.
Edge devices are auto-discovered from the topology and site IDs are auto-assigned
(`edge_site_id_start + n`, sorted alphabetically — default gives 101, 102, 103, …).
No need to list your edge device names manually.

### 2. Run `deploy` — generate variables and run first-boot

```bash
python sdwan_automation.py deploy --host-vars /path/to/netlab/host_vars
```

This generates the variables file from the netlab topology and immediately runs
first-boot automation on Manager, Validator, Controller, and Edges in sequence.

Alternatively, run the two steps separately:

```bash
# Generate the variables file
python sdwan_automation.py generate --host-vars /path/to/netlab/host_vars -o sdwan_variables-test.yml

# Run first-boot on all SD-WAN components
python sdwan_automation.py --variables-file sdwan_variables-test.yml all
```

### 3. Apply edge routing

```bash
python sdwan_automation.py --variables-file sdwan_variables-test.yml edges all --extra-routing
```

This pushes OSPF and BGP routing config to each edge, enabling communication between
the SD-WAN fabric, transport, and LAN devices.

> **Netlab topology requirement:** LAN-side neighbors connected to edges must run OSPF
> in **area 0.0.0.0**. The edge automation always configures LAN interfaces with
> `ip ospf <instance> area 0.0.0.0`.

---

## Requirements

- Python 3.11+
- Network reachability to Manager/Validator/Controller management IPs
- Manager API reachable on HTTPS (default port 443)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

The automation is driven by a single YAML variables file. Not using netlab? Take a look at
`sdwan_variables.example.yml` — it shows the complete structure and every value you will
need to fill in manually: management IPs, system IPs, interface names, and BGP ASNs.

### sdwan_base_variables.yml

Contains **static values** that cannot be derived from the netlab topology — edit this
before running `generate`. Values here always win over topology data.

| Section | Keys | Description |
| --- | --- | --- |
| `shared` | `org`, `username`, `default_password`, `updated_password`, `port` | Organisation name, credentials, Manager API port |
| `timing` | various | Startup sequencing delays, Netmiko and CSR timeouts; `edge_stagger_seconds` (default `2`) controls the delay between launching each edge in parallel |
| `certificates` *(optional)* | `rsa_key`, `root_cert`, `signed_cert` | Override default RSA key and certificate file names |
| `devices` | `component_site_id` | Shared site ID for Manager, Controller, and Validator |
| `devices` | `vpn_id` | Shared VRF/VPN ID and OSPF instance ID applied to all edges |
| `devices` | `edge_site_id_start` *(optional)* | Base for auto-assigned edge site IDs (default `100` → gives 101, 102, …). Set to `200` for 201, 202, … |
| `devices.edges.<name>` *(optional)* | `site_id` | Per-edge site ID override — only needed when you want a specific value instead of the auto-assigned one |
| `generate` *(optional)* | `mpls_node`, `inet_node` | Regex patterns to identify MPLS/internet transport interfaces (provided base file uses: `^mpls\d`, `^inet\d`) |

Do not set IPs, interface names, or BGP ASNs here — those come from the netlab topology.

### sdwan_variables.gen.yml (generated output)

Produced by `generate`/`deploy`; consumed by all automation subcommands. Do not edit
manually. Combines `sdwan_base_variables.yml` with management IPs, system IPs,
data-plane interface names/IPs/gateways (MPLS, internet, LAN), and BGP ASNs from the
topology. See `sdwan_variables.example.yml` for the complete structure and all available keys.

## Usage

Run from the `automate_sdwan` directory. Use `--variables-file <file>` (or `-f` for short)
before any subcommand to load a specific variables file instead of the default.

### Generate Variables from Netlab Topology

Merges `sdwan_base_variables.yml` with IPs and interfaces from netlab. Run after every
`netlab up`.

```bash
python sdwan_automation.py generate --host-vars ../host_vars
python sdwan_automation.py generate --host-vars ../host_vars -o sdwan_variables-test.yml
```

| Flag | Default | Description |
| --- | --- | --- |
| `--host-vars` | *(required)* | Path to the host_vars (topology) directory |
| `-b` / `--base` | `<script dir>/sdwan_base_variables.yml` | Base YAML with static values |
| `-o` / `--output` | `<script dir>/sdwan_variables.gen.yml` | Output file |

#### How device and interface mapping works

The generator scans every `host_vars/<device>/topology.json` and maps devices as follows:

| Directory name | Mapped to | Detection method |
| --- | --- | --- |
| `sdwan-manager` | `devices.manager` | directory name |
| `sdwan-controller` | `devices.controller` | directory name |
| `sdwan-validator` | `devices.validator` | directory name |
| any other dir | `devices.edges.<name>` | `clab.kind == cisco_c8000v` |
| everything else | skipped | — |

Edge site IDs are auto-assigned as `edge_site_id_start + n` (edges sorted alphabetically,
1-indexed). With the default `edge_site_id_start: 100`, three edges get 101, 102, 103.
Per-device overrides in `sdwan_base_variables.yml` under `devices.edges.<name>.site_id`
always take precedence. Any `devices.edges` entries in the base file that have no
corresponding topology device are silently pruned from the output.

Control-plane devices use `interfaces[0]` for transport IP/prefix/gateway. Validator
interface names are translated from Linux `ethX` to vBond `ge0/X` notation.

Edge interfaces are classified by matching the **neighbor node name** against regex patterns:

| Pattern (in provided base file) | Mapped to | Output keys |
| --- | --- | --- |
| `^mpls\d` | MPLS transport | `mpls_interface`, `mpls_ip`, `mpls_mask`, `mpls_gw`, `mpls_desc` |
| `^inet\d` | Internet transport | `inet_interface`, `inet_ip`, `inet_mask`, `inet_gw`, `inet_desc` |
| no match | LAN | entry in `lan_interfaces` list |

BGP ASNs follow the same patterns (`bgp_mpls_as`, `bgp_inet_as`; `bgp_local_as` from `bgp.as`).

Override patterns under `generate:` in `sdwan_base_variables.yml`. Any valid Python regex
is accepted — **quote values** that start with `^` or contain `|` or `\`:

```yaml
generate:
  mpls_node: '^mpls\d'       # matches mpls0, mpls1, but NOT mpls-provider
  inet_node: 'inet|internet' # matches either "inet" or "internet"
```

This section is stripped from the output file.

### Deploy (Generate + First-Boot in one step)

```bash
python sdwan_automation.py deploy --host-vars ../host_vars
python sdwan_automation.py deploy --host-vars ../host_vars -b sdwan_base_netlab.yml -o sdwan_variables-netlab.gen.yml
```

| Flag | Default | Description |
| --- | --- | --- |
| `--host-vars` | *(required)* | Path to the host_vars (topology) directory |
| `-b` / `--base` | `<script dir>/sdwan_base_variables.yml` | Base YAML with static values |
| `-o` / `--output` | `<script dir>/sdwan_variables.gen.yml` | Output variables file (also loaded for automation) |
| `-v` / `--verbose` | — | Enable verbose logging output |

The output file can be passed to subsequent subcommands with `--variables-file` to re-run individual steps.

### All Components (First-Boot)

Runs first-boot in sequence: Manager → Validator → Controller → Edges. Use this when
you have already run `generate` separately, or to re-run first-boot on an existing
variables file.

```bash
python sdwan_automation.py --variables-file sdwan_variables-test.yml all
```

### Manager | Validator | Controller

```bash
python sdwan_automation.py --variables-file sdwan_variables-test.yml [manager|validator|controller] --first-boot
python sdwan_automation.py --variables-file sdwan_variables-test.yml [manager|validator|controller] --cert
python sdwan_automation.py --variables-file sdwan_variables-test.yml [manager|validator|controller] --initial-config
python sdwan_automation.py --variables-file sdwan_variables-test.yml [manager|validator|controller] --config-file myconfig.txt
```

### Edges (cEdge)

Targets are required and can be a comma-separated list or `all`:

```bash
python sdwan_automation.py --variables-file sdwan_variables-test.yml edges all --first-boot
python sdwan_automation.py --variables-file sdwan_variables-test.yml edges all --extra-routing
python sdwan_automation.py --variables-file sdwan_variables-test.yml edges edge1,edge2 --initial-config
python sdwan_automation.py --variables-file sdwan_variables-test.yml edges edge1 --cert
python sdwan_automation.py --variables-file sdwan_variables-test.yml edges edge1 --config-file myconfig.txt
```

Edge options:

- `--first-boot` — implies `--initial-config` and `--cert`
- `--initial-config` — push initial edge configuration
- `--cert` — run certificate automation
- `--config-file <file>` — push an additional config file
- `--extra-routing` — push OSPF and BGP routing config. LAN interfaces are placed in
  **OSPF area 0.0.0.0** — LAN-side neighbors must also be configured for area 0.0.0.0.

Edge targets must match the keys under `devices.edges`. Using `edges all` selects every
edge in the variables file.

### Show Devices Status

```bash
python sdwan_automation.py --variables-file sdwan_variables-test.yml show devices
```

### SDK passthrough

Run any Sastre SDK CLI command without retyping credentials:

```bash
python sdwan_automation.py --variables-file sdwan_variables-test.yml sdk show dev
python sdwan_automation.py --variables-file sdwan_variables-test.yml sdk backup all --workdir backups
```

Add `-v` to most subcommands for verbose output.

## Logs

- `logs/sdwan_automation.log` (INFO+)
- `logs/sdwan_automation.debug.log` (DEBUG)

## Project Layout

- `sdwan_automation.py`: CLI entry point
- `sdwan_base_variables.yml`: static values you maintain manually
- `sdwan_variables.example.yml`: example of a generated variables file (reference for structure)
- `topology.example.yml`: example netlab topology used in this README
- `components/`: automation flows per component
- `utils/generate_sdwan_vars.py`: netlab topology → YAML generator
- `utils/sdwan_config.py`: config assembly and variable loader
- `utils/`: SDK, Netmiko, logging, and console helpers
