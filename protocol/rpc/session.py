"""Wire models for the ``session.*`` lifecycle RPCs (Arc A4).

Also the canonical home for the three composite app-types the whole TUI reads —
``SessionInfo`` / ``Usage`` / ``McpServerStatus``. They were hand-written in
``ui-tui/src/types.ts``; A4 makes the PROTOCOL their single source of truth (the
``types.ts`` copies become re-exports of these generated shapes), so every
``info``/``usage`` field on a response references ONE modelled type instead of a
drifting mirror.

The models below are transcribed field-for-field from the deleted
``ui-tui/src/gatewayTypes.ts`` mirrors — the wire never changes shape, it is only
now generated + validated.
"""

from __future__ import annotations

from typing import Any, Literal

from protocol.events.gateway import BuildInfo
from protocol.types import WireModel, wire_optional

# ── composite app-types (single source of truth; re-exported by types.ts) ──────


class McpServerStatus(WireModel):
    TS_NAME = "McpServerStatus"

    connected: bool
    name: str
    tools: int
    transport: str


class Usage(WireModel):
    TS_NAME = "Usage"

    calls: int
    input: int
    output: int
    total: int
    compressions: int | None = wire_optional()
    context_max: int | None = wire_optional()
    context_percent: int | None = wire_optional()
    context_used: int | None = wire_optional()
    cost_status: str | None = wire_optional()
    cost_usd: float | None = wire_optional()
    reasoning: int | None = wire_optional()


class SessionInfo(WireModel):
    """The full session descriptor the whole app reads (``types.ts`` re-exports
    this). Distinct from the deliberately-thin ``SessionInfoPayload`` A2 modelled
    for the ``session.info`` EVENT — this is the rich shape response ``info`` fields
    carry."""

    TS_NAME = "SessionInfo"

    durable_session_id: str | None = wire_optional()
    model: str
    skills: dict[str, list[str]]
    tools: dict[str, list[str]]
    cwd: str | None = wire_optional()
    fast: bool | None = wire_optional()
    lazy: bool | None = wire_optional()
    mcp_servers: list[McpServerStatus] | None = wire_optional()
    profile_name: str | None = wire_optional()
    reasoning_effort: str | None = wire_optional()
    release_date: str | None = wire_optional()
    service_tier: str | None = wire_optional()
    system_prompt: str | None = wire_optional()
    update_behind: int | None = wire_optional(nullable=True)
    update_command: str | None = wire_optional()
    usage: Usage | None = wire_optional()
    version: str | None = wire_optional()
    # A4 version handshake — echoed on the rich descriptor too (see _session_info).
    protocol_version: int | None = wire_optional()
    # The running application build + staleness verdict (see BuildInfo). The rich
    # descriptor carries it so a resume / model-switch frame refreshes the verdict
    # the TUI first learned from gateway.ready.
    build: BuildInfo | None = wire_optional()


class SessionCreateInfo(SessionInfo):
    """``session.create``'s ``info`` — ``SessionInfo`` plus the two one-shot
    creation warnings (the old ``SessionInfo & {config_warning?, credential_warning?}``
    intersection, expressed as a subclass so it generates a flat interface)."""

    TS_NAME = "SessionCreateInfo"

    config_warning: str | None = wire_optional()
    credential_warning: str | None = wire_optional()


class GatewayTranscriptMessage(WireModel):
    TS_NAME = "GatewayTranscriptMessage"

    role: Literal["assistant", "system", "tool", "user"]
    context: str | None = wire_optional()
    name: str | None = wire_optional()
    text: str | None = wire_optional()


# ── session.create ─────────────────────────────────────────────────────────────


class SessionCreateRequest(WireModel):
    TS_NAME = "SessionCreateRequest"

    cols: int | None = None


class SessionCreateResponse(WireModel):
    TS_NAME = "SessionCreateResponse"

    session_id: str
    info: SessionCreateInfo | None = wire_optional()


# ── session.resume ─────────────────────────────────────────────────────────────


class SessionResumeRequest(WireModel):
    TS_NAME = "SessionResumeRequest"

    session_id: str
    cols: int | None = None
    replace_session_id: str | None = None


class SessionResumeResponse(WireModel):
    TS_NAME = "SessionResumeResponse"

    session_id: str
    messages: list[GatewayTranscriptMessage]
    info: SessionInfo | None = wire_optional()
    message_count: int | None = wire_optional()
    resumed: str | None = wire_optional()
    recovery: dict | None = wire_optional()


# ── session.list ───────────────────────────────────────────────────────────────


class SessionListRequest(WireModel):
    TS_NAME = "SessionListRequest"


class SessionListItem(WireModel):
    TS_NAME = "SessionListItem"

    id: str
    message_count: int
    preview: str
    started_at: int
    title: str
    source: str | None = wire_optional()


class SessionListResponse(WireModel):
    TS_NAME = "SessionListResponse"

    sessions: list[SessionListItem] | None = wire_optional()


# ── session.delete ─────────────────────────────────────────────────────────────


class SessionDeleteRequest(WireModel):
    TS_NAME = "SessionDeleteRequest"

    session_id: str


class SessionDeleteResponse(WireModel):
    TS_NAME = "SessionDeleteResponse"

    deleted: str


# ── session.most_recent ────────────────────────────────────────────────────────


class SessionMostRecentRequest(WireModel):
    TS_NAME = "SessionMostRecentRequest"


class SessionMostRecentResponse(WireModel):
    TS_NAME = "SessionMostRecentResponse"

    session_id: str | None = wire_optional(nullable=True)
    source: str | None = wire_optional()
    started_at: int | None = wire_optional()
    title: str | None = wire_optional()


# ── session.title ──────────────────────────────────────────────────────────────


class SessionTitleRequest(WireModel):
    TS_NAME = "SessionTitleRequest"

    session_id: str | None = None


class SessionTitleResponse(WireModel):
    TS_NAME = "SessionTitleResponse"

    pending: bool | None = wire_optional()
    session_key: str | None = wire_optional()
    title: str | None = wire_optional()


# ── session.save ───────────────────────────────────────────────────────────────


class SessionSaveRequest(WireModel):
    TS_NAME = "SessionSaveRequest"

    session_id: str | None = None


class SessionSaveResponse(WireModel):
    TS_NAME = "SessionSaveResponse"

    file: str | None = wire_optional()


# ── session.undo ───────────────────────────────────────────────────────────────


class SessionUndoRequest(WireModel):
    TS_NAME = "SessionUndoRequest"

    session_id: str | None = None


class SessionUndoResponse(WireModel):
    TS_NAME = "SessionUndoResponse"

    removed: int | None = wire_optional()


# ── session.usage ──────────────────────────────────────────────────────────────


class SessionUsageRequest(WireModel):
    TS_NAME = "SessionUsageRequest"

    session_id: str | None = None


class SessionUsageResponse(WireModel):
    TS_NAME = "SessionUsageResponse"

    cache_read: int | None = wire_optional()
    cache_write: int | None = wire_optional()
    calls: int | None = wire_optional()
    compressions: int | None = wire_optional()
    context_max: int | None = wire_optional()
    context_percent: int | None = wire_optional()
    context_used: int | None = wire_optional()
    cost_status: Literal["estimated", "exact"] | None = wire_optional()
    cost_usd: float | None = wire_optional()
    input: int | None = wire_optional()
    model: str | None = wire_optional()
    output: int | None = wire_optional()
    total: int | None = wire_optional()


# ── session.status ─────────────────────────────────────────────────────────────


class SessionStatusRequest(WireModel):
    TS_NAME = "SessionStatusRequest"

    session_id: str | None = None


class SessionStatusResponse(WireModel):
    TS_NAME = "SessionStatusResponse"

    output: str | None = wire_optional()


# ── session.compress ───────────────────────────────────────────────────────────


class SessionCompressRequest(WireModel):
    TS_NAME = "SessionCompressRequest"

    session_id: str | None = None


class SessionCompressSummary(WireModel):
    TS_NAME = "SessionCompressSummary"

    headline: str | None = wire_optional()
    noop: bool | None = wire_optional()
    note: str | None = wire_optional(nullable=True)
    token_line: str | None = wire_optional()


class SessionCompressResponse(WireModel):
    TS_NAME = "SessionCompressResponse"

    after_messages: int | None = wire_optional()
    after_tokens: int | None = wire_optional()
    before_messages: int | None = wire_optional()
    before_tokens: int | None = wire_optional()
    info: SessionInfo | None = wire_optional()
    messages: list[GatewayTranscriptMessage] | None = wire_optional()
    removed: int | None = wire_optional()
    summary: SessionCompressSummary | None = wire_optional()
    usage: Usage | None = wire_optional()


# ── session.branch ─────────────────────────────────────────────────────────────


class SessionBranchRequest(WireModel):
    TS_NAME = "SessionBranchRequest"

    session_id: str | None = None


class SessionBranchResponse(WireModel):
    TS_NAME = "SessionBranchResponse"

    session_id: str | None = wire_optional()
    title: str | None = wire_optional()


# ── session.close ──────────────────────────────────────────────────────────────


class SessionCloseRequest(WireModel):
    TS_NAME = "SessionCloseRequest"

    session_id: str | None = None


class SessionCloseResponse(WireModel):
    TS_NAME = "SessionCloseResponse"

    ok: bool | None = wire_optional()


# ── session.interrupt ──────────────────────────────────────────────────────────


class SessionInterruptRequest(WireModel):
    TS_NAME = "SessionInterruptRequest"

    session_id: str | None = None


class SessionInterruptResponse(WireModel):
    TS_NAME = "SessionInterruptResponse"
    status: str | None = wire_optional()

    ok: bool | None = wire_optional()


# ── session.steer ──────────────────────────────────────────────────────────────


class SessionSteerRequest(WireModel):
    TS_NAME = "SessionSteerRequest"

    session_id: str | None = None
    text: str | None = None


class SessionSteerResponse(WireModel):
    TS_NAME = "SessionSteerResponse"

    status: Literal["queued", "rejected"] | None = wire_optional()
    text: str | None = wire_optional()


# ── session.history ────────────────────────────────────────────────────────────


class SessionHistoryRequest(WireModel):
    TS_NAME = "SessionHistoryRequest"

    session_id: str | None = None


class SessionHistoryResponse(WireModel):
    TS_NAME = "SessionHistoryResponse"

    messages: list[GatewayTranscriptMessage] | None = wire_optional()


__all__ = [
    "McpServerStatus",
    "Usage",
    "SessionInfo",
    "SessionCreateInfo",
    "GatewayTranscriptMessage",
    "SessionCreateRequest",
    "SessionCreateResponse",
    "SessionResumeRequest",
    "SessionResumeResponse",
    "SessionListRequest",
    "SessionListItem",
    "SessionListResponse",
    "SessionDeleteRequest",
    "SessionDeleteResponse",
    "SessionMostRecentRequest",
    "SessionMostRecentResponse",
    "SessionTitleRequest",
    "SessionTitleResponse",
    "SessionSaveRequest",
    "SessionSaveResponse",
    "SessionUndoRequest",
    "SessionUndoResponse",
    "SessionUsageRequest",
    "SessionUsageResponse",
    "SessionStatusRequest",
    "SessionStatusResponse",
    "SessionCompressRequest",
    "SessionCompressSummary",
    "SessionCompressResponse",
    "SessionBranchRequest",
    "SessionBranchResponse",
    "SessionCloseRequest",
    "SessionCloseResponse",
    "SessionInterruptRequest",
    "SessionInterruptResponse",
    "SessionSteerRequest",
    "SessionSteerResponse",
    "SessionHistoryRequest",
    "SessionHistoryResponse",
]
