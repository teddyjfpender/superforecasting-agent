"""External oauth operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _qwen_cli_auth_path() -> _core.Path:
    return _core.Path.home() / ".qwen" / "oauth_creds.json"


def _read_qwen_cli_tokens() -> _core.Dict[str, _core.Any]:
    auth_path = _core._qwen_cli_auth_path()
    if not auth_path.exists():
        raise _core.AuthError(
            "Qwen CLI credentials not found. Run 'qwen auth qwen-oauth' first.",
            provider="qwen-oauth",
            code="qwen_auth_missing",
        )
    try:
        data = _core.json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise _core.AuthError(
            f"Failed to read Qwen CLI credentials from {auth_path}: {exc}",
            provider="qwen-oauth",
            code="qwen_auth_read_failed",
        ) from exc
    if not isinstance(data, dict):
        raise _core.AuthError(
            f"Invalid Qwen CLI credentials in {auth_path}.",
            provider="qwen-oauth",
            code="qwen_auth_invalid",
        )
    return data


def _save_qwen_cli_tokens(tokens: _core.Dict[str, _core.Any]) -> _core.Path:
    auth_path = _core._qwen_cli_auth_path()
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _core.os.chmod(auth_path.parent, 0o700)
    except OSError:
        pass
    # Per-process random temp suffix avoids collisions between concurrent
    # writers and stale leftovers from a crashed prior write.
    tmp_path = auth_path.with_name(
        f"{auth_path.name}.tmp.{_core.os.getpid()}.{_core.uuid.uuid4().hex}"
    )
    # Create with 0o600 atomically via os.open(O_EXCL) — closes the TOCTOU
    # window where write_text() + post-write chmod briefly exposed tokens
    # at process umask (typically 0o644). See #19673, #21148.
    fd = _core.os.open(
        str(tmp_path),
        _core.os.O_WRONLY | _core.os.O_CREAT | _core.os.O_EXCL,
        _core.stat.S_IRUSR | _core.stat.S_IWUSR,
    )
    try:
        with _core.owned_text_descriptor(fd) as fh:
            fh.write(_core.json.dumps(tokens, indent=2, sort_keys=True) + "\n")
            fh.flush()
            _core.os.fsync(fh.fileno())
        _core.atomic_replace(tmp_path, auth_path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
    return auth_path


def _qwen_access_token_is_expiring(
    expiry_date_ms: _core.Any,
    skew_seconds: int = _core.QWEN_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
) -> bool:
    try:
        expiry_ms = int(expiry_date_ms)
    except Exception:
        return True
    return (_core.time.time() + max(0, int(skew_seconds))) * 1000 >= expiry_ms


def _refresh_qwen_cli_tokens(
    tokens: _core.Dict[str, _core.Any], timeout_seconds: float = 20.0
) -> _core.Dict[str, _core.Any]:
    refresh_token = str(tokens.get("refresh_token", "") or "").strip()
    if not refresh_token:
        raise _core.AuthError(
            "Qwen OAuth refresh token missing. Re-run 'qwen auth qwen-oauth'.",
            provider="qwen-oauth",
            code="qwen_refresh_token_missing",
        )

    try:
        response = _core.httpx.post(
            _core.QWEN_OAUTH_TOKEN_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": _core.QWEN_OAUTH_CLIENT_ID,
            },
            timeout=timeout_seconds,
        )
    except Exception as exc:
        raise _core.AuthError(
            f"Qwen OAuth refresh failed: {exc}",
            provider="qwen-oauth",
            code="qwen_refresh_failed",
        ) from exc

    if response.status_code >= 400:
        body = response.text.strip()
        raise _core.AuthError(
            "Qwen OAuth refresh failed. Re-run 'qwen auth qwen-oauth'."
            + (f" Response: {body}" if body else ""),
            provider="qwen-oauth",
            code="qwen_refresh_failed",
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise _core.AuthError(
            f"Qwen OAuth refresh returned invalid JSON: {exc}",
            provider="qwen-oauth",
            code="qwen_refresh_invalid_json",
        ) from exc

    if (
        not isinstance(payload, dict)
        or not str(payload.get("access_token", "") or "").strip()
    ):
        raise _core.AuthError(
            "Qwen OAuth refresh response missing access_token.",
            provider="qwen-oauth",
            code="qwen_refresh_invalid_response",
        )

    expires_in = payload.get("expires_in")
    try:
        expires_in_seconds = int(expires_in)
    except Exception:
        expires_in_seconds = 6 * 60 * 60

    refreshed = {
        "access_token": str(payload.get("access_token", "") or "").strip(),
        "refresh_token": str(
            payload.get("refresh_token", refresh_token) or refresh_token
        ).strip(),
        "token_type": str(
            payload.get("token_type", tokens.get("token_type", "Bearer")) or "Bearer"
        ).strip()
        or "Bearer",
        "resource_url": str(
            payload.get("resource_url", tokens.get("resource_url", "portal.qwen.ai"))
            or "portal.qwen.ai"
        ).strip(),
        "expiry_date": int(_core.time.time() * 1000)
        + max(1, expires_in_seconds) * 1000,
    }
    _core._save_qwen_cli_tokens(refreshed)
    return refreshed


def resolve_qwen_runtime_credentials(
    *,
    force_refresh: bool = False,
    refresh_if_expiring: bool = True,
    refresh_skew_seconds: int = _core.QWEN_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
) -> _core.Dict[str, _core.Any]:
    tokens = _core._read_qwen_cli_tokens()
    access_token = str(tokens.get("access_token", "") or "").strip()
    should_refresh = bool(force_refresh)
    if not should_refresh and refresh_if_expiring:
        should_refresh = _core._qwen_access_token_is_expiring(
            tokens.get("expiry_date"), refresh_skew_seconds
        )
    if should_refresh:
        tokens = _core._refresh_qwen_cli_tokens(tokens)
        access_token = str(tokens.get("access_token", "") or "").strip()
    if not access_token:
        raise _core.AuthError(
            "Qwen OAuth access token missing. Re-run 'qwen auth qwen-oauth'.",
            provider="qwen-oauth",
            code="qwen_access_token_missing",
        )

    base_url = ""
    for env_name in _core._QWEN_BASE_URL_ENV_NAMES:
        base_url = _core.os.getenv(env_name, "").strip().rstrip("/")
        if base_url:
            break
    base_url = base_url or _core.DEFAULT_QWEN_BASE_URL
    return {
        "provider": "qwen-oauth",
        "base_url": base_url,
        "api_key": access_token,
        "source": "qwen-cli",
        "expires_at_ms": tokens.get("expiry_date"),
        "auth_file": str(_core._qwen_cli_auth_path()),
    }


def resolve_gemini_oauth_runtime_credentials(
    *,
    force_refresh: bool = False,
) -> _core.Dict[str, _core.Any]:
    """Resolve runtime OAuth creds for google-gemini-cli."""
    try:
        from agent.google_oauth import (
            GoogleOAuthError,
            _credentials_path,
            get_valid_access_token,
            load_credentials,
        )
    except ImportError as exc:
        raise _core.AuthError(
            f"agent.google_oauth is not importable: {exc}",
            provider="google-gemini-cli",
            code="google_oauth_module_missing",
        ) from exc

    try:
        access_token = get_valid_access_token(force_refresh=force_refresh)
    except GoogleOAuthError as exc:
        raise _core.AuthError(
            str(exc),
            provider="google-gemini-cli",
            code=exc.code,
        ) from exc

    creds = load_credentials()
    base_url = _core.DEFAULT_GEMINI_CLOUDCODE_BASE_URL
    return {
        "provider": "google-gemini-cli",
        "base_url": base_url,
        "api_key": access_token,
        "source": "google-oauth",
        "expires_at_ms": (creds.expires_ms if creds else None),
        "auth_file": str(_credentials_path()),
        "email": (creds.email if creds else "") or "",
        "project_id": (creds.project_id if creds else "") or "",
    }
