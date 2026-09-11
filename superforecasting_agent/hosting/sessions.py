"""Session-use admission shared by runtime hosts and their command adapters."""

from __future__ import annotations

import threading
from collections.abc import Iterator, MutableMapping
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
        if session.get("_closing"):
            raise SessionBusy("session is closing")
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
