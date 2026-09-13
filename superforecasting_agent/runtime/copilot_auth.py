"""Interactive Copilot login and compatibility credential exports."""

from __future__ import annotations

import superforecasting_agent.credentials.copilot as credential_service

from superforecasting_agent.credentials.copilot import (
    COPILOT_ENV_VARS as COPILOT_ENV_VARS,
    COPILOT_OAUTH_CLIENT_ID as COPILOT_OAUTH_CLIENT_ID,
    Optional as Optional,
    Path as Path,
    _CLASSIC_PAT_PREFIX as _CLASSIC_PAT_PREFIX,
    _DEVICE_CODE_POLL_INTERVAL as _DEVICE_CODE_POLL_INTERVAL,
    _DEVICE_CODE_POLL_SAFETY_MARGIN as _DEVICE_CODE_POLL_SAFETY_MARGIN,
    _EDITOR_VERSION as _EDITOR_VERSION,
    _EXCHANGE_USER_AGENT as _EXCHANGE_USER_AGENT,
    _JWT_REFRESH_MARGIN_SECONDS as _JWT_REFRESH_MARGIN_SECONDS,
    _SUPPORTED_PREFIXES as _SUPPORTED_PREFIXES,
    _TOKEN_EXCHANGE_URL as _TOKEN_EXCHANGE_URL,
    _gh_cli_candidates as _gh_cli_candidates,
    _jwt_cache as _jwt_cache,
    _token_fingerprint as _token_fingerprint,
    _try_gh_cli_token as _try_gh_cli_token,
    copilot_request_headers as copilot_request_headers,
    exchange_copilot_token as exchange_copilot_token,
    get_copilot_api_token as get_copilot_api_token,
    json as json,
    logger as logger,
    logging as logging,
    os as os,
    resolve_copilot_token as resolve_copilot_token,
    shutil as shutil,
    subprocess as subprocess,
    time as time,
    validate_copilot_token as validate_copilot_token,
)

def copilot_device_code_login(
    *,
    host: str = "github.com",
    timeout_seconds: float = 300,
) -> Optional[str]:
    """Run the GitHub OAuth device code flow for Copilot.

    Prints instructions for the user, polls for completion, and returns
    the OAuth access token on success, or None on failure/cancellation.

    This replicates the flow used by opencode and the Copilot CLI.
    """
    import urllib.request
    import urllib.parse

    domain = host.rstrip("/")
    device_code_url = f"https://{domain}/login/device/code"
    access_token_url = f"https://{domain}/login/oauth/access_token"

    # Step 1: Request device code
    data = urllib.parse.urlencode({
        "client_id": COPILOT_OAUTH_CLIENT_ID,
        "scope": "read:user",
    }).encode()

    req = urllib.request.Request(
        device_code_url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "SuperforecastingAgent/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            device_data = json.loads(resp.read().decode())
    except Exception as exc:
        logger.error("Failed to initiate device authorization: %s", exc)
        print(f"  ✗ Failed to start device authorization: {exc}")
        return None

    verification_uri = device_data.get("verification_uri", "https://github.com/login/device")
    user_code = device_data.get("user_code", "")
    device_code = device_data.get("device_code", "")
    interval = max(device_data.get("interval", _DEVICE_CODE_POLL_INTERVAL), 1)

    if not device_code or not user_code:
        print("  ✗ GitHub did not return a device code.")
        return None

    # Step 2: Show instructions
    print()
    print(f"  Open this URL in your browser: {verification_uri}")
    print(f"  Enter this code: {user_code}")
    print()
    print("  Waiting for authorization...", end="", flush=True)

    # Step 3: Poll for completion
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        time.sleep(interval + _DEVICE_CODE_POLL_SAFETY_MARGIN)

        poll_data = urllib.parse.urlencode({
            "client_id": COPILOT_OAUTH_CLIENT_ID,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }).encode()

        poll_req = urllib.request.Request(
            access_token_url,
            data=poll_data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "SuperforecastingAgent/1.0",
            },
        )

        try:
            with urllib.request.urlopen(poll_req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
        except Exception:
            print(".", end="", flush=True)
            continue

        if result.get("access_token"):
            print(" ✓")
            return result["access_token"]

        error = result.get("error", "")
        if error == "authorization_pending":
            print(".", end="", flush=True)
            continue
        elif error == "slow_down":
            # RFC 8628: add 5 seconds to polling interval
            server_interval = result.get("interval")
            if isinstance(server_interval, (int, float)) and server_interval > 0:
                interval = int(server_interval)
            else:
                interval += 5
            print(".", end="", flush=True)
            continue
        elif error == "expired_token":
            print()
            print("  ✗ Device code expired. Please try again.")
            return None
        elif error == "access_denied":
            print()
            print("  ✗ Authorization was denied.")
            return None
        elif error:
            print()
            print(f"  ✗ Authorization failed: {error}")
            return None

    print()
    print("  ✗ Timed out waiting for authorization.")
    return None
