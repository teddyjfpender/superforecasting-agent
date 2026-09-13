"""Api keys operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def get_anthropic_key() -> str:
    """Return the first usable Anthropic credential, or ``""``.

    Checks both the ``.env`` file (via ``get_env_value``) and the process
    environment (``os.getenv``).  The fallback order mirrors the
    ``PROVIDER_REGISTRY["anthropic"].api_key_env_vars`` tuple:

        ANTHROPIC_API_KEY -> ANTHROPIC_TOKEN -> CLAUDE_CODE_OAUTH_TOKEN
    """
    from superforecasting_agent.credentials.environment import get_env_value

    for var in _core.PROVIDER_REGISTRY["anthropic"].api_key_env_vars:
        value = get_env_value(var) or _core.os.getenv(var, "")
        if _core.has_usable_secret(value):
            return value.strip()
    return ""


def _resolve_api_key_provider_secret(
    provider_id: str, pconfig: _core.ProviderConfig
) -> tuple[str, str]:
    """Resolve an API-key provider's token and indicate where it came from."""
    if provider_id == "copilot":
        # Use the dedicated copilot auth module for proper token validation
        try:
            from superforecasting_agent.credentials.copilot import (
                get_copilot_api_token,
                resolve_copilot_token,
            )

            token, source = resolve_copilot_token()
            if token:
                return get_copilot_api_token(token), source
        except ValueError as exc:
            _core.logger.warning("Copilot token validation failed: %s", exc)
        except Exception:
            pass
        return "", ""

    from superforecasting_agent.credentials.environment import get_env_value

    for env_var in pconfig.api_key_env_vars:
        # Check both os.environ and ~/.hermes/.env file
        val = (get_env_value(env_var) or "").strip()
        if _core.has_usable_secret(val):
            return val, env_var

    # Fallback: try credential pool (e.g. zai key stored via auth.json)
    try:
        from agent.credential_pool import load_pool

        pool = load_pool(provider_id)
        if pool and pool.has_credentials():
            entry = pool.peek()
            if entry:
                key = getattr(entry, "access_token", "") or getattr(
                    entry, "runtime_api_key", ""
                )
                key = str(key).strip()
                if _core.has_usable_secret(key):
                    return key, f"credential_pool:{provider_id}"
    except Exception:
        pass

    return "", ""


def detect_zai_endpoint(
    api_key: str, timeout: float = 8.0
) -> _core.Optional[_core.Dict[str, str]]:
    """Probe z.ai endpoints to find one that accepts this API key.

    Returns {"id": ..., "base_url": ..., "model": ..., "label": ...} for the
    first working endpoint, or None if all fail.  For endpoints with multiple
    candidate models, tries each in order and returns the first that succeeds.
    """
    for ep_id, base_url, probe_models, label in _core.ZAI_ENDPOINTS:
        for model in probe_models:
            try:
                resp = _core.httpx.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "stream": False,
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "ping"}],
                    },
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    _core.logger.debug(
                        "Z.AI endpoint probe: %s (%s) model=%s OK",
                        ep_id,
                        base_url,
                        model,
                    )
                    return {
                        "id": ep_id,
                        "base_url": base_url,
                        "model": model,
                        "label": label,
                    }
                _core.logger.debug(
                    "Z.AI endpoint probe: %s model=%s returned %s",
                    ep_id,
                    model,
                    resp.status_code,
                )
            except Exception as exc:
                _core.logger.debug(
                    "Z.AI endpoint probe: %s model=%s failed: %s", ep_id, model, exc
                )
    return None


def _resolve_zai_base_url(api_key: str, default_url: str, env_override: str) -> str:
    """Return the correct Z.AI base URL by probing endpoints.

    If the user has explicitly set GLM_BASE_URL, that always wins.
    Otherwise, probe the candidate endpoints to find one that accepts the
    key.  The detected endpoint is cached in provider state (auth.json) keyed
    on a hash of the API key so subsequent starts skip the probe.
    """
    if env_override:
        return env_override

    # No API key set → don't probe (would fire N×M HTTPS requests with an
    # empty Bearer token, all returning 401).  This path is hit during
    # auxiliary-client auto-detection when the user has no Z.AI credentials
    # at all — the caller discards the result immediately, so the probe is
    # pure latency for every AIAgent construction.
    if not api_key:
        return default_url

    from superforecasting_agent.storage.auth import load_auth_store, save_auth_store

    # Check provider-state cache for a previously-detected endpoint.
    auth_file = _core._auth_file_path().absolute()
    auth_store = load_auth_store(auth_file)
    state = _core._load_provider_state(auth_store, "zai") or {}
    cached = state.get("detected_endpoint")
    if isinstance(cached, dict) and cached.get("base_url"):
        key_hash = cached.get("key_hash", "")
        if key_hash == _core.hashlib.sha256(api_key.encode()).hexdigest()[:16]:
            _core.logger.debug("Z.AI: using cached endpoint %s", cached["base_url"])
            return cached["base_url"]

    # Probe — may take up to ~8s per endpoint.
    detected = _core.detect_zai_endpoint(api_key)
    if detected and detected.get("base_url"):
        # Persist the detection result keyed on the API key hash.
        key_hash = _core.hashlib.sha256(api_key.encode()).hexdigest()[:16]
        metadata = {
            "base_url": detected["base_url"],
            "endpoint_id": detected.get("id", ""),
            "model": detected.get("model", ""),
            "label": detected.get("label", ""),
            "key_hash": key_hash,
        }
        try:
            # The probe runs outside the writer lock. Re-read the captured profile
            # under its exact lock before publishing only this metadata field.
            with _core._file_lock(
                auth_file.with_suffix(".lock"),
                _core._auth_lock_holder,
                _core.AUTH_LOCK_TIMEOUT_SECONDS,
                "Timed out waiting for auth store lock",
            ):
                latest = load_auth_store(auth_file)
                current = _core._load_provider_state(latest, "zai") or {}
                current["detected_endpoint"] = metadata
                _core._store_provider_state(latest, "zai", current, set_active=False)
                save_auth_store(auth_file, latest)
        except (OSError, TimeoutError) as exc:
            # A cache failure must not discard a successfully discovered endpoint.
            _core.logger.warning("Z.AI: could not persist endpoint cache: %s", exc)
        _core.logger.info(
            "Z.AI: auto-detected endpoint %s (%s)",
            detected.get("label", ""),
            detected["base_url"],
        )
        return detected["base_url"]

    _core.logger.debug("Z.AI: probe failed, falling back to default %s", default_url)
    return default_url


def resolve_api_key_provider_credentials(
    provider_id: str,
) -> _core.Dict[str, _core.Any]:
    """Resolve API key and base URL for an API-key provider.

    Returns dict with: provider, api_key, base_url, source.
    """
    pconfig = _core.PROVIDER_REGISTRY.get(provider_id)
    if not pconfig or pconfig.auth_type != "api_key":
        raise _core.AuthError(
            f"Provider '{provider_id}' is not an API-key provider.",
            provider=provider_id,
            code="invalid_provider",
        )

    api_key = ""
    key_source = ""
    api_key, key_source = _core._resolve_api_key_provider_secret(provider_id, pconfig)

    # No-auth LM Studio: substitute a placeholder so runtime / auxiliary_client
    # see the local server as configured. doctor still reports unconfigured
    # because get_api_key_provider_status uses the raw secret resolver.
    if not api_key and provider_id == "lmstudio":
        api_key = _core.LMSTUDIO_NOAUTH_PLACEHOLDER
        key_source = key_source or "default"

    env_url = ""
    if pconfig.base_url_env_var:
        env_url = _core.os.getenv(pconfig.base_url_env_var, "").strip()

    if provider_id in {"kimi-coding", "kimi-coding-cn"}:
        base_url = _core._resolve_kimi_base_url(
            api_key, pconfig.inference_base_url, env_url
        )
    elif provider_id == "zai":
        base_url = _core._resolve_zai_base_url(
            api_key, pconfig.inference_base_url, env_url
        )
    elif env_url:
        base_url = env_url.rstrip("/")
    else:
        base_url = pconfig.inference_base_url

    return {
        "provider": provider_id,
        "api_key": api_key,
        "base_url": base_url.rstrip("/"),
        "source": key_source or "default",
    }


def resolve_external_process_provider_credentials(
    provider_id: str,
) -> _core.Dict[str, _core.Any]:
    """Resolve runtime details for local subprocess-backed providers."""
    pconfig = _core.PROVIDER_REGISTRY.get(provider_id)
    if not pconfig or pconfig.auth_type != "external_process":
        raise _core.AuthError(
            f"Provider '{provider_id}' is not an external-process provider.",
            provider=provider_id,
            code="invalid_provider",
        )

    base_url = (
        _core.os.getenv(pconfig.base_url_env_var, "").strip()
        if pconfig.base_url_env_var
        else ""
    )
    if not base_url:
        base_url = pconfig.inference_base_url

    command = _core._resolve_copilot_acp_command()
    raw_args = _core._resolve_copilot_acp_args_raw()
    args = _core.shlex.split(raw_args) if raw_args else ["--acp", "--stdio"]
    resolved_command = _core.shutil.which(command) if command else None
    if not resolved_command and not base_url.startswith("acp+tcp://"):
        raise _core.AuthError(
            f"Could not find the Copilot CLI command '{command}'. "
            "Install GitHub Copilot CLI or set "
            "SUPERFORECASTING_AGENT_COPILOT_ACP_COMMAND, FORECAST_COPILOT_ACP_COMMAND, "
            "or COPILOT_CLI_PATH.",
            provider=provider_id,
            code="missing_copilot_cli",
        )

    return {
        "provider": provider_id,
        "api_key": "copilot-acp",
        "base_url": base_url.rstrip("/"),
        "command": resolved_command or command,
        "args": args,
        "source": "process",
    }
