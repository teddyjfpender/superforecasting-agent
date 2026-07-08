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

    # G1/G2 (P1): candidate-share tail base-rate + interval coherence. On the READ
    # path the per-outcome base_rate anchors are not persisted (they are commit
    # params), so a named tail is treated as unanchored here — which is exactly the
    # honest migration count (the live boards stored no anchors). Intervals are read
    # from the stored candidate_share_intervals_pp metadata.
    _is_candidate_share = False
    _share_unanchored: tuple[str, ...] = ()
    _share_unanchored_mass = 0.0
    _ci_present = False
    _ci_coherent = True
    _ci_coverage: float | None = None
    _ci_issues: tuple[str, ...] = ()
    try:
        from forecasting.hooks.distribution import assess_candidate_intervals, candidate_shares
        from forecasting.tail_audit import (
            DEFAULT_NAMED_ANCHOR_SHARE,
            audit_named_anchors,
            outcome_paths_from_inputs,
        )

        _shares_ledger = candidate_shares(payload) if isinstance(payload, dict) else None
        _is_cat = ospace.type == "categorical"
        # Vote-share DISTRIBUTION signal (categoricals reach G1 via is_categorical; G2
        # is vote-share only). A categorical PMF also parses as shares — gate it off.
        _is_candidate_share = _shares_ledger is not None and not _is_cat
        if (_shares_ledger is not None or _is_cat) and isinstance(payload, dict):
            _anchor_dist = _shares_ledger if _shares_ledger is not None else {str(k): float(v) for k, v in payload.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
            _anchor_thr = _qthr.get("named_outcome_anchor_share", DEFAULT_NAMED_ANCHOR_SHARE)
            _share_unanchored, _share_unanchored_mass = audit_named_anchors(
                outcome_paths_from_inputs(_anchor_dist, None), threshold=_anchor_thr
            )
        if _shares_ledger is not None:
            _iv_raw = meta.get("candidate_share_intervals_pp")
            _ci_present = isinstance(_iv_raw, dict) and bool(_iv_raw)
            from forecasting.hooks.thresholds import DEFAULT_INTERVAL_MEDIAN_TOLERANCE_PP

            _ci_coherent, _ci_coverage, _ci_issues_list = assess_candidate_intervals(
                payload, _iv_raw, bounds=getattr(ospace, "bounds", None),
                tolerance_pp=_qthr.get("interval_median_tolerance_pp", DEFAULT_INTERVAL_MEDIAN_TOLERANCE_PP),
            )
            _ci_issues = tuple(_ci_issues_list)
    except Exception:
        _is_candidate_share = _is_candidate_share

    # G4 · granularity (round-number anchor). Reads the committed payload + the pooled
    # components + the uncertainty_justified escape — the same arithmetic the commit
    # path uses, so lint and commit agree. Best-effort (defaults to the passing state).
    _round_anchored = False
    try:
        from forecasting.hooks.distribution import is_round_number_anchored

        _round_anchored = is_round_number_anchored(
            payload, comp, uncertainty_justified=bool(meta.get("uncertainty_justified"))
        )
    except Exception:
        _round_anchored = False

    # G5 · cadence overdue ratio (SWEEP-SIDE only). age(current.as_of) / cadence period;
    # populated only on lint/finish_sweep so the commit path never fires it. A live
    # forecast with no explicit review_cadence still owes a weekly review (the desk's
    # scheduled-review default), so the effective cadence falls back to weekly — matching
    # the plan's cadence_days(question.review_cadence, default 7).
    _review_cadence = getattr(question, "review_cadence", None) or "weekly"
    _cadence_ratio = 0.0
    _cadence_reason = bool(meta.get("stale_evidence_reason"))
    if event in ("lint", "finish_sweep") and snap is not None:
        try:
            from datetime import datetime, timezone

            from forecasting.models import timestamp_to_datetime

            _as_of_dt = timestamp_to_datetime(_g("as_of"))
            if _as_of_dt is not None:
                _cadence_days = ledger._cadence_delta(_review_cadence).total_seconds() / 86400.0
                if _cadence_days > 0:
                    _age_days = (datetime.now(timezone.utc) - _as_of_dt).total_seconds() / 86400.0
                    _cadence_ratio = max(0.0, _age_days / _cadence_days)
        except Exception:
            _cadence_ratio = 0.0

    # G7 · crux count (one indexed COUNT on question_cruxes).
    try:
        _crux_count = len(ledger.list_cruxes(question_id))
    except Exception:
        _crux_count = 0

    # G8 · market link + comparison. has_linked_market from a market-prefixed component,
    # an active watched market source, or a market baseline comparison;
    # market_comparison_recorded from the latest panel run's market_anchor annotation or
    # the committer's metadata.market_comparison.
    _has_market = False
    _market_source = None
    _market_recorded = True
    try:
        from forecasting.hooks.market_anchor import (
            detect_linked_market,
            market_comparison_from_metadata,
            panel_run_records_market,
        )

        try:
            _watch_slugs = [
                s
                for w in ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status="active")
                for s in (w.get("source"), w.get("source_type"))
            ]
        except Exception:
            _watch_slugs = []
        try:
            _baseline_types = [b.get("baseline_type") for b in ledger.list_baseline_comparisons(question_id)]
        except Exception:
            _baseline_types = []
        _has_market, _market_source = detect_linked_market(
            components=comp, watched_source_slugs=_watch_slugs, baseline_types=_baseline_types
        )
        if _has_market:
            _market_recorded = (
                panel_run_records_market(_latest_run)
                or market_comparison_from_metadata(meta) is not None
            )
    except Exception:
        _has_market, _market_recorded = False, True

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
        is_candidate_share=_is_candidate_share,
        share_named_unanchored=_share_unanchored,
        share_named_unanchored_mass=_share_unanchored_mass,
        candidate_intervals_present=_ci_present,
        candidate_intervals_coherent=_ci_coherent,
        candidate_interval_coverage=_ci_coverage,
        candidate_interval_issues=_ci_issues,
        no_interval_reason=(meta.get("no_interval_reason") or None),
        candidate_interval_source=((meta.get("candidate_share_intervals_provenance") or {}).get("source") if isinstance(meta.get("candidate_share_intervals_provenance"), dict) else None),
        # P3 gates
        committed_winner_prob=_committed_winner_prob_readpath(ledger, payload, ospace.type),
        round_number_anchored=_round_anchored,
        cadence_overdue_ratio=_cadence_ratio,
        cadence_reason_recorded=_cadence_reason,
        review_cadence=_review_cadence,
        crux_count=_crux_count,
        crux_skip_reason=(meta.get("crux_skip_reason") or None),
        has_linked_market=_has_market,
        market_comparison_recorded=_market_recorded,
        market_skip_reason=(meta.get("market_skip_reason") or None),
        linked_market_source=_market_source,
        thresholds=_qthr,
    )


def _committed_winner_prob_readpath(ledger, payload, outcome_type) -> float | None:
    """The committed winner probability for the G4 message on the read path
    (fail-soft; None on any error so the granularity message degrades gracefully)."""
    try:
        return ledger._committed_winner_prob(payload, outcome_type)
    except Exception:
        return None


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
    # G1/G2 (P1): candidate-share tail base-rate + interval coherence signals.
    is_candidate_share: bool = False,
    share_named_unanchored: tuple[str, ...] = (),
    share_named_unanchored_mass: float = 0.0,
    candidate_intervals_present: bool = False,
    candidate_intervals_coherent: bool = True,
    candidate_interval_coverage: float | None = None,
    candidate_interval_issues: tuple[str, ...] = (),
    no_interval_reason: str | None = None,
    candidate_interval_source: str | None = None,
    # P3 gates (G3 rides has_prior/reference_class_count; these carry G4/G5/G7/G8)
    round_number_anchored: bool = False,
    cadence_overdue_ratio: float = 0.0,
    cadence_reason_recorded: bool = False,
    review_cadence: str | None = None,
    crux_count: int = 0,
    crux_skip_reason: str | None = None,
    has_linked_market: bool = False,
    market_comparison_recorded: bool = True,
    market_skip_reason: str | None = None,
    linked_market_source: str | None = None,
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
        is_candidate_share=is_candidate_share,
        share_named_unanchored=tuple(share_named_unanchored or ()),
        share_named_unanchored_mass=share_named_unanchored_mass,
        candidate_intervals_present=candidate_intervals_present,
        candidate_intervals_coherent=candidate_intervals_coherent,
        candidate_interval_coverage=candidate_interval_coverage,
        candidate_interval_issues=tuple(candidate_interval_issues or ()),
        no_interval_reason=(no_interval_reason or None),
        candidate_interval_source=(candidate_interval_source or None),
        round_number_anchored=round_number_anchored,
        cadence_overdue_ratio=cadence_overdue_ratio,
        cadence_reason_recorded=cadence_reason_recorded,
        review_cadence=review_cadence,
        crux_count=crux_count,
        crux_skip_reason=(crux_skip_reason or None),
        has_linked_market=has_linked_market,
        market_comparison_recorded=market_comparison_recorded,
        market_skip_reason=(market_skip_reason or None),
        linked_market_source=(linked_market_source or None),
        thresholds=dict(thresholds or {}),
    )
