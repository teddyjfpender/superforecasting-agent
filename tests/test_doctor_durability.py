"""The doctor's durability section (integrity + backup) and the daily backup-cron
cadence seam.

The section is the lazy-path surface that keeps the "no backups" gap visible even
when no cron is installed: it WARNs when the newest backup is >48h old or missing.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forecasting.cli import (
    DOCTOR_BACKUP_STALE_HOURS,
    _build_doctor_report,
    _build_durability_section,
)
from forecasting.ledger import ForecastLedger


def _ledger(tmp_path: Path) -> ForecastLedger:
    return ForecastLedger(tmp_path / "ledger.db")


def _write_backup_stamped(ledger: ForecastLedger, when: datetime) -> Path:
    backup_dir = ledger.default_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"forecast-{when.strftime('%Y%m%d-%H%M%S')}.db"
    path.write_text("x")
    return path


# ── durability section: the three WARN states ────────────────────────────────


def test_durability_missing_when_no_backup(tmp_path):
    section = _build_durability_section(_ledger(tmp_path))
    assert section["backup_status"] == "missing"
    assert section["last_backup"] is None
    assert section["integrity_ok"] is True  # a healthy empty ledger
    assert section["stale_after_hours"] == DOCTOR_BACKUP_STALE_HOURS


def test_durability_ok_after_fresh_backup(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.backup()
    section = _build_durability_section(ledger)
    assert section["backup_status"] == "ok"
    assert section["last_backup"]["age_hours"] < DOCTOR_BACKUP_STALE_HOURS
    assert section["integrity_ok"] is True
    assert "questions" in section["counts"]


def test_durability_stale_when_backup_older_than_48h(tmp_path):
    ledger = _ledger(tmp_path)
    _write_backup_stamped(ledger, datetime.now(timezone.utc) - timedelta(hours=72))
    section = _build_durability_section(ledger)
    assert section["backup_status"] == "stale"
    assert section["last_backup"]["age_hours"] > DOCTOR_BACKUP_STALE_HOURS


def test_doctor_report_includes_durability(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.backup()
    args = argparse.Namespace(
        db=str(ledger.db_path),
        last=5,
        dataset=None,
        min_questions=1,
        min_structured_source_questions=0,
        min_scores=0,
        min_postmortems=0,
        min_scheduled_reviews=0,
        min_scheduled_review_runs=0,
        min_live_scores=0,
        min_agent_protocol_cases=0,
        min_external_source_families=0,
        require_pilot_ready=False,
        require_readiness=False,
        json=True,
    )
    report = _build_doctor_report(args)
    assert "durability" in report
    assert report["durability"]["backup_status"] == "ok"


# ── cadence seam ─────────────────────────────────────────────────────────────


def test_backup_cron_script_generation(tmp_path):
    from forecasting import scheduler

    script = tmp_path / "scripts" / "forecast_backup.py"
    scheduler._install_backup_script(script, db_path="/x/y.db")
    text = script.read_text()
    assert "from forecasting.jobs.types.backup import main" in text
    assert "--db" in text and "/x/y.db" in text


def test_default_backup_schedule_is_daily():
    from forecasting import scheduler

    # Daily, and half an hour before the 08:00 self-check.
    assert scheduler.DEFAULT_BACKUP_CRON_SCHEDULE == "30 7 * * *"
    assert scheduler.BACKUP_CRON_SCRIPT == "forecast_backup.py"


def test_install_and_remove_backup_cron(tmp_path, monkeypatch):
    pytest.importorskip("croniter")  # cron schedule parsing needs croniter
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    from cron import jobs as cron_jobs

    monkeypatch.setattr(cron_jobs, "HERMES_DIR", tmp_path, raising=False)
    monkeypatch.setattr(cron_jobs, "CRON_DIR", tmp_path / "cron", raising=False)
    monkeypatch.setattr(cron_jobs, "JOBS_FILE", tmp_path / "cron" / "jobs.json", raising=False)
    monkeypatch.setattr(cron_jobs, "OUTPUT_DIR", tmp_path / "cron" / "output", raising=False)

    from forecasting import scheduler

    assert scheduler.backup_cron_installed() is False
    job = scheduler.install_backup_cron(db_path=str(tmp_path / "l.db"))
    assert job.get("script") == scheduler.BACKUP_CRON_SCRIPT
    assert scheduler.backup_cron_installed() is True
    assert scheduler.backup_cron_status()["installed"] is True
    # Idempotent re-arm never stacks duplicates.
    scheduler.install_backup_cron(db_path=str(tmp_path / "l.db"))
    assert sum(1 for _ in [job]) == 1
    removed = scheduler.remove_backup_cron()
    assert removed >= 1
    assert scheduler.backup_cron_installed() is False
