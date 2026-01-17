# Cisco SD-WAN Certificate Automation

Automate first-boot configuration and enterprise certificate enrollment for a
Cisco SD-WAN lab (vManage, vBond, vSmart). The workflow uses Netmiko for CLI
tasks and the vManage REST API for certificate settings.

## Features

- Manager (vManage) first-boot config push and enterprise root certificate setup
- Validator (vBond) first-boot config push and pulls cert from Manager
- Controller (vSmart) first-boot config push and pulls cert from Manager
- Optional config file push for each component
- Structured console output and rotating log files

## Requirements

- Python 3.10+
- Network reachability to vManage/vBond/vSmart management IPs
- vManage API reachable on HTTPS (default port 443)
- Python deps: `netmiko`, `requests`

Example install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install netmiko requests
```

## Configuration

Edit `sdwan_config.py` to match your lab:

- `ORG`, `USERNAME`, `PASSWORD`, `PORT`
- Device IPs in `CONFIG`
- Initial CLI snippets in `*_INITIAL_CONFIG`
- Certificate file names and CSR defaults

The defaults assume:

- vManage (manager) at `10.194.58.14`
- vBond (validator) at `10.194.58.16`
- vSmart (controller) at `10.194.58.15`
- vBond IP at `10.1.0.6`

## Usage

Run from the `automate_sdwan` directory.

### Manager

```bash
./sdwan_automation.py manager --first-boot
./sdwan_automation.py manager --cert
./sdwan_automation.py manager --initial-config
./sdwan_automation.py manager --config-file myconfig.txt
```

### Validator

```bash
./sdwan_automation.py validator --first-boot
./sdwan_automation.py validator --cert
./sdwan_automation.py validator --initial-config
./sdwan_automation.py validator --config-file myconfig.txt
```

### Controller (vSmart)

```bash
./sdwan_automation.py controller --first-boot
./sdwan_automation.py controller --cert
./sdwan_automation.py controller --initial-config
./sdwan_automation.py controller --config-file myconfig.txt
```

### All Components (First-Boot)

```bash
./sdwan_automation.py all
```

Add `-v` to any command for verbose console output.

## Logs

- `logs/sdwan_automation.log` (INFO+)
- `logs/sdwan_automation.debug.log` (DEBUG)
- `netmiko_session.log` (Netmiko session transcript)

## Project Layout

- `sdwan_automation.py`: CLI entry point
- `sdwan_config.py`: site-specific configuration and initial configs
- `components/`: automation flows per component
- `utils/`: API, Netmiko, logging, and console helpers

