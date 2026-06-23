"""Unit tests for the forecast hooks engine (pure, no DB)."""

from __future__ import annotations

import pytest

from forecasting.hooks import (
    HookContext,
    SaturationBlocked,
    Severity,
    build_commit_context,
    policy_from_require_flags,
    run_hooks,
)


def _saturated_live(**overrides) -> HookContext:
    """A fully-saturated live commit context; override fields to fail a rule."""
    base = dict(
        question_id="q1",
        forecast_origin="live",
        event="update",
        impact="medium",
        has_prior=True,
        is_categorical=False,
        has_reasons_up=True,
        has_reasons_down=True,
        has_change_my_mind=True,
        has_components=True,
        component_count=3,
        has_citations=True,
        panel_linked=True,
        panel_skipped=False,
        has_fresh_evidence=True,
        acknowledge_stale_evidence=False,
        evidence_count=4,
        prior_forecast_id="fs_prior",
        prior_as_of="2026-06-01T00:00:00Z",
        decision_gaps=(),
        tail_audit_passes=None,
        tail_unearned_mass=0.0,
        tail_offenders=(),
        style_clean=True,
        active_lessons_unapplied=0,
        # v2 signals — a genuinely fully-saturated commit also satisfies the new rules
        panel_run_count=2,
        panel_perspective_count=5,
        sharpness=1.0,
        reasoning_methods=("outside_view", "base_rate", "bayesian"),
    )
    base.update(overrides)
    return HookContext(**base)


ALL_ERROR = {
    "require_structured_reasoning": Severity.ERROR,
    "require_components": Severity.ERROR,
    "require_fresh_evidence": Severity.ERROR,
    "require_decision_readiness": Severity.ERROR,
    "require_panel": Severity.ERROR,
    "require_citations": Severity.ERROR,
    "require_outcome_paths": Severity.ERROR,
}


def test_fully_saturated_passes_with_high_score():
    report = run_hooks(_saturated_live(), ALL_ERROR)
    assert report.passed is True
    assert report.score == pytest.approx(100.0)
    assert report.blocking_failures() == []


def test_missing_components_blocks_with_legacy_message():
    report = run_hooks(_saturated_live(has_components=False, component_count=0), ALL_ERROR)
    assert report.passed is False
    blockers = report.blocking_failures()
    assert any(b.rule_id == "require_components" for b in blockers)
    msg = next(b.message for b in blockers if b.rule_id == "require_components")
    assert msg.startswith("live forecast requires ensemble_components:")


def test_structured_reasoning_lists_missing_fields():
    report = run_hooks(_saturated_live(has_reasons_down=False, has_change_my_mind=False), ALL_ERROR)
    msg = next(b.message for b in report.blocking_failures() if b.rule_id == "require_structured_reasoning")
    assert "reasons_down, change_my_mind" in msg


def test_fresh_evidence_only_applies_to_recommit():
    # No prior snapshot -> the fresh-evidence rule does not apply at all.
    report = run_hooks(_saturated_live(has_prior=False, has_fresh_evidence=False), ALL_ERROR)
    assert all(v.rule_id != "require_fresh_evidence" for v in report.verdicts)
    # With a prior + stale + not acknowledged -> blocks.
    report2 = run_hooks(_saturated_live(has_fresh_evidence=False), ALL_ERROR)
    assert any(b.rule_id == "require_fresh_evidence" for b in report2.blocking_failures())
    # Acknowledged -> rule does not apply.
    report3 = run_hooks(_saturated_live(has_fresh_evidence=False, acknowledge_stale_evidence=True), ALL_ERROR)
    assert all(v.rule_id != "require_fresh_evidence" for v in report3.verdicts)


def test_panel_required_on_recommit_and_high_impact_but_not_first_lowimpact():
    # re-commit, no panel, no skip -> blocks
    assert not run_hooks(_saturated_live(panel_linked=False), ALL_ERROR).passed
    # re-commit with skip reason -> passes the panel rule
    r = run_hooks(_saturated_live(panel_linked=False, panel_skipped=True), ALL_ERROR)
    assert all(v.rule_id != "require_panel" or v.passed for v in r.verdicts)
    # first forecast (no prior), low impact, no panel -> panel rule passes
    r2 = run_hooks(_saturated_live(has_prior=False, panel_linked=False, has_fresh_evidence=True), ALL_ERROR)
    assert all(v.rule_id != "require_panel" or v.passed for v in r2.verdicts)
    # first forecast, HIGH impact, no panel -> blocks
    assert not run_hooks(_saturated_live(has_prior=False, impact="high", panel_linked=False), ALL_ERROR).passed


def test_tail_paths_only_categorical():
    # non-categorical: rule does not apply even with bad mass
    r = run_hooks(_saturated_live(tail_audit_passes=None, tail_unearned_mass=0.5), ALL_ERROR)
    assert all(v.rule_id != "require_outcome_paths" for v in r.verdicts)
    # categorical failing -> blocks with percentage + offenders
    r2 = run_hooks(_saturated_live(is_categorical=True, tail_audit_passes=False,
                                   tail_unearned_mass=0.12, tail_offenders=("maybe", "other")), ALL_ERROR)
    msg = next(b.message for b in r2.blocking_failures() if b.rule_id == "require_outcome_paths")
    assert "12.0%" in msg and "maybe, other" in msg


def test_style_blocks_when_dirty():
    report = run_hooks(_saturated_live(style_clean=False, style_offending_fields=("rationale",)))
    assert any(b.rule_id == "style_clean" for b in report.blocking_failures())


def test_warn_severity_scores_but_does_not_block():
    # citations missing but only WARN -> score drops, still passes
    policy = dict(ALL_ERROR)
    policy["require_citations"] = Severity.WARN
    report = run_hooks(_saturated_live(has_citations=False), policy)
    assert report.passed is True
    assert report.score < 100.0
    assert any(w.rule_id == "require_citations" for w in report.warnings())


def test_off_severity_skips_rule():
    policy = dict(ALL_ERROR)
    policy["require_components"] = Severity.OFF
    report = run_hooks(_saturated_live(has_components=False), policy)
    assert all(v.rule_id != "require_components" for v in report.verdicts)
    assert report.passed is True


def test_exploratory_origin_is_never_gated():
    policy = policy_from_require_flags(
        forecast_origin="exploratory",
        require_structured_reasoning=True, require_components=True, require_fresh_evidence=True,
        require_decision_readiness=True, require_panel=True, require_citations=True,
        require_outcome_paths=True,
    )
    # everything off -> empty / passing report even with a barren context
    report = run_hooks(HookContext(question_id="q", forecast_origin="exploratory", event="update",
                                   has_components=False, has_reasons_up=False), policy)
    assert report.passed is True
    assert report.verdicts == []


def test_saturation_blocked_subclasses_validation_error():
    from forecasting.models import ValidationError
    report = run_hooks(_saturated_live(has_components=False), ALL_ERROR)
    err = SaturationBlocked(report)
    assert isinstance(err, ValidationError)
    assert "ensemble_components" in str(err)


def test_build_commit_context_detects_em_dash_style():
    ctx = build_commit_context(
        question_id="q", forecast_origin="live", event="update", impact=None, has_prior=False,
        is_categorical=False, reasons_up=["a"], reasons_down=["b"], change_my_mind=["c"],
        has_components=True, component_count=2, citation_refs=["e1"], panel_run_ref=None,
        panel_skipped_reason=None, has_fresh_evidence=True, acknowledge_stale_evidence=False,
        evidence_count=1, prior_forecast_id=None, prior_as_of=None, decision_gaps=[],
        tail_audit_passes=None, tail_unearned_mass=0.0, tail_offenders=[],
        rationale="rates rose — sharply",  # em dash -> style not clean
    )
    assert ctx.style_clean is False
    assert "rationale" in ctx.style_offending_fields
