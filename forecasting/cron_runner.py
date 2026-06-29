"""No-agent cron runner for forecast scheduled reviews."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from forecasting.learning import is_learning_review_reason
from forecasting.ledger import ForecastLedger, allow_ledger_writes_decorator


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@allow_ledger_writes_decorator("cron_runner.run_due_reviews")
def run_due_reviews(
    *,
    db_path: str | None = None,
    now: str | None = None,
    auto_score: bool = False,
    auto_postmortem: bool = False,
    thesis_aggregate: bool = False,
    synthesize_lessons: bool | None = None,
    obsidian_sync: bool = False,
    reconcile_alerts: bool = True,
    propose_resolutions: bool = True,
    score_market_nightly: bool = True,
    reforecast_runner: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> str:
    """Run due forecast schedule rows and return a concise alert report.

    With ``thesis_aggregate`` (or ``FORECAST_THESIS_AGGREGATE``), a trailing
    phase re-aggregates every active thesis AFTER the review sweep — so theses +
    their entity suitabilities lag the members' fresh runs automatically.

    ``synthesize_lessons`` closes the calibration learning loop on a cadence:
    ``True`` runs :meth:`ForecastLedger.synthesize_bias_lessons` every sweep,
    ``False`` never, and the default ``None`` runs it exactly when this sweep
    minted new score records or postmortems (resolutions accrued, so the bias
    measurement has fresh data). Safe to run eagerly — synthesis is heavily
    gated internally (ESS, CI, FDR, shrinkage) and emits nothing on thin data.

    ``obsidian_sync`` (or ``FORECAST_OBSIDIAN_SYNC``) republishes the desk's
    learnings into the Obsidian vault after the sweep, so resolutions,
    postmortems, and fresh lessons land in the user's notes without a manual
    `obsidian sync`. Lazy plugin import + vault checks — a missing plugin or
    vault degrades to a no-op note, never an error.
    """

    ledger = ForecastLedger(db_path)
    results = ledger.run_due_scheduled_reviews(
        now=now,
        auto_score=auto_score,
        auto_postmortem=auto_postmortem,
    )
    alert_rows = []
    for result in results:
        for alert in result["alerts"]:
            alert_rows.append(alert)

    sections: list[str] = []
    score_events = [alert for alert in alert_rows if alert.reason.startswith("score_created:")]
    postmortem_events = [alert for alert in alert_rows if alert.reason.startswith("postmortem_created:")]
    if results and alert_rows:
        learning_review_events = [
            alert for alert in alert_rows if is_learning_review_reason(alert.reason)
        ]
        lines = [
            "Forecast self-check alerts",
            f"scheduled_reviews: {len(results)}",
            "run_ids: " + ", ".join(result["run"]["id"] for result in results if result.get("run")),
            f"alerts: {len(alert_rows)}",
            f"scores_created: {len(score_events)}",
            f"postmortems_created: {len(postmortem_events)}",
            f"learning_reviews: {len(learning_review_events)}",
            "",
        ]
        for alert in alert_rows:
            lines.append(f"- {alert.severity} {alert.scope_ref}: {alert.reason}")
            lines.append(f"  action: {alert.recommended_action}")
        sections.append("\n".join(lines) + "\n")

    # Autonomous reforecast pass (opt-in via `cycle run --agent`): drive an LLM update
    # over the questions this sweep flagged, BEFORE thesis aggregation + lesson
    # synthesis so those phases reflect the fresh snapshots. The runner is INJECTED by
    # the CLI layer — cron_runner/ledger never import run_agent (layer purity). It
    # validates + gates each question itself and returns per-question result dicts.
    if reforecast_runner is not None:
        due_ids: list[str] = []
        seen: set[str] = set()
        for alert in alert_rows:
            qid = getattr(alert, "scope_ref", None)
            # only QUESTION-scoped alerts are reforecast targets — a domain / topic /
            # portfolio / global alert's scope_ref is not a question id.
            if getattr(alert, "scope_type", None) != "question" or not qid or qid in seen:
                continue
            reason = getattr(alert, "reason", "") or ""
            if reason.startswith(("score_created:", "postmortem_created:")):
                continue  # bookkeeping events, not reforecast triggers (a question-
                # scoped domain_error_profile_applies, by contrast, IS a real trigger)
            seen.add(qid)
            due_ids.append(qid)
        if due_ids:
            try:
                ref_results = reforecast_runner(due_ids)
            except Exception as exc:  # never break the sweep on the reforecast pass
                sections.append(f"Autonomous reforecast\nERROR: {exc}\n")
                ref_results = []
            if ref_results:
                by_status: dict[str, int] = {}
                for r in ref_results:
                    by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
                lines = [
                    "Autonomous reforecast",
                    "reforecast " + str(len(ref_results)) + ": " + ", ".join(f"{k} {v}" for k, v in sorted(by_status.items())),
                    "",
                ]
                for r in ref_results:
                    lines.append(f"- {r.get('status')} {r.get('question_id')}: {r.get('detail', '')}")
                sections.append("\n".join(lines) + "\n")

    # Trailing thesis-aggregation phase: theses (+ their entity suitabilities)
    # re-aggregate after the member review sweep.
    if thesis_aggregate:
        try:
            summary = ledger.aggregate_all_theses(now=now)
        except Exception as exc:  # never break the unattended sweep on aggregation
            sections.append(f"Thesis aggregation\nERROR: {exc}\n")
            summary = {"count": 0, "results": []}
        if summary["count"]:
            rows = summary["results"]
            ok = [row for row in rows if row.get("ok")]
            withheld = [row for row in ok if row.get("withheld")]
            failed = [row for row in rows if not row.get("ok")]
            lines = [
                "Thesis aggregation",
                f"theses: {summary['count']}  committed: {len(ok) - len(withheld)}  "
                f"withheld: {len(withheld)}  failed: {len(failed)}",
                "",
            ]
            for row in rows:
                if not row.get("ok"):
                    lines.append(f"- {row['id']}: ERROR {row.get('error')}")
                    continue
                health = row.get("health")
                health_text = f"{health:.0%}" if isinstance(health, (int, float)) else "withheld"
                lines.append(
                    f"- {row['id']}: health {health_text} "
                    f"({row.get('entity_count', 0)} entities, {row.get('trigger_count', 0)} triggers)"
                )
            sections.append("\n".join(lines) + "\n")

    # Trailing lesson-synthesis phase: when this sweep minted scores or
    # postmortems (or the caller forced it), re-measure signed calibration
    # bias and update the lesson set. Internally gated — emits nothing on
    # thin/noisy data — so the cadence can be eager without over-biasing.
    run_synthesis = (
        synthesize_lessons
        if synthesize_lessons is not None
        else bool(score_events or postmortem_events)
    )
    if run_synthesis:
        try:
            synth_results = ledger.synthesize_bias_lessons(now=now)
        except Exception as exc:  # never break the cron sweep on synthesis
            sections.append(f"Lesson synthesis\nERROR: {exc}\n")
        else:
            acted = [
                row
                for row in synth_results
                if (row.get("action") or {}).get("written")
                or (row.get("action") or {}).get("retired")
            ]
            if acted:
                lines = ["Lesson synthesis", f"scopes_measured: {len(synth_results)}", ""]
                for row in acted:
                    scope_label = row.get("scope_ref") or row.get("scope_type") or "global"
                    action = row.get("action") or {}
                    bits = []
                    if action.get("written"):
                        bits.append(f"lesson {action.get('lesson_status', 'written')}")
                    if action.get("retired"):
                        bits.append(f"retired {len(action['retired'])}")
                    lines.append(f"- {scope_label}: {', '.join(bits)}")
                sections.append("\n".join(lines) + "\n")

    # Trailing vault-publish phase (opt-in): keep the user's Obsidian vault
    # tracking the desk. Plugin and vault are both optional — degrade quietly.
    if obsidian_sync:
        try:
            from plugins.obsidian.sync import sync_learnings
            from plugins.obsidian.vault import resolve_vault_path
        except ImportError:
            sections.append("Obsidian sync\nskipped: obsidian plugin not available\n")
        else:
            vault = resolve_vault_path()
            if vault is None:
                sections.append("Obsidian sync\nskipped: no vault (set OBSIDIAN_VAULT_PATH)\n")
            else:
                try:
                    summary = sync_learnings(vault, db=str(ledger.db_path))
                except Exception as exc:  # never break the cron sweep on publishing
                    sections.append(f"Obsidian sync\nERROR: {exc}\n")
                else:
                    sections.append(
                        "Obsidian sync\n"
                        f"published {summary['questions']} question dossier(s) and "
                        f"{summary['lessons']} lesson(s) -> {summary['vault']}\n"
                    )

    # Trailing alert-reconciliation phase: auto-acknowledge alerts whose
    # source-change has already been consumed (fresh evidence imported AND a
    # forecast committed since the alert fired), so the autonomous loop closes the
    # alert lifecycle instead of leaving the operator with stale, fatigue-inducing
    # alerts. Conservative — only clearly-consumed alerts are touched.
    if reconcile_alerts:
        try:
            recon = ledger.reconcile_alerts(now=now)
        except Exception as exc:  # never break the sweep on reconciliation
            sections.append(f"Alert reconciliation\nERROR: {exc}\n")
        else:
            if recon["reconciled_count"]:
                sections.append(
                    "Alert reconciliation\n"
                    f"acknowledged {recon['reconciled_count']} consumed alert(s); "
                    f"{len(recon['still_open'])} still open\n"
                )

    # Trailing resolver-proposal phase: run resolution rules + raise a confirm-me
    # alert for any question now DETERMINABLY resolvable from ingested data. The
    # resolver framework's autonomy — the desk surfaces "ready to resolve, YES"
    # itself (propose-only; the operator confirms). Deduped, so no re-alert spam.
    if propose_resolutions:
        try:
            proposed = ledger.propose_due_resolutions()
        except Exception as exc:  # never break the sweep on proposal
            sections.append(f"Resolution proposals\nERROR: {exc}\n")
        else:
            raised = [item for item in proposed if item.get("alerted")]
            if raised:
                sections.append(
                    "Resolution proposals\n"
                    f"proposed {len(raised)} resolution(s) for confirmation\n"
                )

    # Trailing market-nightly scoring phase (AIA P2.1): score any pending
    # foreknowledge-proof benchmark entry whose market has since RESOLVED. ONLY
    # scoring runs on the cycle — SAMPLING (which would hit a market source) stays
    # explicit/opt-in via the CLI, never the unattended sweep. Best-effort: a hiccup
    # must never break the cycle, and score_matured is idempotent.
    if score_market_nightly:
        try:
            from forecasting.market_nightly import score_matured

            matured = score_matured(ledger, now=now)
        except Exception as exc:  # never break the sweep on benchmark scoring
            sections.append(f"Market-nightly scoring\nERROR: {exc}\n")
        else:
            # Only announce what was NEWLY scored this sweep, so a fully-scored set
            # does not re-emit the same alert on every cron run.
            if matured.get("n_newly_scored"):
                sections.append(
                    "Market-nightly scoring\n"
                    f"scored {matured['n_newly_scored']} newly-matured benchmark entr(ies); "
                    f"{matured['n_still_pending']} still pending\n"
                )

    return "\n".join(sections)


def build_warning_runners(
    ledger: ForecastLedger,
    *,
    now: str | None = None,
    reforecast_runner: Callable[[Any, Any], Any] | None = None,
):
    """Wire the warning dispatcher's injected runners to the REAL gated paths.

    Shared by the CLI (`forecast warnings resolve/automode`), this cron phase,
    the gateway RPCs, and the agent tool so the "what counts as real gated work"
    judgment lives in exactly one place. Each runner performs genuine gated work
    and signals success by returning a truthy result; the dispatcher acks ONLY on
    that truthy result, so the load-bearing rule holds (no bare ack to drop the
    count).

    ``reforecast_runner`` (the LLM update-stage pass) is INJECTED by the caller:
    the CLI passes its `--agent` closure, while the cron/gateway/tool paths leave
    it ``None`` (so REFORECAST alerts are honestly reported "skipped" / left OPEN
    rather than bare-acked — the heavy LLM pass is opt-in, never automatic).
    """
    from forecasting.warnings import ResolutionRunners

    def autopilot_runner(led, warning):  # MATERIAL_CHANGE
        if warning.scope_type != "question" or not warning.scope_ref:
            return None
        result = led.run_autopilot(
            warning.scope_ref,
            now=now,
            trigger_reason=f"warnings:{warning.reason}"[:120],
        )
        # Real gated work = autopilot re-checked the watched source(s), recorded a
        # source snapshot, and possibly proposed/committed an update. A hard
        # "failed" status (required source down) leaves the alert OPEN to resurface.
        if not result or result.get("status") == "failed":
            return None
        return result

    def score_runner(led, warning):  # SCORE
        if warning.scope_type != "question" or not warning.scope_ref:
            return None
        # The gated work for a score_due alert: compute + persist the resolved
        # question's Brier/log score. score_question writes a real score record
        # (SQLite write-gated) and returns a truthy ScoreRecord; it raises if the
        # question can't be scored yet (no snapshot / unconfirmed resolution) ->
        # the dispatcher catches it and leaves the alert OPEN. Idempotent: an
        # already-scored question returns its existing score (truthy), so acking
        # reflects real scoring work that exists, never a bare close to drop the
        # count.
        return led.score_question(warning.scope_ref)

    def postmortem_runner(led, warning):  # POSTMORTEM
        if warning.scope_type != "question" or not warning.scope_ref:
            return None
        # The gated work for a postmortem_due alert: score the resolved question
        # and write a *real* postmortem record. Mirror self_check's auto_postmortem
        # path (ledger.self_check ... auto_postmortem=True) so the automode-written
        # postmortem carries the same deterministic structured signal — the
        # derived lesson + calibration adjustment — instead of a shallow
        # hard-coded placeholder. Both helpers are non-LLM: they key off the
        # score's Brier / calibration-eligibility / sharpness, returning "" / {}
        # when no real lesson is warranted (so create_postmortem only creates a
        # tentative calibration lesson when the score actually justifies one).
        # create_postmortem raises if the question can't yet be scored -> the
        # dispatcher catches it and leaves the alert OPEN.
        score = led.score_question(warning.scope_ref)
        question = led.get_question(warning.scope_ref)
        return led.create_postmortem(
            question_id=warning.scope_ref,
            summary="Auto-created by warnings resolution after confirmed resolution and scoring.",
            what_happened="The forecast resolved and was scored while draining the open-warning backlog.",
            what_was_expected="See the linked forecast snapshot and score record for the prior probability.",
            lesson=led._auto_postmortem_lesson(question, score),
            calibration_adjustment=led._auto_postmortem_adjustment(question, score),
        )

    return ResolutionRunners(
        reforecast_runner=reforecast_runner,
        autopilot_runner=autopilot_runner,
        score_runner=score_runner,
        postmortem_runner=postmortem_runner,
    )


def run_warning_resolution(
    *,
    db_path: str | None = None,
    ledger: ForecastLedger | None = None,
    now: str | None = None,
    limit: int | None = None,
    reason: str | None = None,
    scope: str | None = None,
    dry_run: bool = False,
    reconcile: bool = True,
    runners: Any = None,
    reforecast_runner: Callable[[Any, Any], Any] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Drain the open ``alert_events`` backlog as a reusable, GATED, INTERRUPTIBLE
    phase — the factored loop behind `forecast warnings automode`, the
    ``forecast.warnings.automode.run`` background job, and the agent tool.

    * GATED: every mutating pass runs inside :func:`allow_ledger_writes`; the
      injected runners (autopilot / score / optional reforecast) are the only
      things that move a forecast, and the dispatcher acks ONLY on their truthy
      result. ``dry_run=True`` opens NO write context and acks NOTHING — it just
      returns the per-alert plan via :func:`forecasting.warnings.plan_alert`.
    * INTERRUPTIBLE: ``should_cancel`` is polled before each alert; on a set flag
      the loop stops cleanly and returns ``cancelled=True`` with the partial
      tally (the alerts already resolved stay resolved — real work is durable).
    * STREAMING: ``progress`` receives a dict per phase
      (``{"phase": "start"|"alert"|"reconcile"|"done", "done", "total",
      "remaining", "alert_id", "reason", "status"}``) so a caller can render a
      live heartbeat (the gateway turns these into events).

    Returns a structured summary dict.
    """
    from forecasting import warnings as fwarn
    from forecasting.ledger import allow_ledger_writes

    led = ledger if ledger is not None else ForecastLedger(db_path)
    if runners is None:
        runners = build_warning_runners(led, now=now, reforecast_runner=reforecast_runner)

    open_warnings = fwarn.select_open_warnings(led, scope=scope, reason=reason, limit=limit)
    total = len(open_warnings)

    def _emit(payload: dict[str, Any]) -> None:
        if progress is not None:
            try:
                progress(payload)
            except Exception:  # a progress sink must never break the sweep
                pass

    def _is_cancelled() -> bool:
        if should_cancel is None:
            return False
        try:
            return bool(should_cancel())
        except Exception:
            return False

    _emit({"phase": "start", "done": 0, "total": total, "remaining": total, "dry_run": dry_run})

    results: list[dict[str, Any]] = []
    cancelled = False

    if dry_run:
        # Pure preview: no write context, no acks, no runner spend.
        for index, warning in enumerate(open_warnings, start=1):
            if _is_cancelled():
                cancelled = True
                break
            entry = fwarn.plan_alert(warning, runners)
            results.append(entry)
            _emit({
                "phase": "alert", "done": index, "total": total,
                "remaining": total - index, "alert_id": warning.id,
                "reason": warning.reason, "status": entry["planned"],
            })
        tally: dict[str, int] = {}
        for entry in results:
            tally[entry["planned"]] = tally.get(entry["planned"], 0) + 1
        _emit({"phase": "done", "done": len(results), "total": total, "remaining": 0,
               "cancelled": cancelled, "dry_run": True})
        return {
            "dry_run": True,
            "cancelled": cancelled,
            "processed": len(results),
            "total": total,
            "results": results,
            "tally": tally,
            "reconcile": None,
        }

    reconcile_result: dict[str, Any] | None = None
    with allow_ledger_writes(reason="forecast_warnings_resolution"):
        for index, warning in enumerate(open_warnings, start=1):
            if _is_cancelled():
                cancelled = True
                break
            result = fwarn.resolve_alert(led, warning, runners=runners, now=now)
            results.append(result)
            _emit({
                "phase": "alert", "done": index, "total": total,
                "remaining": total - index, "alert_id": warning.id,
                "reason": warning.reason, "status": result.get("status"),
            })
        # Only reconcile if we ran the full backlog (a cancel leaves the sweep
        # mid-flight; reconciling then could ack alerts we never got to inspect).
        if reconcile and not cancelled:
            _emit({"phase": "reconcile", "done": len(results), "total": total, "remaining": 0})
            reconcile_result = led.reconcile_alerts(now=now)

    tally = {}
    for result in results:
        status = result.get("status", "?")
        tally[status] = tally.get(status, 0) + 1
    _emit({"phase": "done", "done": len(results), "total": total, "remaining": 0,
           "cancelled": cancelled, "dry_run": False})
    return {
        "dry_run": False,
        "cancelled": cancelled,
        "processed": len(results),
        "total": total,
        "results": results,
        "tally": tally,
        "reconcile": reconcile_result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run due forecast scheduled reviews")
    parser.add_argument("--db")
    parser.add_argument("--now")
    parser.add_argument("--auto-score", action="store_true")
    parser.add_argument("--auto-postmortem", action="store_true")
    parser.add_argument("--thesis-aggregate", action="store_true")
    parser.add_argument(
        "--synthesize-lessons", action="store_true",
        help="Force calibration-lesson synthesis every sweep (default: runs when new scores/postmortems accrue)",
    )
    parser.add_argument(
        "--no-synthesize-lessons", action="store_true",
        help="Never run lesson synthesis from this cron sweep",
    )
    parser.add_argument(
        "--obsidian-sync", action="store_true",
        help="Republish lessons + question dossiers to the Obsidian vault after the sweep",
    )
    args = parser.parse_args(argv)
    db_path = args.db or os.getenv("FORECAST_LEDGER_DB") or None
    synthesize: bool | None = None
    if args.no_synthesize_lessons or _env_flag("FORECAST_NO_LESSON_SYNTHESIS"):
        synthesize = False
    elif args.synthesize_lessons or _env_flag("FORECAST_SYNTHESIZE_LESSONS"):
        synthesize = True
    text = run_due_reviews(
        db_path=db_path,
        now=args.now,
        auto_score=args.auto_score or _env_flag("FORECAST_AUTO_SCORE"),
        auto_postmortem=args.auto_postmortem or _env_flag("FORECAST_AUTO_POSTMORTEM"),
        thesis_aggregate=args.thesis_aggregate or _env_flag("FORECAST_THESIS_AGGREGATE"),
        synthesize_lessons=synthesize,
        obsidian_sync=args.obsidian_sync or _env_flag("FORECAST_OBSIDIAN_SYNC"),
    )
    if text:
        print(text, end="")
    return 0


def install_script(
    script_path: Path,
    *,
    db_path: str | None = None,
    auto_score: bool = False,
    auto_postmortem: bool = False,
    thesis_aggregate: bool = False,
) -> None:
    """Install the small script used by no-agent forecast cron jobs."""

    script_path.parent.mkdir(parents=True, exist_ok=True)
    args = []
    if db_path:
        args.extend(["--db", db_path])
    if auto_score:
        args.append("--auto-score")
    if auto_postmortem:
        args.append("--auto-postmortem")
    if thesis_aggregate:
        args.append("--thesis-aggregate")
    script_path.write_text(
        "\n".join(
            [
                "from forecasting.cron_runner import main",
                "",
                "if __name__ == '__main__':",
                f"    raise SystemExit(main({args!r}))",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
