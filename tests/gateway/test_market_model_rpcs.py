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
    for m in ("create", "chat", "retry", "list", "get", "renarrate", "export", "to_forecast", "delete"):
        assert f"markets.model.{m}" in S._methods


def test_fallback_chain_import_contract():
    # _session_runtime depends on this EXACT name + behaviour to give the market
    # agent provider failover. Regression guard: a wrong import name was silently
    # swallowed, killing the failover entirely.
    from hermes_cli.fallback_cmd import _read_chain

    assert _read_chain({"fallback_providers": [{"provider": "p", "model": "m"}]}) == [{"provider": "p", "model": "m"}]
    assert _read_chain({}) == []


def test_session_runtime_surfaces_fallback_and_interactive(monkeypatch):
    monkeypatch.setattr(S, "_resolve_startup_runtime", lambda: ("model-x", "prov-x"))
    monkeypatch.setattr("hermes_cli.runtime_provider.resolve_runtime_provider",
                        lambda **k: {"provider": "prov-x", "base_url": None, "api_key": "k", "api_mode": None})
    monkeypatch.setattr("hermes_cli.config.load_config_readonly",
                        lambda: {"fallback_providers": [{"provider": "fb", "model": "fb/m"}]})
    monkeypatch.delenv("HERMES_MARKET_INTERACTIVE", raising=False)
    rt = S._session_runtime("")
    assert rt["fallback_model"] == [{"provider": "fb", "model": "fb/m"}]  # failover wired (was dead)
    assert rt["interactive"] is False  # opt-in, off by default
    monkeypatch.setenv("HERMES_MARKET_INTERACTIVE", "1")
    assert S._session_runtime("")["interactive"] is True


def test_retry_reruns_build_on_same_model(tmp_ledger, monkeypatch):
    import json as _json

    import forecasting.market_model as MM

    calls: list[str] = []

    def _fake_agent(**k):
        calls.append(str(k.get("user", "")))
        return {
            "final_response": "done", "model": "m", "completed": True, "api_calls": 2,
            "messages": [{"role": "assistant", "tool_calls": [
                {"id": "t1", "function": {"name": "emit_market_presentation",
                                          "arguments": _json.dumps({"presentation": _good_pres(), "spec": {}})}}
            ]}],
        }

    monkeypatch.setattr(MM, "_run_market_agent", _fake_agent)
    events: list[tuple] = []
    monkeypatch.setattr(S, "_emit", lambda ev, sid, payload=None: events.append((ev, payload)))

    created = _call("markets.model.create", {"question": "how does compute drive revenue", "params": {"depth": "quick"}})
    mid = created["result"]["model_id"]
    for _ in range(50):
        if any(e[0] == "markets.model.complete" for e in events):
            break
        time.sleep(0.05)

    events.clear()
    resp = _call("markets.model.retry", {"id": mid})
    assert resp["result"]["status"] == "building"
    assert resp["result"]["model_id"] == mid  # same model, not a new one
    for _ in range(50):
        if any(e[0] == "markets.model.complete" for e in events):
            break
        time.sleep(0.05)
    assert any(e[0] == "markets.model.complete" for e in events)
    # The retry re-ran the agent reusing the stored question.
    assert any("compute drive revenue" in c for c in calls)

    # Unknown id is a clean error, not a crash.
    bad = _call("markets.model.retry", {"id": "nope"})
    assert "error" in bad


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
