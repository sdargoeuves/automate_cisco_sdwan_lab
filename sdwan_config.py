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
    csr_file_timeout_minutes: int = 1
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
    csr_file_timeout_minutes: int = 1
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
    csr_file_timeout_minutes: int = 1
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
    csr_file_timeout_minutes: int = 1
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

EDGE1_INITIAL_CONFIG = f"""
username admin password {UPDATED_PASSWORD}
ip route 0.0.0.0 0.0.0.0 10.10.0.14
int GigabitEthernet4
ip address 10.10.0.13 255.255.255.252
no shut
exit
commit

system
system-ip 10.194.58.17
site-id 101
organization-name ipf-netlab
vbond 10.10.0.6
exit

interface Tunnel1
ip unnumbered GigabitEthernet4
tunnel source GigabitEthernet4
tunnel mode sdwan
exit

sdwan
interface GigabitEthernet4
tunnel-interface
encapsulation ipsec
allow-service all
color public-internet
exit
commit
"""

EDGE2_INITIAL_CONFIG = f"""
username admin password {UPDATED_PASSWORD}
ip route 0.0.0.0 0.0.0.0 10.10.0.18
int GigabitEthernet4
ip address 10.10.0.17 255.255.255.252
no shut
exit
commit

system
system-ip 10.194.58.18
site-id 102
organization-name ipf-netlab
vbond 10.10.0.6
exit

interface Tunnel1
ip unnumbered GigabitEthernet4
tunnel source GigabitEthernet4
tunnel mode sdwan
exit

sdwan
interface GigabitEthernet4
tunnel-interface
encapsulation ipsec
allow-service all
color public-internet
exit
commit
"""

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
