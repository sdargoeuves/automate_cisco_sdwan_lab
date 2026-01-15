from dataclasses import dataclass


@dataclass(frozen=True)
class ManagerConfig:
    ip: str
    port: str
    username: str
    password: str
    org: str
    validator_ip: str
    country: str
    state: str
    city: str
    rsa_key: str
    root_cert: str
    signed_cert: str
    csr_file: str
    api_ready_timeout_minutes: int
    csr_file_timeout_minutes: int
    initial_config: str


@dataclass(frozen=True)
class ValidatorConfig:
    ip: str
    port: str
    username: str
    password: str
    org: str
    initial_config: str


@dataclass(frozen=True)
class ControllerConfig:
    ip: str
    port: str
    username: str
    password: str
    org: str
    initial_config: str


@dataclass(frozen=True)
class SDWANConfig:
    manager: ManagerConfig
    validator: ValidatorConfig
    controller: ControllerConfig


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

CONTROLLER_INITIAL_CONFIG = ""


CONFIG = SDWANConfig(
    manager=ManagerConfig(
        ip="10.194.58.14",
        port="443",
        username="admin",
        password="admin@123",
        org="ipf-netlab",
        validator_ip="10.1.0.6",
        country="FI",
        state="Finland",
        city="Helsinki",
        rsa_key="SDWAN.key",
        root_cert="SDWAN.pem",
        signed_cert="NewCertificate.crt",
        csr_file="vmanage_csr",
        api_ready_timeout_minutes=15,
        csr_file_timeout_minutes=1,
        initial_config=MANAGER_INITIAL_CONFIG,
    ),
    validator=ValidatorConfig(
        ip="10.194.58.16",
        port="443",
        username="admin",
        password="admin@123",
        org="ipf-netlab",
        initial_config=VALIDATOR_INITIAL_CONFIG,
    ),
    controller=ControllerConfig(
        ip="10.194.58.15",
        port="443",
        username="admin",
        password="admin@123",
        org="ipf-netlab",
        initial_config=CONTROLLER_INITIAL_CONFIG,
    ),
)
