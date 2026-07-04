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
    record = store.read(job_id)

    try:
        job_type = resolve_type(record.type)
    except KeyError as exc:
        record.status = "error"
        record.error = f"KeyError: {exc}"
        store.write(record)
        if on_error is not None:
            on_error(record.error)
        return record

    record.status = "running"
    record.error = None
    store.write(record)

    ctx = JobContext(
        record,
        store,
        sink=sink,
        extra_should_cancel=extra_should_cancel,
        min_interval_s=job_type.min_interval_s,
    )

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
    except Exception as exc:  # noqa: BLE001 — a background worker records, never crashes
        ctx.flush()
        record.status = "error"
        record.error = f"{type(exc).__name__}: {exc}"
        store.write(record)
        if on_error is not None:
            on_error(record.error)
    finally:
        store.clear_stop(job_id)

    return record


__all__ = ["run"]
