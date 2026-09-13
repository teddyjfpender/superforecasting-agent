# ruff: noqa: E402
"""
Multi-provider authentication system for Superforecasting Agent.

Supports OAuth device code flows (Nous Portal, future: OpenAI Codex) and
traditional API key providers (OpenRouter, custom endpoints). Auth state
is persisted in the runtime auth store with cross-process file locking.

Architecture:
- ProviderConfig registry defines known OAuth providers
- Auth store (auth.json) holds per-provider credential state
- resolve_provider() picks the active provider via priority chain
- resolve_*_runtime_credentials() handles token refresh and key minting
- logout_command() is the CLI entry point for clearing auth

Nous authentication paths:
- Invoke JWT (preferred): use a scoped access_token directly for inference.
- Legacy session key (fallback): mint an opaque 24h key when JWT auth is
  unavailable, or when HERMES_AGENT_USE_LEGACY_SESSION_KEYS is set for
  debugging or rollback.
"""

from __future__ import annotations

import base64 as base64
import hashlib as hashlib
import json as json
import logging as logging
import os as os
import shlex as shlex
import shutil as shutil
import ssl as ssl
import stat as stat
import sys as sys
import threading as threading
import time as time
import uuid as uuid
from contextlib import (
    contextmanager as contextmanager,
)
from datetime import (
    datetime as datetime,
)
from datetime import (
    timezone as timezone,
)
from http.server import (
    BaseHTTPRequestHandler as BaseHTTPRequestHandler,
)
from http.server import (
    HTTPServer as HTTPServer,
)
from http.server import (
    ThreadingHTTPServer as ThreadingHTTPServer,
)
from importlib import (
    import_module as import_module,
)
from pathlib import (
    Path as Path,
)
from types import (
    ModuleType as ModuleType,
)
from typing import (
    Any as Any,
)
from typing import (
    Callable as Callable,
)
from typing import (
    Dict as Dict,
)
from typing import (
    List as List,
)
from typing import (
    Optional as Optional,
)
from typing import (
    Tuple as Tuple,
)
from urllib.parse import (
    parse_qs as parse_qs,
)
from urllib.parse import (
    urlencode as urlencode,
)
from urllib.parse import (
    urlparse as urlparse,
)

import httpx as httpx

from superforecasting_agent.configuration.authentication import (
    _PLACEHOLDER_SECRET_VALUES as _PLACEHOLDER_SECRET_VALUES,
)
from superforecasting_agent.configuration.authentication import (
    DEFAULT_CODEX_BASE_URL as DEFAULT_CODEX_BASE_URL,
)
from superforecasting_agent.configuration.authentication import (
    DEFAULT_COPILOT_ACP_BASE_URL as DEFAULT_COPILOT_ACP_BASE_URL,
)
from superforecasting_agent.configuration.authentication import (
    DEFAULT_GEMINI_CLOUDCODE_BASE_URL as DEFAULT_GEMINI_CLOUDCODE_BASE_URL,
)
from superforecasting_agent.configuration.authentication import (
    DEFAULT_GITHUB_MODELS_BASE_URL as DEFAULT_GITHUB_MODELS_BASE_URL,
)
from superforecasting_agent.configuration.authentication import (
    DEFAULT_NOUS_CLIENT_ID as DEFAULT_NOUS_CLIENT_ID,
)
from superforecasting_agent.configuration.authentication import (
    DEFAULT_NOUS_INFERENCE_URL as DEFAULT_NOUS_INFERENCE_URL,
)
from superforecasting_agent.configuration.authentication import (
    DEFAULT_NOUS_PORTAL_URL as DEFAULT_NOUS_PORTAL_URL,
)
from superforecasting_agent.configuration.authentication import (
    DEFAULT_NOUS_SCOPE as DEFAULT_NOUS_SCOPE,
)
from superforecasting_agent.configuration.authentication import (
    DEFAULT_OLLAMA_CLOUD_BASE_URL as DEFAULT_OLLAMA_CLOUD_BASE_URL,
)
from superforecasting_agent.configuration.authentication import (
    DEFAULT_QWEN_BASE_URL as DEFAULT_QWEN_BASE_URL,
)
from superforecasting_agent.configuration.authentication import (
    DEFAULT_XAI_OAUTH_BASE_URL as DEFAULT_XAI_OAUTH_BASE_URL,
)
from superforecasting_agent.configuration.authentication import (
    KIMI_CODE_BASE_URL as KIMI_CODE_BASE_URL,
)
from superforecasting_agent.configuration.authentication import (
    MINIMAX_OAUTH_CLIENT_ID as MINIMAX_OAUTH_CLIENT_ID,
)
from superforecasting_agent.configuration.authentication import (
    MINIMAX_OAUTH_CN_BASE as MINIMAX_OAUTH_CN_BASE,
)
from superforecasting_agent.configuration.authentication import (
    MINIMAX_OAUTH_CN_INFERENCE as MINIMAX_OAUTH_CN_INFERENCE,
)
from superforecasting_agent.configuration.authentication import (
    MINIMAX_OAUTH_GLOBAL_BASE as MINIMAX_OAUTH_GLOBAL_BASE,
)
from superforecasting_agent.configuration.authentication import (
    MINIMAX_OAUTH_GLOBAL_INFERENCE as MINIMAX_OAUTH_GLOBAL_INFERENCE,
)
from superforecasting_agent.configuration.authentication import (
    MINIMAX_OAUTH_SCOPE as MINIMAX_OAUTH_SCOPE,
)
from superforecasting_agent.configuration.authentication import (
    NOUS_INFERENCE_INVOKE_SCOPE as NOUS_INFERENCE_INVOKE_SCOPE,
)
from superforecasting_agent.configuration.authentication import (
    NOUS_LEGACY_AGENT_KEY_SCOPE as NOUS_LEGACY_AGENT_KEY_SCOPE,
)
from superforecasting_agent.configuration.authentication import (
    PROVIDER_REGISTRY as PROVIDER_REGISTRY,
)
from superforecasting_agent.configuration.authentication import (
    STEPFUN_STEP_PLAN_INTL_BASE_URL as STEPFUN_STEP_PLAN_INTL_BASE_URL,
)
from superforecasting_agent.configuration.authentication import (
    ProviderConfig as ProviderConfig,
)
from superforecasting_agent.configuration.authentication import (
    _resolve_kimi_base_url as _resolve_kimi_base_url,
)
from superforecasting_agent.configuration.authentication import (
    has_usable_secret as has_usable_secret,
)
from superforecasting_agent.configuration.nous_env import (
    nous_inference_base_url as nous_inference_base_url,
)
from superforecasting_agent.configuration.nous_env import (
    nous_portal_base_url as nous_portal_base_url,
)
from superforecasting_agent.constants import (
    get_agent_home as get_agent_home,
)
from superforecasting_agent.environment import (
    env_var_alias_enabled as env_var_alias_enabled,
)
from superforecasting_agent.environment import (
    is_truthy_value as is_truthy_value,
)
from superforecasting_agent.storage.auth import (
    AUTH_STORE_VERSION as AUTH_STORE_VERSION,
)
from superforecasting_agent.storage.credential_policy import (
    sanitize_borrowed_credential_payload as sanitize_borrowed_credential_payload,
)
from superforecasting_agent.storage.files import (
    atomic_replace as atomic_replace,
)
from superforecasting_agent.storage.files import (
    owned_text_descriptor as owned_text_descriptor,
)

_PRIMARY_CLI = "superforecasting-agent"


logger = logging.getLogger(__name__)

fcntl: ModuleType | None
try:
    fcntl = import_module("fcntl")
except Exception:
    fcntl = None
msvcrt: ModuleType | None
try:
    msvcrt = import_module("msvcrt")
except Exception:
    msvcrt = None

# =============================================================================
# Constants
# =============================================================================

AUTH_LOCK_TIMEOUT_SECONDS = 15.0

# Nous Portal defaults
NOUS_LEGACY_SESSION_KEYS_ENV = "HERMES_AGENT_USE_LEGACY_SESSION_KEYS"
NOUS_DEVICE_CODE_SOURCE = "device_code"
NOUS_INFERENCE_AUTH_MODE_AUTO = "auto"
NOUS_INFERENCE_AUTH_MODE_FRESH = "fresh"
NOUS_INFERENCE_AUTH_MODE_LEGACY = "legacy"
NOUS_INFERENCE_AUTH_MODES = frozenset({
    NOUS_INFERENCE_AUTH_MODE_AUTO,
    NOUS_INFERENCE_AUTH_MODE_FRESH,
    NOUS_INFERENCE_AUTH_MODE_LEGACY,
})
NOUS_AUTH_PATH_INVOKE_JWT = "invoke_jwt"
NOUS_AUTH_PATH_LEGACY_SESSION_KEY_CACHE = "legacy_session_key_cache"
NOUS_AUTH_PATH_LEGACY_SESSION_KEY_MINT = "legacy_session_key_mint"
DEFAULT_AGENT_KEY_MIN_TTL_SECONDS = 30 * 60  # 30 minutes
ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120  # refresh 2 min before expiry
NOUS_INVOKE_JWT_MIN_TTL_SECONDS = ACCESS_TOKEN_REFRESH_SKEW_SECONDS
DEVICE_AUTH_POLL_INTERVAL_CAP_SECONDS = 1  # poll at most every 1s
MINIMAX_OAUTH_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:user_code"
MINIMAX_OAUTH_REFRESH_SKEW_SECONDS = 60
_QWEN_BASE_URL_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_QWEN_BASE_URL",
    "FORECAST_QWEN_BASE_URL",
    "HERMES_QWEN_BASE_URL",
)
STEPFUN_STEP_PLAN_CN_BASE_URL = "https://api.stepfun.com/step_plan/v1"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120
XAI_OAUTH_ISSUER = "https://auth.x.ai"
XAI_OAUTH_DISCOVERY_URL = f"{XAI_OAUTH_ISSUER}/.well-known/openid-configuration"
XAI_OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_OAUTH_SCOPE = "openid profile email offline_access grok-cli:access api:access"
XAI_OAUTH_REDIRECT_HOST = "127.0.0.1"
XAI_OAUTH_REDIRECT_PORT = 56121
XAI_OAUTH_REDIRECT_PATH = "/callback"
XAI_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120
QWEN_OAUTH_CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"
QWEN_OAUTH_TOKEN_URL = "https://chat.qwen.ai/api/v1/oauth2/token"
QWEN_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120
XAI_OAUTH_DOCS_URL = "website/docs/guides/xai-grok-oauth.md"
OAUTH_OVER_SSH_DOCS_URL = "website/docs/guides/oauth-over-ssh.md"
SERVICE_PROVIDER_NAMES: Dict[str, str] = {}

# Google Gemini OAuth (google-gemini-cli provider, Cloud Code Assist backend)
GEMINI_OAUTH_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 60  # refresh 60s before expiry

# LM Studio's default no-auth mode still requires *some* non-empty bearer for
# the API-key code paths (auxiliary_client, runtime resolver) to treat the
# provider as configured. This sentinel is sent only to LM Studio, never to
# any remote service.
LMSTUDIO_NOAUTH_PLACEHOLDER = "dummy-lm-api-key"


# =============================================================================
# Anthropic Key Helper
# =============================================================================


# =============================================================================
# Z.AI Endpoint Detection
# =============================================================================

# Z.AI has separate billing for general vs coding plans, and global vs China
# endpoints.  A key that works on one may return "Insufficient balance" on
# another.  We probe at setup time and store the working endpoint.
# Each entry lists candidate models to try in order — newer coding plan accounts
# may only have access to recent models (glm-5.1, glm-5v-turbo) while older
# ones still use glm-4.7.

ZAI_ENDPOINTS = [
    # (id, base_url, probe_models, label)
    ("global", "https://api.z.ai/api/paas/v4", ["glm-5"], "Global"),
    ("cn", "https://open.bigmodel.cn/api/paas/v4", ["glm-5"], "China"),
    (
        "coding-global",
        "https://api.z.ai/api/coding/paas/v4",
        ["glm-5.1", "glm-5v-turbo", "glm-4.7"],
        "Global (Coding Plan)",
    ),
    (
        "coding-cn",
        "https://open.bigmodel.cn/api/coding/paas/v4",
        ["glm-5.1", "glm-5v-turbo", "glm-4.7"],
        "China (Coding Plan)",
    ),
]


# =============================================================================
# Error Types
# =============================================================================

# Error code marking upstream rate-limit / usage-quota exhaustion (HTTP 429).
# Such failures are transient and re-authenticating cannot resolve them, so
# they must be kept distinct from missing/expired-credential errors.
CODEX_RATE_LIMITED_CODE = "codex_rate_limited"


class AuthError(RuntimeError):
    """Structured auth error with UX mapping hints."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        code: Optional[str] = None,
        relogin_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.relogin_required = relogin_required


# =============================================================================
# Auth Store — persistence layer for ~/.hermes/auth.json
# =============================================================================


_auth_lock_holder = threading.local()


# =============================================================================
# Provider Resolution — picks which provider to use
# =============================================================================


# =============================================================================
# Timestamp / TTL helpers
# =============================================================================


_NOUS_EFFECTIVE_STATE_IGNORED_KEYS = frozenset({
    # These are derived from expires_at/JWT exp and naturally tick down between
    # reads. Persisting only these changes makes auth.json noisy and defeats
    # the mtime-keyed auth-status cache.
    "expires_in",
    "agent_key_expires_in",
})


# =============================================================================
# Google Gemini OAuth (google-gemini-cli) — PKCE flow + Cloud Code Assist.
#
# Tokens live in ~/.hermes/auth/google_oauth.json (managed by agent.google_oauth).
# The `base_url` here is the marker "cloudcode-pa://google" that run_agent.py
# uses to construct a GeminiCloudCodeClient instead of the default OpenAI SDK.
# Actual HTTP traffic goes to https://cloudcode-pa.googleapis.com/v1internal:*.
# =============================================================================


# =============================================================================
# SSH / remote session detection
# =============================================================================


# =============================================================================
# OpenAI Codex auth — tokens stored in ~/.hermes/auth.json (not ~/.codex/)
#
# Hermes maintains its own Codex OAuth session separate from the Codex CLI
# and VS Code extension. This prevents refresh token rotation conflicts
# where one app's refresh invalidates the other's session.
# =============================================================================


# =============================================================================
# xAI Grok OAuth — tokens stored in ~/.hermes/auth.json
# =============================================================================


# =============================================================================
# TLS verification helper
# =============================================================================


# =============================================================================
# OAuth Device Code Flow — generic, parameterized by provider
# =============================================================================


# =============================================================================
# Nous Portal — token refresh, agent key minting, model discovery
# =============================================================================

# -----------------------------------------------------------------------------
# Shared Nous token store — lets OAuth credentials persist across profiles
# so a new `hermes --profile <name> auth add nous --type oauth` can one-tap
# import instead of running the full device-code flow every time.
#
# File lives at ${HERMES_SHARED_AUTH_DIR}/nous_auth.json, defaulting to
# ``<hermes-root>/shared/nous_auth.json`` where ``<hermes-root>`` is what
# ``get_default_agent_root()`` returns — ``~/.hermes`` on Linux/macOS,
# ``%LOCALAPPDATA%\hermes`` on native Windows, or the Docker/custom root.
# It is OUTSIDE any named profile's HERMES_HOME so named profiles (which
# typically live under ``<hermes-root>/profiles/<name>/``) all see the
# same file.
#
# Written on successful login and on every runtime refresh so the stored
# refresh_token stays current even if one profile refreshes and rotates it.
# If ever the stored refresh_token does go stale server-side, import fails
# gracefully and the user falls back to the normal device-code flow.
# -----------------------------------------------------------------------------

NOUS_SHARED_STORE_FILENAME = "nous_auth.json"
_nous_shared_lock_holder = threading.local()


# =============================================================================
# Status helpers
# =============================================================================


# ── Process-level memo for get_nous_auth_status() ──
# get_nous_auth_status() validates state by calling resolve_nous_runtime_credentials(),
# which does a synchronous OAuth refresh POST to portal.nousresearch.com. That can take
# ~350ms even on the failure path, and read-only UI surfaces
# (`superforecasting-agent tools`, status panels, subscription-feature checks)
# call it many times per render — `superforecasting-agent tools` → "All Platforms"
# was firing the refresh ~31× during one menu paint, racking up >13s of HTTP and burning
# single-use refresh tokens. Cache the snapshot for a few seconds, keyed on the auth.json
# path and mtime so that profiles cannot share a status snapshot and
# `superforecasting-agent auth login/logout/add/remove`
# invalidate naturally on the next call.
_NOUS_AUTH_STATUS_CACHE_TTL = 15.0  # seconds
_nous_auth_status_cache: Optional[
    Tuple[float, Tuple[str, Optional[float]], Dict[str, Any]]
] = None


_COPILOT_ACP_COMMAND_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_COPILOT_ACP_COMMAND",
    "FORECAST_COPILOT_ACP_COMMAND",
    "HERMES_COPILOT_ACP_COMMAND",
    "COPILOT_CLI_PATH",
)
_COPILOT_ACP_ARGS_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_COPILOT_ACP_ARGS",
    "FORECAST_COPILOT_ACP_ARGS",
    "HERMES_COPILOT_ACP_ARGS",
)


# =============================================================================
# CLI Commands — login / logout
# =============================================================================


# ==================== MiniMax Portal OAuth ====================

# Provider leaves load after shared constants/state: their default arguments
# reference this facade during import. Public exports retain one patchable owner.
# isort: off
from superforecasting_agent.credentials.oauth.api_keys import (
    _resolve_api_key_provider_secret as _resolve_api_key_provider_secret,
    _resolve_zai_base_url as _resolve_zai_base_url,
    detect_zai_endpoint as detect_zai_endpoint,
    get_anthropic_key as get_anthropic_key,
    resolve_api_key_provider_credentials as resolve_api_key_provider_credentials,
    resolve_external_process_provider_credentials as resolve_external_process_provider_credentials,
)
from superforecasting_agent.credentials.oauth.callbacks import (
    _is_remote_session as _is_remote_session,
    _make_xai_callback_handler as _make_xai_callback_handler,
    _parse_pasted_callback as _parse_pasted_callback,
    _ssh_user_at_host as _ssh_user_at_host,
    _xai_callback_cors_origin as _xai_callback_cors_origin,
    _xai_start_callback_server as _xai_start_callback_server,
    _xai_validate_loopback_redirect_uri as _xai_validate_loopback_redirect_uri,
    _xai_wait_for_callback as _xai_wait_for_callback,
)
from superforecasting_agent.credentials.oauth.codex import (
    _codex_access_token_is_expiring as _codex_access_token_is_expiring,
    _import_codex_cli_tokens as _import_codex_cli_tokens,
    _is_terminal_codex_oauth_refresh_error as _is_terminal_codex_oauth_refresh_error,
    _read_codex_tokens as _read_codex_tokens,
    _refresh_codex_auth_tokens as _refresh_codex_auth_tokens,
    _save_codex_tokens as _save_codex_tokens,
    _sync_codex_pool_entries as _sync_codex_pool_entries,
    refresh_codex_oauth_pure as refresh_codex_oauth_pure,
    resolve_codex_runtime_credentials as resolve_codex_runtime_credentials,
)
from superforecasting_agent.credentials.oauth.common import (
    _auth_command_hint as _auth_command_hint,
    _coerce_ttl_seconds as _coerce_ttl_seconds,
    _decode_jwt_claims as _decode_jwt_claims,
    _default_verify as _default_verify,
    _is_expiring as _is_expiring,
    _oauth_pkce_code_challenge as _oauth_pkce_code_challenge,
    _oauth_pkce_code_verifier as _oauth_pkce_code_verifier,
    _oauth_trace as _oauth_trace,
    _oauth_trace_enabled as _oauth_trace_enabled,
    _optional_base_url as _optional_base_url,
    _parse_iso_timestamp as _parse_iso_timestamp,
    _parse_retry_after_seconds as _parse_retry_after_seconds,
    _resolve_verify as _resolve_verify,
    _scope_values as _scope_values,
    _token_fingerprint as _token_fingerprint,
    format_auth_error as format_auth_error,
    is_rate_limited_auth_error as is_rate_limited_auth_error,
)
from superforecasting_agent.credentials.oauth.device_flow import (
    _is_nous_invoke_scope_refusal as _is_nous_invoke_scope_refusal,
    _nous_device_scope_with_env_override as _nous_device_scope_with_env_override,
    _poll_for_token as _poll_for_token,
    _request_device_code as _request_device_code,
    _request_nous_device_code_with_scope_fallback as _request_nous_device_code_with_scope_fallback,
)
from superforecasting_agent.credentials.oauth.external_oauth import (
    _qwen_access_token_is_expiring as _qwen_access_token_is_expiring,
    _qwen_cli_auth_path as _qwen_cli_auth_path,
    _read_qwen_cli_tokens as _read_qwen_cli_tokens,
    _refresh_qwen_cli_tokens as _refresh_qwen_cli_tokens,
    _save_qwen_cli_tokens as _save_qwen_cli_tokens,
    resolve_gemini_oauth_runtime_credentials as resolve_gemini_oauth_runtime_credentials,
    resolve_qwen_runtime_credentials as resolve_qwen_runtime_credentials,
)
from superforecasting_agent.credentials.oauth.minimax import (
    _minimax_expired_in_looks_like_unix_ms as _minimax_expired_in_looks_like_unix_ms,
    _minimax_pkce_pair as _minimax_pkce_pair,
    _minimax_poll_token as _minimax_poll_token,
    _minimax_request_user_code as _minimax_request_user_code,
    _minimax_resolve_token_expiry_unix as _minimax_resolve_token_expiry_unix,
    _minimax_save_auth_state as _minimax_save_auth_state,
    _refresh_minimax_oauth_state as _refresh_minimax_oauth_state,
    resolve_minimax_oauth_runtime_credentials as resolve_minimax_oauth_runtime_credentials,
)
from superforecasting_agent.credentials.oauth.nous_policy import (
    _choose_nous_inference_auth_path as _choose_nous_inference_auth_path,
    _log_nous_invoke_jwt_selected as _log_nous_invoke_jwt_selected,
    _log_nous_legacy_session_key_selected as _log_nous_legacy_session_key_selected,
    _normalize_nous_inference_auth_mode as _normalize_nous_inference_auth_mode,
    _nous_effective_provider_state as _nous_effective_provider_state,
    _nous_invoke_jwt_is_usable as _nous_invoke_jwt_is_usable,
    _nous_invoke_jwt_status as _nous_invoke_jwt_status,
    _nous_jwt_expires_at as _nous_jwt_expires_at,
    _nous_legacy_session_key_reason as _nous_legacy_session_key_reason,
    _nous_legacy_session_keys_forced as _nous_legacy_session_keys_forced,
    _nous_scope_has_invoke as _nous_scope_has_invoke,
    _select_nous_invoke_jwt as _select_nous_invoke_jwt,
    _set_nous_agent_key_from_invoke_jwt as _set_nous_agent_key_from_invoke_jwt,
)
from superforecasting_agent.credentials.oauth.nous_refresh import (
    _agent_key_is_usable as _agent_key_is_usable,
    _mint_agent_key as _mint_agent_key,
    _refresh_access_token as _refresh_access_token,
    _sync_nous_pool_from_auth_store as _sync_nous_pool_from_auth_store,
    fetch_nous_models as fetch_nous_models,
    persist_nous_credentials as persist_nous_credentials,
    refresh_nous_oauth_from_state as refresh_nous_oauth_from_state,
    refresh_nous_oauth_pure as refresh_nous_oauth_pure,
    resolve_nous_access_token as resolve_nous_access_token,
)
from superforecasting_agent.credentials.oauth.nous_runtime import (
    resolve_nous_runtime_credentials as resolve_nous_runtime_credentials,
)
from superforecasting_agent.credentials.oauth.nous_storage import (
    _clear_shared_nous_state as _clear_shared_nous_state,
    _is_terminal_nous_refresh_error as _is_terminal_nous_refresh_error,
    _merge_shared_nous_oauth_state as _merge_shared_nous_oauth_state,
    _nous_shared_auth_dir as _nous_shared_auth_dir,
    _nous_shared_store_lock as _nous_shared_store_lock,
    _nous_shared_store_path as _nous_shared_store_path,
    _quarantine_nous_oauth_state as _quarantine_nous_oauth_state,
    _quarantine_nous_pool_entries as _quarantine_nous_pool_entries,
    _read_shared_nous_state as _read_shared_nous_state,
    _try_import_shared_nous_state as _try_import_shared_nous_state,
    _write_shared_nous_state as _write_shared_nous_state,
)
from superforecasting_agent.credentials.oauth.routing import (
    _get_config_hint_for_unknown_provider as _get_config_hint_for_unknown_provider,
    resolve_provider as resolve_provider,
)
from superforecasting_agent.credentials.oauth.status import (
    _auth_file_mtime as _auth_file_mtime,
    _compute_nous_auth_status as _compute_nous_auth_status,
    _empty_nous_auth_status as _empty_nous_auth_status,
    _get_azure_foundry_auth_status as _get_azure_foundry_auth_status,
    _resolve_copilot_acp_args_raw as _resolve_copilot_acp_args_raw,
    _resolve_copilot_acp_command as _resolve_copilot_acp_command,
    _snapshot_nous_pool_status as _snapshot_nous_pool_status,
    get_api_key_provider_status as get_api_key_provider_status,
    get_auth_status as get_auth_status,
    get_codex_auth_status as get_codex_auth_status,
    get_external_process_provider_status as get_external_process_provider_status,
    get_gemini_oauth_auth_status as get_gemini_oauth_auth_status,
    get_minimax_oauth_auth_status as get_minimax_oauth_auth_status,
    get_nous_auth_status as get_nous_auth_status,
    get_qwen_auth_status as get_qwen_auth_status,
    get_xai_oauth_auth_status as get_xai_oauth_auth_status,
    invalidate_nous_auth_status_cache as invalidate_nous_auth_status_cache,
)
from superforecasting_agent.credentials.oauth.store import (
    _auth_file_path as _auth_file_path,
    _auth_lock_path as _auth_lock_path,
    _auth_store_lock as _auth_store_lock,
    _file_lock as _file_lock,
    _global_auth_file_path as _global_auth_file_path,
    _load_auth_store as _load_auth_store,
    _load_global_auth_store as _load_global_auth_store,
    _load_provider_state as _load_provider_state,
    _save_auth_store as _save_auth_store,
    _save_provider_state as _save_provider_state,
    _store_provider_state as _store_provider_state,
    clear_provider_auth as clear_provider_auth,
    deactivate_provider as deactivate_provider,
    get_active_provider as get_active_provider,
    get_auth_provider_display_name as get_auth_provider_display_name,
    get_provider_auth_state as get_provider_auth_state,
    is_known_auth_provider as is_known_auth_provider,
    is_provider_explicitly_configured as is_provider_explicitly_configured,
    is_source_suppressed as is_source_suppressed,
    mark_provider_active_if_unset as mark_provider_active_if_unset,
    read_credential_pool as read_credential_pool,
    suppress_credential_source as suppress_credential_source,
    unsuppress_credential_source as unsuppress_credential_source,
    write_credential_pool as write_credential_pool,
)
from superforecasting_agent.credentials.oauth.xai import (
    _is_terminal_xai_oauth_refresh_error as _is_terminal_xai_oauth_refresh_error,
    _read_xai_oauth_tokens as _read_xai_oauth_tokens,
    _refresh_xai_oauth_tokens as _refresh_xai_oauth_tokens,
    _save_xai_oauth_tokens as _save_xai_oauth_tokens,
    _xai_access_token_is_expiring as _xai_access_token_is_expiring,
    _xai_oauth_build_authorize_url as _xai_oauth_build_authorize_url,
    _xai_oauth_discovery as _xai_oauth_discovery,
    _xai_oauth_exchange_code_for_tokens as _xai_oauth_exchange_code_for_tokens,
    _xai_validate_inference_base_url as _xai_validate_inference_base_url,
    _xai_validate_oauth_endpoint as _xai_validate_oauth_endpoint,
    refresh_xai_oauth_pure as refresh_xai_oauth_pure,
    resolve_xai_oauth_runtime_credentials as resolve_xai_oauth_runtime_credentials,
)
