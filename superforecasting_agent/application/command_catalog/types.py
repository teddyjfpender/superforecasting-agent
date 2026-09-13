"""Shared immutable command definition."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandDef:
    """Definition of a single slash command."""

    name: str  # canonical name without slash: "background"
    description: str  # human-readable description
    category: str  # "Forecast Desk", "Session", etc.
    aliases: tuple[str, ...] = ()  # alternative names: ("bg",)
    args_hint: str = ""  # argument placeholder: "<prompt>", "[name]"
    subcommands: tuple[str, ...] = ()  # tab-completable subcommands
    cli_only: bool = False  # only available in CLI
    gateway_only: bool = False  # only available in gateway/messaging
    gateway_config_gate: str | None = (
        None  # config dotpath; when truthy, overrides cli_only for gateway
    )
