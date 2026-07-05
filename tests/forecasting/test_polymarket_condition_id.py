"""Polymarket conditionId → Gamma lookup (forecasting/source_adapters.py).

ForecastBench stores a Polymarket market as its on-chain ``conditionId`` (a
``0x``-prefixed 32-byte hex hash), but Gamma's ``/markets`` endpoint keys its
``id`` filter on the NUMERIC market id — a conditionId there returns HTTP 422, so
9 past-due polymarket questions were undetectable by the resolution detector.
These tests pin the fix: a conditionId routes to the dedicated ``condition_ids``
filter, a SETTLED market (hidden by Gamma's open-only default) is recovered via an
explicit ``closed=true`` re-query, and its terminal ``outcomePrices`` parse to a
terminal probability the detector reader can read. One bounded live probe
(``integration`` marker, skipped by default) exercises the real Gamma endpoint.
"""

from __future__ import annotations

import json

import pytest

import forecasting.source_adapters as sa

BASE = "https://gamma-api.polymarket.com"
# a real, resolved conditionId (Israeli parliament dissolved by June 30 → NO)
LIVE_CONDITION_ID = "0x3f0bc2757babb8bb9971c9f782fe81f9db734c12d84822f1120a90681c991ff8"
HEX64 = "0x" + "a" * 64


# ── pure: conditionId detection + endpoint routing (no network) ──────────────────
def test_is_condition_id_true_for_0x_hex():
    assert sa._polymarket_is_condition_id(HEX64)
    assert sa._polymarket_is_condition_id(LIVE_CONDITION_ID)
    assert sa._polymarket_is_condition_id("0xABCDEF")


def test_is_condition_id_false_for_numeric_and_slug():
    assert not sa._polymarket_is_condition_id("512724")
    assert not sa._polymarket_is_condition_id("israeli-parliament-dissolved")
    assert not sa._polymarket_is_condition_id("0x")  # empty body
    assert not sa._polymarket_is_condition_id("0xnothex")


def test_endpoint_routes_condition_id_to_condition_ids_filter():
    url = sa._polymarket_endpoint_for_source(f"id:{HEX64}", api_base_url=BASE)
    assert f"condition_ids={HEX64}" in url
    assert "id=" not in url.replace("condition_ids=", "")  # not the numeric id filter


def test_endpoint_keeps_numeric_id_on_id_filter():
    url = sa._polymarket_endpoint_for_source("id:512724", api_base_url=BASE)
    assert "id=512724" in url
    assert "condition_ids" not in url


def test_endpoint_routes_bare_condition_id_not_as_slug():
    # a conditionId with no ``id:`` prefix is still a conditionId, never a slug
    url = sa._polymarket_endpoint_for_source(HEX64, api_base_url=BASE)
    assert f"condition_ids={HEX64}" in url and "slug=" not in url


# ── load_polymarket_market: settled-market fallback + terminal parse ──────────────
def _settled_market(prices):
    return {
        "question": "Will the linked market settle?",
        "conditionId": HEX64,
        "id": "999001",
        "slug": "linked-market",
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(prices),
        "closed": True,
        "volumeNum": 1000.0,
    }


def test_closed_condition_id_uses_closed_fallback(monkeypatch):
    """The open ``condition_ids`` view is empty for a settled market; the loader
    re-queries with ``closed=true`` and recovers the terminal outcome."""
    calls: list[str] = []

    def fake_read(url, label, **kw):
        calls.append(url)
        if "closed=true" in url:
            return [_settled_market(["0", "1"])]  # resolved NO (YES price 0)
        return []  # open-only default hides the settled market

    monkeypatch.setattr(sa, "_read_json_endpoint", fake_read)
    market = sa.load_polymarket_market(f"id:{HEX64}")
    assert market.probability == 0.0  # terminal NO
    assert any("condition_ids=" in u and "closed=true" not in u for u in calls)  # open first
    assert any("closed=true" in u for u in calls)  # then the closed fallback


def test_open_condition_id_returns_without_fallback(monkeypatch):
    """An OPEN market answers on the first ``condition_ids`` query — no fallback."""
    calls: list[str] = []

    def fake_read(url, label, **kw):
        calls.append(url)
        row = _settled_market(["0.42", "0.58"])
        row["closed"] = False
        return [row]

    monkeypatch.setattr(sa, "_read_json_endpoint", fake_read)
    market = sa.load_polymarket_market(f"id:{HEX64}")
    assert market.probability == pytest.approx(0.42)
    assert len(calls) == 1 and "closed=true" not in calls[0]


def test_condition_id_resolved_yes(monkeypatch):
    monkeypatch.setattr(
        sa, "_read_json_endpoint",
        lambda url, label, **kw: ([_settled_market(["1", "0"])] if "closed=true" in url else []),
    )
    assert sa.load_polymarket_market(f"id:{HEX64}").probability == 1.0  # terminal YES


def test_unknown_condition_id_raises_after_fallback(monkeypatch):
    monkeypatch.setattr(sa, "_read_json_endpoint", lambda url, label, **kw: [])
    with pytest.raises(sa.ValidationError):
        sa.load_polymarket_market(f"id:{HEX64}")


# ── detector-coverage regression pin: a forecastbench:conditionId past-due ───────
#    polymarket question becomes DETERMINABLE through the real venue-dispatch
#    reader (this is exactly the arm that raised live coverage 33 → 42/94).
def test_detector_reads_forecastbench_condition_id(tmp_path, monkeypatch):
    import forecasting.resolution_detector as rd
    from forecasting.ledger import ForecastLedger

    def fake_read(url, label, **kw):
        # the fix must NEVER hit Gamma's numeric ``id`` filter with a conditionId
        # (that path 422s) — it routes conditionIds to ``condition_ids``.
        assert f"id={HEX64}" not in url, "conditionId must not use the numeric id filter"
        if "condition_ids=" in url and "closed=true" in url:
            return [_settled_market(["0", "1"])]  # settled NO
        return []

    monkeypatch.setattr(sa, "_read_json_endpoint", fake_read)
    lg = ForecastLedger(db_path=str(tmp_path / "cov.db"))
    lg.initialize_schema()
    q = lg.create_question(
        title="Will the ForecastBench-linked polymarket settle YES?",
        resolution_criteria="Resolves to the linked polymarket market.",
        resolution_time="2020-01-01T00:00:00Z",
        metadata={"market_id": f"forecastbench:{HEX64}", "market_source": "polymarket"},
    )
    now_dt = rd.timestamp_to_datetime("2021-01-01T00:00:00Z")
    detection = rd.detect_deterministic(lg, lg.get_question(q.id), now_dt=now_dt, market_reader=rd.build_market_outcome_reader())
    assert detection.determinable()
    assert detection.outcome == "no"
    assert detection.trigger == rd.TRIGGER_MARKET_TERMINAL


# ── one bounded live probe (skipped by default; run with -m integration) ─────────
@pytest.mark.integration
def test_live_condition_id_resolves_to_terminal():
    market = sa.load_polymarket_market(f"id:{LIVE_CONDITION_ID}")
    assert market.probability is not None
    # a settled market prints a terminal (saturated) YES probability
    assert market.probability <= 0.05 or market.probability >= 0.95
