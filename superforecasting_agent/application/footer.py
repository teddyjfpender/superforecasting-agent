"""Shared runtime-footer inspection and atomic configuration transitions."""

from pathlib import Path
from typing import Any

from superforecasting_agent.storage.configuration import ProfileConfiguration
from superforecasting_agent.storage.files import (
    atomic_roundtrip_yaml_mutate,
    set_nested,
)


def _state(config: dict[str, Any]) -> tuple[bool, list[str]]:
    display = config.get("display", {})
    if not isinstance(display, dict):
        raise ValueError("display must be a mapping")
    footer = display.get("runtime_footer", {})
    if not isinstance(footer, dict):
        raise ValueError("display.runtime_footer must be a mapping")
    enabled = footer.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("display.runtime_footer.enabled must be a boolean")
    fields = footer.get("fields") or ["model", "context_pct", "cwd"]
    if not isinstance(fields, list) or not all(
        isinstance(field, str) for field in fields
    ):
        raise ValueError("display.runtime_footer.fields must be a list of strings")
    return enabled, fields


def footer_command(argument: str, path: Path) -> str:
    """Inspect without writing; mutate a toggle against the locked latest value."""
    argument = argument.strip().lower()
    if argument in {"status", "?"}:
        reader = ProfileConfiguration()
        config = reader.load(path)
        if reader.last_error:
            raise ValueError(reader.last_error)
        enabled, fields = _state(config)
        return (
            f"Runtime footer: {'ON' if enabled else 'OFF'}\nFields: {', '.join(fields)}"
        )

    enabled = change_footer(argument, path)
    return f"Runtime footer: {'ON' if enabled else 'OFF'}"


def change_footer(argument: str, path: Path) -> bool:
    """Set or toggle the global flag while preserving platform overrides."""
    argument = argument.strip().lower()
    choices = {
        "on": True,
        "enable": True,
        "true": True,
        "1": True,
        "off": False,
        "disable": False,
        "false": False,
        "0": False,
    }
    if argument not in {"", *choices}:
        raise ValueError("Usage: /footer [on|off|status]")
    enabled = False

    def mutate(config: dict[str, Any]) -> None:
        nonlocal enabled
        current, _ = _state(config)
        enabled = choices.get(argument, not current)
        set_nested(config, "display.runtime_footer.enabled", enabled)

    atomic_roundtrip_yaml_mutate(path, mutate)
    return enabled
