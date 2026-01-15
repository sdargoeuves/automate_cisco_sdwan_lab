import time

import requests

requests.packages.urllib3.disable_warnings()


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

    for attempt in range(1, max_attempts + 1):
        try:
            session = requests.Session()
            session.verify = False

            session.post(
                f"https://{host}:{port}/j_security_check",
                data={"j_username": username, "j_password": password},
                timeout=10,
            )

            token_response = session.get(
                f"https://{host}:{port}/dataservice/client/token",
                timeout=10,
            )

            token = token_response.text.strip()

            if (
                token
                and "<html>" not in token.lower()
                and len(token) < token_length_limit
            ):
                print(f"✓ API is ready (attempt {attempt})")
                return True
            print(
                f"⏳ API not ready yet (attempt {attempt}/{max_attempts}) - "
                "got HTML response instead of token"
            )

        except (requests.exceptions.RequestException, Exception) as e:
            print(
                f"⏳ API not ready yet (attempt {attempt}/{max_attempts}) - "
                f"{type(e).__name__}"
            )

        if attempt < max_attempts:
            time.sleep(10)

    print(f"✗ API did not become ready after {max_wait_minutes} minutes")
    return False


def api_call(session, method, host, port, endpoint, data=None, raw_data=None):
    """Make API call to a device."""
    url = f"https://{host}:{port}{endpoint}"
    if method == "GET":
        return session.get(url)
    if method == "POST":
        if raw_data is not None:
            return session.post(url, data=raw_data)
        return session.post(url, json=data if data else {})
    if method == "PUT":
        if raw_data is not None:
            return session.put(url, data=raw_data)
        return session.put(url, json=data)
    raise ValueError(f"Unsupported HTTP method: {method}")
