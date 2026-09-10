"""Optional source metadata must not discard an otherwise usable record."""

import json
from dataclasses import asdict

import pytest

from forecasting import source_adapters


@pytest.mark.parametrize(
    ("raw_count", "expected"),
    [
        ("NaN", None),
        ("Infinity", None),
        ("-Infinity", None),
        ("1e999", None),
        ("123", 123),
        ("", None),
        (None, None),
        ("not-a-number", None),
    ],
)
def test_repository_snapshot_retains_record_with_invalid_optional_count(
    monkeypatch, raw_count, expected
):
    payload = {"id": 456, "full_name": "acme/desk", "stargazers_count": raw_count}
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: payload)

    snapshots = source_adapters.load_github_repository_snapshots("githubrepo:acme/desk")

    assert len(snapshots) == 1
    assert snapshots[0].repo == "acme/desk"
    assert snapshots[0].stargazers_count == expected
    assert snapshots[0].raw["stargazers_count"] == raw_count


@pytest.mark.parametrize(("raw_temperature", "expected"), [
    ("NaN", None), ("Infinity", None), ("-Infinity", None), ("1e999", None),
    (10 ** 400, None), ("0", 0.0), ("-12.5", -12.5), ("1e308", 1e308),
], ids=["nan", "positive-infinity", "negative-infinity", "exponent-overflow",
        "integer-overflow", "zero", "negative", "large-finite"])
def test_weather_record_remains_json_safe_with_invalid_optional_number(
    monkeypatch, raw_temperature, expected
):
    payload = {"daily": {
        "time": ["2030-01-01"],
        "temperature_2m_max": [raw_temperature],
        "temperature_2m_min": ["4.5"],
    }}
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: payload)

    rows = source_adapters.load_openmeteo_daily_forecasts("51.5,-0.1")

    assert len(rows) == 1
    json.dumps(asdict(rows[0]), allow_nan=False)
    assert rows[0].temperature_2m_max == expected
    assert rows[0].temperature_2m_min == 4.5
