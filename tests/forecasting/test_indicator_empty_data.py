"""Empty or incomplete indicator data should be a normal import result."""
import pytest
from forecasting import source_adapters


@pytest.mark.parametrize("entity", ["", "   "])
def test_owid_filter_skips_rows_without_entity(monkeypatch, entity):
    csv = f"Entity,Code,Year,Value\n{entity},,2024,1\nFrance,FRA,2024,2\n"
    monkeypatch.setattr(source_adapters, "_read_text_endpoint", lambda *args: csv)
    rows = source_adapters.load_owid_observations("fixture", entity="france")
    assert len(rows) == 1
    assert rows[0].entity == "France"
    assert rows[0].value == 2


@pytest.mark.parametrize("key", ["value", "results", "data"])
def test_who_empty_result_is_valid(monkeypatch, key):
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: {key: []})
    assert source_adapters.load_who_gho_observations("fixture") == []


def test_who_prefers_primary_array_even_when_empty(monkeypatch):
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: {
        "value": [], "results": [{"Id": "stale", "NumericValue": 5}]
    })
    assert source_adapters.load_who_gho_observations("fixture") == []


def test_who_legacy_rows_remain_supported(monkeypatch):
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: {
        "results": [{"Id": "fixture", "NumericValue": 5}]
    })
    rows = source_adapters.load_who_gho_observations("fixture")
    assert len(rows) == 1
    assert rows[0].numeric_value == 5


@pytest.mark.parametrize("year", [10**400, -(10**400)], ids=["huge-year", "negative-huge-year"])
def test_who_unrepresentable_year_keeps_observation(monkeypatch, year):
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: {
        "value": [{"Id": "fixture", "TimeDim": year, "NumericValue": 5}]
    })
    rows = source_adapters.load_who_gho_observations("fixture")
    assert len(rows) == 1
    assert rows[0].published_at is None
    assert rows[0].numeric_value == 5
