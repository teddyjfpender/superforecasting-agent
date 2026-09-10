"""An unrepresentable chart timestamp must not discard valid price rows."""

import pytest
from forecasting import source_adapters


@pytest.mark.parametrize("timestamp, expected", [
    pytest.param(1e100, None, id="positive-overflow"),
    pytest.param(-1e100, None, id="negative-overflow"),
    pytest.param(0, "1970-01-01T00:00:00Z", id="epoch-zero"),
    pytest.param(-1, "1969-12-31T23:59:59Z", id="before-epoch"),
])
def test_chart_skips_invalid_timestamps_without_losing_prices(monkeypatch, timestamp, expected):
    payload = {"chart": {"result": [{"meta": {"symbol": "FIXTURE"},
        "timestamp": [timestamp, 1700000000],
        "indicators": {"quote": [{"close": [10.0, 20.0]}]},
    }]}}
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *_: payload)

    rows = source_adapters.load_yahoo_finance_prices("FIXTURE")

    expected_rows = [("2023-11-14T22:13:20Z", 20)]
    if expected is not None:
        expected_rows.insert(0, (expected, 10))
    assert [(row.observation_time, row.close_price) for row in rows] == expected_rows
