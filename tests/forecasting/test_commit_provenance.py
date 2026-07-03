"""Commit provenance: the record itself must tell the full story.

Born from the operator's Senate-batch audit: snapshots claimed "committed
with panel pr_..." but panel_run_ref was consumed by the gates and DISCARDED;
quorum declines returned bare None, so an audit could not tell a by-design
skip (panel attached) from silent breakage.
"""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger, allow_ledger_writes
from forecasting.quorum_jobs import maybe_autorun_quorum


@pytest.fixture()
def ledger(tmp_path):
    led = ForecastLedger(tmp_path / "prov.db")
    with allow_ledger_writes("test seed"):
        led.create_question(
            title="Will provenance survive the commit?",
            resolution_criteria="Resolves YES if the official record carries it by 2026-12-31.",
            close_time="2026-12-31T00:00:00Z",
        )
    return led


def _commit(led, qid, **over):
    with allow_ledger_writes("test commit"):
        return led.create_snapshot(
            question_id=qid,
            probability_or_distribution=0.4,
            rationale="Structured enough for the test gates.",
            forecast_origin="exploratory",
            **over,
        )


def test_panel_run_ref_is_persisted_in_snapshot_metadata(ledger):
    qid = ledger.list_questions()[0].id
    with allow_ledger_writes("test panel"):
        panel = ledger.record_panel_run(
            question_id=qid,
            estimates=[
                {"name": f"p{i}", "probability": 0.35 + i * 0.02, "rationale": f"view {i}"}
                for i in range(5)
            ],
        )
    panel_id = panel["id"] if isinstance(panel, dict) else panel.id
    snap = _commit(ledger, qid, panel_run_ref=panel_id)
    assert (snap.metadata or {}).get("panel_run_ref") == panel_id


def test_quorum_declines_return_auditable_reasons(ledger):
    qid = ledger.list_questions()[0].id
    snap = _commit(ledger, qid)
    # panel attached → skip record, not bare None
    rec = maybe_autorun_quorum(
        ledger, qid, snapshot=snap, has_panel=True,
        has_prior_snapshot=True, forecast_origin="live",
    )
    assert rec and rec.get("skipped") and "panel" in rec["reason"]
    # non-live origin → skip record
    rec2 = maybe_autorun_quorum(
        ledger, qid, snapshot=snap, has_panel=False,
        has_prior_snapshot=True, forecast_origin="backtest",
    )
    assert rec2 and rec2.get("skipped") and "live" in rec2["reason"]


def test_annotate_snapshot_merges_provenance_only(ledger):
    qid = ledger.list_questions()[0].id
    snap = _commit(ledger, qid)
    ledger.annotate_snapshot(snap.forecast_id, {"quorum_autorun": {"skipped": True, "reason": "test"}})
    fresh = ledger.get_snapshot(snap.forecast_id)
    assert (fresh.metadata or {}).get("quorum_autorun", {}).get("reason") == "test"
    assert fresh.probability_or_distribution == snap.probability_or_distribution
    with pytest.raises(Exception):
        ledger.annotate_snapshot("fs_does_not_exist", {"x": 1})
