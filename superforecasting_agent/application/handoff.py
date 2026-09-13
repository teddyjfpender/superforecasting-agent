"""Attempt-scoped handoff observation independent of presentation and gateway IO."""

from dataclasses import dataclass
from math import isfinite
from threading import Event
from time import monotonic

from superforecasting_agent.storage.session import SessionDB


@dataclass(frozen=True)
class HandoffResult:
    state: str
    error: str = ""
    wait_ended: bool = False


def observe_handoff(db: SessionDB, session_id: str, attempt_id: str) -> HandoffResult:
    row = db.get_handoff_state(session_id)
    if not row:
        return HandoffResult("unknown", "Handoff state is unavailable")
    if row.get("attempt_id") != attempt_id:
        return HandoffResult("replaced", "Handoff attempt changed")
    state = row.get("state")
    if state not in {"pending", "running", "completed", "failed"}:
        return HandoffResult("unknown", "Handoff state is unavailable")
    return HandoffResult(state, str(row.get("error") or ""))


def wait_for_handoff(
    db: SessionDB,
    session_id: str,
    attempt_id: str,
    *,
    stop: Event | None = None,
    timeout: float = 60.0,
) -> HandoffResult:
    """End local waiting without revoking a gateway-owned transfer.

    Callers retain session admission while this function waits. Cancellation or
    deadline may cancel only this attempt's unclaimed work; the returned state
    is read after that compare-and-set, so a concurrent gateway claim wins safely.
    """
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not isfinite(timeout)
        or timeout < 0
    ):
        raise ValueError("handoff timeout must be finite and non-negative")
    stop = stop if stop is not None else Event()
    deadline = monotonic() + timeout
    while not stop.is_set() and monotonic() < deadline:
        result = observe_handoff(db, session_id, attempt_id)
        if result.state != "pending" and result.state != "running":
            return result
        stop.wait(min(0.5, max(0.0, deadline - monotonic())))

    reason = (
        "local handoff wait cancelled"
        if stop.is_set()
        else "timed out waiting for gateway"
    )
    db.cancel_pending_handoff(session_id, reason, attempt_id=attempt_id)
    result = observe_handoff(db, session_id, attempt_id)
    return HandoffResult(result.state, result.error, wait_ended=True)


def require_local_turn(
    db: SessionDB, session_id: str, attempt_id: str | None = None
) -> None:
    """Reject work while transfer owns this session, including after reconnect.

    An explicit later resume has no source attempt marker. A live source handle
    retains its marker so delayed completion cannot silently reopen that handle.
    """
    row = db.get_handoff_state(session_id)
    if attempt_id and (not row or row.get("attempt_id") != attempt_id):
        raise ValueError("handoff state is unavailable or changed; check the transfer")
    state = (row or {}).get("state")
    if state in {"pending", "running"}:
        raise ValueError("session handoff is in progress; wait for gateway transfer")
    if attempt_id and state == "completed":
        raise ValueError(
            "session handed off; close it before explicitly resuming locally"
        )
    if attempt_id and state != "failed":
        raise ValueError("handoff state is unavailable; check the transfer")
