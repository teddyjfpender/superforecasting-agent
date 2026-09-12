"""Device flow operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _request_device_code(
    client: _core.httpx.Client,
    portal_base_url: str,
    client_id: str,
    scope: _core.Optional[str],
) -> _core.Dict[str, _core.Any]:
    """POST to the device code endpoint. Returns device_code, user_code, etc."""
    response = client.post(
        f"{portal_base_url}/api/oauth/device/code",
        data={
            "client_id": client_id,
            **({"scope": scope} if scope else {}),
        },
    )
    response.raise_for_status()
    data = response.json()

    required_fields = [
        "device_code",
        "user_code",
        "verification_uri",
        "verification_uri_complete",
        "expires_in",
        "interval",
    ]
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise ValueError(f"Device code response missing fields: {', '.join(missing)}")
    return data


def _is_nous_invoke_scope_refusal(exc: Exception) -> bool:
    if not isinstance(exc, _core.httpx.HTTPStatusError):
        return False
    response = exc.response
    if response.status_code not in {400, 401, 403}:
        return False
    try:
        payload = response.json()
    except Exception:
        payload = {}
    text = " ".join(
        str(value)
        for value in (
            payload.get("error") if isinstance(payload, dict) else None,
            payload.get("error_description") if isinstance(payload, dict) else None,
            response.text,
        )
        if value
    ).lower()
    if not text:
        return False
    return (
        "invalid_scope" in text
        or "unsupported_scope" in text
        or "scope" in text
        and _core.NOUS_INFERENCE_INVOKE_SCOPE in text
    )


def _nous_device_scope_with_env_override(
    requested_scope: _core.Optional[str],
    *,
    default_scope: str = _core.DEFAULT_NOUS_SCOPE,
) -> _core.Tuple[str, bool]:
    explicit_scope = requested_scope is not None
    scope = requested_scope or default_scope
    if _core._nous_legacy_session_keys_forced():
        scope = _core.NOUS_LEGACY_AGENT_KEY_SCOPE
    return scope, explicit_scope


def _request_nous_device_code_with_scope_fallback(
    *,
    client: _core.httpx.Client,
    portal_base_url: str,
    client_id: str,
    scope: str,
    allow_legacy_fallback: bool,
) -> _core.Tuple[_core.Dict[str, _core.Any], str]:
    try:
        return (
            _core._request_device_code(
                client=client,
                portal_base_url=portal_base_url,
                client_id=client_id,
                scope=scope,
            ),
            scope,
        )
    except Exception as exc:
        if (
            allow_legacy_fallback
            and _core._nous_scope_has_invoke(scope)
            and _core._is_nous_invoke_scope_refusal(exc)
        ):
            _core.logger.info(
                "Nous inference auth: NAS refused invoke scope, retrying legacy scope"
            )
            _core._oauth_trace("nous_device_code_invoke_scope_refused")
            retry_scope = _core.NOUS_LEGACY_AGENT_KEY_SCOPE
            return (
                _core._request_device_code(
                    client=client,
                    portal_base_url=portal_base_url,
                    client_id=client_id,
                    scope=retry_scope,
                ),
                retry_scope,
            )
        raise


def _poll_for_token(
    client: _core.httpx.Client,
    portal_base_url: str,
    client_id: str,
    device_code: str,
    expires_in: int,
    poll_interval: int,
) -> _core.Dict[str, _core.Any]:
    """Poll the token endpoint until the user approves or the code expires."""
    deadline = _core.time.monotonic() + max(1, expires_in)
    current_interval = max(
        1, min(poll_interval, _core.DEVICE_AUTH_POLL_INTERVAL_CAP_SECONDS)
    )

    while _core.time.monotonic() < deadline:
        response = client.post(
            f"{portal_base_url}/api/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code,
            },
        )

        if response.status_code == 200:
            payload = response.json()
            if "access_token" not in payload:
                raise ValueError("Token response did not include access_token")
            return payload

        try:
            error_payload = response.json()
        except Exception:
            response.raise_for_status()
            raise RuntimeError("Token endpoint returned a non-JSON error response")

        error_code = error_payload.get("error", "")
        if error_code == "authorization_pending":
            _core.time.sleep(current_interval)
            continue
        if error_code == "slow_down":
            current_interval = min(current_interval + 1, 30)
            _core.time.sleep(current_interval)
            continue

        description = (
            error_payload.get("error_description") or "Unknown authentication error"
        )
        raise RuntimeError(f"{error_code}: {description}")

    raise TimeoutError("Timed out waiting for device authorization")
