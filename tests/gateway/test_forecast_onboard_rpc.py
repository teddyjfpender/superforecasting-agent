"""Gateway RPC tests for forecast.onboard_propose / forecast.onboard_commit."""

from __future__ import annotations

import json

from tui_gateway import server


def _good_spec():
    return {
        "title": "US CPI YoY for the June 2026 print",
        "resolution_criteria": "Resolves yes if BLS June 2026 CPI YoY exceeds 3.0 percent.",
        "decision_owner": "me",
        "action_threshold": ">=70% act",
        "update_triggers": [{"mechanism": "CPI print", "operator": ">", "threshold": 3.0, "source_ref": "fred:CPIAUCSL"}],
        "watched_sources": [{"source": "fred:CPIAUCSL", "source_type": "fred", "reliability_prior": 0.9}],
        "reference_classes": [{"name": "recent CPI prints", "inclusion_criteria": "monthly CPI since 2015", "base_rate": 0.4}],
    }


def test_onboard_propose_returns_issues_and_clarifications(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(tmp_path / "p.db"))
    propose = server._methods["forecast.onboard_propose"]
    res = propose(1, {"spec": {"title": "forecast", "resolution_criteria": "tbd"}})["result"]
    assert res["committable"] is False
    assert {e["field"] for e in res["errors"]} >= {"title", "resolution_criteria"}
    assert res["recommended_clarifications"]
    for c in res["recommended_clarifications"]:
        assert len(c["choices"]) <= 4


def test_onboard_commit_refuses_then_creates(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(tmp_path / "c.db"))
    commit = server._methods["forecast.onboard_commit"]

    bad = commit(2, {"spec": {"title": "x", "resolution_criteria": "tbd"}})["result"]
    assert bad["committed"] is False
    assert bad["issues"]

    ok = commit(3, {"spec": _good_spec()})["result"]
    assert ok["committed"] is True
    assert ok["question_id"]
    assert len(ok["watched_sources"]) == 1
    assert len(ok["reference_classes"]) == 1
    # JSON-serializable (the RPC envelope must encode)
    json.dumps(ok)
