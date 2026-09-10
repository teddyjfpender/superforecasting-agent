"""Unrepresentable optional earthquake metadata must not discard a feed."""
import pytest
from forecasting import source_adapters


@pytest.mark.parametrize("timestamp", [1e100, -1e100, "1e100", "-1e100"])
def test_usgs_unrepresentable_timestamp_keeps_events(monkeypatch, timestamp):
    payload = {"features": [
        {"id": "bad-date", "properties": {"time": timestamp, "updated": timestamp}},
        {"id": "valid-date", "properties": {"time": 1704067200000}},
    ]}
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: payload)
    events = source_adapters.load_usgs_earthquakes("minmagnitude=4")
    assert [event.event_id for event in events] == ["bad-date", "valid-date"]
    assert events[0].time is None
    assert events[0].updated_at is None
    assert events[1].time == "2024-01-01T00:00:00Z"


@pytest.mark.parametrize("timestamp,expected", [
    (0, "1970-01-01T00:00:00Z"),
    (1704067200, "2024-01-01T00:00:00Z"),
    (1704067200000, "2024-01-01T00:00:00Z"),
    ("2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
])
def test_usgs_existing_timestamp_formats(monkeypatch, timestamp, expected):
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: {
        "features": [{"id": "valid-date", "properties": {"time": timestamp}}]
    })
    assert source_adapters.load_usgs_earthquakes("minmagnitude=4")[0].time == expected
