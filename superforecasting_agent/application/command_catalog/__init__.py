"""Shared command metadata and resolution, independent of presentation.

Workflow definitions and operator support definitions have separate owners;
this catalog assembles them in stable order and owns alias resolution.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .operations import COMMANDS as _OPERATION_COMMANDS
from .types import CommandDef as CommandDef
from .workflow import COMMANDS as _WORKFLOW_COMMANDS
from .workflow import FORECAST_DESK_SUBCOMMANDS as FORECAST_DESK_SUBCOMMANDS

COMMAND_CATEGORY_ORDER: tuple[str, ...] = (
    "Forecast Desk",
    "Session",
    "Configuration",
    "Tools & Skills",
    "Compatibility",
    "Info",
    "Exit",
)

COMMAND_REGISTRY: list[CommandDef] = [*_WORKFLOW_COMMANDS, *_OPERATION_COMMANDS]


def _build_command_lookup() -> dict[str, CommandDef]:
    """Map every name and alias to its CommandDef."""
    lookup: dict[str, CommandDef] = {}
    for cmd in COMMAND_REGISTRY:
        lookup[cmd.name] = cmd
        for alias in cmd.aliases:
            lookup[alias] = cmd
    return lookup


_COMMAND_LOOKUP: dict[str, CommandDef] = _build_command_lookup()


def resolve_command(name: str) -> CommandDef | None:
    """Resolve a command name or alias to its CommandDef.

    Accepts names with or without the leading slash.
    """
    return _COMMAND_LOOKUP.get(name.lower().lstrip("/"))


def configured_command(
    name: str, quick_commands: Mapping | None
) -> Mapping[str, Any] | None:
    """Validate a configured command while preserving built-in precedence."""
    name = name.lower().lstrip("/")
    if (
        resolve_command(name)
        or not isinstance(quick_commands, Mapping)
        or name not in quick_commands
    ):
        return None
    entry = quick_commands[name]
    if not isinstance(entry, Mapping):
        raise ValueError(f"Quick command '/{name}' must be a mapping.")
    kind = entry.get("type")
    if kind not in ("alias", "exec"):
        raise ValueError(
            f"Quick command '/{name}' has unsupported type (supported: 'exec', 'alias')."
        )
    field = "target" if kind == "alias" else "command"
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Quick command '/{name}' has no {field} defined (expected non-empty text)."
        )
    return entry


def expand_quick_alias(command: str, quick_commands: Mapping | None) -> str:
    """Expand configured aliases consistently before CLI/gateway dispatch.

    Built-ins keep precedence; arguments keep their original case. Cycles fail
    without recursion or executing any command in the chain.
    """
    command = command.strip()
    seen: set[str] = set()
    while command and isinstance(quick_commands, Mapping):
        parts = command.split(None, 1)
        name = parts[0].lstrip("/").lower()
        entry = configured_command(name, quick_commands)
        if entry is None or entry["type"] != "alias":
            break
        if name in seen:
            raise ValueError(f"Quick command alias cycle at '/{name}'.")
        seen.add(name)
        target = entry["target"].strip()
        target = target if target.startswith("/") else f"/{target}"
        command = f"{target} {parts[1] if len(parts) > 1 else ''}".strip()
    return command


def _build_description(cmd: CommandDef) -> str:
    """Build a CLI-facing description string including usage hint."""
    if cmd.args_hint:
        return f"{cmd.description} (usage: /{cmd.name} {cmd.args_hint})"
    return cmd.description


SUBCOMMANDS: dict[str, list[str]] = {}
for _cmd in COMMAND_REGISTRY:
    if _cmd.subcommands:
        SUBCOMMANDS[f"/{_cmd.name}"] = list(_cmd.subcommands)

# Also extract subcommands hinted in args_hint via pipe-separated patterns
# e.g. args_hint="[on|off|tts|status]" for commands that don't have explicit subcommands.
# NOTE: If a command already has explicit subcommands, this fallback is skipped.
# Use the `subcommands` field on CommandDef for intentional tab-completable args.
_PIPE_SUBS_RE = re.compile(r"[a-z]+(?:\|[a-z]+)+")
for _cmd in COMMAND_REGISTRY:
    key = f"/{_cmd.name}"
    if key in SUBCOMMANDS or not _cmd.args_hint:
        continue
    m = _PIPE_SUBS_RE.search(_cmd.args_hint)
    if m:
        SUBCOMMANDS[key] = m.group(0).split("|")
