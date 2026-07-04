"""Wire models for the per-turn streaming events (``tui_gateway/server.py``).

The lifecycle of one agent turn: ``message.start`` → interleaved
``thinking.delta`` / ``reasoning.delta`` / ``message.delta`` / ``status.update``
→ ``message.complete`` (or ``error``). ``reasoning.available`` and
``browser.progress`` ride the same transport.
"""

from __future__ import annotations

from typing import Any

from protocol.types import WireModel, wire_optional


class ThinkingDelta(WireModel):
    """``thinking.delta`` — a chunk of the model's thinking stream."""

    TS_NAME = "ThinkingDeltaPayload"

    text: str | None = wire_optional()


class MessageStart(WireModel):
    """``message.start`` — the assistant began a message (no payload body)."""

    TS_NAME = "MessageStartPayload"


class MessageDelta(WireModel):
    """``message.delta`` — a streamed chunk of the assistant message."""

    TS_NAME = "MessageDeltaPayload"

    text: str | None = wire_optional()
    rendered: str | None = wire_optional()


class MessageComplete(WireModel):
    """``message.complete`` — the terminal turn frame.

    The server ALWAYS emits ``text``, ``usage`` and ``status``; ``reasoning`` /
    ``warning`` / ``rendered`` are conditional. (The hand-written TUI type
    omitted ``status`` and ``warning`` — modelled here for fidelity.)
    """

    TS_NAME = "MessageCompletePayload"

    text: str
    status: str
    usage: dict[str, Any]
    rendered: str | None = wire_optional()
    reasoning: str | None = wire_optional()
    warning: str | None = wire_optional()


class ReasoningDelta(WireModel):
    """``reasoning.delta`` — a chunk of the provider's reasoning stream."""

    TS_NAME = "ReasoningDeltaPayload"

    text: str | None = wire_optional()


class ReasoningAvailable(WireModel):
    """``reasoning.available`` — a complete reasoning block became available."""

    TS_NAME = "ReasoningAvailablePayload"

    text: str | None = wire_optional()


class StatusUpdate(WireModel):
    """``status.update`` — a status line (``kind`` steers the TUI's treatment:
    goal / process / status / compressing / error / warn / approval)."""

    TS_NAME = "StatusUpdatePayload"

    kind: str
    text: str


class ErrorEvent(WireModel):
    """``error`` — a turn-level error (auth expiry, init failure, refusal)."""

    TS_NAME = "ErrorPayload"

    message: str


class BrowserProgress(WireModel):
    """``browser.progress`` — a progress line from the browser tool."""

    TS_NAME = "BrowserProgressPayload"

    message: str | None = wire_optional()
    level: str | None = wire_optional()


__all__ = [
    "ThinkingDelta",
    "MessageStart",
    "MessageDelta",
    "MessageComplete",
    "ReasoningDelta",
    "ReasoningAvailable",
    "StatusUpdate",
    "ErrorEvent",
    "BrowserProgress",
]
