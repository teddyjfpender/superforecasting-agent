"""Session telegram operations behind the SessionDB API."""

import sqlite3
import time
from typing import Any, Dict, List, Optional


def enable_telegram_topic_mode(
    self,
    *,
    chat_id: str,
    user_id: str,
    has_topics_enabled: Optional[bool] = None,
    allows_users_to_create_topics: Optional[bool] = None,
) -> None:
    """Enable Telegram DM topic mode for one private chat/user.

    This method intentionally owns the explicit topic migration. Ordinary
    SessionDB startup must not create these side tables.
    """
    self.apply_telegram_topic_migration()
    now = time.time()

    def _to_int(value: Optional[bool]) -> Optional[int]:
        if value is None:
            return None
        return 1 if value else 0

    def _do(conn):
        conn.execute(
            """
                INSERT INTO telegram_dm_topic_mode (
                    chat_id, user_id, enabled, activated_at, updated_at,
                    has_topics_enabled, allows_users_to_create_topics,
                    capability_checked_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    enabled = 1,
                    updated_at = excluded.updated_at,
                    has_topics_enabled = excluded.has_topics_enabled,
                    allows_users_to_create_topics = excluded.allows_users_to_create_topics,
                    capability_checked_at = excluded.capability_checked_at
                """,
            (
                str(chat_id),
                str(user_id),
                now,
                now,
                _to_int(has_topics_enabled),
                _to_int(allows_users_to_create_topics),
                now,
            ),
        )

    self._execute_write(_do)


def disable_telegram_topic_mode(
    self,
    *,
    chat_id: str,
    clear_bindings: bool = True,
) -> None:
    """Disable Telegram DM topic mode for one private chat.

    When ``clear_bindings`` is True (default) the (chat_id, thread_id)
    bindings for this chat are also cleared so re-enabling later
    starts from a clean slate. Set to False if the operator wants to
    preserve bindings for a later re-enable.

    Never creates the topic-mode tables from scratch; if they don't
    exist there is nothing to disable and the call is a no-op.
    """

    def _do(conn):
        try:
            conn.execute(
                "UPDATE telegram_dm_topic_mode SET enabled = 0, updated_at = ? "
                "WHERE chat_id = ?",
                (time.time(), str(chat_id)),
            )
            if clear_bindings:
                conn.execute(
                    "DELETE FROM telegram_dm_topic_bindings WHERE chat_id = ?",
                    (str(chat_id),),
                )
        except sqlite3.OperationalError:
            # Tables don't exist yet — nothing to disable.
            return

    self._execute_write(_do)


def is_telegram_topic_mode_enabled(self, *, chat_id: str, user_id: str) -> bool:
    """Return whether Telegram DM topic mode is enabled for this chat/user."""
    with self._lock:
        try:
            row = self._conn.execute(
                """
                    SELECT enabled FROM telegram_dm_topic_mode
                    WHERE chat_id = ? AND user_id = ?
                    """,
                (str(chat_id), str(user_id)),
            ).fetchone()
        except sqlite3.OperationalError:
            return False
    if row is None:
        return False
    enabled = row["enabled"] if isinstance(row, sqlite3.Row) else row[0]
    return bool(enabled)


def get_telegram_topic_binding(
    self,
    *,
    chat_id: str,
    thread_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the session binding for a Telegram DM topic, if present."""
    with self._lock:
        try:
            row = self._conn.execute(
                """
                    SELECT * FROM telegram_dm_topic_bindings
                    WHERE chat_id = ? AND thread_id = ?
                    """,
                (str(chat_id), str(thread_id)),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return dict(row) if row else None


def list_telegram_topic_bindings_for_chat(
    self,
    *,
    chat_id: str,
) -> List[Dict[str, Any]]:
    """All Telegram DM topic bindings for one chat, newest first.

    Read-only; returns [] if the bindings table doesn't exist yet
    (does not trigger the topic-mode migration).
    """
    with self._lock:
        try:
            rows = self._conn.execute(
                "SELECT * FROM telegram_dm_topic_bindings "
                "WHERE chat_id = ? ORDER BY updated_at DESC",
                (str(chat_id),),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(row) for row in rows]


def get_telegram_topic_binding_by_session(
    self,
    *,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the Telegram DM topic binding for a given session_id, if present.

    Uses the UNIQUE INDEX on telegram_dm_topic_bindings(session_id) for an
    efficient reverse lookup. Returns None when the session has no binding or
    the table does not exist yet.
    """
    with self._lock:
        try:
            row = self._conn.execute(
                """
                    SELECT * FROM telegram_dm_topic_bindings
                    WHERE session_id = ?
                    """,
                (str(session_id),),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return dict(row) if row else None


def bind_telegram_topic(
    self,
    *,
    chat_id: str,
    thread_id: str,
    user_id: str,
    session_key: str,
    session_id: str,
    managed_mode: str = "auto",
) -> None:
    """Bind one Telegram DM topic thread to one agent session.

    An agent session may only be linked to one Telegram topic in MVP.
    Rebinding the same topic to the same session is idempotent; trying to
    link the same session to a different topic raises ValueError.
    """
    self.apply_telegram_topic_migration()
    now = time.time()
    chat_id = str(chat_id)
    thread_id = str(thread_id)
    user_id = str(user_id)
    session_key = str(session_key)
    session_id = str(session_id)

    def _do(conn):
        existing_session = conn.execute(
            """
                SELECT chat_id, thread_id FROM telegram_dm_topic_bindings
                WHERE session_id = ?
                """,
            (session_id,),
        ).fetchone()
        if existing_session is not None:
            linked_chat = (
                existing_session["chat_id"]
                if isinstance(existing_session, sqlite3.Row)
                else existing_session[0]
            )
            linked_thread = (
                existing_session["thread_id"]
                if isinstance(existing_session, sqlite3.Row)
                else existing_session[1]
            )
            if str(linked_chat) != chat_id or str(linked_thread) != thread_id:
                raise ValueError("session is already linked to another Telegram topic")
        conn.execute(
            """
                INSERT INTO telegram_dm_topic_bindings (
                    chat_id, thread_id, user_id, session_key, session_id,
                    managed_mode, linked_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, thread_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    session_key = excluded.session_key,
                    session_id = excluded.session_id,
                    managed_mode = excluded.managed_mode,
                    updated_at = excluded.updated_at
                """,
            (
                chat_id,
                thread_id,
                user_id,
                session_key,
                session_id,
                managed_mode,
                now,
                now,
            ),
        )

    self._execute_write(_do)


def is_telegram_session_linked_to_topic(self, *, session_id: str) -> bool:
    """Return True if an agent session is already bound to any Telegram DM topic.

    Read-only: does NOT trigger the telegram-topic migration. If the
    topic-mode tables have not been created yet (i.e. nobody has run
    ``/topic`` in this profile), the session is by definition unbound
    and we return False.
    """
    with self._lock:
        try:
            row = self._conn.execute(
                """
                    SELECT 1 FROM telegram_dm_topic_bindings
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                (str(session_id),),
            ).fetchone()
        except sqlite3.OperationalError:
            return False
    return row is not None


def list_unlinked_telegram_sessions_for_user(
    self,
    *,
    chat_id: str,
    user_id: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """List previous Telegram sessions for this user that are not bound to a topic.

    Read-only: does NOT trigger the telegram-topic migration. If the
    topic-mode tables are absent, fall back to a simpler query that
    just returns this user's Telegram sessions — there can't be any
    bindings yet.
    """
    with self._lock:
        try:
            rows = self._conn.execute(
                """
                    SELECT s.*,
                        COALESCE(
                            (SELECT SUBSTR(REPLACE(REPLACE(m.content, X'0A', ' '), X'0D', ' '), 1, 63)
                             FROM messages m
                             WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
                             ORDER BY m.timestamp, m.id LIMIT 1),
                            ''
                        ) AS _preview_raw,
                        COALESCE(
                            (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
                            s.started_at
                        ) AS last_active
                    FROM sessions s
                    WHERE s.source = 'telegram'
                      AND s.user_id = ?
                      AND NOT EXISTS (
                          SELECT 1 FROM telegram_dm_topic_bindings b
                          WHERE b.session_id = s.id
                      )
                    ORDER BY last_active DESC, s.started_at DESC
                    LIMIT ?
                    """,
                (str(user_id), int(limit)),
            ).fetchall()
        except sqlite3.OperationalError:
            # telegram_dm_topic_bindings doesn't exist yet — no bindings
            # means every telegram session for this user is "unlinked".
            rows = self._conn.execute(
                """
                    SELECT s.*,
                        COALESCE(
                            (SELECT SUBSTR(REPLACE(REPLACE(m.content, X'0A', ' '), X'0D', ' '), 1, 63)
                             FROM messages m
                             WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
                             ORDER BY m.timestamp, m.id LIMIT 1),
                            ''
                        ) AS _preview_raw,
                        COALESCE(
                            (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
                            s.started_at
                        ) AS last_active
                    FROM sessions s
                    WHERE s.source = 'telegram'
                      AND s.user_id = ?
                    ORDER BY last_active DESC, s.started_at DESC
                    LIMIT ?
                    """,
                (str(user_id), int(limit)),
            ).fetchall()
    sessions: List[Dict[str, Any]] = []
    for row in rows:
        session = dict(row)
        raw = str(session.pop("_preview_raw", "") or "").strip()
        session["preview"] = raw[:60] + ("..." if len(raw) > 60 else "") if raw else ""
        sessions.append(session)
    return sessions
