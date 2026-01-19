import time

import sdwan_config as settings
from utils.netmiko import bootstrap_initial_config, ensure_connection, push_config_from_file
from utils.output import Output
from utils.sdwan_sdk import SdkCallError, sdk_call_json, sdk_call_raw
from utils.vshell import read_file_vshell, run_vshell_cmd


def run_manager_automation(
    config: settings.ManagerConfig,
    initial_config: bool = False,
    cert: bool = False,
    config_file: str | None = None,
):
    """
    Orchestrate Manager/vManage actions.
    """
    out = Output(__name__)
    out.log_only(
        f"Manager run start initial_config={initial_config} cert={cert} config_file={config_file}",
    )
    out.header("Automation: MANAGER (vManage)", f"Target: {config.ip}")

    net_connect = None

    if initial_config:
        out.header("MANAGER: Initial Configuration")
        net_connect = bootstrap_initial_config(
            device_label="Manager",
            device_type="cisco_viptela",
            host=config.ip,
            username=config.username,
            default_password=config.default_password,
            updated_password=config.password,
            initial_config=config.initial_config,
            commit_command="commit",
        )

    if config_file:
        if not net_connect:
            net_connect = ensure_connection(
                net_connect,
                "cisco_viptela",
                config.ip,
                config.username,
                config.password,
            )
        push_config_from_file(
            net_connect,
            config_file,
            commit_command="commit",
        )

    if cert:
        if not net_connect:
            net_connect = ensure_connection(
                net_connect,
                "cisco_viptela",
                config.ip,
                config.username,
                config.password,
            )

        out.header("MANAGER: Certificate Configuration")

        success = run_certificate_automation(net_connect, config)
        if not success:
            net_connect.disconnect()
            raise SystemExit(1)

    if net_connect:
        net_connect.disconnect()
        out.success("Disconnected from Manager")


def run_certificate_automation(net_connect, config: settings.ManagerConfig):
    """
    Run the full certificate automation workflow

    Args:
        net_connect: Active Netmiko connection to Manager
        config: Config object
    """
    out = Output(__name__)

    out.subheader("PART 1: Generate Root Certificate")

    out.step("Generating RSA key...")
    run_vshell_cmd(net_connect, f"openssl genrsa -out {config.rsa_key} 2048")

    out.step("Generating root certificate...")
    subj = f"/C={config.country}/ST={config.state}/L={config.city}/O={config.org}/CN={config.org}"
    run_vshell_cmd(
        net_connect,
        f"openssl req -x509 -new -nodes -key {config.rsa_key} -sha256 -days 2000 "
        f'-subj "{subj}" -out {config.root_cert}',
    )

    root_cert_content = read_file_vshell(net_connect, config.root_cert)
    out.success("Root certificate created")

    out.subheader("PART 2: Configure Manager GUI via API")

    try:
        out.step(f"Setting organization: {config.org}")
        sdk_call_json(
            config,
            "PUT",
            "/dataservice/settings/configuration/organization",
            data={"org": config.org},
        )

        out.step(f"Setting validator IP: {config.validator_ip}")
        sdk_call_json(
            config,
            "PUT",
            "/dataservice/settings/configuration/device",
            data={"domainIp": config.validator_ip, "port": "12346"},
        )

        out.step("Changing certificate to enterprise root certificate...")
        sdk_call_json(
            config,
            "POST",
            "/dataservice/settings/configuration/certificate",
            data={"certificateSigning": "enterprise"},
        )

        out.step("Uploading enterprise root certificate...")
        sdk_call_json(
            config,
            "PUT",
            "/dataservice/settings/configuration/certificate/enterpriserootca",
            data={"enterpriseRootCA": root_cert_content},
        )

        out.step("Setting CSR properties as default...")
        sdk_call_json(
            config,
            "PUT",
            "/dataservice/settings/configuration/certificate/csrproperties",
            data={"domain_name": ""},
        )
    except SdkCallError as exc:
        out.error(str(exc))
        return False

    out.success("Manager configured")

    out.subheader("PART 3: Generate and Sign CSR")

    out.step("Generating CSR...")
    csr_generated = False
    max_csr_attempts = 3

    for csr_attempt in range(1, max_csr_attempts + 1):
        try:
            sdk_call_json(
                config,
                "POST",
                "/dataservice/certificate/generate/csr",
                data={"deviceIP": config.ip},
            )
        except SdkCallError as exc:
            out.error(str(exc))
            return False
        else:
            out.success(
                f"CSR generation successful (attempt {csr_attempt}/{max_csr_attempts})"
            )
            csr_generated = True
            break

        # Failed
        if csr_attempt < max_csr_attempts:
            out.wait(
                f"CSR attempt {csr_attempt}/{max_csr_attempts} failed, retrying in 5s..."
            )
            time.sleep(5)
        else:
            out.error(f"CSR generation failed after {max_csr_attempts} attempts")

    if not csr_generated:
        out.error("CSR generation failed; aborting.")
        return False

    out.wait("Waiting for CSR file to be created...")
    csr_found = False
    max_attempts = int(config.csr_file_timeout_minutes * 12)
    for attempt in range(max_attempts):
        try:
            check_result = run_vshell_cmd(
                net_connect,
                f"test -f {config.csr_file} && echo 'exists' || echo 'not_found'",
            )
            if "exists" in check_result:
                out.success(f"CSR file found (attempt {attempt + 1})")
                csr_found = True
                break
        except Exception as e:
            out.detail(f"Check attempt {attempt + 1} failed: {e}")

        if attempt < max_attempts - 1:
            time.sleep(5)

    if not csr_found:
        out.error(
            f"CSR file was not created after {config.csr_file_timeout_minutes} minute(s)"
        )
        return False

    out.step("Signing CSR...")
    run_vshell_cmd(
        net_connect,
        f"openssl x509 -req -in {config.csr_file} -CA {config.root_cert} "
        f"-CAkey {config.rsa_key} -CAcreateserial -out {config.signed_cert} "
        "-days 2000 -sha256",
    )
    signed_cert_content = read_file_vshell(net_connect, config.signed_cert)
    out.success("CSR signed")

    out.subheader("PART 4: Install Certificate")

    out.step("Installing certificate...")
    try:
        sdk_call_raw(
            config,
            "POST",
            "/dataservice/certificate/install/signedCert",
            raw_data=signed_cert_content,
        )
    except SdkCallError as exc:
        out.error(str(exc))
        return False

    out.success("Certificate installed!")
    return True
