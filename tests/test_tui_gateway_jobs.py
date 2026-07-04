"""Gateway RPCs for the detached-job runtime (Arc B1): jobs.start/status/active/
cancel + the warnings aliases' parity (byte-compatible shape + legacy events).
"""

from __future__ import annotations

import time

from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore
from tui_gateway import server


def _seed_ledger():
    from forecasting.ledger import ForecastLedger

    lg = ForecastLedger()
    lg.create_alert(
        severity="high", scope_type="question", scope_ref="fq_a",
        reason="postmortem_due", recommended_action="Run a postmortem.")
    lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_d",
        reason="domain_error_profile_applies:politics", recommended_action="Human review.")
    lg.create_alert(
        severity="info", scope_type="question", scope_ref="fq_f",
        reason="autopilot_enabled", recommended_action="Informational.")
    return lg


def _wait_for(events, event_type, job_id, *, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for msg in events:
            p = msg.get("params", {})
            if p.get("type") == event_type and p.get("payload", {}).get("job_id") == job_id:
                return p["payload"]
        time.sleep(0.02)
    return None


# ── jobs.start end-to-end ─────────────────────────────────────────────────────


def test_jobs_start_streams_and_completes(tmp_path, monkeypatch):
    _seed_ledger()
    events: list[dict] = []
    monkeypatch.setattr(server, "write_json", lambda msg: events.append(msg) or True)

    resp = server.handle_request(
        {"id": "1", "method": "jobs.start",
         "params": {"type": "warnings", "spec": {"dry_run": True}, "session_id": "s1"}}
    )
    assert "result" in resp, resp
    assert resp["result"]["type"] == "warnings"
    job_id = resp["result"]["job_id"]
    assert job_id.startswith("job_")

    done = _wait_for(events, "jobs.complete", job_id)
    assert done is not None, [m.get("params", {}).get("type") for m in events]
    assert done["type"] == "warnings"
    assert done["result"]["total"] == 3
    progress = [m for m in events if m.get("params", {}).get("type") == "jobs.progress"]
    assert progress, "expected streamed jobs.progress events"
    # Each progress event carries the structured envelope.
    sample = progress[0]["params"]["payload"]
    assert sample["job_id"] == job_id and sample["type"] == "warnings"
    assert isinstance(sample["progress"], dict)


def test_jobs_start_requires_type(tmp_path):
    resp = server.handle_request({"id": "1", "method": "jobs.start", "params": {}})
    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_jobs_start_unknown_type_errors(tmp_path):
    resp = server.handle_request(
        {"id": "1", "method": "jobs.start", "params": {"type": "nope"}}
    )
    assert "error" in resp
    assert resp["error"]["code"] == -32602
    assert "unknown job type" in resp["error"]["message"]


# ── jobs.status / jobs.active (seeded store, deterministic) ───────────────────


def test_jobs_status_found_and_missing(tmp_path):
    store = JobStore()  # default home == per-test HERMES_HOME (same as the gateway)
    store.write(JobRecord(job_id="job_stat", type="warnings", status="running", total=7))

    ok = server.handle_request(
        {"id": "1", "method": "jobs.status", "params": {"job_id": "job_stat"}}
    )
    assert ok["result"]["found"] is True
    assert ok["result"]["job"]["status"] == "running"
    assert ok["result"]["job"]["total"] == 7

    missing = server.handle_request(
        {"id": "2", "method": "jobs.status", "params": {"job_id": "job_ghost"}}
    )
    assert missing["result"]["found"] is False
    assert missing["result"]["job"] is None


def test_jobs_active_filters_and_counts(tmp_path):
    store = JobStore()
    store.write(JobRecord(job_id="job_r", type="warnings", status="running"))
    store.write(JobRecord(job_id="job_q", type="reforecast", status="queued"))
    store.write(JobRecord(job_id="job_d", type="warnings", status="done"))

    every = server.handle_request({"id": "1", "method": "jobs.active", "params": {}})
    assert every["result"]["count"] == 2
    assert {j["job_id"] for j in every["result"]["jobs"]} == {"job_r", "job_q"}

    only = server.handle_request(
        {"id": "2", "method": "jobs.active", "params": {"types": ["warnings"]}}
    )
    assert {j["job_id"] for j in only["result"]["jobs"]} == {"job_r"}


def test_jobs_cancel_unknown_is_not_found(tmp_path):
    resp = server.handle_request(
        {"id": "1", "method": "jobs.cancel", "params": {"job_id": "job_none"}}
    )
    assert resp["result"]["found"] is False
    assert resp["result"]["cancelled"] is False


def test_jobs_cancel_marks_record(tmp_path):
    store = JobStore()
    store.write(JobRecord(job_id="job_cx", type="warnings", status="running"))
    resp = server.handle_request(
        {"id": "1", "method": "jobs.cancel", "params": {"job_id": "job_cx"}}
    )
    assert resp["result"]["found"] is True
    assert resp["result"]["cancelled"] is True
    assert store.read("job_cx").cancel_requested is True


# ── alias parity: forecast.warnings.automode.* over the runtime ───────────────


def test_automode_alias_emits_legacy_AND_jobs_events(tmp_path, monkeypatch):
    """The alias returns the byte-compatible {job_id, dry_run} shape and emits BOTH
    the legacy forecast.warnings.automode.* events (alerts view unchanged) AND the
    new jobs.* events for the same job."""
    _seed_ledger()
    events: list[dict] = []
    monkeypatch.setattr(server, "write_json", lambda msg: events.append(msg) or True)

    resp = server.handle_request(
        {"id": "1", "method": "forecast.warnings.automode.run",
         "params": {"session_id": "s1", "dry_run": True}}
    )
    assert set(resp["result"]) == {"job_id", "dry_run"}
    assert resp["result"]["dry_run"] is True
    job_id = resp["result"]["job_id"]

    # Legacy terminal event — the EXACT old shape ({job_id, **summary}).
    legacy = _wait_for(events, "forecast.warnings.automode.complete", job_id)
    assert legacy is not None, [m.get("params", {}).get("type") for m in events]
    assert legacy["dry_run"] is True
    assert legacy["total"] == 3
    assert "type" not in legacy  # flattened, not the structured jobs.* shape

    # The new jobs.complete fired ALONGSIDE for the same job.
    modern = _wait_for(events, "jobs.complete", job_id)
    assert modern is not None
    assert modern["type"] == "warnings"
    assert modern["result"]["total"] == 3

    # Legacy progress events streamed too.
    legacy_progress = [
        m for m in events
        if m.get("params", {}).get("type") == "forecast.warnings.automode.progress"
    ]
    assert legacy_progress, "expected legacy automode.progress events"


def test_automode_cancel_alias_shape_unknown_and_known(tmp_path, monkeypatch):
    # Unknown (not running) → the exact old {job_id, found: False} shape.
    unknown = server.handle_request(
        {"id": "1", "method": "forecast.warnings.automode.cancel",
         "params": {"job_id": "wj_nope"}}
    )
    assert unknown["result"] == {"job_id": "wj_nope", "found": False}
