"""``forecast refresh`` / ``rerun`` / ``cycle`` / ``run-all`` / ``autopilot`` —
the autonomous reforecast loop.

A carved CLI subcommand domain (the CLI-assembler pattern; see
:mod:`forecasting.cli.thesis`). These groups occupy four separate positions in
the registration order, so the domain exposes four hooks — :func:`register_refresh`,
:func:`register_rerun`, :func:`register_cycle`, and :func:`register` (``run-all`` +
``autopilot``, contiguous) — each invoked at its pre-carve position, keeping
``forecast --help`` byte-identical. The autopilot policy resolvers, the rerun-job
printer/status, ``_order_theses`` and ``_run_one`` travelled with the handlers.

Shared helpers stay in ``core`` and are imported bare; ``_ledger`` is reached via
the call-time ``_core.`` hop. ``_cmd_agent`` and ``_build_cycle_reforecast_runner``
STAY in core (used by ``register_cli`` and the warning-runner builders) and are
imported bare — this preserves the ``_run_update_agent`` façade patch, which they
reach internally. ``core`` re-binds ``_cmd_rerun`` at its bottom for surface
parity (``tests/forecasting/test_reforecast_jobs`` calls it directly).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from forecasting.cli import core as _core
from forecasting.cli.core import (
    ForecastLedger,
    _build_cycle_reforecast_runner,
    _cmd_agent,
    _resolve_question_id,
    _write_analyst_brief,
)


def _ledger(args: argparse.Namespace):
    """Hop to ``core._ledger`` at CALL time (monkeypatch discipline)."""
    return _core._ledger(args)


def register_refresh(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``refresh`` command group (its registration position)."""

    refresh_parser = forecast_sub.add_parser(
        "refresh",
        help="Pull latest watched-source readings + re-estimate, then auto-commit a new live snapshot",
    )
    refresh_parser.add_argument("id")
    refresh_parser.add_argument(
        "--agent",
        action="store_true",
        help="Run the full LLM update stage instead of the deterministic re-pool",
    )
    refresh_parser.add_argument(
        "--no-commit",
        dest="commit",
        action="store_false",
        default=True,
        help="Preview the re-estimate without importing evidence or committing a snapshot",
    )
    refresh_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias for previewing: fetch + re-estimate but write nothing",
    )
    refresh_parser.add_argument(
        "--carry-forward",
        action="store_true",
        help="Skip the re-pool; carry the prior probability forward (flags need for --agent / manual re-reasoning)",
    )
    refresh_parser.add_argument("--extremize", type=float, default=1.0)
    refresh_parser.add_argument(
        "--correlation",
        help="Pass 'estimate' to correlation-adjust pooling weights when sources overlap",
    )
    refresh_parser.add_argument("--concurrency", type=int, default=4)
    refresh_parser.add_argument("--now")
    refresh_parser.add_argument("--json", action="store_true")
    # --agent delegation reuses the protocol agent runner (forecast agent --stage update).
    refresh_parser.add_argument("--model")
    refresh_parser.add_argument("--provider")
    refresh_parser.add_argument("--max-iterations", type=int, default=12)
    refresh_parser.set_defaults(_forecast_handler=_cmd_refresh)



def register_rerun(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``rerun`` command group (its registration position)."""

    rerun_parser = forecast_sub.add_parser(
        "rerun",
        help=(
            "Mass LLM re-run: run the FULL formal forecast flow (fresh research + "
            "VOI audit + base rate + gated commit + auto-quorum where indicated) for "
            "explicit question ids, DETACHED so a keypress can start many multi-minute "
            "sessions. Subcommands: `rerun <id> [<id> ...]` (start), `rerun status "
            "<run-id>`."
        ),
    )
    rerun_parser.add_argument(
        "ids",
        nargs="*",
        help="Question ids to reforecast; or `status <run-id>` to poll a run.",
    )
    rerun_parser.add_argument(
        "--agent",
        action="store_true",
        help="Explicit opt-in flag (the mass re-run is always the LLM agent flow); "
        "accepted for parity with `cycle run --agent`.",
    )
    rerun_parser.add_argument("--model", help="Model id for the reforecast agent.")
    rerun_parser.add_argument("--provider", help="Provider for the reforecast agent.")
    rerun_parser.add_argument(
        "--max-iterations", dest="max_iterations", type=int, default=12,
        help="Max agent iterations per question (default 12).",
    )
    rerun_parser.add_argument(
        "--wait",
        action="store_true",
        help="Run synchronously and print the result (default: background job + run-id).",
    )
    rerun_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    rerun_parser.set_defaults(_forecast_handler=_cmd_rerun)


def register_cycle(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``cycle`` command group (its registration position)."""

    cycle_parser = forecast_sub.add_parser("cycle", help="Run the closed-loop forecast cycle")
    cycle_sub = cycle_parser.add_subparsers(dest="cycle_command")
    cycle_run = cycle_sub.add_parser(
        "run",
        help="Run the full due cycle: reviews -> reconcile alerts -> re-aggregate theses -> synthesize lessons",
    )
    cycle_run.add_argument("--due", action="store_true", help="Run due reviews (the default)")
    cycle_run.add_argument("--now")
    cycle_run.add_argument("--no-thesis-aggregate", action="store_true", help="Skip re-aggregating theses")
    cycle_run.add_argument("--no-reconcile", action="store_true", help="Skip alert reconciliation")
    cycle_run.add_argument("--no-synthesize-lessons", action="store_true", help="Never synthesize lessons this run")
    cycle_run.add_argument("--synthesize-lessons", action="store_true", help="Force lesson synthesis every run")
    cycle_run.add_argument("--agent", action="store_true", help="Autonomously re-forecast the questions this sweep flags via the LLM update stage (runs before thesis + lesson phases so they see fresh snapshots)")
    cycle_run.add_argument("--model", help="--agent: model id for the reforecast agent")
    cycle_run.add_argument("--provider", help="--agent: provider for the reforecast agent")
    cycle_run.add_argument("--max-iterations", type=int, default=12, help="--agent: max agent iterations per question")
    cycle_run.add_argument("--max-questions", type=int, default=None, help="--agent: cap how many questions to reforecast in one sweep")
    cycle_run.add_argument("--force", action="store_true", help="--agent: reforecast even when the pipeline update stage is gated")
    cycle_run.set_defaults(_forecast_handler=_cmd_cycle_run)


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``run-all`` + ``autopilot`` command groups (contiguous block)."""

    run_all_parser = forecast_sub.add_parser(
        "run-all",
        help="Refresh every active member forecast, then aggregate every active thesis",
    )
    run_all_parser.add_argument("--limit", type=int, default=None, help="Cap the number of member forecasts run in phase 1")
    run_all_parser.add_argument("--rho", type=float, default=0.4)
    run_all_parser.add_argument("--dry-run", action="store_true", help="Print what would run without changing anything")
    run_all_parser.set_defaults(_forecast_handler=_cmd_run_all)

    autopilot_parser = forecast_sub.add_parser(
        "autopilot",
        help="Wire watched sources, schedules, materiality, and update proposals",
    )
    autopilot_sub = autopilot_parser.add_subparsers(dest="autopilot_command")
    autopilot_enable = autopilot_sub.add_parser("enable", help="Enable autonomous forecast maintenance")
    autopilot_enable.add_argument("id")
    autopilot_enable.add_argument("--source", action="append", default=[])
    autopilot_enable.add_argument("--sources", help="Comma-separated watched sources")
    autopilot_enable.add_argument("--required-source", action="append", default=[])
    autopilot_enable.add_argument("--required-sources", help="Comma-separated watched sources that block refresh if unavailable")
    autopilot_enable.add_argument("--cadence", required=True)
    autopilot_enable.add_argument("--next-run-at")
    autopilot_enable.add_argument(
        "--mode",
        choices=["propose", "auto-commit", "alert-only"],
        default="propose",
    )
    autopilot_enable.add_argument("--materiality-threshold", action="append", default=[])
    autopilot_enable.add_argument("--max-auto-delta", type=float)
    autopilot_enable.add_argument("--min-sources-for-auto-commit", type=int)
    autopilot_enable.add_argument("--notify")
    autopilot_enable.add_argument("--quiet-if-unchanged", action="store_true")
    autopilot_enable.add_argument("--created-by")
    autopilot_enable.add_argument("--allow-missing-resolution-source", action="store_true")
    autopilot_enable.set_defaults(_forecast_handler=_cmd_autopilot_enable)
    autopilot_disable = autopilot_sub.add_parser("disable", help="Disable active autopilot policy for a question")
    autopilot_disable.add_argument("id")
    autopilot_disable.set_defaults(_forecast_handler=_cmd_autopilot_disable)
    autopilot_status = autopilot_sub.add_parser("status", help="Show autopilot policy state")
    autopilot_status.add_argument("id")
    autopilot_status.set_defaults(_forecast_handler=_cmd_autopilot_status)
    autopilot_run = autopilot_sub.add_parser("run", help="Run autopilot source checks and proposal generation")
    autopilot_run.add_argument("id")
    autopilot_run.add_argument("--now")
    autopilot_run.add_argument("--trigger-reason", default="manual")
    autopilot_run.add_argument("--proposed-probability", type=float)
    autopilot_run.add_argument("--rationale")
    autopilot_run.set_defaults(_forecast_handler=_cmd_autopilot_run)
    autopilot_history = autopilot_sub.add_parser("history", help="Show autopilot run history")
    autopilot_history.add_argument("id")
    autopilot_history.add_argument("--limit", type=int, default=20)
    autopilot_history.set_defaults(_forecast_handler=_cmd_autopilot_history)
    autopilot_proposals = autopilot_sub.add_parser("proposals", help="List forecast update proposals")
    autopilot_proposals.add_argument("id", nargs="?")
    autopilot_proposals.add_argument("--all", action="store_true")
    autopilot_proposals.set_defaults(_forecast_handler=_cmd_autopilot_proposals)
    autopilot_approve = autopilot_sub.add_parser("approve", help="Approve a pending forecast update proposal")
    autopilot_approve.add_argument("proposal_id")
    autopilot_approve.add_argument("--reviewed-by")
    autopilot_approve.set_defaults(_forecast_handler=_cmd_autopilot_approve)
    autopilot_reject = autopilot_sub.add_parser("reject", help="Reject a pending forecast update proposal")
    autopilot_reject.add_argument("proposal_id")
    autopilot_reject.add_argument("--reviewed-by")
    autopilot_reject.set_defaults(_forecast_handler=_cmd_autopilot_reject)


def _cmd_rerun(args: argparse.Namespace) -> None:
    """Dispatch `forecast rerun …` — start a detached mass reforecast over explicit
    ids, or `rerun status <run-id>` to poll one.

    The detached job runs :func:`run_forecast_chain` directly per question (it does
    NOT shell back to the CLI), so this handler only validates + enqueues; the full
    formal flow and every gate live in the shared chain."""

    ids = [str(i).strip() for i in (args.ids or []) if str(i).strip()]
    if ids and ids[0] == "status":
        _rerun_status(args, ids[1:])
        return
    if not ids:
        print("forecast rerun — mass LLM re-run over explicit question ids")
        print("usage:")
        print("  forecast rerun <id> [<id> ...] [--model M] [--max-iterations N] [--wait]")
        print("  forecast rerun status <run-id>")
        return

    from forecasting.jobs.types.reforecast import (
        DEFAULT_MAX_BATCH,
        read_job,
        start_job,
        validate_reforecast_ids,
    )
    from hermes_cli.config import cfg_get, load_config_readonly

    ledger = _ledger(args)
    try:
        max_batch = int(
            cfg_get(load_config_readonly(), "forecasting", "reforecast", "max_batch", default=DEFAULT_MAX_BATCH)
            or DEFAULT_MAX_BATCH
        )
    except (TypeError, ValueError):
        max_batch = DEFAULT_MAX_BATCH

    accepted, errors = validate_reforecast_ids(ledger, ids, max_batch=max_batch)
    if errors:
        raise SystemExit("forecast rerun: " + "; ".join(errors))

    spec = {
        "question_ids": accepted,
        "db": str(ledger.db_path) if getattr(ledger, "db_path", None) else getattr(args, "db", None),
        "model": args.model,
        "provider": args.provider,
        "max_iterations": int(getattr(args, "max_iterations", None) or 12),
        "triggered_by": "desk_mass_agent",
    }
    run_id = start_job(spec, wait=bool(args.wait))

    if args.wait:
        _print_rerun_job(read_job(run_id), json_output=args.json)
        return
    if args.json:
        print(json.dumps({"run_id": run_id, "status": "queued", "total": len(accepted)}, indent=2))
        return
    print(f"reforecast run started: {run_id} ({len(accepted)} question(s))")
    print(f"  poll with:  forecast rerun status {run_id}")


def _rerun_status(args: argparse.Namespace, rest: list[str]) -> None:
    from forecasting.jobs.types.reforecast import list_jobs, read_job

    if not rest:
        jobs = list_jobs()
        if args.json:
            print(json.dumps(jobs, indent=2))
            return
        if not jobs:
            print("No reforecast runs yet. Start one with `forecast rerun <id> [<id> ...]`.")
            return
        print("Run            Status   Done/Total  Updated")
        for job in jobs:
            done = f"{job.get('done_count', 0)}/{job.get('total', 0)}"
            print(f"{job['run_id']:<14} {job['status']:<8} {done:<11} {job.get('updated_at', '-')}")
        return
    try:
        job = read_job(rest[0])
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
    _print_rerun_job(job, json_output=args.json)


def _print_rerun_job(job: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(job, indent=2))
        return
    print(f"reforecast run {job['run_id']}: {job['status']}")
    print(f"  progress: {job.get('done_count', 0)}/{job.get('total', 0)}")
    current = job.get("current")
    if current:
        print(f"  current:  {current.get('question_id')} — {current.get('stage')}")
    if job.get("error"):
        print(f"  error:    {job['error']}")
    quorums = sum(1 for r in (job.get("results") or []) if r.get("quorum_autorun"))
    if quorums:
        print(f"  quorums started: {quorums}")
    for r in job.get("results") or []:
        state = "error" if r.get("error") else ("committed" if r.get("committed") else "no-commit")
        line = f"    {r.get('question_id')}: {state}"
        if r.get("forecast_id"):
            line += f" ({r['forecast_id']})"
        if r.get("error"):
            line += f" — {r['error']}"
        elif not r.get("committed") and r.get("update_blockers"):
            line += f" — gated: {', '.join(r['update_blockers'])}"
        print(line)


def _cmd_cycle_run(args: argparse.Namespace) -> None:
    # The single closed-loop entrypoint: reuses the cron cycle with full-cycle
    # defaults so a lazy operator gets the whole loop in one command — due reviews
    # (auto-scored + auto-postmortemed), alert reconciliation, thesis re-aggregation,
    # and calibration-lesson synthesis. The autonomous --agent reforecast + push
    # notifications are a further layer on top of this deterministic cycle.
    from forecasting import cron_runner

    synthesize: bool | None = None
    if getattr(args, "synthesize_lessons", False):
        synthesize = True
    elif getattr(args, "no_synthesize_lessons", False):
        synthesize = False

    reforecast_runner = _build_cycle_reforecast_runner(args) if getattr(args, "agent", False) else None

    report = cron_runner.run_due_reviews(
        db_path=str(_ledger(args).db_path),
        now=args.now,
        auto_score=True,
        auto_postmortem=True,
        thesis_aggregate=not getattr(args, "no_thesis_aggregate", False),
        reconcile_alerts=not getattr(args, "no_reconcile", False),
        synthesize_lessons=synthesize,
        reforecast_runner=reforecast_runner,
    )
    report = (report or "").strip()
    print(report if report else "Forecast cycle complete — nothing was due.")


def _run_one(ledger: "ForecastLedger", question_id: str, args: argparse.Namespace) -> bool:
    """Refresh a single member forecast via the SAME deterministic re-pool the
    `forecast refresh` handler uses. Tolerant: logs and returns False on any
    failure so a batch run keeps going.
    """

    from tools.forecasting_tool import fetch_watched_source_payloads

    try:
        result = ledger.refresh_forecast(
            question_id,
            fetcher=lambda specs: fetch_watched_source_payloads(specs, concurrency=4),
            re_estimate="deterministic",
            trigger_reason="run_all_batch",
        )
    except Exception as exc:  # pragma: no cover — network/data variability
        print(f"  {question_id}: refresh failed ({exc})", file=sys.stderr)
        return False
    status = result.get("status")
    committed = result.get("forecast_id")
    if committed:
        try:
            _write_analyst_brief(ledger, question_id, ledger.get_snapshot(committed))
        except Exception:
            pass
    print(f"  {question_id}: {status}")
    return True


def _cmd_run_all(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    active = ledger.list_questions(status="active")
    members = [q for q in active if not ledger.is_thesis(q)]
    theses = [q for q in active if ledger.is_thesis(q)]
    if args.limit is not None:
        members = members[: args.limit]

    if args.dry_run:
        print(f"dry-run: would refresh {len(members)} member forecast(s) (phase 1):")
        for question in members:
            print(f"  {question.id}  {question.title}")
        # Order theses: plain (non-nested) first, nested (member of another thesis) last.
        ordered = _order_theses(ledger, theses)
        print(f"dry-run: would aggregate {len(ordered)} thesis/theses (phase 2):")
        for thesis in ordered:
            print(f"  {thesis.id}  {thesis.title}")
        return

    # Phase 1: refresh every active member forecast (commits their snapshots).
    ran = 0
    failed = 0
    print(f"phase1: refreshing {len(members)} member forecast(s)")
    for question in members:
        if _run_one(ledger, question.id, args):
            ran += 1
        else:
            failed += 1

    # Phase 2 (AFTER phase 1 commits): aggregate theses. Plain theses before
    # nested ones so a thesis-of-theses reads its members' fresh snapshots.
    ordered = _order_theses(ledger, theses)
    aggregated = 0
    print(f"phase2: aggregating {len(ordered)} thesis/theses")
    for thesis in ordered:
        try:
            ledger.aggregate_thesis(thesis.id, rho=args.rho)
            aggregated += 1
            print(f"  {thesis.id}: aggregated")
        except Exception as exc:  # pragma: no cover — keep batch going
            print(f"  {thesis.id}: aggregate failed ({exc})", file=sys.stderr)

    print(f"phase1: {ran} members run ({failed} failed); phase2: {aggregated} theses aggregated")


def _order_theses(ledger: "ForecastLedger", theses: list[Any]) -> list[Any]:
    """Run plain theses before nested ones: a thesis that is itself a member of
    another thesis (``list_theses_for_member`` non-empty) is deferred to the end.
    """

    plain: list[Any] = []
    nested: list[Any] = []
    for thesis in theses:
        if ledger.list_theses_for_member(thesis.id):
            nested.append(thesis)
        else:
            plain.append(thesis)
    return plain + nested


def _cmd_autopilot_enable(args: argparse.Namespace) -> None:
    sources = _autopilot_sources(args)
    required_sources = _autopilot_required_sources(args)
    materiality_policy = _autopilot_materiality_policy(args.materiality_threshold)
    guardrail_policy = _autopilot_guardrail_policy(args)
    notification_policy = {
        "destination": args.notify,
        "quiet_if_unchanged": bool(args.quiet_if_unchanged),
    }
    result = _ledger(args).enable_autopilot(
        question_id=args.id,
        sources=sources,
        cadence=args.cadence,
        mode=args.mode,
        materiality_policy=materiality_policy,
        guardrail_policy=guardrail_policy,
        notification_policy=notification_policy,
        required_sources=required_sources,
        next_run_at=args.next_run_at,
        created_by=args.created_by,
        allow_missing_resolution_source=args.allow_missing_resolution_source,
    )
    policy = result["policy"]
    print(f"Autopilot enabled for {args.id}")
    print(f"Policy: {policy['id']}")
    print(f"Sources: {len(result['watched_sources'])}")
    if required_sources:
        print(f"Required sources: {len(required_sources)}")
    print(f"Cadence: {policy['cadence']}")
    print(f"Mode: {policy['mode'].replace('_', '-')}")
    print(f"Next run: {result['scheduled_review']['next_run_at']}")
    warnings = result["readiness"].get("warnings") or []
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    # Close the notify dead-end: `--notify <surface>:<target>` used to write a
    # destination string nothing read. Register it as a real router binding so
    # this question's digests + alerts actually reach the operator.
    if getattr(args, "notify", None):
        try:
            from forecasting import notify as _notify

            route = _notify.register_destination(
                args.notify,
                events=("cycle_digest", "alert"),
                label=f"autopilot:{args.id}",
                source=f"autopilot:{args.id}",
            )
            print(f"Notify: bound {route.id} (digests + alerts)")
        except ValueError as exc:
            print(f"Notify: could not bind {args.notify!r} — {exc}", file=sys.stderr)


def _cmd_autopilot_disable(args: argparse.Namespace) -> None:
    policy = _ledger(args).disable_autopilot(args.id)
    print(f"autopilot disabled for {args.id}")
    print(f"policy: {policy['id']}")


def _cmd_autopilot_status(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    policies = ledger.list_autopilot_policies(question_id=args.id, enabled_only=False)
    if not policies:
        print("No autopilot policy found.")
        return
    watches = ledger.list_watched_sources(scope_type="question", scope_ref=args.id, status=None)
    proposals = ledger.list_forecast_update_proposals(question_id=args.id, status=None, limit=20)
    runs = ledger.list_autopilot_runs(question_id=args.id, limit=5)
    for policy in policies:
        print(
            f"{policy['id']} enabled={policy['enabled']} mode={policy['mode'].replace('_', '-')} "
            f"cadence={policy['cadence']} schedule={policy['scheduled_review_id']}"
        )
    print(f"sources: {len(watches)}")
    print(f"required_sources: {len([row for row in watches if row.get('metadata', {}).get('required')])}")
    print(f"pending_proposals: {len([row for row in proposals if row['status'] == 'pending'])}")
    if runs:
        latest = runs[0]
        print(
            f"latest_run: {latest['id']} status={latest['status']} "
            f"changed={latest['sources_changed']} material={latest['material_changes']}"
        )


def _cmd_refresh(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    args.id = _resolve_question_id(ledger, args.id)
    if args.agent:
        # Delegate to the full LLM update stage (forecast agent --stage update).
        # The agent commits through the forecasting tool, whose hook writes the brief.
        # This is the AUTONOMOUS re-forecast path: it commits a MATERIAL move rather
        # than stopping at a preview (the forecast-update commit is separate from the
        # decision-card ACTION threshold — see protocol._COMMIT_MATERIAL_POLICY).
        args.stage = "update"
        args.commit_policy = "commit_material"
        _cmd_agent(args)
        return
    from tools.forecasting_tool import fetch_watched_source_payloads

    concurrency = args.concurrency
    result = ledger.refresh_forecast(
        args.id,
        fetcher=lambda specs: fetch_watched_source_payloads(specs, concurrency=concurrency),
        now=args.now,
        re_estimate="carry_forward" if args.carry_forward else "deterministic",
        extremize=args.extremize,
        correlation=args.correlation,
        dry_run=args.dry_run,
        commit=args.commit,
        trigger_reason="manual_refresh",
    )
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return
    status = result["status"]
    print(f"status: {status}")
    if result.get("fetch_failures"):
        for failure in result["fetch_failures"]:
            print(f"  fetch_failed: {failure['source']} ({failure['error']})")
    if status in {"no_change", "no_watched_sources"}:
        print(result.get("message", ""))
        return
    changed = result.get("changed_readings") or []
    new_evidence = result.get("new_evidence_ids") or []
    evidence_note = f", +{len(new_evidence)} evidence" if new_evidence else ""
    print(f"refreshed {len(changed)} reading(s){evidence_note}")
    prior = result.get("prior_probability")
    proposed = result.get("proposed_probability")
    if isinstance(prior, (int, float)) and isinstance(proposed, (int, float)):
        print(f"probability: {float(prior):.4f} -> {float(proposed):.4f} (delta {float(proposed) - float(prior):+.4f})")
    for reason in result.get("reasons_up") or []:
        print(f"  up:   {reason}")
    for reason in result.get("reasons_down") or []:
        print(f"  down: {reason}")
    if result.get("unmatched_sources"):
        print(f"  unmatched (fetched but not wired to a component): {', '.join(result['unmatched_sources'])}")
    if result.get("triggers_fired"):
        print(f"  triggers_fired: {', '.join(result['triggers_fired'])}")
    if result.get("needs_agent"):
        print("  note: raw-data change carried forward — re-run with --agent for a re-reasoned estimate.")
    committed = result.get("forecast_id")
    if committed:
        print(f"committed snapshot {committed}")
        # Standard step of the refresh process: write an analyst brief for the
        # snapshot the deterministic re-pool just committed. Best-effort.
        try:
            _write_analyst_brief(ledger, args.id, ledger.get_snapshot(committed))
        except Exception:
            pass
    else:
        print("(preview only — not committed)")


def _cmd_autopilot_run(args: argparse.Namespace) -> None:
    result = _ledger(args).run_autopilot(
        args.id,
        now=args.now,
        trigger_reason=args.trigger_reason,
        proposed_probability_or_distribution=args.proposed_probability,
        rationale=args.rationale,
    )
    run = result["run"]
    print(f"autopilot run {run['id']}")
    print(f"status: {run['status']}")
    print(f"checked: {run['sources_checked']}")
    print(f"changed: {run['sources_changed']}")
    print(f"material: {run['material_changes']}")
    required_failures = run.get("diagnostics", {}).get("required_source_failures") or []
    if required_failures:
        print(f"required_source_failures: {len(required_failures)}")
    proposal = result.get("proposal")
    if proposal:
        print(f"proposal: {proposal['id']} status={proposal['status']}")
        prior = proposal.get("prior_forecast_id") or ""
        print(f"prior_forecast: {prior}")
        print(f"proposed: {proposal['proposed_probability_or_distribution']}")
        print(f"approve: forecast autopilot approve {proposal['id']}")
    snapshot = result.get("forecast_snapshot")
    if snapshot:
        print(f"forecast_snapshot: {snapshot.forecast_id}")
    if not proposal and run["material_changes"] == 0:
        print("No material source changes detected.")


def _cmd_autopilot_history(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_autopilot_runs(question_id=args.id, limit=args.limit)
    if not rows:
        print("No autopilot runs found.")
        return
    print("Run ID         Started at           Status    Checked  Changed  Material  Proposal")
    for row in rows:
        print(
            f"{row['id']:<14} {row['started_at']:<20} {row['status']:<9} "
            f"{row['sources_checked']:<8} {row['sources_changed']:<8} "
            f"{row['material_changes']:<9} {row['proposal_id'] or ''}"
        )


def _cmd_autopilot_proposals(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_forecast_update_proposals(
        question_id=args.id,
        status=None if args.all else "pending",
        limit=100,
    )
    if not rows:
        print("No forecast update proposals found.")
        return
    print("Proposal ID    Question       Status          Created at           Proposed")
    for row in rows:
        print(
            f"{row['id']:<14} {row['question_id']:<14} {row['status']:<15} "
            f"{row['created_at']:<20} {row['proposed_probability_or_distribution']}"
        )


def _cmd_autopilot_approve(args: argparse.Namespace) -> None:
    snapshot = _ledger(args).approve_forecast_update_proposal(
        args.proposal_id,
        reviewed_by=args.reviewed_by,
    )
    print(f"approved proposal {args.proposal_id}")
    print(f"created forecast snapshot {snapshot.forecast_id}")


def _cmd_autopilot_reject(args: argparse.Namespace) -> None:
    proposal = _ledger(args).reject_forecast_update_proposal(
        args.proposal_id,
        reviewed_by=args.reviewed_by,
    )
    print(f"rejected proposal {proposal['id']}")
    print(f"status: {proposal['status']}")


def _autopilot_sources(args: argparse.Namespace) -> list[str]:
    sources = _autopilot_source_values(args.source, args.sources)
    required_sources = _autopilot_required_sources(args)
    for source in required_sources:
        if source not in sources:
            sources.append(source)
    if not sources:
        raise SystemExit("autopilot enable requires --source, --sources, --required-source, or --required-sources")
    return sources


def _autopilot_required_sources(args: argparse.Namespace) -> list[str]:
    return _autopilot_source_values(args.required_source, args.required_sources)


def _autopilot_source_values(single_values: list[str], bulk_value: str | None) -> list[str]:
    sources = [item.strip() for item in (single_values or []) if item and item.strip()]
    if bulk_value:
        for item in re.split(r"[,;]", bulk_value):
            item = item.strip()
            if item:
                sources.append(item)
    return list(dict.fromkeys(sources))


def _autopilot_materiality_policy(thresholds: list[str]) -> dict[str, Any]:
    policy: dict[str, Any] = {"min_source_changes": 1}
    raw_rules = [item.strip() for item in thresholds if item and item.strip()]
    if raw_rules:
        policy["rules"] = raw_rules
    for rule in raw_rules:
        match = re.search(r"(?:source_changes|min_source_changes)\s*(?:>=|=)\s*(\d+)", rule)
        if match:
            policy["min_source_changes"] = max(int(match.group(1)), 1)
    return policy


def _autopilot_guardrail_policy(args: argparse.Namespace) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "require_no_critical_source_failures": True,
        "require_model_parse_success": True,
        "require_evidence_refs": True,
        "require_prior_forecast": True,
        "allow_resolution_auto_commit": False,
    }
    if args.max_auto_delta is not None:
        policy["max_single_run_probability_delta"] = args.max_auto_delta
    if args.min_sources_for_auto_commit is not None:
        policy["min_independent_sources_for_auto_commit"] = args.min_sources_for_auto_commit
    return policy
