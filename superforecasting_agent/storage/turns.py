"""Durable turn receipt; transport delivery is downstream of committed state."""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

T = TypeVar("T")


class TurnStore(Protocol):
    def _execute_write(self, fn: Callable[[sqlite3.Connection], T]) -> T: ...


TERMINAL = ("complete", "error", "interrupted")


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS tui_turns (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL,
        prompt TEXT NOT NULL, partial_text TEXT NOT NULL DEFAULT '',
        error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
        owner_pid INTEGER NOT NULL, owner_started REAL NOT NULL)""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS tui_turns_session ON tui_turns(session_id, created_at)"
    )
    # Session deletion and retention must erase the associated saved prompts.
    conn.execute("""CREATE TRIGGER IF NOT EXISTS delete_tui_turns
        AFTER DELETE ON sessions BEGIN
        DELETE FROM tui_turns WHERE session_id=OLD.id; END""")


def start(db: TurnStore, session_id: str, prompt: str) -> str:
    turn_id = uuid.uuid4().hex

    def write(conn: sqlite3.Connection):
        _schema(conn)
        conn.execute(
            "INSERT INTO tui_turns(id,session_id,status,prompt,created_at,updated_at,owner_pid,owner_started) VALUES (?,?,?,?,?,?,?,?)",
            (
                turn_id,
                session_id,
                "starting",
                str(prompt),
                time.time(),
                time.time(),
                os.getpid(),
                _process_started(os.getpid()),
            ),
        )

    db._execute_write(write)
    return turn_id


def transition(
    db: TurnStore,
    turn_id: str,
    status: str,
    *,
    delta: str | None = None,
    text: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    allowed = {"starting", "running", "cancelling", *TERMINAL}
    if status not in allowed:
        raise ValueError("invalid durable turn state")

    def write(conn: sqlite3.Connection):
        row = conn.execute("SELECT * FROM tui_turns WHERE id=?", (turn_id,)).fetchone()
        if row is None:
            raise ValueError("unknown durable turn")
        if row["status"] in TERMINAL:
            return dict(row)  # late events cannot reopen or rewrite the turn
        # Cancellation remains pending until the worker actually exits.
        next_status = (
            row["status"]
            if row["status"] == "cancelling" and status == "running"
            else status
        )
        partial = text if text is not None else row["partial_text"] + (delta or "")
        conn.execute(
            "UPDATE tui_turns SET status=?,partial_text=?,error=?,updated_at=? WHERE id=?",
            (next_status, partial, error, time.time(), turn_id),
        )
        return dict(
            conn.execute("SELECT * FROM tui_turns WHERE id=?", (turn_id,)).fetchone()
        )

    return db._execute_write(write)


def latest(
    db: TurnStore, session_id: str, *, recover: bool = False
) -> dict[str, Any] | None:
    def write(conn: sqlite3.Connection):
        _schema(conn)
        row = conn.execute(
            "SELECT * FROM tui_turns WHERE session_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        if recover and row["status"] not in TERMINAL:
            if _owner_alive(row):
                return {**dict(row), "owner_active": True}
            conn.execute(
                "UPDATE tui_turns SET status='interrupted',error='Gateway stopped before turn completion',updated_at=? WHERE id=?",
                (time.time(), row["id"]),
            )
            row = conn.execute(
                "SELECT * FROM tui_turns WHERE id=?", (row["id"],)
            ).fetchone()
        return dict(row)

    return db._execute_write(write)


def _process_started(pid: int) -> float:
    import psutil

    return psutil.Process(pid).create_time()


def _owner_alive(row: sqlite3.Row) -> bool:
    import psutil

    try:
        return _process_started(row["owner_pid"]) == row["owner_started"]
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return True  # uncertain ownership cannot authorize stealing a live turn


def reanchor(db: TurnStore, turn_id: str, session_id: str) -> None:
    """Follow a compression continuation without losing the in-flight receipt."""

    def write(conn: sqlite3.Connection):
        conn.execute(
            "UPDATE tui_turns SET session_id=?,updated_at=? WHERE id=? AND status NOT IN (?,?,?)",
            (session_id, time.time(), turn_id, *TERMINAL),
        )

    db._execute_write(write)
