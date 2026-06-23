"""The member-commit cascade: committing a member auto-re-aggregates its parent
thesis/factor so the desk never shows a stale aggregate, plus the freshness hook
signal that guards it."""

from __future__ import annotations

import time

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace

CRIT = "Resolves to the official value reported by the named source on the close date."
THCRIT = "Aggregate health of the tagged member forecasts; reviewed as members update."


def _thesis_with_member(tmp_path, *, factor=False):
    lg = ForecastLedger(tmp_path / "f.db")
    m = lg.create_question(title="Will power capacity tighten by year end?", resolution_criteria=CRIT, domain="energy")
    lg.create_snapshot(question_id=m.id, probability_or_distribution=0.5, rationale="baseline")
    if factor:
        th = lg.create_question(
            title="AI infra factor", resolution_criteria=THCRIT, domain="tech",
            outcome_space=OutcomeSpace(type="thesis", units="return_frac"), metadata={"aggregation": "factor"},
        )
    else:
        th = lg.create_question(
            title="AI infra scarcity thesis", resolution_criteria=THCRIT, domain="tech",
            outcome_space=OutcomeSpace(type="thesis"),
        )
    lg.add_thesis_member(th.id, m.id, direction="support", weight=1.0)
    lg.aggregate_thesis(th.id)
    return lg, th, m


def _health(snap):
    return (snap.probability_or_distribution or {}).get("health")


def test_member_commit_reaggregates_parent_thesis(tmp_path):
    lg, th, m = _thesis_with_member(tmp_path)
    base = lg.get_current_snapshot(th.id)
    assert _health(base) == pytest.approx(0.5, abs=0.01)

    lg.create_snapshot(question_id=m.id, probability_or_distribution=0.85, rationale="tightening")

    after = lg.get_current_snapshot(th.id)
    assert after.forecast_id != base.forecast_id, "the thesis should have re-aggregated on the member commit"
    assert _health(after) == pytest.approx(0.85, abs=0.01), "thesis health should track the moved member"

    # The desk member-contributions table now shows the LIVE belief (not "-"),
    # and the aggregate reads fresh — the exact symptom that was broken.
    from forecasting.dashboard import build_workspace_payload

    tp = next(x for x in build_workspace_payload(ledger=lg)["theses"] if x["id"] == th.id)
    assert tp["aggregate_stale"] is False
    assert tp["components"], "thesis should show member contributions"
    assert tp["components"][0]["latest_belief_display"] == "85%"


def test_member_commit_reaggregates_parent_factor(tmp_path):
    lg, fac, m = _thesis_with_member(tmp_path, factor=True)
    base = lg.get_current_snapshot(fac.id)
    lg.create_snapshot(question_id=m.id, probability_or_distribution=0.30, rationale="moved")
    after = lg.get_current_snapshot(fac.id)
    assert after.forecast_id != base.forecast_id, "the factor should re-aggregate on the constituent commit"


def test_cascade_suppresses_analyst_note(tmp_path):
    lg, th, m = _thesis_with_member(tmp_path)
    notes_before = len(lg.list_analyst_notes(th.id))
    lg.create_snapshot(question_id=m.id, probability_or_distribution=0.85, rationale="moved")
    notes_after = len(lg.list_analyst_notes(th.id))
    assert notes_after == notes_before, "the cascade re-aggregate must not spam the thesis analyst log"


def test_kill_switch_disables_cascade(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_DISABLE_THESIS_CASCADE", "1")
    lg, th, m = _thesis_with_member(tmp_path)
    base = lg.get_current_snapshot(th.id)
    lg.create_snapshot(question_id=m.id, probability_or_distribution=0.85, rationale="moved")
    after = lg.get_current_snapshot(th.id)
    assert after.forecast_id == base.forecast_id, "kill-switch should suppress the cascade"


def test_per_thesis_opt_out(tmp_path):
    lg = ForecastLedger(tmp_path / "f.db")
    m = lg.create_question(title="Will power capacity tighten?", resolution_criteria=CRIT, domain="energy")
    lg.create_snapshot(question_id=m.id, probability_or_distribution=0.5, rationale="b")
    th = lg.create_question(
        title="Opted-out thesis", resolution_criteria=THCRIT, domain="tech",
        outcome_space=OutcomeSpace(type="thesis"), metadata={"forecast_hooks": {"auto_aggregate": False}},
    )
    lg.add_thesis_member(th.id, m.id, direction="support", weight=1.0)
    lg.aggregate_thesis(th.id)
    base = lg.get_current_snapshot(th.id)
    lg.create_snapshot(question_id=m.id, probability_or_distribution=0.85, rationale="moved")
    after = lg.get_current_snapshot(th.id)
    assert after.forecast_id == base.forecast_id, "a thesis with auto_aggregate=false should not cascade"


def test_freshness_signal_flags_stale_aggregate(tmp_path, monkeypatch):
    from forecasting.hooks import resolve_severities, run_hooks
    from forecasting.hooks.signals import build_context_from_ledger

    monkeypatch.setenv("FORECAST_DISABLE_THESIS_CASCADE", "1")  # so it stays stale
    lg, th, m = _thesis_with_member(tmp_path)
    ctx_fresh = build_context_from_ledger(lg, th.id)
    assert ctx_fresh.is_thesis_or_factor is True
    assert ctx_fresh.aggregate_stale is False

    time.sleep(1.1)
    lg.create_snapshot(question_id=m.id, probability_or_distribution=0.85, rationale="moved")
    ctx_stale = build_context_from_ledger(lg, th.id)
    assert ctx_stale.aggregate_stale is True
    assert ctx_stale.newer_member_count == 1

    report = run_hooks(ctx_stale, resolve_severities(None, forecast_origin="live"))
    verdict = next((v for v in report.verdicts if v.rule_id == "thesis_aggregate_fresh"), None)
    assert verdict is not None and verdict.passed is False
