"""Process-local delegation control state with explicit root-session ownership.

The tool runtime supplies child handles and owns execution/disposal. This owner
serializes registration, snapshots, pause policy and cooperative interruption.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_spawn_pause_lock = threading.Lock()
_spawn_paused: bool = False
_spawn_paused_sessions: set[str] = set()

_active_subagents_lock = threading.Lock()
# subagent_id -> mutable record tracking the live child agent.  Stays only
# for the lifetime of the run; _run_single_child is the owner.
_active_subagents: dict[str, dict[str, Any]] = {}


def set_spawn_paused(paused: bool, *, session_key: str | None = None) -> bool:
    """Block/unblock new spawns for a session, or globally when no scope is supplied.

    Active children keep running; only NEW calls to delegate_task fail fast
    with a "spawning paused" error until unblocked.  Returns the new state.
    """
    if not isinstance(paused, bool):
        raise ValueError("paused must be a boolean")
    global _spawn_paused
    with _spawn_pause_lock:
        if session_key is not None:
            if paused:
                _spawn_paused_sessions.add(session_key)
            else:
                _spawn_paused_sessions.discard(session_key)
            return _spawn_paused or bool(paused)
        _spawn_paused = bool(paused)
        return _spawn_paused


def is_spawn_paused(*, session_key: str | None = None) -> bool:
    with _spawn_pause_lock:
        return _spawn_paused or (
            session_key is not None and session_key in _spawn_paused_sessions
        )


def register_subagent(record: dict[str, Any]) -> None:
    sid = record.get("subagent_id")
    if not sid:
        return
    with _active_subagents_lock:
        existing = _active_subagents.get(sid)
        if existing is not None and existing is not record:
            raise RuntimeError(f"subagent already registered: {sid}")
        _active_subagents[sid] = record


def unregister_subagent(subagent_id: str, *, agent: Any) -> None:
    with _active_subagents_lock:
        existing = _active_subagents.get(subagent_id)
        if existing is not None and existing.get("agent") is agent:
            _active_subagents.pop(subagent_id)


def interrupt_subagent(subagent_id: str, *, session_key: str | None = None) -> bool:
    """Request that a single running subagent stop at its next iteration boundary.

    Does not hard-kill the worker thread (Python can't); sets the child's
    interrupt flag which propagates to in-flight tools and recurses into
    grandchildren via AIAgent.interrupt().  Returns True if a matching
    subagent was found.
    """
    with _active_subagents_lock:
        record = _active_subagents.get(subagent_id)
    if not record or (
        session_key is not None and record.get("session_key") != session_key
    ):
        return False
    agent = record.get("agent")
    if agent is None:
        return False
    try:
        agent.interrupt(f"Interrupted via TUI ({subagent_id})")
    except Exception as exc:
        logger.debug("interrupt_subagent(%s) failed: %s", subagent_id, exc)
        return False
    return True


def list_active_subagents(*, session_key: str | None = None) -> list[dict[str, Any]]:
    """Snapshot of the currently running subagent tree.

    Each record: {subagent_id, parent_id, depth, goal, model, started_at,
    tool_count, status}.  Safe to call from any thread — returns a copy.
    """
    with _active_subagents_lock:
        return [
            {k: v for k, v in r.items() if k != "agent"}
            for r in _active_subagents.values()
            if session_key is None or r.get("session_key") == session_key
        ]


def record_progress(subagent_id: str, *, tool_count: int, last_tool: str) -> None:
    """Update observational counters without exposing the mutable registry."""
    with _active_subagents_lock:
        record = _active_subagents.get(subagent_id)
        if record is not None:
            record["tool_count"] = tool_count
            record["last_tool"] = last_tool
