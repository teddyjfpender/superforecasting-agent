"""Forecast-specific extension registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal


ExtensionKind = Literal["importer", "market", "model", "resolver", "alert", "visualizer"]


@dataclass(frozen=True)
class ForecastExtension:
    name: str
    kind: ExtensionKind
    description: str
    version: str | None = None
    handler: Callable | None = field(default=None, compare=False)


class ForecastExtensionRegistry:
    """In-process registry for forecast-native plugin categories."""

    def __init__(self) -> None:
        self._extensions: dict[tuple[ExtensionKind, str], ForecastExtension] = {}

    def register(self, extension: ForecastExtension) -> None:
        key = (extension.kind, extension.name)
        self._extensions[key] = extension

    def get(self, kind: ExtensionKind, name: str) -> ForecastExtension | None:
        return self._extensions.get((kind, name))

    def list(self, kind: ExtensionKind | None = None) -> list[ForecastExtension]:
        values = list(self._extensions.values())
        if kind is not None:
            values = [extension for extension in values if extension.kind == kind]
        return sorted(values, key=lambda extension: (extension.kind, extension.name))

    def clear(self) -> None:
        self._extensions.clear()


extension_registry = ForecastExtensionRegistry()


def register_extension(
    *,
    name: str,
    kind: ExtensionKind,
    description: str,
    version: str | None = None,
    handler: Callable | None = None,
) -> ForecastExtension:
    extension = ForecastExtension(
        name=name,
        kind=kind,
        description=description,
        version=version,
        handler=handler,
    )
    extension_registry.register(extension)
    return extension


def register_builtin_extensions() -> None:
    """Register built-in forecast extension points and lightweight adapters."""

    for name, kind, description in [
        ("generic-url", "importer", "Stage generic URL context as an ingest candidate."),
        ("generic-file", "importer", "Stage local file context as an ingest candidate."),
        ("benchmark-json", "importer", "Replay resolved JSON benchmark cases."),
        ("tournament-export", "importer", "Import tournament exports as replayable benchmark datasets."),
        ("metaculus-question", "importer", "Import Metaculus questions as ledger context and crowd baselines."),
        ("metaculus-resolved-benchmark", "importer", "Create benchmark datasets from resolved Metaculus questions."),
        ("manifold-resolved-benchmark", "importer", "Create benchmark datasets from resolved Manifold markets."),
        ("kalshi-resolved-benchmark", "importer", "Create benchmark datasets from settled Kalshi markets."),
        ("rss-atom-news", "importer", "Capture RSS or Atom feed items as timestamped evidence."),
        ("generic-data", "importer", "Capture CSV or JSON data rows as timestamped evidence."),
        ("gdelt-doc-news", "importer", "Capture GDELT DOC article-list results as timestamped evidence."),
        ("fivethirtyeight-polls", "importer", "Capture FiveThirtyEight polling rows as timestamped evidence."),
        ("github-releases", "importer", "Capture GitHub repository releases as timestamped evidence."),
        ("github-issues", "importer", "Capture GitHub issues and pull requests as timestamped evidence."),
        ("github-commits", "importer", "Capture GitHub commit activity as timestamped evidence."),
        ("github-actions", "importer", "Capture GitHub Actions workflow runs as timestamped evidence."),
        ("coingecko-market-data", "importer", "Capture CoinGecko crypto market snapshots as evidence."),
        ("pypi-releases", "importer", "Capture PyPI package releases as timestamped evidence."),
        ("npm-package-versions", "importer", "Capture npm package versions as timestamped evidence."),
        ("hackernews-search", "importer", "Capture Hacker News search results as public-attention evidence."),
        ("reddit-search", "importer", "Capture Reddit search results as public-attention evidence."),
        ("federal-register-documents", "importer", "Capture Federal Register documents as timestamped evidence."),
        ("courtlistener-search", "importer", "Capture CourtListener legal search results as timestamped evidence."),
        ("nvd-cves", "importer", "Capture NVD CVE records as timestamped security evidence."),
        ("cisa-kev", "importer", "Capture CISA Known Exploited Vulnerabilities as evidence."),
        ("openmeteo-daily-forecast", "importer", "Capture Open-Meteo daily forecasts as weather evidence."),
        ("openmeteo-air-quality", "importer", "Capture Open-Meteo air-quality forecasts as environmental evidence."),
        ("usgs-earthquakes", "importer", "Capture USGS earthquake events as timestamped geophysical evidence."),
        ("nasa-eonet-events", "importer", "Capture NASA EONET natural events as timestamped hazard evidence."),
        ("nws-alerts", "importer", "Capture National Weather Service alerts as weather evidence."),
        ("clinicaltrials-studies", "importer", "Capture ClinicalTrials.gov studies as health evidence."),
        ("openfda-drug-applications", "importer", "Capture openFDA drug applications as regulatory evidence."),
        ("pubmed-articles", "importer", "Capture PubMed biomedical literature as timestamped evidence."),
        ("owid-grapher", "importer", "Capture Our World in Data grapher rows as evidence."),
        ("fred-economic-data", "importer", "Capture FRED CSV observations as timestamped evidence."),
        ("eia-energy-data", "importer", "Capture EIA energy time-series observations as evidence."),
        ("treasury-fiscal-data", "importer", "Capture U.S. Treasury Fiscal Data API records as evidence."),
        ("bls-economic-data", "importer", "Capture BLS public time-series observations as timestamped evidence."),
        ("worldbank-indicators", "importer", "Capture World Bank country indicator observations as evidence."),
        ("census-data", "importer", "Capture U.S. Census API rows as demographic/regional evidence."),
        ("socrata-open-data", "importer", "Capture Socrata open-data portal rows as evidence."),
        ("stooq-market-data", "importer", "Capture Stooq market price CSV rows as timestamped evidence."),
        ("yahoo-finance-chart", "importer", "Capture Yahoo Finance chart observations as market evidence."),
        ("sec-edgar-filings", "importer", "Capture SEC EDGAR company filings as timestamped evidence."),
        ("sec-company-facts", "importer", "Capture SEC XBRL company fact observations as evidence."),
        ("arxiv-papers", "importer", "Capture arXiv research papers as timestamped evidence."),
        ("openalex-works", "importer", "Capture OpenAlex scholarly works as timestamped evidence."),
        ("wikipedia-pages", "importer", "Capture Wikipedia/MediaWiki pages as timestamped evidence."),
        ("wikimedia-pageviews", "importer", "Capture Wikimedia pageviews as public-attention evidence."),
        ("prediction-market", "market", "Stage market-implied probabilities as baseline comparisons."),
        ("manifold", "market", "Read Manifold market probabilities as baseline comparisons."),
        ("polymarket", "market", "Read Polymarket Gamma probabilities as baseline comparisons."),
        ("kalshi", "market", "Read Kalshi market probabilities as baseline comparisons."),
        ("manual-resolution", "resolver", "Manual user-confirmed resolution source."),
        ("base-rate", "model", "Reference-class base-rate model family."),
        ("bayesian-update", "model", "Binary Bayesian prior/likelihood update helper."),
        ("weighted-ensemble", "model", "Weighted component ensemble model family."),
    ]:
        register_extension(name=name, kind=kind, description=description, version="1")


register_builtin_extensions()
