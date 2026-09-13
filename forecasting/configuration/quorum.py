"""Quorum default-policy validation independent of command presentation."""

from __future__ import annotations


def default_policy_changes(
    state: str | None, scope: str | None
) -> dict[str, bool | str]:
    changes: dict[str, bool | str] = {}
    if state is not None:
        if not isinstance(state, str) or state.strip().lower() not in {"on", "off"}:
            raise ValueError("forecast quorum default on|off")
        changes["quorum.default_enabled"] = state.strip().lower() == "on"
    if scope is not None:
        if not isinstance(scope, str) or scope not in {
            "high_impact",
            "always",
            "first_only",
        }:
            raise ValueError(
                "quorum default scope must be high_impact, always, or first_only"
            )
        changes["quorum.default_scope"] = scope
    return changes
