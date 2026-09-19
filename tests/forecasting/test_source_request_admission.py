"""Invalid options must not become plausible provider requests through coercion."""

import pytest

from forecasting.sources import dispatch
from forecasting.sources.watched import fetch_watched_source_payloads


@pytest.mark.parametrize(
    "options",
    [
        {"limit": "7"},
        {"limit": True},
        {"limit": 0},
        {"limit": -1},
        {"limit": 1.5},
        {"dedupe": "false"},
        {"local": "false"},
        {"only_media": 0},
        {"forecast_days": 0},
        {"forecast_days": "5"},
        {"since": "2026-02-30"},
        {"since": "2026-01-01T12:00:00"},
        {"since": 2026},
        {"api_base_url": "file:///tmp/secret"},
        {"api_base_url": "https://example.invalid:99999"},
    ],
)
def test_invalid_common_options_fail_before_fetch(monkeypatch, options):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid options reached network acquisition")

    monkeypatch.setattr(dispatch, "load_news_feed_items", forbidden)
    with pytest.raises(ValueError, match="invalid source options"):
        dispatch.load_source_items("rss", "https://example.invalid/feed", options)


def test_explicit_false_and_sparse_history_limits_preserve_meaning(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dispatch,
        "load_news_feed_items",
        lambda source, **args: calls.append(args) or [],
    )
    options = {"limit": 1, "dedupe": False, "since": "2026-01-01T12:00:00+04:00"}
    dispatch.load_source_items(" ADAPTER:RSS ", "https://example.invalid/feed", options)
    assert calls[0]["dedupe"] is False
    assert calls[0]["limit"] == 1
    assert calls[0]["since"] == options["since"]
    assert options["dedupe"] is False


def test_provider_defaults_are_explicit_and_not_truthiness_based(monkeypatch):
    calls = []
    fetch = lambda source, **args: calls.append(args) or []
    monkeypatch.setattr(dispatch, "load_openmeteo_daily_forecasts", fetch)
    monkeypatch.setattr(dispatch, "load_openmeteo_air_quality_forecasts", fetch)
    dispatch.load_source_items("openmeteo", "London", {})
    dispatch.load_source_items("airquality", "London", {"forecast_days": 1})
    assert [(args["limit"], args["forecast_days"]) for args in calls] == [
        (10, 7),
        (10, 1),
    ]


def test_watched_sources_preserve_validation_and_isolate_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dispatch,
        "load_fred_observations",
        lambda source, **args: calls.append(source) or [],
    )
    results = fetch_watched_source_payloads([
        {"source_type": "fred", "source": 123},
        {"source_type": "fred", "source": "INVALID", "args": [["limit", 3]]},
        {"source_type": "fred", "source": "INVALID", "args": {"limit": "3"}},
        {"source_type": "fred", "source": "UNRATE", "args": {"limit": 3}},
    ])
    assert [item["success"] for item in results] == [False, False, False, True]
    assert calls == ["UNRATE"]
    assert all(item["payloads"] == [] for item in results)


def test_errors_do_not_echo_endpoint_credentials():
    with pytest.raises(ValueError) as error:
        dispatch.load_source_items(
            "fred", "UNRATE", {"api_base_url": "file://token-secret/path"}
        )
    assert str(error.value) == "invalid source options: api_base_url"
    assert "token-secret" not in str(error.value)


def test_annual_since_is_forwarded_without_inventing_a_day(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dispatch,
        "load_imf_datamapper_observations",
        lambda source, **args: calls.append(args) or [],
    )
    dispatch.load_source_items("imf", "NGDP_RPCH/USA", {"since": "2023"})
    assert calls[0]["since"] == "2023"
