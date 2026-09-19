"""Cancellation admission is durable; acknowledgement is not termination."""

import argparse
from unittest.mock import Mock

import pytest

from forecasting.application.job_cancellation import request_job_cancellation
from forecasting.cli.jobs_admin import _cmd_jobs_cancel
from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore
from tui_gateway import jobs_rpc, server


def test_live_owner_receipt_does_not_claim_terminal_status():
    store = JobStore()
    store.write(JobRecord(job_id="job_live", type="warnings", status="queued"))
    with store.claim("job_live"):
        receipt = request_job_cancellation(store, "job_live")
        assert receipt.accepted
        assert receipt.record.status == "running"
        assert store.is_cancel_requested("job_live")
    again = request_job_cancellation(store, "job_live")
    assert again.accepted
    assert again.record.status == "cancelled"


@pytest.mark.parametrize("method", ["jobs.cancel", "forecast.warnings.automode.cancel"])
def test_storage_failure_is_not_acknowledged_or_locally_signalled(monkeypatch, method):
    event = Mock()
    monkeypatch.setitem(jobs_rpc._running, "job_failure", event)
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(JobStore, "request_cancel", fail)
    response = server.handle_request({"id": "cancel", "method": method, "params": {"job_id": "job_failure"}})
    assert response["error"]["code"] == 5008
    assert "disk unavailable" in response["error"]["message"]
    event.set.assert_not_called()
    with pytest.raises(SystemExit) as exc:
        _cmd_jobs_cancel(argparse.Namespace(job_id="job_failure", json=True))
    assert exc.value.code == 1


def test_cli_storage_failure_keeps_stdout_empty(monkeypatch, capsys):
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(JobStore, "request_cancel", fail)
    with pytest.raises(SystemExit):
        _cmd_jobs_cancel(argparse.Namespace(job_id="job_failure", json=True))
    output = capsys.readouterr()
    assert output.out == ""
    assert "disk unavailable" in output.err


def test_rpc_acknowledgement_observes_live_durable_status():
    store = JobStore()
    store.write(JobRecord(job_id="job_live", type="warnings", status="queued"))
    with store.claim("job_live"):
        response = server.handle_request({"id": "cancel", "method": "jobs.cancel", "params": {"job_id": "job_live"}})
        result = response["result"]
        assert result["cancel_requested"] is True
        assert result["status"] == "running"
        assert store.read("job_live").status == result["status"]


def test_terminal_record_is_not_relabelled():
    store = JobStore()
    store.write(JobRecord(job_id="job_done", type="warnings", status="completed"))
    receipt = request_job_cancellation(store, "job_done")
    assert receipt.record.status == "completed"


def test_missing_record_has_no_cancellation_receipt():
    receipt = request_job_cancellation(JobStore(), "job_absent")
    assert not receipt.accepted
    assert receipt.record is None


@pytest.mark.parametrize("arguments,code", [(["jobs", "active", "--json"], 0), (["jobs", "cancel", "job_absent", "--json"], 1)])
def test_cli_machine_output_and_errors_are_noninteractive(tmp_path, arguments, code):
    import json
    import os
    import subprocess
    import sys

    env = {key: value for key, value in os.environ.items() if not any(secret in key for secret in ("API_KEY", "TOKEN", "PASSWORD"))}
    env.update(SUPERFORECASTING_AGENT_HOME=str(tmp_path), HERMES_HOME=str(tmp_path))
    result = subprocess.run([sys.executable, "-m", "superforecasting_agent", *arguments], input="", text=True, capture_output=True, env=env, timeout=20)
    assert result.returncode == code, result.stderr
    assert "Traceback" not in result.stderr
    if code == 0:
        assert json.loads(result.stdout) == {"count": 0, "jobs": []}
        assert result.stderr == ""
    else:
        assert result.stdout == ""
        assert "no job 'job_absent'" in result.stderr


def test_cancel_does_not_signal_replacement_worker(monkeypatch):
    original, replacement = Mock(), Mock()
    monkeypatch.setitem(jobs_rpc._running, "job_swap", original)
    store = JobStore()
    store.write(JobRecord(job_id="job_swap", type="warnings", status="queued"))
    request = JobStore.request_cancel
    def replace_after_admission(self, job_id):
        accepted = request(self, job_id)
        jobs_rpc._running[job_id] = replacement
        return accepted
    monkeypatch.setattr(JobStore, "request_cancel", replace_after_admission)
    result = server.handle_request({"id": "cancel", "method": "jobs.cancel", "params": {"job_id": "job_swap"}})
    assert result["result"]["cancel_requested"] is True
    original.set.assert_not_called()
    replacement.set.assert_not_called()
