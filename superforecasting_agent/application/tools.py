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


def describe_tool_configuration(
    enabled: set[str], mcp_servers: Mapping[str, Any], *, platform: str = "cli"
) -> str:
    """Describe saved selection and filters, without claiming live availability."""
    from superforecasting_agent.tooling.selection import (
        CONFIGURABLE_TOOLSETS,
        _get_effective_configurable_toolsets,
        _toolset_allowed_for_platform,
    )

    builtin = {name for name, _, _ in CONFIGURABLE_TOOLSETS}
    effective = [
        item
        for item in _get_effective_configurable_toolsets()
        if _toolset_allowed_for_platform(item[0], platform)
    ]
    lines = [f"Built-in toolsets ({platform}):"]
    for is_builtin in (True, False):
        rows = [item for item in effective if (item[0] in builtin) == is_builtin]
        if not is_builtin and rows:
            lines.extend(["", f"Plugin toolsets ({platform}):"])
        for name, label, _ in rows:
            status = "✓ enabled" if name in enabled else "✗ disabled"
            lines.append(f"  {status}  {name}  {label}")
    if mcp_servers:
        lines.extend(["", "MCP servers:"])
        for name, config in mcp_servers.items():
            if not isinstance(config, Mapping):
                raise ValueError(f"MCP server {name!r} must be a configuration mapping")
            if config.get("enabled") is False:
                lines.append(f"  {name}  disabled")
                continue
            filters = config.get("tools") or {}
            if not isinstance(filters, Mapping):
                raise ValueError(f"MCP server {name!r} tools must be a mapping")
            descriptions = []
            for key, label in (("include", "include only"), ("exclude", "excluded")):
                values = filters.get(key) or []
                if not isinstance(values, list) or any(
                    not isinstance(value, str) for value in values
                ):
                    raise ValueError(
                        f"MCP server {name!r} {key} must be a list of tool names"
                    )
                if values:
                    descriptions.append(f"[{label}: {', '.join(values)}]")
            lines.append(
                f"  {name}  " + (" ".join(descriptions) or "all tools enabled")
            )
    return "\n".join(lines)
