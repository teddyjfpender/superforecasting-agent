"""Tests for the markets.model.* gateway RPCs."""

from __future__ import annotations

import time

import pytest

import tui_gateway.server as S


@pytest.fixture()
def tmp_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(tmp_path / "ledger.db"))
    return tmp_path


def _call(method, params):
    return S._methods[method](1, params)


def _good_pres():
    return {"schema_version": "market-presentation-v1", "title": "t", "summary": "s", "status": "complete",
            "blocks": [{"type": "metric", "id": "m", "label": "R2", "value": 0.9}]}


def test_all_market_methods_registered():
    for m in ("create", "chat", "list", "get", "renarrate", "export", "to_forecast", "delete"):
        assert f"markets.model.{m}" in S._methods


def test_create_returns_building_then_completes(tmp_ledger, monkeypatch):
    import forecasting.market_model as MM

    # Make the background build deterministic + instant (real run_conversation shape).
    import json as _json

    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: {
        "final_response": "done", "model": "m", "completed": True, "api_calls": 2,
        "messages": [{"role": "assistant", "tool_calls": [
            {"id": "t1", "function": {"name": "emit_market_presentation",
                                      "arguments": _json.dumps({"presentation": _good_pres(), "spec": {}})}}
        ]}],
    })
    events = []
    monkeypatch.setattr(S, "_emit", lambda ev, sid, payload=None: events.append((ev, payload)))

    resp = _call("markets.model.create", {"question": "how does X drive Y", "params": {"depth": "quick"}})
    assert resp["result"]["status"] == "building"
    mid = resp["result"]["model_id"]

    # background thread finishes quickly
    for _ in range(50):
        if any(e[0] == "markets.model.complete" for e in events):
            break
        time.sleep(0.05)
    assert any(e[0] == "markets.model.complete" for e in events)

    listed = _call("markets.model.list", {})
    row = next(m for m in listed["result"]["models"] if m["id"] == mid)
    assert row["last_status"] == "complete"  # the emit produced a real presentation
    got = _call("markets.model.get", {"id": mid})
    assert got["result"]["packet"]["model"]["id"] == mid
    assert got["result"]["packet"]["presentation"]["presentation"]["status"] == "complete"


def test_create_requires_question(tmp_ledger):
    resp = _call("markets.model.create", {"question": "  "})
    assert "error" in resp


def test_delete(tmp_ledger, monkeypatch):
    from forecasting.ledger import ForecastLedger

    lg = ForecastLedger()
    m = lg.create_market_model(title="t", question="q")
    resp = _call("markets.model.delete", {"id": m["id"]})
    assert resp["result"]["deleted"] is True


def test_export_writes_json(tmp_ledger, monkeypatch):
    from forecasting.ledger import ForecastLedger

    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: str(tmp_ledger))
    lg = ForecastLedger()
    m = lg.create_market_model(title="GPU model", question="q")
    lg.add_market_presentation(model_id=m["id"], presentation=_good_pres())
    resp = _call("markets.model.export", {"id": m["id"]})
    assert resp["result"]["path"].endswith(".json")
    assert resp["result"]["bytes"] > 0


def test_renarrate_is_long_handler():
    assert "markets.model.renarrate" in S._LONG_HANDLERS
