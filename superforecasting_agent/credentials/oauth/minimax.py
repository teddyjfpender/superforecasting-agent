"""Minimax operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _minimax_pkce_pair() -> tuple:
    """Generate (code_verifier, code_challenge_S256, state) for MiniMax OAuth."""
    import secrets

    verifier = secrets.token_urlsafe(64)[:96]
    challenge = (
        _core.base64
        .urlsafe_b64encode(_core.hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    state = secrets.token_urlsafe(16)
    return verifier, challenge, state


def _minimax_request_user_code(
    client: _core.httpx.Client,
    *,
    portal_base_url: str,
    client_id: str,
    code_challenge: str,
    state: str,
) -> _core.Dict[str, _core.Any]:
    response = client.post(
        f"{portal_base_url}/oauth/code",
        data={
            "response_type": "code",
            "client_id": client_id,
            "scope": _core.MINIMAX_OAUTH_SCOPE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "x-request-id": str(_core.uuid.uuid4()),
        },
    )
    if response.status_code != 200:
        raise _core.AuthError(
            f"MiniMax OAuth authorization failed: {response.text or response.reason_phrase}",
            provider="minimax-oauth",
            code="authorization_failed",
        )
    payload = response.json()
    for field in ("user_code", "verification_uri", "expired_in"):
        if field not in payload:
            raise _core.AuthError(
                f"MiniMax OAuth response missing field: {field}",
                provider="minimax-oauth",
                code="authorization_incomplete",
            )
    if payload.get("state") != state:
        raise _core.AuthError(
            "MiniMax OAuth state mismatch (possible CSRF).",
            provider="minimax-oauth",
            code="state_mismatch",
        )
    return payload


def _minimax_expired_in_looks_like_unix_ms(expired_in: int, *, now_ms: int) -> bool:
    """True if ``expired_in`` is plausibly a unix-ms absolute time (vs TTL seconds)."""
    return int(expired_in) > (now_ms // 2)


def _minimax_resolve_token_expiry_unix(
    expired_in: int, *, now: _core.datetime
) -> float:
    """Return access-token expiry as unix seconds (MiniMax uses ms epoch or TTL seconds)."""
    raw = int(expired_in)
    now_ms = int(now.timestamp() * 1000)
    if _core._minimax_expired_in_looks_like_unix_ms(raw, now_ms=now_ms):
        return raw / 1000.0
    return now.timestamp() + max(1, raw)


def _minimax_poll_token(
    client: _core.httpx.Client,
    *,
    portal_base_url: str,
    client_id: str,
    user_code: str,
    code_verifier: str,
    expired_in: int,
    interval_ms: _core.Optional[int],
) -> _core.Dict[str, _core.Any]:
    # OpenClaw treats expired_in as a unix-ms timestamp (Date.now() < expireTimeMs).
    # Defensive parsing: if it's small enough to be a duration, treat as seconds.
    import time as _time

    now_ms = int(_time.time() * 1000)
    raw = int(expired_in)
    if _core._minimax_expired_in_looks_like_unix_ms(raw, now_ms=now_ms):
        deadline = raw / 1000.0
    else:
        deadline = _time.time() + max(1, raw)
    interval = max(2.0, (interval_ms or 2000) / 1000.0)

    while _time.time() < deadline:
        response = client.post(
            f"{portal_base_url}/oauth/token",
            data={
                "grant_type": _core.MINIMAX_OAUTH_GRANT_TYPE,
                "client_id": client_id,
                "user_code": user_code,
                "code_verifier": code_verifier,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            payload = response.json() if response.text else {}
        except Exception:
            payload = {}

        if response.status_code != 200:
            msg = (payload.get("base_resp", {}) or {}).get(
                "status_msg"
            ) or response.text
            raise _core.AuthError(
                f"MiniMax OAuth error: {msg or 'unknown'}",
                provider="minimax-oauth",
                code="token_exchange_failed",
            )

        status = payload.get("status")
        if status == "error":
            raise _core.AuthError(
                "MiniMax OAuth reported an error. Please try again later.",
                provider="minimax-oauth",
                code="authorization_denied",
            )
        if status == "success":
            if not all(
                payload.get(k) for k in ("access_token", "refresh_token", "expired_in")
            ):
                raise _core.AuthError(
                    "MiniMax OAuth success payload missing required token fields.",
                    provider="minimax-oauth",
                    code="token_incomplete",
                )
            return payload
        # "pending" or any other status -> keep polling
        _time.sleep(interval)

    raise _core.AuthError(
        "MiniMax OAuth timed out before authorization completed.",
        provider="minimax-oauth",
        code="timeout",
    )


def _minimax_save_auth_state(auth_state: _core.Dict[str, _core.Any]) -> None:
    """Persist MiniMax OAuth state to Hermes auth store (~/.hermes/auth.json)."""
    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        _core._save_provider_state(auth_store, "minimax-oauth", auth_state)
        _core._save_auth_store(auth_store)


def _refresh_minimax_oauth_state(
    state: _core.Dict[str, _core.Any],
    *,
    timeout_seconds: float = 15.0,
    force: bool = False,
) -> _core.Dict[str, _core.Any]:
    """Refresh MiniMax OAuth access token if close to expiry (or forced)."""
    if not state.get("refresh_token"):
        raise _core.AuthError(
            "MiniMax OAuth state has no refresh_token; please re-login.",
            provider="minimax-oauth",
            code="no_refresh_token",
            relogin_required=True,
        )
    try:
        expires_at = _core.datetime.fromisoformat(
            state.get("expires_at", "")
        ).timestamp()
    except Exception:
        expires_at = 0.0
    now = _core.time.time()
    if not force and (expires_at - now) > _core.MINIMAX_OAUTH_REFRESH_SKEW_SECONDS:
        return state

    portal_base_url = state["portal_base_url"]
    with _core.httpx.Client(
        timeout=_core.httpx.Timeout(timeout_seconds), follow_redirects=True
    ) as client:
        response = client.post(
            f"{portal_base_url}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": state["client_id"],
                "refresh_token": state["refresh_token"],
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
    if response.status_code != 200:
        body = response.text.lower()
        relogin = any(
            m in body
            for m in ("invalid_grant", "refresh_token_reused", "invalid_refresh_token")
        )
        raise _core.AuthError(
            f"MiniMax OAuth refresh failed: {response.text or response.reason_phrase}",
            provider="minimax-oauth",
            code="refresh_failed",
            relogin_required=relogin,
        )
    payload = response.json()
    if payload.get("status") != "success":
        raise _core.AuthError(
            "MiniMax OAuth refresh did not return success.",
            provider="minimax-oauth",
            code="refresh_failed",
            relogin_required=True,
        )
    now_dt = _core.datetime.now(_core.timezone.utc)
    expires_at_unix = _core._minimax_resolve_token_expiry_unix(
        int(payload["expired_in"]),
        now=now_dt,
    )
    expires_in_s = max(0, int(expires_at_unix - now_dt.timestamp()))
    new_state = dict(state)
    new_state.update({
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token", state["refresh_token"]),
        "obtained_at": now_dt.isoformat(),
        "expires_at": _core.datetime.fromtimestamp(
            expires_at_unix, tz=_core.timezone.utc
        ).isoformat(),
        "expires_in": expires_in_s,
    })
    _core._minimax_save_auth_state(new_state)
    return new_state


def resolve_minimax_oauth_runtime_credentials(
    *,
    min_token_ttl_seconds: int = _core.MINIMAX_OAUTH_REFRESH_SKEW_SECONDS,
) -> _core.Dict[str, _core.Any]:
    """Return {provider, api_key, base_url, source} for minimax-oauth."""
    state = _core.get_provider_auth_state("minimax-oauth")
    if not state or not state.get("access_token"):
        raise _core.AuthError(
            f"Not logged into MiniMax OAuth. Run `{_core._PRIMARY_CLI} model` and select "
            "MiniMax (OAuth).",
            provider="minimax-oauth",
            code="not_logged_in",
            relogin_required=True,
        )
    try:
        state = _core._refresh_minimax_oauth_state(state)
    except _core.AuthError as exc:
        if exc.relogin_required and state.get("refresh_token"):
            # Terminal refresh failure — clear dead tokens from auth.json so
            # subsequent calls fail fast without a network retry, mirroring
            # the Nous / xAI-OAuth / Codex-OAuth quarantine pattern.
            for _k in (
                "access_token",
                "refresh_token",
                "expires_at",
                "expires_in",
                "obtained_at",
            ):
                state.pop(_k, None)
            state["last_auth_error"] = {
                "provider": "minimax-oauth",
                "code": exc.code or "refresh_failed",
                "message": str(exc),
                "reason": "runtime_refresh_failure",
                "relogin_required": True,
                "at": _core.datetime.now(_core.timezone.utc).isoformat(),
            }
            try:
                _core._minimax_save_auth_state(state)
            except Exception as _save_exc:
                _core.logger.debug(
                    "MiniMax OAuth: failed to persist quarantined state: %s", _save_exc
                )
        raise
    return {
        "provider": "minimax-oauth",
        "api_key": state["access_token"],
        "base_url": state["inference_base_url"].rstrip("/"),
        "source": "oauth",
    }
