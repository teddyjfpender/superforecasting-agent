"""Session sessions operations behind the SessionDB API."""

import json
import re
import time
from typing import Any, Dict, Optional


def _insert_session_row(
    self,
    session_id: str,
    source: str,
    model: str | None = None,
    model_config: Dict[str, Any] | None = None,
    system_prompt: str | None = None,
    user_id: str | None = None,
    parent_session_id: str | None = None,
) -> None:
    """Shared INSERT OR IGNORE for session rows."""

    def _do(conn):
        conn.execute(
            """INSERT OR IGNORE INTO sessions (id, source, user_id, model, model_config,
                   system_prompt, parent_session_id, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                source,
                user_id,
                model,
                json.dumps(model_config) if model_config else None,
                system_prompt,
                parent_session_id,
                time.time(),
            ),
        )

    self._execute_write(_do)


def create_session(self, session_id: str, source: str, **kwargs) -> str:
    """Create a new session record. Returns the session_id."""
    self._insert_session_row(session_id, source, **kwargs)
    return session_id


def end_session(self, session_id: str, end_reason: str) -> None:
    """Mark a session as ended.

    No-ops when the session is already ended. The first end_reason wins:
    compression-split sessions must keep their ``end_reason = 'compression'``
    record even if a later stale ``end_session()`` call (e.g. from a
    desynced CLI session_id after ``/resume`` or ``/branch``) targets them
    with a different reason. Use ``reopen_session()`` first if you
    intentionally need to re-end a closed session with a new reason.
    """

    def _do(conn):
        conn.execute(
            "UPDATE sessions SET ended_at = ?, end_reason = ? "
            "WHERE id = ? AND ended_at IS NULL",
            (time.time(), end_reason, session_id),
        )

    self._execute_write(_do)


def reopen_session(self, session_id: str) -> None:
    """Clear ended_at/end_reason so a session can be resumed."""

    def _do(conn):
        conn.execute(
            "UPDATE sessions SET ended_at = NULL, end_reason = NULL WHERE id = ?",
            (session_id,),
        )

    self._execute_write(_do)


def update_system_prompt(self, session_id: str, system_prompt: str) -> None:
    """Store the full assembled system prompt snapshot."""

    def _do(conn):
        conn.execute(
            "UPDATE sessions SET system_prompt = ? WHERE id = ?",
            (system_prompt, session_id),
        )

    self._execute_write(_do)


def update_token_counts(
    self,
    session_id: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str | None = None,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
    estimated_cost_usd: Optional[float] = None,
    actual_cost_usd: Optional[float] = None,
    cost_status: Optional[str] = None,
    cost_source: Optional[str] = None,
    pricing_version: Optional[str] = None,
    billing_provider: Optional[str] = None,
    billing_base_url: Optional[str] = None,
    billing_mode: Optional[str] = None,
    api_call_count: int = 0,
    absolute: bool = False,
) -> None:
    """Update token counters and backfill model if not already set.

    When *absolute* is False (default), values are **incremented** — use
    this for per-API-call deltas (CLI path).

    When *absolute* is True, values are **set directly** — use this when
    the caller already holds cumulative totals (gateway path, where the
    cached agent accumulates across messages).
    """
    # Ensure the session row exists so the UPDATE doesn't silently affect
    # 0 rows.  Under concurrent load (cron + kanban + delegate_task) the
    # initial create_session() may have failed due to SQLite locking.
    # INSERT OR IGNORE is cheap and idempotent.
    self._insert_session_row(session_id, "unknown", model=model)
    if absolute:
        sql = """UPDATE sessions SET
                   input_tokens = ?,
                   output_tokens = ?,
                   cache_read_tokens = ?,
                   cache_write_tokens = ?,
                   reasoning_tokens = ?,
                   estimated_cost_usd = COALESCE(?, 0),
                   actual_cost_usd = CASE
                       WHEN ? IS NULL THEN actual_cost_usd
                       ELSE ?
                   END,
                   cost_status = COALESCE(?, cost_status),
                   cost_source = COALESCE(?, cost_source),
                   pricing_version = COALESCE(?, pricing_version),
                   billing_provider = COALESCE(billing_provider, ?),
                   billing_base_url = COALESCE(billing_base_url, ?),
                   billing_mode = COALESCE(billing_mode, ?),
                   model = COALESCE(model, ?),
                   api_call_count = ?
                   WHERE id = ?"""
    else:
        sql = """UPDATE sessions SET
                   input_tokens = input_tokens + ?,
                   output_tokens = output_tokens + ?,
                   cache_read_tokens = cache_read_tokens + ?,
                   cache_write_tokens = cache_write_tokens + ?,
                   reasoning_tokens = reasoning_tokens + ?,
                   estimated_cost_usd = COALESCE(estimated_cost_usd, 0) + COALESCE(?, 0),
                   actual_cost_usd = CASE
                       WHEN ? IS NULL THEN actual_cost_usd
                       ELSE COALESCE(actual_cost_usd, 0) + ?
                   END,
                   cost_status = COALESCE(?, cost_status),
                   cost_source = COALESCE(?, cost_source),
                   pricing_version = COALESCE(?, pricing_version),
                   billing_provider = COALESCE(billing_provider, ?),
                   billing_base_url = COALESCE(billing_base_url, ?),
                   billing_mode = COALESCE(billing_mode, ?),
                   model = COALESCE(model, ?),
                   api_call_count = COALESCE(api_call_count, 0) + ?
                   WHERE id = ?"""
    params = (
        input_tokens,
        output_tokens,
        cache_read_tokens,
        cache_write_tokens,
        reasoning_tokens,
        estimated_cost_usd,
        actual_cost_usd,
        actual_cost_usd,
        cost_status,
        cost_source,
        pricing_version,
        billing_provider,
        billing_base_url,
        billing_mode,
        model,
        api_call_count,
        session_id,
    )

    def _do(conn):
        conn.execute(sql, params)

    self._execute_write(_do)


def ensure_session(
    self,
    session_id: str,
    source: str = "unknown",
    model: str | None = None,
    **kwargs,
) -> str:
    """Ensure a session row exists (INSERT OR IGNORE). Accepts optional kwargs."""
    self._insert_session_row(session_id, source, model=model, **kwargs)
    return session_id


def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
    """Get a session by ID."""
    with self._lock:
        cursor = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def resolve_session_id(self, session_id_or_prefix: str) -> Optional[str]:
    """Resolve an exact or uniquely prefixed session ID to the full ID.

    Returns the exact ID when it exists. Otherwise treats the input as a
    prefix and returns the single matching session ID if the prefix is
    unambiguous. Returns None for no matches or ambiguous prefixes.
    """
    exact = self.get_session(session_id_or_prefix)
    if exact:
        return exact["id"]
    escaped = (
        session_id_or_prefix
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    with self._lock:
        cursor = self._conn.execute(
            "SELECT id FROM sessions WHERE id LIKE ? ESCAPE '\\' ORDER BY started_at DESC LIMIT 2",
            (f"{escaped}%",),
        )
        matches = [row["id"] for row in cursor.fetchall()]
    if len(matches) == 1:
        return matches[0]
    return None


def set_session_title(self, session_id: str, title: str) -> bool:
    """Set or update a session's title.

    Returns True if session was found and title was set.
    Raises ValueError if title is already in use by another session,
    or if the title fails validation (too long, invalid characters).
    Empty/whitespace-only strings are normalized to None (clearing the title).
    """
    title = self.sanitize_title(title)

    def _do(conn):
        if title:
            # Check uniqueness (allow the same session to keep its own title)
            cursor = conn.execute(
                "SELECT id FROM sessions WHERE title = ? AND id != ?",
                (title, session_id),
            )
            conflict = cursor.fetchone()
            if conflict:
                raise ValueError(
                    f"Title '{title}' is already in use by session {conflict['id']}"
                )
        cursor = conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            (title, session_id),
        )
        return cursor.rowcount

    rowcount = self._execute_write(_do)
    return rowcount > 0


def get_session_title(self, session_id: str) -> Optional[str]:
    """Get the title for a session, or None."""
    with self._lock:
        cursor = self._conn.execute(
            "SELECT title FROM sessions WHERE id = ?", (session_id,)
        )
        row = cursor.fetchone()
    return row["title"] if row else None


def get_session_by_title(self, title: str) -> Optional[Dict[str, Any]]:
    """Look up a session by exact title. Returns session dict or None."""
    with self._lock:
        cursor = self._conn.execute("SELECT * FROM sessions WHERE title = ?", (title,))
        row = cursor.fetchone()
    return dict(row) if row else None


def resolve_session_by_title(self, title: str) -> Optional[str]:
    """Resolve a title to a session ID, preferring the latest in a lineage.

    If the exact title exists, returns that session's ID.
    If not, searches for "title #N" variants and returns the latest one.
    If the exact title exists AND numbered variants exist, returns the
    latest numbered variant (the most recent continuation).
    """
    # First try exact match
    exact = self.get_session_by_title(title)
    # Also search for numbered variants: "title #2", "title #3", etc.
    # Escape SQL LIKE wildcards (%, _) in the title to prevent false matches
    escaped = title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with self._lock:
        cursor = self._conn.execute(
            "SELECT id, title, started_at FROM sessions "
            "WHERE title LIKE ? ESCAPE '\\' ORDER BY started_at DESC",
            (f"{escaped} #%",),
        )
        numbered = cursor.fetchall()
    if numbered:
        # Return the most recent numbered variant
        return numbered[0]["id"]
    elif exact:
        return exact["id"]
    return None


def get_next_title_in_lineage(self, base_title: str) -> str:
    """Generate the next title in a lineage (e.g., "my session" → "my session #2").

    Strips any existing " #N" suffix to find the base name, then finds
    the highest existing number and increments.
    """
    # Strip existing #N suffix to find the true base
    match = re.match(r"^(.*?) #(\d+)$", base_title)
    if match:
        base = match.group(1)
    else:
        base = base_title
    # Find all existing numbered variants
    # Escape SQL LIKE wildcards (%, _) in the base to prevent false matches
    escaped = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with self._lock:
        cursor = self._conn.execute(
            "SELECT title FROM sessions WHERE title = ? OR title LIKE ? ESCAPE '\\'",
            (base, f"{escaped} #%"),
        )
        existing = [row["title"] for row in cursor.fetchall()]
    if not existing:
        return base  # No conflict, use the base name as-is
    # Find the highest number
    max_num = 1  # The unnumbered original counts as #1
    for t in existing:
        m = re.match(r"^.* #(\d+)$", t)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"{base} #{max_num + 1}"


def get_compression_tip(self, session_id: str) -> Optional[str]:
    """Walk the compression-continuation chain forward and return the tip.

    A compression continuation is a child session where:
    1. The parent's ``end_reason = 'compression'``
    2. The child was created AFTER the parent was ended (started_at >= ended_at)

    The second condition distinguishes compression continuations from
    delegate subagents or branch children, which can also have a
    ``parent_session_id`` but were created while the parent was still live.

    Returns the session_id of the latest continuation in the chain, or the
    input ``session_id`` if it isn't part of a compression chain (or if the
    input itself doesn't exist).
    """
    current = session_id
    # Bound the walk defensively — compression chains this deep are
    # pathological and shouldn't happen in practice. 100 = plenty.
    for _ in range(100):
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id FROM sessions "
                "WHERE parent_session_id = ? "
                "  AND started_at >= ("
                "      SELECT ended_at FROM sessions "
                "      WHERE id = ? AND end_reason = 'compression'"
                "  ) "
                "ORDER BY started_at DESC LIMIT 1",
                (current, current),
            )
            row = cursor.fetchone()
        if row is None:
            return current
        current = row["id"]
    return current


def create_branch(
    self,
    session_id,
    parent_session_id,
    messages,
    *,
    title,
    source,
    model=None,
    model_config=None,
    end_parent=False,
):
    """Commit the branch identity, full transcript and optional parent end together."""
    from superforecasting_agent.storage.messages import _replace_messages

    title = self.sanitize_title(title)
    encoded_config = json.dumps(model_config) if model_config else None

    def write(conn):
        if (
            conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (parent_session_id,)
            ).fetchone()
            is None
        ):
            raise ValueError("parent session not found")
        if (
            title
            and conn.execute(
                "SELECT 1 FROM sessions WHERE title = ?", (title,)
            ).fetchone()
        ):
            raise ValueError(f"Title '{title}' is already in use")
        conn.execute(
            "INSERT INTO sessions (id, source, model, model_config, parent_session_id, started_at, title) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                source,
                model,
                encoded_config,
                parent_session_id,
                time.time(),
                title,
            ),
        )
        _replace_messages(self, conn, session_id, messages)
        if end_parent:
            conn.execute(
                "UPDATE sessions SET ended_at = ?, end_reason = 'branched' WHERE id = ? AND ended_at IS NULL",
                (time.time(), parent_session_id),
            )

    self._execute_write(write)
    return session_id
