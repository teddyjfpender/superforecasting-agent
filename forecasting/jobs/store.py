"""JSON-file-per-job store for the detached-job runtime (Arc B).

One file ``{home}/jobs/{job_id}.json`` per job, atomic writes (temp file +
``os.replace``) — the proven ``quorum_jobs``/``reforecast_jobs`` pattern lifted
into a reusable, typed store. A sibling ``{job_id}.stop`` file is the durable
cancel signal (a cheap ``stat`` poll; cross-process, unlike an in-memory Event).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from hermes_constants import get_hermes_home

from forecasting.jobs.model import JobRecord, _now_iso

_ACTIVE_STATUSES = ("queued", "running")


class JobStore:
    """Read/write/list JobRecords under ``{home}/jobs/``.

    ``home`` is resolved LAZILY (per call) from :func:`get_hermes_home` when not
    pinned, so a test's per-test ``HERMES_HOME`` and a subprocess's propagated
    home are both honoured — matching the legacy job stores.
    """

    def __init__(self, home: Path | None = None) -> None:
        self._home = Path(home) if home is not None else None

    # ── paths ────────────────────────────────────────────────────────────────
    def jobs_dir(self) -> Path:
        base = self._home if self._home is not None else get_hermes_home()
        path = base / "jobs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def new_id() -> str:
        return f"job_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _validate_id(job_id: str) -> str:
        if (
            not job_id
            or "/" in job_id
            or "\\" in job_id
            or ".." in job_id
            or job_id.startswith(".")
        ):
            raise ValueError(f"invalid job id: {job_id!r}")
        return job_id

    def path(self, job_id: str) -> Path:
        return self.jobs_dir() / f"{self._validate_id(job_id)}.json"

    def stop_path(self, job_id: str) -> Path:
        return self.jobs_dir() / f"{self._validate_id(job_id)}.stop"

    # ── lifecycle ────────────────────────────────────────────────────────────
    def exists(self, job_id: str) -> bool:
        try:
            return self.path(job_id).exists()
        except ValueError:
            return False

    def write(self, record: JobRecord) -> None:
        """Atomically persist a record (temp file + ``os.replace``)."""

        record.updated_at = _now_iso()
        path = self.path(record.job_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(record.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        os.replace(tmp, path)

    def read(self, job_id: str) -> JobRecord:
        path = self.path(job_id)
        if not path.exists():
            raise FileNotFoundError(f"no job '{job_id}' (looked in {self.jobs_dir()})")
        return JobRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self, *, limit: int = 100) -> list[JobRecord]:
        rows: list[JobRecord] = []
        for path in self.jobs_dir().glob("job_*.json"):
            try:
                rows.append(JobRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        rows.sort(key=lambda r: r.created_at or "", reverse=True)
        return rows[:limit]

    def active(self, *, types: list[str] | None = None, limit: int = 100) -> list[JobRecord]:
        """The still-in-flight jobs (``queued`` | ``running``), newest first,
        optionally filtered to a set of ``types``."""

        wanted = set(types) if types else None
        out: list[JobRecord] = []
        for record in self.list(limit=limit):
            if record.status not in _ACTIVE_STATUSES:
                continue
            if wanted is not None and record.type not in wanted:
                continue
            out.append(record)
        return out

    # ── cancellation ─────────────────────────────────────────────────────────
    def request_cancel(self, job_id: str) -> bool:
        """Signal a cooperative cancel: touch the durable stop file AND stamp the
        record's ``cancel_requested`` (for observability via ``jobs.status``).
        Returns False when the job does not exist."""

        if not self.exists(job_id):
            return False
        self.stop_path(job_id).write_text("1", encoding="utf-8")
        try:
            record = self.read(job_id)
        except FileNotFoundError:
            return False
        record.cancel_requested = True
        self.write(record)
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        """True if EITHER the stop file exists (the cheap poll) OR the record's
        ``cancel_requested`` flag is set (the flag-only path)."""

        try:
            if self.stop_path(job_id).exists():
                return True
        except ValueError:
            return False
        try:
            return self.read(job_id).cancel_requested
        except FileNotFoundError:
            return False

    def clear_stop(self, job_id: str) -> None:
        try:
            self.stop_path(job_id).unlink()
        except (FileNotFoundError, ValueError):
            pass


__all__ = ["JobStore"]
