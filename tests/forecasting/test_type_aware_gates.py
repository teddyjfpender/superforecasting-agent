"""Type-aware gating: a deterministic thesis/factor aggregate is NOT an LLM
forecast, so the LLM-forecast-quality rules (panel, quorum, structured reasoning,
citations/evidence, outside-view anchor, renderable distribution) must not fire on
it — they were the 'noisy diagnostics' the first feedback pass flagged. Modeled
forecasts still get the full gate."""

from __future__ import annotations

from forecasting.hooks import resolve_severities, run_hooks
from forecasting.hooks.spec import HookContext

# Rules that are about LLM-forecast quality and therefore irrelevant to a
# deterministic aggregate.
LLM_QUALITY_RULES = {
    "require_panel",
    "quorum_required",
    "quorum_participation",
    "quorum_judged",
    "require_structured_reasoning",
    "require_citations",
    "require_evidence",
    "require_outside_view_anchor",
    "output_renderable",
    "uncertainty_well_formed",
    "uncertainty_width_sane",
    "reasoning_composition",
}


def _failing(ctx: HookContext) -> set[str]:
    report = run_hooks(ctx, resolve_severities(None, forecast_origin="live"))
    return {v.rule_id for v in report.verdicts if not v.passed}


def test_thesis_aggregate_skips_llm_quality_rules():
    # A bare aggregate context: no evidence, no panel, no reasons, no distribution.
    aggregate = HookContext(
        question_id="fq_test",
        event="update",
        forecast_origin="live",
        is_thesis_or_factor=True,
        evidence_count=0,
        reference_class_count=0,
        has_components=True,
        component_count=3,
    )
    failing = _failing(aggregate)
    leaked = failing & LLM_QUALITY_RULES
    assert leaked == set(), f"LLM-quality rules must not fire on a deterministic aggregate, but got: {sorted(leaked)}"


def test_modeled_forecast_still_gets_the_full_gate():
    # The SAME bare context, but a modeled (non-aggregate) live forecast: the hard
    # evidence + outside-view rules must still bite. impact="high" makes it a SERIOUS
    # forecast so the (now serious-scoped) outside-view anchor rule fires.
    modeled = HookContext(
        question_id="fq_test",
        event="update",
        forecast_origin="live",
        impact="high",
        is_thesis_or_factor=False,
        evidence_count=0,
        reference_class_count=0,
        has_components=True,
        component_count=3,
    )
    failing = _failing(modeled)
    assert "require_evidence" in failing
    assert "require_outside_view_anchor" in failing
