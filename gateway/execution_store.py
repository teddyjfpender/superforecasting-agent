"""Durable execution and delivery state for hosted gateway runs.

The live gateway may cache active agents and notification queues, but this
store is the source of truth for pollable run state and replayable events.
SQLite keeps classic/local deployments dependency-free; the schema and API are
deliberately small so a hosted Postgres implementation can provide the same
contract without changing transports or renderers.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
ACTIVE_RUN_STATUSES = frozenset({"queued", "running", "waiting_for_approval", "stopping"})
RUN_STATUSES = TERMINAL_RUN_STATUSES | ACTIVE_RUN_STATUSES


class ExecutionStore:
    """Thread-safe SQLite store for executions, events, and delivery obligations."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            from hermes_constants import get_hermes_home

            db_path = get_hermes_home() / "execution_store.db"
        if str(db_path) != ":memory:":
            Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=2)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        from hermes_state import apply_wal_with_fallback

        apply_wal_with_fallback(self._conn, db_label="execution_store.db")
        self._init_schema()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_threads (
                    thread_key TEXT PRIMARY KEY,
                    platform TEXT NOT NULL DEFAULT 'api_server',
                    sandbox_id TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_messages (
                    message_id TEXT PRIMARY KEY,
                    thread_key TEXT NOT NULL REFERENCES agent_threads(thread_key) ON DELETE CASCADE,
                    client_message_id TEXT,
                    role TEXT NOT NULL,
                    parts TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS agent_messages_thread_client_id
                    ON agent_messages(thread_key, client_message_id)
                    WHERE client_message_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS agent_executions (
                    run_id TEXT PRIMARY KEY,
                    thread_key TEXT NOT NULL REFERENCES agent_threads(thread_key) ON DELETE CASCADE,
                    session_id TEXT NOT NULL,
                    idempotency_key TEXT,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS agent_executions_thread_idempotency
                    ON agent_executions(thread_key, idempotency_key)
                    WHERE idempotency_key IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS agent_executions_one_active
                    ON agent_executions(thread_key)
                    WHERE status IN ('queued', 'running', 'waiting_for_approval', 'stopping');

                CREATE TABLE IF NOT EXISTS agent_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES agent_executions(run_id) ON DELETE CASCADE,
                    thread_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS agent_events_run_event
                    ON agent_events(run_id, event_id);

                CREATE TABLE IF NOT EXISTS delivery_obligations (
                    obligation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES agent_executions(run_id) ON DELETE CASCADE,
                    platform TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    last_event_id INTEGER NOT NULL DEFAULT 0,
                    renderer_state TEXT NOT NULL DEFAULT '{}',
                    lease_owner TEXT,
                    lease_expires_at REAL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def create_run(
        self,
        run_id: str,
        *,
        thread_key: str,
        session_id: str,
        data: dict[str, Any],
        idempotency_key: str | None = None,
        platform: str = "api_server",
        initial_message: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = time.time()
        payload = dict(data)
        payload.setdefault("run_id", run_id)
        payload.setdefault("created_at", now)
        payload["updated_at"] = now
        status = str(payload.get("status", "queued"))
        if status not in RUN_STATUSES:
            raise ValueError(f"invalid run status {status!r}")
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO agent_threads
                   (thread_key, platform, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(thread_key) DO UPDATE SET updated_at = excluded.updated_at""",
                (thread_key, platform, now, now),
            )
            if initial_message is not None:
                cursor = self._conn.execute(
                    """INSERT OR IGNORE INTO agent_messages
                       (message_id, thread_key, client_message_id, role, parts, metadata, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        initial_message["message_id"], thread_key,
                        initial_message.get("client_message_id"),
                        initial_message.get("role", "user"),
                        json.dumps(initial_message.get("parts"), default=str),
                        json.dumps(initial_message.get("metadata") or {}, default=str), now,
                    ),
                )
                if cursor.rowcount != 1:
                    return None
            self._conn.execute(
                """INSERT INTO agent_executions
                   (run_id, thread_key, session_id, idempotency_key, status, data, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    thread_key,
                    session_id,
                    idempotency_key,
                    status,
                    json.dumps(payload, default=str),
                    now,
                    now,
                ),
            )
        return payload

    def append_message(
        self,
        *,
        message_id: str,
        thread_key: str,
        client_message_id: str | None,
        role: str,
        parts: Any,
        metadata: dict[str, Any] | None = None,
        platform: str = "api_server",
    ) -> bool:
        """Persist one inbound message, returning False for a redelivery."""
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO agent_threads
                   (thread_key, platform, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(thread_key) DO UPDATE SET updated_at = excluded.updated_at""",
                (thread_key, platform, now, now),
            )
            cursor = self._conn.execute(
                """INSERT OR IGNORE INTO agent_messages
                   (message_id, thread_key, client_message_id, role, parts, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    message_id,
                    thread_key,
                    client_message_id,
                    role,
                    json.dumps(parts, default=str),
                    json.dumps(metadata or {}, default=str),
                    now,
                ),
            )
        return cursor.rowcount == 1

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM agent_executions WHERE run_id = ?", (run_id,)
            ).fetchone()
        return json.loads(row["data"]) if row else None

    def get_run_by_idempotency(
        self, thread_key: str, idempotency_key: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """SELECT data FROM agent_executions
                   WHERE thread_key = ? AND idempotency_key = ?""",
                (thread_key, idempotency_key),
            ).fetchone()
        return json.loads(row["data"]) if row else None

    def list_messages(self, thread_key: str) -> list[dict[str, Any]]:
        """Return a thread's durable messages in arrival order."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT message_id, client_message_id, role, parts, metadata, created_at
                   FROM agent_messages WHERE thread_key = ? ORDER BY created_at, rowid""",
                (thread_key,),
            ).fetchall()
        return [
            {
                "message_id": row["message_id"],
                "client_message_id": row["client_message_id"],
                "role": row["role"],
                "parts": json.loads(row["parts"]),
                "metadata": json.loads(row["metadata"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def update_run(self, run_id: str, status: str, **fields: Any) -> dict[str, Any] | None:
        if status not in RUN_STATUSES:
            raise ValueError(f"invalid run status {status!r}")
        now = time.time()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT status, data FROM agent_executions WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["data"])
            if row["status"] in TERMINAL_RUN_STATUSES and status != row["status"]:
                return payload
            payload.update(fields)
            payload.update({"run_id": run_id, "status": status, "updated_at": now})
            self._conn.execute(
                "UPDATE agent_executions SET status = ?, data = ?, updated_at = ? WHERE run_id = ?",
                (status, json.dumps(payload, default=str), now, run_id),
            )
        return payload

    def count_active_runs(self) -> int:
        placeholders = ",".join("?" for _ in ACTIVE_RUN_STATUSES)
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM agent_executions WHERE status IN ({placeholders})",
                tuple(ACTIVE_RUN_STATUSES),
            ).fetchone()
        return int(row["n"])

    def fail_active_runs(self, reason: str = "control_plane_restarted") -> list[str]:
        """Terminalize in-process runs that cannot survive a control-plane restart."""
        now = time.time()
        recovered: list[str] = []
        placeholders = ",".join("?" for _ in ACTIVE_RUN_STATUSES)
        with self._lock, self._conn:
            rows = self._conn.execute(
                f"SELECT run_id, thread_key, data FROM agent_executions WHERE status IN ({placeholders})",
                tuple(ACTIVE_RUN_STATUSES),
            ).fetchall()
            for row in rows:
                payload = json.loads(row["data"])
                payload.update({
                    "status": "failed", "error": reason, "last_event": "run.failed",
                    "updated_at": now,
                })
                self._conn.execute(
                    "UPDATE agent_executions SET status = 'failed', data = ?, updated_at = ? WHERE run_id = ?",
                    (json.dumps(payload, default=str), now, row["run_id"]),
                )
                event = {
                    "event": "run.failed", "run_id": row["run_id"],
                    "timestamp": now, "error": reason,
                }
                self._conn.execute(
                    """INSERT INTO agent_events(run_id, thread_key, event_type, payload, created_at)
                       VALUES (?, ?, 'run.failed', ?, ?)""",
                    (row["run_id"], row["thread_key"], json.dumps(event), now),
                )
                recovered.append(str(row["run_id"]))
        return recovered

    def append_event(self, run_id: str, event: dict[str, Any]) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        now = time.time()
        payload = dict(event)
        event_type = str(payload.get("event") or payload.get("type") or "event")
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """INSERT INTO agent_events(run_id, thread_key, event_type, payload, created_at)
                   SELECT ?, thread_key, ?, ?, ? FROM agent_executions WHERE run_id = ?""",
                (run_id, event_type, json.dumps(payload, default=str), now, run_id),
            )
            event_id = int(cursor.lastrowid)
        payload["event_id"] = event_id
        return payload

    def list_events(self, run_id: str, *, after_event_id: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT event_id, payload FROM agent_events
                   WHERE run_id = ? AND event_id > ? ORDER BY event_id""",
                (run_id, max(0, int(after_event_id))),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload"])
            payload["event_id"] = int(row["event_id"])
            events.append(payload)
        return events

    def create_delivery(
        self,
        obligation_id: str,
        *,
        run_id: str,
        platform: str,
        destination: str,
        renderer_state: dict[str, Any] | None = None,
    ) -> None:
        """Register a renderer obligation idempotently."""
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR IGNORE INTO delivery_obligations
                   (obligation_id, run_id, platform, destination, renderer_state,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    obligation_id, run_id, platform, destination,
                    json.dumps(renderer_state or {}, default=str), now, now,
                ),
            )

    def claim_delivery(
        self, *, platform: str, owner: str, lease_seconds: float = 30,
    ) -> dict[str, Any] | None:
        """Lease the oldest pending delivery for one renderer process."""
        now = time.time()
        expires = now + max(1.0, float(lease_seconds))
        with self._lock, self._conn:
            row = self._conn.execute(
                """SELECT * FROM delivery_obligations
                   WHERE platform = ? AND state IN ('pending', 'delivering')
                     AND (lease_expires_at IS NULL OR lease_expires_at < ?)
                   ORDER BY created_at LIMIT 1""",
                (platform, now),
            ).fetchone()
            if row is None:
                return None
            cursor = self._conn.execute(
                """UPDATE delivery_obligations
                   SET state = 'delivering', lease_owner = ?, lease_expires_at = ?,
                       attempts = attempts + 1, updated_at = ?
                   WHERE obligation_id = ?
                     AND (lease_expires_at IS NULL OR lease_expires_at < ?)""",
                (owner, expires, now, row["obligation_id"], now),
            )
            if cursor.rowcount != 1:
                return None
            claimed = dict(row)
            claimed.update({
                "state": "delivering", "lease_owner": owner,
                "lease_expires_at": expires, "attempts": int(row["attempts"]) + 1,
            })
            claimed["renderer_state"] = json.loads(claimed["renderer_state"])
            return claimed

    def checkpoint_delivery(
        self,
        obligation_id: str,
        *,
        owner: str,
        last_event_id: int,
        renderer_state: dict[str, Any],
        state: str = "delivering",
    ) -> bool:
        """Persist renderer progress; only the active lease owner may write."""
        if state not in {"delivering", "completed", "failed"}:
            raise ValueError(f"invalid delivery state {state!r}")
        now = time.time()
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """UPDATE delivery_obligations
                   SET last_event_id = MAX(last_event_id, ?), renderer_state = ?, state = ?, updated_at = ?,
                       lease_owner = CASE WHEN ? = 'delivering' THEN lease_owner ELSE NULL END,
                       lease_expires_at = CASE WHEN ? = 'delivering' THEN lease_expires_at ELSE NULL END
                   WHERE obligation_id = ? AND lease_owner = ?""",
                (
                    max(0, int(last_event_id)), json.dumps(renderer_state, default=str),
                    state, now, state, state, obligation_id, owner,
                ),
            )
        return cursor.rowcount == 1

    def delete_terminal_before(self, cutoff: float) -> int:
        placeholders = ",".join("?" for _ in TERMINAL_RUN_STATUSES)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"DELETE FROM agent_executions WHERE status IN ({placeholders}) AND updated_at < ?",
                (*TERMINAL_RUN_STATUSES, float(cutoff)),
            )
        return int(cursor.rowcount)
