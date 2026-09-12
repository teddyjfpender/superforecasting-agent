"""Pure selection of positive, whole-number agent execution budgets."""

from collections.abc import Mapping
from typing import cast


def positive_turn_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        count = int(value)
    except ValueError:
        return None
    return count if count > 0 else None


def configured_turn_count(config: object, *, override: object = None) -> int | None:
    """Select an explicit, nested or legacy budget without reading fallback state."""
    values = cast(Mapping[str, object], config) if isinstance(config, Mapping) else {}
    section = values.get("agent")
    agent = cast(Mapping[str, object], section) if isinstance(section, Mapping) else {}
    for value in (override, agent.get("max_turns"), values.get("max_turns")):
        count = positive_turn_count(value)
        if count is not None:
            return count
    return None


def agent_turn_budget(
    config: object, *, override: object = None, default: int = 90
) -> int:
    """Select a configured budget or a validated caller-owned fallback.

    Numeric strings remain compatible. Invalid candidates fall through without
    truncating fractions or interpreting boolean flags as execution budgets.
    Callers retain ownership of reading environment overrides and profile data.
    """
    if type(default) is not int or default <= 0:
        raise ValueError("default agent turn budget must be a positive integer")
    count = configured_turn_count(config, override=override)
    return count if count is not None else default
