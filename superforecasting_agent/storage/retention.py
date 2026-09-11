"""Session retention operations behind the SessionDB API."""

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def prune_empty_ghost_sessions(self, sessions_dir: "Optional[Path]" = None) -> int:
    """Remove empty TUI ghost sessions (no messages, no title, >24hr old)."""
    cutoff = time.time() - 86400  # Only sessions older than 24 hours
    def _do(conn):
        rows = conn.execute("""
                SELECT id FROM sessions
                WHERE source = 'tui'
                  AND title IS NULL
                  AND ended_at IS NOT NULL
                  AND started_at < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM messages WHERE messages.session_id = sessions.id
                  )
            """, (cutoff,)).fetchall()
        ids = [r[0] if isinstance(r, (tuple, list)) else r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"DELETE FROM sessions WHERE id IN ({placeholders})", ids
            )
        return ids
    removed_ids = self._execute_write(_do) or []
    # Clean up any on-disk session files (belt-and-suspenders)
    if sessions_dir and removed_ids:
        for sid in removed_ids:
            self._remove_session_files(sessions_dir, sid)
    return len(removed_ids)


def finalize_orphaned_compression_sessions(self) -> int:
    """Mark orphaned compression continuation sessions as ended.

        Targets child sessions that were never finalized: parent is ended
        with reason='compression', child has messages but no end_reason/ended_at
        and api_call_count=0.  Non-destructive: preserves all messages and sets
        end_reason='orphaned_compression'.  Fix for #20001.
        """
    cutoff = time.time() - 604800  # 7 days
    def _do(conn):
        now = time.time()
        result = conn.execute(
            """
                UPDATE sessions
                SET ended_at = ?,
                    end_reason = 'orphaned_compression'
                WHERE api_call_count = 0
                  AND end_reason IS NULL
                  AND ended_at IS NULL
                  AND started_at < ?
                  AND parent_session_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM sessions p
                      WHERE p.id = sessions.parent_session_id
                        AND p.end_reason = 'compression'
                        AND p.ended_at IS NOT NULL
                  )
                  AND EXISTS (
                      SELECT 1 FROM messages m
                      WHERE m.session_id = sessions.id
                  )
                """,
            (now, cutoff),
        )
        return result.rowcount
    return self._execute_write(_do) or 0


def clear_messages(self, session_id: str) -> None:
    """Delete all messages for a session and reset its counters."""
    def _do(conn):
        conn.execute(
            "DELETE FROM messages WHERE session_id = ?", (session_id,)
        )
        conn.execute(
            "UPDATE sessions SET message_count = 0, tool_call_count = 0 WHERE id = ?",
            (session_id,),
        )
    self._execute_write(_do)


def _remove_session_files(sessions_dir: Optional[Path], session_id: str) -> None:
    """Remove on-disk transcript files for a session.

        Cleans up ``{session_id}.json``, ``{session_id}.jsonl``, and any
        ``request_dump_{session_id}_*.json`` files left by the gateway.
        Silently skips files that don't exist and swallows OSError so a
        filesystem hiccup never blocks a DB operation.
        """
    if sessions_dir is None:
        return
    for suffix in (".json", ".jsonl"):
        p = sessions_dir / f"{session_id}{suffix}"
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    # request_dump files use session_id as a prefix component
    try:
        for p in sessions_dir.glob(f"request_dump_{session_id}_*.json"):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        pass


def delete_session(
    self,
    session_id: str,
    sessions_dir: Optional[Path] = None,
) -> bool:
    """Delete a session and all its messages.

        Child sessions are orphaned (parent_session_id set to NULL) rather
        than cascade-deleted, so they remain accessible independently.
        When *sessions_dir* is provided, also removes on-disk transcript
        files (``.json`` / ``.jsonl`` / ``request_dump_*``) for the deleted
        session. Returns True if the session was found and deleted.
        """
    def _do(conn):
        cursor = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE id = ?", (session_id,)
        )
        if cursor.fetchone()[0] == 0:
            return False
        # Orphan child sessions so FK constraint is satisfied
        conn.execute(
            "UPDATE sessions SET parent_session_id = NULL "
            "WHERE parent_session_id = ?",
            (session_id,),
        )
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return True
    deleted = self._execute_write(_do)
    if deleted:
        self._remove_session_files(sessions_dir, session_id)
    return deleted


def prune_sessions(
    self,
    older_than_days: int = 90,
    source: str = None,
    sessions_dir: Optional[Path] = None,
) -> int:
    """Delete sessions older than N days. Returns count of deleted sessions.

        Only prunes ended sessions (not active ones).  Child sessions outside
        the prune window are orphaned (parent_session_id set to NULL) rather
        than cascade-deleted.  When *sessions_dir* is provided, also removes
        on-disk transcript files (``.json`` / ``.jsonl`` /
        ``request_dump_*``) for every pruned session, outside the DB
        transaction.
        """
    cutoff = time.time() - (older_than_days * 86400)
    removed_ids: list[str] = []
    def _do(conn):
        if source:
            cursor = conn.execute(
                """SELECT id FROM sessions
                       WHERE started_at < ? AND ended_at IS NOT NULL AND source = ?""",
                (cutoff, source),
            )
        else:
            cursor = conn.execute(
                "SELECT id FROM sessions WHERE started_at < ? AND ended_at IS NOT NULL",
                (cutoff,),
            )
        session_ids = {row["id"] for row in cursor.fetchall()}
        if not session_ids:
            return 0
        # Orphan any sessions whose parent is about to be deleted
        placeholders = ",".join("?" * len(session_ids))
        conn.execute(
            f"UPDATE sessions SET parent_session_id = NULL "
            f"WHERE parent_session_id IN ({placeholders})",
            list(session_ids),
        )
        for sid in session_ids:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            removed_ids.append(sid)
        return len(session_ids)
    count = self._execute_write(_do)
    # Clean up on-disk files outside the DB transaction
    for sid in removed_ids:
        self._remove_session_files(sessions_dir, sid)
    return count


def get_meta(self, key: str) -> Optional[str]:
    """Read a value from the state_meta key/value store."""
    with self._lock:
        row = self._conn.execute(
            "SELECT value FROM state_meta WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return None
    return row["value"] if isinstance(row, sqlite3.Row) else row[0]


def set_meta(self, key: str, value: str) -> None:
    """Write a value to the state_meta key/value store."""
    def _do(conn):
        conn.execute(
            "INSERT INTO state_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    self._execute_write(_do)


def mutate_meta(self, key: str, update) -> str:
    """Read and replace metadata in one write transaction.

    The callback must be side-effect free: lock contention may retry it.
    Raising from the callback rolls back without changing the stored value.
    """
    def _do(conn):
        row = conn.execute("SELECT value FROM state_meta WHERE key = ?", (key,)).fetchone()
        current = row[0] if row is not None else None
        value = update(current)
        if not isinstance(value, str):
            raise TypeError("metadata update must return a string")
        conn.execute(
            "INSERT INTO state_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        return value
    return self._execute_write(_do)


def vacuum(self) -> None:
    """Run VACUUM to reclaim disk space after large deletes.

        SQLite does not shrink the database file when rows are deleted —
        freed pages just get reused on the next insert. After a prune that
        removed hundreds of sessions, the file stays bloated unless we
        explicitly VACUUM.

        VACUUM rewrites the entire DB, so it's expensive (seconds per
        100MB) and cannot run inside a transaction. It also acquires an
        exclusive lock, so callers must ensure no other writers are
        active. Safe to call at startup before the gateway/CLI starts
        serving traffic.
        """
    # VACUUM cannot be executed inside a transaction.
    with self._lock:
        # Best-effort WAL checkpoint first, then VACUUM.
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        self._conn.execute("VACUUM")


def maybe_auto_prune_and_vacuum(
    self,
    retention_days: int = 90,
    min_interval_hours: int = 24,
    vacuum: bool = True,
    sessions_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Idempotent auto-maintenance: prune old sessions + optional VACUUM.

        Records the last run timestamp in state_meta so subsequent calls
        within ``min_interval_hours`` no-op. Designed to be called once at
        startup from long-lived entrypoints (CLI, gateway, cron scheduler).

        When *sessions_dir* is provided, on-disk transcript files
        (``.json`` / ``.jsonl`` / ``request_dump_*``) for pruned sessions
        are removed as part of the same sweep (issue #3015).

        Never raises. On any failure, logs a warning and returns a dict
        with ``"error"`` set.

        Returns a dict with keys:
          - ``"skipped"`` (bool) — true if within min_interval_hours of last run
          - ``"pruned"`` (int)   — number of sessions deleted
          - ``"vacuumed"`` (bool) — true if VACUUM ran
          - ``"error"`` (str, optional) — present only on failure
        """
    result: Dict[str, Any] = {"skipped": False, "pruned": 0, "vacuumed": False}
    try:
        # Skip if another process/call did maintenance recently.
        last_raw = self.get_meta("last_auto_prune")
        now = time.time()
        if last_raw:
            try:
                last_ts = float(last_raw)
                if now - last_ts < min_interval_hours * 3600:
                    result["skipped"] = True
                    return result
            except (TypeError, ValueError):
                pass  # corrupt meta; treat as no prior run
        pruned = self.prune_sessions(
            older_than_days=retention_days,
            sessions_dir=sessions_dir,
        )
        result["pruned"] = pruned
        # Only VACUUM if we actually freed rows — VACUUM on a tight DB
        # is wasted I/O. Threshold keeps small DBs from paying the cost.
        if vacuum and pruned > 0:
            try:
                self.vacuum()
                result["vacuumed"] = True
            except Exception as exc:
                logger.warning("state.db VACUUM failed: %s", exc)
        # Record the attempt even if pruned == 0, so we don't retry
        # every startup within the min_interval_hours window.
        self.set_meta("last_auto_prune", str(now))
        if pruned > 0:
            logger.info(
                "state.db auto-maintenance: pruned %d session(s) older than %d days%s",
                pruned,
                retention_days,
                " + VACUUM" if result["vacuumed"] else "",
            )
    except Exception as exc:
        # Maintenance must never block startup. Log and return error marker.
        logger.warning("state.db auto-maintenance failed: %s", exc)
        result["error"] = str(exc)
    return result
