from dataclasses import dataclass

# =============================================================================
# Shared Configuration Values
# =============================================================================
ORG: str = "ipf-netlab"
USERNAME: str = "admin"
DEFAULT_PASSWORD: str = "admin"
UPDATED_PASSWORD: str = "admin@123"
PORT: str = "443"
WAIT_BEFORE_AUTOMATING_CONTROLLER: int = 120
WAIT_BEFORE_AUTOMATING_VALIDATOR: int = 60
WAIT_CSR_GENERATION: int = 30
WAIT_BEFORE_ACTIVATING_EDGE: int = 60
WAIT_AFTER_GENERATING_PAYG_LICENSE: int = 30
EDGE_CERT_POLL_INTERVAL_SECONDS: int = 10
EDGE_CERT_POLL_TIMEOUT_SECONDS: int = 180
NETMIKO_INCREASED_READ_TIMEOUT: int = 30
CSR_FILE_TIMEOUT_SECONDS: int = 60

# Certificate files (same across all devices)
RSA_KEY: str = "SDWAN.key"
ROOT_CERT: str = "SDWAN.pem"
SIGNED_CERT: str = "NewCertificate.crt"

# Network
VALIDATOR_IP: str = "10.10.0.6"  # Validator/vBond's IP
CONTROLLER_IP: str = "10.10.0.10"  # Controller/vSmart's IP


# =============================================================================
# Device-Specific Configuration
# =============================================================================
@dataclass(frozen=True)
class ManagerConfig:
    mgmt_ip: str
    port: str = PORT
    username: str = USERNAME
    password: str = UPDATED_PASSWORD
    default_password: str = DEFAULT_PASSWORD
    org: str = ORG
    validator_ip: str = VALIDATOR_IP
    country: str = "FI"
    state: str = "Finland"
    city: str = "Helsinki"
    rsa_key: str = RSA_KEY
    root_cert: str = ROOT_CERT
    signed_cert: str = SIGNED_CERT
    csr_file: str = "vmanage_csr"
    api_ready_timeout_minutes: int = 15
    initial_config: str = ""


@dataclass(frozen=True)
class ValidatorConfig:
    mgmt_ip: str
    username: str = USERNAME
    password: str = UPDATED_PASSWORD
    default_password: str = DEFAULT_PASSWORD
    org: str = ORG
    validator_ip: str = VALIDATOR_IP
    rsa_key: str = RSA_KEY
    root_cert: str = ROOT_CERT
    signed_cert: str = SIGNED_CERT
    csr_file: str = "vbond_csr"
    initial_config: str = ""


@dataclass(frozen=True)
class ControllerConfig:
    mgmt_ip: str
    username: str = USERNAME
    password: str = UPDATED_PASSWORD
    default_password: str = DEFAULT_PASSWORD
    org: str = ORG
    validator_ip: str = VALIDATOR_IP
    controller_ip: str = CONTROLLER_IP
    rsa_key: str = RSA_KEY
    root_cert: str = ROOT_CERT
    signed_cert: str = SIGNED_CERT
    csr_file: str = "vsmart_csr"
    initial_config: str = ""


@dataclass(frozen=True)
class EdgeConfig:
    mgmt_ip: str
    username: str = USERNAME
    password: str = UPDATED_PASSWORD
    default_password: str = DEFAULT_PASSWORD
    org: str = ORG
    validator_ip: str = VALIDATOR_IP
    controller_ip: str = CONTROLLER_IP
    rsa_key: str = RSA_KEY
    root_cert: str = ROOT_CERT
    signed_cert: str = SIGNED_CERT
    csr_file: str = "vsmart_csr"
    initial_config: str = ""


# =============================================================================
# Initial Configurations (CLI to push on first boot)
# =============================================================================
def build_manager_initial_config(
    system_ip: str,
    site_id: int,
    route_gw: str,
    interface_name: str,
    interface_ip: str,
    interface_desc: str,
) -> str:
    return f"""
system
aaa
user admin
password {UPDATED_PASSWORD}
site-id {site_id}
organization-name {ORG}
system-ip {system_ip}
vbond {VALIDATOR_IP}
vpn 0
ip route 0.0.0.0/0 {route_gw}
interface {interface_name}
ip address {interface_ip}
description "{interface_desc}"
no shut
tunnel-interface
allow-service all
"""


def build_validator_initial_config(
    system_ip: str,
    site_id: int,
    route_gw: str,
    interface_name: str,
    interface_ip: str,
    interface_desc: str,
) -> str:
    return f"""
system
aaa
user admin
password {UPDATED_PASSWORD}
site-id {site_id}
organization-name {ORG}
system-ip {system_ip}
vbond {VALIDATOR_IP} local
vpn 0
ip route 0.0.0.0/0 {route_gw}
interface {interface_name}
ip address {interface_ip}
description "{interface_desc}"
no shut
no tunnel-interface
commit
tunnel-interface
encapsulation ipsec
allow-service all
"""


def build_controller_initial_config(
    system_ip: str,
    site_id: int,
    route_gw: str,
    interface_name: str,
    interface_ip: str,
    interface_desc: str,
) -> str:
    return f"""
system
aaa
user admin
password {UPDATED_PASSWORD}
site-id {site_id}
organization-name {ORG}
system-ip {system_ip}
vbond {VALIDATOR_IP}
vpn 0
ip route 0.0.0.0/0 {route_gw}
interface {interface_name}
ip address {interface_ip}
description "{interface_desc}"
no shut
tunnel-interface
allow-service all
"""


def build_edge_initial_config(
    name: str,
    system_ip: str,
    site_id: int,
    inet_ip: str,
    inet_mask: str,
    inet_gw: str,
    inet_desc: str,
    inet_interface: str,
    mpls_ip: str,
    mpls_mask: str,
    mpls_gw: str,
    mpls_desc: str,
    mpls_interface: str,
) -> str:
    return f"""
no ip domain lookup
lldp run
username admin password {UPDATED_PASSWORD}

ip route 0.0.0.0 0.0.0.0 {inet_gw}
int {inet_interface}
no shutdown
ip address {inet_ip} {inet_mask}
description "{inet_desc}"
exit

!!! this default route will currently break the automation
!ip route 0.0.0.0 0.0.0.0 {mpls_gw}
!!! DO NOT USE YET
int {mpls_interface}
no shutdown
ip address {mpls_ip} {mpls_mask}
description "{mpls_desc}"
exit

system
system-ip {system_ip}
site-id {site_id}
organization-name {ORG}
vbond {VALIDATOR_IP}
exit

interface Tunnel1
no shutdown
ip unnumbered {inet_interface}
tunnel source {inet_interface}
tunnel mode sdwan
exit
interface Tunnel2
ip unnumbered {mpls_interface}
tunnel source {mpls_interface}
tunnel mode sdwan
exit

sdwan
interface {inet_interface}
no shutdown
tunnel-interface
encapsulation ipsec
allow-service all
color public-internet
exit
commit
interface {mpls_interface}
no shutdown
tunnel-interface
encapsulation ipsec
allow-service all
color mpls
exit
commit
"""


# =============================================================================
# Device Definitions
# =============================================================================
MANAGER_DEVICE = {
    "mgmt_ip": "10.194.58.14",
    "system_ip": "10.194.58.14",
    "site_id": 255,
    "route_gw": "10.10.0.1",
    "interface_name": "eth1",
    "interface_ip": "10.10.0.2/30",
    "interface_desc": "sdwan-manager to inet0",
}

VALIDATOR_DEVICE = {
    "mgmt_ip": "10.194.58.16",
    "system_ip": "10.194.58.16",
    "site_id": 255,
    "route_gw": "10.10.0.5",
    "interface_name": "ge0/0",
    "interface_ip": "10.10.0.6/30",
    "interface_desc": "sdwan-validator to inet0",
}

CONTROLLER_DEVICE = {
    "mgmt_ip": "10.194.58.15",
    "system_ip": "10.194.58.15",
    "site_id": 255,
    "route_gw": "10.10.0.9",
    "interface_name": "eth1",
    "interface_ip": "10.10.0.10/30",
    "interface_desc": "sdwan-controller to inet0",
}

EDGE1_DEVICE = {
    "mgmt_ip": "10.194.58.17",
    "system_ip": "10.194.58.17",
    "site_id": 101,
    "inet_ip": "10.10.0.13",
    "inet_mask": "255.255.255.252",
    "inet_gw": "10.10.0.14",
    "inet_desc": "edge1 to inet0",
    "inet_interface": "GigabitEthernet4",
    "mpls_ip": "10.1.0.5",
    "mpls_mask": "255.255.255.252",
    "mpls_gw": "10.1.0.6",
    "mpls_desc": "edge1 to pe1",
    "mpls_interface": "GigabitEthernet3",
}

EDGE2_DEVICE = {
    "mgmt_ip": "10.194.58.18",
    "system_ip": "10.194.58.18",
    "site_id": 102,
    "inet_ip": "10.10.0.17",
    "inet_mask": "255.255.255.252",
    "inet_gw": "10.10.0.18",
    "inet_desc": "edge2 to inet0",
    "inet_interface": "GigabitEthernet4",
    "mpls_ip": "10.1.0.17",
    "mpls_mask": "255.255.255.252",
    "mpls_gw": "10.1.0.18",
    "mpls_desc": "edge2 to pe2",
    "mpls_interface": "GigabitEthernet3",
}

EDGE3_DEVICE = {
    "mgmt_ip": "10.194.58.19",
    "system_ip": "10.194.58.19",
    "site_id": 103,
    "inet_ip": "10.10.0.21",
    "inet_mask": "255.255.255.252",
    "inet_gw": "10.10.0.22",
    "inet_desc": "edge3 to inet0",
    "inet_interface": "GigabitEthernet4",
    "mpls_ip": "10.1.0.29",
    "mpls_mask": "255.255.255.252",
    "mpls_gw": "10.1.0.30",
    "mpls_desc": "edge3 to pe3",
    "mpls_interface": "GigabitEthernet3",
}


MANAGER_INITIAL_CONFIG = build_manager_initial_config(
    system_ip=MANAGER_DEVICE["system_ip"],
    site_id=MANAGER_DEVICE["site_id"],
    route_gw=MANAGER_DEVICE["route_gw"],
    interface_name=MANAGER_DEVICE["interface_name"],
    interface_ip=MANAGER_DEVICE["interface_ip"],
    interface_desc=MANAGER_DEVICE["interface_desc"],
)

VALIDATOR_INITIAL_CONFIG = build_validator_initial_config(
    system_ip=VALIDATOR_DEVICE["system_ip"],
    site_id=VALIDATOR_DEVICE["site_id"],
    route_gw=VALIDATOR_DEVICE["route_gw"],
    interface_name=VALIDATOR_DEVICE["interface_name"],
    interface_ip=VALIDATOR_DEVICE["interface_ip"],
    interface_desc=VALIDATOR_DEVICE["interface_desc"],
)

CONTROLLER_INITIAL_CONFIG = build_controller_initial_config(
    system_ip=CONTROLLER_DEVICE["system_ip"],
    site_id=CONTROLLER_DEVICE["site_id"],
    route_gw=CONTROLLER_DEVICE["route_gw"],
    interface_name=CONTROLLER_DEVICE["interface_name"],
    interface_ip=CONTROLLER_DEVICE["interface_ip"],
    interface_desc=CONTROLLER_DEVICE["interface_desc"],
)

EDGE1_INITIAL_CONFIG = build_edge_initial_config(
    name="edge1",
    system_ip=EDGE1_DEVICE["system_ip"],
    site_id=EDGE1_DEVICE["site_id"],
    inet_ip=EDGE1_DEVICE["inet_ip"],
    inet_mask=EDGE1_DEVICE["inet_mask"],
    inet_gw=EDGE1_DEVICE["inet_gw"],
    inet_desc=EDGE1_DEVICE["inet_desc"],
    inet_interface=EDGE1_DEVICE["inet_interface"],
    mpls_ip=EDGE1_DEVICE["mpls_ip"],
    mpls_mask=EDGE1_DEVICE["mpls_mask"],
    mpls_gw=EDGE1_DEVICE["mpls_gw"],
    mpls_desc=EDGE1_DEVICE["mpls_desc"],
    mpls_interface=EDGE1_DEVICE["mpls_interface"],
)

EDGE2_INITIAL_CONFIG = build_edge_initial_config(
    name="edge2",
    system_ip=EDGE2_DEVICE["system_ip"],
    site_id=EDGE2_DEVICE["site_id"],
    inet_ip=EDGE2_DEVICE["inet_ip"],
    inet_mask=EDGE2_DEVICE["inet_mask"],
    inet_gw=EDGE2_DEVICE["inet_gw"],
    inet_desc=EDGE2_DEVICE["inet_desc"],
    inet_interface=EDGE2_DEVICE["inet_interface"],
    mpls_ip=EDGE2_DEVICE["mpls_ip"],
    mpls_mask=EDGE2_DEVICE["mpls_mask"],
    mpls_gw=EDGE2_DEVICE["mpls_gw"],
    mpls_desc=EDGE2_DEVICE["mpls_desc"],
    mpls_interface=EDGE2_DEVICE["mpls_interface"],
)

EDGE3_INITIAL_CONFIG = build_edge_initial_config(
    name="edge3",
    system_ip=EDGE3_DEVICE["system_ip"],
    site_id=EDGE3_DEVICE["site_id"],
    inet_ip=EDGE3_DEVICE["inet_ip"],
    inet_mask=EDGE3_DEVICE["inet_mask"],
    inet_gw=EDGE3_DEVICE["inet_gw"],
    inet_desc=EDGE3_DEVICE["inet_desc"],
    inet_interface=EDGE3_DEVICE["inet_interface"],
    mpls_ip=EDGE3_DEVICE["mpls_ip"],
    mpls_mask=EDGE3_DEVICE["mpls_mask"],
    mpls_gw=EDGE3_DEVICE["mpls_gw"],
    mpls_desc=EDGE3_DEVICE["mpls_desc"],
    mpls_interface=EDGE3_DEVICE["mpls_interface"],
)

# =============================================================================
# Configuration Instances
# =============================================================================
manager = ManagerConfig(
    mgmt_ip=MANAGER_DEVICE["mgmt_ip"],
    initial_config=MANAGER_INITIAL_CONFIG,
)

controller = ControllerConfig(
    mgmt_ip=CONTROLLER_DEVICE["mgmt_ip"],
    initial_config=CONTROLLER_INITIAL_CONFIG,
)

validator = ValidatorConfig(
    mgmt_ip=VALIDATOR_DEVICE["mgmt_ip"],
    initial_config=VALIDATOR_INITIAL_CONFIG,
)

edge1 = EdgeConfig(
    mgmt_ip=EDGE1_DEVICE["mgmt_ip"],
    initial_config=EDGE1_INITIAL_CONFIG,
)

edge2 = EdgeConfig(
    mgmt_ip=EDGE2_DEVICE["mgmt_ip"],
    initial_config=EDGE2_INITIAL_CONFIG,
)

edge3 = EdgeConfig(
    mgmt_ip=EDGE3_DEVICE["mgmt_ip"],
    initial_config=EDGE3_INITIAL_CONFIG,
)
