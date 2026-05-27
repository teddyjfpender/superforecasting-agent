from __future__ import annotations

import pytest

from forecasting.extensions import ForecastExtension, ForecastExtensionRegistry, extension_registry


def test_extension_registry_filters_by_kind():
    registry = ForecastExtensionRegistry()
    registry.register(
        ForecastExtension(
            name="test-importer",
            kind="importer",
            description="Test importer.",
            version="1",
        )
    )

    assert registry.list(kind="model") == []
    assert registry.list(kind="importer")[0].name == "test-importer"


def test_builtin_forecast_extensions_are_registered():
    names = {extension.name for extension in extension_registry.list()}

    assert "benchmark-json" in names
    assert "tournament-export" in names
    assert "github-releases" in names
    assert "fivethirtyeight-polls" in names
    assert "github-issues" in names
    assert "github-commits" in names
    assert "github-actions" in names
    assert "coingecko-market-data" in names
    assert "pypi-releases" in names
    assert "npm-package-versions" in names
    assert "hackernews-search" in names
    assert "reddit-search" in names
    assert "bluesky-search" in names
    assert "mastodon-hashtag-timeline" in names
    assert "federal-register-documents" in names
    assert "courtlistener-search" in names
    assert "nvd-cves" in names
    assert "cisa-kev" in names
    assert "openmeteo-daily-forecast" in names
    assert "openmeteo-air-quality" in names
    assert "openmeteo-historical-weather" in names
    assert "usgs-earthquakes" in names
    assert "nasa-eonet-events" in names
    assert "nws-alerts" in names
    assert "clinicaltrials-studies" in names
    assert "openfda-drug-applications" in names
    assert "pubmed-articles" in names
    assert "owid-grapher" in names
    assert "who-gho-indicators" in names
    assert "fema-disaster-declarations" in names
    assert "eia-energy-data" in names
    assert "treasury-fiscal-data" in names
    assert "bls-economic-data" in names
    assert "worldbank-indicators" in names
    assert "census-data" in names
    assert "socrata-open-data" in names
    assert "ckan-open-data" in names
    assert "stooq-market-data" in names
    assert "yahoo-finance-chart" in names
    assert "sec-edgar-filings" in names
    assert "sec-company-facts" in names
    assert "arxiv-papers" in names
    assert "openalex-works" in names
    assert "crossref-works" in names
    assert "reliefweb-reports" in names
    assert "wikipedia-pages" in names
    assert "wikimedia-pageviews" in names
    assert "bayesian-update" in names
    assert "weighted-ensemble" in names
    assert "prediction-market" in names


def test_source_fetch_timeout_default_and_env(monkeypatch):
    from forecasting import source_adapters

    for name in (
        "SUPERFORECASTING_AGENT_SOURCE_TIMEOUT",
        "FORECAST_SOURCE_TIMEOUT",
        "HERMES_SOURCE_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)
    # Default is the forgiving 30s (was a too-tight 10s that produced spurious
    # "FRED refresh timed out" reports on slow government endpoints).
    assert source_adapters._source_fetch_timeout() == 30.0

    monkeypatch.setenv("FORECAST_SOURCE_TIMEOUT", "45")
    assert source_adapters._source_fetch_timeout() == 45.0

    # Non-numeric / non-positive values fall back to the default.
    monkeypatch.setenv("FORECAST_SOURCE_TIMEOUT", "bogus")
    assert source_adapters._source_fetch_timeout() == 30.0
    monkeypatch.setenv("FORECAST_SOURCE_TIMEOUT", "0")
    assert source_adapters._source_fetch_timeout() == 30.0


def test_eia_endpoint_injects_api_key(monkeypatch):
    """load_eia_observations must add the required api_key from EIA_API_KEY."""
    from forecasting import source_adapters

    captured = {}

    def _fake_read_json(url, label):
        captured["url"] = url
        return {"series": []}

    monkeypatch.setenv("EIA_API_KEY", "test-eia-key")
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", _fake_read_json)
    source_adapters.load_eia_observations("eia:PET.EMM_EPM0_PTE_NUS_DPG.W", limit=5)
    assert "api_key=test-eia-key" in captured["url"]


def test_fred_uses_official_api_when_key_set(monkeypatch):
    """With FRED_API_KEY set, the reliable official FRED API is used."""
    from forecasting import source_adapters

    captured = {}

    def _fake_json(url, label, *, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return {"observations": [
            {"date": "2026-05-18", "value": "4.46"},
            {"date": "2026-05-25", "value": "4.475"},
        ]}

    monkeypatch.setenv("FRED_API_KEY", "test-fred-key")
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", _fake_json)
    rows = source_adapters.load_fred_observations("GASREGW", limit=2)
    assert "api.stlouisfed.org/fred/series/observations" in captured["url"]
    assert "api_key=test-fred-key" in captured["url"]
    assert captured["timeout"] == source_adapters._fred_fetch_timeout()
    assert [r.observation_date for r in rows] == ["2026-05-18", "2026-05-25"]
    assert rows[-1].value == 4.475


def test_fred_falls_back_to_series_page_when_csv_fails(monkeypatch):
    """When the CSV endpoint fails, the series-page HTML is used as a fallback."""
    from forecasting import source_adapters
    from forecasting.models import ValidationError

    monkeypatch.delenv("FRED_API_KEY", raising=False)

    def _fake_text(url, label, *, timeout=None):
        if "fredgraph.csv" in url:
            raise ValidationError("fred observations fetch failed: timed out")
        # series page HTML
        return (
            '<div class="series-meta-observation-value">4.475</div>'
            '<div class="series-meta-observation-date">2026-05-25</div>'
        )

    monkeypatch.setattr(source_adapters, "_read_text_endpoint", _fake_text)
    rows = source_adapters.load_fred_observations("GASREGW", limit=3)
    assert len(rows) == 1
    assert rows[0].observation_date == "2026-05-25"
    assert rows[0].value == 4.475
    assert rows[0].raw.get("source") == "series_page_html"


def test_fred_clean_error_when_all_paths_fail(monkeypatch):
    """All paths failing yields a clean error that points at FRED_API_KEY."""
    from forecasting import source_adapters
    from forecasting.models import ValidationError

    monkeypatch.delenv("FRED_API_KEY", raising=False)

    def _boom(url, label, *, timeout=None):
        raise ValidationError("network unavailable")

    monkeypatch.setattr(source_adapters, "_read_text_endpoint", _boom)
    with pytest.raises(ValidationError) as exc:
        source_adapters.load_fred_observations("GASREGW", limit=3)
    assert "FRED_API_KEY" in str(exc.value)


def test_fred_timeout_is_bounded_and_configurable(monkeypatch):
    from forecasting import source_adapters

    for name in ("SUPERFORECASTING_AGENT_FRED_TIMEOUT", "FORECAST_FRED_TIMEOUT", "HERMES_FRED_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    assert source_adapters._fred_fetch_timeout() == 12.0
    monkeypatch.setenv("FORECAST_FRED_TIMEOUT", "8")
    assert source_adapters._fred_fetch_timeout() == 8.0
