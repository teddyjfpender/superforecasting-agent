"""`forecast jobs approve <job_id>` — the CLI verb over ``jobs.policy.approve_job``.

The policy slice's named follow-up: a thin CLI over
:func:`forecasting.jobs.policy.approve_job`. These tests drive the real
``forecast`` parser (``main(["jobs", "approve", …])``) against a JobStore rooted
at a temp HOME, so they exercise the argparse wiring + handler, not just the
policy function.
"""

from __future__ import annotations

import json

import pytest

from forecasting.cli import main as forecast_main
from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("FORECAST_LEDGER_DB", raising=False)
    from forecasting import appconfig

    appconfig.configure(environ=None, config_file=None)
    yield tmp_path
    appconfig.configure(environ=None, config_file=None)


def _parked(store: JobStore) -> str:
    """A job PARKED awaiting operator sign-off (one llm_spend authorize)."""

    job_id = store.new_id()
    store.write(
        JobRecord(
            job_id=job_id,
            type="policy_probe",
            spec={"authorize_class": "llm_spend"},
            status="awaiting_approval",
            policy_decisions=[{"class": "llm_spend", "outcome": "awaiting_approval"}],
        )
    )
    return job_id


def test_jobs_approve_no_resume_flips_status_and_records_grant(home, capsys):
    store = JobStore(home=home)
    job_id = _parked(store)

    forecast_main(["jobs", "approve", job_id, "--no-resume"])

    record = store.read(job_id)
    assert record.status == "queued"
    assert "llm_spend" in (record.policy_grants or [])
    out = capsys.readouterr().out
    assert job_id in out
    assert "queued" in out


def test_jobs_approve_json_emits_the_record(home, capsys):
    store = JobStore(home=home)
    job_id = _parked(store)

    forecast_main(["jobs", "approve", job_id, "--no-resume", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["job_id"] == job_id
    assert payload["status"] == "queued"
    assert "llm_spend" in payload["policy_grants"]


def test_jobs_status_active_and_cancel_cli(home, capsys):
    store = JobStore(home=home)
    job_id = store.new_id()
    store.write(
        JobRecord(
            job_id=job_id,
            type="reforecast",
            spec={"question_ids": ["fq_a"]},
            status="running",
            total=3,
            done_count=1,
            current="fq_a",
        )
    )

    forecast_main(["jobs", "status", job_id, "--json"])
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["job_id"] == job_id
    assert status_payload["status"] == "running"

    forecast_main(["jobs", "active", "--json"])
    active_payload = json.loads(capsys.readouterr().out)
    assert [row["job_id"] for row in active_payload["jobs"]] == [job_id]

    forecast_main(["jobs", "cancel", job_id, "--json"])
    cancel_payload = json.loads(capsys.readouterr().out)
    assert cancel_payload["cancel_requested"] is True
    assert store.stop_path(job_id).exists()


def test_jobs_approve_rejects_a_job_not_awaiting_approval(home, capsys):
    store = JobStore(home=home)
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type="policy_probe", spec={}, status="queued"))

    with pytest.raises(SystemExit) as excinfo:
        forecast_main(["jobs", "approve", job_id])
    assert excinfo.value.code == 1
    assert "not awaiting approval" in capsys.readouterr().err
