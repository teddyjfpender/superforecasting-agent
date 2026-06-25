"""Gap 3b: a quorum's judge synthesis now has a durable home (panel_runs.judge) instead
of being dropped, so the quorum-judged gate can see it. A NULL judge stays indeterminate
(value-based) so adding the column never regresses pre-judge runs."""

from __future__ import annotations

from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace


def _ledger(tmp_path):
    return ForecastLedger(db_path=str(tmp_path / "q.db"))


def _question(lg):
    return lg.create_question(
        title="Will the challenger flip the Ohio Senate seat in 2026?",
        resolution_criteria="Resolves YES if the challenger wins per the certified state result on election day.",
        domain="politics",
        outcome_space=OutcomeSpace(type="binary"),
    )


def _estimates():
    return [
        {"perspective": "base_rate", "probability": 0.58, "agent_model": "m1"},
        {"perspective": "insider", "probability": 0.52, "agent_model": "m2"},
    ]


def test_record_panel_run_persists_judge(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    judge = {"consensus": ["lean challenger"], "contradictions": [], "blind_spots": ["turnout"], "judge_model": "opus"}
    pr = lg.record_panel_run(question_id=q.id, estimates=_estimates(), triggered_by="quorum", judge=judge)
    got = lg.get_panel_run(pr["id"])
    assert got.get("judge")  # stored (json), not dropped


def test_record_panel_run_without_judge_is_null(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    pr = lg.record_panel_run(question_id=q.id, estimates=_estimates(), triggered_by="quorum")
    got = lg.get_panel_run(pr["id"])
    assert not got.get("judge")  # NULL -> the judged gate stays indeterminate (no regression)
