"""Command-line interface for forecast ledger workflows."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from forecasting.agent_protocol import (
    AGENT_PROTOCOL_METHOD,
    AGENT_PROTOCOL_PROMPT_VERSION,
    agent_protocol_binary_probability,
)
from forecasting.backtesting import (
    DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM,
    DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM,
    build_backtest_performance_summaries,
    build_forecasting_evidence_status,
)
from forecasting.benchmarks import list_builtin_benchmarks, load_builtin_benchmark
from forecasting.branding import (
    CLI_SURFACE,
    CORE_PRIMITIVE,
    DEMOTED_SURFACES,
    DESK_TITLE,
    FORK_CONTEXT_DOC,
    FORK_PRD_DOC,
    KEEP_SURFACES,
    NORTH_STAR,
    PRODUCT_NAME,
    PRODUCT_SLUG,
)
from forecasting.dashboard import build_dashboard_summary, render_dashboard_text
from forecasting.ensembles import (
    bayesian_binary_update,
    linear_trend_projection,
    weighted_binary_probability,
)
from forecasting.extensions import extension_registry
from forecasting.forecast_engine import forecast_engine_binary_probability
from forecasting.learning import apply_active_lesson_adjustments
from forecasting.ledger import ForecastLedger, WATCH_SOURCE_TYPES
from forecasting.models import (
    ASSUMPTION_STATUSES,
    CALIBRATION_LESSON_STATUSES,
    EVIDENCE_CLAIM_TYPES,
    REFERENCE_CLASS_STATUSES,
    ForecastingError,
    OutcomeSpace,
    json_dumps,
    json_loads,
    parse_timestamp,
    timestamp_to_datetime,
    utc_now_iso,
)
from forecasting.protocol import PROTOCOL_STAGES, build_protocol_messages
from forecasting.source_adapters import (
    load_arxiv_papers,
    load_bluesky_posts,
    load_bls_observations,
    load_census_records,
    load_cisa_kev_vulnerabilities,
    load_clinicaltrials_studies,
    load_coingecko_market_snapshots,
    load_courtlistener_search_results,
    load_crossref_works,
    load_eia_observations,
    load_federal_register_documents,
    load_fema_disaster_declarations,
    load_fivethirtyeight_polls,
    load_fred_observations,
    load_gdelt_articles,
    load_github_commits,
    load_github_workflow_runs,
    load_hackernews_items,
    load_github_issues,
    load_github_releases,
    load_kalshi_market,
    load_kalshi_resolved_binary_cases,
    load_manifold_market,
    load_manifold_resolved_binary_cases,
    load_metaculus_question,
    load_metaculus_resolved_binary_cases,
    load_mastodon_statuses,
    load_news_feed_items,
    load_npm_package_versions,
    load_nvd_cves,
    load_nasa_eonet_events,
    load_nws_alerts,
    load_openfda_drug_applications,
    load_openmeteo_air_quality_forecasts,
    load_openmeteo_daily_forecasts,
    load_openmeteo_historical_weather,
    load_openalex_works,
    load_owid_observations,
    load_pubmed_articles,
    load_pypi_releases,
    load_reddit_posts,
    load_reliefweb_reports,
    load_sec_company_facts,
    load_polymarket_market,
    load_sec_filings,
    load_socrata_records,
    load_stooq_prices,
    load_treasury_records,
    load_usgs_earthquakes,
    load_wikipedia_pages,
    load_wikimedia_pageviews,
    load_who_gho_observations,
    load_worldbank_observations,
    load_yahoo_finance_prices,
)

SOURCE_ADAPTER_GUIDES: list[dict[str, str]] = [
    {
        "name": "news",
        "domain": "RSS/Atom news",
        "import_command": "forecast import news <rss-or-atom-url> --question <id>",
        "watch_prefix": "rss:<feed-url>",
    },
    {
        "name": "gdelt",
        "domain": "global news search",
        "import_command": 'forecast import gdelt "<query>" --question <id>',
        "watch_prefix": "gdelt:<query>",
    },
    {
        "name": "fivethirtyeight",
        "domain": "election and public-opinion polls",
        "import_command": "forecast import fivethirtyeight <dataset-or-url> --question <id>",
        "watch_prefix": "fivethirtyeight:<dataset-or-url>",
    },
    {
        "name": "data",
        "domain": "generic CSV/JSON rows",
        "import_command": "forecast import data <csv-or-json-url-or-file> --question <id>",
        "watch_prefix": "file:<path> or url:<url>",
    },
    {
        "name": "owid",
        "domain": "public indicator data",
        "import_command": 'forecast import owid <grapher-slug> --entity "<entity>" --question <id>',
        "watch_prefix": "owid:<grapher-slug>",
    },
    {
        "name": "whogho",
        "domain": "global health indicator data",
        "import_command": "forecast import whogho <indicator-code> --country <ISO3> --question <id>",
        "watch_prefix": "whogho:<indicator-code>",
    },
    {
        "name": "fema",
        "domain": "US disaster declarations",
        "import_command": "forecast import fema <state|disaster-number|query> --question <id>",
        "watch_prefix": "fema:<state|disaster-number|query>",
    },
    {
        "name": "openmeteo",
        "domain": "daily weather forecasts",
        "import_command": "forecast import openmeteo <lat,lon> --question <id>",
        "watch_prefix": "openmeteo:<lat,lon>",
    },
    {
        "name": "airquality",
        "domain": "hourly air-quality forecasts",
        "import_command": "forecast import airquality <lat,lon> --question <id>",
        "watch_prefix": "airquality:<lat,lon>",
    },
    {
        "name": "weatherhistory",
        "domain": "historical daily weather observations",
        "import_command": "forecast import weatherhistory <lat,lon> --start-date <date> --end-date <date> --question <id>",
        "watch_prefix": "weatherhistory:<lat,lon>?start=<date>&end=<date>",
    },
    {
        "name": "usgs",
        "domain": "earthquake events",
        "import_command": 'forecast import usgs "<query>" --question <id>',
        "watch_prefix": "usgs:<query>",
    },
    {
        "name": "eonet",
        "domain": "natural hazard events",
        "import_command": 'forecast import eonet "<query-or-category>" --question <id>',
        "watch_prefix": "eonet:<query-or-category>",
    },
    {
        "name": "nws",
        "domain": "US weather alerts",
        "import_command": 'forecast import nws "<area-or-point-or-query>" --question <id>',
        "watch_prefix": "nws:<area-or-point-or-query>",
    },
    {
        "name": "clinicaltrials",
        "domain": "clinical trials",
        "import_command": 'forecast import clinicaltrials "<query-or-NCT-id>" --question <id>',
        "watch_prefix": "clinicaltrials:<query-or-NCT-id>",
    },
    {
        "name": "openfda",
        "domain": "FDA drug applications",
        "import_command": 'forecast import openfda "<query-or-application-number>" --question <id>',
        "watch_prefix": "openfda:<query-or-application-number>",
    },
    {
        "name": "pubmed",
        "domain": "biomedical literature",
        "import_command": 'forecast import pubmed "<query-or-PMID>" --question <id>',
        "watch_prefix": "pubmed:<query-or-PMID>",
    },
    {
        "name": "fred",
        "domain": "US economic time series",
        "import_command": "forecast import fred <series-id> --question <id>",
        "watch_prefix": "fred:<series-id>",
    },
    {
        "name": "eia",
        "domain": "energy time series",
        "import_command": "forecast import eia <series-id-or-api-url> --question <id>",
        "watch_prefix": "eia:<series-id-or-api-url>",
    },
    {
        "name": "treasury",
        "domain": "US Treasury fiscal data",
        "import_command": "forecast import treasury <dataset-path-or-api-url> --question <id>",
        "watch_prefix": "treasury:<dataset-path-or-api-url>",
    },
    {
        "name": "bls",
        "domain": "US labor/economic series",
        "import_command": "forecast import bls <series-id> --question <id>",
        "watch_prefix": "bls:<series-id>",
    },
    {
        "name": "worldbank",
        "domain": "country indicators",
        "import_command": "forecast import worldbank <country>/<indicator> --question <id>",
        "watch_prefix": "worldbank:<country>/<indicator>",
    },
    {
        "name": "census",
        "domain": "US demographic and regional data",
        "import_command": "forecast import census <dataset-path?get=...&for=...> --question <id>",
        "watch_prefix": "census:<dataset-path?get=...&for=...>",
    },
    {
        "name": "socrata",
        "domain": "open-data portal rows",
        "import_command": "forecast import socrata <domain>/<dataset-id> --question <id>",
        "watch_prefix": "socrata:<domain>/<dataset-id>",
    },
    {
        "name": "stooq",
        "domain": "market price history",
        "import_command": "forecast import stooq <symbol-or-csv-url> --question <id>",
        "watch_prefix": "stooq:<symbol-or-csv-url>",
    },
    {
        "name": "yahoo",
        "domain": "multi-asset market chart data",
        "import_command": "forecast import yahoo <symbol> --question <id>",
        "watch_prefix": "yahoo:<symbol>",
    },
    {
        "name": "coingecko",
        "domain": "crypto market snapshots",
        "import_command": "forecast import coingecko <coin-id-or-list> --question <id>",
        "watch_prefix": "coingecko:<coin-id>",
    },
    {
        "name": "sec",
        "domain": "company filings",
        "import_command": "forecast import sec <cik-or-ticker> --question <id>",
        "watch_prefix": "sec:<cik-or-ticker>",
    },
    {
        "name": "secfacts",
        "domain": "company fundamentals/XBRL facts",
        "import_command": "forecast import secfacts <cik>/<concept> --question <id>",
        "watch_prefix": "secfacts:<cik>/<concept>",
    },
    {
        "name": "federalregister",
        "domain": "US policy/regulatory documents",
        "import_command": 'forecast import federalregister "<query>" --question <id>',
        "watch_prefix": "federalregister:<query>",
    },
    {
        "name": "courtlistener",
        "domain": "US legal opinions and docket search",
        "import_command": 'forecast import courtlistener "<query>" --question <id>',
        "watch_prefix": "courtlistener:<query>",
    },
    {
        "name": "nvd",
        "domain": "security vulnerabilities",
        "import_command": 'forecast import nvd "<keyword-or-CVE>" --question <id>',
        "watch_prefix": "nvd:<keyword-or-CVE>",
    },
    {
        "name": "cisakev",
        "domain": "known exploited vulnerabilities",
        "import_command": 'forecast import cisakev "<keyword-or-CVE-or-all>" --question <id>',
        "watch_prefix": "cisakev:<keyword-or-CVE-or-all>",
    },
    {
        "name": "arxiv",
        "domain": "research papers",
        "import_command": 'forecast import arxiv "<query>" --question <id>',
        "watch_prefix": "arxiv:<query>",
    },
    {
        "name": "openalex",
        "domain": "scholarly works",
        "import_command": 'forecast import openalex "<query>" --question <id>',
        "watch_prefix": "openalex:<query>",
    },
    {
        "name": "crossref",
        "domain": "DOI and scholarly metadata",
        "import_command": 'forecast import crossref "<query-or-DOI>" --question <id>',
        "watch_prefix": "crossref:<query-or-DOI>",
    },
    {
        "name": "wikipedia",
        "domain": "reference pages",
        "import_command": 'forecast import wikipedia "<query>" --question <id>',
        "watch_prefix": "wikipedia:<query>",
    },
    {
        "name": "wikipediapageviews",
        "domain": "public attention/pageviews",
        "import_command": "forecast import wikipediapageviews <project>/<article> --question <id>",
        "watch_prefix": "wikipediapageviews:<project>/<article>",
    },
    {
        "name": "github",
        "domain": "repository releases",
        "import_command": "forecast import github <owner/repo> --question <id>",
        "watch_prefix": "github:<owner/repo>",
    },
    {
        "name": "githubissues",
        "domain": "repository issues and pull requests",
        "import_command": "forecast import githubissues <owner/repo> --question <id>",
        "watch_prefix": "githubissues:<owner/repo>",
    },
    {
        "name": "githubcommits",
        "domain": "repository commit activity",
        "import_command": "forecast import githubcommits <owner/repo> --question <id>",
        "watch_prefix": "githubcommits:<owner/repo>",
    },
    {
        "name": "githubactions",
        "domain": "repository workflow runs",
        "import_command": "forecast import githubactions <owner/repo> --question <id>",
        "watch_prefix": "githubactions:<owner/repo>",
    },
    {
        "name": "pypi",
        "domain": "Python package releases",
        "import_command": "forecast import pypi <package> --question <id>",
        "watch_prefix": "pypi:<package>",
    },
    {
        "name": "npm",
        "domain": "JavaScript package versions",
        "import_command": "forecast import npm <package> --question <id>",
        "watch_prefix": "npm:<package>",
    },
    {
        "name": "hackernews",
        "domain": "technical news and public attention",
        "import_command": 'forecast import hackernews "<query>" --question <id>',
        "watch_prefix": "hackernews:<query>",
    },
    {
        "name": "reddit",
        "domain": "public discussion and attention",
        "import_command": 'forecast import reddit "<query>" --question <id>',
        "watch_prefix": "reddit:<query>",
    },
    {
        "name": "bluesky",
        "domain": "public social posts and attention",
        "import_command": 'forecast import bluesky "<query>" --question <id>',
        "watch_prefix": "bluesky:<query>",
    },
    {
        "name": "mastodon",
        "domain": "Fediverse hashtag timelines",
        "import_command": "forecast import mastodon <tag-or-instance/tag> --question <id>",
        "watch_prefix": "mastodon:<tag-or-instance/tag>",
    },
    {
        "name": "reliefweb",
        "domain": "humanitarian/disaster reports",
        "import_command": 'forecast import reliefweb "<query>" --question <id>',
        "watch_prefix": "reliefweb:<query>",
    },
    {
        "name": "markets",
        "domain": "crowd/market priors",
        "import_command": "forecast import manifold|metaculus|polymarket|kalshi <market> --question <id>",
        "watch_prefix": "<market>:<market-id-or-url>",
    },
]


def register_cli(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the top-level ``forecast`` command namespace."""

    parser = subparsers.add_parser(
        CLI_SURFACE,
        help="Run the Superforecasting Agent forecast desk",
        description=(
            "Superforecasting Agent: create, update, review, resolve, score, "
            "and export auditable forecast records."
        ),
    )
    parser.add_argument(
        "--db",
        help="Override forecast ledger database path (for tests or isolated runs)",
    )
    parser.set_defaults(func=cmd_forecast)

    forecast_sub = parser.add_subparsers(dest="forecast_command")

    about_parser = forecast_sub.add_parser("about", help="Show fork identity and forecast-first scope")
    about_parser.set_defaults(_forecast_handler=_cmd_about)

    status_parser = forecast_sub.add_parser("status", help="Show forecast desk operational status")
    status_parser.add_argument("--json", action="store_true", help="Emit machine-readable status JSON")
    status_parser.set_defaults(_forecast_handler=_cmd_status)

    sources_parser = forecast_sub.add_parser("sources", help="List forecast evidence source adapters")
    sources_parser.add_argument("--json", action="store_true", help="Emit machine-readable adapter guidance")
    sources_parser.set_defaults(_forecast_handler=_cmd_sources)

    new_parser = forecast_sub.add_parser("new", help="Create a scoreable forecast question")
    new_parser.add_argument("title")
    new_parser.add_argument("--description", default="")
    new_parser.add_argument("--resolution-criteria", required=True)
    new_parser.add_argument("--resolution-source")
    new_parser.add_argument(
        "--outcome-type",
        choices=["binary", "categorical", "numeric", "distribution"],
        default="binary",
    )
    new_parser.add_argument("--choice", dest="choices", action="append", default=[])
    new_parser.add_argument("--unit", dest="units")
    new_parser.add_argument("--bound", dest="bounds", type=float, action="append", default=[])
    new_parser.add_argument("--close-time")
    new_parser.add_argument("--resolution-time")
    new_parser.add_argument("--tag", dest="tags", action="append", default=[])
    new_parser.add_argument("--domain")
    new_parser.add_argument("--topic", dest="topics", action="append", default=[])
    new_parser.add_argument("--owner")
    new_parser.add_argument("--impact")
    new_parser.add_argument("--review-cadence")
    new_parser.add_argument("--next-review-at")
    new_parser.set_defaults(_forecast_handler=_cmd_new)

    list_parser = forecast_sub.add_parser("list", help="List forecast questions")
    list_parser.add_argument("--status", choices=["active", "closed", "resolved", "archived"])
    list_parser.add_argument("--domain")
    list_parser.add_argument("--limit", type=int)
    list_parser.set_defaults(_forecast_handler=_cmd_list)

    show_parser = forecast_sub.add_parser("show", help="Show a forecast question")
    show_parser.add_argument("id")
    show_parser.set_defaults(_forecast_handler=_cmd_show)

    update_parser = forecast_sub.add_parser("update", help="Append a forecast snapshot")
    update_parser.add_argument("id")
    update_parser.add_argument("--probability", type=float)
    update_parser.add_argument("--numeric-value", type=float)
    update_parser.add_argument(
        "--distribution-json",
        help="JSON object mapping categorical outcomes to probabilities",
    )
    update_parser.add_argument("--rationale", required=True)
    update_parser.add_argument("--as-of")
    update_parser.add_argument("--confidence", type=float)
    update_parser.add_argument("--method")
    update_parser.add_argument("--component-json", default="{}")
    update_parser.add_argument("--assumption", dest="key_assumptions", action="append", default=[])
    update_parser.add_argument("--assumption-ref", dest="assumption_refs", action="append", default=[])
    update_parser.add_argument("--reference-class-ref", dest="reference_class_refs", action="append", default=[])
    update_parser.add_argument("--evidence-ref", dest="evidence_refs", action="append", default=[])
    update_parser.add_argument("--stale-evidence-days", type=int, default=30)
    update_parser.add_argument("--ack-stale-evidence", action="store_true")
    update_parser.add_argument(
        "--require-citations",
        action="store_true",
        help="Require at least one evidence, model, reference-class, source-snapshot, assumption, or lesson ref",
    )
    update_parser.add_argument("--model-run-ref", dest="model_run_refs", action="append", default=[])
    update_parser.add_argument(
        "--origin",
        dest="forecast_origin",
        choices=["live", "backtest", "imported_baseline"],
        default="live",
    )
    update_parser.add_argument("--agent-model")
    update_parser.add_argument("--prompt-version")
    update_parser.add_argument("--protocol-version")
    update_parser.add_argument("--toolset-version")
    update_parser.add_argument("--source-snapshot-ref", dest="source_snapshot_refs", action="append", default=[])
    update_parser.add_argument("--evidence-cutoff")
    update_parser.add_argument("--backtest-run-id")
    update_parser.add_argument("--calibration-ineligible", action="store_true")
    update_parser.add_argument("--calibration-weight", type=float, default=1.0)
    update_parser.add_argument("--calibration-lesson-ref", dest="calibration_lesson_refs", action="append", default=[])
    update_parser.add_argument("--calibration-adjustment-json", default="{}")
    update_parser.add_argument(
        "--use-active-lessons",
        action="store_true",
        help=(
            "Attach active global/domain/topic/question-type calibration lessons "
            "and apply supported probability adjustments."
        ),
    )
    update_parser.add_argument("--preview", action="store_true", help="Show update preview without writing a snapshot")
    update_parser.set_defaults(_forecast_handler=_cmd_update)

    ingest_parser = forecast_sub.add_parser(
        "ingest",
        help="Capture a URL, file, or note as external forecast context",
    )
    ingest_parser.add_argument("source", nargs="?")
    ingest_parser.add_argument("--question", dest="question_id")
    ingest_parser.add_argument("--title")
    ingest_parser.add_argument("--resolution-criteria")
    ingest_parser.add_argument("--resolution-source")
    ingest_parser.add_argument("--close-time")
    ingest_parser.add_argument("--resolution-time")
    ingest_parser.add_argument("--list", action="store_true")
    ingest_parser.add_argument("--show")
    ingest_parser.add_argument("--confirm")
    ingest_parser.add_argument("--domain")
    ingest_parser.add_argument("--tag", dest="tags", action="append", default=[])
    ingest_parser.add_argument("--topic", dest="topics", action="append", default=[])
    ingest_parser.add_argument("--claim", default="")
    ingest_parser.add_argument("--claim-type", choices=sorted(EVIDENCE_CLAIM_TYPES), default="fact")
    ingest_parser.add_argument("--summary", default="")
    ingest_parser.add_argument("--available-at")
    ingest_parser.add_argument("--published-at")
    ingest_parser.add_argument("--source-name")
    ingest_parser.add_argument("--source-type")
    ingest_parser.add_argument("--dry-run", action="store_true")
    ingest_parser.set_defaults(_forecast_handler=_cmd_ingest)

    import_parser = forecast_sub.add_parser(
        "import",
        help="Run an optional source adapter without making it the core workflow",
    )
    import_sub = import_parser.add_subparsers(dest="import_kind")
    for name in (
        "metaculus",
        "market",
        "manifold",
        "polymarket",
        "kalshi",
        "benchmark",
        "tournament",
        "news",
        "data",
        "gdelt",
        "fivethirtyeight",
        "github",
        "githubissues",
        "githubcommits",
        "githubactions",
        "pypi",
        "npm",
        "hackernews",
        "reddit",
        "bluesky",
        "mastodon",
        "reliefweb",
        "federalregister",
        "courtlistener",
        "nvd",
        "cisakev",
        "openmeteo",
        "airquality",
        "weatherhistory",
        "usgs",
        "eonet",
        "nws",
        "clinicaltrials",
        "openfda",
        "pubmed",
        "owid",
        "whogho",
        "fema",
        "fred",
        "eia",
        "treasury",
        "bls",
        "worldbank",
        "census",
        "socrata",
        "stooq",
        "yahoo",
        "coingecko",
        "sec",
        "secfacts",
        "arxiv",
        "openalex",
        "crossref",
        "wikipedia",
        "wikipediapageviews",
    ):
        adapter = import_sub.add_parser(name, help=f"Capture {name} context")
        adapter.add_argument("source")
        adapter.add_argument("--question", dest="question_id")
        adapter.add_argument("--title")
        if name in {"benchmark", "tournament"}:
            adapter.add_argument("--name")
            adapter.add_argument("--description")
            adapter.add_argument("--limit", type=int, default=100)
        if name == "benchmark":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.manifold.markets/v0",
                help="Override API base URL for benchmark adapters such as manifold:resolved, metaculus:resolved, or kalshi:resolved",
            )
        if name == "manifold":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.manifold.markets/v0",
                help="Override Manifold API base URL for tests or private mirrors",
            )
        if name == "metaculus":
            adapter.add_argument(
                "--api-base-url",
                default="https://www.metaculus.com/api",
                help="Override Metaculus API base URL for tests or private mirrors",
            )
        if name == "polymarket":
            adapter.add_argument(
                "--api-base-url",
                default="https://gamma-api.polymarket.com",
                help="Override Polymarket Gamma API base URL for tests or private mirrors",
            )
        if name == "kalshi":
            adapter.add_argument(
                "--api-base-url",
                default="https://external-api.kalshi.com/trade-api/v2",
                help="Override Kalshi Trade API base URL for tests or private mirrors",
            )
        if name in {
            "news",
            "data",
            "gdelt",
            "fivethirtyeight",
            "github",
            "githubissues",
            "githubcommits",
            "githubactions",
            "pypi",
            "npm",
            "hackernews",
            "reddit",
            "bluesky",
            "mastodon",
            "reliefweb",
            "federalregister",
            "courtlistener",
            "nvd",
            "cisakev",
            "openmeteo",
            "airquality",
            "weatherhistory",
            "usgs",
            "eonet",
            "nws",
            "clinicaltrials",
            "openfda",
            "pubmed",
            "owid",
            "whogho",
            "fema",
            "fred",
            "eia",
            "treasury",
            "bls",
            "worldbank",
            "census",
            "socrata",
            "stooq",
            "yahoo",
            "coingecko",
            "sec",
            "secfacts",
            "arxiv",
            "openalex",
            "crossref",
            "wikipedia",
            "wikipediapageviews",
        }:
            adapter.add_argument("--limit", type=int, default=10)
            adapter.add_argument("--since")
            default_claim_type = "estimate" if name in {"fivethirtyeight", "openmeteo", "airquality"} else "fact"
            adapter.add_argument("--claim-type", choices=sorted(EVIDENCE_CLAIM_TYPES), default=default_claim_type)
            adapter.add_argument("--reliability", type=float)
            adapter.add_argument("--relevance", type=float)
        if name == "gdelt":
            adapter.add_argument("--timespan", help="GDELT timespan such as 24h, 7d, or 1month")
            adapter.add_argument("--source-country", help="Limit to a GDELT sourcecountry query operator")
            adapter.add_argument("--source-lang", help="Limit to a GDELT sourcelang query operator")
            adapter.add_argument(
                "--api-base-url",
                default="https://api.gdeltproject.org/api/v2/doc/doc",
                help="Override GDELT DOC API base URL for tests or private mirrors",
            )
        if name == "fivethirtyeight":
            adapter.add_argument("--state", help="Filter polls by state or seat name")
            adapter.add_argument("--candidate", help="Filter polls by candidate/answer substring")
            adapter.add_argument("--pollster", help="Filter polls by pollster substring")
            adapter.add_argument("--cycle", type=int, help="Filter polls by election cycle")
            adapter.add_argument("--office-type", help="Filter polls by office_type")
            adapter.add_argument(
                "--api-base-url",
                default="https://projects.fivethirtyeight.com/polls-page/data",
                help="Override FiveThirtyEight polling CSV base URL or endpoint template for tests or private mirrors",
            )
        if name == "github":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.github.com",
                help="Override GitHub API base URL for tests or private mirrors",
            )
        if name == "githubissues":
            adapter.add_argument("--state", choices=["open", "closed", "all"], default="all")
            adapter.add_argument(
                "--api-base-url",
                default="https://api.github.com",
                help="Override GitHub API base URL for tests or private mirrors",
            )
        if name == "githubcommits":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.github.com",
                help="Override GitHub API base URL for tests or private mirrors",
            )
        if name == "githubactions":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.github.com",
                help="Override GitHub API base URL for tests or private mirrors",
            )
        if name == "pypi":
            adapter.add_argument(
                "--api-base-url",
                default="https://pypi.org/pypi",
                help="Override PyPI JSON API base URL for tests or private mirrors",
            )
        if name == "npm":
            adapter.add_argument(
                "--api-base-url",
                default="https://registry.npmjs.org",
                help="Override npm registry API base URL for tests or private mirrors",
            )
        if name == "hackernews":
            adapter.add_argument(
                "--api-base-url",
                default="https://hn.algolia.com/api/v1/search_by_date",
                help="Override Hacker News Algolia API endpoint for tests or private mirrors",
            )
        if name == "reddit":
            adapter.add_argument(
                "--api-base-url",
                default="https://www.reddit.com/search.json",
                help="Override Reddit JSON search endpoint for tests or private mirrors",
            )
        if name == "bluesky":
            adapter.add_argument("--sort", choices=["latest", "top"], default="latest")
            adapter.add_argument("--author", help="Filter Bluesky search to an author handle or DID")
            adapter.add_argument("--lang", help="Filter Bluesky search by BCP-47 language code")
            adapter.add_argument("--link-domain", help="Filter Bluesky posts by linked domain")
            adapter.add_argument("--url-filter", help="Filter Bluesky posts by linked URL")
            adapter.add_argument(
                "--api-base-url",
                default="https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts",
                help="Override Bluesky public search endpoint for tests or private mirrors",
            )
        if name == "mastodon":
            adapter.add_argument("--local", action="store_true", help="Request only local statuses from the instance")
            adapter.add_argument("--only-media", action="store_true", help="Request only statuses with media")
            adapter.add_argument(
                "--api-base-url",
                default="https://mastodon.social/api/v1/timelines/tag",
                help="Override Mastodon hashtag timeline endpoint for tests or private mirrors",
            )
        if name == "reliefweb":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.reliefweb.int/v1/reports",
                help="Override ReliefWeb reports API endpoint for tests or private mirrors",
            )
            adapter.add_argument(
                "--appname",
                help="ReliefWeb API appname; defaults to RELIEFWEB_APPNAME or superforecasting-agent",
            )
        if name == "federalregister":
            adapter.add_argument(
                "--api-base-url",
                default="https://www.federalregister.gov/api/v1/documents.json",
                help="Override Federal Register API endpoint for tests or private mirrors",
            )
        if name == "courtlistener":
            adapter.add_argument("--search-type", default="o", help="CourtListener search type, defaulting to opinions")
            adapter.add_argument(
                "--api-base-url",
                default="https://www.courtlistener.com/api/rest/v4/search/",
                help="Override CourtListener search API endpoint for tests or private mirrors",
            )
        if name == "nvd":
            adapter.add_argument(
                "--api-base-url",
                default="https://services.nvd.nist.gov/rest/json/cves/2.0",
                help="Override NVD CVE API endpoint for tests or private mirrors",
            )
        if name == "cisakev":
            adapter.add_argument(
                "--api-base-url",
                default="https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
                help="Override CISA KEV catalog endpoint for tests or private mirrors",
            )
        if name == "openmeteo":
            adapter.add_argument("--forecast-days", type=int, default=7)
            adapter.add_argument(
                "--api-base-url",
                default="https://api.open-meteo.com/v1/forecast",
                help="Override Open-Meteo forecast API endpoint for tests or private mirrors",
            )
        if name == "airquality":
            adapter.add_argument("--forecast-days", type=int, default=5)
            adapter.add_argument(
                "--api-base-url",
                default="https://air-quality-api.open-meteo.com/v1/air-quality",
                help="Override Open-Meteo Air Quality API endpoint for tests or private mirrors",
            )
        if name == "weatherhistory":
            adapter.add_argument("--start-date")
            adapter.add_argument("--end-date")
            adapter.add_argument(
                "--api-base-url",
                default="https://archive-api.open-meteo.com/v1/archive",
                help="Override Open-Meteo Historical Weather API endpoint for tests or private mirrors",
            )
        if name == "usgs":
            adapter.add_argument(
                "--api-base-url",
                default="https://earthquake.usgs.gov/fdsnws/event/1/query",
                help="Override USGS earthquake event API endpoint for tests or private mirrors",
            )
        if name == "eonet":
            adapter.add_argument(
                "--api-base-url",
                default="https://eonet.gsfc.nasa.gov/api/v3/events",
                help="Override NASA EONET events API endpoint for tests or private mirrors",
            )
        if name == "nws":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.weather.gov/alerts/active",
                help="Override National Weather Service active alerts API endpoint for tests or private mirrors",
            )
        if name == "clinicaltrials":
            adapter.add_argument(
                "--api-base-url",
                default="https://clinicaltrials.gov/api/v2/studies",
                help="Override ClinicalTrials.gov studies API endpoint for tests or private mirrors",
            )
        if name == "openfda":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.fda.gov/drug/drugsfda.json",
                help="Override openFDA Drugs@FDA API endpoint for tests or private mirrors",
            )
        if name == "pubmed":
            adapter.add_argument(
                "--api-base-url",
                default="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                help="Override PubMed E-utilities search endpoint for tests or private mirrors",
            )
        if name == "owid":
            adapter.add_argument("--entity", help="Filter Our World in Data grapher rows by Entity")
            adapter.add_argument("--value-column", help="Override the OWID value column to import")
            adapter.add_argument(
                "--api-base-url",
                default="https://ourworldindata.org/grapher",
                help="Override Our World in Data grapher base URL for tests or private mirrors",
            )
        if name == "whogho":
            adapter.add_argument("--country", help="Filter WHO GHO rows by SpatialDim ISO3 country code")
            adapter.add_argument(
                "--dimension",
                action="append",
                default=[],
                help="Add a WHO GHO OData dimension filter as KEY=VALUE; can be repeated",
            )
            adapter.add_argument(
                "--api-base-url",
                default="https://ghoapi.azureedge.net/api",
                help="Override WHO GHO OData API base URL for tests or private mirrors",
            )
        if name == "fema":
            adapter.add_argument("--state", help="Filter FEMA declarations by two-letter state code")
            adapter.add_argument("--incident-type", help="Filter FEMA declarations by incident type, such as Fire or Hurricane")
            adapter.add_argument("--declaration-type", help="Filter FEMA declarations by declaration type, such as DR or EM")
            adapter.add_argument(
                "--api-base-url",
                default="https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries",
                help="Override OpenFEMA Disaster Declarations endpoint for tests or private mirrors",
            )
        if name == "fred":
            adapter.add_argument(
                "--api-base-url",
                default="https://fred.stlouisfed.org/graph/fredgraph.csv",
                help="Override FRED CSV endpoint for tests or private mirrors",
            )
        if name == "eia":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.eia.gov/series/",
                help="Override EIA API endpoint or endpoint template for tests or private mirrors",
            )
        if name == "treasury":
            adapter.add_argument("--date-field", default="record_date")
            adapter.add_argument("--value-field", help="Treasury Fiscal Data field to use as the primary value")
            adapter.add_argument(
                "--api-base-url",
                default="https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
                help="Override Treasury Fiscal Data API base URL or endpoint template for tests or private mirrors",
            )
        if name == "bls":
            adapter.add_argument("--start-year", type=int)
            adapter.add_argument("--end-year", type=int)
            adapter.add_argument(
                "--api-base-url",
                default="https://api.bls.gov/publicAPI/v2/timeseries/data",
                help="Override BLS public API base URL for tests or private mirrors",
            )
        if name == "worldbank":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.worldbank.org/v2",
                help="Override World Bank API base URL for tests or private mirrors",
            )
        if name == "census":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.census.gov/data",
                help="Override U.S. Census API base URL for tests or private mirrors",
            )
        if name == "socrata":
            adapter.add_argument(
                "--api-base-url",
                default="https://{domain}/resource/{dataset_id}.json",
                help="Override Socrata API endpoint template for tests or private mirrors",
            )
        if name == "stooq":
            adapter.add_argument("--interval", choices=["d", "w", "m"], default="d")
            adapter.add_argument(
                "--api-base-url",
                default="https://stooq.com/q/d/l/",
                help="Override Stooq CSV endpoint for tests or private mirrors",
            )
        if name == "yahoo":
            adapter.add_argument("--range", dest="range_value", default="1mo")
            adapter.add_argument("--interval", default="1d")
            adapter.add_argument(
                "--api-base-url",
                default="https://query1.finance.yahoo.com/v8/finance/chart",
                help="Override Yahoo Finance chart API base URL for tests or private mirrors",
            )
        if name == "coingecko":
            adapter.add_argument("--vs-currency", default="usd")
            adapter.add_argument(
                "--api-base-url",
                default="https://api.coingecko.com/api/v3/coins/markets",
                help="Override CoinGecko markets API endpoint for tests or private mirrors",
            )
        if name == "sec":
            adapter.add_argument(
                "--api-base-url",
                default="https://data.sec.gov/submissions",
                help="Override SEC submissions API base URL for tests or private mirrors",
            )
        if name == "secfacts":
            adapter.add_argument("--concept", help="SEC XBRL concept, e.g. Revenues")
            adapter.add_argument("--taxonomy", default="us-gaap", help="SEC XBRL taxonomy, defaulting to us-gaap")
            adapter.add_argument("--unit", help="SEC XBRL unit to import, e.g. USD, shares, or pure")
            adapter.add_argument(
                "--api-base-url",
                default="https://data.sec.gov/api/xbrl/companyfacts",
                help="Override SEC company-facts API base URL for tests or private mirrors",
            )
        if name == "arxiv":
            adapter.add_argument(
                "--api-base-url",
                default="https://export.arxiv.org/api/query",
                help="Override arXiv API base URL for tests or private mirrors",
            )
        if name == "openalex":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.openalex.org/works",
                help="Override OpenAlex Works API base URL for tests or private mirrors",
            )
        if name == "crossref":
            adapter.add_argument(
                "--api-base-url",
                default="https://api.crossref.org/works",
                help="Override Crossref Works API base URL for tests or private mirrors",
            )
        if name == "wikipedia":
            adapter.add_argument(
                "--api-base-url",
                default="https://en.wikipedia.org/w/api.php",
                help="Override MediaWiki API base URL for tests or private mirrors",
            )
        if name == "wikipediapageviews":
            adapter.add_argument("--access", default="all-access", help="Wikimedia access filter")
            adapter.add_argument("--agent", default="user", help="Wikimedia agent filter")
            adapter.add_argument(
                "--api-base-url",
                default="https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article",
                help="Override Wikimedia pageviews API base URL for tests or private mirrors",
            )
        adapter.add_argument("--resolution-criteria")
        adapter.add_argument("--close-time")
        adapter.add_argument("--resolution-time")
        adapter.add_argument("--baseline-probability", type=float)
        adapter.add_argument("--baseline-type", default="imported")
        adapter.add_argument("--as-of")
        adapter.set_defaults(_forecast_handler=_cmd_import_adapter)

    plugins_parser = forecast_sub.add_parser("plugins", help="List forecast-specific extension points")
    plugins_parser.add_argument("--kind", choices=["importer", "market", "model", "resolver", "alert", "visualizer"])
    plugins_parser.set_defaults(_forecast_handler=_cmd_plugins)

    research_parser = forecast_sub.add_parser("research", help="Capture research evidence without updating probability")
    research_parser.add_argument("id")
    research_parser.add_argument("sources", nargs="*")
    research_parser.add_argument("--claim", default="")
    research_parser.add_argument("--claim-type", choices=sorted(EVIDENCE_CLAIM_TYPES), default="fact")
    research_parser.add_argument("--summary", default="")
    research_parser.add_argument("--available-at")
    research_parser.add_argument("--published-at")
    research_parser.add_argument("--source-name")
    research_parser.add_argument("--source-type")
    research_parser.add_argument("--reliability", type=float)
    research_parser.add_argument("--relevance", type=float)
    research_parser.add_argument(
        "--stance",
        choices=["increases", "decreases", "mixed", "context"],
        default="context",
    )
    research_parser.set_defaults(_forecast_handler=_cmd_research)

    base_rate_parser = forecast_sub.add_parser("base-rate", help="Store a reference-class base-rate estimate")
    base_rate_parser.add_argument("id")
    base_rate_parser.add_argument("--name", required=True)
    base_rate_parser.add_argument("--inclusion-criteria", required=True)
    base_rate_parser.add_argument("--exclusion-criteria", default="")
    base_rate_parser.add_argument("--base-rate", type=float, required=True)
    base_rate_parser.add_argument("--uncertainty", type=float)
    base_rate_parser.add_argument("--source-ref", dest="source_refs", action="append", default=[])
    base_rate_parser.add_argument("--check-cadence")
    base_rate_parser.add_argument("--notes")
    base_rate_parser.set_defaults(_forecast_handler=_cmd_base_rate)

    model_parser = forecast_sub.add_parser("model", help="Record a probabilistic model run")
    model_parser.add_argument("id")
    model_parser.add_argument("--type", dest="model_type", required=True)
    model_parser.add_argument("--status", choices=["success", "failure"], default="success")
    model_parser.add_argument("--input-json", default="{}")
    model_parser.add_argument("--parameters-json", default="{}")
    model_parser.add_argument("--output-json", default="{}")
    model_parser.add_argument("--diagnostics-json", default="{}")
    model_parser.add_argument("--prior", type=float)
    model_parser.add_argument("--likelihood-if-true", type=float)
    model_parser.add_argument("--likelihood-if-false", type=float)
    model_parser.add_argument("--series-json", help="JSON array for trend_projection model runs")
    model_parser.add_argument("--target-date", help="Projection target date for trend_projection")
    model_parser.add_argument("--target-x", type=float, help="Projection target x value for trend_projection")
    model_parser.add_argument("--date-field", default="date", help="Date field name in trend_projection series rows")
    model_parser.add_argument("--value-field", default="value", help="Value field name in trend_projection series rows")
    model_parser.add_argument("--code-ref")
    model_parser.add_argument("--artifact-path", dest="artifact_paths", action="append", default=[])
    model_parser.add_argument("--model-version")
    model_parser.add_argument("--prompt-version")
    model_parser.add_argument("--data-version")
    model_parser.add_argument("--evidence-cutoff")
    model_parser.set_defaults(_forecast_handler=_cmd_model)

    protocol_parser = forecast_sub.add_parser("protocol", help="Render a forecast-stage agent protocol prompt")
    protocol_parser.add_argument("id")
    protocol_parser.add_argument("--stage", choices=sorted(PROTOCOL_STAGES), default="update")
    protocol_parser.add_argument("--json", action="store_true")
    protocol_parser.set_defaults(_forecast_handler=_cmd_protocol)

    agent_parser = forecast_sub.add_parser("agent", help="Run a forecast protocol stage through AIAgent")
    agent_parser.add_argument("id")
    agent_parser.add_argument("--stage", choices=sorted(PROTOCOL_STAGES), default="update")
    agent_parser.add_argument("--dry-run", action="store_true", help="Print protocol messages without calling a model")
    agent_parser.add_argument("--model")
    agent_parser.add_argument("--provider")
    agent_parser.add_argument("--max-iterations", type=int, default=12)
    agent_parser.set_defaults(_forecast_handler=_cmd_agent)

    assumption_parser = forecast_sub.add_parser("assumption", help="Manage durable forecast assumptions")
    assumption_sub = assumption_parser.add_subparsers(dest="assumption_command")
    assumption_add = assumption_sub.add_parser("add", help="Add an assumption")
    assumption_add.add_argument("id")
    assumption_add.add_argument("text")
    assumption_add.add_argument("--status", choices=sorted(ASSUMPTION_STATUSES), default="active")
    assumption_add.add_argument("--check-cadence")
    assumption_add.add_argument("--evidence-ref", dest="evidence_refs", action="append", default=[])
    assumption_add.add_argument("--notes")
    assumption_add.set_defaults(_forecast_handler=_cmd_assumption_add)
    assumption_list = assumption_sub.add_parser("list", help="List assumptions")
    assumption_list.add_argument("id")
    assumption_list.set_defaults(_forecast_handler=_cmd_assumption_list)
    assumption_status = assumption_sub.add_parser("status", help="Update assumption status")
    assumption_status.add_argument("assumption_id")
    assumption_status.add_argument("--status", choices=sorted(ASSUMPTION_STATUSES), required=True)
    assumption_status.add_argument("--last-checked-at")
    assumption_status.add_argument("--invalidated-at")
    assumption_status.add_argument("--notes")
    assumption_status.set_defaults(_forecast_handler=_cmd_assumption_status)

    reference_parser = forecast_sub.add_parser("reference-class", help="Manage durable reference classes")
    reference_sub = reference_parser.add_subparsers(dest="reference_command")
    reference_list = reference_sub.add_parser("list", help="List reference classes")
    reference_list.add_argument("id")
    reference_list.set_defaults(_forecast_handler=_cmd_reference_class_list)
    reference_status = reference_sub.add_parser("status", help="Update reference class status")
    reference_status.add_argument("reference_class_id")
    reference_status.add_argument("--status", choices=sorted(REFERENCE_CLASS_STATUSES), required=True)
    reference_status.add_argument("--last-checked-at")
    reference_status.add_argument("--invalidated-at")
    reference_status.add_argument("--check-cadence")
    reference_status.add_argument("--notes")
    reference_status.set_defaults(_forecast_handler=_cmd_reference_class_status)

    evidence_parser = forecast_sub.add_parser("evidence", help="Manage evidence items")
    evidence_sub = evidence_parser.add_subparsers(dest="evidence_command")
    evidence_add = evidence_sub.add_parser("add", help="Add evidence to a forecast question")
    evidence_add.add_argument("id")
    evidence_add.add_argument("source_or_note")
    evidence_add.add_argument("--claim", default="")
    evidence_add.add_argument("--claim-type", choices=sorted(EVIDENCE_CLAIM_TYPES), default="fact")
    evidence_add.add_argument("--summary", default="")
    evidence_add.add_argument("--url", dest="source_url")
    evidence_add.add_argument("--source-name")
    evidence_add.add_argument("--source-type")
    evidence_add.add_argument("--published-at")
    evidence_add.add_argument("--available-at")
    evidence_add.add_argument("--reliability", type=float)
    evidence_add.add_argument("--relevance", type=float)
    evidence_add.add_argument(
        "--stance",
        choices=["increases", "decreases", "mixed", "context"],
        default="context",
    )
    evidence_add.add_argument("--snapshot-path")
    evidence_add.add_argument("--not-admissible-for-backtests", action="store_true")
    evidence_add.set_defaults(_forecast_handler=_cmd_evidence_add)
    evidence_list = evidence_sub.add_parser("list", help="List evidence for a forecast question")
    evidence_list.add_argument("id")
    evidence_list.set_defaults(_forecast_handler=_cmd_evidence_list)

    resolve_parser = forecast_sub.add_parser("resolve", help="Record a forecast resolution")
    resolve_parser.add_argument("id")
    resolve_parser.add_argument("--outcome", required=True)
    resolve_parser.add_argument("--source", dest="resolution_source")
    resolve_parser.add_argument("--source-snapshot-ref", dest="resolution_source_snapshot_ref")
    resolve_parser.add_argument(
        "--resolver-type",
        choices=["manual", "source_adapter", "scheduled_check"],
        default="manual",
    )
    resolve_parser.add_argument(
        "--status",
        dest="resolution_status",
        choices=["proposed", "confirmed", "disputed", "corrected"],
        default="confirmed",
    )
    resolve_parser.add_argument(
        "--criteria-satisfied",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    resolve_parser.add_argument("--confidence", type=float)
    resolve_parser.add_argument("--confirmed-by")
    resolve_parser.add_argument("--notes", dest="resolver_notes")
    resolve_parser.add_argument("--correction-ref")
    resolve_parser.add_argument("--trusted-policy")
    resolve_parser.add_argument("--not-scoreable", action="store_true")
    resolve_parser.set_defaults(_forecast_handler=_cmd_resolve)

    score_parser = forecast_sub.add_parser("score", help="Score the current forecast snapshot")
    score_parser.add_argument("id")
    score_parser.add_argument("--force", action="store_true")
    score_parser.set_defaults(_forecast_handler=_cmd_score)

    scores_parser = forecast_sub.add_parser("scores", help="List score records")
    scores_parser.add_argument("--domain")
    scores_parser.add_argument("--origin", dest="forecast_origin", choices=["live", "backtest", "imported_baseline"])
    scores_parser.add_argument("--horizon")
    scores_parser.add_argument("--bucket")
    scores_parser.add_argument("--all", action="store_true", help="Include calibration-ineligible scores")
    scores_parser.add_argument("--include-invalidated", action="store_true")
    scores_parser.set_defaults(_forecast_handler=_cmd_scores)

    postmortem_parser = forecast_sub.add_parser("postmortem", help="Create a structured post-resolution diagnosis")
    postmortem_parser.add_argument("id")
    postmortem_parser.add_argument("--summary", default="")
    postmortem_parser.add_argument("--what-happened", default="")
    postmortem_parser.add_argument("--what-was-expected", default="")
    postmortem_parser.add_argument("--missed-evidence", default="")
    postmortem_parser.add_argument("--overweighted-evidence", default="")
    postmortem_parser.add_argument("--base-rate-error", default="")
    postmortem_parser.add_argument("--inside-view-error", default="")
    postmortem_parser.add_argument("--resolution-error", default="")
    postmortem_parser.add_argument("--lesson", default="")
    postmortem_parser.add_argument("--calibration-adjustment-json", default="{}")
    postmortem_parser.set_defaults(_forecast_handler=_cmd_postmortem)

    lesson_parser = forecast_sub.add_parser("lesson", help="Review and promote calibration lessons")
    lesson_sub = lesson_parser.add_subparsers(dest="lesson_command")
    lesson_list = lesson_sub.add_parser("list", help="List calibration lessons")
    lesson_list.add_argument("--scope-type")
    lesson_list.add_argument("--scope-ref")
    lesson_list.add_argument("--active", action="store_true")
    lesson_list.set_defaults(_forecast_handler=_cmd_lesson_list)
    lesson_status = lesson_sub.add_parser("status", help="Update calibration lesson status")
    lesson_status.add_argument("lesson_id")
    lesson_status.add_argument("--status", choices=sorted(CALIBRATION_LESSON_STATUSES), required=True)
    lesson_status.add_argument("--confidence", type=float)
    lesson_status.add_argument("--recommended-adjustment-json")
    lesson_status.add_argument("--supersedes")
    lesson_status.set_defaults(_forecast_handler=_cmd_lesson_status)

    correction_parser = forecast_sub.add_parser("correction", help="Record non-mutating corrections")
    correction_sub = correction_parser.add_subparsers(dest="correction_command")
    correction_add = correction_sub.add_parser("add", help="Add a correction record")
    correction_add.add_argument("--target-type", required=True)
    correction_add.add_argument("--target-id", required=True)
    correction_add.add_argument("--reason", required=True)
    correction_add.add_argument("--created-by")
    correction_add.add_argument("--old-json", default="null")
    correction_add.add_argument("--new-json", default="null")
    correction_add.add_argument("--patch-json", default="{}")
    correction_add.add_argument("--status", choices=["proposed", "applied", "rejected"], default="proposed")
    correction_add.set_defaults(_forecast_handler=_cmd_correction_add)
    correction_list = correction_sub.add_parser("list", help="List correction records")
    correction_list.add_argument("--target-type")
    correction_list.add_argument("--target-id")
    correction_list.add_argument("--status", choices=["proposed", "applied", "rejected"])
    correction_list.set_defaults(_forecast_handler=_cmd_correction_list)

    resolver_parser = forecast_sub.add_parser("resolver", help="Manage trusted resolver policies")
    resolver_sub = resolver_parser.add_subparsers(dest="resolver_command")
    resolver_trust = resolver_sub.add_parser("trust", help="Create a trusted resolver policy")
    resolver_trust.add_argument("--plugin", dest="resolver_plugin", required=True)
    resolver_trust.add_argument("--plugin-version")
    resolver_trust.add_argument(
        "--scope-type",
        choices=["domain", "topic", "source", "question_type", "global"],
        required=True,
    )
    resolver_trust.add_argument("--scope-ref")
    resolver_trust.add_argument("--enabled", action="store_true")
    resolver_trust.add_argument("--approved-by")
    resolver_trust.add_argument("--audit-log-ref")
    resolver_trust.set_defaults(_forecast_handler=_cmd_resolver_trust)
    resolver_list = resolver_sub.add_parser("list", help="List trusted resolver policies")
    resolver_list.add_argument("--plugin", dest="resolver_plugin")
    resolver_list.add_argument("--scope-type")
    resolver_list.add_argument("--enabled", action="store_true")
    resolver_list.set_defaults(_forecast_handler=_cmd_resolver_list)

    calibration_parser = forecast_sub.add_parser("calibration", help="Show calibration summary")
    calibration_parser.add_argument("--domain")
    calibration_parser.add_argument(
        "--origin",
        dest="forecast_origin",
        choices=["live", "backtest", "imported_baseline"],
    )
    calibration_parser.add_argument(
        "--by-origin",
        action="store_true",
        help="Show combined, live, backtest, and imported-baseline calibration sections",
    )
    calibration_parser.add_argument("--horizon", help="Filter by horizon in days, e.g. 7 or 30-90")
    calibration_parser.add_argument("--all", action="store_true", help="Include calibration-ineligible scores")
    calibration_parser.set_defaults(_forecast_handler=_cmd_calibration)

    errors_parser = forecast_sub.add_parser("errors", help="Show domain error profile summary")
    errors_parser.add_argument("--domain")
    errors_parser.add_argument("--topic")
    errors_parser.set_defaults(_forecast_handler=_cmd_errors)

    review_parser = forecast_sub.add_parser("review", help="Review stale or active forecasts")
    review_parser.add_argument("--stale", action="store_true")
    review_parser.add_argument("--last", dest="last_days", type=_parse_day_count, default=7)
    review_parser.add_argument("--domain")
    review_parser.add_argument("--topic")
    review_parser.add_argument("--horizon", help="Filter by forecast horizon in days, e.g. 30 or 30-90")
    review_parser.add_argument("--confidence-below", type=float)
    review_parser.add_argument("--confidence-above", type=float)
    review_parser.add_argument("--large-delta-threshold", type=float)
    review_parser.add_argument("--now")
    review_parser.set_defaults(_forecast_handler=_cmd_review)

    schedule_parser = forecast_sub.add_parser("schedule", help="Manage scheduled self-checks")
    schedule_sub = schedule_parser.add_subparsers(dest="schedule_command")
    schedule_add = schedule_sub.add_parser("add", help="Add a scheduled review")
    schedule_add.add_argument("--question", dest="question_id")
    schedule_add.add_argument("--domain")
    schedule_add.add_argument("--topic")
    schedule_add.add_argument("--portfolio")
    schedule_add.add_argument("--horizon", help="Scope scheduled review to forecast horizon in days or range")
    schedule_add.add_argument("--cadence", required=True)
    schedule_add.add_argument("--next-run-at", required=True)
    schedule_add.add_argument("--stale-days", type=int, default=7)
    schedule_add.add_argument("--trigger-reason", default="scheduled")
    schedule_add.add_argument("--auto-score", action="store_true")
    schedule_add.add_argument("--auto-postmortem", action="store_true")
    schedule_add.add_argument("--confidence-below", type=float)
    schedule_add.add_argument("--confidence-above", type=float)
    schedule_add.add_argument("--large-delta-threshold", type=float)
    schedule_add.add_argument("--disabled", action="store_true")
    schedule_add.set_defaults(_forecast_handler=_cmd_schedule_add)
    schedule_list = schedule_sub.add_parser("list", help="List scheduled reviews")
    schedule_list.set_defaults(_forecast_handler=_cmd_schedule_list)
    schedule_run = schedule_sub.add_parser("run", help="Run due scheduled self-checks")
    schedule_run.add_argument("--due", action="store_true", help="Run due reviews explicitly; this is the default")
    schedule_run.add_argument("--now")
    schedule_run.add_argument("--auto-score", action="store_true")
    schedule_run.add_argument("--auto-postmortem", action="store_true")
    schedule_run.set_defaults(_forecast_handler=_cmd_schedule_run)
    schedule_cron = schedule_sub.add_parser(
        "install-cron",
        help="Install a no-agent cron bridge for forecast self-checks",
    )
    schedule_cron.add_argument("--schedule", default="every 1h")
    schedule_cron.add_argument("--name", default="Forecast self-check")
    schedule_cron.add_argument("--deliver", default="local")
    schedule_cron.add_argument("--profile")
    schedule_cron.add_argument("--auto-score", action="store_true")
    schedule_cron.add_argument("--auto-postmortem", action="store_true")
    schedule_cron.set_defaults(_forecast_handler=_cmd_schedule_install_cron)

    watch_parser = forecast_sub.add_parser("watch", help="Manage watched sources for self-check alerts")
    watch_sub = watch_parser.add_subparsers(dest="watch_command")
    watch_add = watch_sub.add_parser("add", help="Watch a source for a question, domain, topic, or portfolio")
    watch_add.add_argument("source")
    watch_add.add_argument("--question", dest="question_id")
    watch_add.add_argument("--domain")
    watch_add.add_argument("--topic")
    watch_add.add_argument("--portfolio")
    watch_add.add_argument("--source-type", choices=sorted(WATCH_SOURCE_TYPES))
    watch_add.add_argument("--metadata-json", default="{}")
    watch_add.set_defaults(_forecast_handler=_cmd_watch_add)
    watch_list = watch_sub.add_parser("list", help="List watched sources")
    watch_list.add_argument("--question", dest="question_id")
    watch_list.add_argument("--domain")
    watch_list.add_argument("--topic")
    watch_list.add_argument("--portfolio")
    watch_list.add_argument("--all", action="store_true")
    watch_list.set_defaults(_forecast_handler=_cmd_watch_list)
    watch_check = watch_sub.add_parser("check", help="Check watched sources for changes")
    watch_check.add_argument("--question", dest="question_id")
    watch_check.add_argument("--domain")
    watch_check.add_argument("--topic")
    watch_check.add_argument("--portfolio")
    watch_check.add_argument("--now")
    watch_check.set_defaults(_forecast_handler=_cmd_watch_check)

    alerts_parser = forecast_sub.add_parser("alerts", help="List forecast alerts")
    alerts_parser.add_argument("--all", action="store_true")
    alerts_parser.add_argument("--ack", dest="ack_alert_id")
    alerts_parser.set_defaults(_forecast_handler=_cmd_alerts)

    self_check_parser = forecast_sub.add_parser("self-check", help="Create alerts for review work")
    self_check_parser.add_argument("--question", dest="question_id")
    self_check_parser.add_argument("--domain")
    self_check_parser.add_argument("--topic")
    self_check_parser.add_argument("--portfolio")
    self_check_parser.add_argument("--horizon", help="Filter self-check to forecast horizon in days or range")
    self_check_parser.add_argument("--stale-days", type=int, default=7)
    self_check_parser.add_argument("--now")
    self_check_parser.add_argument("--auto-score", action="store_true")
    self_check_parser.add_argument("--auto-postmortem", action="store_true")
    self_check_parser.add_argument("--confidence-below", type=float)
    self_check_parser.add_argument("--confidence-above", type=float)
    self_check_parser.add_argument("--large-delta-threshold", type=float)
    self_check_parser.set_defaults(_forecast_handler=_cmd_self_check)

    backtest_parser = forecast_sub.add_parser("backtest", help="Run or inspect time-aware historical replay datasets")
    backtest_parser.add_argument("dataset", nargs="?")
    backtest_parser.add_argument("--as-of")
    backtest_parser.add_argument("--evidence-cutoff-policy", default="available_at_lte_cutoff")
    backtest_parser.add_argument(
        "--probability-source",
        choices=["dataset", "baseline-ensemble", "forecast-engine", "agent-protocol", "naive"],
        default="dataset",
        help=(
            "Choose how replay probabilities are produced: dataset uses stored "
            "case probabilities, baseline-ensemble combines explicit baselines, "
            "forecast-engine generates a local desk-ensemble probability, "
            "agent-protocol runs the forecasting protocol through AIAgent or "
            "captured JSONL agent outputs, and naive uses 0.5 for binary cases."
        ),
    )
    backtest_parser.add_argument(
        "--agent-response-jsonl",
        help=(
            "JSONL file of captured agent protocol responses keyed by case_id/id/index; "
            "used only with --probability-source agent-protocol."
        ),
    )
    backtest_parser.add_argument(
        "--agent-output-jsonl",
        help=(
            "Write agent protocol responses as JSONL for later deterministic replay; "
            "used only with --probability-source agent-protocol."
        ),
    )
    backtest_parser.add_argument("--agent-model", help="Model used for agent-protocol backtests")
    backtest_parser.add_argument("--agent-provider", help="Provider used for agent-protocol backtests")
    backtest_parser.add_argument("--agent-max-iterations", type=int, default=12)
    backtest_parser.add_argument("--allow-calibration-memory", action="store_true")
    backtest_parser.add_argument("--benchmarks", action="store_true", help="List built-in benchmark datasets")
    backtest_parser.add_argument(
        "--all-benchmarks",
        action="store_true",
        help="Run every built-in benchmark dataset with the selected probability source",
    )
    backtest_parser.add_argument("--list", action="store_true")
    backtest_parser.add_argument("--show")
    backtest_parser.set_defaults(_forecast_handler=_cmd_backtest)

    performance_parser = forecast_sub.add_parser(
        "performance",
        help="Summarize recent backtest performance against available baselines",
    )
    performance_parser.add_argument("--last", type=int, default=10, help="Number of recent backtest runs to show")
    performance_parser.add_argument("--dataset", help="Filter to runs whose dataset contains this text")
    performance_parser.add_argument("--json", action="store_true", help="Emit machine-readable performance JSON")
    performance_parser.set_defaults(_forecast_handler=_cmd_performance)

    readiness_parser = forecast_sub.add_parser(
        "readiness",
        help="Show live/backtest evidence gaps before stronger performance claims",
    )
    readiness_parser.add_argument("--last", type=int, default=20, help="Number of recent backtest runs to inspect")
    readiness_parser.add_argument("--dataset", help="Filter to runs whose dataset contains this text")
    readiness_parser.add_argument(
        "--min-live-scores",
        type=int,
        default=DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM,
        help="Required resolved live scores for readiness accounting",
    )
    readiness_parser.add_argument(
        "--min-agent-protocol-cases",
        type=int,
        default=DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM,
        help="Required scored agent-protocol replay cases for readiness accounting",
    )
    readiness_parser.add_argument(
        "--require-evidence",
        action="store_true",
        help="Exit nonzero when readiness requirements still have gaps",
    )
    readiness_parser.add_argument("--json", action="store_true", help="Emit machine-readable readiness JSON")
    readiness_parser.set_defaults(_forecast_handler=_cmd_readiness)

    pilot_parser = forecast_sub.add_parser(
        "pilot-report",
        help="Summarize tester-pilot ledger coverage and missing artifacts",
    )
    pilot_parser.add_argument("--min-questions", type=int, default=3)
    pilot_parser.add_argument("--min-structured-source-questions", type=int, default=1)
    pilot_parser.add_argument("--min-scores", type=int, default=1)
    pilot_parser.add_argument("--min-postmortems", type=int, default=1)
    pilot_parser.add_argument("--min-scheduled-reviews", type=int, default=1)
    pilot_parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit nonzero when pilot exit checks still have gaps",
    )
    pilot_parser.add_argument("--json", action="store_true", help="Emit machine-readable pilot-report JSON")
    pilot_parser.set_defaults(_forecast_handler=_cmd_pilot_report)

    pilot_cohort_parser = forecast_sub.add_parser(
        "pilot-cohort",
        help="Seed a prospective live tester cohort from a CSV or JSON manifest",
    )
    pilot_cohort_parser.add_argument("manifest", help="CSV/JSON file or URL containing unresolved live questions")
    pilot_cohort_parser.add_argument("--default-domain")
    pilot_cohort_parser.add_argument("--default-owner")
    pilot_cohort_parser.add_argument("--default-review-cadence")
    pilot_cohort_parser.add_argument(
        "--initial-probability-column",
        default="probability",
        help="Column/key containing the operator's initial live probability; set empty to disable",
    )
    pilot_cohort_parser.add_argument(
        "--watch-source-column",
        default="watch_source",
        help="Column/key containing one or more watched sources separated by comma or semicolon",
    )
    pilot_cohort_parser.add_argument("--schedule-cadence", help="Create one scheduled review per seeded question")
    pilot_cohort_parser.add_argument("--schedule-next-run-at", help="First run timestamp for --schedule-cadence")
    pilot_cohort_parser.add_argument("--schedule-stale-days", type=int, default=7)
    pilot_cohort_parser.add_argument("--dry-run", action="store_true", help="Validate and show the cohort without writing")
    pilot_cohort_parser.add_argument("--json", action="store_true", help="Emit machine-readable cohort JSON")
    pilot_cohort_parser.set_defaults(_forecast_handler=_cmd_pilot_cohort)

    pilot_aggregate_parser = forecast_sub.add_parser(
        "pilot-aggregate",
        help="Aggregate tester export packets into live-evidence collection counts",
    )
    pilot_aggregate_parser.add_argument("exports", nargs="+", help="JSON files from `forecast export <id|all>`")
    pilot_aggregate_parser.add_argument(
        "--min-live-scores",
        type=int,
        default=10,
        help="Minimum live scored forecasts expected across export packets",
    )
    pilot_aggregate_parser.add_argument(
        "--require-live-scores",
        action="store_true",
        help="Exit nonzero when the aggregated live score floor is not met",
    )
    pilot_aggregate_parser.add_argument("--json", action="store_true", help="Emit machine-readable aggregate JSON")
    pilot_aggregate_parser.set_defaults(_forecast_handler=_cmd_pilot_aggregate)

    pilot_bundle_parser = forecast_sub.add_parser(
        "pilot-bundle",
        help="Emit one JSON tester handoff bundle with pilot, readiness, and optional export data",
    )
    pilot_bundle_parser.add_argument("--min-questions", type=int, default=3)
    pilot_bundle_parser.add_argument("--min-structured-source-questions", type=int, default=1)
    pilot_bundle_parser.add_argument("--min-scores", type=int, default=1)
    pilot_bundle_parser.add_argument("--min-postmortems", type=int, default=1)
    pilot_bundle_parser.add_argument("--min-scheduled-reviews", type=int, default=1)
    pilot_bundle_parser.add_argument("--last", type=int, default=20, help="Number of recent backtest runs to inspect")
    pilot_bundle_parser.add_argument("--dataset", help="Filter to runs whose dataset contains this text")
    pilot_bundle_parser.add_argument(
        "--min-live-scores",
        type=int,
        default=DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM,
        help="Required resolved live scores for readiness accounting",
    )
    pilot_bundle_parser.add_argument(
        "--min-agent-protocol-cases",
        type=int,
        default=DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM,
        help="Required scored agent-protocol replay cases for readiness accounting",
    )
    pilot_bundle_parser.add_argument(
        "--include-export",
        action="store_true",
        help="Include `forecast export all --format json` data in the bundle; review for sensitive data first",
    )
    pilot_bundle_parser.add_argument("--output", help="Write the JSON bundle to this path instead of stdout")
    pilot_bundle_parser.set_defaults(_forecast_handler=_cmd_pilot_bundle)

    export_parser = forecast_sub.add_parser("export", help="Export an auditable forecast packet")
    export_parser.add_argument("id")
    export_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    export_parser.add_argument("--output")
    export_parser.set_defaults(_forecast_handler=_cmd_export)

    return parser


def cmd_forecast(args: argparse.Namespace) -> None:
    handler = getattr(args, "_forecast_handler", None)
    if handler is None:
        _cmd_dashboard(args)
        return
    try:
        handler(args)
    except ForecastingError as exc:
        print(f"forecast: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def main(argv: list[str] | None = None, *, prog: str = CLI_SURFACE) -> None:
    """Standalone ``forecast`` console entrypoint.

    The forecast fork can keep `hermes forecast ...` during transition while
    also exposing `forecast ...` as the primary product command.
    """

    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="_forecast_root")
    forecast_parser = register_cli(subparsers)
    _retarget_parser_prog(forecast_parser, prog)
    parsed = parser.parse_args([CLI_SURFACE, *(argv if argv is not None else sys.argv[1:])])
    func = getattr(parsed, "func", None)
    if func is None:
        parser.print_help()
        return
    func(parsed)


def _retarget_parser_prog(parser: argparse.ArgumentParser, prog: str) -> None:
    parser.prog = prog
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, child in action.choices.items():
            _retarget_parser_prog(child, f"{prog} {name}")


def _ledger(args: argparse.Namespace) -> ForecastLedger:
    return ForecastLedger(getattr(args, "db", None))


def _cmd_about(args: argparse.Namespace) -> None:
    del args
    print(PRODUCT_NAME)
    print(f"slug: {PRODUCT_SLUG}")
    print(f"primary_surface: {CLI_SURFACE}")
    print(f"core_primitive: {CORE_PRIMITIVE}")
    print(f"north_star: {NORTH_STAR}")
    print(f"context_doc: {FORK_CONTEXT_DOC}")
    print(f"prd_doc: {FORK_PRD_DOC}")
    print("kept_surfaces:")
    for item in KEEP_SURFACES:
        print(f"  - {item}")
    print("demoted_surfaces:")
    for item in DEMOTED_SURFACES:
        print(f"  - {item}")


def _cmd_status(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    statuses = ["active", "closed", "resolved", "archived"]
    active_questions = ledger.list_questions(status="active")
    question_counts = {
        status: len(active_questions) if status == "active" else len(ledger.list_questions(status=status))
        for status in statuses
    }
    active_assumptions = [
        assumption
        for question in active_questions
        for assumption in ledger.list_assumptions(question.id)
    ]
    review_queue = ledger.review_questions(stale=True, last_days=7)
    open_alerts = ledger.list_alerts(unresolved_only=True)
    schedules = ledger.list_scheduled_reviews()
    watches = ledger.list_watched_sources(status=None)
    benchmarks = list_builtin_benchmarks()
    imported_benchmarks = ledger.list_benchmark_datasets()
    lessons = ledger.list_calibration_lessons()
    active_lessons = ledger.list_calibration_lessons(active_only=True)
    scores = ledger.list_scores(calibration_eligible=None, include_invalidated=True)
    calibration = ledger.calibration_summary(calibration_eligible=True)
    extensions = extension_registry.list()
    payload = {
        "product": PRODUCT_NAME,
        "slug": PRODUCT_SLUG,
        "ledger_path": str(ledger.db_path),
        "question_counts": question_counts,
        "active_assumption_count": sum(1 for row in active_assumptions if row.get("status") == "active"),
        "stale_assumption_count": sum(1 for row in active_assumptions if row.get("status") in {"stale", "invalidated"}),
        "review_queue_count": len(review_queue),
        "open_alert_count": len(open_alerts),
        "scheduled_review_count": len(schedules),
        "enabled_scheduled_review_count": sum(1 for row in schedules if row.get("enabled")),
        "learning_scheduled_review_count": sum(
            1 for row in schedules if row.get("auto_score") or row.get("auto_postmortem")
        ),
        "watched_source_count": len(watches),
        "active_watched_source_count": sum(1 for row in watches if row.get("status") == "active"),
        "score_count": len(scores),
        "calibration_eligible_score_count": calibration["count"],
        "calibration_mean_brier": calibration["mean_brier"],
        "calibration_lesson_count": len(lessons),
        "active_calibration_lesson_count": len(active_lessons),
        "builtin_benchmark_count": len(benchmarks),
        "imported_benchmark_count": len(imported_benchmarks),
        "extension_count": len(extensions),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(PRODUCT_NAME)
    print(f"ledger: {payload['ledger_path']}")
    print(
        "questions: "
        + " ".join(f"{status}={count}" for status, count in question_counts.items())
    )
    print(
        f"assumptions: active={payload['active_assumption_count']}  "
        f"stale={payload['stale_assumption_count']}"
    )
    print(f"reviews: queued={payload['review_queue_count']}")
    print(
        f"alerts: open={payload['open_alert_count']}  "
        f"schedules={payload['enabled_scheduled_review_count']}/{payload['scheduled_review_count']}  "
        f"learning_schedules={payload['learning_scheduled_review_count']}  "
        f"watches={payload['active_watched_source_count']}/{payload['watched_source_count']}"
    )
    print(
        f"scores: total={payload['score_count']}  "
        f"calibration_eligible={payload['calibration_eligible_score_count']}  "
        f"mean_brier={_format_metric(payload['calibration_mean_brier'])}"
    )
    print(
        f"lessons: active={payload['active_calibration_lesson_count']} "
        f"total={payload['calibration_lesson_count']}"
    )
    print(
        f"benchmarks: builtin={payload['builtin_benchmark_count']} "
        f"imported={payload['imported_benchmark_count']}"
    )
    print(f"extensions: {payload['extension_count']}")


def _cmd_dashboard(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    summary = build_dashboard_summary(ledger=ledger, limit=20)
    print(DESK_TITLE)
    print(f"{PRODUCT_NAME} - {NORTH_STAR}")
    print(render_dashboard_text(summary))


def _cmd_new(args: argparse.Namespace) -> None:
    bounds = args.bounds or None
    choices = args.choices or (["yes", "no"] if args.outcome_type == "binary" else [])
    outcome_space = OutcomeSpace(
        type=args.outcome_type,
        choices=choices,
        units=args.units,
        bounds=bounds,
    )
    question = _ledger(args).create_question(
        title=args.title,
        description=args.description,
        resolution_criteria=args.resolution_criteria,
        resolution_source=args.resolution_source,
        outcome_space=outcome_space,
        close_time=args.close_time,
        resolution_time=args.resolution_time,
        tags=args.tags,
        domain=args.domain,
        topics=args.topics,
        owner=args.owner,
        impact=args.impact,
        review_cadence=args.review_cadence,
        next_review_at=args.next_review_at,
    )
    print(f"created forecast question {question.id}")
    print(f"title: {question.title}")
    print(f"status: {question.status}")


def _cmd_list(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    rows = ledger.list_questions(status=args.status, domain=args.domain, limit=args.limit)
    if not rows:
        print("No forecast questions found.")
        return
    print("ID             Status     P(now)    AsOf                 Delta    Close                Domain     Title")
    for question in rows:
        snapshot = ledger.get_current_snapshot(question.id)
        probability = _format_probability(snapshot.probability_or_distribution) if snapshot else "-"
        as_of = snapshot.as_of if snapshot else "-"
        delta = _format_delta(_question_delta(ledger, question.id))
        close = question.close_time or "-"
        domain = question.domain or "-"
        print(
            f"{question.id:<14} {question.status:<10} {probability:<9} {as_of:<20} "
            f"{delta:<8} {close:<20} {domain:<10} {question.title}"
        )


def _cmd_show(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    question = ledger.get_question(args.id)
    snapshots = ledger.list_snapshots(args.id)
    evidence = ledger.list_evidence(args.id)
    resolution = ledger.get_latest_resolution(args.id)
    print(f"{question.title}")
    print(f"id: {question.id}")
    print(f"status: {question.status}")
    print(f"domain: {question.domain or '-'}")
    print(f"outcome: {question.outcome_space.type} {question.outcome_space.choices}")
    print(f"close_time: {question.close_time or '-'}")
    print(f"resolution_time: {question.resolution_time or '-'}")
    print(f"resolution_criteria: {question.resolution_criteria}")
    print()
    current = snapshots[-1] if snapshots else None
    if current:
        print("current_forecast:")
        print(f"  id: {current.forecast_id}")
        print(f"  as_of: {current.as_of}")
        print(f"  probability: {_format_probability(current.probability_or_distribution)}")
        print(f"  confidence: {current.confidence if current.confidence is not None else '-'}")
        print(f"  origin: {current.forecast_origin}")
        print(f"  rationale: {current.rationale}")
    else:
        print("current_forecast: none")
    print()
    print("recent_history:")
    for snapshot in snapshots[-5:]:
        print(f"  {snapshot.as_of} {snapshot.forecast_id} {_format_probability(snapshot.probability_or_distribution)}")
    if not snapshots:
        print("  none")
    print()
    print(f"evidence_count: {len(evidence)}")
    if resolution:
        print(f"resolution: {resolution.outcome} ({resolution.resolution_status})")


def _cmd_update(args: argparse.Namespace) -> None:
    components = _json_arg(args.component_json, "component-json")
    payload = _probability_payload(args, components)
    ledger = _ledger(args)
    question = ledger.get_question(args.id)
    calibration_adjustment = _json_arg(args.calibration_adjustment_json, "calibration-adjustment-json")
    calibration_lesson_refs = list(args.calibration_lesson_refs)
    if args.use_active_lessons:
        payload, calibration_lesson_refs, calibration_adjustment = apply_active_lesson_adjustments(
            ledger=ledger,
            question=question,
            payload=payload,
            calibration_lesson_refs=calibration_lesson_refs,
            calibration_adjustment=calibration_adjustment,
        )
    previous = ledger.get_current_snapshot(args.id)
    if args.preview:
        proposed_as_of = parse_timestamp(args.as_of, field_name="as_of") or utc_now_iso()
        _print_update_preview(
            previous,
            payload,
            components,
            proposed_as_of,
            calibration_lesson_refs,
            calibration_adjustment,
        )
        return
    snapshot = ledger.create_snapshot(
        question_id=args.id,
        probability_or_distribution=payload,
        rationale=args.rationale,
        as_of=args.as_of,
        confidence=args.confidence,
        method=args.method,
        ensemble_components=components,
        key_assumptions=args.key_assumptions,
        assumption_refs=args.assumption_refs,
        reference_class_refs=args.reference_class_refs,
        evidence_refs=args.evidence_refs,
        stale_evidence_days=args.stale_evidence_days,
        acknowledge_stale_evidence=args.ack_stale_evidence,
        require_citations=args.require_citations,
        model_run_refs=args.model_run_refs,
        forecast_origin=args.forecast_origin,
        agent_model=args.agent_model,
        prompt_version=args.prompt_version,
        forecasting_protocol_version=args.protocol_version,
        toolset_version=args.toolset_version,
        source_snapshot_refs=args.source_snapshot_refs,
        evidence_cutoff=args.evidence_cutoff,
        backtest_run_id=args.backtest_run_id,
        calibration_eligible=not args.calibration_ineligible,
        calibration_weight=args.calibration_weight,
        calibration_lesson_refs=calibration_lesson_refs,
        calibration_adjustment=calibration_adjustment,
    )
    print(f"created forecast snapshot {snapshot.forecast_id}")
    print(f"question: {snapshot.question_id}")
    print(f"as_of: {snapshot.as_of}")
    print(f"probability: {_format_probability(snapshot.probability_or_distribution)}")
    if previous is not None:
        delta = _probability_delta(previous.probability_or_distribution, snapshot.probability_or_distribution)
        if delta is not None:
            print(f"previous_probability: {_format_probability(previous.probability_or_distribution)}")
            print(f"delta: {delta:+.3f}")
    if components:
        _print_component_drivers(components, snapshot.probability_or_distribution)
    _print_calibration_adjustment_summary(calibration_lesson_refs, calibration_adjustment)


def _print_update_preview(
    previous: Any,
    payload: Any,
    components: dict[str, Any],
    proposed_as_of: str,
    calibration_lesson_refs: list[str] | None = None,
    calibration_adjustment: dict[str, Any] | None = None,
) -> None:
    print("forecast update preview")
    print(f"previous_as_of: {previous.as_of if previous else '-'}")
    print(f"previous_probability: {_format_probability(previous.probability_or_distribution) if previous else '-'}")
    print(f"proposed_as_of: {proposed_as_of}")
    print(f"proposed_probability: {_format_probability(payload)}")
    delta = _probability_delta(previous.probability_or_distribution, payload) if previous else None
    print(f"delta: {delta:+.3f}" if delta is not None else "delta: -")
    if components:
        _print_component_drivers(components, payload)
    _print_calibration_adjustment_summary(calibration_lesson_refs or [], calibration_adjustment or {})


def _print_calibration_adjustment_summary(
    calibration_lesson_refs: list[str],
    calibration_adjustment: dict[str, Any],
) -> None:
    if calibration_lesson_refs:
        print(f"calibration_lessons: {len(calibration_lesson_refs)}")
    if "raw_probability" in calibration_adjustment:
        print(f"raw_probability: {_format_probability(calibration_adjustment['raw_probability'])}")
    if "applied_probability_delta" in calibration_adjustment:
        print(f"applied_probability_delta: {calibration_adjustment['applied_probability_delta']:+.3f}")
    if "applied_logit_shift" in calibration_adjustment:
        print(f"applied_logit_shift: {calibration_adjustment['applied_logit_shift']:+.3f}")


def _print_component_drivers(components: dict[str, Any], payload: Any) -> None:
    rows = _component_rows(components)
    print(f"ensemble_components: {len(rows)}")
    if not rows or not isinstance(payload, (int, float)):
        return
    try:
        total_weight = sum(float(row.get("weight", 1.0)) for row in rows)
    except (TypeError, ValueError):
        return
    if total_weight <= 0:
        return
    payload_value = float(payload)
    ranked = []
    for row in rows:
        probability = row.get("probability")
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            continue
        try:
            weight = float(row.get("weight", 1.0))
        except (TypeError, ValueError):
            continue
        contribution = (weight / total_weight) * float(probability)
        pull = (float(probability) - payload_value) * (weight / total_weight)
        ranked.append((abs(pull), row.get("name", "-"), float(probability), weight, contribution, pull))
    if not ranked:
        return
    ranked.sort(reverse=True)
    strongest = ranked[0]
    print(f"strongest_driver: {strongest[1]} pull={strongest[5]:+.3f}")
    print("component_drivers:")
    for _, name, probability, weight, contribution, pull in ranked:
        print(f"  {name} p={probability:.3f} w={weight:g} contribution={contribution:.3f} pull={pull:+.3f}")


def _component_rows(components: dict[str, Any]) -> list[dict[str, Any]]:
    rows = components.get("components")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    result = []
    for name, row in components.items():
        if isinstance(row, dict):
            item = dict(row)
            item.setdefault("name", name)
            result.append(item)
    return result


def _cmd_ingest(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    if args.list:
        rows = ledger.list_ingest_candidates(status="proposed")
        if not rows:
            print("No ingest candidates found.")
            return
        print("ID             Status      Source type  Title")
        for row in rows:
            print(f"{row['id']:<14} {row['status']:<11} {row['source_type']:<12} {row['candidate_title']}")
        return
    if args.show:
        row = ledger.get_ingest_candidate(args.show)
        print(f"id: {row['id']}")
        print(f"status: {row['status']}")
        print(f"source: {row['source']}")
        print(f"source_type: {row['source_type']}")
        print(f"title: {row['candidate_title']}")
        print(f"resolution_criteria: {row['resolution_criteria'] or '-'}")
        print(f"confirmed_question_id: {row['confirmed_question_id'] or '-'}")
        return
    if args.confirm:
        question = ledger.confirm_ingest_candidate(
            args.confirm,
            title=args.title,
            resolution_criteria=args.resolution_criteria,
            domain=args.domain,
            tags=args.tags,
            topics=args.topics,
        )
        print(f"confirmed ingest candidate {args.confirm}")
        print(f"created forecast question {question.id}")
        return
    if not args.source:
        raise SystemExit("forecast ingest requires a source, --list, --show, or --confirm")
    if args.dry_run:
        kind = "url" if args.source.startswith(("http://", "https://")) else "file-or-note"
        print(f"ingest candidate ({kind}): {args.source}")
        print("confirmation required before creating or mutating active forecast records")
        return
    if not args.question_id:
        candidate = ledger.create_ingest_candidate(
            source=args.source,
            title=args.title,
            description=args.summary,
            resolution_criteria=args.resolution_criteria or "",
            resolution_source=args.resolution_source,
            close_time=args.close_time,
            resolution_time=args.resolution_time,
        )
        print(f"created ingest candidate {candidate['id']}")
        print(f"status: {candidate['status']}")
        print("confirmation required before creating an active forecast")
        return
    item = ledger.add_evidence(
        question_id=args.question_id,
        source_or_note=args.source,
        claim=args.claim,
        claim_type=args.claim_type,
        summary=args.summary,
        available_at=args.available_at,
        published_at=args.published_at,
        source_name=args.source_name,
        source_type=args.source_type,
    )
    print(f"captured evidence {item.id}")
    print(f"question: {item.question_id}")
    print(f"available_at: {item.available_at}")


def _cmd_import_adapter(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    if args.import_kind == "benchmark" and not args.question_id and str(args.source).startswith("metaculus:"):
        if args.source != "metaculus:resolved":
            raise SystemExit("supported Metaculus benchmark source is metaculus:resolved")
        api_base_url = args.api_base_url
        if api_base_url == "https://api.manifold.markets/v0":
            api_base_url = "https://www.metaculus.com/api"
        cases = load_metaculus_resolved_binary_cases(api_base_url=api_base_url, limit=args.limit)
        if not cases:
            raise SystemExit("metaculus benchmark import found no resolved binary cases")
        dataset = ledger.import_benchmark_dataset(
            source=args.source,
            name=args.name or "metaculus-resolved-binary",
            description=args.description or "Resolved binary Metaculus questions with crowd probabilities as baselines.",
            cases=cases,
            metadata={
                "adapter": "metaculus",
                "api_base_url": api_base_url,
                "limit": args.limit,
            },
        )
        print(f"imported benchmark dataset {dataset['id']}")
        print(f"name: {dataset['name']}")
        print(f"cases: {dataset['case_count']}")
        print(f"source: {args.source}")
        print(f"run: forecast backtest imported:{dataset['id']}")
        return
    if args.import_kind == "benchmark" and not args.question_id and str(args.source).startswith("kalshi:"):
        if args.source != "kalshi:resolved":
            raise SystemExit("supported Kalshi benchmark source is kalshi:resolved")
        api_base_url = args.api_base_url
        if api_base_url == "https://api.manifold.markets/v0":
            api_base_url = "https://external-api.kalshi.com/trade-api/v2"
        cases = load_kalshi_resolved_binary_cases(api_base_url=api_base_url, limit=args.limit)
        if not cases:
            raise SystemExit("kalshi benchmark import found no resolved binary cases")
        dataset = ledger.import_benchmark_dataset(
            source=args.source,
            name=args.name or "kalshi-resolved-binary",
            description=args.description or "Settled binary Kalshi markets with prior market prices as baselines.",
            cases=cases,
            metadata={
                "adapter": "kalshi",
                "api_base_url": api_base_url,
                "limit": args.limit,
            },
        )
        print(f"imported benchmark dataset {dataset['id']}")
        print(f"name: {dataset['name']}")
        print(f"cases: {dataset['case_count']}")
        print(f"source: {args.source}")
        print(f"run: forecast backtest imported:{dataset['id']}")
        return
    if args.import_kind == "benchmark" and not args.question_id and str(args.source).startswith("manifold:"):
        if args.source != "manifold:resolved":
            raise SystemExit("supported Manifold benchmark source is manifold:resolved")
        cases = load_manifold_resolved_binary_cases(api_base_url=args.api_base_url, limit=args.limit)
        if not cases:
            raise SystemExit("manifold benchmark import found no resolved binary cases")
        dataset = ledger.import_benchmark_dataset(
            source=args.source,
            name=args.name or "manifold-resolved-binary",
            description=args.description or "Resolved binary Manifold markets with market probabilities as baselines.",
            cases=cases,
            metadata={
                "adapter": "manifold",
                "api_base_url": args.api_base_url,
                "limit": args.limit,
            },
        )
        print(f"imported benchmark dataset {dataset['id']}")
        print(f"name: {dataset['name']}")
        print(f"cases: {dataset['case_count']}")
        print(f"source: {args.source}")
        print(f"run: forecast backtest imported:{dataset['id']}")
        return
    if args.import_kind == "benchmark" and not args.question_id and _is_importable_benchmark_source(args.source):
        cases = _load_backtest_cases(args.source, ledger=ledger)
        dataset = ledger.import_benchmark_dataset(
            source=args.source,
            name=args.name,
            description=args.description,
            cases=cases,
            metadata={"adapter": "benchmark"},
        )
        print(f"imported benchmark dataset {dataset['id']}")
        print(f"name: {dataset['name']}")
        print(f"cases: {dataset['case_count']}")
        print(f"run: forecast backtest imported:{dataset['id']}")
        return
    if args.import_kind == "tournament" and not args.question_id and _is_importable_benchmark_source(args.source):
        cases = _load_backtest_cases(args.source, ledger=ledger)
        dataset = ledger.import_benchmark_dataset(
            source=args.source,
            name=args.name or "tournament-import",
            description=args.description or "Imported resolved tournament questions for time-aware replay.",
            cases=cases[: args.limit] if args.limit else cases,
            metadata={"adapter": "tournament"},
        )
        print(f"imported tournament benchmark dataset {dataset['id']}")
        print(f"name: {dataset['name']}")
        print(f"cases: {dataset['case_count']}")
        print(f"run: forecast backtest imported:{dataset['id']}")
        return
    if args.import_kind == "metaculus" and _should_use_metaculus_adapter(args):
        question = load_metaculus_question(args.source, api_base_url=args.api_base_url)
        baseline = question.baseline_payload()
        metaculus_metadata = {
            "adapter": "metaculus",
            "source": args.source,
            "question_id": question.question_id,
            "status": question.status,
            "resolution": question.resolution,
            "question_url": question.url,
        }
        if args.question_id:
            item = ledger.add_evidence(
                question_id=args.question_id,
                source_or_note=question.url or args.source,
                source_url=question.url,
                source_name="Metaculus",
                source_type="adapter:metaculus",
                published_at=question.as_of,
                available_at=question.as_of or args.as_of,
                claim=question.title,
                summary=question.description,
                stance="context",
                claim_type="estimate",
                metadata=metaculus_metadata,
            )
            print(f"captured metaculus evidence {item.id}")
            if baseline is not None:
                comparison = ledger.add_baseline_comparison(
                    question_id=args.question_id,
                    source=str(baseline["source"]),
                    baseline_type=str(baseline["baseline_type"]),
                    probability_or_distribution=baseline["probability_or_distribution"],
                    as_of=str(baseline.get("as_of") or args.as_of or ""),
                    metadata=metaculus_metadata,
                )
                print(f"captured metaculus baseline comparison {comparison['id']}")
                print(f"probability: {_format_probability(comparison['probability_or_distribution'])}")
            return
        metadata = metaculus_metadata
        if baseline is not None:
            metadata["baseline"] = baseline
        candidate = ledger.create_ingest_candidate(
            source=question.url or args.source,
            title=args.title or question.title,
            description=question.description,
            resolution_criteria=args.resolution_criteria or question.resolution_criteria,
            close_time=args.close_time or question.close_time,
            resolution_time=args.resolution_time or question.resolution_time,
            outcome_space=question.outcome_space,
            metadata=metadata,
        )
        print(f"created metaculus import candidate {candidate['id']}")
        print("confirmation required before creating an active forecast")
        if baseline is not None:
            print(f"crowd_probability: {_format_probability(baseline['probability_or_distribution'])}")
        return
    if args.import_kind == "manifold":
        market = load_manifold_market(args.source, api_base_url=args.api_base_url)
        baseline = market.baseline_payload()
        manifold_metadata = {
            "adapter": "manifold",
            "source": args.source,
            "market_id": market.market_id,
            "slug": market.slug,
            "outcome_type": market.raw.get("outcomeType"),
            "is_resolved": market.is_resolved,
            "resolution": market.resolution,
            "market_url": market.url,
        }
        if args.question_id:
            item = ledger.add_evidence(
                question_id=args.question_id,
                source_or_note=market.url or args.source,
                source_url=market.url,
                source_name="Manifold",
                source_type="adapter:manifold",
                published_at=market.as_of,
                available_at=market.as_of or args.as_of,
                claim=market.question,
                summary=market.description,
                stance="context",
                claim_type="estimate",
                metadata=manifold_metadata,
            )
            print(f"captured manifold evidence {item.id}")
            if baseline is not None:
                comparison = ledger.add_baseline_comparison(
                    question_id=args.question_id,
                    source=str(baseline["source"]),
                    baseline_type=str(baseline["baseline_type"]),
                    probability_or_distribution=baseline["probability_or_distribution"],
                    as_of=str(baseline.get("as_of") or args.as_of or ""),
                    metadata=manifold_metadata,
                )
                print(f"captured manifold baseline comparison {comparison['id']}")
                print(f"probability: {_format_probability(comparison['probability_or_distribution'])}")
            return
        metadata = manifold_metadata
        if baseline is not None:
            metadata["baseline"] = baseline
        candidate = ledger.create_ingest_candidate(
            source=market.url or args.source,
            title=args.title or market.question,
            description=market.description,
            resolution_criteria=args.resolution_criteria or market.resolution_criteria,
            close_time=args.close_time or market.close_time,
            resolution_time=args.resolution_time or market.resolution_time,
            outcome_space=market.outcome_space,
            metadata=metadata,
        )
        print(f"created manifold import candidate {candidate['id']}")
        print("confirmation required before creating an active forecast")
        if baseline is not None:
            print(f"market_probability: {_format_probability(baseline['probability_or_distribution'])}")
        return
    if args.import_kind == "polymarket":
        market = load_polymarket_market(args.source, api_base_url=args.api_base_url)
        baseline = market.baseline_payload()
        polymarket_metadata = {
            "adapter": "polymarket",
            "source": args.source,
            "market_id": market.market_id,
            "slug": market.slug,
            "market_url": market.url,
        }
        if args.question_id:
            item = ledger.add_evidence(
                question_id=args.question_id,
                source_or_note=market.url or args.source,
                source_url=market.url,
                source_name="Polymarket",
                source_type="adapter:polymarket",
                published_at=market.as_of,
                available_at=market.as_of or args.as_of,
                claim=market.question,
                summary=market.description,
                stance="context",
                claim_type="estimate",
                metadata=polymarket_metadata,
            )
            print(f"captured polymarket evidence {item.id}")
            if baseline is not None:
                comparison = ledger.add_baseline_comparison(
                    question_id=args.question_id,
                    source=str(baseline["source"]),
                    baseline_type=str(baseline["baseline_type"]),
                    probability_or_distribution=baseline["probability_or_distribution"],
                    as_of=str(baseline.get("as_of") or args.as_of or ""),
                    metadata=polymarket_metadata,
                )
                print(f"captured polymarket baseline comparison {comparison['id']}")
                print(f"probability: {_format_probability(comparison['probability_or_distribution'])}")
            return
        metadata = polymarket_metadata
        if baseline is not None:
            metadata["baseline"] = baseline
        candidate = ledger.create_ingest_candidate(
            source=market.url or args.source,
            title=args.title or market.question,
            description=market.description,
            resolution_criteria=args.resolution_criteria or market.resolution_criteria,
            close_time=args.close_time or market.close_time,
            resolution_time=args.resolution_time or market.resolution_time,
            outcome_space=market.outcome_space,
            metadata=metadata,
        )
        print(f"created polymarket import candidate {candidate['id']}")
        print("confirmation required before creating an active forecast")
        if baseline is not None:
            print(f"market_probability: {_format_probability(baseline['probability_or_distribution'])}")
        return
    if args.import_kind == "kalshi":
        market = load_kalshi_market(args.source, api_base_url=args.api_base_url)
        baseline = market.baseline_payload()
        kalshi_metadata = {
            "adapter": "kalshi",
            "source": args.source,
            "ticker": market.ticker,
            "event_ticker": market.event_ticker,
            "status": market.status,
            "market_url": market.url,
        }
        if args.question_id:
            item = ledger.add_evidence(
                question_id=args.question_id,
                source_or_note=market.url or args.source,
                source_url=market.url,
                source_name="Kalshi",
                source_type="adapter:kalshi",
                published_at=market.as_of,
                available_at=market.as_of or args.as_of,
                claim=market.question,
                summary=market.description,
                stance="context",
                claim_type="estimate",
                metadata=kalshi_metadata,
            )
            print(f"captured kalshi evidence {item.id}")
            if baseline is not None:
                comparison = ledger.add_baseline_comparison(
                    question_id=args.question_id,
                    source=str(baseline["source"]),
                    baseline_type=str(baseline["baseline_type"]),
                    probability_or_distribution=baseline["probability_or_distribution"],
                    as_of=str(baseline.get("as_of") or args.as_of or ""),
                    metadata=kalshi_metadata,
                )
                print(f"captured kalshi baseline comparison {comparison['id']}")
                print(f"probability: {_format_probability(comparison['probability_or_distribution'])}")
            return
        metadata = kalshi_metadata
        if baseline is not None:
            metadata["baseline"] = baseline
        candidate = ledger.create_ingest_candidate(
            source=market.url or args.source,
            title=args.title or market.question,
            description=market.description,
            resolution_criteria=args.resolution_criteria or market.resolution_criteria,
            close_time=args.close_time or market.close_time,
            resolution_time=args.resolution_time or market.resolution_time,
            outcome_space=market.outcome_space,
            metadata=metadata,
        )
        print(f"created kalshi import candidate {candidate['id']}")
        print("confirmation required before creating an active forecast")
        if baseline is not None:
            print(f"market_probability: {_format_probability(baseline['probability_or_distribution'])}")
        return
    if args.import_kind == "news" and args.question_id:
        items = load_news_feed_items(args.source, limit=args.limit, since=args.since)
        evidence_items = []
        for item in items:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=item.url or item.title,
                    source_url=item.url,
                    source_name=item.source_name,
                    source_type="adapter:news",
                    published_at=item.published_at,
                    available_at=item.published_at or args.as_of,
                    claim=item.title,
                    summary=item.summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "news",
                        "feed_source": args.source,
                        "feed_entry_id": item.entry_id,
                    },
                )
            )
        print(f"captured {len(evidence_items)} news evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "news" and not args.question_id:
        raise SystemExit("forecast import news requires --question")
    if args.import_kind == "gdelt":
        if not args.question_id:
            raise SystemExit("forecast import gdelt requires --question")
        articles = load_gdelt_articles(
            args.source,
            limit=args.limit,
            since=args.since,
            timespan=args.timespan,
            source_country=args.source_country,
            source_lang=args.source_lang,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for article in articles:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=article.url or article.title,
                    source_url=article.url,
                    source_name=article.source_name,
                    source_type="adapter:gdelt",
                    published_at=article.published_at,
                    available_at=article.published_at or args.as_of,
                    claim=article.title,
                    summary=article.summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "gdelt",
                        "gdelt_query": args.source,
                        "gdelt_article_id": article.entry_id,
                        "domain": article.domain,
                        "source_country": article.source_country,
                        "language": article.language,
                        "image_url": article.image_url,
                        "api_base_url": args.api_base_url,
                        "timespan": args.timespan,
                        "source_country_filter": args.source_country,
                        "source_lang_filter": args.source_lang,
                        "raw": article.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} gdelt evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "fivethirtyeight":
        if not args.question_id:
            raise SystemExit("forecast import fivethirtyeight requires --question")
        observations = load_fivethirtyeight_polls(
            args.source,
            limit=args.limit,
            since=args.since,
            state=args.state,
            candidate=args.candidate,
            pollster=args.pollster,
            cycle=args.cycle,
            office_type=args.office_type,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for observation in observations:
            subject = observation.candidate_name or observation.answer or "poll answer"
            pct = f"{observation.pct:g}%" if observation.pct is not None else "unknown share"
            geography = observation.state or "national"
            sample = f"; n={observation.sample_size:g}" if observation.sample_size is not None else ""
            population = f"; {observation.population}" if observation.population else ""
            date_span = " to ".join(
                part for part in (observation.start_date, observation.end_date) if part
            ) or "unknown dates"
            summary = (
                f"FiveThirtyEight {observation.dataset} poll from "
                f"{observation.pollster or 'unknown pollster'} for {geography}, "
                f"{date_span}: {subject} at {pct}{sample}{population}."
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=observation.source_url or f"FiveThirtyEight:{observation.dataset}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:fivethirtyeight",
                    published_at=observation.published_at,
                    available_at=observation.published_at or args.as_of,
                    claim=f"FiveThirtyEight poll: {subject} {pct} in {geography}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "fivethirtyeight",
                        "dataset": observation.dataset,
                        "poll_id": observation.poll_id,
                        "question_id": observation.question_id,
                        "pollster": observation.pollster,
                        "pollster_grade": observation.pollster_grade,
                        "race_id": observation.race_id,
                        "office_type": observation.office_type,
                        "state": observation.state,
                        "cycle": observation.cycle,
                        "stage": observation.stage,
                        "candidate_name": observation.candidate_name,
                        "answer": observation.answer,
                        "party": observation.party,
                        "pct": observation.pct,
                        "sample_size": observation.sample_size,
                        "population": observation.population,
                        "start_date": observation.start_date,
                        "end_date": observation.end_date,
                        "api_base_url": args.api_base_url,
                        "state_filter": args.state,
                        "candidate_filter": args.candidate,
                        "pollster_filter": args.pollster,
                        "cycle_filter": args.cycle,
                        "office_type_filter": args.office_type,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} fivethirtyeight evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "github":
        if not args.question_id:
            raise SystemExit("forecast import github requires --question")
        releases = load_github_releases(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for release in releases:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=release.html_url or release.url or f"GitHub:{release.repo}:{release.tag_name}",
                    source_url=release.html_url or release.url,
                    source_name=release.source_name,
                    source_type="adapter:github",
                    published_at=release.published_at,
                    available_at=release.published_at or release.created_at or args.as_of,
                    claim=f"GitHub release: {release.repo} {release.tag_name}",
                    summary=release.body or release.name,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "github",
                        "repo": release.repo,
                        "release_id": release.release_id,
                        "tag_name": release.tag_name,
                        "name": release.name,
                        "created_at": release.created_at,
                        "draft": release.draft,
                        "prerelease": release.prerelease,
                        "api_base_url": args.api_base_url,
                        "raw": release.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} github evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "githubissues":
        if not args.question_id:
            raise SystemExit("forecast import githubissues requires --question")
        issues = load_github_issues(
            args.source,
            limit=args.limit,
            since=args.since,
            state=args.state,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for issue in issues:
            issue_kind = "pull request" if issue.is_pull_request else "issue"
            number = f"#{issue.issue_number}" if issue.issue_number is not None else issue.entry_id
            status_bits = [bit for bit in (issue.state, issue.updated_at, f"{issue.comments} comments") if bit]
            label_text = ", ".join(issue.labels[:5]) if issue.labels else "no labels"
            summary = (
                f"GitHub {issue_kind} {issue.repo} {number}: {issue.title}. "
                f"{'; '.join(str(bit) for bit in status_bits)}; labels: {label_text}."
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=issue.html_url or issue.url or f"GitHub:{issue.repo}:{number}",
                    source_url=issue.html_url or issue.url,
                    source_name=issue.source_name,
                    source_type="adapter:githubissues",
                    published_at=issue.updated_at or issue.created_at,
                    available_at=issue.updated_at or issue.created_at or args.as_of,
                    claim=f"GitHub {issue_kind}: {issue.repo} {number} {issue.state or 'state unknown'}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "githubissues",
                        "repo": issue.repo,
                        "issue_number": issue.issue_number,
                        "title": issue.title,
                        "state": issue.state,
                        "is_pull_request": issue.is_pull_request,
                        "author": issue.author,
                        "labels": issue.labels,
                        "created_at": issue.created_at,
                        "updated_at": issue.updated_at,
                        "closed_at": issue.closed_at,
                        "comments": issue.comments,
                        "api_base_url": args.api_base_url,
                        "raw": issue.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} githubissues evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "githubcommits":
        if not args.question_id:
            raise SystemExit("forecast import githubcommits requires --question")
        commits = load_github_commits(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for commit in commits:
            author = commit.author_login or commit.author_name or "unknown author"
            summary = (
                f"GitHub commit {commit.repo}@{commit.short_sha}: {commit.message}. "
                f"Committed by {author}"
                + (f" at {commit.committed_at}." if commit.committed_at else ".")
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=commit.html_url or commit.url or f"GitHub:{commit.repo}@{commit.sha}",
                    source_url=commit.html_url or commit.url,
                    source_name=commit.source_name,
                    source_type="adapter:githubcommits",
                    published_at=commit.committed_at or commit.authored_at,
                    available_at=commit.committed_at or commit.authored_at or args.as_of,
                    claim=f"GitHub commit: {commit.repo} {commit.short_sha}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "githubcommits",
                        "repo": commit.repo,
                        "sha": commit.sha,
                        "short_sha": commit.short_sha,
                        "message": commit.message,
                        "author_name": commit.author_name,
                        "author_login": commit.author_login,
                        "authored_at": commit.authored_at,
                        "committed_at": commit.committed_at,
                        "comments": commit.comments,
                        "api_base_url": args.api_base_url,
                        "raw": commit.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} githubcommits evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "githubactions":
        if not args.question_id:
            raise SystemExit("forecast import githubactions requires --question")
        runs = load_github_workflow_runs(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for run in runs:
            status_text = run.conclusion or run.status or "state unknown"
            branch = f" on {run.head_branch}" if run.head_branch else ""
            actor = run.triggering_actor_login or run.actor_login or "unknown actor"
            summary = (
                f"GitHub Actions run {run.repo} #{run.run_id}: {run.display_title}. "
                f"Workflow {run.name} {status_text}{branch}; triggered by {actor}"
                + (f" at {run.updated_at}." if run.updated_at else ".")
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=run.html_url or run.url or f"GitHub:{run.repo}:actions:{run.run_id}",
                    source_url=run.html_url or run.url,
                    source_name=run.source_name,
                    source_type="adapter:githubactions",
                    published_at=run.updated_at or run.run_started_at or run.created_at,
                    available_at=run.updated_at or run.run_started_at or run.created_at or args.as_of,
                    claim=f"GitHub Actions run: {run.repo} {run.run_id} {status_text}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "githubactions",
                        "repo": run.repo,
                        "run_id": run.run_id,
                        "name": run.name,
                        "display_title": run.display_title,
                        "status": run.status,
                        "conclusion": run.conclusion,
                        "event": run.event,
                        "head_branch": run.head_branch,
                        "head_sha": run.head_sha,
                        "short_sha": run.short_sha,
                        "workflow_id": run.workflow_id,
                        "workflow_url": run.workflow_url,
                        "actor_login": run.actor_login,
                        "triggering_actor_login": run.triggering_actor_login,
                        "run_started_at": run.run_started_at,
                        "created_at": run.created_at,
                        "updated_at": run.updated_at,
                        "api_base_url": args.api_base_url,
                        "raw": run.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} githubactions evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "pypi":
        if not args.question_id:
            raise SystemExit("forecast import pypi requires --question")
        releases = load_pypi_releases(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for release in releases:
            package_types = ", ".join(release.package_types) if release.package_types else "unknown file types"
            python_versions = (
                ", ".join(release.python_versions[:5]) if release.python_versions else "unknown Python versions"
            )
            status = "yanked" if release.yanked else "available"
            summary = (
                f"PyPI release {release.package} {release.version}: {release.summary or 'no project summary'}. "
                f"{release.file_count} files; {package_types}; Python {python_versions}; "
                f"first uploaded {release.uploaded_at or 'unknown'}; latest upload {release.latest_upload_at or 'unknown'}; "
                f"status {status}."
            )
            if release.yanked_reason:
                summary += f" Yanked reason: {release.yanked_reason}."
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=release.url or release.project_url or f"PyPI:{release.package}:{release.version}",
                    source_url=release.url or release.project_url,
                    source_name=release.source_name,
                    source_type="adapter:pypi",
                    published_at=release.uploaded_at,
                    available_at=release.latest_upload_at or release.uploaded_at or args.as_of,
                    claim=f"PyPI release: {release.package} {release.version}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "pypi",
                        "package": release.package,
                        "version": release.version,
                        "uploaded_at": release.uploaded_at,
                        "latest_upload_at": release.latest_upload_at,
                        "file_count": release.file_count,
                        "package_types": release.package_types,
                        "python_versions": release.python_versions,
                        "yanked": release.yanked,
                        "yanked_reason": release.yanked_reason,
                        "api_base_url": args.api_base_url,
                        "raw": release.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} pypi evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "npm":
        if not args.question_id:
            raise SystemExit("forecast import npm requires --question")
        versions = load_npm_package_versions(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for version in versions:
            maintainers = ", ".join(version.maintainers[:3]) if version.maintainers else "maintainers unspecified"
            keywords = ", ".join(version.keywords[:5]) if version.keywords else "no keywords"
            status = "deprecated" if version.deprecated else "available"
            summary = (
                f"npm package {version.package} {version.version}: {version.description or 'no package description'}. "
                f"published {version.published_at or 'unknown'}; license {version.license or 'unknown'}; "
                f"{version.dependency_count} dependencies; {maintainers}; keywords: {keywords}; status {status}."
            )
            if version.deprecated:
                summary += f" Deprecation notice: {version.deprecated}."
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=version.url or version.tarball_url or f"npm:{version.package}:{version.version}",
                    source_url=version.url or version.tarball_url,
                    source_name=version.source_name,
                    source_type="adapter:npm",
                    published_at=version.published_at,
                    available_at=version.published_at or args.as_of,
                    claim=f"npm package version: {version.package} {version.version}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "npm",
                        "package": version.package,
                        "version": version.version,
                        "published_at": version.published_at,
                        "license": version.license,
                        "maintainers": version.maintainers,
                        "keywords": version.keywords,
                        "deprecated": version.deprecated,
                        "dependency_count": version.dependency_count,
                        "api_base_url": args.api_base_url,
                        "raw": version.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} npm evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "hackernews":
        if not args.question_id:
            raise SystemExit("forecast import hackernews requires --question")
        items = load_hackernews_items(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for item in items:
            engagement = []
            if item.points is not None:
                engagement.append(f"{item.points} points")
            if item.comments is not None:
                engagement.append(f"{item.comments} comments")
            engagement_text = f" ({', '.join(engagement)})" if engagement else ""
            summary = (
                f"Hacker News story by {item.author or 'unknown'} at {item.created_at or 'unknown'}"
                f"{engagement_text}."
            )
            if item.story_text:
                summary = f"{summary} {item.story_text}"
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=item.url or item.hn_url or f"HackerNews:{item.object_id}",
                    source_url=item.url or item.hn_url,
                    source_name=item.source_name,
                    source_type="adapter:hackernews",
                    published_at=item.created_at,
                    available_at=item.created_at or args.as_of,
                    claim=f"Hacker News: {item.title}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "hackernews",
                        "query": args.source,
                        "object_id": item.object_id,
                        "hn_url": item.hn_url,
                        "author": item.author,
                        "created_at": item.created_at,
                        "points": item.points,
                        "comments": item.comments,
                        "story_id": item.story_id,
                        "api_base_url": args.api_base_url,
                        "raw": item.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} hackernews evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "reddit":
        if not args.question_id:
            raise SystemExit("forecast import reddit requires --question")
        posts = load_reddit_posts(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for post in posts:
            engagement = []
            if post.score is not None:
                engagement.append(f"{post.score} score")
            if post.comments is not None:
                engagement.append(f"{post.comments} comments")
            if post.upvote_ratio is not None:
                engagement.append(f"{post.upvote_ratio:g} upvote ratio")
            engagement_text = f" ({', '.join(engagement)})" if engagement else ""
            subreddit_text = f" in r/{post.subreddit}" if post.subreddit else ""
            summary = (
                f"Reddit post by {post.author or 'unknown'}{subreddit_text} at "
                f"{post.created_at or 'unknown'}{engagement_text}."
            )
            if post.selftext:
                summary = f"{summary} {post.selftext}"
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=post.url or post.permalink or f"Reddit:{post.post_id}",
                    source_url=post.url or post.permalink,
                    source_name=post.source_name,
                    source_type="adapter:reddit",
                    published_at=post.created_at,
                    available_at=post.created_at or args.as_of,
                    claim=f"Reddit: {post.title}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "reddit",
                        "query": args.source,
                        "post_id": post.post_id,
                        "subreddit": post.subreddit,
                        "author": post.author,
                        "created_at": post.created_at,
                        "score": post.score,
                        "comments": post.comments,
                        "upvote_ratio": post.upvote_ratio,
                        "permalink": post.permalink,
                        "api_base_url": args.api_base_url,
                        "raw": post.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} reddit evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "bluesky":
        if not args.question_id:
            raise SystemExit("forecast import bluesky requires --question")
        posts = load_bluesky_posts(
            args.source,
            limit=args.limit,
            since=args.since,
            sort=args.sort,
            author=args.author,
            lang=args.lang,
            link_domain=args.link_domain,
            url_filter=args.url_filter,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for post in posts:
            engagement = []
            if post.reply_count is not None:
                engagement.append(f"{post.reply_count} replies")
            if post.repost_count is not None:
                engagement.append(f"{post.repost_count} reposts")
            if post.like_count is not None:
                engagement.append(f"{post.like_count} likes")
            if post.quote_count is not None:
                engagement.append(f"{post.quote_count} quotes")
            engagement_text = f" ({', '.join(engagement)})" if engagement else ""
            author_text = f" by @{post.author_handle}" if post.author_handle else ""
            summary = (
                f"Bluesky post{author_text} at {post.created_at or post.indexed_at or 'unknown'}"
                f"{engagement_text}."
            )
            if post.text:
                summary = f"{summary} {post.text}"
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=post.url or f"Bluesky:{post.post_uri}",
                    source_url=post.url,
                    source_name=post.source_name,
                    source_type="adapter:bluesky",
                    published_at=post.created_at,
                    available_at=post.created_at or post.indexed_at or args.as_of,
                    claim=f"Bluesky: {post.text[:140] if post.text else post.post_uri}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "bluesky",
                        "query": args.source,
                        "post_uri": post.post_uri,
                        "cid": post.cid,
                        "author_handle": post.author_handle,
                        "author_display_name": post.author_display_name,
                        "author_did": post.author_did,
                        "created_at": post.created_at,
                        "indexed_at": post.indexed_at,
                        "reply_count": post.reply_count,
                        "repost_count": post.repost_count,
                        "like_count": post.like_count,
                        "quote_count": post.quote_count,
                        "sort": args.sort,
                        "author_filter": args.author,
                        "lang_filter": args.lang,
                        "link_domain_filter": args.link_domain,
                        "url_filter": args.url_filter,
                        "api_base_url": args.api_base_url,
                        "raw": post.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} bluesky evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "mastodon":
        if not args.question_id:
            raise SystemExit("forecast import mastodon requires --question")
        statuses = load_mastodon_statuses(
            args.source,
            limit=args.limit,
            since=args.since,
            local=args.local,
            only_media=args.only_media,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for status in statuses:
            engagement = []
            if status.replies_count is not None:
                engagement.append(f"{status.replies_count} replies")
            if status.reblogs_count is not None:
                engagement.append(f"{status.reblogs_count} boosts")
            if status.favourites_count is not None:
                engagement.append(f"{status.favourites_count} favourites")
            engagement_text = f" ({', '.join(engagement)})" if engagement else ""
            account_text = f" by @{status.account_acct}" if status.account_acct else ""
            tag_text = f" tags: {', '.join(status.tags[:5])}." if status.tags else ""
            card_text = f" Link: {status.card_title or status.card_url}." if status.card_url or status.card_title else ""
            summary = (
                f"Mastodon status{account_text} at {status.created_at or 'unknown'}"
                f"{engagement_text}.{tag_text}{card_text} {status.content_text}"
            ).strip()
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=status.url or status.uri or f"Mastodon:{status.status_id}",
                    source_url=status.url or status.uri,
                    source_name=status.source_name,
                    source_type="adapter:mastodon",
                    published_at=status.created_at,
                    available_at=status.created_at or args.as_of,
                    claim=f"Mastodon: {status.content_text[:140] if status.content_text else status.status_id}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "mastodon",
                        "source": args.source,
                        "status_id": status.status_id,
                        "uri": status.uri,
                        "account_acct": status.account_acct,
                        "account_username": status.account_username,
                        "account_display_name": status.account_display_name,
                        "account_url": status.account_url,
                        "created_at": status.created_at,
                        "replies_count": status.replies_count,
                        "reblogs_count": status.reblogs_count,
                        "favourites_count": status.favourites_count,
                        "language": status.language,
                        "visibility": status.visibility,
                        "tags": status.tags,
                        "card_url": status.card_url,
                        "card_title": status.card_title,
                        "local": args.local,
                        "only_media": args.only_media,
                        "api_base_url": args.api_base_url,
                        "raw": status.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} mastodon evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "reliefweb":
        if not args.question_id:
            raise SystemExit("forecast import reliefweb requires --question")
        reports = load_reliefweb_reports(
            args.source,
            limit=args.limit,
            since=args.since,
            appname=args.appname,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for report in reports:
            geography = f" Countries: {', '.join(report.countries[:5])}." if report.countries else ""
            disasters = f" Disasters: {', '.join(report.disasters[:5])}." if report.disasters else ""
            source_text = f" Sources: {', '.join(report.sources[:5])}." if report.sources else ""
            summary = f"{report.summary}{geography}{disasters}{source_text}".strip()
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=report.url or f"ReliefWeb:{report.entry_id or report.title}",
                    source_url=report.url,
                    source_name=report.source_name,
                    source_type="adapter:reliefweb",
                    published_at=report.published_at,
                    available_at=report.published_at or report.changed_at or args.as_of,
                    claim=f"ReliefWeb: {report.title}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "reliefweb",
                        "query": args.source,
                        "report_id": report.report_id,
                        "changed_at": report.changed_at,
                        "sources": report.sources,
                        "countries": report.countries,
                        "disasters": report.disasters,
                        "formats": report.formats,
                        "themes": report.themes,
                        "api_base_url": args.api_base_url,
                        "appname": args.appname,
                        "raw": report.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} reliefweb evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "federalregister":
        if not args.question_id:
            raise SystemExit("forecast import federalregister requires --question")
        documents = load_federal_register_documents(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for document in documents:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=document.url or document.pdf_url or f"FederalRegister:{document.entry_id}",
                    source_url=document.url or document.pdf_url,
                    source_name=document.source_name,
                    source_type="adapter:federalregister",
                    published_at=document.published_at,
                    available_at=document.published_at or args.as_of,
                    claim=f"Federal Register: {document.title}",
                    summary=document.abstract,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "federalregister",
                        "query": args.source,
                        "document_number": document.document_number,
                        "document_type": document.document_type,
                        "agencies": document.agencies,
                        "citation": document.citation,
                        "pdf_url": document.pdf_url,
                        "api_base_url": args.api_base_url,
                        "raw": document.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} federalregister evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "courtlistener":
        if not args.question_id:
            raise SystemExit("forecast import courtlistener requires --question")
        results = load_courtlistener_search_results(
            args.source,
            limit=args.limit,
            since=args.since,
            search_type=args.search_type,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for result in results:
            court_label = f" ({result.court_id or result.court})" if result.court_id or result.court else ""
            filed = f" filed {result.date_filed}" if result.date_filed else ""
            citation = f" Citation: {result.citation}." if result.citation else ""
            judge = f" Judge: {result.judge}." if result.judge else ""
            summary = (
                f"CourtListener result{court_label}{filed}."
                f"{citation}{judge} {result.snippet}".strip()
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=result.url or f"CourtListener:{result.entry_id or result.title}",
                    source_url=result.url,
                    source_name=result.source_name,
                    source_type="adapter:courtlistener",
                    published_at=result.date_filed,
                    available_at=result.date_filed or result.date_argued or args.as_of,
                    claim=f"CourtListener: {result.title}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "courtlistener",
                        "query": args.source,
                        "result_id": result.result_id,
                        "court": result.court,
                        "court_id": result.court_id,
                        "docket_number": result.docket_number,
                        "date_filed": result.date_filed,
                        "date_argued": result.date_argued,
                        "status": result.status,
                        "citation": result.citation,
                        "judge": result.judge,
                        "cite_count": result.cite_count,
                        "search_type": result.search_type,
                        "api_base_url": args.api_base_url,
                        "raw": result.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} courtlistener evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "nvd":
        if not args.question_id:
            raise SystemExit("forecast import nvd requires --question")
        cves = load_nvd_cves(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for cve in cves:
            severity = f" {cve.severity}" if cve.severity else ""
            score = f" CVSS {cve.base_score:g}" if cve.base_score is not None else ""
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=cve.url or f"NVD:{cve.cve_id}",
                    source_url=cve.url,
                    source_name=cve.source_name,
                    source_type="adapter:nvd",
                    published_at=cve.published_at,
                    available_at=cve.published_at or cve.last_modified_at or args.as_of,
                    claim=f"NVD CVE: {cve.cve_id}{severity}{score}",
                    summary=cve.description,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "nvd",
                        "query": args.source,
                        "cve_id": cve.cve_id,
                        "last_modified_at": cve.last_modified_at,
                        "vuln_status": cve.vuln_status,
                        "severity": cve.severity,
                        "base_score": cve.base_score,
                        "cvss_version": cve.cvss_version,
                        "references": cve.references,
                        "source_identifier": cve.source_identifier,
                        "api_base_url": args.api_base_url,
                        "raw": cve.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} nvd evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "cisakev":
        if not args.question_id:
            raise SystemExit("forecast import cisakev requires --question")
        vulnerabilities = load_cisa_kev_vulnerabilities(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for vulnerability in vulnerabilities:
            vendor = f"{vulnerability.vendor_project} " if vulnerability.vendor_project else ""
            product = vulnerability.product or "affected product"
            ransomware = (
                f" Ransomware use: {vulnerability.ransomware_use}."
                if vulnerability.ransomware_use
                else ""
            )
            due = f" Remediation due {vulnerability.due_date}." if vulnerability.due_date else ""
            action = f" Required action: {vulnerability.required_action}" if vulnerability.required_action else ""
            summary = (
                f"{vulnerability.short_description} Date added {vulnerability.date_added or 'unknown'}."
                f"{due}{ransomware}{action}"
            ).strip()
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=vulnerability.source_url or f"CISAKEV:{vulnerability.cve_id}",
                    source_url=vulnerability.source_url,
                    source_name=vulnerability.source_name,
                    source_type="adapter:cisakev",
                    published_at=vulnerability.date_added,
                    available_at=vulnerability.date_added or args.as_of,
                    claim=f"CISA KEV: {vulnerability.cve_id} {vendor}{product}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "cisakev",
                        "query": args.source,
                        "cve_id": vulnerability.cve_id,
                        "vendor_project": vulnerability.vendor_project,
                        "product": vulnerability.product,
                        "vulnerability_name": vulnerability.vulnerability_name,
                        "due_date": vulnerability.due_date,
                        "required_action": vulnerability.required_action,
                        "ransomware_use": vulnerability.ransomware_use,
                        "notes": vulnerability.notes,
                        "cwes": vulnerability.cwes,
                        "api_base_url": args.api_base_url,
                        "raw": vulnerability.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} cisakev evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "usgs":
        if not args.question_id:
            raise SystemExit("forecast import usgs requires --question")
        events = load_usgs_earthquakes(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for event in events:
            magnitude = f"M{event.magnitude:g}" if event.magnitude is not None else "event"
            event_label = event.event_type or "event"
            location = event.place or event.title
            coordinate_text = (
                f" Coordinates {event.latitude:g},{event.longitude:g}."
                if event.latitude is not None and event.longitude is not None
                else ""
            )
            depth_text = f" Depth {event.depth_km:g} km." if event.depth_km is not None else ""
            status_text = f" Status {event.status}." if event.status else ""
            summary = (
                f"USGS {event_label} {magnitude} at {location}. "
                f"Event time {event.time or 'unknown'}."
                f"{depth_text}{coordinate_text}{status_text}"
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=event.url or f"USGS:{event.entry_id or event.title}",
                    source_url=event.url,
                    source_name=event.source_name,
                    source_type="adapter:usgs",
                    published_at=event.time,
                    available_at=event.time or args.as_of,
                    claim=f"USGS {event_label} {magnitude}: {location}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "usgs",
                        "query": args.source,
                        "event_id": event.event_id,
                        "title": event.title,
                        "magnitude": event.magnitude,
                        "place": event.place,
                        "event_type": event.event_type,
                        "status": event.status,
                        "tsunami": event.tsunami,
                        "significance": event.significance,
                        "longitude": event.longitude,
                        "latitude": event.latitude,
                        "depth_km": event.depth_km,
                        "updated_at": event.updated_at,
                        "api_base_url": args.api_base_url,
                        "raw": event.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} usgs evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "eonet":
        if not args.question_id:
            raise SystemExit("forecast import eonet requires --question")
        events = load_nasa_eonet_events(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for event in events:
            category_label = ", ".join(event.categories) if event.categories else "natural event"
            coordinate_text = (
                f" Coordinates {event.latitude:g},{event.longitude:g}."
                if event.latitude is not None and event.longitude is not None
                else ""
            )
            closed_text = f" Closed {event.closed_at}." if event.closed_at else ""
            source_text = f" Sources: {', '.join(event.source_names)}." if event.source_names else ""
            summary = (
                f"NASA EONET event {event.title}. Category: {category_label}. "
                f"Status {event.status or 'unknown'}. Latest geometry {event.latest_geometry_at or 'unknown'}."
                f"{coordinate_text}{closed_text}{source_text} {event.description}".strip()
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=event.url or f"EONET:{event.entry_id or event.title}",
                    source_url=event.url,
                    source_name=event.source_name,
                    source_type="adapter:eonet",
                    published_at=event.latest_geometry_at,
                    available_at=event.latest_geometry_at or args.as_of,
                    claim=f"NASA EONET {category_label}: {event.title}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "eonet",
                        "query": args.source,
                        "event_id": event.event_id,
                        "title": event.title,
                        "status": event.status,
                        "closed_at": event.closed_at,
                        "latest_geometry_at": event.latest_geometry_at,
                        "categories": event.categories,
                        "source_names": event.source_names,
                        "source_urls": event.source_urls,
                        "longitude": event.longitude,
                        "latitude": event.latitude,
                        "api_base_url": args.api_base_url,
                        "raw": event.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} eonet evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "nws":
        if not args.question_id:
            raise SystemExit("forecast import nws requires --question")
        alerts = load_nws_alerts(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for alert in alerts:
            timing = [
                f"sent {alert.sent_at or 'unknown'}",
                f"effective {alert.effective_at or 'unknown'}",
                f"expires {alert.expires_at or 'unknown'}",
            ]
            severity_bits = [
                bit
                for bit in (alert.severity, alert.urgency, alert.certainty, alert.status, alert.message_type)
                if bit
            ]
            summary = (
                f"NWS {alert.event} for {alert.area_desc or 'unknown area'}. "
                f"{'; '.join(timing)}. "
                f"{' / '.join(severity_bits) if severity_bits else 'No severity metadata'}."
            )
            if alert.description:
                summary = f"{summary} {alert.description}"
            if alert.instruction:
                summary = f"{summary} Instructions: {alert.instruction}"
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=alert.url or f"NWS:{alert.entry_id or alert.headline}",
                    source_url=alert.url,
                    source_name=alert.source_name,
                    source_type="adapter:nws",
                    published_at=alert.sent_at,
                    available_at=alert.sent_at or alert.effective_at or args.as_of,
                    claim=f"NWS {alert.event}: {alert.headline}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "nws",
                        "query": args.source,
                        "alert_id": alert.alert_id,
                        "event": alert.event,
                        "headline": alert.headline,
                        "area_desc": alert.area_desc,
                        "severity": alert.severity,
                        "certainty": alert.certainty,
                        "urgency": alert.urgency,
                        "status": alert.status,
                        "message_type": alert.message_type,
                        "category": alert.category,
                        "response": alert.response,
                        "sent_at": alert.sent_at,
                        "effective_at": alert.effective_at,
                        "onset_at": alert.onset_at,
                        "expires_at": alert.expires_at,
                        "ends_at": alert.ends_at,
                        "api_base_url": args.api_base_url,
                        "raw": alert.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} nws evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "clinicaltrials":
        if not args.question_id:
            raise SystemExit("forecast import clinicaltrials requires --question")
        studies = load_clinicaltrials_studies(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for study in studies:
            phase_text = ", ".join(study.phases) if study.phases else "phase unspecified"
            condition_text = ", ".join(study.conditions[:3]) if study.conditions else "conditions unspecified"
            sponsor_text = ", ".join(study.sponsors[:2]) if study.sponsors else "sponsor unspecified"
            summary = (
                f"ClinicalTrials.gov study {study.nct_id}: {study.brief_title}. "
                f"Status {study.status or 'unknown'}; {phase_text}; conditions: {condition_text}; "
                f"sponsor: {sponsor_text}; primary completion "
                f"{study.primary_completion_date or 'unknown'}; last update "
                f"{study.last_update_posted_at or study.last_update_submitted_at or 'unknown'}."
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=study.url or f"ClinicalTrials:{study.nct_id}",
                    source_url=study.url,
                    source_name=study.source_name,
                    source_type="adapter:clinicaltrials",
                    published_at=study.last_update_posted_at or study.last_update_submitted_at,
                    available_at=study.last_update_posted_at or study.last_update_submitted_at or args.as_of,
                    claim=f"ClinicalTrials.gov {study.nct_id}: {study.status or 'unknown'} - {study.brief_title}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "clinicaltrials",
                        "query": args.source,
                        "nct_id": study.nct_id,
                        "status": study.status,
                        "phases": study.phases,
                        "study_type": study.study_type,
                        "conditions": study.conditions,
                        "interventions": study.interventions,
                        "sponsors": study.sponsors,
                        "start_date": study.start_date,
                        "primary_completion_date": study.primary_completion_date,
                        "completion_date": study.completion_date,
                        "last_update_submitted_at": study.last_update_submitted_at,
                        "last_update_posted_at": study.last_update_posted_at,
                        "has_results": study.has_results,
                        "api_base_url": args.api_base_url,
                        "raw": study.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} clinicaltrials evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "openfda":
        if not args.question_id:
            raise SystemExit("forecast import openfda requires --question")
        applications = load_openfda_drug_applications(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for application in applications:
            brand_text = ", ".join(application.brand_names[:3]) if application.brand_names else "brand unspecified"
            generic_text = (
                ", ".join(application.generic_names[:3]) if application.generic_names else "generic name unspecified"
            )
            route_text = ", ".join(application.routes[:3]) if application.routes else "route unspecified"
            status_bits = [
                bit
                for bit in (
                    application.latest_submission_status,
                    application.latest_submission_type,
                    application.latest_submission_class,
                )
                if bit
            ]
            summary = (
                f"openFDA Drugs@FDA application {application.application_number}: {brand_text} "
                f"({generic_text}). Sponsor {application.sponsor_name or 'unknown'}; routes: {route_text}; "
                f"latest submission date {application.latest_submission_status_date or 'unknown'}; "
                f"{' / '.join(status_bits) if status_bits else 'no submission status metadata'}."
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=application.url or f"openFDA:{application.application_number}",
                    source_url=application.url,
                    source_name=application.source_name,
                    source_type="adapter:openfda",
                    published_at=application.latest_submission_status_date,
                    available_at=application.latest_submission_status_date or args.as_of,
                    claim=(
                        f"openFDA {application.application_number}: "
                        f"{application.latest_submission_status or 'application'} - {brand_text}"
                    ),
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "openfda",
                        "query": args.source,
                        "application_number": application.application_number,
                        "sponsor_name": application.sponsor_name,
                        "brand_names": application.brand_names,
                        "generic_names": application.generic_names,
                        "routes": application.routes,
                        "substances": application.substances,
                        "dosage_forms": application.dosage_forms,
                        "marketing_statuses": application.marketing_statuses,
                        "latest_submission_status": application.latest_submission_status,
                        "latest_submission_status_date": application.latest_submission_status_date,
                        "latest_submission_type": application.latest_submission_type,
                        "latest_submission_class": application.latest_submission_class,
                        "api_base_url": args.api_base_url,
                        "raw": application.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} openfda evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "pubmed":
        if not args.question_id:
            raise SystemExit("forecast import pubmed requires --question")
        articles = load_pubmed_articles(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for article in articles:
            author_text = ", ".join(article.authors[:3]) if article.authors else "authors unspecified"
            type_text = (
                ", ".join(article.publication_types[:3])
                if article.publication_types
                else "publication type unspecified"
            )
            summary = (
                f"PubMed article {article.pmid}: {article.title}. "
                f"Journal {article.journal or 'unknown'}; {author_text}; {type_text}; "
                f"published {article.published_at or 'unknown'}; revised {article.revised_at or 'unknown'}. "
                f"{article.abstract}"
            ).strip()
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=article.url or f"PubMed:{article.pmid}",
                    source_url=article.url,
                    source_name=article.source_name,
                    source_type="adapter:pubmed",
                    published_at=article.published_at,
                    available_at=article.published_at or article.revised_at or args.as_of,
                    claim=f"PubMed {article.pmid}: {article.title}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "pubmed",
                        "pubmed_query": args.source,
                        "pmid": article.pmid,
                        "doi": article.doi,
                        "journal": article.journal,
                        "published_at": article.published_at,
                        "revised_at": article.revised_at,
                        "authors": article.authors,
                        "publication_types": article.publication_types,
                        "api_base_url": args.api_base_url,
                        "raw": article.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} pubmed evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "openmeteo":
        if not args.question_id:
            raise SystemExit("forecast import openmeteo requires --question")
        forecasts = load_openmeteo_daily_forecasts(
            args.source,
            limit=args.limit,
            since=args.since,
            forecast_days=args.forecast_days,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for forecast in forecasts:
            summary = (
                f"Open-Meteo daily forecast for {forecast.latitude:g},{forecast.longitude:g} "
                f"on {forecast.forecast_date}: max {forecast.temperature_2m_max}, "
                f"min {forecast.temperature_2m_min}, precipitation {forecast.precipitation_sum}, "
                f"wind max {forecast.wind_speed_10m_max}."
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=f"OpenMeteo:{forecast.latitude:g},{forecast.longitude:g}:{forecast.forecast_date}",
                    source_name=forecast.source_name,
                    source_type="adapter:openmeteo",
                    available_at=args.as_of,
                    claim=(
                        f"Open-Meteo daily forecast {forecast.forecast_date}: "
                        f"max {forecast.temperature_2m_max}, precip {forecast.precipitation_sum}"
                    ),
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "openmeteo",
                        "latitude": forecast.latitude,
                        "longitude": forecast.longitude,
                        "forecast_date": forecast.forecast_date,
                        "temperature_2m_max": forecast.temperature_2m_max,
                        "temperature_2m_min": forecast.temperature_2m_min,
                        "precipitation_sum": forecast.precipitation_sum,
                        "wind_speed_10m_max": forecast.wind_speed_10m_max,
                        "api_base_url": args.api_base_url,
                        "forecast_days": args.forecast_days,
                        "raw": forecast.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} openmeteo evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "airquality":
        if not args.question_id:
            raise SystemExit("forecast import airquality requires --question")
        forecasts = load_openmeteo_air_quality_forecasts(
            args.source,
            limit=args.limit,
            since=args.since,
            forecast_days=args.forecast_days,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for forecast in forecasts:
            summary = (
                f"Open-Meteo air quality forecast for {forecast.latitude:g},{forecast.longitude:g} "
                f"at {forecast.forecast_time}: US AQI {forecast.us_aqi}, "
                f"European AQI {forecast.european_aqi}, PM2.5 {forecast.pm2_5}, "
                f"PM10 {forecast.pm10}, CO {forecast.carbon_monoxide}, "
                f"NO2 {forecast.nitrogen_dioxide}, O3 {forecast.ozone}."
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=f"OpenMeteoAirQuality:{forecast.latitude:g},{forecast.longitude:g}:{forecast.forecast_time}",
                    source_name=forecast.source_name,
                    source_type="adapter:airquality",
                    available_at=args.as_of,
                    claim=(
                        f"Open-Meteo air quality forecast {forecast.forecast_time}: "
                        f"US AQI {forecast.us_aqi}, PM2.5 {forecast.pm2_5}"
                    ),
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "airquality",
                        "latitude": forecast.latitude,
                        "longitude": forecast.longitude,
                        "forecast_time": forecast.forecast_time,
                        "us_aqi": forecast.us_aqi,
                        "european_aqi": forecast.european_aqi,
                        "pm10": forecast.pm10,
                        "pm2_5": forecast.pm2_5,
                        "carbon_monoxide": forecast.carbon_monoxide,
                        "nitrogen_dioxide": forecast.nitrogen_dioxide,
                        "ozone": forecast.ozone,
                        "api_base_url": args.api_base_url,
                        "forecast_days": args.forecast_days,
                        "raw": forecast.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} airquality evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "weatherhistory":
        if not args.question_id:
            raise SystemExit("forecast import weatherhistory requires --question")
        observations = load_openmeteo_historical_weather(
            args.source,
            limit=args.limit,
            since=args.since,
            start_date=args.start_date,
            end_date=args.end_date,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for observation in observations:
            summary = (
                f"Open-Meteo historical weather for {observation.latitude:g},{observation.longitude:g} "
                f"on {observation.observation_date}: mean {observation.temperature_2m_mean}, "
                f"max {observation.temperature_2m_max}, min {observation.temperature_2m_min}, "
                f"precipitation {observation.precipitation_sum}, wind max {observation.wind_speed_10m_max}."
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=(
                        f"OpenMeteoHistory:{observation.latitude:g},{observation.longitude:g}:"
                        f"{observation.observation_date}"
                    ),
                    source_name=observation.source_name,
                    source_type="adapter:weatherhistory",
                    available_at=args.as_of,
                    claim=(
                        f"Open-Meteo historical weather {observation.observation_date}: "
                        f"mean {observation.temperature_2m_mean}, precip {observation.precipitation_sum}"
                    ),
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "weatherhistory",
                        "latitude": observation.latitude,
                        "longitude": observation.longitude,
                        "observation_date": observation.observation_date,
                        "temperature_2m_mean": observation.temperature_2m_mean,
                        "temperature_2m_max": observation.temperature_2m_max,
                        "temperature_2m_min": observation.temperature_2m_min,
                        "precipitation_sum": observation.precipitation_sum,
                        "wind_speed_10m_max": observation.wind_speed_10m_max,
                        "api_base_url": args.api_base_url,
                        "start_date": args.start_date,
                        "end_date": args.end_date,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} weatherhistory evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "owid":
        if not args.question_id:
            raise SystemExit("forecast import owid requires --question")
        observations = load_owid_observations(
            args.source,
            limit=args.limit,
            since=args.since,
            entity=args.entity,
            value_column=args.value_column,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for observation in observations:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=observation.source_url or f"OWID:{observation.slug}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:owid",
                    published_at=observation.published_at,
                    available_at=observation.published_at or args.as_of,
                    claim=(
                        f"OWID {observation.slug} {observation.entity or observation.code or 'row'} "
                        f"{observation.observation_date}: {observation.value}"
                    ),
                    summary=(
                        f"Our World in Data observation for {observation.value_column} "
                        f"on {observation.observation_date}: {observation.value}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "owid",
                        "slug": observation.slug,
                        "entity": observation.entity,
                        "code": observation.code,
                        "observation_date": observation.observation_date,
                        "value": observation.value,
                        "value_column": observation.value_column,
                        "api_base_url": args.api_base_url,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} owid evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "whogho":
        if not args.question_id:
            raise SystemExit("forecast import whogho requires --question")
        observations = load_who_gho_observations(
            args.source,
            limit=args.limit,
            since=args.since,
            country=args.country,
            dimensions=args.dimension,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for observation in observations:
            geography = f" {observation.spatial_dim}" if observation.spatial_dim else ""
            time_label = f" {observation.time_dim}" if observation.time_dim else ""
            interval = ""
            if observation.low is not None or observation.high is not None:
                interval = f" (low {observation.low}, high {observation.high})"
            summary = (
                f"WHO GHO observation for {observation.indicator}{geography}{time_label}: "
                f"{observation.value}{interval}."
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=observation.source_url or f"WHOGHO:{observation.indicator}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:whogho",
                    published_at=observation.published_at,
                    available_at=observation.published_at or args.as_of,
                    claim=(
                        f"WHO GHO {observation.indicator}{geography}{time_label}: "
                        f"{observation.value}"
                    ),
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "whogho",
                        "indicator": observation.indicator,
                        "spatial_dim": observation.spatial_dim,
                        "time_dim": observation.time_dim,
                        "dim1": observation.dim1,
                        "dim2": observation.dim2,
                        "dim3": observation.dim3,
                        "value": observation.value,
                        "numeric_value": observation.numeric_value,
                        "low": observation.low,
                        "high": observation.high,
                        "country_filter": args.country,
                        "dimension_filters": args.dimension,
                        "api_base_url": args.api_base_url,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} whogho evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "fema":
        if not args.question_id:
            raise SystemExit("forecast import fema requires --question")
        declarations = load_fema_disaster_declarations(
            args.source,
            limit=args.limit,
            since=args.since,
            state=args.state,
            incident_type=args.incident_type,
            declaration_type=args.declaration_type,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for declaration in declarations:
            geography = f" {declaration.state}" if declaration.state else ""
            area = f" {declaration.designated_area}" if declaration.designated_area else ""
            number = f" {declaration.disaster_number}" if declaration.disaster_number is not None else ""
            summary = (
                f"FEMA disaster declaration{number}{geography}{area}: "
                f"{declaration.incident_type or declaration.title}"
            )
            if declaration.declaration_date:
                summary = f"{summary}, declared {declaration.declaration_date}."
            else:
                summary = f"{summary}."
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=declaration.source_url or f"FEMA:{declaration.entry_id}",
                    source_url=declaration.source_url,
                    source_name=declaration.source_name,
                    source_type="adapter:fema",
                    published_at=declaration.declaration_date,
                    available_at=declaration.declaration_date or declaration.last_refresh or args.as_of,
                    claim=(
                        f"FEMA{number}{geography}{area}: "
                        f"{declaration.incident_type or declaration.title}"
                    ),
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "fema",
                        "disaster_number": declaration.disaster_number,
                        "declaration_string": declaration.declaration_string,
                        "state": declaration.state,
                        "declaration_type": declaration.declaration_type,
                        "declaration_date": declaration.declaration_date,
                        "fiscal_year": declaration.fiscal_year,
                        "incident_type": declaration.incident_type,
                        "title": declaration.title,
                        "designated_area": declaration.designated_area,
                        "incident_begin_date": declaration.incident_begin_date,
                        "incident_end_date": declaration.incident_end_date,
                        "individual_assistance": declaration.individual_assistance,
                        "public_assistance": declaration.public_assistance,
                        "hazard_mitigation": declaration.hazard_mitigation,
                        "last_refresh": declaration.last_refresh,
                        "state_filter": args.state,
                        "incident_type_filter": args.incident_type,
                        "declaration_type_filter": args.declaration_type,
                        "api_base_url": args.api_base_url,
                        "raw": declaration.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} fema evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "fred":
        if not args.question_id:
            raise SystemExit("forecast import fred requires --question")
        observations = load_fred_observations(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for observation in observations:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=observation.source_url or f"FRED:{observation.series_id}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:fred",
                    published_at=observation.published_at,
                    available_at=observation.published_at or args.as_of,
                    claim=f"{observation.series_id} {observation.observation_date}: {observation.value}",
                    summary=(
                        f"FRED observation for {observation.series_id} "
                        f"on {observation.observation_date}: {observation.value}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "fred",
                        "series_id": observation.series_id,
                        "observation_date": observation.observation_date,
                        "value": observation.value,
                        "api_base_url": args.api_base_url,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} fred evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "eia":
        if not args.question_id:
            raise SystemExit("forecast import eia requires --question")
        observations = load_eia_observations(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for observation in observations:
            unit_suffix = f" {observation.unit}" if observation.unit else ""
            series_label = observation.series_name or observation.series_id
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=observation.source_url or f"EIA:{observation.series_id}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:eia",
                    published_at=observation.published_at,
                    available_at=observation.published_at or args.as_of,
                    claim=(
                        f"{observation.series_id} {observation.observation_period}: "
                        f"{observation.value}{unit_suffix}"
                    ),
                    summary=(
                        f"EIA observation for {series_label} "
                        f"period {observation.observation_period}: {observation.value}{unit_suffix}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "eia",
                        "series_id": observation.series_id,
                        "series_name": observation.series_name,
                        "observation_period": observation.observation_period,
                        "value": observation.value,
                        "unit": observation.unit,
                        "api_base_url": args.api_base_url,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} eia evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "treasury":
        if not args.question_id:
            raise SystemExit("forecast import treasury requires --question")
        records = load_treasury_records(
            args.source,
            limit=args.limit,
            since=args.since,
            date_field=args.date_field,
            value_field=args.value_field,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for record in records:
            value_part = (
                f"{record.value_field}={record.value}"
                if record.value_field
                else str(record.value)
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=record.source_url or f"Treasury:{record.dataset}",
                    source_url=record.source_url,
                    source_name=record.source_name,
                    source_type="adapter:treasury",
                    published_at=record.published_at,
                    available_at=record.published_at or args.as_of,
                    claim=f"{record.dataset} {record.record_date}: {value_part}",
                    summary=(
                        f"Treasury Fiscal Data record for {record.dataset} "
                        f"on {record.record_date}: {value_part}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "treasury",
                        "dataset": record.dataset,
                        "record_date": record.record_date,
                        "value": record.value,
                        "value_field": record.value_field,
                        "value_label": record.value_label,
                        "api_base_url": args.api_base_url,
                        "raw": record.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} treasury evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "bls":
        if not args.question_id:
            raise SystemExit("forecast import bls requires --question")
        observations = load_bls_observations(
            args.source,
            limit=args.limit,
            since=args.since,
            start_year=args.start_year,
            end_year=args.end_year,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for observation in observations:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=observation.source_url or f"BLS:{observation.series_id}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:bls",
                    published_at=observation.published_at,
                    available_at=observation.published_at or args.as_of,
                    claim=f"{observation.series_id} {observation.observation_date}: {observation.value}",
                    summary=(
                        f"BLS observation for {observation.series_id} "
                        f"period {observation.period} on {observation.observation_date}: {observation.value}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "bls",
                        "series_id": observation.series_id,
                        "observation_date": observation.observation_date,
                        "period": observation.period,
                        "period_name": observation.period_name,
                        "value": observation.value,
                        "api_base_url": args.api_base_url,
                        "start_year": args.start_year,
                        "end_year": args.end_year,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} bls evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "worldbank":
        if not args.question_id:
            raise SystemExit("forecast import worldbank requires --question")
        observations = load_worldbank_observations(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for observation in observations:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=observation.source_url or f"WorldBank:{observation.country}/{observation.indicator}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:worldbank",
                    published_at=observation.published_at,
                    available_at=observation.published_at or args.as_of,
                    claim=(
                        f"{observation.country}/{observation.indicator} "
                        f"{observation.observation_date}: {observation.value}"
                    ),
                    summary=(
                        f"World Bank observation for {observation.country_name or observation.country} "
                        f"{observation.indicator_name or observation.indicator} "
                        f"on {observation.observation_date}: {observation.value}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "worldbank",
                        "country": observation.country,
                        "country_name": observation.country_name,
                        "indicator": observation.indicator,
                        "indicator_name": observation.indicator_name,
                        "observation_date": observation.observation_date,
                        "value": observation.value,
                        "api_base_url": args.api_base_url,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} worldbank evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "census":
        if not args.question_id:
            raise SystemExit("forecast import census requires --question")
        records = load_census_records(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for record in records:
            geography = ", ".join(f"{key}={value}" for key, value in record.geography.items()) or "all geographies"
            values = ", ".join(f"{key}={value}" for key, value in record.values.items())
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=record.source_url or f"Census:{record.dataset}",
                    source_url=record.source_url,
                    source_name=record.source_name,
                    source_type="adapter:census",
                    published_at=record.published_at,
                    available_at=record.published_at or args.as_of,
                    claim=f"Census {record.dataset} {geography}: {values}",
                    summary=(
                        f"U.S. Census Bureau record for {record.dataset} "
                        f"on {record.observation_date or 'unknown date'} "
                        f"({geography}): {values}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "census",
                        "dataset": record.dataset,
                        "dataset_year": record.dataset_year,
                        "observation_date": record.observation_date,
                        "values": record.values,
                        "geography": record.geography,
                        "api_base_url": args.api_base_url,
                        "raw": record.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} census evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "socrata":
        if not args.question_id:
            raise SystemExit("forecast import socrata requires --question")
        records = load_socrata_records(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for record in records:
            value_text = json.dumps(record.values, sort_keys=True)
            if len(value_text) > 400:
                value_text = value_text[:397] + "..."
            summary = (
                f"Socrata record from {record.domain}/{record.dataset_id} "
                f"at {record.observation_time or record.updated_at or 'unknown time'}: {value_text}."
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=record.source_url or f"Socrata:{record.domain}/{record.dataset_id}",
                    source_url=record.source_url,
                    source_name=record.source_name,
                    source_type="adapter:socrata",
                    published_at=record.updated_at or record.observation_time,
                    available_at=record.updated_at or record.observation_time or args.as_of,
                    claim=f"Socrata row: {record.domain}/{record.dataset_id} {record.row_id or record.entry_id}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "socrata",
                        "domain": record.domain,
                        "dataset_id": record.dataset_id,
                        "row_id": record.row_id,
                        "observation_time": record.observation_time,
                        "updated_at": record.updated_at,
                        "api_base_url": args.api_base_url,
                        "values": record.values,
                        "raw": record.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} socrata evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "stooq":
        if not args.question_id:
            raise SystemExit("forecast import stooq requires --question")
        observations = load_stooq_prices(
            args.source,
            limit=args.limit,
            since=args.since,
            interval=args.interval,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for observation in observations:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=observation.source_url or f"Stooq:{observation.symbol}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:stooq",
                    published_at=observation.published_at,
                    available_at=observation.published_at or args.as_of,
                    claim=(
                        f"Stooq {observation.symbol} close {observation.close_price} "
                        f"on {observation.observation_date}"
                    ),
                    summary=(
                        f"Stooq market price observation for {observation.symbol} "
                        f"on {observation.observation_date}: close {observation.close_price}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "stooq",
                        "symbol": observation.symbol,
                        "interval": observation.interval,
                        "observation_date": observation.observation_date,
                        "open_price": observation.open_price,
                        "high_price": observation.high_price,
                        "low_price": observation.low_price,
                        "close_price": observation.close_price,
                        "volume": observation.volume,
                        "api_base_url": args.api_base_url,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} stooq evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "yahoo":
        if not args.question_id:
            raise SystemExit("forecast import yahoo requires --question")
        observations = load_yahoo_finance_prices(
            args.source,
            limit=args.limit,
            since=args.since,
            range_value=args.range_value,
            interval=args.interval,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for observation in observations:
            currency_suffix = f" {observation.currency}" if observation.currency else ""
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=observation.source_url or f"YahooFinance:{observation.symbol}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:yahoo",
                    published_at=observation.published_at,
                    available_at=observation.published_at or args.as_of,
                    claim=(
                        f"Yahoo Finance {observation.symbol} close {observation.close_price}"
                        f"{currency_suffix} at {observation.observation_time}"
                    ),
                    summary=(
                        f"Yahoo Finance chart observation for {observation.symbol} "
                        f"at {observation.observation_time}: close {observation.close_price}{currency_suffix}; "
                        f"open {observation.open_price}, high {observation.high_price}, "
                        f"low {observation.low_price}, volume {observation.volume}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "yahoo",
                        "symbol": observation.symbol,
                        "interval": observation.interval,
                        "observation_time": observation.observation_time,
                        "open_price": observation.open_price,
                        "high_price": observation.high_price,
                        "low_price": observation.low_price,
                        "close_price": observation.close_price,
                        "volume": observation.volume,
                        "currency": observation.currency,
                        "exchange_name": observation.exchange_name,
                        "api_base_url": args.api_base_url,
                        "range": args.range_value,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} yahoo evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "coingecko":
        if not args.question_id:
            raise SystemExit("forecast import coingecko requires --question")
        snapshots = load_coingecko_market_snapshots(
            args.source,
            limit=args.limit,
            since=args.since,
            vs_currency=args.vs_currency,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for snapshot in snapshots:
            currency = snapshot.vs_currency.upper()
            name = snapshot.name or snapshot.coin_id
            change = (
                f"; 24h change {snapshot.price_change_percentage_24h}%"
                if snapshot.price_change_percentage_24h is not None
                else ""
            )
            rank = f"; market cap rank {snapshot.market_cap_rank}" if snapshot.market_cap_rank is not None else ""
            summary = (
                f"CoinGecko market snapshot for {name} ({snapshot.symbol or snapshot.coin_id}) "
                f"last updated {snapshot.last_updated or 'unknown'}: price {snapshot.current_price} {currency}; "
                f"market cap {snapshot.market_cap}; volume {snapshot.total_volume}{change}{rank}."
            )
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=snapshot.source_url or f"CoinGecko:{snapshot.coin_id}",
                    source_url=snapshot.source_url,
                    source_name=snapshot.source_name,
                    source_type="adapter:coingecko",
                    published_at=snapshot.last_updated,
                    available_at=snapshot.last_updated or args.as_of,
                    claim=f"CoinGecko {snapshot.coin_id} price: {snapshot.current_price} {currency}",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "coingecko",
                        "coin_id": snapshot.coin_id,
                        "symbol": snapshot.symbol,
                        "name": snapshot.name,
                        "vs_currency": snapshot.vs_currency,
                        "current_price": snapshot.current_price,
                        "market_cap": snapshot.market_cap,
                        "market_cap_rank": snapshot.market_cap_rank,
                        "total_volume": snapshot.total_volume,
                        "price_change_percentage_24h": snapshot.price_change_percentage_24h,
                        "last_updated": snapshot.last_updated,
                        "api_base_url": args.api_base_url,
                        "raw": snapshot.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} coingecko evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "sec":
        if not args.question_id:
            raise SystemExit("forecast import sec requires --question")
        filings = load_sec_filings(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for filing in filings:
            company = filing.company_name or filing.ticker or filing.cik
            description = filing.description or filing.form
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=filing.source_url or f"SEC:{filing.cik}:{filing.accession_number}",
                    source_url=filing.source_url,
                    source_name=filing.source_name,
                    source_type="adapter:sec",
                    published_at=filing.published_at,
                    available_at=filing.published_at or args.as_of,
                    claim=f"{company} filed {filing.form} on {filing.filing_date}",
                    summary=(
                        f"SEC EDGAR filing for {company}: {filing.form} "
                        f"({description}), filed {filing.filing_date}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "sec",
                        "cik": filing.cik,
                        "company_name": filing.company_name,
                        "ticker": filing.ticker,
                        "form": filing.form,
                        "filing_date": filing.filing_date,
                        "report_date": filing.report_date,
                        "acceptance_time": filing.acceptance_time,
                        "accession_number": filing.accession_number,
                        "primary_document": filing.primary_document,
                        "description": filing.description,
                        "api_base_url": args.api_base_url,
                        "raw": filing.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} sec evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "secfacts":
        if not args.question_id:
            raise SystemExit("forecast import secfacts requires --question")
        facts = load_sec_company_facts(
            args.source,
            concept=args.concept,
            taxonomy=args.taxonomy,
            unit=args.unit,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for fact in facts:
            company = fact.company_name or fact.cik
            label = fact.label or fact.concept
            filed = f", filed {fact.filed_at}" if fact.filed_at else ""
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=fact.source_url or f"SECFACTS:{fact.cik}:{fact.taxonomy}:{fact.concept}",
                    source_url=fact.source_url,
                    source_name=fact.source_name,
                    source_type="adapter:secfacts",
                    published_at=fact.published_at,
                    available_at=fact.published_at or args.as_of,
                    claim=(
                        f"{company} reported {label} of {fact.value} {fact.unit} "
                        f"for period ending {fact.observation_date}"
                    ),
                    summary=(
                        f"SEC Company Facts for {company}: {fact.taxonomy}:{fact.concept} "
                        f"was {fact.value} {fact.unit} for period ending {fact.observation_date}{filed}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "secfacts",
                        "cik": fact.cik,
                        "company_name": fact.company_name,
                        "taxonomy": fact.taxonomy,
                        "concept": fact.concept,
                        "label": fact.label,
                        "description": fact.description,
                        "unit": fact.unit,
                        "observation_date": fact.observation_date,
                        "value": fact.value,
                        "filed_at": fact.filed_at,
                        "form": fact.form,
                        "fiscal_year": fact.fiscal_year,
                        "fiscal_period": fact.fiscal_period,
                        "accession_number": fact.accession_number,
                        "frame": fact.frame,
                        "api_base_url": args.api_base_url,
                        "raw": fact.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} secfacts evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "arxiv":
        if not args.question_id:
            raise SystemExit("forecast import arxiv requires --question")
        papers = load_arxiv_papers(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for paper in papers:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=paper.url or paper.entry_id or paper.title,
                    source_url=paper.url,
                    source_name=paper.source_name,
                    source_type="adapter:arxiv",
                    published_at=paper.published_at,
                    available_at=paper.published_at or paper.updated_at or args.as_of,
                    claim=f"arXiv paper: {paper.title}",
                    summary=paper.abstract,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "arxiv",
                        "arxiv_query": args.source,
                        "arxiv_id": paper.arxiv_id,
                        "pdf_url": paper.pdf_url,
                        "updated_at": paper.updated_at,
                        "authors": paper.authors,
                        "categories": paper.categories,
                        "api_base_url": args.api_base_url,
                        "raw": paper.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} arxiv evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "openalex":
        if not args.question_id:
            raise SystemExit("forecast import openalex requires --question")
        works = load_openalex_works(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for work in works:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=work.url or work.entry_id or work.title,
                    source_url=work.url,
                    source_name=work.source_name,
                    source_type="adapter:openalex",
                    published_at=work.published_at,
                    available_at=work.published_at or work.updated_at or args.as_of,
                    claim=f"OpenAlex work: {work.title}",
                    summary=work.abstract,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "openalex",
                        "openalex_query": args.source,
                        "openalex_work_id": work.work_id,
                        "doi": work.doi,
                        "updated_at": work.updated_at,
                        "authors": work.authors,
                        "concepts": work.concepts,
                        "api_base_url": args.api_base_url,
                        "raw": work.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} openalex evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "crossref":
        if not args.question_id:
            raise SystemExit("forecast import crossref requires --question")
        works = load_crossref_works(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for work in works:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=work.url or work.doi or work.title,
                    source_url=work.url,
                    source_name=work.source_name,
                    source_type="adapter:crossref",
                    published_at=work.published_at,
                    available_at=work.published_at or work.updated_at or args.as_of,
                    claim=f"Crossref work: {work.title}",
                    summary=work.abstract,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "crossref",
                        "crossref_query": args.source,
                        "doi": work.doi,
                        "updated_at": work.updated_at,
                        "authors": work.authors,
                        "subjects": work.subjects,
                        "container_title": work.container_title,
                        "publisher": work.publisher,
                        "work_type": work.work_type,
                        "reference_count": work.reference_count,
                        "cited_by_count": work.cited_by_count,
                        "api_base_url": args.api_base_url,
                        "raw": work.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} crossref evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "wikipedia":
        if not args.question_id:
            raise SystemExit("forecast import wikipedia requires --question")
        pages = load_wikipedia_pages(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for page in pages:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=page.url or page.entry_id or page.title,
                    source_url=page.url,
                    source_name=page.source_name,
                    source_type="adapter:wikipedia",
                    published_at=page.updated_at,
                    available_at=page.updated_at or args.as_of,
                    claim=f"Wikipedia page: {page.title}",
                    summary=page.extract,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "wikipedia",
                        "wikipedia_query": args.source,
                        "page_id": page.page_id,
                        "updated_at": page.updated_at,
                        "api_base_url": args.api_base_url,
                        "raw": page.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} wikipedia evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "wikipediapageviews":
        if not args.question_id:
            raise SystemExit("forecast import wikipediapageviews requires --question")
        observations = load_wikimedia_pageviews(
            args.source,
            limit=args.limit,
            since=args.since,
            access=args.access,
            agent=args.agent,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for observation in observations:
            page = f"{observation.project}/{observation.article}"
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=observation.source_url or f"WikimediaPageviews:{page}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:wikipediapageviews",
                    published_at=observation.published_at,
                    available_at=observation.published_at or args.as_of,
                    claim=f"Wikimedia pageviews {page} {observation.observation_date}: {observation.views}",
                    summary=(
                        f"Wikimedia recorded {observation.views} {observation.access}/{observation.agent} "
                        f"{observation.granularity} pageviews for {observation.article} "
                        f"on {observation.observation_date}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "wikipediapageviews",
                        "project": observation.project,
                        "article": observation.article,
                        "access": observation.access,
                        "agent": observation.agent,
                        "granularity": observation.granularity,
                        "observation_date": observation.observation_date,
                        "views": observation.views,
                        "api_base_url": args.api_base_url,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} wikipediapageviews evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "data":
        if not args.question_id:
            raise SystemExit("forecast import data requires --question")
        rows = _load_data_evidence_rows(args.source, limit=args.limit, since=args.since)
        evidence_items = []
        for row in rows:
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=row["source_or_note"],
                    source_url=row.get("source_url"),
                    source_name=row.get("source_name") or "data",
                    source_type="adapter:data",
                    published_at=row.get("published_at"),
                    available_at=row.get("available_at") or args.as_of,
                    claim=row["claim"],
                    summary=row.get("summary") or "",
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance=row.get("stance") or "context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "data",
                        "data_source": args.source,
                        **dict(row.get("metadata") or {}),
                    },
                )
            )
        print(f"captured {len(evidence_items)} data evidence item(s)")
        for evidence in evidence_items:
            print(f"{evidence.id}: {evidence.available_at} {evidence.claim}")
        return
    if args.import_kind == "market" and args.question_id and args.baseline_probability is None:
        baselines = _load_market_baselines(args.source)
        if baselines:
            captured = []
            for baseline in baselines:
                captured.append(
                    ledger.add_baseline_comparison(
                        question_id=args.question_id,
                        source=str(baseline.get("source") or "market"),
                        baseline_type=str(baseline.get("baseline_type") or "market"),
                        probability_or_distribution=baseline.get("distribution", baseline.get("probability")),
                        as_of=baseline.get("as_of") or args.as_of,
                        metadata={
                            "adapter": "market",
                            "source": args.source,
                            **dict(baseline.get("metadata") or {}),
                        },
                    )
                )
            print(f"captured {len(captured)} market baseline comparison(s)")
            for baseline in captured:
                print(
                    f"{baseline['id']}: {baseline['baseline_type']}:{baseline['source']} "
                    f"{_format_probability(baseline['probability_or_distribution'])}"
                )
            return
    if not args.question_id:
        metadata: dict[str, Any] = {"adapter": args.import_kind, "source": args.source}
        if args.baseline_probability is not None:
            metadata["baseline"] = {
                "source": args.import_kind,
                "baseline_type": args.baseline_type,
                "probability_or_distribution": args.baseline_probability,
                "as_of": args.as_of,
            }
        candidate = ledger.create_ingest_candidate(
            source=args.source,
            title=args.title,
            resolution_criteria=args.resolution_criteria or "",
            close_time=args.close_time,
            resolution_time=args.resolution_time,
            metadata=metadata,
        )
        print(f"created {args.import_kind} import candidate {candidate['id']}")
        print("confirmation required before creating an active forecast")
        if args.baseline_probability is not None:
            print("baseline stored with candidate metadata")
        return
    item = ledger.add_evidence(
        question_id=args.question_id,
        source_or_note=args.source,
        claim=f"Imported context from {args.import_kind}",
        source_type=f"adapter:{args.import_kind}",
        available_at=args.as_of,
        metadata={"adapter": args.import_kind},
    )
    print(f"captured adapter evidence {item.id}")
    if args.baseline_probability is not None:
        baseline = ledger.add_baseline_comparison(
            question_id=args.question_id,
            source=args.import_kind,
            baseline_type=args.baseline_type,
            probability_or_distribution=args.baseline_probability,
            as_of=args.as_of,
            metadata={"source": args.source},
        )
        print(f"captured baseline comparison {baseline['id']}")


def _cmd_plugins(args: argparse.Namespace) -> None:
    extensions = extension_registry.list(kind=args.kind)
    if not extensions:
        print("No forecast extensions found.")
        return
    print("Kind       Name                 Version  Description")
    for extension in extensions:
        print(
            f"{extension.kind:<10} {extension.name:<20} "
            f"{extension.version or '-':<8} {extension.description}"
        )


def _cmd_sources(args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps({"sources": SOURCE_ADAPTER_GUIDES}, indent=2, sort_keys=True))
        return
    print("Name              Domain                         Import command")
    for source in SOURCE_ADAPTER_GUIDES:
        print(f"{source['name']:<17} {source['domain']:<30} {source['import_command']}")
    print("")
    print("Watch prefixes")
    for source in SOURCE_ADAPTER_GUIDES:
        print(f"{source['name']:<17} {source['watch_prefix']}")


def _cmd_research(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    current = ledger.get_current_snapshot(args.id)
    if not args.sources:
        evidence = ledger.list_evidence(args.id)
        print(f"evidence_count: {len(evidence)}")
        print(f"new_since_current_forecast: {_new_evidence_count(evidence, current)}")
        for item in evidence[-5:]:
            source = item.source_url or item.source_name or item.claim or item.summary
            print(f"{item.id} {item.available_at} {item.stance} {item.claim_type} {source}")
        print("probability unchanged")
        return
    created = []
    for source in args.sources:
        created.append(
            ledger.add_evidence(
                question_id=args.id,
                source_or_note=source,
                claim=args.claim,
                claim_type=args.claim_type,
                summary=args.summary,
                available_at=args.available_at,
                published_at=args.published_at,
                source_name=args.source_name,
                source_type=args.source_type,
                reliability_rating=args.reliability,
                relevance_rating=args.relevance,
                stance=args.stance,
            )
        )
    print(f"captured {len(created)} evidence item(s)")
    print(f"new_since_current_forecast: {_new_evidence_count(created, current)}")
    for item in created:
        print(
            f"{item.id} available_at={item.available_at} stance={item.stance} "
            f"claim_type={item.claim_type} reliability={_format_optional_float(item.reliability_rating)} "
            f"relevance={_format_optional_float(item.relevance_rating)}"
        )
    print("probability unchanged")


def _cmd_base_rate(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    ref = ledger.add_reference_class(
        question_id=args.id,
        name=args.name,
        inclusion_criteria=args.inclusion_criteria,
        exclusion_criteria=args.exclusion_criteria,
        base_rate=args.base_rate,
        base_rate_uncertainty=args.uncertainty,
        source_refs=args.source_refs,
        check_cadence=args.check_cadence,
        notes=args.notes,
    )
    model_run = ledger.record_model_run(
        question_id=args.id,
        model_type="base_rate",
        inputs={
            "reference_class_id": ref["id"],
            "inclusion_criteria": args.inclusion_criteria,
            "exclusion_criteria": args.exclusion_criteria,
        },
        output={"base_rate": args.base_rate, "uncertainty": args.uncertainty},
        diagnostics={"source_refs": args.source_refs},
    )
    print(f"reference_class: {ref['id']}")
    print(f"base_rate: {ref['base_rate']}")
    print(f"model_run: {model_run['id']}")


def _cmd_model(args: argparse.Namespace) -> None:
    inputs = _json_arg(args.input_json, "input-json")
    parameters = _json_arg(args.parameters_json, "parameters-json")
    output = _json_arg(args.output_json, "output-json")
    if args.model_type == "bayesian_update":
        supplied = [args.prior, args.likelihood_if_true, args.likelihood_if_false]
        if any(value is not None for value in supplied):
            if any(value is None for value in supplied):
                raise SystemExit(
                    "bayesian_update requires --prior, --likelihood-if-true, and --likelihood-if-false"
                )
            posterior = bayesian_binary_update(
                prior=args.prior,
                likelihood_if_true=args.likelihood_if_true,
                likelihood_if_false=args.likelihood_if_false,
            )
            inputs.setdefault("prior", args.prior)
            parameters.setdefault("likelihood_if_true", args.likelihood_if_true)
            parameters.setdefault("likelihood_if_false", args.likelihood_if_false)
            output.setdefault("posterior", posterior)
    elif args.model_type == "trend_projection" and args.series_json:
        series = _json_value_arg(args.series_json, "series-json")
        if not isinstance(series, list):
            raise SystemExit("trend_projection --series-json must be a JSON array")
        projection = linear_trend_projection(
            series,
            target_date=args.target_date,
            target_x=args.target_x,
            date_field=args.date_field,
            value_field=args.value_field,
        )
        inputs.setdefault("series", series)
        parameters.setdefault("target_date", args.target_date)
        parameters.setdefault("target_x", args.target_x)
        parameters.setdefault("date_field", args.date_field)
        parameters.setdefault("value_field", args.value_field)
        output.update({key: value for key, value in projection.items() if key not in output})
    model_run = _ledger(args).record_model_run(
        question_id=args.id,
        model_type=args.model_type,
        status=args.status,
        inputs=inputs,
        parameters=parameters,
        output=output,
        diagnostics=_json_arg(args.diagnostics_json, "diagnostics-json"),
        code_ref=args.code_ref,
        artifact_paths=args.artifact_paths,
        model_version=args.model_version,
        prompt_version=args.prompt_version,
        data_version=args.data_version,
        evidence_cutoff=args.evidence_cutoff,
    )
    print(f"model_run: {model_run['id']}")
    print(f"type: {model_run['model_type']}")
    print(f"status: {model_run['status']}")
    print(f"evidence_cutoff: {model_run['evidence_cutoff'] or '-'}")
    if args.model_type == "bayesian_update" and "posterior" in model_run["output"]:
        print(f"posterior: {model_run['output']['posterior']:.3f}")
    if args.model_type == "trend_projection" and "projected_value" in model_run["output"]:
        print(f"projected_value: {model_run['output']['projected_value']:.3f}")
        print(f"slope: {model_run['output']['slope']:.6f} {model_run['output'].get('slope_unit', '')}".rstrip())
        print(f"r_squared: {model_run['output']['r_squared']:.3f}")


def _cmd_protocol(args: argparse.Namespace) -> None:
    messages = build_protocol_messages(_ledger(args), args.id, stage=args.stage)
    if args.json:
        print(json.dumps([message.__dict__ for message in messages], indent=2))
        return
    for message in messages:
        print(f"## {message.role}")
        print(message.content)
        print()


def _cmd_agent(args: argparse.Namespace) -> None:
    messages = build_protocol_messages(_ledger(args), args.id, stage=args.stage)
    enabled_toolsets = _toolsets_for_stage(args.stage)
    if args.dry_run:
        print(f"enabled_toolsets: {', '.join(enabled_toolsets)}")
        print()
        for message in messages:
            print(f"## {message.role}")
            print(message.content)
            print()
        return
    from run_agent import AIAgent

    agent = AIAgent(
        model=args.model or "",
        provider=args.provider,
        max_iterations=args.max_iterations,
        enabled_toolsets=enabled_toolsets,
        platform="cli",
    )
    result = agent.run_conversation(
        messages[1].content,
        system_message=messages[0].content,
    )
    print(result.get("final_response") or result)


def _cmd_assumption_add(args: argparse.Namespace) -> None:
    assumption = _ledger(args).add_assumption(
        question_id=args.id,
        text=args.text,
        status=args.status,
        check_cadence=args.check_cadence,
        evidence_refs=args.evidence_refs,
        notes=args.notes,
    )
    print(f"assumption: {assumption['id']}")
    print(f"status: {assumption['status']}")
    print(f"check_cadence: {assumption['check_cadence'] or '-'}")


def _cmd_assumption_list(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_assumptions(args.id)
    if not rows:
        print("No assumptions found.")
        return
    print("ID             Status       Check cadence  Text")
    for row in rows:
        print(f"{row['id']:<14} {row['status']:<12} {row['check_cadence'] or '-':<14} {row['text']}")


def _cmd_assumption_status(args: argparse.Namespace) -> None:
    assumption = _ledger(args).update_assumption(
        args.assumption_id,
        status=args.status,
        last_checked_at=args.last_checked_at,
        invalidated_at=args.invalidated_at,
        notes=args.notes,
    )
    print(f"assumption: {assumption['id']}")
    print(f"status: {assumption['status']}")
    print(f"last_checked_at: {assumption['last_checked_at'] or '-'}")
    print(f"invalidated_at: {assumption['invalidated_at'] or '-'}")


def _cmd_reference_class_list(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_reference_classes(args.id)
    if not rows:
        print("No reference classes found.")
        return
    print("ID             Status       Base rate  Name")
    for row in rows:
        base_rate = "-" if row["base_rate"] is None else f"{row['base_rate']:.3f}"
        print(f"{row['id']:<14} {row['status']:<12} {base_rate:<10} {row['name']}")


def _cmd_reference_class_status(args: argparse.Namespace) -> None:
    reference_class = _ledger(args).update_reference_class(
        args.reference_class_id,
        status=args.status,
        last_checked_at=args.last_checked_at,
        invalidated_at=args.invalidated_at,
        check_cadence=args.check_cadence,
        notes=args.notes,
    )
    print(f"reference_class: {reference_class['id']}")
    print(f"status: {reference_class['status']}")
    print(f"last_checked_at: {reference_class['last_checked_at'] or '-'}")
    print(f"invalidated_at: {reference_class['invalidated_at'] or '-'}")
    print(f"check_cadence: {reference_class['check_cadence'] or '-'}")


def _cmd_evidence_add(args: argparse.Namespace) -> None:
    item = _ledger(args).add_evidence(
        question_id=args.id,
        source_or_note=args.source_or_note,
        claim=args.claim,
        claim_type=args.claim_type,
        summary=args.summary,
        source_url=args.source_url,
        source_name=args.source_name,
        source_type=args.source_type,
        published_at=args.published_at,
        available_at=args.available_at,
        reliability_rating=args.reliability,
        relevance_rating=args.relevance,
        stance=args.stance,
        snapshot_path=args.snapshot_path,
        admissible_for_backtests=not args.not_admissible_for_backtests,
    )
    print(f"added evidence {item.id}")
    print(f"available_at: {item.available_at}")
    print(f"stance: {item.stance}")
    print(f"claim_type: {item.claim_type}")


def _cmd_evidence_list(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_evidence(args.id)
    if not rows:
        print("No evidence found.")
        return
    print("ID             Available at          Stance      Claim type   Rel   Rev   Source/Claim")
    for item in rows:
        source = item.source_url or item.source_name or item.claim or item.summary
        print(
            f"{item.id:<14} {item.available_at:<21} {item.stance:<11} {item.claim_type:<12} "
            f"{_format_optional_float(item.reliability_rating):<5} {_format_optional_float(item.relevance_rating):<5} {source}"
        )


def _cmd_resolve(args: argparse.Namespace) -> None:
    resolution = _ledger(args).resolve_question(
        question_id=args.id,
        outcome=args.outcome,
        resolution_source=args.resolution_source,
        resolution_source_snapshot_ref=args.resolution_source_snapshot_ref,
        resolver_type=args.resolver_type,
        resolution_status=args.resolution_status,
        criteria_satisfied=args.criteria_satisfied,
        confidence=args.confidence,
        confirmed_by=args.confirmed_by,
        resolver_notes=args.resolver_notes,
        correction_ref=args.correction_ref,
        trusted_policy_id=args.trusted_policy,
        scoreable=not args.not_scoreable,
    )
    print(f"recorded resolution {resolution.id}")
    print(f"status: {resolution.resolution_status}")
    print(f"criteria_satisfied: {resolution.criteria_satisfied}")


def _cmd_score(args: argparse.Namespace) -> None:
    score = _ledger(args).score_question(args.id, force=args.force)
    print(f"score: {score.id}")
    print(f"brier_score: {score.brier_score:.6f}" if score.brier_score is not None else "brier_score: -")
    print(f"log_score: {score.log_score:.6f}" if score.log_score is not None else "log_score: -")
    print(f"proper_score: {score.proper_score:.6f}" if score.proper_score is not None else "proper_score: -")
    print(f"score_rule: {score.score_rule or '-'}")
    print(f"bucket: {score.calibration_bucket or '-'}")
    print(f"origin: {score.forecast_origin}")


def _cmd_scores(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_scores(
        domain=args.domain,
        forecast_origin=args.forecast_origin,
        calibration_eligible=None if args.all else True,
        horizon=args.horizon,
        bucket=args.bucket,
        include_invalidated=args.include_invalidated,
    )
    if not rows:
        print("No score records found.")
        return
    print("ID             Brier     Log       Proper    Rule                         Bucket   Horizon  Origin             Domain    Invalidated")
    for score in rows:
        brier = "-" if score.brier_score is None else f"{score.brier_score:.4f}"
        log_score = "-" if score.log_score is None else f"{score.log_score:.4f}"
        proper = "-" if score.proper_score is None else f"{score.proper_score:.4f}"
        horizon = "-" if score.forecast_horizon_days is None else f"{score.forecast_horizon_days:.1f}d"
        print(
            f"{score.id:<14} {brier:<9} {log_score:<9} {proper:<9} {score.score_rule or '-':<28} {score.calibration_bucket or '-':<8} "
            f"{horizon:<8} {score.forecast_origin:<18} {score.domain or '-':<9} "
            f"{score.invalidated_by_correction_id or '-'}"
        )


def _cmd_postmortem(args: argparse.Namespace) -> None:
    postmortem = _ledger(args).create_postmortem(
        question_id=args.id,
        summary=args.summary,
        what_happened=args.what_happened,
        what_was_expected=args.what_was_expected,
        missed_evidence=args.missed_evidence,
        overweighted_evidence=args.overweighted_evidence,
        base_rate_error=args.base_rate_error,
        inside_view_error=args.inside_view_error,
        resolution_error=args.resolution_error,
        lesson=args.lesson,
        calibration_adjustment=_json_arg(args.calibration_adjustment_json, "calibration-adjustment-json"),
    )
    print(f"postmortem: {postmortem['id']}")
    print(f"score_record: {postmortem['score_record_id']}")
    if args.lesson:
        print("calibration_lesson: created")


def _cmd_lesson_list(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_calibration_lessons(
        scope_type=args.scope_type,
        scope_ref=args.scope_ref,
        active_only=args.active,
    )
    if not rows:
        print("No calibration lessons found.")
        return
    print("ID             Status      Scope                  Confidence  Lesson")
    for row in rows:
        scope = f"{row['scope_type']}:{row['scope_ref'] or '*'}"
        confidence = "-" if row["confidence"] is None else f"{row['confidence']:.2f}"
        print(f"{row['id']:<14} {row['status']:<11} {scope:<22} {confidence:<11} {row['lesson']}")


def _cmd_lesson_status(args: argparse.Namespace) -> None:
    adjustment = (
        _json_arg(args.recommended_adjustment_json, "recommended-adjustment-json")
        if args.recommended_adjustment_json is not None
        else None
    )
    row = _ledger(args).update_calibration_lesson(
        args.lesson_id,
        status=args.status,
        confidence=args.confidence,
        recommended_adjustment=adjustment,
        supersedes_lesson_id=args.supersedes,
    )
    print(f"calibration_lesson: {row['id']}")
    print(f"status: {row['status']}")
    print(f"confidence: {row['confidence'] if row['confidence'] is not None else '-'}")


def _cmd_correction_add(args: argparse.Namespace) -> None:
    correction = _ledger(args).create_correction(
        target_type=args.target_type,
        target_id=args.target_id,
        reason=args.reason,
        created_by=args.created_by,
        old_value=_json_value_arg(args.old_json, "old-json"),
        new_value=_json_value_arg(args.new_json, "new-json"),
        patch=_json_arg(args.patch_json, "patch-json"),
        status=args.status,
    )
    print(f"correction: {correction['id']}")
    print(f"target: {correction['target_type']} {correction['target_id']}")
    print(f"affected_scores: {len(correction['affected_score_record_refs'])}")
    print(f"affected_postmortems: {len(correction['affected_postmortem_refs'])}")
    print(f"affected_lessons: {len(correction['affected_calibration_lesson_refs'])}")


def _cmd_correction_list(args: argparse.Namespace) -> None:
    corrections = _ledger(args).list_corrections(
        target_type=args.target_type,
        target_id=args.target_id,
        status=args.status,
    )
    if not corrections:
        print("No correction records found.")
        return
    print("ID             Status    Target                 Affected")
    for correction in corrections:
        affected = (
            len(correction["affected_score_record_refs"])
            + len(correction["affected_postmortem_refs"])
            + len(correction["affected_calibration_lesson_refs"])
        )
        target = f"{correction['target_type']}:{correction['target_id']}"
        print(f"{correction['id']:<14} {correction['status']:<9} {target:<22} {affected}")


def _cmd_resolver_trust(args: argparse.Namespace) -> None:
    policy = _ledger(args).create_trusted_resolver_policy(
        resolver_plugin=args.resolver_plugin,
        plugin_version=args.plugin_version,
        scope_type=args.scope_type,
        scope_ref=args.scope_ref,
        enabled=args.enabled,
        approved_by=args.approved_by,
        audit_log_ref=args.audit_log_ref,
    )
    print(f"trusted_resolver_policy: {policy['id']}")
    print(f"plugin: {policy['resolver_plugin']}")
    print(f"enabled: {policy['enabled']}")


def _cmd_resolver_list(args: argparse.Namespace) -> None:
    policies = _ledger(args).list_trusted_resolver_policies(
        resolver_plugin=args.resolver_plugin,
        scope_type=args.scope_type,
        enabled=True if args.enabled else None,
    )
    if not policies:
        print("No trusted resolver policies found.")
        return
    print("ID              Plugin                 Scope             Enabled")
    for policy in policies:
        scope = f"{policy['scope_type']}:{policy['scope_ref'] or '*'}"
        print(f"{policy['id']:<15} {policy['resolver_plugin']:<22} {scope:<17} {policy['enabled']}")


def _cmd_calibration(args: argparse.Namespace) -> None:
    if args.by_origin and args.forecast_origin:
        raise SystemExit("forecast calibration --by-origin cannot be combined with --origin")
    if args.by_origin:
        for label, origin in (
            ("combined", None),
            ("live", "live"),
            ("backtest", "backtest"),
            ("imported_baseline", "imported_baseline"),
        ):
            summary = _ledger(args).calibration_summary(
                domain=args.domain,
                forecast_origin=origin,
                horizon=args.horizon,
                calibration_eligible=None if args.all else True,
            )
            _print_calibration_summary(summary, label=label)
        return
    summary = _ledger(args).calibration_summary(
        domain=args.domain,
        forecast_origin=args.forecast_origin,
        horizon=args.horizon,
        calibration_eligible=None if args.all else True,
    )
    _print_calibration_summary(summary)


def _print_calibration_summary(summary: dict[str, Any], *, label: str | None = None) -> None:
    if label is not None:
        print(f"origin: {label}")
    print(f"count: {summary['count']}")
    mean = summary["mean_brier"]
    print(f"mean_brier: {mean:.6f}" if mean is not None else "mean_brier: -")
    mean_log = summary["mean_log_score"]
    print(f"mean_log_score: {mean_log:.6f}" if mean_log is not None else "mean_log_score: -")
    sharpness = summary["mean_sharpness"]
    print(f"mean_sharpness: {sharpness:.6f}" if sharpness is not None else "mean_sharpness: -")
    movement = summary.get("mean_probability_movement_before_close")
    abs_movement = summary.get("mean_abs_probability_movement_before_close")
    print(f"probability_movement_n: {summary.get('probability_movement_count', 0)}")
    print(
        f"mean_probability_movement_before_close: {movement:+.6f}"
        if movement is not None
        else "mean_probability_movement_before_close: -"
    )
    print(
        f"mean_abs_probability_movement_before_close: {abs_movement:.6f}"
        if abs_movement is not None
        else "mean_abs_probability_movement_before_close: -"
    )
    components = summary.get("ensemble_component_contributions") or []
    if components:
        print("ensemble_component_contributions:")
        for row in components:
            print(
                f"  {row['name']}: n={row['count']} "
                f"mean_contribution={_format_metric(row.get('mean_contribution'))} "
                f"weight_share={_format_metric(row.get('mean_weight_share'))} "
                f"mean_probability={_format_metric(row.get('mean_probability'))}"
            )
    question_types = summary.get("question_type_breakdown") or []
    if question_types:
        print("question_type_breakdown:")
        for row in question_types:
            print(
                f"  {row['question_type']}: n={row['count']} "
                f"brier_n={row.get('brier_count', 0)} "
                f"mean_brier={_format_metric(row.get('mean_brier'))} "
                f"mean_proper_score={_format_metric(row.get('mean_proper_score'))} "
                f"mean_log_score={_format_metric(row.get('mean_log_score'))}"
            )
    print("buckets:")
    if not summary["buckets"]:
        print("  none")
        return
    for bucket in summary["buckets"]:
        print(
            f"  {bucket['bucket']}: n={bucket['count']} "
            f"mean_brier={_format_metric(bucket['mean_brier'])} {bucket['sample_status']}"
        )
    if label is not None:
        print()


def _cmd_errors(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    profiles = ledger.list_domain_error_profiles(domain=args.domain, topic=args.topic)
    summary = ledger.calibration_summary(domain=args.domain)
    domain_label = args.domain or "all"
    print(f"domain: {domain_label}")
    print(f"scored_forecasts: {summary['count']}")
    if profiles:
        print("profiles:")
        for profile in profiles:
            errors = ",".join(profile["recurring_errors"]) or "none"
            adjustments = " | ".join(profile["recommended_adjustments"]) or "none"
            scope = f"{profile['domain'] or '*'}:{profile['topic'] or '*'}"
            print(
                f"  {profile['id']} scope={scope} n={profile['sample_count']} "
                f"errors={errors} adjustments={adjustments}"
            )
    if summary["mean_brier"] is None:
        print("recurring_errors: insufficient scored forecasts")
    elif summary["mean_brier"] > 0.25:
        print("recurring_errors: elevated average Brier score; inspect postmortems before adjusting priors")
    else:
        print("recurring_errors: no high-level pattern detected from scored forecasts")


def _cmd_review(args: argparse.Namespace) -> None:
    rows = _ledger(args).review_questions(
        stale=args.stale,
        last_days=args.last_days,
        domain=args.domain,
        topic=args.topic,
        horizon=args.horizon,
        confidence_below=args.confidence_below,
        confidence_above=args.confidence_above,
        large_delta_threshold=args.large_delta_threshold,
        now=args.now,
    )
    if not rows:
        print("No forecasts need review.")
        return
    print("ID             P(now)    As of                 Close                Priority  Reasons              Title")
    for row in rows:
        question = row["question"]
        snapshot = row["current_snapshot"]
        probability = _format_probability(snapshot.probability_or_distribution) if snapshot else "-"
        as_of = snapshot.as_of if snapshot else "-"
        close = question.close_time or "-"
        reasons = ",".join(row["reasons"]) or "active"
        print(
            f"{question.id:<14} {probability:<9} {as_of:<20} {close:<20} "
            f"{row.get('priority', 9):<9} {reasons:<20} {question.title}"
        )
        print(f"  next: {_review_next_action(question.id, row['reasons'])}")


def _cmd_schedule_add(args: argparse.Namespace) -> None:
    scope_type, scope_ref = _schedule_scope(args)
    row = _ledger(args).schedule_review(
        scope_type=scope_type,
        scope_ref=scope_ref,
        cadence=args.cadence,
        next_run_at=args.next_run_at,
        trigger_reason=args.trigger_reason,
        enabled=not args.disabled,
        auto_score=args.auto_score,
        auto_postmortem=args.auto_postmortem,
        stale_days=args.stale_days,
        confidence_below=args.confidence_below,
        confidence_above=args.confidence_above,
        large_delta_threshold=args.large_delta_threshold,
    )
    print(f"scheduled review {row['id']}")
    print(f"scope: {row['scope_type']} {row['scope_ref'] or ''}".rstrip())
    print(f"next_run_at: {row['next_run_at']}")


def _cmd_schedule_list(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_scheduled_reviews()
    if not rows:
        print("No scheduled reviews found.")
        return
    print("ID             Scope          Cadence      Stale  Confidence     Delta  Next run             Enabled  Learning")
    for row in rows:
        scope = _format_schedule_scope(row)
        learning = _format_schedule_learning(row)
        confidence = _format_schedule_confidence(row)
        delta = _format_schedule_delta(row)
        print(
            f"{row['id']:<14} {scope:<14} {row['cadence']:<12} {int(row.get('stale_days') or 7):<6} "
            f"{confidence:<14} {delta:<6} {row['next_run_at']:<20} {bool(row['enabled']):<7} {learning}"
        )


def _cmd_schedule_run(args: argparse.Namespace) -> None:
    results = _ledger(args).run_due_scheduled_reviews(
        now=args.now,
        auto_score=args.auto_score,
        auto_postmortem=args.auto_postmortem,
    )
    if not results:
        print("No scheduled reviews due.")
        return
    total_alerts = sum(len(result["alerts"]) for result in results)
    alert_rows = [alert for result in results for alert in result["alerts"]]
    score_events = [alert for alert in alert_rows if alert.reason.startswith("score_created:")]
    postmortem_events = [alert for alert in alert_rows if alert.reason.startswith("postmortem_created:")]
    learning_review_events = [
        alert
        for alert in alert_rows
        if alert.reason in {"calibration_lesson_review", "domain_error_profile_review"}
    ]
    print(f"ran {len(results)} scheduled review(s)")
    print(f"created {total_alerts} alert(s)")
    print(f"scores_created: {len(score_events)}")
    print(f"postmortems_created: {len(postmortem_events)}")
    print(f"learning_reviews: {len(learning_review_events)}")
    for result in results:
        review = result["review"]
        print(f"{review['id']} next_run_at={review['next_run_at']} alerts={len(result['alerts'])}")
        for alert in result["alerts"]:
            print(f"  {alert.id} {alert.scope_type}:{alert.scope_ref} {alert.reason}")


def _cmd_schedule_install_cron(args: argparse.Namespace) -> None:
    from forecasting.scheduler import install_forecast_cron

    job = install_forecast_cron(
        schedule=args.schedule,
        name=args.name,
        deliver=args.deliver,
        profile=args.profile,
        db_path=args.db,
        auto_score=args.auto_score,
        auto_postmortem=args.auto_postmortem,
    )
    print(f"cron_job: {job['id']}")
    print(f"name: {job['name']}")
    print(f"schedule: {job['schedule_display']}")
    print(f"script: {job['script']}")
    print(f"mode: {'no-agent' if job.get('no_agent') else 'agent'}")


def _cmd_watch_add(args: argparse.Namespace) -> None:
    scope_type, scope_ref = _watch_scope(args, required=True)
    row = _ledger(args).add_watched_source(
        scope_type=scope_type,
        scope_ref=scope_ref,
        source=args.source,
        source_type=args.source_type,
        metadata=_json_arg(args.metadata_json, "metadata-json"),
    )
    print(f"watched source {row['id']}")
    print(f"scope: {_format_watch_scope(row)}")
    print(f"source_type: {row['source_type']}")
    print(f"status: {row['status']}")


def _cmd_watch_list(args: argparse.Namespace) -> None:
    scope_type, scope_ref = _watch_scope(args, required=False)
    rows = _ledger(args).list_watched_sources(
        scope_type=scope_type,
        scope_ref=scope_ref,
        status=None if args.all else "active",
    )
    if not rows:
        print("No watched sources found.")
        return
    print("ID             Scope                  Type    Status    Source")
    for row in rows:
        print(
            f"{row['id']:<14} {_format_watch_scope(row):<22} "
            f"{row['source_type']:<7} {row['status']:<9} {row['source']}"
        )


def _cmd_watch_check(args: argparse.Namespace) -> None:
    scope_type, scope_ref = _watch_scope(args, required=False)
    alerts = _ledger(args).check_watched_sources(
        scope_type=scope_type,
        scope_ref=scope_ref,
        now=args.now,
    )
    if not alerts:
        print("No watched source alerts created.")
        return
    print(f"created {len(alerts)} alert(s)")
    for alert in alerts:
        print(f"{alert.id}: {alert.scope_ref} {alert.reason}")


def _cmd_alerts(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    if args.ack_alert_id:
        alert = ledger.acknowledge_alert(args.ack_alert_id)
        print(f"acknowledged alert {alert.id}")
        print(f"acknowledged_at: {alert.acknowledged_at}")
        return
    rows = ledger.list_alerts(unresolved_only=not args.all)
    if not rows:
        print("No alerts found.")
        return
    print("ID             Severity  Scope              Reason")
    for alert in rows:
        scope = f"{alert.scope_type}:{alert.scope_ref}"
        print(f"{alert.id:<14} {alert.severity:<9} {scope:<18} {alert.reason}")


def _cmd_self_check(args: argparse.Namespace) -> None:
    alerts = _ledger(args).self_check(
        question_id=args.question_id,
        domain=args.domain,
        topic=args.topic,
        horizon=args.horizon,
        portfolio=args.portfolio,
        stale_days=args.stale_days,
        now=args.now,
        auto_score=args.auto_score,
        auto_postmortem=args.auto_postmortem,
        confidence_below=args.confidence_below,
        confidence_above=args.confidence_above,
        large_delta_threshold=args.large_delta_threshold,
    )
    if not alerts:
        print("No self-check alerts created.")
        return
    print(f"created {len(alerts)} alert(s)")
    for alert in alerts:
        print(f"{alert.id}: {alert.scope_ref} {alert.reason}")


def _cmd_backtest(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    if args.agent_response_jsonl and args.probability_source != "agent-protocol":
        raise SystemExit("--agent-response-jsonl requires --probability-source agent-protocol")
    if args.agent_output_jsonl and args.probability_source != "agent-protocol":
        raise SystemExit("--agent-output-jsonl requires --probability-source agent-protocol")
    agent_runner = (
        _backtest_agent_protocol_runner(args)
        if args.probability_source == "agent-protocol"
        else None
    )
    if args.benchmarks:
        rows = list_builtin_benchmarks()
        imported = ledger.list_benchmark_datasets()
        if not rows and not imported:
            print("No benchmarks found.")
            return
        print("Name                 Cases  Description")
        for row in rows:
            print(f"builtin:{row['name']:<12} {row['case_count']:<6} {row['description']}")
        for row in imported:
            description = row.get("description") or f"Imported from {row['source']}"
            print(f"imported:{row['id']:<11} {row['case_count']:<6} {description}")
        return
    if args.all_benchmarks:
        if args.dataset:
            raise SystemExit("forecast backtest --all-benchmarks cannot be combined with a dataset")
        rows = list_builtin_benchmarks()
        if not rows:
            print("No built-in benchmarks found.")
            return
        print(f"benchmark_suite: builtin ({len(rows)} datasets)")
        print(f"probability_source: {args.probability_source}")
        for row in rows:
            dataset = f"builtin:{row['name']}"
            cases = _apply_backtest_probability_source(
                _load_backtest_cases(dataset, ledger=ledger),
                args.probability_source,
                agent_runner=agent_runner,
                agent_model=args.agent_model,
                agent_provider=args.agent_provider,
            )
            run = ledger.run_backtest_dataset(
                dataset=dataset,
                cases=cases,
                default_forecast_time_cutoff=args.as_of,
                evidence_cutoff_policy=args.evidence_cutoff_policy,
                allow_calibration_memory=args.allow_calibration_memory,
            )
            summary = run["result_summary"]
            print(
                f"{dataset} backtest_run={run['id']} "
                f"cases={summary.get('case_count', 0)} "
                f"scored={summary.get('scored_cases', 0)} "
                f"agent_mean_brier={_format_metric(summary.get('agent_mean_brier'))} "
                f"leakage={run['leakage_checks_passed']}"
            )
        return
    if args.list:
        rows = ledger.list_backtest_runs()
        if not rows:
            print("No backtest runs found.")
            return
        print("ID             Dataset              Cases  Scored  Leakage  Sources")
        for row in rows:
            summary = row["result_summary"]
            sources = ",".join(summary.get("probability_sources") or ["dataset"])
            print(
                f"{row['id']:<14} {row['dataset']:<20} "
                f"{summary.get('case_count', 0):<6} {summary.get('scored_cases', 0):<7} "
                f"{row['leakage_checks_passed']!s:<8} {sources}"
            )
        return
    if args.show:
        run = ledger.get_backtest_run(args.show)
        cases = ledger.list_backtest_cases(args.show)
        report = ledger.backtest_performance_report(args.show)
        print(f"backtest_run: {run['id']}")
        print(f"dataset: {run['dataset']}")
        print(f"leakage_checks_passed: {run['leakage_checks_passed']}")
        print(
            "probability_sources: "
            f"{', '.join(run['result_summary'].get('probability_sources') or ['dataset'])}"
        )
        print(f"cases: {len(cases)}")
        agent = report["agent"]
        print(
            "agent_mean_brier: "
            f"{_format_metric(agent['mean_brier'])} n={agent['count']}"
        )
        if report["baselines"]:
            print("baselines:")
            for baseline in report["baselines"]:
                name = f"{baseline['baseline_type']}:{baseline['source']}"
                print(
                    f"  {name} mean_brier={_format_metric(baseline['mean_brier'])} "
                    f"n={baseline['count']} paired={baseline['paired_count']} "
                    f"brier_improvement={_format_metric(baseline['mean_brier_improvement_vs_baseline'])}"
                )
                print(
                    "    paired_brier "
                    f"agent={_format_metric(baseline.get('paired_agent_mean_brier'))} "
                    f"baseline={_format_metric(baseline.get('paired_baseline_mean_brier'))} "
                    f"edge={_format_delta(baseline.get('paired_agent_edge_mean_brier'))} "
                    f"ci95={_format_ci95(baseline.get('paired_agent_edge_ci95_low'), baseline.get('paired_agent_edge_ci95_high'))} "
                    f"wins={baseline.get('paired_agent_wins', 0)}/"
                    f"{baseline.get('paired_baseline_wins', 0)}/"
                    f"{baseline.get('paired_ties', 0)}"
                )
        else:
            print("baselines: none")
        if report["agent_by_domain"]:
            print("agent_by_domain:")
            for domain, summary in report["agent_by_domain"].items():
                print(f"  {domain} mean_brier={_format_metric(summary['mean_brier'])} n={summary['count']}")
        if report["agent_by_horizon"]:
            print("agent_by_horizon:")
            for horizon, summary in report["agent_by_horizon"].items():
                print(f"  {horizon} mean_brier={_format_metric(summary['mean_brier'])} n={summary['count']}")
        for case in cases:
            snapshot_details = _backtest_case_snapshot_details(ledger, case)
            print(
                f"  {case['id']} question={case['question_id']} "
                f"score={case['score_record_id'] or '-'} leakage={case['leakage_check_status']}"
                f"{snapshot_details}"
            )
        return
    if not args.dataset:
        raise SystemExit("forecast backtest requires a dataset, --list, or --show")
    cases = _apply_backtest_probability_source(
        _load_backtest_cases(args.dataset, ledger=ledger),
        args.probability_source,
        agent_runner=agent_runner,
        agent_model=args.agent_model,
        agent_provider=args.agent_provider,
    )
    run = ledger.run_backtest_dataset(
        dataset=args.dataset,
        cases=cases,
        default_forecast_time_cutoff=args.as_of,
        evidence_cutoff_policy=args.evidence_cutoff_policy,
        allow_calibration_memory=args.allow_calibration_memory,
    )
    print(f"backtest_run: {run['id']}")
    print(f"cases: {run['result_summary'].get('case_count', 0)}")
    print(f"scored_cases: {run['result_summary'].get('scored_cases', 0)}")
    print(f"leakage_checks_passed: {run['leakage_checks_passed']}")


def _cmd_performance(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    rows, summaries = _recent_backtest_summaries(
        ledger,
        last=args.last,
        dataset=getattr(args, "dataset", None),
    )
    evidence_status = build_forecasting_evidence_status(ledger, summaries)

    if args.json:
        print(
            json.dumps(
                {
                    "last": max(args.last, 0),
                    "dataset_filter": args.dataset,
                    "run_count": len(summaries),
                    "evidence_status": evidence_status,
                    "runs": summaries,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if not rows:
        print("No backtest runs found.")
        _print_evidence_status(evidence_status)
        return

    print("ID             Dataset                  Cases  AgentBrier  BestBaseline           AgentEdge  Leakage")
    for summary in summaries:
        report = summary
        agent = report["agent"]
        agent_brier = agent["mean_brier"]
        best = report["best_baseline"]
        best_label = "-"
        if best is not None:
            best_name = f"{best['baseline_type']}:{best['source']}"
            best_label = f"{best_name}={_format_metric(best['mean_brier'])}"
        print(
            f"{report['id']:<14} {report['dataset'][:24]:<24} "
            f"{report['case_count']:<6} {_format_metric(agent_brier):<11} "
            f"{best_label[:22]:<22} {_format_delta(best.get('agent_edge_mean_brier') if best else None):<10} "
            f"{report['leakage_checks_passed']}"
        )
        for baseline in report["baselines"]:
            name = f"{baseline['baseline_type']}:{baseline['source']}"
            print(
                f"  baseline {name} brier={_format_metric(baseline['mean_brier'])} "
                f"paired={baseline['paired_count']} "
                f"agent_edge={_format_delta(baseline['mean_brier_improvement_vs_baseline'])} "
                f"paired_brier_agent={_format_metric(baseline.get('paired_agent_mean_brier'))} "
                f"paired_brier_baseline={_format_metric(baseline.get('paired_baseline_mean_brier'))} "
                f"paired_edge={_format_delta(baseline.get('paired_agent_edge_mean_brier'))} "
                f"ci95={_format_ci95(baseline.get('paired_agent_edge_ci95_low'), baseline.get('paired_agent_edge_ci95_high'))} "
                f"wins={baseline.get('paired_agent_wins', 0)}/"
                f"{baseline.get('paired_baseline_wins', 0)}/"
                f"{baseline.get('paired_ties', 0)}"
            )
        if report["agent_by_domain"]:
            print(f"  domains {_format_score_breakdown(report['agent_by_domain'])}")
        if report["agent_by_horizon"]:
            print(f"  horizons {_format_score_breakdown(report['agent_by_horizon'])}")
        claim = report.get("claim_status") or {}
        if claim:
            print(f"  claim {claim.get('verdict')}: {claim.get('message')}")
    _print_evidence_status(evidence_status)


def _cmd_readiness(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    rows, summaries = _recent_backtest_summaries(
        ledger,
        last=args.last,
        dataset=getattr(args, "dataset", None),
    )
    evidence_status = build_forecasting_evidence_status(
        ledger,
        summaries,
        min_live_scores=max(args.min_live_scores, 0),
        min_agent_protocol_cases=max(args.min_agent_protocol_cases, 0),
    )
    evidence_gaps = bool(evidence_status.get("gaps"))

    if args.json:
        print(
            json.dumps(
                {
                    "last": max(args.last, 0),
                    "dataset_filter": args.dataset,
                    "run_count": len(summaries),
                    "inspected_backtest_run_ids": [row["id"] for row in rows],
                    "evidence_status": evidence_status,
                },
                indent=2,
                sort_keys=True,
            )
        )
        if args.require_evidence and evidence_gaps:
            raise SystemExit(1)
        return

    print(f"readiness {evidence_status.get('verdict')}: {evidence_status.get('message')}")
    print(f"claim_live_superforecasting: {evidence_status.get('can_claim_live_superforecasting')}")
    _print_evidence_status(evidence_status, include_passed=True)
    if args.require_evidence and evidence_gaps:
        raise SystemExit(1)


def _recent_backtest_summaries(
    ledger: ForecastLedger,
    *,
    last: int,
    dataset: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = ledger.list_backtest_runs()
    if dataset:
        rows = [row for row in rows if dataset in row["dataset"]]
    rows = rows[: max(last, 0)]
    return rows, build_backtest_performance_summaries(ledger, rows)


def _print_evidence_status(evidence_status: dict[str, Any], *, include_passed: bool = False) -> None:
    backtests = evidence_status.get("backtests") or {}
    print(
        f"evidence {evidence_status.get('verdict')}: "
        f"live_scored={evidence_status.get('score_counts', {}).get('live', 0)} "
        f"agent_protocol_scored={backtests.get('agent_protocol_scored_count', 0)} "
        f"leakage_free_runs={backtests.get('leakage_free_run_count', 0)} "
        f"positive_edge_runs={backtests.get('positive_best_baseline_edge_run_count', 0)} "
        f"datasets={backtests.get('distinct_dataset_count', 0)}"
    )
    for requirement in evidence_status.get("requirements") or []:
        passed = bool(requirement.get("passed"))
        if passed and not include_passed:
            continue
        print(
            f"  {'ok' if passed else 'gap'} {requirement.get('id')}: "
            f"{requirement.get('observed', 0)}/{requirement.get('required', 0)}"
        )
    next_actions = list(evidence_status.get("next_actions") or [])
    if next_actions:
        print("next_actions:")
        for item in next_actions[:5]:
            print(f"  - {item.get('requirement_id')}: {item.get('action')}")


def _cmd_pilot_report(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    report = ledger.pilot_report(
        min_questions=args.min_questions,
        min_structured_source_questions=args.min_structured_source_questions,
        min_scores=args.min_scores,
        min_postmortems=args.min_postmortems,
        min_scheduled_reviews=args.min_scheduled_reviews,
    )
    incomplete = report["passed_checks"] < report["total_checks"]
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        if args.require_complete and incomplete:
            raise SystemExit(1)
        return

    summary = report["summary"]
    print(
        f"pilot {report['pilot_status']}: "
        f"{report['passed_checks']}/{report['total_checks']} checks passed"
    )
    print(
        "portfolio "
        f"questions={summary['question_count']} "
        f"forecasts={summary['questions_with_forecasts']} "
        f"evidence={summary['questions_with_evidence']} "
        f"structured_sources={summary['questions_with_structured_sources']} "
        f"live_scores={summary['score_counts_by_origin'].get('live', 0)} "
        f"postmortems={summary['postmortem_count']} "
        f"schedules={summary['enabled_scheduled_review_count']} "
        f"open_alerts={summary['open_alert_count']}"
    )
    for check in report["checks"]:
        label = "ok" if check["passed"] else "gap"
        print(f"  {label} {check['id']}: {check['observed']}/{check['required']} - {check['label']}")
    if report["source_types"]:
        print("source_types:")
        for source_type, count in report["source_types"].items():
            print(f"  - {source_type}: {count}")
    if report["next_actions"]:
        print("next_actions:")
        for action in report["next_actions"][:7]:
            print(f"  - {action}")
    if args.require_complete and incomplete:
        raise SystemExit(1)


def _cmd_pilot_cohort(args: argparse.Namespace) -> None:
    if args.schedule_cadence and not args.schedule_next_run_at:
        raise SystemExit("forecast pilot-cohort --schedule-cadence requires --schedule-next-run-at")
    if args.schedule_stale_days < 0:
        raise SystemExit("forecast pilot-cohort --schedule-stale-days must be non-negative")

    rows = _load_pilot_cohort_manifest(args.manifest)
    specs = [
        _pilot_cohort_spec_from_row(
            row,
            index=index,
            manifest=args.manifest,
            default_domain=args.default_domain,
            default_owner=args.default_owner,
            default_review_cadence=args.default_review_cadence,
            initial_probability_column=args.initial_probability_column,
            watch_source_column=args.watch_source_column,
        )
        for index, row in enumerate(rows)
    ]
    if not specs:
        raise SystemExit("forecast pilot-cohort manifest has no question rows")

    ledger = None if args.dry_run else _ledger(args)
    created: list[dict[str, Any]] = []
    for spec in specs:
        if args.dry_run:
            created.append(
                {
                    "row_index": spec["row_index"],
                    "title": spec["title"],
                    "domain": spec.get("domain"),
                    "topics": spec.get("topics", []),
                    "initial_probability": spec.get("initial_probability"),
                    "watch_sources": spec.get("watch_sources", []),
                    "dry_run": True,
                }
            )
            continue

        assert ledger is not None
        question = ledger.create_question(
            title=spec["title"],
            description=spec.get("description", ""),
            resolution_criteria=spec["resolution_criteria"],
            resolution_source=spec.get("resolution_source"),
            outcome_space=spec["outcome_space"],
            close_time=spec.get("close_time"),
            resolution_time=spec.get("resolution_time"),
            tags=spec.get("tags", []),
            domain=spec.get("domain"),
            topics=spec.get("topics", []),
            owner=spec.get("owner"),
            impact=spec.get("impact"),
            review_cadence=spec.get("review_cadence"),
            next_review_at=spec.get("next_review_at"),
            metadata={
                "pilot_cohort": True,
                "pilot_cohort_source": args.manifest,
                "pilot_cohort_row": spec["row_index"],
                "prospective_live_evidence": True,
            },
        )
        snapshot_id = None
        if spec.get("initial_probability") is not None:
            snapshot = ledger.create_snapshot(
                question_id=question.id,
                probability_or_distribution=spec["initial_probability"],
                rationale=spec.get("rationale")
                or "Initial prospective live forecast from pilot cohort manifest.",
                as_of=spec.get("as_of"),
                confidence=spec.get("confidence"),
                method=spec.get("method") or "pilot_cohort_initial",
                forecast_origin="live",
                metadata={
                    "pilot_cohort": True,
                    "pilot_cohort_source": args.manifest,
                    "pilot_cohort_row": spec["row_index"],
                },
            )
            snapshot_id = snapshot.forecast_id

        schedule_id = None
        if args.schedule_cadence:
            schedule = ledger.schedule_review(
                scope_type="question",
                scope_ref=question.id,
                cadence=args.schedule_cadence,
                next_run_at=args.schedule_next_run_at,
                stale_days=args.schedule_stale_days,
                trigger_reason="pilot_cohort_review",
            )
            schedule_id = schedule["id"]

        watch_ids: list[str] = []
        for source in spec.get("watch_sources", []):
            watch = ledger.add_watched_source(
                scope_type="question",
                scope_ref=question.id,
                source=source,
                metadata={
                    "pilot_cohort": True,
                    "pilot_cohort_source": args.manifest,
                    "pilot_cohort_row": spec["row_index"],
                },
            )
            watch_ids.append(watch["id"])

        created.append(
            {
                "row_index": spec["row_index"],
                "question_id": question.id,
                "title": question.title,
                "domain": question.domain,
                "topics": question.topics,
                "snapshot_id": snapshot_id,
                "schedule_id": schedule_id,
                "watch_ids": watch_ids,
            }
        )

    report = {
        "product": {
            "product_name": PRODUCT_NAME,
            "product_slug": PRODUCT_SLUG,
            "purpose": "prospective_live_pilot_cohort",
        },
        "generated_at": utc_now_iso(),
        "manifest": args.manifest,
        "dry_run": bool(args.dry_run),
        "question_count": len(specs),
        "initial_probability_count": sum(1 for spec in specs if spec.get("initial_probability") is not None),
        "scheduled_review_count": sum(1 for row in created if row.get("schedule_id")),
        "watched_source_count": sum(len(row.get("watch_ids", [])) for row in created),
        "questions": created,
        "next_actions": [
            "Run `forecast pilot-report` to check live pilot coverage.",
            "After outcomes resolve, run `forecast resolve <id> --outcome ...`, `forecast score <id>`, and `forecast postmortem <id> ...`.",
            "Export tester evidence with `forecast export all --format json` and aggregate with `forecast pilot-aggregate <exports...> --json`.",
        ],
        "claim_note": (
            "Pilot cohorts are prospective live evidence collection artifacts. "
            "They do not prove superiority until resolved, scored, postmortemed, and aggregated."
        ),
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    prefix = "would seed" if args.dry_run else "seeded"
    print(
        f"pilot_cohort {prefix} {report['question_count']} live question(s): "
        f"initial_probabilities={report['initial_probability_count']} "
        f"schedules={report['scheduled_review_count']} "
        f"watches={report['watched_source_count']}"
    )
    for row in created:
        question_ref = row.get("question_id") or f"row:{row['row_index']}"
        print(f"  - {question_ref}: {row['title']}")
        if row.get("snapshot_id"):
            print(f"    snapshot: {row['snapshot_id']}")
        if row.get("schedule_id"):
            print(f"    schedule: {row['schedule_id']}")
        if row.get("watch_ids"):
            print(f"    watches: {', '.join(row['watch_ids'])}")
    print("next_actions:")
    for action in report["next_actions"]:
        print(f"  - {action}")


def _cmd_pilot_aggregate(args: argparse.Namespace) -> None:
    report = _aggregate_pilot_exports(
        [Path(path) for path in args.exports],
        min_live_scores=args.min_live_scores,
    )
    incomplete = bool(report["checks"][0]["recommended_action"])
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        if args.require_live_scores and incomplete:
            raise SystemExit(1)
        return

    summary = report["summary"]
    print(
        f"pilot_exports {report['aggregate_status']}: "
        f"{summary['live_score_count']}/{report['checks'][0]['required']} live scores"
    )
    print(
        "portfolio "
        f"exports={summary['export_count']} "
        f"questions={summary['unique_question_count']} "
        f"snapshots={summary['forecast_snapshot_count']} "
        f"evidence={summary['evidence_count']} "
        f"structured_evidence={summary['structured_source_evidence_count']} "
        f"postmortems={summary['postmortem_count']}"
    )
    if report["source_types"]:
        print("source_types:")
        for source_type, count in report["source_types"].items():
            print(f"  - {source_type}: {count}")
    if report["domains"]:
        print("domains:")
        for domain, count in report["domains"].items():
            print(f"  - {domain}: {count}")
    if report["next_actions"]:
        print("next_actions:")
        for action in report["next_actions"]:
            print(f"  - {action}")
    if args.require_live_scores and incomplete:
        raise SystemExit(1)


def _cmd_pilot_bundle(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    pilot_report = ledger.pilot_report(
        min_questions=args.min_questions,
        min_structured_source_questions=args.min_structured_source_questions,
        min_scores=args.min_scores,
        min_postmortems=args.min_postmortems,
        min_scheduled_reviews=args.min_scheduled_reviews,
    )
    rows, summaries = _recent_backtest_summaries(
        ledger,
        last=args.last,
        dataset=getattr(args, "dataset", None),
    )
    evidence_status = build_forecasting_evidence_status(
        ledger,
        summaries,
        min_live_scores=max(args.min_live_scores, 0),
        min_agent_protocol_cases=max(args.min_agent_protocol_cases, 0),
    )
    export_packet = json.loads(ledger.export_all(fmt="json")) if args.include_export else None
    payload = {
        "product": {
            "product_name": PRODUCT_NAME,
            "product_slug": PRODUCT_SLUG,
            "purpose": "tester_pilot_handoff_bundle",
        },
        "generated_at": utc_now_iso(),
        "bundle_version": 1,
        "pilot_report": pilot_report,
        "readiness": {
            "last": max(args.last, 0),
            "dataset_filter": args.dataset,
            "run_count": len(summaries),
            "inspected_backtest_run_ids": [row["id"] for row in rows],
            "evidence_status": evidence_status,
        },
        "export_included": bool(args.include_export),
        "export_packet": export_packet,
        "privacy_note": (
            "Bundles can include source text, rationale, and local metadata when "
            "--include-export is used. Review before sharing outside the pilot."
        ),
        "claim_note": (
            "Pilot bundles collect live-evidence artifacts for evaluation. "
            "They are not, by themselves, proof of live superforecasting performance."
        ),
        "next_actions": [
            "Attach this JSON to a Forecast Pilot Feedback issue when it is safe to share.",
            "Resolve, score, and postmortem live questions as outcomes become known.",
            "Use `forecast readiness --json` to track remaining evidence gaps before stronger claims.",
        ],
    }
    output = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        path = Path(args.output)
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output + "\n", encoding="utf-8")
        print(f"pilot_bundle wrote {path}")
        return
    print(output)


def _load_pilot_cohort_manifest(source: str) -> list[dict[str, Any]]:
    if source.startswith(("http://", "https://")):
        text = _read_url_text(source, "pilot cohort manifest")
        label = source
    else:
        path = Path(source).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"pilot cohort manifest could not be read: {source}") from exc
        label = str(path)

    stripped = text.lstrip()
    if label.lower().endswith(".csv") or (stripped and not stripped.startswith(("{", "["))):
        raw_rows = list(csv.DictReader(text.splitlines()))
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"pilot cohort manifest is not valid JSON or CSV: {label}") from exc
        if isinstance(payload, dict):
            for key in ("questions", "rows", "items", "cohort"):
                if isinstance(payload.get(key), list):
                    raw_rows = payload[key]
                    break
            else:
                raw_rows = [payload]
        elif isinstance(payload, list):
            raw_rows = payload
        else:
            raise SystemExit("pilot cohort manifest must be a JSON object, array, or CSV table")
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if isinstance(raw, dict):
            rows.append({str(key): _strip_cell(value) for key, value in raw.items() if key is not None})
    return rows


def _pilot_cohort_spec_from_row(
    row: dict[str, Any],
    *,
    index: int,
    manifest: str,
    default_domain: str | None,
    default_owner: str | None,
    default_review_cadence: str | None,
    initial_probability_column: str | None,
    watch_source_column: str | None,
) -> dict[str, Any]:
    title = _cohort_text(_first_present(row, "title", "question", "question_title"))
    resolution_criteria = _cohort_text(
        _first_present(row, "resolution_criteria", "resolution", "criteria")
    )
    if not title:
        raise SystemExit(f"pilot cohort row {index + 1} is missing title/question")
    if not resolution_criteria:
        raise SystemExit(f"pilot cohort row {index + 1} is missing resolution_criteria")

    outcome_type = _cohort_text(_first_present(row, "outcome_type", "type")) or "binary"
    choices = _cohort_list(_first_present(row, "choices", "outcomes"))
    if outcome_type == "binary" and not choices:
        choices = ["yes", "no"]
    bounds = _cohort_float_list(_first_present(row, "bounds"))
    outcome_space = OutcomeSpace(
        type=outcome_type,
        choices=choices,
        units=_cohort_text(_first_present(row, "units", "unit")) or None,
        bounds=bounds or None,
    )
    outcome_space.validate()

    probability_column = (initial_probability_column or "").strip()
    probability = None
    if probability_column:
        probability = _cohort_probability(_first_present(row, probability_column, "initial_probability"))

    domain = _cohort_text(_first_present(row, "domain")) or default_domain
    owner = _cohort_text(_first_present(row, "owner")) or default_owner
    review_cadence = _cohort_text(_first_present(row, "review_cadence")) or default_review_cadence
    watch_column = (watch_source_column or "").strip()
    watch_sources = _cohort_list(row.get(watch_column)) if watch_column else []

    return {
        "row_index": index,
        "title": title,
        "description": _cohort_text(_first_present(row, "description", "notes")) or "",
        "resolution_criteria": resolution_criteria,
        "resolution_source": _cohort_text(_first_present(row, "resolution_source", "resolver")) or None,
        "outcome_space": outcome_space,
        "close_time": _cohort_text(_first_present(row, "close_time", "close_date")) or None,
        "resolution_time": _cohort_text(_first_present(row, "resolution_time", "resolution_date")) or None,
        "tags": _cohort_list(_first_present(row, "tags")),
        "domain": domain,
        "topics": _cohort_list(_first_present(row, "topics", "topic")),
        "owner": owner,
        "impact": _cohort_text(_first_present(row, "impact")) or None,
        "review_cadence": review_cadence,
        "next_review_at": _cohort_text(_first_present(row, "next_review_at")) or None,
        "initial_probability": probability,
        "rationale": _cohort_text(_first_present(row, "rationale", "initial_rationale")) or None,
        "as_of": _cohort_text(_first_present(row, "as_of", "forecast_as_of")) or None,
        "confidence": _cohort_probability(_first_present(row, "confidence")),
        "method": _cohort_text(_first_present(row, "method")) or None,
        "watch_sources": watch_sources,
        "manifest": manifest,
    }


def _strip_cell(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _cohort_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _cohort_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parsed = json_loads(value, None)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        delimiter = ";" if ";" in value else ","
        return [item.strip() for item in value.split(delimiter) if item.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _cohort_float_list(value: Any) -> list[float]:
    numbers = []
    for item in _cohort_list(value):
        try:
            numbers.append(float(item))
        except ValueError as exc:
            raise SystemExit("pilot cohort bounds must be numeric") from exc
    return numbers


def _cohort_probability(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        probability = float(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit("pilot cohort probability/confidence values must be numeric") from exc
    if not 0 <= probability <= 1:
        raise SystemExit("pilot cohort probability/confidence values must be between 0 and 1")
    return probability


def _aggregate_pilot_exports(paths: list[Path], *, min_live_scores: int = 10) -> dict[str, Any]:
    min_live_scores = max(int(min_live_scores), 0)
    source_type_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    unique_question_ids: set[str] = set()
    packet_summaries: list[dict[str, Any]] = []
    question_packet_count = 0
    resolved_question_count = 0
    forecast_snapshot_count = 0
    evidence_count = 0
    structured_source_evidence_count = 0
    live_score_count = 0
    score_count = 0
    postmortem_count = 0
    calibration_lesson_count = 0
    non_structured_source_types = {"manual_note", "note"}

    for path in paths:
        packet = _load_pilot_export_packet(path)
        question_packets = _question_packets_from_export(packet, path)
        packet_live_scores = 0
        packet_question_count = 0
        for question_packet in question_packets:
            question = question_packet.get("question") or {}
            question_id = str(question.get("id") or f"{path}:{packet_question_count}")
            unique_question_ids.add(question_id)
            packet_question_count += 1
            question_packet_count += 1
            domain = str(question.get("domain") or "unscoped")
            domain_counts[domain] += 1
            if question.get("status") == "resolved" or question_packet.get("resolution"):
                resolved_question_count += 1

            snapshots = question_packet.get("forecast_history") or []
            evidence = question_packet.get("evidence") or []
            scores = question_packet.get("scores") or []
            postmortems = question_packet.get("postmortems") or []
            lessons = question_packet.get("calibration_lessons") or []
            forecast_snapshot_count += len(snapshots)
            evidence_count += len(evidence)
            score_count += len(scores)
            postmortem_count += len(postmortems)
            calibration_lesson_count += len(lessons)
            for item in evidence:
                source_type = str((item or {}).get("source_type") or "unknown")
                source_type_counts[source_type] += 1
                if source_type not in non_structured_source_types:
                    structured_source_evidence_count += 1
            for score in scores:
                if (score or {}).get("forecast_origin") == "live":
                    live_score_count += 1
                    packet_live_scores += 1

        packet_summaries.append(
            {
                "path": str(path),
                "generated_at": packet.get("generated_at"),
                "question_count": packet_question_count,
                "live_score_count": packet_live_scores,
            }
        )

    live_scores_ready = live_score_count >= min_live_scores
    recommended_action = (
        ""
        if live_scores_ready
        else "Collect more resolved live forecasts: ask testers to run `forecast resolve`, `forecast score`, `forecast postmortem`, then `forecast export all --format json`."
    )
    return {
        "product": {
            "product_name": PRODUCT_NAME,
            "product_slug": PRODUCT_SLUG,
            "purpose": "tester_pilot_live_evidence_aggregate",
        },
        "generated_at": utc_now_iso(),
        "aggregate_status": "live_evidence_floor_met" if live_scores_ready else "collecting_live_evidence",
        "checks": [
            {
                "id": "live_scores_collected",
                "label": "resolved live forecast scores across tester exports",
                "observed": live_score_count,
                "required": min_live_scores,
                "passed": live_scores_ready,
                "recommended_action": recommended_action,
            }
        ],
        "next_actions": [recommended_action] if recommended_action else [],
        "summary": {
            "export_count": len(paths),
            "question_packet_count": question_packet_count,
            "unique_question_count": len(unique_question_ids),
            "resolved_question_count": resolved_question_count,
            "forecast_snapshot_count": forecast_snapshot_count,
            "evidence_count": evidence_count,
            "structured_source_evidence_count": structured_source_evidence_count,
            "score_count": score_count,
            "live_score_count": live_score_count,
            "postmortem_count": postmortem_count,
            "calibration_lesson_count": calibration_lesson_count,
        },
        "source_types": dict(sorted(source_type_counts.items())),
        "domains": dict(sorted(domain_counts.items())),
        "exports": packet_summaries,
        "claim_note": (
            "Aggregated tester exports are live evidence collection artifacts. "
            "They are not, by themselves, proof of superiority over markets, Metaculus, or human superforecasters."
        ),
    }


def _load_pilot_export_packet(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ForecastingError(f"could not read pilot export {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ForecastingError(f"pilot export is not valid JSON: {path}") from exc
    if not isinstance(loaded, dict):
        raise ForecastingError(f"pilot export must be a JSON object: {path}")
    return loaded


def _question_packets_from_export(packet: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    if isinstance(packet.get("questions"), list):
        question_packets = [row for row in packet["questions"] if isinstance(row, dict)]
    elif isinstance(packet.get("question"), dict):
        question_packets = [packet]
    else:
        raise ForecastingError(f"pilot export has no question packets: {path}")
    if not question_packets:
        raise ForecastingError(f"pilot export has no question packets: {path}")
    return question_packets


def _cmd_export(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    if args.id == "all":
        text = ledger.export_all(fmt=args.format)
    else:
        text = ledger.export_question(args.id, fmt=args.format)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(str(output))
        return
    print(text, end="")


def _probability_payload(args: argparse.Namespace, components: dict[str, Any] | None = None) -> Any:
    supplied = sum(
        1
        for value in (args.probability, args.numeric_value, args.distribution_json)
        if value is not None
    )
    if supplied > 1:
        raise SystemExit("use only one of --probability, --numeric-value, or --distribution-json")
    if args.numeric_value is not None:
        return args.numeric_value
    if args.distribution_json is not None:
        payload = json_loads(args.distribution_json, None)
        if not isinstance(payload, dict):
            raise SystemExit("--distribution-json must be a JSON object")
        return payload
    if args.probability is None and components:
        probability = weighted_binary_probability(components)
        if probability is not None:
            return probability
    if args.probability is None:
        raise SystemExit("forecast update requires --probability, --distribution-json, or weighted --component-json")
    return args.probability


def _json_arg(raw: str, name: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--{name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"--{name} must be a JSON object")
    return parsed


def _json_value_arg(raw: str, name: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--{name} must be valid JSON") from exc


def _format_probability(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, int):
        return f"{float(value):.3f}"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _probability_delta(previous: Any, current: Any) -> float | None:
    if isinstance(previous, (int, float)) and isinstance(current, (int, float)):
        return float(current) - float(previous)
    return None


def _question_delta(ledger: ForecastLedger, question_id: str) -> float | None:
    snapshots = ledger.list_snapshots(question_id)
    if len(snapshots) < 2:
        return None
    return _probability_delta(
        snapshots[-2].probability_or_distribution,
        snapshots[-1].probability_or_distribution,
    )


def _new_evidence_count(evidence: list[Any], current_snapshot: Any) -> int:
    if current_snapshot is None:
        return 0
    snapshot_dt = timestamp_to_datetime(current_snapshot.as_of)
    if snapshot_dt is None:
        return 0
    count = 0
    for item in evidence:
        available_dt = timestamp_to_datetime(item.available_at)
        if available_dt and available_dt > snapshot_dt:
            count += 1
    return count


def _review_next_action(question_id: str, reasons: list[str]) -> str:
    if any(reason.startswith("new_evidence:") for reason in reasons):
        return f"forecast research {question_id}; forecast update {question_id} --preview ..."
    if "no_forecast_snapshot" in reasons:
        return f"forecast update {question_id} --preview ..."
    if any(
        reason in {"resolution_check_due", "close_time_passed"}
        or reason.startswith("close_time_within_")
        for reason in reasons
    ):
        return f"forecast resolve {question_id} --outcome <value>"
    if "no_evidence" in reasons or any(reason.startswith("evidence_stale_") for reason in reasons):
        return f"forecast research {question_id}"
    if any(reason.startswith(("assumption_", "reference_class_")) for reason in reasons):
        return f"forecast protocol {question_id} --stage self_check"
    if "review_due" in reasons or any(reason.startswith("last_update_") for reason in reasons):
        return f"forecast research {question_id}; forecast update {question_id} --preview ..."
    return f"forecast show {question_id}"


def _toolsets_for_stage(stage: str) -> list[str]:
    toolsets = {
        "parse": ["forecasting", "file"],
        "research": ["forecasting", "file", "web"],
        "base_rate": ["forecasting", "file", "web"],
        "model": ["forecasting", "file", "terminal"],
        "update": ["forecasting"],
        "resolve": ["forecasting", "file", "web"],
        "postmortem": ["forecasting"],
        "self_check": ["forecasting", "file", "web"],
    }
    return toolsets.get(stage, ["forecasting"])


def _format_delta(delta: float | None) -> str:
    return "-" if delta is None else f"{delta:+.3f}"


def _format_ci95(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "-"
    return f"[{low:+.3f},{high:+.3f}]"


def _format_score_breakdown(items: dict[str, dict[str, Any]]) -> str:
    return " ".join(
        f"{name}={_format_metric(summary.get('mean_brier'))} n={summary.get('count', 0)}"
        for name, summary in items.items()
    )


def _backtest_case_snapshot_details(ledger: ForecastLedger, case: dict[str, Any]) -> str:
    forecast_id = case.get("generated_forecast_id")
    if not forecast_id:
        return " source=- method=- model=-"
    snapshot = ledger.get_snapshot(forecast_id)
    source = snapshot.metadata.get("probability_source") or snapshot.method or "dataset"
    method = snapshot.method or "-"
    model = snapshot.agent_model or "-"
    return f" source={source} method={method} model={model}"


def _format_metric(value: float | None) -> str:
    return "-" if value is None else f"{value:.6f}"


def _format_optional_float(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _parse_day_count(value: str) -> int:
    raw = str(value).strip().lower()
    if raw.endswith("d"):
        raw = raw[:-1]
    days = int(raw)
    if days < 0:
        raise argparse.ArgumentTypeError("day count must be non-negative")
    return days


def _schedule_scope(args: argparse.Namespace) -> tuple[str, str]:
    if args.question_id and (args.domain or args.topic or args.portfolio or args.horizon):
        raise SystemExit("--question cannot be combined with --domain, --topic, --portfolio, or --horizon")
    if args.portfolio and (args.question_id or args.domain or args.topic or args.horizon):
        raise SystemExit("--portfolio cannot be combined with --question, --domain, --topic, or --horizon")
    if args.horizon and (args.question_id or args.domain or args.topic or args.portfolio):
        raise SystemExit("--horizon cannot be combined with --question, --domain, --topic, or --portfolio")
    if args.question_id:
        return "question", args.question_id
    if args.domain and args.topic:
        return "domain_topic", json.dumps({"domain": args.domain, "topic": args.topic}, sort_keys=True)
    if args.domain:
        return "domain", args.domain
    if args.topic:
        return "topic", args.topic
    if args.horizon:
        return "horizon", args.horizon
    if not args.portfolio:
        raise SystemExit("schedule add requires --question, --domain, --topic, --portfolio, or --horizon")
    return "portfolio", args.portfolio


def _watch_scope(args: argparse.Namespace, *, required: bool) -> tuple[str | None, str | None]:
    if args.question_id and (args.domain or args.topic or args.portfolio):
        raise SystemExit("--question cannot be combined with --domain, --topic, or --portfolio")
    if args.portfolio and (args.question_id or args.domain or args.topic):
        raise SystemExit("--portfolio cannot be combined with --question, --domain, or --topic")
    if args.question_id:
        return "question", args.question_id
    if args.domain and args.topic:
        return "domain_topic", json_dumps({"domain": args.domain, "topic": args.topic})
    if args.domain:
        return "domain", args.domain
    if args.topic:
        return "topic", args.topic
    if args.portfolio:
        return "portfolio", args.portfolio
    if required:
        raise SystemExit("watch add requires --question, --domain, --topic, or --portfolio")
    return None, None


def _format_schedule_scope(row: dict[str, Any]) -> str:
    if row["scope_type"] != "domain_topic":
        return f"{row['scope_type']}:{row['scope_ref'] or '*'}"
    payload = json_loads(row["scope_ref"], {})
    return f"domain:{payload.get('domain', '*')}/{payload.get('topic', '*')}"


def _format_schedule_learning(row: dict[str, Any]) -> str:
    enabled = []
    if row.get("auto_score"):
        enabled.append("score")
    if row.get("auto_postmortem"):
        enabled.append("postmortem")
    return ",".join(enabled) if enabled else "-"


def _format_schedule_confidence(row: dict[str, Any]) -> str:
    parts = []
    if row.get("confidence_below") is not None:
        parts.append(f"<{float(row['confidence_below']):.2f}")
    if row.get("confidence_above") is not None:
        parts.append(f">{float(row['confidence_above']):.2f}")
    return ",".join(parts) if parts else "-"


def _format_schedule_delta(row: dict[str, Any]) -> str:
    if row.get("large_delta_threshold") is None:
        return "-"
    return f">={float(row['large_delta_threshold']):.2f}"


def _format_watch_scope(row: dict[str, Any]) -> str:
    return _format_schedule_scope(row)


def _is_importable_benchmark_source(source: str) -> bool:
    return source.startswith(("builtin:", "http://", "https://")) or Path(source).expanduser().is_file()


def _should_use_metaculus_adapter(args: argparse.Namespace) -> bool:
    source = str(args.source or "").strip()
    manual_context = bool(args.title or args.resolution_criteria or args.baseline_probability is not None)
    if source.startswith(("id:", "http://", "https://")):
        return not manual_context or "metaculus.com" in source
    return source.isdigit() or not manual_context


def _load_backtest_cases(dataset: str, *, ledger: ForecastLedger | None = None) -> list[dict[str, Any]]:
    if dataset.startswith("imported:"):
        if ledger is None:
            raise SystemExit("imported benchmark datasets require a forecast ledger")
        return ledger.get_benchmark_dataset(dataset)["cases"]
    if dataset.startswith("builtin:"):
        try:
            return load_builtin_benchmark(dataset)
        except KeyError as exc:
            raise SystemExit(f"unknown built-in benchmark: {dataset}") from exc
    if dataset.startswith(("http://", "https://")):
        text = _read_url_text(dataset, "backtest dataset")
        if dataset.lower().split("?", 1)[0].endswith(".csv"):
            return _load_backtest_cases_csv_text(text)
        return _load_backtest_cases_json_text(text, dataset)
    path = Path(dataset).expanduser()
    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        return _load_backtest_cases_csv_text(path.read_text(encoding="utf-8"))
    try:
        return _load_backtest_cases_json_text(path.read_text(encoding="utf-8"), str(path))
    except UnicodeDecodeError as exc:
        raise SystemExit(f"backtest dataset is not readable text: {path}") from exc


def _backtest_agent_protocol_runner(args: argparse.Namespace):
    output_path = _prepare_agent_protocol_output_jsonl(args.agent_output_jsonl)
    if args.agent_response_jsonl:
        responses = _load_agent_protocol_response_jsonl(args.agent_response_jsonl)

        def captured_runner(messages: list[dict[str, str]], case: dict[str, Any], index: int) -> Any:
            del messages
            keys = []
            if case.get("id") is not None:
                keys.append(str(case["id"]))
            keys.extend([f"index:{index}", str(index)])
            for key in keys:
                if key in responses:
                    response = responses[key]
                    _write_agent_protocol_response_jsonl(output_path, case, index, response)
                    return response
            raise SystemExit(
                "agent protocol response missing for "
                f"{case.get('id') or f'index:{index}'}"
            )

        return captured_runner

    from run_agent import AIAgent

    agent = AIAgent(
        model=args.agent_model or "",
        provider=args.agent_provider,
        max_iterations=args.agent_max_iterations,
        enabled_toolsets=["forecasting", "file", "web"],
        platform="cli",
    )

    def live_runner(messages: list[dict[str, str]], case: dict[str, Any], index: int) -> Any:
        del case, index
        result = agent.run_conversation(
            messages[1]["content"],
            system_message=messages[0]["content"],
        )
        if isinstance(result, dict):
            response = result.get("final_response") or result
        else:
            response = result
        _write_agent_protocol_response_jsonl(output_path, case, index, response)
        return response

    return live_runner


def _prepare_agent_protocol_output_jsonl(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def _write_agent_protocol_response_jsonl(
    path: Path | None,
    case: dict[str, Any],
    index: int,
    response: Any,
) -> None:
    if path is None:
        return
    row = {
        "case_id": case.get("id"),
        "index": index,
        "response": response,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _load_agent_protocol_response_jsonl(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    if not path.exists():
        raise SystemExit(f"agent response JSONL file not found: {path}")
    responses: dict[str, Any] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"agent response JSONL line {line_number} is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise SystemExit(f"agent response JSONL line {line_number} must be an object")
        key = payload.get("case_id", payload.get("id", payload.get("index")))
        if key is None:
            raise SystemExit(
                f"agent response JSONL line {line_number} needs case_id, id, or index"
            )
        responses[str(key)] = payload.get("response", payload)
    return responses


def _apply_backtest_probability_source(
    cases: list[dict[str, Any]],
    source: str,
    *,
    agent_runner=None,
    agent_model: str | None = None,
    agent_provider: str | None = None,
) -> list[dict[str, Any]]:
    if source == "dataset":
        return cases
    if source == "agent-protocol" and agent_runner is None:
        raise SystemExit("agent-protocol probability source requires an agent runner")

    transformed: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        next_case = dict(case)
        if source == "naive":
            next_case["probability"] = 0.5
            next_case["probability_source"] = "naive"
            transformed.append(next_case)
            continue
        if source == "forecast-engine":
            result = forecast_engine_binary_probability(case)
            if result is not None:
                next_case["probability"] = result["probability"]
                next_case["method"] = "forecast_engine_v0"
                next_case["component_forecasts"] = result["components"]
                next_case["probability_source"] = "forecast-engine"
                next_case["rationale"] = (
                    "Backtest probability generated by the local forecast "
                    "engine from pre-cutoff baselines, base rates, evidence "
                    "stance metadata, and fixed extremization."
                )
            transformed.append(next_case)
            continue
        if source == "agent-protocol":
            try:
                result = agent_protocol_binary_probability(
                    case,
                    runner=agent_runner,
                    case_index=index,
                )
            except ValueError as exc:
                case_id = case.get("id") or f"index:{index}"
                raise SystemExit(f"agent-protocol response invalid for {case_id}: {exc}") from exc
            next_case["probability"] = result["probability"]
            next_case["confidence"] = result.get("confidence")
            next_case["method"] = AGENT_PROTOCOL_METHOD
            next_case["prompt_version"] = AGENT_PROTOCOL_PROMPT_VERSION
            next_case["probability_source"] = "agent-protocol"
            if agent_model or result.get("agent_model"):
                next_case["agent_model"] = result.get("agent_model") or agent_model
            if agent_provider:
                next_case.setdefault("forecast_metadata", {})["agent_provider"] = agent_provider
            next_case["ensemble_components"] = _normalize_ensemble_components(result.get("components"))
            next_case["rationale"] = result.get("rationale") or (
                "Backtest probability generated by the agent forecasting protocol."
            )
            transformed.append(next_case)
            continue
        probability = _baseline_ensemble_probability(case)
        if probability is not None:
            next_case["probability"] = probability
            next_case["method"] = "baseline_ensemble"
            next_case["probability_source"] = "baseline-ensemble"
            next_case["rationale"] = (
                "Backtest probability generated from explicit benchmark "
                "baselines with deterministic weights."
            )
        transformed.append(next_case)
    return transformed


def _normalize_ensemble_components(components: Any) -> dict[str, Any]:
    if isinstance(components, dict):
        return components
    if not isinstance(components, list):
        return {}
    normalized: dict[str, Any] = {}
    for index, component in enumerate(components, start=1):
        if isinstance(component, dict):
            name = component.get("name") or component.get("source") or f"component_{index}"
            normalized[str(name)] = component
        else:
            normalized[f"component_{index}"] = component
    return normalized


def _baseline_ensemble_probability(case: dict[str, Any]) -> float | None:
    weighted_sum = 0.0
    total_weight = 0.0
    for baseline in case.get("baselines") or []:
        if not isinstance(baseline, dict):
            continue
        probability = _optional_probability(baseline.get("probability"))
        if probability is None:
            continue
        weight = _baseline_ensemble_weight(
            str(baseline.get("baseline_type") or ""),
            str(baseline.get("source") or ""),
        )
        weighted_sum += probability * weight
        total_weight += weight

    base_rate = case.get("base_rate", case.get("base_rate_probability"))
    base_rate_probability = _optional_probability(base_rate)
    if base_rate_probability is not None:
        weighted_sum += base_rate_probability * 2.0
        total_weight += 2.0

    if total_weight <= 0:
        return None
    return round(weighted_sum / total_weight, 6)


def _baseline_ensemble_weight(baseline_type: str, source: str) -> float:
    if baseline_type in {"market", "crowd"}:
        return 4.0
    if baseline_type == "base_rate":
        return 2.0
    if baseline_type == "naive_0_5" and source == "auto":
        return 1.0
    return 1.0


def _optional_probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        probability = float(value)
    elif isinstance(value, str):
        try:
            probability = float(value)
        except ValueError:
            return None
    else:
        return None
    if not 0 <= probability <= 1:
        return None
    return probability


def _load_backtest_cases_json_text(text: str, label: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"backtest dataset is not valid JSON: {label}") from exc
    if isinstance(payload, list):
        cases = payload
    elif isinstance(payload, dict):
        cases = payload.get("cases", [])
    else:
        raise SystemExit("backtest dataset must be a JSON array or object with cases")
    if not isinstance(cases, list):
        raise SystemExit("backtest dataset cases must be a JSON array")
    return [case for case in cases if isinstance(case, dict)]


def _load_market_baselines(source: str) -> list[dict[str, Any]]:
    if source.startswith(("http://", "https://")):
        text = _read_url_text(source, "market import source")
        if source.lower().split("?", 1)[0].endswith(".csv"):
            return _load_market_baselines_csv_text(text)
        return _load_market_baselines_json_text(text, source)
    path = Path(source).expanduser()
    if not path.is_file():
        return []
    if path.suffix.lower() == ".csv":
        return _load_market_baselines_csv_text(path.read_text(encoding="utf-8"))
    try:
        return _load_market_baselines_json_text(path.read_text(encoding="utf-8"), str(path))
    except UnicodeDecodeError as exc:
        raise SystemExit(f"market import source is not readable text: {path}") from exc


def _load_data_evidence_rows(source: str, *, limit: int, since: str | None = None) -> list[dict[str, Any]]:
    if limit <= 0:
        raise SystemExit("forecast import data --limit must be positive")
    if source.startswith(("http://", "https://")):
        text = _read_url_text(source, "data import source")
        rows = (
            _load_data_evidence_csv_text(text)
            if source.lower().split("?", 1)[0].endswith(".csv")
            else _load_data_evidence_json_text(text, source)
        )
    else:
        path = Path(source).expanduser()
        if not path.is_file():
            raise SystemExit(f"data import source not found: {source}")
        if path.suffix.lower() == ".csv":
            rows = _load_data_evidence_csv_text(path.read_text(encoding="utf-8"))
        else:
            try:
                rows = _load_data_evidence_json_text(path.read_text(encoding="utf-8"), str(path))
            except UnicodeDecodeError as exc:
                raise SystemExit(f"data import source is not readable text: {path}") from exc
    since_dt = timestamp_to_datetime(parse_timestamp(since, field_name="since")) if since else None
    filtered = []
    for row in rows:
        if since_dt is not None:
            available_dt = timestamp_to_datetime(row.get("available_at"))
            if available_dt is None or available_dt < since_dt:
                continue
        filtered.append(row)
        if len(filtered) >= limit:
            break
    return filtered


def _load_data_evidence_json_text(text: str, label: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"data import source is not valid JSON: {label}") from exc
    if isinstance(payload, dict):
        if isinstance(payload.get("rows"), list):
            rows = payload["rows"]
        elif isinstance(payload.get("items"), list):
            rows = payload["items"]
        elif isinstance(payload.get("data"), list):
            rows = payload["data"]
        else:
            rows = [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise SystemExit("data import source must be a JSON object, array, or object with rows/items/data")
    return [
        normalized
        for index, row in enumerate(rows)
        if isinstance(row, dict)
        for normalized in [_data_evidence_from_row(row, index)]
        if normalized is not None
    ]


def _load_data_evidence_csv_text(text: str) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(text.splitlines()))
    evidence_rows = []
    for index, row in enumerate(rows):
        normalized = _data_evidence_from_row(row, index)
        if normalized is not None:
            evidence_rows.append(normalized)
    return evidence_rows


def _data_evidence_from_row(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    cleaned = {str(key): (value.strip() if isinstance(value, str) else value) for key, value in row.items() if key}
    claim = _first_present(cleaned, "claim", "title", "name", "metric", "series_id", "indicator")
    value = _first_present(cleaned, "value", "latest", "observation", "reading")
    if not claim and value in {None, ""}:
        return None
    if not claim:
        claim = f"data row {index + 1}"
    if value not in {None, ""}:
        claim = f"{claim}: {value}"
    available_at = _first_present(cleaned, "available_at", "as_of", "timestamp", "date", "updated_at")
    source_url = _first_present(cleaned, "url", "source_url", "link")
    return {
        "claim": str(claim),
        "summary": str(_first_present(cleaned, "summary", "description", "text", "notes") or ""),
        "available_at": available_at,
        "published_at": _first_present(cleaned, "published_at", "publication_time", "released_at"),
        "source_name": _first_present(cleaned, "source_name", "source", "provider", "dataset"),
        "source_url": source_url,
        "source_or_note": source_url or str(claim),
        "stance": str(_first_present(cleaned, "stance", "direction") or "context"),
        "metadata": {
            "row_index": index,
            "row": cleaned,
        },
    }


def _load_market_baselines_json_text(text: str, label: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"market import source is not valid JSON: {label}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("markets"), list):
        rows = payload["markets"]
    elif isinstance(payload, dict) and isinstance(payload.get("baselines"), list):
        rows = payload["baselines"]
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = [payload]
    baselines = []
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            baseline = _market_baseline_from_row(row, index)
            if baseline:
                baselines.append(baseline)
    return baselines


def _load_market_baselines_csv_text(text: str) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(text.splitlines()))
    baselines = []
    for index, row in enumerate(rows):
        baseline = _market_baseline_from_row(row, index)
        if baseline:
            baselines.append(baseline)
    return baselines


def _market_baseline_from_row(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    probability = _first_present(row, "probability", "market_probability", "baseline_probability", "implied_probability")
    distribution = _first_present(row, "distribution", "baseline_distribution")
    if isinstance(distribution, str):
        distribution = json_loads(distribution, None)
    if probability in {None, ""} and not isinstance(distribution, dict):
        return None
    baseline: dict[str, Any] = {
        "source": _first_present(row, "source", "market", "baseline_source") or "market",
        "baseline_type": row.get("baseline_type") or "market",
        "as_of": _first_present(row, "as_of", "baseline_as_of", "timestamp", "updated_at"),
        "metadata": {
            "row_index": index,
            "market_id": _first_present(row, "id", "market_id", "symbol"),
        },
    }
    if isinstance(distribution, dict):
        baseline["distribution"] = distribution
    else:
        try:
            baseline["probability"] = float(probability)
        except (TypeError, ValueError) as exc:
            raise SystemExit("market probability must be numeric") from exc
    return baseline


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _read_url_text(url: str, label: str) -> str:
    try:
        request = Request(url, headers={"User-Agent": "superforecasting-agent/import"})
        with urlopen(request, timeout=10) as response:
            body = response.read(5 * 1024 * 1024)
            charset = response.headers.get_content_charset() or "utf-8"
            return body.decode(charset, errors="replace")
    except (OSError, URLError, ValueError) as exc:
        raise SystemExit(f"{label} URL could not be read: {url}") from exc


def _load_backtest_cases_csv_text(text: str) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(text.splitlines()))
    cases: list[dict[str, Any]] = []
    for raw_row in rows:
        row = {str(key): (value.strip() if isinstance(value, str) else value) for key, value in raw_row.items() if key}
        case: dict[str, Any] = {}
        for field in (
            "id",
            "title",
            "description",
            "resolution_criteria",
            "resolution_source",
            "as_of",
            "simulated_forecast_time",
            "evidence_cutoff",
            "close_time",
            "resolution_time",
            "outcome",
            "rationale",
            "method",
            "domain",
            "notes",
        ):
            value = _csv_cell(row, field)
            if value:
                case[field] = value

        probability = _csv_float(row, "probability") if _csv_cell(row, "probability") else _csv_float(row, "forecast_probability")
        if probability is not None:
            case["probability"] = probability
        base_rate = _csv_float(row, "base_rate") if _csv_cell(row, "base_rate") else _csv_float(row, "base_rate_probability")
        if base_rate is not None:
            case["base_rate"] = base_rate

        tags = _csv_list(row, "tags")
        if tags:
            case["tags"] = tags
        topics = _csv_list(row, "topics")
        if topics:
            case["topics"] = topics

        outcome_space = _csv_json(row, "outcome_space")
        if outcome_space is None:
            outcome_space = {}
            outcome_type = _csv_cell(row, "outcome_type")
            if outcome_type:
                outcome_space["type"] = outcome_type
            choices = _csv_list(row, "choices")
            if choices:
                outcome_space["choices"] = choices
            units = _csv_cell(row, "units")
            if units:
                outcome_space["units"] = units
        if isinstance(outcome_space, dict) and outcome_space:
            case["outcome_space"] = outcome_space

        evidence = _csv_json(row, "evidence_json")
        if evidence is None:
            evidence_item = {
                "note": _csv_cell(row, "evidence_note"),
                "claim": _csv_cell(row, "evidence_claim"),
                "summary": _csv_cell(row, "evidence_summary"),
                "available_at": _csv_cell(row, "evidence_available_at"),
                "published_at": _csv_cell(row, "evidence_published_at"),
                "source": _csv_cell(row, "evidence_source"),
                "url": _csv_cell(row, "evidence_url"),
                "stance": _csv_cell(row, "evidence_stance"),
                "claim_type": _csv_cell(row, "evidence_claim_type"),
            }
            evidence_item = {key: value for key, value in evidence_item.items() if value}
            evidence = [evidence_item] if evidence_item else []
        if isinstance(evidence, list):
            case["evidence"] = [item for item in evidence if isinstance(item, dict)]

        baselines = _csv_json(row, "baselines_json")
        if not isinstance(baselines, list):
            baselines = []
        baseline_probability = _csv_float(row, "baseline_probability")
        baseline_distribution = _csv_json(row, "baseline_distribution")
        if baseline_probability is not None or isinstance(baseline_distribution, dict):
            baseline: dict[str, Any] = {
                "source": _csv_cell(row, "baseline_source") or "dataset",
                "baseline_type": _csv_cell(row, "baseline_type") or "imported",
                "as_of": _csv_cell(row, "baseline_as_of") or case.get("as_of") or case.get("simulated_forecast_time"),
            }
            if baseline_probability is not None:
                baseline["probability"] = baseline_probability
            if isinstance(baseline_distribution, dict):
                baseline["distribution"] = baseline_distribution
            baselines.append(baseline)
        if baselines:
            case["baselines"] = [item for item in baselines if isinstance(item, dict)]

        if case:
            cases.append(case)
    return cases


def _csv_cell(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) else ""


def _csv_float(row: dict[str, Any], key: str) -> float | None:
    value = _csv_cell(row, key)
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise SystemExit(f"CSV column {key} must be numeric") from exc


def _csv_list(row: dict[str, Any], key: str) -> list[str]:
    value = _csv_cell(row, key)
    if not value:
        return []
    parsed = json_loads(value, None)
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    delimiter = ";" if ";" in value else ","
    return [item.strip() for item in value.split(delimiter) if item.strip()]


def _csv_json(row: dict[str, Any], key: str) -> Any:
    value = _csv_cell(row, key)
    if not value:
        return None
    parsed = json_loads(value, None)
    if parsed is None:
        raise SystemExit(f"CSV column {key} must be valid JSON")
    return parsed
