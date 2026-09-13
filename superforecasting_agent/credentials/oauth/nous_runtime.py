"""Nous runtime operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def resolve_nous_runtime_credentials(
    *,
    min_key_ttl_seconds: int = _core.DEFAULT_AGENT_KEY_MIN_TTL_SECONDS,
    timeout_seconds: float = 15.0,
    insecure: _core.Optional[bool] = None,
    ca_bundle: _core.Optional[str] = None,
    inference_auth_mode: str = _core.NOUS_INFERENCE_AUTH_MODE_AUTO,
) -> _core.Dict[str, _core.Any]:
    """
    Resolve Nous inference credentials for runtime use.

    Ensures access_token is valid (refreshes if needed) and a short-lived
    inference key is present with minimum TTL (mints/reuses as needed).
    Concurrent processes coordinate through the auth store file lock.

    Returns dict with: provider, base_url, api_key, key_id, expires_at,
    expires_in, source ("invoke_jwt", "cache", or "portal"), and auth_path.
    """
    inference_auth_mode = _core._normalize_nous_inference_auth_mode(inference_auth_mode)
    min_key_ttl_seconds = max(60, int(min_key_ttl_seconds))
    sequence_id = _core.uuid.uuid4().hex[:12]

    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        state = _core._load_provider_state(auth_store, "nous")

        if not state:
            raise _core.AuthError(
                "Superforecasting Agent is not logged into Nous Portal.",
                provider="nous",
                relogin_required=True,
            )

        persisted_state = dict(state)
        state_persisted = False

        portal_base_url = (
            _core._optional_base_url(state.get("portal_base_url"))
            or _core.nous_portal_base_url()
            or _core.DEFAULT_NOUS_PORTAL_URL
        ).rstrip("/")
        inference_base_url = (
            _core._optional_base_url(state.get("inference_base_url"))
            or _core.nous_inference_base_url()
            or _core.DEFAULT_NOUS_INFERENCE_URL
        ).rstrip("/")
        client_id = str(state.get("client_id") or _core.DEFAULT_NOUS_CLIENT_ID)

        def _persist_state(reason: str) -> None:
            nonlocal persisted_state, state_persisted
            # Skip writes where only derived TTL countdowns changed; this keeps
            # the mtime-keyed Nous auth-status cache warm during read paths.
            if _core._nous_effective_provider_state(
                state
            ) == _core._nous_effective_provider_state(persisted_state):
                _core._oauth_trace(
                    "nous_state_persist_skipped",
                    sequence_id=sequence_id,
                    reason=reason,
                )
                return
            try:
                _core._save_provider_state(auth_store, "nous", state)
                _core._save_auth_store(auth_store)
            except Exception as exc:
                _core._oauth_trace(
                    "nous_state_persist_failed",
                    sequence_id=sequence_id,
                    reason=reason,
                    error_type=type(exc).__name__,
                )
                raise
            _core._oauth_trace(
                "nous_state_persisted",
                sequence_id=sequence_id,
                reason=reason,
                refresh_token_fp=_core._token_fingerprint(state.get("refresh_token")),
                access_token_fp=_core._token_fingerprint(state.get("access_token")),
            )
            persisted_state = dict(state)
            state_persisted = True
            # Mirror post-refresh state to the shared store so sibling
            # profiles don't hold stale refresh_tokens after rotation.
            # Best-effort — any failure is logged and swallowed inside
            # _write_shared_nous_state.
            _core._write_shared_nous_state(state)

        verify = _core._resolve_verify(
            insecure=insecure, ca_bundle=ca_bundle, auth_state=state
        )
        timeout = _core.httpx.Timeout(timeout_seconds if timeout_seconds else 15.0)
        _core._oauth_trace(
            "nous_runtime_credentials_start",
            sequence_id=sequence_id,
            inference_auth_mode=inference_auth_mode,
            min_key_ttl_seconds=min_key_ttl_seconds,
            refresh_token_fp=_core._token_fingerprint(state.get("refresh_token")),
        )

        with _core.httpx.Client(
            timeout=timeout, headers={"Accept": "application/json"}, verify=verify
        ) as client:
            access_token = state.get("access_token")
            refresh_token = state.get("refresh_token")

            if not isinstance(access_token, str) or not access_token:
                raise _core.AuthError(
                    "No access token found for Nous Portal login.",
                    provider="nous",
                    relogin_required=True,
                )

            # Step 1: refresh access token if expiring. If the access token
            # is already a valid invoke JWT, trust its own exp claim even when
            # older auth.json metadata has a stale/missing expires_at.
            current_invoke_jwt_usable = (
                not _core._nous_legacy_session_keys_forced()
                and _core._nous_invoke_jwt_is_usable(
                    access_token,
                    scope=state.get("scope"),
                    expires_at=state.get("expires_at"),
                )
            )
            if (
                _core._is_expiring(
                    state.get("expires_at"), _core.ACCESS_TOKEN_REFRESH_SKEW_SECONDS
                )
                and not current_invoke_jwt_usable
            ):
                with _core._nous_shared_store_lock(
                    timeout_seconds=max(
                        timeout_seconds + 5.0, _core.AUTH_LOCK_TIMEOUT_SECONDS
                    )
                ):
                    if _core._merge_shared_nous_oauth_state(state):
                        access_token = state.get("access_token")
                        refresh_token = state.get("refresh_token")
                        _persist_state("post_shared_merge_access_expiring")

                    if _core._is_expiring(
                        state.get("expires_at"), _core.ACCESS_TOKEN_REFRESH_SKEW_SECONDS
                    ) and not _core._nous_invoke_jwt_is_usable(
                        access_token,
                        scope=state.get("scope"),
                        expires_at=state.get("expires_at"),
                    ):
                        if not isinstance(refresh_token, str) or not refresh_token:
                            raise _core.AuthError(
                                "Session expired and no refresh token is available.",
                                provider="nous",
                                relogin_required=True,
                            )

                        _core._oauth_trace(
                            "refresh_start",
                            sequence_id=sequence_id,
                            reason="access_expiring",
                            refresh_token_fp=_core._token_fingerprint(refresh_token),
                        )
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
                                    reason="runtime_access_refresh_failure",
                                )
                                _core._quarantine_nous_pool_entries(
                                    auth_store,
                                    exc,
                                    reason="runtime_access_refresh_failure",
                                )
                                _persist_state(
                                    "terminal_runtime_access_refresh_failure"
                                )
                            raise
                        now = _core.datetime.now(_core.timezone.utc)
                        access_ttl = _core._coerce_ttl_seconds(
                            refreshed.get("expires_in")
                        )
                        previous_refresh_token = refresh_token
                        state["access_token"] = refreshed["access_token"]
                        state["refresh_token"] = (
                            refreshed.get("refresh_token") or refresh_token
                        )
                        state["token_type"] = (
                            refreshed.get("token_type")
                            or state.get("token_type")
                            or "Bearer"
                        )
                        state["scope"] = refreshed.get("scope") or state.get("scope")
                        refreshed_url = _core._optional_base_url(
                            refreshed.get("inference_base_url")
                        )
                        if refreshed_url:
                            inference_base_url = refreshed_url
                        state["obtained_at"] = now.isoformat()
                        state["expires_in"] = access_ttl
                        state["expires_at"] = _core.datetime.fromtimestamp(
                            now.timestamp() + access_ttl, tz=_core.timezone.utc
                        ).isoformat()
                        access_token = state["access_token"]
                        refresh_token = state["refresh_token"]
                        _core._oauth_trace(
                            "refresh_success",
                            sequence_id=sequence_id,
                            reason="access_expiring",
                            previous_refresh_token_fp=_core._token_fingerprint(
                                previous_refresh_token
                            ),
                            new_refresh_token_fp=_core._token_fingerprint(
                                refresh_token
                            ),
                        )
                        # Persist immediately so downstream mint failures cannot drop rotated refresh tokens.
                        _persist_state("post_refresh_access_expiring")

            # Step 2: resolve the compatibility ``agent_key`` field. Preferred
            # path stores the NAS invoke JWT there; legacy path mints/reuses
            # the opaque session key.
            used_cached_key = False
            mint_payload: _core.Optional[_core.Dict[str, _core.Any]] = None
            selected_auth_path, fallback_reason = (
                _core._choose_nous_inference_auth_path(
                    state,
                    access_token=access_token,
                    min_key_ttl_seconds=min_key_ttl_seconds,
                    inference_auth_mode=inference_auth_mode,
                )
            )

            if selected_auth_path == _core.NOUS_AUTH_PATH_INVOKE_JWT:
                _core._select_nous_invoke_jwt(
                    state,
                    access_token=access_token,
                    sequence_id=sequence_id,
                )
            elif selected_auth_path == _core.NOUS_AUTH_PATH_LEGACY_SESSION_KEY_CACHE:
                used_cached_key = True
                _core.logger.info("Nous inference auth: using cached agent_key")
                _core._oauth_trace("agent_key_reuse", sequence_id=sequence_id)
            else:
                _core._log_nous_legacy_session_key_selected(
                    fallback_reason or "legacy_session_key_required",
                    access_token=access_token,
                    sequence_id=sequence_id,
                )
                try:
                    _core._oauth_trace(
                        "mint_start",
                        sequence_id=sequence_id,
                        access_token_fp=_core._token_fingerprint(access_token),
                    )
                    mint_payload = _core._mint_agent_key(
                        client=client,
                        portal_base_url=portal_base_url,
                        access_token=access_token,
                        min_ttl_seconds=min_key_ttl_seconds,
                    )
                except _core.AuthError as exc:
                    _core._oauth_trace(
                        "mint_error",
                        sequence_id=sequence_id,
                        code=exc.code,
                    )
                    # Retry path: access token may be stale server-side despite local checks
                    latest_refresh_token = state.get("refresh_token")
                    if (
                        exc.code in {"invalid_token", "invalid_grant"}
                        and isinstance(latest_refresh_token, str)
                        and latest_refresh_token
                    ):
                        with _core._nous_shared_store_lock(
                            timeout_seconds=max(
                                timeout_seconds + 5.0, _core.AUTH_LOCK_TIMEOUT_SECONDS
                            )
                        ):
                            if _core._merge_shared_nous_oauth_state(state):
                                access_token = state.get("access_token")
                                latest_refresh_token = state.get("refresh_token")
                                _persist_state("post_shared_merge_mint_retry")
                            else:
                                _core._oauth_trace(
                                    "refresh_start",
                                    sequence_id=sequence_id,
                                    reason="mint_retry_after_invalid_token",
                                    refresh_token_fp=_core._token_fingerprint(
                                        latest_refresh_token
                                    ),
                                )
                                try:
                                    refreshed = _core._refresh_access_token(
                                        client=client,
                                        portal_base_url=portal_base_url,
                                        client_id=client_id,
                                        refresh_token=latest_refresh_token,
                                    )
                                except _core.AuthError as exc:
                                    if _core._is_terminal_nous_refresh_error(exc):
                                        _core._quarantine_nous_oauth_state(
                                            state,
                                            exc,
                                            reason="runtime_mint_retry_refresh_failure",
                                        )
                                        _core._quarantine_nous_pool_entries(
                                            auth_store,
                                            exc,
                                            reason="runtime_mint_retry_refresh_failure",
                                        )
                                        _persist_state(
                                            "terminal_runtime_mint_retry_refresh_failure"
                                        )
                                    raise
                                now = _core.datetime.now(_core.timezone.utc)
                                access_ttl = _core._coerce_ttl_seconds(
                                    refreshed.get("expires_in")
                                )
                                state["access_token"] = refreshed["access_token"]
                                state["refresh_token"] = (
                                    refreshed.get("refresh_token")
                                    or latest_refresh_token
                                )
                                state["token_type"] = (
                                    refreshed.get("token_type")
                                    or state.get("token_type")
                                    or "Bearer"
                                )
                                state["scope"] = refreshed.get("scope") or state.get(
                                    "scope"
                                )
                                refreshed_url = _core._optional_base_url(
                                    refreshed.get("inference_base_url")
                                )
                                if refreshed_url:
                                    inference_base_url = refreshed_url
                                state["obtained_at"] = now.isoformat()
                                state["expires_in"] = access_ttl
                                state["expires_at"] = _core.datetime.fromtimestamp(
                                    now.timestamp() + access_ttl, tz=_core.timezone.utc
                                ).isoformat()
                                access_token = state["access_token"]
                                refresh_token = state["refresh_token"]
                                _core._oauth_trace(
                                    "refresh_success",
                                    sequence_id=sequence_id,
                                    reason="mint_retry_after_invalid_token",
                                    previous_refresh_token_fp=_core._token_fingerprint(
                                        latest_refresh_token
                                    ),
                                    new_refresh_token_fp=_core._token_fingerprint(
                                        refresh_token
                                    ),
                                )
                                # Persist retry refresh immediately for crash safety and cross-process visibility.
                                _persist_state("post_refresh_mint_retry")

                        retry_inference_auth_mode = (
                            _core.NOUS_INFERENCE_AUTH_MODE_LEGACY
                            if inference_auth_mode
                            == _core.NOUS_INFERENCE_AUTH_MODE_LEGACY
                            else _core.NOUS_INFERENCE_AUTH_MODE_FRESH
                        )
                        retry_auth_path, _ = _core._choose_nous_inference_auth_path(
                            state,
                            access_token=access_token,
                            min_key_ttl_seconds=min_key_ttl_seconds,
                            inference_auth_mode=retry_inference_auth_mode,
                        )
                        if retry_auth_path == _core.NOUS_AUTH_PATH_INVOKE_JWT:
                            mint_payload = None
                            selected_auth_path = _core.NOUS_AUTH_PATH_INVOKE_JWT
                            _core._select_nous_invoke_jwt(
                                state,
                                access_token=access_token,
                                sequence_id=sequence_id,
                            )
                        else:
                            mint_payload = _core._mint_agent_key(
                                client=client,
                                portal_base_url=portal_base_url,
                                access_token=access_token,
                                min_ttl_seconds=min_key_ttl_seconds,
                            )
                    else:
                        raise

            if mint_payload is not None:
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
                    inference_base_url = minted_url
                _core._oauth_trace(
                    "mint_success",
                    sequence_id=sequence_id,
                    reused=bool(mint_payload.get("reused", False)),
                )

            # Persist routing and TLS metadata for non-interactive refresh/mint
            state["portal_base_url"] = portal_base_url
            state["inference_base_url"] = inference_base_url
            state["client_id"] = client_id
            state["tls"] = {
                "insecure": verify is False,
                "ca_bundle": verify if isinstance(verify, str) else None,
            }

        _persist_state("resolve_nous_runtime_credentials_final")

    if state_persisted:
        _core._sync_nous_pool_from_auth_store()

    api_key = state.get("agent_key")
    if not isinstance(api_key, str) or not api_key:
        raise _core.AuthError(
            "Failed to resolve a Nous inference API key",
            provider="nous",
            code="server_error",
        )

    expires_at = state.get("agent_key_expires_at")
    expires_epoch = _core._parse_iso_timestamp(expires_at)
    expires_in = (
        max(0, int(expires_epoch - _core.time.time()))
        if expires_epoch is not None
        else _core._coerce_ttl_seconds(state.get("agent_key_expires_in"))
    )

    return {
        "provider": "nous",
        "base_url": inference_base_url,
        "api_key": api_key,
        "key_id": state.get("agent_key_id"),
        "expires_at": expires_at,
        "expires_in": expires_in,
        "source": (
            _core.NOUS_AUTH_PATH_INVOKE_JWT
            if selected_auth_path == _core.NOUS_AUTH_PATH_INVOKE_JWT
            else ("cache" if used_cached_key else "portal")
        ),
        "auth_path": selected_auth_path,
    }
