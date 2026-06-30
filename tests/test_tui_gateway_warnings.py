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


def test_forecast_warnings_aggregate_folds_into_tiers(tmp_path, monkeypatch):
    lg, _ids = _seed(tmp_path, monkeypatch)
    # Add agent-tier reforecast alerts: one fresh-evidence, two staleness (the
    # STALE sub-bucket) so we can assert the sub-bucket is a subset of the tier.
    lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_g",
        reason="new_evidence:fred", recommended_action="Reforecast.")
    lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_h",
        reason="evidence_stale_7d_plus", recommended_action="Reforecast.")
    lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_i",
        reason="close_time_within_7d", recommended_action="Reforecast.")

    resp = server.handle_request(
        {"id": "1", "method": "forecast.warnings.aggregate", "params": {}}
    )
    assert "result" in resp, resp
    res = resp["result"]

    # Seed: postmortem (free), no_auto (manual), bookkeeping (free) + 3 agent.
    head = res["headline"]
    assert head["total"] == 6
    assert head["free"] == 2          # postmortem_due + autopilot_enabled
    assert head["agent"] == 3         # new_evidence + evidence_stale + close_time_within
    assert head["manual"] == 1        # domain_error_profile_applies
    # Tier totals match the headline and sum to the total.
    assert res["free"]["total"] == 2
    assert res["agent"]["total"] == 3
    assert res["manual"]["total"] == 1
    assert head["free"] + head["agent"] + head["manual"] == head["total"]

    # The STALE sub-bucket is the elapsed-time subset of the agent tier (2 of 3),
    # and its reasons are still counted in the agent total.
    stale = res["agent"]["stale"]
    assert stale["total"] == 2
    stale_reasons = {g["reason"] for g in stale["reasons"]}
    assert stale_reasons == {"evidence_stale_7d_plus", "close_time_within_7d"}
    assert stale["total"] < res["agent"]["total"]

    # Per-reason groups carry the manual tier's human-review alert.
    manual_reasons = {g["reason"] for g in res["manual"]["reasons"]}
    assert "domain_error_profile_applies:politics" in manual_reasons


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


def test_forecast_warnings_dismiss_records_silence_and_is_not_a_resolution(tmp_path, monkeypatch):
    lg, ids = _seed(tmp_path, monkeypatch)
    # Add a reforecast group to dismiss by reason.
    lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_h",
        reason="evidence_stale_7d_plus", recommended_action="Reforecast.")

    # A non-empty note is required (no silent mass-dismiss).
    bad = server.handle_request(
        {"id": "1", "method": "forecast.warnings.dismiss",
         "params": {"reason": "evidence_stale", "actor": "ops"}}
    )
    assert "error" in bad, bad

    ok = server.handle_request(
        {"id": "2", "method": "forecast.warnings.dismiss",
         "params": {"reason": "evidence_stale", "note": "known noisy batch", "actor": "ops"}}
    )
    assert "result" in ok, ok
    res = ok["result"]
    assert res["count"] == 1
    entry = res["dismissed"][0]
    # Recorded, auditable silence — note + actor + TTL persisted.
    assert entry["dismiss_note"] == "known noisy batch"
    assert entry["dismiss_actor"] == "ops"
    assert entry["dismiss_ttl_days"] == 7

    # It dropped out of the open backlog WITHOUT being resolved: the stored alert
    # carries the dismissal trail (distinct from a runner-resolution).
    stored = lg.get_alert(entry["alert_id"])
    assert stored.is_dismissed is True
    assert stored.acknowledged_at is not None
    open_now = {a.id for a in lg.list_alerts(unresolved_only=True)}
    assert entry["alert_id"] not in open_now


def test_forecast_warnings_dismiss_requires_a_selection(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    resp = server.handle_request(
        {"id": "1", "method": "forecast.warnings.dismiss",
         "params": {"note": "n", "actor": "ops"}}
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
