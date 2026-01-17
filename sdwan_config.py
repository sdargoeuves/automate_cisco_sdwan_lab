from dataclasses import dataclass


# =============================================================================
# Shared Configuration Values
# =============================================================================
ORG: str = "ipf-netlab"
USERNAME: str = "admin"
PASSWORD: str = "admin@123"
PORT: str = "443"

# Netmiko session log
NETMIKO_SESSION_LOG: str = "logs/netmiko_session.log"

# Certificate files (same across all devices)
RSA_KEY: str = "SDWAN.key"
ROOT_CERT: str = "SDWAN.pem"
SIGNED_CERT: str = "NewCertificate.crt"

# Network
VALIDATOR_IP: str = "10.1.0.6"  # Validator/vBond's IP
CONTROLLER_IP: str = "10.1.0.10"  # Controller/vSmart's IP

# =============================================================================
# Device-Specific Configuration
# =============================================================================
@dataclass(frozen=True)
class ManagerConfig:
    ip: str
    port: str = PORT
    username: str = USERNAME
    password: str = PASSWORD
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
    port: str = PORT
    username: str = USERNAME
    password: str = PASSWORD
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
    port: str = PORT
    username: str = USERNAME
    password: str = PASSWORD
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
MANAGER_INITIAL_CONFIG = """
system
aaa
user admin
password admin@123
site-id 255
organization-name ipf-netlab
system-ip 10.194.58.14
vbond 10.1.0.6
vpn 0
ip route 0.0.0.0/0 10.1.0.1
interface eth1
ip address 10.1.0.2/30
description "sdwan-manager to inet0"
no shut
tunnel-interface
allow-service all
"""

VALIDATOR_INITIAL_CONFIG = """
system
aaa
user admin
password admin@123
site-id 255
organization-name ipf-netlab
system-ip 10.194.58.16
vbond 10.1.0.6 local
vpn 0
ip route 0.0.0.0/0 10.1.0.5
interface ge0/0
ip address 10.1.0.6/30
description "sdwan-validator to inet0"
no shut
no tunnel-interface
commit
tunnel-interface
encapsulation ipsec
allow-service all
"""

CONTROLLER_INITIAL_CONFIG = """
system
aaa
user admin
password admin@123
site-id 255
organization-name ipf-netlab
system-ip 10.194.58.15
vbond 10.1.0.6
vpn 0
ip route 0.0.0.0/0 10.1.0.9
interface eth1
ip address 10.1.0.10/30
description "sdwan-controller to inet0"
no shut
tunnel-interface
allow-service all
"""


# =============================================================================
# Configuration Instances
# =============================================================================
manager = ManagerConfig(
    ip="10.194.58.14",
    initial_config=MANAGER_INITIAL_CONFIG,
)

validator = ValidatorConfig(
    ip="10.194.58.16",
    initial_config=VALIDATOR_INITIAL_CONFIG,
)

controller = ControllerConfig(
    ip="10.194.58.15",
    initial_config=CONTROLLER_INITIAL_CONFIG,
)
