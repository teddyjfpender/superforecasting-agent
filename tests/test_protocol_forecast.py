"""Conformance for the ``forecast.*`` protocol models (Arc A3 — the biggest family).

* every registered ``forecast.*`` RPC exposes a request + response model;
* REAL captured frames from the builders (dashboard, workspace) parse through the
  response models — the actual server emission validates;
* representative literal frames for the smaller read RPCs (quorum.status,
  schedule.status, reviews.next, config, bench, question.readiness, triage) validate
  and TOLERATE undeclared extras;
* the multi-member ``probability`` union (number | dict | string | null) round-trips;
* the gateway wrapper is VALIDATE-ONLY — the wire is returned UNCHANGED and a request
  the handler rejects keeps the handler's OWN error code (no ``-32602`` short-circuit).
"""

from __future__ import annotations

import pytest

from protocol import RPC_BY_METHOD

# Every forecast.* method wrapped in server.py + the Arc-B aliases modelled here.
FORECAST_METHODS = [
    "forecast.dashboard", "forecast.workspace", "forecast.theses", "forecast.bench",
    "forecast.quorum.status", "forecast.question.readiness", "forecast.triage.contested",
    "forecast.triage.relabel", "forecast.schedule.status", "forecast.reviews.next",
    "forecast.calibration", "forecast.command", "forecast.reforecast", "forecast.config",
    "forecast.config.set", "forecast.question", "forecast.onboard_propose",
    "forecast.onboard_commit", "forecast.hooks", "forecast.hooks.set",
    "forecast.hooks.save_rule", "forecast.hooks.remove_rule", "forecast.hooks.preview",
    "forecast.reforecast.start", "forecast.reforecast.status", "forecast.reforecast.active",
    "forecast.desk.task",
]


@pytest.mark.parametrize("method", FORECAST_METHODS)
def test_forecast_rpc_registered(method):
    spec = RPC_BY_METHOD[method]
    assert spec.request is not None and spec.response is not None


# ── real captured frames (the builders' actual emission) ──────────────────────


def test_dashboard_real_frame_validates():
    from forecasting.dashboard import build_dashboard_summary, render_dashboard_text

    summary = build_dashboard_summary(limit=5, fast=True)
    frame = {"summary": summary, "output": render_dashboard_text(summary)}
    model = RPC_BY_METHOD["forecast.dashboard"].response.model_validate(frame)
    assert model.summary is not None


def test_workspace_real_frame_validates():
    from forecasting.dashboard import build_workspace_payload

    frame = build_workspace_payload(
        limit=10, include_related=False, include_lessons=False, history_limit=40
    )
    model = RPC_BY_METHOD["forecast.workspace"].response.model_validate(frame)
    # the empty book is a valid workspace: an active_count present, forecasts a list
    assert model.active_count is not None or model.forecasts is not None


# ── representative literal frames for the smaller read RPCs ────────────────────


def test_quorum_status_frame_validates_and_tolerates_extras():
    frame = {
        "run_id": "qr_1", "status": "done", "question_id": "q1",
        "panel_run_id": "pr_1",
        "progress": [{"at": "2026-07-04T00:00:00Z", "stage": "collect", "detail": "n=5"}],
        "error": None,
        "result": {"aggregate_probability": 0.42, "committed_probability": 0.4,
                   "disagreement": 0.1, "degraded": False, "extra_detail": "kept"},
        "degraded": False,
    }
    model = RPC_BY_METHOD["forecast.quorum.status"].response.model_validate(frame)
    assert model.run_id == "qr_1" and model.result.aggregate_probability == 0.42


def test_schedule_and_reviews_frames_validate():
    schedule = {
        "cron": {"installed": 1, "jobs": [{"id": "j1", "enabled": True, "errored": False,
                                           "missed": False}], "errored": [], "missed": [],
                 "healthy": True},
        "healthy": True,
        "scheduled_reviews": [{"id": "r1", "scope_type": "question", "scope_ref": "q1",
                               "cadence": "weekly", "next_run_at": None, "last_run_at": None,
                               "trigger_reason": "manual"}],
        "scheduled_review_count": 1,
    }
    RPC_BY_METHOD["forecast.schedule.status"].response.model_validate(schedule)
    reviews = {"next_due_at": None, "due_count": 0,
               "sweeper": {"enabled": True, "interval_minutes": 15, "next_tick_at": None,
                           "running": False},
               "nightly": {"installed": False, "next_run_at": None, "last_run_at": None}}
    RPC_BY_METHOD["forecast.reviews.next"].response.model_validate(reviews)


def test_config_and_readiness_and_bench_and_triage_frames_validate():
    config = {
        "cadence": "weekly", "next_run_at": None, "profile": "standard",
        "question_id": "q1", "title": "Q",
        "decision": {"action_threshold": None, "decision_deadline": None,
                     "decision_owner": None, "update_triggers": []},
        "gates": [{"id": "g1", "label": "Gate", "severity": "warn", "source": "profile"}],
        "thresholds": [{"key": "min_sources", "label": "Min sources", "value": 2,
                        "default": 3, "minimum": 0, "maximum": 10, "source": "profile"}],
        "impact": None,
    }
    RPC_BY_METHOD["forecast.config"].response.model_validate(config)
    readiness = {"question_id": "q1", "title": "Q", "score": 80.0, "src_count": 2,
                 "gaps": [{"key": "sources", "label": "Watched sources", "fix_hint": "add one"}]}
    RPC_BY_METHOD["forecast.question.readiness"].response.model_validate(readiness)
    bench = {"product": "x", "count": 1, "resolved_count": 1,
             "rows": [{"id": "b1", "title": "T", "resolved": True, "agent_brier": 0.1,
                       "market_brier": 0.2, "brier_edge": 0.1}],
             "aggregate": {"n": 1, "mean_agent_brier": 0.1, "mean_market_brier": 0.2,
                           "mean_brier_edge": 0.1}}
    RPC_BY_METHOD["forecast.bench"].response.model_validate(bench)
    triage = {"contested": [{"id": "t1", "question_id": "q1", "title": "H", "summary": "S",
                             "rationale": "R", "relevance": 0.5, "auto_label": "irrelevant"}],
              "count": 1}
    RPC_BY_METHOD["forecast.triage.contested"].response.model_validate(triage)


@pytest.mark.parametrize("value", [0.42, "toss-up", {"pmf": {"a": 0.5, "b": 0.5}}, None])
def test_workspace_item_probability_multiunion_round_trips(value):
    from protocol.rpc.forecast import ForecastWorkspaceItem

    item = ForecastWorkspaceItem.model_validate({"id": "q1", "probability": value})
    assert item.probability == value


# ── gateway wrapper: VALIDATE-ONLY guarantees ─────────────────────────────────


def test_workspace_wrapper_returns_wire_byte_identical(monkeypatch):
    """Even a payload with an undeclared key is returned UNCHANGED (no re-serialise)."""
    from tui_gateway import server

    drifted = {"active_count": 1, "forecasts": [], "__unmodelled__": [1, 2, 3]}
    monkeypatch.setattr(
        "forecasting.dashboard.build_workspace_payload", lambda **kw: dict(drifted)
    )
    resp = server.handle_request({"id": "1", "method": "forecast.workspace", "params": {}})
    assert resp["result"] == drifted  # byte-identical, extra key survives


def test_quorum_status_missing_run_id_keeps_handler_error_code():
    """The wrapper never short-circuits the request — the handler's own 5008 stands."""
    from tui_gateway import server

    resp = server.handle_request(
        {"id": "1", "method": "forecast.quorum.status", "params": {}}
    )
    assert resp["error"]["code"] == 5008
    assert "run_id" in resp["error"]["message"]


def test_config_missing_id_keeps_handler_error_code():
    from tui_gateway import server

    resp = server.handle_request({"id": "1", "method": "forecast.config", "params": {}})
    assert resp["error"]["code"] == 4003
