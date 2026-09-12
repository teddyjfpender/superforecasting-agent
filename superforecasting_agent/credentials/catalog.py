"""Credential availability inventory shared by forecasting and product adapters."""

from __future__ import annotations

import os
from typing import Any

from superforecasting_agent.configuration.provider_catalog import CANONICAL_PROVIDERS
from superforecasting_agent.configuration.provider_catalog import (
    PROVIDER_LABELS as _PROVIDER_LABELS,
)
from superforecasting_agent.configuration.providers import (
    PROVIDER_ALIASES as _PROVIDER_ALIASES,
)


def list_available_providers() -> list[dict[str, Any]]:
    """Return info about all providers the user could use with ``provider:model``.

    Each dict has ``id``, ``label``, and ``aliases``.
    Checks credential configuration, not quota or successful inference.
    Raises when any provider cannot be inspected: this boolean inventory must
    never turn a partial discovery failure into proof of disconnection.

    Derives the provider list from :data:`CANONICAL_PROVIDERS` (single
    source of truth shared with ``superforecasting-agent model``, ``/model``,
    etc.).
    """
    # Derive display order from canonical list + custom
    provider_order = [p.slug for p in CANONICAL_PROVIDERS] + ["custom"]

    # Build reverse alias map
    aliases_for: dict[str, list[str]] = {}
    for alias, canonical in _PROVIDER_ALIASES.items():
        aliases_for.setdefault(canonical, []).append(alias)

    result = []
    for pid in provider_order:
        label = _PROVIDER_LABELS.get(pid, pid)
        alias_list = aliases_for.get(pid, [])
        # Check if this provider has credentials available
        has_creds = False
        try:
            from superforecasting_agent.configuration.authentication import (
                has_usable_secret,
            )
            from superforecasting_agent.credentials.auth import get_auth_status

            if pid == "custom":
                custom_base_url = _get_custom_base_url() or ""
                has_creds = bool(custom_base_url.strip())
            elif pid == "openrouter":
                has_creds = has_usable_secret(os.getenv("OPENROUTER_API_KEY", ""))
            else:
                status = get_auth_status(pid)
                has_creds = bool(status.get("logged_in") or status.get("configured"))
        except Exception as exc:
            raise RuntimeError(
                f"Credential discovery unavailable for provider {pid}"
            ) from exc
        result.append({
            "id": pid,
            "label": label,
            "aliases": alias_list,
            "authenticated": has_creds,
        })
    return result


def _get_custom_base_url() -> str:
    """Get the custom endpoint base_url from config.yaml."""
    try:
        from superforecasting_agent.credentials.environment import load_config

        config = load_config()
        model_cfg = config.get("model", {})
        if isinstance(model_cfg, dict):
            return str(model_cfg.get("base_url", "")).strip()
    except Exception:
        pass
    return ""
