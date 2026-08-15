"""The BACKUP job type: a durable, online SQLite backup + integrity check of the
forecast ledger on the one detached-job runtime (Arc B).

The forecast ledger is the ENTIRE asset — months of irreplaceable judgment — and
had no backup automation. This type closes that gap the runtime-payoff way: ONE
type file, pre-integrated with progress, persistence, cancellation, and re-attach.

:func:`execute` runs :meth:`forecasting.ledger.ForecastLedger.backup` (SQLite's
ONLINE backup API — page-level, safe under the concurrent gateway/cron writers,
never an OS copy of a live WAL db) then :meth:`~ForecastLedger.integrity_check`,
and carries ``{path, bytes, integrity: ok|violations, counts}`` on the result.
Retention (keep-newest-14 + one-per-week-for-8-weeks) is applied by the backup
call itself. Progress is minimal — a backup is seconds, not minutes: two phases
(``backup`` → ``integrity``) plus the terminal ``done``.

New jobs persist as :class:`~forecasting.jobs.model.JobRecord` files under
``{home}/jobs/`` via the shared :class:`~forecasting.jobs.store.JobStore`, so
``forecast backup list``, the desk agents chip, and the doctor all read the SAME
record. There is NO legacy alias family (a net-new capability) and NO LLM spend.
"""

from __future__ import annotations

from typing import Any

from forecasting.jobs.detached import spawn_detached_job
from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore
from forecasting.jobs.types import JobType, register


def _coerce_optional_int(value: Any, field: str) -> int | None:
    """A retention override is either absent (use the ledger default) or a
    non-negative int. Anything else is a spec error the runtime records."""

    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an integer, got {value!r}") from None
    if parsed < 0:
        raise ValueError(f"{field} must be >= 0, got {parsed}")
    return parsed


def validate_spec(spec: dict[str, Any]) -> None:
    """Validate the (all-optional) backup spec: ``db``, ``dest_dir``, and the two
    retention overrides ``keep_recent`` / ``weekly_weeks``."""

    _coerce_optional_int(spec.get("keep_recent"), "keep_recent")
    _coerce_optional_int(spec.get("weekly_weeks"), "weekly_weeks")


def execute(spec: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Back up the ledger, then integrity-check it; carry the honest verdict.

    A bad ``db`` (or an unwritable ``dest_dir``) raises out to the runtime, which
    records a whole-job ``error`` — matching every other type's contract. Cancel is
    honoured before the (fast) backup starts; once the copy is in flight it runs to
    completion, since a half-written prune is worse than a full backup."""

    from forecasting.ledger import ForecastLedger

    keep_recent = _coerce_optional_int(spec.get("keep_recent"), "keep_recent")
    weekly_weeks = _coerce_optional_int(spec.get("weekly_weeks"), "weekly_weeks")
    dest_dir = spec.get("dest_dir") or None

    ledger = ForecastLedger(spec.get("db"))  # a bad db → runtime marks the job error

    if ctx.should_cancel():
        return {"cancelled": True, "path": None, "integrity": None}

    ctx.progress(phase="backup", done=0, total=2)
    backup = ledger.backup(
        dest_dir,
        keep_recent=keep_recent,
        weekly_weeks=weekly_weeks,
    )
    # Durable metadata for jobs.status / the desk, independent of the coalesced
    # progress stream.
    ctx.annotate("backup", backup)

    ctx.progress(phase="integrity", done=1, total=2)
    integ = ledger.integrity_check()

    result = {
        "path": backup.get("path"),
        "bytes": backup.get("bytes"),
        "created_at": backup.get("created_at"),
        "integrity": "ok" if integ.get("ok") else "violations",
        "violations": integ.get("violations") or [],
        "counts": integ.get("counts") or {},
        "retention": backup.get("retention") or {},
        "cancelled": False,
    }
    ctx.progress(phase="done", done=2, total=2)
    return result


# ── enqueue + thin read helpers (the CLI / cron surface) ──────────────────────


def start_job(spec: dict[str, Any], *, wait: bool = True) -> str:
    """Create a queued ``backup`` JobRecord and execute it (inline when ``wait``,
    else as a detached child process).

    ``spec`` keys (all optional): ``db``, ``dest_dir``, ``keep_recent``,
    ``weekly_weeks``. Defaults to ``wait=True`` — a backup is fast and the CLI/cron
    caller wants the ``{path, integrity, counts}`` result synchronously (unlike the
    long-running quorum/reforecast types, which detach)."""

    validate_spec(spec)
    store = JobStore()
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type="backup", spec=dict(spec)))

    if wait:
        from forecasting.jobs import runtime

        runtime.run(job_id, store=store)
        return job_id

    spawn_detached_job(job_id)
    return job_id


def read_job(job_id: str) -> dict[str, Any]:
    """The persisted backup record as a dict (raises ``FileNotFoundError`` when the
    id is unknown)."""

    return JobStore().read(job_id, include_legacy=False).to_dict()


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    """The most recent ``backup`` job records, newest first."""

    rows: list[dict[str, Any]] = []
    for record in JobStore().list(limit=max(limit * 4, 80), include_legacy=False):
        if record.type == "backup":
            rows.append(record.to_dict())
    return rows[:limit]


def run_backup_cron(db_path: str | None = None) -> int:
    """The daily-cron entry point: run a backup job to completion, print a one-line
    summary, and return 0 when the backup committed with clean integrity, else 1.

    A nonzero exit lets the cron surface (and its ``last_status``/``last_error``)
    flag a failed or corrupt backup for the doctor's cron-health probe."""

    job_id = start_job({"db": db_path}, wait=True)
    record = JobStore().read(job_id, include_legacy=False)
    result = record.result or {}
    if record.status != "done":
        print(f"forecast backup FAILED: {record.error or 'unknown error'}")
        return 1
    integrity = result.get("integrity")
    counts = result.get("counts") or {}
    counts_text = " ".join(f"{k}={v}" for k, v in counts.items())
    print(
        f"forecast backup {result.get('path')} "
        f"({result.get('bytes')} bytes) integrity={integrity} {counts_text}".rstrip()
    )
    return 0 if integrity == "ok" else 1


def main(argv: list[str] | None = None) -> int:
    """CLI/cron shim: ``python -m forecasting.jobs.types.backup [--db PATH]``."""

    import argparse

    parser = argparse.ArgumentParser(
        description="Back up the forecast ledger (online snapshot + integrity check)."
    )
    parser.add_argument("--db")
    args = parser.parse_args(argv)
    return run_backup_cron(db_path=args.db)


BACKUP = JobType(
    name="backup",
    execute=execute,
    # Two phase-change events + the terminal — no throttling needed (a backup is
    # seconds), and every phase change passes the coalescer regardless.
    min_interval_s=0.0,
    # A net-new durability capability — no legacy RPC family, no LLM spend.
    alias_namespace=None,
    spend_class="free",
    validate_spec=validate_spec,
)

register(BACKUP)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BACKUP",
    "execute",
    "validate_spec",
    "start_job",
    "read_job",
    "list_jobs",
    "run_backup_cron",
    "main",
]
