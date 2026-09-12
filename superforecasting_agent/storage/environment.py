"""Read profile credential files without CLI initialization or environment mutation."""

from __future__ import annotations

from collections.abc import Collection
from functools import lru_cache
from pathlib import Path

from superforecasting_agent.configuration.env_lines import parse_environment
from superforecasting_agent.configuration.environment_catalog import (
    _EXTRA_ENV_KEYS,
    OPTIONAL_ENV_VARS,
)


@lru_cache(maxsize=1)
def _parse(contents: str, known_keys: frozenset[str]) -> dict[str, str]:
    return parse_environment(contents, known_keys)


def read_environment(
    path: Path, *, known_keys: Collection[str] | None = None
) -> dict[str, str]:
    """Return independent parsed values from this file's current contents.

    Cache parsing, not filesystem metadata: key rotation must remain visible even
    when an external editor preserves size and timestamps. Only the last parsed
    contents are retained, and callers cannot mutate the cached mapping. Missing
    files return an empty mapping; other read errors propagate to the caller.
    """
    try:
        contents = path.read_text(encoding="utf-8-sig", errors="replace")
    except FileNotFoundError:
        contents = ""
    keys = (
        frozenset(known_keys)
        if known_keys is not None
        else frozenset(OPTIONAL_ENV_VARS) | _EXTRA_ENV_KEYS
    )
    return dict(_parse(contents, keys))


def clear_environment_cache() -> None:
    """Discard the retained parsed credentials after an owned mutation."""
    _parse.cache_clear()
