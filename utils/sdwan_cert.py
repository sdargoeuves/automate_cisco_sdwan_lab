import sdwan_config as settings
from utils.netmiko import connect_to_device
from utils.output import Output
from utils.sdwan_sdk import SdkCallError, sdk_call_raw
from utils.vshell import read_file_vshell, run_vshell_cmd, write_file_vshell


def fetch_root_material_from_manager() -> tuple[str, str]:
    out = Output(__name__)
    out.step("Reading RSA key and root certificate from Manager...")
    manager_conn = connect_to_device(
        "cisco_viptela",
        settings.manager.mgmt_ip,
        settings.manager.username,
        settings.manager.password,
    )
    rsa_key_content = read_file_vshell(manager_conn, settings.manager.rsa_key)
    root_cert_content = read_file_vshell(manager_conn, settings.manager.root_cert)
    manager_conn.disconnect()
    return rsa_key_content, root_cert_content


def write_root_material_to_device(
    net_connect,
    rsa_key_content: str,
    root_cert_content: str,
    device_label: str,
) -> None:
    out = Output(__name__)
    out.step(f"Writing RSA key and root certificate to {device_label}...")
    write_file_vshell(net_connect, settings.manager.rsa_key, rsa_key_content)
    write_file_vshell(net_connect, settings.manager.root_cert, root_cert_content)
    out.success(f"RSA key and root certificate copied to {device_label.lower()}")


def sign_csr(net_connect, config) -> str:
    out = Output(__name__)
    out.step("Signing CSR...")
    run_vshell_cmd(
        net_connect,
        f"openssl x509 -req -in {config.csr_file} -CA {config.root_cert} "
        f"-CAkey {config.rsa_key} -CAcreateserial -out {config.signed_cert} "
        "-days 2000 -sha256",
    )
    signed_cert_content = read_file_vshell(net_connect, config.signed_cert)
    out.success("CSR signed")
    return signed_cert_content


def install_signed_cert_on_manager(signed_cert_content: str) -> bool:
    out = Output(__name__)
    out.step("Installing certificate on Manager...")
    try:
        sdk_call_raw(
            settings.manager,
            "POST",
            "/dataservice/certificate/install/signedCert",
            raw_data=signed_cert_content,
        )
    except SdkCallError as exc:
        out.error(str(exc))
        return False

    out.success("Certificate installed!")
    return True
