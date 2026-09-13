"""Forecast-native integration with the inherited cron runtime."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from superforecasting_agent.constants import get_agent_home

from forecasting.cron_runner import (
    install_script,
    install_source_estimator_script,
    install_warning_automode_script,
)


FORECAST_CRON_SCRIPT = "forecast_self_check.py"
FORECAST_CRON_NAME = "Forecast self-check"
# Nightly (08:00) is the documented forecast-refresh cadence — see
# website/docs guides. A cron expression needs croniter; ensure_default_routines
# is fail-open so a missing dependency degrades to "no auto-install", never an error.
DEFAULT_FORECAST_CRON_SCHEDULE = "0 8 * * *"
WARNING_AUTOMODE_CRON_SCRIPT = "forecast_warning_automode.py"
WARNING_AUTOMODE_CRON_NAME = "Forecast warning automode"
SOURCE_ESTIMATOR_CRON_SCRIPT = "forecast_source_estimator.py"
SOURCE_ESTIMATOR_CRON_NAME = "Forecast source estimator"
BACKUP_CRON_SCRIPT = "forecast_backup.py"
BACKUP_CRON_NAME = "Forecast ledger backup"
# Daily at 07:30 — half an hour BEFORE the 08:00 self-check refresh, so the backup
# captures the book as it stood before the nightly reforecast mutates it. The
# ledger is the whole asset, so the backup runs even when nothing else is due.
DEFAULT_BACKUP_CRON_SCHEDULE = "30 7 * * *"


def remove_forecast_cron(*, name: str = FORECAST_CRON_NAME, match_script: bool = False) -> int:
    """Remove the no-agent forecast self-check cron job(s).

    By default matches on NAME only. The install path's idempotent re-arm calls
    this, and a name-only match is deliberate: the feature-rich auto-installed
    nightly routine ("Forecast self-check") shares this script, so a broader
    script-match would let ``install_forecast_cron(name="something else")`` silently
    delete that routine and replace it with a feature-poor one. Pass
    ``match_script=True`` for a full uninstall/teardown that should also sweep any
    job running the self-check script regardless of its name. Returns the number of
    jobs removed (0 if none was installed).
    """
    from cron.jobs import list_jobs, remove_job

    removed = 0
    for job in list_jobs(include_disabled=True):
        name_match = (job.get("name") or "") == name
        script_match = match_script and job.get("script") == FORECAST_CRON_SCRIPT
        if name_match or script_match:
            if remove_job(job["id"]):
                removed += 1
    return removed


def install_forecast_cron(
    *,
    schedule: str = DEFAULT_FORECAST_CRON_SCHEDULE,
    name: str = FORECAST_CRON_NAME,
    deliver: str = "local",
    profile: str | None = None,
    db_path: str | None = None,
    auto_score: bool = False,
    auto_postmortem: bool = False,
    thesis_aggregate: bool = False,
    synthesize_lessons: bool = False,
    refresh_market_models: bool = False,
    estimate_source_changes: bool = False,
    estimator_model: str | None = None,
    estimator_provider: str | None = None,
    estimator_limit: int = 5,
    estimator_max_iterations: int = 12,
    calibrate_utility: bool = False,
) -> dict[str, Any]:
    """Install a no-agent cron job for forecast schedule execution.

    Idempotent START: any prior self-check job (same name OR script) is removed
    first so re-installing re-arms cleanly instead of stacking duplicates.
    """

    # Clean start: remove any prior self-check job before re-arming.
    remove_forecast_cron(name=name)

    scripts_dir = get_agent_home() / "scripts"
    script_path = scripts_dir / FORECAST_CRON_SCRIPT
    install_script(
        script_path,
        db_path=db_path,
        auto_score=auto_score,
        auto_postmortem=auto_postmortem,
        thesis_aggregate=thesis_aggregate,
        synthesize_lessons=synthesize_lessons,
        refresh_market_models=refresh_market_models,
        estimate_source_changes=estimate_source_changes,
        estimator_model=estimator_model,
        estimator_provider=estimator_provider,
        estimator_limit=estimator_limit,
        estimator_max_iterations=estimator_max_iterations,
        calibrate_utility=calibrate_utility,
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


def default_routines_installed(*, name: str = FORECAST_CRON_NAME) -> bool:
    """True when the nightly self-check cron is already installed (by name OR script)."""
    from cron.jobs import list_jobs

    for job in list_jobs(include_disabled=True):
        if (job.get("name") or "") == name or job.get("script") == FORECAST_CRON_SCRIPT:
            return True
    return False


def _auto_install_enabled() -> bool:
    """Read the ``forecasting.cron.auto_install`` config flag (default TRUE).

    Best-effort: a config-read failure degrades to enabled — the auto-install is
    the intended default for the autonomous spine."""
    try:
        from superforecasting_agent.storage.configuration import read_configuration

        cfg = read_configuration() or {}
        fc = cfg.get("forecasting", {}) if isinstance(cfg, dict) else {}
        cron_cfg = fc.get("cron", {}) if isinstance(fc, dict) else {}
        if isinstance(cron_cfg, dict) and "auto_install" in cron_cfg:
            return bool(cron_cfg["auto_install"])
    except Exception:
        pass
    return True


def ensure_default_routines(
    *,
    db_path: str | None = None,
    schedule: str = DEFAULT_FORECAST_CRON_SCHEDULE,
    name: str = FORECAST_CRON_NAME,
    deliver: str = "local",
    profile: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Idempotently install the nightly self-check cron (auto-score + auto-postmortem
    + read-only thesis preview + lesson-synthesis).

    Existing jobs keep their identity and schedule, but their generated script is
    refreshed to the current feature set. Gated behind ``forecasting.cron.auto_install``
    (default TRUE); pass ``force=True`` to bypass the config gate (the explicit
    ``freshen`` / ``keep_fresh`` operator intent). Fail-open callers wrap this so
    a cron hiccup never blocks a forecast commit."""
    if not force and not _auto_install_enabled():
        return {"installed": False, "created": False, "job": None, "reason": "auto_install disabled"}
    scripts_dir = get_agent_home() / "scripts"
    if default_routines_installed(name=name):
        install_script(
            scripts_dir / FORECAST_CRON_SCRIPT,
            db_path=db_path,
            auto_score=True,
            auto_postmortem=True,
            thesis_aggregate=True,
            synthesize_lessons=True,
            refresh_market_models=True,
            estimate_source_changes=False,
            calibrate_utility=True,
        )
        warning = ensure_default_warning_automode_routine(
            db_path=db_path, deliver=deliver, profile=profile, force=force
        )
        estimator = ensure_default_source_estimator_routine(
            db_path=db_path, deliver=deliver, profile=profile, force=force
        )
        return {
            "installed": True,
            "created": False,
            "job": None,
            "reason": "already installed; script current",
            "warning_automode": warning,
            "source_estimator": estimator,
        }
    job = install_forecast_cron(
        schedule=schedule,
        name=name,
        deliver=deliver,
        profile=profile,
        db_path=db_path,
        auto_score=True,
        auto_postmortem=True,
        thesis_aggregate=True,
        synthesize_lessons=True,
        # R4: the nightly self-check re-pulls + recomputes Market Models linked to
        # still-OPEN questions and alerts on a material projection move. Bounded
        # (only active models on active questions) and deduped by the standard
        # _has_open_alert guard, so it never re-alerts every sweep.
        refresh_market_models=True,
        estimate_source_changes=False,
        calibrate_utility=True,
    )
    warning = ensure_default_warning_automode_routine(
        db_path=db_path, deliver=deliver, profile=profile, force=force
    )
    estimator = ensure_default_source_estimator_routine(
        db_path=db_path, deliver=deliver, profile=profile, force=force
    )
    return {
        "installed": True,
        "created": True,
        "job": job,
        "reason": "installed",
        "warning_automode": warning,
        "source_estimator": estimator,
    }


def ensure_default_warning_automode_routine(
    *,
    db_path: str | None = None,
    schedule: str = "every 30 minutes",
    deliver: str = "local",
    profile: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Ensure the bounded warning worker exists alongside the nightly sweep."""
    if not force and not _warning_automode_auto_install_enabled():
        return {"installed": False, "created": False, "job": None, "reason": "auto_install disabled"}
    status = warning_automode_cron_status()
    if status["installed"]:
        return {"installed": True, "created": False, "job": status["job"], "reason": "already installed"}
    job = install_warning_automode_cron(
        schedule=schedule,
        deliver=deliver,
        profile=profile,
        db_path=db_path,
        agent=True,
    )
    return {"installed": True, "created": True, "job": job, "reason": "installed"}


def _warning_automode_auto_install_enabled() -> bool:
    try:
        from superforecasting_agent.storage.configuration import read_configuration

        cfg = read_configuration() or {}
        block = ((cfg.get("forecasting") or {}).get("cron") or {})
        return bool(block.get("warning_automode_auto_install", True))
    except Exception:
        return True


def ensure_default_source_estimator_routine(
    *,
    db_path: str | None = None,
    schedule: str = "every 15 minutes",
    deliver: str = "local",
    profile: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Ensure source estimation has a cadence independent of warning work."""
    try:
        from superforecasting_agent.storage.configuration import read_configuration

        cfg = read_configuration() or {}
        block = ((cfg.get("cron") or {}).get("source_estimator") or {})
        enabled = bool(block.get("enabled", True))
        minutes = max(int(block.get("interval_minutes", 15)), 1)
        schedule = f"every {minutes} minutes"
    except Exception:
        enabled = True
    if not force and not enabled:
        return {"installed": False, "created": False, "job": None, "reason": "disabled"}
    status = source_estimator_cron_status()
    if status["installed"]:
        install_source_estimator_script(
            get_agent_home() / "scripts" / SOURCE_ESTIMATOR_CRON_SCRIPT,
            db_path=db_path,
        )
        return {
            "installed": True,
            "created": False,
            "job": status["job"],
            "reason": "already installed; script current",
        }
    job = install_source_estimator_cron(
        schedule=schedule,
        deliver=deliver,
        profile=profile,
        db_path=db_path,
    )
    return {"installed": True, "created": True, "job": job, "reason": "installed"}


def forecast_self_check_job() -> dict[str, Any] | None:
    """The installed nightly self-check cron job (matched by script), or None.

    The gateway due-sweeper reads its ``last_run_at`` to DEDUPE (skip a catch-up
    sweep when the nightly cron just ran, so the two never double the work) and
    its ``next_run_at`` for the TUI's "next nightly run" countdown. Best-effort:
    returns None on any error."""
    try:
        from cron.jobs import list_jobs

        for job in list_jobs(include_disabled=True):
            if job.get("script") == FORECAST_CRON_SCRIPT:
                return job
    except Exception:
        return None
    return None


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _job_interval_minutes(job: dict[str, Any]) -> int | None:
    """The nominal minutes between two fires of ``job`` (None when unknowable)."""
    sched = job.get("schedule")
    if not isinstance(sched, dict):
        return None
    kind = sched.get("kind")
    if kind == "interval":
        try:
            minutes = int(sched.get("minutes") or 0)
        except (TypeError, ValueError):
            return None
        return minutes or None
    if kind == "cron":
        expr = sched.get("expr")
        try:
            from croniter import croniter

            base = datetime(2000, 1, 1)
            it = croniter(expr, base)
            first = it.get_next(datetime)
            second = it.get_next(datetime)
            return max(int((second - first).total_seconds() / 60), 1)
        except Exception:
            return 1440  # assume daily when croniter is unavailable/unparseable
    return None


def forecast_cron_health(*, now: str | None = None) -> dict[str, Any]:
    """Read the installed forecast cron jobs and flag errored or missed ones.

    * ERRORED — the job's ``last_error`` is set or ``last_status`` is a failure.
    * MISSED  — an enabled job whose ``last_run_at`` is older than 2x its cadence
      (the tick never fired). Only computed when the cadence is knowable.

    Read-only + defensive: returns a structured summary and never raises (the
    doctor caller also wraps it, following the triage_gate fold-in pattern)."""
    from cron.jobs import list_jobs

    try:
        from superforecasting_agent.clock import now as hermes_now

        now_dt = _parse_iso(now) or hermes_now()
    except Exception:
        now_dt = _parse_iso(now) or datetime.utcnow()

    jobs_out: list[dict[str, Any]] = []
    errored: list[str] = []
    missed: list[str] = []
    for job in list_jobs(include_disabled=True):
        is_forecast_job = job.get("script") in {
            FORECAST_CRON_SCRIPT,
            WARNING_AUTOMODE_CRON_SCRIPT,
            SOURCE_ESTIMATOR_CRON_SCRIPT,
        } or "forecast" in " ".join(
            str(job.get(field) or "").lower() for field in ("name", "prompt")
        )
        if not is_forecast_job:
            continue
        status = job.get("last_status")
        last_error = job.get("last_error")
        last_run_at = job.get("last_run_at")
        is_errored = bool(last_error) or (
            isinstance(status, str) and status.strip().lower() in {"error", "failed", "failure"}
        )
        interval_min = _job_interval_minutes(job)
        is_missed = False
        if bool(job.get("enabled", True)) and last_run_at and interval_min:
            last_dt = _parse_iso(last_run_at)
            if last_dt is not None:
                a, b = last_dt, now_dt
                if (a.tzinfo is None) != (b.tzinfo is None):
                    a = a.replace(tzinfo=None)
                    b = b.replace(tzinfo=None)
                age_min = (b - a).total_seconds() / 60.0
                is_missed = age_min > 2 * interval_min
        entry = {
            "id": job.get("id"),
            "name": job.get("name"),
            "script": job.get("script"),
            "enabled": bool(job.get("enabled", True)),
            "schedule": (job.get("schedule") or {}).get("display") if isinstance(job.get("schedule"), dict) else None,
            "last_status": status,
            "last_error": last_error,
            "last_run_at": last_run_at,
            "errored": is_errored,
            "missed": is_missed,
            "failure_retry_count": int(job.get("failure_retry_count") or 0),
            "retry_backoff_minutes": job.get("retry_backoff_minutes"),
            "recurrence_next_run_at": job.get("recurrence_next_run_at"),
        }
        jobs_out.append(entry)
        if is_errored:
            errored.append(entry["id"])
        if is_missed:
            missed.append(entry["id"])
    return {
        "installed": len(jobs_out),
        "jobs": jobs_out,
        "errored": errored,
        "missed": missed,
        "healthy": not errored and not missed,
    }


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
    (per-cycle agent-run cap, default 1) and ``paid_min_interval_hours`` (default
    0.5h), both config-tunable. Source estimation and learned-error review use
    separate leased budgets so warning demand cannot starve them.

    ``agent`` wires the paid (LLM) tier; pass ``agent=False`` for a free-tier-only
    continuous loop. Idempotent START: any prior job with the same name is removed
    first so re-installing re-arms cleanly instead of stacking duplicates.
    """

    # Clean start: remove any prior automode job of the same name before re-arming.
    remove_warning_automode_cron(name=name)

    scripts_dir = get_agent_home() / "scripts"
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
    or None>}`` — the last-paid-run timestamp is read from the same transactional
    SQLite budget lease the runner uses, so concurrent processes cannot double-spend.
    """
    from cron.jobs import list_jobs

    job = None
    for candidate in list_jobs(include_disabled=True):
        if (candidate.get("name") or "") == name or candidate.get("script") == WARNING_AUTOMODE_CRON_SCRIPT:
            job = candidate
            break

    from forecasting.cron_runner import read_warning_automode_state
    from forecasting.ledger import ForecastLedger

    state = ForecastLedger().automation_budget_status("warning_automode_paid") or {}
    return {
        "installed": job is not None,
        "job": job,
        "last_paid_run_at": state.get("last_run_at"),
        "runtime": read_warning_automode_state() or None,
    }


def install_source_estimator_cron(
    *,
    schedule: str = "every 15 minutes",
    name: str = SOURCE_ESTIMATOR_CRON_NAME,
    deliver: str = "local",
    profile: str | None = None,
    db_path: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """Install the independent adaptive source-estimation worker."""
    remove_source_estimator_cron(name=name)
    install_source_estimator_script(
        get_agent_home() / "scripts" / SOURCE_ESTIMATOR_CRON_SCRIPT,
        db_path=db_path,
        model=model,
        provider=provider,
        max_iterations=max_iterations,
    )
    from cron.jobs import create_job

    return create_job(
        prompt="Route and estimate immutable source-change events.",
        schedule=schedule,
        name=name,
        deliver=deliver,
        script=SOURCE_ESTIMATOR_CRON_SCRIPT,
        profile=profile,
        no_agent=True,
    )


def remove_source_estimator_cron(*, name: str = SOURCE_ESTIMATOR_CRON_NAME) -> int:
    from cron.jobs import list_jobs, remove_job

    removed = 0
    for job in list_jobs(include_disabled=True):
        if (job.get("name") or "") == name or job.get("script") == SOURCE_ESTIMATOR_CRON_SCRIPT:
            if remove_job(job["id"]):
                removed += 1
    return removed


def source_estimator_cron_status(
    *, name: str = SOURCE_ESTIMATOR_CRON_NAME
) -> dict[str, Any]:
    from cron.jobs import list_jobs
    from forecasting.cron_runner import read_source_estimator_state

    job = next(
        (
            candidate
            for candidate in list_jobs(include_disabled=True)
            if (candidate.get("name") or "") == name
            or candidate.get("script") == SOURCE_ESTIMATOR_CRON_SCRIPT
        ),
        None,
    )
    return {
        "installed": job is not None,
        "job": job,
        "runtime": read_source_estimator_state() or None,
    }


# ── ledger backup cron (durability) ───────────────────────────────────────────
#
# The forecast ledger is the ENTIRE asset — months of judgment — so a daily online
# backup is the one routine that should always be armed. This mirrors
# ``install_forecast_cron`` / ``install_warning_automode_cron`` exactly: a no-agent
# job whose small script drives ``run_backup_cron`` (online backup + integrity +
# retention) on every tick.


def _install_backup_script(script_path: "Path", *, db_path: str | None = None) -> None:
    """Write the tiny no-agent script the daily backup cron runs — it calls the
    BACKUP job type's ``main`` (a durable job on the shared runtime)."""

    from pathlib import Path as _Path

    _Path(script_path).parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = []
    if db_path:
        args.extend(["--db", db_path])
    _Path(script_path).write_text(
        "\n".join(
            [
                "from forecasting.jobs.types.backup import main",
                "",
                "if __name__ == '__main__':",
                f"    raise SystemExit(main({args!r}))",
                "",
            ]
        ),
        encoding="utf-8",
    )


def install_backup_cron(
    *,
    schedule: str = DEFAULT_BACKUP_CRON_SCHEDULE,
    name: str = BACKUP_CRON_NAME,
    deliver: str = "local",
    profile: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Install the daily no-agent ledger-backup cron job.

    Idempotent START: any prior backup job (same name OR script) is removed first so
    re-installing re-arms cleanly instead of stacking duplicates.
    """

    remove_backup_cron(name=name)

    scripts_dir = get_agent_home() / "scripts"
    script_path = scripts_dir / BACKUP_CRON_SCRIPT
    _install_backup_script(script_path, db_path=db_path)

    from cron.jobs import create_job

    return create_job(
        prompt="Back up the forecast ledger (online snapshot + integrity + retention).",
        schedule=schedule,
        name=name,
        deliver=deliver,
        script=BACKUP_CRON_SCRIPT,
        profile=profile,
        no_agent=True,
    )


def remove_backup_cron(*, name: str = BACKUP_CRON_NAME) -> int:
    """STOP (uninstall) the daily ledger-backup cron job(s). Returns the count
    removed. Matches the backup name OR script so a clean stop leaves no duplicate."""

    from cron.jobs import list_jobs, remove_job

    removed = 0
    for job in list_jobs(include_disabled=True):
        if (job.get("name") or "") == name or job.get("script") == BACKUP_CRON_SCRIPT:
            if remove_job(job["id"]):
                removed += 1
    return removed


def backup_cron_installed(*, name: str = BACKUP_CRON_NAME) -> bool:
    """True when the daily backup cron is already installed (by name OR script)."""

    from cron.jobs import list_jobs

    for job in list_jobs(include_disabled=True):
        if (job.get("name") or "") == name or job.get("script") == BACKUP_CRON_SCRIPT:
            return True
    return False


def backup_cron_status(*, name: str = BACKUP_CRON_NAME) -> dict[str, Any]:
    """STATUS of the daily ledger-backup cron job: ``{installed, job}``."""

    from cron.jobs import list_jobs

    job = None
    for candidate in list_jobs(include_disabled=True):
        if (candidate.get("name") or "") == name or candidate.get("script") == BACKUP_CRON_SCRIPT:
            job = candidate
            break
    return {"installed": job is not None, "job": job}


def ensure_default_backup_routine(
    *,
    db_path: str | None = None,
    schedule: str = DEFAULT_BACKUP_CRON_SCHEDULE,
    name: str = BACKUP_CRON_NAME,
    deliver: str = "local",
    profile: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Idempotently install the daily ledger-backup cron.

    Mirrors :func:`ensure_default_routines`: cheap + silent when already installed,
    gated behind the same ``forecasting.cron.auto_install`` flag (default TRUE);
    pass ``force=True`` for explicit operator intent. Fail-open callers wrap this so
    a cron hiccup never blocks a forecast commit."""

    if not force and not _auto_install_enabled():
        return {"installed": False, "created": False, "job": None, "reason": "auto_install disabled"}
    if backup_cron_installed(name=name):
        return {"installed": True, "created": False, "job": None, "reason": "already installed"}
    job = install_backup_cron(
        schedule=schedule, name=name, deliver=deliver, profile=profile, db_path=db_path
    )
    return {"installed": True, "created": True, "job": job, "reason": "installed"}
