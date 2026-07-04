"""Wire models for the gateway lifecycle / session events.

Mirrors the frames ``tui_gateway/server.py`` (and, for the three
client-synthesised transport events, ``ui-tui/src/gatewayClient.ts``) put on the
wire. ``gateway.ready`` / ``skin.changed`` / ``session.info`` originate
server-side; ``gateway.stderr`` / ``gateway.start_timeout`` /
``gateway.protocol_error`` are synthesised by the TUI transport itself and are
typed here so the TUI references ONE constant set for every event name it
handles (the A2 grep-proof).
"""

from __future__ import annotations

from typing import Any

from protocol.types import WireModel, wire_optional


class Skin(WireModel):
    """The active skin — the ``skin.changed`` payload IS this object, and it is
    nested under ``gateway.ready``'s ``skin`` key. ``tui_gateway.server.resolve_skin``
    emits every key together, or ``{}`` on failure; all keys are conditional."""

    TS_NAME = "SkinPayload"

    name: str | None = wire_optional()
    appearance: str | None = wire_optional()
    banner_logo: str | None = wire_optional()
    banner_hero: str | None = wire_optional()
    tool_prefix: str | None = wire_optional()
    help_header: str | None = wire_optional()
    colors: dict[str, Any] | None = wire_optional()
    branding: dict[str, Any] | None = wire_optional()


class GatewayReady(WireModel):
    """``gateway.ready`` — first frame after connect; carries the initial skin."""

    TS_NAME = "GatewayReadyPayload"

    skin: Skin | None = wire_optional()


class SessionInfo(WireModel):
    """``session.info`` — the agent/session descriptor (``_session_info``).

    NOTE (A2 scope): the full descriptor is large and consumed app-wide as the
    hand-written ``SessionInfo`` interface; this models the STABLE top-level
    fields the server always emits. ``extra='ignore'`` lets the richer real
    frame validate; the conformance test asserts the declared fields survive.
    """

    TS_NAME = "SessionInfoPayload"

    model: str
    reasoning_effort: str
    service_tier: str
    fast: bool
    cwd: str
    version: str
    release_date: str
    update_behind: bool | None
    update_command: str
    profile_name: str
    usage: dict[str, Any]
    tools: dict[str, Any]
    skills: dict[str, Any]


class GatewayStderr(WireModel):
    """``gateway.stderr`` — a stderr/log line (client-synthesised by the TUI transport)."""

    TS_NAME = "GatewayStderrPayload"

    line: str


class GatewayStartTimeout(WireModel):
    """``gateway.start_timeout`` — startup handshake timed out (client-synthesised)."""

    TS_NAME = "GatewayStartTimeoutPayload"

    cwd: str | None = wire_optional()
    python: str | None = wire_optional()
    stderr_tail: str | None = wire_optional()


class GatewayProtocolError(WireModel):
    """``gateway.protocol_error`` — an unparseable/non-JSONRPC line (client-synthesised)."""

    TS_NAME = "GatewayProtocolErrorPayload"

    preview: str | None = wire_optional()


__all__ = [
    "Skin",
    "GatewayReady",
    "SessionInfo",
    "GatewayStderr",
    "GatewayStartTimeout",
    "GatewayProtocolError",
]
