from dataclasses import dataclass
from pathlib import Path

import yaml

# =============================================================================
# Shared Configuration Values
# =============================================================================
DEFAULT_VARIABLES_PATH = (
    Path(__file__).resolve().parent.parent / "sdwan_variables.gen.yml"
)

# Module-level state — populated by load()
_VARIABLES_PATH: Path = None
_DEVICES: dict = {}


def _load_variables(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Missing variables file: {path}") from exc


def _require_device(name: str) -> dict:
    device = _DEVICES.get(name)
    if device is None:
        raise KeyError(f"Missing device '{name}' in {_VARIABLES_PATH}")
    device = dict(device)
    device["_name"] = name
    return device


def _require_value(device: dict, key: str, name: str = None):
    if key not in device:
        device_name = name or device.get("_name") or "device"
        raise KeyError(f"Missing '{key}' for '{device_name}' in {_VARIABLES_PATH}")
    return device[key]


def _optional_value(device: dict, key: str, default):
    return device.get(key, default)


# Module-level variables — populated by load()
ORG: str = None
USERNAME: str = None
DEFAULT_PASSWORD: str = None
UPDATED_PASSWORD: str = None
PORT: str = None
WAIT_BEFORE_AUTOMATING_CONTROLLER_SECONDS: int = None
WAIT_BEFORE_AUTOMATING_VALIDATOR_SECONDS: int = None
WAIT_CSR_GENERATION_SECONDS: int = None
WAIT_BEFORE_ACTIVATING_EDGE_SECONDS: int = None
WAIT_AFTER_GENERATING_PAYG_LICENSE_SECONDS: int = None
EDGE_CERT_POLL_INTERVAL_SECONDS: int = None
EDGE_CERT_POLL_TIMEOUT_SECONDS: int = None
NETMIKO_INCREASED_READ_TIMEOUT_SECONDS: int = None
CSR_FILE_TIMEOUT_SECONDS: int = None
NETMIKO_CONFIG_RETRY_ATTEMPTS: int = None
NETMIKO_CONFIG_RETRY_WAIT_SECONDS: int = None
NETMIKO_COMMIT_READ_TIMEOUT_SECONDS: int = None
NETMIKO_COMMIT_RETRY_ATTEMPTS: int = None
NETMIKO_COMMIT_RETRY_WAIT_SECONDS: int = None
NETMIKO_CONNECT_RETRY_WAIT_SECONDS: int = None
NETMIKO_CONNECT_RETRY_MAX_SECONDS: int = None
NETMIKO_CONNECT_LOCKOUT_RETRY_INTERVAL_SECONDS: int = None
CSR_GENERATION_MAX_ATTEMPTS: int = None
CSR_GENERATION_RETRY_WAIT_SECONDS: int = None
CSR_FILE_POLL_INTERVAL_SECONDS: int = None
EDGE_STAGGER_SECONDS: float = None
RSA_KEY: str = None
ROOT_CERT: str = None
SIGNED_CERT: str = None
VALIDATOR_IP: str = None
CONTROLLER_IP: str = None
MANAGER_DEVICE: dict = None
VALIDATOR_DEVICE: dict = None
CONTROLLER_DEVICE: dict = None
EDGE_GROUP: dict = None
EDGE_DEVICES: dict = None
EDGE_NAMES: tuple = None
MANAGER_INITIAL_CONFIG: str = None
VALIDATOR_INITIAL_CONFIG: str = None
CONTROLLER_INITIAL_CONFIG: str = None
EDGE_INITIAL_CONFIGS: dict = None
EDGE_EXTRA_ROUTING_CONFIGS: dict = None
manager = None
controller = None
validator = None
EDGES: dict = None


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
    bgp_local_as: int,
    bgp_mpls_as: int,
    bgp_inet_as: int,
    lan_interfaces: list,
    mpls_gw: str,
    inet_gw: str,
) -> str:
    lan_blocks = ""
    for lan in lan_interfaces:
        lan_blocks += f"""
interface {lan["lan_interface"]}
 vrf forwarding {vrf_id}
 ip address {lan["lan_ip"]} {lan["lan_mask"]}
 description "{lan["lan_desc"]}"
 ip ospf network point-to-point
 ip ospf {ospf_instance} area 0.0.0.0
 no shut
"""

    return f"""
router ospf {ospf_instance} vrf {vrf_id}
 redistribute omp
 router-id {system_ip}
{lan_blocks}
router bgp {bgp_local_as}
 bgp log-neighbor-changes
 neighbor {mpls_gw} remote-as {bgp_mpls_as}
 neighbor {mpls_gw} description mpls0
 neighbor {inet_gw} remote-as {bgp_inet_as}
 neighbor {inet_gw} description inet0
 !
 address-family ipv4
  neighbor {mpls_gw} activate
  neighbor {inet_gw} activate
 exit-address-family
!
"""


# =============================================================================
# Load function — call this once at startup before using any settings
# =============================================================================
def load(variables_path=None) -> None:
    """Load (or reload) all settings from the variables YAML file.

    Args:
        variables_path: Path to the YAML file. Defaults to
            ``sdwan_variables.gen.yml`` next to the project root.
    """
    global _VARIABLES_PATH, _DEVICES
    global ORG, USERNAME, DEFAULT_PASSWORD, UPDATED_PASSWORD, PORT
    global \
        WAIT_BEFORE_AUTOMATING_CONTROLLER_SECONDS, \
        WAIT_BEFORE_AUTOMATING_VALIDATOR_SECONDS
    global WAIT_CSR_GENERATION_SECONDS, WAIT_BEFORE_ACTIVATING_EDGE_SECONDS
    global WAIT_AFTER_GENERATING_PAYG_LICENSE_SECONDS, EDGE_CERT_POLL_INTERVAL_SECONDS
    global EDGE_CERT_POLL_TIMEOUT_SECONDS, NETMIKO_INCREASED_READ_TIMEOUT_SECONDS
    global CSR_FILE_TIMEOUT_SECONDS, NETMIKO_CONFIG_RETRY_ATTEMPTS
    global NETMIKO_CONFIG_RETRY_WAIT_SECONDS, NETMIKO_COMMIT_READ_TIMEOUT_SECONDS
    global NETMIKO_COMMIT_RETRY_ATTEMPTS, NETMIKO_COMMIT_RETRY_WAIT_SECONDS
    global NETMIKO_CONNECT_RETRY_WAIT_SECONDS, NETMIKO_CONNECT_RETRY_MAX_SECONDS
    global NETMIKO_CONNECT_LOCKOUT_RETRY_INTERVAL_SECONDS
    global CSR_GENERATION_MAX_ATTEMPTS, CSR_GENERATION_RETRY_WAIT_SECONDS
    global CSR_FILE_POLL_INTERVAL_SECONDS, EDGE_STAGGER_SECONDS
    global RSA_KEY, ROOT_CERT, SIGNED_CERT, VALIDATOR_IP, CONTROLLER_IP
    global MANAGER_DEVICE, VALIDATOR_DEVICE, CONTROLLER_DEVICE
    global EDGE_GROUP, EDGE_DEVICES, EDGE_NAMES
    global MANAGER_INITIAL_CONFIG, VALIDATOR_INITIAL_CONFIG, CONTROLLER_INITIAL_CONFIG
    global EDGE_INITIAL_CONFIGS, EDGE_EXTRA_ROUTING_CONFIGS
    global manager, controller, validator, EDGES

    _VARIABLES_PATH = (
        Path(variables_path).resolve() if variables_path else DEFAULT_VARIABLES_PATH
    )

    _vars = _load_variables(_VARIABLES_PATH)
    _shared = _vars.get("shared", {})
    _timing = _vars.get("timing", {})
    _certs = _vars.get("certificates", {})
    _DEVICES = _vars.get("devices", {})

    ORG = _shared.get("org", "ipf-netlab")
    USERNAME = _shared.get("username", "admin")
    DEFAULT_PASSWORD = _shared.get("default_password", "admin")
    UPDATED_PASSWORD = _shared.get("updated_password", "admin@123")
    PORT = str(_shared.get("port", "443"))
    WAIT_BEFORE_AUTOMATING_CONTROLLER_SECONDS = int(
        _timing.get("wait_before_automating_controller_seconds", 120)
    )
    WAIT_BEFORE_AUTOMATING_VALIDATOR_SECONDS = int(
        _timing.get("wait_before_automating_validator_seconds", 60)
    )
    WAIT_CSR_GENERATION_SECONDS = int(_timing.get("wait_csr_generation_seconds", 30))
    WAIT_BEFORE_ACTIVATING_EDGE_SECONDS = int(
        _timing.get("wait_before_activating_edge_seconds", 60)
    )
    WAIT_AFTER_GENERATING_PAYG_LICENSE_SECONDS = int(
        _timing.get("wait_after_generating_payg_license_seconds", 30)
    )
    EDGE_CERT_POLL_INTERVAL_SECONDS = int(
        _timing.get("edge_cert_poll_interval_seconds", 10)
    )
    EDGE_CERT_POLL_TIMEOUT_SECONDS = int(
        _timing.get("edge_cert_poll_timeout_seconds", 180)
    )
    NETMIKO_INCREASED_READ_TIMEOUT_SECONDS = int(
        _timing.get("netmiko_increased_read_timeout_seconds", 30)
    )
    CSR_FILE_TIMEOUT_SECONDS = int(_timing.get("csr_file_timeout_seconds", 60))
    NETMIKO_CONFIG_RETRY_ATTEMPTS = int(_timing.get("netmiko_config_retry_attempts", 2))
    NETMIKO_CONFIG_RETRY_WAIT_SECONDS = int(
        _timing.get("netmiko_config_retry_wait_seconds", 10)
    )
    NETMIKO_COMMIT_READ_TIMEOUT_SECONDS = int(
        _timing.get("netmiko_commit_read_timeout_seconds", 120)
    )
    NETMIKO_COMMIT_RETRY_ATTEMPTS = int(_timing.get("netmiko_commit_retry_attempts", 2))
    NETMIKO_COMMIT_RETRY_WAIT_SECONDS = int(
        _timing.get("netmiko_commit_retry_wait_seconds", 30)
    )
    NETMIKO_CONNECT_RETRY_WAIT_SECONDS = int(
        _timing.get("netmiko_connect_retry_wait_seconds", 120)
    )
    NETMIKO_CONNECT_RETRY_MAX_SECONDS = int(
        _timing.get("netmiko_connect_retry_max_seconds", 900)
    )
    NETMIKO_CONNECT_LOCKOUT_RETRY_INTERVAL_SECONDS = int(
        _timing.get("netmiko_connect_lockout_retry_interval_seconds", 180)
    )
    CSR_GENERATION_MAX_ATTEMPTS = int(_timing.get("csr_generation_max_attempts", 3))
    CSR_GENERATION_RETRY_WAIT_SECONDS = int(
        _timing.get("csr_generation_retry_wait_seconds", 5)
    )
    CSR_FILE_POLL_INTERVAL_SECONDS = int(
        _timing.get("csr_file_poll_interval_seconds", 5)
    )
    EDGE_STAGGER_SECONDS = float(_timing.get("edge_stagger_seconds", 2.0))

    RSA_KEY = _certs.get("rsa_key", "SDWAN.key")
    ROOT_CERT = _certs.get("root_cert", "SDWAN.pem")
    SIGNED_CERT = _certs.get("signed_cert", "NewCertificate.crt")

    VALIDATOR_IP = _require_value(_require_device("validator"), "interface_ip")
    CONTROLLER_IP = _require_value(_require_device("controller"), "interface_ip")

    # -------------------------------------------------------------------------
    # Device Definitions
    # -------------------------------------------------------------------------
    MANAGER_DEVICE = _require_device("manager")
    VALIDATOR_DEVICE = _require_device("validator")
    CONTROLLER_DEVICE = _require_device("controller")
    EDGE_GROUP = _require_device("edges")
    EDGE_DEVICES = {}
    for edge_name, edge_device in EDGE_GROUP.items():
        if edge_name == "_name":
            continue
        if not isinstance(edge_device, dict):
            raise TypeError(
                f"Edge '{edge_name}' in {_VARIABLES_PATH} must be a mapping."
            )
        device_copy = dict(edge_device)
        device_copy["_name"] = edge_name
        EDGE_DEVICES[edge_name] = device_copy

    if not EDGE_DEVICES:
        raise KeyError(f"Missing edge definitions in {_VARIABLES_PATH}.")

    EDGE_NAMES = tuple(EDGE_DEVICES.keys())

    MANAGER_INITIAL_CONFIG = build_manager_initial_config(
        system_ip=_require_value(MANAGER_DEVICE, "system_ip"),
        site_id=_require_value(MANAGER_DEVICE, "site_id"),
        route_gw=_require_value(MANAGER_DEVICE, "route_gw"),
        interface_name=_require_value(MANAGER_DEVICE, "interface_name"),
        interface_ip=_require_value(MANAGER_DEVICE, "interface_ip"),
        interface_prefix=_require_value(MANAGER_DEVICE, "interface_prefix"),
        interface_desc=_require_value(MANAGER_DEVICE, "interface_desc"),
    )

    VALIDATOR_INITIAL_CONFIG = build_validator_initial_config(
        system_ip=_require_value(VALIDATOR_DEVICE, "system_ip"),
        site_id=_require_value(VALIDATOR_DEVICE, "site_id"),
        route_gw=_require_value(VALIDATOR_DEVICE, "route_gw"),
        interface_name=_require_value(VALIDATOR_DEVICE, "interface_name"),
        interface_ip=_require_value(VALIDATOR_DEVICE, "interface_ip"),
        interface_prefix=_require_value(VALIDATOR_DEVICE, "interface_prefix"),
        interface_desc=_require_value(VALIDATOR_DEVICE, "interface_desc"),
    )

    CONTROLLER_INITIAL_CONFIG = build_controller_initial_config(
        system_ip=_require_value(CONTROLLER_DEVICE, "system_ip"),
        site_id=_require_value(CONTROLLER_DEVICE, "site_id"),
        route_gw=_require_value(CONTROLLER_DEVICE, "route_gw"),
        interface_name=_require_value(CONTROLLER_DEVICE, "interface_name"),
        interface_ip=_require_value(CONTROLLER_DEVICE, "interface_ip"),
        interface_prefix=_require_value(CONTROLLER_DEVICE, "interface_prefix"),
        interface_desc=_require_value(CONTROLLER_DEVICE, "interface_desc"),
    )

    EDGE_INITIAL_CONFIGS = {}
    EDGE_EXTRA_ROUTING_CONFIGS = {}

    for edge_name, edge_device in EDGE_DEVICES.items():
        EDGE_INITIAL_CONFIGS[edge_name] = build_edge_initial_config(
            name=edge_name,
            system_ip=_require_value(edge_device, "system_ip"),
            site_id=_require_value(edge_device, "site_id"),
            vrf_id=_require_value(edge_device, "vrf_id"),
            inet_ip=_require_value(edge_device, "inet_ip"),
            inet_mask=_require_value(edge_device, "inet_mask"),
            inet_gw=_require_value(edge_device, "inet_gw"),
            inet_desc=_require_value(edge_device, "inet_desc"),
            inet_interface=_require_value(edge_device, "inet_interface"),
            mpls_ip=_require_value(edge_device, "mpls_ip"),
            mpls_mask=_require_value(edge_device, "mpls_mask"),
            mpls_gw=_require_value(edge_device, "mpls_gw"),
            mpls_desc=_require_value(edge_device, "mpls_desc"),
            mpls_interface=_require_value(edge_device, "mpls_interface"),
        )
        EDGE_EXTRA_ROUTING_CONFIGS[edge_name] = build_edge_extra_routing_config(
            name=edge_name,
            system_ip=_require_value(edge_device, "system_ip"),
            vrf_id=_require_value(edge_device, "vrf_id"),
            ospf_instance=_require_value(edge_device, "ospf_instance"),
            bgp_local_as=_require_value(edge_device, "bgp_local_as"),
            bgp_mpls_as=_require_value(edge_device, "bgp_mpls_as"),
            bgp_inet_as=_require_value(edge_device, "bgp_inet_as"),
            lan_interfaces=_require_value(edge_device, "lan_interfaces"),
            mpls_gw=_require_value(edge_device, "mpls_gw"),
            inet_gw=_require_value(edge_device, "inet_gw"),
        )

    # -------------------------------------------------------------------------
    # Configuration Instances
    # -------------------------------------------------------------------------
    manager = ManagerConfig(
        mgmt_ip=_require_value(MANAGER_DEVICE, "mgmt_ip"),
        port=PORT,
        username=USERNAME,
        password=UPDATED_PASSWORD,
        default_password=DEFAULT_PASSWORD,
        org=ORG,
        validator_ip=VALIDATOR_IP,
        country=_optional_value(MANAGER_DEVICE, "country", "FI"),
        state=_optional_value(MANAGER_DEVICE, "state", "Finland"),
        city=_optional_value(MANAGER_DEVICE, "city", "Helsinki"),
        rsa_key=RSA_KEY,
        root_cert=ROOT_CERT,
        signed_cert=SIGNED_CERT,
        csr_file=_optional_value(MANAGER_DEVICE, "csr_file", "vmanage_csr"),
        api_ready_timeout_minutes=int(
            _optional_value(MANAGER_DEVICE, "api_ready_timeout_minutes", 15)
        ),
        initial_config=MANAGER_INITIAL_CONFIG,
    )

    controller = ControllerConfig(
        mgmt_ip=_require_value(CONTROLLER_DEVICE, "mgmt_ip"),
        username=USERNAME,
        password=UPDATED_PASSWORD,
        default_password=DEFAULT_PASSWORD,
        org=ORG,
        validator_ip=VALIDATOR_IP,
        controller_ip=CONTROLLER_IP,
        rsa_key=RSA_KEY,
        root_cert=ROOT_CERT,
        signed_cert=SIGNED_CERT,
        csr_file=_optional_value(CONTROLLER_DEVICE, "csr_file", "vsmart_csr"),
        initial_config=CONTROLLER_INITIAL_CONFIG,
    )

    validator = ValidatorConfig(
        mgmt_ip=_require_value(VALIDATOR_DEVICE, "mgmt_ip"),
        username=USERNAME,
        password=UPDATED_PASSWORD,
        default_password=DEFAULT_PASSWORD,
        org=ORG,
        validator_ip=VALIDATOR_IP,
        rsa_key=RSA_KEY,
        root_cert=ROOT_CERT,
        signed_cert=SIGNED_CERT,
        csr_file=_optional_value(VALIDATOR_DEVICE, "csr_file", "vbond_csr"),
        initial_config=VALIDATOR_INITIAL_CONFIG,
    )

    EDGES = {
        edge_name: EdgeConfig(
            mgmt_ip=_require_value(edge_device, "mgmt_ip"),
            username=USERNAME,
            password=UPDATED_PASSWORD,
            default_password=DEFAULT_PASSWORD,
            org=ORG,
            validator_ip=VALIDATOR_IP,
            controller_ip=CONTROLLER_IP,
            rsa_key=RSA_KEY,
            root_cert=ROOT_CERT,
            signed_cert=SIGNED_CERT,
            initial_config=EDGE_INITIAL_CONFIGS[edge_name],
        )
        for edge_name, edge_device in EDGE_DEVICES.items()
    }
