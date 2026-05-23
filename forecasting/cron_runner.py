"""No-agent cron runner for forecast scheduled reviews."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from forecasting.ledger import ForecastLedger


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def run_due_reviews(
    *,
    db_path: str | None = None,
    now: str | None = None,
    auto_score: bool = False,
    auto_postmortem: bool = False,
) -> str:
    """Run due forecast schedule rows and return a concise alert report."""

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
    if not results or not alert_rows:
        return ""

    lines = [
        "Forecast self-check alerts",
        f"scheduled_reviews: {len(results)}",
        f"alerts: {len(alert_rows)}",
        "",
    ]
    for alert in alert_rows:
        lines.append(f"- {alert.severity} {alert.scope_ref}: {alert.reason}")
        lines.append(f"  action: {alert.recommended_action}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run due forecast scheduled reviews")
    parser.add_argument("--db")
    parser.add_argument("--now")
    parser.add_argument("--auto-score", action="store_true")
    parser.add_argument("--auto-postmortem", action="store_true")
    args = parser.parse_args(argv)
    db_path = args.db or os.getenv("FORECAST_LEDGER_DB") or None
    text = run_due_reviews(
        db_path=db_path,
        now=args.now,
        auto_score=args.auto_score or _env_flag("FORECAST_AUTO_SCORE"),
        auto_postmortem=args.auto_postmortem or _env_flag("FORECAST_AUTO_POSTMORTEM"),
    )
    if text:
        print(text, end="")
    return 0


def install_script(
    script_path: Path,
    *,
    auto_score: bool = False,
    auto_postmortem: bool = False,
) -> None:
    """Install the small script used by no-agent forecast cron jobs."""

    script_path.parent.mkdir(parents=True, exist_ok=True)
    args = []
    if auto_score:
        args.append("--auto-score")
    if auto_postmortem:
        args.append("--auto-postmortem")
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
