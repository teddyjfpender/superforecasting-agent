"""Session handoff operations behind the SessionDB API."""

from typing import Any, Dict, List, Optional
from uuid import uuid4


def request_handoff(
    self, session_id: str, platform: str, *, attempt_id: str | None = None
) -> bool:
    """Mark a session as pending handoff to the given platform.

    Returns True if the row was found and not already in flight; False if
    the session is already in a non-terminal handoff state.
    """

    attempt_id = uuid4().hex if attempt_id is None else attempt_id
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError("handoff attempt_id must be a non-empty string")

    def _do(conn):
        cur = conn.execute(
            "UPDATE sessions "
            "SET handoff_state = 'pending', "
            "    handoff_platform = ?, "
            "    handoff_error = NULL, handoff_attempt_id = ? "
            "WHERE id = ? AND (handoff_state IS NULL "
            "                  OR handoff_state IN ('completed', 'failed'))",
            (platform, attempt_id, session_id),
        )
        return cur.rowcount > 0

    return self._execute_write(_do)


def get_handoff_state(self, session_id: str) -> Optional[Dict[str, Any]]:
    """Read the current handoff state for a session.

    Returns ``{"state", "platform", "error", "attempt_id"}`` or None if the session has
    no handoff record.
    """
    try:
        cur = self._conn.execute(
            "SELECT handoff_state, handoff_platform, handoff_error, handoff_attempt_id "
            "FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "state": row["handoff_state"],
            "platform": row["handoff_platform"],
            "error": row["handoff_error"],
            "attempt_id": row["handoff_attempt_id"],
        }
    except Exception:
        return None


def list_pending_handoffs(self) -> List[Dict[str, Any]]:
    """Return all sessions in handoff_state='pending', oldest first.

    Used by the gateway's handoff watcher.
    """
    try:
        cur = self._conn.execute(
            "SELECT * FROM sessions "
            "WHERE handoff_state = 'pending' "
            "ORDER BY started_at ASC"
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def claim_handoff(self, session_id: str, *, attempt_id: str) -> bool:
    """Atomically transition pending → running. Returns True if claimed."""

    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError("handoff attempt_id must be a non-empty string")

    def _do(conn):
        cur = conn.execute(
            "UPDATE sessions SET handoff_state = 'running' "
            "WHERE id = ? AND handoff_state = 'pending' AND handoff_attempt_id = ?",
            (session_id, attempt_id),
        )
        return cur.rowcount > 0

    return self._execute_write(_do)


def complete_handoff(self, session_id: str, *, attempt_id: str) -> bool:
    """Complete only a running handoff; preserve terminal results."""

    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError("handoff attempt_id must be a non-empty string")

    def _do(conn):
        cur = conn.execute(
            "UPDATE sessions SET handoff_state = 'completed', "
            "handoff_error = NULL WHERE id = ? AND handoff_state = 'running' AND handoff_attempt_id = ?",
            (session_id, attempt_id),
        )

        return cur.rowcount > 0

    return self._execute_write(_do)


def fail_handoff(self, session_id: str, error: str, *, attempt_id: str) -> bool:
    """Fail only a running handoff and preserve terminal results."""

    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError("handoff attempt_id must be a non-empty string")

    def _do(conn):
        cur = conn.execute(
            "UPDATE sessions SET handoff_state = 'failed', "
            "handoff_error = ? WHERE id = ? AND handoff_state = 'running' AND handoff_attempt_id = ?",
            (error[:500], session_id, attempt_id),
        )

        return cur.rowcount > 0

    return self._execute_write(_do)


def cancel_pending_handoff(
    self, session_id: str, error: str, *, attempt_id: str
) -> bool:
    """Cancel only unclaimed work; never revoke a gateway's running transfer."""

    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError("handoff attempt_id must be a non-empty string")

    def _do(conn):
        cur = conn.execute(
            "UPDATE sessions SET handoff_state = 'failed', handoff_error = ? "
            "WHERE id = ? AND handoff_state = 'pending' AND handoff_attempt_id = ?",
            (error[:500], session_id, attempt_id),
        )
        return cur.rowcount > 0

    return self._execute_write(_do)
