"""Transactional background research outcomes and pending delivery records.

Execution owners must prove admission before starting work. A notification is
only a hint: pending events remain queryable until their consumer acknowledges
successful delivery. This store never retries model calls or external effects.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from superforecasting_agent.storage.sqlite import apply_wal_with_fallback

TERMINAL = frozenset({"completed", "error", "interrupted", "rejected"})


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)


def _host_identity() -> str:
    """Scope PID observations to the same named machine and network identity."""
    return hashlib.sha256(
        f"{socket.gethostname()}:{uuid.getnode()}".encode()
    ).hexdigest()


class BackgroundResearchJournal:
    def __init__(self, home: Path):
        self.path = home / "background-research.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            apply_wal_with_fallback(db, db_label=str(self.path))
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError("Unsupported background research journal version")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, batch TEXT NOT NULL, session TEXT NOT NULL,
                    owner TEXT NOT NULL, delivery_group TEXT, specification TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN
                        ('accepted','running','completed','error','interrupted','rejected')),
                    result TEXT, position INTEGER NOT NULL, created REAL NOT NULL, finished REAL
                );
                CREATE INDEX IF NOT EXISTS tasks_session ON tasks(session, created);
                CREATE INDEX IF NOT EXISTS tasks_batch ON tasks(batch, delivery_group);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, event_key TEXT NOT NULL UNIQUE,
                    session TEXT NOT NULL, payload TEXT NOT NULL,
                    created REAL NOT NULL, acknowledged REAL
                );
                CREATE TABLE IF NOT EXISTS owners (
                    id TEXT PRIMARY KEY, host TEXT NOT NULL, pid INTEGER NOT NULL,
                    started REAL NOT NULL
                );
                PRAGMA user_version=2;
            """)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            with db:
                yield db

    def admit(
        self, tasks: list[dict[str, Any]], *, session: str, owner: str
    ) -> list[str]:
        """Freeze an entire bounded batch before any member can run."""
        if not owner or not session or not 1 <= len(tasks) <= 64:
            raise ValueError(
                "Background admission requires an owner, session and bounded tasks"
            )
        specifications = []
        for task in tasks:
            if not isinstance(task.get("goal"), str) or not task["goal"].strip():
                raise ValueError("Every background task requires a goal")
            group = task.get("delivery_group")
            if group is not None and (
                not isinstance(group, str) or not 1 <= len(group) <= 128
            ):
                raise ValueError("delivery_group must be a nonempty bounded string")
            specifications.append((_json(task), group))
        batch, created = uuid.uuid4().hex, time.time()
        ids = [f"deleg_{uuid.uuid4().hex}" for _ in tasks]
        from superforecasting_agent.storage.turns import _process_started

        with self._transaction() as db:
            identity = (_host_identity(), os.getpid(), _process_started(os.getpid()))
            previous = db.execute(
                "SELECT host,pid,started FROM owners WHERE id=?", (owner,)
            ).fetchone()
            if previous is not None and tuple(previous) != identity:
                raise ValueError("Background owner identity cannot be replaced")
            db.execute(
                "INSERT OR IGNORE INTO owners VALUES (?,?,?,?)", (owner, *identity)
            )
            db.executemany(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, 'accepted', NULL, ?, ?, NULL)",
                [
                    (task_id, batch, session, owner, group, spec, index, created)
                    for index, (task_id, (spec, group)) in enumerate(
                        zip(ids, specifications)
                    )
                ],
            )
        return ids

    def start(self, task_id: str, owner: str) -> None:
        with self._transaction() as db:
            changed = db.execute(
                "UPDATE tasks SET state='running' WHERE id=? AND owner=? AND state='accepted'",
                (task_id, owner),
            ).rowcount
            if not changed:
                raise ValueError(
                    "Background task cannot start without fresh owned admission"
                )

    def finish(
        self, task_id: str, owner: str, state: str, result: dict[str, Any]
    ) -> None:
        if state not in TERMINAL:
            raise ValueError("Invalid terminal background state")
        encoded = _json(result)
        with self._transaction() as db:
            task = db.execute(
                "SELECT * FROM tasks WHERE id=? AND owner=?", (task_id, owner)
            ).fetchone()
            if task is None:
                raise ValueError("Background task owner mismatch")
            if task["state"] in TERMINAL:
                if task["state"] == state and task["result"] == encoded:
                    return
                raise ValueError("Conflicting background completion")
            if task["state"] == "accepted" and state == "completed":
                raise ValueError("Unstarted background task cannot complete")
            db.execute(
                "UPDATE tasks SET state=?, result=?, finished=? WHERE id=?",
                (state, encoded, time.time(), task_id),
            )
            members = list(
                db.execute(
                    "SELECT * FROM tasks WHERE batch=? AND delivery_group IS ? ORDER BY created,position,id",
                    (task["batch"], task["delivery_group"]),
                )
            )
            current = next(member for member in members if member["id"] == task_id)
            if task["delivery_group"] is None:
                self._event(
                    db, [task_id, "complete"], task["session"], [current], "complete"
                )
            else:
                if state != "completed":
                    self._event(
                        db,
                        [task_id, "failure"],
                        task["session"],
                        [current],
                        "member_failure",
                    )
                if all(member["state"] in TERMINAL for member in members):
                    self._event(
                        db,
                        [task["batch"], task["delivery_group"], "complete"],
                        task["session"],
                        members,
                        "group_complete",
                    )

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        key: list[str],
        session: str,
        members: list[sqlite3.Row],
        kind: str,
    ) -> None:
        payload = {
            "kind": kind,
            "tasks": [BackgroundResearchJournal._task(row) for row in members],
        }
        db.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, NULL)",
            (uuid.uuid4().hex, _json(key), session, _json(payload), time.time()),
        )

    @staticmethod
    def _task(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "delegation_id": row["id"],
            "batch_id": row["batch"],
            "task_index": row["position"],
            "session_key": row["session"],
            "status": row["state"],
            "specification": json.loads(row["specification"]),
            "result": json.loads(row["result"]) if row["result"] else None,
            "dispatched_at": row["created"],
            "completed_at": row["finished"],
        }

    def tasks(self, session: str | None) -> list[dict[str, Any]]:
        with self._transaction() as db:
            return [
                self._task(row)
                for row in db.execute(
                    "SELECT * FROM tasks WHERE (? IS NULL OR session=?) ORDER BY created,position,id",
                    (session, session),
                )
            ]

    def recover(self, session: str) -> int:
        """Mark only positively dead local owners interrupted; never rerun work.

        Foreign hosts, legacy admissions without identity and inaccessible
        processes remain unconfirmed. Their absence from a local registry does
        not prove death.
        """
        import psutil

        from superforecasting_agent.storage.turns import _process_started

        with self._transaction() as db:
            candidates = list(
                db.execute(
                    "SELECT t.id,t.owner,o.host,o.pid,o.started FROM tasks t JOIN owners o ON o.id=t.owner "
                    "WHERE t.session=? AND t.state IN ('accepted','running')",
                    (session,),
                )
            )
        recovered = 0
        for row in candidates:
            if row["host"] != _host_identity():
                continue
            try:
                dead = _process_started(row["pid"]) != row["started"]
            except psutil.NoSuchProcess:
                dead = True
            except (psutil.AccessDenied, OSError):
                continue
            if dead:
                try:
                    self.finish(
                        row["id"],
                        row["owner"],
                        "interrupted",
                        {
                            "error": "Execution owner exited before durable completion; external effects may have occurred",
                            "recovery": "owner_exited",
                            "automatic_retry": False,
                        },
                    )
                except ValueError:
                    # A concurrent recovery or final outcome may have committed.
                    continue
                recovered += 1
        return recovered

    def pending(self, session: str) -> list[dict[str, Any]]:
        with self._transaction() as db:
            return [
                {"event_id": row["id"], **json.loads(row["payload"])}
                for row in db.execute(
                    "SELECT * FROM events WHERE session=? AND acknowledged IS NULL ORDER BY created,id",
                    (session,),
                )
            ]

    def acknowledge(self, event_id: str, session: str) -> None:
        with self._transaction() as db:
            changed = db.execute(
                "UPDATE events SET acknowledged=COALESCE(acknowledged,?) WHERE id=? AND session=?",
                (time.time(), event_id, session),
            ).rowcount
            if not changed:
                raise ValueError("Background event does not belong to this session")
