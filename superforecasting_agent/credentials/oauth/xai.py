"""Xai operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _read_xai_oauth_tokens(*, _lock: bool = True) -> _core.Dict[str, _core.Any]:
    if _lock:
        with _core._auth_store_lock():
            auth_store = _core._load_auth_store()
    else:
        auth_store = _core._load_auth_store()
    state = _core._load_provider_state(auth_store, "xai-oauth")
    if not state:
        raise _core.AuthError(
            "No xAI OAuth credentials stored. Select xAI Grok OAuth "
            f"(SuperGrok Subscription) in `{_core._PRIMARY_CLI} model`.",
            provider="xai-oauth",
            code="xai_auth_missing",
            relogin_required=True,
        )
    tokens = state.get("tokens")
    if not isinstance(tokens, dict):
        raise _core.AuthError(
            f"xAI OAuth state is missing tokens. Re-authenticate with `{_core._PRIMARY_CLI} model`.",
            provider="xai-oauth",
            code="xai_auth_invalid_shape",
            relogin_required=True,
        )
    access_token = str(tokens.get("access_token", "") or "").strip()
    refresh_token = str(tokens.get("refresh_token", "") or "").strip()
    if not access_token:
        raise _core.AuthError(
            f"xAI OAuth state is missing access_token. Re-authenticate with `{_core._PRIMARY_CLI} model`.",
            provider="xai-oauth",
            code="xai_auth_missing_access_token",
            relogin_required=True,
        )
    if not refresh_token:
        raise _core.AuthError(
            f"xAI OAuth state is missing refresh_token. Re-authenticate with `{_core._PRIMARY_CLI} model`.",
            provider="xai-oauth",
            code="xai_auth_missing_refresh_token",
            relogin_required=True,
        )
    return {
        "tokens": tokens,
        "last_refresh": state.get("last_refresh"),
        "discovery": state.get("discovery") or {},
        "redirect_uri": state.get("redirect_uri"),
    }


def _save_xai_oauth_tokens(
    tokens: _core.Dict[str, _core.Any],
    *,
    discovery: _core.Optional[_core.Dict[str, _core.Any]] = None,
    redirect_uri: str = "",
    last_refresh: _core.Optional[str] = None,
) -> None:
    if last_refresh is None:
        last_refresh = (
            _core.datetime.now(_core.timezone.utc).isoformat().replace("+00:00", "Z")
        )
    with _core._auth_store_lock():
        auth_store = _core._load_auth_store()
        state = _core._load_provider_state(auth_store, "xai-oauth") or {}
        state["tokens"] = tokens
        state["last_refresh"] = last_refresh
        state["auth_mode"] = "oauth_pkce"
        if discovery:
            state["discovery"] = discovery
        if redirect_uri:
            state["redirect_uri"] = redirect_uri
        _core._save_provider_state(auth_store, "xai-oauth", state)
        _core._save_auth_store(auth_store)


def _xai_access_token_is_expiring(access_token: str, skew_seconds: int = 0) -> bool:
    if not isinstance(access_token, str) or "." not in access_token:
        return False
    try:
        parts = access_token.split(".")
        if len(parts) < 2:
            return False
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = _core.json.loads(
            _core.base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
        )
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)):
            return False
        return float(exp) <= (_core.time.time() + max(0, int(skew_seconds)))
    except Exception:
        return False


def _xai_validate_oauth_endpoint(url: str, *, field: str) -> str:
    """Refuse any OIDC discovery endpoint that isn't HTTPS on the xAI origin.

    The OIDC discovery response is a long-lived, low-frequency request whose
    output is cached in ``~/.hermes/auth.json``. A single MITM during initial
    login could substitute a malicious ``token_endpoint``; that URL would
    then receive the refresh_token on every subsequent refresh — a permanent
    credential leak from a one-time MITM. Validating scheme + host pins the
    cached endpoint to the xAI auth origin (or a future ``*.x.ai`` subdomain
    if xAI migrates) so the cache poisoning loses its persistence guarantee.

    RFC 8414 §2 requires the issuer to be ``https://`` and SHOULD-keeps the
    token_endpoint on the same origin; we enforce both. ``x.ai`` is the
    bare apex, so we accept either exact host match or any ``.x.ai`` suffix.
    """
    parsed = _core.urlparse(url)
    if parsed.scheme != "https":
        raise _core.AuthError(
            f"xAI OIDC discovery returned a non-HTTPS {field}: {url!r}.",
            provider="xai-oauth",
            code="xai_discovery_invalid",
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise _core.AuthError(
            f"xAI OIDC discovery {field} is missing a hostname: {url!r}.",
            provider="xai-oauth",
            code="xai_discovery_invalid",
        )
    if host != "x.ai" and not host.endswith(".x.ai"):
        raise _core.AuthError(
            f"xAI OIDC discovery {field} host {host!r} is not on the xAI origin "
            f"(expected x.ai or a *.x.ai subdomain). Refusing to use a cached "
            f"endpoint that may have been substituted by a MITM during initial "
            f"discovery; re-authenticate with `{_core._PRIMARY_CLI} model` to re-fetch.",
            provider="xai-oauth",
            code="xai_discovery_invalid",
        )
    return url


def _xai_validate_inference_base_url(value: str, *, fallback: str) -> str:
    """Refuse a non-xAI base_url for the OAuth-authenticated inference path.

    The xAI Grok OAuth bearer is a high-value, long-lived credential tied to
    the user's SuperGrok subscription. ``XAI_BASE_URL`` / ``HERMES_XAI_BASE_URL``
    let users repoint the inference endpoint (handy for staging or a local
    proxy), but the env override is also a credential-leak vector: a tampered
    ``.env`` or hostile shell init that sets
    ``XAI_BASE_URL=https://attacker.example/v1`` would ship the OAuth access
    token to a third party on every request, silently.

    Pin the inference origin to ``api.x.ai`` (or any ``*.x.ai`` subdomain xAI
    may add). On rejection, fall back to the default and log a warning rather
    than raise — a bad env var should not deadlock authentication, but it
    should also never leak the bearer.

    ``value`` is the already-stripped, trailing-slash-trimmed candidate from
    env. Empty input returns ``fallback`` unchanged.
    """
    candidate = (value or "").strip().rstrip("/")
    if not candidate:
        return fallback
    try:
        parsed = _core.urlparse(candidate)
    except Exception:
        _core.logger.warning(
            "Ignoring malformed xAI base_url override %r; using %s instead.",
            candidate,
            fallback,
        )
        return fallback
    if parsed.scheme != "https":
        _core.logger.warning(
            "Refusing non-HTTPS xAI base_url override %r (xai-oauth bearer would "
            "be sent in cleartext); falling back to %s.",
            candidate,
            fallback,
        )
        return fallback
    host = (parsed.hostname or "").lower()
    if not host:
        _core.logger.warning(
            "Ignoring xAI base_url override %r with no hostname; using %s instead.",
            candidate,
            fallback,
        )
        return fallback
    if host != "x.ai" and not host.endswith(".x.ai"):
        _core.logger.warning(
            "Refusing xAI base_url override %r — host %r is not on the xAI origin "
            "(expected x.ai or a *.x.ai subdomain). The xai-oauth bearer is only "
            "valid against xAI's inference API; sending it elsewhere would leak "
            "the credential. Falling back to %s.",
            candidate,
            host,
            fallback,
        )
        return fallback
    return candidate


def _xai_oauth_discovery(timeout_seconds: float = 15.0) -> _core.Dict[str, str]:
    try:
        response = _core.httpx.get(
            _core.XAI_OAUTH_DISCOVERY_URL,
            headers={"Accept": "application/json"},
            timeout=timeout_seconds,
        )
    except Exception as exc:
        raise _core.AuthError(
            f"xAI OIDC discovery failed: {exc}",
            provider="xai-oauth",
            code="xai_discovery_failed",
        ) from exc
    if response.status_code != 200:
        raise _core.AuthError(
            f"xAI OIDC discovery returned status {response.status_code}.",
            provider="xai-oauth",
            code="xai_discovery_failed",
        )
    try:
        payload = response.json()
    except Exception as exc:
        raise _core.AuthError(
            f"xAI OIDC discovery returned invalid JSON: {exc}",
            provider="xai-oauth",
            code="xai_discovery_invalid_json",
        ) from exc
    if not isinstance(payload, dict):
        raise _core.AuthError(
            "xAI OIDC discovery response was not a JSON object.",
            provider="xai-oauth",
            code="xai_discovery_incomplete",
        )
    authorization_endpoint = str(
        payload.get("authorization_endpoint", "") or ""
    ).strip()
    token_endpoint = str(payload.get("token_endpoint", "") or "").strip()
    if not authorization_endpoint or not token_endpoint:
        raise _core.AuthError(
            "xAI OIDC discovery response was missing required endpoints.",
            provider="xai-oauth",
            code="xai_discovery_incomplete",
        )
    _core._xai_validate_oauth_endpoint(
        authorization_endpoint, field="authorization_endpoint"
    )
    _core._xai_validate_oauth_endpoint(token_endpoint, field="token_endpoint")
    return {
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
    }


def refresh_xai_oauth_pure(
    access_token: str,
    refresh_token: str,
    *,
    token_endpoint: str = "",
    timeout_seconds: float = 20.0,
) -> _core.Dict[str, _core.Any]:
    del access_token
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise _core.AuthError(
            f"xAI OAuth is missing refresh_token. Re-authenticate with `{_core._PRIMARY_CLI} model`.",
            provider="xai-oauth",
            code="xai_auth_missing_refresh_token",
            relogin_required=True,
        )
    endpoint = (
        token_endpoint.strip()
        or _core._xai_oauth_discovery(timeout_seconds)["token_endpoint"]
    )
    # Re-validate cached endpoints on the refresh hot path: an auth.json
    # written by an older runtime (or hand-edited) may carry a non-xAI
    # token_endpoint that would receive every future refresh_token in
    # plaintext if we trusted it blindly. Cheap suffix check; fast-fail
    # with a clear error so the user can re-run `superforecasting-agent model` to refetch.
    _core._xai_validate_oauth_endpoint(endpoint, field="token_endpoint")
    timeout = _core.httpx.Timeout(max(5.0, float(timeout_seconds)))
    with _core.httpx.Client(
        timeout=timeout, headers={"Accept": "application/json"}
    ) as client:
        response = client.post(
            endpoint,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "client_id": _core.XAI_OAUTH_CLIENT_ID,
                "refresh_token": refresh_token,
            },
        )
    if response.status_code != 200:
        detail = response.text.strip()
        # ``403`` from xAI's token endpoint is almost always a tier /
        # entitlement gate (the OAuth grant exists but the account isn't
        # on the allowlist for API access). Re-running
        # ``superforecasting-agent model``
        # won't fix that — surface a separate error code so
        # ``format_auth_error`` doesn't append a misleading
        # re-authenticate hint, and point users at the ``XAI_API_KEY``
        # fallback.  See #26847.
        if response.status_code == 403:
            raise _core.AuthError(
                "xAI token refresh failed with HTTP 403."
                + (f" Response: {detail}" if detail else "")
                + " This OAuth account is not authorized for xAI API"
                " access — xAI may be restricting API/OAuth use to"
                " specific SuperGrok tiers despite the in-app"
                " subscription being active. Re-logging in won't"
                " change that; set ``XAI_API_KEY`` and switch to"
                " ``provider: xai`` (API-key path) if available, or"
                " upgrade your subscription at https://x.ai/grok.",
                provider="xai-oauth",
                code="xai_oauth_tier_denied",
                relogin_required=False,
            )
        raise _core.AuthError(
            "xAI token refresh failed." + (f" Response: {detail}" if detail else ""),
            provider="xai-oauth",
            code="xai_refresh_failed",
            relogin_required=(response.status_code in {400, 401}),
        )
    try:
        payload = response.json()
    except Exception as exc:
        raise _core.AuthError(
            f"xAI token refresh returned invalid JSON: {exc}",
            provider="xai-oauth",
            code="xai_refresh_invalid_json",
        ) from exc
    if not isinstance(payload, dict):
        raise _core.AuthError(
            "xAI token refresh response was not a JSON object.",
            provider="xai-oauth",
            code="xai_refresh_invalid_response",
            relogin_required=True,
        )
    refreshed_access = str(payload.get("access_token", "") or "").strip()
    if not refreshed_access:
        raise _core.AuthError(
            "xAI token refresh response was missing access_token.",
            provider="xai-oauth",
            code="xai_refresh_missing_access_token",
            relogin_required=True,
        )
    updated = {
        "access_token": refreshed_access,
        "refresh_token": str(payload.get("refresh_token") or refresh_token).strip(),
        "id_token": str(payload.get("id_token") or "").strip(),
        "expires_in": payload.get("expires_in"),
        "token_type": str(payload.get("token_type") or "Bearer").strip() or "Bearer",
        "last_refresh": _core.datetime
        .now(_core.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    return updated


def _refresh_xai_oauth_tokens(
    tokens: _core.Dict[str, _core.Any],
    *,
    token_endpoint: str,
    redirect_uri: str = "",
    timeout_seconds: float,
) -> _core.Dict[str, _core.Any]:
    refreshed = _core.refresh_xai_oauth_pure(
        str(tokens.get("access_token", "") or ""),
        str(tokens.get("refresh_token", "") or ""),
        token_endpoint=token_endpoint,
        timeout_seconds=timeout_seconds,
    )
    updated_tokens = dict(tokens)
    updated_tokens["access_token"] = refreshed["access_token"]
    updated_tokens["refresh_token"] = refreshed["refresh_token"]
    if refreshed.get("id_token"):
        updated_tokens["id_token"] = refreshed["id_token"]
    if refreshed.get("expires_in") is not None:
        updated_tokens["expires_in"] = refreshed["expires_in"]
    if refreshed.get("token_type"):
        updated_tokens["token_type"] = refreshed["token_type"]
    _core._save_xai_oauth_tokens(
        updated_tokens,
        discovery={"token_endpoint": token_endpoint},
        redirect_uri=redirect_uri,
        last_refresh=refreshed["last_refresh"],
    )
    return updated_tokens


def resolve_xai_oauth_runtime_credentials(
    *,
    force_refresh: bool = False,
    refresh_if_expiring: bool = True,
    refresh_skew_seconds: int = _core.XAI_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
) -> _core.Dict[str, _core.Any]:
    data = _core._read_xai_oauth_tokens()
    tokens = dict(data["tokens"])
    access_token = str(tokens.get("access_token", "") or "").strip()
    refresh_timeout_seconds = float(
        _core.os.getenv("HERMES_XAI_REFRESH_TIMEOUT_SECONDS", "20")
    )
    discovery = dict(data.get("discovery") or {})
    token_endpoint = str(discovery.get("token_endpoint", "") or "").strip()
    redirect_uri = str(data.get("redirect_uri", "") or "").strip()

    should_refresh = bool(force_refresh)
    if (not should_refresh) and refresh_if_expiring:
        should_refresh = _core._xai_access_token_is_expiring(
            access_token, refresh_skew_seconds
        )
    if should_refresh:
        with _core._auth_store_lock(
            timeout_seconds=max(
                float(_core.AUTH_LOCK_TIMEOUT_SECONDS), refresh_timeout_seconds + 5.0
            )
        ):
            data = _core._read_xai_oauth_tokens(_lock=False)
            tokens = dict(data["tokens"])
            access_token = str(tokens.get("access_token", "") or "").strip()
            discovery = dict(data.get("discovery") or {})
            token_endpoint = str(discovery.get("token_endpoint", "") or "").strip()
            redirect_uri = str(data.get("redirect_uri", "") or "").strip()
            should_refresh = bool(force_refresh)
            if (not should_refresh) and refresh_if_expiring:
                should_refresh = _core._xai_access_token_is_expiring(
                    access_token, refresh_skew_seconds
                )
            if should_refresh:
                if not token_endpoint:
                    token_endpoint = _core._xai_oauth_discovery(
                        refresh_timeout_seconds
                    )["token_endpoint"]
                try:
                    tokens = _core._refresh_xai_oauth_tokens(
                        tokens,
                        token_endpoint=token_endpoint,
                        redirect_uri=redirect_uri,
                        timeout_seconds=refresh_timeout_seconds,
                    )
                    access_token = str(tokens.get("access_token", "") or "").strip()
                except _core.AuthError as exc:
                    if _core._is_terminal_xai_oauth_refresh_error(exc):
                        # Terminal failure (HTTP 400/401/403 — invalid_grant, token revoked).
                        # Clear dead tokens from auth.json so subsequent sessions fail fast
                        # without a network retry. Mirrors credential_pool.py quarantine.
                        try:
                            _q_store = _core._load_auth_store()
                            _q_state = (
                                _core._load_provider_state(_q_store, "xai-oauth") or {}
                            )
                            _q_tokens = dict(_q_state.get("tokens") or {})
                            _q_tokens.pop("access_token", None)
                            _q_tokens.pop("refresh_token", None)
                            _q_state["tokens"] = _q_tokens
                            _q_state["last_auth_error"] = {
                                "provider": "xai-oauth",
                                "code": exc.code or "xai_refresh_failed",
                                "message": str(exc),
                                "reason": "runtime_refresh_failure",
                                "relogin_required": True,
                                "at": _core.datetime.now(
                                    _core.timezone.utc
                                ).isoformat(),
                            }
                            _core._store_provider_state(
                                _q_store, "xai-oauth", _q_state, set_active=False
                            )
                            _core._save_auth_store(_q_store)
                        except Exception as _save_exc:
                            _core.logger.debug(
                                "xAI OAuth: failed to persist quarantined state: %s",
                                _save_exc,
                            )
                    raise

    base_url = _core._xai_validate_inference_base_url(
        _core.os.getenv("HERMES_XAI_BASE_URL", "").strip().rstrip("/")
        or _core.os.getenv("XAI_BASE_URL", "").strip().rstrip("/"),
        fallback=_core.DEFAULT_XAI_OAUTH_BASE_URL,
    )
    return {
        "provider": "xai-oauth",
        "base_url": base_url,
        "api_key": access_token,
        "source": "hermes-auth-store",
        "last_refresh": data.get("last_refresh"),
        "auth_mode": "oauth_pkce",
    }


def _is_terminal_xai_oauth_refresh_error(exc: Exception) -> bool:
    """True when retrying the same xAI OAuth refresh token cannot succeed.

    ``xai_refresh_failed`` covers HTTP 400/401/403 from the token endpoint
    (invalid_grant, token revoked, refresh_token_reused).
    ``xai_auth_missing_refresh_token`` means the pool entry has no refresh
    token at all — retrying will never work.
    Both carry ``relogin_required=True``; transient failures (429, 5xx) do not.
    """
    return (
        isinstance(exc, _core.AuthError)
        and exc.provider == "xai-oauth"
        and exc.code in {"xai_refresh_failed", "xai_auth_missing_refresh_token"}
        and bool(exc.relogin_required)
    )


def _xai_oauth_build_authorize_url(
    *,
    authorization_endpoint: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    nonce: str,
) -> str:
    # `plan=generic` opts the consent screen into xAI's generic OAuth plan
    # tier instead of falling back to the per-account default. Without it,
    # accounts.x.ai rejects loopback OAuth from non-allowlisted clients.
    # `referrer=superforecasting-agent` lets xAI attribute fork-originated
    # logins in their OAuth server logs (we still impersonate the upstream
    # Grok-CLI client_id; this is best-effort attribution until xAI mints us
    # our own).
    authorize_params = {
        "response_type": "code",
        "client_id": _core.XAI_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": _core.XAI_OAUTH_SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce,
        "plan": "generic",
        "referrer": "superforecasting-agent",
    }
    return f"{authorization_endpoint}?{_core.urlencode(authorize_params)}"


def _xai_oauth_exchange_code_for_tokens(
    *,
    token_endpoint: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    code_challenge: str,
    timeout_seconds: float = 20.0,
) -> _core.Dict[str, _core.Any]:
    """POST the authorization code to xAI's token endpoint and return
    the parsed JSON payload.

    Sends ``code_verifier`` as required by RFC 7636 §4.5.  Also echoes
    ``code_challenge`` + ``code_challenge_method`` in the request body
    as a defense-in-depth measure for OAuth servers (xAI's among them,
    per #26990) that re-validate the challenge at the token step
    instead of relying solely on server-side session state captured
    during the authorize step.  Echoing the challenge is harmless for
    strict RFC-compliant servers — RFC 7636 doesn't forbid additional
    parameters at the token endpoint — and decisively fixes the
    ``code_challenge is required`` failure mode users hit on the
    loopback flow.

    Raises :class:`AuthError` on any non-2xx response or transport
    failure; the error message embeds the HTTP status code and the
    full response body so users can disambiguate cause at a glance.
    """
    # Paranoia: if upstream call sites ever drop ``code_verifier`` we
    # want to surface a precise, local error rather than send a
    # missing-PKCE request to xAI and receive their generic "code
    # challenge required" message back.
    if not code_verifier:
        raise _core.AuthError(
            "xAI token exchange refused locally: PKCE code_verifier is empty. "
            "This is a bug in Superforecasting Agent; please report it in "
            "this fork's issue tracker.",
            provider="xai-oauth",
            code="xai_pkce_verifier_missing",
        )

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": _core.XAI_OAUTH_CLIENT_ID,
        "code_verifier": code_verifier,
    }
    # Defense-in-depth: include the original ``code_challenge`` and
    # ``code_challenge_method``.  Some OAuth servers (including xAI's
    # auth.x.ai implementation, per the symptom reported in #26990)
    # validate these at the token endpoint instead of relying purely on
    # state captured during the authorize step — without them, xAI
    # rejects the exchange with ``code_challenge is required`` even
    # though we sent a valid ``code_verifier``.
    if code_challenge:
        data["code_challenge"] = code_challenge
        data["code_challenge_method"] = "S256"

    try:
        response = _core.httpx.post(
            token_endpoint,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data=data,
            timeout=max(20.0, timeout_seconds),
        )
    except Exception as exc:
        raise _core.AuthError(
            f"xAI token exchange failed: {exc}",
            provider="xai-oauth",
            code="xai_token_exchange_failed",
        ) from exc

    if response.status_code != 200:
        body = response.text.strip()
        # See ``refresh_xai_oauth_pure`` — token-exchange 403 also
        # surfaces tier/entitlement gating from xAI's backend.  Avoid
        # the misleading "re-authenticate" hint and point at the API
        # key fallback.  See #26847.
        if response.status_code == 403:
            raise _core.AuthError(
                "xAI token exchange failed (HTTP 403)."
                + (f" Response: {body}" if body else "")
                + " This OAuth account is not authorized for xAI API"
                " access — xAI may be restricting API/OAuth use to"
                " specific SuperGrok tiers despite the in-app"
                " subscription being active. Set ``XAI_API_KEY``"
                " and switch to ``provider: xai`` (API-key path) if"
                " available, or upgrade your subscription at"
                " https://x.ai/grok.",
                provider="xai-oauth",
                code="xai_oauth_tier_denied",
                relogin_required=False,
            )
        raise _core.AuthError(
            f"xAI token exchange failed (HTTP {response.status_code})."
            + (f" Response: {body}" if body else ""),
            provider="xai-oauth",
            code="xai_token_exchange_failed",
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise _core.AuthError(
            f"xAI token exchange returned invalid JSON: {exc}",
            provider="xai-oauth",
            code="xai_token_exchange_invalid",
        ) from exc
    if not isinstance(payload, dict):
        raise _core.AuthError(
            "xAI token exchange response was not a JSON object.",
            provider="xai-oauth",
            code="xai_token_exchange_invalid",
        )
    return payload
