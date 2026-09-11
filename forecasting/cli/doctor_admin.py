"""``forecast doctor`` / ``backup`` / ``config`` — operational diagnostics.

A carved CLI subcommand domain (the CLI-assembler pattern; see
:mod:`forecasting.cli.thesis`). Registers its subparsers via the shared per-domain
hooks and owns its handlers. Because ``doctor``+``backup`` and ``config`` occupy
two DIFFERENT positions in the registration order, this domain exposes two hooks —
:func:`register` (doctor + backup) and :func:`register_config` — each invoked by
:func:`forecasting.cli.core.register_cli` at the exact position its subcommands
held pre-carve, so ``forecast --help`` stays byte-identical.

Shared helpers stay in ``core`` and are imported bare; ``_ledger`` IS patched at
``forecasting.cli._ledger`` by tests, so it is reached through a call-time
``_core.`` wrapper (the ``_core.`` monkeypatch discipline). ``core`` imports this
module back at its bottom for registration + surface parity
(``forecasting.cli._build_doctor_report`` / ``_build_durability_section`` are
imported by ``tests/test_doctor_durability.py``).
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from forecasting.cli import core as _core
from forecasting.cli.core import (
    DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM,
    DEFAULT_MIN_EXTERNAL_SOURCE_FAMILIES_FOR_CLAIM,
    DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM,
    DOCTOR_BACKUP_STALE_HOURS,
    ForecastLedger,
    PRODUCT_NAME,
    _forecast_status_payload,
    _format_metric,
    _print_cohort_scoreboard,
    _recent_backtest_summaries,
    build_forecasting_evidence_status,
    utc_now_iso,
)


def _ledger(args: argparse.Namespace) -> ForecastLedger:
    """Delegate to ``core._ledger`` at CALL time so a test that patches
    ``forecasting.cli._ledger`` reaches these carved handlers (the ``_core.``
    monkeypatch discipline)."""

    return _core._ledger(args)


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``doctor`` + ``backup`` command groups (contiguous block)."""

    lifecycle = forecast_sub.add_parser("lifecycle", help="Inspect or recover forecast lifecycle handoffs")
    lifecycle.add_argument("action", choices=["status", "run", "review"], nargs="?", default="status", help="Inspect by default; run recovers confirmed score/postmortem handoffs")
    lifecycle.add_argument("question_id", nargs="?")
    from forecasting.settlement_reviews import STATES
    lifecycle.add_argument("--state", choices=STATES)
    lifecycle.add_argument("--next-action")
    lifecycle.add_argument("--owner")
    lifecycle.add_argument("--reason", help="Review finding; does not resolve or change probability")
    lifecycle.add_argument("--source", help="Source inspected for this review")
    lifecycle.add_argument("--revisit-at", help="Next check, ISO timestamp; with --state creates a durable reminder")
    lifecycle.add_argument("--now", help="UTC inspection/recovery time (defaults to now)")
    lifecycle.add_argument("--limit", type=int, default=25, help="Maximum tasks to execute or rows to display (default 25)")
    lifecycle.add_argument("--json", action="store_true", help="Emit full structured status and execution results")
    lifecycle.set_defaults(_forecast_handler=_cmd_lifecycle)

    doctor_parser = forecast_sub.add_parser(
        "doctor",
        help="Run operational, pilot, and readiness checks",
    )
    doctor_parser.add_argument("--last", type=int, default=20, help="Number of recent backtest runs to inspect")
    doctor_parser.add_argument("--dataset", help="Filter readiness to runs whose dataset contains this text")
    doctor_parser.add_argument("--min-questions", type=int, default=3)
    doctor_parser.add_argument("--min-structured-source-questions", type=int, default=1)
    doctor_parser.add_argument("--min-scores", type=int, default=1)
    doctor_parser.add_argument("--min-postmortems", type=int, default=1)
    doctor_parser.add_argument("--min-scheduled-reviews", type=int, default=1)
    doctor_parser.add_argument("--min-scheduled-review-runs", type=int, default=1)
    doctor_parser.add_argument(
        "--min-live-scores",
        type=int,
        default=DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM,
        help="Required resolved live scores for readiness accounting",
    )
    doctor_parser.add_argument(
        "--min-agent-protocol-cases",
        type=int,
        default=DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM,
        help="Required scored agent-protocol replay cases for readiness accounting",
    )
    doctor_parser.add_argument(
        "--min-external-source-families",
        type=int,
        default=DEFAULT_MIN_EXTERNAL_SOURCE_FAMILIES_FOR_CLAIM,
        help="Required distinct external resolved-question source families for readiness accounting",
    )
    doctor_parser.add_argument(
        "--require-pilot-ready",
        action="store_true",
        help="Exit nonzero if tester pilot artifacts are incomplete",
    )
    doctor_parser.add_argument(
        "--require-readiness",
        action="store_true",
        help="Exit nonzero if benchmark/live evidence-readiness gaps remain",
    )
    doctor_parser.add_argument("--json", action="store_true", help="Emit machine-readable doctor JSON")
    doctor_parser.set_defaults(_forecast_handler=_cmd_doctor)

    backup_parser = forecast_sub.add_parser(
        "backup",
        help="Back up the forecast ledger (online snapshot + integrity check) and manage retention",
    )
    backup_sub = backup_parser.add_subparsers(dest="backup_command")
    backup_run = backup_sub.add_parser(
        "run", help="Create an online backup + integrity check now (runs as a durable job)"
    )
    backup_run.add_argument(
        "--dest-dir", help="Override the backup directory (default: <ledger dir>/backups)"
    )
    backup_run.add_argument(
        "--keep-recent", type=int, help="Retention override: newest N backups always kept (default 14)"
    )
    backup_run.add_argument(
        "--weekly-weeks", type=int, help="Retention override: one-per-week for W weeks (default 8)"
    )
    backup_run.add_argument("--json", action="store_true", help="Emit the machine-readable job record")
    backup_run.set_defaults(_forecast_handler=_cmd_backup_run)
    backup_list = backup_sub.add_parser("list", help="List existing ledger backups (newest first)")
    backup_list.add_argument(
        "--dest-dir", help="Override the backup directory (default: <ledger dir>/backups)"
    )
    backup_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    backup_list.set_defaults(_forecast_handler=_cmd_backup_list)
    # Bare `forecast backup` runs a backup now.
    backup_parser.set_defaults(_forecast_handler=_cmd_backup_run)


def register_config(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``config`` command group (its own registration position)."""

    config_parser = forecast_sub.add_parser(
        "config",
        help="Inspect the layered runtime configuration (typed loader + config doctor).",
    )
    config_sub = config_parser.add_subparsers(dest="config_command")
    config_doctor = config_sub.add_parser(
        "doctor",
        help="Report unknown/typo vars, defaults in effect, secret presence, "
        "file-vs-env conflicts, and the Kalshi two-var trap (read-only).",
    )
    config_doctor.add_argument("--json", action="store_true", help="Emit the machine-readable report JSON.")
    config_doctor.set_defaults(_forecast_handler=_cmd_config_doctor)
    config_parser.set_defaults(_forecast_handler=_cmd_config_doctor)


def _build_durability_section(
    ledger: ForecastLedger, *, stale_hours: float = DOCTOR_BACKUP_STALE_HOURS
) -> dict[str, Any]:
    """The doctor's integrity+backup section: last-backup age (``ok`` / ``stale`` /
    ``missing``), the integrity verdict, and the row-count snapshot.

    ``missing`` (no backup at all) and ``stale`` (>``stale_hours`` old) are the two
    WARN states — the surface that keeps the durability gap on the lazy path even
    when the backup cadence is operator-created."""

    latest = ledger.latest_backup()
    integ = ledger.integrity_check()
    if latest is None:
        backup_status = "missing"
    elif isinstance(latest.get("age_hours"), (int, float)) and latest["age_hours"] > stale_hours:
        backup_status = "stale"
    else:
        backup_status = "ok"
    return {
        "backup_status": backup_status,  # ok | stale | missing
        "stale_after_hours": stale_hours,
        "last_backup": latest,
        "backup_dir": str(ledger.default_backup_dir()),
        "integrity_ok": bool(integ.get("ok")),
        "violations": integ.get("violations") or [],
        "counts": integ.get("counts") or {},
    }


def _build_doctor_report(args: argparse.Namespace) -> dict[str, Any]:
    ledger = _ledger(args)
    status = _forecast_status_payload(ledger)
    pilot_report = ledger.pilot_report(
        min_questions=args.min_questions,
        min_structured_source_questions=args.min_structured_source_questions,
        min_scores=args.min_scores,
        min_postmortems=args.min_postmortems,
        min_scheduled_reviews=args.min_scheduled_reviews,
        min_scheduled_review_runs=args.min_scheduled_review_runs,
    )
    rows, summaries = _recent_backtest_summaries(
        ledger,
        last=args.last,
        dataset=getattr(args, "dataset", None),
    )
    evidence_status = build_forecasting_evidence_status(
        ledger,
        summaries,
        min_live_scores=max(args.min_live_scores, 0),
        min_agent_protocol_cases=max(args.min_agent_protocol_cases, 0),
        min_external_source_families=max(args.min_external_source_families, 0),
    )
    pilot_ready = pilot_report["passed_checks"] == pilot_report["total_checks"]
    readiness_gaps = bool(evidence_status.get("gaps"))
    if not pilot_ready:
        doctor_status = "needs_tester_pilot_artifacts"
    elif readiness_gaps:
        doctor_status = "tester_handoff_ready_live_claim_unproven"
    else:
        doctor_status = "benchmark_evidence_ready_live_claim_unproven"

    from forecasting.protocol import PROCESS_VERSION

    # Measurement honesty: score aggregates BY COHORT (never a pooled headline) +
    # the pathological-row audit that separates ingestion artifacts from real
    # catastrophic misses. Both read-only + fail-safe, like every probe here.
    try:
        cohort_scoreboard = ledger.cohort_scoreboard()
    except Exception:
        cohort_scoreboard = None
    try:
        scores_audit = ledger.scores_audit()
    except Exception:
        scores_audit = None

    # A heuristic, read-only detector must NEVER take down the doctor audit.
    try:
        templated_batches = ledger.detect_templated_batches()
    except Exception:
        templated_batches = []

    # SLICE 5 fold: one place that shows ALL three "warning" models together — the
    # alert_events backlog (grouped by reason), the saturation/hook issues, and the
    # templated-batch clusters. Each sub-probe is read-only and fail-safe so a
    # heuristic can never take down the audit (mirrors templated_batches above).
    from forecasting.warnings import summarize_open_warnings

    try:
        alert_backlog = summarize_open_warnings(ledger)
    except Exception:
        alert_backlog = {"groups": [], "group_count": 0, "open_total": 0}
    try:
        from forecasting.hooks import finish_sweep

        active_ids = [q.id for q in ledger.list_questions(status="active")]
        saturation = finish_sweep(ledger, active_ids)
    except Exception:
        saturation = {"checked": 0, "clean": 0, "under_saturated": []}
    # ADHERENCE SCORECARD: per-gate pass rates over active questions, tallied from
    # the STORED saturation verdicts (read-only, no recompute). The glanceable trust
    # number — failed_block should be zero, failed_warn columns should be falling.
    try:
        from forecasting.hooks import adherence_scorecard

        hook_adherence = adherence_scorecard(ledger, question_ids=active_ids)
    except Exception:
        hook_adherence = {"questions_scored": 0, "rules_tracked": 0, "total_failed_block": 0, "rules": {}}
    warnings_fold = {
        "alert_backlog": alert_backlog,
        "saturation": saturation,
        "templated_batches": templated_batches,
    }

    # Triage trust gate: is the cheap auto-labeler good enough (held-out auto-vs-
    # expert accuracy) to be trusted to auto-filter, or still SUGGEST-ONLY? Read-
    # only + fail-safe, like every probe above.
    try:
        from forecasting.triage import build_triage_trust_gate

        triage_gate = build_triage_trust_gate(ledger)
    except Exception:
        triage_gate = None

    # SLICE S4 fold: cron health. Is the recurrence spine actually FIRING? Read the
    # installed forecast cron jobs' last_status/last_error/last_run_at and flag
    # errored or missed (last_run_at older than 2x cadence) jobs. Read-only +
    # fail-safe, like every probe above.
    try:
        from forecasting.scheduler import forecast_cron_health

        cron_health = forecast_cron_health()
    except Exception:
        cron_health = None

    # Runtime conservation/liveness gates. Unit tests can prove individual
    # transitions while a production ledger still accumulates orphaned events or
    # runs without a worker; fold the live queue invariants into doctor explicitly.
    try:
        operations = ledger.operational_cockpit()
        operational_issues: list[dict[str, Any]] = []
        source_changes = operations.get("source_changes") or {}
        coverage = operations.get("coverage") or {}
        high = operations.get("high_severity") or {}
        installed_scripts = {
            row.get("script") for row in (cron_health or {}).get("jobs", [])
        }
        lifecycle = (operations.get("lifecycle") or {}).get("counts") or {}
        checks = (
            ("unfinished_forecast_lifecycles", int(lifecycle.get("unfinished") or 0)),
            ("failed_finalization_tasks", int(lifecycle.get("failed_tasks") or 0)),
            ("stranded_source_events", int(source_changes.get("stranded") or 0)),
            ("open_source_failures", int(source_changes.get("open_failed") or 0)),
            ("service_mode_coverage_gaps", int(coverage.get("service_mode_coverage_gaps") or 0)),
            ("unowned_high_severity", int(high.get("unclaimed") or 0)),
        )
        for issue_id, observed in checks:
            if observed:
                operational_issues.append({"id": issue_id, "observed": observed})
        if "forecast_warning_automode.py" not in installed_scripts:
            operational_issues.append({"id": "warning_worker_not_installed", "observed": 1})
        operational_health = {
            "healthy": not operational_issues,
            "issues": operational_issues,
            "operations": operations,
        }
        from forecasting.cron_runner import read_warning_automode_state

        operational_health["warning_worker"] = read_warning_automode_state() or None
    except Exception:
        operational_health = None

    # Free-tier warning DRAIN (nightly): the last drain count (from the state file
    # the run_due_reviews free-tier phase writes) + the LIVE remaining free-tier
    # backlog, so an operator can see the "free" alerts draining themselves at zero
    # token spend without re-running the sweep. Read-only + fail-safe, like every
    # probe above.
    try:
        from forecasting.cron_runner import read_free_tier_drain_state
        from forecasting.warnings import aggregate_open_warnings

        drain_state = read_free_tier_drain_state()
        remaining_free = int(
            (aggregate_open_warnings(ledger).get("headline") or {}).get("free", 0) or 0
        )
        free_tier_drain = {"last": drain_state or None, "remaining_free": remaining_free}
    except Exception:
        free_tier_drain = None

    # Gateway DUE-SWEEPER: is the sweeper closing the "due on the Desk vs actually
    # runs" gap between nightly cron runs? Read its config (enabled/interval), its
    # last-tick state file (the run_review_sweep writer), and the LIVE count of
    # reviews already due right now. Read-only + fail-safe, like every probe above.
    try:
        from forecasting.cron_runner import (
            read_review_sweeper_state,
            resolve_review_sweep_interval_minutes,
        )

        sweep_interval = resolve_review_sweep_interval_minutes()
        review_sweeper = {
            "enabled": sweep_interval > 0,
            "interval_minutes": sweep_interval,
            "last": read_review_sweeper_state() or None,
            "due_now": int(ledger.count_due_scheduled_reviews()),
        }
    except Exception:
        review_sweeper = None

    # Prediction-markets sibling (Arc 4): streaming readiness (ws lib +
    # cryptography + Kalshi key) and per-venue market-data availability. Read-
    # only + fail-safe, like every probe above; no network unless asked.
    try:
        from forecasting.pm.health import build_pm_doctor

        prediction_markets = build_pm_doctor()
    except Exception:
        prediction_markets = None

    # DURABILITY: the ledger IS the asset (months of judgment). Surface the last
    # backup age (WARN when >48h / none), the integrity verdict, and a row-count
    # snapshot so the lazy path can never silently lose the book. Read-only +
    # fail-safe, like every probe above.
    try:
        durability = _build_durability_section(ledger)
    except Exception:
        durability = None

    # SOURCE DIVERSITY (the monoculture guard): median distinct sources/question
    # + the single-source share across the book. The edge rests on ORTHOGONAL
    # signal, so a ledger collapsed to one source per question has nothing to
    # pool. Read-only + fail-safe, like every probe above.
    try:
        source_diversity = ledger.source_diversity_summary()
    except Exception:
        source_diversity = None

    # SECOND BRAIN: vault health — pages/orphans/broken-links/stale/tombstones,
    # section budget state, and the manifest's pending operator edits. Read-only
    # + fail-safe (the plugin import is call-time; a missing vault reports None).
    try:
        from plugins.obsidian.prune import build_vault_health
        from plugins.obsidian.vault import resolve_vault_path

        _vault = resolve_vault_path()
        vault_health = build_vault_health(_vault, ledger=ledger) if _vault else None
    except Exception:
        vault_health = None

    # PANEL-vs-SOLO ABLATION: does the 5-role panel + judge machinery actually
    # beat a lone panelist on the resolved book? A paired recenter-at-zero
    # bootstrap over resolved Brier-scoreable panels. Read-only + fail-safe;
    # honest n (a tiny/empty sample is reported as such). A weekly cron can
    # persist/surface this — the doctor is its read-only window.
    try:
        from forecasting.ablation_study import run_panel_vs_solo_ablation

        ablation = run_panel_vs_solo_ablation(ledger)
    except Exception:
        ablation = None

    # DEVIATION EDGE (UPGRADE 2): did the desk's named-edge deviations from the
    # market beat it, on resolved bets? The clean read on whether the whole
    # orthogonality thesis is paying off — n, win-rate, mean Brier delta + CI, and
    # a threshold recommendation (advisory only). Read-only + fail-safe.
    try:
        deviation_edge = ledger.deviation_bet_edge_report()
    except Exception:
        deviation_edge = None

    return {
        "product": PRODUCT_NAME,
        "process_version": PROCESS_VERSION,
        "generated_at": utc_now_iso(),
        "doctor_status": doctor_status,
        "tester_handoff_ready": pilot_ready,
        "claim_live_superforecasting": evidence_status.get("can_claim_live_superforecasting"),
        "triage_gate": triage_gate,
        "cron_health": cron_health,
        "operational_health": operational_health,
        "free_tier_drain": free_tier_drain,
        "review_sweeper": review_sweeper,
        "prediction_markets": prediction_markets,
        "durability": durability,
        "source_diversity": source_diversity,
        "vault_health": vault_health,
        "panel_vs_solo_ablation": ablation,
        "deviation_edge": deviation_edge,
        "hook_adherence": hook_adherence,
        "status": status,
        "cohort_scoreboard": cohort_scoreboard,
        "scores_audit": scores_audit,
        "pilot_report": pilot_report,
        "readiness": {
            "last": max(args.last, 0),
            "dataset_filter": args.dataset,
            "run_count": len(summaries),
            "inspected_backtest_run_ids": [row["id"] for row in rows],
            "evidence_status": evidence_status,
        },
        "required_exit_gates": {
            "pilot_ready_required": bool(args.require_pilot_ready),
            "readiness_required": bool(args.require_readiness),
            "pilot_ready": pilot_ready,
            "readiness_gaps": readiness_gaps,
        },
        # Recent LIVE forecasts that look like a 'one template x N' batch (same method
        # + reasoning_methods + rationale tail) rather than per-question deliberation.
        # A heuristic flag for review, never a block — see skills/ledger-interaction.
        "templated_batches": templated_batches,
        # SLICE 5: the three warning models folded into one view (alert backlog by
        # reason + saturation/hook issues + templated batches).
        "warnings_fold": warnings_fold,
    }


def _cmd_doctor(args: argparse.Namespace) -> None:
    report = _build_doctor_report(args)
    pilot_report = report["pilot_report"]
    readiness = report["readiness"]["evidence_status"]
    status = report["status"]
    summary = pilot_report["summary"]
    should_fail = (
        args.require_pilot_ready
        and not report["tester_handoff_ready"]
    ) or (
        args.require_readiness
        and bool(readiness.get("gaps"))
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        if should_fail:
            raise SystemExit(1)
        return

    print(
        f"doctor {report['doctor_status']}: "
        f"pilot {pilot_report['passed_checks']}/{pilot_report['total_checks']} checks, "
        f"readiness {readiness.get('verdict')}"
    )
    print(f"process_version: {report['process_version']}")
    print(f"ledger: {status['ledger_path']}")
    print(
        "book: "
        f"active={status['question_counts'].get('active', 0)} "
        f"reviews={status['review_queue_count']} "
        f"alerts={status['open_alert_count']} "
        f"schedules={status['enabled_scheduled_review_count']}/{status['scheduled_review_count']} "
        f"schedule_runs={summary.get('scheduled_review_run_count', 0)} "
        f"autopilot={status['active_autopilot_policy_count']}/{status['autopilot_policy_count']} "
        f"autopilot_runs={status['autopilot_run_count']} "
        f"pending_proposals={status['pending_autopilot_proposal_count']}"
    )
    print(
        "learning: "
        f"live_scores={summary['score_counts_by_origin'].get('live', 0)} "
        f"postmortems={summary['postmortem_count']} "
        f"lessons={status['active_calibration_lesson_count']}/{status['calibration_lesson_count']} "
        # Labelled: this is the live calibration-eligible cohort's Brier, NOT a
        # pooled all-artifact number. The full by-cohort board prints below.
        f"live_elig_brier={_format_metric(status['calibration_mean_brier'])}"
    )
    board = report.get("cohort_scoreboard")
    if board:
        _print_cohort_scoreboard(board)
    audit = report.get("scores_audit")
    if audit:
        counts = audit.get("counts") or {}
        artifact_n = counts.get("artifact_degenerate_import", 0)
        real_cont = counts.get("real_continuous_miss", 0)
        real_bin = counts.get("real_binary_miss", 0)
        total = sum(counts.values())
        print(
            f"scores audit: {total} pathological row(s) — "
            f"artifact_degenerate_import={artifact_n} "
            f"real_continuous_miss={real_cont} real_binary_miss={real_bin}"
            + (
                "  — propose `forecast scoreboard quarantine` (dry-run)"
                if audit.get("proposed_quarantine")
                else ""
            )
        )
    crux = status.get("crux_promotion") or {}
    print(
        "cruxes: "
        f"promoted={crux.get('promoted_total', 0)} "
        f"(from_panels={crux.get('promoted_from_panels', 0)}) "
        f"unpromoted_panel_cruxes={crux.get('unpromoted_panel_cruxes', 0)}"
        + (
            "  — run `forecast crux backfill --apply`"
            if crux.get("unpromoted_panel_cruxes", 0)
            else ""
        )
    )
    print(f"claim_live_superforecasting: {report['claim_live_superforecasting']}")
    operational = report.get("operational_health") or {}
    if operational:
        issues = operational.get("issues") or []
        print(
            "operational_health: "
            + ("healthy" if operational.get("healthy") else "degraded")
            + (" — " + ", ".join(f"{row['id']}={row['observed']}" for row in issues) if issues else "")
        )

    # SLICE 5 fold: one unified "warnings" line that folds all three models —
    # the alert_events backlog (by reason), the saturation/hook issues, and the
    # templated-batch clusters — so there is a single place to see every warning.
    fold = report.get("warnings_fold") or {}
    backlog = fold.get("alert_backlog") or {}
    backlog_groups = backlog.get("groups") or []
    sweep = fold.get("saturation") or {}
    under_saturated = sweep.get("under_saturated") or []
    fold_templated = fold.get("templated_batches") or []
    print(
        "warnings: "
        f"alerts={backlog.get('open_total', 0)} open across {backlog.get('group_count', 0)} reason(s); "
        f"saturation={len(under_saturated)} under/{sweep.get('checked', 0)} checked; "
        f"templated_batches={len(fold_templated)}"
    )
    for g in backlog_groups[:6]:
        tag = g.get("kind", "")
        if not g.get("auto_resolvable", True):
            tag += " NO_AUTO"
        print(f"  - alert x{g.get('count', 0):>3}  {(g.get('reason') or '')[:42]:<42} [{tag}]")
    for u in under_saturated[:4]:
        print(f"  - hook {u.get('question_id')}  {u.get('score')}/100 saturation")

    # Free-tier warning drain: the nightly zero-spend sweep's last result + the live
    # remaining free backlog (a sibling of cron_health).
    fdrain = report.get("free_tier_drain") or {}
    if fdrain:
        last = fdrain.get("last") or {}
        remaining = fdrain.get("remaining_free")
        remaining_text = f"{remaining} free alert(s) remain" if remaining is not None else "backlog unknown"
        if last:
            drained = f"last drain resolved {last.get('resolved', 0)}, errors {last.get('errors', 0)}"
            if last.get("cap_hit"):
                drained += f" (cap {last.get('cap')} hit — run `forecast warnings automode`)"
            print(f"free_tier_drain: {drained}; {remaining_text}")
        else:
            print(f"free_tier_drain: not yet run; {remaining_text}")

    # Gateway due-sweeper: whether the between-nightly-runs sweeper is enabled and
    # what its last tick did (a sibling of free_tier_drain / cron_health).
    rsweep = report.get("review_sweeper") or {}
    if rsweep:
        if not rsweep.get("enabled"):
            print(f"review_sweeper: disabled; {rsweep.get('due_now', 0)} review(s) due now")
        else:
            interval = rsweep.get("interval_minutes")
            due_now = rsweep.get("due_now", 0)
            last = rsweep.get("last") or {}
            if last:
                if last.get("running"):
                    tail = f"sweep running since {last.get('last_sweep_started_at') or 'unknown'}"
                elif last.get("ran"):
                    tail = (
                        f"last sweep proposed {last.get('proposals', last.get('refreshed', 0))}, "
                        f"alerts {last.get('alerts', 0)}"
                    )
                else:
                    tail = f"last tick skipped ({last.get('skipped_reason') or 'none due'})"
            else:
                tail = "not yet run"
            print(
                f"review_sweeper: every {interval}m; {due_now} due now; {tail}"
            )

    # Durability: last-backup age (WARN >48h/none) + integrity verdict + counts —
    # the ledger is the whole asset, so this is the line that can't go missing.
    dur = report.get("durability") or {}
    if dur:
        integ_ok = dur.get("integrity_ok")
        integ_txt = "ok" if integ_ok else f"VIOLATIONS ({len(dur.get('violations') or [])})"
        status = dur.get("backup_status")
        last = dur.get("last_backup") or {}
        if status == "missing":
            btxt = "NO BACKUP YET — run `forecast backup run`"
        else:
            age = last.get("age_hours")
            age_txt = f"{age:.1f}h ago" if isinstance(age, (int, float)) else "age unknown"
            warn = "  WARN>48h" if status == "stale" else ""
            btxt = f"last {age_txt} ({last.get('bytes', 0)} bytes){warn}"
        counts = dur.get("counts") or {}
        counts_txt = " ".join(f"{k}={v}" for k, v in counts.items())
        print(f"durability: backup {btxt}; integrity {integ_txt}; {counts_txt}".rstrip("; "))
        for v in (dur.get("violations") or [])[:3]:
            print(f"  - integrity: {v[:80]}")

    # Source diversity (monoculture guard): median distinct sources/question +
    # the single-source share. A median of 1.0 = the whole book reads one source.
    div = report.get("source_diversity") or {}
    if div and div.get("questions_with_evidence"):
        median = div.get("median_sources_per_question")
        pct = div.get("single_source_pct")
        median_txt = f"{median:.1f}" if isinstance(median, (int, float)) else "-"
        pct_txt = f"{pct * 100:.0f}%" if isinstance(pct, (int, float)) else "-"
        warn = "  WARN monoculture" if isinstance(median, (int, float)) and median <= 1.0 else ""
        print(
            f"source_diversity: median {median_txt} sources/question; "
            f"{div.get('single_source_question_count', 0)}/{div['questions_with_evidence']} "
            f"single-source ({pct_txt}){warn}"
        )

    # Second brain: vault health — page counts, rot signals, budget state, and
    # pending operator edits awaiting triage-gated ingestion.
    vh = report.get("vault_health") or {}
    if vh and vh.get("pages"):
        rot_bits = []
        for key in ("orphans", "broken_links", "stale", "contradictions"):
            if vh.get(key):
                rot_bits.append(f"{vh[key]} {key.replace('_', ' ')}")
        over = vh.get("budget_overflows") or {}
        if over:
            rot_bits.append(
                "budget over: "
                + ", ".join(f"{s} +{v.get('over_by')}" for s, v in over.items())
            )
        rot_txt = "; ".join(rot_bits) if rot_bits else "no rot flagged"
        pending = vh.get("operator_edits_pending", 0)
        pending_txt = (
            f"; {pending} operator edit(s) pending ingest" if pending else ""
        )
        print(
            f"vault_health: {vh.get('pages', 0)} pages "
            f"({vh.get('tombstones', 0)} tombstones); {rot_txt}{pending_txt}"
        )

    # Panel-vs-solo ablation: is the panel machinery earning its cost?
    ablation = report.get("panel_vs_solo_ablation")
    if ablation is not None:
        from forecasting.ablation_study import format_ablation_line

        print(format_ablation_line(ablation))

    edge = report.get("deviation_edge")
    if isinstance(edge, dict) and (edge.get("n") or edge.get("n_open")):
        delta = edge.get("mean_brier_delta")
        delta_txt = f"{delta:+.4f}" if isinstance(delta, (int, float)) else "-"
        wr = edge.get("win_rate")
        wr_txt = f"{wr:.0%}" if isinstance(wr, (int, float)) else "-"
        print(
            f"deviation_edge: {edge.get('n', 0)} scored / {edge.get('n_open', 0)} open "
            f"named-edge bets; win-rate {wr_txt}, mean Brier delta {delta_txt} "
            f"[{edge.get('status')}]"
        )
        print(f"  {edge.get('recommendation')}")

    batches = report.get("templated_batches") or []
    if batches:
        flagged = sum(b["count"] for b in batches)
        print(f"templated_batches: {len(batches)} cluster(s), {flagged} live forecasts share a template (review for real per-question reasoning)")
        for b in batches[:5]:
            print(f"  - x{b['count']} method={b['method'][:40] or '(none)'!r} e.g. {b['members'][0]['title']!r}")

    pilot_gaps = [check for check in pilot_report["checks"] if not check["passed"]]
    if pilot_gaps:
        print("pilot_gaps:")
        for check in pilot_gaps[:7]:
            print(
                f"  - {check['id']}: {check['observed']}/{check['required']} "
                f"- {check['recommended_action']}"
            )

    readiness_actions = list(readiness.get("next_actions") or [])
    if readiness_actions:
        print("readiness_gaps:")
        for item in readiness_actions[:7]:
            print(f"  - {item.get('requirement_id')}: {item.get('action')}")

    if not pilot_gaps and not readiness_actions:
        print("next_actions: none")

    if should_fail:
        raise SystemExit(1)


def _cmd_backup_run(args: argparse.Namespace) -> None:
    """`forecast backup run` — take an online backup + integrity check now.

    Thin over the BACKUP job type: enqueues a durable job, waits for it, and prints
    the ``{path, integrity, counts}`` result. Exits nonzero when the backup failed
    or reported integrity violations."""

    from forecasting.jobs.types.backup import read_job, start_job

    spec = {
        "db": getattr(args, "db", None),
        "dest_dir": getattr(args, "dest_dir", None),
        "keep_recent": getattr(args, "keep_recent", None),
        "weekly_weeks": getattr(args, "weekly_weeks", None),
    }
    job_id = start_job(spec, wait=True)
    job = read_job(job_id)
    result = job.get("result") or {}
    integrity = result.get("integrity")
    failed = job.get("status") != "done" or integrity != "ok"

    if getattr(args, "json", False):
        print(json.dumps(job, indent=2, sort_keys=True))
        if failed:
            raise SystemExit(1)
        return

    if job.get("status") != "done":
        print(f"backup failed: {job.get('error') or 'unknown error'}")
        raise SystemExit(1)

    print(f"backup {result.get('path')}  ({result.get('bytes')} bytes)")
    print(f"integrity: {integrity}")
    counts = result.get("counts") or {}
    if counts:
        print("counts: " + " ".join(f"{k}={v}" for k, v in counts.items()))
    retention = result.get("retention") or {}
    if retention.get("pruned_count"):
        print(f"retention: pruned {retention['pruned_count']} old backup(s), {retention.get('kept')} kept")
    if integrity != "ok":
        for v in (result.get("violations") or [])[:5]:
            print(f"  violation: {v}")
        raise SystemExit(1)


def _cmd_backup_list(args: argparse.Namespace) -> None:
    """`forecast backup list` — the existing ledger backups, newest first."""

    ledger = _ledger(args)
    rows = ledger.list_backups(getattr(args, "dest_dir", None))
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, sort_keys=True))
        return
    if not rows:
        print(f"no backups yet in {ledger.default_backup_dir()} — run `forecast backup run`")
        return
    print(f"{len(rows)} backup(s) in {ledger.default_backup_dir()}:")
    for r in rows:
        print(f"  {r['created_at']}  {r['bytes']:>10} bytes  {r['path']}")


def _cmd_config_doctor(args: argparse.Namespace) -> None:
    """`forecast config doctor` — read-only report over the layered config loader.

    Surfaces set-but-unknown (typo) vars, known-but-unset defaults in effect,
    secret presence (never values), file-vs-env precedence conflicts, and the
    Kalshi two-var trap. Delegates to :mod:`forecasting.appconfig` so the report
    logic stays pure and testable."""
    from forecasting import appconfig

    report = appconfig.build_doctor_report(appconfig.get_config())
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return
    print(appconfig.render_doctor_report(report))


def _cmd_lifecycle(args: argparse.Namespace) -> None:
    from forecasting.lifecycle import lifecycle_status, run_lifecycle

    ledger = _ledger(args)
    if args.limit < 1:
        raise SystemExit("--limit must be positive")
    results = []
    if args.action == "review":
        if not args.question_id or not args.reason or not args.source:
            raise SystemExit("review requires a question ID, --reason, and --source")
        if getattr(args, "state", None):
            from forecasting.settlement_reviews import record_review
            review = record_review(ledger, question_id=args.question_id, state=args.state,
                reason=args.reason, source=args.source, next_action=args.next_action,
                owner=args.owner, revisit_at=args.revisit_at, now=args.now)
            print(json.dumps(review, indent=2))
            return
        from forecasting.models import parse_timestamp
        revisit = parse_timestamp(args.revisit_at, field_name="revisit_at")
        question = ledger.get_question(args.question_id)
        note = ledger.add_analyst_note(
            question_id=question.id, body=args.reason, headline="Settlement review",
            generator="operator", forecast_id=question.current_forecast_id,
            metadata={"lifecycle_review": True, "source": args.source, "revisit_at": revisit},
        )
        print(json.dumps(note, indent=2) if args.json else f"Recorded review {note['id']}: {args.reason}")
        return
    if args.action == "run":
        import uuid
        results = run_lifecycle(ledger, owner=f"cli-lifecycle:{uuid.uuid4().hex[:12]}", now=args.now, limit=args.limit)
    report = lifecycle_status(ledger, now=args.now)
    report["results"] = results
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Forecast lifecycle")
        print("; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in report["counts"].items()))
        for row in (report["unfinished"] + report["attention"] + report["limitations"])[:args.limit]:
            print(f"  {row['question_id']} {row['reason']}: {row['title']}")
            if row.get("review"):
                print(f"    last review: {row['review']['body']}")
                print(f"    source: {row['review']['source']}; revisit: {row['review']['revisit_at'] or 'not set'}")
        for review in report['settlement_reviews'][:args.limit]:
            print(f"  {review['question_id']} [{review['state']}] owner={review['owner']} next={review['revisit_at'] or 'no retry'}")
            print(f"    {review['next_action']}")
        for row in report["tasks"][:args.limit]:
            print(f"  task {row['id']} {row['status']} ({row['attempt_count']}/{row['max_attempts']}): {row.get('error') or 'awaiting worker'}")
        print("Review settlement evidence with `forecast protocol <id> --stage resolve`; confirm outcomes explicitly.")
        print("Recover confirmed score/postmortem handoffs with `forecast lifecycle run`.")
    if any(row.get("status") != "completed" for row in results):
        raise SystemExit(1)
