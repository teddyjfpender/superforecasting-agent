"""Wire models for the tool-execution events (``tui_gateway/server.py``).

``tool.generating`` (drafting args) → ``tool.start`` → ``tool.progress`` (0+) →
``tool.complete``. The server builds these payloads by conditional key
insertion, so every field beyond the identity ones is optional.
"""

from __future__ import annotations

from typing import Any

from protocol.rpc.session import Usage
from protocol.types import WireModel, wire_optional


class ToolProgress(WireModel):
    """``tool.progress`` — a mid-execution progress preview for a running tool."""

    TS_NAME = "ToolProgressPayload"

    name: str | None = wire_optional()
    preview: str | None = wire_optional()


class ToolGenerating(WireModel):
    """``tool.generating`` — the model is drafting this tool's arguments."""

    TS_NAME = "ToolGeneratingPayload"

    name: str | None = wire_optional()


class ToolStart(WireModel):
    """``tool.start`` — a tool call began (``tool_id`` identifies the call)."""

    TS_NAME = "ToolStartPayload"

    tool_id: str
    name: str | None = wire_optional()
    context: str | None = wire_optional()
    todos: list[Any] | None = wire_optional()


class ToolComplete(WireModel):
    """``tool.complete`` — a tool call finished.

    The server (``_on_tool_complete``) emits ``tool_id`` + ``name`` always, then
    conditionally ``duration_s`` / ``summary`` / ``todos`` / ``inline_diff`` /
    ``usage``.  It NEVER emits ``error`` (the hand-written TUI type read a
    non-existent ``error`` field — see the A2 report).

    ``usage`` carries the CUMULATIVE session usage (the same shape
    ``message.complete`` ships) as of tool-complete time.  The API call that
    produced this tool call has already folded into the session counters before
    the tool executes (``conversation_loop`` folds usage right after the
    response; ``_execute_tool_calls`` fires the complete callback afterward), so
    the TUI can climb its liveness counter mid-turn instead of only at
    ``message.complete``.
    """

    TS_NAME = "ToolCompletePayload"

    tool_id: str
    name: str | None = wire_optional()
    duration_s: float | None = wire_optional()
    summary: str | None = wire_optional()
    inline_diff: str | None = wire_optional()
    todos: list[Any] | None = wire_optional()
    usage: Usage | None = wire_optional()


__all__ = ["ToolProgress", "ToolGenerating", "ToolStart", "ToolComplete"]
