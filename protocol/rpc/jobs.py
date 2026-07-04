"""Wire models for the ``jobs.*`` detached-job-runtime RPCs (Arc B on Arc A).

Mirrors ``tui_gateway/jobs_rpc.py``:
* ``jobs.start`` ``{type, spec?, session_id?}`` → ``{job_id, type}``
* ``jobs.status`` ``{job_id}`` → ``{found, job?}`` (``job`` is the record shape)
* ``jobs.active`` ``{types?}`` → ``{jobs, count}``
* ``jobs.cancel`` ``{job_id}`` → ``{job_id, found, cancelled}``

The record ``job`` is nested (never flattened) so the response is a single clean
model; ``None`` accounting fields stay ``null`` on the wire (the law: None ≠ 0).
"""

from __future__ import annotations

from typing import Any

from protocol.types import WireModel


class JobRecordDTO(WireModel):
    TS_NAME = "JobRecordDTO"

    job_id: str
    type: str
    status: str
    spec: dict[str, Any]
    created_at: str
    updated_at: str | None
    done_count: int
    total: int | None
    current: str | None
    progress: list[dict[str, Any]]
    result: dict[str, Any] | None
    error: str | None
    cancel_requested: bool
    annotations: dict[str, Any]


# ── jobs.start ────────────────────────────────────────────────────────────────


class JobsStartRequest(WireModel):
    TS_NAME = "JobsStartRequest"

    type: str
    spec: dict[str, Any] | None = None
    session_id: str | None = None


class JobsStartResponse(WireModel):
    TS_NAME = "JobsStartResponse"

    job_id: str
    type: str


# ── jobs.status ───────────────────────────────────────────────────────────────


class JobsStatusRequest(WireModel):
    TS_NAME = "JobsStatusRequest"

    job_id: str


class JobsStatusResponse(WireModel):
    TS_NAME = "JobsStatusResponse"

    found: bool
    job: JobRecordDTO | None


# ── jobs.active ───────────────────────────────────────────────────────────────


class JobsActiveRequest(WireModel):
    TS_NAME = "JobsActiveRequest"

    types: list[str] | None = None


class JobsActiveResponse(WireModel):
    TS_NAME = "JobsActiveResponse"

    jobs: list[JobRecordDTO]
    count: int


# ── jobs.cancel ───────────────────────────────────────────────────────────────


class JobsCancelRequest(WireModel):
    TS_NAME = "JobsCancelRequest"

    job_id: str


class JobsCancelResponse(WireModel):
    TS_NAME = "JobsCancelResponse"

    job_id: str
    found: bool
    cancelled: bool


__all__ = [
    "JobRecordDTO",
    "JobsStartRequest",
    "JobsStartResponse",
    "JobsStatusRequest",
    "JobsStatusResponse",
    "JobsActiveRequest",
    "JobsActiveResponse",
    "JobsCancelRequest",
    "JobsCancelResponse",
]
