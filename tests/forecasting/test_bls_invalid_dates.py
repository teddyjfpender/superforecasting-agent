"""Malformed observation years must not discard valid sibling BLS rows."""

import pytest
from forecasting import source_adapters


@pytest.mark.parametrize("year", ["0", "10000", "999999999999999999999", "²"])
def test_bls_skips_unrepresentable_years(monkeypatch, year):
    payload = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [{"seriesID": "FIXTURE", "data": [
        {"year": year, "period": "M01", "value": "1.2"},
        {"year": "2026", "period": "M02", "value": "3.4"},
    ]}]}}
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *_: payload)
    monkeypatch.delenv("BLS_API_KEY", raising=False)
    rows = source_adapters.load_bls_observations("FIXTURE")
    assert [(row.observation_date, row.value) for row in rows] == [("2026-02-01", 3.4)]
