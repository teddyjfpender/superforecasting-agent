"""
Single source of truth for provider identity in Superforecasting Agent.

Three data sources, merged at runtime:

1. **models.dev catalog** — 109+ providers with base URLs, env vars, display
   names, and full model metadata (context, cost, capabilities).  This is
   the primary database.

2. **Superforecasting Agent overlays** — transport type, auth patterns, aggregator flags,
   and additional env vars that models.dev doesn't track.  Small dict,
   maintained in ``provider_catalog.py``.

3. **User config** (``providers:`` section in config.yaml) — user-defined
   endpoints and overrides.  Merged on top of everything else.

Other modules import from this file.  No parallel registries.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from superforecasting_agent.urls import base_url_host_matches, base_url_hostname

logger = logging.getLogger(__name__)


# -- Provider overlay ----------------------------------------------------------
# Runtime metadata that models.dev doesn't provide.

from superforecasting_agent.runtime.provider_catalog import (
    ProviderOverlay as ProviderOverlay,
    ProviderDef as ProviderDef,
    ALIASES as ALIASES,
    _LABEL_OVERRIDES as _LABEL_OVERRIDES,
    TRANSPORT_TO_API_MODE as TRANSPORT_TO_API_MODE,
    PROVIDER_OVERLAYS as PROVIDER_OVERLAYS,
)

# Compatibility imports for integrations using the inherited registry names.
HermesOverlay = ProviderOverlay
HERMES_OVERLAYS = PROVIDER_OVERLAYS


# -- Helper functions ---------------------------------------------------------

def normalize_provider(name: str) -> str:
    """Resolve aliases and normalise casing to a canonical provider id.

    Returns the canonical id string.  Does *not* validate that the id
    corresponds to a known provider.
    """
    key = name.strip().lower()
    return ALIASES.get(key, key)


def get_provider(name: str) -> Optional[ProviderDef]:
    """Look up a built-in provider by id or alias.

    Resolution order:
      1. runtime overlays (for providers not in models.dev: nous, openai-codex, etc.)
      2. models.dev catalog + runtime overlay

    User-defined providers from config.yaml (``providers:`` / ``custom_providers:``)
    are resolved by :func:`resolve_provider_full`, which layers ``resolve_user_provider``
    and ``resolve_custom_provider`` on top of this function. Callers that need
    user-config support should use ``resolve_provider_full`` instead.

    Returns a fully-resolved ProviderDef or None.
    """
    canonical = normalize_provider(name)

    # Try to get models.dev data
    try:
        from agent.models_dev import get_provider_info as _mdev_provider
        mdev_info = _mdev_provider(canonical)
    except Exception:
        mdev_info = None

    overlay = PROVIDER_OVERLAYS.get(canonical)

    if mdev_info is not None:
        # Merge models.dev + overlay
        transport = overlay.transport if overlay else "openai_chat"
        is_agg = overlay.is_aggregator if overlay else False
        auth = overlay.auth_type if overlay else "api_key"
        base_url_env = overlay.base_url_env_var if overlay else ""
        base_url_override = overlay.base_url_override if overlay else ""

        # Combine env vars: models.dev env + runtime extra
        env_vars = list(mdev_info.env)
        if overlay and overlay.extra_env_vars:
            for ev in overlay.extra_env_vars:
                if ev not in env_vars:
                    env_vars.append(ev)

        return ProviderDef(
            id=canonical,
            name=mdev_info.name,
            transport=transport,
            api_key_env_vars=tuple(env_vars),
            base_url=base_url_override or mdev_info.api,
            base_url_env_var=base_url_env,
            is_aggregator=is_agg,
            auth_type=auth,
            doc=mdev_info.doc,
            source="models.dev",
        )

    if overlay is not None:
        # Overlay-only provider (not in models.dev)
        return ProviderDef(
            id=canonical,
            name=_LABEL_OVERRIDES.get(canonical, canonical),
            transport=overlay.transport,
            api_key_env_vars=overlay.extra_env_vars,
            base_url=overlay.base_url_override,
            base_url_env_var=overlay.base_url_env_var,
            is_aggregator=overlay.is_aggregator,
            auth_type=overlay.auth_type,
            source="hermes",
        )

    return None


def get_label(provider_id: str) -> str:
    """Get a human-readable display name for a provider."""
    canonical = normalize_provider(provider_id)

    # Check label overrides first
    if canonical in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[canonical]

    # Try models.dev
    pdef = get_provider(canonical)
    if pdef:
        return pdef.name

    return canonical


def is_aggregator(provider: str) -> bool:
    """Return True when the provider is a multi-model aggregator."""
    pdef = get_provider(provider)
    return pdef.is_aggregator if pdef else False


def determine_api_mode(provider: str, base_url: str = "") -> str:
    """Determine the API mode (wire protocol) for a provider/endpoint.

    Resolution order:
      1. Known provider → transport → TRANSPORT_TO_API_MODE.
      2. URL heuristics for unknown / custom providers.
      3. Default: 'chat_completions'.
    """
    pdef = get_provider(provider)
    if pdef is not None:
        # Even for known providers, check URL heuristics for special endpoints
        # (e.g. kimi /coding endpoint needs anthropic_messages even on 'custom')
        if base_url:
            url_lower = base_url.rstrip("/").lower()
            if "api.kimi.com/coding" in url_lower:
                return "anthropic_messages"
            if url_lower.endswith("/anthropic") or "api.anthropic.com" in url_lower:
                return "anthropic_messages"
            if "api.openai.com" in url_lower:
                return "codex_responses"
        return TRANSPORT_TO_API_MODE.get(pdef.transport, "chat_completions")

    # Direct provider checks for providers not in PROVIDER_OVERLAYS
    if provider == "bedrock":
        return "bedrock_converse"

    # URL-based heuristics for custom / unknown providers
    if base_url:
        url_lower = base_url.rstrip("/").lower()
        hostname = base_url_hostname(base_url)
        if url_lower.endswith("/anthropic") or hostname == "api.anthropic.com":
            return "anthropic_messages"
        if hostname == "api.kimi.com" and "/coding" in url_lower:
            return "anthropic_messages"
        if hostname == "api.openai.com":
            return "codex_responses"
        if hostname.startswith("bedrock-runtime.") and base_url_host_matches(base_url, "amazonaws.com"):
            return "bedrock_converse"

    return "chat_completions"


# -- Provider from user config ------------------------------------------------

def resolve_user_provider(name: str, user_config: Dict[str, Any]) -> Optional[ProviderDef]:
    """Resolve a provider from the user's config.yaml ``providers:`` section.

    Args:
        name: Provider name as given by the user.
        user_config: The ``providers:`` dict from config.yaml.

    Returns:
        ProviderDef if found, else None.
    """
    if not user_config or not isinstance(user_config, dict):
        return None

    entry = user_config.get(name)
    if not isinstance(entry, dict):
        return None

    # Extract fields
    display_name = entry.get("name", "") or name
    api_url = entry.get("api", "") or entry.get("url", "") or entry.get("base_url", "") or ""
    key_env = entry.get("key_env", "") or ""
    transport = entry.get("transport", "openai_chat") or "openai_chat"

    env_vars: List[str] = []
    if key_env:
        env_vars.append(key_env)

    return ProviderDef(
        id=name,
        name=display_name,
        transport=transport,
        api_key_env_vars=tuple(env_vars),
        base_url=api_url,
        is_aggregator=False,
        auth_type="api_key",
        source="user-config",
    )


def custom_provider_slug(display_name: str) -> str:
    """Build a canonical slug for a custom_providers entry.

    Matches the convention used by runtime_provider and credential_pool
    (``custom:<normalized-name>``).  Centralised here so all call-sites
    produce identical slugs.
    """
    return "custom:" + display_name.strip().lower().replace(" ", "-")


def resolve_custom_provider(
    name: str,
    custom_providers: Optional[List[Dict[str, Any]]],
) -> Optional[ProviderDef]:
    """Resolve a provider from the user's config.yaml ``custom_providers`` list."""
    if not custom_providers or not isinstance(custom_providers, list):
        return None

    requested = (name or "").strip().lower()
    if not requested:
        return None

    # If the stored provider is the bare string "custom" (corrupt state
    # from a prior model-switch bug), fall back to the first custom
    # provider entry so existing configs self-heal.  (GH #17478)
    bare_custom_fallback = requested == "custom"
    first_valid = None

    for entry in custom_providers:
        if not isinstance(entry, dict):
            continue

        display_name = (entry.get("name") or "").strip()
        api_url = (
            entry.get("base_url", "")
            or entry.get("url", "")
            or entry.get("api", "")
            or ""
        ).strip()
        if not display_name or not api_url:
            continue

        # Stash the first valid entry for bare-"custom" fallback
        if first_valid is None:
            first_valid = (display_name, api_url)

        slug = custom_provider_slug(display_name)
        if requested not in {display_name.lower(), slug}:
            continue

        return ProviderDef(
            id=slug,
            name=display_name,
            transport="openai_chat",
            api_key_env_vars=(),
            base_url=api_url,
            is_aggregator=False,
            auth_type="api_key",
            source="user-config",
        )

    # Self-heal: bare "custom" matched nothing — return first valid entry
    if bare_custom_fallback and first_valid:
        dname, aurl = first_valid
        slug = custom_provider_slug(dname)
        return ProviderDef(
            id=slug,
            name=dname,
            transport="openai_chat",
            api_key_env_vars=(),
            base_url=aurl,
            is_aggregator=False,
            auth_type="api_key",
            source="user-config",
        )

    return None


def resolve_provider_full(
    name: str,
    user_providers: Optional[Dict[str, Any]] = None,
    custom_providers: Optional[List[Dict[str, Any]]] = None,
) -> Optional[ProviderDef]:
    """Full resolution chain: built-in → models.dev → user config.

    This is the main entry point for --provider flag resolution.

    Args:
        name: Provider name or alias.
        user_providers: The ``providers:`` dict from config.yaml (optional).
        custom_providers: The ``custom_providers:`` list from config.yaml (optional).

    Returns:
        ProviderDef if found, else None.
    """
    canonical = normalize_provider(name)

    # 1. Built-in (models.dev + overlays)
    pdef = get_provider(canonical)
    if pdef is not None:
        return pdef

    # 2. User-defined providers from config
    if user_providers:
        # Try canonical name
        user_pdef = resolve_user_provider(canonical, user_providers)
        if user_pdef is not None:
            return user_pdef
        # Try original name (in case alias didn't match)
        user_pdef = resolve_user_provider(name.strip().lower(), user_providers)
        if user_pdef is not None:
            return user_pdef

    # 2b. Saved custom providers from config
    custom_pdef = resolve_custom_provider(name, custom_providers)
    if custom_pdef is not None:
        return custom_pdef

    # 3. Try models.dev directly (for providers not in our ALIASES)
    try:
        from agent.models_dev import get_provider_info as _mdev_provider
        mdev_info = _mdev_provider(canonical)
        if mdev_info is not None:
            return ProviderDef(
                id=canonical,
                name=mdev_info.name,
                transport="openai_chat",
                api_key_env_vars=mdev_info.env,
                base_url=mdev_info.api,
                source="models.dev",
            )
    except Exception:
        pass

    return None
