"""Inheritance policy for background agents, independent of transport."""

import copy
from typing import Any


def background_agent_options(
    agent: Any, task_id: str, defaults: dict[str, Any]
) -> dict[str, Any]:
    def _inherit(name: str) -> Any:
        value = getattr(agent, name, None)
        return copy.deepcopy(defaults.get(name) if value is None else value)

    return {
        "base_url": getattr(agent, "base_url", None) or None,
        "api_key": getattr(agent, "api_key", None) or None,
        "provider": getattr(agent, "provider", None) or None,
        "api_mode": getattr(agent, "api_mode", None) or None,
        "acp_command": getattr(agent, "acp_command", None) or None,
        "acp_args": getattr(agent, "acp_args", None) or None,
        "model": getattr(agent, "model", None) or defaults.get("model", ""),
        "max_iterations": defaults.get("max_iterations", 25),
        "enabled_toolsets": _inherit("enabled_toolsets"),
        "quiet_mode": True,
        "verbose_logging": False,
        "ephemeral_system_prompt": getattr(agent, "ephemeral_system_prompt", None)
        or None,
        "providers_allowed": _inherit("providers_allowed"),
        "providers_ignored": _inherit("providers_ignored"),
        "providers_order": _inherit("providers_order"),
        "provider_sort": getattr(agent, "provider_sort", None),
        "provider_require_parameters": getattr(
            agent, "provider_require_parameters", False
        ),
        "provider_data_collection": getattr(agent, "provider_data_collection", None),
        "openrouter_min_coding_score": getattr(
            agent, "openrouter_min_coding_score", None
        ),
        "session_id": task_id,
        "reasoning_config": _inherit("reasoning_config"),
        "service_tier": _inherit("service_tier"),
        "request_overrides": copy.deepcopy(
            getattr(agent, "request_overrides", {}) or {}
        ),
        "platform": defaults.get("platform"),
        "session_db": defaults.get("session_db"),
        "fallback_model": getattr(agent, "_fallback_model", None),
    }
