"""Signal helpers for forecast hooks.

Phase 1 provides the style detector + a builder that assembles a ``HookContext``
from values ``create_snapshot`` has already computed (the hot path). The
from-ledger builder used by ``forecast lint`` / the finish sweep / the dry-run
preview lands in Phase 5 (it reads the saturation signals off the ledger for an
existing snapshot).
"""

from __future__ import annotations

from typing import Any

from forecasting.hooks.spec import HookContext

# Prose fields a style rule inspects (mirrors sanitize_presentation_prose's set).
_PROSE_KEYS = ("rationale",)


def detect_style_offenders(fields: dict[str, str]) -> tuple[str, ...]:
    """Return the names of prose fields that are NOT already house-clean (contain
    em-dashes / formatting that ``sanitize_writeup_text`` would change). Exact:
    a field is offending iff sanitizing it changes it."""
    try:
        from forecasting.writeup import sanitize_writeup_text
    except Exception:
        return ()
    offenders: list[str] = []
    for name, text in fields.items():
        if not isinstance(text, str) or not text:
            continue
        if sanitize_writeup_text(text) != text:
            offenders.append(name)
    return tuple(offenders)


def style_clean_for_rationale(rationale: str, extra: dict[str, str] | None = None) -> tuple[bool, tuple[str, ...]]:
    fields: dict[str, str] = {"rationale": rationale or ""}
    if extra:
        fields.update(extra)
    offenders = detect_style_offenders(fields)
    return (not offenders), offenders


def quorum_signals_from_panel_run(run: Any) -> tuple[bool, int, int, bool]:
    """Derive the four quorum/panel-participation signals from a SINGLE panel-run
    dict (as returned by ``ledger.get_panel_run`` / ``list_panel_runs``), or the
    all-falsey defaults when there is no run. Shared by the lint path (latest run)
    and the commit path (the run linked via ``panel_run_ref``) so both compute the
    signals identically.

    Returns ``(is_quorum, panel_perspective_count, quorum_model_count, quorum_judged)``.

    Judge presence is VALUE-based: a quorum is "judged" when a judge synthesis value
    is stored (``panel_runs.judge``, persisted for runs from quorum_jobs). Value-based
    so a genuinely-unjudged quorum is honestly flagged, while a NULL judge on an old
    committed run stays honest too.
    """
    if not isinstance(run, dict):
        return False, 0, 0, False
    persp_count = len(run.get("perspectives") or [])
    is_quorum = (run.get("triggered_by") == "quorum")
    ests = run.get("estimates") or []
    quorum_models = len({(e.get("agent_model") or e.get("model")) for e in ests if (e.get("agent_model") or e.get("model"))})
    _meta = run.get("metadata")
    _judge_field = (_meta.get("judge") if isinstance(_meta, dict) else None) or run.get("judge_model") or run.get("judge")
    quorum_judged = bool(_judge_field)
    return is_quorum, persp_count, quorum_models, quorum_judged


def build_context_from_ledger(ledger, question_id: str, *, event: str = "lint", snapshot=None) -> HookContext:
    """Assemble a HookContext for an EXISTING current snapshot by reading the
    ledger's saturation signals (read-only). Used by ``forecast lint`` / the finish
    sweep / the dry-run preview. This ASSESSES saturation of a committed forecast,
    so commit-time-only signals (fresh-evidence re-run discipline) are treated as
    satisfied — a lint should not flag "you didn't collect fresh evidence", which is
    a property of the act of re-committing, not of the stored forecast."""
    question = ledger.get_question(question_id)
    snap = snapshot if snapshot is not None else ledger.get_current_snapshot(question_id)

    def _g(name, default=None):
        return getattr(snap, name, default) if snap is not None else default

    comp = _g("ensemble_components") or {}
    if isinstance(comp, dict):
        comp = comp.get("components", comp)
    comp_n = len(comp) if isinstance(comp, (list, dict)) else 0

    meta = _g("metadata") or {}
    td = meta.get("tail_audit") or {}
    rationale = _g("rationale") or ""
    style_ok, style_offenders = style_clean_for_rationale(rationale)

    try:
        evidence_count = len(ledger.list_evidence(question_id))
    except Exception:
        evidence_count = len(_g("evidence_refs") or [])
    try:
        reference_class_count = len(ledger.list_reference_classes(question_id))
    except Exception:
        reference_class_count = 0
    try:
        watched_source_count = len(ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status="active"))
    except Exception:
        watched_source_count = 0
    try:
        panel_run_count = len(ledger.list_panel_runs(question_id))
    except Exception:
        panel_run_count = 0
    try:
        from forecasting.models import question_decision_readiness_issues
        decision_gaps = tuple(question_decision_readiness_issues(question))
    except Exception:
        decision_gaps = ()

    panel_linked = panel_run_count > 0 or bool(meta.get("panel_skipped_reason"))

    # ── v2 signals: distribution structure, sharpness, reasoning, quorum, tails-null ──
    from forecasting.hooks.distribution import assess_distribution

    payload = _g("probability_or_distribution")
    ospace = question.outcome_space
    dist = assess_distribution(payload, outcome_type=ospace.type, bounds=getattr(ospace, "bounds", None), units=getattr(ospace, "units", None))
    null_model = (td.get("null_model") if isinstance(td, dict) else None) or {}
    sharp = None
    try:
        sharp = ledger._sharpness(payload)
    except Exception:
        sharp = None
    # reasoning requirement resolved from the question's profile
    try:
        from forecasting.hooks.engine import load_hook_config
        from forecasting.hooks.profiles import resolve_reasoning_requirement

        _hcfg = load_hook_config()
        _prof = ((getattr(question, "metadata", None) or {}).get("forecast_hooks") or {}).get("profile") or _hcfg.get("profile") or "standard"
        req_methods, min_methods = resolve_reasoning_requirement(_prof)
    except Exception:
        req_methods, min_methods = (), 0

    # per-question minimum-requirement threshold overrides
    try:
        from forecasting.hooks.thresholds import normalize_thresholds

        _qthr = normalize_thresholds(((getattr(question, "metadata", None) or {}).get("forecast_hooks") or {}).get("thresholds"))
    except Exception:
        _qthr = {}

    # measured chronic under-confidence for this scope (drives calibration_bias_applied)
    under_confident = False
    try:
        _bias = ledger.calibration_bias(domain=getattr(question, "domain", None))
        under_confident = (_bias.get("status") not in (None, "insufficient_evidence")) and _bias.get("direction") == "under"
    except Exception:
        under_confident = False

    # thesis/factor aggregate freshness: stale when a member's current snapshot is
    # newer than the aggregate's as_of (or the thesis has members but no aggregate).
    is_tf = False
    agg_stale = False
    newer_members = 0
    try:
        if ledger.is_thesis(question):
            is_tf = True
            _members_tf = ledger.list_thesis_members(question_id)
            if snap is None:
                agg_stale = bool(_members_tf)
            else:
                _agg_as_of = _g("as_of") or ""
                for _m in _members_tf:
                    _ms = ledger.get_current_snapshot(_m.get("member_question_id"))
                    if _ms is not None and (_ms.as_of or "") > _agg_as_of:
                        newer_members += 1
                agg_stale = newer_members > 0
    except Exception:
        is_tf, agg_stale, newer_members = is_tf, agg_stale, newer_members

    try:
        runs = ledger.list_panel_runs(question_id, limit=1)
        _latest_run = runs[0] if runs else None
    except Exception:
        _latest_run = None
    is_quorum, persp_count, quorum_models, quorum_judged = quorum_signals_from_panel_run(_latest_run)

    # research adequacy (VOI-directed research judge): the deterministic checks only,
    # over the CURRENT ledger state + this snapshot. Fail-open (defaults adequate).
    research_adequate = True
    research_adequacy_score = None
    try:
        from forecasting.research_audit import audit_research

        _ra = audit_research(ledger, question, snapshot=snap)
        research_adequate = bool(_ra.get("adequate"))
        research_adequacy_score = _ra.get("score")
    except Exception:
        research_adequate, research_adequacy_score = True, None

    # machine-readiness composite (the Desk "RDY" score) — drives readiness_floor.
    # Fail-open to None so a question whose composite cannot be computed never fires.
    try:
        from forecasting.readiness_lens import build_question_readiness

        readiness_score = build_question_readiness(ledger, question_id).get("score")
    except Exception:
        readiness_score = None

    return HookContext(
        question_id=question_id,
        forecast_origin=_g("forecast_origin", "live") or "live",
        event=event,
        impact=getattr(question, "impact", None),
        has_prior=bool(getattr(question, "current_forecast_id", None)),
        is_categorical=(question.outcome_space.type == "categorical"),
        has_reasons_up=bool(_g("reasons_up")),
        has_reasons_down=bool(_g("reasons_down")),
        has_change_my_mind=bool(_g("change_my_mind")),
        has_components=comp_n > 0,
        component_count=comp_n,
        has_citations=bool(_g("evidence_refs")),
        panel_linked=panel_linked,
        panel_skipped=bool(meta.get("panel_skipped_reason")),
        panel_run_count=panel_run_count,
        evidence_count=evidence_count,
        # acknowledged stale evidence WITHOUT a recorded reason -> WARN on re-read too
        stale_evidence_acknowledged=bool(meta.get("acknowledge_stale_evidence")) and not bool(meta.get("stale_evidence_reason")),
        has_fresh_evidence=True,  # not a commit; re-run freshness is not assessed here
        reference_class_count=reference_class_count,
        # lint/re-read path: default the snapshot-link count to the question-level count so
        # re-reading old snapshots never spuriously fires the snapshot-honest anchor warn
        linked_reference_class_count=reference_class_count,
        watched_source_count=watched_source_count,
        readiness_score=readiness_score,
        decision_gaps=decision_gaps,
        tail_audit_passes=(td.get("passes") if td else None),
        tail_unearned_mass=float(td.get("unearned_mass") or 0.0),
        tail_offenders=tuple(v.get("name") for v in (td.get("verdicts") or []) if v.get("unearned")),
        style_clean=style_ok,
        style_offending_fields=style_offenders,
        is_distribution=bool(dist and dist.is_distribution),
        distribution_renderable=(dist.renderable if dist else True),
        bounds_well_formed=(dist.well_formed if dist else True),
        bounds_in_range=(dist.in_range if dist else True),
        interval_width_ratio=(dist.width_ratio if dist else None),
        has_units=(dist.has_units if dist else True),
        distribution_issues=tuple(dist.issues) if dist else (),
        sharpness=sharp,
        categorical_top_mass=(max((v.get("probability") or 0.0) for v in (td.get("verdicts") or [])) if (td and td.get("verdicts")) else None),
        uncertainty_justified=bool(meta.get("uncertainty_justified")),
        tail_null_excess=float(null_model.get("excess_tail") or 0.0),
        is_quorum=is_quorum,
        panel_perspective_count=persp_count,
        quorum_model_count=quorum_models,
        quorum_judged=quorum_judged,
        calibration_under_confident=under_confident,
        is_thesis_or_factor=is_tf,
        aggregate_stale=agg_stale,
        newer_member_count=newer_members,
        reasoning_methods=tuple(meta.get("reasoning_methods") or ()),
        required_reasoning_methods=tuple(req_methods),
        min_reasoning_methods=min_methods,
        domain=getattr(question, "domain", None),
        outcome_type=question.outcome_space.type,
        research_adequate=research_adequate,
        research_adequacy_score=research_adequacy_score,
        thresholds=_qthr,
    )


def build_commit_context(
    *,
    question_id: str,
    forecast_origin: str,
    event: str,
    impact: str | None,
    has_prior: bool,
    is_categorical: bool,
    reasons_up: list[str] | None,
    reasons_down: list[str] | None,
    change_my_mind: list[str] | None,
    has_components: bool,
    component_count: int,
    citation_refs: list[str],
    panel_run_ref: str | None,
    panel_skipped_reason: str | None,
    has_fresh_evidence: bool,
    acknowledge_stale_evidence: bool,
    stale_evidence_reason: str | None = None,
    evidence_count: int,
    prior_forecast_id: str | None,
    prior_as_of: str | None,
    decision_gaps: list[str],
    tail_audit_passes: bool | None,
    tail_unearned_mass: float,
    tail_offenders: list[str],
    rationale: str,
    domain: str | None = None,
    outcome_type: str | None = None,
    active_lessons_unapplied: int = 0,
    # v2 (optional; observe-mode populates what create_snapshot has computed)
    reasoning_methods: list[str] | None = None,
    required_reasoning_methods: tuple[str, ...] = (),
    min_reasoning_methods: int = 0,
    is_distribution: bool = False,
    distribution_renderable: bool = True,
    bounds_well_formed: bool = True,
    bounds_in_range: bool = True,
    interval_width_ratio: float | None = None,
    sharpness: float | None = None,
    panel_run_count: int = 0,
    # quorum / panel participation (v2): derived from the linked panel_run_ref via
    # quorum_signals_from_panel_run so the quorum rules evaluate truthfully at commit.
    is_quorum: bool = False,
    panel_perspective_count: int = 0,
    quorum_model_count: int = 0,
    quorum_judged: bool = False,
    calibration_under_confident: bool = False,
    watched_source_count: int = 0,
    readiness_score: float | None = None,
    reference_class_count: int = 0,
    linked_reference_class_count: int = 0,
    is_thesis_or_factor: bool = False,
    committed_winner_prob: float | None = None,
    derived_child_present: bool = False,
    machine_scoreable: bool = True,
    terminal_calibration_present: bool = True,
    research_adequate: bool = True,
    research_adequacy_score: float | None = None,
    thresholds: dict[str, float] | None = None,
) -> HookContext:
    """Assemble a HookContext from the values create_snapshot already has in
    scope. Cheap: no ledger IO (the caller passes precomputed signals)."""
    style_clean, style_offenders = style_clean_for_rationale(rationale)
    return HookContext(
        question_id=question_id,
        forecast_origin=forecast_origin,
        event=event,
        impact=impact,
        has_prior=has_prior,
        is_categorical=is_categorical,
        has_reasons_up=bool(reasons_up),
        has_reasons_down=bool(reasons_down),
        has_change_my_mind=bool(change_my_mind),
        has_components=has_components,
        component_count=component_count,
        has_citations=bool(citation_refs),
        panel_linked=bool(panel_run_ref),
        panel_skipped=bool((panel_skipped_reason or "").strip()),
        evidence_count=evidence_count,
        has_fresh_evidence=has_fresh_evidence,
        acknowledge_stale_evidence=acknowledge_stale_evidence,
        # acknowledged stale evidence but left no reason -> the WARN rule fires
        stale_evidence_acknowledged=acknowledge_stale_evidence and not (stale_evidence_reason or "").strip(),
        prior_forecast_id=prior_forecast_id,
        prior_as_of=prior_as_of,
        decision_gaps=tuple(decision_gaps or ()),
        tail_audit_passes=tail_audit_passes,
        tail_unearned_mass=tail_unearned_mass,
        tail_offenders=tuple(tail_offenders or ()),
        style_clean=style_clean,
        style_offending_fields=style_offenders,
        domain=domain,
        outcome_type=outcome_type,
        active_lessons_unapplied=active_lessons_unapplied,
        reasoning_methods=tuple(reasoning_methods or ()),
        required_reasoning_methods=required_reasoning_methods,
        min_reasoning_methods=min_reasoning_methods,
        is_distribution=is_distribution,
        distribution_renderable=distribution_renderable,
        bounds_well_formed=bounds_well_formed,
        bounds_in_range=bounds_in_range,
        interval_width_ratio=interval_width_ratio,
        sharpness=sharpness,
        panel_run_count=panel_run_count,
        is_quorum=is_quorum,
        panel_perspective_count=panel_perspective_count,
        quorum_model_count=quorum_model_count,
        quorum_judged=quorum_judged,
        calibration_under_confident=calibration_under_confident,
        watched_source_count=watched_source_count,
        readiness_score=readiness_score,
        reference_class_count=reference_class_count,
        linked_reference_class_count=linked_reference_class_count,
        is_thesis_or_factor=is_thesis_or_factor,
        committed_winner_prob=committed_winner_prob,
        derived_child_present=derived_child_present,
        machine_scoreable=machine_scoreable,
        terminal_calibration_present=terminal_calibration_present,
        research_adequate=research_adequate,
        research_adequacy_score=research_adequacy_score,
        thresholds=dict(thresholds or {}),
    )
