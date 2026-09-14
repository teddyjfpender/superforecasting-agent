"""Session ownership policy for background notifications."""

import hashlib
import logging
import queue
import threading
import time
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from superforecasting_agent.storage import turns


def notification_profile_key(home: Path | None = None) -> str:
    """Opaque routing identity for the owning profile, without exposing its path."""
    if home is None:
        from superforecasting_agent.constants import get_agent_home

        home = get_agent_home()
    return hashlib.sha256(str(home.resolve()).encode()).hexdigest()


def route_notification(
    event: Mapping[str, object],
    session_key: str | None,
    *,
    profile_key: str | None = None,
) -> Literal["consume", "requeue"]:
    """Never redirect a session-bound result based on retry count or timing.

    Legacy unscoped events retain single-session delivery. Process session IDs
    identify processes, not conversations, and must not be used as routing keys.
    """
    profile = event.get("profile_key")
    if profile is not None and profile != (profile_key or notification_profile_key()):
        return "requeue"
    owner = event.get("session_key")
    if owner and owner != session_key:
        return "requeue"
    return "consume"


def admit_background_notification(
    db: turns.TurnStore | None,
    event: Mapping[str, object],
    session_key: str,
    prompt: str,
    *,
    acknowledge: Callable[[str, str], None],
) -> tuple[str, bool]:
    """Commit an idempotent receiving turn before acknowledging its source.

    A duplicate returns the original identity without authorizing another model
    execution. Failure to acknowledge leaves the source retryable; the receiving
    turn still owns the work. Adapters retain responsibility for turn transitions.
    """
    if not session_key or event.get("session_key") != session_key:
        raise ValueError("Background result belongs to another session")
    if route_notification(event, session_key) != "consume":
        raise ValueError("Background result belongs to another profile")
    event_id = event.get("journal_event_id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("Background result requires a durable event identity")
    if db is None:
        raise RuntimeError(
            "Background result delivery requires durable session storage"
        )
    receipt = turns.admit_notification(db, session_key, prompt, event_id)
    try:
        acknowledge(event_id, session_key)
    except Exception:
        logging.getLogger(__name__).exception(
            "Background acknowledgement pending; receiving turn is durable"
        )
    return receipt


@dataclass(frozen=True)
class BackgroundNotification:
    event: Mapping[str, object]
    prompt: str


def execute_background_notification(
    db: turns.TurnStore | None,
    notification: BackgroundNotification,
    session_key: str,
    *,
    acknowledge: Callable[[str, str], None],
    execute: Callable[[str], Mapping[str, object] | None],
) -> str:
    """Execute only a newly admitted receipt and persist its actual outcome."""
    turn_id, created = admit_background_notification(
        db,
        notification.event,
        session_key,
        notification.prompt,
        acknowledge=acknowledge,
    )
    if not created:
        return turn_id
    assert db is not None  # Admission rejects unavailable storage.
    turns.transition(db, turn_id, "running")
    try:
        result = execute(notification.prompt) or {}
    except BaseException as exc:
        turns.transition(db, turn_id, "interrupted", error=type(exc).__name__)
        raise
    status = (
        "interrupted"
        if result.get("interrupted") is True
        else "error"
        if result.get("failed") is True or result.get("error")
        else "complete"
        if result.get("completed") is True
        else "interrupted"
    )
    text = result.get("final_response")
    error = result.get("error")
    turns.transition(
        db,
        turn_id,
        status,
        text=text if isinstance(text, str) else None,
        error=error if isinstance(error, str) else None,
    )
    return turn_id


def poll_notifications(
    stop: threading.Event,
    session: MutableMapping[str, Any],
    pending: queue.Queue[dict],
    *,
    consumed: Callable[[str], bool],
    format_event: Callable[[dict], str],
    host_stopping: Callable[[], bool],
    dispatch: Callable[[str], None],
    recover: Callable[[], list[dict]] | None = None,
    dispatch_event: Callable[[str, dict], None] | None = None,
) -> None:
    """Own queue admission and session exclusion; adapters supply delivery.

    A dispatch failure is logged, never blindly retried: the adapter may have
    already started a durable turn. Unadmitted events stay queued for their owner.
    """
    profile_key = notification_profile_key()
    next_recovery = 0.0
    while not stop.is_set() and not session.get("_finalized"):
        event = None
        if (
            recover is not None
            and not session.get("running")
            and time.monotonic() >= next_recovery
        ):
            next_recovery = time.monotonic() + 0.5
            try:
                recovered = recover()
                # Deliver one durable record directly. Other records stay in the
                # journal, avoiding duplicate queue growth while this host is busy.
                if recovered:
                    event = recovered[0]
            except Exception:
                logging.getLogger(__name__).exception(
                    "Notification recovery unavailable"
                )
        if event is None:
            try:
                event = pending.get(timeout=0.5)
            except queue.Empty:
                continue
        if stop.is_set() or session.get("_finalized"):
            pending.put(event)
            break
        if event.get("type") == "completion" and consumed(event.get("session_id", "")):
            continue
        if (
            route_notification(
                event, session.get("session_key"), profile_key=profile_key
            )
            == "requeue"
        ):
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
            if dispatch_event is not None:
                dispatch_event(text, event)
            else:
                dispatch(text)
        except Exception:
            logging.getLogger(__name__).exception("Notification dispatch failed")
            with session["history_lock"]:
                session["running"] = False
