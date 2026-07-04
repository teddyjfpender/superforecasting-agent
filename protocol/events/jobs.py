"""Wire models for the sessionless ``jobs.*`` events (Arc B on Arc A).

Emitted by ``tui_gateway/jobs_rpc.py`` for every job on the detached-job runtime:
a coalesced ``jobs.progress`` per phase, then exactly one terminal
``jobs.complete`` (graceful, incl. a cooperative cancel) or ``jobs.error`` (crash).
The inner ``progress`` / ``result`` dicts are the job type's own payloads.
"""

from __future__ import annotations

from typing import Any

from protocol.types import WireModel


class JobProgress(WireModel):
    TS_NAME = "JobProgressPayload"

    job_id: str
    type: str
    # The job type's raw progress dict (e.g. run_warning_resolution's
    # {phase, done, total, remaining, alert_id, reason, status}).
    progress: dict[str, Any]


class JobComplete(WireModel):
    TS_NAME = "JobCompletePayload"

    job_id: str
    type: str
    # The job type's terminal summary (a cooperative cancel carries
    # ``cancelled: true`` here — it is still a completion, not an error).
    result: dict[str, Any]


class JobError(WireModel):
    TS_NAME = "JobErrorPayload"

    job_id: str
    type: str
    message: str


__all__ = ["JobProgress", "JobComplete", "JobError"]
