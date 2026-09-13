"""``forecast new`` / ``onboard`` / ``list`` / ``next`` / ``search`` / ``show`` /
``set-decision`` / ``update`` — the question lifecycle (create → inspect → append).

A carved CLI subcommand domain (the CLI-assembler pattern; see
:mod:`forecasting.cli.thesis`). These eight groups are contiguous in the
registration order, so they register via a single :func:`register` hook invoked
at their pre-carve position — ``forecast --help`` stays byte-identical. This is
the biggest single domain (the ``update`` snapshot-append machinery + its
component-pooling / preview / delta helpers travelled here); the slice carries
``MOVES-ONLY`` because the moved body exceeds the 1,200-line soft cap.

Shared helpers stay in ``core`` and are imported bare. Two names are reached via
call-time ``_core.`` hops (the monkeypatch discipline): ``_ledger`` and
``_draft_resolution_criteria`` (patched at ``forecasting.cli._draft_resolution_criteria``
by ``test_full_forecast_chain`` and called from ``_cmd_onboard``/``_cmd_new``).
``_print_panel_summary`` and ``_resolve_active_model_id`` STAY in ``core`` because
sibling carved domains (``quorum_panel``/``markets_pm``) import them. ``core``
imports this module back at its bottom for registration + surface parity
(``forecasting.cli._maybe_autorun_quorum`` is called by ``test_quorum_autonomy``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from forecasting.cli import core as _core
from forecasting.cli.core import (
    ForecastLedger,
    OutcomeSpace,
    PRODUCT_NAME,
    _BAYES_POOL_METHODS,
    _apply_source_plan_watches,
    _format_delta,
    _format_optional_float,
    _format_probability,
    _json_arg,
    _parse_outcome_paths,
    _print_panel_summary,
    _print_source_plan,
    _resolve_question_id,
    _truncate,
    _write_analyst_brief,
    apply_active_lesson_adjustments,
    json_loads,
    match_to_dict,
    parse_timestamp,
    plan_sources_for_question,
    run_forecast_chain,
    search_forecasts,
    should_apply_active_lessons,
    utc_now_iso,
    weighted_binary_probability,
)


def _ledger(args: argparse.Namespace) -> ForecastLedger:
    """Hop to ``core._ledger`` at CALL time (monkeypatch discipline)."""
    return _core._ledger(args)


def _draft_resolution_criteria(*args, **kwargs):
    """Hop to ``core._draft_resolution_criteria`` at CALL time — it stays in core
    (patched at the façade by ``test_full_forecast_chain`` and shared with the
    onboard path), so ``_cmd_onboard``/``_cmd_new`` see the patch."""
    return _core._draft_resolution_criteria(*args, **kwargs)


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the question-lifecycle command groups (contiguous block)."""

    new_parser = forecast_sub.add_parser("new", help="Create a scoreable forecast question")
    new_parser.add_argument("title")
    new_parser.add_argument("--description", default="")
    new_parser.add_argument("--resolution-criteria", required=True)
    new_parser.add_argument("--resolution-source")
    new_parser.add_argument(
        "--outcome-type",
        choices=["binary", "categorical", "numeric", "distribution"],
        default="binary",
    )
    new_parser.add_argument("--choice", dest="choices", action="append", default=[])
    new_parser.add_argument("--censor-at", type=float, help="Declare an inclusive right-censoring threshold; scores its event probability")
    new_parser.add_argument("--unit", dest="units")
    new_parser.add_argument("--bound", dest="bounds", type=float, action="append", default=[])
    new_parser.add_argument("--close-time")
    new_parser.add_argument("--resolution-time")
    new_parser.add_argument("--tag", dest="tags", action="append", default=[])
    new_parser.add_argument("--domain")
    new_parser.add_argument("--topic", dest="topics", action="append", default=[])
    new_parser.add_argument("--owner")
    new_parser.add_argument("--impact")
    new_parser.add_argument("--source-plan", action="store_true", help="Print recommended sources after creating the question")
    new_parser.add_argument(
        "--apply-source-plan",
        "--apply-watch",
        dest="apply_source_plan",
        action="store_true",
        help="Add (apply) the top recommended watched sources from the generated source plan",
    )
    new_parser.add_argument("--review-cadence")
    new_parser.add_argument("--next-review-at")
    new_parser.add_argument(
        "--decision-owner",
        help="Who owns the decision this forecast informs (e.g. 'ops lead', 'trading desk')",
    )
    new_parser.add_argument(
        "--decision-deadline",
        help="ISO-8601 timestamp by which the decision must be made",
    )
    new_parser.add_argument(
        "--action-threshold",
        help="Probability/threshold that triggers an action (e.g. 'evacuate if P > 0.05')",
    )
    new_parser.add_argument(
        "--update-trigger",
        dest="update_triggers",
        action="append",
        default=[],
        help=(
            "Repeatable. Each value is either a free-form trigger ('PCE release within 24h') "
            "or a JSON object with mechanism/threshold/action keys"
        ),
    )
    new_parser.set_defaults(_forecast_handler=_cmd_new)

    onboard_parser = forecast_sub.add_parser(
        "onboard",
        help="Curate a new question as a typed QuestionSpec — propose + validate, then commit the full fan-out",
    )
    onboard_parser.add_argument("prompt", nargs="?", help="Plain-language question to seed a draft spec")
    onboard_parser.add_argument("--spec", help="Path to a QuestionSpec JSON file (from a prior --json proposal, edited)")
    onboard_parser.add_argument(
        "--commit",
        action="store_true",
        help="Validate and commit the --spec (refuses on error-severity issues)",
    )
    onboard_parser.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Accept every recommended default, commit the question, then autonomously "
            "chain research -> base_rate -> update through the gated agent — a single "
            "vague sentence yields a complete, committed forecast"
        ),
    )
    onboard_parser.add_argument(
        "--criteria",
        help="Resolution criteria for the question (skips the LLM criteria draft under --auto)",
    )
    onboard_parser.add_argument("--model", help="--auto: model the pipeline stages run on")
    onboard_parser.add_argument("--provider", help="--auto: provider the pipeline stages run on")
    onboard_parser.add_argument(
        "--max-iterations", type=int, default=12, help="--auto: agent tool-calling budget per stage"
    )
    onboard_parser.add_argument(
        "--force-new",
        action="store_true",
        help=(
            "--auto: commit a NEW question even when a strong near-duplicate exists "
            "(default routes the refresh onto the existing question instead of forking a rival)"
        ),
    )
    onboard_parser.add_argument("--json", action="store_true", help="Emit the proposed spec + issues + clarifications as JSON")
    onboard_parser.set_defaults(_forecast_handler=_cmd_onboard)

    list_parser = forecast_sub.add_parser("list", help="List forecast questions")
    list_parser.add_argument("--status", choices=["active", "closed", "resolved", "archived"])
    list_parser.add_argument("--domain")
    list_parser.add_argument("--limit", type=int)
    list_parser.set_defaults(_forecast_handler=_cmd_list)

    next_parser = forecast_sub.add_parser(
        "next",
        help="Rank the book by value-of-information — what should I touch next?",
    )
    next_parser.add_argument("--limit", type=int, default=5, help="How many actions to print (default: 5)")
    next_parser.add_argument("--json", action="store_true", help="Emit the machine-readable ranked actions")
    next_parser.set_defaults(_forecast_handler=_cmd_next)

    search_parser = forecast_sub.add_parser(
        "search",
        help="Search forecast questions without remembering IDs",
    )
    search_parser.add_argument("query", nargs="+")
    search_parser.add_argument(
        "--status",
        choices=["active", "closed", "resolved", "archived", "all"],
        default="active",
        help="Question status to search; default: active",
    )
    search_parser.add_argument("--domain")
    search_parser.add_argument("--topic")
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.add_argument("--json", action="store_true", help="Emit machine-readable search results")
    search_parser.set_defaults(_forecast_handler=_cmd_search)

    show_parser = forecast_sub.add_parser("show", help="Show a forecast question")
    show_parser.add_argument("id")
    show_parser.set_defaults(_forecast_handler=_cmd_show)

    set_decision_parser = forecast_sub.add_parser(
        "set-decision",
        help="Set or revise decision_owner / decision_deadline / action_threshold / update_triggers",
    )
    set_decision_parser.add_argument("id")
    set_decision_parser.add_argument("--decision-owner")
    set_decision_parser.add_argument("--decision-deadline")
    set_decision_parser.add_argument("--action-threshold")
    set_decision_parser.add_argument(
        "--update-trigger",
        dest="update_triggers",
        action="append",
        default=None,
        help=(
            "Repeatable. Replaces existing triggers with the given set. Pass an empty value "
            "with --clear-triggers to remove all."
        ),
    )
    set_decision_parser.add_argument(
        "--clear-triggers",
        action="store_true",
        help="Remove all existing update triggers",
    )
    set_decision_parser.set_defaults(_forecast_handler=_cmd_set_decision)

    update_parser = forecast_sub.add_parser("update", help="Append a forecast snapshot")
    update_parser.add_argument("id")
    update_parser.add_argument("--probability", type=float)
    update_parser.add_argument("--numeric-value", type=float)
    update_parser.add_argument(
        "--distribution-json",
        help="JSON object mapping categorical outcomes to probabilities or distribution parameters such as mean/std",
    )
    update_parser.add_argument(
        "--rationale",
        nargs="+",
        help="Forecast rationale; quotes are optional when it is the last update field",
    )
    update_parser.add_argument("--as-of")
    update_parser.add_argument("--confidence", type=float)
    update_parser.add_argument(
        "--method",
        help=(
            "Ensemble method recorded with the snapshot. With --component-json and no "
            "explicit --probability, 'log_odds_pool' (or 'log_pool') pools components "
            "through the Bayesian toolkit (geometric pooling of odds, respects confident "
            "minorities); 'weighted_ensemble'/'linear' keeps the weighted average."
        ),
    )
    update_parser.add_argument("--component-json", default="{}")
    update_parser.add_argument(
        "--extremize",
        type=float,
        default=None,
        help="Extremization factor (>1 sharpens) applied when pooling components via a Bayesian method",
    )
    update_parser.add_argument(
        "--correlation",
        default=None,
        help="Correlation handling for Bayesian pooling: 'estimate' or a JSON NxN matrix; downweights double-counted sources",
    )
    update_parser.add_argument("--assumption", dest="key_assumptions", action="append", default=[])
    update_parser.add_argument("--assumption-ref", dest="assumption_refs", action="append", default=[])
    update_parser.add_argument("--reference-class-ref", dest="reference_class_refs", action="append", default=[])
    update_parser.add_argument("--evidence-ref", dest="evidence_refs", action="append", default=[])
    update_parser.add_argument("--stale-evidence-days", type=int, default=30)
    update_parser.add_argument("--ack-stale-evidence", action="store_true")
    update_parser.add_argument("--stale-evidence-reason", default=None,
                               help="Why committing on stale evidence is OK (records + clears the stale_evidence_justified WARN).")
    update_parser.add_argument(
        "--require-citations",
        action="store_true",
        help="Require a live forecast to cite at least one evidence/model/reference-class/"
        "source-snapshot/assumption/lesson ref. Opt-in (the soul/protocol nudges citing "
        "evidence); pass it when committing an evidence-backed forecast.",
    )
    update_parser.add_argument("--model-run-ref", dest="model_run_refs", action="append", default=[])
    update_parser.add_argument(
        "--origin",
        dest="forecast_origin",
        choices=["live", "exploratory", "backtest", "imported_baseline"],
        default="live",
        help="'live' commits a scored forecast (formalities enforced); 'exploratory' is a "
        "scratchpad forecast — free of commit-time formalities and not calibration-scored.",
    )
    update_parser.add_argument("--agent-model")
    update_parser.add_argument("--prompt-version")
    update_parser.add_argument("--protocol-version")
    update_parser.add_argument("--toolset-version")
    update_parser.add_argument("--source-snapshot-ref", dest="source_snapshot_refs", action="append", default=[])
    update_parser.add_argument(
        "--reason-up",
        dest="reasons_up",
        action="append",
        default=[],
        help="Repeatable. One concrete reason the probability should be higher.",
    )
    update_parser.add_argument(
        "--reason-down",
        dest="reasons_down",
        action="append",
        default=[],
        help="Repeatable. One concrete reason the probability should be lower.",
    )
    update_parser.add_argument(
        "--change-my-mind",
        dest="change_my_mind",
        action="append",
        default=[],
        help="Repeatable. One observation that would force a material update.",
    )
    update_parser.add_argument(
        "--require-structured-reasoning",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refuse to save a live snapshot unless --reason-up, --reason-down, and "
        "--change-my-mind are all set. On by default; use --no-require-structured-reasoning "
        "(or --origin exploratory) to skip.",
    )
    update_parser.add_argument(
        "--require-decision-readiness",
        action="store_true",
        help=(
            "Refuse to save the snapshot unless the question has decision_owner, "
            "action_threshold, and at least one update_trigger"
        ),
    )
    update_parser.add_argument(
        "--panel-estimates-json",
        dest="panel_estimates_json",
        default=None,
        help=(
            "JSON array of panel estimates (one per perspective). When supplied, "
            "the panel is aggregated to derive the snapshot probability and a "
            "panel_run record is attached to the snapshot."
        ),
    )
    update_parser.add_argument(
        "--panel-estimates-file",
        dest="panel_estimates_file",
        default=None,
        help="Path to a JSON file containing panel estimates",
    )
    update_parser.add_argument(
        "--panel-method",
        dest="panel_method",
        choices=sorted(["trimmed_geomean_odds", "log_odds_pool", "median", "mean"]),
        default="trimmed_geomean_odds",
    )
    update_parser.add_argument(
        "--panel-trim",
        dest="panel_trim",
        type=int,
        default=1,
    )
    update_parser.add_argument(
        "--panel-triggered-by",
        dest="panel_triggered_by",
        default="manual",
    )
    update_parser.add_argument(
        "--require-panel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For a high-impact live forecast, refuse to save unless a panel run is "
        "linked (--panel-run-ref / --panel-estimates-json) or --panel-skipped-reason is "
        "given. On by default; lower-impact first forecasts are only nudged. Use "
        "--no-require-panel (or --origin exploratory) to skip.",
    )
    update_parser.add_argument(
        "--panel-run-ref",
        dest="panel_run_ref",
        default=None,
        help="ID of an already-recorded panel run to link to this snapshot as its "
        "deliberative-panel evidence.",
    )
    update_parser.add_argument(
        "--panel-skipped-reason",
        dest="panel_skipped_reason",
        default=None,
        help="Recorded reason for committing a panel-indicated forecast without a panel "
        "(escape valve for the panel formality).",
    )
    update_parser.add_argument(
        "--outcome-path",
        dest="outcome_paths",
        action="append",
        default=[],
        metavar="OUTCOME=PATH|JSON",
        help="Categorical forecasts: name the causal path for an outcome, e.g. "
        "--outcome-path 'Lasher=leads polls + endorsements' or "
        "--outcome-path 'Lasher={\"base_rate\":0.42,\"base_rate_source\":\"prior result\"}'. "
        "Repeatable. Feeds the probability-mass audit that flags unearned tail mass "
        "and uncited named outcomes.",
    )
    update_parser.add_argument(
        "--require-outcome-paths",
        dest="require_outcome_paths",
        action="store_true",
        help="Categorical live forecasts: refuse to commit when a material outcome holds "
        "mass with no named path (unearned tail mass).",
    )
    update_parser.add_argument("--evidence-cutoff")
    update_parser.add_argument("--backtest-run-id")
    update_parser.add_argument("--calibration-ineligible", action="store_true")
    update_parser.add_argument("--calibration-weight", type=float, default=1.0)
    update_parser.add_argument("--calibration-lesson-ref", dest="calibration_lesson_refs", action="append", default=[])
    update_parser.add_argument("--calibration-adjustment-json", default="{}")
    update_parser.add_argument(
        "--use-active-lessons",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Attach active global/domain/topic/question-type calibration lessons "
            "and apply the measured probability adjustment. ON by default for LIVE "
            "commits only (the pre-adjustment raw_probability is recorded for audit); "
            "backtest/imported commits are NOT auto-adjusted (pass "
            "--use-active-lessons to opt in). Use --no-use-active-lessons to commit "
            "your raw number. Exploratory commits are never adjusted."
        ),
    )
    update_parser.add_argument("--preview", action="store_true", help="Show update preview without writing a snapshot")
    update_parser.set_defaults(_forecast_handler=_cmd_update)



def _cmd_new(args: argparse.Namespace) -> None:
    bounds = args.bounds or None
    choices = args.choices or (["yes", "no"] if args.outcome_type == "binary" else [])
    outcome_space = OutcomeSpace(
        type=args.outcome_type,
        censoring={"threshold": args.censor_at, "inclusive": True} if getattr(args, "censor_at", None) is not None else None,
        choices=choices,
        units=args.units,
        bounds=bounds,
    )
    ledger = _ledger(args)
    triggers = _parse_update_trigger_args(getattr(args, "update_triggers", None) or [])
    question = ledger.create_question(
        title=args.title,
        description=args.description,
        resolution_criteria=args.resolution_criteria,
        resolution_source=args.resolution_source,
        outcome_space=outcome_space,
        close_time=args.close_time,
        resolution_time=args.resolution_time,
        tags=args.tags,
        domain=args.domain,
        topics=args.topics,
        owner=args.owner,
        impact=args.impact,
        review_cadence=args.review_cadence,
        next_review_at=args.next_review_at,
        decision_owner=getattr(args, "decision_owner", None),
        decision_deadline=getattr(args, "decision_deadline", None),
        action_threshold=getattr(args, "action_threshold", None),
        update_triggers=triggers,
    )
    print(f"created forecast question {question.id}")
    print(f"title: {question.title}")
    print(f"status: {question.status}")
    if question.decision_owner or question.action_threshold or question.update_triggers:
        print(f"decision_owner: {question.decision_owner or '-'}")
        print(f"action_threshold: {question.action_threshold or '-'}")
        if question.update_triggers:
            print(f"update_triggers: {len(question.update_triggers)}")
    else:
        issues = ledger.decision_readiness_issues(question)
        if issues:
            print(f"decision_readiness: {', '.join(issues)}")
            print(
                f"  add: forecast set-decision {question.id} --decision-owner ... "
                "--action-threshold ... --update-trigger ..."
            )
    if args.source_plan or args.apply_source_plan:
        print("")
        _print_source_plan(ledger, question, apply_watch=args.apply_source_plan, limit=12)


def _cmd_onboard(args: argparse.Namespace) -> None:
    from forecasting.question_spec import (
        apply_recommended_defaults,
        recommended_clarifications,
        spec_from_dict,
        spec_quality,
        suggest_resolution_rule,
    )

    ledger = _ledger(args)
    if args.spec:
        with open(args.spec, encoding="utf-8") as fh:
            raw = json.load(fh)
    elif args.prompt:
        raw = {"title": args.prompt, "resolution_criteria": getattr(args, "criteria", None) or ""}
    else:
        raise SystemExit("forecast onboard needs a prompt or --spec FILE")

    spec = spec_from_dict(raw)

    if getattr(args, "auto", False):
        # Accept-defaults autonomous entry point: a single vague sentence becomes a
        # complete, committed, self-refreshing forecast. Apply the recommended
        # default of every gap/error clarification, commit the whole fan-out, then
        # chain research -> base_rate -> update through the SAME gated agent path a
        # manual run uses (no gate is weakened — error-severity issues still block
        # the commit below via spec.commit()).
        spec, applied = apply_recommended_defaults(spec)

        # Stage 0 of the autonomous pipeline: DRAFT the resolution criteria when the
        # bare sentence carries none. accept-defaults rightly refuses to fabricate
        # free text, but --auto already requires an LLM for the research/base_rate/
        # update chain below — so one bounded, tool-less drafting call is what makes
        # "one sentence in, a forecast out" actually true from the CLI. The draft
        # still faces the full spec validation: an unscoreable draft fails the same
        # honest error below, never a weaker commit.
        if not (spec.resolution_criteria or "").strip():
            drafted = _draft_resolution_criteria(spec, model=args.model, provider=args.provider)
            if drafted:
                from dataclasses import replace as _spec_replace

                spec = _spec_replace(spec, resolution_criteria=drafted)
                print(f'  drafted resolution criteria: "{drafted}"')
                # criteria text can pin the horizon — re-apply so close_time upgrades
                # from the end-of-year fallback to the criteria-implied deadline.
                spec, more = apply_recommended_defaults(spec)
                applied += more

        errs = [i for i in spec.errors()]
        if errs:
            # accept-defaults never fabricates past an un-defaultable error (e.g. an
            # unscoreable resolution criteria) — the commit gate is unchanged.
            print("cannot auto-forecast — fix these first:")
            for e in errs:
                print(f"  [error] {e.field}: {e.message}" + (f"  ({e.fix})" if e.fix else ""))
            raise SystemExit(1)

        # Duplicate routing: two lazy prompts of the same sentence must REFRESH the
        # existing question, not fork a rival. Reuse the shared duplicate ranker — a
        # strong near-duplicate (score >= the warn threshold) routes the SAME stage
        # chain onto the existing id unless --force-new is set.
        from forecasting.application.question_reuse import (
            DUPLICATE_WARN_SCORE as _DUPLICATE_WARN_SCORE,
            find_possible_duplicates as _find_possible_duplicates,
        )

        duplicates = _find_possible_duplicates(ledger, spec.title)
        top = duplicates[0] if duplicates else None
        strong_dup = top is not None and top["score"] >= _DUPLICATE_WARN_SCORE
        force_new = getattr(args, "force_new", False)
        if strong_dup and not force_new:
            qid = top["id"]
            print(
                f"routed to existing forecast {qid} (\"{top['title']}\") — refreshing that "
                "instead of forking a rival (pass --force-new to create a new question)"
            )
        else:
            if strong_dup:
                print(
                    f"warning: you already track {top['id']} (\"{top['title']}\") — "
                    "committing a new rival question anyway (--force-new)"
                )
            result = spec.commit(ledger)
            qid = result["question_id"]
            print(f"created forecast question {qid} (accepted {len(applied)} defaults)")
            print(f"  watched_sources: {len(result['watched_sources'])}")
            print(f"  reference_classes: {len(result['reference_classes'])}")
            if result["readiness_gaps"]:
                print(f"  readiness gaps (waived): {', '.join(g['field'] for g in result['readiness_gaps'])}")
            # Feed the spine: an auto-path question usually commits with ZERO watched
            # sources, so the deterministic scheduled refresh has nothing to pull.
            # Auto-attach the top recommended watches via the SAME apply seam
            # `forecast sources --apply-watch` uses. Fail-open — a planner hiccup must
            # never block the forecast.
            if not spec.watched_sources and spec.allow_evidence_gathering:
                attached: list[dict[str, Any]] = []
                try:
                    question = ledger.get_question(qid)
                    recs = plan_sources_for_question(question)
                    candidates = [r for r in recs if not r.requires_user_source and r.watch_source][:3]
                    attached, _ = _apply_source_plan_watches(ledger, qid, candidates)
                except Exception:
                    attached = []
                if attached:
                    print(f"  attached {len(attached)} watched source(s) so this refreshes itself:")
                    for row in attached:
                        print(f"    {row['source_type']} {row['source']}")

        def _progress(stage: str, outcome: dict[str, Any]) -> None:
            mark = "committed" if outcome.get("committed") else outcome.get("status", "ran")
            detail = outcome.get("detail")
            line = f"  stage {stage:<10} [{mark}]"
            if outcome.get("forecast_id"):
                line += f" -> {outcome['forecast_id']}"
            if detail:
                line += f"  {detail}"
            print(line)

        print("chaining pipeline stages:")
        chain = run_forecast_chain(
            ledger,
            qid,
            model=args.model,
            provider=args.provider,
            max_iterations=args.max_iterations,
            on_stage=_progress,
        )
        if chain["committed"] and chain["snapshot"]:
            snap = chain["snapshot"]
            print(f"committed forecast {snap['forecast_id']}: {snap['probability_or_distribution']}")
        elif chain["update_blockers"]:
            print(f"forecast NOT committed — update still gated by: {', '.join(chain['update_blockers'])}")
        else:
            print("forecast NOT committed — the agent declined to commit a new snapshot")
        return

    issues = spec.validate()

    if args.commit:
        errs = [i for i in issues if i.severity == "error"]
        if errs:
            print("cannot commit — fix these first:")
            for e in errs:
                print(f"  [error] {e.field}: {e.message}" + (f"  ({e.fix})" if e.fix else ""))
            raise SystemExit(1)
        result = spec.commit(ledger)
        print(f"created forecast question {result['question_id']}")
        print(f"  watched_sources: {len(result['watched_sources'])}")
        print(f"  reference_classes: {len(result['reference_classes'])}")
        if result["readiness_gaps"]:
            print(f"  readiness gaps (waived): {', '.join(g['field'] for g in result['readiness_gaps'])}")
        return

    if args.json:
        print(
            json.dumps(
                {
                    "spec": spec.to_dict(),
                    "issues": [i.to_dict() for i in issues],
                    "recommended_clarifications": recommended_clarifications(spec),
                    "committable": spec.is_committable(),
                    "spec_quality": spec_quality(spec),
                    "suggested_resolution_rule": suggest_resolution_rule(spec),
                },
                indent=2,
            )
        )
        return

    # Human-readable proposal: the draft, its issues, and the clarifications to ask.
    print(f"proposed forecast question: {spec.title or '(untitled)'}")
    print(f"  outcome: {spec.outcome_type}   committable: {spec.is_committable()}")
    for label in ("error", "gap", "warn"):
        for i in (x for x in issues if x.severity == label):
            print(f"  [{label}] {i.field}: {i.message}")
    clarifications = recommended_clarifications(spec)
    if clarifications:
        print("clarify with the user:")
        for c in clarifications:
            choices = f"  [{' / '.join(c['choices'])}]" if c["choices"] else "  (free text)"
            print(f"  - {c['question']}{choices}")
    print("")
    print('fastest: forecast onboard "<your question>" --auto   (accepts every recommended')
    print("         default, drafts auditable criteria, then runs research -> base rate ->")
    print("         committed forecast autonomously; add --criteria to pin your own)")
    print("or edit a spec JSON and commit:  forecast onboard --spec spec.json --commit")
    print("(get the JSON skeleton with:  forecast onboard \"<your question>\" --json)")


def _parse_update_trigger_args(values: list[str]) -> list[Any]:
    """Parse repeated ``--update-trigger`` values into trigger payloads.

    Each value is JSON-decoded if it looks like an object; otherwise treated
    as a free-form mechanism string. Normalization happens downstream in the
    ledger.
    """

    parsed: list[Any] = []
    for raw in values:
        text = (raw or "").strip()
        if not text:
            continue
        if text.startswith("{"):
            try:
                parsed.append(json.loads(text))
                continue
            except json.JSONDecodeError as exc:
                raise SystemExit(f"--update-trigger JSON is invalid: {exc.msg}") from exc
        parsed.append(text)
    return parsed


def _cmd_list(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    rows = ledger.list_questions(status=args.status, domain=args.domain, limit=args.limit)
    if not rows:
        print("No forecast questions found.")
        return
    print("ID             Status     P(now)    AsOf                 Delta    Close                Domain     Title")
    for question in rows:
        snapshot = ledger.get_current_snapshot(question.id)
        probability = _format_probability(snapshot.probability_or_distribution) if snapshot else "-"
        as_of = snapshot.as_of if snapshot else "-"
        delta = _format_delta(_question_delta(ledger, question.id))
        close = question.close_time or "-"
        domain = question.domain or "-"
        print(
            f"{question.id:<14} {question.status:<10} {probability:<9} {as_of:<20} "
            f"{delta:<8} {close:<20} {domain:<10} {question.title}"
        )


def _cmd_next(args: argparse.Namespace) -> None:
    """Print the desk's VOI ranking — "what should I touch next?". Reads the SAME
    server-side voi scores/reasons the TUI Desk shows (build_workspace_payload), so
    the CLI, the agent, and the surface never disagree on the priority order."""

    from forecasting.dashboard import build_workspace_payload

    ledger = _ledger(args)
    payload = build_workspace_payload(ledger=ledger, include_related=False, include_lessons=False)
    limit = max(1, getattr(args, "limit", None) or 5)
    # The canonical desk-level top-5 rides in the payload; for a deeper --limit we
    # walk the same server-assigned voi.rank over the actionable book (identical
    # ordering, just not truncated to 5).
    forecasts = payload.get("forecasts") or []
    ranked = sorted(
        (f for f in forecasts if (f.get("voi") or {}).get("action") not in (None, "none")),
        key=lambda f: (f.get("voi") or {}).get("rank") or 10**9,
    )[:limit]
    rows = [
        {
            "question_id": f.get("id"),
            "title": f.get("title"),
            "action": (f.get("voi") or {}).get("action"),
            "reason": (f.get("voi") or {}).get("reason"),
            "score": (f.get("voi") or {}).get("score"),
            "rank": (f.get("voi") or {}).get("rank"),
        }
        for f in ranked
    ]
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, sort_keys=True))
        return
    print(PRODUCT_NAME)
    print("next best actions — value of information (what to touch next)")
    if not rows:
        print("nothing pressing: the book is fresh, sourced, and away from resolution.")
        return
    for index, row in enumerate(rows, start=1):
        score = row.get("score")
        score_text = f"{float(score):.2f}" if isinstance(score, (int, float)) else "-"
        print(f"{index}. [{row.get('action') or '-'}] {row.get('title') or row.get('question_id') or '-'}  (voi {score_text})")
        if row.get("reason"):
            print(f"   {row['reason']}")
        print(f"   forecast show {row.get('question_id')}")


def _cmd_search(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    query = " ".join(args.query).strip()
    matches = search_forecasts(
        ledger,
        query,
        status=args.status,
        domain=args.domain,
        topic=args.topic,
        limit=args.limit,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "query": query,
                    "status": args.status,
                    "domain": args.domain,
                    "topic": args.topic,
                    "matches": [match_to_dict(match) for match in matches],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    if not matches:
        print("No matching forecast questions found.")
        return
    print("FORECAST SEARCH")
    print(f"query: {query}")
    print("ID             Status     P(now)    AsOf                 Delta    Close                Domain     Score  Fields        Title")
    for match in matches:
        question = match.question
        snapshot = match.current_snapshot
        probability = _format_probability(snapshot.probability_or_distribution) if snapshot else "-"
        as_of = snapshot.as_of if snapshot else "-"
        delta = _format_delta(_question_delta(ledger, question.id))
        close = question.close_time or "-"
        domain = question.domain or "-"
        fields = ",".join(match.matched_fields[:3]) or "-"
        print(
            f"{question.id:<14} {question.status:<10} {probability:<9} {as_of:<20} "
            f"{delta:<8} {close:<20} {domain:<10} {match.score:<6} "
            f"{_truncate(fields, 13):<13} {question.title}"
        )
        for field, snippet in list(match.snippets.items())[:2]:
            print(f"  {field}: {snippet}")
        print(f"  open: forecast show {question.id}")


def _cmd_set_decision(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    triggers: Any = None
    if args.clear_triggers:
        triggers = []
    elif args.update_triggers is not None:
        triggers = _parse_update_trigger_args(args.update_triggers)
    question = ledger.update_question_decision(
        args.id,
        decision_owner=args.decision_owner,
        decision_deadline=args.decision_deadline,
        action_threshold=args.action_threshold,
        update_triggers=triggers,
    )
    print(f"question: {question.id}")
    print(f"decision_owner: {question.decision_owner or '-'}")
    print(f"decision_deadline: {question.decision_deadline or '-'}")
    print(f"action_threshold: {question.action_threshold or '-'}")
    print(f"update_triggers: {len(question.update_triggers)}")
    issues = ledger.decision_readiness_issues(question)
    if issues:
        print(f"decision_readiness: {', '.join(issues)}")
    else:
        print("decision_readiness: ready")


def _cmd_show(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    args.id = _resolve_question_id(ledger, args.id)
    question = ledger.get_question(args.id)
    snapshots = ledger.list_snapshots(args.id)
    evidence = ledger.list_evidence(args.id)
    baselines = ledger.list_baseline_comparisons(args.id)
    resolution = ledger.get_latest_resolution(args.id)
    print(f"{question.title}")
    print(f"id: {question.id}")
    print(f"status: {question.status}")
    print(f"domain: {question.domain or '-'}")
    print(f"outcome: {question.outcome_space.type} {question.outcome_space.choices}")
    print(f"close_time: {question.close_time or '-'}")
    print(f"resolution_time: {question.resolution_time or '-'}")
    print(f"resolution_criteria: {question.resolution_criteria}")
    if (
        question.decision_owner
        or question.decision_deadline
        or question.action_threshold
        or question.update_triggers
    ):
        print()
        print("decision_card:")
        print(f"  owner: {question.decision_owner or '-'}")
        print(f"  deadline: {question.decision_deadline or '-'}")
        print(f"  action_threshold: {question.action_threshold or '-'}")
        if question.update_triggers:
            print(f"  update_triggers: {len(question.update_triggers)}")
            for trigger in question.update_triggers[:5]:
                line = trigger.get("mechanism", "-")
                if trigger.get("threshold"):
                    line += f" [{trigger['threshold']}]"
                if trigger.get("action"):
                    line += f" -> {trigger['action']}"
                print(f"    - {line}")
        readiness = ledger.decision_readiness_issues(question)
        if readiness:
            print(f"  decision_readiness: {', '.join(readiness)}")
    print()
    current = ledger.get_current_snapshot(args.id)
    if current:
        print("current_forecast:")
        print(f"  id: {current.forecast_id}")
        print(f"  as_of: {current.as_of}")
        print(f"  probability: {_format_probability(current.probability_or_distribution)}")
        print(f"  confidence: {current.confidence if current.confidence is not None else '-'}")
        print(f"  origin: {current.forecast_origin}")
        print(f"  rationale: {current.rationale}")
        if current.reasons_up:
            print("  reasons_up:")
            for reason in current.reasons_up:
                print(f"    - {reason}")
        if current.reasons_down:
            print("  reasons_down:")
            for reason in current.reasons_down:
                print(f"    - {reason}")
        if current.change_my_mind:
            print("  change_my_mind:")
            for reason in current.change_my_mind:
                print(f"    - {reason}")
    else:
        print("current_forecast: none")
    print()
    print("recent_history:")
    for snapshot in snapshots[-5:]:
        print(f"  {snapshot.as_of} {snapshot.forecast_id} {_format_probability(snapshot.probability_or_distribution)}")
    if not snapshots:
        print("  none")
    print()
    print(f"evidence_count: {len(evidence)}")
    print(f"baseline_comparisons: {len(baselines)}")
    if resolution:
        print(f"resolution: {resolution.outcome} ({resolution.resolution_status})")


def _cmd_update(args: argparse.Namespace) -> None:
    components = _json_arg(args.component_json, "component-json")
    ledger = _ledger(args)
    question = ledger.get_question(args.id)
    rationale = _joined_arg(args.rationale)
    panel_estimates = _load_panel_estimates(args)
    panel_run_record: dict[str, Any] | None = None
    has_panel = panel_estimates is not None
    has_payload = (
        any(
            value is not None
            for value in (args.probability, args.numeric_value, args.distribution_json)
        )
        or bool(components)
        or has_panel
    )
    non_citation_update_fields = [
        rationale is not None,
        args.as_of is not None,
        args.confidence is not None,
        args.method is not None,
        bool(args.key_assumptions),
        bool(args.assumption_refs),
        bool(args.reference_class_refs),
        bool(args.evidence_refs),
        args.stale_evidence_days != 30,
        args.ack_stale_evidence,
        bool(args.model_run_refs),
        args.forecast_origin != "live",
        args.agent_model is not None,
        args.prompt_version is not None,
        args.protocol_version is not None,
        args.toolset_version is not None,
        bool(args.source_snapshot_refs),
        bool(getattr(args, "reasons_up", None)),
        bool(getattr(args, "reasons_down", None)),
        bool(getattr(args, "change_my_mind", None)),
        # NOTE: require_structured_reasoning / require_citations are now policies
        # that default ON for live forecasts (BooleanOptionalAction), so they no
        # longer signal "the user wants to save" — they're deliberately excluded
        # from update-intent detection. require_decision_readiness stays opt-in.
        getattr(args, "require_decision_readiness", False),
        args.evidence_cutoff is not None,
        args.backtest_run_id is not None,
        args.calibration_ineligible,
        args.calibration_weight != 1.0,
        bool(args.calibration_lesson_refs),
        args.calibration_adjustment_json != "{}",
        # NOTE: use_active_lessons now DEFAULTS ON (BooleanOptionalAction), so it no
        # longer signals "the user wants to save" — like require_citations, it is
        # excluded from update-intent detection. A bare `forecast update <id>` stays
        # a no-op inspection.
        args.preview,
    ]
    # require_citations now defaults ON for live forecasts, so it is no longer a
    # save-intent signal either; intent is a probability payload or a real content
    # change. A bare `forecast update <id>` stays a no-op inspection.
    update_fields = [has_payload, *non_citation_update_fields]
    if not any(update_fields):
        previous = ledger.get_current_snapshot(args.id)
        print(f"question: {question.id}")
        print(f"title: {question.title}")
        probability = _format_probability(previous.probability_or_distribution) if previous else "-"
        print(f"current_probability: {probability}")
        print(f"current_as_of: {previous.as_of if previous else '-'}")
        print(f"current_confidence: {_format_optional_float(previous.confidence) if previous else '-'}")
        if args.require_citations:
            print("citation_policy: required on next saved update")
            print(
                f"add: forecast update {args.id} --probability <p> --rationale <why> "
                "--evidence-ref <ref> --require-citations"
            )
        else:
            print(f"add: forecast update {args.id} --probability <p> --rationale <why>")
        print("probability unchanged")
        return
    if has_panel:
        panel_run_record = ledger.record_panel_run(
            question_id=args.id,
            estimates=panel_estimates,
            aggregation_method=getattr(args, "panel_method", "trimmed_geomean_odds"),
            trim=getattr(args, "panel_trim", 1),
            triggered_by=getattr(args, "panel_triggered_by", "manual"),
        )
        if args.probability is None and args.numeric_value is None and args.distribution_json is None:
            args.probability = panel_run_record["aggregate_probability"]
        if not components:
            components = {
                "components": [
                    {
                        "name": estimate["perspective"],
                        "probability": estimate["probability"],
                        "weight": estimate["weight"],
                        "source": f"panel:{estimate['perspective']}",
                    }
                    for estimate in panel_run_record["estimates"]
                    if not estimate.get("trimmed")
                ]
            }
        if args.method is None:
            args.method = panel_run_record["aggregation_method"]
    payload = _probability_payload(args, components)
    calibration_adjustment = _json_arg(args.calibration_adjustment_json, "calibration-adjustment-json")
    calibration_lesson_refs = list(args.calibration_lesson_refs)
    # Measured-bias correction applies BY DEFAULT for LIVE commits (S7);
    # --no-use-active-lessons opts out. backtest/imported_baseline are never auto-
    # adjusted (the live-derived correction would contaminate the closed-book
    # benchmark) — pass --use-active-lessons to opt in. Exploratory scratchpad
    # commits are never calibration-scored, so they are left untouched.
    # apply_active_lesson_adjustments records raw_probability before adjusting, so
    # net movement stays auditable.
    if should_apply_active_lessons(args.use_active_lessons, args.forecast_origin):
        payload, calibration_lesson_refs, calibration_adjustment = apply_active_lesson_adjustments(
            ledger=ledger,
            question=question,
            payload=payload,
            calibration_lesson_refs=calibration_lesson_refs,
            calibration_adjustment=calibration_adjustment,
        )
    previous = ledger.get_current_snapshot(args.id)
    if args.preview:
        proposed_as_of = parse_timestamp(args.as_of, field_name="as_of") or utc_now_iso()
        _print_update_preview(
            previous,
            payload,
            components,
            proposed_as_of,
            calibration_lesson_refs,
            calibration_adjustment,
        )
        return
    if not rationale:
        raise SystemExit("forecast update requires --rationale when saving a snapshot")
    # An inline panel (--panel-estimates-json) IS the deliberative panel, so it
    # satisfies the panel formality; otherwise honor an explicit --panel-run-ref.
    panel_run_ref = (
        panel_run_record["id"]
        if panel_run_record is not None
        else getattr(args, "panel_run_ref", None)
    )
    snapshot = ledger.create_snapshot(
        question_id=args.id,
        probability_or_distribution=payload,
        rationale=rationale,
        as_of=args.as_of,
        confidence=args.confidence,
        method=args.method,
        ensemble_components=components,
        key_assumptions=args.key_assumptions,
        assumption_refs=args.assumption_refs,
        reference_class_refs=args.reference_class_refs,
        evidence_refs=args.evidence_refs,
        stale_evidence_days=args.stale_evidence_days,
        acknowledge_stale_evidence=args.ack_stale_evidence,
        stale_evidence_reason=args.stale_evidence_reason,
        require_citations=args.require_citations,
        model_run_refs=args.model_run_refs,
        forecast_origin=args.forecast_origin,
        agent_model=args.agent_model,
        prompt_version=args.prompt_version,
        forecasting_protocol_version=args.protocol_version,
        toolset_version=args.toolset_version,
        source_snapshot_refs=args.source_snapshot_refs,
        evidence_cutoff=args.evidence_cutoff,
        backtest_run_id=args.backtest_run_id,
        calibration_eligible=not args.calibration_ineligible,
        calibration_weight=args.calibration_weight,
        calibration_lesson_refs=calibration_lesson_refs,
        calibration_adjustment=calibration_adjustment,
        reasons_up=getattr(args, "reasons_up", None) or None,
        reasons_down=getattr(args, "reasons_down", None) or None,
        change_my_mind=getattr(args, "change_my_mind", None) or None,
        require_structured_reasoning=getattr(args, "require_structured_reasoning", False),
        require_decision_readiness=getattr(args, "require_decision_readiness", False),
        require_panel=getattr(args, "require_panel", False),
        panel_run_ref=panel_run_ref,
        panel_skipped_reason=getattr(args, "panel_skipped_reason", None),
        outcome_paths=_parse_outcome_paths(getattr(args, "outcome_paths", None)),
        require_outcome_paths=getattr(args, "require_outcome_paths", False),
        # Record which related forecasts informed this one (server-side provenance).
        metadata={"cross_refs": _xrefs} if (_xrefs := ledger.build_cross_refs(args.id)) else None,
    )
    # create_snapshot links panel_run_ref itself; no separate attach needed.
    print(f"created forecast snapshot {snapshot.forecast_id}")
    print(f"question: {snapshot.question_id}")
    print(f"as_of: {snapshot.as_of}")
    print(f"probability: {_format_probability(snapshot.probability_or_distribution)}")
    if previous is not None:
        delta = _probability_delta(previous.probability_or_distribution, snapshot.probability_or_distribution)
        if delta is not None:
            print(f"previous_probability: {_format_probability(previous.probability_or_distribution)}")
            print(f"delta: {delta:+.3f}")
    if panel_run_record is not None:
        _print_panel_summary(panel_run_record)
    if components:
        _print_component_drivers(components, snapshot.probability_or_distribution)
    _print_calibration_adjustment_summary(calibration_lesson_refs, calibration_adjustment)
    # Standard step of the update process: write a time-indexed analyst brief for
    # the snapshot we just committed. Best-effort, after the ledger write.
    _write_analyst_brief(ledger, args.id, snapshot, previous=previous)
    _maybe_autorun_quorum(
        ledger, args.id, snapshot=snapshot,
        has_panel=panel_run_ref is not None,
        has_prior_snapshot=previous is not None,
        forecast_origin=args.forecast_origin,
    )


def _maybe_autorun_quorum(
    ledger: "ForecastLedger",
    question_id: str,
    *,
    snapshot: Any,
    has_panel: bool,
    has_prior_snapshot: bool,
    forecast_origin: str | None,
) -> None:
    """AUTO-RUN a quorum (detached) when one is auto-indicated but none attached.

    Thin CLI wrapper over :func:`forecasting.quorum_autorun.maybe_autorun_quorum` —
    the shared seam every commit surface uses (the agent tool's
    ``update_forecast`` calls the same function, so the autonomous paths get the
    same multi-model fusion a hand-typed ``forecast update`` does) — printing its
    progress lines. Fail-open by construction: the shared helper never raises.
    """

    from forecasting.quorum_autorun import maybe_autorun_quorum

    maybe_autorun_quorum(
        ledger,
        question_id,
        snapshot=snapshot,
        has_panel=has_panel,
        has_prior_snapshot=has_prior_snapshot,
        forecast_origin=forecast_origin,
        notify=print,
    )


def _print_update_preview(
    previous: Any,
    payload: Any,
    components: dict[str, Any],
    proposed_as_of: str,
    calibration_lesson_refs: list[str] | None = None,
    calibration_adjustment: dict[str, Any] | None = None,
) -> None:
    print("forecast update preview")
    print(f"previous_as_of: {previous.as_of if previous else '-'}")
    print(f"previous_probability: {_format_probability(previous.probability_or_distribution) if previous else '-'}")
    print(f"proposed_as_of: {proposed_as_of}")
    print(f"proposed_probability: {_format_probability(payload)}")
    delta = _probability_delta(previous.probability_or_distribution, payload) if previous else None
    print(f"delta: {delta:+.3f}" if delta is not None else "delta: -")
    if components:
        _print_component_drivers(components, payload)
    _print_calibration_adjustment_summary(calibration_lesson_refs or [], calibration_adjustment or {})


def _print_calibration_adjustment_summary(
    calibration_lesson_refs: list[str],
    calibration_adjustment: dict[str, Any],
) -> None:
    if calibration_lesson_refs:
        print(f"calibration_lessons: {len(calibration_lesson_refs)}")
    if "raw_probability" in calibration_adjustment:
        print(f"raw_probability: {_format_probability(calibration_adjustment['raw_probability'])}")
    if "applied_probability_delta" in calibration_adjustment:
        print(f"applied_probability_delta: {calibration_adjustment['applied_probability_delta']:+.3f}")
    if "applied_logit_shift" in calibration_adjustment:
        print(f"applied_logit_shift: {calibration_adjustment['applied_logit_shift']:+.3f}")


def _print_component_drivers(components: dict[str, Any], payload: Any) -> None:
    rows = _component_rows(components)
    print(f"ensemble_components: {len(rows)}")
    if not rows or not isinstance(payload, (int, float)):
        return
    try:
        total_weight = sum(float(row.get("weight", 1.0)) for row in rows)
    except (TypeError, ValueError):
        return
    if total_weight <= 0:
        return
    payload_value = float(payload)
    ranked = []
    for row in rows:
        probability = row.get("probability")
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            continue
        try:
            weight = float(row.get("weight", 1.0))
        except (TypeError, ValueError):
            continue
        contribution = (weight / total_weight) * float(probability)
        pull = (float(probability) - payload_value) * (weight / total_weight)
        ranked.append((abs(pull), row.get("name", "-"), float(probability), weight, contribution, pull))
    if not ranked:
        return
    ranked.sort(reverse=True)
    strongest = ranked[0]
    print(f"strongest_driver: {strongest[1]} pull={strongest[5]:+.3f}")
    print("component_drivers:")
    for _, name, probability, weight, contribution, pull in ranked:
        print(f"  {name} p={probability:.3f} w={weight:g} contribution={contribution:.3f} pull={pull:+.3f}")


def _component_rows(components: dict[str, Any]) -> list[dict[str, Any]]:
    rows = components.get("components")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    result = []
    for name, row in components.items():
        if isinstance(row, dict):
            item = dict(row)
            item.setdefault("name", name)
            result.append(item)
    return result


def _load_panel_estimates(args: argparse.Namespace) -> list[dict[str, Any]] | None:
    """Resolve panel-estimate JSON from --panel-estimates-json or --panel-estimates-file."""

    raw = getattr(args, "panel_estimates_json", None)
    if raw is None:
        path = getattr(args, "panel_estimates_file", None)
        if path:
            try:
                raw = Path(path).expanduser().read_text(encoding="utf-8")
            except OSError as exc:
                raise SystemExit(f"forecast update: cannot read --panel-estimates-file: {exc}") from exc
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"forecast update: invalid --panel-estimates-json: {exc.msg}") from exc
    if isinstance(data, dict) and "estimates" in data:
        data = data["estimates"]
    if not isinstance(data, list) or not data:
        raise SystemExit(
            "forecast update: --panel-estimates-json must be a non-empty JSON array of estimate objects"
        )
    return data


def _pool_components_probability(args: argparse.Namespace, components: dict[str, Any]) -> float | None:
    """Combine ensemble components into a probability.

    Routes through the Bayesian toolkit (log-odds / log-linear pooling with
    optional extremization and correlation discounting) when the chosen method
    is a Bayesian pooling method; otherwise keeps the historic weighted-average
    behaviour so existing ``weighted_ensemble`` workflows are unchanged.
    """

    method = str(getattr(args, "method", None) or "").strip().lower()
    extremize = getattr(args, "extremize", None)
    correlation = getattr(args, "correlation", None)
    pooled_method = _BAYES_POOL_METHODS.get(method)
    if pooled_method is None and extremize is None and correlation is None:
        return weighted_binary_probability(components)

    rows = _component_rows(components)
    if not rows:
        return weighted_binary_probability(components)

    # Default to log-odds pooling when extremize/correlation requested without a method.
    pooled_method = pooled_method or "log_odds_pool"
    correlation_matrix: Any = None
    if correlation is not None:
        text = str(correlation).strip()
        if text.lower() in {"estimate", "auto"}:
            correlation_matrix = "estimate"
        elif text:
            try:
                correlation_matrix = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"--correlation must be 'estimate' or a JSON matrix: {exc}")

    from forecasting.bayes_toolkit import combine_forecasts, ensure_industry_backends

    ensure_industry_backends()
    result = combine_forecasts(
        rows,
        method=pooled_method,
        extremize=float(extremize) if extremize is not None else 1.0,
        correlation_matrix=correlation_matrix,
    )
    return result.probability


def _probability_payload(args: argparse.Namespace, components: dict[str, Any] | None = None) -> Any:
    supplied = sum(
        1
        for value in (args.probability, args.numeric_value, args.distribution_json)
        if value is not None
    )
    if supplied > 1:
        raise SystemExit("use only one of --probability, --numeric-value, or --distribution-json")
    if args.numeric_value is not None:
        return args.numeric_value
    if args.distribution_json is not None:
        payload = json_loads(args.distribution_json, None)
        if not isinstance(payload, dict):
            raise SystemExit("--distribution-json must be a JSON object")
        return payload
    if args.probability is None and components:
        probability = _pool_components_probability(args, components)
        if probability is not None:
            return probability
    if args.probability is None:
        raise SystemExit(
            "forecast update requires --probability, --numeric-value, --distribution-json, "
            "or weighted --component-json"
        )
    return args.probability


def _probability_delta(previous: Any, current: Any) -> float | None:
    if isinstance(previous, (int, float)) and isinstance(current, (int, float)):
        return float(current) - float(previous)
    return None


def _question_delta(ledger: ForecastLedger, question_id: str) -> float | None:
    snapshots = ledger.list_snapshots(question_id)
    if len(snapshots) < 2:
        return None
    return _probability_delta(
        snapshots[-2].probability_or_distribution,
        snapshots[-1].probability_or_distribution,
    )


def _joined_arg(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return " ".join(str(item) for item in value).strip()
    return str(value).strip()
