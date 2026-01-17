import time
from threading import Lock

import requests

from utils.output import Output

requests.packages.urllib3.disable_warnings()

out = Output(__name__)
_session_cache = {}
_cache_lock = Lock()


def wait_for_api_ready(
    host, port, username, password, max_wait_minutes, token_length_limit=500
):
    """
    Wait for API to be ready and accessible.

    Args:
        host: Target IP or hostname
        port: API port
        username: Login username
        password: Login password
        max_wait_minutes: Maximum time to wait in minutes
        token_length_limit: Upper limit for token length to detect HTML
    """
    max_attempts = max_wait_minutes * 6  # Check every 10 seconds
    login_url = f"https://{host}:{port}/j_security_check"
    token_url = f"https://{host}:{port}/dataservice/client/token"

    out.log_only(f"Waiting for API ready at {host}:{port} (max {max_wait_minutes} min)", level="debug")

    for attempt in range(1, max_attempts + 1):
        try:
            session = requests.Session()
            session.verify = False

            out.log_only(f"Attempt {attempt}: POST {login_url}", level="debug")
            login_response = session.post(
                login_url,
                data={"j_username": username, "j_password": password},
                timeout=10,
            )
            out.log_only(f"Attempt {attempt}: Login response: {login_response.status_code}", level="debug")

            out.log_only(f"Attempt {attempt}: GET {token_url}", level="debug")
            token_response = session.get(
                token_url,
                timeout=10,
            )
            out.log_only(f"Attempt {attempt}: Token response: {token_response.status_code}", level="debug")

            token = token_response.text.strip()
            out.log_only(f"Attempt {attempt}: Token length: {len(token)}, starts with: {token[:50] if token else 'empty'}...", level="debug")

            if (
                token
                and "<html>" not in token.lower()
                and len(token) < token_length_limit
            ):
                out.success(f"API is ready (attempt {attempt})")
                return True
            out.wait(
                f"API not ready yet (attempt {attempt}/{max_attempts}) - "
                "got HTML response instead of token"
            )

        except (requests.exceptions.RequestException, Exception) as e:
            out.log_only(f"Attempt {attempt}: Exception: {type(e).__name__}: {e}", level="debug")
            out.wait(
                f"API not ready yet (attempt {attempt}/{max_attempts}) - "
                f"{type(e).__name__}"
            )

        if attempt < max_attempts:
            time.sleep(10)

    out.error(f"API did not become ready after {max_wait_minutes} minutes")
    return False


def get_api_session(host, port, username, password, max_wait_minutes=None):
    """
    Create an authenticated vManage API session.

    Returns:
        requests.Session | None: Authenticated session or None on failure.
    """
    if max_wait_minutes is not None:
        if not wait_for_api_ready(
            host, port, username, password, max_wait_minutes
        ):
            return None

    session = requests.Session()
    session.verify = False

    login_url = f"https://{host}:{port}/j_security_check"
    token_url = f"https://{host}:{port}/dataservice/client/token"

    out.log_only(f"POST {login_url}", level="debug")
    session.post(
        login_url,
        data={"j_username": username, "j_password": password},
        timeout=10,
    )

    out.log_only(f"GET {token_url}", level="debug")
    token_response = session.get(token_url, timeout=10)
    token = token_response.text.strip()

    if not token or "<html" in token.lower():
        out.warning("Failed to obtain API token from vManage.")
        out.detail(
            f"Token response token_length={len(token)} status={token_response.status_code}"
        )
        return None

    session.headers.update({"X-XSRF-TOKEN": token, "Content-Type": "application/json"})
    return session


def api_call_with_session(manager_config, method, endpoint, **kwargs):
    """
    Make an API call with automatic session creation and refresh.

    Returns:
        requests.Response | None
    """
    cache_key = f"{manager_config.username}@{manager_config.ip}:{manager_config.port}"
    with _cache_lock:
        session = _session_cache.get(cache_key)

    if not session:
        session = _create_and_cache_session(manager_config, cache_key)
        if not session:
            return None

    response = api_call(
        session,
        method,
        manager_config.ip,
        manager_config.port,
        endpoint,
        **kwargs,
    )

    if response is not None and response.status_code in (401, 403):
        session = _create_and_cache_session(manager_config, cache_key)
        if session:
            response = api_call(
                session,
                method,
                manager_config.ip,
                manager_config.port,
                endpoint,
                **kwargs,
            )

    return response


def _create_and_cache_session(manager_config, cache_key):
    session = get_api_session(
        manager_config.ip,
        manager_config.port,
        manager_config.username,
        manager_config.password,
        manager_config.api_ready_timeout_minutes,
    )
    if session:
        with _cache_lock:
            _session_cache[cache_key] = session
    return session


def api_call(session, method, host, port, endpoint, data=None, raw_data=None):
    """Make API call to a device."""
    url = f"https://{host}:{port}{endpoint}"

    # Debug logging
    out.log_only(f"API {method} {url}", level="debug")
    if data:
        out.log_only(f"API Payload: {data}", level="debug")
    if raw_data:
        out.log_only(f"API Raw Data: {raw_data[:200]}..." if len(str(raw_data)) > 200 else f"API Raw Data: {raw_data}", level="debug")

    if method == "GET":
        response = session.get(url)
    elif method == "POST":
        if raw_data is not None:
            response = session.post(url, data=raw_data)
        else:
            response = session.post(url, json=data if data else {})
    elif method == "PUT":
        if raw_data is not None:
            response = session.put(url, data=raw_data)
        else:
            response = session.put(url, json=data)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    out.log_only(f"API Response: {response.status_code}", level="debug")
    return response
