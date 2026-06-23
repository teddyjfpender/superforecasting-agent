"""The outside-view anchor gate: a serious live forecast should carry a reference
class / base rate, so the system nudges a lazy prompter off pure inside-view prose
toward an empirical anchor (the highest-ROI forecasting-quality ask in feedback)."""

from __future__ import annotations

from forecasting.hooks import resolve_severities, run_hooks
from forecasting.hooks.signals import build_context_from_ledger
from forecasting.ledger import ForecastLedger

CRIT = "Resolves yes if the reported value exceeds the stated threshold at the close date."


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "rc.db"))
    lg.initialize_schema()
    return lg


def _anchor_verdict(lg, qid):
    ctx = build_context_from_ledger(lg, qid)
    report = run_hooks(ctx, resolve_severities(None, forecast_origin="live"))
    return next((v for v in report.verdicts if v.rule_id == "require_outside_view_anchor"), None)


def test_live_forecast_without_reference_class_is_flagged(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the metric exceed target by close?", resolution_criteria=CRIT)
    lg.add_evidence(question_id=q.id, source_or_note="a source", claim="x")
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.6, rationale="inside-view read")

    verdict = _anchor_verdict(lg, q.id)
    assert verdict is not None and verdict.passed is False
    assert verdict.severity.value == "warn"  # nudge by default; ERROR in strict


def test_attaching_a_reference_class_clears_the_anchor_gate(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the indicator cross the line by close?", resolution_criteria=CRIT)
    lg.add_evidence(question_id=q.id, source_or_note="a source", claim="x")
    lg.add_reference_class(
        question_id=q.id,
        name="historical cross-rate of comparable indicators",
        inclusion_criteria="comparable indicators in the same regime",
        base_rate=0.4,
    )
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.6, rationale="anchored read")

    verdict = _anchor_verdict(lg, q.id)
    assert verdict is not None and verdict.passed is True
