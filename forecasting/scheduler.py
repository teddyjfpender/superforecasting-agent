"""Forecast-native integration with the inherited cron runtime."""

from __future__ import annotations

from typing import Any

from hermes_constants import get_hermes_home

from forecasting.cron_runner import install_script


FORECAST_CRON_SCRIPT = "forecast_self_check.py"


def install_forecast_cron(
    *,
    schedule: str,
    name: str = "Forecast self-check",
    deliver: str = "local",
    profile: str | None = None,
    db_path: str | None = None,
    auto_score: bool = False,
    auto_postmortem: bool = False,
    thesis_aggregate: bool = False,
) -> dict[str, Any]:
    """Install a no-agent cron job for forecast schedule execution."""

    scripts_dir = get_hermes_home() / "scripts"
    script_path = scripts_dir / FORECAST_CRON_SCRIPT
    install_script(
        script_path,
        db_path=db_path,
        auto_score=auto_score,
        auto_postmortem=auto_postmortem,
        thesis_aggregate=thesis_aggregate,
    )

    from cron.jobs import create_job

    return create_job(
        prompt="Run due forecast scheduled reviews.",
        schedule=schedule,
        name=name,
        deliver=deliver,
        script=FORECAST_CRON_SCRIPT,
        profile=profile,
        no_agent=True,
    )
