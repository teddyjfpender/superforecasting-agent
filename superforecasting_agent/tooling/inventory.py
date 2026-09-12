"""Shared toolset inventory, independent of command and transport rendering."""

from collections.abc import Sequence
from typing import TypedDict


class ToolsetInventoryItem(TypedDict):
    name: str
    description: str
    tool_count: int
    enabled: bool
    tools: list[str]


def toolset_inventory(
    selection: Sequence[str] | None, *, include_legacy: bool = True
) -> list[ToolsetInventoryItem]:
    from superforecasting_agent.tooling.toolsets import (
        get_all_toolsets,
        get_toolset_info,
        is_legacy_toolset,
    )

    enabled = set(selection) if selection is not None else None
    items: list[ToolsetInventoryItem] = []
    for name in sorted(get_all_toolsets()):
        if not include_legacy and is_legacy_toolset(name):
            continue
        info = get_toolset_info(name)
        if info:
            items.append({
                "name": name,
                "description": info["description"],
                "tool_count": info["tool_count"],
                "enabled": enabled is None or name in enabled,
                "tools": list(info["resolved_tools"]),
            })
    return items
