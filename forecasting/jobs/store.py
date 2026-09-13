"""JSON-file-per-job store for the detached-job runtime (Arc B).

One file ``{home}/jobs/{job_id}.json`` per job, atomic writes (temp file +
``os.replace``) — the proven ``quorum_jobs``/``reforecast_jobs`` pattern lifted
into a reusable, typed store. A sibling ``{job_id}.stop`` file is the durable
cancel signal (a cheap ``stat`` poll; cross-process, unlike an in-memory Event).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from superforecasting_agent.constants import get_agent_home

from forecasting.jobs.model import JobRecord, _now_iso

_ACTIVE_STATUSES = ("queued", "running")

# A ``queued``/``running`` record only counts as LIVE while its heartbeat is
# fresh. TWO real records read as forever-running otherwise, keeping the Home
# "✦ N agents running" chip lit indefinitely:
#   1. a worker that CRASHED/was killed (OOM, SIGKILL, a segfault in the detached
#      ``python -m superforecasting_agent.worker run`` child) never reaches the runtime's
#      try/except, so it never writes a terminal ``done``/``error`` status; the
#      record is stuck at ``running`` on disk.
#   2. a pre-migration legacy ``rf_``/``qr_`` file with NO ``status`` key — the
#      read-shim rebuilds it and :class:`JobRecord` DEFAULTS ``status`` to
#      ``queued`` (an active status), so a finished/abandoned legacy run scans as
#      in-flight.
# The runtime stamps ``updated_at`` on every progress write (reforecast per
# stage/question, quorum per emit), so a live job's heartbeat advances
# continuously; a gap past this cutoff means the worker is gone. Generous enough
# to never stale a legitimately slow single stage, far below a session-long stuck
# chip. Mirrors the process registry's FINISHED_TTL (30 min).
ACTIVE_HEARTBEAT_MAX_STALE_S = 1800


def _heartbeat_epoch(record: JobRecord) -> float | None:
    """Epoch seconds of a record's freshest liveness stamp (``updated_at``, else
    the enqueue ``created_at``), or ``None`` when neither is a parseable ISO time —
    a record with no usable heartbeat cannot be PROVEN live, so callers treat
    ``None`` as stale."""

    for stamp in (record.updated_at, record.created_at):
        if not stamp:
            continue
        try:
            return datetime.fromisoformat(str(stamp)).timestamp()
        except (ValueError, TypeError):
            continue
    return None

# Legacy on-disk job stores that predate the unified runtime (Arc B4). A record
# that was in flight across the migration still lives here; the GENERIC jobs.*
# path answers for it by scanning these dirs and shimming each file into a
# JobRecord — so the per-type read-shims (reforecast.list_jobs / quorum.list_jobs
# each globbing their own dir) collapse onto this ONE store-level path.
#   (dir, filename prefix, default type)
# The reforecast dir carries BOTH reforecast and task runs; ``_legacy_type``
# disambiguates on ``spec.mode`` before falling back to the default.
_LEGACY_SOURCES = (
    ("reforecast_runs", "rf_", "reforecast"),
    ("quorum_runs", "qr_", "quorum"),
)


def _legacy_type(data: dict, default_type: str) -> str:
    """Resolve a legacy record's TYPE: an explicit ``type``, else ``mode`` /
    ``spec.mode`` (a task run), else the dir's default."""

    if data.get("type"):
        return str(data["type"])
    mode = data.get("mode") or (data.get("spec") or {}).get("mode")
    if isinstance(mode, str) and mode.strip():
        return mode.strip()
    return default_type


class JobStore:
    """Read/write/list JobRecords under ``{home}/jobs/``.

    ``home`` is resolved LAZILY (per call) from :func:`get_agent_home` when not
    pinned, so a test's per-test ``HERMES_HOME`` and a subprocess's propagated
    home are both honoured — matching the legacy job stores.
    """

    def __init__(self, home: Path | None = None) -> None:
        self._home = Path(home) if home is not None else None

    # ── paths ────────────────────────────────────────────────────────────────
    def _base(self) -> Path:
        return self._home if self._home is not None else get_agent_home()

    def jobs_dir(self) -> Path:
        path = self._base() / "jobs"
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

    def lock_path(self, job_id: str) -> Path:
        return self.jobs_dir() / f"{self._validate_id(job_id)}.lock"

    # ── lifecycle ────────────────────────────────────────────────────────────
    def exists(self, job_id: str) -> bool:
        try:
            return self.path(job_id).exists()
        except ValueError:
            return False

    def write(self, record: JobRecord) -> None:
        """Atomically persist a record through a writer-unique temporary file."""

        record.updated_at = _now_iso()
        path = self.path(record.job_id)
        payload = json.dumps(record.to_dict(), indent=2, sort_keys=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(payload)
            os.replace(tmp, path)
        finally:
            if fd >= 0:
                os.close(fd)
            tmp.unlink(missing_ok=True)

    @contextmanager
    def claim(self, job_id: str) -> Iterator[JobRecord | None]:
        """Try to claim one queued or crash-stranded running job.

        The non-blocking kernel lock is held for the whole execution. A second
        runner therefore gets ``None`` without executing side effects, while an
        abrupt process exit releases the lock so a later runner can reclaim the
        persisted ``running`` record.
        """

        lock_path = self.lock_path(job_id)
        handle = lock_path.open("a+b")
        acquired = False
        try:
            try:
                if os.name == "nt":
                    handle.seek(0, os.SEEK_END)
                    if handle.tell() == 0:
                        handle.write(b"\0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                yield None
                return
            except OSError:
                if os.name != "nt":
                    raise
                yield None
                return

            record = self.read(job_id)
            if record.status not in _ACTIVE_STATUSES:
                yield None
                return
            record.status = "running"
            record.error = None
            self.write(record)
            yield record
        finally:
            if acquired:
                try:
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()

    def read(self, job_id: str, *, include_legacy: bool = True) -> JobRecord:
        path = self.path(job_id)
        if path.exists():
            return JobRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if include_legacy:
            legacy = self._read_legacy(job_id)
            if legacy is not None:
                return legacy
        raise FileNotFoundError(f"no job '{job_id}' (looked in {self.jobs_dir()})")

    def list(self, *, limit: int = 100, include_legacy: bool = True) -> list[JobRecord]:
        rows: list[JobRecord] = []
        seen: set[str] = set()
        for path in self.jobs_dir().glob("job_*.json"):
            try:
                record = JobRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            rows.append(record)
            seen.add(record.job_id)
        if include_legacy:
            rows.extend(self._legacy_records(seen))
        rows.sort(key=lambda r: r.created_at or "", reverse=True)
        return rows[:limit]

    def active(
        self,
        *,
        types: list[str] | None = None,
        limit: int = 100,
        include_legacy: bool = True,
        max_stale_s: float | None = ACTIVE_HEARTBEAT_MAX_STALE_S,
        now: float | None = None,
    ) -> list[JobRecord]:
        """The still-in-flight jobs (``queued`` | ``running``), newest first,
        optionally filtered to a set of ``types``. Legacy ``rf_``/``qr_`` records
        that were in flight across the migration are included by default.

        A record only counts as active while its heartbeat is FRESH: a crashed or
        killed worker never writes a terminal status (its record is stuck at
        ``running``), and a status-less legacy file defaults to ``queued`` — both
        would otherwise read as forever-live. A record whose heartbeat
        (``updated_at``, else ``created_at``) is older than ``max_stale_s``, or that
        carries no parseable heartbeat at all, is treated as dead and excluded. Pass
        ``max_stale_s=None`` to disable the freshness gate (return every
        queued/running record regardless of age)."""

        wanted = set(types) if types else None
        cutoff = (
            None
            if max_stale_s is None
            else (time.time() if now is None else now) - max_stale_s
        )
        out: list[JobRecord] = []
        for record in self.list(limit=limit, include_legacy=include_legacy):
            if record.status not in _ACTIVE_STATUSES:
                continue
            if cutoff is not None:
                heartbeat = _heartbeat_epoch(record)
                # No parseable heartbeat, or one older than the cutoff → the worker
                # is gone (crash/kill) or the record is a stale legacy shim: a
                # finished job that never wrote a terminal status is NOT live.
                if heartbeat is None or heartbeat < cutoff:
                    continue
            if wanted is not None and record.type not in wanted:
                continue
            out.append(record)
        return out

    # ── legacy read-shim (rf_/qr_ files that predate the runtime) ─────────────
    def _legacy_records(self, seen: set[str]) -> list[JobRecord]:
        """Every legacy ``rf_``/``qr_`` file across the pre-migration dirs, shimmed
        into JobRecords. ``seen`` de-dupes against the new ``job_`` store (a run
        that already migrated wins) and across the scan itself."""

        base = self._base()
        out: list[JobRecord] = []
        for dirname, prefix, default_type in _LEGACY_SOURCES:
            directory = base / dirname
            if not directory.is_dir():
                continue
            for path in directory.glob(f"{prefix}*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue
                rid = data.get("run_id") or data.get("job_id")
                if not rid or rid in seen:
                    continue
                try:
                    record = JobRecord.from_dict({**data, "type": _legacy_type(data, default_type)})
                except (TypeError, ValueError):
                    continue
                out.append(record)
                seen.add(rid)
        return out

    def _read_legacy(self, job_id: str) -> JobRecord | None:
        """The one legacy file named ``{job_id}.json`` across the pre-migration dirs
        (the id prefix effectively pins the dir), shimmed into a JobRecord — or None
        when no legacy file has it."""

        try:
            self._validate_id(job_id)
        except ValueError:
            return None
        base = self._base()
        for dirname, _prefix, default_type in _LEGACY_SOURCES:
            path = base / dirname / f"{job_id}.json"
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            if not isinstance(data, dict):
                return None
            try:
                return JobRecord.from_dict({**data, "type": _legacy_type(data, default_type)})
            except (TypeError, ValueError):
                return None
        return None

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
