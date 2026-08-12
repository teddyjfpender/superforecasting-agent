"""The forecast-production path (full_forecast, update_forecast).

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

from forecasting.ensembles import weighted_binary_probability
from forecasting.learning import apply_active_lesson_adjustments, should_apply_active_lessons
from tools.registry import tool_error, tool_result
from typing import Any
from tools.forecasting_tool import _DUPLICATE_WARN_SCORE, _apply_source_plan_watches, _find_possible_duplicates, _required
from tools import forecasting_tool as _ft

def full_forecast(args: dict[str, Any], ledger) -> str:
    from forecasting.cli import run_forecast_chain
    from forecasting.question_spec import (
        apply_recommended_defaults,
        spec_from_dict,
        spec_quality,
    )

    raw = dict(args.get("spec") or {})
    if not raw.get("title") and args.get("prompt"):
        raw["title"] = str(args.get("prompt"))
    spec = spec_from_dict(raw)
    # A full_forecast is by definition the accept-defaults fast path.
    spec, applied_defaults = apply_recommended_defaults(spec)

    errs = [issue.to_dict() for issue in spec.errors()]
    if errs:
        return tool_error(
            "question spec is not committable: "
            + "; ".join(f"{e['field']}: {e['message']}" for e in errs),
            success=False,
            issues=errs,
            spec_quality=spec_quality(spec),
            applied_defaults=applied_defaults,
        )

    # Duplicate routing on the laziest path: calling full_forecast twice with
    # the same sentence must REFRESH the existing question, not fork a rival.
    # When a strong near-duplicate exists (score >= the warn threshold) and the
    # caller did not pass allow_duplicate=true, run the SAME gated stage chain
    # onto the EXISTING question id instead of committing a new one.
    allow_duplicate = bool(args.get("allow_duplicate"))
    duplicates = _find_possible_duplicates(ledger, spec.title)
    top = duplicates[0] if duplicates else None
    strong_dup = top is not None and top["score"] >= _DUPLICATE_WARN_SCORE
    routed_to_existing = False
    duplicate_of: dict[str, Any] | None = None
    duplicate_note: str | None = None
    duplicate_warning: str | None = None
    watched_sources_attached: list[dict[str, Any]] = []
    commit_result: dict[str, Any] | None = None
    if strong_dup and not allow_duplicate:
        question_id = top["id"]
        routed_to_existing = True
        duplicate_of = top
        duplicate_note = (
            f"you already track {top['id']} (\"{top['title']}\") — refreshed that "
            "instead of forking a rival (pass allow_duplicate=true to force a new question)"
        )
    else:
        commit_result = spec.commit(ledger)
        question_id = commit_result["question_id"]
        if strong_dup:
            # allow_duplicate forced a new, rival question — surface the warning anyway.
            duplicate_warning = (
                f"you already track {top['id']} (\"{top['title']}\") — "
                "committed a rival question anyway (allow_duplicate=true)"
            )
        # Feed the spine: an auto-path question usually commits with ZERO
        # watched sources, so the deterministic scheduled refresh has nothing
        # to refresh. Auto-attach the top recommended watches (reusing the
        # source-plan apply seam) so the question refreshes itself. Fail-open:
        # a planner hiccup must never block the forecast.
        if not spec.watched_sources and spec.allow_evidence_gathering:
            try:
                question = ledger.get_question(question_id)
                recs = _ft.plan_sources_for_question(question)
                candidates = [r for r in recs if not r.requires_user_source and r.watch_source][:3]
                watched_sources_attached, _ = _apply_source_plan_watches(ledger, question_id, candidates)
            except Exception:
                watched_sources_attached = []

    chain = run_forecast_chain(
        ledger,
        question_id,
        model=args.get("model"),
        provider=args.get("provider"),
        max_iterations=int(args["max_iterations"]) if args.get("max_iterations") is not None else 12,
    )
    payload: dict[str, Any] = dict(
        success=True,
        question_id=question_id,
        created=commit_result,
        routed_to_existing=routed_to_existing,
        applied_defaults=applied_defaults,
        spec_quality=spec_quality(spec),
        watched_sources_attached=watched_sources_attached,
        stages=chain["stages"],
        committed=chain["committed"],
        snapshot=chain["snapshot"],
        update_ready=chain["update_ready"],
        update_blockers=chain["update_blockers"],
    )
    if duplicates:
        payload["possible_duplicates"] = duplicates
    if duplicate_of is not None:
        payload["duplicate_of"] = duplicate_of
        payload["duplicate_note"] = duplicate_note
    if duplicate_warning is not None:
        payload["duplicate_warning"] = duplicate_warning
    return tool_result(**payload)

def update_forecast(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    # PREVIEW FIRST: when set, run the full gate/saturation pass WITHOUT writing
    # a snapshot (no brief, no quorum, no annotate) and return the verdict so
    # the agent fixes advisories/blockers and commits ONCE — never
    # commit-then-remediate.
    proposal_only = bool(args.get("proposal_only", False))
    preview_flag = bool(args.get("preview", False) or proposal_only)
    components = args.get("components") or {}
    # Accept the schema-advertised aliases so an agent can pass
    # probability_or_distribution / proposed_probability_or_distribution
    # interchangeably with probability (these were documented but only
    # `probability` was honoured — the agent had to guess by trial and
    # error which one the tool actually wanted).
    probability = next(
        (
            args[name]
            for name in (
                "probability",
                "probability_or_distribution",
                "proposed_probability",
                "proposed_probability_or_distribution",
            )
            if args.get(name) is not None
        ),
        None,
    )
    if probability is None and components:
        probability = weighted_binary_probability(components)
    if probability is None:
        return tool_error(
            "update_forecast requires a probability (use 'probability', "
            "'probability_or_distribution', 'proposed_probability', "
            "'proposed_probability_or_distribution', or 'components')",
            success=False,
        )
    calibration_lesson_refs = args.get("calibration_lesson_refs") or []
    calibration_adjustment = args.get("calibration_adjustment") or {}
    # Measured-bias adjustments apply BY DEFAULT for LIVE commits (S7): the
    # ledger's learned calibration correction lands on every live forecast
    # unless the caller passes use_active_lessons=false. raw_probability is
    # recorded before adjustment inside apply_active_lesson_adjustments, so net
    # movement stays auditable. backtest/imported_baseline are NEVER auto-
    # adjusted (the correction is live-derived; auto-applying it would
    # contaminate the closed-book grounding benchmark) — they opt in
    # explicitly. Exploratory scratchpad commits are never adjusted.
    _lessons_origin = args.get("forecast_origin") or "live"
    if should_apply_active_lessons(args.get("use_active_lessons"), _lessons_origin):
        probability, calibration_lesson_refs, calibration_adjustment = apply_active_lesson_adjustments(
            ledger=ledger,
            question=ledger.get_question(question_id),
            payload=probability,
            calibration_lesson_refs=calibration_lesson_refs,
            calibration_adjustment=calibration_adjustment,
        )
    # Resolve the enforcement severity of each rule from config (profile +
    # impact/origin scaling + overrides + per-question), so the gates are
    # config-driven, not hardcoded. An explicit require_* arg still wins
    # (tests / one-off overrides). The `standard` default profile equals
    # the prior hardcoded defaults, so behaviour is unchanged out of the box.
    from forecasting.hooks import Severity as _HookSeverity
    from forecasting.hooks import resolve_severities as _resolve_sev

    _hook_origin = args.get("forecast_origin") or "live"
    _hook_sev = _resolve_sev(ledger.get_question(question_id), forecast_origin=_hook_origin)

    def _require(arg_name: str, rule_id: str) -> bool:
        if arg_name in args:
            return bool(args[arg_name])
        return _hook_sev.get(rule_id) == _HookSeverity.ERROR

    # Inline reference-class attach: declare a reference class in the SAME call as
    # the forecast (create + link it to this snapshot), so the outside-view anchor
    # is satisfied without a separate add_reference_class round-trip. Existing ids
    # can still be linked via reference_class_refs.
    _rc_refs = list(args.get("reference_class_refs") or [])
    _inline_rc = args.get("reference_class")
    if isinstance(_inline_rc, dict) and (_inline_rc.get("name") or "").strip():
        _rc_name = _inline_rc["name"].strip()
        # Validate BEFORE creating so an incomplete inline class returns a precise
        # field error instead of aborting the whole forecast with a vague one.
        if not (_inline_rc.get("inclusion_criteria") or "").strip():
            return tool_error(
                "inline reference_class needs both name and inclusion_criteria — "
                "complete it, or omit reference_class and call add_reference_class separately.",
                success=False,
            )
        # Reuse an existing ACTIVE same-name reference class on this question rather
        # than creating a duplicate. If a prior commit was refused by another gate
        # (saturation/stale/etc.) the inline class it created is unlinked; reusing it
        # here links that same anchor on retry instead of piling up orphans.
        _existing = next(
            (rc for rc in ledger.list_reference_classes(question_id)
             if (rc.get("name") or "").strip() == _rc_name and (rc.get("status") or "active") == "active"),
            None,
        )
        if _existing is not None:
            _rc_refs.append(_existing["id"])
        else:
            # Create + link the inline anchor. This runs for a preview too: the G3
            # first-commit anchor tier makes the outside view mandatory, so a preview
            # must actually provision it to PREDICT the real commit's outcome (writing
            # a reference-class row, never a snapshot — the preview's no-snapshot
            # contract is intact). The reuse-by-name branch above means a subsequent
            # real commit links this SAME anchor instead of piling up a duplicate.
            _created_rc = ledger.add_reference_class(
                question_id=question_id,
                name=_rc_name,
                inclusion_criteria=_inline_rc["inclusion_criteria"],
                exclusion_criteria=_inline_rc.get("exclusion_criteria") or "",
                base_rate=_inline_rc.get("base_rate"),
                base_rate_uncertainty=_inline_rc.get("uncertainty"),
                source_refs=_inline_rc.get("source_refs") or [],
                sample_size=_inline_rc.get("sample_size"),
            )
            _rc_refs.append(_created_rc["id"])

    # Read BEFORE the commit: whether a prior snapshot existed feeds the
    # auto-quorum indication below (should_run_panel treats a first
    # forecast differently from a re-forecast).
    _prior_snapshot = ledger.get_current_snapshot(question_id)
    _had_prior_snapshot = _prior_snapshot is not None

    snapshot_args = dict(
        question_id=question_id,
        probability_or_distribution=probability,
        rationale=_required(args, "rationale"),
        as_of=args.get("as_of"),
        confidence=args.get("confidence"),
        method=args.get("method"),
        ensemble_components=components,
        key_assumptions=args.get("key_assumptions") or [],
        assumption_refs=args.get("assumption_refs") or [],
        reference_class_refs=_rc_refs,
        evidence_refs=args.get("evidence_refs") or [],
        model_run_refs=args.get("model_run_refs") or [],
        forecast_origin=args.get("forecast_origin") or "live",
        agent_model=args.get("agent_model"),
        prompt_version=args.get("prompt_version"),
        forecasting_protocol_version=args.get("forecasting_protocol_version") or args.get("protocol_version"),
        toolset_version=args.get("toolset_version"),
        source_snapshot_refs=args.get("source_snapshot_refs") or [],
        evidence_cutoff=args.get("evidence_cutoff"),
        backtest_run_id=args.get("backtest_run_id"),
        calibration_eligible=bool(args.get("calibration_eligible", True)),
        calibration_weight=args.get("calibration_weight") if args.get("calibration_weight") is not None else 1.0,
        stale_evidence_days=args.get("stale_evidence_days", 30),
        acknowledge_stale_evidence=bool(args.get("ack_stale_evidence", False)),
        stale_evidence_reason=args.get("stale_evidence_reason"),
        require_citations=_require("require_citations", "require_citations"),
        calibration_lesson_refs=calibration_lesson_refs,
        calibration_adjustment=calibration_adjustment,
        # Stamp which related forecasts informed this one, server-side from
        # the resolver — never trusting the model to echo its own provenance.
        metadata={
            **(args.get("metadata") or {}),
            **({"cross_refs": _xr} if (_xr := ledger.build_cross_refs(question_id)) else {}),
        },
        reasons_up=args.get("reasons_up"),
        reasons_down=args.get("reasons_down"),
        change_my_mind=args.get("change_my_mind"),
        require_structured_reasoning=_require("require_structured_reasoning", "require_structured_reasoning"),
        require_components=_require("require_components", "require_components"),
        require_fresh_evidence=_require("require_fresh_evidence", "require_fresh_evidence"),
        require_decision_readiness=_require("require_decision_readiness", "require_decision_readiness"),
        require_panel=_require("require_panel", "require_panel"),
        panel_run_ref=args.get("panel_run_ref"),
        panel_skipped_reason=args.get("panel_skipped_reason"),
        outcome_paths=args.get("outcome_paths"),
        require_outcome_paths=_require("require_outcome_paths", "require_outcome_paths"),
        require_style=_require("require_style", "style_clean"),
        reasoning_methods=args.get("reasoning_methods"),
        require_output_structure=(
            bool(args["require_output_structure"]) if "require_output_structure" in args
            else (_hook_sev.get("output_renderable") == _HookSeverity.ERROR
                  or _hook_sev.get("uncertainty_well_formed") == _HookSeverity.ERROR)
        ),
        # Agent commit: opt into the ledger's RESOLVED-POLICY blocking pass so the
        # built-in rules that carry no inline require_* gate (require_evidence and,
        # under a strict / impact-scaled profile, the outside-view / quorum /
        # reasoning-composition rules) enforce their resolved severity for THIS
        # commit — the evidence floor + profile promotions become real for the
        # agent path, while direct/programmatic callers stay observe-only.
        enforce_resolved_hooks=True,
    )
    snapshot = ledger.create_snapshot(**snapshot_args, preview=preview_flag)
    if preview_flag:
        # snapshot is a preview record (dict), NOT a committed snapshot. Nothing
        # was written: skip the brief, the auto-quorum, and annotate_snapshot —
        # all post-commit machinery. Surface the saturation summary the same way
        # the real path does so the agent reads "would commit at 78/100, 2
        # advisories" (or the blockers) and commits ONCE after fixing them.
        _pv = snapshot if isinstance(snapshot, dict) else {}
        _pv_sat = _ft.saturation_summary(_pv.get("saturation")) if _pv.get("would_commit") else None
        if proposal_only and _pv.get("would_commit"):
            from forecasting.warnings import is_material_move

            proposed_probability = _pv.get("probability_or_distribution", probability)
            prior_probability = (
                _prior_snapshot.probability_or_distribution
                if _prior_snapshot is not None
                else None
            )
            if is_material_move(prior_probability, proposed_probability):
                proposal_snapshot_args = dict(snapshot_args)
                proposal_snapshot_args["probability_or_distribution"] = proposed_probability
                proposal = ledger.create_forecast_update_proposal(
                    question_id=question_id,
                    run_id=None,
                    prior_forecast_id=(
                        _prior_snapshot.forecast_id if _prior_snapshot is not None else None
                    ),
                    proposed_probability_or_distribution=proposed_probability,
                    rationale=_required(args, "rationale"),
                    evidence_refs=args.get("evidence_refs") or [],
                    source_snapshot_refs=args.get("source_snapshot_refs") or [],
                    model_run_refs=args.get("model_run_refs") or [],
                    assumption_refs=args.get("assumption_refs") or [],
                    reference_class_refs=_rc_refs,
                    snapshot_args=proposal_snapshot_args,
                )
                ledger.create_alert(
                    severity="info",
                    scope_type="question",
                    scope_ref=question_id,
                    reason=f"autopilot_update_proposed:{proposal['id']}",
                    recommended_action=(
                        f"Review with `forecast autopilot approve {proposal['id']}` or reject it."
                    ),
                )
                return tool_result(
                    success=True,
                    status="proposal_created",
                    proposal=proposal,
                    preview=_pv,
                    committed=None,
                    **({"saturation": _pv_sat} if _pv_sat is not None else {}),
                )
            return tool_result(
                success=True,
                status="marginal",
                proposal=None,
                preview=_pv,
                committed=None,
                **({"saturation": _pv_sat} if _pv_sat is not None else {}),
            )
        return tool_result(
            success=True,
            preview=_pv,
            **({"saturation": _pv_sat} if _pv_sat is not None else {}),
        )
    try:
        from forecasting.writeup import write_brief

        write_brief(
            ledger,
            question_id,
            snapshot,
            main_runtime=args.get("_main_runtime"),
        )
    except Exception:
        pass
    # Saturation visibility (Wave 3 H4): surface the observe-mode score +
    # WARN advisories ALREADY recorded on this snapshot (no recompute) so the
    # agent SEES "committed at 72/100, 3 advisories" and can self-improve on
    # the next call without the user re-prompting. Read straight from the
    # just-committed snapshot's metadata; absent when no report was recorded.
    _sat = _ft.saturation_summary((getattr(snapshot, "metadata", None) or {}).get("saturation"))
    _extra = {"saturation": _sat} if _sat is not None else {}
    # Auto-quorum on the AGENT path (the lazy path): the same shared seam the
    # CLI `forecast update` verb uses — a high-impact live commit with no
    # panel attached detached-starts a multi-model quorum that attaches its
    # panel run to this snapshot. Without this, full_forecast, the chained
    # pipeline, and `cycle run --agent` (which all commit through THIS
    # handler) would never get the fusion the goal promises. Fail-open by
    # construction (the helper never raises); the notes + run_id land in the
    # result so the agent can report and poll it (show_quorum_status).
    try:
        from forecasting.quorum_autorun import maybe_autorun_quorum

        _qa_notes: list[str] = []
        _qa = maybe_autorun_quorum(
            ledger,
            question_id,
            snapshot=snapshot,
            has_panel=args.get("panel_run_ref") is not None,
            has_prior_snapshot=_had_prior_snapshot,
            forecast_origin=args.get("forecast_origin") or "live",
            notify=_qa_notes.append,
        )
        if _qa is not None:
            _extra["quorum_autorun"] = {**_qa, "notes": _qa_notes}
            # PROVENANCE: persist the started/skipped decision onto the
            # snapshot itself so a post-hoc audit reads the full story
            # from the record (the operator's Senate-batch review could
            # not tell a by-design skip from silent breakage).
            try:
                ledger.annotate_snapshot(snapshot.forecast_id, {"quorum_autorun": _qa})
            except Exception:
                pass
    except Exception:
        pass
    return tool_result(success=True, forecast_snapshot=snapshot.__dict__, **_extra)


HANDLERS = {
    "full_forecast": full_forecast,
    "update_forecast": update_forecast,
}
