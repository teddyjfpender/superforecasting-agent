"""Gateway RPCs for the detached-job runtime (Arc B).

``server.py`` only imports :func:`register` and calls it. Every handler is thin:
it drives :mod:`forecasting.jobs` (store + runtime) and turns the runtime's
progress / terminal callbacks into ``jobs.progress`` / ``jobs.complete`` /
``jobs.error`` events.

Methods
-------
* ``jobs.start`` ``{type, spec?, session_id?}`` → ``{job_id, type}``
* ``jobs.status`` ``{job_id}`` → ``{found, job?}``
* ``jobs.active`` ``{types?}`` → ``{jobs, count}``
* ``jobs.cancel`` ``{job_id}`` → ``{job_id, found, cancelled}``

Backward compatibility: ``forecast.warnings.automode.run`` / ``.cancel`` are
ALIASES over the runtime that return the exact current response shapes and emit
the exact current ``forecast.warnings.automode.*`` event names ALONGSIDE the new
``jobs.*`` events — the alerts view works unchanged. Any job whose TYPE declares
an ``alias_namespace`` emits that legacy event family too, regardless of which
entry point started it.

``forecast.reforecast.start`` / ``.status`` / ``.active`` and ``forecast.desk.task``
are the same kind of alias over the REFORECAST/TASK types (Arc B2): they enqueue a
detached job on the shared JobStore + runtime and return the byte-compatible
response shapes the desk already speaks. NEW runs carry ``job_`` ids; a legacy
``rf_`` run still on disk is answered by the type module's read-shim, so the
``run_id`` in a response is simply whatever id the record has.
"""

from __future__ import annotations

import contextvars
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# job_id -> stop Event for the in-process fast-cancel path (the durable stop file
# is the cross-process path; both are polled by JobContext.should_cancel).
_running: dict[str, threading.Event] = {}
_running_lock = threading.Lock()


def _get_store():
    from forecasting.jobs.store import JobStore

    return JobStore()


def active_jobs(types: list[str] | None = None) -> list[dict[str, Any]]:
    """The in-flight jobs as plain dicts — the seam a desk/agents chip reads."""
    return [r.to_dict() for r in _get_store().active(types=types)]


def register(server) -> None:
    """Register every ``jobs.*`` handler + the warnings aliases into the gateway
    dispatch table."""

    def _spawn(job_type_name: str, spec: dict[str, Any], sid: str) -> str:
        """Create a JobRecord + run it on a daemon thread, streaming events.

        The request's contextvars are snapshotted into the worker thread (home
        override, tenant runtime, session) — a verbatim lift of the old gateway
        ``_run`` wrapper's ``contextvars.copy_context()`` semantics.
        """
        from forecasting.jobs import runtime
        from forecasting.jobs.model import JobRecord
        from forecasting.jobs.types import resolve as resolve_type

        job_type = resolve_type(job_type_name)  # raises KeyError on unknown type
        store = _get_store()
        job_id = store.new_id()
        store.write(JobRecord(job_id=job_id, type=job_type_name, spec=dict(spec or {})))

        stop = threading.Event()
        with _running_lock:
            _running[job_id] = stop

        ns = job_type.alias_namespace

        def _emit_progress(event: dict[str, Any]) -> None:
            server._emit(
                "jobs.progress",
                sid,
                {"job_id": job_id, "type": job_type_name, "progress": event},
            )
            if ns:
                server._emit(f"{ns}.progress", sid, {"job_id": job_id, **event})

        def _emit_complete(result: dict[str, Any]) -> None:
            server._emit(
                "jobs.complete",
                sid,
                {"job_id": job_id, "type": job_type_name, "result": result},
            )
            if ns:
                payload = result if isinstance(result, dict) else {}
                server._emit(f"{ns}.complete", sid, {"job_id": job_id, **payload})

        def _emit_error(message: str) -> None:
            server._emit(
                "jobs.error",
                sid,
                {"job_id": job_id, "type": job_type_name, "message": message},
            )
            if ns:
                server._emit(f"{ns}.error", sid, {"job_id": job_id, "message": message})

        snapshot = contextvars.copy_context()

        def _run() -> None:
            try:
                runtime.run(
                    job_id,
                    store=store,
                    sink=_emit_progress,
                    extra_should_cancel=stop.is_set,
                    on_complete=_emit_complete,
                    on_error=_emit_error,
                )
            finally:
                with _running_lock:
                    _running.pop(job_id, None)

        threading.Thread(target=lambda: snapshot.run(_run), daemon=True).start()
        return job_id

    # ── jobs.start / status / active / cancel ────────────────────────────────

    def jobs_start(rid, params):
        job_type = str(params.get("type") or "").strip()
        if not job_type:
            return server._err(rid, -32602, "jobs.start requires a 'type'")
        raw_spec = params.get("spec")
        spec = raw_spec if isinstance(raw_spec, dict) else {}
        sid = str(params.get("session_id") or "")
        try:
            job_id = _spawn(job_type, spec, sid)
        except KeyError as exc:
            return server._err(rid, -32602, str(exc))
        except Exception as exc:  # noqa: BLE001
            return server._err(rid, 5008, str(exc))
        return server._ok(rid, {"job_id": job_id, "type": job_type})

    def jobs_status(rid, params):
        job_id = str(params.get("job_id") or "").strip()
        if not job_id:
            return server._err(rid, -32602, "jobs.status requires a 'job_id'")
        try:
            record = _get_store().read(job_id)
        except (FileNotFoundError, ValueError):
            return server._ok(rid, {"found": False, "job": None})
        return server._ok(rid, {"found": True, "job": record.to_dict()})

    def jobs_active(rid, params):
        types = params.get("types")
        if isinstance(types, str):
            types = [types]
        elif types is not None and not isinstance(types, list):
            types = None
        jobs = [r.to_dict() for r in _get_store().active(types=types)]
        return server._ok(rid, {"jobs": jobs, "count": len(jobs)})

    def jobs_cancel(rid, params):
        job_id = str(params.get("job_id") or "").strip()
        if not job_id:
            return server._err(rid, -32602, "jobs.cancel requires a 'job_id'")
        store = _get_store()
        with _running_lock:
            ev = _running.get(job_id)
        found = ev is not None or store.exists(job_id)
        try:
            store.request_cancel(job_id)
        except Exception:  # noqa: BLE001 — best-effort durable signal
            pass
        if ev is not None:
            ev.set()
        return server._ok(rid, {"job_id": job_id, "found": found, "cancelled": found})

    server.register_method("jobs.start", jobs_start)
    server.register_method("jobs.status", jobs_status)
    server.register_method("jobs.active", jobs_active)
    server.register_method("jobs.cancel", jobs_cancel)

    # ── ALIASES: forecast.warnings.automode.run / .cancel ────────────────────
    # Byte-compatible responses + the legacy event names, over the runtime. The
    # coalescing that used to be a hand-written throttle here now lives in
    # JobContext, so those handlers are gone from server.py.

    def automode_run(rid, params):
        sid = str(params.get("session_id") or "")
        if not sid:
            logger.warning(
                "forecast.warnings.automode.run called without session_id; "
                "progress events will not be session-routed (falling back to the "
                "request transport)"
            )
        dry_run = bool(params.get("dry_run", False))
        spec = {
            "dry_run": dry_run,
            "limit": params.get("limit"),
            "reason": params.get("reason") or None,
            "scope": params.get("scope") or None,
            "tier": params.get("tier") or None,
            "kinds": params.get("kinds") or None,
            "now": params.get("now"),
        }
        try:
            job_id = _spawn("warnings", spec, sid)
        except Exception as exc:  # noqa: BLE001
            return server._err(rid, 5008, str(exc))
        return server._ok(rid, {"job_id": job_id, "dry_run": dry_run})

    def automode_cancel(rid, params):
        job_id = str(params.get("job_id") or "").strip()
        with _running_lock:
            ev = _running.get(job_id)
        if ev is None:
            return server._ok(rid, {"job_id": job_id, "found": False})
        try:
            _get_store().request_cancel(job_id)
        except Exception:  # noqa: BLE001 — durable signal is best-effort
            pass
        ev.set()
        return server._ok(rid, {"job_id": job_id, "found": True, "cancelled": True})

    server.register_method("forecast.warnings.automode.run", automode_run)
    server.register_method("forecast.warnings.automode.cancel", automode_cancel)

    # ── ALIASES: forecast.reforecast.* / forecast.desk.task ──────────────────
    # Byte-compatible responses over the REFORECAST/TASK types on the runtime. The
    # per-question chain loop + the one-shot task session moved to
    # forecasting.jobs.types.{reforecast,task}; these handlers only validate, cap,
    # enqueue, and report — the exact shapes the old server.py handlers returned.
    # The reforecast/task modules are looked up at call time so tests can stub
    # start_job/validate exactly as before.

    def _reforecast_module():
        from forecasting.jobs.types import reforecast

        return reforecast

    def _max_batch(default: int) -> int:
        from superforecasting_agent.runtime.config import cfg_get, load_config_readonly

        try:
            return int(
                cfg_get(
                    load_config_readonly(),
                    "forecasting", "reforecast", "max_batch",
                    default=default,
                )
                or default
            )
        except (TypeError, ValueError):
            return default

    def reforecast_start(rid, params):
        try:
            from forecasting.ledger import ForecastLedger

            reforecast = _reforecast_module()
            raw_ids = params.get("question_ids")
            if not isinstance(raw_ids, list) or not raw_ids:
                return server._err(
                    rid, 5008,
                    "forecast.reforecast.start requires a non-empty question_ids list",
                )
            model = (params.get("model") or "").strip() or None
            provider = (params.get("provider") or "").strip() or None
            try:
                max_iterations = int(
                    params.get("max_iterations") or reforecast.DEFAULT_MAX_ITERATIONS
                )
            except (TypeError, ValueError):
                max_iterations = reforecast.DEFAULT_MAX_ITERATIONS

            ledger = ForecastLedger()
            max_batch = _max_batch(reforecast.DEFAULT_MAX_BATCH)
            accepted, errors = reforecast.validate_reforecast_ids(
                ledger, raw_ids, max_batch=max_batch
            )
            if errors:
                return server._err(rid, 5008, "; ".join(errors))

            spec = {
                "question_ids": accepted,
                "db": str(ledger.db_path) if getattr(ledger, "db_path", None) else None,
                "model": model,
                "provider": provider,
                "max_iterations": max_iterations,
                "triggered_by": "desk_mass_agent",
            }
            run_id = reforecast.start_job(spec, wait=False)
            return server._ok(
                rid,
                {
                    "run_id": run_id,
                    "total": len(accepted),
                    "note": (
                        f"reforecasting {len(accepted)} question(s) — the full formal "
                        f"flow runs one at a time; poll forecast.reforecast.status"
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001
            return server._err(rid, 5008, str(exc))

    def reforecast_active(rid, params):
        try:
            reforecast = _reforecast_module()
            jobs = []
            for row in reforecast.list_jobs(limit=int(params.get("limit") or 10)):
                if row.get("status") not in ("queued", "running"):
                    continue
                spec = row.get("spec") or {}
                jobs.append(
                    {
                        "run_id": row.get("run_id"),
                        "mode": spec.get("mode") or "reforecast",
                        "status": row.get("status"),
                        "question_ids": list(spec.get("question_ids") or []),
                        "done_count": row.get("done_count") or 0,
                        "total": row.get("total") or len(spec.get("question_ids") or []),
                        "created_at": row.get("created_at"),
                    }
                )
            return server._ok(rid, {"jobs": jobs})
        except Exception as exc:  # noqa: BLE001 — surface, never crash the gateway
            return server._ok(rid, {"jobs": [], "error": str(exc)})

    def reforecast_status(rid, params):
        try:
            reforecast = _reforecast_module()
            run_id = str(params.get("run_id") or "").strip()
            if not run_id:
                return server._err(
                    rid, 5008, "forecast.reforecast.status requires a run_id"
                )
            try:
                job = reforecast.read_job(run_id)
            except FileNotFoundError as exc:
                return server._err(rid, 5008, str(exc))
            results = job.get("results") or []
            return server._ok(
                rid,
                {
                    "run_id": job.get("run_id"),
                    "status": job.get("status"),
                    "total": job.get("total"),
                    "done_count": job.get("done_count"),
                    "current": job.get("current"),
                    "results": results,
                    "error": job.get("error"),
                    "quorums_started": sum(1 for r in results if r.get("quorum_autorun")),
                },
            )
        except Exception as exc:  # noqa: BLE001
            return server._err(rid, 5008, str(exc))

    def desk_task(rid, params):
        try:
            from forecasting.ledger import ForecastLedger
            from forecasting.jobs.types import task as task_type

            reforecast = _reforecast_module()
            instruction = str(params.get("instruction") or "").strip()
            if not instruction:
                return server._err(
                    rid, 5008, "forecast.desk.task requires a non-empty instruction"
                )
            raw_ids = params.get("question_ids")
            if not isinstance(raw_ids, list) or not raw_ids:
                return server._err(
                    rid, 5008,
                    "forecast.desk.task requires a non-empty question_ids list",
                )
            model = (params.get("model") or "").strip() or None
            provider = (params.get("provider") or "").strip() or None
            try:
                max_iterations = int(
                    params.get("max_iterations") or task_type.DEFAULT_TASK_MAX_ITERATIONS
                )
            except (TypeError, ValueError):
                max_iterations = task_type.DEFAULT_TASK_MAX_ITERATIONS

            ledger = ForecastLedger()
            max_batch = _max_batch(reforecast.DEFAULT_MAX_BATCH)
            accepted, errors = reforecast.validate_reforecast_ids(
                ledger, raw_ids, max_batch=max_batch
            )
            if errors:
                return server._err(rid, 5008, "; ".join(errors))

            spec = {
                "mode": "task",
                "instruction": instruction,
                "question_ids": accepted,
                "db": str(ledger.db_path) if getattr(ledger, "db_path", None) else None,
                "model": model,
                "provider": provider,
                "max_iterations": max_iterations,
                "triggered_by": "desk_task",
            }
            run_id = reforecast.start_job(spec, wait=False)
            return server._ok(
                rid,
                {
                    "run_id": run_id,
                    "total": len(accepted),
                    "note": (
                        f"task over {len(accepted)} question(s) — one agent session; "
                        f"poll forecast.reforecast.status"
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001
            return server._err(rid, 5008, str(exc))

    server.register_method("forecast.reforecast.start", reforecast_start)
    server.register_method("forecast.reforecast.active", reforecast_active)
    server.register_method("forecast.reforecast.status", reforecast_status)
    server.register_method("forecast.desk.task", desk_task)


__all__ = ["register", "active_jobs"]
