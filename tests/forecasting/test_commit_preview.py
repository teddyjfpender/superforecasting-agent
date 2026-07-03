"""Pre-commit preview: see the gate/saturation verdict BEFORE writing a snapshot.

Born from the operator's Senate-batch audit: agents committed a snapshot, read
the saturation advisories in the RESULT, then immediately re-committed an
"administrative remediation" to clear them — TWO snapshots a minute apart on
every question, because there was NO way to see the verdict before writing.

`create_snapshot(preview=True)` / `update_forecast preview:true` run every gate
and the saturation/observe scoring IDENTICALLY up to the first ledger WRITE, then
return the verdict instead of inserting:
  - all gates passed  -> {preview, would_commit: True, saturation, probability_or_distribution, metadata}
  - a gate refused it -> {preview, would_commit: False, blockers: [str(err)]}  (no raise)
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from forecasting.ledger import ForecastLedger, allow_ledger_writes
from tools.forecasting_tool import forecast_ledger_tool


@pytest.fixture(autouse=True)
def _gate_on(monkeypatch):
    # The direct-write gate + connection-level authorizer ON (the production
    # default) for every test here, so the no-write proof is airtight: an
    # accidental INSERT would fail LOUDLY.
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "on")


@pytest.fixture()
def ledger(tmp_path):
    led = ForecastLedger(tmp_path / "preview.db")
    with allow_ledger_writes("test seed"):
        led.create_question(
            title="Will the preview path write nothing?",
            resolution_criteria=(
                "Resolves YES if no snapshot row is written to the ledger on a "
                "preview call by 2026-12-31."
            ),
            close_time="2026-12-31T00:00:00Z",
        )
    return led


def _qid(led):
    return led.list_questions()[0].id


# --- 1. THE NO-WRITE PROOF --------------------------------------------------

def test_preview_writes_nothing_even_when_inserts_are_denied(ledger):
    qid = _qid(ledger)

    # The connection-level authorizer is ARMED: any INSERT into a gated table
    # OUTSIDE a commit context is refused at compile time ("not authorized").
    # Prove it here, so the preview's success below is a genuine no-write result
    # and not a silently-disabled gate.
    with pytest.raises(sqlite3.DatabaseError) as excinfo:
        with ledger._connect() as conn:
            conn.execute(
                "INSERT INTO forecast_snapshots (forecast_id, question_id, created_at, as_of) "
                "VALUES ('fs_denied', ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
                (qid,),
            )
    assert "not authorized" in str(excinfo.value)

    before = len(ledger.list_snapshots(qid))

    # Preview OUTSIDE any allow_ledger_writes context, gate ON. It must SUCCEED
    # (it never reaches an INSERT) and write nothing.
    record = ledger.create_snapshot(
        question_id=qid,
        probability_or_distribution=0.4,
        rationale="Clean rationale for the preview no-write proof.",
        forecast_origin="live",
        preview=True,
    )

    assert record["preview"] is True
    assert record["would_commit"] is True
    assert record["saturation"] is not None
    assert "score" in record["saturation"]
    # Nothing was written: count pinned, no current snapshot.
    assert len(ledger.list_snapshots(qid)) == before
    assert ledger.get_current_snapshot(qid) is None


# --- 2. PREVIEW PARITY ------------------------------------------------------

def test_preview_saturation_matches_the_real_commit(ledger):
    qid = _qid(ledger)
    kwargs = dict(
        question_id=qid,
        probability_or_distribution=0.4,
        rationale="Clean rationale, identical for preview and commit.",
        forecast_origin="live",
    )

    preview = ledger.create_snapshot(**kwargs, preview=True)
    assert preview["would_commit"] is True

    with allow_ledger_writes("test commit"):
        committed = ledger.create_snapshot(**kwargs)

    # The committed snapshot's saturation is byte-identical to the previewed one
    # (deterministic score, same inputs, no prior snapshot in either case).
    assert (committed.metadata or {}).get("saturation") == preview["saturation"]
    assert committed.metadata["saturation"]["score"] == preview["saturation"]["score"]
    # And the preview really was cheap: exactly ONE snapshot exists.
    assert len(ledger.list_snapshots(qid)) == 1


# --- 3. BLOCKER SURFACING (no raise) ---------------------------------------

def test_preview_surfaces_blocker_without_raising(ledger):
    # A high-impact live commit with require_panel and no panel / no
    # panel_skipped_reason WOULD raise on the real path. In preview it returns
    # would_commit False with the blocker text — no exception.
    with allow_ledger_writes("test seed high"):
        q = ledger.create_question(
            title="Does the panel gate surface as a preview blocker?",
            resolution_criteria=(
                "Resolves YES if a high-impact commit without a panel is blocked "
                "by 2026-12-31."
            ),
            close_time="2026-12-31T00:00:00Z",
            impact="high",
        )

    record = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.5,
        rationale="Clean rationale for the blocker preview.",
        forecast_origin="live",
        require_panel=True,
        preview=True,
    )

    assert record["preview"] is True
    assert record["would_commit"] is False
    assert record["blockers"]
    assert any("deliberative panel" in b for b in record["blockers"])
    # Refused-in-preview writes nothing either.
    assert ledger.get_current_snapshot(q.id) is None


# --- 4. TOOL-LEVEL: preview starts NO quorum, writes NOTHING ----------------

def _tool(db, **args):
    return json.loads(forecast_ledger_tool({"db": db, **args}))


def test_tool_preview_returns_record_starts_no_quorum_writes_nothing(tmp_path):
    db = str(tmp_path / "tool.db")
    created = _tool(
        db,
        action="create_question",
        title="Does the tool preview pin the snapshot count?",
        resolution_criteria=(
            "Resolves YES if update_forecast preview writes no snapshot by 2026-12-31."
        ),
        close_time="2026-12-31T00:00:00Z",
    )
    qid = created["question"]["id"]
    # Seed evidence so the agent-path require_evidence floor is cleared and the
    # preview reaches would_commit True.
    _tool(db, action="add_evidence", question_id=qid, source_or_note="seed", claim="observed signal")

    result = _tool(
        db,
        action="update_forecast",
        question_id=qid,
        probability=0.55,
        rationale="Clean tool rationale for the preview.",
        require_components=False,
        require_structured_reasoning=False,
        require_panel=False,
        preview=True,
    )

    assert result["success"] is True
    assert "preview" in result
    assert result["preview"]["would_commit"] is True
    assert result["preview"]["preview"] is True
    # NO post-commit machinery ran: no quorum started, no committed snapshot.
    assert "quorum_autorun" not in result
    assert "forecast_snapshot" not in result

    led = ForecastLedger(db)
    assert len(led.list_snapshots(qid)) == 0  # snapshot count pinned
    assert led.get_current_snapshot(qid) is None


def test_tool_preview_surfaces_blocker_as_data_not_error(tmp_path):
    db = str(tmp_path / "tool_block.db")
    created = _tool(
        db,
        action="create_question",
        title="Does the tool preview surface a blocker as data?",
        resolution_criteria=(
            "Resolves YES if a high-impact tool preview reports a blocker by 2026-12-31."
        ),
        close_time="2026-12-31T00:00:00Z",
        impact="high",
    )
    qid = created["question"]["id"]

    result = _tool(
        db,
        action="update_forecast",
        question_id=qid,
        probability=0.5,
        rationale="Clean rationale.",
        require_panel=True,
        preview=True,
    )

    # The preview itself SUCCEEDED (it computed a verdict); the blocker is data.
    assert result["success"] is True
    assert result["preview"]["would_commit"] is False
    assert result["preview"]["blockers"]

    led = ForecastLedger(db)
    assert len(led.list_snapshots(qid)) == 0


def test_tool_real_commit_still_writes_after_a_preview(tmp_path):
    # The real path is unchanged: after previewing, a normal commit writes exactly
    # one snapshot and runs its post-commit machinery.
    db = str(tmp_path / "tool_real.db")
    created = _tool(
        db,
        action="create_question",
        title="Does the real commit path survive the preview seam?",
        resolution_criteria=(
            "Resolves YES if a non-preview commit writes exactly one snapshot by 2026-12-31."
        ),
        close_time="2026-12-31T00:00:00Z",
    )
    qid = created["question"]["id"]
    _tool(db, action="add_evidence", question_id=qid, source_or_note="seed", claim="observed signal")

    preview = _tool(
        db, action="update_forecast", question_id=qid, probability=0.55,
        rationale="Clean tool rationale.", require_components=False,
        require_structured_reasoning=False, require_panel=False, preview=True,
    )
    assert preview["preview"]["would_commit"] is True

    committed = _tool(
        db, action="update_forecast", question_id=qid, probability=0.55,
        rationale="Clean tool rationale.", require_components=False,
        require_structured_reasoning=False, require_panel=False,
    )
    assert committed["success"] is True
    assert "forecast_snapshot" in committed
    assert "preview" not in committed

    led = ForecastLedger(db)
    assert len(led.list_snapshots(qid)) == 1
    assert led.get_current_snapshot(qid) is not None
