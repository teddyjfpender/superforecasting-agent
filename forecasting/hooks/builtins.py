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
from forecasting.hooks.thresholds import DEFAULT_MIN_EVIDENCE_COUNT, DEFAULT_READINESS_FLOOR

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


# ── machine-readiness floor (the Desk "RDY" score — previously UN-enforced) ────
# The autonomous desk keeps a forecast alive from its machine-workability inputs
# (watched sources, structured components, reference classes, an executable update
# trigger, an enabled review schedule, resolution scaffolding). readiness_lens
# scores that 0-100. Below the floor the loop is literally missing inputs — this
# rule surfaces that at commit. Tunable via FORECAST_HOOK_READINESS_FLOOR (or the
# per-question ``readiness_floor`` threshold override).


def _check_readiness_floor(ctx: HookContext):
    # A benchmark/market commit with no composite carries readiness_score=None -> PASS.
    if ctx.readiness_score is None:
        return _OK
    floor = ctx.threshold("readiness_floor")
    if floor is None:
        try:
            from forecasting import appconfig
            floor = appconfig.get_float("FORECAST_HOOK_READINESS_FLOOR")
        except Exception:
            floor = None
    if floor is None:
        floor = DEFAULT_READINESS_FLOOR
    if ctx.readiness_score >= floor:
        return _OK
    msg = (
        f"machine-readiness for this forecast is {ctx.readiness_score:.0f}/100, below the "
        f"floor of {floor:.0f}. The autonomous desk is missing inputs it needs to keep this "
        "forecast alive (watched sources, structured components, reference classes, an "
        "executable update trigger, an enabled review schedule). Close the readiness gaps "
        "(Desk RDY / `forecast readiness`) before committing, or record it as "
        "forecast_origin='exploratory'."
    )
    return False, msg, {"readiness_score": ctx.readiness_score, "floor": floor}


# ── watched sources present (the desk can only refresh what it watches) ────────
def _check_no_watched_sources(ctx: HookContext):
    if ctx.watched_source_count > 0:
        return _OK
    msg = (
        "live forecast has NO active watched sources: the autonomous desk cannot refresh "
        "this forecast without a source to watch, so it will silently go stale. Add at "
        "least one watched source (`forecast watch add <source> --question <id>`), or "
        "record it as forecast_origin='exploratory'."
    )
    return False, msg, {"watched_source_count": ctx.watched_source_count}


# ── evidence depth (the Desk EV floor, distinct from "any evidence") ──────────
def _check_evidence_depth(ctx: HookContext):
    floor = ctx.threshold("min_evidence_count")
    if floor is None:
        floor = DEFAULT_MIN_EVIDENCE_COUNT
    if ctx.evidence_count >= floor:
        return _OK
    msg = (
        f"live forecast has {ctx.evidence_count} evidence item(s), below the default "
        f"EV floor of {floor:.0f}. Add enough independent, decision-relevant evidence "
        "items for the forecast to clear the desk lint floor, or record it as "
        "forecast_origin='exploratory'."
    )
    return False, msg, {"evidence_count": ctx.evidence_count, "floor": floor}


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


# ── terminal Platt calibration applied (NEW — advisory by default) ────────────
def _applies_terminal_calibration(ctx: HookContext) -> bool:
    # Only meaningful for a live, modeled commit that LINKED a panel run: the
    # terminal calibration stage lives inside panel aggregation, so a forecast
    # with no panel has nothing to skip. (Exploratory origin is exempt via
    # _modeled's is_live requirement.)
    return ctx.is_live and not ctx.is_thesis_or_factor and ctx.panel_linked


def _check_terminal_calibration_applied(ctx: HookContext):
    if ctx.terminal_calibration_present:
        return _OK
    msg = (
        "this live forecast linked a panel run that SKIPPED the terminal Platt "
        "calibration stage (no applied_alpha recorded on the pool). Re-run the panel "
        "through aggregate_panel_estimates so the pooled scalar is recalibrated "
        "(alpha_extremize, default 1.0 = identity), or record it as "
        "forecast_origin='exploratory'."
    )
    return False, msg, {}


def _rem_recalibrate(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor("mechanical", "recalibrate_pool",
                                 "Re-aggregate the panel so the terminal Platt calibration stage records applied_alpha.",
                                 target_stage="update")


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
# These constants are the DEFAULT minimum-requirement floors/ceilings. They are
# tunable per-forecast: each gate reads ``ctx.threshold(<key>)`` first and only
# falls back to the constant when the question carries no override (see
# forecasting/hooks/thresholds.py for the registry the ledger + TUI share).
from forecasting.hooks.thresholds import (  # noqa: E402
    DEFAULT_MAX_WIDTH_RATIO,
    DEFAULT_MIN_PERSPECTIVES,
    DEFAULT_MIN_SHARPNESS,
    DEFAULT_NULL_EXCESS_TOLERANCE,
)

MIN_PERSPECTIVES = DEFAULT_MIN_PERSPECTIVES
MAX_WIDTH_RATIO = DEFAULT_MAX_WIDTH_RATIO       # an interval wider than the whole question range is absurd
MIN_SHARPNESS = DEFAULT_MIN_SHARPNESS           # binary: |p-0.5| >= 0.025; below = effectively a coin flip
NULL_EXCESS_TOLERANCE = DEFAULT_NULL_EXCESS_TOLERANCE

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
    limit = ctx.threshold("max_width_ratio")
    if limit is None:
        limit = MAX_WIDTH_RATIO
    if ctx.interval_width_ratio is None or ctx.interval_width_ratio <= limit:
        return _OK
    return False, (
        f"forecast interval is implausibly wide ({ctx.interval_width_ratio:.1f}x the question "
        "range). Tighten it to a defensible spread, or justify the fat tail."
    ), {"width_ratio": ctx.interval_width_ratio, "limit": limit}


def _check_quorum_participation(ctx: HookContext):
    # Only meaningful when THIS context actually carries a counted deliberation to
    # judge — key on the SAME signal the counts are derived from (perspectives /
    # models), NOT the question-total panel_run_count. On the commit path the
    # participation counts come only from the run linked to this commit (0 when
    # unlinked) while panel_run_count spans ALL historical runs; keying on
    # panel_run_count there false-fired this rule for an unlinked re-commit whose
    # question merely had an older panel run. quorum_required handles "must run".
    if not (ctx.panel_perspective_count or ctx.quorum_model_count):
        return _OK
    need = ctx.threshold("min_perspectives")
    need = MIN_PERSPECTIVES if need is None else int(need)
    if ctx.panel_perspective_count >= need or ctx.quorum_model_count >= need:
        return _OK
    return False, (
        f"the deliberation had too few distinct viewpoints "
        f"(perspectives={ctx.panel_perspective_count}, models={ctx.quorum_model_count}; "
        f"need >= {need} of EITHER — a fuller perspective panel OR a wider model quorum). "
        "record_panel reports the distinct counts up front so this isn't a surprise."
    ), {"perspectives": ctx.panel_perspective_count, "models": ctx.quorum_model_count, "need": need}


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
    tol = ctx.threshold("null_excess_tolerance")
    tol = NULL_EXCESS_TOLERANCE if tol is None else tol
    bad = (ctx.tail_audit_passes is False) or (ctx.tail_null_excess > tol)
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
    floor = ctx.threshold("min_sharpness")
    floor = MIN_SHARPNESS if floor is None else floor
    if ctx.sharpness is None or ctx.sharpness >= floor or ctx.uncertainty_justified:
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
    # An explicit per-question override wins over the profile-resolved floor.
    over = ctx.threshold("min_reasoning_methods")
    need = ctx.min_reasoning_methods if over is None else int(over)
    short = len(have) < need
    if not missing and not short:
        return _OK
    parts = []
    if missing:
        parts.append("missing required methods: " + ", ".join(missing))
    if short:
        parts.append(f"only {len(have)} distinct methods, need >= {need}")
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


# ── research adequacy (VOI-directed research judge) ───────────────────────────
def _check_research_adequate(ctx: HookContext):
    # research_adequate is precomputed at commit-context build from the deterministic
    # research_audit checks (NO LLM at commit). True by default so a commit whose
    # audit could not be computed never false-fires.
    if ctx.research_adequate:
        return _OK
    score = ctx.research_adequacy_score
    score_txt = f" (adequacy {score:.0f}/100)" if isinstance(score, (int, float)) else ""
    return False, (
        f"the research backing this forecast is thin on a lever that matters{score_txt}: it is "
        "missing a reference class, below the evidence floor, single-sourced, has no disconfirming "
        "evidence, is stale, or leaves an executable update trigger unwatched. Call the "
        "forecast_ledger research_audit action, work the VOI angles from research_plan, and close the "
        "gaps it lists before committing."
    ), {"adequacy_score": score}


def _rem_research(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor(
        "agentic", "collect_evidence",
        "Run research_plan + research_audit and close the listed research gaps (reference class, "
        "evidence floor, independent source, disconfirming evidence, recency, trigger coverage).",
        target_stage="research",
    )


# ── outside-view anchor (reference class) ─────────────────────────────────────
def _check_outside_view_anchor(ctx: HookContext):
    # G3 · ANCHOR UNIVERSALITY (two tiers, no re-forecast bricking).
    #   * HIGH-IMPACT (any commit) — the forecasts that most need an outside view.
    #   * FIRST live commit of ANY question (``not has_prior``) — the cheapest, most
    #     valuable moment for the anchor, and the one with NO re-forecast flow to
    #     brick (the has_prior trap that scoped this rule last time was about
    #     RE-commits; a first commit has no prior to be stale against). On the read/
    #     lint path has_prior is True for every current snapshot, so the first-commit
    #     tier fires 0 retroactively — it binds only NEW questions going forward.
    # A non-high-impact RE-commit self-passes here (the outside_view_refresh WARN
    # nags it instead, without blocking the flow).
    first_commit = not ctx.has_prior
    if not (ctx.high_impact or first_commit):
        return _OK
    # Snapshot-honest: a serious forecast must LINK its outside-view anchor to THIS
    # snapshot, not merely have one somewhere on the question (linked_reference_class_count
    # falls back to the question count on non-commit lint, so re-reads don't over-fire).
    if ctx.linked_reference_class_count >= 1:
        return _OK
    claims_outside = any(method in {"outside_view", "base_rate"} for method in ctx.reasoning_methods)
    _opener = "first live forecast on this question requires an outside-view anchor: " if (first_commit and not ctx.high_impact) else ""
    if ctx.reference_class_count >= 1:
        msg = (
            f"{_opener}this forecast links NO reference class though the question has {ctx.reference_class_count} — "
            "link your outside-view anchor to THIS snapshot (reference_class_refs, or the inline "
            "reference_class on update_forecast)."
        )
    elif claims_outside:
        msg = (
            f"{_opener}reasoning_methods claims outside_view/base_rate but NO reference class is attached — "
            "anchor the base rate you're claiming to reason from: call the 'add_reference_class' action."
        )
    else:
        msg = (
            f"{_opener}serious live forecast has no outside-view anchor: attach at least one reference class / base rate "
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


# ── G3 · outside-view REFRESH tier (WARN) ─────────────────────────────────────
# The non-blocking companion to the anchor gate: a routine RE-forecast of a
# question that has NEVER carried a reference class (pure inside view since birth)
# WARNs — surfaced, not blocked. It checks the QUESTION level (not the snapshot
# link) precisely so a routine re-commit need not re-link its anchor every time,
# which is the vector that bricked the re-forecast flow. High-impact re-commits are
# already ERROR-gated by require_outside_view_anchor, so this tier scopes OUT of
# high-impact to avoid a double verdict.
def _applies_outside_view_refresh(ctx: HookContext) -> bool:
    return ctx.is_live and not ctx.is_thesis_or_factor and ctx.has_prior and not ctx.high_impact


def _check_outside_view_refresh(ctx: HookContext):
    if ctx.reference_class_count >= 1:
        return _OK
    msg = (
        "this question still has NO reference class on the books — the forecast has been "
        "pure inside view since birth. Call 'add_reference_class' with the base rate you are "
        "implicitly using; if you cannot name one, that is the finding."
    )
    return False, msg, {"reference_class_count": ctx.reference_class_count}


# ── G4 · granularity discipline (Tetlock's hallmark) ──────────────────────────
# The WARN-FOREVER half of the confidence family (confidence_committed is the
# hedging half): flag a binary commit that sits on a round-number anchor (a 0.10
# multiple, or 0.25/0.5/0.75) that NO pooled component actually produced and that
# carries no uncertainty_justified escape. Never ERROR — hard-gating precision
# teaches models to fabricate 0.43s, the opposite failure. It exists to make
# round-number anchoring VISIBLE (the desk badge + the adherence scorecard).
def _applies_granularity(ctx: HookContext) -> bool:
    return (
        ctx.is_live and not ctx.is_thesis_or_factor
        and (ctx.outcome_type == "binary" or (ctx.outcome_type is None and not ctx.is_categorical and not ctx.is_distribution))
    )


def _check_granularity_disciplined(ctx: HookContext):
    if not ctx.round_number_anchored:
        return _OK
    p = ctx.committed_winner_prob
    p_txt = f"{p:g}" if isinstance(p, (int, float)) else "a round number"
    msg = (
        f"the committed probability {p_txt} is a round-number anchor (a 0.10 multiple, or "
        "0.25/0.5/0.75) that no pooled component actually produced. Tetlock's granularity "
        "finding: superforecasters' edge lives in distinctions finer than 10%. Re-pool the "
        "components and commit the number the evidence computes — or record uncertainty_justified "
        "if the roundness is genuinely earned."
    )
    return False, msg, {"p": p}


# ── G5 · update-cadence escalation (SWEEP-SIDE) ───────────────────────────────
# A stale question is stale precisely because it is NOT committing, so a commit-time
# gate is the wrong shape. This rule evaluates ONLY on lint/finish_sweep events: a
# question whose current snapshot has out-lived its review cadence (past the grace
# multiple) with no recorded stale_evidence_reason fails, which drops its saturation
# below the desk badge bar and rides the sweep_saturation_alerts → deduped
# cadence-overdue alert the cron already services. WARN in standard (a red badge +
# alert priority), ERROR in strict; commits are never touched.
def _applies_update_cadence(ctx: HookContext) -> bool:
    return (
        ctx.event in ("lint", "finish_sweep")
        and ctx.is_live and not ctx.is_thesis_or_factor
        and ctx.review_cadence is not None
    )


def _check_update_cadence_honored(ctx: HookContext):
    grace = ctx.threshold("cadence_grace_ratio")
    if grace is None:
        from forecasting.hooks.thresholds import DEFAULT_CADENCE_GRACE_RATIO
        grace = DEFAULT_CADENCE_GRACE_RATIO
    if ctx.cadence_overdue_ratio <= grace:
        return _OK
    if ctx.cadence_reason_recorded:
        return _OK  # an acknowledged, explained pause is honest
    cadence = ctx.review_cadence or "weekly"
    msg = (
        f"this forecast is {ctx.cadence_overdue_ratio:.1f}x past its {cadence} review cadence with no "
        "recorded reason. A forecast that is not updated on cadence is not a live forecast — run "
        "`forecast refresh <id>` (or the autonomous cycle), or record stale_evidence_reason if "
        "nothing material can have changed."
    )
    return False, msg, {"overdue_ratio": ctx.cadence_overdue_ratio, "cadence": cadence}


# ── G7 · crux minimum on high-impact ──────────────────────────────────────────
# A high-impact commit must carry >=1 registered crux (the variable that would most
# change the call) OR name why none exists (crux_skip_reason). In-flow this is nearly
# free: a high-impact commit already requires a panel (require_panel ERROR), and the
# panel auto-promotes its cruxes into question_cruxes before the commit reaches the
# gate, so the rule binds only the panel-skipped path + pre-promotion legacy
# questions — exactly the ones that should explain themselves. WARN standard (60/63
# cruxless today — WARN-first, promote after the crux backfill), ERROR strict.
def _applies_crux_named(ctx: HookContext) -> bool:
    return ctx.is_live and not ctx.is_thesis_or_factor and ctx.high_impact


def _check_crux_named(ctx: HookContext):
    if ctx.crux_count >= 1:
        return _OK
    if (ctx.crux_skip_reason or "").strip():
        return _OK
    msg = (
        "high-impact forecast has no registered crux: nothing on the question names the variable "
        "that would most change this call. Run the panel (its cruxes auto-promote), promote them "
        "with `forecast crux backfill --apply`, or record crux_skip_reason explaining why no single "
        "crux exists. change_my_mind prose is not a tracked crux — a crux row is watchable, "
        "statusable, and survives the next re-forecast."
    )
    return False, msg, {"crux_count": ctx.crux_count}


def _rem_run_panel_crux(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor(
        "agentic", "run_panel",
        "Run the panel (its cruxes auto-promote) or record crux_skip_reason.",
        target_stage="model",
    )


# ── G8 · market-anchor universality (the deviation-ledger path) ───────────────
# Any commit on a question with a LINKED market must record the market price +
# deviation, even outside a quorum job (the discipline was a quorum courtesy, not a
# commit invariant — deviation_bets had 0 rows while 7 live questions watched
# markets). The rule requires ENGAGEMENT (record the price and, past threshold, the
# named edge), never AGREEMENT — the soul's anti-market-echo stance is untouched.
# WARN standard (6/7 record no comparison — WARN-first), ERROR strict.
def _applies_market_anchor_engaged(ctx: HookContext) -> bool:
    return ctx.is_live and not ctx.is_thesis_or_factor and ctx.has_linked_market


def _check_market_anchor_engaged(ctx: HookContext):
    if ctx.market_comparison_recorded:
        return _OK
    if (ctx.market_skip_reason or "").strip():
        return _OK
    from forecasting.hooks.thresholds import DEFAULT_NAMED_OUTCOME_ANCHOR_SHARE  # noqa: F401 (kept for parity)
    source = ctx.linked_market_source or "a market source"
    msg = (
        f"this question has a live market ({source}) but the commit records no comparison against it. "
        "Run the quorum (its blind-then-reconcile phase records the anchor, the deviation, and the "
        "named edge automatically), or stamp metadata.market_comparison = {price, deviation_pp, "
        "justification} — a deviation past the threshold with a named edge becomes a pre-registered "
        "deviation bet the ledger scores at resolution. Disagreeing with the market is fine; not "
        "knowing you disagree is not."
    )
    return False, msg, {"source": ctx.linked_market_source}


def _rem_run_quorum_market(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor(
        "agentic", "run_quorum",
        "Run the quorum (records the market anchor + deviation) or stamp metadata.market_comparison.",
        target_stage="model",
    )


# ── G1 · distribution-tail base rates (the Binface gate) ──────────────────────
# The categorical tail-audit family keyed on ``is_categorical`` alone, so a
# candidate-share DISTRIBUTION (the Clacton shape) was never audited — a named
# person could carry material, unearned, uncited mass forever. This closes that:
# every named, non-residual outcome above the anchor-share threshold must carry a
# cited base rate (outside view), else the mass belongs in the residual bucket.
def _applies_tail_base_rates(ctx: HookContext) -> bool:
    return ctx.is_live and not ctx.is_thesis_or_factor and (ctx.is_categorical or ctx.is_candidate_share)


def _check_tail_base_rates(ctx: HookContext):
    if not ctx.share_named_unanchored:
        return _OK
    threshold = ctx.threshold("named_outcome_anchor_share")
    if threshold is None:
        from forecasting.tail_audit import DEFAULT_NAMED_ANCHOR_SHARE
        threshold = DEFAULT_NAMED_ANCHOR_SHARE
    kind = "vote-share" if ctx.is_candidate_share else "categorical"
    offenders = ", ".join(ctx.share_named_unanchored)
    msg = (
        f"live {kind} forecast puts {ctx.share_named_unanchored_mass:.1%} on named outcome(s) with NO "
        f"cited base rate: {offenders}. A named person or option above {threshold:.0%} must carry an "
        "outside view — pass outcome_paths with base_rate + base_rate_source for each (e.g. the "
        "candidate's own prior vote shares), link a reference class scoped to that outcome, or move "
        "the mass into the residual 'Other' bucket where unanchored mass belongs. Precision you "
        "cannot cite is not precision."
    )
    return False, msg, {"offenders": list(ctx.share_named_unanchored), "mass": ctx.share_named_unanchored_mass}


# ── G2 · per-candidate interval coherence ─────────────────────────────────────
# Intervals live out-of-band in metadata.candidate_share_intervals_pp. When they
# are present, nothing validated coverage or coherence — a band could contradict
# its own point. This is a structural bug-catcher (same class as
# uncertainty_well_formed): a malformed band is rejected; ABSENCE stays honest
# (the presence gate is P2, this rule only fires when intervals are present).
def _applies_candidate_intervals_coherent(ctx: HookContext) -> bool:
    return (
        ctx.is_live and not ctx.is_thesis_or_factor
        and ctx.is_candidate_share and ctx.candidate_intervals_present
    )


def _check_candidate_intervals_coherent(ctx: HookContext):
    if ctx.candidate_intervals_coherent:
        return _OK
    tol = ctx.threshold("interval_median_tolerance_pp")
    if tol is None:
        from forecasting.hooks.thresholds import DEFAULT_INTERVAL_MEDIAN_TOLERANCE_PP
        tol = DEFAULT_INTERVAL_MEDIAN_TOLERANCE_PP
    issues = "; ".join(ctx.candidate_interval_issues) or "malformed intervals"
    msg = (
        f"per-candidate intervals are malformed: {issues}. Each candidate needs finite "
        f"p05 <= median <= p95, the median within {tol:.0f}pp of the committed share, inside the "
        "question bounds. Fix the intervals — a band that contradicts its own point is worse than "
        "no band."
    )
    return False, msg, {"issues": list(ctx.candidate_interval_issues)}


# ── G2 · per-candidate interval PRESENCE (P2) ─────────────────────────────────
# The committer now COMPUTES intervals when absent (ensemble spread > model quantiles
# > evidence-tied default), so on the commit path this passes with coverage 1.0. The
# WARN exists to make an UN-refilled live board visible on lint/sweep: a HIGH-IMPACT
# vote-share forecast that carries no per-candidate uncertainty (was silently honest)
# now WARNs in standard (ERROR in strict), unless a no_interval_reason is recorded. The
# require_outside_view_anchor precedent — land WARN, promote once the fire rate is read.
def _applies_candidate_intervals_present(ctx: HookContext) -> bool:
    return (
        ctx.is_live and not ctx.is_thesis_or_factor
        and ctx.is_candidate_share and ctx.high_impact
    )


def _check_candidate_intervals_present(ctx: HookContext):
    if (ctx.no_interval_reason or "").strip():
        return _OK
    if ctx.candidate_interval_coverage is not None and ctx.candidate_interval_coverage >= 1.0:
        return _OK
    cov = ctx.candidate_interval_coverage
    cov_txt = f" (coverage {cov:.0%})" if isinstance(cov, (int, float)) else ""
    msg = (
        f"high-impact vote-share forecast carries no per-candidate uncertainty{cov_txt}: add "
        "metadata.candidate_share_intervals_pp = {candidate: {p05, median, p95}} (percentage "
        "points) for every named candidate — the Desk draws an error bar per candidate and the "
        "scorer grades interval coverage at resolution. The committer computes these from the "
        "ensemble spread automatically; if intervals are genuinely not computable here, record "
        "no_interval_reason. A point share with no spread is a claim you did not quantify."
    )
    return False, msg, {"coverage": cov}


# ── BLF · belief trajectories present (A1) ────────────────────────────────────
# A panel-backed live commit whose panel ran AFTER the BLF gates shipped must carry
# per-panelist belief trajectories (the sequential revision that IS BLF's result vs
# its terminal-synthesis baseline). A search-enabled panelist owes >=2 steps; a
# single step is allowed WITH a recorded reason. RETROACTIVITY: applies ONLY to a
# post-harvest panel run (panel_ran_post_harvest) — a panel that predates the
# machinery is never judged for it, so this fires ~0 on the current board.
def _applies_belief_trajectory(ctx: HookContext) -> bool:
    return _modeled(ctx) and ctx.panel_ran_post_harvest


def _check_belief_trajectory_present(ctx: HookContext):
    if ctx.belief_trajectory_ok:
        return _OK
    offenders = ", ".join(ctx.belief_trajectory_offenders) or "the panelists"
    need = (
        "at least two belief-revision steps (or a single step WITH its reason)"
        if ctx.belief_trajectory_search_enabled
        else "at least one recorded belief step"
    )
    msg = (
        f"this panel run recorded no per-panelist belief trajectory for: {offenders}. "
        f"Each panelist must emit {need} on panel_estimates.metadata.belief_trajectory "
        "— the ordered {step, probability, evidence_for/against, moved_by} revisions "
        "where moved_by names what moved the number. Sequential revision is BLF's "
        "result over terminal synthesis; re-run the panel so the trajectory is captured."
    )
    return False, msg, {"offenders": list(ctx.belief_trajectory_offenders)}


def _rem_belief_trajectory(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor(
        "agentic", "run_panel",
        "Re-run the panel so each panelist emits its ordered belief_trajectory (the "
        "moved_by revisions), >=2 steps for a search-enabled seat.",
        target_stage="model",
    )


# ── BLF · pool-shrinkage provenance recorded + valid (A3) ─────────────────────
# A post-harvest quorum-pooled commit must carry the variance-adaptive pool-shrinkage
# provenance (α + inputs) so every pooled number's shrink toward the outside-view
# anchor is reconstructable. A present-but-garbage α (does not reconstruct from the
# documented formula) is the sharp fault; an ABSENCE on a non-calm MARKET-linked panel
# — where a shrink should have been recorded — is the softer nag (anchorless absence is
# legitimate: nothing to shrink toward). RETROACTIVITY: post-harvest quorum runs only.
def _applies_pool_shrinkage(ctx: HookContext) -> bool:
    return _modeled(ctx) and ctx.is_quorum and ctx.panel_ran_post_harvest


def _check_pool_shrinkage_recorded(ctx: HookContext):
    if ctx.pool_shrinkage_present and not ctx.pool_shrinkage_valid:
        msg = (
            "this quorum's pool-shrinkage provenance is invalid: the recorded α does NOT "
            "reconstruct from the documented A3 formula "
            "(α = clamp01(max(floor, 1 − c·max(0, s² − s²_calm)))). A fabricated or drifted "
            "provenance is worse than none — re-run the quorum so shrink_pool_toward_anchor "
            "stamps the real α + inputs (var_logit, anchor, floor, c, calm_var)."
        )
        return False, msg, {"fault": "garbage"}
    if (not ctx.pool_shrinkage_present) and ctx.pool_non_calm and ctx.has_linked_market:
        msg = (
            "this market-linked quorum disagreed past the calm dead-zone but recorded NO "
            "pool-shrinkage provenance: the variance-adaptive shrink toward the market anchor "
            "left no α + inputs on the pool. Re-run the quorum through run_quorum so "
            "QuorumResult.pool_shrinkage is stamped, or record why the shrink was skipped."
        )
        return False, msg, {"fault": "absent"}
    return _OK


def _rem_pool_shrinkage(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor(
        "agentic", "run_quorum",
        "Re-run the quorum so the variance-adaptive cross-model pool shrinkage records "
        "its α + inputs (QuorumResult.pool_shrinkage).",
        target_stage="model",
    )


# ── BLF · specialist seat considered (A5, WARN-only) ──────────────────────────
# A continuous/count/temperature live commit where attach_specialists WOULD offer a
# runnable deterministic seat (a derivable threshold) but the post-harvest panel shows
# NO specialist seat AND none honestly declined is nudged (WARN forever — a specialist
# on the wrong question is worse than none, so this never hard-gates). A recorded
# SpecialistDeclined passes. RETROACTIVITY: post-harvest panel runs only.
def _applies_specialist_seat(ctx: HookContext) -> bool:
    return _modeled(ctx) and ctx.panel_ran_post_harvest and ctx.specialist_offerable


def _check_specialist_seat_considered(ctx: HookContext):
    if ctx.specialist_seat_present or ctx.specialist_declined:
        return _OK
    series = ctx.specialist_series or "the question's series"
    msg = (
        "this continuous/count forecast could seat a deterministic specialist "
        "(climatology KNN / seasonal-naive over "
        f"{series}) but the panel ran without one and none declined. Attach the "
        "specialist seats (attach_specialists) so the honest outside view — the historical "
        "same-season distribution — votes alongside the LLM panel, or let the seat DECLINE "
        "on the record if its series is unreachable."
    )
    return False, msg, {"series": ctx.specialist_series}


def _rem_specialist_seat(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor(
        "agentic", "run_quorum",
        "Re-run the quorum with attach_specialists so the deterministic climatology / "
        "seasonal-naive seats are offered (they decline honestly if their series is missing).",
        target_stage="model",
    )


# ── thesis-remediation gate family (anchor re-link + event-band honesty) ──────
# THE ORPHANED-ANCHOR GATE. Distinct from require_outside_view_anchor: that gate
# fires when NO anchor exists (an agentic research task); THIS one fires only when
# an anchor EXISTS on the question but is not linked on the snapshot — a MECHANICAL
# defect (re-link, no research). It reads snapshot_reference_class_count, the honest
# unmasked count, so it is visible on lint where the anchor gate is deliberately
# masked to the question count.
def _applies_anchor_refs_attached(ctx: HookContext) -> bool:
    return ctx.is_live and not ctx.is_thesis_or_factor and ctx.reference_class_count >= 1


def _check_anchor_refs_attached(ctx: HookContext):
    if ctx.snapshot_reference_class_count >= 1:
        return _OK
    return False, (
        f"this question has {ctx.reference_class_count} reference class(es) on the books but the "
        "current snapshot links NONE of them — the outside-view anchor is ORPHANED off the snapshot. "
        "This is a MECHANICAL fix (the class already exists): run `forecast reference-class relink "
        "--apply` to re-attach it, or stamp reference_class_refs on the next commit."
    ), {"reference_class_count": ctx.reference_class_count}


def _rem_relink_anchor(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor(
        "mechanical", "add_reference_class",
        "Re-attach the question's existing reference class to the current snapshot (forecast reference-class relink --apply).",
    )


# THE EVENT-BAND-EARNED GATE. A thesis is a joint event; its headline should be a
# scoreable P(event) with a band EARNED from the members. Two failure modes: (1) the
# thesis has members but no event configured (name set-event); (2) it has an event
# whose member-interval coverage is too thin (a default-width band unearned).
_EVENT_BAND_COVERAGE_FLOOR = 0.30


def _applies_event_band_earned(ctx: HookContext) -> bool:
    return ctx.is_live and ctx.is_thesis_or_factor and not ctx.is_factor and ctx.thesis_member_count >= 1


def _check_event_band_earned(ctx: HookContext):
    floor = ctx.threshold("event_band_coverage_floor")
    floor = _EVENT_BAND_COVERAGE_FLOOR if floor is None else floor
    if not ctx.thesis_has_event:
        return False, (
            f"this thesis has {ctx.thesis_member_count} member(s) but NO joint-threshold event "
            "configured — its headline is a damped mean index, not the P(event) the question really "
            "asks. Configure it with `forecast thesis set-event <id> --kind count_threshold --threshold K` "
            "so it emits a scoreable probability with a band."
        ), {"mode": "thesis_event_missing", "member_count": ctx.thesis_member_count}
    cov = ctx.thesis_event_interval_coverage
    if cov is None or cov >= floor:
        return _OK
    return False, (
        f"this thesis event band is DEFAULT-WIDTH — unearned: only {cov:.0%} of the participating "
        f"members carry their own measured interval (below the {floor:.0%} floor), so the band is a "
        "flat epistemic default, not measured uncertainty. Backfill member intervals with `forecast "
        "thesis member-intervals <id> --apply` (panel spread), then re-aggregate."
    ), {"mode": "event_band_unearned", "coverage": cov}


def _rem_event_band(_ctx: HookContext) -> RemediationDescriptor:
    return RemediationDescriptor(
        "mechanical", "run_aggregate",
        "Configure the thesis event (set-event) or backfill member intervals (member-intervals --apply), then re-aggregate.",
    )


# THE HEALTH-NOT-PROBABILITY GATE. A mean-index HEALTH value must be labeled
# index-not-probability UNLESS an event band exists (then P is the headline). A
# thesis presenting health as a bare number reads as a probability it is not.
def _applies_health_not_probability(ctx: HookContext) -> bool:
    return ctx.is_live and ctx.is_thesis_or_factor and ctx.thesis_health_present


def _check_health_not_probability(ctx: HookContext):
    if ctx.thesis_has_event or ctx.thesis_health_index_labeled:
        return _OK
    return False, (
        "this thesis presents a mean-index HEALTH value with no event band and no index label — a "
        "severity index reads as a probability it is not. Either configure the event (set-event) so "
        "the headline becomes a real P(event), or ensure the surface labels health as an INDEX "
        "(re-aggregate stamps thesis_headline_kind='index')."
    ), {"health_present": True}


# THE CORRELATION-TRANSPARENCY GATE. A low n_eff / member ratio is a co-directional
# cluster (one bet dressed as many) — an honest dashboard label, NEVER a block.
_NEFF_RATIO_FLOOR = 0.5


def _applies_thesis_correlation_transparency(ctx: HookContext) -> bool:
    return ctx.is_live and ctx.is_thesis_or_factor and ctx.thesis_n_eff_ratio is not None and ctx.thesis_member_count >= 3


def _check_thesis_correlation_transparency(ctx: HookContext):
    floor = ctx.threshold("neff_ratio_floor")
    floor = _NEFF_RATIO_FLOOR if floor is None else floor
    ratio = ctx.thesis_n_eff_ratio
    if ratio is None or ratio >= floor:
        return _OK
    neff = ctx.thesis_n_eff
    neff_txt = f"{neff:.1f}" if isinstance(neff, (int, float)) else "?"
    return False, (
        f"CO-DIRECTIONAL CLUSTER: n_eff ~{neff_txt} over {ctx.thesis_member_count} members "
        f"(ratio {ratio:.0%}, below the {floor:.0%} floor) — the members co-move so strongly this is "
        "closer to one bet dressed as many. The band is correlation-honest already; this label keeps "
        "the member COUNT from reading as independent evidence."
    ), {"n_eff": neff, "member_count": ctx.thesis_member_count, "ratio": ratio}


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
    SimpleRule("evidence_depth", Category.SATURATION, Severity.WARN, 8.0,
               _check_evidence_depth, _modeled, _rem_collect),
    SimpleRule("require_outside_view_anchor", Category.REASONING, Severity.WARN, 9.0,
               _check_outside_view_anchor, _modeled, _rem_reference_class),
    # G3 — outside-view REFRESH tier: WARN when a routine (non-high-impact) re-forecast
    # of a question that has never carried a reference class commits. Visibility, not a
    # block (promoting it would re-create the has_prior brick).
    SimpleRule("outside_view_refresh", Category.REASONING, Severity.WARN, 6.0,
               _check_outside_view_refresh, _applies_outside_view_refresh, _rem_reference_class),
    SimpleRule("require_outcome_paths", Category.SATURATION, Severity.WARN, 10.0,
               _check_tail_paths, lambda c: c.is_live and (c.is_categorical or c.is_candidate_share), _rem_compress),
    # G1 — every named tail (categorical OR vote-share distribution) needs a cited base rate.
    SimpleRule("require_tail_base_rates", Category.REASONING, Severity.WARN, 14.0,
               _check_tail_base_rates, _applies_tail_base_rates, _rem_reference_class),
    # G2 — per-candidate intervals (when present) must be coherent (a structural bug-catcher).
    SimpleRule("candidate_intervals_coherent", Category.OUTPUT, Severity.ERROR, 12.0,
               _check_candidate_intervals_coherent, _applies_candidate_intervals_coherent, _rem_fix_distribution),
    # G2 (P2) — a high-impact vote-share forecast must carry per-candidate intervals
    # (auto-computed at commit; the WARN surfaces un-refilled live boards on lint).
    SimpleRule("candidate_intervals_present", Category.OUTPUT, Severity.WARN, 10.0,
               _check_candidate_intervals_present, _applies_candidate_intervals_present, _rem_sharpen),
    SimpleRule("style_clean", Category.STYLE, Severity.ERROR, 5.0,
               _check_style, _live, _rem_style),
    SimpleRule("lessons_applied", Category.CALIBRATION, Severity.WARN, 6.0,
               _check_lessons_applied, _live, _rem_lessons),
    SimpleRule("terminal_calibration_applied", Category.CALIBRATION, Severity.WARN, 6.0,
               _check_terminal_calibration_applied, _applies_terminal_calibration, _rem_recalibrate),
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
               _check_tails_justified, lambda c: c.is_live and (c.is_categorical or c.is_candidate_share), _rem_compress),
    SimpleRule("calibration_bias_applied", Category.CONFIDENCE, Severity.WARN, 6.0,
               _check_calibration_bias_applied, _live, _rem_sharpen),
    SimpleRule("confidence_committed", Category.CONFIDENCE, Severity.WARN, 6.0,
               _check_confidence_committed, _live, _rem_sharpen),
    # G4 — granularity discipline: WARN (never ERROR) on a binary round-number anchor
    # no pooled component produced. Makes false-roundness visible; never blocks.
    SimpleRule("granularity_disciplined", Category.CONFIDENCE, Severity.WARN, 4.0,
               _check_granularity_disciplined, _applies_granularity, _rem_sharpen),
    # v2 — reasoning composition
    SimpleRule("reasoning_composition", Category.REASONING, Severity.WARN, 8.0,
               _check_reasoning_composition, _modeled, _rem_tag_reasoning),
    # G7 — crux minimum: a high-impact commit must carry >=1 registered crux OR name
    # why none exists. WARN standard (WARN-first; ERROR after the crux backfill), ERROR strict.
    SimpleRule("crux_named", Category.REASONING, Severity.WARN, 8.0,
               _check_crux_named, _applies_crux_named, _rem_run_panel_crux),
    # G8 — market-anchor universality: a market-linked commit must record the market
    # price + deviation (engagement, never agreement). WARN standard, ERROR strict.
    SimpleRule("market_anchor_engaged", Category.QUORUM, Severity.WARN, 10.0,
               _check_market_anchor_engaged, _applies_market_anchor_engaged, _rem_run_quorum_market),
    # G5 — update-cadence escalation (SWEEP-SIDE): fires only on lint/finish_sweep for a
    # question past its cadence×grace with no recorded reason. WARN standard, ERROR strict.
    SimpleRule("update_cadence_honored", Category.DECISION, Severity.WARN, 8.0,
               _check_update_cadence_honored, _applies_update_cadence, _rem_collect),
    # v3 — thesis/factor aggregate freshness (members moved since last aggregate)
    SimpleRule("thesis_aggregate_fresh", Category.SATURATION, Severity.WARN, 8.0,
               _check_thesis_fresh, lambda c: c.is_live and c.is_thesis_or_factor, _rem_run_aggregate),
    # v3 — VOI-directed research adequacy (research_audit.py deterministic checks)
    SimpleRule("research_adequate", Category.SATURATION, Severity.WARN, 10.0,
               _check_research_adequate, _modeled, _rem_research),
    # v3 — machine-readiness enforcement (the Desk "RDY" score, previously un-hooked)
    SimpleRule("readiness_floor", Category.DECISION, Severity.WARN, 10.0,
               _check_readiness_floor, _live),
    SimpleRule("no_watched_sources", Category.DECISION, Severity.WARN, 8.0,
               _check_no_watched_sources, _live, _rem_collect),
    # BLF A1 — per-panelist belief trajectories on a post-harvest panel run. WARN
    # standard, ERROR strict, OFF exploratory; applies only to NEW (post-marker) runs.
    SimpleRule("belief_trajectory_present", Category.REASONING, Severity.WARN, 8.0,
               _check_belief_trajectory_present, _applies_belief_trajectory, _rem_belief_trajectory),
    # BLF A3 — variance-adaptive pool-shrinkage provenance recorded + valid. WARN
    # standard, ERROR strict; garbage α is the sharp fault, absence-on-non-calm the nag.
    SimpleRule("pool_shrinkage_recorded", Category.OUTPUT, Severity.WARN, 10.0,
               _check_pool_shrinkage_recorded, _applies_pool_shrinkage, _rem_pool_shrinkage),
    # BLF A5 — deterministic specialist seat considered on a continuous/count panel.
    # WARN FOREVER (a specialist on the wrong class is worse than none); never blocks.
    SimpleRule("specialist_seat_considered", Category.REASONING, Severity.WARN, 6.0,
               _check_specialist_seat_considered, _applies_specialist_seat, _rem_specialist_seat),
    # Thesis-remediation family — anchor re-link + event-band honesty.
    # anchor_refs_attached: RC exists on the question but not on the snapshot (mechanical).
    SimpleRule("anchor_refs_attached", Category.REASONING, Severity.WARN, 7.0,
               _check_anchor_refs_attached, _applies_anchor_refs_attached, _rem_relink_anchor),
    # event_band_earned: a thesis missing its event, or an unearned default-width band.
    SimpleRule("event_band_earned", Category.SATURATION, Severity.WARN, 9.0,
               _check_event_band_earned, _applies_event_band_earned, _rem_event_band),
    # health_not_probability: a thesis health index presented without a label / event band.
    SimpleRule("health_not_probability", Category.OUTPUT, Severity.WARN, 6.0,
               _check_health_not_probability, _applies_health_not_probability),
    # thesis_correlation_transparency: a low n_eff/member ratio — honest label, never blocks.
    SimpleRule("thesis_correlation_transparency", Category.CONFIDENCE, Severity.WARN, 4.0,
               _check_thesis_correlation_transparency, _applies_thesis_correlation_transparency),
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
    "evidence_depth": "A modeled live forecast should carry at least the default EV floor of evidence items.",
    "require_outside_view_anchor": "A serious live forecast (high-impact OR the FIRST commit of any question) must carry an outside-view anchor (reference class / base rate).",
    "outside_view_refresh": "A routine re-forecast of a question that has never carried a reference class WARNs (pure inside view since birth) — visibility, not a block.",
    "granularity_disciplined": "WARN when a binary commit sits on a round-number anchor (a 0.10 multiple / quarter-point) no pooled component produced (Tetlock's granularity finding); never blocks.",
    "crux_named": "A high-impact commit must carry >=1 registered crux (question_cruxes) OR record crux_skip_reason naming why no single crux exists.",
    "market_anchor_engaged": "A commit on a market-linked question must record the market price + deviation (via a quorum run or metadata.market_comparison) — engagement, never agreement.",
    "update_cadence_honored": "SWEEP-SIDE: a live forecast past its review cadence (x the grace multiple) with no recorded stale_evidence_reason fails on lint/finish_sweep (badge + alert, never a commit block).",
    "require_outcome_paths": "Every material categorical / vote-share outcome needs a named path (no unearned tails).",
    "require_tail_base_rates": "Every named, non-residual outcome above the anchor-share threshold (categorical OR vote-share) must carry a cited base rate — else the mass belongs in the residual bucket.",
    "candidate_intervals_coherent": "Per-candidate vote-share intervals, when present, must be coherent (finite p05<=median<=p95, median near the committed share, in bounds).",
    "candidate_intervals_present": "A high-impact vote-share forecast must carry per-candidate intervals (auto-computed from the ensemble spread; record no_interval_reason to opt out).",
    "style_clean": "Prose must be house-clean (no em-dashes / formatting issues).",
    "lessons_applied": "Active calibration lessons should be applied to the commit.",
    "terminal_calibration_applied": "A linked panel run must pass through the terminal Platt calibration stage.",
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
    "research_adequate": "Research must cover the levers that would move the forecast (reference class, evidence floor, independent + disconfirming + fresh evidence, watched triggers).",
    "readiness_floor": "A live forecast's machine-readiness (Desk RDY) score must clear the floor so the autonomous desk has the inputs to keep it alive.",
    "no_watched_sources": "A live forecast must have at least one active watched source the desk can refresh.",
    "belief_trajectory_present": "BLF A1: a post-harvest panel-backed commit must carry per-panelist belief trajectories (>=2 revision steps for a search-enabled seat; a single step needs a reason). Applies only to NEW panel runs — never retroactive.",
    "pool_shrinkage_recorded": "BLF A3: a post-harvest quorum-pooled commit must carry valid variance-adaptive pool-shrinkage provenance (α + inputs reconstructing the documented formula); a garbage α is the sharp fault, an absence on a non-calm market-linked panel the softer nag.",
    "specialist_seat_considered": "BLF A5: a post-harvest continuous/count panel where a deterministic specialist seat is offerable (climatology KNN / seasonal-naive) should seat one or record its decline. WARN forever — never blocks.",
    "anchor_refs_attached": "A question whose reference class EXISTS but is not linked on the current snapshot (the orphaned-anchor defect) — a MECHANICAL re-link fix, distinct from require_outside_view_anchor (which needs research). WARN standard, ERROR strict.",
    "event_band_earned": "A thesis with members but no configured joint event (name set-event), OR an event band whose member-interval coverage is below the earned floor (a default-width band masquerading as measured uncertainty). WARN.",
    "health_not_probability": "A thesis presenting a mean-index health value must label it index-not-probability unless an event band exists (the index-as-probability lie). WARN.",
    "thesis_correlation_transparency": "A thesis whose n_eff / member ratio is below the floor is a co-directional cluster (one bet dressed as many) — an honest dashboard label, never a block.",
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
