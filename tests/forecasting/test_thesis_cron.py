"""The cron auto-trigger: theses re-aggregate after the member review sweep."""

from __future__ import annotations

from forecasting import ForecastLedger
from forecasting.cron_runner import run_due_reviews
from forecasting.models import OutcomeSpace

CRITERIA = "Resolves to the official value reported by the named source on the close date."
THESIS_CRITERIA = "Aggregate health of the tagged member forecasts; reviewed as members update."


def _thesis(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    member = ledger.create_question(title="Power is the binding AI constraint?", resolution_criteria=CRITERIA, domain="macro")
    ledger.create_snapshot(question_id=member.id, probability_or_distribution=0.6, rationale="x")
    thesis = ledger.create_question(title="AI infra scarcity thesis", resolution_criteria=THESIS_CRITERIA, domain="macro", outcome_space=OutcomeSpace(type="thesis"))
    ledger.add_thesis_member(thesis.id, member.id, direction="support", weight=1.0)
    return ledger, thesis, member


def test_aggregate_all_theses_commits_each(tmp_path):
    ledger, thesis, _member = _thesis(tmp_path)
    assert ledger.get_current_snapshot(thesis.id) is None
    summary = ledger.aggregate_all_theses()
    assert summary["count"] == 1
    assert summary["results"][0]["ok"] is True
    assert ledger.get_current_snapshot(thesis.id) is not None


def test_nested_thesis_runs_last(tmp_path):
    ledger, parent, member = _thesis(tmp_path)
    # a child thesis that is itself a member of the parent must aggregate first
    child = ledger.create_question(title="Sub-thesis: power supply chain?", resolution_criteria=THESIS_CRITERIA, domain="macro", outcome_space=OutcomeSpace(type="thesis"))
    ledger.add_thesis_member(child.id, member.id, direction="support", weight=1.0)
    ledger.add_thesis_member(parent.id, child.id, direction="support", weight=1.0)
    summary = ledger.aggregate_all_theses()
    order = [r["id"] for r in summary["results"]]
    assert order.index(child.id) < order.index(parent.id)


def test_cron_flag_gates_thesis_aggregation(tmp_path):
    ledger, thesis, _member = _thesis(tmp_path)
    db_path = str(tmp_path / "f.db")
    # without the flag the cron commits no thesis snapshot
    run_due_reviews(db_path=db_path, thesis_aggregate=False)
    assert ledger.get_current_snapshot(thesis.id) is None
    # with the flag it previews + reports, but never mutates the active forecast
    report = run_due_reviews(db_path=db_path, thesis_aggregate=True)
    assert ledger.get_current_snapshot(thesis.id) is None
    assert "Thesis aggregation" in report
    assert "previewed: 1" in report
    assert "health 60%" in report
