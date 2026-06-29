"""Gateway RPCs for the warning-resolution surface (slice 3b):
forecast.warnings.list / .resolve / .automode.run / .automode.cancel.

list is read-only; resolve acks ONLY genuine gated work; automode.run spawns a
background job that streams progress events and finishes with a terminal
complete event.
"""

from __future__ import annotations

import time

from tui_gateway import server


def _seed(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    from forecasting.ledger import ForecastLedger

    lg = ForecastLedger()  # default home DB (under the patched HERMES_HOME)
    ids = {}
    ids["postmortem"] = lg.create_alert(
        severity="high", scope_type="question", scope_ref="fq_a",
        reason="postmortem_due", recommended_action="Run a postmortem.").id
    ids["no_auto"] = lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_d",
        reason="domain_error_profile_applies:politics", recommended_action="Human review.").id
    ids["bookkeeping"] = lg.create_alert(
        severity="info", scope_type="question", scope_ref="fq_f",
        reason="autopilot_enabled", recommended_action="Informational.").id
    return lg, ids


def test_forecast_warnings_list_groups_open_backlog(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    resp = server.handle_request(
        {"id": "1", "method": "forecast.warnings.list", "params": {}}
    )
    assert "result" in resp, resp
    res = resp["result"]
    assert res["open_total"] == 3
    by_reason = {g["reason"]: g for g in res["groups"]}
    assert by_reason["postmortem_due"]["kind"] == "postmortem"
    assert by_reason["domain_error_profile_applies:politics"]["auto_resolvable"] is False


def test_forecast_warnings_resolve_acks_only_real_work(tmp_path, monkeypatch):
    lg, ids = _seed(tmp_path, monkeypatch)

    # The bookkeeping notice resolves (genuine close-out).
    ok = server.handle_request(
        {"id": "1", "method": "forecast.warnings.resolve",
         "params": {"alert_id": ids["bookkeeping"]}}
    )
    assert "result" in ok, ok
    assert ok["result"]["results"][0]["status"] == "resolved"

    # A NO_AUTO alert is surfaced, never acked.
    surf = server.handle_request(
        {"id": "2", "method": "forecast.warnings.resolve",
         "params": {"alert_id": ids["no_auto"]}}
    )
    assert surf["result"]["results"][0]["status"] == "surfaced"

    open_now = {a.id for a in lg.list_alerts(unresolved_only=True)}
    assert ids["bookkeeping"] not in open_now
    assert ids["no_auto"] in open_now


def test_forecast_warnings_resolve_requires_alert_id(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    resp = server.handle_request(
        {"id": "1", "method": "forecast.warnings.resolve", "params": {}}
    )
    assert "error" in resp, resp


def test_forecast_warnings_automode_run_streams_and_completes(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    events: list[dict] = []
    monkeypatch.setattr(server, "write_json", lambda msg: events.append(msg) or True)

    resp = server.handle_request(
        {"id": "1", "method": "forecast.warnings.automode.run",
         "params": {"session_id": "s1", "dry_run": True}}
    )
    assert "result" in resp, resp
    job_id = resp["result"]["job_id"]
    assert resp["result"]["dry_run"] is True

    # The job runs on a daemon thread; wait for its terminal complete event.
    deadline = time.time() + 5.0
    complete = None
    while time.time() < deadline:
        for msg in events:
            p = msg.get("params", {})
            if p.get("type") == "forecast.warnings.automode.complete" and p["payload"]["job_id"] == job_id:
                complete = p["payload"]
                break
        if complete is not None:
            break
        time.sleep(0.02)

    assert complete is not None, [m.get("params", {}).get("type") for m in events]
    assert complete["dry_run"] is True
    assert complete["total"] == 3
    # Progress events streamed during the run.
    progress = [m for m in events
                if m.get("params", {}).get("type") == "forecast.warnings.automode.progress"]
    assert progress, "expected streamed progress events"


def test_forecast_warnings_automode_cancel_unknown_job():
    resp = server.handle_request(
        {"id": "1", "method": "forecast.warnings.automode.cancel",
         "params": {"job_id": "wj_nope"}}
    )
    assert resp["result"]["found"] is False
