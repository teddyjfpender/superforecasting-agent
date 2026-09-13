"""Provider entry normalization and structural diagnostics on supplied configuration."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_PRIMARY_CLI = "superforecasting-agent"


def _normalize_custom_provider_entry(
    entry: Any,
    *,
    provider_key: str = "",
) -> Optional[Dict[str, Any]]:
    """Return a runtime-compatible custom provider entry or ``None``."""
    if not isinstance(entry, dict):
        return None

    # Accept camelCase aliases commonly used in hand-written configs.
    _CAMEL_ALIASES: Dict[str, str] = {
        "apiKey": "api_key",
        "baseUrl": "base_url",
        "apiMode": "api_mode",
        "keyEnv": "key_env",
        "apiKeyEnv": "key_env",  # alias — OpenClaw-compatible + docs variant
        "defaultModel": "default_model",
        "contextLength": "context_length",
        "rateLimitDelay": "rate_limit_delay",
    }
    # api_key_env is a documented snake_case alias for key_env (see
    # website/docs/guides/azure-foundry.md).  Normalize it up front so the
    # rest of the normalizer treats it as the canonical field.
    if "api_key_env" in entry and "key_env" not in entry:
        entry["key_env"] = entry["api_key_env"]
    _KNOWN_KEYS = {
        "name",
        "api",
        "url",
        "base_url",
        "api_key",
        "key_env",
        "api_key_env",
        "api_mode",
        "transport",
        "model",
        "default_model",
        "models",
        "context_length",
        "rate_limit_delay",
        "request_timeout_seconds",
        "stale_timeout_seconds",
        "discover_models",
    }
    for camel, snake in _CAMEL_ALIASES.items():
        if camel in entry and snake not in entry:
            logger.warning(
                "providers.%s: camelCase key '%s' auto-mapped to '%s' "
                "(use snake_case to avoid this warning)",
                provider_key or "?",
                camel,
                snake,
            )
            entry[snake] = entry[camel]
    unknown = set(entry.keys()) - _KNOWN_KEYS - set(_CAMEL_ALIASES.keys())
    if unknown:
        logger.warning(
            "providers.%s: unknown config keys ignored: %s",
            provider_key or "?",
            ", ".join(sorted(unknown)),
        )

    from urllib.parse import urlparse

    base_url = ""
    for url_key in ("base_url", "url", "api"):
        raw_url = entry.get(url_key)
        if isinstance(raw_url, str) and raw_url.strip():
            candidate = raw_url.strip()
            parsed = urlparse(candidate)
            if parsed.scheme and parsed.netloc:
                base_url = candidate
                break
            else:
                logger.warning(
                    "providers.%s: '%s' value '%s' is not a valid URL "
                    "(no scheme or host) — skipped",
                    provider_key or "?",
                    url_key,
                    candidate,
                )
    if not base_url:
        return None

    name = ""
    raw_name = entry.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        name = raw_name.strip()
    elif provider_key.strip():
        name = provider_key.strip()
    if not name:
        return None

    normalized: Dict[str, Any] = {
        "name": name,
        "base_url": base_url,
    }

    provider_key = provider_key.strip()
    if provider_key:
        normalized["provider_key"] = provider_key

    api_key = entry.get("api_key")
    if isinstance(api_key, str) and api_key.strip():
        normalized["api_key"] = api_key.strip()

    key_env = entry.get("key_env")
    if isinstance(key_env, str) and key_env.strip():
        normalized["key_env"] = key_env.strip()

    api_mode = entry.get("api_mode") or entry.get("transport")
    if isinstance(api_mode, str) and api_mode.strip():
        normalized["api_mode"] = api_mode.strip()

    model_name = entry.get("model") or entry.get("default_model")
    if isinstance(model_name, str) and model_name.strip():
        normalized["model"] = model_name.strip()

    models = entry.get("models")
    if isinstance(models, dict) and models:
        normalized["models"] = models
    elif isinstance(models, list) and models:
        # Hand-edited configs (and older Hermes versions) write ``models`` as
        # a plain list of model ids. Preserve them by converting to the dict
        # shape downstream code expects; otherwise normalize silently drops
        # the list and /model shows the provider with (0) models.
        normalized["models"] = {
            str(m): {} for m in models if isinstance(m, str) and m.strip()
        }

    context_length = entry.get("context_length")
    if isinstance(context_length, int) and context_length > 0:
        normalized["context_length"] = context_length

    rate_limit_delay = entry.get("rate_limit_delay")
    if isinstance(rate_limit_delay, (int, float)) and rate_limit_delay >= 0:
        normalized["rate_limit_delay"] = rate_limit_delay

    discover_models = entry.get("discover_models")
    if isinstance(discover_models, bool):
        normalized["discover_models"] = discover_models

    return normalized


def providers_dict_to_custom_providers(providers_dict: Any) -> List[Dict[str, Any]]:
    """Normalize ``providers`` config entries into the legacy custom-provider shape."""
    if not isinstance(providers_dict, dict):
        return []

    custom_providers: List[Dict[str, Any]] = []
    for key, entry in providers_dict.items():
        normalized = _normalize_custom_provider_entry(entry, provider_key=str(key))
        if normalized is not None:
            custom_providers.append(normalized)

    return custom_providers


def get_compatible_custom_providers(
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return a deduplicated custom-provider view across legacy and v12+ config.

    ``custom_providers`` remains the on-disk legacy format, while ``providers``
    is the newer keyed schema.  Runtime and picker flows still need a single
    list-shaped view, but we should not materialise that compatibility layer
    back into config.yaml because it duplicates entries in UIs.
    """
    compatible: List[Dict[str, Any]] = []
    seen_provider_keys: set = set()
    seen_name_url_pairs: set = set()

    def _append_if_new(entry: Optional[Dict[str, Any]]) -> None:
        if entry is None:
            return
        provider_key = str(entry.get("provider_key", "") or "").strip().lower()
        name = str(entry.get("name", "") or "").strip().lower()
        base_url = str(entry.get("base_url", "") or "").strip().rstrip("/").lower()
        model = str(entry.get("model", "") or "").strip().lower()
        pair = (name, base_url, model)

        if provider_key and provider_key in seen_provider_keys:
            return
        if name and base_url and pair in seen_name_url_pairs:
            return

        compatible.append(entry)
        if provider_key:
            seen_provider_keys.add(provider_key)
        if name and base_url:
            seen_name_url_pairs.add(pair)

    custom_providers = config.get("custom_providers")
    if custom_providers is not None:
        if not isinstance(custom_providers, list):
            return []
        for entry in custom_providers:
            _append_if_new(_normalize_custom_provider_entry(entry))

    for entry in providers_dict_to_custom_providers(config.get("providers")):
        _append_if_new(entry)

    return compatible


_KNOWN_ROOT_KEYS = {
    "_config_version",
    "model",
    "providers",
    "fallback_model",
    "fallback_providers",
    "credential_pool_strategies",
    "toolsets",
    "agent",
    "terminal",
    "display",
    "compression",
    "delegation",
    "auxiliary",
    "custom_providers",
    "context",
    "memory",
    "gateway",
    "sessions",
}


_VALID_CUSTOM_PROVIDER_FIELDS = {
    "name",
    "base_url",
    "api_key",
    "api_mode",
    "model",
    "models",
    "context_length",
    "rate_limit_delay",
    # key_env is read at runtime by runtime_provider.py and auxiliary_client.py
    # — include it here so the set accurately describes the supported schema.
    "key_env",
}


_CUSTOM_PROVIDER_LIKE_FIELDS = {"base_url", "api_key", "rate_limit_delay", "api_mode"}


@dataclass
class ConfigIssue:
    """A detected config structure problem."""

    severity: str  # "error", "warning"
    message: str
    hint: str


def validate_config_structure(config: Dict[str, Any]) -> List["ConfigIssue"]:
    """Validate config.yaml structure and return a list of detected issues.

    Catches common YAML formatting mistakes that produce confusing runtime
    errors (like "Unknown provider") instead of clear diagnostics.

    Can be called with a pre-loaded config dict, or will load from disk.
    """
    issues: List[ConfigIssue] = []

    # ── multiplayer ledger collaboration ────────────────────────────────
    collaboration = config.get("collaboration")
    if collaboration is not None and not isinstance(collaboration, dict):
        issues.append(
            ConfigIssue(
                "error",
                "collaboration must be a YAML mapping",
                "Use collaboration: {enabled: false, github: ..., repository: ...}",
            )
        )
    elif isinstance(collaboration, dict):
        from urllib.parse import urlparse

        github = collaboration.get("github") or {}
        repository = collaboration.get("repository") or {}
        review = collaboration.get("review") or {}
        discussion = collaboration.get("discussion") or {}
        transcripts = collaboration.get("transcripts") or {}
        for section_name, section in (
            ("github", github),
            ("repository", repository),
            ("review", review),
            ("discussion", discussion),
            ("transcripts", transcripts),
        ):
            if not isinstance(section, dict):
                issues.append(
                    ConfigIssue(
                        "error",
                        f"collaboration.{section_name} must be a YAML mapping",
                        f"Replace collaboration.{section_name} with a mapping of named settings",
                    )
                )
        if isinstance(github, dict):
            for key in ("api_url", "upload_url"):
                value = str(github.get(key) or "")
                parsed = urlparse(value)
                if parsed.scheme != "https" or not parsed.hostname:
                    issues.append(
                        ConfigIssue(
                            "error",
                            f"collaboration.github.{key} must be an absolute HTTPS URL",
                            f"Set collaboration.github.{key} to an https:// endpoint",
                        )
                    )
            public_base = str(github.get("public_base_url") or "")
            if public_base:
                parsed = urlparse(public_base)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or parsed.query
                    or parsed.fragment
                ):
                    issues.append(
                        ConfigIssue(
                            "error",
                            "collaboration.github.public_base_url must be an absolute HTTPS URL",
                            "Example: https://forecast.example.com",
                        )
                    )
            for key in ("oauth_state_ttl_seconds", "installation_state_ttl_seconds"):
                ttl = github.get(key, 600)
                if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 60:
                    issues.append(
                        ConfigIssue(
                            "error",
                            f"collaboration.github.{key} must be at least 60",
                            "Use 600 for the default ten-minute authorization window",
                        )
                    )
            app_slug = str(github.get("app_slug") or "")
            if app_slug and not re.fullmatch(r"[A-Za-z0-9-]+", app_slug):
                issues.append(
                    ConfigIssue(
                        "error",
                        "collaboration.github.app_slug is invalid",
                        "Use the slug from https://github.com/apps/<app-slug>",
                    )
                )
            for key in (
                "oauth_callback_path",
                "installation_begin_path",
                "installation_callback_path",
                "webhook_path",
            ):
                path = str(github.get(key) or "")
                if not path.startswith("/") or ".." in path or "\\" in path:
                    issues.append(
                        ConfigIssue(
                            "error",
                            f"collaboration.github.{key} must be a safe absolute path",
                            "Use a fixed absolute /api/... path without traversal",
                        )
                    )
        if isinstance(repository, dict):
            slug = str(repository.get("slug") or "").strip()
            if slug and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", slug):
                issues.append(
                    ConfigIssue(
                        "error",
                        "collaboration.repository.slug must use owner/repository form",
                        "Example: forecasting-team/forecast-ledger",
                    )
                )
            branch = str(repository.get("default_branch") or "").strip()
            if (
                not branch
                or branch.startswith(("-", "."))
                or any(marker in branch for marker in ("..", "~", "^", ":", "\\", " "))
            ):
                issues.append(
                    ConfigIssue(
                        "error",
                        "collaboration.repository.default_branch is not a safe Git ref",
                        "Use a simple branch name such as main",
                    )
                )
        if isinstance(review, dict):
            threshold = review.get("materiality_threshold", 0.10)
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, (int, float))
                or not 0 <= float(threshold) <= 1
            ):
                issues.append(
                    ConfigIssue(
                        "error",
                        "collaboration.review.materiality_threshold must be between 0 and 1",
                        "Use 0.10 for the default ten-percentage-point boundary",
                    )
                )
            for key in ("medium_required_humans", "high_required_humans"):
                value = review.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    issues.append(
                        ConfigIssue(
                            "error",
                            f"collaboration.review.{key} must be a non-negative integer",
                            "Use 1 for medium risk and 2 for high risk",
                        )
                    )
            overrides = review.get("risk_overrides") or {}
            if not isinstance(overrides, dict):
                issues.append(
                    ConfigIssue(
                        "error",
                        "collaboration.review.risk_overrides must be a mapping",
                        "Map operation kinds to low, medium, or high",
                    )
                )
            elif any(
                value not in {"low", "medium", "high"} for value in overrides.values()
            ):
                issues.append(
                    ConfigIssue(
                        "error",
                        "collaboration.review.risk_overrides contains an unknown risk tier",
                        "Risk override values must be low, medium, or high",
                    )
                )
        if isinstance(transcripts, dict):
            retention = transcripts.get("raw_retention_days", 90)
            if (
                isinstance(retention, bool)
                or not isinstance(retention, int)
                or retention < 0
            ):
                issues.append(
                    ConfigIssue(
                        "error",
                        "collaboration.transcripts.raw_retention_days must be non-negative",
                        "Use 90 for the default retention period",
                    )
                )
        if isinstance(discussion, dict):
            for key in (
                "max_comments",
                "max_rounds",
                "max_tokens",
                "max_elapsed_seconds",
                "max_concurrent_tasks",
                "agent_loop_threshold",
                "max_comment_bytes",
            ):
                value = discussion.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    issues.append(
                        ConfigIssue(
                            "error",
                            f"collaboration.discussion.{key} must be a positive integer",
                            "Use the documented default or another value greater than zero",
                        )
                    )

    # ── custom_providers must be a list, not a dict ──────────────────────
    cp = config.get("custom_providers")
    if cp is not None:
        if isinstance(cp, dict):
            issues.append(
                ConfigIssue(
                    "error",
                    "custom_providers is a dict — it must be a YAML list (items prefixed with '-')",
                    "Change to:\n"
                    "  custom_providers:\n"
                    "    - name: my-provider\n"
                    "      base_url: https://...\n"
                    "      api_key: ...",
                )
            )
            # Check if dict keys look like they should be list-entry fields
            cp_keys = set(cp.keys()) if isinstance(cp, dict) else set()
            suspicious = cp_keys & _CUSTOM_PROVIDER_LIKE_FIELDS
            if suspicious:
                issues.append(
                    ConfigIssue(
                        "warning",
                        f"Root-level keys {sorted(suspicious)} look like custom_providers entry fields",
                        "These should be indented under a '- name: ...' list entry, not at root level",
                    )
                )
        elif isinstance(cp, list):
            # Validate each entry in the list
            for i, entry in enumerate(cp):
                if not isinstance(entry, dict):
                    issues.append(
                        ConfigIssue(
                            "warning",
                            f"custom_providers[{i}] is not a dict (got {type(entry).__name__})",
                            "Each entry should have at minimum: name, base_url",
                        )
                    )
                    continue
                if not entry.get("name"):
                    issues.append(
                        ConfigIssue(
                            "warning",
                            f"custom_providers[{i}] is missing 'name' field",
                            "Add a name, e.g.: name: my-provider",
                        )
                    )
                if not entry.get("base_url"):
                    issues.append(
                        ConfigIssue(
                            "warning",
                            f"custom_providers[{i}] is missing 'base_url' field",
                            "Add the API endpoint URL, e.g.: base_url: https://api.example.com/v1",
                        )
                    )

    # ── fallback_model: single dict OR list of dicts (chain) ─────────────
    fb = config.get("fallback_model")
    if fb is not None:
        if isinstance(fb, list):
            # Chain fallback — validate each entry
            for i, entry in enumerate(fb):
                if not isinstance(entry, dict):
                    issues.append(
                        ConfigIssue(
                            "error",
                            f"fallback_model[{i}] should be a dict, got {type(entry).__name__}",
                            "Each entry needs provider + model",
                        )
                    )
                else:
                    if not entry.get("provider"):
                        issues.append(
                            ConfigIssue(
                                "warning",
                                f"fallback_model[{i}] is missing 'provider' field",
                                "Add: provider: openrouter (or another provider)",
                            )
                        )
                    if not entry.get("model"):
                        issues.append(
                            ConfigIssue(
                                "warning",
                                f"fallback_model[{i}] is missing 'model' field",
                                "Add: model: <model-name>",
                            )
                        )
        elif not isinstance(fb, dict):
            issues.append(
                ConfigIssue(
                    "error",
                    f"fallback_model should be a dict with 'provider' and 'model', got {type(fb).__name__}",
                    "Change to:\n"
                    "  fallback_model:\n"
                    "    provider: openrouter\n"
                    "    model: anthropic/claude-sonnet-4",
                )
            )
        elif fb:
            if not fb.get("provider"):
                issues.append(
                    ConfigIssue(
                        "warning",
                        "fallback_model is missing 'provider' field — fallback will be disabled",
                        "Add: provider: openrouter (or another provider)",
                    )
                )
            if not fb.get("model"):
                issues.append(
                    ConfigIssue(
                        "warning",
                        "fallback_model is missing 'model' field — fallback will be disabled",
                        "Add: model: anthropic/claude-sonnet-4 (or another model)",
                    )
                )

    # ── Check for fallback_model accidentally nested inside custom_providers ──
    if (
        isinstance(cp, dict)
        and "fallback_model" not in config
        and "fallback_model" in (cp or {})
    ):
        issues.append(
            ConfigIssue(
                "error",
                "fallback_model appears inside custom_providers instead of at root level",
                "Move fallback_model to the top level of config.yaml (no indentation)",
            )
        )

    # ── model section: should exist when custom_providers is configured ──
    model_cfg = config.get("model")
    if cp and not model_cfg:
        issues.append(
            ConfigIssue(
                "warning",
                "custom_providers defined but no 'model' section — Superforecasting Agent won't know which provider to use",
                "Add a model section:\n"
                "  model:\n"
                "    provider: custom\n"
                "    default: your-model-name\n"
                "    base_url: https://...",
            )
        )

    # ── Root-level keys that look misplaced ──────────────────────────────
    for key in config:
        if key.startswith("_"):
            continue
        if key not in _KNOWN_ROOT_KEYS and key in _CUSTOM_PROVIDER_LIKE_FIELDS:
            issues.append(
                ConfigIssue(
                    "warning",
                    f"Root-level key '{key}' looks misplaced — should it be under 'model:' or inside a 'custom_providers' entry?",
                    f"Move '{key}' under the appropriate section",
                )
            )

    return issues
