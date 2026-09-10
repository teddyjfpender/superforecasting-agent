"""Non-interactive primitives for the OpenAI Codex device-code login.

The CLI flow (`superforecasting_agent.runtime.auth._codex_device_code_login`) is one blocking
function that prints to stdout and polls for up to 15 minutes — unusable from
the TUI gateway, which needs to show the code, return immediately, and poll
in the background. These primitives split the same handshake into steps:

    request_device_code()  -> show user_code + verification URL
    poll_device_token_once -> None while the user hasn't finished signing in
    exchange_device_code   -> tokens dict ready for auth._save_codex_tokens

No persistence here; callers decide where tokens land. Endpoints, client id,
and error envelope all come from superforecasting_agent.runtime.auth so the two flows can't drift.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from superforecasting_agent.runtime.auth import (
    AuthError,
    CODEX_OAUTH_CLIENT_ID,
    CODEX_OAUTH_TOKEN_URL,
    DEFAULT_CODEX_BASE_URL,
)

CODEX_ISSUER = "https://auth.openai.com"
CODEX_DEVICE_VERIFICATION_URL = f"{CODEX_ISSUER}/codex/device"
DEVICE_FLOW_MAX_WAIT_SECONDS = 15 * 60


@dataclass
class DeviceCodeGrant:
    user_code: str
    device_auth_id: str
    interval: int
    verification_url: str = CODEX_DEVICE_VERIFICATION_URL


def request_device_code(timeout_seconds: float = 15.0) -> DeviceCodeGrant:
    """Start a device-code login: returns the code the user must enter."""
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_seconds)) as client:
            resp = client.post(
                f"{CODEX_ISSUER}/api/accounts/deviceauth/usercode",
                json={"client_id": CODEX_OAUTH_CLIENT_ID},
                headers={"Content-Type": "application/json"},
            )
    except Exception as exc:
        raise AuthError(
            f"Failed to request device code: {exc}",
            provider="openai-codex", code="device_code_request_failed",
        )
    if resp.status_code != 200:
        raise AuthError(
            f"Device code request returned status {resp.status_code}.",
            provider="openai-codex", code="device_code_request_error",
        )
    data = resp.json()
    user_code = str(data.get("user_code", ""))
    device_auth_id = str(data.get("device_auth_id", ""))
    if not user_code or not device_auth_id:
        raise AuthError(
            "Device code response missing required fields.",
            provider="openai-codex", code="device_code_incomplete",
        )
    try:
        interval = max(3, int(data.get("interval", "5")))
    except (TypeError, ValueError):
        interval = 5
    return DeviceCodeGrant(user_code=user_code, device_auth_id=device_auth_id, interval=interval)


def poll_device_token_once(
    grant: DeviceCodeGrant, timeout_seconds: float = 15.0
) -> Optional[Dict[str, str]]:
    """One poll of the device-token endpoint.

    Returns None while the user hasn't completed sign-in; on completion
    returns ``{authorization_code, code_verifier}``. Raises AuthError on a
    terminal polling error.
    """
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_seconds)) as client:
            resp = client.post(
                f"{CODEX_ISSUER}/api/accounts/deviceauth/token",
                json={"device_auth_id": grant.device_auth_id, "user_code": grant.user_code},
                headers={"Content-Type": "application/json"},
            )
    except Exception as exc:
        raise AuthError(
            f"Device auth polling failed: {exc}",
            provider="openai-codex", code="device_code_poll_failed",
        )
    if resp.status_code in {403, 404}:
        return None  # user hasn't completed login yet
    if resp.status_code != 200:
        raise AuthError(
            f"Device auth polling returned status {resp.status_code}.",
            provider="openai-codex", code="device_code_poll_error",
        )
    payload = resp.json()
    authorization_code = str(payload.get("authorization_code", ""))
    code_verifier = str(payload.get("code_verifier", ""))
    if not authorization_code or not code_verifier:
        raise AuthError(
            "Device auth response missing authorization_code or code_verifier.",
            provider="openai-codex", code="device_code_incomplete_exchange",
        )
    return {"authorization_code": authorization_code, "code_verifier": code_verifier}


def exchange_device_code(
    authorization_code: str, code_verifier: str, timeout_seconds: float = 15.0
) -> Dict[str, Any]:
    """Exchange the authorization code for tokens.

    Returns the same shape `_codex_device_code_login` produces:
    ``{"tokens": {"access_token", "refresh_token"}, "base_url": ...}``.
    """
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_seconds)) as client:
            resp = client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": f"{CODEX_ISSUER}/deviceauth/callback",
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as exc:
        raise AuthError(
            f"Token exchange failed: {exc}",
            provider="openai-codex", code="token_exchange_failed",
        )
    if resp.status_code != 200:
        raise AuthError(
            f"Token exchange returned status {resp.status_code}.",
            provider="openai-codex", code="token_exchange_error",
        )
    tokens = resp.json()
    access_token = str(tokens.get("access_token", "") or "")
    refresh_token = str(tokens.get("refresh_token", "") or "")
    if not access_token:
        raise AuthError(
            "Token exchange did not return an access_token.",
            provider="openai-codex", code="token_exchange_no_access_token",
        )
    base_url = (
        os.getenv("HERMES_CODEX_BASE_URL", "").strip().rstrip("/") or DEFAULT_CODEX_BASE_URL
    )
    return {
        "tokens": {"access_token": access_token, "refresh_token": refresh_token},
        "base_url": base_url,
    }
