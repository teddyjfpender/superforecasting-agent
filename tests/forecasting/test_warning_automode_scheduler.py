"""Slice 7 — the scheduler START/STOP/STATUS surface for the continuous
warning-automode cron (Shape B: own cadence, clean start/stop)."""

from __future__ import annotations

from pathlib import Path

from forecasting.scheduler import (
    SOURCE_ESTIMATOR_CRON_SCRIPT,
    WARNING_AUTOMODE_CRON_SCRIPT,
    install_source_estimator_cron,
    remove_source_estimator_cron,
    source_estimator_cron_status,
    install_warning_automode_cron,
    remove_warning_automode_cron,
    warning_automode_cron_status,
)


def test_source_estimator_has_its_own_no_agent_job_and_script(tmp_path):
    assert source_estimator_cron_status()["installed"] is False
    job = install_source_estimator_cron(schedule="every 15 minutes")
    assert job["no_agent"] is True
    assert job["script"] == SOURCE_ESTIMATOR_CRON_SCRIPT
    from superforecasting_agent.constants import get_agent_home

    body = (
        get_agent_home() / "scripts" / SOURCE_ESTIMATOR_CRON_SCRIPT
    ).read_text(encoding="utf-8")
    assert "main_source_estimator" in body
    assert source_estimator_cron_status()["installed"] is True
    assert remove_source_estimator_cron() == 1


def test_start_installs_a_no_agent_job_and_script(tmp_path):
    # _hermetic_environment isolates HERMES_HOME + repoints cron.jobs paths.
    status0 = warning_automode_cron_status()
    assert status0["installed"] is False

    job = install_warning_automode_cron(
        schedule="every 30 minutes", agent=True, paid_budget=2, paid_min_interval_hours=6.0
    )
    assert job["no_agent"] is True
    assert job["script"] == WARNING_AUTOMODE_CRON_SCRIPT

    from superforecasting_agent.constants import get_agent_home

    script = get_agent_home() / "scripts" / WARNING_AUTOMODE_CRON_SCRIPT
    body = Path(script).read_text(encoding="utf-8")
    assert "main_warning_automode" in body
    assert "--agent" in body
    assert "--paid-budget" in body

    status = warning_automode_cron_status()
    assert status["installed"] is True
    assert status["job"]["id"] == job["id"]


def test_start_is_idempotent_clean_rearm(tmp_path):
    job1 = install_warning_automode_cron(schedule="every 30 minutes")
    job2 = install_warning_automode_cron(schedule="every 1h")
    assert job1["id"] != job2["id"]

    from cron.jobs import list_jobs

    automode_jobs = [
        j for j in list_jobs(include_disabled=True)
        if j.get("script") == WARNING_AUTOMODE_CRON_SCRIPT
    ]
    assert len(automode_jobs) == 1  # the prior job was removed on re-arm
    assert automode_jobs[0]["id"] == job2["id"]


def test_stop_removes_the_job(tmp_path):
    install_warning_automode_cron(schedule="every 30 minutes")
    removed = remove_warning_automode_cron()
    assert removed == 1
    assert warning_automode_cron_status()["installed"] is False
    # Stopping again is a no-op (nothing to remove).
    assert remove_warning_automode_cron() == 0


def test_free_only_start_omits_agent_flag(tmp_path):
    install_warning_automode_cron(schedule="every 30 minutes", agent=False)
    from superforecasting_agent.constants import get_agent_home

    body = (get_agent_home() / "scripts" / WARNING_AUTOMODE_CRON_SCRIPT).read_text(encoding="utf-8")
    assert "--agent" not in body
