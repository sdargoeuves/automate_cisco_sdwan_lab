import shutil
import subprocess
import time
from threading import Lock
from typing import Any, Mapping

import requests
from cisco_sdwan.base.rest_api import Rest, RestAPIException

from utils.output import Output

out = Output(__name__)
_client_cache: dict[str, Rest] = {}
_cache_lock = Lock()


class SdkCallError(RuntimeError):
    """SDK call failure with user-friendly context."""


def _cache_key(manager_config) -> str:
    return f"{manager_config.username}@{manager_config.ip}:{manager_config.port}"


def _create_client_with_retry(manager_config) -> Rest | None:
    base_url = f"https://{manager_config.ip}:{manager_config.port}"
    max_wait = getattr(manager_config, "api_ready_timeout_minutes", 15)
    deadline = time.monotonic() + (max_wait * 60)
    attempt = 0

    while True:
        attempt += 1
        try:
            out.log_only(
                f"SDK login attempt {attempt} to {manager_config.ip}:{manager_config.port}",
                level="debug",
            )
            return Rest(
                base_url=base_url,
                username=manager_config.username,
                password=manager_config.password,
                verify=False,
            )
        except (RestAPIException, requests.exceptions.RequestException) as exc:
            if time.monotonic() >= deadline:
                out.error(f"Manager SDK login failed: {exc}")
                return None
            out.wait(
                f"Manager API not ready yet (attempt {attempt}/{int(max_wait * 60 / 10)}); retrying in 10s"
            )
            time.sleep(10)


def _get_or_create_client(manager_config) -> Rest | None:
    key = _cache_key(manager_config)
    with _cache_lock:
        client = _client_cache.get(key)
        if client:
            return client

    client = _create_client_with_retry(manager_config)
    if not client:
        return None

    with _cache_lock:
        _client_cache[key] = client
    return client


def sdk_init(manager_config) -> bool:
    """
    Initialize and cache a Manager SDK client for reuse.
    """
    client = _create_client_with_retry(manager_config)
    if not client:
        return False

    key = _cache_key(manager_config)
    with _cache_lock:
        _client_cache[key] = client
    return True


def sdk_cleanup() -> None:
    """
    Logout and clear all cached SDK clients.
    """
    with _cache_lock:
        clients = list(_client_cache.values())
        _client_cache.clear()

    for client in clients:
        try:
            client.logout()
            client.session.close()
        except Exception as exc:
            out.log_only(f"SDK cleanup error: {exc}", level="debug")


def _endpoint_parts(endpoint: str) -> list[str]:
    if not endpoint or not endpoint.strip():
        raise ValueError("Endpoint cannot be empty")

    path = endpoint.strip()
    if path.startswith("/dataservice/"):
        path = path[len("/dataservice/") :]
    path = path.strip("/")
    return [part for part in path.split("/") if part]


def sdk_call_json(
    manager_config,
    method: str,
    endpoint: str,
    data: Mapping[str, Any] | None = None,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    client = _get_or_create_client(manager_config)
    if not client:
        raise SdkCallError("vManage API not ready.")

    parts = _endpoint_parts(endpoint)
    try:
        if method == "GET":
            return client.get(*parts, **(params or {}))
        if method == "POST":
            return client.post(data or {}, *parts)
        if method == "PUT":
            return client.put(data or {}, *parts)
        if method == "DELETE":
            return client.delete(*parts, input_data=data, **(params or {}))
        raise ValueError(f"Unsupported HTTP method: {method}")
    except RestAPIException as exc:
        raise SdkCallError(f"vManage SDK {method} failed: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise SdkCallError(f"vManage SDK {method} request error: {exc}") from exc


def sdk_call_raw(
    manager_config,
    method: str,
    endpoint: str,
    raw_data: str,
) -> bool:
    if not raw_data:
        raise ValueError("raw_data cannot be empty")

    client = _get_or_create_client(manager_config)
    if not client:
        raise SdkCallError("vManage API not ready.")

    path = "/".join(_endpoint_parts(endpoint))
    url = f"{client.base_url}/dataservice/{path}"
    try:
        if method == "POST":
            response = client.session.post(
                url,
                data=raw_data,
                timeout=client.timeout,
                verify=client.verify,
            )
        elif method == "PUT":
            response = client.session.put(
                url,
                data=raw_data,
                timeout=client.timeout,
                verify=client.verify,
            )
        else:
            raise ValueError(f"Unsupported HTTP method for raw call: {method}")
    except Exception as exc:
        raise SdkCallError(f"vManage SDK raw {method} failed: {exc}") from exc

    if not (200 <= response.status_code < 300):
        raise SdkCallError(
            f"vManage SDK raw {method} failed: HTTP {response.status_code} {response.text}"
        )

    return True


def run_sdwan_cli(settings, sdk_args: list[str]) -> int:
    sdwan_cli = shutil.which("sdwan")
    if not sdwan_cli:
        out.error("Sastre CLI not found on PATH. Install cisco-sdwan first.")
        return 1

    base_args = [
        "-a",
        settings.manager.ip,
        "-u",
        settings.manager.username,
        "-p",
        settings.manager.password,
        "--port",
        settings.manager.port,
    ]
    out.step(f"Running: {sdwan_cli} {' '.join(base_args + sdk_args)}")
    result = subprocess.run([sdwan_cli, *base_args, *sdk_args])
    return result.returncode
