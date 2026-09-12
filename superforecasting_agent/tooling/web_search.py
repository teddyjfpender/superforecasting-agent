"""Shared provider-routed web search, independent of tool serialization."""

from __future__ import annotations

import logging
from typing import Any

from agent import web_search_registry
from superforecasting_agent.tooling.interrupts import is_interrupted

logger = logging.getLogger(__name__)


def normalize_search_limit(limit: Any) -> int:
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5
    return min(max(limit, 1), 100)


def search_web(query: str, limit: int = 5) -> dict[str, Any]:
    """Use the registry's configured provider and preserve its structured result.

    Provider calls are synchronous and cooperative. An interrupt observed after a
    call prevents its result from becoming research evidence; it cannot forcibly
    stop a provider that ignores cancellation while blocked inside its own client.
    """
    try:
        if is_interrupted():
            return {"success": False, "error": "Interrupted"}
        provider = web_search_registry.get_active_search_provider()
        if is_interrupted():
            return {"success": False, "error": "Interrupted"}
        if provider is None:
            return {
                "success": False,
                "error": "No web search provider configured. Run `superforecasting-agent tools` to set one up.",
            }
        bounded_limit = normalize_search_limit(limit)
        logger.info(
            "Web search via %s: '%s' (limit: %d)", provider.name, query, bounded_limit
        )
        result = provider.search(query, bounded_limit)
        if is_interrupted():
            return {"success": False, "error": "Interrupted"}
        if not isinstance(result, dict):
            raise ValueError("Search provider returned a non-object response")
        if result.get("error"):
            return {**result, "success": False}
        if not isinstance(result.get("success"), bool):
            raise ValueError("Search provider returned an invalid success status")
        if result["success"]:
            data = result.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("web"), list):
                raise ValueError("Search provider returned an invalid web result list")
        return result
    except Exception as exc:
        message = f"Error searching web: {exc}"
        logger.debug("%s", message)
        if is_interrupted():
            return {"success": False, "error": "Interrupted"}
        return {"error": message}
