"""The runtime: resolve a job's registered TYPE, execute it with a JobContext,
and write the terminal ``done``/``cancelled``/``error`` state.

``run`` is transport-agnostic. In the gateway it runs on a daemon thread with the
``on_progress``/``on_complete``/``on_error`` hooks wired to event emit; as a
detached process (``python -m forecasting.jobs run <id>``) the hooks are absent
and the persisted record IS the channel a poller reads.
"""

from __future__ import annotations

from typing import Any, Callable

from forecasting.jobs.context import JobContext
from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore
from forecasting.jobs.types import resolve as resolve_type


def run(
    job_id: str,
    *,
    store: JobStore | None = None,
    sink: Callable[[dict[str, Any]], None] | None = None,
    extra_should_cancel: Callable[[], bool] | None = None,
    on_complete: Callable[[dict[str, Any]], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> JobRecord:
    store = store or JobStore()
    with store.claim(job_id) as record:
        if record is None:
            return store.read(job_id)
        return _run_claimed(
            record,
            store,
            sink=sink,
            extra_should_cancel=extra_should_cancel,
            on_complete=on_complete,
            on_error=on_error,
        )


def _run_claimed(
    record: JobRecord,
    store: JobStore,
    *,
    sink: Callable[[dict[str, Any]], None] | None,
    extra_should_cancel: Callable[[], bool] | None,
    on_complete: Callable[[dict[str, Any]], None] | None,
    on_error: Callable[[str], None] | None,
) -> JobRecord:

    try:
        job_type = resolve_type(record.type)
    except KeyError as exc:
        record.status = "error"
        record.error = f"KeyError: {exc}"
        store.write(record)
        if on_error is not None:
            on_error(record.error)
        return record

    ctx = JobContext(
        record,
        store,
        sink=sink,
        extra_should_cancel=extra_should_cancel,
        min_interval_s=job_type.min_interval_s,
    )

    from forecasting.jobs.policy import ApprovalRequired, PolicyRefused

    try:
        raw = job_type.execute(record.spec or {}, ctx)
        ctx.flush()
        result: dict[str, Any]
        if isinstance(raw, dict):
            result = raw
        elif raw is None:
            result = {}
        else:
            result = {"value": raw}
        record.result = result
        # A cooperative cancel is a GRACEFUL terminal (partial work is durable),
        # not a crash — the summary carries ``cancelled=True``.
        record.status = "cancelled" if result.get("cancelled") else "done"
        store.write(record)
        if on_complete is not None:
            on_complete(result)
    except ApprovalRequired:
        # A `policy.<mode>.<class> = ask` cell PARKED the job before it spent. This is
        # NOT a crash and NOT a completion — leave it at ``awaiting_approval`` (already
        # stamped by ctx.authorize, with the surfacing alert raised) for the operator
        # to approve via ``policy.approve_job``. No on_complete / on_error fires.
        ctx.flush()
        record.status = "awaiting_approval"
        store.write(record)
    except PolicyRefused as exc:
        # A `never` cell refused. Terminal ``error`` carrying the TEACHING message
        # verbatim (it names the config key to loosen) — no ``PolicyRefused:`` prefix.
        ctx.flush()
        record.status = "error"
        record.error = str(exc)
        store.write(record)
        if on_error is not None:
            on_error(record.error)
    except Exception as exc:  # noqa: BLE001 — a background worker records, never crashes
        ctx.flush()
        record.status = "error"
        record.error = f"{type(exc).__name__}: {exc}"
        store.write(record)
        if on_error is not None:
            on_error(record.error)
    finally:
        store.clear_stop(record.job_id)

    return record


__all__ = ["run"]
