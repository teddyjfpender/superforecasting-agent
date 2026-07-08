"""The outside-view anchor gate: a serious live forecast should carry a reference
class / base rate, so the system nudges a lazy prompter off pure inside-view prose
toward an empirical anchor (the highest-ROI forecasting-quality ask in feedback)."""

from __future__ import annotations

from forecasting.hooks import resolve_severities, run_hooks
from forecasting.hooks.signals import build_context_from_ledger
from forecasting.hooks.spec import HookContext
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


def test_serious_live_forecast_without_reference_class_blocks(tmp_path):
    # A SERIOUS (high-impact) live forecast with no outside-view anchor now BLOCKS in
    # the standard profile (finding #4: WARN -> ERROR — the highest-ROI reasoning ask).
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Will the metric exceed target by close?", resolution_criteria=CRIT, impact="high"
    )
    lg.add_evidence(question_id=q.id, source_or_note="a source", claim="x")
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.6, rationale="inside-view read",
        require_panel=False, enforce_resolved_hooks=False,
    )

    verdict = _anchor_verdict(lg, q.id)
    assert verdict is not None and verdict.passed is False
    assert verdict.severity.value == "error"  # standard now blocks a serious forecast


def test_first_commit_low_impact_forecast_requires_anchor():
    # G3 · ANCHOR UNIVERSALITY: the FIRST live commit of ANY question (not just
    # high-impact) now requires an outside-view anchor — the cheapest, most valuable
    # moment, with no re-forecast flow to brick. A first-pass low-impact forecast with
    # no linked reference class now BLOCKS (ERROR standard). Pure-engine: has_prior=False.
    ctx = HookContext(
        question_id="fq_low",
        event="update",
        forecast_origin="live",
        impact="low",
        has_prior=False,
        is_thesis_or_factor=False,
        reference_class_count=0,
        linked_reference_class_count=0,
    )
    report = run_hooks(ctx, resolve_severities(None, forecast_origin="live"))
    anchor = next((v for v in report.verdicts if v.rule_id == "require_outside_view_anchor"), None)
    assert anchor is not None and anchor.passed is False
    assert anchor.severity.value == "error"
    assert "first live forecast on this question requires an outside-view anchor" in anchor.message


def test_low_impact_re_forecast_is_not_hard_blocked_on_anchor():
    # The has_prior trap is designed around: a RE-forecast (has_prior=True) of a
    # non-high-impact question does NOT hard-block on the anchor (the first-commit ERROR
    # tier is scoped to first commits; the outside_view_refresh WARN nags it instead).
    ctx = HookContext(
        question_id="fq_low",
        event="update",
        forecast_origin="live",
        impact="low",
        has_prior=True,
        is_thesis_or_factor=False,
        reference_class_count=0,
        linked_reference_class_count=0,
    )
    report = run_hooks(ctx, resolve_severities(None, forecast_origin="live"))
    anchor = next((v for v in report.verdicts if v.rule_id == "require_outside_view_anchor"), None)
    assert anchor is not None and anchor.passed is True  # re-commit self-passes the ERROR tier
    assert not any(b.rule_id == "require_outside_view_anchor" for b in report.blocking_failures())
    # ...but the WARN refresh tier fires (visibility): the question has no anchor on the books.
    refresh = next((v for v in report.verdicts if v.rule_id == "outside_view_refresh"), None)
    assert refresh is not None and refresh.passed is False and refresh.severity.value == "warn"


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
