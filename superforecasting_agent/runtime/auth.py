"""Interactive authentication commands and inherited credential compatibility exports."""

from __future__ import annotations

import superforecasting_agent.credentials.auth as credential_service

import subprocess
import webbrowser
from superforecasting_agent.constants import OPENROUTER_BASE_URL

from superforecasting_agent.runtime.config import get_config_path, read_raw_config, save_config
from superforecasting_agent.credentials.auth import (
    ACCESS_TOKEN_REFRESH_SKEW_SECONDS as ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
    AUTH_LOCK_TIMEOUT_SECONDS as AUTH_LOCK_TIMEOUT_SECONDS,
    AUTH_STORE_VERSION as AUTH_STORE_VERSION,
    Any as Any,
    AuthError as AuthError,
    BaseHTTPRequestHandler as BaseHTTPRequestHandler,
    CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS as CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
    CODEX_OAUTH_CLIENT_ID as CODEX_OAUTH_CLIENT_ID,
    CODEX_OAUTH_TOKEN_URL as CODEX_OAUTH_TOKEN_URL,
    CODEX_RATE_LIMITED_CODE as CODEX_RATE_LIMITED_CODE,
    Callable as Callable,
    DEFAULT_AGENT_KEY_MIN_TTL_SECONDS as DEFAULT_AGENT_KEY_MIN_TTL_SECONDS,
    DEFAULT_CODEX_BASE_URL as DEFAULT_CODEX_BASE_URL,
    DEFAULT_COPILOT_ACP_BASE_URL as DEFAULT_COPILOT_ACP_BASE_URL,
    DEFAULT_GEMINI_CLOUDCODE_BASE_URL as DEFAULT_GEMINI_CLOUDCODE_BASE_URL,
    DEFAULT_GITHUB_MODELS_BASE_URL as DEFAULT_GITHUB_MODELS_BASE_URL,
    DEFAULT_NOUS_CLIENT_ID as DEFAULT_NOUS_CLIENT_ID,
    DEFAULT_NOUS_INFERENCE_URL as DEFAULT_NOUS_INFERENCE_URL,
    DEFAULT_NOUS_PORTAL_URL as DEFAULT_NOUS_PORTAL_URL,
    DEFAULT_NOUS_SCOPE as DEFAULT_NOUS_SCOPE,
    DEFAULT_OLLAMA_CLOUD_BASE_URL as DEFAULT_OLLAMA_CLOUD_BASE_URL,
    DEFAULT_QWEN_BASE_URL as DEFAULT_QWEN_BASE_URL,
    DEFAULT_XAI_OAUTH_BASE_URL as DEFAULT_XAI_OAUTH_BASE_URL,
    DEVICE_AUTH_POLL_INTERVAL_CAP_SECONDS as DEVICE_AUTH_POLL_INTERVAL_CAP_SECONDS,
    Dict as Dict,
    GEMINI_OAUTH_ACCESS_TOKEN_REFRESH_SKEW_SECONDS as GEMINI_OAUTH_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
    HTTPServer as HTTPServer,
    KIMI_CODE_BASE_URL as KIMI_CODE_BASE_URL,
    LMSTUDIO_NOAUTH_PLACEHOLDER as LMSTUDIO_NOAUTH_PLACEHOLDER,
    List as List,
    MINIMAX_OAUTH_CLIENT_ID as MINIMAX_OAUTH_CLIENT_ID,
    MINIMAX_OAUTH_CN_BASE as MINIMAX_OAUTH_CN_BASE,
    MINIMAX_OAUTH_CN_INFERENCE as MINIMAX_OAUTH_CN_INFERENCE,
    MINIMAX_OAUTH_GLOBAL_BASE as MINIMAX_OAUTH_GLOBAL_BASE,
    MINIMAX_OAUTH_GLOBAL_INFERENCE as MINIMAX_OAUTH_GLOBAL_INFERENCE,
    MINIMAX_OAUTH_GRANT_TYPE as MINIMAX_OAUTH_GRANT_TYPE,
    MINIMAX_OAUTH_REFRESH_SKEW_SECONDS as MINIMAX_OAUTH_REFRESH_SKEW_SECONDS,
    MINIMAX_OAUTH_SCOPE as MINIMAX_OAUTH_SCOPE,
    NOUS_AUTH_PATH_INVOKE_JWT as NOUS_AUTH_PATH_INVOKE_JWT,
    NOUS_AUTH_PATH_LEGACY_SESSION_KEY_CACHE as NOUS_AUTH_PATH_LEGACY_SESSION_KEY_CACHE,
    NOUS_AUTH_PATH_LEGACY_SESSION_KEY_MINT as NOUS_AUTH_PATH_LEGACY_SESSION_KEY_MINT,
    NOUS_DEVICE_CODE_SOURCE as NOUS_DEVICE_CODE_SOURCE,
    NOUS_INFERENCE_AUTH_MODES as NOUS_INFERENCE_AUTH_MODES,
    NOUS_INFERENCE_AUTH_MODE_AUTO as NOUS_INFERENCE_AUTH_MODE_AUTO,
    NOUS_INFERENCE_AUTH_MODE_FRESH as NOUS_INFERENCE_AUTH_MODE_FRESH,
    NOUS_INFERENCE_AUTH_MODE_LEGACY as NOUS_INFERENCE_AUTH_MODE_LEGACY,
    NOUS_INFERENCE_INVOKE_SCOPE as NOUS_INFERENCE_INVOKE_SCOPE,
    NOUS_INVOKE_JWT_MIN_TTL_SECONDS as NOUS_INVOKE_JWT_MIN_TTL_SECONDS,
    NOUS_LEGACY_AGENT_KEY_SCOPE as NOUS_LEGACY_AGENT_KEY_SCOPE,
    NOUS_LEGACY_SESSION_KEYS_ENV as NOUS_LEGACY_SESSION_KEYS_ENV,
    NOUS_SHARED_STORE_FILENAME as NOUS_SHARED_STORE_FILENAME,
    OAUTH_OVER_SSH_DOCS_URL as OAUTH_OVER_SSH_DOCS_URL,
    Optional as Optional,
    PROVIDER_REGISTRY as PROVIDER_REGISTRY,
    Path as Path,
    ProviderConfig as ProviderConfig,
    QWEN_ACCESS_TOKEN_REFRESH_SKEW_SECONDS as QWEN_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
    QWEN_OAUTH_CLIENT_ID as QWEN_OAUTH_CLIENT_ID,
    QWEN_OAUTH_TOKEN_URL as QWEN_OAUTH_TOKEN_URL,
    SERVICE_PROVIDER_NAMES as SERVICE_PROVIDER_NAMES,
    STEPFUN_STEP_PLAN_CN_BASE_URL as STEPFUN_STEP_PLAN_CN_BASE_URL,
    STEPFUN_STEP_PLAN_INTL_BASE_URL as STEPFUN_STEP_PLAN_INTL_BASE_URL,
    ThreadingHTTPServer as ThreadingHTTPServer,
    Tuple as Tuple,
    XAI_ACCESS_TOKEN_REFRESH_SKEW_SECONDS as XAI_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
    XAI_OAUTH_CLIENT_ID as XAI_OAUTH_CLIENT_ID,
    XAI_OAUTH_DISCOVERY_URL as XAI_OAUTH_DISCOVERY_URL,
    XAI_OAUTH_DOCS_URL as XAI_OAUTH_DOCS_URL,
    XAI_OAUTH_ISSUER as XAI_OAUTH_ISSUER,
    XAI_OAUTH_REDIRECT_HOST as XAI_OAUTH_REDIRECT_HOST,
    XAI_OAUTH_REDIRECT_PATH as XAI_OAUTH_REDIRECT_PATH,
    XAI_OAUTH_REDIRECT_PORT as XAI_OAUTH_REDIRECT_PORT,
    XAI_OAUTH_SCOPE as XAI_OAUTH_SCOPE,
    ZAI_ENDPOINTS as ZAI_ENDPOINTS,
    _COPILOT_ACP_ARGS_ENV_NAMES as _COPILOT_ACP_ARGS_ENV_NAMES,
    _COPILOT_ACP_COMMAND_ENV_NAMES as _COPILOT_ACP_COMMAND_ENV_NAMES,
    _NOUS_AUTH_STATUS_CACHE_TTL as _NOUS_AUTH_STATUS_CACHE_TTL,
    _NOUS_EFFECTIVE_STATE_IGNORED_KEYS as _NOUS_EFFECTIVE_STATE_IGNORED_KEYS,
    _PLACEHOLDER_SECRET_VALUES as _PLACEHOLDER_SECRET_VALUES,
    _PRIMARY_CLI as _PRIMARY_CLI,
    _QWEN_BASE_URL_ENV_NAMES as _QWEN_BASE_URL_ENV_NAMES,
    _agent_key_is_usable as _agent_key_is_usable,
    _auth_command_hint as _auth_command_hint,
    _auth_file_mtime as _auth_file_mtime,
    _auth_file_path as _auth_file_path,
    _auth_lock_holder as _auth_lock_holder,
    _auth_lock_path as _auth_lock_path,
    _auth_store_lock as _auth_store_lock,
    _choose_nous_inference_auth_path as _choose_nous_inference_auth_path,
    _clear_shared_nous_state as _clear_shared_nous_state,
    _codex_access_token_is_expiring as _codex_access_token_is_expiring,
    _coerce_ttl_seconds as _coerce_ttl_seconds,
    _compute_nous_auth_status as _compute_nous_auth_status,
    _decode_jwt_claims as _decode_jwt_claims,
    _default_verify as _default_verify,
    _empty_nous_auth_status as _empty_nous_auth_status,
    _file_lock as _file_lock,
    _get_azure_foundry_auth_status as _get_azure_foundry_auth_status,
    _get_config_hint_for_unknown_provider as _get_config_hint_for_unknown_provider,
    _global_auth_file_path as _global_auth_file_path,
    _import_codex_cli_tokens as _import_codex_cli_tokens,
    _is_expiring as _is_expiring,
    _is_nous_invoke_scope_refusal as _is_nous_invoke_scope_refusal,
    _is_remote_session as _is_remote_session,
    _is_terminal_codex_oauth_refresh_error as _is_terminal_codex_oauth_refresh_error,
    _is_terminal_nous_refresh_error as _is_terminal_nous_refresh_error,
    _is_terminal_xai_oauth_refresh_error as _is_terminal_xai_oauth_refresh_error,
    _load_auth_store as _load_auth_store,
    _load_global_auth_store as _load_global_auth_store,
    _load_provider_state as _load_provider_state,
    _log_nous_invoke_jwt_selected as _log_nous_invoke_jwt_selected,
    _log_nous_legacy_session_key_selected as _log_nous_legacy_session_key_selected,
    _make_xai_callback_handler as _make_xai_callback_handler,
    _merge_shared_nous_oauth_state as _merge_shared_nous_oauth_state,
    _minimax_expired_in_looks_like_unix_ms as _minimax_expired_in_looks_like_unix_ms,
    _minimax_pkce_pair as _minimax_pkce_pair,
    _minimax_poll_token as _minimax_poll_token,
    _minimax_request_user_code as _minimax_request_user_code,
    _minimax_resolve_token_expiry_unix as _minimax_resolve_token_expiry_unix,
    _minimax_save_auth_state as _minimax_save_auth_state,
    _mint_agent_key as _mint_agent_key,
    _normalize_nous_inference_auth_mode as _normalize_nous_inference_auth_mode,
    _nous_auth_status_cache as _nous_auth_status_cache,
    _nous_device_scope_with_env_override as _nous_device_scope_with_env_override,
    _nous_effective_provider_state as _nous_effective_provider_state,
    _nous_invoke_jwt_is_usable as _nous_invoke_jwt_is_usable,
    _nous_invoke_jwt_status as _nous_invoke_jwt_status,
    _nous_jwt_expires_at as _nous_jwt_expires_at,
    _nous_legacy_session_key_reason as _nous_legacy_session_key_reason,
    _nous_legacy_session_keys_forced as _nous_legacy_session_keys_forced,
    _nous_scope_has_invoke as _nous_scope_has_invoke,
    _nous_shared_auth_dir as _nous_shared_auth_dir,
    _nous_shared_lock_holder as _nous_shared_lock_holder,
    _nous_shared_store_lock as _nous_shared_store_lock,
    _nous_shared_store_path as _nous_shared_store_path,
    _oauth_pkce_code_challenge as _oauth_pkce_code_challenge,
    _oauth_pkce_code_verifier as _oauth_pkce_code_verifier,
    _oauth_trace as _oauth_trace,
    _oauth_trace_enabled as _oauth_trace_enabled,
    _optional_base_url as _optional_base_url,
    _parse_iso_timestamp as _parse_iso_timestamp,
    _parse_pasted_callback as _parse_pasted_callback,
    _parse_retry_after_seconds as _parse_retry_after_seconds,
    _poll_for_token as _poll_for_token,
    _quarantine_nous_oauth_state as _quarantine_nous_oauth_state,
    _quarantine_nous_pool_entries as _quarantine_nous_pool_entries,
    _qwen_access_token_is_expiring as _qwen_access_token_is_expiring,
    _qwen_cli_auth_path as _qwen_cli_auth_path,
    _read_codex_tokens as _read_codex_tokens,
    _read_qwen_cli_tokens as _read_qwen_cli_tokens,
    _read_shared_nous_state as _read_shared_nous_state,
    _read_xai_oauth_tokens as _read_xai_oauth_tokens,
    _refresh_access_token as _refresh_access_token,
    _refresh_codex_auth_tokens as _refresh_codex_auth_tokens,
    _refresh_minimax_oauth_state as _refresh_minimax_oauth_state,
    _refresh_qwen_cli_tokens as _refresh_qwen_cli_tokens,
    _refresh_xai_oauth_tokens as _refresh_xai_oauth_tokens,
    _request_device_code as _request_device_code,
    _request_nous_device_code_with_scope_fallback as _request_nous_device_code_with_scope_fallback,
    _resolve_api_key_provider_secret as _resolve_api_key_provider_secret,
    _resolve_copilot_acp_args_raw as _resolve_copilot_acp_args_raw,
    _resolve_copilot_acp_command as _resolve_copilot_acp_command,
    _resolve_kimi_base_url as _resolve_kimi_base_url,
    _resolve_verify as _resolve_verify,
    _resolve_zai_base_url as _resolve_zai_base_url,
    _save_auth_store as _save_auth_store,
    _save_codex_tokens as _save_codex_tokens,
    _save_provider_state as _save_provider_state,
    _save_qwen_cli_tokens as _save_qwen_cli_tokens,
    _save_xai_oauth_tokens as _save_xai_oauth_tokens,
    _scope_values as _scope_values,
    _select_nous_invoke_jwt as _select_nous_invoke_jwt,
    _set_nous_agent_key_from_invoke_jwt as _set_nous_agent_key_from_invoke_jwt,
    _snapshot_nous_pool_status as _snapshot_nous_pool_status,
    _ssh_user_at_host as _ssh_user_at_host,
    _store_provider_state as _store_provider_state,
    _sync_codex_pool_entries as _sync_codex_pool_entries,
    _sync_nous_pool_from_auth_store as _sync_nous_pool_from_auth_store,
    _token_fingerprint as _token_fingerprint,
    _try_import_shared_nous_state as _try_import_shared_nous_state,
    _write_shared_nous_state as _write_shared_nous_state,
    _xai_access_token_is_expiring as _xai_access_token_is_expiring,
    _xai_callback_cors_origin as _xai_callback_cors_origin,
    _xai_oauth_build_authorize_url as _xai_oauth_build_authorize_url,
    _xai_oauth_discovery as _xai_oauth_discovery,
    _xai_oauth_exchange_code_for_tokens as _xai_oauth_exchange_code_for_tokens,
    _xai_start_callback_server as _xai_start_callback_server,
    _xai_validate_inference_base_url as _xai_validate_inference_base_url,
    _xai_validate_loopback_redirect_uri as _xai_validate_loopback_redirect_uri,
    _xai_validate_oauth_endpoint as _xai_validate_oauth_endpoint,
    _xai_wait_for_callback as _xai_wait_for_callback,
    atomic_replace as atomic_replace,
    base64 as base64,
    clear_provider_auth as clear_provider_auth,
    contextmanager as contextmanager,
    datetime as datetime,
    deactivate_provider as deactivate_provider,
    detect_zai_endpoint as detect_zai_endpoint,
    env_var_alias_enabled as env_var_alias_enabled,
    fcntl as fcntl,
    fetch_nous_models as fetch_nous_models,
    format_auth_error as format_auth_error,
    get_active_provider as get_active_provider,
    get_agent_home as get_agent_home,
    get_anthropic_key as get_anthropic_key,
    get_api_key_provider_status as get_api_key_provider_status,
    get_auth_provider_display_name as get_auth_provider_display_name,
    get_auth_status as get_auth_status,
    get_codex_auth_status as get_codex_auth_status,
    get_external_process_provider_status as get_external_process_provider_status,
    get_gemini_oauth_auth_status as get_gemini_oauth_auth_status,
    get_minimax_oauth_auth_status as get_minimax_oauth_auth_status,
    get_nous_auth_status as get_nous_auth_status,
    get_provider_auth_state as get_provider_auth_state,
    get_qwen_auth_status as get_qwen_auth_status,
    get_xai_oauth_auth_status as get_xai_oauth_auth_status,
    has_usable_secret as has_usable_secret,
    hashlib as hashlib,
    httpx as httpx,
    invalidate_nous_auth_status_cache as invalidate_nous_auth_status_cache,
    is_known_auth_provider as is_known_auth_provider,
    is_provider_explicitly_configured as is_provider_explicitly_configured,
    is_rate_limited_auth_error as is_rate_limited_auth_error,
    is_source_suppressed as is_source_suppressed,
    is_truthy_value as is_truthy_value,
    json as json,
    logger as logger,
    logging as logging,
    mark_provider_active_if_unset as mark_provider_active_if_unset,
    msvcrt as msvcrt,
    nous_inference_base_url as nous_inference_base_url,
    nous_portal_base_url as nous_portal_base_url,
    os as os,
    owned_text_descriptor as owned_text_descriptor,
    parse_qs as parse_qs,
    persist_nous_credentials as persist_nous_credentials,
    read_credential_pool as read_credential_pool,
    refresh_codex_oauth_pure as refresh_codex_oauth_pure,
    refresh_nous_oauth_from_state as refresh_nous_oauth_from_state,
    refresh_nous_oauth_pure as refresh_nous_oauth_pure,
    refresh_xai_oauth_pure as refresh_xai_oauth_pure,
    resolve_api_key_provider_credentials as resolve_api_key_provider_credentials,
    resolve_codex_runtime_credentials as resolve_codex_runtime_credentials,
    resolve_external_process_provider_credentials as resolve_external_process_provider_credentials,
    resolve_gemini_oauth_runtime_credentials as resolve_gemini_oauth_runtime_credentials,
    resolve_minimax_oauth_runtime_credentials as resolve_minimax_oauth_runtime_credentials,
    resolve_nous_access_token as resolve_nous_access_token,
    resolve_nous_runtime_credentials as resolve_nous_runtime_credentials,
    resolve_provider as resolve_provider,
    resolve_qwen_runtime_credentials as resolve_qwen_runtime_credentials,
    resolve_xai_oauth_runtime_credentials as resolve_xai_oauth_runtime_credentials,
    sanitize_borrowed_credential_payload as sanitize_borrowed_credential_payload,
    shlex as shlex,
    shutil as shutil,
    ssl as ssl,
    stat as stat,
    suppress_credential_source as suppress_credential_source,
    sys as sys,
    threading as threading,
    time as time,
    timezone as timezone,
    unsuppress_credential_source as unsuppress_credential_source,
    urlencode as urlencode,
    urlparse as urlparse,
    uuid as uuid,
    write_credential_pool as write_credential_pool,
)

def _prompt_manual_callback_paste(redirect_uri: str) -> dict:
    """Read a callback URL from stdin as a fallback for browser-only remotes.

    Used when ``--manual-paste`` is set or when the loopback listener
    cannot bind.  Returns the parsed callback dict (same shape as the
    HTTP handler output) so the existing state / error validation in
    the caller works unchanged.  See #26923.
    """
    print()
    print("─── Manual callback paste ─────────────────────────────────────")
    print("After approving in your browser, your browser will try to load")
    print(f"  {redirect_uri}")
    print("which fails (the loopback listener is on this remote machine,")
    print("not on your laptop) — that is expected.  Copy the FULL URL")
    print("from your browser's address bar of that failed page and paste")
    print("it below.  A bare '?code=...&state=...' fragment also works.")
    print("───────────────────────────────────────────────────────────────")
    try:
        raw = input("Callback URL: ")
    except (EOFError, KeyboardInterrupt):
        raw = ""
    return credential_service._parse_pasted_callback(raw)


def _print_loopback_ssh_hint(redirect_uri: str, *, docs_url: str | None = None) -> None:
    """Print an SSH tunnel hint when running a loopback-redirect OAuth flow on a
    remote host. The auth server (xAI, ...) will redirect the user's
    browser to ``127.0.0.1:<port>/callback``. If the browser is on a different
    machine than the loopback listener (the usual SSH case), the redirect can't
    reach the listener without a local port forward.

    The hint is best-effort: silent if we don't think we're remote, or if we
    can't parse a host/port out of the redirect URI.

    Pass ``docs_url`` for a provider-specific guide (e.g. the xAI Grok OAuth
    page); the generic OAuth-over-SSH guide is always shown after it.
    """
    if not credential_service._is_remote_session():
        return
    try:
        parsed = urlparse(redirect_uri)
    except Exception:
        return
    host = parsed.hostname or ""
    port = parsed.port
    if host not in {"127.0.0.1", "::1", "localhost"} or not port:
        return
    divider = "-" * 60
    print()
    print(divider)
    print("Remote session detected — SSH tunnel required")
    print(divider)
    print(f"Superforecasting Agent is waiting for the OAuth callback on {redirect_uri}")
    print("but your browser is on a different machine. Run this command")
    print("in a NEW terminal on your local machine BEFORE opening the URL:")
    print()
    print(f"  ssh -N -L {port}:127.0.0.1:{port} {credential_service._ssh_user_at_host()}")
    print()
    print("Then open the authorize URL above in your local browser.")
    print()
    print("No SSH client (Cloud Shell / Codespaces / web IDE)?  Re-run with")
    print("`--manual-paste` to skip the loopback listener and paste the failed")
    print("callback URL directly.")
    if docs_url:
        print(f"Provider docs:      {docs_url}")
    print(f"SSH/jump-box guide: {OAUTH_OVER_SSH_DOCS_URL}")
    print(divider)
    print()


def _update_config_for_provider(
    provider_id: str,
    inference_base_url: str,
    default_model: Optional[str] = None,
) -> Path:
    """Update config.yaml and auth.json to reflect the active provider.

    When *default_model* is provided the function also writes it as the
    ``model.default`` value.  This prevents a race condition where the
    gateway (which re-reads config per-message) picks up the new provider
    before the caller has finished model selection, resulting in a
    mismatched model/provider (e.g. ``anthropic/claude-opus-4.6`` sent to
    MiniMax's API).
    """
    # Update config.yaml model section
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = read_raw_config()

    current_model = config.get("model")
    if isinstance(current_model, dict):
        model_cfg = dict(current_model)
    elif isinstance(current_model, str) and current_model.strip():
        model_cfg = {"default": current_model.strip()}
    else:
        model_cfg = {}

    model_cfg["provider"] = provider_id
    if inference_base_url and inference_base_url.strip():
        model_cfg["base_url"] = inference_base_url.rstrip("/")
    else:
        # Clear stale base_url to prevent contamination when switching providers
        model_cfg.pop("base_url", None)

    # Clear stale api_key/api_mode left over from a previous custom provider.
    # When the user switches from e.g. a MiniMax custom endpoint
    # (api_mode=anthropic_messages, api_key=mxp-...) to a built-in provider
    # (e.g. OpenRouter), the stale api_key/api_mode would override the new
    # provider's credentials and transport choice.  Built-in providers that
    # need a specific api_mode (copilot, xai) set it at request-resolution
    # time via `_copilot_runtime_api_mode` / `_detect_api_mode_for_url`, so
    # removing the persisted value here is safe.
    model_cfg.pop("api_key", None)
    model_cfg.pop("api_mode", None)

    # When switching to a non-OpenRouter provider, ensure model.default is
    # valid for the new provider.  An OpenRouter-formatted name like
    # "anthropic/claude-opus-4.6" will fail on direct-API providers.
    if default_model:
        cur_default = model_cfg.get("default", "")
        if not cur_default or "/" in cur_default:
            model_cfg["default"] = default_model

    config["model"] = model_cfg

    save_config(config)
    # Set active_provider in auth.json so auto-resolution picks this provider
    with credential_service._auth_store_lock():
        auth_store = credential_service._load_auth_store()
        auth_store["active_provider"] = provider_id
        credential_service._save_auth_store(auth_store)

    return config_path


def _get_config_provider() -> Optional[str]:
    """Return model.provider from config.yaml, normalized, if present."""
    try:
        config = read_raw_config()
    except Exception:
        return None
    if not config:
        return None
    model = config.get("model")
    if not isinstance(model, dict):
        return None
    provider = model.get("provider")
    if not isinstance(provider, str):
        return None
    provider = provider.strip().lower()
    return provider or None


def _config_provider_matches(provider_id: Optional[str]) -> bool:
    """Return True when config.yaml currently selects *provider_id*."""
    if not provider_id:
        return False
    return _get_config_provider() == provider_id.strip().lower()


def _should_reset_config_provider_on_logout(provider_id: Optional[str]) -> bool:
    """Return True when logout should reset the model provider config."""
    if not provider_id:
        return False
    normalized = provider_id.strip().lower()
    return normalized in PROVIDER_REGISTRY and _config_provider_matches(normalized)


def _logout_default_provider_from_config() -> Optional[str]:
    """Fallback logout target when auth.json has no active provider.

    `hermes logout` historically keyed off auth.json.active_provider only.
    That left users stuck when auth state had already been cleared but
    config.yaml still selected an OAuth provider such as openai-codex for the
    agent model: there was no active auth provider to target, so logout printed
    "No provider is currently logged in" and never reset model.provider.
    """
    provider = _get_config_provider()
    if provider in {"nous", "openai-codex", "xai-oauth"}:
        return provider
    return None


def _reset_config_provider() -> Path:
    """Reset config.yaml provider back to auto after logout."""
    config_path = get_config_path()
    if not config_path.exists():
        return config_path

    config = read_raw_config()
    if not config:
        return config_path

    model = config.get("model")
    if isinstance(model, dict):
        model["provider"] = "auto"
        if "base_url" in model:
            model["base_url"] = OPENROUTER_BASE_URL
    save_config(config)
    return config_path


def _prompt_model_selection(
    model_ids: List[str],
    current_model: str = "",
    pricing: Optional[Dict[str, Dict[str, str]]] = None,
    unavailable_models: Optional[List[str]] = None,
    portal_url: str = "",
) -> Optional[str]:
    """Interactive model selection. Puts current_model first with a marker. Returns chosen model ID or None.

    If *pricing* is provided (``{model_id: {prompt, completion}}``), a compact
    price indicator is shown next to each model in aligned columns.

    If *unavailable_models* is provided, those models are shown grayed out
    and unselectable, with an upgrade link to *portal_url*.
    """
    from superforecasting_agent.runtime.models import _format_price_per_mtok

    _unavailable = unavailable_models or []

    # Reorder: current model first, then the rest (deduplicated)
    ordered = []
    if current_model and current_model in model_ids:
        ordered.append(current_model)
    for mid in model_ids:
        if mid not in ordered:
            ordered.append(mid)

    # All models for column-width computation (selectable + unavailable)
    all_models = list(ordered) + list(_unavailable)

    # Column-aligned labels when pricing is available
    has_pricing = bool(pricing and any(pricing.get(m) for m in all_models))
    name_col = max((len(m) for m in all_models), default=0) + 2 if has_pricing else 0

    # Pre-compute formatted prices and dynamic column widths
    _price_cache: dict[str, tuple[str, str, str]] = {}
    price_col = 3  # minimum width
    cache_col = 0  # only set if any model has cache pricing
    has_cache = False
    if has_pricing:
        for mid in all_models:
            p = pricing.get(mid)  # type: ignore[union-attr]
            if p:
                inp = _format_price_per_mtok(p.get("prompt", ""))
                out = _format_price_per_mtok(p.get("completion", ""))
                cache_read = p.get("input_cache_read", "")
                cache = _format_price_per_mtok(cache_read) if cache_read else ""
                if cache:
                    has_cache = True
            else:
                inp, out, cache = "", "", ""
            _price_cache[mid] = (inp, out, cache)
            price_col = max(price_col, len(inp), len(out))
            cache_col = max(cache_col, len(cache))
        if has_cache:
            cache_col = max(cache_col, 5)  # minimum: "Cache" header

    def _label(mid):
        if has_pricing:
            inp, out, cache = _price_cache.get(mid, ("", "", ""))
            price_part = f" {inp:>{price_col}}  {out:>{price_col}}"
            if has_cache:
                price_part += f"  {cache:>{cache_col}}"
            base = f"{mid:<{name_col}}{price_part}"
        else:
            base = mid
        if mid == current_model:
            base += "  ← currently in use"
        return base

    # Default cursor on the current model (index 0 if it was reordered to top)
    default_idx = 0

    # Build a pricing header hint for the menu title
    menu_title = "Select default model:"
    if has_pricing:
        # Align the header with the model column.
        # Each choice is "  {label}" (2 spaces) and simple_term_menu prepends
        # a 3-char cursor region ("-> " or "   "), so content starts at col 5.
        pad = " " * 5
        header = f"\n{pad}{'':>{name_col}} {'In':>{price_col}}  {'Out':>{price_col}}"
        if has_cache:
            header += f"  {'Cache':>{cache_col}}"
        menu_title += header + "  /Mtok"

    # ANSI escape for dim text
    _DIM = "\033[2m"
    _RESET = "\033[0m"

    # Try arrow-key menu first, fall back to number input
    try:
        from simple_term_menu import TerminalMenu

        choices = [f"  {_label(mid)}" for mid in ordered]
        choices.append("  Enter custom model name")
        choices.append("  Skip (keep current)")

        # Print the unavailable block BEFORE the menu via regular print().
        # simple_term_menu pads title lines to terminal width (causes wrapping),
        # so we keep the title minimal and use stdout for the static block.
        # clear_screen=False means our printed output stays visible above.
        _upgrade_url = (portal_url or DEFAULT_NOUS_PORTAL_URL).rstrip("/")
        if _unavailable:
            print(menu_title)
            print()
            for mid in _unavailable:
                print(f"{_DIM}     {_label(mid)}{_RESET}")
            print()
            print(f"{_DIM}  ── Upgrade at {_upgrade_url} for paid models ──{_RESET}")
            print()
            effective_title = "Available free models:"
        else:
            effective_title = menu_title

        menu = TerminalMenu(
            choices,
            cursor_index=default_idx,
            menu_cursor="-> ",
            menu_cursor_style=("fg_green", "bold"),
            menu_highlight_style=("fg_green",),
            cycle_cursor=True,
            clear_screen=False,
            title=effective_title,
        )
        idx = menu.show()
        from superforecasting_agent.runtime.curses_ui import flush_stdin
        flush_stdin()
        if idx is None:
            return None
        print()
        if idx < len(ordered):
            return ordered[idx]
        elif idx == len(ordered):
            custom = input("Enter model name: ").strip()
            return custom if custom else None
        return None
    except (ImportError, NotImplementedError, OSError, subprocess.SubprocessError):
        pass

    # Fallback: numbered list
    print(menu_title)
    num_width = len(str(len(ordered) + 2))
    for i, mid in enumerate(ordered, 1):
        print(f"  {i:>{num_width}}. {_label(mid)}")
    n = len(ordered)
    print(f"  {n + 1:>{num_width}}. Enter custom model name")
    print(f"  {n + 2:>{num_width}}. Skip (keep current)")

    if _unavailable:
        _upgrade_url = (portal_url or DEFAULT_NOUS_PORTAL_URL).rstrip("/")
        print()
        print(f"  {_DIM}── Unavailable models (requires paid tier — upgrade at {_upgrade_url}) ──{_RESET}")
        for mid in _unavailable:
            print(f"  {'':>{num_width}}  {_DIM}{_label(mid)}{_RESET}")
    print()

    while True:
        try:
            choice = input(f"Choice [1-{n + 2}] (default: skip): ").strip()
            if not choice:
                return None
            idx = int(choice)
            if 1 <= idx <= n:
                return ordered[idx - 1]
            elif idx == n + 1:
                custom = input("Enter model name: ").strip()
                return custom if custom else None
            elif idx == n + 2:
                return None
            print(f"Please enter 1-{n + 2}")
        except ValueError:
            print("Please enter a number")
        except (KeyboardInterrupt, EOFError):
            return None


def _save_model_choice(model_id: str) -> None:
    """Save the selected model to config.yaml (single source of truth).

    The model is stored in config.yaml only — NOT in .env.  This avoids
    conflicts in multi-agent setups where env vars would stomp each other.
    """
    from superforecasting_agent.runtime.config import save_config, load_config

    config = load_config()
    # Always use dict format so provider/base_url can be stored alongside
    if isinstance(config.get("model"), dict):
        config["model"]["default"] = model_id
    else:
        config["model"] = {"default": model_id}
    save_config(config)


def login_command(args) -> None:
    """Deprecated: use the model or setup commands instead."""
    print("The 'hermes login' compatibility command has been removed.")
    print(f"Use '{_PRIMARY_CLI} auth' to manage credentials,")
    print(
        f"'{_PRIMARY_CLI} model' to select a provider, or "
        f"'{_PRIMARY_CLI} setup' for full setup."
    )
    raise SystemExit(0)


def _login_openai_codex(
    args,
    pconfig: ProviderConfig,
    *,
    force_new_login: bool = False,
) -> None:
    """OpenAI Codex login via device code flow. Tokens stored in ~/.hermes/auth.json."""

    del args, pconfig  # kept for parity with other provider login helpers

    # Check for existing Hermes-owned credentials
    if not force_new_login:
        try:
            existing = credential_service.resolve_codex_runtime_credentials()
            # Verify the resolved token is actually usable (not expired).
            # resolve_codex_runtime_credentials attempts refresh, so if we get
            # here the token should be valid — but double-check before telling
            # the user "Login successful!".
            _resolved_key = existing.get("api_key", "")
            if isinstance(_resolved_key, str) and _resolved_key and not credential_service._codex_access_token_is_expiring(_resolved_key, 60):
                print("Existing Codex credentials found in the runtime auth store.")
                try:
                    reuse = input("Use existing credentials? [Y/n]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    reuse = "y"
                if reuse in {"", "y", "yes"}:
                    config_path = _update_config_for_provider("openai-codex", existing.get("base_url", DEFAULT_CODEX_BASE_URL))
                    print()
                    print("Login successful!")
                    print(f"  Config updated: {config_path} (model.provider=openai-codex)")
                    return
            else:
                print("Existing Codex credentials are expired. Starting fresh login...")
        except credential_service.AuthError:
            pass

    # Check for existing Codex CLI tokens we can import
    if not force_new_login:
        cli_tokens = credential_service._import_codex_cli_tokens()
        if cli_tokens:
            print("Found existing Codex CLI credentials at ~/.codex/auth.json")
            print(
                "Superforecasting Agent will create its own session to avoid "
                "conflicts with Codex CLI / VS Code."
            )
            try:
                do_import = input("Import these credentials? (a separate login is recommended) [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                do_import = "n"
            if do_import in {"y", "yes"}:
                credential_service._save_codex_tokens(cli_tokens)
                base_url = os.getenv("HERMES_CODEX_BASE_URL", "").strip().rstrip("/") or DEFAULT_CODEX_BASE_URL
                config_path = _update_config_for_provider("openai-codex", base_url)
                print()
                print("Credentials imported. Note: if Codex CLI refreshes its token,")
                print("Superforecasting Agent will keep working independently with its own session.")
                print(f"  Config updated: {config_path} (model.provider=openai-codex)")
                return

    # Run a fresh device code flow — the fork gets its own OAuth session
    print()
    print("Signing in to OpenAI Codex...")
    print("(Superforecasting Agent creates its own session — won't affect Codex CLI or VS Code)")
    print()

    creds = _codex_device_code_login()

    # Save tokens to the runtime auth store
    credential_service._save_codex_tokens(creds["tokens"], creds.get("last_refresh"))
    config_path = _update_config_for_provider("openai-codex", creds.get("base_url", DEFAULT_CODEX_BASE_URL))
    print()
    print("Login successful!")
    from superforecasting_agent.constants import display_agent_home as _dhh
    print(f"  Auth state: {_dhh()}/auth.json")
    print(f"  Config updated: {config_path} (model.provider=openai-codex)")


def _login_xai_oauth(
    args,
    pconfig: ProviderConfig,
    *,
    force_new_login: bool = False,
) -> None:
    del pconfig

    if not force_new_login:
        try:
            existing = credential_service.resolve_xai_oauth_runtime_credentials()
            api_key = existing.get("api_key", "")
            if isinstance(api_key, str) and api_key and not credential_service._xai_access_token_is_expiring(api_key, 60):
                print("Existing xAI OAuth credentials found in the runtime auth store.")
                try:
                    reuse = input("Use existing credentials? [Y/n]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    reuse = "y"
                if reuse in {"", "y", "yes"}:
                    config_path = _update_config_for_provider(
                        "xai-oauth",
                        existing.get("base_url", DEFAULT_XAI_OAUTH_BASE_URL),
                    )
                    print()
                    print("Login successful!")
                    print(f"  Config updated: {config_path} (model.provider=xai-oauth)")
                    return
        except credential_service.AuthError:
            pass

    print()
    print("Signing in to xAI Grok OAuth (SuperGrok Subscription)...")
    print("(Superforecasting Agent creates its own local OAuth session)")
    print()

    timeout_seconds = float(getattr(args, "timeout", None) or 20.0)
    open_browser = not getattr(args, "no_browser", False)
    if credential_service._is_remote_session():
        open_browser = False
    manual_paste = bool(getattr(args, "manual_paste", False))

    creds = _xai_oauth_loopback_login(
        timeout_seconds=timeout_seconds,
        open_browser=open_browser,
        manual_paste=manual_paste,
    )
    credential_service._save_xai_oauth_tokens(
        creds["tokens"],
        discovery=creds.get("discovery"),
        redirect_uri=creds.get("redirect_uri", ""),
        last_refresh=creds.get("last_refresh"),
    )
    config_path = _update_config_for_provider("xai-oauth", creds.get("base_url", DEFAULT_XAI_OAUTH_BASE_URL))
    print()
    print("Login successful!")
    from superforecasting_agent.constants import display_agent_home as _dhh
    print(f"  Auth state: {_dhh()}/auth.json")
    print(f"  Config updated: {config_path} (model.provider=xai-oauth)")


def _xai_oauth_loopback_login(
    *,
    timeout_seconds: float = 20.0,
    open_browser: bool = True,
    manual_paste: bool = False,
) -> Dict[str, Any]:
    """Run the xAI OAuth PKCE flow.

    When ``manual_paste=True`` the loopback HTTP listener is skipped
    entirely and the user is prompted to paste the failed callback
    URL into stdin (regression fix for #26923 — browser-only remote
    consoles like GCP Cloud Shell / GitHub Codespaces / EC2 Instance
    Connect, where the laptop's browser can't reach 127.0.0.1 on the
    remote VM).  The same PKCE verifier, ``state``, and ``nonce`` are
    used for both paths so the upstream-side OAuth flow is identical.
    """
    discovery = credential_service._xai_oauth_discovery(timeout_seconds)
    authorization_endpoint = discovery["authorization_endpoint"]
    token_endpoint = discovery["token_endpoint"]

    if manual_paste:
        # No HTTP listener — synthesize a redirect_uri matching what
        # the server would have bound to so the authorize URL the user
        # opens (and the redirect_uri sent in the token exchange) stay
        # byte-identical to the loopback path.  xAI's token endpoint
        # cross-checks redirect_uri against the authorize request.
        redirect_uri = (
            f"http://{XAI_OAUTH_REDIRECT_HOST}:{XAI_OAUTH_REDIRECT_PORT}"
            f"{XAI_OAUTH_REDIRECT_PATH}"
        )
        credential_service._xai_validate_loopback_redirect_uri(redirect_uri)
        code_verifier = credential_service._oauth_pkce_code_verifier()
        code_challenge = credential_service._oauth_pkce_code_challenge(code_verifier)
        state = uuid.uuid4().hex
        nonce = uuid.uuid4().hex
        authorize_url = credential_service._xai_oauth_build_authorize_url(
            authorization_endpoint=authorization_endpoint,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            state=state,
            nonce=nonce,
        )

        print("Open this URL to authorize Superforecasting Agent with xAI:")
        print(authorize_url)
        callback = _prompt_manual_callback_paste(redirect_uri)
    else:
        server, thread, callback_result, redirect_uri = credential_service._xai_start_callback_server()
        try:
            credential_service._xai_validate_loopback_redirect_uri(redirect_uri)
            code_verifier = credential_service._oauth_pkce_code_verifier()
            code_challenge = credential_service._oauth_pkce_code_challenge(code_verifier)
            state = uuid.uuid4().hex
            nonce = uuid.uuid4().hex
            authorize_url = credential_service._xai_oauth_build_authorize_url(
                authorization_endpoint=authorization_endpoint,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                state=state,
                nonce=nonce,
            )

            print("Open this URL to authorize Superforecasting Agent with xAI:")
            print(authorize_url)
            print()
            print(f"Waiting for callback on {redirect_uri}")

            _print_loopback_ssh_hint(redirect_uri, docs_url=XAI_OAUTH_DOCS_URL)

            if open_browser and not credential_service._is_remote_session():
                try:
                    opened = webbrowser.open(authorize_url)
                except Exception:
                    opened = False
                if opened:
                    print("Browser opened for xAI authorization.")
                else:
                    print("Could not open the browser automatically; use the URL above.")

            callback = credential_service._xai_wait_for_callback(
                server,
                thread,
                callback_result,
                timeout_seconds=max(30.0, timeout_seconds * 9),
            )
        except Exception:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
            try:
                thread.join(timeout=1.0)
            except Exception:
                pass
            raise

    if callback.get("error"):
        detail = callback.get("error_description") or callback["error"]
        raise credential_service.AuthError(
            f"xAI authorization failed: {detail}",
            provider="xai-oauth",
            code="xai_authorization_failed",
        )
    if callback.get("state") != state:
        raise credential_service.AuthError(
            "xAI authorization failed: state mismatch.",
            provider="xai-oauth",
            code="xai_state_mismatch",
        )
    code = str(callback.get("code") or "").strip()
    if not code:
        raise credential_service.AuthError(
            "xAI authorization failed: missing authorization code.",
            provider="xai-oauth",
            code="xai_code_missing",
        )

    payload = credential_service._xai_oauth_exchange_code_for_tokens(
        token_endpoint=token_endpoint,
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        code_challenge=code_challenge,
        timeout_seconds=timeout_seconds,
    )
    access_token = str(payload.get("access_token", "") or "").strip()
    refresh_token = str(payload.get("refresh_token", "") or "").strip()
    if not access_token:
        raise credential_service.AuthError(
            "xAI token exchange did not return an access_token.",
            provider="xai-oauth",
            code="xai_token_exchange_invalid",
        )
    if not refresh_token:
        raise credential_service.AuthError(
            "xAI token exchange did not return a refresh_token.",
            provider="xai-oauth",
            code="xai_token_exchange_invalid",
        )

    base_url = credential_service._xai_validate_inference_base_url(
        os.getenv("HERMES_XAI_BASE_URL", "").strip().rstrip("/")
        or os.getenv("XAI_BASE_URL", "").strip().rstrip("/"),
        fallback=DEFAULT_XAI_OAUTH_BASE_URL,
    )
    return {
        "tokens": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": str(payload.get("id_token", "") or "").strip(),
            "expires_in": payload.get("expires_in"),
            "token_type": str(payload.get("token_type") or "Bearer").strip() or "Bearer",
        },
        "discovery": discovery,
        "redirect_uri": redirect_uri,
        "base_url": base_url,
        "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "oauth-loopback",
    }


def _codex_device_code_login() -> Dict[str, Any]:
    """Run the OpenAI device code login flow and return credentials dict."""
    import time as _time

    issuer = "https://auth.openai.com"
    client_id = CODEX_OAUTH_CLIENT_ID

    # Step 1: Request device code
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.post(
                f"{issuer}/api/accounts/deviceauth/usercode",
                json={"client_id": client_id},
                headers={"Content-Type": "application/json"},
            )
    except Exception as exc:
        raise credential_service.AuthError(
            f"Failed to request device code: {exc}",
            provider="openai-codex", code="device_code_request_failed",
        )

    if resp.status_code != 200:
        raise credential_service.AuthError(
            f"Device code request returned status {resp.status_code}.",
            provider="openai-codex", code="device_code_request_error",
        )

    device_data = resp.json()
    user_code = device_data.get("user_code", "")
    device_auth_id = device_data.get("device_auth_id", "")
    poll_interval = max(3, int(device_data.get("interval", "5")))

    if not user_code or not device_auth_id:
        raise credential_service.AuthError(
            "Device code response missing required fields.",
            provider="openai-codex", code="device_code_incomplete",
        )

    # Step 2: Show user the code
    print("To continue, follow these steps:\n")
    print("  1. Open this URL in your browser:")
    print(f"     \033[94m{issuer}/codex/device\033[0m\n")
    print("  2. Enter this code:")
    print(f"     \033[94m{user_code}\033[0m\n")
    print("Waiting for sign-in... (press Ctrl+C to cancel)")

    # Step 3: Poll for authorization code
    max_wait = 15 * 60  # 15 minutes
    start = _time.monotonic()
    code_resp = None

    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            while _time.monotonic() - start < max_wait:
                _time.sleep(poll_interval)
                poll_resp = client.post(
                    f"{issuer}/api/accounts/deviceauth/token",
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Content-Type": "application/json"},
                )

                if poll_resp.status_code == 200:
                    code_resp = poll_resp.json()
                    break
                elif poll_resp.status_code in {403, 404}:
                    continue  # User hasn't completed login yet
                else:
                    raise credential_service.AuthError(
                        f"Device auth polling returned status {poll_resp.status_code}.",
                        provider="openai-codex", code="device_code_poll_error",
                    )
    except KeyboardInterrupt:
        print("\nLogin cancelled.")
        raise SystemExit(130)

    if code_resp is None:
        raise credential_service.AuthError(
            "Login timed out after 15 minutes.",
            provider="openai-codex", code="device_code_timeout",
        )

    # Step 4: Exchange authorization code for tokens
    authorization_code = code_resp.get("authorization_code", "")
    code_verifier = code_resp.get("code_verifier", "")
    redirect_uri = f"{issuer}/deviceauth/callback"

    if not authorization_code or not code_verifier:
        raise credential_service.AuthError(
            "Device auth response missing authorization_code or code_verifier.",
            provider="openai-codex", code="device_code_incomplete_exchange",
        )

    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            token_resp = client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as exc:
        raise credential_service.AuthError(
            f"Token exchange failed: {exc}",
            provider="openai-codex", code="token_exchange_failed",
        )

    if token_resp.status_code != 200:
        raise credential_service.AuthError(
            f"Token exchange returned status {token_resp.status_code}.",
            provider="openai-codex", code="token_exchange_error",
        )

    tokens = token_resp.json()
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")

    if not access_token:
        raise credential_service.AuthError(
            "Token exchange did not return an access_token.",
            provider="openai-codex", code="token_exchange_no_access_token",
        )

    # Return tokens for the caller to persist (no longer writes to ~/.codex/)
    base_url = (
        os.getenv("HERMES_CODEX_BASE_URL", "").strip().rstrip("/")
        or DEFAULT_CODEX_BASE_URL
    )

    return {
        "tokens": {
            "access_token": access_token,
            "refresh_token": refresh_token,
        },
        "base_url": base_url,
        "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "auth_mode": "chatgpt",
        "source": "device-code",
    }


def _minimax_oauth_login(
    *, region: str = "global", open_browser: bool = True,
    timeout_seconds: float = 15.0,
) -> Dict[str, Any]:
    """Run MiniMax OAuth flow, persist tokens, return auth state dict."""
    pconfig = PROVIDER_REGISTRY["minimax-oauth"]
    if region == "cn":
        portal_base_url = pconfig.extra["cn_portal_base_url"]
        inference_base_url = pconfig.extra["cn_inference_base_url"]
    else:
        portal_base_url = pconfig.portal_base_url
        inference_base_url = pconfig.inference_base_url

    verifier, challenge, state = credential_service._minimax_pkce_pair()

    if credential_service._is_remote_session():
        open_browser = False

    print(f"Starting Superforecasting Agent login via MiniMax ({region}) OAuth...")
    print(f"Portal: {portal_base_url}")

    with httpx.Client(timeout=httpx.Timeout(timeout_seconds),
                      headers={"Accept": "application/json"},
                      follow_redirects=True) as client:
        code_data = credential_service._minimax_request_user_code(
            client, portal_base_url=portal_base_url,
            client_id=pconfig.client_id,
            code_challenge=challenge, state=state,
        )
        verification_url = str(code_data["verification_uri"])
        user_code = str(code_data["user_code"])

        print()
        print("To continue:")
        print(f"  1. Open: {verification_url}")
        print(f"  2. If prompted, enter code: {user_code}")
        if open_browser:
            if webbrowser.open(verification_url):
                print("  (Opened browser for verification)")
            else:
                print("  Could not open browser automatically -- use the URL above.")

        interval_raw = code_data.get("interval")
        interval_ms = int(interval_raw) if interval_raw is not None else None
        print("Waiting for approval...")

        token_data = credential_service._minimax_poll_token(
            client, portal_base_url=portal_base_url,
            client_id=pconfig.client_id,
            user_code=user_code, code_verifier=verifier,
            expired_in=int(code_data["expired_in"]),
            interval_ms=interval_ms,
        )

    now = datetime.now(timezone.utc)
    expires_at_unix = credential_service._minimax_resolve_token_expiry_unix(
        int(token_data["expired_in"]), now=now,
    )
    expires_in_s = max(0, int(expires_at_unix - now.timestamp()))

    auth_state = {
        "provider": "minimax-oauth",
        "region": region,
        "portal_base_url": portal_base_url,
        "inference_base_url": inference_base_url,
        "client_id": pconfig.client_id,
        "scope": MINIMAX_OAUTH_SCOPE,
        "token_type": token_data.get("token_type", "Bearer"),
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "resource_url": token_data.get("resource_url"),
        "obtained_at": now.isoformat(),
        "expires_at": datetime.fromtimestamp(expires_at_unix, tz=timezone.utc).isoformat(),
        "expires_in": expires_in_s,
    }

    credential_service._minimax_save_auth_state(auth_state)
    print("\u2713 MiniMax OAuth login successful.")
    if msg := token_data.get("notification_message"):
        print(f"Note from MiniMax: {msg}")
    return auth_state


def _login_minimax_oauth(args, pconfig: ProviderConfig) -> None:
    """CLI entry for MiniMax OAuth login."""
    region = getattr(args, "region", None) or "global"
    open_browser = not getattr(args, "no_browser", False)
    timeout = getattr(args, "timeout", None) or 15.0
    try:
        _minimax_oauth_login(
            region=region, open_browser=open_browser, timeout_seconds=timeout,
        )
    except credential_service.AuthError as exc:
        print(credential_service.format_auth_error(exc))
        raise SystemExit(1)


def _nous_device_code_login(
    *,
    portal_base_url: Optional[str] = None,
    inference_base_url: Optional[str] = None,
    client_id: Optional[str] = None,
    scope: Optional[str] = None,
    open_browser: bool = True,
    timeout_seconds: float = 15.0,
    insecure: bool = False,
    ca_bundle: Optional[str] = None,
    min_key_ttl_seconds: int = 5 * 60,
) -> Dict[str, Any]:
    """Run the Nous device-code flow and return full OAuth state without persisting."""
    pconfig = PROVIDER_REGISTRY["nous"]
    portal_base_url = (
        portal_base_url
        or nous_portal_base_url()
        or pconfig.portal_base_url
    ).rstrip("/")
    requested_inference_url = (
        inference_base_url
        or nous_inference_base_url()
        or pconfig.inference_base_url
    ).rstrip("/")
    client_id = client_id or pconfig.client_id
    scope, explicit_scope = credential_service._nous_device_scope_with_env_override(
        scope,
        default_scope=pconfig.scope,
    )
    timeout = httpx.Timeout(timeout_seconds)
    verify: bool | str = False if insecure else (ca_bundle if ca_bundle else True)

    if credential_service._is_remote_session():
        open_browser = False

    print(f"Starting Superforecasting Agent login via {pconfig.name}...")
    print(f"Portal: {portal_base_url}")
    if insecure:
        print("TLS verification: disabled (--insecure)")
    elif ca_bundle:
        print(f"TLS verification: custom CA bundle ({ca_bundle})")

    with httpx.Client(timeout=timeout, headers={"Accept": "application/json"}, verify=verify) as client:
        device_data, scope = credential_service._request_nous_device_code_with_scope_fallback(
            client=client,
            portal_base_url=portal_base_url,
            client_id=client_id,
            scope=scope,
            allow_legacy_fallback=not explicit_scope,
        )

        verification_url = str(device_data["verification_uri_complete"])
        user_code = str(device_data["user_code"])
        expires_in = int(device_data["expires_in"])
        interval = int(device_data["interval"])

        print()
        print("To continue:")
        print(f"  1. Open: {verification_url}")
        print(f"  2. If prompted, enter code: {user_code}")

        if open_browser:
            opened = webbrowser.open(verification_url)
            if opened:
                print("  (Opened browser for verification)")
            else:
                print("  Could not open browser automatically — use the URL above.")

        effective_interval = max(1, min(interval, DEVICE_AUTH_POLL_INTERVAL_CAP_SECONDS))
        print(f"Waiting for approval (polling every {effective_interval}s)...")

        token_data = credential_service._poll_for_token(
            client=client,
            portal_base_url=portal_base_url,
            client_id=client_id,
            device_code=str(device_data["device_code"]),
            expires_in=expires_in,
            poll_interval=interval,
        )

    now = datetime.now(timezone.utc)
    token_expires_in = credential_service._coerce_ttl_seconds(token_data.get("expires_in", 0))
    expires_at = now.timestamp() + token_expires_in
    resolved_inference_url = (
        credential_service._optional_base_url(token_data.get("inference_base_url"))
        or requested_inference_url
    )
    if resolved_inference_url != requested_inference_url:
        print(f"Using portal-provided inference URL: {resolved_inference_url}")

    auth_state = {
        "portal_base_url": portal_base_url,
        "inference_base_url": resolved_inference_url,
        "client_id": client_id,
        "scope": token_data.get("scope") or scope,
        "token_type": token_data.get("token_type", "Bearer"),
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token"),
        "obtained_at": now.isoformat(),
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "expires_in": token_expires_in,
        "tls": {
            "insecure": verify is False,
            "ca_bundle": verify if isinstance(verify, str) else None,
        },
        "agent_key": None,
        "agent_key_id": None,
        "agent_key_expires_at": None,
        "agent_key_expires_in": None,
        "agent_key_reused": None,
        "agent_key_obtained_at": None,
    }
    try:
        return credential_service.refresh_nous_oauth_from_state(
            auth_state,
            min_key_ttl_seconds=min_key_ttl_seconds,
            timeout_seconds=timeout_seconds,
            force_refresh=False,
            inference_auth_mode=NOUS_INFERENCE_AUTH_MODE_FRESH,
        )
    except credential_service.AuthError as exc:
        if exc.code == "subscription_required":
            portal_url = auth_state.get(
                "portal_base_url", DEFAULT_NOUS_PORTAL_URL
            ).rstrip("/")
            print()
            print("Your Nous Portal account does not have an active subscription.")
            print(f"  Subscribe here: {portal_url}/billing")
            print()
            print(f"After subscribing, run `{_PRIMARY_CLI} model` again to finish setup.")
            raise SystemExit(1)
        raise


def _login_nous(args, pconfig: ProviderConfig) -> None:
    """Nous Portal device authorization flow."""
    timeout_seconds = getattr(args, "timeout", None) or 15.0
    insecure = bool(getattr(args, "insecure", False))
    ca_bundle = (
        getattr(args, "ca_bundle", None)
        or os.getenv("HERMES_CA_BUNDLE")
        or os.getenv("SSL_CERT_FILE")
    )

    try:
        auth_state = None

        # Codex-style auto-import: before launching a fresh device-code
        # flow, check the shared store for an existing Nous credential
        # from any other profile. If present, offer to rehydrate it.
        shared = credential_service._read_shared_nous_state()
        if shared:
            try:
                shared_path = credential_service._nous_shared_store_path()
            except RuntimeError:
                shared_path = None
            print()
            if shared_path:
                print(f"Found existing Nous OAuth credentials at {shared_path}")
            else:
                print("Found existing shared Nous OAuth credentials")
            try:
                do_import = input("Import these credentials? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                do_import = "y"
            if do_import in {"", "y", "yes"}:
                print("Rehydrating Nous session from shared credentials...")
                auth_state = credential_service._try_import_shared_nous_state(
                    timeout_seconds=timeout_seconds,
                    min_key_ttl_seconds=5 * 60,
                )
                if auth_state is None:
                    print("Could not refresh shared credentials — falling back to device-code login.")

        if auth_state is None:
            auth_state = _nous_device_code_login(
                portal_base_url=getattr(args, "portal_url", None),
                inference_base_url=getattr(args, "inference_url", None),
                client_id=getattr(args, "client_id", None) or pconfig.client_id,
                scope=getattr(args, "scope", None),
                open_browser=not getattr(args, "no_browser", False),
                timeout_seconds=timeout_seconds,
                insecure=insecure,
                ca_bundle=ca_bundle,
                min_key_ttl_seconds=5 * 60,
            )

        inference_base_url = auth_state["inference_base_url"]

        # Snapshot the prior active_provider BEFORE _save_provider_state
        # overwrites it to "nous".  If the user picks "Skip (keep current)"
        # during model selection below, we restore this so the user's previous
        # provider (e.g. openrouter) is preserved.
        with credential_service._auth_store_lock():
            _prior_store = credential_service._load_auth_store()
            prior_active_provider = _prior_store.get("active_provider")

        with credential_service._auth_store_lock():
            auth_store = credential_service._load_auth_store()
            credential_service._save_provider_state(auth_store, "nous", auth_state)
            saved_to = credential_service._save_auth_store(auth_store)

        # Mirror to the shared store so other profiles can one-tap import
        # these credentials. Best-effort: any I/O failure is logged and
        # swallowed inside the helper.
        credential_service._write_shared_nous_state(auth_state)
        credential_service._sync_nous_pool_from_auth_store()

        print()
        print("Login successful!")
        print(f"  Auth state: {saved_to}")

        # Resolve model BEFORE writing provider to config.yaml so we never
        # leave the config in a half-updated state (provider=nous but model
        # still set to the previous provider's model, e.g. opus from
        # OpenRouter).  The auth.json active_provider was already set above.
        selected_model = None
        try:
            runtime_key = auth_state.get("agent_key") or auth_state.get("access_token")
            if not isinstance(runtime_key, str) or not runtime_key:
                raise credential_service.AuthError(
                    "No runtime API key available to fetch models",
                    provider="nous",
                    code="invalid_token",
                )

            from superforecasting_agent.runtime.models import (
                get_curated_nous_model_ids, get_pricing_for_provider,
                check_nous_free_tier, partition_nous_models_by_tier,
                union_with_portal_free_recommendations,
                union_with_portal_paid_recommendations,
            )
            model_ids = get_curated_nous_model_ids()

            print()
            unavailable_models: list = []
            if model_ids:
                pricing = get_pricing_for_provider("nous")
                free_tier = check_nous_free_tier()
                _portal_for_recs = auth_state.get("portal_base_url", "")
                if free_tier:
                    # The Portal's freeRecommendedModels endpoint is the
                    # source of truth for what's free *right now*. Augment
                    # the curated list with anything new the Portal flags
                    # as free so users on older Hermes builds still see
                    # newly-launched free models without a CLI release.
                    model_ids, pricing = union_with_portal_free_recommendations(
                        model_ids, pricing, _portal_for_recs,
                    )
                    model_ids, unavailable_models = partition_nous_models_by_tier(
                        model_ids, pricing, free_tier=True,
                    )
                else:
                    # Paid-tier mirror: pull paidRecommendedModels so newly
                    # launched paid models surface in the picker even if
                    # the in-repo curated list and docs-hosted manifest
                    # haven't caught up yet.
                    model_ids, pricing = union_with_portal_paid_recommendations(
                        model_ids, pricing, _portal_for_recs,
                    )
            _portal = auth_state.get("portal_base_url", "")
            if model_ids:
                print(f"Showing {len(model_ids)} curated models — use \"Enter custom model name\" for others.")
                selected_model = _prompt_model_selection(
                    model_ids, pricing=pricing,
                    unavailable_models=unavailable_models,
                    portal_url=_portal,
                )
            elif unavailable_models:
                _url = (_portal or DEFAULT_NOUS_PORTAL_URL).rstrip("/")
                print("No free models currently available.")
                print(f"Upgrade at {_url} to access paid models.")
            else:
                print("No curated models available for Nous Portal.")
        except Exception as exc:
            message = credential_service.format_auth_error(exc) if isinstance(exc, credential_service.AuthError) else str(exc)
            print()
            print(f"Login succeeded, but could not fetch available models. Reason: {message}")

        # Write provider + model atomically so config is never mismatched.
        # If no model was selected (user picked "Skip (keep current)",
        # model list fetch failed, or no curated models were available),
        # preserve the user's previous provider — don't silently switch
        # them to Nous with a mismatched model.  The Nous OAuth tokens
        # stay saved for future use.
        if not selected_model:
            # Restore the prior active_provider that _save_provider_state
            # overwrote to "nous".  config.yaml model.provider is left
            # untouched, so the user's previous provider is fully preserved.
            with credential_service._auth_store_lock():
                auth_store = credential_service._load_auth_store()
                if prior_active_provider:
                    auth_store["active_provider"] = prior_active_provider
                else:
                    auth_store.pop("active_provider", None)
                credential_service._save_auth_store(auth_store)
            print()
            print("No provider change. Nous credentials saved for future use.")
            print(f"  Run `{_PRIMARY_CLI} model` again to switch to Nous Portal.")
            return

        config_path = _update_config_for_provider(
            "nous", inference_base_url, default_model=selected_model,
        )
        if selected_model:
            _save_model_choice(selected_model)
            print(f"Default model set to: {selected_model}")
        print(f"  Config updated: {config_path} (model.provider=nous)")

    except KeyboardInterrupt:
        print("\nLogin cancelled.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"Login failed: {exc}")
        raise SystemExit(1)


def logout_command(args) -> None:
    """Clear auth state for a provider."""
    provider_id = getattr(args, "provider", None)

    if provider_id and not credential_service.is_known_auth_provider(provider_id):
        print(f"Unknown provider: {provider_id}")
        raise SystemExit(1)

    active = credential_service.get_active_provider()
    target = provider_id or active or _logout_default_provider_from_config()

    if not target:
        print("No provider is currently logged in.")
        return

    should_reset_config = _should_reset_config_provider_on_logout(target)
    provider_name = credential_service.get_auth_provider_display_name(target)

    if credential_service.clear_provider_auth(target) or should_reset_config:
        if should_reset_config:
            _reset_config_provider()
        print(f"Logged out of {provider_name}.")
        if should_reset_config and os.getenv("OPENROUTER_API_KEY"):
            print("Superforecasting Agent will use OpenRouter for inference.")
        elif should_reset_config:
            print(f"Run `{_PRIMARY_CLI} model` or configure an API key to use Superforecasting Agent.")
        else:
            print("Model provider configuration was unchanged.")
    else:
        print(f"No auth state found for {provider_name}.")
