from __future__ import annotations

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
