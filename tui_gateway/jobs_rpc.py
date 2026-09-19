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

from superforecasting_agent.hosting.workers import HostStopping

logger = logging.getLogger(__name__)


def _get_store():
    from forecasting.jobs.store import JobStore

    return JobStore()


def active_jobs(types: list[str] | None = None) -> list[dict[str, Any]]:
    """The in-flight jobs as plain dicts — the seam a desk/agents chip reads."""
    return [r.to_dict() for r in _get_store().active(types=types)]


def register(server, *, store_factory=None):
    """Register every ``jobs.*`` handler + the warnings aliases into the gateway
    dispatch table."""

    from superforecasting_agent.hosting.job_workers import JobWorkers
    from tui_gateway.rpc_binding import bind_host_handler

    workers = JobWorkers()
    # Compatibility composition exposes the owner for diagnostics; handlers and
    # workers capture this instance, never a module-level replacement.
    server._job_workers = workers
    get_store = store_factory or _get_store

    admitted_host = contextvars.ContextVar("job_rpc_host")

    def register_method(name, handler):
        def invoke(owner, rid, params):
            token = admitted_host.set(owner)
            try:
                return handler(rid, params)
            finally:
                admitted_host.reset(token)

        server.register_method(name, bind_host_handler(
            lambda: server._host, server._err,
            invoke,
        ))

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
        owner = admitted_host.get()
        lifetime = owner.workers
        store = get_store()
        job_id = store.new_id()
        store.write(JobRecord(job_id=job_id, type=job_type_name, spec=dict(spec or {})))

        stop = threading.Event()
        workers.install(job_id, stop)

        def emit(event, session_id, payload):
            if server._host is owner and owner.workers is lifetime and not lifetime.stopping:
                server._emit(event, session_id, payload)

        ns = job_type.alias_namespace

        def _emit_progress(event: dict[str, Any]) -> None:
            emit(
                "jobs.progress",
                sid,
                {"job_id": job_id, "type": job_type_name, "progress": event},
            )
            if ns:
                emit(f"{ns}.progress", sid, {"job_id": job_id, **event})

        def _emit_complete(result: dict[str, Any]) -> None:
            emit(
                "jobs.complete",
                sid,
                {"job_id": job_id, "type": job_type_name, "result": result},
            )
            if ns:
                payload = result if isinstance(result, dict) else {}
                emit(f"{ns}.complete", sid, {"job_id": job_id, **payload})

        def _emit_error(message: str) -> None:
            emit(
                "jobs.error",
                sid,
                {"job_id": job_id, "type": job_type_name, "message": message},
            )
            if ns:
                emit(f"{ns}.error", sid, {"job_id": job_id, "message": message})

        snapshot = contextvars.copy_context()

        def _run() -> None:
            try:
                runtime.run(
                    job_id,
                    store=store,
                    sink=_emit_progress,
                    extra_should_cancel=lambda: stop.is_set() or lifetime.stopping,
                    on_complete=_emit_complete,
                    on_error=_emit_error,
                )
            finally:
                workers.retire(job_id, stop)

        try:
            lifetime.start(lambda: snapshot.run(_run), name=f"forecast-job-{job_id}")
        except BaseException:
            workers.retire(job_id, stop)
            # Keep the queued record for explicit recovery; it has not executed.
            raise
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
        except HostStopping:
            raise
        except Exception as exc:  # noqa: BLE001
            return server._err(rid, 5008, str(exc))
        return server._ok(rid, {"job_id": job_id, "type": job_type})

    def jobs_status(rid, params):
        job_id = str(params.get("job_id") or "").strip()
        if not job_id:
            return server._err(rid, -32602, "jobs.status requires a 'job_id'")
        try:
            record = get_store().read(job_id)
        except (FileNotFoundError, ValueError):
            return server._ok(rid, {"found": False, "job": None})
        return server._ok(rid, {"found": True, "job": record.to_dict()})

    def jobs_active(rid, params):
        types = params.get("types")
        if isinstance(types, str):
            types = [types]
        elif types is not None and not isinstance(types, list):
            types = None
        jobs = [r.to_dict() for r in get_store().active(types=types)]
        return server._ok(rid, {"jobs": jobs, "count": len(jobs)})

    def jobs_cancel(rid, params):
        job_id = str(params.get("job_id") or "").strip()
        if not job_id:
            return server._err(rid, -32602, "jobs.cancel requires a 'job_id'")
        from forecasting.application.job_cancellation import request_job_cancellation

        admitted_event = workers.get(job_id)
        try:
            receipt = request_job_cancellation(get_store(), job_id)
        except ValueError as exc:
            return server._err(rid, -32602, str(exc))
        except OSError as exc:
            return server._err(rid, 5008, f"Cancellation could not be persisted: {exc}")
        if receipt.accepted:
            workers.signal(receipt.job_id, admitted_event)
        return server._ok(rid, {
            "job_id": receipt.job_id,
            "found": receipt.accepted,
            # Legacy field means admission, NOT worker termination.
            "cancelled": receipt.accepted,
            "cancel_requested": receipt.accepted,
            "status": receipt.record.status if receipt.record is not None else None,
        })

    register_method("jobs.start", jobs_start)
    register_method("jobs.status", jobs_status)
    register_method("jobs.active", jobs_active)
    register_method("jobs.cancel", jobs_cancel)

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
        except HostStopping:
            raise
        except Exception as exc:  # noqa: BLE001
            return server._err(rid, 5008, str(exc))
        return server._ok(rid, {"job_id": job_id, "dry_run": dry_run})

    def automode_cancel(rid, params):
        response = jobs_cancel(rid, params)
        result = response.get("result")
        if result is not None:
            # Preserve the legacy envelope while sharing durable admission.
            result.pop("cancel_requested", None)
            result.pop("status", None)
            if not result["found"]:
                result.pop("cancelled", None)
        return response

    register_method("forecast.warnings.automode.run", automode_run)
    register_method("forecast.warnings.automode.cancel", automode_cancel)

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
        except HostStopping:
            raise
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
        except HostStopping:
            raise
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
        except HostStopping:
            raise
        except Exception as exc:  # noqa: BLE001
            return server._err(rid, 5008, str(exc))

    register_method("forecast.reforecast.start", reforecast_start)
    register_method("forecast.reforecast.active", reforecast_active)
    register_method("forecast.reforecast.status", reforecast_status)
    register_method("forecast.desk.task", desk_task)

    return workers


__all__ = ["register", "active_jobs"]
