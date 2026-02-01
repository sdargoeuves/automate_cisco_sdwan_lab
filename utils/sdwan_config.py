from dataclasses import dataclass
from pathlib import Path

import yaml

# =============================================================================
# Shared Configuration Values
# =============================================================================
_VARIABLES_PATH = Path(__file__).resolve().parent.parent / "sdwan_variables.yml"


def _load_variables() -> dict:
    try:
        with _VARIABLES_PATH.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Missing variables file: {_VARIABLES_PATH}") from exc


_VARS = _load_variables()
_SHARED = _VARS.get("shared", {})
_TIMING = _VARS.get("timing", {})
_CERTS = _VARS.get("certificates", {})
_DEVICES = _VARS.get("devices", {})


def _require_device(name: str) -> dict:
    device = _DEVICES.get(name)
    if device is None:
        raise KeyError(f"Missing device '{name}' in {_VARIABLES_PATH}")
    return device


def _require_value(device: dict, key: str, name: str):
    if key not in device:
        raise KeyError(f"Missing '{key}' for '{name}' in {_VARIABLES_PATH}")
    return device[key]


def _optional_value(device: dict, key: str, default):
    return device.get(key, default)

ORG: str = _SHARED.get("org", "ipf-netlab")
USERNAME: str = _SHARED.get("username", "admin")
DEFAULT_PASSWORD: str = _SHARED.get("default_password", "admin")
UPDATED_PASSWORD: str = _SHARED.get("updated_password", "admin@123")
PORT: str = str(_SHARED.get("port", "443"))
WAIT_BEFORE_AUTOMATING_CONTROLLER: int = int(
    _TIMING.get("wait_before_automating_controller", 120)
)
WAIT_BEFORE_AUTOMATING_VALIDATOR: int = int(
    _TIMING.get("wait_before_automating_validator", 60)
)
WAIT_CSR_GENERATION: int = int(_TIMING.get("wait_csr_generation", 30))
WAIT_BEFORE_ACTIVATING_EDGE: int = int(
    _TIMING.get("wait_before_activating_edge", 60)
)
WAIT_AFTER_GENERATING_PAYG_LICENSE: int = int(
    _TIMING.get("wait_after_generating_payg_license", 30)
)
EDGE_CERT_POLL_INTERVAL_SECONDS: int = int(
    _TIMING.get("edge_cert_poll_interval_seconds", 10)
)
EDGE_CERT_POLL_TIMEOUT_SECONDS: int = int(
    _TIMING.get("edge_cert_poll_timeout_seconds", 180)
)
NETMIKO_INCREASED_READ_TIMEOUT: int = int(
    _TIMING.get("netmiko_increased_read_timeout", 30)
)
CSR_FILE_TIMEOUT_SECONDS: int = int(_TIMING.get("csr_file_timeout_seconds", 60))
NETMIKO_CONFIG_RETRY_ATTEMPTS: int = int(
    _TIMING.get("netmiko_config_retry_attempts", 2)
)
NETMIKO_CONFIG_RETRY_WAIT_SECONDS: int = int(
    _TIMING.get("netmiko_config_retry_wait_seconds", 10)
)
NETMIKO_COMMIT_READ_TIMEOUT: int = int(
    _TIMING.get("netmiko_commit_read_timeout", 120)
)
NETMIKO_COMMIT_RETRY_ATTEMPTS: int = int(
    _TIMING.get("netmiko_commit_retry_attempts", 2)
)
NETMIKO_COMMIT_RETRY_WAIT_SECONDS: int = int(
    _TIMING.get("netmiko_commit_retry_wait_seconds", 30)
)

# Certificate files (same across all devices)
RSA_KEY: str = _CERTS.get("rsa_key", "SDWAN.key")
ROOT_CERT: str = _CERTS.get("root_cert", "SDWAN.pem")
SIGNED_CERT: str = _CERTS.get("signed_cert", "NewCertificate.crt")

# Network (derived from device interface IPs)
VALIDATOR_IP: str = _require_value(
    _require_device("validator"), "interface_ip", "validator"
)
CONTROLLER_IP: str = _require_value(
    _require_device("controller"), "interface_ip", "controller"
)


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
    interface_prefix: int,
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
ip address {interface_ip}/{interface_prefix}
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
    interface_prefix: int,
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
ip address {interface_ip}/{interface_prefix}
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
    interface_prefix: int,
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
ip address {interface_ip}/{interface_prefix}
description "{interface_desc}"
no shut
tunnel-interface
allow-service all
"""


def build_edge_initial_config(
    name: str,
    system_ip: str,
    site_id: int,
    vrf_id: int,
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

interface Tunnel2
 ip unnumbered {mpls_interface}
 tunnel source {mpls_interface}
 tunnel mode sdwan
exit


vrf definition {vrf_id}
 rd 1:{vrf_id}
 address-family ipv4
  route-target export 1:{vrf_id}
  route-target import 1:{vrf_id}
 exit-address-family
!
 address-family ipv6
 exit-address-family
!

sdwan
interface {inet_interface}
 tunnel-interface
  encapsulation ipsec
  allow-service all
  color public-internet
 exit
interface {mpls_interface}
 tunnel-interface
  encapsulation ipsec
  allow-service all
  color mpls restrict
  max-control-connections 0
 exit
exit
omp
 address-family ipv4
  advertise bgp
  advertise connected
  advertise ospf external
  advertise static
exit
commit
"""


def build_edge_extra_routing_config(
    name: str,
    system_ip: str,
    vrf_id: int,
    ospf_instance: int,
    ospf_area: str,
    bgp_local_as: int,
    bgp_mpls_as: int,
    bgp_inet_as: int,
    lan_interface: str,
    lan_ip: str,
    lan_mask: str,
    lan_desc: str,
    bgp_neighbor_mpls_ip: str,
    bgp_neighbor_inet_ip: str,
    lan2_interface: str = None,
    lan2_ip: str = None,
    lan2_mask: str = None,
    lan2_desc: str = None,
) -> str:
    second_lan_interface = ""
    if lan2_interface and lan2_ip and lan2_mask and lan2_desc:
        second_lan_interface = f"""

interface {lan2_interface}
 vrf forwarding {vrf_id}
 ip address {lan2_ip} {lan2_mask}
 description "{lan2_desc}"
 ip ospf network point-to-point
 ip ospf {ospf_instance} area {ospf_area}
 no shut

"""

    return f"""

router ospf {ospf_instance} vrf {vrf_id}
 redistribute omp
 router-id {system_ip}

interface {lan_interface}
 vrf forwarding {vrf_id}
 ip address {lan_ip} {lan_mask}
 description "{lan_desc}"
 ip ospf network point-to-point
 ip ospf {ospf_instance} area {ospf_area}
 no shut

router bgp {bgp_local_as}
 bgp log-neighbor-changes
 neighbor {bgp_neighbor_mpls_ip} remote-as {bgp_mpls_as}
 neighbor {bgp_neighbor_mpls_ip} description mpls0
 neighbor {bgp_neighbor_inet_ip} remote-as {bgp_inet_as}
 neighbor {bgp_neighbor_inet_ip} description inet0
 !
 address-family ipv4
  neighbor {bgp_neighbor_mpls_ip} activate
  neighbor {bgp_neighbor_inet_ip} activate
 exit-address-family
!
""" + second_lan_interface


# =============================================================================
# Device Definitions
# =============================================================================
MANAGER_DEVICE = _require_device("manager")
VALIDATOR_DEVICE = _require_device("validator")
CONTROLLER_DEVICE = _require_device("controller")
EDGE_GROUP = _require_device("edges")
EDGE1_DEVICE = EDGE_GROUP.get("edge1") or EDGE_GROUP.get("edge1x01")
EDGE2_DEVICE = EDGE_GROUP.get("edge2") or EDGE_GROUP.get("edge2x01")
EDGE3_DEVICE = EDGE_GROUP.get("edge3") or EDGE_GROUP.get("edge3x01")

if EDGE1_DEVICE is None or EDGE2_DEVICE is None or EDGE3_DEVICE is None:
    raise KeyError(
        f"Missing edge definitions in {_VARIABLES_PATH}. "
        "Expected edge1/edge2/edge3 or edge1x01/edge2x01/edge3x01."
    )


MANAGER_INITIAL_CONFIG = build_manager_initial_config(
    system_ip=_require_value(MANAGER_DEVICE, "system_ip", "manager"),
    site_id=_require_value(MANAGER_DEVICE, "site_id", "manager"),
    route_gw=_require_value(MANAGER_DEVICE, "route_gw", "manager"),
    interface_name=_require_value(MANAGER_DEVICE, "interface_name", "manager"),
    interface_ip=_require_value(MANAGER_DEVICE, "interface_ip", "manager"),
    interface_prefix=_require_value(MANAGER_DEVICE, "interface_prefix", "manager"),
    interface_desc=_require_value(MANAGER_DEVICE, "interface_desc", "manager"),
)

VALIDATOR_INITIAL_CONFIG = build_validator_initial_config(
    system_ip=_require_value(VALIDATOR_DEVICE, "system_ip", "validator"),
    site_id=_require_value(VALIDATOR_DEVICE, "site_id", "validator"),
    route_gw=_require_value(VALIDATOR_DEVICE, "route_gw", "validator"),
    interface_name=_require_value(VALIDATOR_DEVICE, "interface_name", "validator"),
    interface_ip=_require_value(VALIDATOR_DEVICE, "interface_ip", "validator"),
    interface_prefix=_require_value(VALIDATOR_DEVICE, "interface_prefix", "validator"),
    interface_desc=_require_value(VALIDATOR_DEVICE, "interface_desc", "validator"),
)

CONTROLLER_INITIAL_CONFIG = build_controller_initial_config(
    system_ip=_require_value(CONTROLLER_DEVICE, "system_ip", "controller"),
    site_id=_require_value(CONTROLLER_DEVICE, "site_id", "controller"),
    route_gw=_require_value(CONTROLLER_DEVICE, "route_gw", "controller"),
    interface_name=_require_value(CONTROLLER_DEVICE, "interface_name", "controller"),
    interface_ip=_require_value(CONTROLLER_DEVICE, "interface_ip", "controller"),
    interface_prefix=_require_value(CONTROLLER_DEVICE, "interface_prefix", "controller"),
    interface_desc=_require_value(CONTROLLER_DEVICE, "interface_desc", "controller"),
)

EDGE1_INITIAL_CONFIG = build_edge_initial_config(
    name="edge1",
    system_ip=_require_value(EDGE1_DEVICE, "system_ip", "edge1"),
    site_id=_require_value(EDGE1_DEVICE, "site_id", "edge1"),
    vrf_id=_require_value(EDGE1_DEVICE, "vrf_id", "edge1"),
    inet_ip=_require_value(EDGE1_DEVICE, "inet_ip", "edge1"),
    inet_mask=_require_value(EDGE1_DEVICE, "inet_mask", "edge1"),
    inet_gw=_require_value(EDGE1_DEVICE, "inet_gw", "edge1"),
    inet_desc=_require_value(EDGE1_DEVICE, "inet_desc", "edge1"),
    inet_interface=_require_value(EDGE1_DEVICE, "inet_interface", "edge1"),
    mpls_ip=_require_value(EDGE1_DEVICE, "mpls_ip", "edge1"),
    mpls_mask=_require_value(EDGE1_DEVICE, "mpls_mask", "edge1"),
    mpls_gw=_require_value(EDGE1_DEVICE, "mpls_gw", "edge1"),
    mpls_desc=_require_value(EDGE1_DEVICE, "mpls_desc", "edge1"),
    mpls_interface=_require_value(EDGE1_DEVICE, "mpls_interface", "edge1"),
)

EDGE2_INITIAL_CONFIG = build_edge_initial_config(
    name="edge2",
    system_ip=_require_value(EDGE2_DEVICE, "system_ip", "edge2"),
    site_id=_require_value(EDGE2_DEVICE, "site_id", "edge2"),
    vrf_id=_require_value(EDGE2_DEVICE, "vrf_id", "edge2"),
    inet_ip=_require_value(EDGE2_DEVICE, "inet_ip", "edge2"),
    inet_mask=_require_value(EDGE2_DEVICE, "inet_mask", "edge2"),
    inet_gw=_require_value(EDGE2_DEVICE, "inet_gw", "edge2"),
    inet_desc=_require_value(EDGE2_DEVICE, "inet_desc", "edge2"),
    inet_interface=_require_value(EDGE2_DEVICE, "inet_interface", "edge2"),
    mpls_ip=_require_value(EDGE2_DEVICE, "mpls_ip", "edge2"),
    mpls_mask=_require_value(EDGE2_DEVICE, "mpls_mask", "edge2"),
    mpls_gw=_require_value(EDGE2_DEVICE, "mpls_gw", "edge2"),
    mpls_desc=_require_value(EDGE2_DEVICE, "mpls_desc", "edge2"),
    mpls_interface=_require_value(EDGE2_DEVICE, "mpls_interface", "edge2")
)

EDGE3_INITIAL_CONFIG = build_edge_initial_config(
    name="edge3",
    system_ip=_require_value(EDGE3_DEVICE, "system_ip", "edge3"), 
    site_id=_require_value(EDGE3_DEVICE, "site_id", "edge3"),
    vrf_id=_require_value(EDGE3_DEVICE, "vrf_id", "edge3"),
    inet_ip=_require_value(EDGE3_DEVICE, "inet_ip", "edge3"),
    inet_mask=_require_value(EDGE3_DEVICE, "inet_mask", "edge3"),
    inet_gw=_require_value(EDGE3_DEVICE, "inet_gw", "edge3"),
    inet_desc=_require_value(EDGE3_DEVICE, "inet_desc", "edge3"),
    inet_interface=_require_value(EDGE3_DEVICE, "inet_interface", "edge3"),
    mpls_ip=_require_value(EDGE3_DEVICE, "mpls_ip", "edge3"),
    mpls_mask=_require_value(EDGE3_DEVICE, "mpls_mask", "edge3"),
    mpls_gw=_require_value(EDGE3_DEVICE, "mpls_gw", "edge3"),
    mpls_desc=_require_value(EDGE3_DEVICE, "mpls_desc", "edge3"),
    mpls_interface=_require_value(EDGE3_DEVICE, "mpls_interface", "edge3")
)

EDGE1_EXTRA_ROUTING_CONFIG = build_edge_extra_routing_config(
    name="edge1",
    system_ip=_require_value(EDGE1_DEVICE, "system_ip", "edge1"),
    vrf_id=_require_value(EDGE1_DEVICE, "vrf_id", "edge1"),
    ospf_instance=_require_value(EDGE1_DEVICE, "ospf_instance", "edge1"),
    ospf_area=_require_value(EDGE1_DEVICE, "ospf_area", "edge1"),
    bgp_local_as=_require_value(EDGE1_DEVICE, "bgp_local_as", "edge1"),
    bgp_mpls_as=_require_value(EDGE1_DEVICE, "bgp_mpls_as", "edge1"),
    bgp_inet_as=_require_value(EDGE1_DEVICE, "bgp_inet_as", "edge1"),
    lan_interface=_require_value(EDGE1_DEVICE, "lan_interface", "edge1"),
    lan_ip=_require_value(EDGE1_DEVICE, "lan_ip", "edge1"),
    lan_mask=_require_value(EDGE1_DEVICE, "lan_mask", "edge1"),
    lan_desc=_require_value(EDGE1_DEVICE, "lan_desc", "edge1"),
    lan2_interface=_optional_value(EDGE1_DEVICE, "lan2_interface", "edge1"),
    lan2_ip=_optional_value(EDGE1_DEVICE, "lan2_ip", "edge1"),
    lan2_mask=_optional_value(EDGE1_DEVICE, "lan2_mask", "edge1"),
    lan2_desc=_optional_value(EDGE1_DEVICE, "lan2_desc", "edge1"),
    bgp_neighbor_mpls_ip=_require_value(EDGE1_DEVICE, "bgp_neighbor_mpls_ip", "edge1"),
    bgp_neighbor_inet_ip=_require_value(EDGE1_DEVICE, "bgp_neighbor_inet_ip", "edge1"),
)

EDGE2_EXTRA_ROUTING_CONFIG = build_edge_extra_routing_config(
    name="edge2",
    system_ip=_require_value(EDGE2_DEVICE, "system_ip", "edge2"),
    vrf_id=_require_value(EDGE2_DEVICE, "vrf_id", "edge2"),
    ospf_instance=_require_value(EDGE2_DEVICE, "ospf_instance", "edge2"),
    ospf_area=_require_value(EDGE2_DEVICE, "ospf_area", "edge2"),
    bgp_local_as=_require_value(EDGE2_DEVICE, "bgp_local_as", "edge2"),
    bgp_mpls_as=_require_value(EDGE2_DEVICE, "bgp_mpls_as", "edge2"),
    bgp_inet_as=_require_value(EDGE2_DEVICE, "bgp_inet_as", "edge2"),
    lan_interface=_require_value(EDGE2_DEVICE, "lan_interface", "edge2"),
    lan_ip=_require_value(EDGE2_DEVICE, "lan_ip", "edge2"),
    lan_mask=_require_value(EDGE2_DEVICE, "lan_mask", "edge2"),
    lan_desc=_require_value(EDGE2_DEVICE, "lan_desc", "edge2"),
    lan2_interface=_optional_value(EDGE2_DEVICE, "lan2_interface", "edge2"),
    lan2_ip=_optional_value(EDGE2_DEVICE, "lan2_ip", "edge2"),
    lan2_mask=_optional_value(EDGE2_DEVICE, "lan2_mask", "edge2"),
    lan2_desc=_optional_value(EDGE2_DEVICE, "lan2_desc", "edge2"),
    bgp_neighbor_mpls_ip=_require_value(EDGE2_DEVICE, "bgp_neighbor_mpls_ip", "edge2"),
    bgp_neighbor_inet_ip=_require_value(EDGE2_DEVICE, "bgp_neighbor_inet_ip", "edge2"),
)

EDGE3_EXTRA_ROUTING_CONFIG = build_edge_extra_routing_config(
    name="edge3",
    system_ip=_require_value(EDGE3_DEVICE, "system_ip", "edge3"),
    vrf_id=_require_value(EDGE3_DEVICE, "vrf_id", "edge3"),
    ospf_instance=_require_value(EDGE3_DEVICE, "ospf_instance", "edge3"),
    ospf_area=_require_value(EDGE3_DEVICE, "ospf_area", "edge3"),
    bgp_local_as=_require_value(EDGE3_DEVICE, "bgp_local_as", "edge3"),
    bgp_mpls_as=_require_value(EDGE3_DEVICE, "bgp_mpls_as", "edge3"),
    bgp_inet_as=_require_value(EDGE3_DEVICE, "bgp_inet_as", "edge3"),
    lan_interface=_require_value(EDGE3_DEVICE, "lan_interface", "edge3"),
    lan_ip=_require_value(EDGE3_DEVICE, "lan_ip", "edge3"),
    lan_mask=_require_value(EDGE3_DEVICE, "lan_mask", "edge3"),
    lan_desc=_require_value(EDGE3_DEVICE, "lan_desc", "edge3"),
    lan2_interface=_optional_value(EDGE3_DEVICE, "lan2_interface", "edge3"),
    lan2_ip=_optional_value(EDGE3_DEVICE, "lan2_ip", "edge3"),
    lan2_mask=_optional_value(EDGE3_DEVICE, "lan2_mask", "edge3"),
    lan2_desc=_optional_value(EDGE3_DEVICE, "lan2_desc", "edge3"),
    bgp_neighbor_mpls_ip=_require_value(EDGE3_DEVICE, "bgp_neighbor_mpls_ip", "edge3"),
    bgp_neighbor_inet_ip=_require_value(EDGE3_DEVICE, "bgp_neighbor_inet_ip", "edge3"),
)

# =============================================================================
# Configuration Instances
# =============================================================================
manager = ManagerConfig(
    mgmt_ip=_require_value(MANAGER_DEVICE, "mgmt_ip", "manager"),
    country=_optional_value(MANAGER_DEVICE, "country", "FI"),
    state=_optional_value(MANAGER_DEVICE, "state", "Finland"),
    city=_optional_value(MANAGER_DEVICE, "city", "Helsinki"),
    csr_file=_optional_value(MANAGER_DEVICE, "csr_file", "vmanage_csr"),
    api_ready_timeout_minutes=int(
        _optional_value(MANAGER_DEVICE, "api_ready_timeout_minutes", 15)
    ),
    initial_config=MANAGER_INITIAL_CONFIG,
)

controller = ControllerConfig(
    mgmt_ip=_require_value(CONTROLLER_DEVICE, "mgmt_ip", "controller"),
    csr_file=_optional_value(CONTROLLER_DEVICE, "csr_file", "vsmart_csr"),
    initial_config=CONTROLLER_INITIAL_CONFIG,
)

validator = ValidatorConfig(
    mgmt_ip=_require_value(VALIDATOR_DEVICE, "mgmt_ip", "validator"),
    csr_file=_optional_value(VALIDATOR_DEVICE, "csr_file", "vbond_csr"),
    initial_config=VALIDATOR_INITIAL_CONFIG,
)

edge1 = EdgeConfig(
    mgmt_ip=_require_value(EDGE1_DEVICE, "mgmt_ip", "edge1"),
    initial_config=EDGE1_INITIAL_CONFIG,
)

edge2 = EdgeConfig(
    mgmt_ip=_require_value(EDGE2_DEVICE, "mgmt_ip", "edge2"),
    initial_config=EDGE2_INITIAL_CONFIG,
)

edge3 = EdgeConfig(
    mgmt_ip=_require_value(EDGE3_DEVICE, "mgmt_ip", "edge3"),
    initial_config=EDGE3_INITIAL_CONFIG,
)
