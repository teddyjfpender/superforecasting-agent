"""Source adapters for generic forecasting evidence feeds."""

from __future__ import annotations


import csv
from html import unescape
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen
from typing import Any
from xml.etree import ElementTree

from forecasting import appconfig
from forecasting.models import OutcomeSpace, ValidationError, parse_timestamp, timestamp_to_datetime
from forecasting.pm import polymarket as _pm_polymarket
from forecasting.observation_freshness import (
    FreshnessAssessment,
    assess_observation_freshness,
    resolve_max_business_days,
)


from forecasting.sources.dates import (
    _optional_prediction_timestamp,
    _fred_date as _fred_date,
    _fred_date_to_iso as _fred_date_to_iso,
    _optional_iso_timestamp,
)

from forecasting.sources.public_records import (
    NewsFeedItem as NewsFeedItem,
    GdeltArticle as GdeltArticle,
    HackerNewsItem as HackerNewsItem,
    RedditPost as RedditPost,
    BlueskyPost as BlueskyPost,
    MastodonStatus as MastodonStatus,
    ReliefWebReport as ReliefWebReport,
    FederalRegisterDocument as FederalRegisterDocument,
    CourtListenerSearchResult as CourtListenerSearchResult,
)

from forecasting.sources.economic_records import (
    FiveThirtyEightPollObservation as FiveThirtyEightPollObservation,
    FredObservation as FredObservation,
    EiaObservation as EiaObservation,
    TreasuryRecord as TreasuryRecord,
    BlsObservation as BlsObservation,
    WorldBankObservation as WorldBankObservation,
    ImfDataMapperObservation as ImfDataMapperObservation,
    CensusRecord as CensusRecord,
    SocrataRecord as SocrataRecord,
    CkanDataset as CkanDataset,
    StooqPriceObservation as StooqPriceObservation,
    YahooFinancePriceObservation as YahooFinancePriceObservation,
    SecFiling as SecFiling,
    SecCompanyFact as SecCompanyFact,
)

from forecasting.sources.research_records import (
    ArxivPaper as ArxivPaper,
    OpenAlexWork as OpenAlexWork,
    CrossrefWork as CrossrefWork,
    PubMedArticle as PubMedArticle,
    WikipediaPage as WikipediaPage,
    WikimediaPageviewObservation as WikimediaPageviewObservation,
    ClinicalTrialStudy as ClinicalTrialStudy,
    OpenFdaDrugApplication as OpenFdaDrugApplication,
    OwidObservation as OwidObservation,
    WhoGhoObservation as WhoGhoObservation,
)

from forecasting.sources.technology_records import (
    GitHubRelease as GitHubRelease,
    GitHubRepositorySnapshot as GitHubRepositorySnapshot,
    GitHubIssue as GitHubIssue,
    GitHubCommit as GitHubCommit,
    GitHubWorkflowRun as GitHubWorkflowRun,
    PypiRelease as PypiRelease,
    NpmPackageVersion as NpmPackageVersion,
    NvdCve as NvdCve,
    CisaKevVulnerability as CisaKevVulnerability,
)

from forecasting.sources.market_records import (
    CoinGeckoMarketSnapshot as CoinGeckoMarketSnapshot,
    ManifoldMarketImport as ManifoldMarketImport,
    MetaculusQuestionImport as MetaculusQuestionImport,
    PolymarketMarketImport as PolymarketMarketImport,
    KalshiMarketImport as KalshiMarketImport,
)

from forecasting.sources.environment_records import (
    UsgsEarthquakeEvent as UsgsEarthquakeEvent,
    NasaEonetEvent as NasaEonetEvent,
    NwsAlert as NwsAlert,
    OpenMeteoDailyForecast as OpenMeteoDailyForecast,
    OpenMeteoAirQualityForecast as OpenMeteoAirQualityForecast,
    OpenMeteoHistoricalWeatherObservation as OpenMeteoHistoricalWeatherObservation,
    FemaDisasterDeclaration as FemaDisasterDeclaration,
)

from forecasting.sources import (
    eia as _eia,
    treasury as _treasury,
    bls as _bls,
    macroeconomic as _macroeconomic,
    census as _census,
    openalex as _openalex,
    crossref as _crossref,
    github_activity as _github_activity,
    github_repository as _github_repository,
    package_releases as _package_releases,
    openmeteo as _openmeteo,
    socrata as _socrata,
    ckan as _ckan,
    arxiv as _arxiv,
    pubmed as _pubmed,
    stooq as _stooq,
    yahoo as _yahoo,
    coingecko as _coingecko,
    hackernews as _hackernews,
    reddit as _reddit,
    bluesky as _bluesky,
    mastodon as _mastodon,
    nvd as _nvd,
    cisa_kev as _cisa_kev,
    usgs as _usgs,
    eonet as _eonet,
    nws as _nws,
    reliefweb as _reliefweb,
    federal_register as _federal_register,
    courtlistener as _courtlistener,
    clinicaltrials as _clinicaltrials,
    openfda as _openfda,
    owid as _owid,
    who_gho as _who_gho,
    fema as _fema,
    gdelt as _gdelt,
    fivethirtyeight as _fivethirtyeight,
    wikipedia as _wikipedia,
    wikimedia as _wikimedia,
    fred as _fred,
)

from forecasting.sources.eia import (
    _eia_endpoint as _eia_endpoint,
    _eia_observations_from_payload as _eia_observations_from_payload,
    _eia_legacy_series_rows as _eia_legacy_series_rows,
    _eia_period_to_iso as _eia_period_to_iso,
)

from forecasting.sources.treasury import (
    _treasury_endpoint as _treasury_endpoint,
    _treasury_records_from_payload as _treasury_records_from_payload,
    _treasury_value as _treasury_value,
    _treasury_date_to_iso as _treasury_date_to_iso,
)

from forecasting.sources.bls import (
    _bls_endpoint as _bls_endpoint,
    _bls_observation_date as _bls_observation_date,
)

from forecasting.sources.macroeconomic import (
    _worldbank_source_parts as _worldbank_source_parts,
    _worldbank_endpoint as _worldbank_endpoint,
    _worldbank_since_date as _worldbank_since_date,
    _worldbank_observation_date as _worldbank_observation_date,
    _imf_source_parts as _imf_source_parts,
    _imf_endpoint as _imf_endpoint,
    _imf_values_for as _imf_values_for,
    _imf_year_value_mapping as _imf_year_value_mapping,
    _imf_metadata_label as _imf_metadata_label,
    _dict_value_case_insensitive as _dict_value_case_insensitive,
)

from forecasting.sources.census import (
    _census_endpoint as _census_endpoint,
    _census_dataset_from_path as _census_dataset_from_path,
    _census_requires_api_key as _census_requires_api_key,
    _census_records_from_payload as _census_records_from_payload,
    _census_public_source_url as _census_public_source_url,
    _census_dataset_year as _census_dataset_year,
    _census_is_geography_header as _census_is_geography_header,
    _census_value as _census_value,
)

from forecasting.sources.values import (
    _first_present as _first_present,
    _optional_float as _optional_float,
    _optional_int as _optional_int,
    _optional_bool as _optional_bool,
    _optional_str as _optional_str,
    _collapse_ws as _collapse_ws,
    _collapse_optional as _collapse_optional,
    _list_get as _list_get,
)

from forecasting.sources.openalex import (
    _openalex_abstract as _openalex_abstract,
    _openalex_authors as _openalex_authors,
    _openalex_concepts as _openalex_concepts,
    _openalex_timestamp as _openalex_timestamp,
)

from forecasting.sources.crossref import (
    _crossref_first as _crossref_first,
    _crossref_string_list as _crossref_string_list,
    _crossref_authors as _crossref_authors,
    _crossref_published_at as _crossref_published_at,
    _crossref_date_parts as _crossref_date_parts,
    _crossref_timestamp as _crossref_timestamp,
)

from forecasting.sources.github_metadata import (
    _github_timestamp as _github_timestamp,
    _github_repo_parts as _github_repo_parts,
    _github_label_names as _github_label_names,
)

from forecasting.sources.openmeteo import (
    _openmeteo_coordinates as _openmeteo_coordinates,
    _openmeteo_history_request as _openmeteo_history_request,
    _openmeteo_history_date as _openmeteo_history_date,
    _openmeteo_date_to_iso as _openmeteo_date_to_iso,
    _openmeteo_time_to_iso as _openmeteo_time_to_iso,
    _openmeteo_daily_float as _openmeteo_daily_float,
    _openmeteo_hourly_float as _openmeteo_hourly_float,
)

from forecasting.sources.package_registry import (
    _pypi_package_name as _pypi_package_name,
    _pypi_project_endpoint as _pypi_project_endpoint,
    _pypi_upload_timestamp as _pypi_upload_timestamp,
    _pypi_yanked_reason as _pypi_yanked_reason,
    _npm_package_name as _npm_package_name,
    _npm_package_endpoint as _npm_package_endpoint,
    _npm_timestamp as _npm_timestamp,
    _npm_license as _npm_license,
    _npm_people as _npm_people,
    _npm_keywords as _npm_keywords,
    _npm_dependency_count as _npm_dependency_count,
)

from forecasting.sources.feeds import (
    _arxiv_entry_url as _arxiv_entry_url,
    _arxiv_pdf_url as _arxiv_pdf_url,
    _arxiv_id_from_entry_id as _arxiv_id_from_entry_id,
    _parse_rss_items as _parse_rss_items,
    _parse_atom_items as _parse_atom_items,
    _normalize_feed_timestamp as _normalize_feed_timestamp,
    _text as _text,
    _namespaced_text as _namespaced_text,
    _namespaced_find as _namespaced_find,
    _namespaced_findall as _namespaced_findall,
    _local_name as _local_name,
)

from forecasting.sources.socrata import (
    _socrata_endpoint as _socrata_endpoint,
    _socrata_dataset_id_from_path as _socrata_dataset_id_from_path,
    _socrata_public_source_url as _socrata_public_source_url,
    _socrata_timestamp as _socrata_timestamp,
)

from forecasting.sources.ckan import (
    _ckan_endpoint as _ckan_endpoint,
    _ckan_api_base as _ckan_api_base,
    _ckan_query_param as _ckan_query_param,
    _ckan_query_from_path as _ckan_query_from_path,
    _ckan_package_results as _ckan_package_results,
    _ckan_organization as _ckan_organization,
    _ckan_names as _ckan_names,
    _ckan_resources as _ckan_resources,
    _ckan_public_dataset_url as _ckan_public_dataset_url,
    _ckan_timestamp as _ckan_timestamp,
)

from forecasting.sources.pubmed import (
    _pubmed_normalize_source as _pubmed_normalize_source,
    _pubmed_search_endpoint as _pubmed_search_endpoint,
    _pubmed_fetch_endpoint as _pubmed_fetch_endpoint,
    _pubmed_fetch_base_url as _pubmed_fetch_base_url,
    _pubmed_search_pmids as _pubmed_search_pmids,
    _pubmed_descendants as _pubmed_descendants,
    _pubmed_first_descendant as _pubmed_first_descendant,
    _pubmed_text as _pubmed_text,
    _pubmed_published_at as _pubmed_published_at,
    _pubmed_date_to_iso as _pubmed_date_to_iso,
    _pubmed_month_number as _pubmed_month_number,
    _pubmed_day_number as _pubmed_day_number,
    _pubmed_abstract as _pubmed_abstract,
    _pubmed_journal as _pubmed_journal,
    _pubmed_authors as _pubmed_authors,
    _pubmed_publication_types as _pubmed_publication_types,
    _pubmed_doi as _pubmed_doi,
)

from forecasting.sources.yahoo import (
    _yahoo_symbol as _yahoo_symbol,
    _yahoo_interval as _yahoo_interval,
    _yahoo_range as _yahoo_range,
    _yahoo_chart_endpoint as _yahoo_chart_endpoint,
    _yahoo_chart_result as _yahoo_chart_result,
    _yahoo_series as _yahoo_series,
    _yahoo_timestamp as _yahoo_timestamp,
    _yahoo_optional_number as _yahoo_optional_number,
)

from forecasting.sources.stooq import (
    _stooq_interval as _stooq_interval,
    _stooq_endpoint as _stooq_endpoint,
    _stooq_column as _stooq_column,
    _stooq_optional_number as _stooq_optional_number,
)

from forecasting.sources.coingecko import (
    _coingecko_coin_ids as _coingecko_coin_ids,
    _coingecko_markets_endpoint as _coingecko_markets_endpoint,
    _coingecko_timestamp as _coingecko_timestamp,
    _coingecko_optional_number as _coingecko_optional_number,
)

from forecasting.sources.hackernews import (
    _hackernews_timestamp as _hackernews_timestamp,
    _hackernews_endpoint as _hackernews_endpoint,
    _hackernews_hits as _hackernews_hits,
)

from forecasting.sources.reddit import (
    _reddit_timestamp as _reddit_timestamp,
    _reddit_endpoint as _reddit_endpoint,
    _reddit_children as _reddit_children,
    _reddit_permalink as _reddit_permalink,
)

from forecasting.sources.bluesky import (
    _bluesky_timestamp as _bluesky_timestamp,
    _bluesky_endpoint as _bluesky_endpoint,
    _bluesky_posts as _bluesky_posts,
    _bluesky_post_url as _bluesky_post_url,
)

from forecasting.sources.mastodon import (
    _mastodon_timestamp as _mastodon_timestamp,
    _mastodon_endpoint as _mastodon_endpoint,
    _mastodon_source_parts as _mastodon_source_parts,
    _mastodon_status_rows as _mastodon_status_rows,
    _mastodon_tag_names as _mastodon_tag_names,
    _mastodon_content_text as _mastodon_content_text,
)

from forecasting.sources.nvd import (
    _nvd_timestamp as _nvd_timestamp,
    _nvd_description as _nvd_description,
    _nvd_references as _nvd_references,
    _nvd_cvss_summary as _nvd_cvss_summary,
)

from forecasting.sources.cisa_kev import (
    _cisa_kev_timestamp as _cisa_kev_timestamp,
    _cisa_kev_matches_query as _cisa_kev_matches_query,
    _cisa_kev_cwes as _cisa_kev_cwes,
)

from forecasting.sources.usgs import (
    _usgs_earthquake_endpoint as _usgs_earthquake_endpoint,
    _usgs_ms_to_iso as _usgs_ms_to_iso,
    _usgs_coordinates as _usgs_coordinates,
    _usgs_event_title as _usgs_event_title,
)

from forecasting.sources.eonet import (
    _eonet_endpoint as _eonet_endpoint,
    _eonet_timestamp as _eonet_timestamp,
    _eonet_latest_geometry as _eonet_latest_geometry,
    _eonet_categories as _eonet_categories,
    _eonet_source_names as _eonet_source_names,
    _eonet_source_urls as _eonet_source_urls,
    _eonet_first_coordinate as _eonet_first_coordinate,
)

from forecasting.sources.nws import (
    _nws_alerts_endpoint as _nws_alerts_endpoint,
    _nws_alert_timestamp as _nws_alert_timestamp,
    _looks_like_lat_lon as _looks_like_lat_lon,
)

from forecasting.sources.reliefweb import (
    _reliefweb_timestamp as _reliefweb_timestamp,
    _reliefweb_endpoint as _reliefweb_endpoint,
    _reliefweb_rows as _reliefweb_rows,
    _reliefweb_date as _reliefweb_date,
    _reliefweb_names as _reliefweb_names,
    _reliefweb_summary as _reliefweb_summary,
)

from forecasting.sources.federal_register import (
    _federalregister_timestamp as _federalregister_timestamp,
)

from forecasting.sources.courtlistener import (
    _courtlistener_timestamp as _courtlistener_timestamp,
    _courtlistener_endpoint as _courtlistener_endpoint,
    _courtlistener_result_url as _courtlistener_result_url,
    _courtlistener_citation as _courtlistener_citation,
)

from forecasting.sources.clinicaltrials import (
    _clinicaltrials_endpoint as _clinicaltrials_endpoint,
    _clinicaltrials_study_rows as _clinicaltrials_study_rows,
    _clinicaltrials_date_to_iso as _clinicaltrials_date_to_iso,
    _clinicaltrials_list as _clinicaltrials_list,
    _clinicaltrials_interventions as _clinicaltrials_interventions,
    _clinicaltrials_sponsors as _clinicaltrials_sponsors,
)

from forecasting.sources.openfda import (
    _openfda_endpoint as _openfda_endpoint,
    _openfda_search_query as _openfda_search_query,
    _looks_like_openfda_application_number as _looks_like_openfda_application_number,
    _openfda_application_rows as _openfda_application_rows,
    _openfda_date_to_iso as _openfda_date_to_iso,
    _openfda_latest_submission as _openfda_latest_submission,
    _openfda_list as _openfda_list,
    _openfda_product_values as _openfda_product_values,
    _openfda_active_ingredient_names as _openfda_active_ingredient_names,
    _openfda_unique as _openfda_unique,
    _openfda_application_url as _openfda_application_url,
)

from forecasting.sources.owid import (
    _owid_endpoint as _owid_endpoint,
    _owid_value_column as _owid_value_column,
    _owid_date_to_iso as _owid_date_to_iso,
)

from forecasting.sources.who_gho import (
    _who_gho_endpoint as _who_gho_endpoint,
    _who_gho_dimensions as _who_gho_dimensions,
    _who_gho_filter_expression as _who_gho_filter_expression,
    _who_gho_timestamp as _who_gho_timestamp,
)

from forecasting.sources.fema import (
    _fema_disaster_declarations_endpoint as _fema_disaster_declarations_endpoint,
    _fema_filter_expression as _fema_filter_expression,
    _fema_timestamp as _fema_timestamp,
)

from forecasting.sources.gdelt import (
    _gdelt_augmented_query as _gdelt_augmented_query,
    _gdelt_query_operator_value as _gdelt_query_operator_value,
    _gdelt_datetime_parameter as _gdelt_datetime_parameter,
    _gdelt_timestamp as _gdelt_timestamp,
)

from forecasting.sources.fivethirtyeight import (
    _fivethirtyeight_poll_endpoint as _fivethirtyeight_poll_endpoint,
    _fivethirtyeight_date as _fivethirtyeight_date,
    _fivethirtyeight_timestamp as _fivethirtyeight_timestamp,
    _fivethirtyeight_sample_size as _fivethirtyeight_sample_size,
)

from forecasting.sources.wikipedia import (
    _wikipedia_revision_text as _wikipedia_revision_text,
    _wikipedia_api_timestamp as _wikipedia_api_timestamp,
    _wikipedia_timestamp as _wikipedia_timestamp,
)

from forecasting.sources.wikimedia import (
    _wikimedia_pageview_source_parts as _wikimedia_pageview_source_parts,
    _wikimedia_pageviews_endpoint as _wikimedia_pageviews_endpoint,
    _wikimedia_pageview_date_param as _wikimedia_pageview_date_param,
    _wikimedia_pageview_timestamp as _wikimedia_pageview_timestamp,
    _wikimedia_pageview_count as _wikimedia_pageview_count,
)

from forecasting.sources.fred import (
    _fred_make_observation as _fred_make_observation,
    _parse_fred_series_page as _parse_fred_series_page,
    _fred_date_column as _fred_date_column,
    _fred_value_column as _fred_value_column,
)

from forecasting.sources.sec_parsing import (
    _sec_search_cik as _sec_search_cik,
    _sec_search_company as _sec_search_company,
    _sec_search_ticker as _sec_search_ticker,
    _sec_submissions_endpoint as _sec_submissions_endpoint,
    _sec_company_fact_unit_rows as _sec_company_fact_unit_rows,
    _sec_company_fact_filed_at as _sec_company_fact_filed_at,
    _sec_company_fact_fiscal_year as _sec_company_fact_fiscal_year,
    _sec_company_fact_value as _sec_company_fact_value,
    _sec_filing_timestamp as _sec_filing_timestamp,
    _sec_filing_url as _sec_filing_url,
    _sec_recent_row as _sec_recent_row,
)

from forecasting.sources.metaculus_parsing import (
    _metaculus_resolution_to_outcome as _metaculus_resolution_to_outcome,
    _metaculus_endpoint_for_source as _metaculus_endpoint_for_source,
    _metaculus_choices as _metaculus_choices,
    _metaculus_forecast_value as _metaculus_forecast_value,
    _metaculus_extract_prediction_value as _metaculus_extract_prediction_value,
    _metaculus_outcome_space as _metaculus_outcome_space,
    _metaculus_description as _metaculus_description,
    _metaculus_public_url as _metaculus_public_url,
    _metaculus_timestamp as _metaculus_timestamp,
    _metaculus_question_from_payload as _metaculus_question_from_payload,
    _metaculus_question_to_benchmark_case as _metaculus_question_to_benchmark_case,
)

from forecasting.sources.kalshi_parsing import (
    _kalshi_resolution_to_outcome as _kalshi_resolution_to_outcome,
    _kalshi_endpoint_for_source as _kalshi_endpoint_for_source,
    _kalshi_yes_probability as _kalshi_yes_probability,
    _kalshi_previous_yes_probability as _kalshi_previous_yes_probability,
    _kalshi_price as _kalshi_price,
    _kalshi_description as _kalshi_description,
    _kalshi_public_url as _kalshi_public_url,
    _kalshi_timestamp as _kalshi_timestamp,
    _kalshi_market_from_payload as _kalshi_market_from_payload,
    _kalshi_market_to_benchmark_case as _kalshi_market_to_benchmark_case,
)

from forecasting.sources.manifold_parsing import (
    _manifold_endpoint_for_source as _manifold_endpoint_for_source,
    _manifold_distribution as _manifold_distribution,
    _manifold_outcome_space as _manifold_outcome_space,
    _manifold_description as _manifold_description,
    _extract_rich_text as _extract_rich_text,
    _manifold_ms_to_iso as _manifold_ms_to_iso,
    _manifold_market_from_payload as _manifold_market_from_payload,
    _manifold_market_to_benchmark_case as _manifold_market_to_benchmark_case,
)

logger = logging.getLogger(__name__)


_SOURCE_ADAPTER_USER_AGENT = (
    "Mozilla/5.0 (compatible; SuperforecastingAgent/1.0; "
    "+https://github.com/teddyjfpender/superforecasting-agent)"
)
_FEED_ACCEPT_HEADER = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"
_JSON_ACCEPT_HEADER = "application/json, text/json;q=0.9, */*;q=0.5"
_TEXT_ACCEPT_HEADER = "text/plain, text/csv, text/html;q=0.8, */*;q=0.5"


# Bot-block / interstitial signatures. Detection runs over the first ~8 KB of a
# response body (case-folded) so we recognise a Cloudflare / DataDome / cookie
# / JS-required block page disguised as HTTP 200, instead of silently treating
# the block markup as evidence content. Patterns are short, very-low-FP, drawn
# from each vendor's standard interstitial text/markup.
_BLOCK_PAGE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cloudflare_challenge", (
        "just a moment...",
        "cf-browser-verification",
        "_cf_chl_",
        "challenge-platform",
        "cloudflare ray id",
        "attention required! | cloudflare",
        "checking your browser before accessing",
    )),
    ("akamai_bot_manager", ("pardon our interruption",)),
    ("datadome", ("datadome",)),
    ("perimeterx", ("perimeterx", "px-captcha")),
    ("imperva_incapsula", ("incapsula", "_incap_ses")),
    ("cookie_wall", ("please enable cookies", "enable cookies to continue")),
    ("js_required", (
        "please enable javascript",
        "javascript is required",
        "enable javascript to continue",
        "this site requires javascript",
    )),
    ("captcha", ("complete the captcha", "verify you are human")),
)


def detect_block_page(text: str, *, status: int | None = None) -> dict | None:
    """Return ``{reason, signal}`` when ``text`` looks like a bot-block / interstitial.

    Recognises Cloudflare challenges, DataDome / PerimeterX / Imperva walls,
    cookie / JavaScript-required pages, and generic CAPTCHAs disguised as HTTP
    200. Returns ``None`` for genuine content. Intentionally conservative — the
    matched ``signal`` is exposed so callers can audit a false positive.
    """

    if not text:
        return None
    snippet = text[:8192].lower()
    # Block pages are usually small; if the body is large and HTML-heavy, lower
    # confidence somewhat by requiring a stronger match. For now, the patterns
    # are specific enough (e.g. "cloudflare ray id") that any hit is reliable.
    for reason, keywords in _BLOCK_PAGE_PATTERNS:
        for keyword in keywords:
            if keyword in snippet:
                return {"reason": reason, "signal": keyword, "status": status}
    return None


def _source_fetch_timeout(default: float = 30.0) -> float:
    """Per-request timeout for source-adapter HTTP fetches (seconds).

    The previous fixed 10s was too tight for slow government endpoints (FRED,
    BLS, EIA, Treasury), which surfaced to the agent as spurious "FRED refresh
    timed out" messages and discouraged it from refreshing evidence. Default to
    a more forgiving 30s and let operators tune it via env var.
    """
    for name in (
        "SUPERFORECASTING_AGENT_SOURCE_TIMEOUT",
        "FORECAST_SOURCE_TIMEOUT",
        "HERMES_SOURCE_TIMEOUT",
    ):
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            continue
        value = _optional_float(raw)
        if value is not None and value > 0:
            return value
    return default


def load_news_feed_items(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    dedupe: bool = True,
) -> list[NewsFeedItem]:
    """Load RSS/Atom items from a URL or local XML file."""

    if limit <= 0:
        raise ValidationError("news import --limit must be positive")
    since_dt = timestamp_to_datetime(parse_timestamp(since, field_name="since")) if since else None
    include_terms = _normalize_feed_filter_terms(keywords)
    exclude_terms = _normalize_feed_filter_terms(exclude_keywords)
    try:
        root = ElementTree.fromstring(_read_feed_source(source))
    except ElementTree.ParseError as exc:
        raise ValidationError("news feed source is not valid XML") from exc
    items = _parse_rss_items(root) or _parse_atom_items(root)
    filtered: list[NewsFeedItem] = []
    seen: set[str] = set()
    for item in items:
        if since_dt is not None:
            item_dt = timestamp_to_datetime(item.published_at)
            if item_dt is None or item_dt < since_dt:
                continue
        if not _feed_item_matches_filters(item, include_terms, exclude_terms):
            continue
        if dedupe:
            dedupe_key = _feed_item_dedupe_key(item)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
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
    return _gdelt.load_gdelt_articles(
        query,
        limit=limit,
        since=since,
        timespan=timespan,
        source_country=source_country,
        source_lang=source_lang,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


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
    return _fivethirtyeight.load_fivethirtyeight_polls(
        source,
        limit=limit,
        since=since,
        state=state,
        candidate=candidate,
        pollster=pollster,
        cycle=cycle,
        office_type=office_type,
        api_base_url=api_base_url,
        _read_text_endpoint=_read_text_endpoint,
    )


def _fred_fetch_timeout() -> float:
    """Per-attempt timeout (seconds) for FRED fetches.

    Tighter than the general source timeout so a flaky FRED endpoint fails fast
    and the fallback chain (API → CSV → HTML) stays bounded instead of hanging
    for tens of seconds per series.
    """

    for name in ("SUPERFORECASTING_AGENT_FRED_TIMEOUT", "FORECAST_FRED_TIMEOUT", "HERMES_FRED_TIMEOUT"):
        raw = os.environ.get(name)
        if raw and raw.strip():
            value = _optional_float(raw)
            if value is not None and value > 0:
                return value
    return 12.0


def _load_fred_from_api(
    series_id: str, *, api_key: str, limit: int, since_date, timeout: float
) -> list[FredObservation]:
    """Official FRED API path — reliable JSON, used when FRED_API_KEY is set."""
    return _fred._load_fred_from_api(
        series_id,
        api_key=api_key,
        limit=limit,
        since_date=since_date,
        timeout=timeout,
        _read_json_endpoint=_read_json_endpoint,
    )


def _load_fred_from_csv(
    series_id: str, *, api_base_url: str, limit: int, since_date, timeout: float
) -> list[FredObservation]:
    """Public fredgraph.csv path (no key). Bounded by ``timeout``."""
    return _fred._load_fred_from_csv(
        series_id,
        api_base_url=api_base_url,
        limit=limit,
        since_date=since_date,
        timeout=timeout,
        _read_text_endpoint=_read_text_endpoint,
    )


def _load_fred_from_series_page(
    series_id: str, *, limit: int, since_date, timeout: float
) -> list[FredObservation]:
    return _fred._load_fred_from_series_page(
        series_id,
        limit=limit,
        since_date=since_date,
        timeout=timeout,
        _read_text_endpoint=_read_text_endpoint,
    )


# Newest-observation date is read from the first attribute present, preferring
# the explicit observation date over the derived publish timestamp.
_FRESHNESS_DATE_ATTRS = ("observation_date", "record_date", "published_at", "observation_period")


def assess_series_freshness(
    observations: list,
    *,
    as_of_reference=None,
    series_class: str = "daily",
    max_business_days: int | None = None,
    label: str | None = None,
) -> FreshnessAssessment:
    """Age the newest row of a loaded series via the missing-observation rule.

    ``observations`` is a list of loaded rows (``FredObservation``,
    ``EiaObservation``, ...) in the loaders' ascending order, so the newest is
    last. ``as_of_reference`` defaults to today (UTC). The result is ORDINARY
    (use the lagged-latest stamped with its OWN observation date — the honest
    reading of a T-1/T-2 daily feed), EXCESSIVE (treat as missing + flag
    staleness), or UNKNOWN (undated). See :func:`describe_missing_observation_rule`.
    """

    limit = resolve_max_business_days(series_class, explicit=max_business_days)
    if not observations:
        return FreshnessAssessment(
            status="unknown",
            lag_business_days=-1,
            as_of=None,
            max_business_days=limit,
            note=f"{label or 'series'}: no observations returned — empty, not merely lagged.",
        )
    newest = observations[-1]
    obs_date = None
    for attr in _FRESHNESS_DATE_ATTRS:
        candidate = getattr(newest, attr, None)
        if candidate:
            obs_date = candidate
            break
    reference = as_of_reference if as_of_reference is not None else datetime.now(timezone.utc).date()
    resolved_label = (
        label
        or getattr(newest, "series_id", None)
        or getattr(newest, "series_name", None)
        or getattr(newest, "dataset", None)
        or "series"
    )
    return assess_observation_freshness(
        obs_date,
        as_of_reference=reference,
        max_business_days=limit,
        label=str(resolved_label),
    )


def load_fred_observations(
    series_id: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://fred.stlouisfed.org/graph/fredgraph.csv",
    api_key: str | None = None,
) -> list[FredObservation]:
    """Load recent FRED observations as timestamped evidence rows.

    FRED endpoints are flaky from some networks — the ``fredgraph.csv`` graph
    endpoint can hang or return HTTP/2 stream errors while the official API or
    the series HTML page work, and vice-versa. To stay fast and reliable this
    tries a bounded fallback chain and never blocks for more than a few seconds
    per attempt:

    1. Official FRED API (``api.stlouisfed.org``) when ``FRED_API_KEY`` is set —
       the reliable path; get a free key at https://fred.stlouisfed.org/docs/api/api_key.html
    2. Public ``fredgraph.csv`` (no key).
    3. Series-page HTML latest-observation extraction (best effort).
    """

    normalized_series = series_id.strip()
    if not normalized_series:
        raise ValidationError("fred import series id is required")
    if limit <= 0:
        raise ValidationError("fred import --limit must be positive")
    since_date = _fred_date(since, field_name="since") if since else None
    timeout = _fred_fetch_timeout()
    key = (api_key or appconfig.secret("FRED_API_KEY") or "").strip()

    attempts: list[tuple[str, Any]] = []
    if key:
        attempts.append(("api", lambda: _load_fred_from_api(
            normalized_series, api_key=key, limit=limit, since_date=since_date, timeout=timeout)))
    attempts.append(("csv", lambda: _load_fred_from_csv(
        normalized_series, api_base_url=api_base_url, limit=limit, since_date=since_date, timeout=timeout)))
    attempts.append(("series-page", lambda: _load_fred_from_series_page(
        normalized_series, limit=limit, since_date=since_date, timeout=timeout)))

    errors: list[str] = []
    for label, attempt in attempts:
        try:
            observations = attempt()
        except ValidationError as exc:
            errors.append(f"{label}: {exc}")
            continue
        if observations:
            return observations
        errors.append(f"{label}: no observations returned")

    detail = "; ".join(errors)
    hint = "" if key else " Set FRED_API_KEY for the reliable official FRED API (free key)."
    raise ValidationError(f"fred observations unavailable for {normalized_series} ({detail}).{hint}")


def load_eia_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.eia.gov/series/",
    api_key: str | None = None,
) -> list[EiaObservation]:
    """Load EIA energy time-series observations as timestamped evidence rows.

    The EIA Open Data API (both the v1 ``/series/`` route and the current v2
    ``/v2/...`` routes) REQUIRES an ``api_key`` query parameter. A keyless
    request is rejected with HTTP 403 ``{"error":{"code":"API_KEY_MISSING"}}`` —
    so rather than pass that bare 403 through, we fail fast BEFORE the request
    with a teaching error naming ``EIA_API_KEY`` and the free registration URL.
    The key is read from the ``api_key`` argument or the ``EIA_API_KEY`` env var
    and injected when the caller's endpoint does not already carry one. Prefer
    FRED for energy series (``GASREGW`` gasoline, ``DCOILWTICO`` crude), which
    serve the same numbers keyless.
    """
    return _eia.load_eia_observations(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        api_key=api_key,
        _read_json_endpoint=_read_json_endpoint,
    )


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
    return _treasury.load_treasury_records(
        source,
        limit=limit,
        since=since,
        date_field=date_field,
        value_field=value_field,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


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
    return _bls.load_bls_observations(
        series_id,
        limit=limit,
        since=since,
        start_year=start_year,
        end_year=end_year,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_worldbank_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.worldbank.org/v2",
) -> list[WorldBankObservation]:
    """Load World Bank country indicator observations as timestamped evidence rows."""
    return _macroeconomic.load_worldbank_observations(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_imf_datamapper_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://www.imf.org/external/datamapper/api/v1",
) -> list[ImfDataMapperObservation]:
    """Load IMF DataMapper country indicator observations as timestamped evidence rows."""
    return _macroeconomic.load_imf_datamapper_observations(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_census_records(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.census.gov/data",
    api_key: str | None = None,
) -> list[CensusRecord]:
    """Load U.S. Census API rows as timestamped demographic or regional evidence."""
    return _census.load_census_records(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        api_key=api_key,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_socrata_records(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://{domain}/resource/{dataset_id}.json",
) -> list[SocrataRecord]:
    """Load Socrata open-data portal rows as timestamped evidence."""
    return _socrata.load_socrata_records(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_ckan_datasets(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://{domain}/api/3/action/package_search",
) -> list[CkanDataset]:
    """Load CKAN open-data package metadata as timestamped evidence."""
    return _ckan.load_ckan_datasets(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_stooq_prices(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    interval: str = "d",
    api_base_url: str = "https://stooq.com/q/d/l/",
) -> list[StooqPriceObservation]:
    """Load Stooq historical price CSV rows as timestamped evidence."""
    return _stooq.load_stooq_prices(
        source,
        limit=limit,
        since=since,
        interval=interval,
        api_base_url=api_base_url,
        _read_text_endpoint=_read_text_endpoint,
    )


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
    return _yahoo.load_yahoo_finance_prices(
        source,
        limit=limit,
        since=since,
        range_value=range_value,
        interval=interval,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


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
    payload = _read_json_endpoint(endpoint, "sec submissions", headers=_sec_request_headers())
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
    payload = _read_json_endpoint(endpoint, "sec company facts", headers=_sec_request_headers())
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


def load_sec_full_text_search(
    source: str,
    *,
    forms: str | None = None,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://efts.sec.gov/LATEST/search-index",
) -> list[SecFiling]:
    """Search EDGAR full-text (EFTS) for filings matching a query.

    ``source`` is the search query (a deal name, product, dollar figure, …).
    Returns SecFiling rows pointing at the matching primary documents so the
    agent can open the primary source to confirm a value that XBRL/company-facts
    do not expose. ``forms`` optionally restricts to comma-separated form types
    (e.g. ``8-K,10-Q``).
    """
    query = source.strip()
    for prefix in ("sec_search:", "secsearch:", "sec-search:"):
        if query.lower().startswith(prefix):
            query = query[len(prefix):].strip()
            break
    if not query:
        raise ValidationError("sec_search source must be a non-empty query")
    if limit <= 0:
        raise ValidationError("sec_search import --limit must be positive")

    params: dict[str, str] = {"q": query}
    if forms and forms.strip():
        params["forms"] = forms.strip()
    if since:
        since_dt = timestamp_to_datetime(parse_timestamp(since, field_name="since"))
        if since_dt is not None:
            params["startdt"] = since_dt.date().isoformat()
            params["enddt"] = datetime.now(timezone.utc).date().isoformat()

    url = f"{api_base_url.rstrip('/')}?{urlencode(params)}"
    payload = _read_json_endpoint(url, "sec full-text search", headers=_sec_request_headers())
    if not isinstance(payload, dict):
        raise ValidationError("sec full-text search response must be a JSON object")
    hits = payload.get("hits")
    hit_rows = hits.get("hits") if isinstance(hits, dict) else None
    if not isinstance(hit_rows, list):
        raise ValidationError("sec full-text search response must contain hits.hits")

    rows: list[SecFiling] = []
    for hit in hit_rows:
        if not isinstance(hit, dict):
            continue
        sec_id = _optional_str(hit.get("_id")) or ""
        accession, _, document = sec_id.partition(":")
        src = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
        cik = _sec_search_cik(src)
        if not cik or not accession:
            continue
        form = _optional_str(src.get("root_form")) or _optional_str(src.get("form")) or "UNKNOWN"
        filing_date = _optional_str(src.get("file_date")) or ""
        if not filing_date:
            continue
        published_at = _sec_filing_timestamp(None, filing_date)
        rows.append(
            SecFiling(
                cik=cik,
                company_name=_sec_search_company(src),
                ticker=_sec_search_ticker(src),
                form=form,
                filing_date=filing_date,
                report_date=None,
                acceptance_time=None,
                published_at=published_at,
                accession_number=accession,
                primary_document=document or None,
                description=_optional_str(src.get("file_description")) or _optional_str(src.get("file_type")),
                source_url=_sec_filing_url(cik, accession, document or None),
                source_name="SEC EDGAR Full-Text Search",
                # Document-specific: one accession can return several matching
                # exhibits (distinct documents), each a different primary source.
                # Keying on accession alone would dedupe them away on import.
                entry_id=f"{cik}:{sec_id}",
                raw={"query": query, "hit": hit},
            )
        )
    # Preserve EFTS relevance order (most relevant first) — the point of full-
    # text search is to surface the filing that best matches the query, not the
    # most recent. Truncate after collecting the full page.
    return rows[:limit]


def load_arxiv_papers(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://export.arxiv.org/api/query",
) -> list[ArxivPaper]:
    """Load recent arXiv API papers as timestamped evidence rows."""
    return _arxiv.load_arxiv_papers(
        query,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_text_endpoint=_read_text_endpoint,
    )


def load_openalex_works(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.openalex.org/works",
) -> list[OpenAlexWork]:
    """Load OpenAlex scholarly works as timestamped research evidence."""
    return _openalex.load_openalex_works(
        query,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_crossref_works(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.crossref.org/works",
) -> list[CrossrefWork]:
    """Load Crossref works as timestamped DOI/scholarly evidence."""
    return _crossref.load_crossref_works(
        query,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_pubmed_articles(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
) -> list[PubMedArticle]:
    """Load PubMed articles as timestamped biomedical evidence."""
    return _pubmed.load_pubmed_articles(
        query,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
        _read_text_endpoint=_read_text_endpoint,
    )


def load_wikipedia_pages(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    as_of: str | None = None,
    api_base_url: str = "https://en.wikipedia.org/w/api.php",
) -> list[WikipediaPage]:
    """Load Wikipedia/MediaWiki pages as timestamped reference evidence.

    When ``as_of`` is ``None`` (the default), behaviour is UNCHANGED: the live
    intro extract and latest-revision timestamp are returned. When ``as_of`` is
    set (the backtest path), each page is pinned to the NEWEST revision whose
    timestamp is ``<= as_of`` via the MediaWiki revisions API
    (``prop=revisions&rvstart=<as_of>&rvlimit=1&rvdir=older``); the page text is
    taken from that historical revision and ``updated_at`` is set to the revision
    timestamp so the resulting evidence's ``available_at`` predates the cutoff
    (no Sub-type-B time travel).
    """
    return _wikipedia.load_wikipedia_pages(
        query,
        limit=limit,
        since=since,
        as_of=as_of,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
        _wikipedia_revision_as_of=_wikipedia_revision_as_of,
    )


def _wikipedia_revision_as_of(
    *,
    page_id: str | None,
    title: str,
    as_of: str,
    endpoint_base: str,
) -> dict[str, object] | None:
    """Resolve the newest revision of a page dated ``<= as_of``.

    Returns ``{"timestamp", "revid", "extract"}`` for that revision, or ``None``
    when the page has no revision at-or-before ``as_of`` (i.e. it did not yet
    exist). Network access goes through the same JSON client the module already
    uses, so tests mock it the same way.
    """
    return _wikipedia._wikipedia_revision_as_of(
        page_id=page_id,
        title=title,
        as_of=as_of,
        endpoint_base=endpoint_base,
        _read_json_endpoint=_read_json_endpoint,
    )


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
    return _wikimedia.load_wikimedia_pageviews(
        source,
        limit=limit,
        since=since,
        access=access,
        agent=agent,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
        _wikimedia_today_utc=_wikimedia_today_utc,
    )


def load_github_releases(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.github.com",
) -> list[GitHubRelease]:
    """Load GitHub repository releases as timestamped software evidence."""
    return _github_activity.load_github_releases(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_github_repository_snapshots(
    source: str,
    *,
    limit: int = 1,
    since: str | None = None,
    api_base_url: str = "https://api.github.com",
) -> list[GitHubRepositorySnapshot]:
    """Load a GitHub repository metadata snapshot as software adoption evidence."""
    return _github_repository.load_github_repository_snapshots(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_github_issues(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    state: str = "all",
    api_base_url: str = "https://api.github.com",
) -> list[GitHubIssue]:
    """Load GitHub repository issues and pull requests as timestamped software evidence."""
    return _github_activity.load_github_issues(
        source,
        limit=limit,
        since=since,
        state=state,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_github_commits(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.github.com",
) -> list[GitHubCommit]:
    """Load GitHub repository commits as timestamped software activity evidence."""
    return _github_activity.load_github_commits(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_github_workflow_runs(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.github.com",
) -> list[GitHubWorkflowRun]:
    """Load GitHub Actions workflow runs as timestamped operational evidence."""
    return _github_activity.load_github_workflow_runs(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_coingecko_market_snapshots(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    vs_currency: str = "usd",
    api_base_url: str = "https://api.coingecko.com/api/v3/coins/markets",
) -> list[CoinGeckoMarketSnapshot]:
    """Load CoinGecko market snapshots as timestamped crypto market evidence."""
    return _coingecko.load_coingecko_market_snapshots(
        source,
        limit=limit,
        since=since,
        vs_currency=vs_currency,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_pypi_releases(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://pypi.org/pypi",
) -> list[PypiRelease]:
    """Load PyPI package releases as timestamped software ecosystem evidence."""
    return _package_releases.load_pypi_releases(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_npm_package_versions(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://registry.npmjs.org",
) -> list[NpmPackageVersion]:
    """Load npm package versions as timestamped software ecosystem evidence."""
    return _package_releases.load_npm_package_versions(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_hackernews_items(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://hn.algolia.com/api/v1/search_by_date",
) -> list[HackerNewsItem]:
    """Load Hacker News search results as timestamped public-attention evidence."""
    return _hackernews.load_hackernews_items(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_reddit_posts(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://www.reddit.com/search.json",
) -> list[RedditPost]:
    """Load Reddit search results as timestamped public-attention evidence."""
    return _reddit.load_reddit_posts(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


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
    return _bluesky.load_bluesky_posts(
        source,
        limit=limit,
        since=since,
        sort=sort,
        author=author,
        lang=lang,
        link_domain=link_domain,
        url_filter=url_filter,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_mastodon_statuses(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    local: bool = False,
    only_media: bool = False,
    api_base_url: str = "https://mastodon.social/api/v1/timelines/tag",
) -> list[MastodonStatus]:
    """Load Mastodon hashtag timeline statuses as timestamped public-attention evidence."""
    return _mastodon.load_mastodon_statuses(
        source,
        limit=limit,
        since=since,
        local=local,
        only_media=only_media,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_reliefweb_reports(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    appname: str | None = None,
    api_base_url: str = "https://api.reliefweb.int/v1/reports",
) -> list[ReliefWebReport]:
    """Load ReliefWeb reports as humanitarian/disaster evidence."""
    return _reliefweb.load_reliefweb_reports(
        query,
        limit=limit,
        since=since,
        appname=appname,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_federal_register_documents(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://www.federalregister.gov/api/v1/documents.json",
) -> list[FederalRegisterDocument]:
    """Load Federal Register documents as timestamped policy evidence."""
    return _federal_register.load_federal_register_documents(
        query,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_courtlistener_search_results(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    search_type: str = "o",
    api_base_url: str = "https://www.courtlistener.com/api/rest/v4/search/",
) -> list[CourtListenerSearchResult]:
    """Load CourtListener search results as timestamped legal evidence."""
    return _courtlistener.load_courtlistener_search_results(
        source,
        limit=limit,
        since=since,
        search_type=search_type,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_nvd_cves(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://services.nvd.nist.gov/rest/json/cves/2.0",
) -> list[NvdCve]:
    """Load NVD CVE records as timestamped security evidence."""
    return _nvd.load_nvd_cves(
        query,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_cisa_kev_vulnerabilities(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
) -> list[CisaKevVulnerability]:
    """Load CISA Known Exploited Vulnerabilities records as security evidence."""
    return _cisa_kev.load_cisa_kev_vulnerabilities(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_usgs_earthquakes(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://earthquake.usgs.gov/fdsnws/event/1/query",
) -> list[UsgsEarthquakeEvent]:
    """Load USGS earthquake GeoJSON events as timestamped geophysical evidence."""
    return _usgs.load_usgs_earthquakes(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_nasa_eonet_events(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://eonet.gsfc.nasa.gov/api/v3/events",
) -> list[NasaEonetEvent]:
    """Load NASA EONET natural events as timestamped hazard evidence."""
    return _eonet.load_nasa_eonet_events(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_nws_alerts(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.weather.gov/alerts/active",
) -> list[NwsAlert]:
    """Load National Weather Service active alerts as timestamped operational evidence."""
    return _nws.load_nws_alerts(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_clinicaltrials_studies(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://clinicaltrials.gov/api/v2/studies",
) -> list[ClinicalTrialStudy]:
    """Load ClinicalTrials.gov studies as timestamped health/biotech evidence."""
    return _clinicaltrials.load_clinicaltrials_studies(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_openfda_drug_applications(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.fda.gov/drug/drugsfda.json",
) -> list[OpenFdaDrugApplication]:
    """Load openFDA Drugs@FDA application records as regulatory evidence."""
    return _openfda.load_openfda_drug_applications(
        source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_openmeteo_daily_forecasts(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    forecast_days: int = 7,
    api_base_url: str = "https://api.open-meteo.com/v1/forecast",
) -> list[OpenMeteoDailyForecast]:
    """Load Open-Meteo daily forecast rows as weather evidence."""
    return _openmeteo.load_openmeteo_daily_forecasts(
        source,
        limit=limit,
        since=since,
        forecast_days=forecast_days,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_openmeteo_air_quality_forecasts(
    source: str,
    *,
    limit: int = 24,
    since: str | None = None,
    forecast_days: int = 5,
    api_base_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality",
) -> list[OpenMeteoAirQualityForecast]:
    """Load Open-Meteo hourly air-quality forecast rows as evidence."""
    return _openmeteo.load_openmeteo_air_quality_forecasts(
        source,
        limit=limit,
        since=since,
        forecast_days=forecast_days,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


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
    return _openmeteo.load_openmeteo_historical_weather(
        source,
        limit=limit,
        since=since,
        start_date=start_date,
        end_date=end_date,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


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
    return _owid.load_owid_observations(
        source,
        limit=limit,
        since=since,
        entity=entity,
        value_column=value_column,
        api_base_url=api_base_url,
        _read_text_endpoint=_read_text_endpoint,
    )


def load_who_gho_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    country: str | None = None,
    dimensions: dict[str, str] | list[str] | None = None,
    api_base_url: str = "https://ghoapi.azureedge.net/api",
) -> list[WhoGhoObservation]:
    """Load WHO Global Health Observatory indicator rows as evidence."""
    return _who_gho.load_who_gho_observations(
        source,
        limit=limit,
        since=since,
        country=country,
        dimensions=dimensions,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


def load_fema_disaster_declarations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    state: str | None = None,
    incident_type: str | None = None,
    declaration_type: str | None = None,
    api_base_url: str = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries",
) -> list[FemaDisasterDeclaration]:
    """Load OpenFEMA Disaster Declarations Summaries v2 rows as evidence."""
    return _fema.load_fema_disaster_declarations(
        source,
        limit=limit,
        since=since,
        state=state,
        incident_type=incident_type,
        declaration_type=declaration_type,
        api_base_url=api_base_url,
        _read_json_endpoint=_read_json_endpoint,
    )


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
        rows = next((payload[key] for key in ('results', 'questions', 'data')
                     if isinstance(payload.get(key), list)), None)
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


def load_polymarket_market(
    source: str,
    *,
    api_base_url: str = "https://gamma-api.polymarket.com",
) -> PolymarketMarketImport:
    """Load a single Polymarket Gamma market by URL, API URL, id, or slug."""

    if not source.strip():
        raise ValidationError("polymarket import source is required")
    # Try the market endpoint(s) first, then the EVENT fallbacks — the data plane
    # orders them so a source that already resolved as a market keeps hitting the
    # SAME endpoint first (identical payload → identical watch signature), while a
    # bare event slug / numeric event id / event-page URL now resolves instead of
    # raising a validation miss.
    payload = None
    for endpoint in _polymarket_endpoint_candidates(source.strip(), api_base_url=api_base_url):
        payload = _polymarket_first_market(_read_json_endpoint(endpoint, "polymarket market"))
        if payload is None and "condition_ids=" in endpoint and "closed=" not in endpoint:
            # Gamma's default ``condition_ids`` view is OPEN-only, so a SETTLED
            # market (exactly what RESOLUTION needs to read) comes back empty on
            # the first call. Re-query explicitly for closed markets to recover
            # its terminal ``outcomePrices``.
            closed_endpoint = f"{endpoint}&{urlencode({'closed': 'true'})}"
            payload = _polymarket_first_market(_read_json_endpoint(closed_endpoint, "polymarket market (closed)"))
        if payload is not None:
            break
    if payload is None:
        raise ValidationError("polymarket market response did not include any markets")

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
        rows = next((payload[key] for key in ('markets', 'results', 'data')
                     if isinstance(payload.get(key), list)), None)
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


def _read_feed_source(source: str) -> bytes:
    if source.startswith(("http://", "https://")):
        parsed = urlparse(source)
        if not parsed.netloc:
            raise ValidationError("news feed URL is invalid")
        request = Request(source, headers=_source_request_headers(source, accept=_FEED_ACCEPT_HEADER))
        try:
            with urlopen(request, timeout=_source_fetch_timeout()) as response:
                return response.read(2 * 1024 * 1024)
        except HTTPError as exc:
            raise ValidationError(_http_fetch_error("news feed", source, exc)) from exc
        except OSError as exc:
            raise ValidationError(f"news feed fetch failed for {source}: {exc}") from exc
    path = Path(source).expanduser()
    if not path.is_file():
        raise ValidationError(f"news feed source not found: {source}")
    return path.read_bytes()


def _normalize_feed_filter_terms(values: list[str] | None) -> list[str]:
    terms: list[str] = []
    for value in values or []:
        for chunk in str(value).split(","):
            term = chunk.strip().lower()
            if term and term not in terms:
                terms.append(term)
    return terms


def _feed_item_matches_filters(
    item: NewsFeedItem,
    include_terms: list[str],
    exclude_terms: list[str],
) -> bool:
    haystack = " ".join(
        value
        for value in (
            item.title,
            item.summary,
            item.url or "",
            item.source_name or "",
            item.entry_id or "",
        )
        if value
    ).lower()
    if include_terms and not any(term in haystack for term in include_terms):
        return False
    if exclude_terms and any(term in haystack for term in exclude_terms):
        return False
    return True


def _feed_item_dedupe_key(item: NewsFeedItem) -> str:
    if item.url:
        return f"url:{_canonical_feed_url(item.url)}"
    if item.entry_id:
        return f"id:{item.entry_id.strip().lower()}"
    title = re.sub(r"\s+", " ", item.title.strip().lower())
    return f"title:{title}:{item.published_at or ''}"


def _canonical_feed_url(value: str) -> str:
    raw = value.strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.lower()
    query_pairs = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query=urlencode(query_pairs, doseq=True),
        fragment="",
    ).geturl()


def _source_request_headers(url: str, *, accept: str) -> dict[str, str]:
    headers = {
        "User-Agent": _SOURCE_ADAPTER_USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    parsed = urlparse(url)
    if parsed.netloc.lower().endswith("bls.gov"):
        headers["Referer"] = "https://www.bls.gov/"
    return headers


def _http_fetch_error(label: str, url: str, exc: HTTPError) -> str:
    status = getattr(exc, "code", None)
    parsed = urlparse(url)
    host = parsed.netloc or url
    message = f"{label} fetch failed for {host}: HTTP {status or exc}"
    if status == 403:
        if host.lower().endswith("sec.gov"):
            message += (
                "; SEC EDGAR enforces its fair-access policy and rejects requests without a valid "
                "contact in the User-Agent. Set SEC_CONTACT_EMAIL (or SUPERFORECASTING_AGENT_CONTACT / "
                "FORECAST_CONTACT_EMAIL / HERMES_CONTACT_EMAIL) to a real email and retry."
            )
        else:
            message += (
                "; the source denied this runtime after a browser-compatible request. "
                "Keep the forecast probability unchanged, try the official structured adapter if available, "
                "or rerun from a network allowed by the source."
            )
    return message


def _read_json_endpoint(
    url: str, label: str, *, timeout: float | None = None, headers: dict[str, str] | None = None
) -> object:
    try:
        request = Request(url, headers=headers or _source_request_headers(url, accept=_JSON_ACCEPT_HEADER))
        with urlopen(request, timeout=timeout or _source_fetch_timeout()) as response:
            data = response.read(2 * 1024 * 1024)
    except HTTPError as exc:
        raise ValidationError(_http_fetch_error(label, url, exc)) from exc
    except OSError as exc:
        raise ValidationError(f"{label} fetch failed: {exc}") from exc
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{label} response is not valid JSON") from exc


def _read_text_endpoint(url: str, label: str, *, timeout: float | None = None) -> str:
    try:
        request = Request(url, headers=_source_request_headers(url, accept=_TEXT_ACCEPT_HEADER))
        with urlopen(request, timeout=timeout or _source_fetch_timeout()) as response:
            data = response.read(2 * 1024 * 1024)
    except HTTPError as exc:
        raise ValidationError(_http_fetch_error(label, url, exc)) from exc
    except OSError as exc:
        raise ValidationError(f"{label} fetch failed: {exc}") from exc
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{label} response is not valid UTF-8 text") from exc


# --- SEC EDGAR fair-access identity + ticker/company → CIK resolution ------

_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_TICKERS_TTL_SECONDS = 7 * 24 * 3600


def _sec_user_agent() -> str:
    """SEC EDGAR fair-access User-Agent.

    SEC requires an honest, identifying User-Agent (declared name + a contact)
    and actively blocks generic browser-spoofing strings. We declare the app
    and a contact taken from a configurable env var so operators can set their
    own per SEC's fair-access policy; the default carries the project URL.
    """
    for name in (
        "SEC_CONTACT_EMAIL",
        "SUPERFORECASTING_AGENT_CONTACT",
        "FORECAST_CONTACT_EMAIL",
        "HERMES_CONTACT_EMAIL",
    ):
        # Drop control/non-printable chars so a stray CR/LF in the env var can't
        # corrupt the header (it would otherwise crash the fetch at send time).
        contact = "".join(ch for ch in os.environ.get(name, "").strip() if ch.isprintable())
        if contact:
            # SEC's prescribed fair-access form is "<name> <contact>", space-
            # separated with a bare email — its WAF 403s the parenthetical "(...)"
            # and "+url" forms, so do NOT wrap the contact in parentheses.
            return f"Superforecasting Agent {contact}"
    # No contact configured: a bare declared UA SEC accepts (verified). Set one of
    # the *_CONTACT_EMAIL env vars to a real email for full fair-access compliance.
    return "Superforecasting Agent/1.0"


def _sec_request_headers(*, accept: str = _JSON_ACCEPT_HEADER) -> dict[str, str]:
    """Headers for SEC endpoints — uses the fair-access User-Agent, not the
    generic browser-compatible one (which SEC 403s)."""
    return {
        "User-Agent": _sec_user_agent(),
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    }


def _sec_tickers_cache_path() -> Path | None:
    try:
        from superforecasting_agent.constants import get_agent_home

        cache_dir = get_agent_home() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "sec_company_tickers.json"
    except Exception:
        return None


def _load_sec_company_tickers() -> dict:
    """SEC's ticker→CIK→title map, cached on disk with a 7-day TTL."""
    cache = _sec_tickers_cache_path()
    if cache and cache.is_file():
        try:
            if time.time() - cache.stat().st_mtime < _SEC_TICKERS_TTL_SECONDS:
                data = json.loads(cache.read_text("utf-8"))
                # Validate the cached shape too — a corrupt/poisoned non-dict
                # must fall through to a refetch, not crash the resolver.
                if isinstance(data, dict):
                    return data
        except (OSError, ValueError):  # ValueError covers JSONDecodeError
            pass
    payload = _read_json_endpoint(_SEC_TICKERS_URL, "sec company tickers", headers=_sec_request_headers())
    if not isinstance(payload, dict):
        raise ValidationError("sec company_tickers response must be a JSON object")
    if cache:
        # Write atomically so concurrent imports never see a half-written file
        # and an interrupted write can't reset the TTL on corrupt content.
        try:
            tmp = cache.with_name(f"{cache.name}.tmp.{os.getpid()}")
            tmp.write_text(json.dumps(payload), "utf-8")
            os.replace(tmp, cache)
        except OSError:
            try:
                cache.with_name(f"{cache.name}.tmp.{os.getpid()}").unlink(missing_ok=True)
            except OSError:
                pass
    return payload


def _resolve_sec_cik(raw: str) -> str:
    """Resolve a ticker (preferred) or company name to a 10-digit CIK."""
    needle = raw.strip()
    if not needle:
        raise ValidationError("sec source must be a CIK, ticker, or company name")
    rows = [row for row in _load_sec_company_tickers().values() if isinstance(row, dict)]
    upper = needle.upper()
    lower = needle.lower()

    for row in rows:  # 1) exact ticker — most precise
        if str(row.get("ticker", "")).upper() == upper:
            return str(row.get("cik_str", "")).zfill(10)

    exact = [row for row in rows if str(row.get("title", "")).lower() == lower]
    matches = exact or [row for row in rows if lower in str(row.get("title", "")).lower()]
    if len(matches) == 1:
        row = matches[0]
        if not exact:
            # Resolved by a non-exact substring match — surface it so a wrong
            # single-container match is debuggable (exact ticker/title win first).
            logger.info(
                "sec source %r fuzzy-matched company %r (CIK %s); pass the ticker or numeric CIK to disambiguate",
                raw,
                row.get("title"),
                str(row.get("cik_str", "")).zfill(10),
            )
        return str(row.get("cik_str", "")).zfill(10)
    if len(matches) > 1:
        sample = ", ".join(str(r.get("ticker") or r.get("title")) for r in matches[:5])
        raise ValidationError(
            f"sec source {raw!r} is ambiguous ({len(matches)} matches: {sample}); use the ticker or a numeric CIK"
        )
    raise ValidationError(
        f"sec source {raw!r} did not match a ticker or company; use a numeric CIK (e.g. 0000320193)"
    )


def _sec_cik(source: str) -> str:
    raw = source.strip()
    if raw.startswith("sec:"):
        raw = raw.split(":", 1)[1].strip()
    if not raw:
        raise ValidationError("sec source must be a CIK, ticker, or company name")
    # Strip an explicit CIK literal (CIK0000320193 / CIK 320193 / cik-320193)
    # ONLY when it is "CIK" followed by digits — never blindly chop a 3-char
    # prefix, which would mangle real tickers/names beginning with "CIK".
    cik_literal = re.match(r"(?i)^cik[-\s]*(\d+)$", raw)
    if cik_literal:
        raw = cik_literal.group(1)
    # A bare numeric value is a CIK; anything else is a ticker or company name
    # to resolve through SEC's company_tickers map.
    if raw.isdigit():
        if not 0 < int(raw) <= 9_999_999_999:
            raise ValidationError("sec CIK must be a positive number with at most 10 digits")
        return raw.zfill(10)
    return _resolve_sec_cik(raw)


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


# Venue id-form routing lives in the PM data plane (forecasting.pm.polymarket) —
# ONE Polymarket truth shared by this watched-source adapter and the resolution
# reader. These thin wrappers keep the ``sa.``-prefixed names the tests pin and
# translate the data plane's ``ValueError`` into this module's ``ValidationError``.
_polymarket_is_condition_id = _pm_polymarket.is_condition_id


def _polymarket_endpoint_candidates(source: str, *, api_base_url: str) -> list[str]:
    """Ordered Gamma endpoints for any id form (market slug/id/conditionId first,
    then the event fallbacks). See ``pm.polymarket.market_endpoint_candidates``."""
    try:
        return _pm_polymarket.market_endpoint_candidates(source, gamma_base=api_base_url)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def _polymarket_endpoint_for_source(source: str, *, api_base_url: str) -> str:
    """The PRIMARY (market) endpoint for a source — first of the candidate list."""
    return _polymarket_endpoint_candidates(source, api_base_url=api_base_url)[0]


def _polymarket_first_market(payload: object) -> dict | None:
    """The first market dict from a Gamma ``/markets`` response, or None when the
    response carried no market. Accepts the three shapes Gamma returns: a bare
    market list, a ``{"markets": [...]}`` envelope, or a single market object."""
    if isinstance(payload, list):
        return next((item for item in payload if isinstance(item, dict)), None)
    if isinstance(payload, dict):
        markets = payload.get("markets")
        if isinstance(markets, list):
            return next((item for item in markets if isinstance(item, dict)), None)
        return payload
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


def _wikimedia_today_utc():
    from datetime import datetime

    return datetime.now(timezone.utc).date()
