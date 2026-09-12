"""Shared text view of the tools available to a conversation."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any


def describe_tools(
    definitions: Sequence[Mapping[str, Any]],
    toolset_for_tool: Callable[[str], str | None],
) -> str:
    if not definitions:
        return "No tools available"
    groups: dict[str, list[tuple[str, str]]] = {}
    for tool in sorted(definitions, key=lambda item: item["function"]["name"]):
        function = tool["function"]
        name = function["name"]
        description = function.get("description", "").split("\n")[0]
        if ". " in description:
            description = description[: description.index(". ") + 1]
        groups.setdefault(toolset_for_tool(name) or "unknown", []).append((
            name,
            description,
        ))
    title = "Forecast Desk Tools"
    width = 78
    padding = width - len(title)
    lines = [
        "",
        "+" + "-" * width + "+",
        "|" + " " * (padding // 2) + title + " " * (padding - padding // 2) + "|",
        "+" + "-" * width + "+",
        "",
    ]
    for group in sorted(groups):
        lines.append(f"  [{group}]")
        lines.extend(
            f"    * {name:<20} - {description}" for name, description in groups[group]
        )
        lines.append("")
    lines.extend([f"  Total: {len(definitions)} tools", ""])
    return "\n".join(lines)
