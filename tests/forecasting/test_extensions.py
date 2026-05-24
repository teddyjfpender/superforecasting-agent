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
    assert "github-issues" in names
    assert "pypi-releases" in names
    assert "hackernews-search" in names
    assert "reddit-search" in names
    assert "federal-register-documents" in names
    assert "courtlistener-search" in names
    assert "nvd-cves" in names
    assert "cisa-kev" in names
    assert "openmeteo-daily-forecast" in names
    assert "usgs-earthquakes" in names
    assert "nasa-eonet-events" in names
    assert "nws-alerts" in names
    assert "clinicaltrials-studies" in names
    assert "openfda-drug-applications" in names
    assert "pubmed-articles" in names
    assert "owid-grapher" in names
    assert "eia-energy-data" in names
    assert "treasury-fiscal-data" in names
    assert "bls-economic-data" in names
    assert "worldbank-indicators" in names
    assert "census-data" in names
    assert "stooq-market-data" in names
    assert "sec-edgar-filings" in names
    assert "arxiv-papers" in names
    assert "openalex-works" in names
    assert "wikipedia-pages" in names
    assert "wikimedia-pageviews" in names
    assert "bayesian-update" in names
    assert "weighted-ensemble" in names
    assert "prediction-market" in names
