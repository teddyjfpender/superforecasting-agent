"""Forecast-native integration with the inherited cron runtime."""

from __future__ import annotations

from typing import Any

from hermes_constants import get_hermes_home

from forecasting.cron_runner import install_script, install_warning_automode_script


FORECAST_CRON_SCRIPT = "forecast_self_check.py"
WARNING_AUTOMODE_CRON_SCRIPT = "forecast_warning_automode.py"
WARNING_AUTOMODE_CRON_NAME = "Forecast warning automode"


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


def install_warning_automode_cron(
    *,
    schedule: str = "every 30 minutes",
    name: str = WARNING_AUTOMODE_CRON_NAME,
    deliver: str = "local",
    profile: str | None = None,
    db_path: str | None = None,
    agent: bool = True,
    paid_budget: int | None = None,
    paid_min_interval_hours: float | None = None,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """START (install) the continuous warning-automode cron job — Shape B.

    Mirrors :func:`install_forecast_cron`: own cadence, clean start/stop. It is a
    no-agent job whose script drives :func:`forecasting.cron_runner.run_warning_automode`
    on every tick — the FREE tier sweeps unbudgeted at zero token spend, while the
    PAID tier (reforecast + evidence_collection) runs BOUNDED by ``paid_budget``
    (per-cycle agent-run cap, default 3) and ``paid_min_interval_hours`` (default
    6h), both config-tunable.

    ``agent`` wires the paid (LLM) tier; pass ``agent=False`` for a free-tier-only
    continuous loop. Idempotent START: any prior job with the same name is removed
    first so re-installing re-arms cleanly instead of stacking duplicates.
    """

    # Clean start: remove any prior automode job of the same name before re-arming.
    remove_warning_automode_cron(name=name)

    scripts_dir = get_hermes_home() / "scripts"
    script_path = scripts_dir / WARNING_AUTOMODE_CRON_SCRIPT
    install_warning_automode_script(
        script_path,
        db_path=db_path,
        agent=agent,
        paid_budget=paid_budget,
        paid_min_interval_hours=paid_min_interval_hours,
        model=model,
        provider=provider,
        max_iterations=max_iterations,
    )

    from cron.jobs import create_job

    return create_job(
        prompt="Run the continuous warning-automode sweep (free tier + bounded paid tier).",
        schedule=schedule,
        name=name,
        deliver=deliver,
        script=WARNING_AUTOMODE_CRON_SCRIPT,
        profile=profile,
        no_agent=True,
    )


def remove_warning_automode_cron(*, name: str = WARNING_AUTOMODE_CRON_NAME) -> int:
    """STOP (uninstall) the continuous warning-automode cron job(s).

    Returns the number of jobs removed (0 if none was installed). Removes every
    job matching the automode name OR script, so a clean stop never leaves a
    dangling duplicate behind.
    """
    from cron.jobs import list_jobs, remove_job

    removed = 0
    for job in list_jobs(include_disabled=True):
        if (job.get("name") or "") == name or job.get("script") == WARNING_AUTOMODE_CRON_SCRIPT:
            if remove_job(job["id"]):
                removed += 1
    return removed


def warning_automode_cron_status(*, name: str = WARNING_AUTOMODE_CRON_NAME) -> dict[str, Any]:
    """STATUS of the continuous warning-automode cron job.

    Returns ``{"installed": bool, "job": <job or None>, "last_paid_run_at": <iso
    or None>}`` — the last-paid-run timestamp is read from the same state file the
    runner's min-interval gate uses, so an operator can see when the paid tier last
    spent budget.
    """
    from cron.jobs import list_jobs

    job = None
    for candidate in list_jobs(include_disabled=True):
        if (candidate.get("name") or "") == name or candidate.get("script") == WARNING_AUTOMODE_CRON_SCRIPT:
            job = candidate
            break

    from forecasting.cron_runner import _read_automode_state

    state = _read_automode_state()
    return {
        "installed": job is not None,
        "job": job,
        "last_paid_run_at": state.get("last_paid_run_at"),
    }
