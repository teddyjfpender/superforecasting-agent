"""The BACKUP job type end-to-end on the one detached-job runtime (Arc B): the
durable, online ledger backup + integrity check.

All state (the JobStore + the scratch ledger + its backups) lands under a pinned
per-test HERMES_HOME — never the operator's live home.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from forecasting.jobs import runtime
from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore
from forecasting.jobs.types import resolve
from forecasting.jobs.types import backup as backup_type
from forecasting.ledger import ForecastLedger


@pytest.fixture
def home(tmp_path, monkeypatch):
    # Pin both home env vars (get_agent_home checks SUPERFORECASTING_AGENT_HOME
    # first) so the JobStore + ForecastLedger(None) land in the tempdir.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("FORECAST_LEDGER_DB", raising=False)
    return tmp_path


def _ledger_db(home: Path) -> str:
    db = home / "ledger.db"
    ForecastLedger(db)  # create the schema
    return str(db)


# ── registration ─────────────────────────────────────────────────────────────


def test_backup_type_is_registered():
    bt = resolve("backup")
    assert bt.name == "backup"
    # A net-new durability capability: no legacy alias family, no LLM spend.
    assert bt.alias_namespace is None
    assert bt.spend_class == "free"
    assert bt.validate_spec is not None


def test_validate_spec_rejects_bad_retention():
    with pytest.raises(ValueError):
        backup_type.validate_spec({"keep_recent": "seven"})
    with pytest.raises(ValueError):
        backup_type.validate_spec({"weekly_weeks": -1})
    # Absent overrides are fine.
    backup_type.validate_spec({})
    backup_type.validate_spec({"keep_recent": 3, "weekly_weeks": 2})


# ── lifecycle ────────────────────────────────────────────────────────────────


def test_backup_job_runs_to_done(home, monkeypatch):
    db = _ledger_db(home)
    store = JobStore(home=home)
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type="backup", spec={"db": db}))

    events: list[dict] = []
    completed: list[dict] = []
    record = runtime.run(job_id, store=store, sink=events.append, on_complete=completed.append)

    assert record.status == "done"
    result = record.result
    assert result["integrity"] == "ok"
    assert result["bytes"] > 0
    assert "questions" in result["counts"]
    assert result["cancelled"] is False

    # The backup file is a readable db.
    conn = sqlite3.connect(result["path"])
    try:
        conn.execute("SELECT COUNT(*) FROM forecast_questions").fetchone()
    finally:
        conn.close()

    # Progress streamed the two phases plus a terminal; the backup metadata is
    # durably annotated for jobs.status / the desk.
    phases = [e.get("phase") for e in events]
    assert "backup" in phases and "integrity" in phases and "done" in phases
    persisted = store.read(job_id)
    assert "backup" in persisted.annotations
    assert completed and completed[0]["integrity"] == "ok"


def test_bad_db_marks_the_job_error(home):
    # A db path whose parent is a FILE (not a dir) can't be created → the ledger
    # ctor raises → the runtime records a whole-job error (never crashes).
    blocker = home / "not_a_dir"
    blocker.write_text("x")
    store = JobStore(home=home)
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type="backup", spec={"db": str(blocker / "ledger.db")}))

    errors: list[str] = []
    record = runtime.run(job_id, store=store, on_error=errors.append)
    assert record.status == "error"
    assert record.error
    assert errors


def test_cancel_before_backup_is_graceful(home, monkeypatch):
    db = _ledger_db(home)
    store = JobStore(home=home)
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type="backup", spec={"db": db}))
    store.request_cancel(job_id)

    completed: list[dict] = []
    errors: list[str] = []
    record = runtime.run(job_id, store=store, on_complete=completed.append, on_error=errors.append)
    assert record.status == "cancelled"
    assert record.result["cancelled"] is True
    assert errors == []


# ── thin CLI/cron surface ────────────────────────────────────────────────────


def test_start_job_wait_returns_result_and_lists(home):
    db = _ledger_db(home)
    job_id = backup_type.start_job({"db": db}, wait=True)
    record = backup_type.read_job(job_id)
    assert record["status"] == "done"
    assert record["result"]["integrity"] == "ok"

    listed = backup_type.list_jobs()
    assert any(r["job_id"] == job_id for r in listed)
    assert all(r["type"] == "backup" for r in listed)


def test_run_backup_cron_returns_zero_on_clean_backup(home, capsys):
    db = _ledger_db(home)
    rc = backup_type.run_backup_cron(db_path=db)
    assert rc == 0
    out = capsys.readouterr().out
    assert "forecast backup" in out
    assert "integrity=ok" in out
