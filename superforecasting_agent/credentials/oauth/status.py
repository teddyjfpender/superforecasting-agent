"""Status operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def get_qwen_auth_status() -> _core.Dict[str, _core.Any]:
    auth_path = _core._qwen_cli_auth_path()
    try:
        creds = _core.resolve_qwen_runtime_credentials(refresh_if_expiring=False)
        return {
            "logged_in": True,
            "auth_file": str(auth_path),
            "source": creds.get("source"),
            "api_key": creds.get("api_key"),
            "expires_at_ms": creds.get("expires_at_ms"),
        }
    except _core.AuthError as exc:
        return {
            "logged_in": False,
            "auth_file": str(auth_path),
            "error": str(exc),
        }


def get_gemini_oauth_auth_status() -> _core.Dict[str, _core.Any]:
    """Return a status dict for auth-list and status surfaces."""
    try:
        from agent.google_oauth import _credentials_path, load_credentials
    except ImportError:
        return {"logged_in": False, "error": "agent.google_oauth unavailable"}
    auth_path = _credentials_path()
    creds = load_credentials()
    if creds is None or not creds.access_token:
        return {
            "logged_in": False,
            "auth_file": str(auth_path),
            "error": "not logged in",
        }
    return {
        "logged_in": True,
        "auth_file": str(auth_path),
        "source": "google-oauth",
        "api_key": creds.access_token,
        "expires_at_ms": creds.expires_ms,
        "email": creds.email,
        "project_id": creds.project_id,
    }


def _empty_nous_auth_status() -> _core.Dict[str, _core.Any]:
    return {
        "logged_in": False,
        "portal_base_url": None,
        "inference_base_url": None,
        "access_expires_at": None,
        "agent_key_expires_at": None,
        "has_refresh_token": False,
    }


def _snapshot_nous_pool_status() -> _core.Dict[str, _core.Any]:
    """Best-effort status from the credential pool.

    This is a fallback only. The auth-store provider state is the runtime source
    of truth because it is what ``resolve_nous_runtime_credentials()`` refreshes
    and mints against.
    """
    try:
        from agent.credential_pool import load_pool

        pool = load_pool("nous")
        if not pool or not pool.has_credentials():
            return _core._empty_nous_auth_status()

        entries = list(pool.entries())
        if not entries:
            return _core._empty_nous_auth_status()

        def _entry_sort_key(entry: _core.Any) -> tuple[float, float, int]:
            agent_exp = (
                _core._parse_iso_timestamp(getattr(entry, "agent_key_expires_at", None))
                or 0.0
            )
            access_exp = (
                _core._parse_iso_timestamp(getattr(entry, "expires_at", None)) or 0.0
            )
            priority = int(getattr(entry, "priority", 0) or 0)
            return (agent_exp, access_exp, -priority)

        entry = max(entries, key=_entry_sort_key)
        access_token = getattr(entry, "access_token", None) or getattr(
            entry, "runtime_api_key", ""
        )
        if not access_token:
            return _core._empty_nous_auth_status()

        return {
            "logged_in": True,
            "portal_base_url": getattr(entry, "portal_base_url", None)
            or getattr(entry, "base_url", None),
            "inference_base_url": getattr(entry, "inference_base_url", None)
            or getattr(entry, "base_url", None),
            "access_token": access_token,
            "access_expires_at": getattr(entry, "expires_at", None),
            "agent_key_expires_at": getattr(entry, "agent_key_expires_at", None),
            "has_refresh_token": bool(getattr(entry, "refresh_token", None)),
            "source": f"pool:{getattr(entry, 'label', 'unknown')}",
        }
    except Exception:
        return _core._empty_nous_auth_status()


def _auth_file_mtime(
    auth_file: _core.Optional[_core.Path] = None,
) -> _core.Optional[float]:
    try:
        return (
            (auth_file if auth_file is not None else _core._auth_file_path())
            .stat()
            .st_mtime
        )
    except FileNotFoundError:
        return None
    except Exception:
        return None


def invalidate_nous_auth_status_cache() -> None:
    """Clear the get_nous_auth_status() process-level memo.

    Call this from any code path that mutates Nous auth state without going
    through resolve_nous_runtime_credentials() (e.g. tests). Login/logout
    flows touch auth.json, so the mtime check below invalidates them
    automatically — explicit invalidation is the belt-and-braces option.
    """
    pass  # Mutable credential state belongs to the shared facade.
    _core._nous_auth_status_cache = None


def get_nous_auth_status() -> _core.Dict[str, _core.Any]:
    """Status snapshot for Nous auth.

    Prefer the auth-store provider state, because that is the live source of
    truth for refresh + mint operations. When provider state exists, validate it
    by resolving runtime credentials so revoked refresh sessions do not show up
    as a healthy login. If provider state is absent, fall back to the credential
    pool for the just-logged-in / not-yet-promoted case.

    The returned snapshot is memoised for ~15s keyed on the resolved auth.json path and mtime,
    so menu/status surfaces that ask repeatedly don't trigger one refresh POST
    per call. Login/logout flows write to auth.json and therefore invalidate
    the cache automatically; tests can also call
    ``invalidate_nous_auth_status_cache()`` explicitly.
    """
    pass  # Mutable credential state belongs to the shared facade.
    now = _core.time.monotonic()
    auth_file = _core._auth_file_path().resolve()
    cache_key = (str(auth_file), _core._auth_file_mtime(auth_file))
    cached = _core._nous_auth_status_cache
    if cached is not None:
        cached_at, cached_key, cached_status = cached
        if (
            cached_key == cache_key
            and (now - cached_at) < _core._NOUS_AUTH_STATUS_CACHE_TTL
        ):
            return dict(cached_status)

    status = _core._compute_nous_auth_status()
    _core._nous_auth_status_cache = (now, cache_key, dict(status))
    return status


def _compute_nous_auth_status() -> _core.Dict[str, _core.Any]:
    """Uncached implementation of get_nous_auth_status(). See that function."""
    state = _core.get_provider_auth_state("nous")
    if state:
        base_status = {
            "logged_in": bool(state.get("access_token")),
            "portal_base_url": state.get("portal_base_url"),
            "inference_base_url": state.get("inference_base_url"),
            "access_expires_at": state.get("expires_at"),
            "agent_key_expires_at": state.get("agent_key_expires_at"),
            "has_refresh_token": bool(state.get("refresh_token")),
            "access_token": state.get("access_token"),
            "source": "auth_store",
        }
        try:
            creds = _core.resolve_nous_runtime_credentials(min_key_ttl_seconds=60)
            refreshed_state = _core.get_provider_auth_state("nous") or state
            base_status.update({
                "logged_in": True,
                "portal_base_url": refreshed_state.get("portal_base_url")
                or base_status.get("portal_base_url"),
                "inference_base_url": creds.get("base_url")
                or refreshed_state.get("inference_base_url")
                or base_status.get("inference_base_url"),
                "access_expires_at": refreshed_state.get("expires_at")
                or base_status.get("access_expires_at"),
                "agent_key_expires_at": creds.get("expires_at")
                or refreshed_state.get("agent_key_expires_at")
                or base_status.get("agent_key_expires_at"),
                "has_refresh_token": bool(refreshed_state.get("refresh_token")),
                "source": f"runtime:{creds.get('source', 'portal')}",
                "key_id": creds.get("key_id"),
            })
            return base_status
        except _core.AuthError as exc:
            base_status.update({
                "logged_in": False,
                "error": str(exc),
                "relogin_required": bool(getattr(exc, "relogin_required", False)),
                "error_code": getattr(exc, "code", None),
            })
            return base_status

    return _core._snapshot_nous_pool_status()


def get_codex_auth_status() -> _core.Dict[str, _core.Any]:
    """Status snapshot for Codex auth.

    Checks the credential pool first (where `superforecasting-agent auth`
    stores credentials), then falls back to the legacy provider state.
    """
    # Check credential pool first — this is where `superforecasting-agent auth`
    # and `superforecasting-agent model` store device_code tokens.
    try:
        from agent.credential_pool import load_pool

        pool = load_pool("openai-codex")
        if pool and pool.has_credentials():
            entry = pool.select()
            if entry is not None:
                api_key = getattr(entry, "runtime_api_key", None) or getattr(
                    entry, "access_token", ""
                )
                if api_key and not _core._codex_access_token_is_expiring(api_key, 0):
                    return {
                        "logged_in": True,
                        "auth_store": str(_core._auth_file_path()),
                        "last_refresh": getattr(entry, "last_refresh", None),
                        "auth_mode": "chatgpt",
                        "source": f"pool:{getattr(entry, 'label', 'unknown')}",
                        "api_key": api_key,
                    }
    except Exception:
        pass

    # Fall back to legacy provider state
    try:
        creds = _core.resolve_codex_runtime_credentials()
        return {
            "logged_in": True,
            "auth_store": str(_core._auth_file_path()),
            "last_refresh": creds.get("last_refresh"),
            "auth_mode": creds.get("auth_mode"),
            "source": creds.get("source"),
            "api_key": creds.get("api_key"),
        }
    except _core.AuthError as exc:
        return {
            "logged_in": False,
            "auth_store": str(_core._auth_file_path()),
            "error": str(exc),
        }


def get_xai_oauth_auth_status() -> _core.Dict[str, _core.Any]:
    try:
        from agent.credential_pool import load_pool

        pool = load_pool("xai-oauth")
        if pool and pool.has_credentials():
            entry = pool.select()
            if entry is not None:
                api_key = getattr(entry, "runtime_api_key", None) or getattr(
                    entry, "access_token", ""
                )
                if api_key and not _core._xai_access_token_is_expiring(api_key, 0):
                    return {
                        "logged_in": True,
                        "auth_store": str(_core._auth_file_path()),
                        "last_refresh": getattr(entry, "last_refresh", None),
                        "auth_mode": "oauth_pkce",
                        "source": f"pool:{getattr(entry, 'label', 'unknown')}",
                        "api_key": api_key,
                    }
    except Exception:
        pass

    try:
        creds = _core.resolve_xai_oauth_runtime_credentials()
        return {
            "logged_in": True,
            "auth_store": str(_core._auth_file_path()),
            "last_refresh": creds.get("last_refresh"),
            "auth_mode": creds.get("auth_mode"),
            "source": creds.get("source"),
            "api_key": creds.get("api_key"),
        }
    except _core.AuthError as exc:
        return {
            "logged_in": False,
            "auth_store": str(_core._auth_file_path()),
            "error": str(exc),
        }


def get_api_key_provider_status(provider_id: str) -> _core.Dict[str, _core.Any]:
    """Status snapshot for API-key providers (z.ai, Kimi, MiniMax)."""
    pconfig = _core.PROVIDER_REGISTRY.get(provider_id)
    if not pconfig or pconfig.auth_type != "api_key":
        return {"configured": False}

    api_key = ""
    key_source = ""
    api_key, key_source = _core._resolve_api_key_provider_secret(provider_id, pconfig)

    env_url = ""
    if pconfig.base_url_env_var:
        env_url = _core.os.getenv(pconfig.base_url_env_var, "").strip()

    if provider_id in {"kimi-coding", "kimi-coding-cn"}:
        base_url = _core._resolve_kimi_base_url(
            api_key, pconfig.inference_base_url, env_url
        )
    elif env_url:
        base_url = env_url
    else:
        base_url = pconfig.inference_base_url

    return {
        "configured": bool(api_key),
        "provider": provider_id,
        "name": pconfig.name,
        "key_source": key_source,
        "base_url": base_url,
        "logged_in": bool(api_key),  # compat with OAuth status shape
    }


def _resolve_copilot_acp_command() -> str:
    for env_name in _core._COPILOT_ACP_COMMAND_ENV_NAMES:
        value = _core.os.getenv(env_name, "").strip()
        if value:
            return value
    return "copilot"


def _resolve_copilot_acp_args_raw() -> str:
    for env_name in _core._COPILOT_ACP_ARGS_ENV_NAMES:
        value = _core.os.getenv(env_name, "").strip()
        if value:
            return value
    return ""


def get_external_process_provider_status(
    provider_id: str,
) -> _core.Dict[str, _core.Any]:
    """Status snapshot for providers that run a local subprocess."""
    pconfig = _core.PROVIDER_REGISTRY.get(provider_id)
    if not pconfig or pconfig.auth_type != "external_process":
        return {"configured": False}

    command = _core._resolve_copilot_acp_command()
    raw_args = _core._resolve_copilot_acp_args_raw()
    args = _core.shlex.split(raw_args) if raw_args else ["--acp", "--stdio"]
    base_url = (
        _core.os.getenv(pconfig.base_url_env_var, "").strip()
        if pconfig.base_url_env_var
        else ""
    )
    if not base_url:
        base_url = pconfig.inference_base_url

    resolved_command = _core.shutil.which(command) if command else None
    return {
        "configured": bool(resolved_command or base_url.startswith("acp+tcp://")),
        "provider": provider_id,
        "name": pconfig.name,
        "command": command,
        "args": args,
        "resolved_command": resolved_command,
        "base_url": base_url,
        "logged_in": bool(resolved_command or base_url.startswith("acp+tcp://")),
    }


def get_auth_status(
    provider_id: _core.Optional[str] = None,
) -> _core.Dict[str, _core.Any]:
    """Generic auth status dispatcher."""
    target = (provider_id or _core.get_active_provider() or "").strip().lower()
    if not target:
        return {"logged_in": False}
    if target == "nous":
        return _core.get_nous_auth_status()
    if target == "openai-codex":
        return _core.get_codex_auth_status()
    if target == "xai-oauth":
        return _core.get_xai_oauth_auth_status()
    if target == "qwen-oauth":
        return _core.get_qwen_auth_status()
    if target == "google-gemini-cli":
        return _core.get_gemini_oauth_auth_status()
    if target == "minimax-oauth":
        return _core.get_minimax_oauth_auth_status()
    if target == "copilot-acp":
        return _core.get_external_process_provider_status(target)
    if target == "azure-foundry":
        return _core._get_azure_foundry_auth_status()
    # API-key providers
    pconfig = _core.PROVIDER_REGISTRY.get(target)
    if pconfig and pconfig.auth_type == "api_key":
        return _core.get_api_key_provider_status(target)
    # AWS SDK providers (Bedrock) — check via boto3 credential chain
    if pconfig and pconfig.auth_type == "aws_sdk":
        try:
            from superforecasting_agent.hosting.aws_credentials import (
                has_aws_credentials,
            )

            return {"logged_in": has_aws_credentials(), "provider": target}
        except ImportError:
            return {
                "logged_in": False,
                "provider": target,
                "error": "boto3 not installed",
            }
    return {"logged_in": False}


def _get_azure_foundry_auth_status() -> _core.Dict[str, _core.Any]:
    """Return structural auth status for Azure Foundry.

    ``logged_in`` is structural, matching other non-OAuth provider status
    checks:

      * ``auth_mode == "entra_id"`` AND ``azure-identity`` is importable
        (we do NOT mint a token here; ``superforecasting-agent doctor`` runs the live
        probe and reports whether the credential chain can acquire one).
      * ``auth_mode == "api_key"`` (default) AND ``AZURE_FOUNDRY_API_KEY``
        is set with a usable value.

    Never invokes the Entra credential chain — keeps CLI startup latency
    flat regardless of token-service / az login state.
    """
    info: _core.Dict[str, _core.Any] = {"provider": "azure-foundry"}
    try:
        from superforecasting_agent.credentials.environment import (
            get_env_value,
            load_config,
        )

        cfg = load_config()
    except Exception:
        cfg = {}

    model_cfg = cfg.get("model") if isinstance(cfg, dict) else None
    auth_mode = "api_key"
    base_url = ""
    if isinstance(model_cfg, dict):
        auth_mode = (
            str(model_cfg.get("auth_mode") or "api_key").strip().lower() or "api_key"
        )
        base_url = str(model_cfg.get("base_url") or "").strip()
    info["auth_mode"] = auth_mode
    info["base_url"] = base_url

    if auth_mode == "entra_id":
        try:
            from superforecasting_agent.credentials.azure import (
                SCOPE_AI_AZURE_DEFAULT,
                EntraIdentityConfig,
                has_azure_identity_installed,
            )

            installed = has_azure_identity_installed()
            entra_cfg = {}
            if isinstance(model_cfg, dict) and isinstance(model_cfg.get("entra"), dict):
                entra_cfg = model_cfg["entra"]
            identity_config = EntraIdentityConfig.from_dict(
                entra_cfg,
                default_scope=SCOPE_AI_AZURE_DEFAULT,
            )
            info["azure_identity_installed"] = installed
            info["scope"] = identity_config.scope
            info["credential_probe"] = "not_run"
            info["credential_verified"] = False
            info["logged_in"] = bool(installed)
            if not installed:
                info["hint"] = (
                    "azure-identity not installed. Install with: "
                    "pip install azure-identity  (or rely on Superforecasting Agent's "
                    "lazy-install at first use)."
                )
            else:
                info["hint"] = (
                    "azure-identity is installed; live credential validation "
                    f"is skipped here. Run `{_core._PRIMARY_CLI} doctor` to verify token acquisition."
                )
            return info
        except Exception as exc:
            info["logged_in"] = False
            info["error"] = f"azure-identity check failed: {exc}"
            return info

    # api_key mode (default)
    try:
        api_key = get_env_value("AZURE_FOUNDRY_API_KEY") or _core.os.getenv(
            "AZURE_FOUNDRY_API_KEY", ""
        )
    except Exception:
        api_key = _core.os.getenv("AZURE_FOUNDRY_API_KEY", "")
    info["logged_in"] = _core.has_usable_secret(api_key)
    return info


def get_minimax_oauth_auth_status() -> _core.Dict[str, _core.Any]:
    """Return auth status dict for MiniMax OAuth provider."""
    state = _core.get_provider_auth_state("minimax-oauth")
    if not state or not state.get("access_token"):
        return {"logged_in": False, "provider": "minimax-oauth"}
    try:
        expires_at = _core.datetime.fromisoformat(
            state.get("expires_at", "")
        ).timestamp()
        token_valid = (expires_at - _core.time.time()) > 0
    except Exception:
        token_valid = bool(state.get("access_token"))
    return {
        "logged_in": token_valid,
        "provider": "minimax-oauth",
        "region": state.get("region", "global"),
        "expires_at": state.get("expires_at"),
    }
