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


class BuildInfo(WireModel):
    """The running APPLICATION build — which binary the operator is actually in,
    and whether it is behind the newest published release.

    Distinct from ``protocol_version`` (the wire handshake): this is the product
    version, and it exists because a pipx-installed build freezes its own TUI
    bundle inside its venv, so a repo-side rebuild never reaches it and the
    operator has no way to tell. ``tui_gateway.server.build_info`` fills it from
    ``superforecasting_agent.runtime.banner.get_update_state()``, which reads only the ALREADY
    scheduled + 6-hour-cached background update check — never its own network
    call, so it cannot delay ``gateway.ready`` or fail when offline.

    ``version`` is the only guaranteed key; every remote-derived field is absent
    when the check has not landed (cold cache) or the box is offline.
    """

    TS_NAME = "BuildInfoPayload"

    version: str
    release_date: str | None = wire_optional()
    # git / pip / homebrew / nixos / docker — how this build got on the box.
    install_method: str | None = wire_optional()
    # The newest PUBLISHED release, when the cached check has resolved one.
    latest_version: str | None = wire_optional()
    # Commits behind the snapshot branch; -1 = known behind, count unavailable.
    behind: int | None = wire_optional(nullable=True)
    # THE verdict the TUI branches on — never recomputed client-side.
    stale: bool | None = wire_optional()
    # The concrete command that replaces this build (lane-aware).
    remedy: str | None = wire_optional()


class GatewayReady(WireModel):
    """``gateway.ready`` — first frame after connect; carries the initial skin, the
    running ``build`` identity, and the wire ``protocol_version`` (the A4 version
    handshake — the TUI compares it against its generated ``PROTOCOL_VERSION`` and
    warns, never hard-fails, on a mismatch). Optional so an older gateway that
    omits them is tolerated."""

    TS_NAME = "GatewayReadyPayload"

    skin: Skin | None = wire_optional()
    protocol_version: int | None = wire_optional()
    build: BuildInfo | None = wire_optional()


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
    # A4 version handshake — the same wire version gateway.ready advertises,
    # echoed on session.info so a resumed/steered path can revalidate. Optional
    # (an older gateway omits it).
    protocol_version: int | None = wire_optional()
    # The running build, echoed from gateway.ready. session.info lands AFTER the
    # background update check has usually finished, so this is the frame that
    # upgrades a cold-cache "unknown" into a real staleness verdict.
    build: BuildInfo | None = wire_optional()


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
    "BuildInfo",
    "GatewayReady",
    "SessionInfo",
    "GatewayStderr",
    "GatewayStartTimeout",
    "GatewayProtocolError",
]
