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
) -> str:
    """Run due forecast schedule rows and return a concise alert report.

    With ``thesis_aggregate`` (or ``FORECAST_THESIS_AGGREGATE``), a trailing
    phase re-aggregates every active thesis AFTER the review sweep — so theses +
    their entity suitabilities lag the members' fresh runs automatically.
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
    if results and alert_rows:
        score_events = [alert for alert in alert_rows if alert.reason.startswith("score_created:")]
        postmortem_events = [alert for alert in alert_rows if alert.reason.startswith("postmortem_created:")]
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
        summary = ledger.aggregate_all_theses(now=now)
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

    return "\n".join(sections)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run due forecast scheduled reviews")
    parser.add_argument("--db")
    parser.add_argument("--now")
    parser.add_argument("--auto-score", action="store_true")
    parser.add_argument("--auto-postmortem", action="store_true")
    parser.add_argument("--thesis-aggregate", action="store_true")
    args = parser.parse_args(argv)
    db_path = args.db or os.getenv("FORECAST_LEDGER_DB") or None
    text = run_due_reviews(
        db_path=db_path,
        now=args.now,
        auto_score=args.auto_score or _env_flag("FORECAST_AUTO_SCORE"),
        auto_postmortem=args.auto_postmortem or _env_flag("FORECAST_AUTO_POSTMORTEM"),
        thesis_aggregate=args.thesis_aggregate or _env_flag("FORECAST_THESIS_AGGREGATE"),
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
