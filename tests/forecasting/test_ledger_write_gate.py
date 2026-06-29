"""Direct-ledger-write gate.

The desk agent has fabricated forecasts by scripting ``ForecastLedger`` directly
(importing it from an ad-hoc script and calling ``create_snapshot`` /
``create_question`` / ``record_panel_run``) — bypassing the calibration / panel /
evidence gates the gated forecast TOOL enforces on its commit path.

This guard refuses a forecast-producing WRITE attempted OUTSIDE a recognised
commit context. These tests pin BOTH directions, with the gate explicitly forced
ON (the suite-wide conftest defaults it OFF so the in-process library tests can
write freely; production defaults it ON):

  * a raw, out-of-context ``create_snapshot`` / ``create_question`` /
    ``record_panel_run`` is REFUSED (method-level ``ForecastingError``),
  * the REAL bypass vector — a raw ``_connect().execute("INSERT INTO …")`` that
    skips the methods entirely — is REFUSED at the CONNECTION level by the
    SQLite authorizer, inside the allow-context it succeeds, and reads always
    work,
  * READS are always allowed (audits / migrations script the ledger freely),
  * every allowlisted writer STILL writes fine with the gate ON — the forecast
    tool's commit flow, ``market_nightly.record_pending`` + ``score_matured``,
    ``cron_runner.run_due_reviews``, an operator seed script, a schema migration
    (``initialize_schema``), the CLI's own commands, and the public
    ``allow_ledger_writes`` context manager,
  * a non-forecast write (e.g. UPDATE question status / metadata) is NOT gated,
  * ``warn`` mode logs but does NOT refuse,
  * ``off`` mode is a no-op.
"""

from __future__ import annotations

import sqlite3

import pytest

from forecasting import ForecastLedger
from forecasting.models import ForecastingError, OutcomeSpace
from forecasting.ledger import (
    GATED_LEDGER_TABLES,
    allow_ledger_writes,
    forecast_commit_active,
    ledger_write_gate_mode,
)
from forecasting.market_nightly import record_pending, score_matured


@pytest.fixture()
def enforced(monkeypatch):
    """Force the gate ON (production default) for this test."""
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "on")
    assert ledger_write_gate_mode() == "on"
    yield


def _ledger(tmp_path):
    # initialize_schema runs in __init__ — a migration MUST work even with the
    # gate ON (constructing a ledger is not a forecast-producing write).
    return ForecastLedger(str(tmp_path / "gate.db"))


# ── 1. raw out-of-context writes are REFUSED ──────────────────────────────────


def test_raw_create_snapshot_refused(tmp_path, enforced):
    ledger = _ledger(tmp_path)
    # Seed a question THROUGH the allowed path so the snapshot has a target.
    with allow_ledger_writes(reason="test-setup"):
        q = ledger.create_question(
            title="Will the raw write be refused?",
            resolution_criteria="Resolves YES if the gate refuses the ad-hoc snapshot.",
            outcome_space=OutcomeSpace(),
        )
    with pytest.raises(ForecastingError) as exc:
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=0.5,
            rationale="ad-hoc scripted snapshot that must be refused",
        )
    assert "Direct ledger writes are gated" in str(exc.value)
    assert "forecast tool's commit flow" in str(exc.value)


def test_raw_create_question_refused(tmp_path, enforced):
    ledger = _ledger(tmp_path)
    with pytest.raises(ForecastingError):
        ledger.create_question(
            title="Will this raw question be refused?",
            resolution_criteria="Resolves YES if the gate refuses the ad-hoc question.",
            outcome_space=OutcomeSpace(),
        )


def test_raw_record_panel_run_refused(tmp_path, enforced):
    ledger = _ledger(tmp_path)
    with allow_ledger_writes(reason="test-setup"):
        q = ledger.create_question(
            title="Will the raw panel run be refused?",
            resolution_criteria="Resolves YES if the gate refuses the ad-hoc panel run.",
            outcome_space=OutcomeSpace(),
        )
    with pytest.raises(ForecastingError):
        ledger.record_panel_run(
            question_id=q.id,
            estimates=[
                {"perspective": "a", "probability": 0.4},
                {"perspective": "b", "probability": 0.6},
            ],
        )


# ── 1b. the REAL bypass: a raw _connect() INSERT is refused at the conn level ──


def _raw_insert_question(conn, qid: str = "raw-q") -> None:
    conn.execute(
        "INSERT INTO forecast_questions "
        "(id, title, description, resolution_criteria, created_at, outcome_space) "
        "VALUES (?, 't', '', 'c', '2026-01-01T00:00:00Z', '{}')",
        (qid,),
    )


def test_raw_connection_insert_refused_outside_context(tmp_path, enforced):
    """The method-name gate is bypassable via `led._connect()`; the SQLite
    authorizer is not. A raw forecast-producing INSERT outside a commit context
    must be DENIED at the connection level."""
    from forecasting.models import LedgerNotFoundError

    ledger = _ledger(tmp_path)
    with pytest.raises(sqlite3.DatabaseError) as exc:
        with ledger._connect() as conn:
            _raw_insert_question(conn)
    assert "not authorized" in str(exc.value).lower()
    # And nothing was written — the question does not exist.
    with pytest.raises(LedgerNotFoundError):
        ledger.get_question("raw-q")


def test_raw_connection_insert_allowed_inside_context(tmp_path, enforced):
    ledger = _ledger(tmp_path)
    with allow_ledger_writes(reason="test-raw-write"):
        with ledger._connect() as conn:
            _raw_insert_question(conn, "raw-ok")
    assert ledger.get_question("raw-ok") is not None


def test_raw_connection_read_always_allowed(tmp_path, enforced):
    ledger = _ledger(tmp_path)
    # No commit context — a raw SELECT must never be denied.
    with ledger._connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM forecast_snapshots").fetchone()
    assert row["n"] == 0


def test_raw_connection_insert_to_nonforecast_table_allowed(tmp_path, enforced):
    """Only the forecast-producing tables are gated. A raw INSERT into a
    non-forecast table (here: evidence_items) outside a commit context must NOT
    be denied by the authorizer — the rest of the library API + its scripts keep
    working with the gate ON. (The INSERT may still fail on a NOT NULL/FK
    constraint; that is a SCHEMA error, never an authorization 'not authorized'
    error, which is the only thing the gate raises.)"""
    ledger = _ledger(tmp_path)
    assert "evidence_items" not in GATED_LEDGER_TABLES
    try:
        with ledger._connect() as conn:
            conn.execute(
                "INSERT INTO evidence_items (id) VALUES (?)", ("ev-raw",)
            )
    except sqlite3.DatabaseError as e:
        # A constraint failure is fine; an authorization denial is NOT.
        assert "not authorized" not in str(e).lower(), (
            "authorizer wrongly denied a write to a non-forecast table"
        )


def test_nonforecast_update_to_gated_table_not_blocked(tmp_path, enforced):
    """UPDATE/DELETE on a gated table is NOT a forecast-producing CREATE — e.g.
    resolving / editing config UPDATEs forecast_questions.status outside any
    commit context. The authorizer must leave those alone (gate INSERT only)."""
    ledger = _ledger(tmp_path)
    with allow_ledger_writes(reason="test-setup"):
        q = ledger.create_question(
            title="Can a non-create UPDATE run with the gate on?",
            resolution_criteria="Resolves YES if the status UPDATE is not blocked.",
            outcome_space=OutcomeSpace(),
        )
    # A bare UPDATE (no INSERT) on the gated table, OUTSIDE a commit context.
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE forecast_questions SET status = 'closed' WHERE id = ?", (q.id,)
        )
    assert ledger.get_question(q.id).status == "closed"


# ── 2. READS are always allowed ───────────────────────────────────────────────


def test_reads_allowed_with_gate_on(tmp_path, enforced):
    ledger = _ledger(tmp_path)
    with allow_ledger_writes(reason="test-setup"):
        q = ledger.create_question(
            title="Is reading allowed?",
            resolution_criteria="Resolves YES if reads are never gated.",
            outcome_space=OutcomeSpace(),
        )
    # No commit context here — but reads must never raise.
    assert not forecast_commit_active()
    fetched = ledger.get_question(q.id)
    assert fetched.id == q.id
    assert isinstance(ledger.list_questions(), list)


# ── 3. allowlisted writers STILL write with the gate ON ───────────────────────


def test_allow_context_manager_permits_writes(tmp_path, enforced):
    ledger = _ledger(tmp_path)
    with allow_ledger_writes(reason="test"):
        assert forecast_commit_active()
        q = ledger.create_question(
            title="Does the context manager permit the write?",
            resolution_criteria="Resolves YES if the allowed context writes fine.",
            outcome_space=OutcomeSpace(),
        )
        snap = ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=0.5,
            rationale="committed inside the allowed context",
        )
    assert snap.forecast_id
    # Context closed -> the flag is reset.
    assert not forecast_commit_active()


def test_market_nightly_record_pending_and_score_matured_write(tmp_path, enforced):
    ledger = _ledger(tmp_path)
    market = {
        "id": "mkt-1",
        "question": "Will mkt-1 happen?",
        "probability": 0.6,
        "close_time": "2026-07-01T00:00:00Z",
    }
    # record_pending is allowlisted (decorated) -> writes fine with the gate ON.
    run = record_pending(ledger, [market], "2026-06-01T00:00:00Z", lambda m: 0.7)
    assert run.recorded, "record_pending must store the pending entry"
    # score_matured is allowlisted too -> runs (no matured entries yet) fine.
    result = score_matured(ledger, now="2026-06-02T00:00:00Z")
    assert isinstance(result, dict)


def test_forecast_tool_commit_writes_with_gate_on(tmp_path, enforced):
    from tools.forecasting_tool import forecast_ledger_tool

    db = str(tmp_path / "tool.db")
    created = forecast_ledger_tool(
        {
            "db": db,
            "action": "create_question",
            "title": "Does the gated forecast tool still commit?",
            "resolution_criteria": "Resolves YES if the tool's create_question writes.",
        }
    )
    assert '"success": true' in created or '"success":true' in created.replace(" ", "")


def test_migration_initialize_schema_writes_with_gate_on(tmp_path, enforced):
    # Constructing the ledger runs initialize_schema (DDL/migration) — must work
    # with the gate ON. A second explicit call is idempotent and also fine.
    ledger = _ledger(tmp_path)
    ledger.initialize_schema()  # must not raise
    assert ledger.db_path.exists()


def test_cron_runner_run_due_reviews_writes_with_gate_on(tmp_path, monkeypatch, enforced):
    """cron_runner.run_due_reviews is allowlisted (decorated) — it must be able
    to drive the create_snapshot commit path with the gate ON. Point it at a
    throwaway db with no due reviews; it must return cleanly (and, crucially,
    NOT raise the gate's ForecastingError)."""
    from forecasting import cron_runner

    # Seed a question THROUGH the allowed path so the db exists + is non-empty.
    ledger = _ledger(tmp_path)
    with allow_ledger_writes(reason="test-setup"):
        ledger.create_question(
            title="Does cron run with the gate on?",
            resolution_criteria="Resolves YES if run_due_reviews does not hit the gate.",
            outcome_space=OutcomeSpace(),
        )
    # run_due_reviews returns a concise report STRING (empty when nothing is
    # due). The point is that it drives the create_snapshot commit path without
    # tripping the gate's ForecastingError.
    out = cron_runner.run_due_reviews(db_path=str(ledger.db_path))
    assert isinstance(out, str)


def test_operator_seed_script_writes_with_gate_on(tmp_path, monkeypatch, enforced):
    """The sanctioned operator seed scripts wrap their writes in
    allow_ledger_writes, so they create questions/snapshots with the gate ON."""
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(tmp_path / "seed.db"))
    import importlib

    seed = importlib.import_module("scripts.seed_eval_questions")
    seed.main()  # must not raise the gate's ForecastingError

    ledger = ForecastLedger(str(tmp_path / "seed.db"))
    titles = {q.title for q in ledger.list_questions(status=None)}
    assert any("CPI-U" in t for t in titles), "seed script must have created questions"


# ── 4. mode flag: warn logs-but-allows; off is a no-op ────────────────────────


def test_warn_mode_allows_but_logs(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "warn")
    assert ledger_write_gate_mode() == "warn"
    ledger = _ledger(tmp_path)
    with caplog.at_level("WARNING"):
        # No commit context, but warn mode must NOT refuse.
        q = ledger.create_question(
            title="Does warn mode allow the write?",
            resolution_criteria="Resolves YES if warn mode logs but writes.",
            outcome_space=OutcomeSpace(),
        )
    assert q.id
    assert any("Direct ledger writes are gated" in r.message for r in caplog.records)


def test_off_mode_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "off")
    assert ledger_write_gate_mode() == "off"
    ledger = _ledger(tmp_path)
    # No commit context, no warning, no refusal.
    q = ledger.create_question(
        title="Is off mode a no-op?",
        resolution_criteria="Resolves YES if off mode never refuses.",
        outcome_space=OutcomeSpace(),
    )
    assert q.id
