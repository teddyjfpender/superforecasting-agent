"""Codex operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _codex_access_token_is_expiring(access_token: _core.Any, skew_seconds: int) -> bool:
    claims = _core._decode_jwt_claims(access_token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return float(exp) <= (_core.time.time() + max(0, int(skew_seconds)))


def _read_codex_tokens(*, _lock: bool = True) -> _core.Dict[str, _core.Any]:
    """Read Codex OAuth tokens from Hermes auth store (~/.hermes/auth.json).

    Returns dict with 'tokens' (access_token, refresh_token) and 'last_refresh'.
    Raises AuthError if no Codex tokens are stored.
    """
    if _lock:
        with _core._auth_store_lock():
            auth_store = _core._load_auth_store()
    else:
        auth_store = _core._load_auth_store()
    state = _core._load_provider_state(auth_store, "openai-codex")
    if not state:
        raise _core.AuthError(
            f"No Codex credentials stored. Run {_core._auth_command_hint()} to authenticate.",
            provider="openai-codex",
            code="codex_auth_missing",
            relogin_required=True,
        )
    tokens = state.get("tokens")
    if not isinstance(tokens, dict):
        raise _core.AuthError(
            f"Codex auth state is missing tokens. Run {_core._auth_command_hint()} to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_invalid_shape",
            relogin_required=True,
        )
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise _core.AuthError(
            f"Codex auth is missing access_token. Run {_core._auth_command_hint()} to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_missing_access_token",
            relogin_required=True,
        )
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise _core.AuthError(
            f"Codex auth is missing refresh_token. Run {_core._auth_command_hint()} to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_missing_refresh_token",
            relogin_required=True,
        )
    return {
        "tokens": tokens,
        "last_refresh": state.get("last_refresh"),
    }


def _sync_codex_pool_entries(
    auth_store: _core.Dict[str, _core.Any],
    tokens: _core.Dict[str, str],
    last_refresh: _core.Optional[str],
    previous_singleton_tokens: _core.Optional[_core.Dict[str, str]] = None,
) -> None:
    """Mirror a fresh Codex re-auth into the credential_pool OAuth entries.

    The runtime selects credentials from ``credential_pool.openai-codex``, not
    from ``providers.openai-codex.tokens``.  A re-auth invalidates the prior
    OAuth pair server-side, but pool entries keep holding the now-consumed
    refresh token plus any stale error markers — so the next request spends a
    dead token and gets a 401 ``token_invalidated``.

    What gets refreshed:

    * ``device_code`` — the singleton-seeded entry written by the device-code
      OAuth flow when the user logged in via setup / the model picker.
      Always synced with the fresh tokens.
    * ``manual:device_code`` — entries created by ``auth add openai-codex``
      that use the same device-code OAuth mechanism.  ONLY synced if the
      entry's existing access_token matches the *previous* singleton
      access_token (i.e. the entry is a legacy singleton-alias from the
      #33000 workaround era).  Manual entries whose tokens never matched the
      singleton represent INDEPENDENT accounts added via
      ``auth add openai-codex`` and must not be overwritten by a
      re-auth that targeted a different account (regression for #39236).

      The original #33538 fix refreshed every ``manual:device_code`` entry
      unconditionally.  That worked when ``manual:device_code`` only meant
      "legacy alias of the singleton", but the same source string is now
      also produced by independent-account additions, and the broad sync
      silently clobbered distinct accounts with the latest-authenticated
      token pair.  The access_token-match check distinguishes the two cases
      without changing the source-string contract.

    What does NOT get refreshed:

    * ``manual:api_key`` and any other non-device-code manual sources — those
      are independent credentials (an explicit API key, a different ChatGPT
      account, etc.) and must not be overwritten by a single re-auth.
    * ``manual:device_code`` entries whose access_token does NOT match the
      previous singleton — see above; these are independent accounts.

    Error markers (``last_status``, ``last_error_*``) are cleared ONLY on
    entries that actually had their tokens rewritten by this re-auth.
    Independent entries keep their own error state (their 401/429 markers
    belong to that account's own auth flow, not this re-auth).
    """
    access_token = tokens.get("access_token")
    if not access_token:
        return
    refresh_token = tokens.get("refresh_token")
    pool = auth_store.get("credential_pool")
    if not isinstance(pool, dict):
        return
    entries = pool.get("openai-codex")
    if not isinstance(entries, list):
        return
    # Previous singleton access_token (before this re-auth overwrote it) —
    # used to distinguish legacy singleton-aliases from independent accounts.
    # When None or empty, no manual entry can be treated as an alias (which
    # is the right default for first-ever-save or a freshly initialized
    # auth.json).
    prev_at = None
    if isinstance(previous_singleton_tokens, dict):
        prev_at = previous_singleton_tokens.get("access_token") or None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source")
        if source == "device_code":
            # Singleton-seeded mirror — always refresh.
            refresh_this_entry = True
        elif source == "manual:device_code":
            # Refresh only if this entry's existing access_token matches the
            # previous singleton access_token (i.e. it is a true alias of the
            # singleton from the #33000 workaround era).  An entry with its
            # own distinct token material is an independent account and must
            # be left alone (#39236).
            refresh_this_entry = bool(prev_at and entry.get("access_token") == prev_at)
        else:
            # ``manual:api_key`` and any future non-device-code sources.
            refresh_this_entry = False
        if not refresh_this_entry:
            continue
        entry["access_token"] = access_token
        if refresh_token:
            entry["refresh_token"] = refresh_token
        if last_refresh:
            entry["last_refresh"] = last_refresh
        entry["last_status"] = None
        entry["last_status_at"] = None
        entry["last_error_code"] = None
        entry["last_error_reason"] = None
        entry["last_error_message"] = None
        entry["last_error_reset_at"] = None


def _save_codex_tokens(
    tokens: _core.Dict[str, str],
    last_refresh: str | None = None,
    label: str | None = None,
) -> None:
    """Save Codex OAuth tokens to the runtime auth store."""
    if last_refresh is None:
        last_refresh = (
            _core.datetime.now(_core.timezone.utc).isoformat().replace("+00:00", "Z")
        )
    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        state = _core._load_provider_state(auth_store, "openai-codex") or {}
        # Capture the previous singleton tokens BEFORE overwriting them.  The
        # pool-sync step uses this to distinguish legacy singleton-aliases
        # (which should be refreshed) from independent accounts that
        # ``auth add openai-codex`` created (which must not be
        # overwritten — see #39236).
        previous_singleton_tokens = (
            state.get("tokens") if isinstance(state.get("tokens"), dict) else None
        )
        state["tokens"] = tokens
        state["last_refresh"] = last_refresh
        state["auth_mode"] = "chatgpt"
        if label and str(label).strip():
            state["label"] = str(label).strip()
        _core._save_provider_state(auth_store, "openai-codex", state)
        _core._sync_codex_pool_entries(
            auth_store,
            tokens,
            last_refresh,
            previous_singleton_tokens=previous_singleton_tokens,
        )
        _core._save_auth_store(auth_store)


def refresh_codex_oauth_pure(
    access_token: str,
    refresh_token: str,
    *,
    timeout_seconds: float = 20.0,
) -> _core.Dict[str, _core.Any]:
    """Refresh Codex OAuth tokens without mutating Hermes auth state."""
    del (
        access_token
    )  # Access token is only used by callers to decide whether to refresh.
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise _core.AuthError(
            f"Codex auth is missing refresh_token. Run {_core._auth_command_hint()} to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_missing_refresh_token",
            relogin_required=True,
        )

    timeout = _core.httpx.Timeout(max(5.0, float(timeout_seconds)))
    with _core.httpx.Client(
        timeout=timeout, headers={"Accept": "application/json"}
    ) as client:
        response = client.post(
            _core.CODEX_OAUTH_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": _core.CODEX_OAUTH_CLIENT_ID,
            },
        )

    if response.status_code == 429:
        # Upstream rate-limit / usage-quota exhaustion on the token endpoint.
        # The stored refresh token is still valid here — re-authenticating
        # cannot lift a quota cap. Classify distinctly from auth failures so
        # callers surface a "retry later" notice instead of a misleading
        # re-auth prompt (see upstream issue #32790).
        retry_after = _core._parse_retry_after_seconds(
            getattr(response, "headers", None)
        )
        if retry_after is not None:
            message = (
                f"Codex provider quota exhausted (429); retry after {retry_after}s. "
                "Credentials are still valid."
            )
        else:
            message = (
                "Codex provider quota exhausted (429). Credentials are still valid; "
                "retry after the usage limit resets."
            )
        raise _core.AuthError(
            message,
            provider="openai-codex",
            code=_core.CODEX_RATE_LIMITED_CODE,
            relogin_required=False,
        )

    if response.status_code != 200:
        code = "codex_refresh_failed"
        message = f"Codex token refresh failed with status {response.status_code}."
        relogin_required = False
        try:
            err = response.json()
            if isinstance(err, dict):
                err_obj = err.get("error")
                # OpenAI shape: {"error": {"code": "...", "message": "...", "type": "..."}}
                if isinstance(err_obj, dict):
                    nested_code = err_obj.get("code") or err_obj.get("type")
                    if isinstance(nested_code, str) and nested_code.strip():
                        code = nested_code.strip()
                    nested_msg = err_obj.get("message")
                    if isinstance(nested_msg, str) and nested_msg.strip():
                        message = f"Codex token refresh failed: {nested_msg.strip()}"
                # OAuth spec shape: {"error": "code_str", "error_description": "..."}
                elif isinstance(err_obj, str) and err_obj.strip():
                    code = err_obj.strip()
                    err_desc = err.get("error_description") or err.get("message")
                    if isinstance(err_desc, str) and err_desc.strip():
                        message = f"Codex token refresh failed: {err_desc.strip()}"
        except Exception:
            pass
        if code in {"invalid_grant", "invalid_token", "invalid_request"}:
            relogin_required = True
        if code == "refresh_token_reused":
            message = (
                "Codex refresh token was already consumed by another client "
                "(e.g. Codex CLI or VS Code extension). "
                "Run `codex` in your terminal to generate fresh tokens, "
                f"then run `{_core._PRIMARY_CLI} auth` to re-authenticate."
            )
            relogin_required = True
        # A 401/403 from the token endpoint always means the refresh token
        # is invalid/expired — force relogin even if the body error code
        # wasn't one of the known strings above.
        if response.status_code in {401, 403} and not relogin_required:
            relogin_required = True
        raise _core.AuthError(
            message,
            provider="openai-codex",
            code=code,
            relogin_required=relogin_required,
        )

    try:
        refresh_payload = response.json()
    except Exception as exc:
        raise _core.AuthError(
            "Codex token refresh returned invalid JSON.",
            provider="openai-codex",
            code="codex_refresh_invalid_json",
            relogin_required=True,
        ) from exc

    refreshed_access = refresh_payload.get("access_token")
    if not isinstance(refreshed_access, str) or not refreshed_access.strip():
        raise _core.AuthError(
            "Codex token refresh response was missing access_token.",
            provider="openai-codex",
            code="codex_refresh_missing_access_token",
            relogin_required=True,
        )

    updated = {
        "access_token": refreshed_access.strip(),
        "refresh_token": refresh_token.strip(),
        "last_refresh": _core.datetime
        .now(_core.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    next_refresh = refresh_payload.get("refresh_token")
    if isinstance(next_refresh, str) and next_refresh.strip():
        updated["refresh_token"] = next_refresh.strip()
    return updated


def _refresh_codex_auth_tokens(
    tokens: _core.Dict[str, str],
    timeout_seconds: float,
) -> _core.Dict[str, str]:
    """Refresh Codex access token using the refresh token.

    Saves the new tokens to Hermes auth store automatically.
    """
    refreshed = _core.refresh_codex_oauth_pure(
        str(tokens.get("access_token", "") or ""),
        str(tokens.get("refresh_token", "") or ""),
        timeout_seconds=timeout_seconds,
    )
    updated_tokens = dict(tokens)
    updated_tokens["access_token"] = refreshed["access_token"]
    updated_tokens["refresh_token"] = refreshed["refresh_token"]

    _core._save_codex_tokens(updated_tokens)
    return updated_tokens


def _import_codex_cli_tokens() -> _core.Optional[_core.Dict[str, str]]:
    """Try to read tokens from ~/.codex/auth.json (Codex CLI shared file).

    Returns tokens dict if valid and not expired, None otherwise.
    Does NOT write to the shared file.
    """
    codex_home = _core.os.getenv("CODEX_HOME", "").strip()
    if not codex_home:
        codex_home = str(_core.Path.home() / ".codex")
    auth_path = _core.Path(codex_home).expanduser() / "auth.json"
    if not auth_path.is_file():
        return None
    try:
        payload = _core.json.loads(auth_path.read_text())
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            return None
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if not access_token or not refresh_token:
            return None
        # Reject expired tokens — importing stale tokens from ~/.codex/
        # that can't be refreshed leaves the user stuck with "Login successful!"
        # but no working credentials.
        if _core._codex_access_token_is_expiring(access_token, 0):
            _core.logger.debug(
                "Codex CLI tokens at %s are expired — skipping import.",
                auth_path,
            )
            return None
        return dict(tokens)
    except Exception:
        return None


def resolve_codex_runtime_credentials(
    *,
    force_refresh: bool = False,
    refresh_if_expiring: bool = True,
    refresh_skew_seconds: int = _core.CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
) -> _core.Dict[str, _core.Any]:
    """Resolve runtime credentials from Hermes's own Codex token store."""
    data = _core._read_codex_tokens()
    tokens = dict(data["tokens"])
    access_token = str(tokens.get("access_token", "") or "").strip()
    refresh_timeout_seconds = float(
        _core.os.getenv("HERMES_CODEX_REFRESH_TIMEOUT_SECONDS", "20")
    )

    should_refresh = bool(force_refresh)
    if (not should_refresh) and refresh_if_expiring:
        should_refresh = _core._codex_access_token_is_expiring(
            access_token, refresh_skew_seconds
        )
    if should_refresh:
        # Re-read under lock to avoid racing with other Hermes processes
        with _core._auth_store_lock(
            timeout_seconds=max(
                float(_core.AUTH_LOCK_TIMEOUT_SECONDS), refresh_timeout_seconds + 5.0
            )
        ):
            data = _core._read_codex_tokens(_lock=False)
            tokens = dict(data["tokens"])
            access_token = str(tokens.get("access_token", "") or "").strip()

            should_refresh = bool(force_refresh)
            if (not should_refresh) and refresh_if_expiring:
                should_refresh = _core._codex_access_token_is_expiring(
                    access_token, refresh_skew_seconds
                )

            if should_refresh:
                tokens = _core._refresh_codex_auth_tokens(
                    tokens, refresh_timeout_seconds
                )
                access_token = str(tokens.get("access_token", "") or "").strip()

    base_url = (
        _core.os.getenv("HERMES_CODEX_BASE_URL", "").strip().rstrip("/")
        or _core.DEFAULT_CODEX_BASE_URL
    )

    return {
        "provider": "openai-codex",
        "base_url": base_url,
        "api_key": access_token,
        "source": "hermes-auth-store",
        "last_refresh": data.get("last_refresh"),
        "auth_mode": "chatgpt",
    }


def _is_terminal_codex_oauth_refresh_error(exc: Exception) -> bool:
    """True when retrying the same Codex OAuth refresh token cannot succeed.

    ``codex_refresh_failed`` covers HTTP 400/401/403 from the token endpoint
    (invalid_grant, token revoked, refresh_token_reused).
    ``codex_auth_missing_refresh_token`` means the pool entry has no refresh
    token at all — retrying will never work.
    Both carry ``relogin_required=True``; transient failures (429, 5xx) do not.
    """
    return (
        isinstance(exc, _core.AuthError)
        and exc.provider == "openai-codex"
        and exc.code
        in {
            "codex_refresh_failed",
            "codex_auth_missing_refresh_token",
            "invalid_grant",
            "invalid_token",
            "refresh_token_reused",
        }
        and bool(exc.relogin_required)
    )
