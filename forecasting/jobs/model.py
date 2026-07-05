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
# is a crash. ``awaiting_approval`` is a PARKED state (Arc-9 approval matrix): the
# job stopped BEFORE spending because a ``policy.<mode>.<class>`` cell resolved to
# ``ask``, and it resumes once an operator approves. It is deliberately neither
# ACTIVE (it must not light the "N agents running" chip — nothing is running) nor
# TERMINAL (the work is not finished) — the store's ``_ACTIVE_STATUSES`` excludes
# it, and the desk surfaces it via the approval alert it raised, not the job list.
STATUSES = ("queued", "running", "done", "error", "cancelled", "awaiting_approval")


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
    # ── Arc-9 approval/spend policy audit trail ──────────────────────────────
    # ``resolved_policy`` — the full matrix that governed this run (run_mode + the
    # per-class decisions), stamped once at the first ``authorize`` call.
    # ``policy_decisions`` — one entry per ``authorize`` call (class/detail/decision/
    # bounded/outcome), so a status poll can audit exactly what was allowed, parked,
    # or refused. ``policy_grants`` — action classes an operator APPROVED for a resumed
    # run, so a re-run's ``authorize`` proceeds instead of re-parking. All default
    # empty/None → a run that never authorizes (backup, free-tier warnings) is
    # byte-identical to before.
    resolved_policy: dict[str, Any] | None = None
    policy_decisions: list[dict[str, Any]] = field(default_factory=list)
    policy_grants: list[str] = field(default_factory=list)

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
            "resolved_policy": self.resolved_policy,
            "policy_decisions": self.policy_decisions,
            "policy_grants": self.policy_grants,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobRecord":
        """Rebuild from a persisted dict, ignoring unknown keys (forward-compat +
        the read-shim seam for legacy ``rf_*``/``qr_*`` records).

        The LEGACY read-shim (Arc B4): a pre-migration reforecast/quorum record
        keyed its id as ``run_id`` and (for a reforecast/task run) its kind as
        ``mode``. Map those onto the canonical ``job_id`` / ``type`` fields when the
        canonical keys are absent, so a single ``from_dict`` shims BOTH shapes — the
        per-type read-shims collapse onto this one path. ``type`` may also live in
        the legacy ``spec.mode`` (the reforecast dir carries both reforecast and task
        runs); that final fallback is resolved here too so a raw legacy dict rebuilds
        without the caller pre-injecting a type."""

        known = {f.name for f in fields(cls)}
        data = data or {}
        filtered = {k: v for k, v in data.items() if k in known}
        if not filtered.get("job_id") and data.get("run_id"):
            filtered["job_id"] = data["run_id"]
        if not filtered.get("type"):
            mode = data.get("mode") or (data.get("spec") or {}).get("mode")
            if isinstance(mode, str) and mode.strip():
                filtered["type"] = mode.strip()
        return cls(**filtered)


__all__ = ["JobRecord", "STATUSES"]
