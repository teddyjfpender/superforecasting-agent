"""Command input validation shared by terminal, CLI and messaging adapters."""

from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandInput:
    name: str
    arguments: str


def command_fields(name: object, arguments: object = "") -> CommandInput:
    """Validate structured RPC input without silently coercing malformed values."""
    if not isinstance(name, str) or not name.strip().lstrip("/"):
        raise ValueError("Command name must be non-empty text")
    canonical = name.strip().lstrip("/").lower()
    if any(character.isspace() for character in canonical):
        raise ValueError("Command name must be a single word")
    if not isinstance(arguments, str):
        raise ValueError("Command arguments must be text")
    return CommandInput(canonical, arguments.strip())


def command_text(text: str) -> CommandInput:
    """Split a full slash invocation while preserving argument case and quoting."""
    parts = text.strip().split(None, 1)
    return command_fields(parts[0] if parts else "", parts[1] if len(parts) > 1 else "")


@dataclass(frozen=True)
class BoardInvocation:
    arguments: str
    tokens: tuple[str, ...]
    board: str | None
    action: str | None


def board_invocation(arguments: str) -> BoardInvocation:
    """Parse shell quoting and leading board selection before execution/delivery.

    Subcommand-specific flags remain owned by the board's argparse tree. This
    shared projection ensures gateway notifications target the same leading
    board selection used by execution and malformed quoting fails before I/O.
    """
    try:
        tokens = tuple(shlex.split(arguments))
    except ValueError as exc:
        raise ValueError(f"Invalid command arguments: {exc}") from exc
    board = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--board":
            index += 1
            if (
                index >= len(tokens)
                or tokens[index].startswith("--")
                or not tokens[index]
            ):
                raise ValueError("--board requires a slug")
            board = tokens[index]
        elif token.startswith("--board="):
            board = token.partition("=")[2]
            if not board:
                raise ValueError("--board requires a slug")
        else:
            break
        index += 1
    return BoardInvocation(
        arguments, tokens, board, tokens[index] if index < len(tokens) else None
    )
