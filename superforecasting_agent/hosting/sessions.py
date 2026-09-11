"""Session-use admission shared by runtime hosts and their command adapters."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any


class SessionBusy(RuntimeError):
    """Session resources are still in use, or close already owns them."""


def in_use(session: MutableMapping[str, Any], *, reserved: bool = False) -> bool:
    ready = session.get("agent_ready")
    return bool(
        session.get("_active_calls")
        or (session.get("running") and not reserved)
        or session.get("_background_jobs")
        or session.get("_background_agents")
        or (
            session.get("agent_build_started")
            and ready is not None
            and not ready.is_set()
        )
    )


@contextmanager
def use_session(session: MutableMapping[str, Any]) -> Iterator[None]:
    lock = session.setdefault("history_lock", threading.Lock())
    with lock:
        if session.get("_closing") or session.get("_replacing"):
            raise SessionBusy("session is closing or being replaced")
        session["_active_calls"] = session.get("_active_calls", 0) + 1
    try:
        yield
    finally:
        with lock:
            session["_active_calls"] -= 1


def reserve_close(
    session: MutableMapping[str, Any], *, reserved: bool = False, drained: bool = False
) -> None:
    """Claim cleanup under the same lock used to admit operations and turns.

    `reserved` belongs to a successful replacement operation; `drained` requires
    the host worker owner to have stopped admission and drained all work.
    """
    with session.setdefault("history_lock", threading.Lock()):
        if session.get("_closing"):
            raise SessionBusy("session is closing")
        if not drained and in_use(session, reserved=reserved):
            raise SessionBusy(
                "session is busy; cancel or finish active work before closing"
            )
        session["_closing"] = True


@contextmanager
def replacement(session: MutableMapping[str, Any]) -> Iterator[None]:
    """Reserve an idle session until its replacement is ready or fails."""
    lock = session.setdefault("history_lock", threading.Lock())
    with lock:
        if session.get("_closing") or session.get("_replacing") or in_use(session):
            raise SessionBusy(
                "session is busy; cancel or finish active work before replacing"
            )
        session["_replacing"] = True
        session["running"] = True
    try:
        yield
    finally:
        with lock:
            session["_replacing"] = False
            session["running"] = False


def finalize_session(
    session: MutableMapping[str, Any],
    *,
    end_session: Callable[[str, str], None],
    notify: Callable[[str, str | None], None],
    end_reason: str,
    mark_ended: bool,
) -> None:
    """Finish a conversation boundary before releasing its runtime resources.

    A durable end failure is retryable and must propagate to the host. Optional
    memory/hook failures are diagnosed but do not discard a saved transcript.
    Process shutdown skips the durable end so the conversation remains resumable.
    """
    logger = logging.getLogger(__name__)
    with session.setdefault("_finalize_lock", threading.Lock()):
        agent = session.get("agent")
        session_id = getattr(agent, "session_id", None) or session.get("session_key")
        if mark_ended and session_id and not session.get("_durable_ended"):
            end_session(session_id, end_reason)
            session["_durable_ended"] = True
        if session.get("_finalized"):
            return
        stop = session.get("_notif_stop")
        if stop is not None:
            stop.set()
        with session.setdefault("history_lock", threading.Lock()):
            history = list(session.get("history", []))
        if agent is not None and history and hasattr(agent, "commit_memory_session"):
            try:
                agent.commit_memory_session(history)
            except Exception:
                logger.exception(
                    "Memory finalization failed for session %s", session_id
                )
        try:
            notify("on_session_finalize", session_id)
        except Exception:
            logger.exception("Finalization hook failed for session %s", session_id)
        session["_finalized"] = True
