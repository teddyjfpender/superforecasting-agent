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


__all__ = ["register", "active_jobs"]
