"""Nous policy operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _nous_legacy_session_keys_forced() -> bool:
    return _core.is_truthy_value(
        _core.os.getenv(_core.NOUS_LEGACY_SESSION_KEYS_ENV), default=False
    )


def _nous_scope_has_invoke(raw_scope: _core.Any) -> bool:
    return _core.NOUS_INFERENCE_INVOKE_SCOPE in _core._scope_values(raw_scope)


def _normalize_nous_inference_auth_mode(
    inference_auth_mode: _core.Optional[str],
) -> str:
    mode = (
        str(inference_auth_mode or _core.NOUS_INFERENCE_AUTH_MODE_AUTO).strip().lower()
    )
    if mode not in _core.NOUS_INFERENCE_AUTH_MODES:
        allowed = ", ".join(sorted(_core.NOUS_INFERENCE_AUTH_MODES))
        raise ValueError(
            "Invalid Nous inference auth mode "
            f"{inference_auth_mode!r}; expected one of: {allowed}"
        )
    return mode


def _nous_invoke_jwt_status(
    token: _core.Any,
    *,
    scope: _core.Any = None,
    expires_at: _core.Any = None,
    min_ttl_seconds: int = _core.NOUS_INVOKE_JWT_MIN_TTL_SECONDS,
) -> _core.Optional[str]:
    """Return None when the token can be used for inference, else a reason."""
    claims = _core._decode_jwt_claims(token)
    if not claims:
        return "access_token_not_jwt"
    scopes = (
        _core._scope_values(scope)
        | _core._scope_values(claims.get("scope"))
        | _core._scope_values(claims.get("scp"))
    )
    if _core.NOUS_INFERENCE_INVOKE_SCOPE not in scopes:
        return "missing_inference_invoke_scope"
    exp = claims.get("exp")
    skew = max(0, int(min_ttl_seconds))
    if isinstance(exp, (int, float)):
        if float(exp) <= (_core.time.time() + skew):
            return "invoke_jwt_expiring"
        return None
    if _core._is_expiring(expires_at, skew):
        return "invoke_jwt_expiry_unknown_or_expiring"
    return None


def _nous_invoke_jwt_is_usable(
    token: _core.Any,
    *,
    scope: _core.Any = None,
    expires_at: _core.Any = None,
    min_ttl_seconds: int = _core.NOUS_INVOKE_JWT_MIN_TTL_SECONDS,
) -> bool:
    return (
        _core._nous_invoke_jwt_status(
            token,
            scope=scope,
            expires_at=expires_at,
            min_ttl_seconds=min_ttl_seconds,
        )
        is None
    )


def _nous_legacy_session_key_reason(
    token: _core.Any,
    *,
    scope: _core.Any = None,
    expires_at: _core.Any = None,
    inference_auth_mode: str = _core.NOUS_INFERENCE_AUTH_MODE_AUTO,
) -> str:
    if inference_auth_mode == _core.NOUS_INFERENCE_AUTH_MODE_LEGACY:
        return "forced_legacy_session_key"
    if _core._nous_legacy_session_keys_forced():
        return "forced_legacy_session_keys"
    return (
        _core._nous_invoke_jwt_status(token, scope=scope, expires_at=expires_at)
        or "invoke_jwt_unavailable"
    )


def _choose_nous_inference_auth_path(
    state: _core.Dict[str, _core.Any],
    *,
    access_token: _core.Any = None,
    min_key_ttl_seconds: int = _core.DEFAULT_AGENT_KEY_MIN_TTL_SECONDS,
    inference_auth_mode: str = _core.NOUS_INFERENCE_AUTH_MODE_AUTO,
) -> _core.Tuple[str, _core.Optional[str]]:
    inference_auth_mode = _core._normalize_nous_inference_auth_mode(inference_auth_mode)
    token = state.get("access_token") if access_token is None else access_token
    if (
        not _core._nous_legacy_session_keys_forced()
        and inference_auth_mode != _core.NOUS_INFERENCE_AUTH_MODE_LEGACY
        and _core._nous_invoke_jwt_is_usable(
            token,
            scope=state.get("scope"),
            expires_at=state.get("expires_at"),
        )
    ):
        return _core.NOUS_AUTH_PATH_INVOKE_JWT, None
    if (
        inference_auth_mode == _core.NOUS_INFERENCE_AUTH_MODE_AUTO
        and _core._agent_key_is_usable(
            state,
            max(60, int(min_key_ttl_seconds)),
        )
    ):
        return _core.NOUS_AUTH_PATH_LEGACY_SESSION_KEY_CACHE, None
    return (
        _core.NOUS_AUTH_PATH_LEGACY_SESSION_KEY_MINT,
        _core._nous_legacy_session_key_reason(
            token,
            scope=state.get("scope"),
            expires_at=state.get("expires_at"),
            inference_auth_mode=inference_auth_mode,
        ),
    )


def _log_nous_invoke_jwt_selected(
    *,
    access_token: _core.Any,
    sequence_id: _core.Optional[str] = None,
) -> None:
    _core.logger.info("Nous inference auth: using NAS invoke JWT")
    _core._oauth_trace(
        "nous_invoke_jwt_selected",
        sequence_id=sequence_id,
        access_token_fp=_core._token_fingerprint(access_token),
    )


def _log_nous_legacy_session_key_selected(
    reason: str,
    *,
    access_token: _core.Any,
    sequence_id: _core.Optional[str] = None,
) -> None:
    _core.logger.info(
        "Nous inference auth: using legacy session key path (%s)",
        reason,
    )
    _core._oauth_trace(
        "nous_legacy_session_key_selected",
        sequence_id=sequence_id,
        reason=reason,
        access_token_fp=_core._token_fingerprint(access_token),
    )


def _nous_jwt_expires_at(
    token: _core.Any, fallback_expires_at: _core.Any = None
) -> _core.Optional[str]:
    claims = _core._decode_jwt_claims(token)
    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        try:
            return _core.datetime.fromtimestamp(
                float(exp), tz=_core.timezone.utc
            ).isoformat()
        except Exception:
            pass
    return fallback_expires_at if isinstance(fallback_expires_at, str) else None


def _set_nous_agent_key_from_invoke_jwt(
    state: _core.Dict[str, _core.Any],
    *,
    obtained_at: _core.Optional[str] = None,
) -> None:
    access_token = state.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        return
    now = _core.datetime.now(_core.timezone.utc)
    existing_obtained_at = state.get("agent_key_obtained_at")
    if obtained_at:
        effective_obtained_at = obtained_at
    elif (
        state.get("agent_key") == access_token
        and isinstance(existing_obtained_at, str)
        and existing_obtained_at.strip()
    ):
        effective_obtained_at = existing_obtained_at
    else:
        effective_obtained_at = now.isoformat()
    expires_at = _core._nous_jwt_expires_at(access_token, state.get("expires_at"))
    expires_epoch = _core._parse_iso_timestamp(expires_at)
    expires_in = (
        max(0, int(expires_epoch - _core.time.time()))
        if expires_epoch is not None
        else _core._coerce_ttl_seconds(state.get("expires_in"))
    )
    if expires_at:
        state["expires_at"] = expires_at
        state["expires_in"] = expires_in
    state["agent_key"] = access_token
    state["agent_key_id"] = None
    state["agent_key_expires_at"] = expires_at
    state["agent_key_expires_in"] = expires_in
    state["agent_key_reused"] = False
    state["agent_key_obtained_at"] = effective_obtained_at


def _select_nous_invoke_jwt(
    state: _core.Dict[str, _core.Any],
    *,
    access_token: _core.Any = None,
    sequence_id: _core.Optional[str] = None,
) -> None:
    if isinstance(access_token, str) and access_token.strip():
        state["access_token"] = access_token
    _core._set_nous_agent_key_from_invoke_jwt(state)
    _core._log_nous_invoke_jwt_selected(
        access_token=state.get("access_token"),
        sequence_id=sequence_id,
    )


def _nous_effective_provider_state(
    state: _core.Dict[str, _core.Any],
) -> _core.Dict[str, _core.Any]:
    return {
        key: value
        for key, value in state.items()
        if key not in _core._NOUS_EFFECTIVE_STATE_IGNORED_KEYS
    }
