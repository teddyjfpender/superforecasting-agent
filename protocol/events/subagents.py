"""Wire models for the delegation / subagent events.

The six ``subagent.*`` frames share ONE payload shape (built by
``_on_tool_progress`` in ``tui_gateway/server.py``): ``goal`` / ``task_index`` /
``task_count`` are always present, everything else is conditional identity /
rollup metadata. ``background.complete`` is the detached ``delegate_task``
completion.
"""

from __future__ import annotations

from typing import Any

from protocol.types import WireModel, wire_optional


class SubagentEvent(WireModel):
    """Shared payload for ``subagent.spawn_requested`` / ``.start`` / ``.thinking``
    / ``.tool`` / ``.progress`` / ``.complete``."""

    # Distinct TS name so it does NOT collide with the hand-written
    # ``SubagentEventPayload`` interface the handler still consumes (A2 keeps the
    # hand mirror; this DTO is for conformance + future migration).
    TS_NAME = "SubagentEventDTO"

    goal: str
    task_index: int
    task_count: int
    subagent_id: str | None = wire_optional()
    parent_id: str | None = wire_optional()
    depth: int | None = wire_optional()
    model: str | None = wire_optional()
    tool_count: int | None = wire_optional()
    toolsets: list[str] | None = wire_optional()
    input_tokens: int | None = wire_optional()
    output_tokens: int | None = wire_optional()
    reasoning_tokens: int | None = wire_optional()
    api_calls: int | None = wire_optional()
    cost_usd: float | None = wire_optional()
    files_read: list[str] | None = wire_optional()
    files_written: list[str] | None = wire_optional()
    output_tail: list[dict[str, Any]] | None = wire_optional()
    tool_name: str | None = wire_optional()
    tool_preview: str | None = wire_optional()
    text: str | None = wire_optional()
    status: str | None = wire_optional()
    summary: str | None = wire_optional()
    duration_seconds: float | None = wire_optional()


class BackgroundComplete(WireModel):
    """``background.complete`` — a detached ``delegate_task`` finished (or errored;
    the error text rides ``text``)."""

    TS_NAME = "BackgroundCompletePayload"

    task_id: str
    text: str


__all__ = ["SubagentEvent", "BackgroundComplete"]
