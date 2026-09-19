#!/usr/bin/env python3
"""
Async (background) delegation registry.

Backs ``delegate_task(background=true)``: the parent agent dispatches a
subagent that runs on a module-level daemon executor and returns a handle
immediately, so the user and the model can keep working while the child runs.

When the child finishes, a completion event is pushed onto the SHARED
``process_registry.completion_queue`` with ``type="async_delegation"``. The
CLI (``cli.py`` process_loop) and gateway (``_run_process_watcher`` /
``completion_queue`` drain) already poll that queue while the agent is idle
and forge a fresh user/internal turn from each event. We deliberately reuse
that rail rather than reaching into a running agent loop:

  - completions surface as a NEW turn when the agent is idle, never spliced
    between a tool result and an assistant message. That keeps strict
    message-role alternation legal and the prompt cache intact (hard
    invariant: never mutate past context).
  - existing CLI and gateway consumers drain notification hints. Durable
    admission, outcomes and pending delivery events live in the background
    research journal; process checkpoints do not persist delegation results.

The completion payload carries a RICH, self-contained task-source block (the
original goal, the context the parent supplied, toolsets, model, dispatch
time, status, and the full result summary). When the result re-enters the
conversation the parent may be deep in unrelated context and won't remember
why the subagent existed; the block lets it either use the result or
re-dispatch if the world has moved on.

This module owns ONLY the async lifecycle. The actual child build + run is
delegated back to ``delegate_tool._run_single_child`` via an injected
runner, so all the credential leasing, heartbeat, timeout, and result-shaping
logic stays in one place.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
import weakref
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.thread import _worker
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class _DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor variant whose workers do not block process exit.

    Stdlib ``ThreadPoolExecutor`` workers are non-daemon. Background
    delegation is explicitly best-effort detached work, so a long child should
    be interruptible by ``/stop``/shutdown but must not keep a CLI process alive
    after the user exits.
    """

    def _adjust_thread_count(self) -> None:
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = "%s_%d" % (self._thread_name_prefix or self, num_threads)
            t = threading.Thread(
                name=thread_name,
                target=_worker,
                args=(
                    weakref.ref(self, weakref_cb),
                    self._work_queue,
                    self._initializer,
                    self._initargs,
                ),
                daemon=True,
            )
            t.start()
            self._threads.add(t)


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
# A persistent daemon executor (NOT a `with ThreadPoolExecutor()` block, which
# would join on exit and defeat the whole point of async). Workers are daemon
# threads so a hard process exit doesn't hang on an in-flight child.
_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()
_executor_max_workers: int = 0

_records_lock = threading.Lock()
# delegation_id -> record dict. Kept for the lifetime of the run plus a short
# tail after completion so `list_async_delegations()` can show recent results.
_records: Dict[str, Dict[str, Any]] = {}
_hinted_events: set[str] = set()

_DEFAULT_MAX_ASYNC_CHILDREN = 3
# How many completed records to retain for status queries before pruning.
_MAX_RETAINED_COMPLETED = 50


def _get_executor(max_workers: int) -> ThreadPoolExecutor:
    """Lazily create (or grow) the shared daemon executor.

    We never shrink — ThreadPoolExecutor can't resize — but if the configured
    cap grows between calls we rebuild a larger pool. Existing in-flight
    futures keep running on the old pool until it's garbage collected.
    """
    global _executor, _executor_max_workers
    with _executor_lock:
        if _executor is None or max_workers > _executor_max_workers:
            # Daemon threads: thread_name_prefix aids debugging in stack dumps.
            _executor = _DaemonThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="async-delegate",
            )
            _executor_max_workers = max_workers
        return _executor


class CapacityReservation:
    """Slots reserved before child allocation; consume under the registry lock."""

    def __init__(self, count: int, limit: int):
        if type(count) is not int or type(limit) is not int or not 0 < count <= limit:
            raise ValueError("Invalid background delegation capacity")
        self.remaining = count
        self.limit = limit
        with _records_lock:
            occupied = sum((r.get("status") in {"running", "cleanup_pending"} or r.get("_cleanup_pending", False)) for r in _records.values())
            if occupied + sum(r.remaining for r in _reservations) + count > limit:
                raise ValueError(f"Async delegation capacity reached ({limit} running or reserved)")
            _reservations.add(self)

    def release(self) -> None:
        with _records_lock:
            self.remaining = 0
            _reservations.discard(self)

    def consume_locked(self) -> None:
        if self not in _reservations or self.remaining < 1:
            raise ValueError("Background delegation reservation is no longer valid")
        self.remaining -= 1
        if self.remaining == 0:
            _reservations.remove(self)


_reservations: set[CapacityReservation] = set()


def active_count() -> int:
    """Number of async delegations currently running."""
    with _records_lock:
        return sum(1 for r in _records.values() if (r.get("status") in {"running", "cleanup_pending"} or r.get("_cleanup_pending", False)))


def _new_delegation_id() -> str:
    return f"deleg_{uuid.uuid4().hex[:8]}"


def _prune_completed_locked() -> None:
    """Drop the oldest completed records beyond the retention cap.

    Caller must hold ``_records_lock``.
    """
    completed = [
        (rid, r)
        for rid, r in _records.items()
        if r.get("status") not in {"running", "completion_pending", "cleanup_pending"}
    ]
    if len(completed) <= _MAX_RETAINED_COMPLETED:
        return
    # Oldest-first by completion time (fall back to dispatch time).
    completed.sort(key=lambda kv: kv[1].get("completed_at") or kv[1].get("dispatched_at") or 0)
    for rid, _ in completed[: len(completed) - _MAX_RETAINED_COMPLETED]:
        _records.pop(rid, None)


def admit_background_batch(tasks: list[dict], session_key: str) -> list[dict]:
    """Freeze every member and group before any worker can complete."""
    import json
    from agent.redact import redact_sensitive_text
    from superforecasting_agent.constants import get_agent_home
    from superforecasting_agent.storage.background_research import BackgroundResearchJournal

    journal = BackgroundResearchJournal(get_agent_home())
    owner = uuid.uuid4().hex
    specifications = json.loads(redact_sensitive_text(json.dumps(tasks), force=True))
    ids = journal.admit(specifications, session=session_key or "cli", owner=owner)
    return [{"journal": journal, "owner": owner, "id": task_id,
             "session": session_key, "specification": specification}
            for task_id, specification in zip(ids, specifications)]


def dispatch_async_delegation(
    *,
    goal: str,
    context: Optional[str],
    toolsets: Optional[List[str]],
    role: str,
    model: Optional[str],
    session_key: str,
    runner: Callable[[], Dict[str, Any]],
    interrupt_fn: Optional[Callable[[], None]] = None,
    max_async_children: int = _DEFAULT_MAX_ASYNC_CHILDREN,
    reservation: CapacityReservation | None = None,
    abandon_fn: Callable[[], None] | None = None,
    admission: dict | None = None,
) -> Dict[str, Any]:
    """Spawn ``runner`` on the daemon executor and return a handle immediately.

    Parameters
    ----------
    goal, context, toolsets, role, model
        The dispatch-time task spec, captured verbatim for the rich
        completion block.
    session_key
        The gateway session_key (from ``tools.approval.get_current_session_key``)
        captured on the parent thread BEFORE dispatch, because the daemon
        worker thread won't carry the contextvar. Used to route the
        completion back to the originating session.
    runner
        Zero-arg callable that builds + runs the child and returns the same
        result dict ``_run_single_child`` produces. Runs on the worker thread.
    interrupt_fn
        Optional callable to signal the child to stop (used on shutdown /
        explicit cancel).
    max_async_children
        Concurrency cap. When at capacity the dispatch is REJECTED (the caller
        should fall back to sync or tell the user) rather than queued, so a
        runaway model can't pile up unbounded background work.

    Returns
    -------
    dict
        ``{"status": "dispatched", "delegation_id": ...}`` on success, or
        ``{"status": "rejected", "error": ...}`` when at capacity.
    """
    try:
        bound = admission or admit_background_batch([{
            "goal": goal, "context": context, "toolsets": toolsets,
            "role": role, "model": model,
        }], session_key)[0]
        if bound["session"] != session_key:
            raise ValueError("Background admission session mismatch")
        journal, owner, delegation_id = bound["journal"], bound["owner"], bound["id"]
        specification = bound["specification"]
        journal_session = session_key or "cli"
    except Exception as exc:
        return {"status": "rejected", "error": f"Background admission could not be persisted: {exc}"}

    dispatched_at = time.time()
    record: Dict[str, Any] = {
        "delegation_id": delegation_id,
        "goal": specification["goal"],
        "context": specification["context"],
        "toolsets": specification["toolsets"],
        "role": role,
        "model": model,
        "session_key": session_key,
        "status": "running",
        "dispatched_at": dispatched_at,
        "completed_at": None,
        "interrupt_fn": interrupt_fn,
        "_journal": journal,
        "_owner": owner,
        "_journal_session": journal_session,
        "_abandon_fn": abandon_fn,
        "_finalize_lock": threading.Lock(),
        "_cleanup_lock": threading.Lock(),
    }
    try:
        reserved = reservation or CapacityReservation(1, max_async_children)
        with _records_lock:
            if reserved.limit != max_async_children:
                raise ValueError("Background delegation capacity changed during admission")
            reserved.consume_locked()
            _records[delegation_id] = record
    except ValueError as exc:
        journal.finish(delegation_id, owner, "rejected", {"error": str(exc)})
        return {"status": "rejected", "error": str(exc)}

    from superforecasting_agent.constants import set_agent_home_override
    from superforecasting_agent.tooling.interrupts import detached_execution_context
    from tools.approval import set_current_session_key

    worker_context = detached_execution_context()
    worker_context.run(set_agent_home_override, journal.path.parent)
    worker_context.run(set_current_session_key, session_key)
    record["_worker_context"] = worker_context

    def _worker() -> None:
        result: Dict[str, Any] = {}
        status = "error"
        started = False
        try:
            journal.start(delegation_id, owner)
            started = True
            result = runner() or {}
            status = result.get("status") or "completed"
        except Exception as exc:  # noqa: BLE001 — must never crash the worker
            logger.exception("Async delegation %s crashed", delegation_id)
            result = {
                "status": "error",
                "summary": None,
                "error": f"{type(exc).__name__}: {exc}",
                "api_calls": 0,
                "duration_seconds": round(time.time() - dispatched_at, 2),
            }
            status = "error"
        finally:
            if not started and abandon_fn is not None:
                try:
                    abandon_fn()
                except Exception:
                    with _records_lock:
                        record["_cleanup_pending"] = True
                    logger.exception("Unstarted background child cleanup is pending")
            _finalize(delegation_id, result, status)

    try:
        executor = _get_executor(max_async_children)
        executor.submit(lambda: worker_context.run(_worker))
    except Exception as exc:  # pragma: no cover — pool submit failure is rare
        _finalize(delegation_id, {"error": str(exc)}, "rejected")
        with _records_lock:
            if _records.get(delegation_id, {}).get("status") != "completion_pending":
                _records.pop(delegation_id, None)
        return {
            "status": "rejected",
            "error": f"Failed to schedule async delegation: {exc}",
        }

    logger.info(
        "Dispatched async delegation %s (session_key=%s): %s",
        delegation_id, session_key or "<cli>", (goal or "")[:80],
    )
    return {"status": "dispatched", "delegation_id": delegation_id}


def _finalize(delegation_id: str, result: Dict[str, Any], status: str) -> None:
    with _records_lock:
        record = _records.get(delegation_id)
    if record is None or not record["_finalize_lock"].acquire(blocking=False):
        return
    try:
        _finalize_owned(delegation_id, result, status)
    finally:
        record["_finalize_lock"].release()


def _finalize_owned(delegation_id: str, result: Dict[str, Any], status: str) -> None:
    """Mark a record complete and push the completion event onto the queue."""
    from agent.redact import redact_sensitive_text
    import json

    with _records_lock:
        record = _records.get(delegation_id)
        if record is None or record.get("status") not in {"running", "completion_pending"}:
            return
    try:
        safe_result = json.loads(redact_sensitive_text(json.dumps(result, allow_nan=False), force=True))
        durable_status = "error" if status not in {"completed", "interrupted", "rejected"} else status
        record["_journal"].finish(delegation_id, record["_owner"], durable_status, safe_result)
    except Exception:
        with _records_lock:
            record.update(status="completion_pending", _pending_result=result, _pending_status=status)
        logger.exception("Background result persistence pending for %s", delegation_id)
        return
    result = safe_result
    with _records_lock:
        record = _records.get(delegation_id)
        if record is None:
            return
        if record.get("status") not in {"running", "completion_pending"}:
            return
        record.pop("_pending_result", None)
        record.pop("_pending_status", None)
        record["_terminal_status"] = status
        record["status"] = "cleanup_pending" if record.get("_cleanup_pending") else status
        record["completed_at"] = time.time()
        if not record.get("_cleanup_pending"):
            record["interrupt_fn"] = None
            record["_abandon_fn"] = None
        # Snapshot fields needed for the event while holding the lock.
        event_record = dict(record)
        _prune_completed_locked()

    _push_completion_event(event_record, result, status)


def _push_completion_event(record: dict, result: dict, status: str) -> None:
    """Queue canonical hints; a failed queue write never loses the journal event."""
    from tools.process_registry import process_registry

    for event in pending_notifications(record["session_key"], journal=record["_journal"]):
        if record["delegation_id"] not in event["delegation_ids"]:
            continue
        with _records_lock:
            if event["journal_event_id"] in _hinted_events:
                continue
            try:
                process_registry.completion_queue.put(event)
            except Exception:
                logger.exception("Background notification pending in durable journal")
            else:
                _hinted_events.add(event["journal_event_id"])


def pending_notifications(session_key: str, *, journal=None) -> list[dict]:
    """Recover durable notifications for exactly one session in this profile."""
    import json
    from superforecasting_agent.constants import get_agent_home
    from superforecasting_agent.storage.background_research import BackgroundResearchJournal

    if journal is None:
        home = get_agent_home()
        if not (home / "background-research.db").exists():
            return []
        journal = BackgroundResearchJournal(home)
    from superforecasting_agent.hosting.notifications import notification_profile_key

    journal.recover(session_key or "cli")
    notifications = []
    for event in journal.pending(session_key or "cli"):
        members = event["tasks"]
        first = members[0]
        specification, result = first["specification"], first["result"] or {}
        grouped = event["kind"] == "group_complete"
        notifications.append({
            "type": "async_delegation", "session_key": session_key,
            "profile_key": notification_profile_key(journal.path.parent),
            "delegation_id": first["batch_id"] if grouped else first["delegation_id"],
            "journal_event_id": event["event_id"], "delivery_kind": event["kind"],
            "delegation_ids": [task["delegation_id"] for task in members],
            "goal": "Grouped background research" if grouped else specification["goal"],
            "context": None if grouped else specification.get("context"),
            "toolsets": specification.get("toolsets"), "role": specification.get("role"),
            "model": result.get("model") or specification.get("model"),
            "status": ("completed" if all(task["status"] == "completed" for task in members) else "error")
                      if grouped else first["status"],
            "summary": json.dumps([{"goal": task["specification"]["goal"], "status": task["status"],
                                    "result": task["result"]} for task in members], ensure_ascii=False)
                       if grouped else result.get("summary"),
            "error": None if grouped else result.get("error"),
            "api_calls": sum((task["result"] or {}).get("api_calls", 0) for task in members),
            "dispatched_at": first["dispatched_at"],
            "completed_at": max(task["completed_at"] for task in members),
            "duration_seconds": result.get("duration_seconds", 0),
            "exit_reason": result.get("exit_reason"),
        })
    return notifications


def acknowledge_notification(event_id: str, session_key: str) -> None:
    from superforecasting_agent.constants import get_agent_home
    from superforecasting_agent.storage.background_research import BackgroundResearchJournal

    BackgroundResearchJournal(get_agent_home()).acknowledge(event_id, session_key or "cli")


def retry_pending_completions() -> None:
    """Retry only retained outcome persistence; never run the worker again."""
    with _records_lock:
        pending = [(key, record["_pending_result"], record["_pending_status"])
                   for key, record in _records.items()
                   if record.get("status") == "completion_pending"]
    for task_id, result, status in pending:
        _finalize(task_id, result, status)
    with _records_lock:
        cleanup = [record for record in _records.values() if record.get("_cleanup_pending")]
    for record in cleanup:
        if not record["_cleanup_lock"].acquire(blocking=False):
            continue
        try:
            callback = record.get("_abandon_fn")
            if callback is None:
                continue
            record["_worker_context"].copy().run(callback)
            with _records_lock:
                record.pop("_cleanup_pending", None)
                record["_abandon_fn"] = None
                record["interrupt_fn"] = None
                if record.get("status") == "cleanup_pending":
                    record["status"] = record["_terminal_status"]
        except Exception:
            logger.exception("Unstarted background child cleanup remains pending")
        finally:
            record["_cleanup_lock"].release()


def list_async_delegations(*, session_key: str | None = None) -> List[Dict[str, Any]]:
    """Snapshot of async delegations (running + recently completed).

    Safe to call from any thread. Excludes the non-serialisable interrupt_fn.
    """
    from superforecasting_agent.constants import get_agent_home
    from superforecasting_agent.storage.background_research import BackgroundResearchJournal

    retry_pending_completions()
    home = get_agent_home()
    with _records_lock:
        live = {
            key: {k: v for k, v in record.items() if k != "interrupt_fn" and not k.startswith("_")}
            for key, record in _records.items()
            if record["_journal"].path.parent == home
            and (session_key is None or record.get("session_key") == session_key)
        }
    if not (home / "background-research.db").exists():
        return list(live.values())
    journal = BackgroundResearchJournal(home)
    rows = journal.tasks(None if session_key is None else session_key or "cli")
    for session in {row["session_key"] for row in rows}:
        journal.recover(session)
    rows = journal.tasks(None if session_key is None else session_key or "cli")
    records = {}
    for row in rows:
        specification = row["specification"]
        records[row["delegation_id"]] = {
            **specification, **row,
            "session_key": "" if row["session_key"] == "cli" else row["session_key"],
            "durable_status": row["status"],
            "status": "unconfirmed" if row["status"] in {"accepted", "running"} else row["status"],
        }
    records.update(live)
    ordered = sorted(records.values(), key=lambda row: row.get("dispatched_at", 0))
    unresolved = [row for row in ordered if row.get("status") in {
        "running", "accepted", "unconfirmed", "completion_pending", "cleanup_pending",
    }]
    completed = [row for row in ordered if row not in unresolved]
    return unresolved + completed[-_MAX_RETAINED_COMPLETED:]


def interrupt_delegation(delegation_id: str, session_key: str) -> bool:
    """Signal only an observed worker belonging to this session and profile."""
    from superforecasting_agent.constants import get_agent_home

    with _records_lock:
        record = _records.get(delegation_id)
        if (record is None or record.get("session_key") != session_key
                or record["_journal"].path.parent.resolve() != get_agent_home().resolve()):
            return False
        callback = record.get("interrupt_fn")
    if not callable(callback):
        return False
    record["_worker_context"].copy().run(callback)
    return True


def interrupt_all(reason: str = "shutdown", *, session_key: str | None = None) -> int:
    """Signal every running async delegation to stop. Returns how many.

    Used on ``/stop`` and gateway shutdown so a dangling background subagent
    can't keep burning tokens with no one listening. The child still emits a
    completion event (status='interrupted') via the normal finalize path.
    A session key is scoped to the active profile (including an empty key);
    only None requests process-wide shutdown. Callbacks retain worker context.
    """
    from superforecasting_agent.constants import get_agent_home

    profile_home = get_agent_home().resolve()
    count = 0
    with _records_lock:
        targets = [
            r for r in _records.values() if (r.get("status") in {"running", "cleanup_pending"} or r.get("_cleanup_pending", False))
            and (session_key is None or (
                r.get("session_key") == session_key
                and r["_journal"].path.parent.resolve() == profile_home
            ))
        ]
    for r in targets:
        fn = r.get("interrupt_fn")
        if callable(fn):
            try:
                r["_worker_context"].copy().run(fn)
                count += 1
            except Exception as exc:
                logger.debug(
                    "interrupt_all: %s interrupt failed: %s",
                    r.get("delegation_id"), exc,
                )
    if count:
        logger.info("Interrupted %d async delegation(s) (%s)", count, reason)
    return count


def _reset_for_tests() -> None:
    """Test-only teardown; callers must stop submitting before resetting.

    A terminal record is not a joined worker: completion notification publication
    follows the terminal-state update. Join before clearing records/queue hints so
    the preceding test cannot publish into the next test's completion queue.
    """
    global _executor, _executor_max_workers
    with _executor_lock:
        executor = _executor
        _executor = None
        _executor_max_workers = 0
    # Never join while holding registry locks needed by finishing workers.
    if executor is not None:
        executor.shutdown(wait=True)
    with _records_lock:
        _records.clear()
        _hinted_events.clear()
        for reservation in list(_reservations):
            reservation.remaining = 0
        _reservations.clear()
