"""Session transcript operations behind the SessionDB API."""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
    """Load all messages for a session, ordered by insertion order."""
    with self._lock:
        cursor = self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        )
        rows = cursor.fetchall()
    result = []
    for row in rows:
        msg = dict(row)
        if "content" in msg:
            msg["content"] = self._decode_content(msg["content"])
        if msg.get("tool_calls"):
            try:
                msg["tool_calls"] = json.loads(msg["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("Failed to deserialize tool_calls in get_messages, falling back to []")
                msg["tool_calls"] = []
        result.append(msg)
    return result


def get_messages_around(
    self,
    session_id: str,
    around_message_id: int,
    window: int = 5,
) -> Dict[str, Any]:
    """Load a window of messages anchored on a specific message id.

        Returns a dict with:
          - ``window``: up to ``window`` messages before the anchor, the anchor
            itself, and up to ``window`` messages after, ordered by id ascending.
          - ``messages_before``: count of messages strictly before the anchor
            still in the session (== window unless we hit the start).
          - ``messages_after``: count of messages strictly after the anchor
            still in the session (== window unless we hit the end).

        Used by ``session_search`` for both the discovery shape (anchored on the
        FTS5 match) and the scroll shape (anchored on any message id). The
        ``messages_before`` / ``messages_after`` counts let the caller detect
        session boundaries: when either is less than ``window``, the agent has
        reached one end of the session.

        Returns an empty window when ``around_message_id`` is not a real id in
        ``session_id`` — callers decide how to surface that.
        """
    if window < 0:
        window = 0
    with self._lock:
        # Confirm the anchor exists in this session.
        anchor_exists = self._conn.execute(
            "SELECT 1 FROM messages WHERE id = ? AND session_id = ? LIMIT 1",
            (around_message_id, session_id),
        ).fetchone()
        if not anchor_exists:
            return {"window": [], "messages_before": 0, "messages_after": 0}
        # Two queries: anchor + before (DESC, take window+1), and after
        # (ASC, take window). Final order is id ASC.
        before_rows = self._conn.execute(
            "SELECT * FROM messages "
            "WHERE session_id = ? AND id <= ? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, around_message_id, window + 1),
        ).fetchall()
        after_rows = self._conn.execute(
            "SELECT * FROM messages "
            "WHERE session_id = ? AND id > ? "
            "ORDER BY id ASC LIMIT ?",
            (session_id, around_message_id, window),
        ).fetchall()
    # before_rows is DESC; reverse so it's ASC, then concatenate after_rows.
    rows = list(reversed(before_rows)) + list(after_rows)
    result = []
    for row in rows:
        msg = dict(row)
        if "content" in msg:
            msg["content"] = self._decode_content(msg["content"])
        if msg.get("tool_calls"):
            try:
                msg["tool_calls"] = json.loads(msg["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Failed to deserialize tool_calls in get_messages_around, falling back to []"
                )
                msg["tool_calls"] = []
        result.append(msg)
    # before_rows includes the anchor itself; subtract 1 for the count of
    # messages strictly before the anchor in the returned slice.
    messages_before = max(0, len(before_rows) - 1)
    messages_after = len(after_rows)
    return {
        "window": result,
        "messages_before": messages_before,
        "messages_after": messages_after,
    }


def get_anchored_view(
    self,
    session_id: str,
    around_message_id: int,
    window: int = 5,
    bookend: int = 3,
    keep_roles: Optional[Tuple[str, ...]] = ("user", "assistant"),
) -> Dict[str, Any]:
    """Return an anchored window plus session bookends.

        Built on top of ``get_messages_around``. Three slices:

          - ``window``: messages immediately surrounding the anchor. Filtered
            to ``keep_roles`` (tool-response noise dropped by default), EXCEPT
            the anchor itself is always preserved regardless of role.
          - ``bookend_start``: first ``bookend`` user/assistant messages of the
            session — but only those whose id is strictly before the window's
            first message id. Empty when the window already overlaps the
            session head. Empty-content messages (tool-call-only assistant
            turns) are skipped so they don't crowd out actual prose openings.
          - ``bookend_end``: last ``bookend`` user/assistant messages of the
            session, same non-overlap rule at the tail.

        Bookends let an FTS5 hit anywhere in a long session yield the goal
        (opening) and the resolution (closing) on a single call — without
        loading the whole transcript.

        Returns ``{"window": [], "messages_before": 0, "messages_after": 0,
        "bookend_start": [], "bookend_end": []}`` when the anchor isn't in
        the session.

        ``keep_roles=None`` disables role filtering (raw window + raw
        bookends).
        """
    if bookend < 0:
        bookend = 0
    # Reuse the primitive — handles anchor-existence, content decoding,
    # tool_calls deserialisation, and boundary counts.
    primitive = self.get_messages_around(
        session_id, around_message_id, window=window
    )
    window_rows = primitive["window"]
    if not window_rows:
        return {
            "window": [],
            "messages_before": 0,
            "messages_after": 0,
            "bookend_start": [],
            "bookend_end": [],
        }
    # Apply role filter to the window, but never drop the anchor itself.
    if keep_roles is not None:
        keep_set = set(keep_roles)
        filtered_window = [
            m for m in window_rows
            if m.get("id") == around_message_id or m.get("role") in keep_set
        ]
    else:
        filtered_window = window_rows
    window_min_id = window_rows[0]["id"]
    window_max_id = window_rows[-1]["id"]
    # Fetch bookends only when there's room outside the window. SQL filters
    # by id range, role, and non-empty content — tool-call-only assistant
    # turns (content='' with tool_calls populated) are excluded so they
    # don't crowd out actual prose openings/closings.
    bookend_start_rows: List[Any] = []
    bookend_end_rows: List[Any] = []
    if bookend > 0:
        with self._lock:
            role_clause = ""
            role_params: list = []
            if keep_roles is not None:
                role_placeholders = ",".join("?" for _ in keep_roles)
                role_clause = f" AND role IN ({role_placeholders})"
                role_params = list(keep_roles)
            bookend_start_rows = self._conn.execute(
                f"SELECT * FROM messages "
                f"WHERE session_id = ? AND id < ?{role_clause} "
                f"AND length(content) > 0 "
                f"ORDER BY id ASC LIMIT ?",
                (session_id, window_min_id, *role_params, bookend),
            ).fetchall()
            bookend_end_rows = self._conn.execute(
                f"SELECT * FROM messages "
                f"WHERE session_id = ? AND id > ?{role_clause} "
                f"AND length(content) > 0 "
                f"ORDER BY id DESC LIMIT ?",
                (session_id, window_max_id, *role_params, bookend),
            ).fetchall()
            # End rows came back DESC for the LIMIT cap; flip to ASC.
            bookend_end_rows = list(reversed(bookend_end_rows))
    def _hydrate(row) -> Dict[str, Any]:
        msg = dict(row)
        if "content" in msg:
            msg["content"] = self._decode_content(msg["content"])
        if msg.get("tool_calls"):
            try:
                msg["tool_calls"] = json.loads(msg["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Failed to deserialize tool_calls in get_anchored_view, falling back to []"
                )
                msg["tool_calls"] = []
        return msg
    return {
        "window": filtered_window,
        "messages_before": primitive["messages_before"],
        "messages_after": primitive["messages_after"],
        "bookend_start": [_hydrate(r) for r in bookend_start_rows],
        "bookend_end": [_hydrate(r) for r in bookend_end_rows],
    }
