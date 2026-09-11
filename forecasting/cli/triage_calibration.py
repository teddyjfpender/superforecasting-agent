"""``forecast lesson`` / ``lessons`` / ``calibration`` / ``triage`` — the calibration loop.

A carved CLI subcommand domain (the CLI-assembler pattern; see
:mod:`forecasting.cli.thesis`). These groups occupy three separate positions in
the registration order (``correction``/``resolver`` sit between ``lessons`` and
``calibration``; ``scoreboard`` sits between ``calibration`` and ``triage``), so
the domain exposes three hooks — :func:`register` (``lesson`` + ``lessons``,
contiguous), :func:`register_calibration`, and :func:`register_triage` — each
invoked at its pre-carve position, keeping ``forecast --help`` byte-identical.
The calibration printers and ``_run_triage_tool`` travelled with the handlers.

Shared helpers stay in ``core`` and are imported bare; ``_ledger`` is reached via
the call-time ``_core.`` hop.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from forecasting.cli import core as _core
from forecasting.cli.core import (
    CALIBRATION_LESSON_STATUSES,
    _format_metric,
    _json_arg,
    _print_cohort_scoreboard,
    _print_evidence_status,
    _print_operator_calibration,
    _recent_backtest_summaries,
    build_forecasting_evidence_status,
)


def _ledger(args: argparse.Namespace):
    """Hop to ``core._ledger`` at CALL time (monkeypatch discipline)."""

    return _core._ledger(args)


def register(forecast_sub: argparse._SubParsersAction) -> None:
    from forecasting.cli.learning_operations import register as register_learning_operations
    register_learning_operations(forecast_sub)
    """Register the ``lesson`` + ``lessons`` command groups (contiguous block)."""

    lesson_parser = forecast_sub.add_parser("lesson", help="Review and promote calibration lessons")
    lesson_sub = lesson_parser.add_subparsers(dest="lesson_command")
    lesson_create = lesson_sub.add_parser("create", help="Create a reviewed lesson from a JSON specification")
    lesson_create.add_argument("--spec-file", required=True)
    lesson_create.set_defaults(_forecast_handler=_cmd_lesson_create)
    lesson_list = lesson_sub.add_parser("list", help="List calibration lessons")
    lesson_list.add_argument("--scope-type")
    lesson_list.add_argument("--scope-ref")
    lesson_list.add_argument("--active", action="store_true")
    lesson_list.set_defaults(_forecast_handler=_cmd_lesson_list)
    lesson_status = lesson_sub.add_parser("status", help="Update calibration lesson status")
    lesson_status.add_argument("lesson_id")
    lesson_status.add_argument("--status", choices=sorted(CALIBRATION_LESSON_STATUSES), required=True)
    lesson_status.add_argument("--confidence", type=float)
    lesson_status.add_argument("--recommended-adjustment-json")
    lesson_status.add_argument("--supersedes")
    lesson_status.add_argument("--metadata-json")
    lesson_status.set_defaults(_forecast_handler=_cmd_lesson_status)
    lesson_synth = lesson_sub.add_parser(
        "synthesize",
        help="Derive signed over/under-confidence lessons from resolved forecasts (FDR-gated; advisory by default)",
    )
    lesson_synth.add_argument("--scope", default="all", help="'all', 'global', 'domain', or a specific domain name")
    lesson_synth.add_argument("--since", help="Only count resolutions on/after this ISO date (regime cutoff)")
    lesson_synth.add_argument("--recency-halflife", type=float, dest="recency_halflife_days", help="Exponential recency half-life (days)")
    lesson_synth.add_argument(
        "--mechanical",
        action="store_true",
        help="Opt in to bounded numeric logit-scale nudges (OFF by default → advisory text only)",
    )
    lesson_synth.add_argument("--no-activate", action="store_true", help="Leave every synthesized lesson tentative")
    lesson_synth.add_argument("--dry-run", action="store_true", help="Measure and decide without writing any lesson")
    lesson_synth.set_defaults(_forecast_handler=_cmd_lesson_synthesize)

    lessons_parser = forecast_sub.add_parser("lessons", help="List calibration lessons")
    lessons_parser.add_argument("--scope-type")
    lessons_parser.add_argument("--scope-ref")
    lessons_parser.add_argument("--active", action="store_true")
    lessons_parser.set_defaults(_forecast_handler=_cmd_lesson_list)
    lessons_sub = lessons_parser.add_subparsers(dest="lessons_command")
    lessons_audit = lessons_sub.add_parser("audit", help="Per-lesson coverage: is each learning actually being used? (in-scope / applied / dormant)")
    lessons_audit.add_argument("--json", action="store_true")
    lessons_audit.set_defaults(_forecast_handler=_cmd_lessons_audit)
    effectiveness = lessons_sub.add_parser("effectiveness", help="Measure outcome evidence for learning; distinguish compliance from skill")
    effectiveness.add_argument("--json", action="store_true")
    effectiveness.set_defaults(_forecast_handler=_cmd_lessons_effectiveness)
    explain = lessons_sub.add_parser("explain", help="Show in-scope lessons and recorded decisions for a forecast")
    explain.add_argument("id")
    explain.set_defaults(_forecast_handler=_cmd_lessons_explain)
    lessons_apply = lessons_sub.add_parser("apply", help="Compile a lesson into an enforceable hook rule (auto-detects the enforcement pattern)")
    lessons_apply.add_argument("lesson_id")
    lessons_apply.add_argument("--severity", choices=["warn", "error"], default="warn", help="WARN (observe, default) or ERROR (blocks at commit)")
    lessons_apply.set_defaults(_forecast_handler=_cmd_lessons_apply)


def register_calibration(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``calibration`` command group (its registration position)."""

    calibration_parser = forecast_sub.add_parser("calibration", help="Show calibration summary (add `status` for the readiness cockpit)")
    calibration_parser.add_argument(
        "mode", nargs="?", choices=["summary", "status"], default="summary",
        help="`status` = the readiness cockpit (calibration + live track record + readiness gaps + next actions)",
    )
    calibration_parser.add_argument("--domain")
    calibration_parser.add_argument(
        "--origin",
        dest="forecast_origin",
        choices=["live", "backtest", "imported_baseline"],
    )
    calibration_parser.add_argument(
        "--by-origin",
        action="store_true",
        help="Show combined, live, backtest, and imported-baseline calibration sections",
    )
    calibration_parser.add_argument("--horizon", help="Filter by horizon in days, e.g. 7 or 30-90")
    calibration_parser.add_argument("--all", action="store_true", help="Include calibration-ineligible scores")
    calibration_parser.add_argument(
        "--operator",
        action="store_true",
        help="Show the OPERATOR's own calibration (practice/drill estimates) instead of the system's",
    )
    calibration_parser.add_argument(
        "--window-days",
        type=int,
        dest="operator_window_days",
        help="Operator view: restrict to estimates scored within the trailing N days",
    )
    calibration_parser.add_argument(
        "--bias",
        action="store_true",
        help="Show the SIGNED over/under-confidence view (per scope: SCE, CI, status) instead of the unsigned summary",
    )
    calibration_parser.add_argument("--since", help="Bias view: only count resolutions on/after this ISO date")
    calibration_parser.add_argument(
        "--recency-halflife", type=float, dest="recency_halflife_days", help="Bias view: recency half-life (days)"
    )
    calibration_parser.add_argument(
        "--hierarchical",
        action="store_true",
        help="Hierarchical-Platt validation: held-out per-cohort Brier, global vs "
        "per-cohort-intercept (BLF A4). The flip evidence for FORECAST_HIERARCHICAL_CALIBRATION.",
    )
    calibration_parser.add_argument(
        "--min-cohort-n", type=int, dest="min_cohort_n",
        help="Hierarchical view: min resolved rows before a cohort earns an offset (default 40).",
    )
    calibration_parser.add_argument(
        "--folds", type=int, default=5, help="Hierarchical view: held-out CV folds (default 5).",
    )
    calibration_parser.add_argument(
        "--split-by-venue", action="store_true", dest="split_by_venue",
        help="Hierarchical view: refine cohorts to <origin>:<venue> where the data exists.",
    )
    calibration_parser.add_argument(
        "--json", action="store_true", dest="as_json", help="Emit the raw report as JSON.",
    )
    calibration_parser.set_defaults(_forecast_handler=_cmd_calibration)


def register_triage(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``triage`` command group (its registration position)."""

    triage_parser = forecast_sub.add_parser(
        "triage",
        help="Three-way relevance labeling on candidate readings (keep/skim/skip) before they become evidence",
    )
    triage_sub = triage_parser.add_subparsers(dest="triage_command")

    triage_label = triage_sub.add_parser("label", help="Auto-label candidate readings (three-way)")
    triage_label.add_argument("--question", dest="question_id")
    triage_label.add_argument(
        "--use-watched",
        action="store_true",
        help="Pull candidates from the question's watched sources (requires --question)",
    )
    triage_label.add_argument(
        "--candidates-json",
        help="JSON array of candidate readings [{title, summary?, source_type?, source?, url?, id?}]",
    )
    triage_label.add_argument("--rubric-ref", help="Explicit triage rubric id to apply")
    triage_label.add_argument("--model", help="Model id for the cheap auto-labeler (default $FORECAST_TRIAGE_MODEL)")
    triage_label.add_argument("--query", help="Optional query when pulling watched candidates")
    triage_label.add_argument("--limit", type=int, default=20)
    triage_label.add_argument(
        "--no-persist", action="store_true", help="Do not persist verdicts as triage_labels staging rows"
    )
    triage_label.set_defaults(_forecast_handler=_cmd_triage_label)

    triage_contested = triage_sub.add_parser(
        "contested", help="Route contested/boundary auto-labels to operator hand-labeling"
    )
    triage_contested.add_argument("--question", dest="question_id")
    triage_contested.add_argument(
        "--label-id", dest="label_ids", action="append", default=[], help="Specific triage_label id(s) to check"
    )
    triage_contested.add_argument(
        "--verifier-json",
        dest="verifier_json",
        help="Optional second-opinion labels [{candidate_ref|id, label}] to define disagreement",
    )
    triage_contested.add_argument("--disagreement-threshold", type=float)
    triage_contested.set_defaults(_forecast_handler=_cmd_triage_contested)

    triage_relabel = triage_sub.add_parser(
        "relabel", help="Record an operator expert label (adjudication) + ack its contested alert"
    )
    triage_relabel.add_argument("label_id", nargs="?")
    triage_relabel.add_argument("label", nargs="?", help="relevant_interesting | relevant_uninteresting | irrelevant")
    triage_relabel.add_argument(
        "--adjudications-json", help="JSON array [{label_id, label}] for bulk adjudication"
    )
    triage_relabel.set_defaults(_forecast_handler=_cmd_triage_relabel)

    triage_trust = triage_sub.add_parser("trust", help="Show the held-out trust gate for the auto-labeler")
    triage_trust.add_argument("--threshold", type=float)
    triage_trust.add_argument("--min-sample", type=int)
    triage_trust.set_defaults(_forecast_handler=_cmd_triage_trust)

    triage_set_rubric = triage_sub.add_parser("set-rubric", help="Store/replace a desk triage rubric for a scope")
    triage_set_rubric.add_argument("--scope-type", default="global")
    triage_set_rubric.add_argument("--scope-ref")
    triage_set_rubric.add_argument("--interesting", required=True, help="What counts as INTERESTING here (required)")
    triage_set_rubric.add_argument("--uninteresting", default="")
    triage_set_rubric.add_argument("--irrelevant", default="")
    triage_set_rubric.add_argument("--notes", default="")
    triage_set_rubric.set_defaults(_forecast_handler=_cmd_triage_set_rubric)

    triage_list_rubrics = triage_sub.add_parser("list-rubrics", help="List stored triage rubrics")
    triage_list_rubrics.add_argument("--scope-type")
    triage_list_rubrics.add_argument("--scope-ref")
    triage_list_rubrics.add_argument("--all", action="store_true", help="Include inactive rubrics")
    triage_list_rubrics.set_defaults(_forecast_handler=_cmd_triage_list_rubrics)


def _run_triage_tool(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    """Call the SAME triage tool action the agent uses and return the parsed result.

    The CLI triage group is a thin surface over ``forecast_ledger_tool`` so the
    triage logic (labeler wiring, contested routing, trust gate) lives in exactly
    one place. Prints the structured result and raises SystemExit(1) on a tool error.
    """
    from tools.forecasting_tool import forecast_ledger_tool

    payload = {**payload, "db": getattr(args, "db", None)}
    out = forecast_ledger_tool(payload)
    result = json.loads(out)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("error") or result.get("success") is False:
        raise SystemExit(1)
    return result


def _cmd_triage_label(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {
        "action": "triage_label",
        "persist": not getattr(args, "no_persist", False),
        "limit": getattr(args, "limit", 20),
    }
    if getattr(args, "question_id", None):
        payload["question_id"] = args.question_id
    if getattr(args, "use_watched", False):
        payload["use_watched"] = True
    if getattr(args, "rubric_ref", None):
        payload["rubric_ref"] = args.rubric_ref
    if getattr(args, "model", None):
        payload["model"] = args.model
    if getattr(args, "query", None):
        payload["query"] = args.query
    if getattr(args, "candidates_json", None):
        try:
            payload["candidates"] = json.loads(args.candidates_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--candidates-json is not valid JSON: {exc}")
    _run_triage_tool(args, payload)


def _cmd_triage_contested(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {"action": "triage_contested"}
    if getattr(args, "question_id", None):
        payload["question_id"] = args.question_id
    if getattr(args, "label_ids", None):
        payload["label_ids"] = args.label_ids
    if getattr(args, "disagreement_threshold", None) is not None:
        payload["disagreement_threshold"] = args.disagreement_threshold
    if getattr(args, "verifier_json", None):
        try:
            payload["verifier_labels"] = json.loads(args.verifier_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--verifier-json is not valid JSON: {exc}")
    _run_triage_tool(args, payload)


def _cmd_triage_relabel(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {"action": "relabel_route"}
    if getattr(args, "adjudications_json", None):
        try:
            payload["adjudications"] = json.loads(args.adjudications_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--adjudications-json is not valid JSON: {exc}")
    elif getattr(args, "label_id", None) and getattr(args, "label", None):
        payload["label_id"] = args.label_id
        payload["label"] = args.label
    else:
        raise SystemExit("forecast triage relabel needs LABEL_ID LABEL (or --adjudications-json)")
    _run_triage_tool(args, payload)


def _cmd_triage_trust(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {"action": "triage_trust"}
    if getattr(args, "threshold", None) is not None:
        payload["threshold"] = args.threshold
    if getattr(args, "min_sample", None) is not None:
        payload["min_sample"] = args.min_sample
    _run_triage_tool(args, payload)


def _cmd_triage_set_rubric(args: argparse.Namespace) -> None:
    rubric = {
        "interesting_criteria": args.interesting,
        "uninteresting_criteria": getattr(args, "uninteresting", "") or "",
        "irrelevant_criteria": getattr(args, "irrelevant", "") or "",
        "notes": getattr(args, "notes", "") or "",
    }
    payload = {
        "action": "set_label_rubric",
        "scope_type": getattr(args, "scope_type", "global") or "global",
        "rubric": rubric,
    }
    if getattr(args, "scope_ref", None):
        payload["scope_ref"] = args.scope_ref
    _run_triage_tool(args, payload)


def _cmd_triage_list_rubrics(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {"action": "list_label_rubrics"}
    if getattr(args, "scope_type", None):
        payload["scope_type"] = args.scope_type
    if getattr(args, "scope_ref", None):
        payload["scope_ref"] = args.scope_ref
    if getattr(args, "all", False):
        payload["active_only"] = False
    _run_triage_tool(args, payload)


def _cmd_lesson_list(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_calibration_lessons(
        scope_type=args.scope_type,
        scope_ref=args.scope_ref,
        active_only=args.active,
    )
    if not rows:
        print("No calibration lessons found.")
        return
    print("ID             Status      Scope                  Confidence  Lesson")
    for row in rows:
        scope = f"{row['scope_type']}:{row['scope_ref'] or '*'}"
        confidence = "-" if row["confidence"] is None else f"{row['confidence']:.2f}"
        print(f"{row['id']:<14} {row['status']:<11} {scope:<22} {confidence:<11} {row['lesson']}")


def _cmd_lesson_status(args: argparse.Namespace) -> None:
    adjustment = (
        _json_arg(args.recommended_adjustment_json, "recommended-adjustment-json")
        if args.recommended_adjustment_json is not None
        else None
    )
    row = _ledger(args).update_calibration_lesson(
        args.lesson_id,
        status=args.status,
        confidence=args.confidence,
        recommended_adjustment=adjustment,
        supersedes_lesson_id=args.supersedes,
        metadata=_json_arg(args.metadata_json, "metadata-json") if getattr(args, "metadata_json", None) is not None else None,
    )
    print(f"calibration_lesson: {row['id']}")
    print(f"status: {row['status']}")
    print(f"confidence: {row['confidence'] if row['confidence'] is not None else '-'}")


def _cmd_lesson_synthesize(args: argparse.Namespace) -> None:
    results = _ledger(args).synthesize_bias_lessons(
        scope=args.scope,
        since=args.since,
        recency_halflife_days=args.recency_halflife_days,
        enable_mechanical=args.mechanical,
        activate=not args.no_activate,
        dry_run=args.dry_run,
    )
    if not results:
        print("No scopes with scored forecasts to assess.")
        return
    mode = "DRY-RUN" if args.dry_run else ("MECHANICAL" if args.mechanical else "advisory")
    print(f"calibration-bias synthesis ({mode}); FDR q=0.10 across {len(results)} scope(s):")
    for r in results:
        scope = f"{r['scope_type']}:{r['scope_ref'] or '*'}"
        line = f"  {scope:<22} {r['status']:<20} ess={r['ess']:.1f} n={r['n']}"
        if r.get("sce_shrunk") is not None:
            line += f" sce={r['sce_shrunk'] * 100:+.1f}pp"
        if r.get("ci_low") is not None:
            line += f" ci=[{r['ci_low'] * 100:+.1f},{r['ci_high'] * 100:+.1f}]pp"
        line += f" bh={'yes' if r.get('bh_survived') else 'no'} -> {r.get('disposition', {}).get('lesson_status', '-')}"
        print(line)
        action = r.get("action", {})
        if action.get("written"):
            tail = f", retired {action['retired']}" if action.get("retired") else ""
            print(f"      wrote {action['lesson_id']} ({action['lesson_status']}){tail}")
        elif action.get("retired"):
            print(f"      retired {action['retired']}")


def _print_calibration_bias(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    if args.domain:
        scopes = [("domain", args.domain)]
    else:
        scopes = [("global", None)] + [("domain", d) for d in ledger._domains_with_scores()]
    print("Signed calibration bias (negative=under-confident, positive=over-confident):")
    print(f"{'scope':<22} {'status':<20} {'ess':>6} {'n':>4} {'sce(pp)':>9} {'ci(pp)':>18}  note")
    for scope_type, scope_ref in scopes:
        rep = ledger.calibration_bias(
            domain=scope_ref,
            scope_type=scope_type,
            since=args.since,
            recency_halflife_days=args.recency_halflife_days,
        )
        scope = f"{scope_type}:{scope_ref or '*'}"
        sce = "-" if rep["sce_shrunk"] is None else f"{rep['sce_shrunk'] * 100:+.1f}"
        ci = (
            "-"
            if rep["ci_low"] is None
            else f"[{rep['ci_low'] * 100:+.1f},{rep['ci_high'] * 100:+.1f}]"
        )
        if rep["status"] == "insufficient_evidence":
            need = max(1, int(rep["ess_min"] - rep["ess"]) + 1)
            note = f"need ~{need} more resolution(s)"
        elif rep["status"] == "calibrated":
            note = "within noise — no direction"
        else:
            note = (rep.get("advisory_text") or "")[:70]
        print(f"{scope:<22} {rep['status']:<20} {rep['ess']:>6.1f} {rep['n']:>4} {sce:>9} {ci:>18}  {note}")


def _print_calibration_cockpit(args: argparse.Namespace) -> None:
    """The `forecast calibration status` cockpit: makes claim_live_superforecasting
    ACTIONABLE in one view — the live track record + readiness requirements (passed
    AND failing) + the concrete next actions/commands to close each gap."""
    ledger = _ledger(args)
    _rows, summaries = _recent_backtest_summaries(ledger, last=20, dataset=None)
    evidence_status = build_forecasting_evidence_status(ledger, summaries)
    verdict = evidence_status.get("verdict")
    print("=== calibration / readiness cockpit ===")
    print(f"claim_live_superforecasting: {'SUPPORTED' if verdict == 'pass' else 'NOT YET — see gaps below'}")
    _print_evidence_status(evidence_status, include_passed=True)
    if not evidence_status.get("gaps"):
        print("\nAll readiness requirements met.")
    else:
        print("\nClose the next_actions above; `forecast readiness` shows the full backtest breakdown.")


def _cmd_lessons_audit(args: argparse.Namespace) -> None:
    rows = _ledger(args).lesson_coverage()
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No active calibration lessons.")
        return
    print("Lesson coverage — is each learning actually being used?")
    print(f"{'Lesson':<15} {'Kind':<9} {'Scope':<22} {'InScope':<8} {'Applied':<8} Status")
    for r in rows:
        if r["dormant"]:
            status = "DORMANT — never in scope since creation"
        elif not r["enforceable"]:
            status = "advisory — prose only, will NOT bite"
        elif r.get("unverified_count"):
            status = f"{r['unverified_count']} historical application(s) lack verified decisions"
        elif r["application_rate"] < 1.0:
            status = f"applied {r['application_rate'] * 100:.0f}% of in-scope commits"
        else:
            status = "verified rule compliance"
        print(f"{r['lesson_id']:<15} {r['kind']:<9} {r['scope']:<22} {r['in_scope_count']:<8} {r['applied_count']:<8} {status}")
    dormant = [r for r in rows if r["dormant"]]
    advisory = [r for r in rows if not r["enforceable"]]
    if dormant:
        print(f"\n{len(dormant)} DORMANT lesson(s) — never encountered an in-scope forecast; retire or re-scope.")
    if advisory:
        print(f"{len(advisory)} ADVISORY lesson(s) — prose only; compile to a `rule` so they enforce instead of decorate.")


def _cmd_lessons_apply(args: argparse.Namespace) -> None:
    result = _ledger(args).apply_lesson(args.lesson_id, severity=args.severity)
    if not result["applied"]:
        print(f"{args.lesson_id}: not applied — {result['reason']}.")
        print("  Declare `enforcement_pattern` in the lesson's recommended_adjustment, or use a recognized process_rule.")
        return
    import json as _json

    print(f"{args.lesson_id}: applied pattern '{result['pattern']}' at {result['severity'].upper()} — it now enforces at commit for its scope.")
    print(f"  check: {_json.dumps(result['check'])}")


def _print_hierarchical_calibration(args: argparse.Namespace) -> None:
    """Held-out per-cohort Brier: global vs hierarchical Platt (BLF A4).

    READ-ONLY. The numbers here are the operator's evidence for flipping
    ``FORECAST_HIERARCHICAL_CALIBRATION`` on: where a cohort's base-rate skew makes
    a per-cohort intercept beat the single global map on OUT-OF-SAMPLE Brier."""

    ledger = _ledger(args)
    report = ledger.validate_hierarchical_calibration(
        min_cohort_n=getattr(args, "min_cohort_n", None),
        folds=getattr(args, "folds", 5),
        split_by_venue=getattr(args, "split_by_venue", False),
        since=getattr(args, "since", None),
        recency_halflife_days=getattr(args, "recency_halflife_days", None),
    )
    if getattr(args, "as_json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    print("hierarchical Platt calibration — held-out per-cohort Brier (global vs per-cohort intercept)")
    print(f"  rows={report.get('n', 0)}  folds={report.get('folds')}  min_cohort_n={report.get('min_cohort_n')}")
    for note in report.get("notes", []):
        print(f"  note: {note}")
    if report.get("lambda") is not None:
        ceiling = " [pinned at grid ceiling — offsets unsupported]" if report.get("lambda_at_ceiling") else ""
        print(f"  ridge lambda (LOO-CV): {report['lambda']:g}{ceiling}")
    cohorts = report.get("cohorts") or {}
    if cohorts:
        print("  cohort                             n   identity    global   hierarch    delta  helps  offset")
        for name, row in cohorts.items():
            print(
                f"  {name:<32} {row['n']:>5.0f}  {row['brier_identity']:>8.4f} "
                f"{row['brier_global']:>8.4f} {row['brier_hierarchical']:>9.4f} "
                f"{row['delta_brier_global_minus_hier']:>+8.4f}  "
                f"{'yes' if row.get('materially_helps') else ' no':>5}  "
                f"{'yes' if row['has_offset'] else ' no':>5}"
            )
    overall = report.get("overall") or {}
    if overall:
        print(
            f"  overall: global={overall['brier_global']:.4f} "
            f"hierarchical={overall['brier_hierarchical']:.4f} "
            f"delta={overall['delta_brier_global_minus_hier']:+.4f} "
            f"(material bar {report.get('material_brier_delta', 0.001)})"
        )
    rec = report.get("recommendation", "insufficient_data")
    improved = report.get("large_cohorts_improved")
    tail = f" ({improved} offset-cohort(s) materially improve)" if improved is not None else ""
    print(f"  recommendation: {rec}{tail}")
    if rec == "flip_on":
        print("  → set FORECAST_HIERARCHICAL_CALIBRATION=on to activate the per-cohort intercepts.")
    elif rec == "marginal":
        print("  → gain is inside the noise; keep global (do not flip) until it clears the material bar.")


def _cmd_calibration(args: argparse.Namespace) -> None:
    if getattr(args, "hierarchical", False):
        _print_hierarchical_calibration(args)
        return
    if getattr(args, "operator", False):
        _print_operator_calibration(
            _ledger(args),
            window_days=getattr(args, "operator_window_days", None),
        )
        return
    if getattr(args, "mode", "summary") == "status":
        _print_calibration_cockpit(args)
        return
    if getattr(args, "bias", False):
        _print_calibration_bias(args)
        return
    if args.by_origin and args.forecast_origin:
        raise SystemExit("forecast calibration --by-origin cannot be combined with --origin")
    if args.by_origin:
        for label, origin in (
            ("combined", None),
            ("live", "live"),
            ("backtest", "backtest"),
            ("imported_baseline", "imported_baseline"),
        ):
            summary = _ledger(args).calibration_summary(
                domain=args.domain,
                forecast_origin=origin,
                horizon=args.horizon,
                calibration_eligible=None if args.all else True,
            )
            _print_calibration_summary(summary, label=label)
        return
    ledger = _ledger(args)
    summary = ledger.calibration_summary(
        domain=args.domain,
        forecast_origin=args.forecast_origin,
        horizon=args.horizon,
        calibration_eligible=None if args.all else True,
    )
    # Cohort scoreboard FIRST — the honest, un-pooled default read. Only on the
    # unfiltered global view (a domain/origin/horizon filter is already a slice).
    if not (args.domain or args.forecast_origin or args.horizon):
        try:
            _print_cohort_scoreboard(ledger.cohort_scoreboard())
        except Exception:
            pass
    _print_calibration_summary(summary)
    # Plain-language read (S7): the measured signed-bias advisory teaching text for
    # this scope, then the active lessons CORRECTING forecasts here + whether they
    # are biting. Best-effort — a thin/legacy ledger simply prints nothing.
    try:
        report = ledger.calibration_bias(domain=args.domain)
        advisory = report.get("advisory_text")
        if advisory:
            print(f"advisory: {advisory}")
    except Exception:
        pass
    try:
        lessons = ledger.calibration_correcting_lessons(domain=args.domain)
    except Exception:
        lessons = []
    if lessons:
        print("lessons_correcting_this:")
        for row in lessons:
            cov = row.get("coverage") or {}
            adj = row.get("recommended_adjustment") or {}
            adj_bits = [
                f"{k}={v}"
                for k, v in adj.items()
                if k in ("probability_delta", "logit_shift", "logit_scale")
            ]
            adj_str = f" [{', '.join(adj_bits)}]" if adj_bits else ""
            dormant = " DORMANT" if row.get("dormant") else ""
            print(
                f"  {row['scope']}: {(row.get('lesson') or '')[:70]}{adj_str} "
                f"(applied {cov.get('applied_count', 0)}/{cov.get('in_scope_count', 0)}){dormant}"
            )


def _print_calibration_summary(summary: dict[str, Any], *, label: str | None = None) -> None:
    if label is not None:
        print(f"origin: {label}")
    print(f"count: {summary['count']}")
    mean = summary["mean_brier"]
    print(f"mean_brier: {mean:.6f}" if mean is not None else "mean_brier: -")
    mean_log = summary["mean_log_score"]
    print(f"mean_log_score: {mean_log:.6f}" if mean_log is not None else "mean_log_score: -")
    sharpness = summary["mean_sharpness"]
    print(f"mean_sharpness: {sharpness:.6f}" if sharpness is not None else "mean_sharpness: -")
    movement = summary.get("mean_probability_movement_before_close")
    abs_movement = summary.get("mean_abs_probability_movement_before_close")
    print(f"probability_movement_n: {summary.get('probability_movement_count', 0)}")
    print(
        f"mean_probability_movement_before_close: {movement:+.6f}"
        if movement is not None
        else "mean_probability_movement_before_close: -"
    )
    print(
        f"mean_abs_probability_movement_before_close: {abs_movement:.6f}"
        if abs_movement is not None
        else "mean_abs_probability_movement_before_close: -"
    )
    components = summary.get("ensemble_component_contributions") or []
    if components:
        print("ensemble_component_contributions:")
        for row in components:
            print(
                f"  {row['name']}: n={row['count']} "
                f"mean_contribution={_format_metric(row.get('mean_contribution'))} "
                f"weight_share={_format_metric(row.get('mean_weight_share'))} "
                f"mean_probability={_format_metric(row.get('mean_probability'))}"
            )
    question_types = summary.get("question_type_breakdown") or []
    if question_types:
        print("question_type_breakdown:")
        for row in question_types:
            print(
                f"  {row['question_type']}: n={row['count']} "
                f"brier_n={row.get('brier_count', 0)} "
                f"mean_brier={_format_metric(row.get('mean_brier'))} "
                f"mean_proper_score={_format_metric(row.get('mean_proper_score'))} "
                f"mean_log_score={_format_metric(row.get('mean_log_score'))}"
            )
    ece = summary.get("expected_calibration_error")
    mce = summary.get("max_calibration_error")
    curve = summary.get("calibration_curve") or []
    populated = [row for row in curve if row["count"]]
    print(f"expected_calibration_error: {_format_metric(ece)}")
    print(f"max_calibration_error: {_format_metric(mce)}")
    print(f"calibration_curve_sample_count: {summary.get('calibration_curve_sample_count', 0)}")
    if populated:
        print("calibration_curve (P(yes): predicted vs observed):")
        for row in populated:
            print(
                f"  {row['bucket']}: n={row['count']} "
                f"predicted={_format_metric(row['mean_predicted'])} "
                f"observed={_format_metric(row['observed_frequency'])} "
                f"gap={_format_metric(row['calibration_gap'])} {row['sample_status']}"
            )
    print("buckets:")
    if not summary["buckets"]:
        print("  none")
    else:
        for bucket in summary["buckets"]:
            print(
                f"  {bucket['bucket']}: n={bucket['count']} "
                f"mean_brier={_format_metric(bucket['mean_brier'])} {bucket['sample_status']}"
            )
    trend = summary.get("calibration_trend") or {}
    windows = trend.get("windows") or []
    if windows:
        print(f"calibration_trend ({trend.get('direction', 'insufficient')}):")
        for window in windows:
            print(
                f"  {window['period']}: n={window['n']} "
                f"mean_brier={_format_metric(window.get('brier'))} "
                f"sce={_format_metric(window.get('sce'))}"
            )
    if label is not None:
        print()


def _cmd_lessons_explain(args: argparse.Namespace) -> None:
    from forecasting.learning import active_lessons_for_question, _in_scope_lessons, lesson_applicability

    ledger = _ledger(args)
    question = ledger.get_question(_core._resolve_question_id(ledger, args.id))
    snapshot = ledger.get_current_snapshot(question.id)
    print(json.dumps({
        "question_id": question.id,
        "active_lessons": active_lessons_for_question(ledger, question),
        "conditional_lessons": [{"lesson_id": l["id"], "conditions": l["recommended_adjustment"].get("applicability"),
            "reason": lesson_applicability(l, question, ledger=ledger)[1]} for l in _in_scope_lessons(ledger, question)
            if not lesson_applicability(l, question, ledger=ledger)[0]],
        "forecast_id": snapshot.forecast_id if snapshot else None,
        "recorded_decisions": (snapshot.metadata or {}).get("lesson_decisions", []) if snapshot else [],
        "interpretation": "Recorded application is process evidence, not evidence of improved accuracy. Historical snapshots without decisions are unverified.",
    }, indent=2))


def _cmd_lessons_effectiveness(args):
    from forecasting.learning_evaluation import learning_effectiveness
    report = learning_effectiveness(_ledger(args))
    if args.json:
        print(json.dumps(report, indent=2))
        return
    counts = report["counts"]
    print("Learning benefit: not established")
    print(f"Scored distinct questions: {counts.get('scored_distinct_questions', 0)}")
    print(f"Verified decision snapshots: {counts.get('verified_decision_snapshots', 0)}; historical unverified: {counts.get('historical_unverified_snapshots', 0)}")
    print(f"Numeric replay pairs: {report['numeric_replay']['pairs']} (self-reported inputs; diagnostic only)")
    for row in report["observational_cohorts"]:
        print(f"{row['domain']} | {row['score_rule']} [{row['units']}] | lesson refs={row['lesson_refs_recorded']} | n={row['questions']} | mean={row['mean_score']:.6f}")
    print(report["interpretation"])
    print("Next: " + report["next_action"])


def _cmd_lesson_create(args):
    from pathlib import Path
    spec = json.loads(Path(args.spec_file).read_text(encoding="utf-8"))
    print(json.dumps(_ledger(args).create_calibration_lesson(**spec), indent=2))
