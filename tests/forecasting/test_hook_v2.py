"""Tests for the v2 hook families: output/uncertainty structure, quorum/panel
participation, confidence lean, and reasoning composition."""

from __future__ import annotations

import math

import pytest

from forecasting import ForecastLedger
from forecasting.hooks import (
    HookContext,
    SaturationBlocked,
    Severity,
    assess_distribution,
    autofix_distribution,
    run_hooks,
)
from forecasting.hooks.dsl import RuleSpec, compile_rule, evaluate_predicate, validate_rule
from forecasting.hooks.reasoning import REASONING_METHODS, normalize_methods
from forecasting.models import OutcomeSpace


def _ctx(**over) -> HookContext:
    base = dict(question_id="q", forecast_origin="live", event="update")
    base.update(over)
    return HookContext(**base)


def _verdict(ctx, rule_id, severity=Severity.ERROR):
    report = run_hooks(ctx, {rule_id: severity})
    return next((v for v in report.verdicts if v.rule_id == rule_id), None)


# ── distribution helpers ──────────────────────────────────────────────────────
def test_assess_inverted_and_nested_and_range():
    assert assess_distribution({"mean": 4, "interval_90_low": 5, "interval_90_high": 3}, outcome_type="numeric").ordered is False
    a = assess_distribution({"mean": 4, "interval_90_low": 3, "interval_90_high": 5, "interval_50_low": 2, "interval_50_high": 6}, outcome_type="numeric")
    assert a.nested is False
    assert assess_distribution({"mean": 5, "interval_90_low": -3, "interval_90_high": 20}, outcome_type="numeric", bounds=[0, 10]).in_range is False
    assert assess_distribution(0.6, outcome_type="binary") is None  # binary not assessed


def test_assess_median_only_not_renderable():
    a = assess_distribution({"median": 4.2}, outcome_type="distribution")
    assert a is not None and a.renderable is False


def test_autofix_reorders_clamps_nests_derives():
    fixed, fixes = autofix_distribution({"median": 4.2, "interval_90_low": 12, "interval_90_high": 2}, bounds=[0, 10])
    assert "derived mean from median" in fixes
    assert "reordered ci90" in fixes
    assert fixed["interval_90_high"] <= 10  # clamped


# ── distribution commit gate ──────────────────────────────────────────────────
def _dist_q(lg):
    return lg.create_question(
        title="What will the metric read at year end?",
        resolution_criteria="Resolves to the reported metric value at year end.",
        outcome_space=OutcomeSpace(type="distribution", units="%", bounds=[0, 10]),
    )


def test_malformed_distribution_blocks_agent_path(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "d.db"))
    lg.initialize_schema()
    q = _dist_q(lg)
    with pytest.raises(SaturationBlocked) as ei:
        lg.create_snapshot(question_id=q.id, probability_or_distribution={"mean": 4, "interval_90_low": 5, "interval_90_high": 3},
                           rationale="r", method="m", require_panel=False, require_components=False, require_structured_reasoning=False)
    assert ei.value.report.blocking_failures()[0].rule_id in ("uncertainty_well_formed", "output_renderable")


def test_distribution_autofix_commits(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "d.db"))
    lg.initialize_schema()
    q = _dist_q(lg)
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution={"mean": 4, "interval_90_low": 5, "interval_90_high": 3},
                              rationale="r", method="m", require_panel=False, require_components=False, require_structured_reasoning=False,
                              distribution_autofix=True)
    assert (snap.metadata or {}).get("distribution_autofixed")


# ── quorum / panel ────────────────────────────────────────────────────────────
def test_quorum_participation_needs_min_perspectives():
    assert _verdict(_ctx(panel_run_count=1, panel_perspective_count=2), "quorum_participation").passed is False
    assert _verdict(_ctx(panel_run_count=1, panel_perspective_count=5), "quorum_participation").passed is True
    assert _verdict(_ctx(panel_run_count=0), "quorum_participation").passed is True  # no panel -> not this rule


def test_quorum_required_by_tier():
    assert _verdict(_ctx(has_prior=True, panel_run_count=0), "quorum_required").passed is False
    assert _verdict(_ctx(has_prior=True, panel_run_count=1), "quorum_required").passed is True
    assert _verdict(_ctx(has_prior=False, impact="low", panel_run_count=0), "quorum_required").passed is True


def test_quorum_judged():
    assert _verdict(_ctx(is_quorum=True, quorum_judged=False), "quorum_judged").passed is False
    assert _verdict(_ctx(is_quorum=True, quorum_judged=True), "quorum_judged").passed is True
    assert _verdict(_ctx(is_quorum=False), "quorum_judged").passed is True


# ── confidence lean ───────────────────────────────────────────────────────────
def test_tails_justified():
    assert _verdict(_ctx(is_categorical=True, tail_audit_passes=False), "tails_justified").passed is False
    assert _verdict(_ctx(is_categorical=True, tail_null_excess=0.2), "tails_justified").passed is False
    assert _verdict(_ctx(is_categorical=True, tail_audit_passes=True, tail_null_excess=0.0), "tails_justified").passed is True


def test_calibration_bias_applied_only_when_under_confident():
    assert _verdict(_ctx(calibration_under_confident=True, active_lessons_unapplied=2), "calibration_bias_applied").passed is False
    assert _verdict(_ctx(calibration_under_confident=True, active_lessons_unapplied=0), "calibration_bias_applied").passed is True
    assert _verdict(_ctx(calibration_under_confident=False, active_lessons_unapplied=5), "calibration_bias_applied").passed is True


def test_confidence_committed_soft_with_escape():
    assert _verdict(_ctx(sharpness=0.0), "confidence_committed").passed is False           # coin flip, no justification
    assert _verdict(_ctx(sharpness=0.0, uncertainty_justified=True), "confidence_committed").passed is True  # escape
    assert _verdict(_ctx(sharpness=0.6), "confidence_committed").passed is True            # committed
    # never a hard block: even in strict it stays WARN
    from forecasting.hooks.profiles import HOOK_PROFILES
    assert HOOK_PROFILES["strict"]["confidence_committed"] is Severity.WARN


# ── reasoning composition ─────────────────────────────────────────────────────
def test_reasoning_composition_required_set_and_count():
    req = ("outside_view", "base_rate")
    v = _verdict(_ctx(reasoning_methods=("base_rate",), required_reasoning_methods=req, min_reasoning_methods=3), "reasoning_composition")
    assert v.passed is False and "outside_view" in v.message
    v2 = _verdict(_ctx(reasoning_methods=("outside_view", "base_rate", "bayesian"), required_reasoning_methods=req, min_reasoning_methods=3), "reasoning_composition")
    assert v2.passed is True


def test_normalize_methods_taxonomy():
    slugs, unknown = normalize_methods(["Outside View", "base-rate", "BAYESIAN", "telepathy"])
    assert slugs == ["outside_view", "base_rate", "bayesian"]
    assert unknown == ["telepathy"]
    assert "pre_mortem" in REASONING_METHODS


# ── DSL signals for v2 ────────────────────────────────────────────────────────
def test_dsl_v2_signals_validate_and_evaluate():
    spec = RuleSpec.from_dict({
        "id": "needs-3-methods", "severity": "error", "remediation_hint": "tag_reasoning",
        "check": {"all": [{"signal": "reasoning.method_count", "op": ">=", "value": 3},
                          {"signal": "bounds.well_formed", "op": "is_true"}]},
        "message": "needs 3 methods + clean bounds",
    })
    assert [i for i in validate_rule(spec) if i.severity == "error"] == []
    rule = compile_rule(spec)
    assert rule.evaluate(_ctx(reasoning_methods=("a", "b", "c"), bounds_well_formed=True), Severity.ERROR).passed is True
    assert evaluate_predicate({"signal": "confidence.sharpness", "op": "<", "value": 0.1}, _ctx(sharpness=0.0)) is True


def test_strict_profile_promotes_v2_warns_to_error():
    from forecasting.hooks import resolve_severities
    from types import SimpleNamespace
    q = SimpleNamespace(impact=None, metadata={"forecast_hooks": {"profile": "strict"}})
    sev = resolve_severities(q, forecast_origin="live", hooks_config={"profile": "standard"})
    assert sev["reasoning_composition"] is Severity.ERROR
    assert sev["quorum_required"] is Severity.ERROR
    assert sev["tails_justified"] is Severity.ERROR
