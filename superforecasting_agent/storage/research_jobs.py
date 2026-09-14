"""Frozen trigger admission and exclusive execution claims for research jobs."""

import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from superforecasting_agent.storage.process_identity import (
    host_identity,
    process_has_exited,
)
from superforecasting_agent.storage.sqlite import apply_wal_with_fallback


class JobTriggerJournal:
    """One profile's scheduled/webhook deliveries; retries never replace inputs."""

    def __init__(self, home: Path):
        self.path = home / "research-job-triggers.db"
        home.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            apply_wal_with_fallback(db, db_label=str(self.path))
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise ValueError("Unsupported job trigger journal version")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS triggers (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, trigger_key TEXT NOT NULL,
                    input_digest TEXT NOT NULL, specification TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('accepted','running','completed','failed','interrupted')),
                    owner TEXT, result TEXT, created REAL NOT NULL,
                    UNIQUE(job_id, trigger_key)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_running_job ON triggers(job_id) WHERE state='running';
                CREATE TABLE IF NOT EXISTS webhook_bindings (
                    trigger_key TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                    target_home TEXT NOT NULL, input_digest TEXT NOT NULL
                );
            """)
            with db:
                db.execute("BEGIN IMMEDIATE")
                columns = {row[1] for row in db.execute("PRAGMA table_info(triggers)")}
                for column, kind in (
                    ("owner_host", "TEXT"),
                    ("owner_pid", "INTEGER"),
                    ("owner_started", "REAL"),
                ):
                    if column not in columns:
                        db.execute(f"ALTER TABLE triggers ADD COLUMN {column} {kind}")
                db.execute("PRAGMA user_version=3")

    @staticmethod
    def _validate_identity(job_id: object, trigger_key: str, input_digest: str) -> None:
        if (
            not isinstance(job_id, str)
            or not 1 <= len(job_id) <= 256
            or not isinstance(trigger_key, str)
            or not 1 <= len(trigger_key) <= 1024
            or not isinstance(input_digest, str)
            or len(input_digest) != 64
            or any(char not in "0123456789abcdef" for char in input_digest)
        ):
            raise ValueError(
                "Bounded job/trigger identities and a SHA-256 input digest are required"
            )

    def bind_webhook(
        self, job_id: str, trigger_key: str, input_digest: str, target_home: Path
    ) -> None:
        """Pin a delivery's destination at its ingress profile before admission.

        A failed target admission leaves the binding intact. Retries may finish
        that admission, but a route edit cannot redirect the same delivery.
        """
        self._validate_identity(job_id, trigger_key, input_digest)
        target = str(target_home.resolve())
        expected = (job_id, target, input_digest)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            # Preserve local receipts written before ingress bindings existed.
            legacy = db.execute(
                "SELECT job_id,input_digest FROM triggers WHERE trigger_key=?",
                (trigger_key,),
            ).fetchall()
            if legacy and (
                target != str(self.path.parent.resolve())
                or any(row != (job_id, input_digest) for row in legacy)
            ):
                raise ValueError(
                    "Delivery conflicts with an existing local job receipt"
                )
            db.execute(
                "INSERT OR IGNORE INTO webhook_bindings VALUES (?,?,?,?)",
                (trigger_key, *expected),
            )
            bound = db.execute(
                "SELECT job_id,target_home,input_digest FROM webhook_bindings WHERE trigger_key=?",
                (trigger_key,),
            ).fetchone()
            if bound != expected:
                raise ValueError(
                    "Delivery is already bound to different job, profile or input"
                )

    def admit(self, job: dict[str, Any], trigger_key: str, input_digest: str) -> str:
        job_id = job.get("id")
        self._validate_identity(job_id, trigger_key, input_digest)
        specification = json.dumps(job, sort_keys=True, allow_nan=False)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id,input_digest FROM triggers WHERE job_id=? AND trigger_key=?",
                (job_id, trigger_key),
            ).fetchone()
            if row is not None:
                if row[1] != input_digest:
                    raise ValueError(
                        "Trigger identity conflicts with previously admitted input"
                    )
                return str(row[0])
            identity = uuid.uuid4().hex
            db.execute(
                "INSERT INTO triggers(id,job_id,trigger_key,input_digest,specification,state,created) VALUES (?,?,?,?,?,?,?)",
                (
                    identity,
                    job_id,
                    trigger_key,
                    input_digest,
                    specification,
                    "accepted",
                    time.time(),
                ),
            )
            return identity

    def pending(self) -> list[dict[str, Any]]:
        """Return admitted triggers awaiting execution in admission order."""
        with closing(sqlite3.connect(self.path)) as db:
            identities = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM triggers WHERE state='accepted' ORDER BY created,id"
                )
            ]
        return [self.get(identity) for identity in identities]

    def recover(self) -> int:
        """Retire positively exited owners without retrying uncertain effects."""
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            rows = list(db.execute("SELECT * FROM triggers WHERE state='running'"))
            changed = 0
            for row in rows:
                if process_has_exited(
                    row["owner_host"], row["owner_pid"], row["owner_started"]
                ):
                    db.execute(
                        "UPDATE triggers SET state='interrupted',result=? WHERE id=? AND owner=? AND state='running'",
                        (
                            json.dumps({
                                "error": "Execution owner exited; external effects may have occurred",
                                "automatic_retry": False,
                            }),
                            row["id"],
                            row["owner"],
                        ),
                    )
                    changed += 1
            return changed

    def claim(self, identity: str) -> str | None:
        import psutil

        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT job_id,state FROM triggers WHERE id=?", (identity,)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown job trigger")
            if (
                row[1] != "accepted"
                or db.execute(
                    "SELECT 1 FROM triggers WHERE job_id=? AND state='running'",
                    (row[0],),
                ).fetchone()
            ):
                return None
            owner = uuid.uuid4().hex
            db.execute(
                "UPDATE triggers SET state='running',owner=?,owner_host=?,owner_pid=?,owner_started=? WHERE id=?",
                (
                    owner,
                    host_identity(),
                    os.getpid(),
                    psutil.Process().create_time(),
                    identity,
                ),
            )
            return owner

    def get(self, identity: str) -> dict[str, Any]:
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT * FROM triggers WHERE id=?", (identity,)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown job trigger")
            return {
                **dict(row),
                "specification": json.loads(row["specification"]),
                "result": json.loads(row["result"])
                if row["result"] is not None
                else None,
            }

    def finish(
        self, identity: str, owner: str, state: str, result: dict[str, Any]
    ) -> None:
        if state not in {"completed", "failed", "interrupted"}:
            raise ValueError("Expected a terminal job outcome")
        encoded = json.dumps(result, sort_keys=True, allow_nan=False)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT owner,state,result FROM triggers WHERE id=?", (identity,)
            ).fetchone()
            if row is None or row[0] != owner:
                raise ValueError("Job trigger belongs to another execution owner")
            if row[1] != "running":
                if row[1:] == (state, encoded):
                    return
                raise ValueError("Job trigger already has a different outcome")
            db.execute(
                "UPDATE triggers SET state=?,result=? WHERE id=? AND owner=?",
                (state, encoded, identity, owner),
            )
