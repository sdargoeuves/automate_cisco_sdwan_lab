import time

import requests

from sdwan_config import ManagerConfig
from utils.logging import get_logger
from utils.api import api_call, wait_for_api_ready
from utils.netmiko import connect_to_device, push_config_from_file, push_initial_config
from utils.vshell import read_file_vshell, run_vshell_cmd


def run_certificate_automation(net_connect, config: ManagerConfig):
    """
    Run the full certificate automation workflow

    Args:
        net_connect: Active Netmiko connection to Manager
        config: Config object
    """
    print("\n" + "=" * 50)
    print("PART 1: Generate Root Certificate")
    print("=" * 50)

    print("Generating RSA key...")
    run_vshell_cmd(net_connect, f"openssl genrsa -out {config.rsa_key} 2048")

    print("Generating root certificate...")
    subj = f"/C={config.country}/ST={config.state}/L={config.city}/O={config.org}/CN={config.org}"
    run_vshell_cmd(
        net_connect,
        f"openssl req -x509 -new -nodes -key {config.rsa_key} -sha256 -days 2000 "
        f'-subj "{subj}" -out {config.root_cert}',
    )

    root_cert_content = read_file_vshell(net_connect, config.root_cert)
    print("✓ Root certificate created")

    print("\n" + "=" * 50)
    print("PART 2: Configure Manager (vManage)")
    print("=" * 50)

    if not wait_for_api_ready(
        config.ip,
        config.port,
        config.username,
        config.password,
        config.api_ready_timeout_minutes,
    ):
        print("✗ Manager API is not ready. Please check the system and try again.")
        get_logger(__name__).error("Manager API not ready after timeout")
        return False

    session = requests.Session()
    session.verify = False

    session.post(
        f"https://{config.ip}:{config.port}/j_security_check",
        data={"j_username": config.username, "j_password": config.password},
    )

    token = session.get(
        f"https://{config.ip}:{config.port}/dataservice/client/token"
    ).text
    session.headers.update({"X-XSRF-TOKEN": token, "Content-Type": "application/json"})

    print(f"Setting organization: {config.org}")
    api_call(
        session,
        "PUT",
        config.ip,
        config.port,
        "/dataservice/settings/configuration/organization",
        {"org": config.org},
    )

    print(f"Setting validator IP: {config.validator_ip}")
    api_call(
        session,
        "PUT",
        config.ip,
        config.port,
        "/dataservice/settings/configuration/device",
        {"domainIp": config.validator_ip, "port": "12346"},
    )

    print("Change certificate to enterprise root certificate...")
    api_call(
        session,
        "POST",
        config.ip,
        config.port,
        "/dataservice/settings/configuration/certificate",
        {"certificateSigning": "enterprise"},
    )

    print("Uploading enterprise root certificate...")
    api_call(
        session,
        "PUT",
        config.ip,
        config.port,
        "/dataservice/settings/configuration/certificate/enterpriserootca",
        {"enterpriseRootCA": root_cert_content},
    )

    print("Set CSR properties as default")
    api_call(
        session,
        "PUT",
        config.ip,
        config.port,
        "/dataservice/settings/configuration/certificate/csrproperties",
        {"domain_name": ""},
    )

    print("✓ Manager configured")

    print("\n" + "=" * 50)
    print("PART 3: Generate and Sign CSR")
    print("=" * 50)

    print("Generating CSR...")
    csr_generated = False
    max_csr_attempts = 3

    for csr_attempt in range(1, max_csr_attempts + 1):
        csr_response = api_call(
            session,
            "POST",
            config.ip,
            config.port,
            "/dataservice/certificate/generate/csr",
            {"deviceIP": config.ip},
        )
        print(
            f"API Response Status: {csr_response.status_code} "
            f"(attempt {csr_attempt}/{max_csr_attempts})"
        )

        if csr_response.status_code == 200:
            print("✓ CSR generation request successful")
            csr_generated = True
            break
        print(f"⚠ CSR generation failed with status {csr_response.status_code}")
        if csr_attempt < max_csr_attempts:
            print("Retrying in 5 seconds...")
            time.sleep(5)

    if not csr_generated:
        print(f"ERROR: CSR generation failed after {max_csr_attempts} attempts")
        get_logger(__name__).error(
            f"CSR generation failed after {max_csr_attempts} attempts"
        )
        return False

    print("Waiting for CSR file to be created...")
    csr_found = False
    max_attempts = int(config.csr_file_timeout_minutes * 12)
    for attempt in range(max_attempts):
        try:
            check_result = run_vshell_cmd(
                net_connect,
                f"test -f {config.csr_file} && echo 'exists' || echo 'not_found'",
            )
            if "exists" in check_result:
                print(f"✓ CSR file found (attempt {attempt + 1})")
                csr_found = True
                break
        except Exception as e:
            print(f"Check attempt {attempt + 1} failed: {e}")

        if attempt < max_attempts - 1:
            time.sleep(5)

    if not csr_found:
        print(
            "ERROR: CSR file was not created after "
            f"{config.csr_file_timeout_minutes} minute(s)"
        )
        get_logger(__name__).error(
            f"CSR file not created after {config.csr_file_timeout_minutes} minute(s)"
        )
        return False

    print("Signing CSR...")
    run_vshell_cmd(
        net_connect,
        f"openssl x509 -req -in {config.csr_file} -CA {config.root_cert} "
        f"-CAkey {config.rsa_key} -CAcreateserial -out {config.signed_cert} "
        "-days 2000 -sha256",
    )
    signed_cert_content = read_file_vshell(net_connect, config.signed_cert)
    print("✓ CSR signed")

    print("\n" + "=" * 50)
    print("PART 4: Install Certificate")
    print("=" * 50)

    print("Installing certificate...")
    api_call(
        session,
        "POST",
        config.ip,
        config.port,
        "/dataservice/certificate/install/signedCert",
        raw_data=signed_cert_content,
    )

    print("✓ Certificate installed!")
    return True


def run_manager_automation(
    config: ManagerConfig,
    initial_config: bool = False,
    cert: bool = False,
    config_file: str | None = None,
):
    """
    Orchestrate Manager actions based on CLI flags.
    """
    logger = get_logger(__name__)
    logger.info(
        f"Manager run start initial_config={initial_config} cert={cert} config_file={config_file}",
    )
    net_connect = None

    if initial_config:
        print("\n" + "=" * 50)
        print("Mode: Initial Configuration")
        print("=" * 50)

        print("Attempting to connect with default credentials...")
        net_connect = connect_to_device(
            "cisco_viptela",
            config.ip,
            config.username,
            config.username,
            exit_on_failure=False,
        )

        if net_connect:
            push_initial_config(net_connect, config.initial_config)

            net_connect.disconnect()
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
            )
        else:
            print("⚠ Default credentials failed, trying configured password...")
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
            )
            print(
                "✓ Already configured with updated password - skipping initial config push"
            )

    if cert:
        if not net_connect:
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
            )

        print("\n" + "=" * 50)
        print("Mode: Certificate Automation")
        print("=" * 50)

        success = run_certificate_automation(net_connect, config)
        if not success:
            net_connect.disconnect()
            raise SystemExit(1)

        print("\n" + "=" * 50)
        print("SUCCESS! Check GUI: Configuration > Certificates > Control Components")
        print("=" * 50)

    if config_file:
        if not net_connect:
            net_connect = connect_to_device(
                "cisco_viptela", config.ip, config.username, config.password
            )
        push_config_from_file(net_connect, config_file)

    if net_connect:
        net_connect.disconnect()
        print("\n✓ Disconnected from Manager")
