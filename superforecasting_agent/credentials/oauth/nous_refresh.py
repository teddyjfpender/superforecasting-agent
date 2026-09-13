"""Nous refresh operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _refresh_access_token(
    *,
    client: _core.httpx.Client,
    portal_base_url: str,
    client_id: str,
    refresh_token: str,
) -> _core.Dict[str, _core.Any]:
    response = client.post(
        f"{portal_base_url}/api/oauth/token",
        headers={"x-nous-refresh-token": refresh_token},
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
        },
    )

    if response.status_code == 200:
        payload = response.json()
        if "access_token" not in payload:
            raise _core.AuthError(
                "Refresh response missing access_token",
                provider="nous",
                code="invalid_token",
                relogin_required=True,
            )
        return payload

    try:
        error_payload = response.json()
    except Exception as exc:
        raise _core.AuthError(
            "Refresh token exchange failed", provider="nous", relogin_required=True
        ) from exc

    code = str(error_payload.get("error", "invalid_grant"))
    description = str(
        error_payload.get("error_description") or "Refresh token exchange failed"
    )
    relogin = code in {"invalid_grant", "invalid_token", "refresh_token_reused"}

    # Detect the OAuth 2.1 "refresh token reuse" signal from the Nous portal
    # server and surface an actionable message.  This fires when an external
    # process (health-check script, monitoring tool, custom self-heal hook)
    # called POST /api/oauth/token with Hermes's refresh_token without
    # persisting the rotated token back to auth.json — the server then
    # retires the original RT, Hermes's next refresh uses it, and the whole
    # session chain gets revoked as a token-theft signal (#15099).
    lowered = description.lower()
    if (
        code == "refresh_token_reused"
        or "reuse" in lowered
        or "reuse detected" in lowered
    ):
        description = (
            "Nous Portal detected refresh-token reuse and revoked this session.\n"
            "This usually means an external process (monitoring script, "
            "custom self-heal hook, or another Superforecasting Agent install sharing "
            "the runtime auth store) called POST /api/oauth/token with this "
            "refresh token without persisting the rotated token back.\n"
            "Nous refresh tokens are single-use — only Superforecasting Agent may call the "
            f"refresh endpoint. For health checks, use `{_core._PRIMARY_CLI} auth status` "
            "instead.\n"
            f"Re-authenticate with: {_core._PRIMARY_CLI} auth add nous"
        )
        relogin = True

    raise _core.AuthError(
        description, provider="nous", code=code, relogin_required=relogin
    )


def _mint_agent_key(
    *,
    client: _core.httpx.Client,
    portal_base_url: str,
    access_token: str | None,
    min_ttl_seconds: int,
) -> _core.Dict[str, _core.Any]:
    """Mint (or reuse) a short-lived inference API key."""
    if not isinstance(access_token, str) or not access_token.strip():
        raise _core.AuthError(
            "Missing access token for key minting",
            provider="nous",
            code="not_authenticated",
        )
    response = client.post(
        f"{portal_base_url}/api/oauth/agent-key",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"min_ttl_seconds": max(60, int(min_ttl_seconds))},
    )

    if response.status_code == 200:
        payload = response.json()
        if "api_key" not in payload:
            raise _core.AuthError(
                "Mint response missing api_key", provider="nous", code="server_error"
            )
        return payload

    try:
        error_payload = response.json()
    except Exception as exc:
        raise _core.AuthError(
            "Agent key mint request failed", provider="nous", code="server_error"
        ) from exc

    code = str(error_payload.get("error", "server_error"))
    description = str(
        error_payload.get("error_description") or "Agent key mint request failed"
    )
    relogin = code in {"invalid_token", "invalid_grant"}
    raise _core.AuthError(
        description, provider="nous", code=code, relogin_required=relogin
    )


def fetch_nous_models(
    *,
    inference_base_url: str,
    api_key: str,
    timeout_seconds: float = 15.0,
    verify: bool | str = True,
) -> _core.List[str]:
    """Fetch available model IDs from the Nous inference API."""
    timeout = _core.httpx.Timeout(timeout_seconds)
    with _core.httpx.Client(
        timeout=timeout, headers={"Accept": "application/json"}, verify=verify
    ) as client:
        response = client.get(
            f"{inference_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )

    if response.status_code != 200:
        description = f"/models request failed with status {response.status_code}"
        try:
            err = response.json()
            description = str(
                err.get("error_description") or err.get("error") or description
            )
        except Exception as e:
            _core.logger.debug("Could not parse error response JSON: %s", e)
        raise _core.AuthError(description, provider="nous", code="models_fetch_failed")

    payload = response.json()
    data = payload.get("data")
    if not isinstance(data, list):
        return []

    model_ids: _core.List[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id.strip():
            mid = model_id.strip()
            # Skip Hermes models — they're not reliable for agentic tool-calling
            if "hermes" in mid.lower():
                continue
            model_ids.append(mid)

    # Sort: prefer opus > pro > haiku/flash > sonnet (sonnet is cheap/fast,
    # users who want the best model should see opus first).
    def _model_priority(mid: str) -> tuple:
        low = mid.lower()
        if "opus" in low:
            return (0, mid)
        if "pro" in low and "sonnet" not in low:
            return (1, mid)
        if "sonnet" in low:
            return (3, mid)
        return (2, mid)

    model_ids.sort(key=_model_priority)
    return list(dict.fromkeys(model_ids))


def _agent_key_is_usable(
    state: _core.Dict[str, _core.Any], min_ttl_seconds: int
) -> bool:
    key = state.get("agent_key")
    if not isinstance(key, str) or not key.strip():
        return False
    if _core._decode_jwt_claims(key):
        if _core._nous_legacy_session_keys_forced():
            return False
        return _core._nous_invoke_jwt_is_usable(
            key,
            scope=state.get("scope"),
            expires_at=state.get("agent_key_expires_at"),
        )
    return not _core._is_expiring(state.get("agent_key_expires_at"), min_ttl_seconds)


def resolve_nous_access_token(
    *,
    timeout_seconds: float = 15.0,
    insecure: _core.Optional[bool] = None,
    ca_bundle: _core.Optional[str] = None,
    refresh_skew_seconds: int = _core.ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
) -> str:
    """Resolve a refresh-aware Nous Portal access token for managed tool gateways."""
    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        state = _core._load_provider_state(auth_store, "nous")

        if not state:
            raise _core.AuthError(
                "Superforecasting Agent is not logged into Nous Portal.",
                provider="nous",
                relogin_required=True,
            )

        portal_base_url = (
            _core._optional_base_url(state.get("portal_base_url"))
            or _core.nous_portal_base_url()
            or _core.DEFAULT_NOUS_PORTAL_URL
        ).rstrip("/")
        client_id = str(state.get("client_id") or _core.DEFAULT_NOUS_CLIENT_ID)
        verify = _core._resolve_verify(
            insecure=insecure, ca_bundle=ca_bundle, auth_state=state
        )

        with _core._nous_shared_store_lock(
            timeout_seconds=max(timeout_seconds + 5.0, _core.AUTH_LOCK_TIMEOUT_SECONDS)
        ):
            merged_shared = _core._merge_shared_nous_oauth_state(state)
            access_token = state.get("access_token")
            refresh_token = state.get("refresh_token")
            if not isinstance(access_token, str) or not access_token:
                raise _core.AuthError(
                    "No access token found for Nous Portal login.",
                    provider="nous",
                    relogin_required=True,
                )

            if not _core._is_expiring(state.get("expires_at"), refresh_skew_seconds):
                if merged_shared:
                    _core._save_provider_state(auth_store, "nous", state)
                    _core._save_auth_store(auth_store)
                return access_token

            if not isinstance(refresh_token, str) or not refresh_token:
                raise _core.AuthError(
                    "Session expired and no refresh token is available.",
                    provider="nous",
                    relogin_required=True,
                )

            timeout = _core.httpx.Timeout(timeout_seconds if timeout_seconds else 15.0)
            with _core.httpx.Client(
                timeout=timeout,
                headers={"Accept": "application/json"},
                verify=verify,
            ) as client:
                try:
                    refreshed = _core._refresh_access_token(
                        client=client,
                        portal_base_url=portal_base_url,
                        client_id=client_id,
                        refresh_token=refresh_token,
                    )
                except _core.AuthError as exc:
                    if _core._is_terminal_nous_refresh_error(exc):
                        _core._quarantine_nous_oauth_state(
                            state,
                            exc,
                            reason="managed_access_token_refresh_failure",
                        )
                        _core._quarantine_nous_pool_entries(
                            auth_store,
                            exc,
                            reason="managed_access_token_refresh_failure",
                        )
                        _core._save_provider_state(auth_store, "nous", state)
                        _core._save_auth_store(auth_store)
                    raise

            now = _core.datetime.now(_core.timezone.utc)
            access_ttl = _core._coerce_ttl_seconds(refreshed.get("expires_in"))
            state["access_token"] = refreshed["access_token"]
            state["refresh_token"] = refreshed.get("refresh_token") or refresh_token
            state["token_type"] = (
                refreshed.get("token_type") or state.get("token_type") or "Bearer"
            )
            state["scope"] = refreshed.get("scope") or state.get("scope")
            state["obtained_at"] = now.isoformat()
            state["expires_in"] = access_ttl
            state["expires_at"] = _core.datetime.fromtimestamp(
                now.timestamp() + access_ttl,
                tz=_core.timezone.utc,
            ).isoformat()
            state["portal_base_url"] = portal_base_url
            state["client_id"] = client_id
            state["tls"] = {
                "insecure": verify is False,
                "ca_bundle": verify if isinstance(verify, str) else None,
            }
            _core._save_provider_state(auth_store, "nous", state)
            _core._save_auth_store(auth_store)
            _core._write_shared_nous_state(state)
            return state["access_token"]


def refresh_nous_oauth_pure(
    access_token: str,
    refresh_token: str,
    client_id: str,
    portal_base_url: str,
    inference_base_url: str,
    *,
    token_type: str = "Bearer",
    scope: str = _core.DEFAULT_NOUS_SCOPE,
    obtained_at: _core.Optional[str] = None,
    expires_at: _core.Optional[str] = None,
    agent_key: _core.Optional[str] = None,
    agent_key_expires_at: _core.Optional[str] = None,
    min_key_ttl_seconds: int = _core.DEFAULT_AGENT_KEY_MIN_TTL_SECONDS,
    timeout_seconds: float = 15.0,
    insecure: _core.Optional[bool] = None,
    ca_bundle: _core.Optional[str] = None,
    force_refresh: bool = False,
    inference_auth_mode: str = _core.NOUS_INFERENCE_AUTH_MODE_AUTO,
    on_state_update: _core.Optional[
        _core.Callable[[_core.Dict[str, _core.Any], str], None]
    ] = None,
) -> _core.Dict[str, _core.Any]:
    """Refresh Nous OAuth state without mutating auth.json directly.

    ``on_state_update`` is called after a successful access-token refresh and
    before any subsequent agent-key mint. Callers that own persistent state can
    use it to save the newly rotated refresh token before later work can fail.
    """
    inference_auth_mode = _core._normalize_nous_inference_auth_mode(inference_auth_mode)
    state: _core.Dict[str, _core.Any] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "client_id": client_id or _core.DEFAULT_NOUS_CLIENT_ID,
        "portal_base_url": (portal_base_url or _core.DEFAULT_NOUS_PORTAL_URL).rstrip(
            "/"
        ),
        "inference_base_url": (
            inference_base_url or _core.DEFAULT_NOUS_INFERENCE_URL
        ).rstrip("/"),
        "token_type": token_type or "Bearer",
        "scope": scope or _core.DEFAULT_NOUS_SCOPE,
        "obtained_at": obtained_at,
        "expires_at": expires_at,
        "agent_key": agent_key,
        "agent_key_expires_at": agent_key_expires_at,
        "tls": {
            "insecure": bool(insecure),
            "ca_bundle": ca_bundle,
        },
    }
    verify = _core._resolve_verify(
        insecure=insecure, ca_bundle=ca_bundle, auth_state=state
    )
    timeout = _core.httpx.Timeout(timeout_seconds if timeout_seconds else 15.0)

    with _core.httpx.Client(
        timeout=timeout, headers={"Accept": "application/json"}, verify=verify
    ) as client:
        min_agent_key_ttl = max(60, int(min_key_ttl_seconds))
        legacy_session_keys = _core._nous_legacy_session_keys_forced()
        current_invoke_jwt_usable = (
            not legacy_session_keys
            and _core._nous_invoke_jwt_is_usable(
                state.get("access_token"),
                scope=state.get("scope"),
                expires_at=state.get("expires_at"),
            )
        )
        if force_refresh or (
            _core._is_expiring(
                state.get("expires_at"), _core.ACCESS_TOKEN_REFRESH_SKEW_SECONDS
            )
            and not current_invoke_jwt_usable
        ):
            refreshed = _core._refresh_access_token(
                client=client,
                portal_base_url=state["portal_base_url"],
                client_id=state["client_id"],
                refresh_token=state["refresh_token"],
            )
            now = _core.datetime.now(_core.timezone.utc)
            access_ttl = _core._coerce_ttl_seconds(refreshed.get("expires_in"))
            state["access_token"] = refreshed["access_token"]
            state["refresh_token"] = (
                refreshed.get("refresh_token") or state["refresh_token"]
            )
            state["token_type"] = (
                refreshed.get("token_type") or state.get("token_type") or "Bearer"
            )
            state["scope"] = refreshed.get("scope") or state.get("scope")
            refreshed_url = _core._optional_base_url(
                refreshed.get("inference_base_url")
            )
            if refreshed_url:
                state["inference_base_url"] = refreshed_url
            state["obtained_at"] = now.isoformat()
            state["expires_in"] = access_ttl
            state["expires_at"] = _core.datetime.fromtimestamp(
                now.timestamp() + access_ttl, tz=_core.timezone.utc
            ).isoformat()
            if on_state_update is not None:
                on_state_update(dict(state), "post_refresh_access_token")

        selected_auth_path, fallback_reason = _core._choose_nous_inference_auth_path(
            state,
            min_key_ttl_seconds=min_agent_key_ttl,
            inference_auth_mode=inference_auth_mode,
        )
        if selected_auth_path == _core.NOUS_AUTH_PATH_INVOKE_JWT:
            _core._select_nous_invoke_jwt(state)
        elif selected_auth_path == _core.NOUS_AUTH_PATH_LEGACY_SESSION_KEY_MINT:
            _core._log_nous_legacy_session_key_selected(
                fallback_reason or "legacy_session_key_required",
                access_token=state.get("access_token"),
            )
            mint_payload = _core._mint_agent_key(
                client=client,
                portal_base_url=state["portal_base_url"],
                access_token=state["access_token"],
                min_ttl_seconds=min_key_ttl_seconds,
            )
            now = _core.datetime.now(_core.timezone.utc)
            state["agent_key"] = mint_payload.get("api_key")
            state["agent_key_id"] = mint_payload.get("key_id")
            state["agent_key_expires_at"] = mint_payload.get("expires_at")
            state["agent_key_expires_in"] = mint_payload.get("expires_in")
            state["agent_key_reused"] = bool(mint_payload.get("reused", False))
            state["agent_key_obtained_at"] = now.isoformat()
            minted_url = _core._optional_base_url(
                mint_payload.get("inference_base_url")
            )
            if minted_url:
                state["inference_base_url"] = minted_url

    return state


def refresh_nous_oauth_from_state(
    state: _core.Dict[str, _core.Any],
    *,
    min_key_ttl_seconds: int = _core.DEFAULT_AGENT_KEY_MIN_TTL_SECONDS,
    timeout_seconds: float = 15.0,
    force_refresh: bool = False,
    inference_auth_mode: str = _core.NOUS_INFERENCE_AUTH_MODE_AUTO,
    on_state_update: _core.Optional[
        _core.Callable[[_core.Dict[str, _core.Any], str], None]
    ] = None,
) -> _core.Dict[str, _core.Any]:
    """Refresh Nous OAuth from a state dict. Thin wrapper around refresh_nous_oauth_pure."""
    tls = state.get("tls") or {}
    return _core.refresh_nous_oauth_pure(
        state.get("access_token", ""),
        state.get("refresh_token", ""),
        state.get("client_id", "hermes-cli"),
        state.get("portal_base_url", _core.DEFAULT_NOUS_PORTAL_URL),
        state.get("inference_base_url", _core.DEFAULT_NOUS_INFERENCE_URL),
        token_type=state.get("token_type", "Bearer"),
        scope=state.get("scope", _core.DEFAULT_NOUS_SCOPE),
        obtained_at=state.get("obtained_at"),
        expires_at=state.get("expires_at"),
        agent_key=state.get("agent_key"),
        agent_key_expires_at=state.get("agent_key_expires_at"),
        min_key_ttl_seconds=min_key_ttl_seconds,
        timeout_seconds=timeout_seconds,
        insecure=tls.get("insecure"),
        ca_bundle=tls.get("ca_bundle"),
        force_refresh=force_refresh,
        inference_auth_mode=inference_auth_mode,
        on_state_update=on_state_update,
    )


def persist_nous_credentials(
    creds: _core.Dict[str, _core.Any],
    *,
    label: _core.Optional[str] = None,
):
    """Persist minted Nous OAuth credentials as the singleton provider state
    and ensure the credential pool is in sync.

    Nous credentials are read at runtime from two independent locations:

    - ``providers.nous``: singleton state read by
      ``resolve_nous_runtime_credentials()`` during 401 recovery and by
      ``_seed_from_singletons()`` during pool load.
    - ``credential_pool.nous``: used by the runtime ``pool.select()`` path.

    Historically ``superforecasting-agent auth add nous`` wrote a ``manual:device_code`` pool
    entry only, skipping ``providers.nous``.  When the 24h agent_key TTL
    expired, the recovery path read the empty singleton state and raised
    ``AuthError`` silently (``logger.debug`` at INFO level).

    This helper writes ``providers.nous`` then calls ``load_pool("nous")`` so
    ``_seed_from_singletons`` materialises the canonical ``device_code`` pool
    entry from the singleton.  Re-running login upserts the same entry in
    place; the pool never accumulates duplicate device_code rows.

    ``label`` is an optional user-chosen display name (from
    ``superforecasting-agent auth add nous --label <name>``).  It gets embedded in the
    singleton state so that ``_seed_from_singletons`` uses it as the pool
    entry's label on every subsequent ``load_pool("nous")`` instead of the
    auto-derived token fingerprint.  When ``None``, the auto-derived label
    via ``label_from_token`` is used (unchanged default behaviour).

    Returns the upserted :class:`PooledCredential` entry (or ``None`` if
    seeding somehow produced no match — shouldn't happen).
    """
    from agent.credential_pool import load_pool

    state = dict(creds)
    if label and str(label).strip():
        state["label"] = str(label).strip()

    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        _core._save_provider_state(auth_store, "nous", state)
        _core._save_auth_store(auth_store)

    # Mirror to the shared store so a new profile can one-tap import
    # these credentials via `superforecasting-agent auth add nous --type oauth`. Best-
    # effort: any I/O failure is logged and swallowed (the per-profile
    # auth.json is still the source of truth).
    _core._write_shared_nous_state(state)

    pool = load_pool("nous")
    return next(
        (e for e in pool.entries() if e.source == _core.NOUS_DEVICE_CODE_SOURCE),
        None,
    )


def _sync_nous_pool_from_auth_store() -> None:
    """Best-effort pool reseed after providers.nous changes; never fail login."""
    try:
        from agent.credential_pool import load_pool

        load_pool("nous")
    except Exception as exc:
        _core.logger.debug(
            "Failed to sync Nous credential pool from auth store: %s", exc
        )
