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
    ip: str
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
    ip: str
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
    ip: str
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
    ip: str
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
MANAGER_INITIAL_CONFIG = f"""
system
aaa
user admin
password {UPDATED_PASSWORD}
site-id 255
organization-name ipf-netlab
system-ip 10.194.58.14
vbond 10.10.0.6
vpn 0
ip route 0.0.0.0/0 10.10.0.1
interface eth1
ip address 10.10.0.2/30
description "sdwan-manager to inet0"
no shut
tunnel-interface
allow-service all
"""

VALIDATOR_INITIAL_CONFIG = f"""
system
aaa
user admin
password {UPDATED_PASSWORD}
site-id 255
organization-name ipf-netlab
system-ip 10.194.58.16
vbond 10.10.0.6 local
vpn 0
ip route 0.0.0.0/0 10.10.0.5
interface ge0/0
ip address 10.10.0.6/30
description "sdwan-validator to inet0"
no shut
no tunnel-interface
commit
tunnel-interface
encapsulation ipsec
allow-service all
"""

CONTROLLER_INITIAL_CONFIG = f"""
system
aaa
user admin
password {UPDATED_PASSWORD}
site-id 255
organization-name ipf-netlab
system-ip 10.194.58.15
vbond 10.10.0.6
vpn 0
ip route 0.0.0.0/0 10.10.0.9
interface eth1
ip address 10.10.0.10/30
description "sdwan-controller to inet0"
no shut
tunnel-interface
allow-service all
"""

def build_edge_initial_config(
    name: str,
    system_ip: str,
    site_id: int,
    inet_ip: str,
    inet_gw: str,
    inet_desc: str,
    mpls_ip: str,
    mpls_gw: str,
    mpls_desc: str,
) -> str:
    return f"""
no ip domain lookup
username admin password {UPDATED_PASSWORD}

ip route 0.0.0.0 0.0.0.0 {inet_gw}
int GigabitEthernet4
no shutdown
ip address {inet_ip} 255.255.255.252
description "{inet_desc}"
exit

!!! this default route will currently break theh automation
!ip route 0.0.0.0 0.0.0.0 {mpls_gw}
!!! DO NOT USE YET
int GigabitEthernet3
no shutdown
ip address {mpls_ip} 255.255.255.252
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
ip unnumbered GigabitEthernet4
tunnel source GigabitEthernet4
tunnel mode sdwan
exit
interface Tunnel2
ip unnumbered GigabitEthernet3
tunnel source GigabitEthernet3
tunnel mode sdwan
exit

sdwan
interface GigabitEthernet4
no shutdown
tunnel-interface
encapsulation ipsec
allow-service all
color public-internet
exit
commit
interface GigabitEthernet3
no shutdown
tunnel-interface
encapsulation ipsec
allow-service all
color mpls
exit
commit
"""


EDGE1_INITIAL_CONFIG = build_edge_initial_config(
    name="edge1",
    system_ip="10.194.58.17",
    site_id=101,
    inet_ip="10.10.0.13",
    inet_gw="10.10.0.14",
    inet_desc="edge1 to inet0",
    mpls_ip="10.1.0.5",
    mpls_gw="10.1.0.6",
    mpls_desc="edge1 to pe1",
)

EDGE2_INITIAL_CONFIG = build_edge_initial_config(
    name="edge2",
    system_ip="10.194.58.18",
    site_id=102,
    inet_ip="10.10.0.17",
    inet_gw="10.10.0.18",
    inet_desc="edge2 to inet0",
    mpls_ip="10.1.0.17",
    mpls_gw="10.1.0.18",
    mpls_desc="edge2 to pe2",
)

EDGE3_INITIAL_CONFIG = build_edge_initial_config(
    name="edge3",
    system_ip="10.194.58.19",
    site_id=103,
    inet_ip="10.10.0.21",
    inet_gw="10.10.0.22",
    inet_desc="edge3 to inet0",
    mpls_ip="10.1.0.29",
    mpls_gw="10.1.0.30",
    mpls_desc="edge3 to pe3",
)

# =============================================================================
# Configuration Instances
# =============================================================================
manager = ManagerConfig(
    ip="10.194.58.14",
    initial_config=MANAGER_INITIAL_CONFIG,
)

controller = ControllerConfig(
    ip="10.194.58.15",
    initial_config=CONTROLLER_INITIAL_CONFIG,
)

validator = ValidatorConfig(
    ip="10.194.58.16",
    initial_config=VALIDATOR_INITIAL_CONFIG,
)

edge1 = EdgeConfig(
    ip="10.194.58.17",
    initial_config=EDGE1_INITIAL_CONFIG,
)

edge2 = EdgeConfig(
    ip="10.194.58.18",
    initial_config=EDGE2_INITIAL_CONFIG,
)

edge3 = EdgeConfig(
    ip="10.194.58.19",
    initial_config=EDGE3_INITIAL_CONFIG,
)
