"""Built-in forecast hook rules — one per legacy ``create_snapshot`` gate, plus
``style_clean`` and ``lessons_applied``.

CRITICAL: the blocking ``message`` of each rule that mirrors a legacy gate is
BYTE-IDENTICAL to the string the inline gate raised (see forecasting/ledger.py
create_snapshot). This is what lets the engine become the single enforcement
chokepoint without breaking the test suite, which asserts on these substrings.
The rule order here matches the legacy evaluation order so the first blocking
failure is the same message the inline gates would have raised first.
"""

from __future__ import annotations

from typing import Any

from forecasting.hooks.spec import (
    Category,
    HookContext,
    RemediationDescriptor,
    Severity,
    SimpleRule,
)

_OK: tuple[bool, str, dict[str, Any]] = (True, "", {})


def _live(ctx: HookContext) -> bool:
    return ctx.is_live


def _modeled(ctx: HookContext) -> bool:
    # A "modeled" forecast = a live, LLM-reasoned forecast — NOT a deterministic
    # thesis/factor aggregate. The aggregate's quality lives in its members + the
    # aggregation math, so the LLM-forecast-quality rules (panel, quorum, structured
    # reasoning, citations/evidence, outside-view anchor, renderable distribution)
    # are noise on it. Type-aware gating: those rules apply to modeled forecasts only.
    return ctx.is_live and not ctx.is_thesis_or_factor


# ── structured reasoning ──────────────────────────────────────────────────────
def _check_structured_reasoning(ctx: HookContext):
    missing = []
    if not ctx.has_reasons_up:
        missing.append("reasons_up")
    if not ctx.has_reasons_down:
        missing.append("reasons_down")
    if not ctx.has_change_my_mind:
        missing.append("change_my_mind")
    if not missing:
        return _OK
    msg = (
        "live forecast requires structured reasoning fields: "
        + ", ".join(missing)
        + ". Provide reasons_up/reasons_down/change_my_mind, rerun with "
        "require_structured_reasoning=false, or record it as "
        "forecast_origin='exploratory'."
    )
    return False, msg, {"missing": missing}


# ── components / decomposition ────────────────────────────────────────────────
def _check_components(ctx: HookContext):
    if ctx.has_components:
        return _OK
    msg = (
        "live forecast requires ensemble_components: decompose the estimate "
        "into pooled drivers (base rate, mechanism, market/crowd, case-specific "
        "factors), each with a stable source slug. Provide ensemble_components, "
        "rerun with require_components=false, or record it as "
        "forecast_origin='exploratory'."
    )
    return False, msg, {"component_count": ctx.component_count}


# ── fresh evidence (re-run discipline) ────────────────────────────────────────
def _applies_fresh_evidence(ctx: HookContext) -> bool:
    # The legacy gate only fires for a live re-run that hasn't acknowledged stale
    # evidence (a prior snapshot must exist to compare against).
    return ctx.is_live and ctx.has_prior and not ctx.acknowledge_stale_evidence


def _check_fresh_evidence(ctx: HookContext):
    if ctx.has_fresh_evidence:
        return _OK
    msg = (
        "re-run blocked: no fresh evidence collected since the prior forecast "
        f"({ctx.prior_forecast_id}, as_of {ctx.prior_as_of}). Re-running a forecast must "
        "start from fresh readings — run `forecast refresh <id>` (re-fetches "
        "watched sources and re-pools) or import_source_evidence for each driver "
        "to pull the latest data, THEN update. If you have genuinely checked and "
        "nothing has changed, set acknowledge_stale_evidence=true (CLI "
        "--ack-stale-evidence), or record it as forecast_origin='exploratory'."
    )
    return False, msg, {}


# ── stale-evidence justification (the freshness bypass must be explained) ──────
def _applies_stale_evidence_justified(ctx: HookContext) -> bool:
    # Fires only when a live RE-RUN used the freshness bypass without a reason
    # (the bypass is only meaningful when there is a prior to be stale against).
    return ctx.is_live and ctx.has_prior and ctx.stale_evidence_acknowledged


def _check_stale_evidence_justified(ctx: HookContext):
    # stale_evidence_acknowledged is True ONLY when acknowledged WITHOUT a reason,
    # so whenever this applies it is the WARN state.
    msg = (
        "stale evidence was acknowledged on this commit, but no reason was recorded. "
        "Record WHY nothing material changed since the prior forecast "
        "(stale_evidence_reason=..., CLI --stale-evidence-reason) so the bypass is "
        "auditable — or collect fresh evidence with `forecast refresh <id>`."
    )
    return False, msg, {}


# ── decision readiness ────────────────────────────────────────────────────────
def _check_decision_readiness(ctx: HookContext):
    if not ctx.decision_gaps:
        return _OK
    msg = (
        "forecast update blocked by missing decision context: "
        + "; ".join(ctx.decision_gaps)
        + ". Set decision_owner, action_threshold, and update_triggers "
        "on the question, or rerun without require_decision_readiness."
    )
    return False, msg, {"gaps": list(ctx.decision_gaps)}


# ── panel ─────────────────────────────────────────────────────────────────────
def _check_panel(ctx: HookContext):
    # Blocking only for a high-impact OR re-committed live forecast with neither a
    # linked panel run nor a recorded skip reason. (First-forecast lower-impact
    # panels are "recommended", recorded as a metadata note, not blocked.)
    if not (ctx.high_impact or ctx.has_prior):
        return _OK
    if ctx.panel_linked or ctx.panel_skipped:
        return _OK
    why = "high-impact" if ctx.high_impact else "re-committed (a prior live snapshot exists)"
    msg = (
        f"{why} live forecast requires a deliberative panel: run a "
        "panel or quorum and pass panel_run_ref, record why you skipped it "
        "with panel_skipped_reason, rerun with require_panel=false, or record "
        "it as forecast_origin='exploratory'."
    )
    return False, msg, {"why": why}


# ── citations ─────────────────────────────────────────────────────────────────
def _check_citations(ctx: HookContext):
    if ctx.has_citations:
        return _OK
    msg = (
        "live forecast requires citations: add evidence/model/reference/source refs, "
        "rerun with require_citations=false, or record it as forecast_origin='exploratory'"
    )
    return False, msg, {}


# ── evidence floor (hard requirement) ─────────────────────────────────────────
def _check_require_evidence(ctx: HookContext):
    # The hard guarantee: a live forecast MUST carry at least one evidence record.
    # We assume the operator is lazy, so this is a default ERROR rather than a
    # nudge — an evidence-free forecast is not trustworthy and is not calibrated.
    if ctx.evidence_count >= 1:
        return _OK
    msg = (
        "live forecast has NO evidence attached — evidence is a hard requirement. "
        "Collect at least one source / reference (the agent's research + record_evidence) "
        "before committing; do not coast on the model's prior knowledge."
    )
    return False, msg, {"evidence_count": ctx.evidence_count}


# ── tail paths (categorical) ──────────────────────────────────────────────────
def _check_tail_paths(ctx: HookContext):
    # Only meaningful for categorical; tail_audit_passes is None for others.
    if ctx.tail_audit_passes is None or ctx.tail_audit_passes:
        return _OK
    offenders = ", ".join(ctx.tail_offenders)
    msg = (
        "live categorical forecast has unearned tail mass "
        f"({ctx.tail_unearned_mass:.1%}) on outcomes with no named path: "
        f"{offenders}. Name the mechanism for each (pass "
        "outcome_paths / --outcome-path), compress the mass onto outcomes "
        "with a live path, rerun with require_outcome_paths=false, or record "
        "it as forecast_origin='exploratory'."
    )
    return False, msg, {"unearned_mass": ctx.tail_unearned_mass, "offenders": list(ctx.tail_offenders)}


# ── style (NEW — blocking per the design) ─────────────────────────────────────
def style_message(offending_fields) -> str:
    fields = ", ".join(offending_fields) or "rationale"
    return (
        "live forecast prose violates house style (em-dashes / formatting) in: "
        f"{fields}. Rewrite without em-dashes (use commas) and normalize the "
        "whitespace, or record it as forecast_origin='exploratory'."
    )


def _check_style(ctx: HookContext):
    if ctx.style_clean:
        return _OK
    return False, style_message(ctx.style_offending_fields), {"fields": list(ctx.style_offending_fields)}


# ── calibration lessons applied (NEW — advisory by default) ───────────────────
def _check_lessons_applied(ctx: HookContext):
    if ctx.active_lessons_unapplied <= 0:
        return _OK
    msg = (
        f"{ctx.active_lessons_unapplied} active calibration lesson(s) for this "
        "question were not applied. Pass use_active_lessons=true so the ledger's "
        "measured bias is corrected, not merely noted."
    )
    return False, msg, {"unapplied": ctx.active_lessons_unapplied}


def _rem_collect(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("agentic", "collect_evidence",
                                 "Collect fresh evidence for each driver before re-estimating.",
                                 target_stage="research")


def _rem_run_panel(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("agentic", "run_panel",
                                 "Run a multi-perspective decomposition panel (or record why you skipped it).",
                                 target_stage="model")


def _rem_decompose(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("agentic", "decompose",
                                 "Decompose the estimate into pooled drivers (ensemble_components).",
                                 target_stage="update")


def _rem_compress(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("agentic", "compress_tails",
                                 "Name a path for every material outcome or compress unearned tail mass.",
                                 target_stage="update")


def _rem_style(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("mechanical", "sanitize_style",
                                 "Strip em-dashes / normalize whitespace in prose fields.")


def _rem_lessons(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("mechanical", "none",
                                 "Apply active calibration lessons (use_active_lessons).")


# ── v2 rules ──────────────────────────────────────────────────────────────────
MIN_PERSPECTIVES = 3
MAX_WIDTH_RATIO = 1.0       # an interval wider than the whole question range is absurd
MIN_SHARPNESS = 0.05        # binary: |p-0.5| >= 0.025; below = effectively a coin flip
NULL_EXCESS_TOLERANCE = 0.05

_dist = lambda c: c.is_live and c.is_distribution and not c.is_thesis_or_factor  # noqa: E731


def _check_output_renderable(ctx: HookContext):
    if ctx.distribution_renderable:
        return _OK
    return False, (
        "distribution forecast is not renderable: it needs a central tendency "
        "(median or mean) AND at least one ordered interval (ci90 or quantiles) so "
        "the Desk chart can draw a band. Provide them, or record forecast_origin='exploratory'."
    ), {}


def _check_uncertainty_well_formed(ctx: HookContext):
    if ctx.bounds_well_formed and ctx.bounds_in_range:
        return _OK
    issues = "; ".join(ctx.distribution_issues) or "malformed interval bounds"
    return False, (
        f"forecast uncertainty bounds are malformed: {issues}. Intervals must be ordered "
        "(lo<=hi), nested (ci50 inside ci90), finite, non-degenerate, and within the question "
        "bounds. Fix the distribution, or record forecast_origin='exploratory'."
    ), {"issues": list(ctx.distribution_issues)}


def _check_uncertainty_width(ctx: HookContext):
    if ctx.interval_width_ratio is None or ctx.interval_width_ratio <= MAX_WIDTH_RATIO:
        return _OK
    return False, (
        f"forecast interval is implausibly wide ({ctx.interval_width_ratio:.1f}x the question "
        "range). Tighten it to a defensible spread, or justify the fat tail."
    ), {"width_ratio": ctx.interval_width_ratio}


def _check_quorum_participation(ctx: HookContext):
    # Only meaningful when a panel/quorum actually ran; quorum_required handles "must run".
    if ctx.panel_run_count == 0:
        return _OK
    if ctx.panel_perspective_count >= MIN_PERSPECTIVES or ctx.quorum_model_count >= MIN_PERSPECTIVES:
        return _OK
    return False, (
        f"the deliberation had too few distinct viewpoints "
        f"(perspectives={ctx.panel_perspective_count}, models={ctx.quorum_model_count}; "
        f"need >= {MIN_PERSPECTIVES} of EITHER — a fuller perspective panel OR a wider model quorum). "
        "record_panel reports the distinct counts up front so this isn't a surprise."
    ), {"perspectives": ctx.panel_perspective_count, "models": ctx.quorum_model_count}


def _check_quorum_required(ctx: HookContext):
    # A serious forecast (high-impact or re-committed) must have a panel/quorum RUN
    # linked (stricter than require_panel, which accepts a skip reason).
    if not (ctx.high_impact or ctx.has_prior):
        return _OK
    if ctx.panel_run_count > 0:
        return _OK
    return False, (
        "serious forecast requires an actual panel or model-quorum run (a recorded "
        "skip reason is not enough at this tier). Run a panel or quorum."
    ), {}


def _check_quorum_judged(ctx: HookContext):
    if not ctx.is_quorum:
        return _OK
    if ctx.quorum_judged:
        return _OK
    return False, (
        "quorum run is missing a judge synthesis (consensus + contradictions + blind-spots). "
        "The diverse model views must be reconciled, not just pooled."
    ), {}


def _check_tails_justified(ctx: HookContext):
    bad = (ctx.tail_audit_passes is False) or (ctx.tail_null_excess > NULL_EXCESS_TOLERANCE)
    if not bad:
        return _OK
    return False, (
        f"the forecast over-weights no-path tails (unearned mass on outcomes with no named "
        f"mechanism; null-model excess {ctx.tail_null_excess:.1%}). Name a path for each tail "
        "or compress the mass onto outcomes the evidence supports."
    ), {"null_excess": ctx.tail_null_excess}


def _check_calibration_bias_applied(ctx: HookContext):
    # Only fires when the ledger has MEASURED chronic under-confidence for this scope.
    if not ctx.calibration_under_confident:
        return _OK
    if ctx.active_lessons_unapplied <= 0:
        return _OK
    return False, (
        "this scope is measured chronically UNDER-confident, yet the active calibration "
        "lesson was not applied. Pass use_active_lessons=true to sharpen in the calibrated "
        "direction rather than hedge."
    ), {}


def _check_confidence_committed(ctx: HookContext):
    # Soft nudge: flag near-maximum hedging unless explicitly justified. Never a hard block.
    if ctx.sharpness is None or ctx.sharpness >= MIN_SHARPNESS or ctx.uncertainty_justified:
        return _OK
    return False, (
        "the forecast sits at near-maximum hedging (effectively a coin flip) with no recorded "
        "justification. Commit to a sharper estimate if the evidence supports it, or record an "
        "explicit 'genuine maximum uncertainty' justification (metadata.uncertainty_justified)."
    ), {"sharpness": ctx.sharpness}


def _check_reasoning_composition(ctx: HookContext):
    have = set(ctx.reasoning_methods)
    required = set(ctx.required_reasoning_methods)
    missing = sorted(required - have)
    short = len(have) < ctx.min_reasoning_methods
    if not missing and not short:
        return _OK
    parts = []
    if missing:
        parts.append("missing required methods: " + ", ".join(missing))
    if short:
        parts.append(f"only {len(have)} distinct methods, need >= {ctx.min_reasoning_methods}")
    return False, (
        "reasoning composition is insufficient (" + "; ".join(parts) + "). Declare the reasoning "
        "methods you used in `reasoning_methods` (e.g. outside_view, base_rate, bayesian, pre_mortem)."
    ), {"missing": missing, "have": sorted(have)}


def _rem_fix_distribution(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("mechanical", "fix_distribution", "Reorder/clamp/nest the interval bounds; derive a missing interval.")


def _rem_run_quorum(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("agentic", "run_quorum", "Run a multi-perspective panel or model quorum.", target_stage="model")


def _rem_sharpen(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("agentic", "sharpen", "Commit to a sharper estimate or justify genuine maximum uncertainty.", target_stage="update")


def _rem_tag_reasoning(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("agentic", "tag_reasoning", "Declare the reasoning methods used in reasoning_methods.", target_stage="update")


def _check_thesis_fresh(ctx: HookContext):
    if not ctx.aggregate_stale:
        return _OK
    moved = f"{ctx.newer_member_count} member(s) have moved" if ctx.newer_member_count else "members have moved (or it has never been aggregated)"
    return False, (
        f"this thesis/factor aggregate is STALE: {moved} since the last aggregate, so its "
        "health + member contributions lag the live members. Re-aggregate it (the "
        "member-commit cascade normally keeps this fresh automatically)."
    ), {"newer_member_count": ctx.newer_member_count}


def _rem_run_aggregate(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("mechanical", "run_aggregate", "Re-aggregate the thesis/factor from its current members.")


# ── outside-view anchor (reference class) ─────────────────────────────────────
def _check_outside_view_anchor(ctx: HookContext):
    # Snapshot-honest: a serious forecast must LINK its outside-view anchor to THIS
    # snapshot, not merely have one somewhere on the question (linked_reference_class_count
    # falls back to the question count on non-commit lint, so re-reads don't over-fire).
    if ctx.linked_reference_class_count >= 1:
        return _OK
    claims_outside = any(method in {"outside_view", "base_rate"} for method in ctx.reasoning_methods)
    if ctx.reference_class_count >= 1:
        msg = (
            f"this forecast links NO reference class though the question has {ctx.reference_class_count} — "
            "link your outside-view anchor to THIS snapshot (reference_class_refs, or the inline "
            "reference_class on update_forecast)."
        )
    elif claims_outside:
        msg = (
            "reasoning_methods claims outside_view/base_rate but NO reference class is attached — "
            "anchor the base rate you're claiming to reason from: call the 'add_reference_class' action."
        )
    else:
        msg = (
            "serious live forecast has no outside-view anchor: attach at least one reference class / base rate "
            "(call 'add_reference_class') so the forecast isn't pure inside-view prose."
        )
    return False, msg, {
        "reference_class_count": ctx.reference_class_count,
        "linked_reference_class_count": ctx.linked_reference_class_count,
    }


def _rem_reference_class(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor(
        "agentic", "add_reference_class",
        "Call the 'add_reference_class' action to attach an outside-view reference class / base rate to the forecast.",
        target_stage="research",
    )


# Ordered to match the legacy gate evaluation order (so the first blocking
# failure yields the same message the inline gates raised first), then the two
# additive rules.
BUILTIN_RULES: tuple[SimpleRule, ...] = (
    SimpleRule("require_structured_reasoning", Category.SATURATION, Severity.ERROR, 15.0,
               _check_structured_reasoning, _modeled, lambda c: RemediationDescriptor("agentic", "decompose", "Add reasons_up / reasons_down / change_my_mind.", target_stage="update")),
    SimpleRule("require_components", Category.SATURATION, Severity.ERROR, 15.0,
               _check_components, _live, _rem_decompose),
    SimpleRule("require_fresh_evidence", Category.SATURATION, Severity.ERROR, 15.0,
               _check_fresh_evidence, _applies_fresh_evidence, _rem_collect),
    SimpleRule("stale_evidence_justified", Category.SATURATION, Severity.WARN, 6.0,
               _check_stale_evidence_justified, _applies_stale_evidence_justified, _rem_collect),
    SimpleRule("require_decision_readiness", Category.DECISION, Severity.WARN, 6.0,
               _check_decision_readiness, _live),
    SimpleRule("require_panel", Category.SATURATION, Severity.ERROR, 12.0,
               _check_panel, _modeled, _rem_run_panel),
    SimpleRule("require_citations", Category.SATURATION, Severity.WARN, 8.0,
               _check_citations, _modeled, _rem_collect),
    SimpleRule("require_evidence", Category.SATURATION, Severity.ERROR, 16.0,
               _check_require_evidence, _modeled, _rem_collect),
    SimpleRule("require_outside_view_anchor", Category.REASONING, Severity.WARN, 9.0,
               _check_outside_view_anchor, _modeled, _rem_reference_class),
    SimpleRule("require_outcome_paths", Category.SATURATION, Severity.WARN, 10.0,
               _check_tail_paths, lambda c: c.is_live and c.is_categorical, _rem_compress),
    SimpleRule("style_clean", Category.STYLE, Severity.ERROR, 5.0,
               _check_style, _live, _rem_style),
    SimpleRule("lessons_applied", Category.CALIBRATION, Severity.WARN, 6.0,
               _check_lessons_applied, _live, _rem_lessons),
    # v2 — output / uncertainty structure
    SimpleRule("output_renderable", Category.OUTPUT, Severity.ERROR, 12.0,
               _check_output_renderable, _dist, _rem_fix_distribution),
    SimpleRule("uncertainty_well_formed", Category.OUTPUT, Severity.ERROR, 12.0,
               _check_uncertainty_well_formed, _dist, _rem_fix_distribution),
    SimpleRule("uncertainty_width_sane", Category.OUTPUT, Severity.WARN, 6.0,
               _check_uncertainty_width, _dist, _rem_fix_distribution),
    # v2 — quorum / panel participation
    SimpleRule("quorum_participation", Category.QUORUM, Severity.WARN, 8.0,
               _check_quorum_participation, _modeled, _rem_run_quorum),
    SimpleRule("quorum_required", Category.QUORUM, Severity.WARN, 10.0,
               _check_quorum_required, _modeled, _rem_run_quorum),
    SimpleRule("quorum_judged", Category.QUORUM, Severity.WARN, 6.0,
               _check_quorum_judged, _modeled, _rem_run_quorum),
    # v2 — confidence lean
    SimpleRule("tails_justified", Category.CONFIDENCE, Severity.WARN, 10.0,
               _check_tails_justified, lambda c: c.is_live and c.is_categorical, _rem_compress),
    SimpleRule("calibration_bias_applied", Category.CONFIDENCE, Severity.WARN, 6.0,
               _check_calibration_bias_applied, _live, _rem_sharpen),
    SimpleRule("confidence_committed", Category.CONFIDENCE, Severity.WARN, 6.0,
               _check_confidence_committed, _live, _rem_sharpen),
    # v2 — reasoning composition
    SimpleRule("reasoning_composition", Category.REASONING, Severity.WARN, 8.0,
               _check_reasoning_composition, _modeled, _rem_tag_reasoning),
    # v3 — thesis/factor aggregate freshness (members moved since last aggregate)
    SimpleRule("thesis_aggregate_fresh", Category.SATURATION, Severity.WARN, 8.0,
               _check_thesis_fresh, lambda c: c.is_live and c.is_thesis_or_factor, _rem_run_aggregate),
)

BUILTIN_RULE_IDS: tuple[str, ...] = tuple(r.id for r in BUILTIN_RULES)

# Human-readable "what this rule checks" for the TUI inspector + `forecast hooks`.
RULE_DOCS: dict[str, str] = {
    "require_structured_reasoning": "Reasons up / down / change-my-mind must all be present.",
    "require_components": "The forecast must decompose into pooled ensemble components.",
    "require_fresh_evidence": "Evidence must be freshly collected for this commit (no stale re-run).",
    "stale_evidence_justified": "If you acknowledge stale evidence to skip the freshness gate, record a reason.",
    "require_decision_readiness": "The decision card should have no missing fields.",
    "require_panel": "A deliberation panel must run (or record an explicit skip reason).",
    "require_citations": "The forecast should cite evidence / model runs.",
    "require_evidence": "A live forecast MUST carry at least one evidence record (hard requirement).",
    "require_outside_view_anchor": "A serious live forecast should carry an outside-view anchor (reference class / base rate).",
    "require_outcome_paths": "Every material categorical outcome needs a named path (no unearned tails).",
    "style_clean": "Prose must be house-clean (no em-dashes / formatting issues).",
    "lessons_applied": "Active calibration lessons should be applied to the commit.",
    "output_renderable": "A distribution needs a central tendency + an ordered interval the charts can draw.",
    "uncertainty_well_formed": "Intervals must be ordered, nested, finite, non-degenerate, in-bounds.",
    "uncertainty_width_sane": "Intervals must not be implausibly wide vs the question range.",
    "quorum_participation": "A panel/quorum that runs needs enough distinct perspectives.",
    "quorum_required": "Serious forecasts (high-impact / re-commit) need an actual panel or quorum run.",
    "quorum_judged": "A model quorum must carry a judge synthesis (consensus + contradictions).",
    "tails_justified": "No-path tails must be justified; do not over-weight unearned outcomes.",
    "calibration_bias_applied": "When measured under-confident, apply the calibration lesson.",
    "confidence_committed": "Avoid near-maximum hedging unless genuine uncertainty is justified.",
    "reasoning_composition": "Declare a sufficient set + count of reasoning methods.",
    "thesis_aggregate_fresh": "A thesis/factor must re-aggregate after its members move (no stale health).",
}

_RULE_BY_ID = {r.id: r for r in BUILTIN_RULES}


def rule_doc(rule_id: str) -> str:
    return RULE_DOCS.get(rule_id, "")


def builtin_rule_meta(rule_id: str) -> dict | None:
    """Static metadata for a built-in rule (category + default severity +
    remediation action) for the TUI inspector. None for unknown ids."""
    r = _RULE_BY_ID.get(rule_id)
    if r is None:
        return None
    action = "none"
    try:
        if r.remediation_fn is not None:
            action = r.remediation_fn(HookContext(question_id="_", forecast_origin="live", event="update")).action
    except Exception:
        action = "none"
    return {
        "category": r.category.value,
        "default": r.default_severity.value,
        "remediation": action,
        "doc": RULE_DOCS.get(rule_id, ""),
    }
