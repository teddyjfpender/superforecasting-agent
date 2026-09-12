"""Common operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _auth_command_hint() -> str:
    """Re-authentication hint offering BOTH paths (backtick-wrapped).

    Rather than guess the context, surface both ways to authenticate: the in-TUI
    ``/auth`` slash command (the device-code flow, tui_gateway/server.py) and the
    shell command ``superforecasting-agent auth``. Whichever surface the user is
    on, one of the two is the one they need.
    """
    return f"`/auth` (in the TUI) or `{_core._PRIMARY_CLI} auth` (from a shell)"


def is_rate_limited_auth_error(error: Exception) -> bool:
    """True when an :class:`AuthError` represents upstream rate-limiting / quota
    exhaustion rather than missing or invalid credentials.

    These failures are transient — re-authenticating cannot resolve them — so
    callers should surface a "retry later" notice and prefer a fallback chain
    instead of prompting the operator to re-authenticate.
    """
    return (
        isinstance(error, _core.AuthError)
        and not error.relogin_required
        and error.code == _core.CODEX_RATE_LIMITED_CODE
    )


def _parse_retry_after_seconds(headers: _core.Any) -> _core.Optional[int]:
    """Best-effort parse of a ``Retry-After`` header into whole seconds.

    Supports the delta-seconds form (e.g. ``"120"``). HTTP-date forms and
    missing/unparseable values return ``None`` rather than guessing.
    """
    if headers is None:
        return None
    try:
        raw = headers.get("retry-after")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        seconds = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def format_auth_error(error: Exception) -> str:
    """Map auth failures to concise user-facing guidance."""
    if not isinstance(error, _core.AuthError):
        return str(error)

    # Rate-limit / quota errors are not credential problems — never append the
    # "re-authenticate" remediation, which would mislead the operator.
    if _core.is_rate_limited_auth_error(error):
        return str(error)

    if error.relogin_required:
        return f"{error} Run `{_core._PRIMARY_CLI} model` to re-authenticate."

    if error.code == "subscription_required":
        return (
            "No active paid subscription found on Nous Portal. "
            "Please purchase/activate a subscription, then retry."
        )

    if error.code == "insufficient_credits":
        return (
            "Subscription credits are exhausted. "
            "Top up/renew credits in Nous Portal, then retry."
        )

    if error.code == "temporarily_unavailable":
        return f"{error} Please retry in a few seconds."

    return str(error)


def _token_fingerprint(token: _core.Any) -> _core.Optional[str]:
    """Return a short hash fingerprint for telemetry without leaking token bytes."""
    if not isinstance(token, str):
        return None
    cleaned = token.strip()
    if not cleaned:
        return None
    return _core.hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:12]


def _oauth_trace_enabled() -> bool:
    return _core.env_var_alias_enabled((
        "SUPERFORECASTING_AGENT_OAUTH_TRACE",
        "FORECAST_OAUTH_TRACE",
        "HERMES_OAUTH_TRACE",
    ))


def _oauth_trace(
    event: str, *, sequence_id: _core.Optional[str] = None, **fields: _core.Any
) -> None:
    if not _core._oauth_trace_enabled():
        return
    payload: _core.Dict[str, _core.Any] = {"event": event}
    if sequence_id:
        payload["sequence_id"] = sequence_id
    payload.update(fields)
    _core.logger.info(
        "oauth_trace %s", _core.json.dumps(payload, sort_keys=True, ensure_ascii=False)
    )


def _parse_iso_timestamp(value: _core.Any) -> _core.Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _core.datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_core.timezone.utc)
    return parsed.timestamp()


def _is_expiring(expires_at_iso: _core.Any, skew_seconds: int) -> bool:
    expires_epoch = _core._parse_iso_timestamp(expires_at_iso)
    if expires_epoch is None:
        return True
    return expires_epoch <= (_core.time.time() + skew_seconds)


def _coerce_ttl_seconds(expires_in: _core.Any) -> int:
    try:
        ttl = int(expires_in)
    except Exception:
        ttl = 0
    return max(0, ttl)


def _optional_base_url(value: _core.Any) -> _core.Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().rstrip("/")
    return cleaned if cleaned else None


def _decode_jwt_claims(token: _core.Any) -> _core.Dict[str, _core.Any]:
    if not isinstance(token, str) or token.count(".") != 2:
        return {}
    payload = token.split(".")[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        raw = _core.base64.urlsafe_b64decode(payload.encode("utf-8"))
        claims = _core.json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}


def _scope_values(raw_scope: _core.Any) -> set[str]:
    # OAuth token responses normally return a space-separated string. Keep
    # collection support for JWT ``scp`` claims and older stored test fixtures.
    scopes: set[str] = set()
    if isinstance(raw_scope, str):
        for part in raw_scope.replace(",", " ").split():
            cleaned = part.strip()
            if cleaned:
                scopes.add(cleaned)
    elif isinstance(raw_scope, (list, tuple, set, frozenset)):
        for item in raw_scope:
            if isinstance(item, str):
                scopes.update(_core._scope_values(item))
    return scopes


def _oauth_pkce_code_verifier(length: int = 64) -> str:
    raw = _core.base64.urlsafe_b64encode(_core.os.urandom(length)).decode("ascii")
    return raw.rstrip("=")[:128]


def _oauth_pkce_code_challenge(code_verifier: str) -> str:
    digest = _core.hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return _core.base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _default_verify() -> bool | _core.ssl.SSLContext:
    """Platform-aware default SSL verify for httpx clients.

    On macOS with Homebrew Python, the system OpenSSL cannot locate the
    system trust store and valid public certs fail verification. When
    certifi is importable we pin its bundle explicitly; elsewhere we
    defer to httpx's built-in default (certifi via its own dependency).
    Mirrors the weixin fix in 3a0ec1d93.
    """
    if _core.sys.platform == "darwin":
        try:
            import certifi

            return _core.ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
    return True


def _resolve_verify(
    *,
    insecure: _core.Optional[bool] = None,
    ca_bundle: _core.Optional[str] = None,
    auth_state: _core.Optional[_core.Dict[str, _core.Any]] = None,
) -> bool | _core.ssl.SSLContext:
    tls_state = auth_state.get("tls") if isinstance(auth_state, dict) else {}
    tls_state = tls_state if isinstance(tls_state, dict) else {}

    effective_insecure = (
        _core.is_truthy_value(insecure, default=False)
        if insecure is not None
        else _core.is_truthy_value(tls_state.get("insecure", False), default=False)
    )
    effective_ca = (
        ca_bundle
        or tls_state.get("ca_bundle")
        or _core.os.getenv("HERMES_CA_BUNDLE")
        or _core.os.getenv("SSL_CERT_FILE")
        or _core.os.getenv("REQUESTS_CA_BUNDLE")
    )

    if effective_insecure:
        return False
    if effective_ca:
        ca_path = str(effective_ca)
        if not _core.os.path.isfile(ca_path):
            _core.logger.warning(
                "CA bundle path does not exist: %s — falling back to default certificates",
                ca_path,
            )
            return _core._default_verify()
        return _core.ssl.create_default_context(cafile=ca_path)
    return _core._default_verify()
