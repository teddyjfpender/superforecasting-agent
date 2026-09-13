"""Pure interpretation of configured cross-turn goal budgets."""

from collections.abc import Mapping
from typing import cast

DEFAULT_MAX_TURNS = 20


def configured_goal_turn_budget(settings: object) -> int:
    """Read a positive whole-number budget, defaulting malformed configuration.

    Numeric strings remain supported for existing profiles. Booleans, fractions,
    nonpositive values and malformed sections must not become execution budgets.
    This does not rewrite configuration or reinterpret stored goal history.
    """
    value = (
        cast(Mapping[object, object], settings).get("max_turns")
        if isinstance(settings, Mapping)
        else None
    )
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return DEFAULT_MAX_TURNS
    try:
        budget = int(value)
    except ValueError:
        return DEFAULT_MAX_TURNS
    return budget if budget > 0 else DEFAULT_MAX_TURNS
