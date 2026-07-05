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


# ── H1: quorum signals live at COMMIT (populated from the linked panel_run_ref) ──
def _quorum_estimates():
    return [
        {"perspective": p, "probability": 0.5, "rationale": "r", "agent_model": f"m-{p}"}
        for p in ("outside", "inside", "market", "red_team", "sanity")
    ]


def _bin_q(lg):
    return lg.create_question(title="Will X happen by year end?", resolution_criteria="Resolves YES if X occurs.")


_COMMIT_COMMON = dict(method="m", require_panel=False, require_components=False, require_structured_reasoning=False)


def test_quorum_signals_true_at_commit_with_linked_panel(tmp_path):
    """A commit linking a judged quorum run computes the quorum signals from that run:
    participation does NOT false-fire (perspectives populated, not 0) and a judged
    quorum does not raise the quorum_judged warn."""
    lg = ForecastLedger(db_path=str(tmp_path / "q1.db"))
    lg.initialize_schema()
    q = _bin_q(lg)
    run = lg.record_panel_run(question_id=q.id, estimates=_quorum_estimates(), triggered_by="quorum",
                              judge={"consensus": "c", "judge_model": "j"})
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="r",
                              panel_run_ref=run["id"], **_COMMIT_COMMON)
    sat = (snap.metadata or {}).get("saturation") or {}
    assert "quorum_participation" not in sat.get("warnings", [])
    assert "quorum_judged" not in sat.get("warnings", [])


def test_unjudged_quorum_flags_quorum_judged_at_commit(tmp_path):
    """A commit linking an UNjudged quorum run now honestly raises the quorum_judged
    warn — before H1, is_quorum defaulted False at commit and this never fired."""
    lg = ForecastLedger(db_path=str(tmp_path / "q2.db"))
    lg.initialize_schema()
    q = _bin_q(lg)
    run = lg.record_panel_run(question_id=q.id, estimates=_quorum_estimates(), triggered_by="quorum")
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="r",
                              panel_run_ref=run["id"], **_COMMIT_COMMON)
    sat = (snap.metadata or {}).get("saturation") or {}
    assert "quorum_judged" in sat.get("warnings", [])
    # a 5-perspective quorum still satisfies participation
    assert "quorum_participation" not in sat.get("warnings", [])


def test_quorum_participation_no_false_fire_without_panel_at_commit(tmp_path):
    """A commit with NO panel linked must not false-fire quorum_participation /
    quorum_judged (the rules key on panel_run_count / is_quorum being falsey)."""
    lg = ForecastLedger(db_path=str(tmp_path / "q3.db"))
    lg.initialize_schema()
    q = _bin_q(lg)
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="r",
                              **_COMMIT_COMMON)
    sat = (snap.metadata or {}).get("saturation") or {}
    assert "quorum_participation" not in sat.get("warnings", [])
    assert "quorum_judged" not in sat.get("warnings", [])


def test_quorum_participation_no_false_fire_on_unlinked_recommit_with_prior_run(tmp_path):
    """Regression: a re-commit that does NOT link a panel_run_ref, on a question that
    ALREADY has an older panel run, must not false-fire quorum_participation. At commit
    the participation counts come only from the linked run (0 here) while panel_run_count
    spans all runs (>0) — keying the rule on panel_run_count blocked/flagged a legitimate
    re-forecast with the wrong reason (perspectives=0). The rule must key on the counts."""
    lg = ForecastLedger(db_path=str(tmp_path / "q4.db"))
    lg.initialize_schema()
    q = _bin_q(lg)
    run = lg.record_panel_run(question_id=q.id, estimates=_quorum_estimates(), triggered_by="quorum",
                              judge={"consensus": "c", "judge_model": "j"})
    # forecast #1 links the panel
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="r",
                       panel_run_ref=run["id"], **_COMMIT_COMMON)
    # re-forecast (has_prior) WITHOUT linking a panel, recording a skip reason instead
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.55, rationale="r2",
                              panel_skipped_reason="no material change since the judged panel",
                              **_COMMIT_COMMON)
    sat = (snap.metadata or {}).get("saturation") or {}
    assert "quorum_participation" not in sat.get("warnings", [])
    assert "quorum_participation" not in sat.get("blocking", [])


def test_quorum_participation_na_when_no_counts_even_with_prior_run():
    """The rule keys on the participation COUNTS (perspectives/models), not the
    question-total panel_run_count. So the finding's shape — panel_run_count>0 (an older
    run on the question) but this context carries 0 perspectives / 0 models (unlinked
    re-commit) — is N/A and does NOT fire, even at ERROR severity (strict profile).
    quorum_required owns the 'a run must exist' requirement at this tier."""
    ctx = _ctx(panel_run_count=1, panel_perspective_count=0, quorum_model_count=0)
    assert _verdict(ctx, "quorum_participation").passed is True
    # a linked run WITH counts still enforces the minimum
    assert _verdict(_ctx(panel_run_count=1, panel_perspective_count=2), "quorum_participation").passed is False


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


# ── RDY machine-readiness rules ───────────────────────────────────────────────
def test_readiness_floor_fires_below_passes_at_or_above_and_on_none():
    # below the default floor (60) -> fires
    assert _verdict(_ctx(readiness_score=40.0), "readiness_floor").passed is False
    # exactly at / above the floor -> passes
    assert _verdict(_ctx(readiness_score=60.0), "readiness_floor").passed is True
    assert _verdict(_ctx(readiness_score=85.0), "readiness_floor").passed is True
    # no composite (benchmark/market) -> PASSES (never fires on None)
    assert _verdict(_ctx(readiness_score=None), "readiness_floor").passed is True
    # non-live never applies (not even evaluated -> no verdict)
    assert _verdict(_ctx(forecast_origin="exploratory", readiness_score=5.0), "readiness_floor") is None


def test_no_watched_sources_fires_on_zero_live_only():
    assert _verdict(_ctx(watched_source_count=0), "no_watched_sources").passed is False
    assert _verdict(_ctx(watched_source_count=3), "no_watched_sources").passed is True
    # non-live never applies
    assert _verdict(_ctx(forecast_origin="exploratory", watched_source_count=0), "no_watched_sources") is None


def test_readiness_floor_appconfig_tunable():
    # The fire boundary tracks FORECAST_HOOK_READINESS_FLOOR: score 55 passes at
    # floor=50 and fires at floor=60. set_override has the highest precedence and is
    # robust to a reconfigured appconfig singleton in the test session.
    from forecasting import appconfig

    try:
        appconfig.set_override("FORECAST_HOOK_READINESS_FLOOR", "50")
        assert _verdict(_ctx(readiness_score=55.0), "readiness_floor").passed is True
        appconfig.set_override("FORECAST_HOOK_READINESS_FLOOR", "60")
        assert _verdict(_ctx(readiness_score=55.0), "readiness_floor").passed is False
    finally:
        appconfig.get_config().clear_override("FORECAST_HOOK_READINESS_FLOOR")


def test_readiness_floor_per_question_threshold_beats_appconfig():
    # A per-question ctx.threshold('readiness_floor') override wins over the appconfig floor.
    assert _verdict(_ctx(readiness_score=55.0, thresholds={"readiness_floor": 50.0}), "readiness_floor").passed is True
    assert _verdict(_ctx(readiness_score=55.0, thresholds={"readiness_floor": 70.0}), "readiness_floor").passed is False


def test_strict_profile_promotes_v2_warns_to_error():
    from forecasting.hooks import resolve_severities
    from types import SimpleNamespace
    q = SimpleNamespace(impact=None, metadata={"forecast_hooks": {"profile": "strict"}})
    sev = resolve_severities(q, forecast_origin="live", hooks_config={"profile": "standard"})
    assert sev["reasoning_composition"] is Severity.ERROR
    assert sev["quorum_required"] is Severity.ERROR
    assert sev["tails_justified"] is Severity.ERROR
