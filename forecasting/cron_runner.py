"""No-agent cron runner for forecast scheduled reviews."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from forecasting.learning import is_learning_review_reason
from forecasting.ledger import ForecastLedger


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


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

    return "\n".join(sections)


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
