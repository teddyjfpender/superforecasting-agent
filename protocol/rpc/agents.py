"""Wire models for the ``agents.*`` / ``delegation.*`` / ``subagent.*`` /
``spawn_tree.*`` RPCs and the shared ``SubagentEventPayload`` (Arc A4 — the
plan's named "agents" family).

``SubagentEventPayload`` is the shape carried by every ``subagent.*`` event
(spawn/start/thinking/tool/progress/complete); it lived hand-written in
``gatewayTypes.ts`` and is nested under the ``GatewayEvent`` union — modelling it
here lets the union reference ONE generated type. The 7-way ``status`` string
keeps its precise literal union (the app-internal ``SubagentStatus`` alias in
``types.ts`` stays importable for consumers that switch on it)."""

from __future__ import annotations

from typing import Any, Literal

from protocol.types import WireModel, wire_optional

_SubagentStatus = Literal[
    "completed", "error", "failed", "interrupted", "queued", "running", "timeout"
]


class SubagentOutputTailItem(WireModel):
    TS_NAME = "SubagentOutputTailItem"

    is_error: bool | None = wire_optional()
    preview: str | None = wire_optional()
    tool: str | None = wire_optional()


class SubagentEventPayload(WireModel):
    TS_NAME = "SubagentEventPayload"

    goal: str
    task_index: int
    api_calls: int | None = wire_optional()
    cost_usd: float | None = wire_optional()
    depth: int | None = wire_optional()
    duration_seconds: float | None = wire_optional()
    files_read: list[str] | None = wire_optional()
    files_written: list[str] | None = wire_optional()
    input_tokens: int | None = wire_optional()
    iteration: int | None = wire_optional()
    model: str | None = wire_optional()
    output_tail: list[SubagentOutputTailItem] | None = wire_optional()
    output_tokens: int | None = wire_optional()
    parent_id: str | None = wire_optional(nullable=True)
    reasoning_tokens: int | None = wire_optional()
    status: _SubagentStatus | None = wire_optional()
    subagent_id: str | None = wire_optional()
    summary: str | None = wire_optional()
    task_count: int | None = wire_optional()
    text: str | None = wire_optional()
    tool_count: int | None = wire_optional()
    tool_name: str | None = wire_optional()
    tool_preview: str | None = wire_optional()
    toolsets: list[str] | None = wire_optional()


# ── agents.list ────────────────────────────────────────────────────────────────


class AgentsListRequest(WireModel):
    TS_NAME = "AgentsListRequest"


class AgentProcess(WireModel):
    TS_NAME = "AgentProcess"

    session_id: str
    command: str
    status: str
    uptime: float


class AgentsListResponse(WireModel):
    TS_NAME = "AgentsListResponse"

    processes: list[AgentProcess]


# ── agents.active.summary ──────────────────────────────────────────────────────


class AgentsActiveSummaryRequest(WireModel):
    TS_NAME = "AgentsActiveSummaryRequest"


class AgentsActiveKinds(WireModel):
    TS_NAME = "AgentsActiveKinds"

    procs: int
    reforecast: int
    quorum: int


class AgentsActiveSummaryResponse(WireModel):
    TS_NAME = "AgentsActiveSummaryResponse"

    count: int
    kinds: AgentsActiveKinds
    headline: str


# ── delegation.status / delegation.pause / subagent.interrupt ──────────────────


class DelegationStatusRequest(WireModel):
    TS_NAME = "DelegationStatusRequest"

    session_id: str | None = wire_optional()


class DelegationActiveEntry(WireModel):
    TS_NAME = "DelegationActiveEntry"

    depth: int | None = wire_optional()
    goal: str | None = wire_optional()
    model: str | None = wire_optional(nullable=True)
    parent_id: str | None = wire_optional(nullable=True)
    started_at: int | None = wire_optional()
    status: str | None = wire_optional()
    subagent_id: str | None = wire_optional()
    tool_count: int | None = wire_optional()


class DelegationStatusResponse(WireModel):
    TS_NAME = "DelegationStatusResponse"

    active: list[DelegationActiveEntry] | None = wire_optional()
    max_concurrent_children: int | None = wire_optional()
    max_spawn_depth: int | None = wire_optional()
    paused: bool | None = wire_optional()


class DelegationPauseRequest(WireModel):
    TS_NAME = "DelegationPauseRequest"

    session_id: str | None = wire_optional()

    paused: bool | None = None


class DelegationPauseResponse(WireModel):
    TS_NAME = "DelegationPauseResponse"

    paused: bool | None = wire_optional()


class SubagentInterruptRequest(WireModel):
    TS_NAME = "SubagentInterruptRequest"

    session_id: str | None = wire_optional()

    subagent_id: str | None = None


class SubagentInterruptResponse(WireModel):
    TS_NAME = "SubagentInterruptResponse"

    found: bool | None = wire_optional()
    subagent_id: str | None = wire_optional()


# ── spawn_tree.list / spawn_tree.load ──────────────────────────────────────────


class SpawnTreeListRequest(WireModel):
    TS_NAME = "SpawnTreeListRequest"


class SpawnTreeListEntry(WireModel):
    TS_NAME = "SpawnTreeListEntry"

    count: int
    path: str
    finished_at: int | None = wire_optional()
    label: str | None = wire_optional()
    session_id: str | None = wire_optional()
    started_at: int | None = wire_optional(nullable=True)


class SpawnTreeListResponse(WireModel):
    TS_NAME = "SpawnTreeListResponse"

    entries: list[SpawnTreeListEntry] | None = wire_optional()


class SpawnTreeLoadRequest(WireModel):
    TS_NAME = "SpawnTreeLoadRequest"

    path: str | None = None


class SpawnTreeLoadResponse(WireModel):
    TS_NAME = "SpawnTreeLoadResponse"

    finished_at: int | None = wire_optional()
    label: str | None = wire_optional()
    session_id: str | None = wire_optional()
    started_at: int | None = wire_optional(nullable=True)
    subagents: list[Any] | None = wire_optional()


__all__ = [
    "SubagentOutputTailItem",
    "SubagentEventPayload",
    "AgentsListRequest",
    "AgentProcess",
    "AgentsListResponse",
    "AgentsActiveSummaryRequest",
    "AgentsActiveKinds",
    "AgentsActiveSummaryResponse",
    "DelegationStatusRequest",
    "DelegationActiveEntry",
    "DelegationStatusResponse",
    "DelegationPauseRequest",
    "DelegationPauseResponse",
    "SubagentInterruptRequest",
    "SubagentInterruptResponse",
    "SpawnTreeListRequest",
    "SpawnTreeListEntry",
    "SpawnTreeListResponse",
    "SpawnTreeLoadRequest",
    "SpawnTreeLoadResponse",
]
