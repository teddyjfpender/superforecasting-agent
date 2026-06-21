"""Tests for the Market Models ledger tables/CRUD (forecasting.ledger)."""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger, LedgerNotFoundError


@pytest.fixture()
def ledger(tmp_path):
    lg = ForecastLedger(db_path=tmp_path / "ledger.db")
    lg.initialize_schema()
    return lg


def test_create_and_get_model(ledger):
    m = ledger.create_market_model(title="GPU vs NVDA", question="how does compute drive revenue", depth="deep",
                                   spec={"series": [{"name": "flops"}]}, tags=["gpu"])
    assert m["id"].startswith("mm_")
    assert m["current_version"] == 0
    assert m["spec"]["series"][0]["name"] == "flops"
    fetched = ledger.get_market_model(m["id"])
    assert fetched["title"] == "GPU vs NVDA"


def test_presentation_versions_append_and_advance(ledger):
    m = ledger.create_market_model(title="t", question="q")
    p1 = ledger.add_market_presentation(model_id=m["id"], presentation={"title": "t", "blocks": []}, summary="v1")
    p2 = ledger.add_market_presentation(model_id=m["id"], presentation={"title": "t", "blocks": []}, summary="v2")
    assert p1["version"] == 1 and p2["version"] == 2
    assert ledger.get_market_model(m["id"])["current_version"] == 2
    # default get → latest
    assert ledger.get_market_presentation(m["id"])["version"] == 2
    assert ledger.get_market_presentation(m["id"], version=1)["summary"] == "v1"
    assert len(ledger.list_market_presentations(m["id"])) == 2


def test_messages_and_series_roundtrip(ledger):
    m = ledger.create_market_model(title="t", question="q")
    ledger.add_market_message(model_id=m["id"], role="user", content="extend to 2030")
    ledger.add_market_message(model_id=m["id"], role="assistant", content="done", version_ref=1)
    msgs = ledger.list_market_messages(m["id"])
    assert [x["role"] for x in msgs] == ["user", "assistant"]

    ledger.add_market_data_series(model_id=m["id"], name="NVDA rev", source_type="sec",
                                  points=[{"x": 2020, "value": 10}, {"x": 2021, "value": 27}])
    series = ledger.list_market_data_series(m["id"])
    assert series[0]["name"] == "NVDA rev"
    assert series[0]["points"][1]["value"] == 27


def test_replace_series_used_by_repull(ledger):
    m = ledger.create_market_model(title="t", question="q")
    ledger.add_market_data_series(model_id=m["id"], name="old", points=[{"x": 1, "value": 1}])
    ledger.replace_market_data_series(m["id"], [{"name": "fresh", "points": [{"x": 1, "value": 2}]}])
    series = ledger.list_market_data_series(m["id"])
    assert len(series) == 1 and series[0]["name"] == "fresh"


def test_export_packet_shape(ledger):
    m = ledger.create_market_model(title="t", question="q")
    ledger.add_market_presentation(model_id=m["id"], presentation={"title": "t", "blocks": []})
    packet = ledger.export_market_model(m["id"])
    assert packet["model"]["id"] == m["id"]
    assert packet["presentation"]["version"] == 1
    assert packet["product"] == "market-models"


def test_delete_cascades(ledger):
    m = ledger.create_market_model(title="t", question="q")
    ledger.add_market_presentation(model_id=m["id"], presentation={"title": "t", "blocks": []})
    ledger.add_market_data_series(model_id=m["id"], name="s", points=[])
    assert ledger.delete_market_model(m["id"]) is True
    with pytest.raises(LedgerNotFoundError):
        ledger.get_market_model(m["id"])
    # cascade removed children
    assert ledger.list_market_data_series(m["id"]) == []


def test_create_validation(ledger):
    with pytest.raises(Exception):
        ledger.create_market_model(title="", question="q")
