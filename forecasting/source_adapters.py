"""Source adapters for generic forecasting evidence feeds."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from forecasting.models import OutcomeSpace, ValidationError, parse_timestamp, timestamp_to_datetime


@dataclass(frozen=True)
class NewsFeedItem:
    title: str
    summary: str
    url: str | None
    published_at: str | None
    source_name: str | None
    entry_id: str | None


@dataclass(frozen=True)
class GdeltArticle:
    title: str
    summary: str
    url: str | None
    published_at: str | None
    source_name: str | None
    entry_id: str | None
    domain: str | None
    source_country: str | None
    language: str | None
    image_url: str | None
    raw: dict


@dataclass(frozen=True)
class FiveThirtyEightPollObservation:
    dataset: str
    poll_id: str | None
    question_id: str | None
    pollster: str | None
    pollster_grade: str | None
    race_id: str | None
    office_type: str | None
    state: str | None
    cycle: int | None
    stage: str | None
    candidate_name: str | None
    answer: str | None
    party: str | None
    pct: float | None
    sample_size: float | int | None
    population: str | None
    start_date: str | None
    end_date: str | None
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class FredObservation:
    series_id: str
    observation_date: str
    value: float | str
    published_at: str
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class EiaObservation:
    series_id: str
    series_name: str | None
    observation_period: str
    value: float | str
    unit: str | None
    published_at: str
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class TreasuryRecord:
    dataset: str
    record_date: str
    value: float | str | None
    value_field: str | None
    value_label: str | None
    published_at: str
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class BlsObservation:
    series_id: str
    observation_date: str
    period: str
    period_name: str | None
    value: float | str
    published_at: str
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class WorldBankObservation:
    country: str
    country_name: str | None
    indicator: str
    indicator_name: str | None
    observation_date: str
    value: float | str
    published_at: str
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class CensusRecord:
    dataset: str
    dataset_year: int | None
    observation_date: str | None
    values: dict[str, float | str]
    geography: dict[str, str]
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class SocrataRecord:
    domain: str
    dataset_id: str
    row_id: str | None
    observation_time: str | None
    updated_at: str | None
    values: dict[str, object]
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class StooqPriceObservation:
    symbol: str
    interval: str
    observation_date: str
    open_price: float | str | None
    high_price: float | str | None
    low_price: float | str | None
    close_price: float | str
    volume: float | int | str | None
    published_at: str
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class YahooFinancePriceObservation:
    symbol: str
    interval: str
    observation_time: str
    open_price: float | str | None
    high_price: float | str | None
    low_price: float | str | None
    close_price: float | str
    volume: float | int | str | None
    published_at: str
    currency: str | None
    exchange_name: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class SecFiling:
    cik: str
    company_name: str | None
    ticker: str | None
    form: str
    filing_date: str
    report_date: str | None
    acceptance_time: str | None
    published_at: str
    accession_number: str
    primary_document: str | None
    description: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class SecCompanyFact:
    cik: str
    company_name: str | None
    taxonomy: str
    concept: str
    label: str | None
    description: str | None
    unit: str
    observation_date: str
    value: float | int | str
    filed_at: str | None
    published_at: str
    form: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    accession_number: str | None
    frame: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class ArxivPaper:
    arxiv_id: str | None
    title: str
    abstract: str
    url: str | None
    pdf_url: str | None
    published_at: str | None
    updated_at: str | None
    authors: list[str]
    categories: list[str]
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class OpenAlexWork:
    work_id: str | None
    title: str
    abstract: str
    url: str | None
    doi: str | None
    published_at: str | None
    updated_at: str | None
    authors: list[str]
    concepts: list[str]
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class CrossrefWork:
    doi: str | None
    title: str
    abstract: str
    url: str | None
    published_at: str | None
    updated_at: str | None
    authors: list[str]
    subjects: list[str]
    container_title: str | None
    publisher: str | None
    work_type: str | None
    reference_count: int | None
    cited_by_count: int | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class PubMedArticle:
    pmid: str
    title: str
    abstract: str
    journal: str | None
    url: str | None
    doi: str | None
    published_at: str | None
    revised_at: str | None
    authors: list[str]
    publication_types: list[str]
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class WikipediaPage:
    page_id: str | None
    title: str
    extract: str
    url: str | None
    updated_at: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class WikimediaPageviewObservation:
    project: str
    article: str
    access: str
    agent: str
    granularity: str
    observation_date: str
    views: int
    published_at: str
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class GitHubRelease:
    repo: str
    release_id: str | None
    tag_name: str
    name: str
    body: str
    url: str | None
    html_url: str | None
    created_at: str | None
    published_at: str | None
    draft: bool
    prerelease: bool
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class GitHubIssue:
    repo: str
    issue_number: int | None
    title: str
    state: str | None
    is_pull_request: bool
    author: str | None
    labels: list[str]
    created_at: str | None
    updated_at: str | None
    closed_at: str | None
    comments: int | None
    url: str | None
    html_url: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class GitHubCommit:
    repo: str
    sha: str
    short_sha: str
    message: str
    author_name: str | None
    author_login: str | None
    authored_at: str | None
    committed_at: str | None
    comments: int | None
    url: str | None
    html_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class GitHubWorkflowRun:
    repo: str
    run_id: str
    name: str
    display_title: str
    status: str | None
    conclusion: str | None
    event: str | None
    head_branch: str | None
    head_sha: str | None
    short_sha: str | None
    workflow_id: str | None
    workflow_url: str | None
    actor_login: str | None
    triggering_actor_login: str | None
    run_started_at: str | None
    created_at: str | None
    updated_at: str | None
    url: str | None
    html_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class CoinGeckoMarketSnapshot:
    coin_id: str
    symbol: str | None
    name: str | None
    vs_currency: str
    current_price: float | str | None
    market_cap: float | int | str | None
    market_cap_rank: int | None
    total_volume: float | int | str | None
    price_change_percentage_24h: float | str | None
    last_updated: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class PypiRelease:
    package: str
    version: str
    summary: str
    url: str | None
    project_url: str | None
    uploaded_at: str | None
    latest_upload_at: str | None
    file_count: int
    package_types: list[str]
    python_versions: list[str]
    yanked: bool
    yanked_reason: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class NpmPackageVersion:
    package: str
    version: str
    description: str
    url: str | None
    tarball_url: str | None
    published_at: str | None
    license: str | None
    maintainers: list[str]
    keywords: list[str]
    deprecated: str | None
    dependency_count: int
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class HackerNewsItem:
    object_id: str
    title: str
    url: str | None
    hn_url: str | None
    author: str | None
    created_at: str | None
    points: int | None
    comments: int | None
    story_id: int | None
    story_text: str
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class RedditPost:
    post_id: str
    title: str
    subreddit: str | None
    author: str | None
    url: str | None
    permalink: str | None
    created_at: str | None
    score: int | None
    comments: int | None
    upvote_ratio: float | None
    selftext: str
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class BlueskyPost:
    post_uri: str
    cid: str | None
    text: str
    author_handle: str | None
    author_display_name: str | None
    author_did: str | None
    created_at: str | None
    indexed_at: str | None
    reply_count: int | None
    repost_count: int | None
    like_count: int | None
    quote_count: int | None
    url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class ReliefWebReport:
    report_id: str | None
    title: str
    summary: str
    url: str | None
    published_at: str | None
    changed_at: str | None
    sources: list[str]
    countries: list[str]
    disasters: list[str]
    formats: list[str]
    themes: list[str]
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class FederalRegisterDocument:
    document_number: str | None
    title: str
    abstract: str
    url: str | None
    pdf_url: str | None
    published_at: str | None
    document_type: str | None
    agencies: list[str]
    citation: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class CourtListenerSearchResult:
    result_id: str | None
    title: str
    snippet: str
    url: str | None
    court: str | None
    court_id: str | None
    docket_number: str | None
    date_filed: str | None
    date_argued: str | None
    status: str | None
    citation: str | None
    judge: str | None
    cite_count: int | None
    search_type: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class NvdCve:
    cve_id: str
    description: str
    url: str | None
    published_at: str | None
    last_modified_at: str | None
    vuln_status: str | None
    severity: str | None
    base_score: float | None
    cvss_version: str | None
    references: list[str]
    source_identifier: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class CisaKevVulnerability:
    cve_id: str
    vendor_project: str | None
    product: str | None
    vulnerability_name: str
    short_description: str
    date_added: str | None
    due_date: str | None
    required_action: str
    ransomware_use: str | None
    notes: str | None
    cwes: list[str]
    source_url: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class UsgsEarthquakeEvent:
    event_id: str | None
    title: str
    url: str | None
    time: str | None
    updated_at: str | None
    magnitude: float | None
    place: str | None
    event_type: str | None
    status: str | None
    tsunami: int | None
    significance: int | None
    longitude: float | None
    latitude: float | None
    depth_km: float | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class NasaEonetEvent:
    event_id: str | None
    title: str
    description: str
    url: str | None
    status: str | None
    closed_at: str | None
    latest_geometry_at: str | None
    categories: list[str]
    source_names: list[str]
    source_urls: list[str]
    longitude: float | None
    latitude: float | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class NwsAlert:
    alert_id: str | None
    event: str
    headline: str
    description: str
    instruction: str
    url: str | None
    area_desc: str | None
    severity: str | None
    certainty: str | None
    urgency: str | None
    status: str | None
    message_type: str | None
    category: str | None
    response: str | None
    sent_at: str | None
    effective_at: str | None
    onset_at: str | None
    expires_at: str | None
    ends_at: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class ClinicalTrialStudy:
    nct_id: str
    brief_title: str
    official_title: str | None
    url: str | None
    status: str | None
    phases: list[str]
    study_type: str | None
    conditions: list[str]
    interventions: list[str]
    sponsors: list[str]
    start_date: str | None
    primary_completion_date: str | None
    completion_date: str | None
    last_update_submitted_at: str | None
    last_update_posted_at: str | None
    has_results: bool
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class OpenFdaDrugApplication:
    application_number: str
    sponsor_name: str | None
    brand_names: list[str]
    generic_names: list[str]
    routes: list[str]
    substances: list[str]
    dosage_forms: list[str]
    marketing_statuses: list[str]
    latest_submission_status: str | None
    latest_submission_status_date: str | None
    latest_submission_type: str | None
    latest_submission_class: str | None
    url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class OpenMeteoDailyForecast:
    latitude: float
    longitude: float
    forecast_date: str
    temperature_2m_max: float | None
    temperature_2m_min: float | None
    precipitation_sum: float | None
    wind_speed_10m_max: float | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class OpenMeteoAirQualityForecast:
    latitude: float
    longitude: float
    forecast_time: str
    us_aqi: float | None
    european_aqi: float | None
    pm10: float | None
    pm2_5: float | None
    carbon_monoxide: float | None
    nitrogen_dioxide: float | None
    ozone: float | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class OpenMeteoHistoricalWeatherObservation:
    latitude: float
    longitude: float
    observation_date: str
    temperature_2m_mean: float | None
    temperature_2m_max: float | None
    temperature_2m_min: float | None
    precipitation_sum: float | None
    wind_speed_10m_max: float | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class OwidObservation:
    slug: str
    entity: str | None
    code: str | None
    observation_date: str
    value: float | str | None
    value_column: str
    published_at: str
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class ManifoldMarketImport:
    market_id: str | None
    slug: str | None
    question: str
    description: str
    url: str | None
    outcome_space: OutcomeSpace
    probability: float | None
    distribution: dict[str, float] | None
    close_time: str | None
    resolution_time: str | None
    resolution: str | None
    is_resolved: bool
    as_of: str | None
    raw: dict

    @property
    def baseline_source(self) -> str:
        return f"manifold:{self.slug or self.market_id or 'market'}"

    @property
    def resolution_criteria(self) -> str:
        if self.description:
            return self.description
        return "Resolved according to the linked Manifold market and its creator's resolution rules."

    def baseline_payload(self) -> dict[str, object] | None:
        value = self.distribution if self.distribution is not None else self.probability
        if value is None:
            return None
        return {
            "source": self.baseline_source,
            "baseline_type": "market",
            "probability_or_distribution": value,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class MetaculusQuestionImport:
    question_id: str | None
    title: str
    description: str
    resolution_criteria_text: str
    url: str | None
    outcome_space: OutcomeSpace
    probability: float | None
    distribution: dict[str, float] | None
    close_time: str | None
    resolution_time: str | None
    resolution: str | None
    status: str | None
    as_of: str | None
    raw: dict

    @property
    def baseline_source(self) -> str:
        return f"metaculus:{self.question_id or 'question'}"

    @property
    def resolution_criteria(self) -> str:
        if self.resolution_criteria_text:
            return self.resolution_criteria_text
        return "Resolved according to the linked Metaculus question and its resolution criteria."

    def baseline_payload(self) -> dict[str, object] | None:
        value = self.distribution if self.distribution is not None else self.probability
        if value is None:
            return None
        return {
            "source": self.baseline_source,
            "baseline_type": "crowd",
            "probability_or_distribution": value,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class PolymarketMarketImport:
    market_id: str | None
    slug: str | None
    question: str
    description: str
    url: str | None
    outcome_space: OutcomeSpace
    probability: float | None
    distribution: dict[str, float] | None
    close_time: str | None
    resolution_time: str | None
    as_of: str | None
    raw: dict

    @property
    def baseline_source(self) -> str:
        return f"polymarket:{self.slug or self.market_id or 'market'}"

    @property
    def resolution_criteria(self) -> str:
        if self.description:
            return self.description
        return "Resolved according to the linked Polymarket market and its settlement rules."

    def baseline_payload(self) -> dict[str, object] | None:
        value = self.distribution if self.distribution is not None else self.probability
        if value is None:
            return None
        return {
            "source": self.baseline_source,
            "baseline_type": "market",
            "probability_or_distribution": value,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class KalshiMarketImport:
    ticker: str | None
    event_ticker: str | None
    question: str
    description: str
    url: str | None
    outcome_space: OutcomeSpace
    probability: float | None
    close_time: str | None
    resolution_time: str | None
    status: str | None
    result: str | None
    as_of: str | None
    raw: dict

    @property
    def baseline_source(self) -> str:
        return f"kalshi:{self.ticker or 'market'}"

    @property
    def resolution_criteria(self) -> str:
        if self.description:
            return self.description
        return "Resolved according to the linked Kalshi market and its settlement rules."

    def baseline_payload(self) -> dict[str, object] | None:
        if self.probability is None:
            return None
        return {
            "source": self.baseline_source,
            "baseline_type": "market",
            "probability_or_distribution": self.probability,
            "as_of": self.as_of,
        }


def load_news_feed_items(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
) -> list[NewsFeedItem]:
    """Load RSS/Atom items from a URL or local XML file."""

    if limit <= 0:
        raise ValidationError("news import --limit must be positive")
    since_dt = timestamp_to_datetime(parse_timestamp(since, field_name="since")) if since else None
    try:
        root = ElementTree.fromstring(_read_feed_source(source))
    except ElementTree.ParseError as exc:
        raise ValidationError("news feed source is not valid XML") from exc
    items = _parse_rss_items(root) or _parse_atom_items(root)
    filtered: list[NewsFeedItem] = []
    for item in items:
        if since_dt is not None:
            item_dt = timestamp_to_datetime(item.published_at)
            if item_dt is None or item_dt < since_dt:
                continue
        filtered.append(item)
        if len(filtered) >= limit:
            break
    return filtered


def load_gdelt_articles(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    timespan: str | None = None,
    source_country: str | None = None,
    source_lang: str | None = None,
    api_base_url: str = "https://api.gdeltproject.org/api/v2/doc/doc",
) -> list[GdeltArticle]:
    """Load GDELT DOC 2.0 article-list results as timestamped evidence."""

    if not query.strip():
        raise ValidationError("gdelt import query is required")
    if limit <= 0:
        raise ValidationError("gdelt import --limit must be positive")
    since_iso = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_iso) if since_iso else None
    params: dict[str, object] = {
        "query": _gdelt_augmented_query(
            query,
            source_country=source_country,
            source_lang=source_lang,
        ),
        "mode": "ArtList",
        "format": "json",
        "maxrecords": min(limit, 250),
        "sort": "DateDesc",
    }
    if timespan:
        params["timespan"] = timespan
    if since_iso:
        params["startdatetime"] = _gdelt_datetime_parameter(since_iso)
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "gdelt article list")
    if isinstance(payload, dict):
        rows = payload.get("articles")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValidationError("gdelt article list response must contain an articles array")

    articles: list[GdeltArticle] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        published_at = _gdelt_timestamp(
            _first_present(row.get("seendate"), row.get("seenDate"), row.get("date"), row.get("publishedAt"))
        )
        if since_dt is not None:
            article_dt = timestamp_to_datetime(published_at)
            if article_dt is None or article_dt < since_dt:
                continue
        title = _optional_str(row.get("title")) or "Untitled GDELT article"
        url = _optional_str(row.get("url"))
        domain = _optional_str(row.get("domain"))
        source_country_value = _optional_str(_first_present(row.get("sourcecountry"), row.get("sourceCountry")))
        language = _optional_str(row.get("language"))
        source_name = domain or source_country_value or "GDELT"
        articles.append(
            GdeltArticle(
                title=title,
                summary=_optional_str(_first_present(row.get("summary"), row.get("snippet"), row.get("description")))
                or "",
                url=url,
                published_at=published_at,
                source_name=source_name,
                entry_id=_optional_str(_first_present(row.get("id"), url, title)),
                domain=domain,
                source_country=source_country_value,
                language=language,
                image_url=_optional_str(_first_present(row.get("socialimage"), row.get("image"))),
                raw=dict(row),
            )
        )
        if len(articles) >= limit:
            break
    return articles


def load_fivethirtyeight_polls(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    state: str | None = None,
    candidate: str | None = None,
    pollster: str | None = None,
    cycle: int | None = None,
    office_type: str | None = None,
    api_base_url: str = "https://projects.fivethirtyeight.com/polls-page/data",
) -> list[FiveThirtyEightPollObservation]:
    """Load FiveThirtyEight polling CSV rows as timestamped public-opinion evidence."""

    dataset, endpoint = _fivethirtyeight_poll_endpoint(source, api_base_url=api_base_url)
    if not dataset:
        raise ValidationError("fivethirtyeight import dataset or CSV URL is required")
    if limit <= 0:
        raise ValidationError("fivethirtyeight import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    state_filter = state.strip().casefold() if state else None
    candidate_filter = candidate.strip().casefold() if candidate else None
    pollster_filter = pollster.strip().casefold() if pollster else None
    office_filter = office_type.strip().casefold() if office_type else None

    text = _read_text_endpoint(endpoint, "fivethirtyeight polls")
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ValidationError("fivethirtyeight polls CSV has no header row")

    observations: list[FiveThirtyEightPollObservation] = []
    for index, row in enumerate(reader):
        if not isinstance(row, dict):
            continue
        row_state = _collapse_optional(_first_present(row.get("state"), row.get("seat_name")))
        row_candidate = _collapse_optional(_first_present(row.get("candidate_name"), row.get("candidate"), row.get("answer")))
        row_pollster = _collapse_optional(
            _first_present(row.get("pollster"), row.get("display_name"), row.get("pollster_name"))
        )
        row_office = _collapse_optional(_first_present(row.get("office_type"), row.get("office")))
        row_cycle = _optional_int(row.get("cycle"))

        if state_filter and (row_state or "").casefold() != state_filter:
            continue
        if candidate_filter and candidate_filter not in (row_candidate or "").casefold():
            continue
        if pollster_filter and pollster_filter not in (row_pollster or "").casefold():
            continue
        if office_filter and (row_office or "").casefold() != office_filter:
            continue
        if cycle is not None and row_cycle != cycle:
            continue

        start_date = _fivethirtyeight_date(_first_present(row.get("start_date"), row.get("startDate")))
        end_date = _fivethirtyeight_date(_first_present(row.get("end_date"), row.get("endDate")))
        published_at = _fivethirtyeight_timestamp(
            _first_present(
                row.get("created_at"),
                row.get("createdAt"),
                row.get("published_at"),
                row.get("updated_at"),
                row.get("last_updated"),
                end_date,
            )
        )
        if since_dt is not None:
            published_dt = timestamp_to_datetime(published_at)
            if published_dt is None or published_dt < since_dt:
                continue

        pct = _optional_float(_first_present(row.get("pct"), row.get("percent"), row.get("value")))
        sample_size = _fivethirtyeight_sample_size(
            _first_present(row.get("sample_size"), row.get("samplesize"), row.get("sampleSize"))
        )
        poll_id = _optional_str(row.get("poll_id"))
        question_id = _optional_str(row.get("question_id"))
        answer = _collapse_optional(row.get("answer"))
        entry_id = ":".join(
            part
            for part in (
                dataset,
                poll_id,
                question_id,
                row_candidate or answer,
                str(index),
            )
            if part
        )
        observations.append(
            FiveThirtyEightPollObservation(
                dataset=dataset,
                poll_id=poll_id,
                question_id=question_id,
                pollster=row_pollster,
                pollster_grade=_collapse_optional(
                    _first_present(row.get("fte_grade"), row.get("pollster_rating_name"), row.get("grade"))
                ),
                race_id=_optional_str(row.get("race_id")),
                office_type=row_office,
                state=row_state,
                cycle=row_cycle,
                stage=_collapse_optional(row.get("stage")),
                candidate_name=row_candidate,
                answer=answer,
                party=_collapse_optional(row.get("party")),
                pct=pct,
                sample_size=sample_size,
                population=_collapse_optional(row.get("population")),
                start_date=start_date,
                end_date=end_date,
                published_at=published_at,
                source_url=_optional_str(row.get("url")) or endpoint,
                source_name=row_pollster or "FiveThirtyEight Polls",
                entry_id=entry_id,
                raw={"row_index": index, "endpoint": endpoint, **dict(row)},
            )
        )
    observations.sort(
        key=lambda item: (
            timestamp_to_datetime(item.published_at)
            or datetime.min.replace(tzinfo=timezone.utc),
            item.poll_id or "",
            item.question_id or "",
            item.candidate_name or item.answer or "",
        )
    )
    return observations[-limit:]


def load_fred_observations(
    series_id: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://fred.stlouisfed.org/graph/fredgraph.csv",
) -> list[FredObservation]:
    """Load recent FRED CSV observations as timestamped evidence rows."""

    normalized_series = series_id.strip()
    if not normalized_series:
        raise ValidationError("fred import series id is required")
    if limit <= 0:
        raise ValidationError("fred import --limit must be positive")
    since_date = _fred_date(since, field_name="since") if since else None
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode({'id': normalized_series})}"
    text = _read_text_endpoint(endpoint, "fred observations")
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ValidationError("fred observations CSV has no header row")
    date_key = _fred_date_column(reader.fieldnames)
    value_key = _fred_value_column(reader.fieldnames, normalized_series, date_key)
    observations: list[FredObservation] = []
    for index, row in enumerate(reader):
        raw_date = str(row.get(date_key) or "").strip()
        observation_date = _fred_date(raw_date, field_name="fred observation date")
        if observation_date is None:
            continue
        if since_date is not None and observation_date < since_date:
            continue
        raw_value = str(row.get(value_key) or "").strip()
        if raw_value in {"", "."}:
            continue
        value = _optional_float(raw_value)
        observation_iso = _fred_date_to_iso(observation_date)
        observations.append(
            FredObservation(
                series_id=normalized_series,
                observation_date=observation_date.isoformat(),
                value=value if value is not None else raw_value,
                published_at=observation_iso,
                source_url=f"https://fred.stlouisfed.org/series/{quote(normalized_series)}",
                source_name="FRED",
                entry_id=f"{normalized_series}:{observation_date.isoformat()}",
                raw={"row_index": index, **dict(row)},
            )
        )
    return observations[-limit:]


def load_eia_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.eia.gov/series/",
) -> list[EiaObservation]:
    """Load EIA energy time-series observations as timestamped evidence rows."""

    series_id, endpoint = _eia_endpoint(source, api_base_url=api_base_url)
    if not series_id:
        raise ValidationError("eia import series id or API URL is required")
    if limit <= 0:
        raise ValidationError("eia import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    payload = _read_json_endpoint(endpoint, "eia observations")
    observations = _eia_observations_from_payload(payload, series_id=series_id, endpoint=endpoint)
    if since_dt is not None:
        observations = [
            observation
            for observation in observations
            if (timestamp_to_datetime(observation.published_at) or since_dt) >= since_dt
        ]
    observations.sort(key=lambda item: item.published_at)
    return observations[-limit:]


def load_treasury_records(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    date_field: str = "record_date",
    value_field: str | None = None,
    api_base_url: str = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
) -> list[TreasuryRecord]:
    """Load U.S. Treasury Fiscal Data API rows as timestamped evidence."""

    dataset, endpoint = _treasury_endpoint(
        source,
        api_base_url=api_base_url,
        date_field=date_field,
        limit=max(limit, 100),
    )
    if not dataset:
        raise ValidationError("treasury import dataset path or API URL is required")
    if limit <= 0:
        raise ValidationError("treasury import --limit must be positive")
    if not date_field.strip():
        raise ValidationError("treasury import --date-field cannot be empty")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    payload = _read_json_endpoint(endpoint, "treasury fiscal data")
    records = _treasury_records_from_payload(
        payload,
        dataset=dataset,
        endpoint=endpoint,
        date_field=date_field,
        value_field=value_field,
    )
    if since_dt is not None:
        records = [
            record
            for record in records
            if (timestamp_to_datetime(record.published_at) or since_dt) >= since_dt
        ]
    records.sort(key=lambda item: item.published_at)
    return records[-limit:]


def load_bls_observations(
    series_id: str,
    *,
    limit: int = 10,
    since: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    api_base_url: str = "https://api.bls.gov/publicAPI/v2/timeseries/data",
) -> list[BlsObservation]:
    """Load BLS public time-series observations as timestamped evidence rows."""

    normalized_series = series_id.strip()
    if not normalized_series:
        raise ValidationError("bls import series id is required")
    if limit <= 0:
        raise ValidationError("bls import --limit must be positive")
    if start_year is not None and end_year is not None and start_year > end_year:
        raise ValidationError("bls import --start-year cannot be after --end-year")
    since_date = _fred_date(since, field_name="since") if since else None
    endpoint = _bls_endpoint(normalized_series, api_base_url=api_base_url, start_year=start_year, end_year=end_year)
    payload = _read_json_endpoint(endpoint, "bls observations")
    if not isinstance(payload, dict):
        raise ValidationError("bls observations response must be a JSON object")
    status = str(payload.get("status") or "").upper()
    if status and status != "REQUEST_SUCCEEDED":
        messages = payload.get("message")
        detail = "; ".join(str(item) for item in messages) if isinstance(messages, list) else str(messages or status)
        raise ValidationError(f"bls observations request failed: {detail}")
    results = payload.get("Results")
    series_rows = results.get("series") if isinstance(results, dict) else None
    if not isinstance(series_rows, list):
        raise ValidationError("bls observations response must contain Results.series")

    observations: list[BlsObservation] = []
    for series in series_rows:
        if not isinstance(series, dict):
            continue
        row_series_id = str(series.get("seriesID") or normalized_series).strip() or normalized_series
        data_rows = series.get("data")
        if not isinstance(data_rows, list):
            continue
        for row in data_rows:
            if not isinstance(row, dict):
                continue
            year = str(row.get("year") or "").strip()
            period = str(row.get("period") or "").strip()
            observation_date = _bls_observation_date(year, period)
            if observation_date is None:
                continue
            if since_date is not None and observation_date < since_date:
                continue
            raw_value = str(row.get("value") or "").strip()
            if raw_value in {"", "."}:
                continue
            value = _optional_float(raw_value)
            observation_iso = _fred_date_to_iso(observation_date)
            observations.append(
                BlsObservation(
                    series_id=row_series_id,
                    observation_date=observation_date.isoformat(),
                    period=period,
                    period_name=_optional_str(row.get("periodName")),
                    value=value if value is not None else raw_value,
                    published_at=observation_iso,
                    source_url=f"https://data.bls.gov/timeseries/{quote(row_series_id)}",
                    source_name="BLS",
                    entry_id=f"{row_series_id}:{year}:{period}",
                    raw=dict(row),
                )
            )
    observations.sort(key=lambda item: item.observation_date)
    return observations[-limit:]


def load_worldbank_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.worldbank.org/v2",
) -> list[WorldBankObservation]:
    """Load World Bank country indicator observations as timestamped evidence rows."""

    country, indicator = _worldbank_source_parts(source)
    if limit <= 0:
        raise ValidationError("worldbank import --limit must be positive")
    since_date = _worldbank_since_date(since) if since else None
    endpoint = _worldbank_endpoint(country, indicator, api_base_url=api_base_url, per_page=max(limit, 100))
    payload = _read_json_endpoint(endpoint, "worldbank observations")
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise ValidationError("worldbank observations response must be a metadata/data array")

    observations: list[WorldBankObservation] = []
    for row in payload[1]:
        if not isinstance(row, dict):
            continue
        year = str(row.get("date") or "").strip()
        observation_date = _worldbank_observation_date(year)
        if observation_date is None:
            continue
        if since_date is not None and observation_date < since_date:
            continue
        raw_value = row.get("value")
        if raw_value in (None, ""):
            continue
        value = _optional_float(raw_value)
        country_payload = row.get("country")
        indicator_payload = row.get("indicator")
        row_country = _optional_str(country_payload.get("id")) if isinstance(country_payload, dict) else country
        row_country_name = _optional_str(country_payload.get("value")) if isinstance(country_payload, dict) else None
        row_indicator = _optional_str(indicator_payload.get("id")) if isinstance(indicator_payload, dict) else indicator
        row_indicator_name = _optional_str(indicator_payload.get("value")) if isinstance(indicator_payload, dict) else None
        observation_iso = _fred_date_to_iso(observation_date)
        observations.append(
            WorldBankObservation(
                country=row_country or country,
                country_name=row_country_name,
                indicator=row_indicator or indicator,
                indicator_name=row_indicator_name,
                observation_date=observation_date.isoformat(),
                value=value if value is not None else str(raw_value),
                published_at=observation_iso,
                source_url=f"https://data.worldbank.org/indicator/{quote(row_indicator or indicator)}?locations={quote(row_country or country)}",
                source_name="World Bank",
                entry_id=f"{row_country or country}:{row_indicator or indicator}:{year}",
                raw=dict(row),
            )
        )
    observations.sort(key=lambda item: item.observation_date)
    return observations[-limit:]


def load_census_records(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.census.gov/data",
    api_key: str | None = None,
) -> list[CensusRecord]:
    """Load U.S. Census API rows as timestamped demographic or regional evidence."""

    dataset, endpoint = _census_endpoint(source, api_base_url=api_base_url, api_key=api_key)
    if not dataset:
        raise ValidationError("census import dataset path or API URL is required")
    if limit <= 0:
        raise ValidationError("census import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    payload = _read_json_endpoint(endpoint, "census data")
    records = _census_records_from_payload(payload, dataset=dataset, endpoint=endpoint)
    if since_dt is not None:
        records = [
            record
            for record in records
            if record.published_at is None or (timestamp_to_datetime(record.published_at) or since_dt) >= since_dt
        ]
    return records[:limit]


def load_socrata_records(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://{domain}/resource/{dataset_id}.json",
) -> list[SocrataRecord]:
    """Load Socrata open-data portal rows as timestamped evidence."""

    if limit <= 0:
        raise ValidationError("socrata import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    domain, dataset_id, endpoint = _socrata_endpoint(source, api_base_url=api_base_url, limit=limit)
    payload = _read_json_endpoint(endpoint, "socrata records")
    if not isinstance(payload, list):
        raise ValidationError("socrata response must be an array of JSON objects")

    records: list[SocrataRecord] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            continue
        updated_at = _socrata_timestamp(
            _first_present(
                row.get(":updated_at"),
                row.get("updated_at"),
                row.get("last_updated"),
                row.get("modified_at"),
                row.get("date_updated"),
            )
        )
        observation_time = _socrata_timestamp(
            _first_present(
                row.get("date"),
                row.get("report_date"),
                row.get("period"),
                row.get("timestamp"),
                row.get("created_at"),
                row.get(":created_at"),
            )
        )
        available_at = updated_at or observation_time
        if since_dt is not None and available_at:
            available_dt = timestamp_to_datetime(available_at)
            if available_dt is not None and available_dt < since_dt:
                continue
        values = {
            str(key): value
            for key, value in row.items()
            if not str(key).startswith(":") and value not in (None, "")
        }
        row_id = _optional_str(_first_present(row.get(":id"), row.get("id"), row.get("row_id"), row.get("sid")))
        records.append(
            SocrataRecord(
                domain=domain,
                dataset_id=dataset_id,
                row_id=row_id,
                observation_time=observation_time,
                updated_at=updated_at,
                values=values,
                source_url=_socrata_public_source_url(endpoint),
                source_name="Socrata",
                entry_id=f"{domain}/{dataset_id}:{row_id or index}",
                raw={"row_index": index, **dict(row)},
            )
        )
        if len(records) >= limit:
            break
    return records


def load_stooq_prices(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    interval: str = "d",
    api_base_url: str = "https://stooq.com/q/d/l/",
) -> list[StooqPriceObservation]:
    """Load Stooq historical price CSV rows as timestamped evidence."""

    normalized_source = source.strip()
    if not normalized_source:
        raise ValidationError("stooq import symbol or CSV URL is required")
    if limit <= 0:
        raise ValidationError("stooq import --limit must be positive")
    normalized_interval = _stooq_interval(interval)
    since_date = _fred_date(since, field_name="since") if since else None
    symbol, effective_interval, endpoint = _stooq_endpoint(
        normalized_source,
        interval=normalized_interval,
        api_base_url=api_base_url,
    )
    text = _read_text_endpoint(endpoint, "stooq prices")
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ValidationError("stooq prices CSV has no header row")
    date_key = _stooq_column(reader.fieldnames, "date")
    close_key = _stooq_column(reader.fieldnames, "close")
    open_key = _stooq_column(reader.fieldnames, "open", required=False)
    high_key = _stooq_column(reader.fieldnames, "high", required=False)
    low_key = _stooq_column(reader.fieldnames, "low", required=False)
    volume_key = _stooq_column(reader.fieldnames, "volume", required=False)

    observations: list[StooqPriceObservation] = []
    for index, row in enumerate(reader):
        raw_date = str(row.get(date_key) or "").strip()
        observation_date = _fred_date(raw_date, field_name="stooq observation date")
        if observation_date is None:
            continue
        if since_date is not None and observation_date < since_date:
            continue
        close_price = _stooq_optional_number(row.get(close_key))
        if close_price is None:
            continue
        observation_iso = _fred_date_to_iso(observation_date)
        observations.append(
            StooqPriceObservation(
                symbol=symbol,
                interval=effective_interval,
                observation_date=observation_date.isoformat(),
                open_price=_stooq_optional_number(row.get(open_key)) if open_key else None,
                high_price=_stooq_optional_number(row.get(high_key)) if high_key else None,
                low_price=_stooq_optional_number(row.get(low_key)) if low_key else None,
                close_price=close_price,
                volume=_stooq_optional_number(row.get(volume_key)) if volume_key else None,
                published_at=observation_iso,
                source_url=endpoint,
                source_name="Stooq",
                entry_id=f"{symbol}:{effective_interval}:{observation_date.isoformat()}",
                raw={"row_index": index, **dict(row)},
            )
        )
    observations.sort(key=lambda item: item.observation_date)
    return observations[-limit:]


def load_yahoo_finance_prices(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    range_value: str = "1mo",
    interval: str = "1d",
    api_base_url: str = "https://query1.finance.yahoo.com/v8/finance/chart",
) -> list[YahooFinancePriceObservation]:
    """Load Yahoo Finance chart observations as timestamped market evidence."""

    symbol = _yahoo_symbol(source)
    if limit <= 0:
        raise ValidationError("yahoo import --limit must be positive")
    normalized_interval = _yahoo_interval(interval)
    normalized_range = _yahoo_range(range_value)
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _yahoo_chart_endpoint(
        symbol,
        range_value=normalized_range,
        interval=normalized_interval,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "yahoo finance chart")
    result = _yahoo_chart_result(payload)
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    timestamps = result.get("timestamp") if isinstance(result.get("timestamp"), list) else []
    indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
    quote_rows = indicators.get("quote") if isinstance(indicators.get("quote"), list) else []
    quote_row = quote_rows[0] if quote_rows and isinstance(quote_rows[0], dict) else {}
    closes = _yahoo_series(quote_row.get("close"))
    opens = _yahoo_series(quote_row.get("open"))
    highs = _yahoo_series(quote_row.get("high"))
    lows = _yahoo_series(quote_row.get("low"))
    volumes = _yahoo_series(quote_row.get("volume"))
    if not timestamps or not closes:
        raise ValidationError("yahoo finance chart response contains no price observations")

    effective_symbol = _optional_str(meta.get("symbol")) or symbol
    currency = _optional_str(meta.get("currency"))
    exchange_name = _optional_str(_first_present(meta.get("exchangeName"), meta.get("fullExchangeName")))
    observations: list[YahooFinancePriceObservation] = []
    for index, raw_timestamp in enumerate(timestamps):
        observation_time = _yahoo_timestamp(raw_timestamp)
        if observation_time is None:
            continue
        observation_dt = timestamp_to_datetime(observation_time)
        if since_dt is not None and observation_dt is not None and observation_dt < since_dt:
            continue
        close_price = _yahoo_optional_number(_list_get(closes, index))
        if close_price is None:
            continue
        observations.append(
            YahooFinancePriceObservation(
                symbol=effective_symbol,
                interval=normalized_interval,
                observation_time=observation_time,
                open_price=_yahoo_optional_number(_list_get(opens, index)),
                high_price=_yahoo_optional_number(_list_get(highs, index)),
                low_price=_yahoo_optional_number(_list_get(lows, index)),
                close_price=close_price,
                volume=_yahoo_optional_number(_list_get(volumes, index)),
                published_at=observation_time,
                currency=currency,
                exchange_name=exchange_name,
                source_url=f"https://finance.yahoo.com/quote/{quote(effective_symbol, safe='=^.-')}",
                source_name="Yahoo Finance",
                entry_id=f"{effective_symbol}:{normalized_interval}:{observation_time}",
                raw={
                    "endpoint": endpoint,
                    "timestamp": raw_timestamp,
                    "symbol": effective_symbol,
                    "range": normalized_range,
                    "interval": normalized_interval,
                    "meta": dict(meta),
                },
            )
        )
    observations.sort(key=lambda item: item.observation_time)
    return observations[-limit:]


def load_sec_filings(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://data.sec.gov/submissions",
) -> list[SecFiling]:
    """Load recent SEC EDGAR company-submission filings as evidence rows."""

    cik = _sec_cik(source)
    if limit <= 0:
        raise ValidationError("sec import --limit must be positive")
    since_dt = timestamp_to_datetime(parse_timestamp(since, field_name="since")) if since else None
    endpoint = _sec_submissions_endpoint(cik, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "sec submissions")
    if not isinstance(payload, dict):
        raise ValidationError("sec submissions response must be a JSON object")
    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    if not isinstance(recent, dict):
        raise ValidationError("sec submissions response must contain filings.recent")
    accession_numbers = recent.get("accessionNumber")
    if not isinstance(accession_numbers, list):
        raise ValidationError("sec submissions response must contain recent accession numbers")

    company_name = _optional_str(payload.get("name"))
    tickers = payload.get("tickers")
    ticker = _optional_str(tickers[0]) if isinstance(tickers, list) and tickers else None
    forms = recent.get("form") if isinstance(recent.get("form"), list) else []
    filing_dates = recent.get("filingDate") if isinstance(recent.get("filingDate"), list) else []
    report_dates = recent.get("reportDate") if isinstance(recent.get("reportDate"), list) else []
    acceptance_times = recent.get("acceptanceDateTime") if isinstance(recent.get("acceptanceDateTime"), list) else []
    primary_documents = recent.get("primaryDocument") if isinstance(recent.get("primaryDocument"), list) else []
    descriptions = (
        recent.get("primaryDocDescription") if isinstance(recent.get("primaryDocDescription"), list) else []
    )

    rows: list[SecFiling] = []
    for index, accession in enumerate(accession_numbers):
        accession_number = _optional_str(accession)
        if not accession_number:
            continue
        filing_date = _optional_str(_list_get(filing_dates, index))
        if not filing_date:
            continue
        published_at = _sec_filing_timestamp(
            _optional_str(_list_get(acceptance_times, index)),
            filing_date,
        )
        published_dt = timestamp_to_datetime(published_at)
        if since_dt is not None and (published_dt is None or published_dt < since_dt):
            continue
        primary_document = _optional_str(_list_get(primary_documents, index))
        source_url = _sec_filing_url(cik, accession_number, primary_document)
        rows.append(
            SecFiling(
                cik=cik,
                company_name=company_name,
                ticker=ticker,
                form=_optional_str(_list_get(forms, index)) or "UNKNOWN",
                filing_date=filing_date,
                report_date=_optional_str(_list_get(report_dates, index)),
                acceptance_time=_optional_str(_list_get(acceptance_times, index)),
                published_at=published_at,
                accession_number=accession_number,
                primary_document=primary_document,
                description=_optional_str(_list_get(descriptions, index)),
                source_url=source_url,
                source_name="SEC EDGAR",
                entry_id=f"{cik}:{accession_number}",
                raw={"index": index, **_sec_recent_row(recent, index)},
            )
        )
    rows.sort(key=lambda item: item.published_at)
    return rows[-limit:]


def load_sec_company_facts(
    source: str,
    *,
    concept: str | None = None,
    taxonomy: str = "us-gaap",
    unit: str | None = None,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://data.sec.gov/api/xbrl/companyfacts",
) -> list[SecCompanyFact]:
    """Load SEC XBRL company-facts observations as timestamped evidence rows."""

    cik, effective_taxonomy, effective_concept = _sec_company_fact_query(
        source,
        concept=concept,
        taxonomy=taxonomy,
    )
    if limit <= 0:
        raise ValidationError("secfacts import --limit must be positive")
    since_dt = timestamp_to_datetime(parse_timestamp(since, field_name="since")) if since else None
    endpoint = _sec_submissions_endpoint(cik, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "sec company facts")
    if not isinstance(payload, dict):
        raise ValidationError("sec company facts response must be a JSON object")
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise ValidationError("sec company facts response must contain facts")
    taxonomy_payload = facts.get(effective_taxonomy)
    if not isinstance(taxonomy_payload, dict):
        raise ValidationError(f"sec company facts response has no {effective_taxonomy} taxonomy")
    concept_payload = taxonomy_payload.get(effective_concept)
    if not isinstance(concept_payload, dict):
        raise ValidationError(
            f"sec company facts response has no {effective_taxonomy}:{effective_concept} concept"
        )

    units = concept_payload.get("units")
    if not isinstance(units, dict) or not units:
        raise ValidationError(f"sec company facts concept {effective_concept} has no units")
    effective_unit, unit_rows = _sec_company_fact_unit_rows(units, unit=unit)
    company_name = _optional_str(payload.get("entityName"))
    label = _optional_str(concept_payload.get("label"))
    description = _optional_str(concept_payload.get("description"))

    rows: list[SecCompanyFact] = []
    for index, raw_row in enumerate(unit_rows):
        if not isinstance(raw_row, dict):
            continue
        observation_date = _optional_str(raw_row.get("end"))
        if not observation_date or raw_row.get("val") is None:
            continue
        try:
            _fred_date(observation_date, field_name="sec company fact end")
        except ValidationError:
            continue
        filed_at = _sec_company_fact_filed_at(_optional_str(raw_row.get("filed")))
        published_at = filed_at or _fred_date_to_iso(
            _fred_date(observation_date, field_name="sec company fact end")
        )
        published_dt = timestamp_to_datetime(published_at)
        if since_dt is not None and (published_dt is None or published_dt < since_dt):
            continue
        accession_number = _optional_str(raw_row.get("accn"))
        value = _sec_company_fact_value(raw_row.get("val"))
        rows.append(
            SecCompanyFact(
                cik=cik,
                company_name=company_name,
                taxonomy=effective_taxonomy,
                concept=effective_concept,
                label=label,
                description=description,
                unit=effective_unit,
                observation_date=observation_date,
                value=value,
                filed_at=filed_at,
                published_at=published_at,
                form=_optional_str(raw_row.get("form")),
                fiscal_year=_sec_company_fact_fiscal_year(raw_row.get("fy")),
                fiscal_period=_optional_str(raw_row.get("fp")),
                accession_number=accession_number,
                frame=_optional_str(raw_row.get("frame")),
                source_url=endpoint,
                source_name="SEC Company Facts",
                entry_id=(
                    f"{cik}:{effective_taxonomy}:{effective_concept}:"
                    f"{effective_unit}:{observation_date}:{accession_number or index}"
                ),
                raw={"index": index, "endpoint": endpoint, "row": dict(raw_row)},
            )
        )
    rows.sort(
        key=lambda item: (
            item.published_at,
            item.observation_date,
            item.accession_number or "",
            item.entry_id,
        )
    )
    return rows[-limit:]


def load_arxiv_papers(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://export.arxiv.org/api/query",
) -> list[ArxivPaper]:
    """Load recent arXiv API papers as timestamped evidence rows."""

    normalized_query = query.strip()
    if not normalized_query:
        raise ValidationError("arxiv import query is required")
    if limit <= 0:
        raise ValidationError("arxiv import --limit must be positive")
    since_dt = timestamp_to_datetime(parse_timestamp(since, field_name="since")) if since else None
    params = {
        "search_query": normalized_query,
        "start": 0,
        "max_results": min(limit, 100),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(params)}"
    text = _read_text_endpoint(endpoint, "arxiv papers")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValidationError("arxiv papers response is not valid Atom XML") from exc

    papers: list[ArxivPaper] = []
    for entry in _namespaced_findall(root, "entry"):
        published_at = _normalize_feed_timestamp(
            _namespaced_text(entry, "published") or _namespaced_text(entry, "updated")
        )
        updated_at = _normalize_feed_timestamp(_namespaced_text(entry, "updated"))
        candidate_dt = timestamp_to_datetime(published_at or updated_at)
        if since_dt is not None and (candidate_dt is None or candidate_dt < since_dt):
            continue
        title = _collapse_ws(_namespaced_text(entry, "title") or "Untitled arXiv paper")
        abstract = _collapse_ws(_namespaced_text(entry, "summary") or "")
        entry_id = _optional_str(_namespaced_text(entry, "id"))
        url = _arxiv_entry_url(entry, entry_id)
        pdf_url = _arxiv_pdf_url(entry)
        authors = [
            name
            for author in _namespaced_findall(entry, "author")
            for name in [_optional_str(_namespaced_text(author, "name"))]
            if name
        ]
        categories = [
            term
            for category in _namespaced_findall(entry, "category")
            for term in [_optional_str(category.attrib.get("term"))]
            if term
        ]
        arxiv_id = _arxiv_id_from_entry_id(entry_id)
        papers.append(
            ArxivPaper(
                arxiv_id=arxiv_id,
                title=title,
                abstract=abstract,
                url=url,
                pdf_url=pdf_url,
                published_at=published_at,
                updated_at=updated_at,
                authors=authors,
                categories=categories,
                source_name="arXiv",
                entry_id=entry_id or arxiv_id or title,
                raw={
                    "id": entry_id,
                    "published": published_at,
                    "updated": updated_at,
                    "authors": authors,
                    "categories": categories,
                    "query": normalized_query,
                },
            )
        )
        if len(papers) >= limit:
            break
    return papers


def load_openalex_works(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.openalex.org/works",
) -> list[OpenAlexWork]:
    """Load OpenAlex scholarly works as timestamped research evidence."""

    normalized_query = query.strip()
    if not normalized_query:
        raise ValidationError("openalex import query is required")
    if limit <= 0:
        raise ValidationError("openalex import --limit must be positive")
    since_date = _fred_date(since, field_name="since") if since else None
    params: dict[str, object] = {
        "search": normalized_query,
        "per-page": min(limit, 200),
        "sort": "publication_date:desc",
    }
    if since_date is not None:
        params["filter"] = f"from_publication_date:{since_date.isoformat()}"
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "openalex works")
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("works") or payload.get("data")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValidationError("openalex works response must contain a results array")

    works: list[OpenAlexWork] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        publication_date = _fred_date(_optional_str(row.get("publication_date")), field_name="openalex publication date")
        if publication_date is not None and since_date is not None and publication_date < since_date:
            continue
        title = _collapse_ws(
            _optional_str(_first_present(row.get("display_name"), row.get("title"))) or "Untitled OpenAlex work"
        )
        location = row.get("primary_location") if isinstance(row.get("primary_location"), dict) else {}
        source = location.get("source") if isinstance(location.get("source"), dict) else {}
        url = _optional_str(
            _first_present(
                location.get("landing_page_url"),
                location.get("pdf_url"),
                row.get("doi"),
                row.get("id"),
            )
        )
        authors = _openalex_authors(row.get("authorships"))
        concepts = _openalex_concepts(row.get("concepts"))
        works.append(
            OpenAlexWork(
                work_id=_optional_str(row.get("id")),
                title=title,
                abstract=_openalex_abstract(row.get("abstract_inverted_index")),
                url=url,
                doi=_optional_str(row.get("doi")),
                published_at=_fred_date_to_iso(publication_date) if publication_date is not None else None,
                updated_at=_openalex_timestamp(row.get("updated_date")),
                authors=authors,
                concepts=concepts,
                source_name=_optional_str(source.get("display_name")) or "OpenAlex",
                entry_id=_optional_str(row.get("id")) or _optional_str(row.get("doi")) or title,
                raw={
                    "id": row.get("id"),
                    "doi": row.get("doi"),
                    "publication_date": row.get("publication_date"),
                    "updated_date": row.get("updated_date"),
                    "authors": authors,
                    "concepts": concepts,
                    "query": normalized_query,
                },
            )
        )
        if len(works) >= limit:
            break
    return works


def load_crossref_works(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.crossref.org/works",
) -> list[CrossrefWork]:
    """Load Crossref works as timestamped DOI/scholarly evidence."""

    normalized_query = query.split(":", 1)[1].strip() if query.startswith("crossref:") else query.strip()
    if not normalized_query:
        raise ValidationError("crossref import query or DOI is required")
    if limit <= 0:
        raise ValidationError("crossref import --limit must be positive")
    since_date = _fred_date(since, field_name="since") if since else None
    params: dict[str, object] = {
        "query.bibliographic": normalized_query,
        "rows": min(limit, 100),
        "sort": "published",
        "order": "desc",
    }
    if since_date is not None:
        params["filter"] = f"from-pub-date:{since_date.isoformat()}"
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "crossref works")
    rows: object
    if isinstance(payload, dict):
        message = payload.get("message")
        rows = message.get("items") if isinstance(message, dict) else payload.get("items")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValidationError("crossref works response must contain a message.items array")

    works: list[CrossrefWork] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        published_at = _crossref_published_at(row)
        published_date = _fred_date(published_at[:10], field_name="crossref publication date") if published_at else None
        if since_date is not None and published_date is not None and published_date < since_date:
            continue
        title = _collapse_ws(_crossref_first(row.get("title")) or "Untitled Crossref work")
        abstract = _collapse_ws(_optional_str(row.get("abstract")) or "")
        doi = _optional_str(row.get("DOI"))
        container_title = _crossref_first(row.get("container-title"))
        publisher = _optional_str(row.get("publisher"))
        source_name = container_title or publisher or "Crossref"
        url = _optional_str(row.get("URL")) or (f"https://doi.org/{quote(doi, safe='/')}" if doi else None)
        entry_id = doi or _optional_str(row.get("member")) or title
        works.append(
            CrossrefWork(
                doi=doi,
                title=title,
                abstract=abstract,
                url=url,
                published_at=published_at,
                updated_at=_crossref_timestamp(row.get("deposited")),
                authors=_crossref_authors(row.get("author")),
                subjects=_crossref_string_list(row.get("subject")),
                container_title=container_title,
                publisher=publisher,
                work_type=_optional_str(row.get("type")),
                reference_count=_optional_int(row.get("reference-count")),
                cited_by_count=_optional_int(row.get("is-referenced-by-count")),
                source_name=source_name,
                entry_id=entry_id,
                raw={
                    "DOI": row.get("DOI"),
                    "URL": row.get("URL"),
                    "published_at": published_at,
                    "deposited": row.get("deposited"),
                    "publisher": row.get("publisher"),
                    "type": row.get("type"),
                    "container-title": row.get("container-title"),
                    "subject": row.get("subject"),
                    "query": normalized_query,
                },
            )
        )
        if len(works) >= limit:
            break
    return works


def load_pubmed_articles(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
) -> list[PubMedArticle]:
    """Load PubMed articles as timestamped biomedical evidence."""

    normalized_query = _pubmed_normalize_source(query)
    if not normalized_query:
        raise ValidationError("pubmed import query, PMID, or URL is required")
    if limit <= 0:
        raise ValidationError("pubmed import --limit must be positive")
    since_date = _fred_date(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(_fred_date_to_iso(since_date)) if since_date is not None else None

    search_endpoint = _pubmed_search_endpoint(
        normalized_query,
        limit=limit,
        since_date=since_date,
        api_base_url=api_base_url,
    )
    search_payload = _read_json_endpoint(search_endpoint, "pubmed search")
    pmids = _pubmed_search_pmids(search_payload)
    if not pmids:
        return []

    fetch_endpoint = _pubmed_fetch_endpoint(pmids[: min(limit, 100)], api_base_url=api_base_url)
    text = _read_text_endpoint(fetch_endpoint, "pubmed articles")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValidationError("pubmed articles response is not valid XML") from exc

    articles: list[PubMedArticle] = []
    for row in _pubmed_descendants(root, "PubmedArticle"):
        article = _pubmed_first_descendant(row, "Article")
        medline = _pubmed_first_descendant(row, "MedlineCitation")
        pubmed_data = _pubmed_first_descendant(row, "PubmedData")
        pmid = _pubmed_text(_pubmed_first_descendant(row, "PMID"))
        if article is None or not pmid:
            continue
        title = _pubmed_text(_pubmed_first_descendant(article, "ArticleTitle")) or f"PubMed article {pmid}"
        abstract = _pubmed_abstract(article)
        journal = _pubmed_journal(article)
        published_at = _pubmed_published_at(article)
        revised_at = _pubmed_date_to_iso(
            _pubmed_first_descendant(medline, "DateRevised") if medline is not None else None
        )
        candidate_dt = timestamp_to_datetime(published_at or revised_at)
        if since_dt is not None and (candidate_dt is None or candidate_dt < since_dt):
            continue
        doi = _pubmed_doi(pubmed_data)
        articles.append(
            PubMedArticle(
                pmid=pmid,
                title=title,
                abstract=abstract,
                journal=journal,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{quote(pmid, safe='')}/",
                doi=doi,
                published_at=published_at,
                revised_at=revised_at,
                authors=_pubmed_authors(article),
                publication_types=_pubmed_publication_types(article),
                source_name="PubMed",
                entry_id=pmid,
                raw={
                    "pmid": pmid,
                    "title": title,
                    "journal": journal,
                    "doi": doi,
                    "published_at": published_at,
                    "revised_at": revised_at,
                    "query": normalized_query,
                },
            )
        )
        if len(articles) >= limit:
            break
    return articles


def load_wikipedia_pages(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://en.wikipedia.org/w/api.php",
) -> list[WikipediaPage]:
    """Load Wikipedia/MediaWiki pages as timestamped reference evidence."""

    normalized_query = query.split(":", 1)[1].strip() if query.startswith("wikipedia:") else query.strip()
    if not normalized_query:
        raise ValidationError("wikipedia import query is required")
    if limit <= 0:
        raise ValidationError("wikipedia import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    params: dict[str, object] = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": normalized_query,
        "gsrlimit": min(limit, 50),
        "prop": "extracts|info|revisions",
        "exintro": 1,
        "explaintext": 1,
        "inprop": "url",
        "rvprop": "timestamp",
    }
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "wikipedia pages")
    if not isinstance(payload, dict):
        raise ValidationError("wikipedia pages response must be a JSON object")
    query_payload = payload.get("query")
    if not isinstance(query_payload, dict):
        return []
    raw_pages = query_payload.get("pages")
    if isinstance(raw_pages, dict):
        rows = list(raw_pages.values())
    elif isinstance(raw_pages, list):
        rows = raw_pages
    else:
        rows = []
    rows = sorted(
        [row for row in rows if isinstance(row, dict)],
        key=lambda row: (
            int(row.get("index") or 10_000_000),
            str(row.get("title") or ""),
        ),
    )

    pages: list[WikipediaPage] = []
    for row in rows:
        title = _collapse_ws(_optional_str(row.get("title")) or "Untitled Wikipedia page")
        revisions = row.get("revisions") if isinstance(row.get("revisions"), list) else []
        revision = revisions[0] if revisions and isinstance(revisions[0], dict) else {}
        updated_at = _wikipedia_timestamp(revision.get("timestamp"))
        updated_dt = timestamp_to_datetime(updated_at) if updated_at else None
        if since_dt is not None and updated_dt is not None and updated_dt < since_dt:
            continue
        page_id = _optional_str(row.get("pageid"))
        pages.append(
            WikipediaPage(
                page_id=page_id,
                title=title,
                extract=_collapse_ws(_optional_str(row.get("extract")) or ""),
                url=_optional_str(row.get("fullurl"))
                or f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                updated_at=updated_at,
                source_name="Wikipedia",
                entry_id=page_id or title,
                raw={
                    "pageid": row.get("pageid"),
                    "title": row.get("title"),
                    "updated_at": updated_at,
                    "query": normalized_query,
                },
            )
        )
        if len(pages) >= limit:
            break
    return pages


def load_wikimedia_pageviews(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    access: str = "all-access",
    agent: str = "user",
    api_base_url: str = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article",
) -> list[WikimediaPageviewObservation]:
    """Load Wikimedia pageview observations as public-attention evidence."""

    project, article = _wikimedia_pageview_source_parts(source)
    if limit <= 0:
        raise ValidationError("wikipediapageviews import --limit must be positive")
    normalized_access = access.strip() or "all-access"
    normalized_agent = agent.strip() or "user"
    since_date = _fred_date(since, field_name="since") if since else None
    end_date = _wikimedia_today_utc()
    if since_date is None:
        from datetime import timedelta

        start_date = end_date - timedelta(days=max(30, limit * 2))
    else:
        start_date = since_date
    if start_date > end_date:
        start_date = end_date
    endpoint = _wikimedia_pageviews_endpoint(
        project,
        article,
        normalized_access,
        normalized_agent,
        start_date,
        end_date,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "wikimedia pageviews")
    if isinstance(payload, dict):
        rows = payload.get("items")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValidationError("wikimedia pageviews response must contain an items array")

    observations: list[WikimediaPageviewObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = row.get("timestamp") or row.get("date")
        observation_date, published_at = _wikimedia_pageview_timestamp(timestamp)
        if observation_date is None or published_at is None:
            continue
        parsed_date = _fred_date(observation_date, field_name="wikimedia pageview date")
        if since_date is not None and parsed_date is not None and parsed_date < since_date:
            continue
        views = _wikimedia_pageview_count(row.get("views"))
        if views is None:
            continue
        row_project = _optional_str(row.get("project")) or project
        row_article = _optional_str(row.get("article")) or article
        row_access = _optional_str(row.get("access")) or normalized_access
        row_agent = _optional_str(row.get("agent")) or normalized_agent
        granularity = _optional_str(row.get("granularity")) or "daily"
        observations.append(
            WikimediaPageviewObservation(
                project=row_project,
                article=row_article,
                access=row_access,
                agent=row_agent,
                granularity=granularity,
                observation_date=observation_date,
                views=views,
                published_at=published_at,
                source_url=endpoint,
                source_name="Wikimedia Pageviews",
                entry_id=f"{row_project}:{row_article}:{observation_date}",
                raw={"endpoint": endpoint, **dict(row)},
            )
        )
    observations.sort(key=lambda item: item.observation_date)
    return observations[-limit:]


def load_github_releases(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.github.com",
) -> list[GitHubRelease]:
    """Load GitHub repository releases as timestamped software evidence."""

    owner, repo_name = _github_repo_parts(source)
    if limit <= 0:
        raise ValidationError("github import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    repo = f"{owner}/{repo_name}"
    endpoint = (
        f"{api_base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repo_name, safe='')}/releases?{urlencode({'per_page': min(limit, 100)})}"
    )
    payload = _read_json_endpoint(endpoint, "github releases")
    if not isinstance(payload, list):
        raise ValidationError("github releases response must be an array")

    releases: list[GitHubRelease] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        published_at = _github_timestamp(row.get("published_at"))
        created_at = _github_timestamp(row.get("created_at"))
        available_at = published_at or created_at
        available_dt = timestamp_to_datetime(available_at) if available_at else None
        if since_dt is not None and available_dt is not None and available_dt < since_dt:
            continue
        tag_name = _optional_str(row.get("tag_name")) or _optional_str(row.get("name")) or "untagged"
        name = _optional_str(row.get("name")) or tag_name
        release_id = _optional_str(row.get("id"))
        releases.append(
            GitHubRelease(
                repo=repo,
                release_id=release_id,
                tag_name=tag_name,
                name=_collapse_ws(name),
                body=_collapse_ws(_optional_str(row.get("body")) or ""),
                url=_optional_str(row.get("url")),
                html_url=_optional_str(row.get("html_url")),
                created_at=created_at,
                published_at=published_at,
                draft=bool(row.get("draft")),
                prerelease=bool(row.get("prerelease")),
                source_name="GitHub",
                entry_id=release_id or tag_name,
                raw={
                    "id": row.get("id"),
                    "tag_name": row.get("tag_name"),
                    "name": row.get("name"),
                    "draft": row.get("draft"),
                    "prerelease": row.get("prerelease"),
                    "repo": repo,
                },
            )
        )
        if len(releases) >= limit:
            break
    return releases


def load_github_issues(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    state: str = "all",
    api_base_url: str = "https://api.github.com",
) -> list[GitHubIssue]:
    """Load GitHub repository issues and pull requests as timestamped software evidence."""

    owner, repo_name = _github_repo_parts(source)
    if limit <= 0:
        raise ValidationError("githubissues import --limit must be positive")
    normalized_state = state.strip().lower()
    if normalized_state not in {"open", "closed", "all"}:
        raise ValidationError("githubissues import --state must be open, closed, or all")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    repo = f"{owner}/{repo_name}"
    params: dict[str, object] = {
        "state": normalized_state,
        "per_page": min(limit, 100),
        "sort": "updated",
        "direction": "desc",
    }
    if since_ts:
        params["since"] = since_ts
    endpoint = (
        f"{api_base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repo_name, safe='')}/issues?{urlencode(params)}"
    )
    payload = _read_json_endpoint(endpoint, "github issues")
    if not isinstance(payload, list):
        raise ValidationError("github issues response must be an array")

    issues: list[GitHubIssue] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        updated_at = _github_timestamp(row.get("updated_at"))
        created_at = _github_timestamp(row.get("created_at"))
        closed_at = _github_timestamp(row.get("closed_at"))
        available_at = updated_at or created_at
        available_dt = timestamp_to_datetime(available_at) if available_at else None
        if since_dt is not None and available_dt is not None and available_dt < since_dt:
            continue
        title = _collapse_ws(_optional_str(row.get("title")) or "Untitled GitHub issue")
        issue_number = _optional_int(row.get("number"))
        labels = _github_label_names(row.get("labels"))
        user = row.get("user")
        author = _optional_str(user.get("login")) if isinstance(user, dict) else None
        is_pull_request = isinstance(row.get("pull_request"), dict)
        issues.append(
            GitHubIssue(
                repo=repo,
                issue_number=issue_number,
                title=title,
                state=_optional_str(row.get("state")),
                is_pull_request=is_pull_request,
                author=author,
                labels=labels,
                created_at=created_at,
                updated_at=updated_at,
                closed_at=closed_at,
                comments=_optional_int(row.get("comments")),
                url=_optional_str(row.get("url")),
                html_url=_optional_str(row.get("html_url")),
                source_name="GitHub",
                entry_id=f"{repo}#{issue_number}" if issue_number is not None else _optional_str(row.get("id")),
                raw={
                    "id": row.get("id"),
                    "number": row.get("number"),
                    "state": row.get("state"),
                    "title": row.get("title"),
                    "repo": repo,
                    "is_pull_request": is_pull_request,
                    "labels": labels,
                },
            )
        )
        if len(issues) >= limit:
            break
    return issues


def load_github_commits(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.github.com",
) -> list[GitHubCommit]:
    """Load GitHub repository commits as timestamped software activity evidence."""

    owner, repo_name = _github_repo_parts(source)
    if limit <= 0:
        raise ValidationError("githubcommits import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    repo = f"{owner}/{repo_name}"
    params: dict[str, object] = {"per_page": min(limit, 100)}
    if since_ts:
        params["since"] = since_ts
    endpoint = (
        f"{api_base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repo_name, safe='')}/commits?{urlencode(params)}"
    )
    payload = _read_json_endpoint(endpoint, "github commits")
    if not isinstance(payload, list):
        raise ValidationError("github commits response must be an array")

    commits: list[GitHubCommit] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        sha = _optional_str(row.get("sha"))
        if not sha:
            continue
        commit = row.get("commit") if isinstance(row.get("commit"), dict) else {}
        author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
        committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
        github_author = row.get("author") if isinstance(row.get("author"), dict) else {}
        authored_at = _github_timestamp(author.get("date"))
        committed_at = _github_timestamp(committer.get("date")) or authored_at
        available_dt = timestamp_to_datetime(committed_at or authored_at) if committed_at or authored_at else None
        if since_dt is not None and available_dt is not None and available_dt < since_dt:
            continue
        message = _collapse_ws(_optional_str(commit.get("message")) or "Untitled GitHub commit")
        commits.append(
            GitHubCommit(
                repo=repo,
                sha=sha,
                short_sha=sha[:7],
                message=message,
                author_name=_optional_str(author.get("name")),
                author_login=_optional_str(github_author.get("login")),
                authored_at=authored_at,
                committed_at=committed_at,
                comments=_optional_int(commit.get("comment_count")),
                url=_optional_str(row.get("url")),
                html_url=_optional_str(row.get("html_url")),
                source_name="GitHub",
                entry_id=f"{repo}@{sha}",
                raw={
                    "sha": sha,
                    "repo": repo,
                    "message": commit.get("message"),
                    "author_name": author.get("name"),
                    "author_login": github_author.get("login"),
                    "authored_at": authored_at,
                    "committed_at": committed_at,
                },
            )
        )
        if len(commits) >= limit:
            break
    return commits


def load_github_workflow_runs(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.github.com",
) -> list[GitHubWorkflowRun]:
    """Load GitHub Actions workflow runs as timestamped operational evidence."""

    owner, repo_name = _github_repo_parts(source)
    if limit <= 0:
        raise ValidationError("githubactions import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    repo = f"{owner}/{repo_name}"
    endpoint = (
        f"{api_base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repo_name, safe='')}/actions/runs?{urlencode({'per_page': min(limit, 100)})}"
    )
    payload = _read_json_endpoint(endpoint, "github actions workflow runs")
    if not isinstance(payload, dict):
        raise ValidationError("github actions workflow runs response must be an object")
    rows = payload.get("workflow_runs")
    if not isinstance(rows, list):
        raise ValidationError("github actions workflow runs response must include workflow_runs array")

    runs: list[GitHubWorkflowRun] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        run_id = _optional_str(row.get("id"))
        if not run_id:
            continue
        created_at = _github_timestamp(row.get("created_at"))
        updated_at = _github_timestamp(row.get("updated_at"))
        run_started_at = _github_timestamp(row.get("run_started_at"))
        available_at = updated_at or run_started_at or created_at
        available_dt = timestamp_to_datetime(available_at) if available_at else None
        if since_dt is not None and available_dt is not None and available_dt < since_dt:
            continue
        actor = row.get("actor") if isinstance(row.get("actor"), dict) else {}
        triggering_actor = row.get("triggering_actor") if isinstance(row.get("triggering_actor"), dict) else {}
        head_sha = _optional_str(row.get("head_sha"))
        name = _collapse_ws(_optional_str(row.get("name")) or "GitHub Actions workflow")
        display_title = _collapse_ws(_optional_str(row.get("display_title")) or name)
        runs.append(
            GitHubWorkflowRun(
                repo=repo,
                run_id=run_id,
                name=name,
                display_title=display_title,
                status=_optional_str(row.get("status")),
                conclusion=_optional_str(row.get("conclusion")),
                event=_optional_str(row.get("event")),
                head_branch=_optional_str(row.get("head_branch")),
                head_sha=head_sha,
                short_sha=head_sha[:7] if head_sha else None,
                workflow_id=_optional_str(row.get("workflow_id")),
                workflow_url=_optional_str(row.get("workflow_url")),
                actor_login=_optional_str(actor.get("login")),
                triggering_actor_login=_optional_str(triggering_actor.get("login")),
                run_started_at=run_started_at,
                created_at=created_at,
                updated_at=updated_at,
                url=_optional_str(row.get("url")),
                html_url=_optional_str(row.get("html_url")),
                source_name="GitHub",
                entry_id=f"{repo}/actions/runs/{run_id}",
                raw={
                    "id": row.get("id"),
                    "repo": repo,
                    "name": row.get("name"),
                    "display_title": row.get("display_title"),
                    "status": row.get("status"),
                    "conclusion": row.get("conclusion"),
                    "event": row.get("event"),
                    "head_branch": row.get("head_branch"),
                    "head_sha": head_sha,
                    "workflow_id": row.get("workflow_id"),
                    "actor_login": actor.get("login"),
                    "triggering_actor_login": triggering_actor.get("login"),
                    "run_started_at": run_started_at,
                    "created_at": created_at,
                    "updated_at": updated_at,
                },
            )
        )
        if len(runs) >= limit:
            break
    return runs


def load_coingecko_market_snapshots(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    vs_currency: str = "usd",
    api_base_url: str = "https://api.coingecko.com/api/v3/coins/markets",
) -> list[CoinGeckoMarketSnapshot]:
    """Load CoinGecko market snapshots as timestamped crypto market evidence."""

    coin_ids = _coingecko_coin_ids(source)
    if limit <= 0:
        raise ValidationError("coingecko import --limit must be positive")
    normalized_currency = vs_currency.strip().lower()
    if not normalized_currency:
        raise ValidationError("coingecko import --vs-currency cannot be empty")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _coingecko_markets_endpoint(
        coin_ids,
        vs_currency=normalized_currency,
        limit=limit,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "coingecko markets")
    if not isinstance(payload, list):
        raise ValidationError("coingecko markets response must be an array")

    snapshots: list[CoinGeckoMarketSnapshot] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        coin_id = _optional_str(row.get("id"))
        if not coin_id:
            continue
        last_updated = _coingecko_timestamp(row.get("last_updated"))
        last_updated_dt = timestamp_to_datetime(last_updated) if last_updated else None
        if since_dt is not None and last_updated_dt is not None and last_updated_dt < since_dt:
            continue
        snapshots.append(
            CoinGeckoMarketSnapshot(
                coin_id=coin_id,
                symbol=_optional_str(row.get("symbol")),
                name=_collapse_optional(row.get("name")),
                vs_currency=normalized_currency,
                current_price=_coingecko_optional_number(row.get("current_price")),
                market_cap=_coingecko_optional_number(row.get("market_cap")),
                market_cap_rank=_optional_int(row.get("market_cap_rank")),
                total_volume=_coingecko_optional_number(row.get("total_volume")),
                price_change_percentage_24h=_coingecko_optional_number(
                    row.get("price_change_percentage_24h")
                ),
                last_updated=last_updated,
                source_url=f"https://www.coingecko.com/en/coins/{quote(coin_id, safe='')}",
                source_name="CoinGecko",
                entry_id=f"{coin_id}:{normalized_currency}:{last_updated or 'latest'}",
                raw={"endpoint": endpoint, "vs_currency": normalized_currency, **dict(row)},
            )
        )
        if len(snapshots) >= limit:
            break
    return snapshots


def load_pypi_releases(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://pypi.org/pypi",
) -> list[PypiRelease]:
    """Load PyPI package releases as timestamped software ecosystem evidence."""

    package = _pypi_package_name(source)
    if limit <= 0:
        raise ValidationError("pypi import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _pypi_project_endpoint(package, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "pypi package")
    if not isinstance(payload, dict):
        raise ValidationError("pypi package response must be a JSON object")
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    releases_payload = payload.get("releases")
    if not isinstance(releases_payload, dict):
        raise ValidationError("pypi package response must include a releases object")

    package_name = _collapse_ws(_optional_str(info.get("name")) or package)
    summary = _collapse_ws(_optional_str(info.get("summary")) or "")
    project_url = _optional_str(info.get("package_url")) or f"https://pypi.org/project/{quote(package_name, safe='')}/"
    rows: list[PypiRelease] = []
    for version, files_value in releases_payload.items():
        version_text = _optional_str(version)
        if not version_text:
            continue
        files = [item for item in files_value if isinstance(item, dict)] if isinstance(files_value, list) else []
        upload_times = [
            uploaded_at
            for item in files
            for uploaded_at in [_pypi_upload_timestamp(item)]
            if uploaded_at is not None
        ]
        uploaded_at = min(upload_times) if upload_times else None
        latest_upload_at = max(upload_times) if upload_times else None
        available_dt = timestamp_to_datetime(latest_upload_at or uploaded_at) if latest_upload_at or uploaded_at else None
        if since_dt is not None and (available_dt is None or available_dt < since_dt):
            continue
        package_types = sorted(
            {
                text
                for item in files
                for text in [_collapse_optional(item.get("packagetype"))]
                if text
            }
        )
        python_versions = sorted(
            {
                text
                for item in files
                for text in [_collapse_optional(item.get("python_version"))]
                if text
            }
        )
        yanked_reason = _pypi_yanked_reason(files)
        rows.append(
            PypiRelease(
                package=package_name,
                version=version_text,
                summary=summary,
                url=f"https://pypi.org/project/{quote(package_name, safe='')}/{quote(version_text, safe='')}/",
                project_url=project_url,
                uploaded_at=uploaded_at,
                latest_upload_at=latest_upload_at,
                file_count=len(files),
                package_types=package_types,
                python_versions=python_versions,
                yanked=any(bool(item.get("yanked")) for item in files),
                yanked_reason=yanked_reason,
                source_name="PyPI",
                entry_id=f"{package_name}:{version_text}",
                raw={
                    "package": package_name,
                    "version": version_text,
                    "summary": summary,
                    "latest_version": info.get("version"),
                    "uploaded_at": uploaded_at,
                    "latest_upload_at": latest_upload_at,
                    "file_count": len(files),
                    "package_types": package_types,
                    "python_versions": python_versions,
                    "yanked": any(bool(item.get("yanked")) for item in files),
                    "yanked_reason": yanked_reason,
                },
            )
        )

    rows.sort(
        key=lambda item: (
            timestamp_to_datetime(item.latest_upload_at or item.uploaded_at)
            or datetime.min.replace(tzinfo=timezone.utc),
            item.version,
        ),
        reverse=True,
    )
    return rows[:limit]


def load_npm_package_versions(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://registry.npmjs.org",
) -> list[NpmPackageVersion]:
    """Load npm package versions as timestamped software ecosystem evidence."""

    package = _npm_package_name(source)
    if limit <= 0:
        raise ValidationError("npm import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _npm_package_endpoint(package, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "npm package")
    if not isinstance(payload, dict):
        raise ValidationError("npm package response must be a JSON object")
    versions_payload = payload.get("versions")
    if not isinstance(versions_payload, dict):
        raise ValidationError("npm package response must include a versions object")
    times = payload.get("time") if isinstance(payload.get("time"), dict) else {}
    package_name = _collapse_ws(_optional_str(payload.get("name")) or package)
    package_description = _collapse_ws(_optional_str(payload.get("description")) or "")

    rows: list[NpmPackageVersion] = []
    for version, row in versions_payload.items():
        if not isinstance(row, dict):
            continue
        version_text = _optional_str(version)
        if not version_text:
            continue
        published_at = _npm_timestamp(times.get(version_text))
        published_dt = timestamp_to_datetime(published_at) if published_at else None
        if since_dt is not None and (published_dt is None or published_dt < since_dt):
            continue
        description = _collapse_ws(_optional_str(row.get("description")) or package_description)
        dist = row.get("dist") if isinstance(row.get("dist"), dict) else {}
        rows.append(
            NpmPackageVersion(
                package=package_name,
                version=version_text,
                description=description,
                url=f"https://www.npmjs.com/package/{quote(package_name, safe='@/')}/v/{quote(version_text, safe='')}",
                tarball_url=_optional_str(dist.get("tarball")),
                published_at=published_at,
                license=_npm_license(row.get("license")),
                maintainers=_npm_people(row.get("maintainers")),
                keywords=_npm_keywords(row.get("keywords")),
                deprecated=_collapse_optional(row.get("deprecated")),
                dependency_count=_npm_dependency_count(row),
                source_name="npm",
                entry_id=f"{package_name}:{version_text}",
                raw={
                    "package": package_name,
                    "version": version_text,
                    "description": description,
                    "dist_tags": payload.get("dist-tags") if isinstance(payload.get("dist-tags"), dict) else {},
                    "published_at": published_at,
                    "tarball_url": _optional_str(dist.get("tarball")),
                    "license": _npm_license(row.get("license")),
                    "deprecated": _collapse_optional(row.get("deprecated")),
                    "dependency_count": _npm_dependency_count(row),
                },
            )
        )

    rows.sort(
        key=lambda item: (
            timestamp_to_datetime(item.published_at) or datetime.min.replace(tzinfo=timezone.utc),
            item.version,
        ),
        reverse=True,
    )
    return rows[:limit]


def load_hackernews_items(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://hn.algolia.com/api/v1/search_by_date",
) -> list[HackerNewsItem]:
    """Load Hacker News search results as timestamped public-attention evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("hackernews:") else source.strip()
    if not normalized_source:
        raise ValidationError("hackernews import query or API URL is required")
    if limit <= 0:
        raise ValidationError("hackernews import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _hackernews_endpoint(normalized_source, limit=limit, since_ts=since_ts, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "hackernews search")
    hits = _hackernews_hits(payload)

    items: list[HackerNewsItem] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        object_id = _optional_str(hit.get("objectID"))
        if not object_id:
            continue
        created_at = _hackernews_timestamp(hit.get("created_at"))
        created_dt = timestamp_to_datetime(created_at) if created_at else None
        if since_dt is not None and created_dt is not None and created_dt < since_dt:
            continue
        title = _collapse_ws(
            _optional_str(
                _first_present(hit.get("title"), hit.get("story_title"), hit.get("comment_text"))
            )
            or "Untitled Hacker News item"
        )
        story_id = _optional_int(_first_present(hit.get("story_id"), hit.get("objectID")))
        hn_url = f"https://news.ycombinator.com/item?id={story_id or object_id}"
        items.append(
            HackerNewsItem(
                object_id=object_id,
                title=title,
                url=_optional_str(_first_present(hit.get("url"), hit.get("story_url"))),
                hn_url=hn_url,
                author=_optional_str(hit.get("author")),
                created_at=created_at,
                points=_optional_int(hit.get("points")),
                comments=_optional_int(hit.get("num_comments")),
                story_id=story_id,
                story_text=_collapse_ws(_optional_str(_first_present(hit.get("story_text"), hit.get("comment_text"))) or ""),
                source_name="Hacker News",
                entry_id=object_id,
                raw={
                    "objectID": hit.get("objectID"),
                    "title": hit.get("title"),
                    "story_title": hit.get("story_title"),
                    "url": hit.get("url"),
                    "story_url": hit.get("story_url"),
                    "author": hit.get("author"),
                    "created_at": hit.get("created_at"),
                    "points": hit.get("points"),
                    "num_comments": hit.get("num_comments"),
                    "query": normalized_source,
                },
            )
        )
        if len(items) >= limit:
            break
    return items


def load_reddit_posts(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://www.reddit.com/search.json",
) -> list[RedditPost]:
    """Load Reddit search results as timestamped public-attention evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("reddit:") else source.strip()
    if not normalized_source:
        raise ValidationError("reddit import query or API URL is required")
    if limit <= 0:
        raise ValidationError("reddit import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _reddit_endpoint(normalized_source, limit=limit, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "reddit search")
    children = _reddit_children(payload)

    posts: list[RedditPost] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        row = child.get("data") if isinstance(child.get("data"), dict) else child
        if not isinstance(row, dict):
            continue
        post_id = _optional_str(_first_present(row.get("name"), row.get("id")))
        if not post_id:
            continue
        created_at = _reddit_timestamp(_first_present(row.get("created_utc"), row.get("created")))
        created_dt = timestamp_to_datetime(created_at) if created_at else None
        if since_dt is not None and created_dt is not None and created_dt < since_dt:
            continue
        title = _collapse_ws(_optional_str(row.get("title")) or "Untitled Reddit post")
        subreddit = _optional_str(row.get("subreddit"))
        permalink = _reddit_permalink(_optional_str(row.get("permalink")))
        posts.append(
            RedditPost(
                post_id=post_id,
                title=title,
                subreddit=subreddit,
                author=_optional_str(row.get("author")),
                url=_optional_str(_first_present(row.get("url_overridden_by_dest"), row.get("url"))),
                permalink=permalink,
                created_at=created_at,
                score=_optional_int(row.get("score")),
                comments=_optional_int(row.get("num_comments")),
                upvote_ratio=_optional_float(row.get("upvote_ratio")),
                selftext=_collapse_ws(_optional_str(row.get("selftext")) or ""),
                source_name=f"Reddit r/{subreddit}" if subreddit else "Reddit",
                entry_id=post_id,
                raw={
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "title": row.get("title"),
                    "subreddit": row.get("subreddit"),
                    "author": row.get("author"),
                    "created_utc": row.get("created_utc"),
                    "score": row.get("score"),
                    "num_comments": row.get("num_comments"),
                    "upvote_ratio": row.get("upvote_ratio"),
                    "query": normalized_source,
                },
            )
        )
        if len(posts) >= limit:
            break
    return posts


def load_bluesky_posts(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    sort: str = "latest",
    author: str | None = None,
    lang: str | None = None,
    link_domain: str | None = None,
    url_filter: str | None = None,
    api_base_url: str = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts",
) -> list[BlueskyPost]:
    """Load Bluesky public search results as timestamped public-attention evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("bluesky:") else source.strip()
    if not normalized_source:
        raise ValidationError("bluesky import query or API URL is required")
    if limit <= 0:
        raise ValidationError("bluesky import --limit must be positive")
    if sort not in {"latest", "top"}:
        raise ValidationError("bluesky import --sort must be latest or top")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _bluesky_endpoint(
        normalized_source,
        limit=limit,
        since_ts=since_ts,
        sort=sort,
        author=author,
        lang=lang,
        link_domain=link_domain,
        url_filter=url_filter,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "bluesky search")
    rows = _bluesky_posts(payload)

    posts: list[BlueskyPost] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = row.get("record") if isinstance(row.get("record"), dict) else {}
        author_row = row.get("author") if isinstance(row.get("author"), dict) else {}
        post_uri = _optional_str(row.get("uri"))
        cid = _optional_str(row.get("cid"))
        if not post_uri:
            continue
        text = _collapse_ws(_optional_str(record.get("text")) or "")
        created_at = _bluesky_timestamp(record.get("createdAt"))
        indexed_at = _bluesky_timestamp(row.get("indexedAt"))
        comparison_time = timestamp_to_datetime(created_at or indexed_at) if (created_at or indexed_at) else None
        if since_dt is not None and comparison_time is not None and comparison_time < since_dt:
            continue
        author_handle = _optional_str(author_row.get("handle"))
        author_did = _optional_str(author_row.get("did"))
        post_url = _bluesky_post_url(post_uri, author_handle or author_did)
        entry_id = post_uri or cid
        posts.append(
            BlueskyPost(
                post_uri=post_uri,
                cid=cid,
                text=text,
                author_handle=author_handle,
                author_display_name=_optional_str(author_row.get("displayName")),
                author_did=author_did,
                created_at=created_at,
                indexed_at=indexed_at,
                reply_count=_optional_int(row.get("replyCount")),
                repost_count=_optional_int(row.get("repostCount")),
                like_count=_optional_int(row.get("likeCount")),
                quote_count=_optional_int(row.get("quoteCount")),
                url=post_url,
                source_name=f"Bluesky @{author_handle}" if author_handle else "Bluesky",
                entry_id=entry_id,
                raw={
                    "uri": row.get("uri"),
                    "cid": row.get("cid"),
                    "author": row.get("author"),
                    "record": row.get("record"),
                    "indexedAt": row.get("indexedAt"),
                    "replyCount": row.get("replyCount"),
                    "repostCount": row.get("repostCount"),
                    "likeCount": row.get("likeCount"),
                    "quoteCount": row.get("quoteCount"),
                    "query": normalized_source,
                    "sort": sort,
                    "author_filter": author,
                    "lang_filter": lang,
                    "link_domain_filter": link_domain,
                    "url_filter": url_filter,
                },
            )
        )
        if len(posts) >= limit:
            break
    return posts


def load_reliefweb_reports(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    appname: str | None = None,
    api_base_url: str = "https://api.reliefweb.int/v1/reports",
) -> list[ReliefWebReport]:
    """Load ReliefWeb reports as humanitarian/disaster evidence."""

    normalized_query = query.split(":", 1)[1].strip() if query.startswith("reliefweb:") else query.strip()
    if not normalized_query:
        raise ValidationError("reliefweb import query or API URL is required")
    if limit <= 0:
        raise ValidationError("reliefweb import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _reliefweb_endpoint(
        normalized_query,
        limit=limit,
        since_ts=since_ts,
        appname=appname or os.getenv("RELIEFWEB_APPNAME") or "superforecasting-agent",
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "reliefweb reports")
    rows = _reliefweb_rows(payload)

    reports: list[ReliefWebReport] = []
    for row in rows:
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else row
        if not isinstance(fields, dict):
            continue
        report_id = _optional_str(_first_present(row.get("id"), fields.get("id")))
        published_at = _reliefweb_timestamp(_first_present(_reliefweb_date(fields, "created"), fields.get("date.created")))
        changed_at = _reliefweb_timestamp(_first_present(_reliefweb_date(fields, "changed"), fields.get("date.changed")))
        published_dt = timestamp_to_datetime(published_at) if published_at else None
        if since_dt is not None and published_dt is not None and published_dt < since_dt:
            continue
        title = _collapse_ws(_optional_str(fields.get("title")) or "Untitled ReliefWeb report")
        sources = _reliefweb_names(fields.get("source"))
        countries = _reliefweb_names(fields.get("country"))
        disasters = _reliefweb_names(fields.get("disaster"))
        formats = _reliefweb_names(fields.get("format"))
        themes = _reliefweb_names(fields.get("theme"))
        url = _optional_str(_first_present(fields.get("url"), row.get("href")))
        summary = _reliefweb_summary(fields)
        reports.append(
            ReliefWebReport(
                report_id=report_id,
                title=title,
                summary=summary,
                url=url,
                published_at=published_at,
                changed_at=changed_at,
                sources=sources,
                countries=countries,
                disasters=disasters,
                formats=formats,
                themes=themes,
                source_name=", ".join(sources[:2]) if sources else "ReliefWeb",
                entry_id=report_id or url or title,
                raw={
                    "id": report_id,
                    "href": row.get("href"),
                    "title": fields.get("title"),
                    "date": fields.get("date"),
                    "sources": sources,
                    "countries": countries,
                    "disasters": disasters,
                    "formats": formats,
                    "themes": themes,
                    "query": normalized_query,
                },
            )
        )
        if len(reports) >= limit:
            break
    return reports


def load_federal_register_documents(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://www.federalregister.gov/api/v1/documents.json",
) -> list[FederalRegisterDocument]:
    """Load Federal Register documents as timestamped policy evidence."""

    normalized_query = query.strip()
    if not normalized_query:
        raise ValidationError("federalregister import query is required")
    if limit <= 0:
        raise ValidationError("federalregister import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    base = api_base_url.rstrip("/")
    endpoint_base = base if base.endswith(".json") else f"{base}/documents.json"
    params: dict[str, object] = {
        "conditions[term]": normalized_query,
        "order": "newest",
        "per_page": min(limit, 100),
    }
    if since_ts:
        params["conditions[publication_date][gte]"] = since_ts[:10]
    endpoint = f"{endpoint_base}?{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "federal register documents")
    if isinstance(payload, dict):
        rows = payload.get("results")
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValidationError("federal register documents response must include a results array")

    documents: list[FederalRegisterDocument] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        published_at = _federalregister_timestamp(row.get("publication_date"))
        published_dt = timestamp_to_datetime(published_at) if published_at else None
        if since_dt is not None and published_dt is not None and published_dt < since_dt:
            continue
        agencies_raw = row.get("agencies") if isinstance(row.get("agencies"), list) else []
        agencies = [
            name
            for agency in agencies_raw
            if isinstance(agency, dict)
            for name in [_optional_str(agency.get("name"))]
            if name
        ]
        document_number = _optional_str(row.get("document_number"))
        title = _collapse_ws(_optional_str(row.get("title")) or "Untitled Federal Register document")
        documents.append(
            FederalRegisterDocument(
                document_number=document_number,
                title=title,
                abstract=_collapse_ws(_optional_str(row.get("abstract")) or ""),
                url=_optional_str(row.get("html_url")),
                pdf_url=_optional_str(row.get("pdf_url")),
                published_at=published_at,
                document_type=_optional_str(row.get("type")) or _optional_str(row.get("document_type")),
                agencies=agencies,
                citation=_optional_str(row.get("citation")),
                source_name="Federal Register",
                entry_id=document_number or _optional_str(row.get("html_url")) or title,
                raw={
                    "document_number": row.get("document_number"),
                    "title": row.get("title"),
                    "publication_date": row.get("publication_date"),
                    "type": row.get("type"),
                    "agencies": agencies,
                    "query": normalized_query,
                },
            )
        )
        if len(documents) >= limit:
            break
    return documents


def load_courtlistener_search_results(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    search_type: str = "o",
    api_base_url: str = "https://www.courtlistener.com/api/rest/v4/search/",
) -> list[CourtListenerSearchResult]:
    """Load CourtListener search results as timestamped legal evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("courtlistener:") else source.strip()
    if not normalized_source:
        raise ValidationError("courtlistener import query or API URL is required")
    if limit <= 0:
        raise ValidationError("courtlistener import --limit must be positive")
    normalized_type = search_type.strip() or "o"
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _courtlistener_endpoint(
        normalized_source,
        limit=limit,
        search_type=normalized_type,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "courtlistener search")
    if isinstance(payload, dict):
        rows = payload.get("results")
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValidationError("courtlistener search response must include a results array")

    results: list[CourtListenerSearchResult] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date_filed = _courtlistener_timestamp(
            _first_present(row.get("dateFiled"), row.get("date_filed"), row.get("dateFiledPretty"))
        )
        date_argued = _courtlistener_timestamp(
            _first_present(row.get("dateArgued"), row.get("date_argued"), row.get("dateReargued"))
        )
        available_at = date_filed or date_argued
        available_dt = timestamp_to_datetime(available_at) if available_at else None
        if since_dt is not None and available_dt is not None and available_dt < since_dt:
            continue
        title = _collapse_ws(
            _optional_str(_first_present(row.get("caseName"), row.get("caseNameFull"), row.get("title")))
            or "Untitled CourtListener result"
        )
        result_id = _optional_str(_first_present(row.get("id"), row.get("cluster_id"), row.get("opinion_id")))
        court = _optional_str(row.get("court"))
        court_id = _optional_str(row.get("court_id"))
        url = _courtlistener_result_url(
            _optional_str(_first_present(row.get("absolute_url"), row.get("absoluteUrl"), row.get("url")))
        )
        results.append(
            CourtListenerSearchResult(
                result_id=result_id,
                title=title,
                snippet=_collapse_ws(_optional_str(_first_present(row.get("snippet"), row.get("text"))) or ""),
                url=url,
                court=court,
                court_id=court_id,
                docket_number=_optional_str(_first_present(row.get("docketNumber"), row.get("docket_number"))),
                date_filed=date_filed,
                date_argued=date_argued,
                status=_optional_str(row.get("status")),
                citation=_courtlistener_citation(row),
                judge=_collapse_ws(_optional_str(row.get("judge")) or ""),
                cite_count=_optional_int(_first_present(row.get("citeCount"), row.get("cite_count"))),
                search_type=normalized_type,
                source_name=f"CourtListener {court_id}" if court_id else "CourtListener",
                entry_id=result_id or url or title,
                raw={
                    "id": row.get("id"),
                    "cluster_id": row.get("cluster_id"),
                    "opinion_id": row.get("opinion_id"),
                    "caseName": row.get("caseName"),
                    "court": court,
                    "court_id": court_id,
                    "docketNumber": row.get("docketNumber"),
                    "dateFiled": row.get("dateFiled"),
                    "query": normalized_source,
                    "search_type": normalized_type,
                },
            )
        )
        if len(results) >= limit:
            break
    return results


def load_nvd_cves(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://services.nvd.nist.gov/rest/json/cves/2.0",
) -> list[NvdCve]:
    """Load NVD CVE records as timestamped security evidence."""

    normalized_query = query.split(":", 1)[1].strip() if query.startswith("nvd:") else query.strip()
    if not normalized_query:
        raise ValidationError("nvd import query is required")
    if limit <= 0:
        raise ValidationError("nvd import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    params: dict[str, object] = {"resultsPerPage": min(limit, 2000)}
    if normalized_query.upper().startswith("CVE-"):
        params["cveIds"] = normalized_query.upper()
    else:
        params["keywordSearch"] = normalized_query
    endpoint = f"{api_base_url.rstrip('/')}?{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "nvd cves")
    if not isinstance(payload, dict) or not isinstance(payload.get("vulnerabilities"), list):
        raise ValidationError("nvd cves response must include a vulnerabilities array")

    cves: list[NvdCve] = []
    for row in payload["vulnerabilities"]:
        if not isinstance(row, dict):
            continue
        cve = row.get("cve")
        if not isinstance(cve, dict):
            continue
        cve_id = _optional_str(cve.get("id"))
        if not cve_id:
            continue
        published_at = _nvd_timestamp(cve.get("published"))
        published_dt = timestamp_to_datetime(published_at) if published_at else None
        if since_dt is not None and published_dt is not None and published_dt < since_dt:
            continue
        severity, base_score, cvss_version = _nvd_cvss_summary(cve.get("metrics"))
        references = _nvd_references(cve.get("references"))
        cves.append(
            NvdCve(
                cve_id=cve_id,
                description=_nvd_description(cve.get("descriptions")),
                url=f"https://nvd.nist.gov/vuln/detail/{quote(cve_id, safe='')}",
                published_at=published_at,
                last_modified_at=_nvd_timestamp(cve.get("lastModified")),
                vuln_status=_optional_str(cve.get("vulnStatus")),
                severity=severity,
                base_score=base_score,
                cvss_version=cvss_version,
                references=references,
                source_identifier=_optional_str(cve.get("sourceIdentifier")),
                source_name="NVD",
                entry_id=cve_id,
                raw={
                    "id": cve.get("id"),
                    "published": cve.get("published"),
                    "lastModified": cve.get("lastModified"),
                    "vulnStatus": cve.get("vulnStatus"),
                    "severity": severity,
                    "base_score": base_score,
                    "cvss_version": cvss_version,
                    "query": normalized_query,
                },
            )
        )
        if len(cves) >= limit:
            break
    return cves


def load_cisa_kev_vulnerabilities(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
) -> list[CisaKevVulnerability]:
    """Load CISA Known Exploited Vulnerabilities records as security evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("cisakev:") else source.strip()
    if not normalized_source:
        raise ValidationError("cisakev import query, CVE id, all, or catalog URL is required")
    if limit <= 0:
        raise ValidationError("cisakev import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None

    parsed = urlparse(normalized_source)
    is_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    endpoint = normalized_source if is_url else api_base_url
    filter_query = "" if is_url else normalized_source
    payload = _read_json_endpoint(endpoint, "cisa kev catalog")
    if isinstance(payload, dict):
        rows = payload.get("vulnerabilities")
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValidationError("cisa kev catalog response must include a vulnerabilities array")

    vulnerabilities: list[CisaKevVulnerability] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cve_id = _optional_str(_first_present(row.get("cveID"), row.get("cveId"), row.get("cve_id")))
        if not cve_id:
            continue
        if filter_query and not _cisa_kev_matches_query(row, filter_query):
            continue
        date_added = _cisa_kev_timestamp(row.get("dateAdded"))
        added_dt = timestamp_to_datetime(date_added) if date_added else None
        if since_dt is not None and added_dt is not None and added_dt < since_dt:
            continue
        vulnerability_name = _collapse_ws(
            _optional_str(row.get("vulnerabilityName")) or f"CISA KEV record for {cve_id}"
        )
        vulnerabilities.append(
            CisaKevVulnerability(
                cve_id=cve_id,
                vendor_project=_optional_str(row.get("vendorProject")),
                product=_optional_str(row.get("product")),
                vulnerability_name=vulnerability_name,
                short_description=_collapse_ws(_optional_str(row.get("shortDescription")) or ""),
                date_added=date_added,
                due_date=_cisa_kev_timestamp(row.get("dueDate")),
                required_action=_collapse_ws(_optional_str(row.get("requiredAction")) or ""),
                ransomware_use=_optional_str(row.get("knownRansomwareCampaignUse")),
                notes=_collapse_ws(_optional_str(row.get("notes")) or ""),
                cwes=_cisa_kev_cwes(row.get("cwes")),
                source_url=endpoint,
                source_name="CISA Known Exploited Vulnerabilities",
                entry_id=cve_id,
                raw={
                    "cveID": row.get("cveID"),
                    "vendorProject": row.get("vendorProject"),
                    "product": row.get("product"),
                    "vulnerabilityName": row.get("vulnerabilityName"),
                    "dateAdded": row.get("dateAdded"),
                    "dueDate": row.get("dueDate"),
                    "knownRansomwareCampaignUse": row.get("knownRansomwareCampaignUse"),
                    "query": filter_query or normalized_source,
                },
            )
        )
        if len(vulnerabilities) >= limit:
            break
    return vulnerabilities


def load_usgs_earthquakes(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://earthquake.usgs.gov/fdsnws/event/1/query",
) -> list[UsgsEarthquakeEvent]:
    """Load USGS earthquake GeoJSON events as timestamped geophysical evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("usgs:") else source.strip()
    if not normalized_source:
        raise ValidationError("usgs import query, event id, or API URL is required")
    if limit <= 0:
        raise ValidationError("usgs import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _usgs_earthquake_endpoint(
        normalized_source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "usgs earthquakes")
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValidationError("usgs earthquake response must be GeoJSON with a features array")

    events: list[UsgsEarthquakeEvent] = []
    for feature in payload["features"]:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict):
            continue
        geometry = geometry if isinstance(geometry, dict) else {}
        time = _usgs_ms_to_iso(properties.get("time"))
        time_dt = timestamp_to_datetime(time) if time else None
        if since_dt is not None and time_dt is not None and time_dt < since_dt:
            continue
        event_id = _optional_str(feature.get("id")) or _optional_str(properties.get("code"))
        magnitude = _optional_float(properties.get("mag"))
        place = _optional_str(properties.get("place"))
        event_type = _optional_str(properties.get("type"))
        title = _collapse_ws(
            _optional_str(properties.get("title")) or _usgs_event_title(magnitude=magnitude, place=place)
        )
        longitude, latitude, depth_km = _usgs_coordinates(geometry.get("coordinates"))
        events.append(
            UsgsEarthquakeEvent(
                event_id=event_id,
                title=title,
                url=_optional_str(_first_present(properties.get("url"), properties.get("detail"))),
                time=time,
                updated_at=_usgs_ms_to_iso(properties.get("updated")),
                magnitude=magnitude,
                place=place,
                event_type=event_type,
                status=_optional_str(properties.get("status")),
                tsunami=_optional_int(properties.get("tsunami")),
                significance=_optional_int(properties.get("sig")),
                longitude=longitude,
                latitude=latitude,
                depth_km=depth_km,
                source_name="USGS Earthquake Catalog",
                entry_id=event_id or title,
                raw=dict(feature),
            )
        )
        if len(events) >= limit:
            break
    return events


def load_nasa_eonet_events(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://eonet.gsfc.nasa.gov/api/v3/events",
) -> list[NasaEonetEvent]:
    """Load NASA EONET natural events as timestamped hazard evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("eonet:") else source.strip()
    if not normalized_source:
        raise ValidationError("eonet import query, category, or API URL is required")
    if limit <= 0:
        raise ValidationError("eonet import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _eonet_endpoint(
        normalized_source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "nasa eonet events")
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValidationError("nasa eonet response must include an events array")

    events: list[NasaEonetEvent] = []
    for row in payload["events"]:
        if not isinstance(row, dict):
            continue
        geometry = _eonet_latest_geometry(row.get("geometry"))
        latest_geometry_at = _eonet_timestamp(geometry.get("date")) if geometry else None
        latest_dt = timestamp_to_datetime(latest_geometry_at) if latest_geometry_at else None
        if since_dt is not None and latest_dt is not None and latest_dt < since_dt:
            continue
        longitude, latitude = _eonet_first_coordinate(geometry.get("coordinates") if geometry else None)
        event_id = _optional_str(row.get("id"))
        title = _collapse_ws(_optional_str(row.get("title")) or "Untitled NASA EONET event")
        events.append(
            NasaEonetEvent(
                event_id=event_id,
                title=title,
                description=_collapse_ws(_optional_str(row.get("description")) or ""),
                url=_optional_str(_first_present(row.get("link"), row.get("url"))),
                status=_optional_str(row.get("status")),
                closed_at=_eonet_timestamp(row.get("closed")),
                latest_geometry_at=latest_geometry_at,
                categories=_eonet_categories(row.get("categories")),
                source_names=_eonet_source_names(row.get("sources")),
                source_urls=_eonet_source_urls(row.get("sources")),
                longitude=longitude,
                latitude=latitude,
                source_name="NASA EONET",
                entry_id=event_id or title,
                raw=dict(row),
            )
        )
        if len(events) >= limit:
            break
    return events


def load_nws_alerts(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.weather.gov/alerts/active",
) -> list[NwsAlert]:
    """Load National Weather Service active alerts as timestamped operational evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("nws:") else source.strip()
    if not normalized_source:
        raise ValidationError("nws import area, point, event query, or API URL is required")
    if limit <= 0:
        raise ValidationError("nws import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _nws_alerts_endpoint(normalized_source, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "nws alerts")
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValidationError("nws alerts response must be GeoJSON with a features array")

    alerts: list[NwsAlert] = []
    for feature in payload["features"]:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        sent_at = _nws_alert_timestamp(properties.get("sent"))
        effective_at = _nws_alert_timestamp(properties.get("effective"))
        onset_at = _nws_alert_timestamp(properties.get("onset"))
        updated_at = sent_at or effective_at or onset_at
        updated_dt = timestamp_to_datetime(updated_at) if updated_at else None
        if since_dt is not None and updated_dt is not None and updated_dt < since_dt:
            continue
        alert_id = _optional_str(_first_present(properties.get("id"), properties.get("@id"), feature.get("id")))
        event = _collapse_ws(_optional_str(properties.get("event")) or "NWS alert")
        headline = _collapse_ws(_optional_str(properties.get("headline")) or event)
        alerts.append(
            NwsAlert(
                alert_id=alert_id,
                event=event,
                headline=headline,
                description=_collapse_ws(_optional_str(properties.get("description")) or ""),
                instruction=_collapse_ws(_optional_str(properties.get("instruction")) or ""),
                url=_optional_str(_first_present(properties.get("@id"), feature.get("id"))),
                area_desc=_collapse_ws(_optional_str(properties.get("areaDesc")) or ""),
                severity=_optional_str(properties.get("severity")),
                certainty=_optional_str(properties.get("certainty")),
                urgency=_optional_str(properties.get("urgency")),
                status=_optional_str(properties.get("status")),
                message_type=_optional_str(properties.get("messageType")),
                category=_optional_str(properties.get("category")),
                response=_optional_str(properties.get("response")),
                sent_at=sent_at,
                effective_at=effective_at,
                onset_at=onset_at,
                expires_at=_nws_alert_timestamp(properties.get("expires")),
                ends_at=_nws_alert_timestamp(properties.get("ends")),
                source_name=_optional_str(properties.get("senderName")) or "National Weather Service",
                entry_id=alert_id or headline,
                raw=dict(feature),
            )
        )
        if len(alerts) >= limit:
            break
    return alerts


def load_clinicaltrials_studies(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://clinicaltrials.gov/api/v2/studies",
) -> list[ClinicalTrialStudy]:
    """Load ClinicalTrials.gov studies as timestamped health/biotech evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("clinicaltrials:") else source.strip()
    if not normalized_source:
        raise ValidationError("clinicaltrials import query, NCT id, or API URL is required")
    if limit <= 0:
        raise ValidationError("clinicaltrials import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _clinicaltrials_endpoint(normalized_source, limit=limit, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "clinicaltrials studies")
    raw_studies = _clinicaltrials_study_rows(payload)

    studies: list[ClinicalTrialStudy] = []
    for row in raw_studies:
        if not isinstance(row, dict):
            continue
        protocol = row.get("protocolSection")
        if not isinstance(protocol, dict):
            protocol = {}
        identification = protocol.get("identificationModule")
        status = protocol.get("statusModule")
        design = protocol.get("designModule")
        conditions = protocol.get("conditionsModule")
        interventions = protocol.get("armsInterventionsModule")
        sponsors = protocol.get("sponsorCollaboratorsModule")
        identification = identification if isinstance(identification, dict) else {}
        status = status if isinstance(status, dict) else {}
        design = design if isinstance(design, dict) else {}
        conditions = conditions if isinstance(conditions, dict) else {}
        interventions = interventions if isinstance(interventions, dict) else {}
        sponsors = sponsors if isinstance(sponsors, dict) else {}

        nct_id = _optional_str(identification.get("nctId"))
        if not nct_id:
            continue
        last_update_posted_at = _clinicaltrials_date_to_iso(
            _first_present(status.get("lastUpdatePostDateStruct"), status.get("lastUpdatePostDate"))
        )
        last_update_submitted_at = _clinicaltrials_date_to_iso(
            _first_present(status.get("lastUpdateSubmitDate"), status.get("lastUpdateSubmittedDate"))
        )
        updated_at = last_update_posted_at or last_update_submitted_at
        updated_dt = timestamp_to_datetime(updated_at) if updated_at else None
        if since_dt is not None and updated_dt is not None and updated_dt < since_dt:
            continue

        brief_title = _collapse_ws(
            _optional_str(_first_present(identification.get("briefTitle"), identification.get("officialTitle")))
            or nct_id
        )
        study = ClinicalTrialStudy(
            nct_id=nct_id,
            brief_title=brief_title,
            official_title=_collapse_optional(identification.get("officialTitle")),
            url=f"https://clinicaltrials.gov/study/{quote(nct_id, safe='')}",
            status=_optional_str(status.get("overallStatus")),
            phases=_clinicaltrials_list(design.get("phases")),
            study_type=_optional_str(design.get("studyType")),
            conditions=_clinicaltrials_list(conditions.get("conditions")),
            interventions=_clinicaltrials_interventions(interventions.get("interventions")),
            sponsors=_clinicaltrials_sponsors(sponsors),
            start_date=_clinicaltrials_date_to_iso(_first_present(status.get("startDateStruct"), status.get("startDate"))),
            primary_completion_date=_clinicaltrials_date_to_iso(
                _first_present(status.get("primaryCompletionDateStruct"), status.get("primaryCompletionDate"))
            ),
            completion_date=_clinicaltrials_date_to_iso(
                _first_present(status.get("completionDateStruct"), status.get("completionDate"))
            ),
            last_update_submitted_at=last_update_submitted_at,
            last_update_posted_at=last_update_posted_at,
            has_results=bool(row.get("hasResults")),
            source_name="ClinicalTrials.gov",
            entry_id=nct_id,
            raw=dict(row),
        )
        studies.append(study)
        if len(studies) >= limit:
            break
    return studies


def load_openfda_drug_applications(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.fda.gov/drug/drugsfda.json",
) -> list[OpenFdaDrugApplication]:
    """Load openFDA Drugs@FDA application records as regulatory evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("openfda:") else source.strip()
    if not normalized_source:
        raise ValidationError("openfda import query, application number, or API URL is required")
    if limit <= 0:
        raise ValidationError("openfda import --limit must be positive")
    since_iso = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_iso) if since_iso else None
    endpoint = _openfda_endpoint(normalized_source, limit=limit, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "openFDA Drugs@FDA applications")
    rows = _openfda_application_rows(payload)

    applications: list[OpenFdaDrugApplication] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        application_number = _collapse_optional(row.get("application_number"))
        if not application_number:
            continue
        latest = _openfda_latest_submission(row.get("submissions"))
        latest_submission_status_date = _openfda_date_to_iso(
            _first_present(latest.get("submission_status_date"), latest.get("submission_date"))
        )
        if since_dt is not None:
            application_dt = timestamp_to_datetime(latest_submission_status_date)
            if application_dt is None or application_dt < since_dt:
                continue
        openfda = row.get("openfda") if isinstance(row.get("openfda"), dict) else {}
        products = row.get("products") if isinstance(row.get("products"), list) else []
        brand_names = _openfda_unique(
            _openfda_list(openfda.get("brand_name")) + _openfda_product_values(products, "brand_name")
        )
        generic_names = _openfda_unique(
            _openfda_list(openfda.get("generic_name")) + _openfda_product_values(products, "generic_name")
        )
        routes = _openfda_unique(_openfda_list(openfda.get("route")) + _openfda_product_values(products, "route"))
        substances = _openfda_unique(
            _openfda_list(openfda.get("substance_name")) + _openfda_active_ingredient_names(products)
        )
        dosage_forms = _openfda_unique(_openfda_product_values(products, "dosage_form"))
        marketing_statuses = _openfda_unique(_openfda_product_values(products, "marketing_status"))
        url = _openfda_application_url(application_number, latest)
        applications.append(
            OpenFdaDrugApplication(
                application_number=application_number,
                sponsor_name=_collapse_optional(row.get("sponsor_name")),
                brand_names=brand_names,
                generic_names=generic_names,
                routes=routes,
                substances=substances,
                dosage_forms=dosage_forms,
                marketing_statuses=marketing_statuses,
                latest_submission_status=_collapse_optional(latest.get("submission_status")),
                latest_submission_status_date=latest_submission_status_date,
                latest_submission_type=_collapse_optional(latest.get("submission_type")),
                latest_submission_class=_collapse_optional(
                    _first_present(latest.get("submission_class_code"), latest.get("submission_class_code_description"))
                ),
                url=url,
                source_name="openFDA Drugs@FDA",
                entry_id=application_number,
                raw=dict(row),
            )
        )
        if len(applications) >= limit:
            break
    return applications


def load_openmeteo_daily_forecasts(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    forecast_days: int = 7,
    api_base_url: str = "https://api.open-meteo.com/v1/forecast",
) -> list[OpenMeteoDailyForecast]:
    """Load Open-Meteo daily forecast rows as weather evidence."""

    latitude, longitude = _openmeteo_coordinates(source)
    if limit <= 0:
        raise ValidationError("openmeteo import --limit must be positive")
    if forecast_days <= 0 or forecast_days > 16:
        raise ValidationError("openmeteo import --forecast-days must be between 1 and 16")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join(
            [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "wind_speed_10m_max",
            ]
        ),
        "timezone": "UTC",
        "forecast_days": forecast_days,
    }
    endpoint = f"{api_base_url.rstrip('/')}?{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "openmeteo forecast")
    if not isinstance(payload, dict) or not isinstance(payload.get("daily"), dict):
        raise ValidationError("openmeteo forecast response must include a daily object")
    daily = payload["daily"]
    dates = daily.get("time")
    if not isinstance(dates, list):
        raise ValidationError("openmeteo forecast daily response must include time")

    forecasts: list[OpenMeteoDailyForecast] = []
    for index, raw_date in enumerate(dates):
        forecast_date = _optional_str(raw_date)
        if not forecast_date:
            continue
        forecast_ts = _openmeteo_date_to_iso(forecast_date)
        forecast_dt = timestamp_to_datetime(forecast_ts) if forecast_ts else None
        if since_dt is not None and forecast_dt is not None and forecast_dt < since_dt:
            continue
        forecasts.append(
            OpenMeteoDailyForecast(
                latitude=latitude,
                longitude=longitude,
                forecast_date=forecast_date,
                temperature_2m_max=_openmeteo_daily_float(daily, "temperature_2m_max", index),
                temperature_2m_min=_openmeteo_daily_float(daily, "temperature_2m_min", index),
                precipitation_sum=_openmeteo_daily_float(daily, "precipitation_sum", index),
                wind_speed_10m_max=_openmeteo_daily_float(daily, "wind_speed_10m_max", index),
                source_name="Open-Meteo",
                entry_id=f"{latitude},{longitude}:{forecast_date}",
                raw={
                    "latitude": payload.get("latitude", latitude),
                    "longitude": payload.get("longitude", longitude),
                    "forecast_date": forecast_date,
                    "daily_units": payload.get("daily_units") if isinstance(payload.get("daily_units"), dict) else {},
                },
            )
        )
        if len(forecasts) >= limit:
            break
    return forecasts


def load_openmeteo_air_quality_forecasts(
    source: str,
    *,
    limit: int = 24,
    since: str | None = None,
    forecast_days: int = 5,
    api_base_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality",
) -> list[OpenMeteoAirQualityForecast]:
    """Load Open-Meteo hourly air-quality forecast rows as evidence."""

    latitude, longitude = _openmeteo_coordinates(source, label="airquality")
    if limit <= 0:
        raise ValidationError("airquality import --limit must be positive")
    if forecast_days <= 0 or forecast_days > 7:
        raise ValidationError("airquality import --forecast-days must be between 1 and 7")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(
            [
                "us_aqi",
                "european_aqi",
                "pm10",
                "pm2_5",
                "carbon_monoxide",
                "nitrogen_dioxide",
                "ozone",
            ]
        ),
        "timezone": "UTC",
        "forecast_days": forecast_days,
    }
    endpoint = f"{api_base_url.rstrip('/')}?{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "openmeteo air quality")
    if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
        raise ValidationError("airquality response must include an hourly object")
    hourly = payload["hourly"]
    times = hourly.get("time")
    if not isinstance(times, list):
        raise ValidationError("airquality hourly response must include time")

    forecasts: list[OpenMeteoAirQualityForecast] = []
    for index, raw_time in enumerate(times):
        forecast_time = _optional_str(raw_time)
        if not forecast_time:
            continue
        forecast_ts = _openmeteo_time_to_iso(forecast_time)
        forecast_dt = timestamp_to_datetime(forecast_ts) if forecast_ts else None
        if since_dt is not None and forecast_dt is not None and forecast_dt < since_dt:
            continue
        stored_time = forecast_ts or forecast_time
        forecasts.append(
            OpenMeteoAirQualityForecast(
                latitude=latitude,
                longitude=longitude,
                forecast_time=stored_time,
                us_aqi=_openmeteo_hourly_float(hourly, "us_aqi", index),
                european_aqi=_openmeteo_hourly_float(hourly, "european_aqi", index),
                pm10=_openmeteo_hourly_float(hourly, "pm10", index),
                pm2_5=_openmeteo_hourly_float(hourly, "pm2_5", index),
                carbon_monoxide=_openmeteo_hourly_float(hourly, "carbon_monoxide", index),
                nitrogen_dioxide=_openmeteo_hourly_float(hourly, "nitrogen_dioxide", index),
                ozone=_openmeteo_hourly_float(hourly, "ozone", index),
                source_name="Open-Meteo Air Quality",
                entry_id=f"{latitude},{longitude}:{stored_time}",
                raw={
                    "latitude": payload.get("latitude", latitude),
                    "longitude": payload.get("longitude", longitude),
                    "forecast_time": stored_time,
                    "hourly_units": payload.get("hourly_units") if isinstance(payload.get("hourly_units"), dict) else {},
                },
            )
        )
        if len(forecasts) >= limit:
            break
    return forecasts


def load_openmeteo_historical_weather(
    source: str,
    *,
    limit: int = 30,
    since: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    api_base_url: str = "https://archive-api.open-meteo.com/v1/archive",
) -> list[OpenMeteoHistoricalWeatherObservation]:
    """Load Open-Meteo historical daily weather observations as evidence."""

    latitude, longitude, start_day, end_day = _openmeteo_history_request(
        source,
        start_date=start_date,
        end_date=end_date,
    )
    if limit <= 0:
        raise ValidationError("weatherhistory import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_day,
        "end_date": end_day,
        "daily": ",".join(
            [
                "temperature_2m_mean",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "wind_speed_10m_max",
            ]
        ),
        "timezone": "UTC",
    }
    endpoint = f"{api_base_url.rstrip('/')}?{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "openmeteo historical weather")
    if not isinstance(payload, dict) or not isinstance(payload.get("daily"), dict):
        raise ValidationError("weatherhistory response must include a daily object")
    daily = payload["daily"]
    dates = daily.get("time")
    if not isinstance(dates, list):
        raise ValidationError("weatherhistory daily response must include time")

    observations: list[OpenMeteoHistoricalWeatherObservation] = []
    for index, raw_date in enumerate(dates):
        observation_date = _optional_str(raw_date)
        if not observation_date:
            continue
        observation_ts = _openmeteo_date_to_iso(observation_date)
        observation_dt = timestamp_to_datetime(observation_ts) if observation_ts else None
        if since_dt is not None and observation_dt is not None and observation_dt < since_dt:
            continue
        observations.append(
            OpenMeteoHistoricalWeatherObservation(
                latitude=latitude,
                longitude=longitude,
                observation_date=observation_date,
                temperature_2m_mean=_openmeteo_daily_float(daily, "temperature_2m_mean", index),
                temperature_2m_max=_openmeteo_daily_float(daily, "temperature_2m_max", index),
                temperature_2m_min=_openmeteo_daily_float(daily, "temperature_2m_min", index),
                precipitation_sum=_openmeteo_daily_float(daily, "precipitation_sum", index),
                wind_speed_10m_max=_openmeteo_daily_float(daily, "wind_speed_10m_max", index),
                source_name="Open-Meteo Historical Weather",
                entry_id=f"{latitude},{longitude}:{observation_date}",
                raw={
                    "latitude": payload.get("latitude", latitude),
                    "longitude": payload.get("longitude", longitude),
                    "observation_date": observation_date,
                    "daily_units": payload.get("daily_units") if isinstance(payload.get("daily_units"), dict) else {},
                },
            )
        )
        if len(observations) >= limit:
            break
    return observations


def load_owid_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    entity: str | None = None,
    value_column: str | None = None,
    api_base_url: str = "https://ourworldindata.org/grapher",
) -> list[OwidObservation]:
    """Load Our World in Data grapher CSV rows as data evidence."""

    slug, endpoint = _owid_endpoint(source, api_base_url=api_base_url)
    if limit <= 0:
        raise ValidationError("owid import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    text = _read_text_endpoint(endpoint, "owid grapher csv")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        return []
    selected_value_column = value_column or _owid_value_column(rows[0])
    observations: list[OwidObservation] = []
    entity_filter = entity.casefold() if entity else None
    for row in rows:
        if entity_filter and _optional_str(row.get("Entity", "")).casefold() != entity_filter:
            continue
        observation_date = _optional_str(row.get("Year")) or _optional_str(row.get("Date"))
        if not observation_date:
            continue
        published_at = _owid_date_to_iso(observation_date)
        if not published_at:
            continue
        published_dt = timestamp_to_datetime(published_at) if published_at else None
        if since_dt is not None and published_dt is not None and published_dt < since_dt:
            continue
        raw_value = _optional_str(row.get(selected_value_column))
        value = _optional_float(raw_value)
        observations.append(
            OwidObservation(
                slug=slug,
                entity=_optional_str(row.get("Entity")),
                code=_optional_str(row.get("Code")),
                observation_date=observation_date,
                value=value if value is not None else raw_value,
                value_column=selected_value_column,
                published_at=published_at,
                source_url=endpoint,
                source_name="Our World in Data",
                entry_id=f"{slug}:{row.get('Entity', '')}:{observation_date}",
                raw=dict(row),
            )
        )
        if len(observations) >= limit:
            break
    return observations


def load_manifold_market(
    source: str,
    *,
    api_base_url: str = "https://api.manifold.markets/v0",
) -> ManifoldMarketImport:
    """Load a single Manifold market by URL, API URL, market id, or slug.

    The connector is read-only. It extracts market-implied probabilities as
    baseline comparisons while leaving forecast updates explicit.
    """

    if not source.strip():
        raise ValidationError("manifold import source is required")
    endpoint = _manifold_endpoint_for_source(source.strip(), api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "manifold market")
    if not isinstance(payload, dict):
        raise ValidationError("manifold market response must be a JSON object")
    return _manifold_market_from_payload(payload, source)


def load_manifold_resolved_binary_cases(
    *,
    api_base_url: str = "https://api.manifold.markets/v0",
    limit: int = 100,
) -> list[dict[str, object]]:
    """Load resolved Manifold binary markets as benchmark cases.

    Cases keep Manifold probabilities as external market baselines. They do not
    claim agent skill; they provide a real resolved-question benchmark substrate
    for comparing future agent runs against a market-implied baseline.
    """

    if limit <= 0:
        raise ValidationError("manifold benchmark --limit must be positive")
    query = urlencode(
        {
            "term": "",
            "filter": "resolved",
            "contractType": "BINARY",
            "limit": min(limit, 1000),
        }
    )
    endpoint = f"{api_base_url.rstrip('/')}/search-markets?{query}"
    payload = _read_json_endpoint(endpoint, "manifold resolved markets")
    rows: list[object]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("markets"), list):
        rows = payload["markets"]
    else:
        raise ValidationError("manifold resolved markets response must be a JSON array or object with markets")

    cases: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            market = _manifold_market_from_payload(row, str(row.get("url") or api_base_url))
        except ValidationError:
            continue
        case = _manifold_market_to_benchmark_case(market)
        if case is not None:
            cases.append(case)
        if len(cases) >= limit:
            break
    return cases


def load_metaculus_question(
    source: str,
    *,
    api_base_url: str = "https://www.metaculus.com/api",
) -> MetaculusQuestionImport:
    """Load a Metaculus question as neutral ledger context.

    The adapter extracts question metadata and visible aggregate forecasts as
    baseline comparisons. It never treats the crowd forecast as the agent's own
    probability update.
    """

    if not source.strip():
        raise ValidationError("metaculus import source is required")
    endpoint = _metaculus_endpoint_for_source(source.strip(), api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "metaculus question")
    if not isinstance(payload, dict):
        raise ValidationError("metaculus question response must be a JSON object")
    return _metaculus_question_from_payload(payload, source)


def load_metaculus_resolved_binary_cases(
    *,
    api_base_url: str = "https://www.metaculus.com/api",
    limit: int = 100,
) -> list[dict[str, object]]:
    """Load resolved Metaculus binary questions as benchmark cases."""

    if limit <= 0:
        raise ValidationError("metaculus benchmark --limit must be positive")
    query = urlencode({"status": "resolved", "type": "binary", "limit": min(limit, 1000)})
    endpoint = f"{api_base_url.rstrip('/')}/questions/?{query}"
    payload = _read_json_endpoint(endpoint, "metaculus resolved questions")
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("results") or payload.get("questions") or payload.get("data")
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValidationError("metaculus resolved questions response must be a JSON array or object with results")

    cases: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            question = _metaculus_question_from_payload(row, str(row.get("url") or api_base_url))
        except ValidationError:
            continue
        case = _metaculus_question_to_benchmark_case(question)
        if case is not None:
            cases.append(case)
        if len(cases) >= limit:
            break
    return cases


def _metaculus_question_from_payload(payload: dict, source: str) -> MetaculusQuestionImport:
    question_payload = payload.get("question") if isinstance(payload.get("question"), dict) else payload
    title = str(
        _first_present(
            question_payload.get("title"),
            question_payload.get("question"),
            payload.get("title"),
        )
        or ""
    ).strip()
    if not title:
        raise ValidationError("metaculus question response is missing title")
    choices = _metaculus_choices(question_payload)
    forecast_value = _metaculus_forecast_value(question_payload, choices)
    probability = forecast_value if isinstance(forecast_value, float) else None
    distribution = forecast_value if isinstance(forecast_value, dict) else None
    outcome_space = _metaculus_outcome_space(question_payload, choices, probability, distribution)

    return MetaculusQuestionImport(
        question_id=_optional_str(_first_present(question_payload.get("id"), payload.get("id"))),
        title=title,
        description=_metaculus_description(question_payload, payload),
        resolution_criteria_text=str(
            _first_present(
                question_payload.get("resolution_criteria"),
                question_payload.get("fine_print"),
                question_payload.get("resolution"),
                payload.get("resolution_criteria"),
            )
            or ""
        ).strip(),
        url=_optional_str(payload.get("url")) or _metaculus_public_url(question_payload, payload, source),
        outcome_space=outcome_space,
        probability=probability if outcome_space.type == "binary" else None,
        distribution=distribution if outcome_space.type != "binary" else None,
        close_time=_metaculus_timestamp(
            _first_present(
                question_payload.get("close_time"),
                question_payload.get("scheduled_close_time"),
                question_payload.get("closes_at"),
            )
        ),
        resolution_time=_metaculus_timestamp(
            _first_present(
                question_payload.get("resolve_time"),
                question_payload.get("scheduled_resolve_time"),
                question_payload.get("resolved_at"),
                question_payload.get("actual_resolve_time"),
            )
        ),
        resolution=_optional_str(
            _first_present(
                question_payload.get("resolution"),
                question_payload.get("resolve_value"),
                question_payload.get("actual_resolution"),
            )
        ),
        status=_optional_str(question_payload.get("status")),
        as_of=_metaculus_timestamp(
            _first_present(
                question_payload.get("last_prediction_time"),
                question_payload.get("publish_time"),
                question_payload.get("created_time"),
                payload.get("published_at"),
            )
        ),
        raw=payload,
    )


def load_polymarket_market(
    source: str,
    *,
    api_base_url: str = "https://gamma-api.polymarket.com",
) -> PolymarketMarketImport:
    """Load a single Polymarket Gamma market by URL, API URL, id, or slug."""

    if not source.strip():
        raise ValidationError("polymarket import source is required")
    endpoint = _polymarket_endpoint_for_source(source.strip(), api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "polymarket market")
    if isinstance(payload, list):
        row = next((item for item in payload if isinstance(item, dict)), None)
        if row is None:
            raise ValidationError("polymarket market response did not include any markets")
        payload = row
    elif isinstance(payload, dict) and isinstance(payload.get("markets"), list):
        row = next((item for item in payload["markets"] if isinstance(item, dict)), None)
        if row is None:
            raise ValidationError("polymarket market response did not include any markets")
        payload = row
    if not isinstance(payload, dict):
        raise ValidationError("polymarket market response must be a JSON object or market list")

    question = str(payload.get("question") or payload.get("title") or "").strip()
    if not question:
        raise ValidationError("polymarket market response is missing question")
    outcomes = _polymarket_sequence(payload.get("outcomes"))
    outcome_prices = _polymarket_sequence(payload.get("outcomePrices"))
    distribution = _polymarket_distribution(outcomes, outcome_prices)
    probability = _polymarket_binary_probability(distribution)
    outcome_space = OutcomeSpace(type="binary") if probability is not None else (
        OutcomeSpace(type="categorical", choices=list(distribution.keys())) if len(distribution) >= 2 else OutcomeSpace(type="distribution", choices=[])
    )
    return PolymarketMarketImport(
        market_id=_optional_str(payload.get("id") or payload.get("conditionId")),
        slug=_optional_str(payload.get("slug")),
        question=question,
        description=str(payload.get("description") or "").strip(),
        url=_optional_str(payload.get("url")) or _polymarket_public_url(payload),
        outcome_space=outcome_space,
        probability=probability,
        distribution=None if probability is not None else distribution or None,
        close_time=_polymarket_timestamp(payload.get("endDate") or payload.get("endDateIso") or payload.get("closedTime")),
        resolution_time=_polymarket_timestamp(payload.get("closedTime") or payload.get("resolvedAt")),
        as_of=_polymarket_timestamp(payload.get("updatedAt") or payload.get("createdAt")),
        raw=payload,
    )


def load_kalshi_market(
    source: str,
    *,
    api_base_url: str = "https://external-api.kalshi.com/trade-api/v2",
) -> KalshiMarketImport:
    """Load a single Kalshi market by API URL, UI URL, or ticker."""

    if not source.strip():
        raise ValidationError("kalshi import source is required")
    endpoint = _kalshi_endpoint_for_source(source.strip(), api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "kalshi market")
    if isinstance(payload, dict) and isinstance(payload.get("market"), dict):
        payload = payload["market"]
    elif isinstance(payload, dict) and isinstance(payload.get("markets"), list):
        row = next((item for item in payload["markets"] if isinstance(item, dict)), None)
        if row is None:
            raise ValidationError("kalshi market response did not include any markets")
        payload = row
    if not isinstance(payload, dict):
        raise ValidationError("kalshi market response must be a JSON object or object with market")

    return _kalshi_market_from_payload(payload)


def load_kalshi_resolved_binary_cases(
    *,
    api_base_url: str = "https://external-api.kalshi.com/trade-api/v2",
    limit: int = 100,
) -> list[dict[str, object]]:
    """Load settled Kalshi binary markets as benchmark cases."""

    if limit <= 0:
        raise ValidationError("kalshi benchmark --limit must be positive")
    query = urlencode({"status": "settled", "limit": min(limit, 1000)})
    endpoint = f"{api_base_url.rstrip('/')}/markets?{query}"
    payload = _read_json_endpoint(endpoint, "kalshi settled markets")
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("markets") or payload.get("results") or payload.get("data")
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValidationError("kalshi settled markets response must be a JSON array or object with markets")

    cases: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            market = _kalshi_market_from_payload(row)
        except ValidationError:
            continue
        case = _kalshi_market_to_benchmark_case(market)
        if case is not None:
            cases.append(case)
        if len(cases) >= limit:
            break
    return cases


def _kalshi_market_from_payload(payload: dict) -> KalshiMarketImport:
    question = str(payload.get("title") or payload.get("question") or "").strip()
    if not question:
        raise ValidationError("kalshi market response is missing title")
    ticker = _optional_str(payload.get("ticker"))
    probability = _kalshi_yes_probability(payload)
    return KalshiMarketImport(
        ticker=ticker,
        event_ticker=_optional_str(payload.get("event_ticker")),
        question=question,
        description=_kalshi_description(payload),
        url=_optional_str(payload.get("url")) or _kalshi_public_url(payload),
        outcome_space=OutcomeSpace(type="binary"),
        probability=probability,
        close_time=_kalshi_timestamp(
            _first_present(
                payload.get("close_time"),
                payload.get("expiration_time"),
                payload.get("expected_expiration_time"),
            )
        ),
        resolution_time=_kalshi_timestamp(
            _first_present(
                payload.get("settlement_time"),
                payload.get("expiration_time"),
                payload.get("expected_expiration_time"),
                payload.get("latest_expiration_time"),
            )
        ),
        status=_optional_str(payload.get("status")),
        result=_optional_str(
            _first_present(
                payload.get("result"),
                payload.get("settlement_value"),
                payload.get("settlement_value_dollars"),
                payload.get("yes_settlement_value_dollars"),
            )
        ),
        as_of=_kalshi_timestamp(
            _first_present(
                payload.get("updated_time"),
                payload.get("last_update_time"),
                payload.get("last_update_ts"),
            )
        ),
        raw=payload,
    )


def _manifold_market_from_payload(payload: dict, source: str) -> ManifoldMarketImport:
    question = str(payload.get("question") or "").strip()
    if not question:
        raise ValidationError("manifold market response is missing question")
    outcome_type = str(payload.get("outcomeType") or "BINARY").upper()
    probability = _optional_float(payload.get("probability"))
    distribution = _manifold_distribution(payload)
    outcome_space = _manifold_outcome_space(outcome_type, distribution, payload)
    return ManifoldMarketImport(
        market_id=_optional_str(payload.get("id")),
        slug=_optional_str(payload.get("slug")),
        question=question,
        description=_manifold_description(payload),
        url=_optional_str(payload.get("url")) or source,
        outcome_space=outcome_space,
        probability=probability if outcome_space.type == "binary" else None,
        distribution=distribution,
        close_time=_manifold_ms_to_iso(payload.get("closeTime")),
        resolution_time=_manifold_ms_to_iso(payload.get("resolutionTime")),
        resolution=_optional_str(payload.get("resolution")),
        is_resolved=bool(payload.get("isResolved")),
        as_of=_manifold_ms_to_iso(
            payload.get("lastUpdatedTime")
            or payload.get("lastBetTime")
            or payload.get("closeTime")
            or payload.get("createdTime")
        ),
        raw=payload,
    )


def _manifold_market_to_benchmark_case(market: ManifoldMarketImport) -> dict[str, object] | None:
    if market.outcome_space.type != "binary" or not market.is_resolved:
        return None
    resolution = (market.resolution or "").upper()
    if resolution not in {"YES", "NO"}:
        return None
    baseline = market.baseline_payload()
    if baseline is None:
        return None
    as_of = _manifold_ms_to_iso(market.raw.get("lastBetTime")) or market.close_time or market.as_of
    if not as_of:
        return None
    return {
        "id": f"manifold:{market.market_id or market.slug or market.question}",
        "title": market.question,
        "description": market.description,
        "resolution_criteria": market.resolution_criteria,
        "resolution_source": market.url,
        "as_of": as_of,
        "simulated_forecast_time": as_of,
        "evidence_cutoff": as_of,
        "close_time": market.close_time,
        "resolution_time": market.resolution_time,
        "outcome": "yes" if resolution == "YES" else "no",
        "domain": "prediction_markets",
        "topics": ["manifold"],
        "evidence": [
            {
                "source": market.url or market.baseline_source,
                "source_name": "Manifold",
                "source_type": "adapter:manifold",
                "url": market.url,
                "claim": market.question,
                "summary": market.description,
                "available_at": as_of,
                "claim_type": "estimate",
                "stance": "context",
            }
        ],
        "baselines": [
            {
                "source": "manifold",
                "baseline_type": baseline["baseline_type"],
                "probability": baseline["probability_or_distribution"],
                "as_of": as_of,
            }
        ],
        "notes": (
            "Manifold resolved-market benchmark case. Market probability is "
            "stored as an external baseline, not as an agent forecast."
        ),
    }


def _metaculus_question_to_benchmark_case(question: MetaculusQuestionImport) -> dict[str, object] | None:
    if question.outcome_space.type != "binary":
        return None
    outcome = _metaculus_resolution_to_outcome(question.resolution)
    if outcome is None:
        return None
    baseline = question.baseline_payload()
    if baseline is None:
        return None
    as_of = question.as_of or question.close_time
    if not as_of:
        return None
    return {
        "id": f"metaculus:{question.question_id or question.title}",
        "title": question.title,
        "description": question.description,
        "resolution_criteria": question.resolution_criteria,
        "resolution_source": question.url,
        "as_of": as_of,
        "simulated_forecast_time": as_of,
        "evidence_cutoff": as_of,
        "close_time": question.close_time,
        "resolution_time": question.resolution_time,
        "outcome": outcome,
        "domain": "forecasting_platforms",
        "topics": ["metaculus"],
        "evidence": [
            {
                "source": question.url or question.baseline_source,
                "source_name": "Metaculus",
                "source_type": "adapter:metaculus",
                "url": question.url,
                "claim": question.title,
                "summary": question.description,
                "available_at": as_of,
                "claim_type": "estimate",
                "stance": "context",
            }
        ],
        "baselines": [
            {
                "source": "metaculus",
                "baseline_type": baseline["baseline_type"],
                "probability": baseline["probability_or_distribution"],
                "as_of": as_of,
            }
        ],
        "notes": (
            "Metaculus resolved-question benchmark case. Crowd probability is "
            "stored as an external baseline, not as an agent forecast."
        ),
    }


def _kalshi_market_to_benchmark_case(market: KalshiMarketImport) -> dict[str, object] | None:
    if market.outcome_space.type != "binary":
        return None
    outcome = _kalshi_resolution_to_outcome(market.result)
    if outcome is None:
        return None
    probability = _kalshi_previous_yes_probability(market.raw)
    if probability is None:
        probability = market.probability
    if probability is None:
        return None
    as_of = (
        _kalshi_timestamp(
            _first_present(
                market.raw.get("last_trade_time"),
                market.raw.get("last_trade_ts"),
                market.raw.get("last_price_time"),
            )
        )
        or market.close_time
        or market.as_of
    )
    if not as_of:
        return None
    return {
        "id": f"kalshi:{market.ticker or market.question}",
        "title": market.question,
        "description": market.description,
        "resolution_criteria": market.resolution_criteria,
        "resolution_source": market.url,
        "as_of": as_of,
        "simulated_forecast_time": as_of,
        "evidence_cutoff": as_of,
        "close_time": market.close_time,
        "resolution_time": market.resolution_time,
        "outcome": outcome,
        "domain": "prediction_markets",
        "topics": ["kalshi"],
        "evidence": [
            {
                "source": market.url or market.baseline_source,
                "source_name": "Kalshi",
                "source_type": "adapter:kalshi",
                "url": market.url,
                "claim": market.question,
                "summary": market.description,
                "available_at": as_of,
                "claim_type": "estimate",
                "stance": "context",
            }
        ],
        "baselines": [
            {
                "source": "kalshi",
                "baseline_type": "market",
                "probability": probability,
                "as_of": as_of,
            }
        ],
        "notes": (
            "Kalshi settled-market benchmark case. Market probability is "
            "stored as an external baseline, not as an agent forecast."
        ),
    }


def _metaculus_resolution_to_outcome(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"yes", "true", "1", "1.0", "resolved_yes"}:
        return "yes"
    if normalized in {"no", "false", "0", "0.0", "resolved_no"}:
        return "no"
    return None


def _kalshi_resolution_to_outcome(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"yes", "true"}:
        return "yes"
    if normalized in {"no", "false"}:
        return "no"
    numeric = _optional_float(normalized)
    if numeric is None:
        return None
    if numeric >= 0.999:
        return "yes"
    if numeric <= 0.001:
        return "no"
    return None


def _read_feed_source(source: str) -> bytes:
    if source.startswith(("http://", "https://")):
        parsed = urlparse(source)
        if not parsed.netloc:
            raise ValidationError("news feed URL is invalid")
        request = Request(source, headers={"User-Agent": "superforecasting-agent/news-feed"})
        with urlopen(request, timeout=10) as response:
            return response.read(2 * 1024 * 1024)
    path = Path(source).expanduser()
    if not path.is_file():
        raise ValidationError(f"news feed source not found: {source}")
    return path.read_bytes()


def _read_json_endpoint(url: str, label: str) -> object:
    try:
        request = Request(url, headers={"User-Agent": "superforecasting-agent/source-adapter"})
        with urlopen(request, timeout=10) as response:
            data = response.read(2 * 1024 * 1024)
    except OSError as exc:
        raise ValidationError(f"{label} fetch failed: {exc}") from exc
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{label} response is not valid JSON") from exc


def _read_text_endpoint(url: str, label: str) -> str:
    try:
        request = Request(url, headers={"User-Agent": "superforecasting-agent/source-adapter"})
        with urlopen(request, timeout=10) as response:
            data = response.read(2 * 1024 * 1024)
    except OSError as exc:
        raise ValidationError(f"{label} fetch failed: {exc}") from exc
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{label} response is not valid UTF-8 text") from exc


def _gdelt_augmented_query(query: str, *, source_country: str | None, source_lang: str | None) -> str:
    parts = [query.strip()]
    if source_country:
        parts.append(f"sourcecountry:{_gdelt_query_operator_value(source_country)}")
    if source_lang:
        parts.append(f"sourcelang:{_gdelt_query_operator_value(source_lang)}")
    return " ".join(part for part in parts if part)


def _gdelt_query_operator_value(value: str) -> str:
    return "".join(str(value).strip().lower().split())


def _gdelt_datetime_parameter(value: str) -> str:
    parsed = timestamp_to_datetime(value)
    if parsed is None:
        raise ValidationError("gdelt timestamp cannot be empty")
    return parsed.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def _gdelt_timestamp(value: object) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    try:
        if len(raw) == 14 and raw.isdigit():
            from datetime import datetime

            parsed = datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if len(raw) == 16 and raw.endswith("Z") and raw[8] == "T":
            from datetime import datetime

            parsed = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return parse_timestamp(raw, field_name="gdelt timestamp")
    except (ValueError, ValidationError):
        return None


def _fivethirtyeight_poll_endpoint(source: str, *, api_base_url: str) -> tuple[str, str]:
    raw = source.strip()
    if raw.startswith(("fivethirtyeight:", "538:")):
        raw = raw.split(":", 1)[1].strip()
    if not raw:
        return "", ""
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        dataset = Path(unquote(parsed.path)).name.removesuffix(".csv") or "polls"
        return dataset, raw

    aliases = {
        "president": "president_polls",
        "presidential": "president_polls",
        "president-polls": "president_polls",
        "senate": "senate_polls",
        "senate-polls": "senate_polls",
        "house": "house_polls",
        "house-polls": "house_polls",
        "governor": "governor_polls",
        "governor-polls": "governor_polls",
        "approval": "president_approval_polls",
        "president-approval": "president_approval_polls",
        "president-approval-polls": "president_approval_polls",
        "generic": "generic_ballot_polls",
        "generic-ballot": "generic_ballot_polls",
        "generic-ballot-polls": "generic_ballot_polls",
    }
    dataset = aliases.get(raw.strip().lower().removesuffix(".csv"), raw.strip().removesuffix(".csv"))
    if not dataset or any(character.isspace() for character in dataset) or "/" in dataset:
        raise ValidationError("fivethirtyeight source must be a dataset alias, dataset name, or CSV URL")
    base = api_base_url.strip()
    if not base:
        raise ValidationError("fivethirtyeight import --api-base-url cannot be empty")
    if "{dataset}" in base:
        return dataset, base.replace("{dataset}", quote(dataset, safe="_-."))
    if base.endswith(".csv"):
        return dataset, base
    return dataset, f"{base.rstrip('/')}/{quote(dataset, safe='_-')}.csv"


def _fivethirtyeight_date(value: object) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            from datetime import datetime

            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        parsed = parse_timestamp(raw, field_name="fivethirtyeight date")
    except ValidationError:
        return None
    parsed_dt = timestamp_to_datetime(parsed)
    return parsed_dt.date().isoformat() if parsed_dt is not None else None


def _fivethirtyeight_timestamp(value: object) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parsed_date = _fivethirtyeight_date(raw)
    if parsed_date and len(raw) <= 10:
        return f"{parsed_date}T00:00:00Z"
    try:
        return parse_timestamp(raw, field_name="fivethirtyeight timestamp")
    except ValidationError:
        return f"{parsed_date}T00:00:00Z" if parsed_date else None


def _fivethirtyeight_sample_size(value: object) -> float | int | None:
    number = _optional_float(value)
    if number is None:
        return None
    return int(number) if number.is_integer() else number


def _fred_date(value: str | None, *, field_name: str):
    if value in (None, ""):
        return None
    from datetime import date

    raw = str(value).strip()
    if not raw:
        return None
    try:
        if "T" not in raw and len(raw) == 10:
            return date.fromisoformat(raw)
        timestamp = parse_timestamp(raw, field_name=field_name)
        parsed = timestamp_to_datetime(timestamp)
        return parsed.date() if parsed is not None else None
    except (ValueError, ValidationError) as exc:
        raise ValidationError(f"{field_name} must be an ISO-8601 date or timestamp") from exc


def _fred_date_to_iso(value) -> str:
    from datetime import datetime

    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _fred_date_column(fieldnames: list[str]) -> str:
    for field in fieldnames:
        if field.strip().lower() in {"date", "observation_date"}:
            return field
    return fieldnames[0]


def _fred_value_column(fieldnames: list[str], series_id: str, date_key: str) -> str:
    lowered_series = series_id.strip().lower()
    for field in fieldnames:
        if field != date_key and field.strip().lower() == lowered_series:
            return field
    for field in fieldnames:
        if field != date_key:
            return field
    raise ValidationError("fred observations CSV has no value column")


def _eia_endpoint(source: str, *, api_base_url: str) -> tuple[str, str]:
    raw = source.strip()
    if not raw:
        return "", ""
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        series_id = (
            params.get("series_id")
            or params.get("seriesId")
            or params.get("series")
            or Path(unquote(parsed.path)).name
        )
        return str(series_id or raw), raw
    series_id = raw.split(":", 1)[1].strip() if raw.startswith("eia:") else raw
    base = api_base_url.strip()
    if not base:
        raise ValidationError("eia import --api-base-url cannot be empty")
    if "{series_id}" in base:
        return series_id, base.replace("{series_id}", quote(series_id, safe=""))
    separator = "&" if "?" in base else "?"
    return series_id, f"{base.rstrip('?&')}{separator}{urlencode({'series_id': series_id})}"


def _eia_observations_from_payload(payload: object, *, series_id: str, endpoint: str) -> list[EiaObservation]:
    if not isinstance(payload, dict):
        raise ValidationError("eia observations response must be a JSON object")
    rows: list[dict[str, object]] = []
    series_name: str | None = None
    unit: str | None = None
    response = payload.get("response")
    if isinstance(response, dict) and isinstance(response.get("data"), list):
        rows = [row for row in response["data"] if isinstance(row, dict)]
        series_name = _optional_str(
            _first_present(
                payload.get("name"),
                response.get("series-description"),
                response.get("seriesDescription"),
                response.get("description"),
            )
        )
    elif isinstance(payload.get("data"), list):
        rows = [row for row in payload["data"] if isinstance(row, dict)]
        series_name = _optional_str(_first_present(payload.get("name"), payload.get("description")))
    elif isinstance(payload.get("series"), list):
        series_rows = [row for row in payload["series"] if isinstance(row, dict)]
        rows = _eia_legacy_series_rows(series_rows, series_id=series_id)
        if series_rows:
            series_name = _optional_str(series_rows[0].get("name"))
            unit = _optional_str(series_rows[0].get("units"))
    else:
        raise ValidationError("eia observations response must contain response.data, data, or series")

    observations: list[EiaObservation] = []
    for index, row in enumerate(rows):
        row_series_id = _optional_str(_first_present(row.get("series_id"), row.get("seriesId"), row.get("series"))) or series_id
        period = _optional_str(_first_present(row.get("period"), row.get("date"), row.get("timestamp")))
        if not period:
            continue
        published_at = _eia_period_to_iso(period)
        if not published_at:
            continue
        raw_value = _first_present(row.get("value"), row.get("price"), row.get("generation"), row.get("consumption"))
        if raw_value in (None, ""):
            continue
        value = _optional_float(raw_value)
        row_unit = _optional_str(
            _first_present(row.get("units"), row.get("unit"), row.get("value-units"), row.get("value_units"))
        )
        row_series_name = _optional_str(
            _first_present(
                row.get("series-description"),
                row.get("seriesDescription"),
                row.get("series_name"),
                row.get("name"),
            )
        )
        observations.append(
            EiaObservation(
                series_id=row_series_id,
                series_name=row_series_name or series_name,
                observation_period=str(period),
                value=value if value is not None else str(raw_value),
                unit=row_unit or unit,
                published_at=published_at,
                source_url=endpoint,
                source_name="EIA",
                entry_id=f"{row_series_id}:{period}",
                raw={"row_index": index, **dict(row)},
            )
        )
    return observations


def _eia_legacy_series_rows(series_rows: list[dict[str, object]], *, series_id: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for series in series_rows:
        row_series_id = _optional_str(series.get("series_id")) or series_id
        unit = _optional_str(series.get("units"))
        name = _optional_str(series.get("name"))
        data_rows = series.get("data")
        if not isinstance(data_rows, list):
            continue
        for item in data_rows:
            if isinstance(item, list) and len(item) >= 2:
                rows.append(
                    {
                        "series_id": row_series_id,
                        "period": item[0],
                        "value": item[1],
                        "units": unit,
                        "name": name,
                    }
                )
    return rows


def _treasury_endpoint(source: str, *, api_base_url: str, date_field: str, limit: int) -> tuple[str, str]:
    raw = source.strip()
    if not raw:
        return "", ""
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        dataset = unquote(parsed.path).split("/fiscal_service/", 1)[-1].strip("/") or Path(unquote(parsed.path)).name
        return dataset or raw, raw
    dataset = raw.split(":", 1)[1].strip() if raw.startswith("treasury:") else raw
    base = api_base_url.strip()
    if not base:
        raise ValidationError("treasury import --api-base-url cannot be empty")
    if "{dataset}" in base:
        endpoint = base.replace("{dataset}", quote(dataset, safe="/?:=&[]-,"))
    else:
        endpoint = f"{base.rstrip('/')}/{dataset.lstrip('/')}"
    parsed = urlparse(endpoint)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    additions: dict[str, str] = {}
    if "page[size]" not in params and "page%5Bsize%5D" not in parsed.query:
        additions["page[size]"] = str(limit)
    if "sort" not in params and date_field:
        additions["sort"] = f"-{date_field}"
    if additions:
        separator = "&" if parsed.query else "?"
        endpoint = f"{endpoint}{separator}{urlencode(additions)}"
    return dataset, endpoint


def _treasury_records_from_payload(
    payload: object,
    *,
    dataset: str,
    endpoint: str,
    date_field: str,
    value_field: str | None,
) -> list[TreasuryRecord]:
    if not isinstance(payload, dict):
        raise ValidationError("treasury fiscal data response must be a JSON object")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValidationError("treasury fiscal data response must contain data rows")
    meta = payload.get("meta")
    labels = meta.get("labels") if isinstance(meta, dict) and isinstance(meta.get("labels"), dict) else {}
    records: list[TreasuryRecord] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        raw_date = _first_present(
            row.get(date_field),
            row.get("record_date"),
            row.get("effective_date"),
            row.get("auction_date"),
            row.get("reporting_date"),
            row.get("calendar_date"),
        )
        record_date = _optional_str(raw_date)
        if not record_date:
            continue
        published_at = _treasury_date_to_iso(record_date)
        if not published_at:
            continue
        selected_field, raw_value = _treasury_value(row, date_field=date_field, value_field=value_field)
        value = _optional_float(raw_value) if raw_value is not None else None
        label = _optional_str(labels.get(selected_field)) if selected_field and isinstance(labels, dict) else None
        records.append(
            TreasuryRecord(
                dataset=dataset,
                record_date=record_date,
                value=value if value is not None else (_optional_str(raw_value) if raw_value is not None else None),
                value_field=selected_field,
                value_label=label,
                published_at=published_at,
                source_url=endpoint,
                source_name="U.S. Treasury Fiscal Data",
                entry_id=f"{dataset}:{record_date}:{index}",
                raw={"row_index": index, "labels": dict(labels) if isinstance(labels, dict) else {}, **dict(row)},
            )
        )
    return records


def _treasury_value(row: dict[str, object], *, date_field: str, value_field: str | None) -> tuple[str | None, object | None]:
    if value_field:
        return value_field, row.get(value_field)
    ignored = {date_field, "record_date", "effective_date", "auction_date", "reporting_date", "calendar_date"}
    for key, value in row.items():
        if key in ignored or value in (None, ""):
            continue
        if _optional_float(value) is not None:
            return str(key), value
    for key, value in row.items():
        if key not in ignored and value not in (None, ""):
            return str(key), value
    return None, None


def _treasury_date_to_iso(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = parse_timestamp(raw, field_name="treasury date")
    except ValidationError:
        return None
    return parsed


def _eia_period_to_iso(value: str) -> str | None:
    raw = str(value).strip()
    if not raw:
        return None
    if len(raw) == 4 and raw.isdigit():
        return f"{raw}-01-01T00:00:00Z"
    if len(raw) == 6 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:]}-01T00:00:00Z"
    if len(raw) == 7 and raw[4] == "-" and raw[:4].isdigit() and raw[5:].isdigit():
        return f"{raw}-01T00:00:00Z"
    upper = raw.upper()
    if len(upper) == 6 and upper[:4].isdigit() and upper[4] == "Q" and upper[5] in "1234":
        month = {"1": "01", "2": "04", "3": "07", "4": "10"}[upper[5]]
        return f"{upper[:4]}-{month}-01T00:00:00Z"
    try:
        timestamp = parse_timestamp(raw, field_name="eia period")
        parsed = timestamp_to_datetime(timestamp)
        if parsed is None:
            return None
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValidationError:
        return None



def _bls_endpoint(
    series_id: str,
    *,
    api_base_url: str,
    start_year: int | None,
    end_year: int | None,
) -> str:
    endpoint_base = api_base_url.rstrip("/")
    if endpoint_base.endswith(f"/{quote(series_id)}"):
        endpoint = endpoint_base
    else:
        endpoint = f"{endpoint_base}/{quote(series_id)}"
    params: dict[str, int] = {}
    if start_year is not None:
        params["startyear"] = start_year
    if end_year is not None:
        params["endyear"] = end_year
    if params:
        endpoint = f"{endpoint}?{urlencode(params)}"
    return endpoint


def _bls_observation_date(year: str, period: str):
    from datetime import date

    if not year.isdigit():
        return None
    year_int = int(year)
    normalized_period = period.strip().upper()
    if len(normalized_period) == 3 and normalized_period.startswith("M") and normalized_period[1:].isdigit():
        month = int(normalized_period[1:])
        if 1 <= month <= 12:
            return date(year_int, month, 1)
        if month == 13:
            return date(year_int, 12, 31)
    if len(normalized_period) == 3 and normalized_period.startswith("Q") and normalized_period[1:].isdigit():
        quarter = int(normalized_period[1:])
        if 1 <= quarter <= 4:
            return date(year_int, 1 + (quarter - 1) * 3, 1)
    if normalized_period in {"A01", "Y01"}:
        return date(year_int, 12, 31)
    return None


def _worldbank_source_parts(source: str) -> tuple[str, str]:
    raw = source.strip()
    if raw.startswith("worldbank:"):
        raw = raw.split(":", 1)[1].strip()
    if "/" in raw:
        country, indicator = raw.split("/", 1)
    elif ":" in raw:
        country, indicator = raw.split(":", 1)
    else:
        raise ValidationError("worldbank source must be COUNTRY/INDICATOR, e.g. USA/NY.GDP.MKTP.CD")
    country = country.strip()
    indicator = indicator.strip()
    if not country or not indicator:
        raise ValidationError("worldbank source must include both country and indicator")
    return country, indicator


def _worldbank_endpoint(country: str, indicator: str, *, api_base_url: str, per_page: int) -> str:
    endpoint_base = api_base_url.rstrip("/")
    endpoint = f"{endpoint_base}/country/{quote(country)}/indicator/{quote(indicator)}"
    return f"{endpoint}?{urlencode({'format': 'json', 'per_page': per_page})}"


def _worldbank_since_date(value: str | None):
    if value in (None, ""):
        return None
    from datetime import date

    raw = str(value).strip()
    if len(raw) == 4 and raw.isdigit():
        return date(int(raw), 1, 1)
    return _fred_date(raw, field_name="since")


def _worldbank_observation_date(year: str):
    if len(year) != 4 or not year.isdigit():
        return None
    from datetime import date

    return date(int(year), 12, 31)


def _census_endpoint(source: str, *, api_base_url: str, api_key: str | None) -> tuple[str, str]:
    raw = source.strip()
    if raw.startswith("census:"):
        raw = raw.split(":", 1)[1].strip()
    if not raw:
        return "", ""

    effective_key = api_key or os.getenv("CENSUS_API_KEY")
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        dataset = _census_dataset_from_path(unquote(parsed.path))
        params = parse_qsl(parsed.query, keep_blank_values=True)
        endpoint = raw.split("?", 1)[0]
    else:
        if "?" not in raw:
            raise ValidationError(
                "census source must be DATASET?get=...&for=..., "
                "e.g. 2023/acs/acs5?get=NAME,B01003_001E&for=state:*"
            )
        dataset_part, query = raw.split("?", 1)
        dataset = dataset_part.strip("/")
        if not dataset:
            raise ValidationError("census source must include a dataset path")
        base = api_base_url.strip()
        if not base:
            raise ValidationError("census import --api-base-url cannot be empty")
        endpoint = f"{base.rstrip('/')}/{quote(dataset, safe='/')}"
        params = parse_qsl(query, keep_blank_values=True)

    param_names = {name for name, _ in params}
    if "get" not in param_names or "for" not in param_names:
        raise ValidationError("census source query must include get=... and for=... parameters")
    if "key" not in param_names and effective_key:
        params.append(("key", effective_key))
    if "key" not in {name for name, _ in params} and _census_requires_api_key(endpoint):
        raise ValidationError("census import requires CENSUS_API_KEY for api.census.gov requests")
    return dataset, f"{endpoint}?{urlencode(params)}"


def _census_dataset_from_path(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    if "data" in parts:
        index = parts.index("data")
        dataset = "/".join(parts[index + 1 :])
        if dataset:
            return dataset
    return "/".join(parts)


def _census_requires_api_key(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    return parsed.netloc.lower() == "api.census.gov"


def _census_records_from_payload(payload: object, *, dataset: str, endpoint: str) -> list[CensusRecord]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise ValidationError("census data response must be a two-dimensional array with a header row")
    headers = [str(header) for header in payload[0]]
    if not headers:
        raise ValidationError("census data response has an empty header row")
    dataset_year = _census_dataset_year(dataset)
    observation_date = f"{dataset_year}-12-31" if dataset_year is not None else None
    published_at = f"{observation_date}T00:00:00Z" if observation_date else None
    source_url = _census_public_source_url(endpoint)
    records: list[CensusRecord] = []
    for index, raw_row in enumerate(payload[1:]):
        if not isinstance(raw_row, list):
            continue
        row = {header: raw_row[position] if position < len(raw_row) else None for position, header in enumerate(headers)}
        geography = {
            key: str(value)
            for key, value in row.items()
            if value not in (None, "") and _census_is_geography_header(key)
        }
        values = {
            key: _census_value(value)
            for key, value in row.items()
            if value not in (None, "") and key not in geography
        }
        if not values and not geography:
            continue
        records.append(
            CensusRecord(
                dataset=dataset,
                dataset_year=dataset_year,
                observation_date=observation_date,
                values=values,
                geography=geography,
                published_at=published_at,
                source_url=source_url,
                source_name="U.S. Census Bureau",
                entry_id=f"{dataset}:{observation_date or 'unknown'}:{index}",
                raw={"row_index": index, "headers": headers, "row": row},
            )
        )
    return records


def _census_public_source_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if not parsed.query:
        return endpoint
    params = [(name, value) for name, value in parse_qsl(parsed.query, keep_blank_values=True) if name.lower() != "key"]
    return parsed._replace(query=urlencode(params)).geturl()


def _census_dataset_year(dataset: str) -> int | None:
    for part in dataset.split("/"):
        if len(part) == 4 and part.isdigit():
            year = int(part)
            if 1900 <= year <= 2200:
                return year
    return None


def _census_is_geography_header(header: str) -> bool:
    normalized = header.strip().lower()
    if not normalized or normalized == "name":
        return False
    if normalized.startswith("ucgid"):
        return True
    if normalized in {
        "us",
        "region",
        "division",
        "state",
        "county",
        "county subdivision",
        "tract",
        "block group",
        "block",
        "place",
        "zip code tabulation area",
        "metropolitan statistical area/micropolitan statistical area",
        "congressional district",
        "school district (elementary)",
        "school district (secondary)",
        "school district (unified)",
    }:
        return True
    return normalized == header and not any(character.isdigit() for character in normalized)


def _census_value(value: object) -> float | str:
    text = str(value).strip()
    number = _optional_float(text)
    if number is None:
        return text
    return number


def _socrata_endpoint(source: str, *, api_base_url: str, limit: int) -> tuple[str, str, str]:
    raw = source.split(":", 1)[1].strip() if source.startswith("socrata:") else source.strip()
    if not raw:
        raise ValidationError("socrata source must include a portal domain and dataset id")

    parsed = urlparse(raw)
    query_pairs: list[tuple[str, str]]
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        domain = parsed.netloc
        dataset_id = _socrata_dataset_id_from_path(parsed.path)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        endpoint_base = f"{parsed.scheme}://{domain}/resource/{quote(dataset_id, safe='')}.json"
    else:
        path, query = raw.split("?", 1) if "?" in raw else (raw, "")
        parts = [part for part in path.strip("/").split("/") if part]
        if len(parts) < 2:
            raise ValidationError("socrata source must be domain/dataset-id or a Socrata API URL")
        domain = parts[0]
        dataset_id = parts[-1].removesuffix(".json")
        query_pairs = parse_qsl(query, keep_blank_values=True)
        base = api_base_url.strip()
        if not base:
            raise ValidationError("socrata import --api-base-url cannot be empty")
        if "{domain}" in base or "{dataset_id}" in base:
            endpoint_base = base.format(
                domain=quote(domain, safe=".:-"),
                dataset_id=quote(dataset_id, safe=""),
            )
        elif base.endswith(".json"):
            endpoint_base = base
        else:
            endpoint_base = f"{base.rstrip('/')}/resource/{quote(dataset_id, safe='')}.json"

    if not domain or not dataset_id:
        raise ValidationError("socrata source must include a portal domain and dataset id")
    if "$limit" not in {name for name, _ in query_pairs}:
        query_pairs.append(("$limit", str(min(limit, 50000))))
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(query_pairs)}" if query_pairs else endpoint_base
    return domain, dataset_id, endpoint


def _socrata_dataset_id_from_path(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    if "resource" in parts:
        index = parts.index("resource")
        if index + 1 < len(parts):
            return parts[index + 1].removesuffix(".json")
    if "views" in parts:
        index = parts.index("views")
        if index + 1 < len(parts):
            return parts[index + 1].removesuffix(".json")
    if parts:
        return parts[-1].removesuffix(".json")
    raise ValidationError("socrata API URL must include a dataset id")


def _socrata_public_source_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    params = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if name not in {"$$app_token", "$limit"}
    ]
    return parsed._replace(query=urlencode(params)).geturl()


def _socrata_timestamp(value: object) -> str | None:
    if isinstance(value, (int, float)) and value > 0:
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(number, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="socrata timestamp")
    except ValidationError:
        return None


def _yahoo_symbol(source: str) -> str:
    value = source.split(":", 1)[1].strip() if source.startswith("yahoo:") else source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if "quote" in parts:
            index = parts.index("quote")
            value = parts[index + 1] if index + 1 < len(parts) else ""
        elif parts:
            value = parts[-1]
    symbol = value.strip().upper()
    if not symbol:
        raise ValidationError("yahoo source must be a symbol, yahoo:<symbol>, or Yahoo Finance quote URL")
    if any(character.isspace() for character in symbol) or "/" in symbol:
        raise ValidationError("yahoo symbols cannot contain whitespace or slashes")
    return symbol


def _yahoo_interval(value: str | None) -> str:
    interval = (value or "1d").strip().lower()
    allowed = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}
    if interval not in allowed:
        raise ValidationError("yahoo import --interval must be a Yahoo Finance chart interval")
    return interval


def _yahoo_range(value: str | None) -> str:
    range_value = (value or "1mo").strip().lower()
    allowed = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
    if range_value not in allowed:
        raise ValidationError("yahoo import --range must be a Yahoo Finance chart range")
    return range_value


def _yahoo_chart_endpoint(symbol: str, *, range_value: str, interval: str, api_base_url: str) -> str:
    base = api_base_url.strip()
    if not base:
        raise ValidationError("yahoo import --api-base-url cannot be empty")
    if "{symbol}" in base:
        endpoint = base.replace("{symbol}", quote(symbol, safe="=^.-"))
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}{urlencode({'range': range_value, 'interval': interval})}"
    endpoint = f"{base.rstrip('/')}/{quote(symbol, safe='=^.-')}"
    return f"{endpoint}?{urlencode({'range': range_value, 'interval': interval})}"


def _yahoo_chart_result(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("yahoo finance chart response must be a JSON object")
    chart = payload.get("chart") if isinstance(payload.get("chart"), dict) else {}
    error = chart.get("error")
    if error:
        raise ValidationError(f"yahoo finance chart request failed: {error}")
    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ValidationError("yahoo finance chart response must include chart.result")
    return results[0]


def _yahoo_series(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _yahoo_timestamp(value: object) -> str | None:
    number = _optional_float(value)
    if number is None:
        return None
    return datetime.fromtimestamp(number, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _yahoo_optional_number(value: object) -> float | int | str | None:
    number = _optional_float(value)
    if number is not None:
        if number.is_integer():
            return int(number)
        return number
    return _optional_str(value)


def _stooq_interval(value: str | None) -> str:
    interval = (value or "d").strip().lower()
    if interval not in {"d", "w", "m"}:
        raise ValidationError("stooq import --interval must be one of d, w, or m")
    return interval


def _stooq_endpoint(source: str, *, interval: str, api_base_url: str) -> tuple[str, str, str]:
    raw = source.strip()
    if raw.startswith("stooq:"):
        raw = raw.split(":", 1)[1].strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        symbol = str(params.get("s") or Path(unquote(parsed.path)).stem or raw).strip()
        effective_interval = _stooq_interval(str(params.get("i") or interval))
        return symbol or raw, effective_interval, raw
    symbol = raw
    base = api_base_url.strip()
    if not base:
        raise ValidationError("stooq import --api-base-url cannot be empty")
    if "{symbol}" in base or "{interval}" in base:
        endpoint = base.replace("{symbol}", quote(symbol, safe="")).replace("{interval}", quote(interval, safe=""))
        return symbol, interval, endpoint
    endpoint_base = base.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode({'s': symbol.lower(), 'i': interval})}"
    return symbol, interval, endpoint


def _stooq_column(fieldnames: list[str], name: str, *, required: bool = True) -> str | None:
    for field in fieldnames:
        if field.strip().lower() == name:
            return field
    if required:
        raise ValidationError(f"stooq prices CSV has no {name} column")
    return None


def _stooq_optional_number(value: object) -> float | int | str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if raw in {"", "-", "."}:
        return None
    number = _optional_float(raw)
    if number is None:
        return raw
    if number.is_integer():
        return int(number)
    return number


def _sec_cik(source: str) -> str:
    raw = source.strip()
    if raw.startswith("sec:"):
        raw = raw.split(":", 1)[1].strip()
    if raw.upper().startswith("CIK"):
        raw = raw[3:]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise ValidationError("sec source must be a numeric CIK, e.g. 0000320193")
    return digits.zfill(10)


def _sec_submissions_endpoint(cik: str, *, api_base_url: str) -> str:
    return f"{api_base_url.rstrip('/')}/CIK{cik}.json"


def _sec_company_fact_query(
    source: str,
    *,
    concept: str | None,
    taxonomy: str,
) -> tuple[str, str, str]:
    raw = source.strip()
    if raw.startswith("secfacts:"):
        raw = raw.split(":", 1)[1].strip()
    raw = raw.strip("/")
    if not raw:
        raise ValidationError("secfacts source must include a CIK and concept")

    provided_concept = concept.strip() if concept and concept.strip() else None
    provided_taxonomy = taxonomy.strip() if taxonomy and taxonomy.strip() else "us-gaap"
    cik_part = raw
    source_concept: str | None = None
    source_taxonomy: str | None = None

    if "/" in raw:
        parts = [unquote(part).strip() for part in raw.split("/") if part.strip()]
        if len(parts) >= 3:
            cik_part = parts[0]
            source_taxonomy = parts[1]
            source_concept = parts[2]
        elif len(parts) == 2:
            cik_part, source_concept = parts
        else:
            cik_part = parts[0]
    elif ":" in raw:
        cik_part, source_concept = (part.strip() for part in raw.split(":", 1))

    effective_concept = provided_concept or source_concept
    if not effective_concept:
        raise ValidationError(
            "secfacts source must include a concept, e.g. 0000320193/Revenues or --concept Revenues"
        )
    effective_taxonomy = source_taxonomy or provided_taxonomy
    return _sec_cik(cik_part), effective_taxonomy, effective_concept


def _sec_company_fact_unit_rows(units: dict, *, unit: str | None) -> tuple[str, list]:
    requested_unit = unit.strip() if unit and unit.strip() else None
    if requested_unit:
        rows = units.get(requested_unit)
        if not isinstance(rows, list):
            raise ValidationError(f"sec company facts concept has no {requested_unit} unit rows")
        return requested_unit, rows

    for candidate in ("USD", "shares", "pure"):
        rows = units.get(candidate)
        if isinstance(rows, list):
            return candidate, rows
    for candidate in sorted(str(key) for key in units):
        rows = units.get(candidate)
        if isinstance(rows, list):
            return candidate, rows
    raise ValidationError("sec company facts concept has no list-valued unit rows")


def _sec_company_fact_filed_at(value: str | None) -> str | None:
    filed = _fred_date(value, field_name="sec company fact filed")
    return _fred_date_to_iso(filed) if filed is not None else None


def _sec_company_fact_fiscal_year(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sec_company_fact_value(value: object) -> float | int | str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int | float):
        return value
    parsed = _optional_float(value)
    if parsed is None:
        text = _optional_str(value)
        return text if text is not None else ""
    if parsed.is_integer():
        return int(parsed)
    return parsed


def _sec_filing_timestamp(acceptance_time: str | None, filing_date: str) -> str:
    if acceptance_time:
        try:
            return parse_timestamp(acceptance_time, field_name="sec acceptanceDateTime") or _fred_date_to_iso(
                _fred_date(filing_date, field_name="sec filingDate")
            )
        except ValidationError:
            pass
    filing = _fred_date(filing_date, field_name="sec filingDate")
    if filing is None:
        raise ValidationError("sec filingDate must be an ISO-8601 date")
    return _fred_date_to_iso(filing)


def _sec_filing_url(cik: str, accession_number: str, primary_document: str | None) -> str | None:
    if not primary_document:
        return None
    accession_path = accession_number.replace("-", "")
    cik_path = str(int(cik))
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_path}/{quote(primary_document)}"


def _sec_recent_row(recent: dict, index: int) -> dict:
    row: dict[str, object] = {}
    for key, value in recent.items():
        if isinstance(value, list):
            row[key] = _list_get(value, index)
    return row


def _list_get(values: list, index: int) -> object:
    return values[index] if 0 <= index < len(values) else None


def _manifold_endpoint_for_source(source: str, *, api_base_url: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc == "api.manifold.markets":
            return source
        if parsed.netloc.endswith("manifold.markets"):
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2:
                slug = parts[-1]
                return f"{api_base_url.rstrip('/')}/slug/{quote(slug)}"
            raise ValidationError("manifold market URL must include a market slug")
        return source
    if source.startswith("id:"):
        market_id = source.split(":", 1)[1].strip()
        if not market_id:
            raise ValidationError("manifold market id is empty")
        return f"{api_base_url.rstrip('/')}/market/{quote(market_id)}"
    if source.startswith("slug:"):
        slug = source.split(":", 1)[1].strip()
    else:
        slug = source
    if not slug:
        raise ValidationError("manifold market slug is empty")
    return f"{api_base_url.rstrip('/')}/slug/{quote(slug)}"


def _metaculus_endpoint_for_source(source: str, *, api_base_url: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc.endswith("metaculus.com"):
            if parsed.path.startswith(("/api/", "/api2/")):
                return source
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0] == "questions":
                return f"{api_base_url.rstrip('/')}/questions/{quote(parts[1])}/"
            raise ValidationError("metaculus URL must include a question id")
        return source
    question_id = source.removeprefix("id:").strip()
    if not question_id:
        raise ValidationError("metaculus question id is empty")
    return f"{api_base_url.rstrip('/')}/questions/{quote(question_id)}/"


def _polymarket_endpoint_for_source(source: str, *, api_base_url: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc == "gamma-api.polymarket.com":
            return source
        if parsed.netloc.endswith("polymarket.com"):
            parts = [part for part in parsed.path.split("/") if part]
            if not parts:
                raise ValidationError("polymarket URL must include a market or event slug")
            slug = parts[-1]
            return f"{api_base_url.rstrip('/')}/markets?{urlencode({'slug': slug})}"
        return source
    if source.startswith("id:"):
        market_id = source.split(":", 1)[1].strip()
        if not market_id:
            raise ValidationError("polymarket market id is empty")
        return f"{api_base_url.rstrip('/')}/markets?{urlencode({'id': market_id})}"
    slug = source.removeprefix("slug:").strip()
    if not slug:
        raise ValidationError("polymarket market slug is empty")
    return f"{api_base_url.rstrip('/')}/markets?{urlencode({'slug': slug})}"


def _metaculus_choices(payload: dict) -> list[str]:
    for key in ("possibilities", "options", "choices"):
        value = payload.get(key)
        if isinstance(value, dict):
            choices = [str(item).strip() for item in value.values() if str(item).strip()]
            if choices:
                return choices
        if isinstance(value, list):
            choices: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    text = _first_present(item.get("label"), item.get("name"), item.get("title"), item.get("text"))
                else:
                    text = item
                if text is not None and str(text).strip():
                    choices.append(str(text).strip())
            if choices:
                return choices
    return []


def _metaculus_forecast_value(payload: dict, choices: list[str]) -> float | dict[str, float] | None:
    candidates: list[object] = [
        payload.get("community_prediction"),
        payload.get("community_prediction_stats"),
        payload.get("prediction"),
    ]
    aggregations = payload.get("aggregations")
    if isinstance(aggregations, dict):
        for key in ("recency_weighted", "community", "unweighted", "metaculus_prediction"):
            candidates.append(aggregations.get(key))
    for candidate in candidates:
        value = _metaculus_extract_prediction_value(candidate, choices)
        if value is not None:
            return value
    return None


def _metaculus_extract_prediction_value(value: object, choices: list[str]) -> float | dict[str, float] | None:
    probability = _optional_float(value)
    if probability is not None and 0 <= probability <= 1:
        return probability
    if isinstance(value, list):
        probabilities = [_optional_float(item) for item in value]
        probabilities = [item for item in probabilities if item is not None]
        if len(probabilities) == 1 and 0 <= probabilities[0] <= 1:
            return probabilities[0]
        if choices and len(probabilities) >= len(choices):
            return {choice: probabilities[index] for index, choice in enumerate(choices)}
        return None
    if not isinstance(value, dict):
        return None
    for key in ("latest", "full", "center", "centers", "forecast_values"):
        if key in value:
            extracted = _metaculus_extract_prediction_value(value.get(key), choices)
            if extracted is not None:
                return extracted
    for key in ("probability", "probability_yes", "median", "q2", "mean", "value", "prediction"):
        if key in value:
            number = _optional_float(value.get(key))
            if number is not None and 0 <= number <= 1:
                return number
    if choices:
        distribution: dict[str, float] = {}
        lowered = {choice.lower(): choice for choice in choices}
        for key, raw_probability in value.items():
            match = lowered.get(str(key).strip().lower())
            number = _optional_float(raw_probability)
            if match and number is not None:
                distribution[match] = number
        if distribution:
            return distribution
    return None


def _metaculus_outcome_space(
    payload: dict,
    choices: list[str],
    probability: float | None,
    distribution: dict[str, float] | None,
) -> OutcomeSpace:
    raw_type = str(_first_present(payload.get("type"), payload.get("question_type")) or "").lower()
    if "binary" in raw_type or probability is not None:
        return OutcomeSpace(type="binary")
    if "multiple" in raw_type or "choice" in raw_type or distribution:
        return OutcomeSpace(type="categorical", choices=choices or list((distribution or {}).keys()))
    if "numeric" in raw_type or "date" in raw_type or "continuous" in raw_type:
        scaling = payload.get("scaling") if isinstance(payload.get("scaling"), dict) else {}
        bounds = [
            bound
            for bound in (
                _optional_float(scaling.get("range_min")),
                _optional_float(scaling.get("range_max")),
            )
            if bound is not None
        ]
        return OutcomeSpace(type="numeric", bounds=bounds, units=_optional_str(scaling.get("unit")))
    return OutcomeSpace(type="distribution", choices=choices)


def _metaculus_description(question_payload: dict, root_payload: dict) -> str:
    value = _first_present(
        question_payload.get("description"),
        question_payload.get("body"),
        question_payload.get("text"),
        root_payload.get("description"),
    )
    return str(value or "").strip()


def _metaculus_public_url(question_payload: dict, root_payload: dict, source: str) -> str | None:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc.endswith("metaculus.com") and not parsed.path.startswith(("/api/", "/api2/")):
        return source
    question_id = _optional_str(_first_present(question_payload.get("id"), root_payload.get("id")))
    return f"https://www.metaculus.com/questions/{question_id}/" if question_id else None


def _metaculus_timestamp(value: object) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        from datetime import datetime

        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return (
            datetime.fromtimestamp(seconds, tz=timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    try:
        return parse_timestamp(str(value), field_name="metaculus timestamp")
    except ValidationError:
        return None


def _kalshi_endpoint_for_source(source: str, *, api_base_url: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc == "external-api.kalshi.com":
            return source
        if parsed.netloc.endswith("kalshi.com"):
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0].lower() == "markets":
                ticker = parts[-1].upper()
                return f"{api_base_url.rstrip('/')}/markets/{quote(ticker)}"
            raise ValidationError("kalshi market URL must include a market ticker")
        return source
    ticker = source.removeprefix("ticker:").strip().upper()
    if not ticker:
        raise ValidationError("kalshi market ticker is empty")
    return f"{api_base_url.rstrip('/')}/markets/{quote(ticker)}"


def _kalshi_yes_probability(payload: dict) -> float | None:
    bid = _kalshi_price(
        _first_present(
            payload.get("yes_bid"),
            payload.get("yes_bid_cents"),
            payload.get("yes_bid_dollars"),
        )
    )
    ask = _kalshi_price(
        _first_present(
            payload.get("yes_ask"),
            payload.get("yes_ask_cents"),
            payload.get("yes_ask_dollars"),
        )
    )
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    last = _kalshi_price(
        _first_present(
            payload.get("last_price"),
            payload.get("last_price_cents"),
            payload.get("last_price_dollars"),
        )
    )
    if last is not None:
        return last
    if bid is not None:
        return bid
    return ask


def _kalshi_previous_yes_probability(payload: dict) -> float | None:
    previous = _kalshi_price(
        _first_present(
            payload.get("previous_price"),
            payload.get("previous_price_cents"),
            payload.get("previous_price_dollars"),
        )
    )
    if previous is not None:
        return previous
    previous_bid = _kalshi_price(
        _first_present(
            payload.get("previous_yes_bid"),
            payload.get("previous_yes_bid_cents"),
            payload.get("previous_yes_bid_dollars"),
        )
    )
    previous_ask = _kalshi_price(
        _first_present(
            payload.get("previous_yes_ask"),
            payload.get("previous_yes_ask_cents"),
            payload.get("previous_yes_ask_dollars"),
        )
    )
    if previous_bid is not None and previous_ask is not None:
        return (previous_bid + previous_ask) / 2
    if previous_bid is not None:
        return previous_bid
    return previous_ask


def _kalshi_price(value: object) -> float | None:
    number = _optional_float(value)
    if number is None:
        return None
    if number > 1:
        number = number / 100
    return max(0.0, min(1.0, number))


def _kalshi_description(payload: dict) -> str:
    parts = [
        _optional_str(payload.get("rules_primary")),
        _optional_str(payload.get("rules_secondary")),
        _optional_str(payload.get("settlement_sources")),
        _optional_str(payload.get("subtitle")),
    ]
    return "\n\n".join(part for part in parts if part)


def _kalshi_public_url(payload: dict) -> str | None:
    ticker = _optional_str(payload.get("ticker"))
    return f"https://kalshi.com/markets/{ticker.lower()}" if ticker else None


def _kalshi_timestamp(value: object) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        from datetime import datetime

        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return (
            datetime.fromtimestamp(seconds, tz=timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    try:
        return parse_timestamp(str(value), field_name="kalshi timestamp")
    except ValidationError:
        return None


def _first_present(*values: object) -> object | None:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _polymarket_sequence(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        value = parsed
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _polymarket_distribution(outcomes: list[str], prices: list[str]) -> dict[str, float]:
    distribution: dict[str, float] = {}
    for outcome, price in zip(outcomes, prices, strict=False):
        probability = _optional_float(price)
        if outcome and probability is not None:
            distribution[outcome] = probability
    return distribution


def _polymarket_binary_probability(distribution: dict[str, float]) -> float | None:
    lowered = {key.lower(): value for key, value in distribution.items()}
    if "yes" in lowered and "no" in lowered:
        return lowered["yes"]
    return None


def _polymarket_public_url(payload: dict) -> str | None:
    slug = _optional_str(payload.get("slug"))
    return f"https://polymarket.com/event/{slug}" if slug else None


def _polymarket_timestamp(value: object) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return _manifold_ms_to_iso(value)
    try:
        return parse_timestamp(str(value), field_name="polymarket timestamp")
    except ValidationError:
        return None


def _manifold_distribution(payload: dict) -> dict[str, float] | None:
    answers = payload.get("answers")
    if not isinstance(answers, list):
        return None
    distribution: dict[str, float] = {}
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        probability = _optional_float(answer.get("probability"))
        text = str(answer.get("text") or answer.get("number") or answer.get("id") or "").strip()
        if text and probability is not None:
            distribution[text] = probability
    return distribution or None


def _manifold_outcome_space(
    outcome_type: str,
    distribution: dict[str, float] | None,
    payload: dict,
) -> OutcomeSpace:
    if outcome_type == "BINARY":
        return OutcomeSpace(type="binary")
    if distribution:
        return OutcomeSpace(type="categorical", choices=list(distribution.keys()))
    if outcome_type in {"PSEUDO_NUMERIC", "NUMERIC"}:
        return OutcomeSpace(
            type="numeric",
            units="manifold_value",
            bounds=(
                [_optional_float(payload.get("min")), _optional_float(payload.get("max"))]
                if payload.get("min") is not None and payload.get("max") is not None
                else []
            ),
        )
    return OutcomeSpace(type="distribution", choices=[])


def _manifold_description(payload: dict) -> str:
    text_description = payload.get("textDescription")
    if isinstance(text_description, str) and text_description.strip():
        return text_description.strip()
    description = payload.get("description")
    if isinstance(description, str):
        return description.strip()
    if isinstance(description, dict):
        text = " ".join(_extract_rich_text(description))
        return " ".join(text.split())
    return ""


def _extract_rich_text(node: object) -> list[str]:
    if isinstance(node, dict):
        parts: list[str] = []
        text = node.get("text")
        if isinstance(text, str):
            parts.append(text)
        content = node.get("content")
        if isinstance(content, list):
            for child in content:
                parts.extend(_extract_rich_text(child))
        return parts
    if isinstance(node, list):
        parts = []
        for child in node:
            parts.extend(_extract_rich_text(child))
        return parts
    return []


def _manifold_ms_to_iso(value: object) -> str | None:
    number = _optional_float(value)
    if number is None:
        return None
    from datetime import datetime

    return datetime.fromtimestamp(number / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    number = _optional_float(value)
    if number is None:
        return None
    return int(number)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _collapse_ws(value: str) -> str:
    return " ".join(value.split())


def _pubmed_normalize_source(source: str) -> str:
    raw = source.split(":", 1)[1].strip() if source.startswith("pubmed:") else source.strip()
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc.endswith("pubmed.ncbi.nlm.nih.gov"):
        for part in parsed.path.split("/"):
            if part.isdigit():
                return part
    return raw


def _pubmed_search_endpoint(query: str, *, limit: int, since_date, api_base_url: str) -> str:
    params: dict[str, object] = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": min(limit, 100),
        "sort": "pub date",
    }
    if since_date is not None:
        params["mindate"] = f"{since_date.year:04d}/{since_date.month:02d}/{since_date.day:02d}"
        params["datetype"] = "pdat"
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    return f"{endpoint_base}{separator}{urlencode(params)}"


def _pubmed_fetch_endpoint(pmids: list[str], *, api_base_url: str) -> str:
    endpoint_base = _pubmed_fetch_base_url(api_base_url).rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    return f"{endpoint_base}{separator}{urlencode(params)}"


def _pubmed_fetch_base_url(api_base_url: str) -> str:
    base = api_base_url.strip()
    if not base:
        raise ValidationError("pubmed import --api-base-url cannot be empty")
    if "efetch.fcgi" in base:
        return base
    if "esearch.fcgi" in base:
        return base.replace("esearch.fcgi", "efetch.fcgi")
    return f"{base.rstrip('/')}/efetch.fcgi"


def _pubmed_search_pmids(payload: object) -> list[str]:
    if isinstance(payload, dict):
        result = payload.get("esearchresult")
        if isinstance(result, dict):
            raw_ids = result.get("idlist") or result.get("ids")
        else:
            raw_ids = payload.get("idlist") or payload.get("ids")
    else:
        raw_ids = None
    if not isinstance(raw_ids, list):
        raise ValidationError("pubmed search response must include an idlist array")
    return [str(item).strip() for item in raw_ids if str(item).strip()]


def _pubmed_descendants(parent: ElementTree.Element, tag: str) -> list[ElementTree.Element]:
    return [child for child in parent.iter() if _local_name(child.tag) == tag]


def _pubmed_first_descendant(parent: ElementTree.Element | None, tag: str) -> ElementTree.Element | None:
    if parent is None:
        return None
    for child in parent.iter():
        if _local_name(child.tag) == tag:
            return child
    return None


def _pubmed_text(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    return _collapse_ws("".join(element.itertext()))


def _pubmed_published_at(article: ElementTree.Element) -> str | None:
    article_date = _pubmed_first_descendant(article, "ArticleDate")
    if article_date is not None:
        parsed = _pubmed_date_to_iso(article_date)
        if parsed:
            return parsed
    journal_issue = _pubmed_first_descendant(article, "JournalIssue")
    if journal_issue is not None:
        pub_date = _pubmed_first_descendant(journal_issue, "PubDate")
        parsed = _pubmed_date_to_iso(pub_date)
        if parsed:
            return parsed
    return None


def _pubmed_date_to_iso(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    year_text = _pubmed_text(_pubmed_first_descendant(element, "Year"))
    if not year_text:
        medline_date = _pubmed_text(_pubmed_first_descendant(element, "MedlineDate"))
        if medline_date:
            match = re.search(r"\b(\d{4})\b", medline_date)
            year_text = match.group(1) if match else None
    if not year_text:
        return None
    try:
        year = int(year_text[:4])
    except ValueError:
        return None
    month = _pubmed_month_number(_pubmed_text(_pubmed_first_descendant(element, "Month")))
    day = _pubmed_day_number(_pubmed_text(_pubmed_first_descendant(element, "Day")))
    return datetime(year, month, day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _pubmed_month_number(value: str | None) -> int:
    if not value:
        return 1
    raw = value.strip()
    if raw.isdigit():
        month = int(raw)
        return month if 1 <= month <= 12 else 1
    month_names = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    return month_names.get(raw[:3].lower(), 1)


def _pubmed_day_number(value: str | None) -> int:
    if not value:
        return 1
    try:
        day = int(value.strip())
    except ValueError:
        return 1
    return day if 1 <= day <= 31 else 1


def _pubmed_abstract(article: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in _pubmed_descendants(article, "AbstractText"):
        text = _pubmed_text(node)
        if not text:
            continue
        label = _optional_str(node.attrib.get("Label"))
        parts.append(f"{label}: {text}" if label else text)
    return _collapse_ws(" ".join(parts))


def _pubmed_journal(article: ElementTree.Element) -> str | None:
    journal = _pubmed_first_descendant(article, "Journal")
    if journal is None:
        return None
    return _pubmed_text(_pubmed_first_descendant(journal, "Title")) or _pubmed_text(
        _pubmed_first_descendant(journal, "ISOAbbreviation")
    )


def _pubmed_authors(article: ElementTree.Element) -> list[str]:
    authors = []
    for author in _pubmed_descendants(article, "Author"):
        collective = _pubmed_text(_pubmed_first_descendant(author, "CollectiveName"))
        if collective:
            authors.append(collective)
            continue
        last = _pubmed_text(_pubmed_first_descendant(author, "LastName"))
        fore = _pubmed_text(_pubmed_first_descendant(author, "ForeName"))
        initials = _pubmed_text(_pubmed_first_descendant(author, "Initials"))
        name = " ".join(part for part in (fore or initials, last) if part)
        if name:
            authors.append(name)
    return authors


def _pubmed_publication_types(article: ElementTree.Element) -> list[str]:
    return [
        text
        for node in _pubmed_descendants(article, "PublicationType")
        for text in [_pubmed_text(node)]
        if text
    ]


def _pubmed_doi(pubmed_data: ElementTree.Element | None) -> str | None:
    if pubmed_data is None:
        return None
    for article_id in _pubmed_descendants(pubmed_data, "ArticleId"):
        if article_id.attrib.get("IdType", "").lower() == "doi":
            return _pubmed_text(article_id)
    return None


def _openalex_abstract(value: object) -> str:
    if isinstance(value, str):
        return _collapse_ws(value)
    if not isinstance(value, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, raw_indexes in value.items():
        if not isinstance(raw_indexes, list):
            continue
        for raw_index in raw_indexes:
            try:
                positions.append((int(raw_index), str(word)))
            except (TypeError, ValueError):
                continue
    return _collapse_ws(" ".join(word for _, word in sorted(positions)))


def _openalex_authors(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    authors: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        author = row.get("author")
        if isinstance(author, dict):
            name = _optional_str(author.get("display_name"))
            if name:
                authors.append(name)
    return authors


def _openalex_concepts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    concepts: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        name = _optional_str(row.get("display_name"))
        if name:
            concepts.append(name)
    return concepts


def _openalex_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="openalex timestamp")
    except ValidationError:
        parsed_date = _fred_date(text, field_name="openalex timestamp")
        return _fred_date_to_iso(parsed_date) if parsed_date is not None else None


def _crossref_first(value: object) -> str | None:
    if isinstance(value, list):
        for item in value:
            text = _optional_str(item)
            if text:
                return _collapse_ws(text)
        return None
    text = _optional_str(value)
    return _collapse_ws(text) if text else None


def _crossref_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = _optional_str(item)
        if text:
            items.append(_collapse_ws(text))
    return items


def _crossref_authors(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    authors: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        name = _optional_str(row.get("name"))
        if not name:
            name = " ".join(
                part
                for part in (
                    _optional_str(row.get("given")),
                    _optional_str(row.get("family")),
                )
                if part
            )
        if name:
            authors.append(_collapse_ws(name))
    return authors


def _crossref_published_at(row: dict) -> str | None:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        parsed = _crossref_date_parts(row.get(key))
        if parsed:
            return parsed
    return None


def _crossref_date_parts(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if not isinstance(parts, list) or not parts:
        return None
    first = parts[0]
    if not isinstance(first, list) or not first:
        return None
    try:
        year = int(first[0])
        month = int(first[1]) if len(first) > 1 else 1
        day = int(first[2]) if len(first) > 2 else 1
    except (TypeError, ValueError):
        return None
    if month < 1 or month > 12:
        month = 1
    if day < 1 or day > 31:
        day = 1
    try:
        return datetime(year, month, day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return datetime(year, month, 1, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _crossref_timestamp(value: object) -> str | None:
    if isinstance(value, dict):
        timestamp = _optional_str(value.get("date-time") or value.get("timestamp"))
    else:
        timestamp = _optional_str(value)
    if not timestamp:
        return None
    try:
        return parse_timestamp(timestamp, field_name="crossref timestamp")
    except ValidationError:
        return None


def _wikipedia_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="wikipedia timestamp")
    except ValidationError:
        return None


def _wikimedia_pageview_source_parts(source: str) -> tuple[str, str]:
    value = source.split(":", 1)[1].strip() if source.startswith("wikipediapageviews:") else source.strip()
    if not value:
        raise ValidationError("wikipediapageviews source is required")
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        project = parsed.netloc.lower()
        path = parsed.path.strip("/")
        article = parsed.path.split("/wiki/", 1)[1] if "/wiki/" in parsed.path else path
    elif "/" in value and "." in value.split("/", 1)[0]:
        project, article = value.split("/", 1)
    else:
        project = "en.wikipedia.org"
        article = value
    project = project.strip().lower()
    article = unquote(article).strip().lstrip("/")
    if article.startswith("wiki/"):
        article = article[5:]
    article = article.replace(" ", "_")
    if not project or not article:
        raise ValidationError("wikipediapageviews source must include a project and article")
    return project, article


def _wikimedia_today_utc():
    from datetime import datetime

    return datetime.now(timezone.utc).date()


def _wikimedia_pageviews_endpoint(
    project: str,
    article: str,
    access: str,
    agent: str,
    start_date,
    end_date,
    *,
    api_base_url: str,
) -> str:
    start = _wikimedia_pageview_date_param(start_date)
    end = _wikimedia_pageview_date_param(end_date)
    parts = [project, access, agent, article, "daily", start, end]
    path = "/".join(quote(part, safe="") for part in parts)
    return f"{api_base_url.rstrip('/')}/{path}"


def _wikimedia_pageview_date_param(value) -> str:
    return f"{value.year:04d}{value.month:02d}{value.day:02d}00"


def _wikimedia_pageview_timestamp(value: object) -> tuple[str | None, str | None]:
    text = _optional_str(value)
    if text is None:
        return None, None
    if len(text) >= 8 and text[:8].isdigit():
        raw_date = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        try:
            parsed_date = _fred_date(raw_date, field_name="wikimedia pageview timestamp")
        except ValidationError:
            return None, None
        if parsed_date is None:
            return None, None
        return parsed_date.isoformat(), _fred_date_to_iso(parsed_date)
    try:
        parsed = parse_timestamp(text, field_name="wikimedia pageview timestamp")
    except ValidationError:
        return None, None
    parsed_dt = timestamp_to_datetime(parsed)
    if parsed_dt is None:
        return None, None
    parsed_date = parsed_dt.date()
    return parsed_date.isoformat(), _fred_date_to_iso(parsed_date)


def _wikimedia_pageview_count(value: object) -> int | None:
    number = _optional_float(value)
    if number is None or number < 0:
        return None
    return int(number)


def _github_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="github timestamp")
    except ValidationError:
        return None


def _hackernews_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="hackernews timestamp")
    except ValidationError:
        return None


def _reddit_timestamp(value: object) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
    text = _optional_str(value)
    if not text:
        return None
    try:
        return datetime.fromtimestamp(float(text), tz=timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
    except ValueError:
        pass
    try:
        return parse_timestamp(text, field_name="reddit timestamp")
    except ValidationError:
        return None


def _bluesky_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="bluesky timestamp")
    except ValidationError:
        return None


def _reliefweb_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="reliefweb timestamp")
    except ValidationError:
        return None


def _federalregister_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="federal register timestamp")
    except ValidationError:
        return None


def _courtlistener_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="courtlistener timestamp")
    except ValidationError:
        return None


def _nvd_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="nvd timestamp")
    except ValidationError:
        return None


def _cisa_kev_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="cisa kev timestamp")
    except ValidationError:
        return None


def _usgs_earthquake_endpoint(
    source: str,
    *,
    limit: int,
    since: str | None,
    api_base_url: str,
) -> str:
    value = source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        endpoint_base = value.split("?", 1)[0].rstrip("?&")
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    else:
        endpoint_base = api_base_url.rstrip("?&")
        params = dict(parse_qsl(value.lstrip("?"), keep_blank_values=True)) if "=" in value else {}
        if not params:
            params["eventid"] = value
    params["format"] = "geojson"
    params.setdefault("orderby", "time")
    params["limit"] = min(limit, 20000)
    if since and not params.get("starttime"):
        params["starttime"] = since.strip()
    return f"{endpoint_base}?{urlencode(params)}"


def _usgs_ms_to_iso(value: object) -> str | None:
    if value in (None, ""):
        return None
    number = _optional_float(value)
    if number is None:
        try:
            return parse_timestamp(str(value), field_name="usgs timestamp")
        except ValidationError:
            return None
    from datetime import datetime

    seconds = number / 1000 if number > 10_000_000_000 else number
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _usgs_coordinates(value: object) -> tuple[float | None, float | None, float | None]:
    if not isinstance(value, list):
        return None, None, None
    longitude = _optional_float(value[0]) if len(value) > 0 else None
    latitude = _optional_float(value[1]) if len(value) > 1 else None
    depth_km = _optional_float(value[2]) if len(value) > 2 else None
    return longitude, latitude, depth_km


def _usgs_event_title(*, magnitude: float | None, place: str | None) -> str:
    magnitude_label = f"M {magnitude:g}" if magnitude is not None else "USGS event"
    return f"{magnitude_label} - {place}" if place else magnitude_label


def _eonet_endpoint(
    source: str,
    *,
    limit: int,
    since: str | None,
    api_base_url: str,
) -> str:
    value = source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        endpoint_base = value.split("?", 1)[0].rstrip("?&")
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    else:
        endpoint_base = api_base_url.rstrip("?&")
        params = dict(parse_qsl(value.lstrip("?"), keep_blank_values=True)) if "=" in value else {}
        if not params:
            params["category"] = value
    params["limit"] = min(limit, 1000)
    if since and not params.get("start"):
        params["start"] = since.strip()
    return f"{endpoint_base}?{urlencode(params)}"


def _eonet_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="nasa eonet timestamp")
    except ValidationError:
        return None


def _eonet_latest_geometry(value: object) -> dict:
    if not isinstance(value, list):
        return {}
    rows = [row for row in value if isinstance(row, dict)]
    if not rows:
        return {}
    return rows[-1]


def _eonet_categories(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    categories: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        title = _optional_str(_first_present(row.get("title"), row.get("id")))
        if title:
            categories.append(title)
    return categories


def _eonet_source_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        source_id = _optional_str(row.get("id"))
        if source_id:
            names.append(source_id)
    return names


def _eonet_source_urls(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    urls: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        url = _optional_str(row.get("url"))
        if url:
            urls.append(url)
    return urls


def _eonet_first_coordinate(value: object) -> tuple[float | None, float | None]:
    if not isinstance(value, list):
        return None, None
    if len(value) >= 2:
        longitude = _optional_float(value[0])
        latitude = _optional_float(value[1])
        if longitude is not None and latitude is not None:
            return longitude, latitude
    for item in value:
        longitude, latitude = _eonet_first_coordinate(item)
        if longitude is not None and latitude is not None:
            return longitude, latitude
    return None, None


def _nws_alerts_endpoint(source: str, *, api_base_url: str) -> str:
    value = source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        endpoint_base = value.split("?", 1)[0].rstrip("?&")
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    else:
        endpoint_base = api_base_url.rstrip("?&")
        params = dict(parse_qsl(value.lstrip("?"), keep_blank_values=True)) if "=" in value else {}
        if not params:
            if _looks_like_lat_lon(value):
                params["point"] = value
            elif len(value) == 2 and value.isalpha():
                params["area"] = value.upper()
            else:
                params["event"] = value
    return f"{endpoint_base}?{urlencode(params)}" if params else endpoint_base


def _clinicaltrials_endpoint(source: str, *, limit: int, api_base_url: str) -> str:
    value = source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        endpoint_base = value.split("?", 1)[0].rstrip("?&")
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    else:
        endpoint_base = api_base_url.rstrip("?&")
        params = dict(parse_qsl(value.lstrip("?"), keep_blank_values=True)) if "=" in value else {}
        if not params:
            if value.upper().startswith("NCT"):
                params["query.id"] = value.upper()
            else:
                params["query.term"] = value
    params.setdefault("format", "json")
    params["pageSize"] = min(max(limit, 1), 1000)
    return f"{endpoint_base}?{urlencode(params)}"


def _clinicaltrials_study_rows(payload: object) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("studies"), list):
        return [row for row in payload["studies"] if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("protocolSection"), dict):
        return [payload]
    raise ValidationError("clinicaltrials studies response must contain a studies array")


def _clinicaltrials_date_to_iso(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("date")
    text = _optional_str(value)
    if not text:
        return None
    raw = text.strip()
    if len(raw) == 4 and raw.isdigit():
        raw = f"{raw}-01-01"
    elif len(raw) == 7 and raw[4] == "-" and raw[:4].isdigit() and raw[5:].isdigit():
        raw = f"{raw}-01"
    try:
        return parse_timestamp(raw, field_name="clinicaltrials date")
    except ValidationError:
        return None


def _clinicaltrials_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [_collapse_ws(value)] if value.strip() else []
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        text = _optional_str(item)
        if text:
            rows.append(_collapse_ws(text))
    return rows


def _clinicaltrials_interventions(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = _first_present(item.get("name"), item.get("type"))
        else:
            text = item
        label = _optional_str(text)
        if label:
            rows.append(_collapse_ws(label))
    return rows


def _clinicaltrials_sponsors(value: dict) -> list[str]:
    rows: list[str] = []
    lead = value.get("leadSponsor")
    if isinstance(lead, dict):
        label = _optional_str(lead.get("name"))
        if label:
            rows.append(_collapse_ws(label))
    collaborators = value.get("collaborators")
    if isinstance(collaborators, list):
        for item in collaborators:
            if not isinstance(item, dict):
                continue
            label = _optional_str(item.get("name"))
            if label:
                rows.append(_collapse_ws(label))
    return rows


def _collapse_optional(value: object) -> str | None:
    text = _optional_str(value)
    return _collapse_ws(text) if text else None


def _openfda_endpoint(source: str, *, limit: int, api_base_url: str) -> str:
    value = source.strip()
    parsed = urlparse(value)
    params: dict[str, str | int] = {}
    if parsed.scheme in {"http", "https"}:
        endpoint_base = value.split("?", 1)[0].rstrip("?&")
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    else:
        endpoint_base = api_base_url.rstrip("?&")
        if "=" in value and not _looks_like_openfda_application_number(value):
            params = dict(parse_qsl(value.lstrip("?"), keep_blank_values=True))
        else:
            params["search"] = _openfda_search_query(value)
    params.setdefault("limit", min(limit, 100))
    separator = "&" if "?" in endpoint_base else "?"
    return f"{endpoint_base}{separator}{urlencode(params)}"


def _openfda_search_query(value: str) -> str:
    source = value.strip()
    if not source:
        raise ValidationError("openfda source is required")
    if _looks_like_openfda_application_number(source):
        return f'application_number:"{source.upper()}"'
    if ":" in source or " " in source and any(operator in source.upper() for operator in (" AND ", " OR ", " NOT ")):
        return source
    quoted = source.replace('"', r"\"")
    return (
        f'(openfda.brand_name:"{quoted}" OR '
        f'openfda.generic_name:"{quoted}" OR '
        f'sponsor_name:"{quoted}" OR '
        f'products.brand_name:"{quoted}")'
    )


def _looks_like_openfda_application_number(value: str) -> bool:
    raw = "".join(value.strip().upper().split())
    prefixes = ("NDA", "ANDA", "BLA")
    if any(raw.startswith(prefix) and raw[len(prefix) :].isdigit() for prefix in prefixes):
        return True
    return raw.isdigit() and 3 <= len(raw) <= 8


def _openfda_application_rows(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        rows = payload.get("results")
    else:
        rows = payload
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    raise ValidationError("openFDA Drugs@FDA response must contain a results array")


def _openfda_date_to_iso(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    raw = "".join(text.split())
    if len(raw) == 8 and raw.isdigit():
        raw = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    try:
        return parse_timestamp(raw, field_name="openFDA date")
    except ValidationError:
        return None


def _openfda_latest_submission(value: object) -> dict:
    if not isinstance(value, list):
        return {}
    latest: dict = {}
    latest_date = ""
    for row in value:
        if not isinstance(row, dict):
            continue
        date_text = _optional_str(_first_present(row.get("submission_status_date"), row.get("submission_date"))) or ""
        normalized_date = "".join(date_text.split())
        if normalized_date >= latest_date:
            latest = row
            latest_date = normalized_date
    return latest


def _openfda_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [_collapse_ws(str(item)) for item in value if _optional_str(item)]
    text = _optional_str(value)
    return [_collapse_ws(text)] if text else []


def _openfda_product_values(products: object, key: str) -> list[str]:
    if not isinstance(products, list):
        return []
    values: list[str] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        values.extend(_openfda_list(product.get(key)))
    return values


def _openfda_active_ingredient_names(products: object) -> list[str]:
    if not isinstance(products, list):
        return []
    names: list[str] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        ingredients = product.get("active_ingredients")
        if not isinstance(ingredients, list):
            continue
        for ingredient in ingredients:
            if not isinstance(ingredient, dict):
                continue
            label = _collapse_optional(ingredient.get("name"))
            if label:
                names.append(label)
    return names


def _openfda_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = _collapse_ws(value)
        key = normalized.lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def _openfda_application_url(application_number: str, latest_submission: dict) -> str:
    docs = latest_submission.get("application_docs")
    if isinstance(docs, list):
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            url = _optional_str(doc.get("url"))
            if url:
                return url
    digits = "".join(ch for ch in application_number if ch.isdigit())
    if digits:
        return f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={digits}"
    return "https://www.accessdata.fda.gov/scripts/cder/daf/"


def _nws_alert_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="nws alert timestamp")
    except ValidationError:
        return None


def _looks_like_lat_lon(value: str) -> bool:
    parts = [part.strip() for part in value.split(",", 1)]
    if len(parts) != 2:
        return False
    try:
        latitude = float(parts[0])
        longitude = float(parts[1])
    except ValueError:
        return False
    return -90 <= latitude <= 90 and -180 <= longitude <= 180


def _nvd_description(value: object) -> str:
    if not isinstance(value, list):
        return ""
    fallback = ""
    for row in value:
        if not isinstance(row, dict):
            continue
        description = _optional_str(row.get("value"))
        if not description:
            continue
        if not fallback:
            fallback = description
        if _optional_str(row.get("lang")) == "en":
            return _collapse_ws(description)
    return _collapse_ws(fallback)


def _nvd_references(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    rows = value.get("referenceData")
    if not isinstance(rows, list):
        return []
    urls: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = _optional_str(row.get("url"))
        if url:
            urls.append(url)
    return urls


def _nvd_cvss_summary(value: object) -> tuple[str | None, float | None, str | None]:
    if not isinstance(value, dict):
        return None, None, None
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        rows = value.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        metric = rows[0] if isinstance(rows[0], dict) else {}
        data = metric.get("cvssData") if isinstance(metric.get("cvssData"), dict) else {}
        severity = (
            _optional_str(data.get("baseSeverity"))
            or _optional_str(metric.get("baseSeverity"))
            or _optional_str(metric.get("severity"))
        )
        base_score = _optional_float(data.get("baseScore"))
        cvss_version = _optional_str(data.get("version"))
        return severity, base_score, cvss_version
    return None, None, None


def _cisa_kev_matches_query(row: dict, query: str) -> bool:
    normalized = query.strip().lower()
    if normalized in {"*", "all", "latest"}:
        return True
    cve_id = _optional_str(_first_present(row.get("cveID"), row.get("cveId"), row.get("cve_id")))
    if cve_id and normalized == cve_id.lower():
        return True
    haystack = " ".join(
        str(value)
        for value in (
            row.get("cveID"),
            row.get("vendorProject"),
            row.get("product"),
            row.get("vulnerabilityName"),
            row.get("shortDescription"),
            row.get("requiredAction"),
            row.get("knownRansomwareCampaignUse"),
            row.get("notes"),
            row.get("cwes"),
        )
        if value not in (None, "")
    ).lower()
    return normalized in haystack


def _cisa_kev_cwes(value: object) -> list[str]:
    if isinstance(value, list):
        return [text for item in value for text in [_optional_str(item)] if text]
    text = _optional_str(value)
    if not text:
        return []
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


def _openmeteo_coordinates(source: str, *, label: str = "openmeteo") -> tuple[float, float]:
    value = (
        source.split(":", 1)[1].strip()
        if source.startswith(("openmeteo:", "airquality:", "weatherhistory:"))
        else source.strip()
    )
    parts = [part.strip() for part in value.replace("/", ",").split(",") if part.strip()]
    if len(parts) != 2:
        raise ValidationError(f"{label} source must be latitude,longitude")
    try:
        latitude = float(parts[0])
        longitude = float(parts[1])
    except ValueError as exc:
        raise ValidationError(f"{label} source must use numeric latitude and longitude") from exc
    if not -90 <= latitude <= 90:
        raise ValidationError(f"{label} latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValidationError(f"{label} longitude must be between -180 and 180")
    return latitude, longitude


def _openmeteo_history_request(
    source: str,
    *,
    start_date: str | None,
    end_date: str | None,
) -> tuple[float, float, str, str]:
    value = source.split(":", 1)[1].strip() if source.startswith("weatherhistory:") else source.strip()
    location = value
    query = ""
    if "?" in value:
        location, query = value.split("?", 1)
    query_params = dict(parse_qsl(query, keep_blank_values=False))
    start_value = start_date or query_params.get("start") or query_params.get("start_date")
    end_value = end_date or query_params.get("end") or query_params.get("end_date")
    if not start_value or not end_value:
        raise ValidationError("weatherhistory import requires --start-date and --end-date or source query start/end")
    latitude, longitude = _openmeteo_coordinates(location, label="weatherhistory")
    start_day = _openmeteo_history_date(start_value, field_name="weatherhistory start date")
    end_day = _openmeteo_history_date(end_value, field_name="weatherhistory end date")
    if start_day > end_day:
        raise ValidationError("weatherhistory start date must be on or before end date")
    return latitude, longitude, start_day, end_day


def _openmeteo_history_date(value: str, *, field_name: str) -> str:
    parsed = parse_timestamp(value, field_name=field_name)
    if not parsed:
        raise ValidationError(f"{field_name} is required")
    return parsed[:10]


def _openmeteo_date_to_iso(value: str) -> str | None:
    try:
        return parse_timestamp(value, field_name="openmeteo forecast date")
    except ValidationError:
        return None


def _openmeteo_time_to_iso(value: str) -> str | None:
    try:
        return parse_timestamp(value, field_name="openmeteo forecast time")
    except ValidationError:
        return None


def _openmeteo_daily_float(daily: dict, key: str, index: int) -> float | None:
    rows = daily.get(key)
    if not isinstance(rows, list) or index >= len(rows):
        return None
    return _optional_float(rows[index])


def _openmeteo_hourly_float(hourly: dict, key: str, index: int) -> float | None:
    rows = hourly.get(key)
    if not isinstance(rows, list) or index >= len(rows):
        return None
    return _optional_float(rows[index])


def _owid_endpoint(source: str, *, api_base_url: str) -> tuple[str, str]:
    value = source.split(":", 1)[1].strip() if source.startswith("owid:") else source.strip()
    if not value:
        raise ValidationError("owid source slug or URL is required")
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        slug = Path(parsed.path).name.removesuffix(".csv").removesuffix(".metadata.json")
        endpoint = value if value.endswith(".csv") else f"{value.rstrip('/')}.csv"
        return slug or "owid", endpoint
    slug = value.removesuffix(".csv").strip("/")
    if "/" in slug:
        raise ValidationError("owid source must be a grapher slug or CSV URL")
    endpoint = f"{api_base_url.rstrip('/')}/{quote(slug, safe='')}.csv"
    return slug, endpoint


def _owid_value_column(row: dict[str, str]) -> str:
    for key in row:
        if key not in {"Entity", "Code", "Year", "Date"}:
            return key
    raise ValidationError("owid CSV must include a value column")


def _owid_date_to_iso(value: str) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    if text.isdigit() and len(text) == 4:
        text = f"{text}-01-01"
    try:
        return parse_timestamp(text, field_name="owid observation date")
    except ValidationError:
        return None


def _github_repo_parts(source: str) -> tuple[str, str]:
    value = (
        source.split(":", 1)[1].strip()
        if source.startswith(("github:", "githubissues:", "githubcommits:", "githubactions:"))
        else source.strip()
    )
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "github.com":
        parts = [part for part in parsed.path.strip("/").split("/") if part]
    else:
        parts = [part for part in value.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValidationError(
            "github source must be owner/repo, github:owner/repo, githubissues:owner/repo, "
            "githubcommits:owner/repo, githubactions:owner/repo, or a GitHub repository URL"
        )
    owner, repo = parts[0], parts[1]
    if not owner or not repo:
        raise ValidationError("github source must include owner and repo")
    return owner, repo.removesuffix(".git")


def _github_label_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    for item in value:
        if isinstance(item, dict):
            label = _collapse_optional(item.get("name"))
        else:
            label = _collapse_optional(item)
        if label:
            labels.append(label)
    return labels


def _coingecko_coin_ids(source: str) -> list[str]:
    value = source.split(":", 1)[1].strip() if source.startswith("coingecko:") else source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        host = parsed.netloc.lower()
        if host.endswith("coingecko.com"):
            if host.startswith("api.") and parsed.query:
                params = dict(parse_qsl(parsed.query, keep_blank_values=True))
                value = params.get("ids") or ""
            else:
                parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
                if "coins" in parts:
                    index = parts.index("coins")
                    value = parts[index + 1] if index + 1 < len(parts) else ""
                else:
                    value = ""
        else:
            raise ValidationError("coingecko source URL must be a CoinGecko coin page or markets API URL")
    normalized = [item.strip().lower() for item in re.split(r"[\s,]+", value) if item.strip()]
    if not normalized:
        raise ValidationError(
            "coingecko source must be a coin id, comma-separated ids, coingecko:<coin-id>, "
            "or a CoinGecko coin URL"
        )
    if any("/" in item for item in normalized):
        raise ValidationError("coingecko coin ids cannot contain slashes")
    return normalized


def _coingecko_markets_endpoint(
    coin_ids: list[str],
    *,
    vs_currency: str,
    limit: int,
    api_base_url: str,
) -> str:
    base = api_base_url.strip()
    if not base:
        raise ValidationError("coingecko import --api-base-url cannot be empty")
    ids = ",".join(coin_ids)
    if "{ids}" in base or "{vs_currency}" in base:
        return base.replace("{ids}", quote(ids, safe=",")).replace("{vs_currency}", quote(vs_currency, safe=""))
    endpoint_base = base.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    params = {
        "vs_currency": vs_currency,
        "ids": ids,
        "order": "market_cap_desc",
        "per_page": min(max(limit, len(coin_ids)), 250),
        "page": 1,
        "price_change_percentage": "24h",
    }
    return f"{endpoint_base}{separator}{urlencode(params)}"


def _coingecko_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="coingecko timestamp")
    except ValidationError:
        return None


def _coingecko_optional_number(value: object) -> float | int | str | None:
    number = _optional_float(value)
    if number is not None:
        if number.is_integer():
            return int(number)
        return number
    return _optional_str(value)


def _pypi_package_name(source: str) -> str:
    value = source.split(":", 1)[1].strip() if source.startswith("pypi:") else source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2 and parts[0] == "project":
            package = parts[1]
        elif len(parts) >= 2 and parts[0] == "pypi":
            package = parts[1]
        else:
            raise ValidationError("pypi source URL must be a PyPI project or JSON API URL")
    else:
        package = value
    package = package.strip()
    if not package:
        raise ValidationError("pypi source must be a package name, pypi:<package>, or a PyPI project URL")
    if "/" in package or any(ch.isspace() for ch in package):
        raise ValidationError("pypi package names cannot contain slashes or whitespace")
    return package


def _pypi_project_endpoint(package: str, *, api_base_url: str) -> str:
    base = api_base_url.rstrip("/")
    if "{package}" in base:
        return base.format(package=quote(package, safe=""))
    if base.endswith("/json"):
        return base
    return f"{base}/{quote(package, safe='')}/json"


def _pypi_upload_timestamp(item: dict) -> str | None:
    value = _first_present(item.get("upload_time_iso_8601"), item.get("upload_time"))
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="pypi upload time")
    except ValidationError:
        return None


def _pypi_yanked_reason(files: list[dict]) -> str | None:
    for item in files:
        if not item.get("yanked"):
            continue
        reason = _collapse_optional(item.get("yanked_reason"))
        if reason:
            return reason
    return None


def _npm_package_name(source: str) -> str:
    value = source.split(":", 1)[1].strip() if source.startswith("npm:") else source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if parsed.netloc.lower().endswith("npmjs.com") and len(parts) >= 2 and parts[0] == "package":
            package = "/".join(parts[1:3]) if parts[1].startswith("@") and len(parts) >= 3 else parts[1]
        elif parsed.netloc.lower().endswith("npmjs.org") or parsed.netloc.lower().endswith("npmjs.com"):
            package = unquote(parsed.path.strip("/"))
        else:
            package = unquote(parsed.path.strip("/"))
    else:
        package = value
    package = package.strip()
    if not package:
        raise ValidationError("npm source must be a package name, npm:<package>, or an npm package URL")
    if any(ch.isspace() for ch in package):
        raise ValidationError("npm package names cannot contain whitespace")
    if "/" in package and not (package.startswith("@") and package.count("/") == 1):
        raise ValidationError("npm scoped package names must look like @scope/name")
    return package


def _npm_package_endpoint(package: str, *, api_base_url: str) -> str:
    base = api_base_url.rstrip("/")
    if "{package}" in base:
        return base.format(package=quote(package, safe=""))
    return f"{base}/{quote(package, safe='')}"


def _npm_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="npm package time")
    except ValidationError:
        return None


def _npm_license(value: object) -> str | None:
    if isinstance(value, dict):
        return _collapse_optional(value.get("type") or value.get("name"))
    return _collapse_optional(value)


def _npm_people(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    people: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = _collapse_optional(item.get("name") or item.get("email"))
        else:
            name = _collapse_optional(item)
        if name:
            people.append(name)
    return people


def _npm_keywords(value: object) -> list[str]:
    if isinstance(value, list):
        return [text for item in value for text in [_collapse_optional(item)] if text]
    text = _collapse_optional(value)
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _npm_dependency_count(row: dict) -> int:
    names: set[str] = set()
    for key in ("dependencies", "optionalDependencies", "peerDependencies"):
        value = row.get(key)
        if isinstance(value, dict):
            names.update(str(name) for name in value if name)
    return len(names)


def _hackernews_endpoint(
    source: str,
    *,
    limit: int,
    since_ts: str | None,
    api_base_url: str,
) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source
    params: dict[str, object] = {
        "query": source,
        "tags": "story",
        "hitsPerPage": min(limit, 1000),
    }
    if since_ts:
        since_dt = timestamp_to_datetime(since_ts)
        if since_dt is not None:
            params["numericFilters"] = f"created_at_i>{int(since_dt.timestamp())}"
    return f"{api_base_url.rstrip('/')}?{urlencode(params)}"


def _hackernews_hits(payload: object) -> list:
    if isinstance(payload, dict) and isinstance(payload.get("hits"), list):
        return payload["hits"]
    if isinstance(payload, list):
        return payload
    raise ValidationError("hackernews search response must include a hits array")


def _reddit_endpoint(source: str, *, limit: int, api_base_url: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source
    params: dict[str, object] = {
        "q": source,
        "sort": "new",
        "limit": min(limit, 100),
        "raw_json": 1,
        "type": "link",
    }
    separator = "&" if "?" in api_base_url else "?"
    return f"{api_base_url.rstrip('/')}{separator}{urlencode(params)}"


def _bluesky_endpoint(
    source: str,
    *,
    limit: int,
    since_ts: str | None,
    sort: str,
    author: str | None,
    lang: str | None,
    link_domain: str | None,
    url_filter: str | None,
    api_base_url: str,
) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source
    params: dict[str, object] = {
        "q": source,
        "sort": sort,
        "limit": min(limit, 100),
    }
    if since_ts:
        params["since"] = since_ts
    if author:
        params["author"] = author
    if lang:
        params["lang"] = lang
    if link_domain:
        params["domain"] = link_domain
    if url_filter:
        params["url"] = url_filter
    separator = "&" if "?" in api_base_url else "?"
    return f"{api_base_url.rstrip('/')}{separator}{urlencode(params)}"


def _bluesky_posts(payload: object) -> list:
    if isinstance(payload, dict) and isinstance(payload.get("posts"), list):
        return payload["posts"]
    if isinstance(payload, list):
        return payload
    raise ValidationError("bluesky search response must include a posts array")


def _bluesky_post_url(post_uri: str | None, actor: str | None) -> str | None:
    if not post_uri:
        return None
    parsed = urlparse(post_uri)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return post_uri
    if not post_uri.startswith("at://"):
        return None
    parts = post_uri[5:].split("/")
    if len(parts) < 3:
        return None
    profile = actor or parts[0]
    rkey = parts[-1]
    if not profile or not rkey:
        return None
    return f"https://bsky.app/profile/{quote(profile, safe=':.')}/post/{quote(rkey, safe='')}"


def _reliefweb_endpoint(
    source: str,
    *,
    limit: int,
    since_ts: str | None,
    appname: str,
    api_base_url: str,
) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source
    endpoint_base = api_base_url.rstrip("?&")
    params: dict[str, object] = {
        "appname": appname,
        "query[value]": source,
        "limit": min(limit, 100),
        "sort[]": "date.created:desc",
        "fields[include][]": [
            "title",
            "body",
            "body-html",
            "date",
            "source",
            "country",
            "disaster",
            "format",
            "theme",
            "url",
        ],
    }
    if since_ts:
        since_dt = timestamp_to_datetime(since_ts)
        if since_dt is not None:
            params["filter[field]"] = "date.created"
            params["filter[value][from]"] = since_dt.date().isoformat()
    separator = "&" if "?" in endpoint_base else "?"
    return f"{endpoint_base}{separator}{urlencode(params, doseq=True)}"


def _reliefweb_rows(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        for key in ("data", "results", "reports"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    raise ValidationError("reliefweb reports response must include a data array")


def _reliefweb_date(fields: dict, key: str) -> object | None:
    date_value = fields.get("date")
    if isinstance(date_value, dict):
        return date_value.get(key)
    return None


def _reliefweb_names(value: object) -> list[str]:
    if isinstance(value, dict):
        label = _optional_str(_first_present(value.get("name"), value.get("shortname"), value.get("title")))
        return [_collapse_ws(label)] if label else []
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, dict):
                label = _optional_str(_first_present(item.get("name"), item.get("shortname"), item.get("title")))
            else:
                label = _optional_str(item)
            if label:
                names.append(_collapse_ws(label))
        return names
    label = _optional_str(value)
    return [_collapse_ws(label)] if label else []


def _reliefweb_summary(fields: dict) -> str:
    summary = _collapse_optional(fields.get("body")) or _collapse_optional(fields.get("summary"))
    if summary:
        return summary
    html_text = _optional_str(fields.get("body-html"))
    if not html_text:
        return ""
    return _collapse_ws(re.sub(r"<[^>]+>", " ", html_text))


def _courtlistener_endpoint(source: str, *, limit: int, search_type: str, api_base_url: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    params = {
        "q": source,
        "type": search_type,
        "page_size": min(limit, 100),
    }
    return f"{endpoint_base}{separator}{urlencode(params)}"


def _courtlistener_result_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if value.startswith("/"):
        return f"https://www.courtlistener.com{value}"
    return f"https://www.courtlistener.com/{value.lstrip('/')}"


def _courtlistener_citation(row: dict[str, object]) -> str | None:
    for key in ("citation", "citation_str", "neutralCite", "neutral_cite"):
        value = row.get(key)
        if isinstance(value, list):
            parts = [
                _optional_str(item.get("cite") if isinstance(item, dict) else item)
                for item in value
            ]
            citation = ", ".join(part for part in parts if part)
            if citation:
                return citation
        text = _optional_str(value)
        if text:
            return text
    citations = row.get("citations")
    if isinstance(citations, list):
        parts = [
            _optional_str(item.get("cite") if isinstance(item, dict) else item)
            for item in citations
        ]
        citation = ", ".join(part for part in parts if part)
        if citation:
            return citation
    return None


def _reddit_children(payload: object) -> list:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("children"), list):
            return data["children"]
        if isinstance(payload.get("children"), list):
            return payload["children"]
    if isinstance(payload, list):
        return payload
    raise ValidationError("reddit search response must include data.children")


def _reddit_permalink(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if value.startswith("/"):
        return f"https://www.reddit.com{value}"
    return f"https://www.reddit.com/{value}"


def _arxiv_entry_url(entry: ElementTree.Element, entry_id: str | None) -> str | None:
    for link in _namespaced_findall(entry, "link"):
        attrs = dict(link.attrib)
        if attrs.get("rel", "alternate") == "alternate" and attrs.get("href"):
            return attrs["href"]
    return entry_id


def _arxiv_pdf_url(entry: ElementTree.Element) -> str | None:
    for link in _namespaced_findall(entry, "link"):
        attrs = dict(link.attrib)
        if attrs.get("title") == "pdf" and attrs.get("href"):
            return attrs["href"]
    return None


def _arxiv_id_from_entry_id(entry_id: str | None) -> str | None:
    if not entry_id:
        return None
    parsed = urlparse(entry_id)
    candidate = parsed.path.rsplit("/", 1)[-1] if parsed.scheme else entry_id.rsplit("/", 1)[-1]
    return candidate.strip() or None


def _parse_rss_items(root: ElementTree.Element) -> list[NewsFeedItem]:
    channel = root.find("channel")
    if channel is None:
        return []
    source_name = _text(channel, "title")
    items = []
    for item in channel.findall("item"):
        title = _text(item, "title") or "Untitled feed item"
        summary = _text(item, "description") or ""
        url = _text(item, "link")
        published_at = _normalize_feed_timestamp(_text(item, "pubDate") or _text(item, "published"))
        entry_id = _text(item, "guid") or url
        items.append(
            NewsFeedItem(
                title=title,
                summary=summary,
                url=url,
                published_at=published_at,
                source_name=source_name,
                entry_id=entry_id,
            )
        )
    return items


def _parse_atom_items(root: ElementTree.Element) -> list[NewsFeedItem]:
    source_name = _namespaced_text(root, "title")
    items = []
    for entry in _namespaced_findall(root, "entry"):
        title = _namespaced_text(entry, "title") or "Untitled feed item"
        summary = _namespaced_text(entry, "summary") or _namespaced_text(entry, "content") or ""
        published_at = _normalize_feed_timestamp(
            _namespaced_text(entry, "published") or _namespaced_text(entry, "updated")
        )
        url = None
        for link in _namespaced_findall(entry, "link"):
            link_attrs = dict(link.attrib)
            if link_attrs.get("rel", "alternate") == "alternate" and link_attrs.get("href"):
                url = link_attrs["href"]
                break
        entry_id = _namespaced_text(entry, "id") or url
        items.append(
            NewsFeedItem(
                title=title,
                summary=summary,
                url=url,
                published_at=published_at,
                source_name=source_name,
                entry_id=entry_id,
            )
        )
    return items


def _normalize_feed_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parse_timestamp(value, field_name="feed timestamp")
    except ValidationError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(parent: ElementTree.Element, tag: str) -> str | None:
    child = parent.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _namespaced_text(parent: ElementTree.Element, tag: str) -> str | None:
    child = _namespaced_find(parent, tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _namespaced_find(parent: ElementTree.Element, tag: str) -> ElementTree.Element | None:
    for child in parent:
        if _local_name(child.tag) == tag:
            return child
    return None


def _namespaced_findall(parent: ElementTree.Element, tag: str) -> list[ElementTree.Element]:
    return [child for child in parent if _local_name(child.tag) == tag]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
