"""``forecast review`` / ``schedule`` — stale-forecast review + scheduled self-checks.

A carved CLI subcommand domain (the CLI-assembler pattern; see
:mod:`forecasting.cli.thesis`). The ``review`` and ``schedule`` groups are
registered as one contiguous block via :func:`register` at their pre-carve
position, so ``forecast --help`` stays byte-identical. ``schedule`` owns the
nested ``install-cron`` and ``automode-cron start/stop/status`` verbs.

Shared helpers stay in ``core`` and are imported bare; ``_ledger`` is reached
through the call-time ``_core.`` hop (the monkeypatch discipline). ``core``
imports this module back at its bottom for registration.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from forecasting.cli import core as _core
from forecasting.cli.core import (
    ForecastLedger,
    _format_probability,
    _format_schedule_scope,
    _parse_day_count,
    _review_next_action,
    is_learning_review_reason,
)


def _ledger(args: argparse.Namespace) -> ForecastLedger:
    """Hop to ``core._ledger`` at CALL time (the ``_core.`` monkeypatch
    discipline: a test patching ``forecasting.cli._ledger`` reaches here)."""

    return _core._ledger(args)


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``review`` + ``schedule`` command groups (contiguous block)."""

    review_parser = forecast_sub.add_parser("review", help="Review stale or active forecasts")
    from forecasting.interfaces.commands import add_review_arguments
    add_review_arguments(review_parser)
    review_parser.set_defaults(_forecast_handler=_cmd_review)

    schedule_parser = forecast_sub.add_parser("schedule", help="Manage scheduled self-checks")
    schedule_sub = schedule_parser.add_subparsers(dest="schedule_command")
    schedule_add = schedule_sub.add_parser("add", help="Add a scheduled review")
    schedule_add.add_argument("--question", dest="question_id")
    schedule_add.add_argument("--domain")
    schedule_add.add_argument("--topic")
    schedule_add.add_argument("--portfolio")
    schedule_add.add_argument("--horizon", help="Scope scheduled review to forecast horizon in days or range")
    schedule_add.add_argument("--cadence", required=True)
    schedule_add.add_argument(
        "--next-run-at",
        help="First run timestamp; defaults to now so the review is due immediately",
    )
    schedule_add.add_argument("--stale-days", type=int, default=7)
    schedule_add.add_argument("--trigger-reason", default="scheduled")
    schedule_add.add_argument("--auto-score", action="store_true")
    schedule_add.add_argument("--auto-postmortem", action="store_true")
    schedule_add.add_argument("--confidence-below", type=float)
    schedule_add.add_argument("--confidence-above", type=float)
    schedule_add.add_argument("--large-delta-threshold", type=float)
    schedule_add.add_argument("--disabled", action="store_true")
    schedule_add.set_defaults(_forecast_handler=_cmd_schedule_add)
    schedule_list = schedule_sub.add_parser("list", help="List scheduled reviews")
    schedule_list.set_defaults(_forecast_handler=_cmd_schedule_list)
    schedule_dedupe = schedule_sub.add_parser(
        "dedupe",
        help="Collapse duplicate scheduled reviews (keeps one per scope + cadence + reason)",
    )
    schedule_dedupe.add_argument("--json", action="store_true", help="Emit machine-readable dedupe summary")
    schedule_dedupe.set_defaults(_forecast_handler=_cmd_schedule_dedupe)
    schedule_run = schedule_sub.add_parser("run", help="Run due scheduled self-checks")
    schedule_run.add_argument("--due", action="store_true", help="Run due reviews explicitly; this is the default")
    schedule_run.add_argument("--now")
    schedule_run.add_argument("--auto-score", action="store_true")
    schedule_run.add_argument("--auto-postmortem", action="store_true")
    schedule_run.set_defaults(_forecast_handler=_cmd_schedule_run)
    schedule_history = schedule_sub.add_parser("history", help="Show scheduled self-check run history")
    schedule_history.add_argument("--schedule", dest="scheduled_review_id")
    schedule_history.add_argument("--limit", type=int, default=20)
    schedule_history.add_argument("--json", action="store_true", help="Emit machine-readable run history JSON")
    schedule_history.set_defaults(_forecast_handler=_cmd_schedule_history)
    schedule_cron = schedule_sub.add_parser(
        "install-cron",
        help="Install a no-agent cron bridge for forecast self-checks",
    )
    schedule_cron.add_argument("--schedule", default="0 8 * * *")
    schedule_cron.add_argument("--name", default="Forecast self-check")
    schedule_cron.add_argument("--deliver", default="local")
    schedule_cron.add_argument("--profile")
    # Feature flags default ON so an operator-installed cron is as capable as the
    # auto-installed nightly routine (ensure_default_routines) — a bare install-cron
    # must not silently downgrade the desk's learning loop. `--no-*` opts out; the
    # positive flags are kept as no-ops for backward compatibility.
    schedule_cron.add_argument("--auto-score", dest="auto_score", action="store_true")
    schedule_cron.add_argument("--no-auto-score", dest="auto_score", action="store_false",
                               help="Do NOT auto-score resolved questions in the nightly sweep")
    schedule_cron.add_argument("--auto-postmortem", dest="auto_postmortem", action="store_true")
    schedule_cron.add_argument("--no-auto-postmortem", dest="auto_postmortem", action="store_false",
                               help="Do NOT auto-write postmortems in the nightly sweep")
    schedule_cron.add_argument(
        "--thesis-aggregate",
        dest="thesis_aggregate",
        action="store_true",
        help="Preview all thesis aggregates (+ entity suitabilities) after each member review sweep",
    )
    schedule_cron.add_argument("--no-thesis-aggregate", dest="thesis_aggregate", action="store_false",
                               help="Do NOT preview thesis aggregates in the nightly sweep")
    schedule_cron.add_argument("--synthesize-lessons", dest="synthesize_lessons", action="store_true",
                               help="Synthesize calibration lessons after the nightly sweep")
    schedule_cron.add_argument("--no-synthesize-lessons", dest="synthesize_lessons", action="store_false",
                               help="Do NOT synthesize calibration lessons in the nightly sweep")
    schedule_cron.add_argument("--refresh-market-models", dest="refresh_market_models", action="store_true",
                               help="Re-pull + recompute Market Models linked to open questions in the nightly sweep")
    schedule_cron.add_argument("--no-refresh-market-models", dest="refresh_market_models", action="store_false",
                               help="Do NOT refresh Market Models in the nightly sweep")
    schedule_cron.add_argument("--estimate-source-changes", dest="estimate_source_changes", action="store_true",
                               help="Also estimate queued source changes nightly (normally owned by automode)")
    schedule_cron.add_argument("--no-estimate-source-changes", dest="estimate_source_changes", action="store_false",
                               help="Do NOT run the source-change estimator in the nightly sweep")
    schedule_cron.add_argument("--estimator-model")
    schedule_cron.add_argument("--estimator-provider")
    schedule_cron.add_argument("--estimator-limit", type=int, default=5)
    schedule_cron.add_argument("--estimator-max-iterations", type=int, default=12)
    schedule_cron.add_argument("--calibrate-utility", dest="calibrate_utility", action="store_true")
    schedule_cron.add_argument("--no-calibrate-utility", dest="calibrate_utility", action="store_false")
    schedule_cron.set_defaults(
        _forecast_handler=_cmd_schedule_install_cron,
        auto_score=True,
        auto_postmortem=True,
        thesis_aggregate=True,
        synthesize_lessons=True,
        refresh_market_models=True,
        estimate_source_changes=False,
        calibrate_utility=True,
    )

    automode_cron = schedule_sub.add_parser(
        "automode-cron",
        help="Start/stop/status the continuous warning-automode cron (free tier + bounded paid tier)",
    )
    automode_cron_sub = automode_cron.add_subparsers(dest="automode_cron_command")
    ac_start = automode_cron_sub.add_parser(
        "start", help="Install the continuous warning-automode cron job (clean re-arm)"
    )
    ac_start.add_argument("--schedule", default="every 30 minutes")
    ac_start.add_argument("--name", default="Forecast warning automode")
    ac_start.add_argument("--deliver", default="local")
    ac_start.add_argument("--profile")
    ac_start.add_argument(
        "--no-agent",
        dest="agent",
        action="store_false",
        help="Free-tier-only continuous mode (do NOT wire the paid LLM tier)",
    )
    ac_start.set_defaults(agent=True)
    ac_start.add_argument(
        "--paid-budget", type=int, help="Per-cycle paid-tier agent-run cap (default 1)"
    )
    ac_start.add_argument(
        "--paid-min-interval-hours", type=float, help="Minimum hours between paid passes (default 0.5)"
    )
    ac_start.add_argument("--model")
    ac_start.add_argument("--provider")
    ac_start.add_argument("--max-iterations", type=int)
    ac_start.set_defaults(_forecast_handler=_cmd_automode_cron_start)
    ac_stop = automode_cron_sub.add_parser("stop", help="Remove the continuous warning-automode cron job")
    ac_stop.add_argument("--name", default="Forecast warning automode")
    ac_stop.set_defaults(_forecast_handler=_cmd_automode_cron_stop)
    ac_status = automode_cron_sub.add_parser("status", help="Show the continuous warning-automode cron status")
    ac_status.add_argument("--name", default="Forecast warning automode")
    ac_status.add_argument("--json", action="store_true")
    ac_status.set_defaults(_forecast_handler=_cmd_automode_cron_status)


def _cmd_review(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    from forecasting.application.reviews import review_forecasts

    rows = review_forecasts(ledger,
        stale=args.stale,
        last_days=args.last_days,
        domain=args.domain,
        topic=args.topic,
        horizon=args.horizon,
        confidence_below=args.confidence_below,
        confidence_above=args.confidence_above,
        large_delta_threshold=args.large_delta_threshold,
        now=args.now,
    )
    from forecasting.interfaces.commands import format_review
    print(format_review(rows))


# Compatibility names for callers; these helpers have one application owner.
from forecasting.application.reviews import _merge_learned_error_reviews, _sort_review_rows


def _cmd_schedule_add(args: argparse.Namespace) -> None:
    scope_type, scope_ref = _schedule_scope(args)
    row = _ledger(args).schedule_review(
        scope_type=scope_type,
        scope_ref=scope_ref,
        cadence=args.cadence,
        next_run_at=args.next_run_at,
        trigger_reason=args.trigger_reason,
        enabled=not args.disabled,
        auto_score=args.auto_score,
        auto_postmortem=args.auto_postmortem,
        stale_days=args.stale_days,
        confidence_below=args.confidence_below,
        confidence_above=args.confidence_above,
        large_delta_threshold=args.large_delta_threshold,
    )
    print(f"scheduled review {row['id']}")
    print(f"scope: {row['scope_type']} {row['scope_ref'] or ''}".rstrip())
    print(f"next_run_at: {row['next_run_at']}")


def _cmd_schedule_dedupe(args: argparse.Namespace) -> None:
    result = _ledger(args).dedupe_scheduled_reviews()
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    if result["disabled_count"] == 0:
        print("No duplicate scheduled reviews found.")
        return
    print(
        f"Collapsed {result['groups_collapsed']} duplicate group(s); "
        f"disabled {result['disabled_count']} redundant review(s)."
    )
    for review_id in result["disabled"]:
        print(f"  disabled {review_id}")


def _cmd_schedule_list(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_scheduled_reviews()
    if not rows:
        print("No scheduled reviews found.")
        return
    print("ID             Scope          Cadence      Stale  Confidence     Delta  Next run             Enabled  Learning")
    for row in rows:
        scope = _format_schedule_scope(row)
        learning = _format_schedule_learning(row)
        confidence = _format_schedule_confidence(row)
        delta = _format_schedule_delta(row)
        print(
            f"{row['id']:<14} {scope:<14} {row['cadence']:<12} {int(row.get('stale_days') or 7):<6} "
            f"{confidence:<14} {delta:<6} {row['next_run_at']:<20} {bool(row['enabled']):<7} {learning}"
        )


def _cmd_schedule_run(args: argparse.Namespace) -> None:
    results = _ledger(args).run_due_scheduled_reviews(
        now=args.now,
        auto_score=args.auto_score,
        auto_postmortem=args.auto_postmortem,
    )
    if not results:
        print("No scheduled reviews due.")
        return
    total_alerts = sum(len(result["alerts"]) for result in results)
    alert_rows = [alert for result in results for alert in result["alerts"]]
    score_events = [alert for alert in alert_rows if alert.reason.startswith("score_created:")]
    postmortem_events = [alert for alert in alert_rows if alert.reason.startswith("postmortem_created:")]
    learning_review_events = [
        alert
        for alert in alert_rows
        if is_learning_review_reason(alert.reason)
    ]
    print(f"ran {len(results)} scheduled review(s)")
    print(f"created {total_alerts} alert(s)")
    print(f"scores_created: {len(score_events)}")
    print(f"postmortems_created: {len(postmortem_events)}")
    print(f"learning_reviews: {len(learning_review_events)}")
    for result in results:
        review = result["review"]
        run = result.get("run") or {}
        run_suffix = f" run={run['id']}" if run.get("id") else ""
        observed = len(result["alerts"])
        created = int(run.get("alert_count") or 0)
        print(
            f"{review['id']} next_run_at={review['next_run_at']} "
            f"alerts_created={created} alerts_observed={observed}{run_suffix}"
        )
        for alert in result["alerts"]:
            print(f"  {alert.id} {alert.scope_type}:{alert.scope_ref} {alert.reason}")


def _cmd_schedule_history(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    rows = ledger.list_scheduled_review_runs(
        scheduled_review_id=args.scheduled_review_id,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps({"runs": rows, "count": len(rows)}, indent=2, sort_keys=True))
        return
    if not rows:
        print("No scheduled review runs found.")
        return
    print("Run ID         Schedule       Run at               Alerts  Scores  Postmortems  Learning  Next run")
    for row in rows:
        print(
            f"{row['id']:<14} {row['scheduled_review_id']:<14} {row['run_at']:<20} "
            f"{int(row.get('alert_count') or 0):<7} "
            f"{int(row.get('score_count') or 0):<7} "
            f"{int(row.get('postmortem_count') or 0):<12} "
            f"{int(row.get('learning_review_count') or 0):<9} "
            f"{row['next_run_at']}"
        )


def _cmd_schedule_install_cron(args: argparse.Namespace) -> None:
    from forecasting.scheduler import install_forecast_cron

    job = install_forecast_cron(
        schedule=args.schedule,
        name=args.name,
        deliver=args.deliver,
        profile=args.profile,
        db_path=args.db,
        auto_score=getattr(args, "auto_score", True),
        auto_postmortem=getattr(args, "auto_postmortem", True),
        thesis_aggregate=getattr(args, "thesis_aggregate", True),
        synthesize_lessons=getattr(args, "synthesize_lessons", True),
        refresh_market_models=getattr(args, "refresh_market_models", True),
        estimate_source_changes=getattr(args, "estimate_source_changes", False),
        estimator_model=getattr(args, "estimator_model", None),
        estimator_provider=getattr(args, "estimator_provider", None),
        estimator_limit=getattr(args, "estimator_limit", 5),
        estimator_max_iterations=getattr(args, "estimator_max_iterations", 12),
        calibrate_utility=getattr(args, "calibrate_utility", True),
    )
    print(f"cron_job: {job['id']}")
    print(f"name: {job['name']}")
    print(f"schedule: {job['schedule_display']}")
    print(f"script: {job['script']}")
    print(f"mode: {'no-agent' if job.get('no_agent') else 'agent'}")


def _cmd_automode_cron_start(args: argparse.Namespace) -> None:
    from forecasting.scheduler import install_warning_automode_cron

    job = install_warning_automode_cron(
        schedule=args.schedule,
        name=args.name,
        deliver=args.deliver,
        profile=args.profile,
        db_path=getattr(args, "db", None),
        agent=getattr(args, "agent", True),
        paid_budget=getattr(args, "paid_budget", None),
        paid_min_interval_hours=getattr(args, "paid_min_interval_hours", None),
        model=getattr(args, "model", None),
        provider=getattr(args, "provider", None),
        max_iterations=getattr(args, "max_iterations", None),
    )
    print(f"cron_job: {job['id']}")
    print(f"name: {job['name']}")
    print(f"schedule: {job['schedule_display']}")
    print(f"script: {job['script']}")
    print(f"paid_tier: {'on' if getattr(args, 'agent', True) else 'off (free-only)'}")


def _cmd_automode_cron_stop(args: argparse.Namespace) -> None:
    from forecasting.scheduler import remove_warning_automode_cron

    removed = remove_warning_automode_cron(name=args.name)
    print(f"removed {removed} warning-automode cron job(s)")


def _cmd_automode_cron_status(args: argparse.Namespace) -> None:
    from forecasting.scheduler import warning_automode_cron_status

    status = warning_automode_cron_status(name=args.name)
    if getattr(args, "json", False):
        print(json.dumps(status, indent=2, sort_keys=True, default=str))
        return
    if not status["installed"]:
        print("warning-automode cron: not installed")
        print(f"last_paid_run_at: {status.get('last_paid_run_at') or '(never)'}")
        return
    job = status["job"]
    print("warning-automode cron: installed")
    print(f"job_id: {job['id']}")
    print(f"name: {job.get('name')}")
    print(f"schedule: {job.get('schedule_display')}")
    print(f"enabled: {job.get('enabled', True)}")
    print(f"last_run_at: {job.get('last_run_at') or '(never)'}")
    print(f"last_paid_run_at: {status.get('last_paid_run_at') or '(never)'}")


def _schedule_scope(args: argparse.Namespace) -> tuple[str, str]:
    if args.question_id and (args.domain or args.topic or args.portfolio or args.horizon):
        raise SystemExit("--question cannot be combined with --domain, --topic, --portfolio, or --horizon")
    if args.portfolio and (args.question_id or args.domain or args.topic or args.horizon):
        raise SystemExit("--portfolio cannot be combined with --question, --domain, --topic, or --horizon")
    if args.horizon and (args.question_id or args.domain or args.topic or args.portfolio):
        raise SystemExit("--horizon cannot be combined with --question, --domain, --topic, or --portfolio")
    if args.question_id:
        return "question", args.question_id
    if args.domain and args.topic:
        return "domain_topic", json.dumps({"domain": args.domain, "topic": args.topic}, sort_keys=True)
    if args.domain:
        return "domain", args.domain
    if args.topic:
        return "topic", args.topic
    if args.horizon:
        return "horizon", args.horizon
    if not args.portfolio:
        raise SystemExit("schedule add requires --question, --domain, --topic, --portfolio, or --horizon")
    return "portfolio", args.portfolio


def _format_schedule_learning(row: dict[str, Any]) -> str:
    enabled = []
    if row.get("auto_score"):
        enabled.append("score")
    if row.get("auto_postmortem"):
        enabled.append("postmortem")
    return ",".join(enabled) if enabled else "-"


def _format_schedule_confidence(row: dict[str, Any]) -> str:
    parts = []
    if row.get("confidence_below") is not None:
        parts.append(f"<{float(row['confidence_below']):.2f}")
    if row.get("confidence_above") is not None:
        parts.append(f">{float(row['confidence_above']):.2f}")
    return ",".join(parts) if parts else "-"


def _format_schedule_delta(row: dict[str, Any]) -> str:
    if row.get("large_delta_threshold") is None:
        return "-"
    return f">={float(row['large_delta_threshold']):.2f}"
