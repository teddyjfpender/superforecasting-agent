"""S4 — the agent's first-class prediction-market pull.

Exercises the ``pm_query`` action of ``forecast_ledger_tool`` over a STUBBED
PMService (never touches the network), plus schema completeness and the
protocol/skill/README teaching text.
"""

from __future__ import annotations

import json
from pathlib import Path

import tools.forecasting_tool as ft
from tools.forecasting_tool import (
    FORECAST_LEDGER_SCHEMA,
    forecast_ledger_tool,
    set_pm_service,
)
from forecasting.pm.model import (
    PMDistribution,
    PMEvent,
    PMHistoryPoint,
    PMMarket,
    PMOrderBook,
    PMOrderLevel,
    PMOutcome,
)


def _event(venue="polymarket", event_id="evt-1"):
    market = PMMarket(
        venue=venue,
        market_id="mkt-a",
        label="Yes",
        question="Will X happen?",
        event_id=event_id,
        yes_bid=0.40,
        yes_ask=0.44,
        volume=1000.0,
    )
    return PMEvent(venue=venue, event_id=event_id, title="Will X?", markets=(market,))


def _distribution(venue="polymarket", event_id="evt-1"):
    return PMDistribution(
        venue=venue,
        event_id=event_id,
        title="Will X?",
        outcomes=(
            PMOutcome(label="Yes", prob=0.6, raw_prob=0.42, market_id="mkt-a", liquid=True),
            PMOutcome(label="No", prob=0.4, raw_prob=0.30, market_id="mkt-b", liquid=False),
        ),
        total_volume=1000.0,
        normalized=True,
    )


class _StubService:
    def __init__(self):
        self.calls = []

    def list_events(self, *, venue=None, query=None, tag=None, limit=40):
        self.calls.append(("list", venue, query, tag, limit))
        return [(_event(), _distribution())]

    def event_detail(self, venue, event_id):
        self.calls.append(("detail", venue, event_id))
        return _event(venue, event_id), _distribution(venue, event_id)

    def orderbook(self, venue, market_id):
        self.calls.append(("book", venue, market_id))
        return PMOrderBook(
            venue=venue,
            market_id=market_id,
            bids=(PMOrderLevel(price=0.40, size=500.0),),
            asks=(PMOrderLevel(price=0.44, size=300.0),),
        )

    def history(self, venue, market_id, *, series_ticker=None, interval="1w"):
        self.calls.append(("history", venue, market_id, series_ticker, interval))
        return [PMHistoryPoint(ts=1000, p=0.4), PMHistoryPoint(ts=2000, p=0.45)]


def _run(**args):
    return json.loads(forecast_ledger_tool(args))


def _stub():
    svc = _StubService()
    set_pm_service(svc)
    return svc


def teardown_function(_):
    # Reset the module singleton so a real PMService isn't leaked across tests.
    set_pm_service(None)


# ── modes over the stub ──────────────────────────────────────────────────────


def test_pm_query_search():
    svc = _stub()
    out = _run(action="pm_query", pm_mode="search", query="fed")
    assert out["success"] is True and out["mode"] == "search"
    assert out["count"] == 1
    row = out["events"][0]
    assert row["event"]["venue"] == "polymarket"
    assert row["distribution"]["normalized"] is True
    assert row["distribution"]["outcomes"][0]["label"] == "Yes"
    assert svc.calls[0][0] == "list" and svc.calls[0][2] == "fed"


def test_pm_query_search_accepts_mode_alias():
    _stub()
    out = _run(action="pm_query", mode="search")  # 'mode' alias, not 'pm_mode'
    assert out["success"] is True and out["mode"] == "search"


def test_pm_query_event():
    svc = _stub()
    out = _run(action="pm_query", pm_mode="event", venue="kalshi", event_id="E7")
    assert out["success"] is True and out["mode"] == "event"
    assert out["event"]["event_id"] == "E7"
    assert out["distribution"]["outcomes"][1]["liquid"] is False
    assert ("detail", "kalshi", "E7") in svc.calls


def test_pm_query_event_requires_ids():
    _stub()
    out = _run(action="pm_query", pm_mode="event", venue="kalshi")
    assert out.get("success") is False and "event_id" in out["error"]


def test_pm_query_book():
    svc = _stub()
    out = _run(action="pm_query", pm_mode="book", venue="polymarket", market_id="mkt-a")
    assert out["success"] is True and out["mode"] == "book"
    assert out["book"]["best_bid"] == 0.40 and out["book"]["best_ask"] == 0.44
    assert ("book", "polymarket", "mkt-a") in svc.calls


def test_pm_query_book_requires_market_id():
    _stub()
    out = _run(action="pm_query", pm_mode="book", venue="polymarket")
    assert out.get("success") is False and "market_id" in out["error"]


def test_pm_query_history_passes_range_and_series():
    svc = _stub()
    out = _run(
        action="pm_query",
        pm_mode="history",
        venue="kalshi",
        market_id="mkt-a",
        range="1m",
        series_ticker="KXSER",
    )
    assert out["success"] is True and out["mode"] == "history"
    assert out["count"] == 2 and out["points"][0]["p"] == 0.4
    hist = [c for c in svc.calls if c[0] == "history"][0]
    assert hist[3] == "KXSER" and hist[4] == "1m"


def test_pm_query_unknown_mode():
    _stub()
    out = _run(action="pm_query", pm_mode="frobnicate")
    assert out.get("success") is False
    assert "search" in out["error"] and "history" in out["error"]


# ── schema completeness ──────────────────────────────────────────────────────


def test_schema_registers_pm_query_and_params():
    props = FORECAST_LEDGER_SCHEMA["parameters"]["properties"]
    assert "pm_query" in props["action"]["enum"]
    assert props["pm_mode"]["enum"] == ["search", "event", "book", "history"]
    assert set(props["venue"]["enum"]) == {"polymarket", "kalshi"}
    for key in ("event_id", "market_id", "range", "series_ticker", "tag"):
        assert key in props, key


def test_service_singleton_is_lazy_and_injectable():
    set_pm_service(None)
    stub = _StubService()
    set_pm_service(stub)
    assert ft._pm_service() is stub


# ── teaching text presence ───────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parents[2]


def test_protocol_teaches_pm_query():
    text = (_ROOT / "forecasting" / "protocol.py").read_text()
    assert "pm_query" in text
    assert "de-vigged" in text


def test_skill_and_readme_mention_pm_query():
    skill = (_ROOT / "skills" / "forecasting-loop" / "SKILL.md").read_text()
    readme = (_ROOT / "README.md").read_text()
    assert "pm_query" in skill
    assert "pm_query" in readme
    assert "Prediction Markets" in readme
