"""The one durable job record for the detached-job runtime (Arc B).

Every background capability — warning-automode today, reforecast/task/quorum as
they migrate — persists as a :class:`JobRecord` JSON file under ``{home}/jobs/``.
One shape, one store, one runtime. ``None`` is never ``0`` (the accounting fields
stay ``None`` until a phase actually sets them).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any

# The lifecycle state machine. ``cancelled`` is a graceful terminal (the run
# finished after a cooperative cancel — its partial work is durable); ``error``
# is a crash.
STATUSES = ("queued", "running", "done", "error", "cancelled")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobRecord:
    """One background job. ``job_id`` is prefixed ``job_``; ``type`` names the
    registered :class:`~forecasting.jobs.types.JobType` that knows how to run it.

    Accounting (``done_count``/``total``/``current``) is updated in-memory on
    every progress call and persisted on the coalesced ones — the final value
    always lands because the terminal event always passes the coalescer.
    """

    job_id: str
    type: str
    status: str = "queued"
    spec: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str | None = None
    done_count: int = 0
    total: int | None = None
    current: str | None = None
    progress: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    cancel_requested: bool = False
    annotations: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "type": self.type,
            "status": self.status,
            "spec": self.spec,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "done_count": self.done_count,
            "total": self.total,
            "current": self.current,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
            "annotations": self.annotations,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobRecord":
        """Rebuild from a persisted dict, ignoring unknown keys (forward-compat +
        the read-shim seam for legacy ``rf_*``/``wj_*`` records)."""

        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in (data or {}).items() if k in known}
        return cls(**filtered)


__all__ = ["JobRecord", "STATUSES"]
