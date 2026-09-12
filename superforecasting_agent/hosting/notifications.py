"""Session ownership policy for background notifications."""

import logging
import queue
import threading
from collections.abc import Callable, Mapping, MutableMapping
from typing import Any, Literal


def route_notification(
    event: Mapping[str, object], session_key: str | None
) -> Literal["consume", "requeue"]:
    """Never redirect a session-bound result based on retry count or timing.

    Legacy unscoped events retain single-session delivery. Process session IDs
    identify processes, not conversations, and must not be used as routing keys.
    """
    owner = event.get("session_key")
    if owner and owner != session_key:
        return "requeue"
    return "consume"


def poll_notifications(
    stop: threading.Event,
    session: MutableMapping[str, Any],
    pending: queue.Queue[dict],
    *,
    consumed: Callable[[str], bool],
    format_event: Callable[[dict], str],
    host_stopping: Callable[[], bool],
    dispatch: Callable[[str], None],
) -> None:
    """Own queue admission and session exclusion; adapters supply delivery.

    A dispatch failure is logged, never blindly retried: the adapter may have
    already started a durable turn. Unadmitted events stay queued for their owner.
    """
    while not stop.is_set() and not session.get("_finalized"):
        try:
            event = pending.get(timeout=0.5)
        except queue.Empty:
            continue
        if stop.is_set() or session.get("_finalized"):
            pending.put(event)
            break
        if event.get("type") == "completion" and consumed(event.get("session_id", "")):
            continue
        if route_notification(event, session.get("session_key")) == "requeue":
            pending.put(event)
            stop.wait(0.02)
            continue
        text = format_event(event)
        if not text:
            continue
        with session["history_lock"]:
            stopping = (
                stop.is_set()
                or session.get("_finalized")
                or session.get("_closing")
                or host_stopping()
            )
            busy = session.get("running")
            if not stopping and not busy:
                session["running"] = True
        if stopping or busy:
            pending.put(event)
            if stopping:
                break
            stop.wait(0.02)
            continue
        try:
            dispatch(text)
        except Exception:
            logging.getLogger(__name__).exception("Notification dispatch failed")
            with session["history_lock"]:
                session["running"] = False
