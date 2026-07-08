"""Command-line interface for forecast ledger workflows."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen

from forecasting.agent_protocol import (
    AGENT_PROTOCOL_METHOD,
    AGENT_PROTOCOL_PROMPT_VERSION,
    agent_protocol_binary_probability,
    build_agent_protocol_prompt_packet,
)
from forecasting.backtesting import (
    DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM,
    DEFAULT_MIN_EXTERNAL_SOURCE_FAMILIES_FOR_CLAIM,
    DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM,
    build_backtest_performance_summaries,
    build_forecasting_evidence_status,
)
from forecasting.benchmark_evidence import build_benchmark_evidence_profile
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
from forecasting.learning import (
    apply_active_lesson_adjustments,
    should_apply_active_lessons,
    is_learned_error_review_reason,
    is_learning_review_reason,
    learned_error_profile_id,
)
from forecasting.ledger import CRUX_MATERIALITY, CRUX_STATUS, FORECAST_LINK_TYPES, ForecastLedger, WATCH_SOURCE_ROLES, WATCH_SOURCE_TYPES
from forecasting.models import (
    ASSUMPTION_STATUSES,
    CALIBRATION_LESSON_STATUSES,
    EVIDENCE_CLAIM_TYPES,
    FAILURE_CLASSES,
    REFERENCE_CLASS_STATUSES,
    ForecastingError,
    OutcomeSpace,
    json_dumps,
    json_loads,
    parse_timestamp,
    timestamp_to_datetime,
    utc_now_iso,
)
from forecasting.protocol import (
    PROTOCOL_STAGES,
    build_pipeline_status,
    build_protocol_messages,
    pipeline_advance_block,
)
from forecasting.source_adapters import (
    load_arxiv_papers,
    load_bluesky_posts,
    load_bls_observations,
    load_census_records,
    load_ckan_datasets,
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
    load_github_repository_snapshots,
    load_github_workflow_runs,
    load_hackernews_items,
    load_github_issues,
    load_github_releases,
    load_imf_datamapper_observations,
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
from forecasting.source_planner import SourceRecommendation, plan_sources_for_question
from forecasting.search import match_to_dict, resolve_question_ref, search_forecasts
from forecasting.source_search import (
    WatchedTextSourceSearchResult,
    capture_watched_text_candidates,
    search_watched_text_sources,
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
        "name": "imf",
        "domain": "IMF macro indicators",
        "import_command": "forecast import imf <indicator>/<country> --question <id>",
        "watch_prefix": "imf:<indicator>/<country>",
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
        "name": "ckan",
        "domain": "open-data package metadata",
        "import_command": "forecast import ckan <domain>/<query> --question <id>",
        "watch_prefix": "ckan:<domain>/<query>",
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
        "name": "githubrepo",
        "domain": "repository metadata and adoption counters",
        "import_command": "forecast import githubrepo <owner/repo> --question <id>",
        "watch_prefix": "githubrepo:<owner/repo>",
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

    bench_parser = forecast_sub.add_parser(
        "bench",
        help="Show the read-only ForecastBench backtest scoreboard (agent vs market Brier)",
    )
    bench_parser.add_argument("--limit", type=int, default=None, help="Cap the number of rows shown")
    bench_parser.add_argument("--json", action="store_true", help="Emit the machine-readable scoreboard JSON")
    bench_parser.set_defaults(_forecast_handler=_cmd_bench)

    doctor_parser = forecast_sub.add_parser(
        "doctor",
        help="Run operational, pilot, and readiness checks",
    )
    doctor_parser.add_argument("--last", type=int, default=20, help="Number of recent backtest runs to inspect")
    doctor_parser.add_argument("--dataset", help="Filter readiness to runs whose dataset contains this text")
    doctor_parser.add_argument("--min-questions", type=int, default=3)
    doctor_parser.add_argument("--min-structured-source-questions", type=int, default=1)
    doctor_parser.add_argument("--min-scores", type=int, default=1)
    doctor_parser.add_argument("--min-postmortems", type=int, default=1)
    doctor_parser.add_argument("--min-scheduled-reviews", type=int, default=1)
    doctor_parser.add_argument("--min-scheduled-review-runs", type=int, default=1)
    doctor_parser.add_argument(
        "--min-live-scores",
        type=int,
        default=DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM,
        help="Required resolved live scores for readiness accounting",
    )
    doctor_parser.add_argument(
        "--min-agent-protocol-cases",
        type=int,
        default=DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM,
        help="Required scored agent-protocol replay cases for readiness accounting",
    )
    doctor_parser.add_argument(
        "--min-external-source-families",
        type=int,
        default=DEFAULT_MIN_EXTERNAL_SOURCE_FAMILIES_FOR_CLAIM,
        help="Required distinct external resolved-question source families for readiness accounting",
    )
    doctor_parser.add_argument(
        "--require-pilot-ready",
        action="store_true",
        help="Exit nonzero if tester pilot artifacts are incomplete",
    )
    doctor_parser.add_argument(
        "--require-readiness",
        action="store_true",
        help="Exit nonzero if benchmark/live evidence-readiness gaps remain",
    )
    doctor_parser.add_argument("--json", action="store_true", help="Emit machine-readable doctor JSON")
    doctor_parser.set_defaults(_forecast_handler=_cmd_doctor)

    backup_parser = forecast_sub.add_parser(
        "backup",
        help="Back up the forecast ledger (online snapshot + integrity check) and manage retention",
    )
    backup_sub = backup_parser.add_subparsers(dest="backup_command")
    backup_run = backup_sub.add_parser(
        "run", help="Create an online backup + integrity check now (runs as a durable job)"
    )
    backup_run.add_argument(
        "--dest-dir", help="Override the backup directory (default: <ledger dir>/backups)"
    )
    backup_run.add_argument(
        "--keep-recent", type=int, help="Retention override: newest N backups always kept (default 14)"
    )
    backup_run.add_argument(
        "--weekly-weeks", type=int, help="Retention override: one-per-week for W weeks (default 8)"
    )
    backup_run.add_argument("--json", action="store_true", help="Emit the machine-readable job record")
    backup_run.set_defaults(_forecast_handler=_cmd_backup_run)
    backup_list = backup_sub.add_parser("list", help="List existing ledger backups (newest first)")
    backup_list.add_argument(
        "--dest-dir", help="Override the backup directory (default: <ledger dir>/backups)"
    )
    backup_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    backup_list.set_defaults(_forecast_handler=_cmd_backup_list)
    # Bare `forecast backup` runs a backup now.
    backup_parser.set_defaults(_forecast_handler=_cmd_backup_run)

    lint_parser = forecast_sub.add_parser(
        "lint", help="Saturation report for a forecast: 0-100 score + per-rule verdicts (style + completeness)"
    )
    lint_parser.add_argument("question_id", nargs="?", help="Question id to lint")
    lint_parser.add_argument("--all", action="store_true", help="Lint every active question and summarize (finish sweep)")
    lint_parser.add_argument("--by-rule", action="store_true", help="Read-only per-rule fire-count table across active live forecasts (the migration debt table)")
    lint_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    lint_parser.set_defaults(_forecast_handler=_cmd_lint)

    hooks_parser = forecast_sub.add_parser(
        "hooks", help="Inspect / tune / author the saturation + style hook rules"
    )
    hooks_sub = hooks_parser.add_subparsers(dest="hooks_command")

    hooks_list = hooks_sub.add_parser("list", help="Show the active rules + their resolved severity (and why)")
    hooks_list.add_argument("--question", dest="question_id", help="Resolve severities for a specific question")
    hooks_list.add_argument("--json", action="store_true")
    hooks_list.set_defaults(_forecast_handler=_cmd_hooks_list)

    hooks_profiles = hooks_sub.add_parser("profiles", help="List the curated profiles + their rule severities")
    hooks_profiles.set_defaults(_forecast_handler=_cmd_hooks_profiles)

    hooks_explain = hooks_sub.add_parser("explain", help="Explain a signal (or list every signal the DSL exposes)")
    hooks_explain.add_argument("signal", nargs="?", help="Signal name; omit to list all")
    hooks_explain.set_defaults(_forecast_handler=_cmd_hooks_explain)

    hooks_lint = hooks_sub.add_parser("lint", help="Validate the configured user-defined rules (teaching errors)")
    hooks_lint.set_defaults(_forecast_handler=_cmd_hooks_lint)

    hooks_methods = hooks_sub.add_parser("methods", help="List the reasoning-method taxonomy the reasoning hook checks")
    hooks_methods.set_defaults(_forecast_handler=_cmd_hooks_methods)

    hooks_preview = hooks_sub.add_parser(
        "preview", help="Dry-run a candidate rule spec against the current ledger (which forecasts would it block?)"
    )
    hooks_preview.add_argument("--spec", required=True, help="Path to a YAML/JSON rule spec to preview")
    hooks_preview.add_argument("--json", action="store_true")
    hooks_preview.set_defaults(_forecast_handler=_cmd_hooks_preview)

    hooks_set_sev = hooks_sub.add_parser("set-severity", help="Set a rule's severity override (off|warn|error)")
    hooks_set_sev.add_argument("rule_id")
    hooks_set_sev.add_argument("severity", choices=["off", "warn", "error"])
    hooks_set_sev.set_defaults(_forecast_handler=_cmd_hooks_set_severity)

    hooks_set_prof = hooks_sub.add_parser("set-profile", help="Set the active hook profile")
    hooks_set_prof.add_argument("profile")
    hooks_set_prof.set_defaults(_forecast_handler=_cmd_hooks_set_profile)

    hooks_enable = hooks_sub.add_parser("enable", help="Enable a rule (revert to the profile's severity)")
    hooks_enable.add_argument("rule_id")
    hooks_enable.set_defaults(_forecast_handler=_cmd_hooks_enable)

    hooks_disable = hooks_sub.add_parser("disable", help="Disable a rule (severity off)")
    hooks_disable.add_argument("rule_id")
    hooks_disable.set_defaults(_forecast_handler=_cmd_hooks_disable)

    hooks_add = hooks_sub.add_parser("add", help="Validate + save a user rule from a spec file")
    hooks_add.add_argument("--spec", required=True, help="Path to a YAML/JSON rule spec")
    hooks_add.set_defaults(_forecast_handler=_cmd_hooks_add)

    hooks_edit = hooks_sub.add_parser("edit", help="Validate + replace an existing user rule from a spec file")
    hooks_edit.add_argument("rule_id")
    hooks_edit.add_argument("--spec", required=True, help="Path to a YAML/JSON rule spec")
    hooks_edit.set_defaults(_forecast_handler=_cmd_hooks_edit)

    hooks_remove = hooks_sub.add_parser("remove", help="Remove a user rule by id")
    hooks_remove.add_argument("rule_id")
    hooks_remove.set_defaults(_forecast_handler=_cmd_hooks_remove)

    sources_parser = forecast_sub.add_parser("sources", help="List forecast evidence source adapters")
    sources_parser.add_argument("--question", dest="question_id", help="Plan sources for a forecast question")
    sources_parser.add_argument("--plan", action="store_true", help="Show forecast-aware source recommendations")
    sources_parser.add_argument("--apply-watch", action="store_true", help="Add concrete recommended watched sources")
    sources_parser.add_argument(
        "--search-watched",
        action="store_true",
        help="Search active watched RSS/Atom streams for question-relevant candidate evidence",
    )
    sources_parser.add_argument("--query", help="Extra source-search terms; defaults to question metadata and watch filters")
    sources_parser.add_argument("--since", help="Only consider watched RSS/Atom items at or after this timestamp")
    sources_parser.add_argument(
        "--capture-candidates",
        action="store_true",
        help="Promote matching watched-source search results into evidence without updating probability",
    )
    sources_parser.add_argument("--limit", type=int, default=12, help="Maximum source-plan rows to show")
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
    new_parser.add_argument("--source-plan", action="store_true", help="Print recommended sources after creating the question")
    new_parser.add_argument(
        "--apply-source-plan",
        "--apply-watch",
        dest="apply_source_plan",
        action="store_true",
        help="Add (apply) the top recommended watched sources from the generated source plan",
    )
    new_parser.add_argument("--review-cadence")
    new_parser.add_argument("--next-review-at")
    new_parser.add_argument(
        "--decision-owner",
        help="Who owns the decision this forecast informs (e.g. 'ops lead', 'trading desk')",
    )
    new_parser.add_argument(
        "--decision-deadline",
        help="ISO-8601 timestamp by which the decision must be made",
    )
    new_parser.add_argument(
        "--action-threshold",
        help="Probability/threshold that triggers an action (e.g. 'evacuate if P > 0.05')",
    )
    new_parser.add_argument(
        "--update-trigger",
        dest="update_triggers",
        action="append",
        default=[],
        help=(
            "Repeatable. Each value is either a free-form trigger ('PCE release within 24h') "
            "or a JSON object with mechanism/threshold/action keys"
        ),
    )
    new_parser.set_defaults(_forecast_handler=_cmd_new)

    onboard_parser = forecast_sub.add_parser(
        "onboard",
        help="Curate a new question as a typed QuestionSpec — propose + validate, then commit the full fan-out",
    )
    onboard_parser.add_argument("prompt", nargs="?", help="Plain-language question to seed a draft spec")
    onboard_parser.add_argument("--spec", help="Path to a QuestionSpec JSON file (from a prior --json proposal, edited)")
    onboard_parser.add_argument(
        "--commit",
        action="store_true",
        help="Validate and commit the --spec (refuses on error-severity issues)",
    )
    onboard_parser.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Accept every recommended default, commit the question, then autonomously "
            "chain research -> base_rate -> update through the gated agent — a single "
            "vague sentence yields a complete, committed forecast"
        ),
    )
    onboard_parser.add_argument(
        "--criteria",
        help="Resolution criteria for the question (skips the LLM criteria draft under --auto)",
    )
    onboard_parser.add_argument("--model", help="--auto: model the pipeline stages run on")
    onboard_parser.add_argument("--provider", help="--auto: provider the pipeline stages run on")
    onboard_parser.add_argument(
        "--max-iterations", type=int, default=12, help="--auto: agent tool-calling budget per stage"
    )
    onboard_parser.add_argument(
        "--force-new",
        action="store_true",
        help=(
            "--auto: commit a NEW question even when a strong near-duplicate exists "
            "(default routes the refresh onto the existing question instead of forking a rival)"
        ),
    )
    onboard_parser.add_argument("--json", action="store_true", help="Emit the proposed spec + issues + clarifications as JSON")
    onboard_parser.set_defaults(_forecast_handler=_cmd_onboard)

    list_parser = forecast_sub.add_parser("list", help="List forecast questions")
    list_parser.add_argument("--status", choices=["active", "closed", "resolved", "archived"])
    list_parser.add_argument("--domain")
    list_parser.add_argument("--limit", type=int)
    list_parser.set_defaults(_forecast_handler=_cmd_list)

    next_parser = forecast_sub.add_parser(
        "next",
        help="Rank the book by value-of-information — what should I touch next?",
    )
    next_parser.add_argument("--limit", type=int, default=5, help="How many actions to print (default: 5)")
    next_parser.add_argument("--json", action="store_true", help="Emit the machine-readable ranked actions")
    next_parser.set_defaults(_forecast_handler=_cmd_next)

    search_parser = forecast_sub.add_parser(
        "search",
        help="Search forecast questions without remembering IDs",
    )
    search_parser.add_argument("query", nargs="+")
    search_parser.add_argument(
        "--status",
        choices=["active", "closed", "resolved", "archived", "all"],
        default="active",
        help="Question status to search; default: active",
    )
    search_parser.add_argument("--domain")
    search_parser.add_argument("--topic")
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.add_argument("--json", action="store_true", help="Emit machine-readable search results")
    search_parser.set_defaults(_forecast_handler=_cmd_search)

    show_parser = forecast_sub.add_parser("show", help="Show a forecast question")
    show_parser.add_argument("id")
    show_parser.set_defaults(_forecast_handler=_cmd_show)

    set_decision_parser = forecast_sub.add_parser(
        "set-decision",
        help="Set or revise decision_owner / decision_deadline / action_threshold / update_triggers",
    )
    set_decision_parser.add_argument("id")
    set_decision_parser.add_argument("--decision-owner")
    set_decision_parser.add_argument("--decision-deadline")
    set_decision_parser.add_argument("--action-threshold")
    set_decision_parser.add_argument(
        "--update-trigger",
        dest="update_triggers",
        action="append",
        default=None,
        help=(
            "Repeatable. Replaces existing triggers with the given set. Pass an empty value "
            "with --clear-triggers to remove all."
        ),
    )
    set_decision_parser.add_argument(
        "--clear-triggers",
        action="store_true",
        help="Remove all existing update triggers",
    )
    set_decision_parser.set_defaults(_forecast_handler=_cmd_set_decision)

    update_parser = forecast_sub.add_parser("update", help="Append a forecast snapshot")
    update_parser.add_argument("id")
    update_parser.add_argument("--probability", type=float)
    update_parser.add_argument("--numeric-value", type=float)
    update_parser.add_argument(
        "--distribution-json",
        help="JSON object mapping categorical outcomes to probabilities or distribution parameters such as mean/std",
    )
    update_parser.add_argument(
        "--rationale",
        nargs="+",
        help="Forecast rationale; quotes are optional when it is the last update field",
    )
    update_parser.add_argument("--as-of")
    update_parser.add_argument("--confidence", type=float)
    update_parser.add_argument(
        "--method",
        help=(
            "Ensemble method recorded with the snapshot. With --component-json and no "
            "explicit --probability, 'log_odds_pool' (or 'log_pool') pools components "
            "through the Bayesian toolkit (geometric pooling of odds, respects confident "
            "minorities); 'weighted_ensemble'/'linear' keeps the weighted average."
        ),
    )
    update_parser.add_argument("--component-json", default="{}")
    update_parser.add_argument(
        "--extremize",
        type=float,
        default=None,
        help="Extremization factor (>1 sharpens) applied when pooling components via a Bayesian method",
    )
    update_parser.add_argument(
        "--correlation",
        default=None,
        help="Correlation handling for Bayesian pooling: 'estimate' or a JSON NxN matrix; downweights double-counted sources",
    )
    update_parser.add_argument("--assumption", dest="key_assumptions", action="append", default=[])
    update_parser.add_argument("--assumption-ref", dest="assumption_refs", action="append", default=[])
    update_parser.add_argument("--reference-class-ref", dest="reference_class_refs", action="append", default=[])
    update_parser.add_argument("--evidence-ref", dest="evidence_refs", action="append", default=[])
    update_parser.add_argument("--stale-evidence-days", type=int, default=30)
    update_parser.add_argument("--ack-stale-evidence", action="store_true")
    update_parser.add_argument("--stale-evidence-reason", default=None,
                               help="Why committing on stale evidence is OK (records + clears the stale_evidence_justified WARN).")
    update_parser.add_argument(
        "--require-citations",
        action="store_true",
        help="Require a live forecast to cite at least one evidence/model/reference-class/"
        "source-snapshot/assumption/lesson ref. Opt-in (the soul/protocol nudges citing "
        "evidence); pass it when committing an evidence-backed forecast.",
    )
    update_parser.add_argument("--model-run-ref", dest="model_run_refs", action="append", default=[])
    update_parser.add_argument(
        "--origin",
        dest="forecast_origin",
        choices=["live", "exploratory", "backtest", "imported_baseline"],
        default="live",
        help="'live' commits a scored forecast (formalities enforced); 'exploratory' is a "
        "scratchpad forecast — free of commit-time formalities and not calibration-scored.",
    )
    update_parser.add_argument("--agent-model")
    update_parser.add_argument("--prompt-version")
    update_parser.add_argument("--protocol-version")
    update_parser.add_argument("--toolset-version")
    update_parser.add_argument("--source-snapshot-ref", dest="source_snapshot_refs", action="append", default=[])
    update_parser.add_argument(
        "--reason-up",
        dest="reasons_up",
        action="append",
        default=[],
        help="Repeatable. One concrete reason the probability should be higher.",
    )
    update_parser.add_argument(
        "--reason-down",
        dest="reasons_down",
        action="append",
        default=[],
        help="Repeatable. One concrete reason the probability should be lower.",
    )
    update_parser.add_argument(
        "--change-my-mind",
        dest="change_my_mind",
        action="append",
        default=[],
        help="Repeatable. One observation that would force a material update.",
    )
    update_parser.add_argument(
        "--require-structured-reasoning",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refuse to save a live snapshot unless --reason-up, --reason-down, and "
        "--change-my-mind are all set. On by default; use --no-require-structured-reasoning "
        "(or --origin exploratory) to skip.",
    )
    update_parser.add_argument(
        "--require-decision-readiness",
        action="store_true",
        help=(
            "Refuse to save the snapshot unless the question has decision_owner, "
            "action_threshold, and at least one update_trigger"
        ),
    )
    update_parser.add_argument(
        "--panel-estimates-json",
        dest="panel_estimates_json",
        default=None,
        help=(
            "JSON array of panel estimates (one per perspective). When supplied, "
            "the panel is aggregated to derive the snapshot probability and a "
            "panel_run record is attached to the snapshot."
        ),
    )
    update_parser.add_argument(
        "--panel-estimates-file",
        dest="panel_estimates_file",
        default=None,
        help="Path to a JSON file containing panel estimates",
    )
    update_parser.add_argument(
        "--panel-method",
        dest="panel_method",
        choices=sorted(["trimmed_geomean_odds", "log_odds_pool", "median", "mean"]),
        default="trimmed_geomean_odds",
    )
    update_parser.add_argument(
        "--panel-trim",
        dest="panel_trim",
        type=int,
        default=1,
    )
    update_parser.add_argument(
        "--panel-triggered-by",
        dest="panel_triggered_by",
        default="manual",
    )
    update_parser.add_argument(
        "--require-panel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For a high-impact live forecast, refuse to save unless a panel run is "
        "linked (--panel-run-ref / --panel-estimates-json) or --panel-skipped-reason is "
        "given. On by default; lower-impact first forecasts are only nudged. Use "
        "--no-require-panel (or --origin exploratory) to skip.",
    )
    update_parser.add_argument(
        "--panel-run-ref",
        dest="panel_run_ref",
        default=None,
        help="ID of an already-recorded panel run to link to this snapshot as its "
        "deliberative-panel evidence.",
    )
    update_parser.add_argument(
        "--panel-skipped-reason",
        dest="panel_skipped_reason",
        default=None,
        help="Recorded reason for committing a panel-indicated forecast without a panel "
        "(escape valve for the panel formality).",
    )
    update_parser.add_argument(
        "--outcome-path",
        dest="outcome_paths",
        action="append",
        default=[],
        metavar="OUTCOME=PATH",
        help="Categorical forecasts: name the causal path for an outcome, e.g. "
        "--outcome-path 'Lasher=leads polls + endorsements'. Repeatable. Feeds the "
        "probability-mass audit that flags unearned tail mass.",
    )
    update_parser.add_argument(
        "--require-outcome-paths",
        dest="require_outcome_paths",
        action="store_true",
        help="Categorical live forecasts: refuse to commit when a material outcome holds "
        "mass with no named path (unearned tail mass).",
    )
    update_parser.add_argument("--evidence-cutoff")
    update_parser.add_argument("--backtest-run-id")
    update_parser.add_argument("--calibration-ineligible", action="store_true")
    update_parser.add_argument("--calibration-weight", type=float, default=1.0)
    update_parser.add_argument("--calibration-lesson-ref", dest="calibration_lesson_refs", action="append", default=[])
    update_parser.add_argument("--calibration-adjustment-json", default="{}")
    update_parser.add_argument(
        "--use-active-lessons",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Attach active global/domain/topic/question-type calibration lessons "
            "and apply the measured probability adjustment. ON by default for LIVE "
            "commits only (the pre-adjustment raw_probability is recorded for audit); "
            "backtest/imported commits are NOT auto-adjusted (pass "
            "--use-active-lessons to opt in). Use --no-use-active-lessons to commit "
            "your raw number. Exploratory commits are never adjusted."
        ),
    )
    update_parser.add_argument("--preview", action="store_true", help="Show update preview without writing a snapshot")
    update_parser.set_defaults(_forecast_handler=_cmd_update)

    refresh_parser = forecast_sub.add_parser(
        "refresh",
        help="Pull latest watched-source readings + re-estimate, then auto-commit a new live snapshot",
    )
    refresh_parser.add_argument("id")
    refresh_parser.add_argument(
        "--agent",
        action="store_true",
        help="Run the full LLM update stage instead of the deterministic re-pool",
    )
    refresh_parser.add_argument(
        "--no-commit",
        dest="commit",
        action="store_false",
        default=True,
        help="Preview the re-estimate without importing evidence or committing a snapshot",
    )
    refresh_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias for previewing: fetch + re-estimate but write nothing",
    )
    refresh_parser.add_argument(
        "--carry-forward",
        action="store_true",
        help="Skip the re-pool; carry the prior probability forward (flags need for --agent / manual re-reasoning)",
    )
    refresh_parser.add_argument("--extremize", type=float, default=1.0)
    refresh_parser.add_argument(
        "--correlation",
        help="Pass 'estimate' to correlation-adjust pooling weights when sources overlap",
    )
    refresh_parser.add_argument("--concurrency", type=int, default=4)
    refresh_parser.add_argument("--now")
    refresh_parser.add_argument("--json", action="store_true")
    # --agent delegation reuses the protocol agent runner (forecast agent --stage update).
    refresh_parser.add_argument("--model")
    refresh_parser.add_argument("--provider")
    refresh_parser.add_argument("--max-iterations", type=int, default=12)
    refresh_parser.set_defaults(_forecast_handler=_cmd_refresh)

    freshen_parser = forecast_sub.add_parser(
        "freshen",
        help="Put a forecast on a refresh cadence + ensure the nightly self-check cron (one verb)",
    )
    freshen_parser.add_argument("id", nargs="?", help="Question id (or --all for every active question)")
    freshen_parser.add_argument("--all", action="store_true", help="Freshen every active question")
    freshen_parser.add_argument(
        "--cadence",
        default="daily",
        help="Review cadence (daily/weekly, 'every 2 days', '12h', ...). Default daily.",
    )
    freshen_parser.add_argument("--json", action="store_true")
    freshen_parser.set_defaults(_forecast_handler=_cmd_freshen)

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
    packet_import = import_sub.add_parser("packet", help="Import a JSON forecast export packet")
    packet_import.add_argument("source", help="Path to a JSON packet, or '-' for stdin")
    packet_import.add_argument("--conflict", choices=["error", "skip", "replace"], default="error")
    packet_import.add_argument("--json", action="store_true", help="Print the import summary as JSON")
    packet_import.set_defaults(_forecast_handler=_cmd_import_packet)
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
        "githubrepo",
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
        "imf",
        "census",
        "socrata",
        "ckan",
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
            "githubrepo",
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
            "imf",
            "census",
            "socrata",
            "ckan",
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
            default_claim_type = "estimate" if name in {"fivethirtyeight", "imf", "openmeteo", "airquality"} else "fact"
            adapter.add_argument("--claim-type", choices=sorted(EVIDENCE_CLAIM_TYPES), default=default_claim_type)
            adapter.add_argument("--reliability", type=_parse_rating)
            adapter.add_argument("--relevance", type=_parse_rating)
        if name == "news":
            adapter.add_argument("--keyword", dest="keywords", action="append", default=[], help="Only import RSS/Atom items containing this term; repeatable or comma-separated")
            adapter.add_argument("--exclude-keyword", dest="exclude_keywords", action="append", default=[], help="Skip RSS/Atom items containing this term; repeatable or comma-separated")
            adapter.add_argument("--no-dedupe", dest="dedupe", action="store_false", default=True, help="Disable RSS/Atom item deduplication")
            adapter.add_argument("--materiality", choices=["low", "medium", "high"], help="Expected materiality label to store with imported news metadata")
            adapter.add_argument("--direction", choices=["upward", "downward", "ambiguous"], help="Expected directional impact label to store with imported news metadata")
            adapter.add_argument("--affected-component", dest="affected_components", action="append", default=[], help="Forecast assumption or component affected by matching news; repeatable")
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
        if name == "githubrepo":
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
        if name == "imf":
            adapter.add_argument(
                "--api-base-url",
                default="https://www.imf.org/external/datamapper/api/v1",
                help="Override IMF DataMapper API base URL for tests or private mirrors",
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
        if name == "ckan":
            adapter.add_argument(
                "--api-base-url",
                default="https://{domain}/api/3/action/package_search",
                help="Override CKAN package_search endpoint template for tests or private mirrors",
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

    tournament_parser = forecast_sub.add_parser(
        "tournament",
        help="Import a resolved tournament export as a replay benchmark",
    )
    tournament_parser.add_argument("source")
    tournament_parser.add_argument("--name")
    tournament_parser.add_argument("--description")
    tournament_parser.add_argument("--limit", type=int, default=100)
    tournament_parser.set_defaults(
        _forecast_handler=_cmd_import_adapter,
        import_kind="tournament",
        question_id=None,
        title=None,
        resolution_criteria=None,
        close_time=None,
        resolution_time=None,
        baseline_probability=None,
        baseline_type="imported",
        as_of=None,
    )

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
    research_parser.add_argument("--reliability", type=_parse_rating)
    research_parser.add_argument("--relevance", type=_parse_rating)
    research_parser.add_argument("--stance", type=_parse_stance, default="context")
    research_parser.set_defaults(_forecast_handler=_cmd_research)

    base_rate_parser = forecast_sub.add_parser("base-rate", help="Store a reference-class base-rate estimate")
    base_rate_parser.add_argument("id")
    base_rate_parser.add_argument("--name")
    base_rate_parser.add_argument("--inclusion-criteria")
    base_rate_parser.add_argument("--exclusion-criteria", default="")
    base_rate_parser.add_argument("--base-rate", type=float)
    base_rate_parser.add_argument("--uncertainty", type=float)
    base_rate_parser.add_argument("--source-ref", dest="source_refs", action="append", default=[])
    base_rate_parser.add_argument("--check-cadence")
    base_rate_parser.add_argument("--notes")
    base_rate_parser.set_defaults(_forecast_handler=_cmd_base_rate)

    model_parser = forecast_sub.add_parser("model", help="Record a probabilistic model run (or `model build <ref>` to build a Market Model as a forecast leg)")
    model_parser.add_argument(
        "id",
        help="A forecast question id/name — OR the literal 'build' to build a deterministic Market Model as a forecast leg.",
    )
    model_parser.add_argument(
        "build_question",
        nargs="?",
        help="With `build`: the question ref (id or free-text quant question) to build a Market Model for.",
    )
    model_parser.add_argument("--depth", choices=["quick", "standard", "deep", "ultra"], help="model build: research depth")
    model_parser.add_argument("--analysis-type", dest="analysis_type", help="model build: pin a model family (overrides the recommender)")
    model_parser.add_argument("--type", dest="model_type")
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

    bayes_parser = forecast_sub.add_parser(
        "bayes",
        help="Bayesian scratchpad: LR updates, log-odds pooling, polls→prob, de-vig, sensitivity, forecast-diff",
    )
    bayes_parser.add_argument(
        "bayes_action",
        nargs="?",
        help=(
            "Toolkit routine: lr_update, decompose_update, combine, evidence_weight, "
            "evidence_cluster, blend_base_rates, poll_to_prob, polls, devig, "
            "normalize_market, combine_markets, sensitivity, forecast_diff, "
            "conditional_chain (omit to list available actions)"
        ),
    )
    bayes_parser.add_argument(
        "--input", "-i", dest="bayes_input", default=None,
        help="JSON object payload for the chosen action",
    )
    bayes_parser.add_argument(
        "--input-file", dest="bayes_input_file", default=None,
        help="Path to a JSON payload file (alternative to --input)",
    )
    bayes_parser.add_argument(
        "--json", dest="bayes_json", action="store_true",
        help="Emit machine-readable JSON (default prints a human rationale)",
    )
    bayes_parser.set_defaults(_forecast_handler=_cmd_bayes)

    panel_parser = forecast_sub.add_parser(
        "panel",
        help=(
            "Run / aggregate / inspect a multi-perspective forecast panel "
            "(outside, inside, market, red-team, sanity)"
        ),
    )
    panel_sub = panel_parser.add_subparsers(dest="panel_command")

    panel_perspectives_parser = panel_sub.add_parser(
        "perspectives",
        help="Print the system+user prompt for each panel perspective",
    )
    panel_perspectives_parser.add_argument("question_id", nargs="?")
    panel_perspectives_parser.add_argument(
        "--perspective",
        dest="perspectives",
        action="append",
        default=[],
        help=(
            "Subset of perspectives to print (repeatable). Defaults to all five: "
            "outside, inside, market, red_team, sanity."
        ),
    )
    panel_perspectives_parser.add_argument("--json", action="store_true")
    panel_perspectives_parser.set_defaults(_forecast_handler=_cmd_panel_perspectives)

    panel_aggregate_parser = panel_sub.add_parser(
        "aggregate",
        help="Aggregate a JSON array of perspective estimates without saving",
    )
    panel_aggregate_parser.add_argument(
        "--input",
        "-i",
        dest="panel_input",
        default=None,
        help="JSON array of estimate objects",
    )
    panel_aggregate_parser.add_argument(
        "--input-file",
        dest="panel_input_file",
        default=None,
    )
    panel_aggregate_parser.add_argument(
        "--method",
        choices=sorted(["trimmed_geomean_odds", "log_odds_pool", "median", "mean"]),
        default="trimmed_geomean_odds",
    )
    panel_aggregate_parser.add_argument(
        "--trim",
        type=int,
        default=1,
        help="Drop this many highest + lowest estimates before pooling (default 1)",
    )
    panel_aggregate_parser.add_argument("--json", action="store_true")
    panel_aggregate_parser.set_defaults(_forecast_handler=_cmd_panel_aggregate)

    panel_record_parser = panel_sub.add_parser(
        "record",
        help="Aggregate panel estimates AND save the panel_run for a question",
    )
    panel_record_parser.add_argument("question_id")
    panel_record_parser.add_argument(
        "--input", "-i", dest="panel_input", default=None,
        help="JSON array of estimate objects",
    )
    panel_record_parser.add_argument("--input-file", dest="panel_input_file", default=None)
    panel_record_parser.add_argument(
        "--method",
        choices=sorted(["trimmed_geomean_odds", "log_odds_pool", "median", "mean"]),
        default="trimmed_geomean_odds",
    )
    panel_record_parser.add_argument("--trim", type=int, default=1)
    panel_record_parser.add_argument(
        "--triggered-by",
        choices=["manual", "first_forecast", "impact_high", "force"],
        default="manual",
    )
    panel_record_parser.add_argument("--snapshot-id")
    panel_record_parser.add_argument(
        "--track-record-weights", action="store_true",
        help=(
            "Weight perspectives by their measured Brier edge over the committed "
            "aggregate (resolved questions only; advisory weights from `forecast "
            "track-record`). Estimates that already carry an explicit weight keep it."
        ),
    )
    panel_record_parser.set_defaults(_forecast_handler=_cmd_panel_record)

    panel_show_parser = panel_sub.add_parser(
        "show",
        help="Render a stored panel_run",
    )
    panel_show_parser.add_argument("panel_run_id")
    panel_show_parser.add_argument("--json", action="store_true")
    panel_show_parser.set_defaults(_forecast_handler=_cmd_panel_show)

    panel_list_parser = panel_sub.add_parser(
        "list",
        help="List panel_runs (optionally scoped to a question)",
    )
    panel_list_parser.add_argument("question_id", nargs="?")
    panel_list_parser.add_argument("--limit", type=int, default=20)
    panel_list_parser.set_defaults(_forecast_handler=_cmd_panel_list)

    quorum_parser = forecast_sub.add_parser(
        "quorum",
        help=(
            "Run a model-diverse forecast quorum (Fusion-style): dispatch a "
            "panel of models, then a judge synthesizes a verdict. Subcommands: "
            "`quorum <id>` (run), `quorum status [run-id]`, `quorum config "
            "[set k v]`, `quorum default on|off`."
        ),
    )
    quorum_parser.add_argument(
        "target",
        nargs="?",
        help="Question id to forecast, or one of: status | config | default.",
    )
    quorum_parser.add_argument(
        "rest",
        nargs="*",
        help="Sub-arguments (run-id for status; key value for config set; on/off for default).",
    )
    quorum_parser.add_argument(
        "--preset",
        choices=sorted(("frontier", "budget", "self", "wide")),
        help="Panel preset (overrides the configured default). 'wide' is the "
        "opt-in ~10-draw variance-reduction panel (AIA P1.4).",
    )
    quorum_parser.add_argument(
        "--models",
        help="Comma-separated OpenRouter model ids (overrides the preset).",
    )
    quorum_parser.add_argument("--judge", help="Judge model id (overrides the preset default).")
    quorum_parser.add_argument(
        "--pool",
        dest="pool_method",
        choices=sorted({"trimmed_geomean_odds", "log_odds_pool", "median", "mean"}),
        help="Pooling method for the panel ('mean' is the convexity baseline; "
        "the default stays trimmed_geomean_odds).",
    )
    quorum_parser.add_argument("--trim", type=int, help="Drop this many extremes before pooling.")
    quorum_parser.add_argument("--samples", type=int, help="Self-fusion sample count (self preset).")
    quorum_parser.add_argument(
        "--trials",
        type=int,
        help="Trials per panelist (BLF multi-trial). Each seat is drawn this many "
        "times and pooled as a variance-shrunk logit mean toward the anchor; "
        "default is impact-driven (high-impact 3, else 1).",
    )
    quorum_parser.add_argument(
        "--attach-snapshot",
        dest="attach_snapshot",
        help="Attach the resulting panel run to an existing snapshot id.",
    )
    quorum_parser.add_argument("--triggered-by", dest="triggered_by", default="quorum")
    quorum_parser.add_argument(
        "--supervisor-search",
        dest="supervisor_search",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Live agentic-supervisor fresh-search loop (AIA P1.1): when the judge "
        "flags an unresolved crux it runs a real bounded web/news search and "
        "re-synthesises once on the fresh evidence. DEFAULT ON for live runs "
        "(leak-guarded off for a historical evidence_cutoff); pass "
        "--no-supervisor-search to disable this run, or set quorum.supervisor_search "
        "= false fleet-wide.",
    )
    quorum_parser.add_argument(
        "--scope",
        choices=sorted(("high_impact", "always", "first_only")),
        help="For `quorum default`: which indicated panels get a quorum.",
    )
    quorum_parser.add_argument(
        "--wait",
        action="store_true",
        help="Run synchronously and print the result (default: background job + run-id).",
    )
    quorum_parser.add_argument(
        "--seed", type=int, default=0,
        help="Bootstrap seed for `quorum bench` (deterministic).",
    )
    quorum_parser.add_argument(
        "--draws", type=int,
        help="Bootstrap resamples per ensemble size for `quorum bench` (default 500).",
    )
    quorum_parser.add_argument(
        "--delphi",
        action="store_true",
        help="Add one anonymous Delphi-style revision round (shorthand for "
        "--delphi-rounds 1). Default OFF (byte-identical baseline).",
    )
    quorum_parser.add_argument(
        "--delphi-rounds",
        dest="delphi_rounds",
        type=int,
        choices=(0, 1),
        help="Number of Delphi revision rounds (v1 supports 0 or 1). Overrides "
        "quorum.delphi_rounds.",
    )
    quorum_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    quorum_parser.set_defaults(_forecast_handler=_cmd_quorum)

    rerun_parser = forecast_sub.add_parser(
        "rerun",
        help=(
            "Mass LLM re-run: run the FULL formal forecast flow (fresh research + "
            "VOI audit + base rate + gated commit + auto-quorum where indicated) for "
            "explicit question ids, DETACHED so a keypress can start many multi-minute "
            "sessions. Subcommands: `rerun <id> [<id> ...]` (start), `rerun status "
            "<run-id>`."
        ),
    )
    rerun_parser.add_argument(
        "ids",
        nargs="*",
        help="Question ids to reforecast; or `status <run-id>` to poll a run.",
    )
    rerun_parser.add_argument(
        "--agent",
        action="store_true",
        help="Explicit opt-in flag (the mass re-run is always the LLM agent flow); "
        "accepted for parity with `cycle run --agent`.",
    )
    rerun_parser.add_argument("--model", help="Model id for the reforecast agent.")
    rerun_parser.add_argument("--provider", help="Provider for the reforecast agent.")
    rerun_parser.add_argument(
        "--max-iterations", dest="max_iterations", type=int, default=12,
        help="Max agent iterations per question (default 12).",
    )
    rerun_parser.add_argument(
        "--wait",
        action="store_true",
        help="Run synchronously and print the result (default: background job + run-id).",
    )
    rerun_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    rerun_parser.set_defaults(_forecast_handler=_cmd_rerun)

    apikey_parser = forecast_sub.add_parser(
        "api-key",
        help="Manage data-provider API keys (FRED, EIA, Firecrawl, Exa, …). Writes to the user .env and activates immediately.",
    )
    apikey_sub = apikey_parser.add_subparsers(dest="apikey_command")
    apikey_list = apikey_sub.add_parser("list", help="List known providers and whether a key is currently set (redacted).")
    apikey_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    apikey_list.set_defaults(_forecast_handler=_cmd_apikey_list)
    apikey_show = apikey_sub.add_parser("show", help="Show one provider's status (redacted).")
    apikey_show.add_argument("provider")
    apikey_show.add_argument("--json", action="store_true")
    apikey_show.set_defaults(_forecast_handler=_cmd_apikey_show)
    apikey_set = apikey_sub.add_parser("set", help="Persist a key to the user .env and activate it (`forecast api-key set fred <key>`).")
    apikey_set.add_argument("provider")
    apikey_set.add_argument("value", nargs="?", help="The key value (or, for kalshi, the access key id).")
    apikey_set.add_argument(
        "--from-stdin", action="store_true",
        help="Read the key value from stdin (recommended in shared terminals — keeps the key out of shell history).",
    )
    apikey_set.add_argument(
        "--pem-file",
        help="Kalshi only: path to the RSA private key PEM (streaming handshake). The PEM is copied 0600 into the workspace.",
    )
    apikey_set.add_argument(
        "--pem-stdin", action="store_true",
        help="Kalshi only: read the PEM body from stdin instead of --pem-file.",
    )
    apikey_set.set_defaults(_forecast_handler=_cmd_apikey_set)
    apikey_unset = apikey_sub.add_parser("unset", help="Remove a provider's key from .env and the current process.")
    apikey_unset.add_argument("provider")
    apikey_unset.set_defaults(_forecast_handler=_cmd_apikey_unset)
    apikey_parser.set_defaults(_forecast_handler=_cmd_apikey_default)

    config_parser = forecast_sub.add_parser(
        "config",
        help="Inspect the layered runtime configuration (typed loader + config doctor).",
    )
    config_sub = config_parser.add_subparsers(dest="config_command")
    config_doctor = config_sub.add_parser(
        "doctor",
        help="Report unknown/typo vars, defaults in effect, secret presence, "
        "file-vs-env conflicts, and the Kalshi two-var trap (read-only).",
    )
    config_doctor.add_argument("--json", action="store_true", help="Emit the machine-readable report JSON.")
    config_doctor.set_defaults(_forecast_handler=_cmd_config_doctor)
    config_parser.set_defaults(_forecast_handler=_cmd_config_doctor)

    protocol_parser = forecast_sub.add_parser("protocol", help="Render a forecast-stage agent protocol prompt")
    protocol_parser.add_argument("id")
    protocol_parser.add_argument("--stage", choices=sorted(PROTOCOL_STAGES), default="update")
    protocol_parser.add_argument("--json", action="store_true")
    protocol_parser.set_defaults(_forecast_handler=_cmd_protocol)

    pipeline_parser = forecast_sub.add_parser(
        "pipeline",
        help="Show the guided forecasting loop for a question (which stages are done, what is next)",
    )
    pipeline_parser.add_argument("id")
    pipeline_parser.add_argument(
        "--stage",
        choices=sorted(PROTOCOL_STAGES),
        default=None,
        help="Render this stage's protocol prompt. Advancing to 'update' is refused until "
        "research+base_rate have produced ledger artifacts (override with --force).",
    )
    pipeline_parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the pipeline sequencing gate (e.g. render the update stage early).",
    )
    pipeline_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Pull latest watched-source readings + re-estimate + auto-commit, then render the post-refresh status.",
    )
    pipeline_parser.add_argument("--json", action="store_true")
    pipeline_parser.set_defaults(_forecast_handler=_cmd_pipeline)

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
    reference_relink = reference_sub.add_parser(
        "relink",
        help="Re-attach a question's EXISTING reference classes to its current snapshot's refs (the orphaned-anchor fix; dry-run by default)",
    )
    reference_relink.add_argument(
        "--apply", action="store_true",
        help="Stamp the existing class ids onto each orphaned current snapshot (default is a dry-run preview).",
    )
    reference_relink.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    reference_relink.set_defaults(_forecast_handler=_cmd_reference_class_relink)

    crux_parser = forecast_sub.add_parser("crux", help="Manage per-forecast crux variables (the decisive inputs)")
    crux_sub = crux_parser.add_subparsers(dest="crux_command")
    crux_add = crux_sub.add_parser("add", help="Register a decisive crux variable for a forecast")
    crux_add.add_argument("question", help="row number, id, or search words for the question")
    crux_add.add_argument("--variable", required=True, help="the decisive variable the resolution hinges on")
    crux_add.add_argument(
        "--role", dest="roles", action="append", default=[], choices=sorted(WATCH_SOURCE_ROLES),
        help="preferred source role that would satisfy this crux (repeatable)",
    )
    crux_add.add_argument("--materiality", choices=sorted(CRUX_MATERIALITY), default="medium")
    crux_add.add_argument("--status", choices=sorted(CRUX_STATUS), default="missing")
    crux_add.add_argument("--notes")
    crux_add.set_defaults(_forecast_handler=_cmd_crux_add)
    crux_list = crux_sub.add_parser("list", help="List a forecast's crux variables")
    crux_list.add_argument("question")
    crux_list.set_defaults(_forecast_handler=_cmd_crux_list)
    crux_status_p = crux_sub.add_parser("status", help="Update a crux's evidence status")
    crux_status_p.add_argument("crux_id")
    crux_status_p.add_argument("status", choices=sorted(CRUX_STATUS))
    crux_status_p.set_defaults(_forecast_handler=_cmd_crux_status)
    crux_backfill = crux_sub.add_parser(
        "backfill",
        help="Promote cruxes trapped in existing panel runs into question_cruxes (dry-run by default)",
    )
    crux_backfill.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the promoted cruxes (default is a dry-run preview).",
    )
    crux_backfill.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    crux_backfill.set_defaults(_forecast_handler=_cmd_crux_backfill)

    # Per-candidate vote-share intervals (P2): propose intervals for live share boards
    # from their existing panel/model artifacts (dry-run by default).
    intervals_parser = forecast_sub.add_parser("intervals", help="Manage per-candidate vote-share intervals")
    intervals_sub = intervals_parser.add_subparsers(dest="intervals_command")
    intervals_backfill = intervals_sub.add_parser(
        "backfill",
        help="Propose per-candidate intervals for live vote-share boards from their panel/model artifacts (dry-run by default)",
    )
    intervals_backfill.add_argument(
        "--dry-run", action="store_true",
        help="Preview the proposed intervals + counts without writing (this is the default).",
    )
    intervals_backfill.add_argument(
        "--apply", action="store_true",
        help="Stamp the proposed intervals onto each current snapshot's metadata (default is a dry-run preview).",
    )
    intervals_backfill.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    intervals_backfill.set_defaults(_forecast_handler=_cmd_intervals_backfill)

    evidence_map_parser = forecast_sub.add_parser("evidence-map", help="Show the crux evidence map for a forecast")
    evidence_map_parser.add_argument("question", help="row number, id, or search words for the question")
    evidence_map_parser.add_argument("--json", action="store_true")
    evidence_map_parser.set_defaults(_forecast_handler=_cmd_evidence_map)

    evidence_parser = forecast_sub.add_parser("evidence", help="Manage evidence items")
    evidence_sub = evidence_parser.add_subparsers(dest="evidence_command")
    evidence_add = evidence_sub.add_parser("add", help="Add evidence to a forecast question")
    evidence_add.add_argument("id")
    evidence_add.add_argument("source_or_note", nargs="?")
    evidence_add.add_argument("--source", dest="source_or_note_option")
    evidence_add.add_argument("--claim", default="")
    evidence_add.add_argument("--claim-type", choices=sorted(EVIDENCE_CLAIM_TYPES), default="fact")
    evidence_add.add_argument("--summary", default="")
    evidence_add.add_argument("--url", "--source-url", dest="source_url")
    evidence_add.add_argument("--source-name")
    evidence_add.add_argument("--source-type")
    evidence_add.add_argument("--published-at")
    evidence_add.add_argument("--available-at")
    evidence_add.add_argument("--reliability", type=_parse_rating)
    evidence_add.add_argument("--relevance", type=_parse_rating)
    evidence_add.add_argument("--stance", type=_parse_stance, default="context")
    evidence_add.add_argument("--snapshot-path")
    evidence_add.add_argument("--not-admissible-for-backtests", action="store_true")
    evidence_add.set_defaults(_forecast_handler=_cmd_evidence_add)
    evidence_list = evidence_sub.add_parser("list", help="List evidence for a forecast question")
    evidence_list.add_argument("id")
    evidence_list.set_defaults(_forecast_handler=_cmd_evidence_list)

    resolve_parser = forecast_sub.add_parser("resolve", help="Record a forecast resolution")
    resolve_parser.add_argument("id")
    resolve_parser.add_argument("--outcome", required=True)
    resolve_parser.add_argument("--source", "--resolution-source", dest="resolution_source")
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
        "--confirmed",
        dest="resolution_status",
        action="store_const",
        const="confirmed",
        help="Alias for --status confirmed",
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
    resolve_parser.add_argument(
        "--auto-score",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Automatically score the current live snapshot on a confirmed, criteria-satisfied resolution (default on; --no-auto-score to defer).",
    )
    resolve_parser.set_defaults(_forecast_handler=_cmd_resolve)

    score_parser = forecast_sub.add_parser("score", help="Score the current forecast snapshot")
    score_parser.add_argument("id")
    score_parser.add_argument("--force", action="store_true")
    score_parser.add_argument(
        "--baselines",
        action="store_true",
        help="Also score imported market/crowd/baseline comparisons without changing the current forecast",
    )
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
    postmortem_parser.add_argument(
        "--failure-class",
        choices=sorted(FAILURE_CLASSES),
        help=(
            "Dominant failure mode. 'noise' means the miss was within expected error of a "
            "calibrated forecast; the others mark reusable lessons for domain error profiles."
        ),
    )
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
    lesson_synth = lesson_sub.add_parser(
        "synthesize",
        help="Derive signed over/under-confidence lessons from resolved forecasts (FDR-gated; advisory by default)",
    )
    lesson_synth.add_argument("--scope", default="all", help="'all', 'global', 'domain', or a specific domain name")
    lesson_synth.add_argument("--since", help="Only count resolutions on/after this ISO date (regime cutoff)")
    lesson_synth.add_argument("--recency-halflife", type=float, dest="recency_halflife_days", help="Exponential recency half-life (days)")
    lesson_synth.add_argument(
        "--mechanical",
        action="store_true",
        help="Opt in to bounded numeric logit-scale nudges (OFF by default → advisory text only)",
    )
    lesson_synth.add_argument("--no-activate", action="store_true", help="Leave every synthesized lesson tentative")
    lesson_synth.add_argument("--dry-run", action="store_true", help="Measure and decide without writing any lesson")
    lesson_synth.set_defaults(_forecast_handler=_cmd_lesson_synthesize)

    lessons_parser = forecast_sub.add_parser("lessons", help="List calibration lessons")
    lessons_parser.add_argument("--scope-type")
    lessons_parser.add_argument("--scope-ref")
    lessons_parser.add_argument("--active", action="store_true")
    lessons_parser.set_defaults(_forecast_handler=_cmd_lesson_list)
    lessons_sub = lessons_parser.add_subparsers(dest="lessons_command")
    lessons_audit = lessons_sub.add_parser("audit", help="Per-lesson coverage: is each learning actually being used? (in-scope / applied / dormant)")
    lessons_audit.add_argument("--json", action="store_true")
    lessons_audit.set_defaults(_forecast_handler=_cmd_lessons_audit)
    lessons_apply = lessons_sub.add_parser("apply", help="Compile a lesson into an enforceable hook rule (auto-detects the enforcement pattern)")
    lessons_apply.add_argument("lesson_id")
    lessons_apply.add_argument("--severity", choices=["warn", "error"], default="warn", help="WARN (observe, default) or ERROR (blocks at commit)")
    lessons_apply.set_defaults(_forecast_handler=_cmd_lessons_apply)

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
    resolver_rule = resolver_sub.add_parser("rule", help="Attach a metric-threshold resolution rule (propose from an ingested source metric)")
    resolver_rule.add_argument("question", help="row number, id, or search words for the question")
    resolver_rule.add_argument("--field", required=True, help="parsed source field to read (e.g. segment_revenue)")
    resolver_rule.add_argument("--comparator", required=True, choices=[">=", ">", "<=", "<", "==", "!="])
    resolver_rule.add_argument("--threshold", required=True, type=float)
    resolver_rule.add_argument("--source-role", default="resolver", choices=sorted(WATCH_SOURCE_ROLES))
    resolver_rule.set_defaults(_forecast_handler=_cmd_resolver_rule)
    resolver_propose = resolver_sub.add_parser("propose", help="Propose a resolution from the latest ingested source value (no commit)")
    resolver_propose.add_argument("question", help="row number, id, or search words for the question")
    resolver_propose.add_argument("--json", action="store_true")
    resolver_propose.set_defaults(_forecast_handler=_cmd_resolver_propose)
    resolver_propose_due = resolver_sub.add_parser("propose-due", help="Run all resolution rules + raise confirm-me alerts for determinable resolutions (autonomy)")
    resolver_propose_due.add_argument("--dry-run", action="store_true", help="Preview proposals without raising alerts")
    resolver_propose_due.set_defaults(_forecast_handler=_cmd_resolver_propose_due)

    calibration_parser = forecast_sub.add_parser("calibration", help="Show calibration summary (add `status` for the readiness cockpit)")
    calibration_parser.add_argument(
        "mode", nargs="?", choices=["summary", "status"], default="summary",
        help="`status` = the readiness cockpit (calibration + live track record + readiness gaps + next actions)",
    )
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
    calibration_parser.add_argument(
        "--operator",
        action="store_true",
        help="Show the OPERATOR's own calibration (practice/drill estimates) instead of the system's",
    )
    calibration_parser.add_argument(
        "--window-days",
        type=int,
        dest="operator_window_days",
        help="Operator view: restrict to estimates scored within the trailing N days",
    )
    calibration_parser.add_argument(
        "--bias",
        action="store_true",
        help="Show the SIGNED over/under-confidence view (per scope: SCE, CI, status) instead of the unsigned summary",
    )
    calibration_parser.add_argument("--since", help="Bias view: only count resolutions on/after this ISO date")
    calibration_parser.add_argument(
        "--recency-halflife", type=float, dest="recency_halflife_days", help="Bias view: recency half-life (days)"
    )
    calibration_parser.add_argument(
        "--hierarchical",
        action="store_true",
        help="Hierarchical-Platt validation: held-out per-cohort Brier, global vs "
        "per-cohort-intercept (BLF A4). The flip evidence for FORECAST_HIERARCHICAL_CALIBRATION.",
    )
    calibration_parser.add_argument(
        "--min-cohort-n", type=int, dest="min_cohort_n",
        help="Hierarchical view: min resolved rows before a cohort earns an offset (default 40).",
    )
    calibration_parser.add_argument(
        "--folds", type=int, default=5, help="Hierarchical view: held-out CV folds (default 5).",
    )
    calibration_parser.add_argument(
        "--split-by-venue", action="store_true", dest="split_by_venue",
        help="Hierarchical view: refine cohorts to <origin>:<venue> where the data exists.",
    )
    calibration_parser.add_argument(
        "--json", action="store_true", dest="as_json", help="Emit the raw report as JSON.",
    )
    calibration_parser.set_defaults(_forecast_handler=_cmd_calibration)

    # Measurement-honesty surface: the by-cohort scoreboard, the pathological-row
    # audit, and the two GATED remediation actions (artifact quarantine + CRPS
    # backfill + continuous-miss postmortem stubs). Every action defaults to a
    # dry-run report; `--apply` performs the gated write.
    scores_parser = forecast_sub.add_parser(
        "scoreboard", help="Cohort scoreboard, pathological-row audit, and gated score remediation"
    )
    scores_sub = scores_parser.add_subparsers(dest="scoreboard_command")

    scores_board = scores_sub.add_parser("board", help="Print the by-cohort scoreboard (never a pooled headline)")
    scores_board.set_defaults(_forecast_handler=_cmd_scores_board)

    scores_audit_p = scores_sub.add_parser("audit", help="Classify pathological score rows (Brier=1.0 / |log|>10)")
    scores_audit_p.add_argument("--json", action="store_true", help="Emit the machine-readable audit JSON")
    scores_audit_p.set_defaults(_forecast_handler=_cmd_scores_audit)

    scores_quar = scores_sub.add_parser("quarantine", help="Quarantine provable ingestion artifacts (dry-run unless --apply)")
    scores_quar.add_argument("--apply", action="store_true", help="Perform the gated write (default: dry-run report)")
    scores_quar.set_defaults(_forecast_handler=_cmd_scores_quarantine)

    scores_crps = scores_sub.add_parser("backfill-crps", help="Score the distribution/numeric class with CRPS (dry-run unless --apply)")
    scores_crps.add_argument("--apply", action="store_true", help="Perform the gated rescore (default: dry-run report)")
    scores_crps.set_defaults(_forecast_handler=_cmd_scores_backfill_crps)

    scores_pm = scores_sub.add_parser("postmortem-misses", help="Create postmortem STUBS for continuous misses (dry-run unless --apply)")
    scores_pm.add_argument("--apply", action="store_true", help="Create the stubs (default: dry-run report)")
    scores_pm.add_argument("--min-crps", type=float, default=0.0, help="Only stub misses with CRPS at or above this")
    scores_pm.set_defaults(_forecast_handler=_cmd_scores_postmortem_misses)

    scores_parser.set_defaults(_forecast_handler=_cmd_scores_board)

    # Operator practice loop (R2): train the HUMAN, Tetlock-style.
    practice_parser = forecast_sub.add_parser(
        "practice",
        help="Record YOUR OWN estimate for a question (scored when it resolves) — Tetlock practice",
    )
    practice_parser.add_argument("question_ref", help="Question id or free-text name")
    practice_parser.add_argument("--note", help="Optional rationale for your number")
    practice_parser.set_defaults(_forecast_handler=_cmd_practice)

    drill_parser = forecast_sub.add_parser(
        "drill",
        help="Practice on already-RESOLVED binary questions and get scored instantly",
    )
    drill_parser.add_argument("--n", type=int, default=5, help="How many questions to drill (default 5)")
    drill_parser.add_argument("--domain", help="Restrict to a domain (desk corpus only)")
    drill_parser.add_argument(
        "--corpus",
        choices=("desk", "forecastbench"),
        default=None,
        help=(
            "Which corpus to drill. 'desk' replays YOUR resolved questions; "
            "'forecastbench' replays obscure resolved market questions you've "
            "never seen (deliberate practice, no recall). Default: auto — "
            "forecastbench when its dataset is cached and the desk has too few "
            "never-drilled questions, else desk."
        ),
    )
    drill_parser.add_argument(
        "--date",
        help=(
            "ForecastBench question-set date for --corpus forecastbench "
            "(e.g. 2026-06-07, or 'latest' to fetch the newest). Defaults to the "
            "newest locally-cached set."
        ),
    )
    drill_parser.set_defaults(_forecast_handler=_cmd_drill)

    complementarity_parser = forecast_sub.add_parser(
        "complementarity",
        help="AIA P1.3 — fitted convex market+LLM Brier-minimizing blend + LOO additive value (read-only)",
    )
    complementarity_parser.add_argument(
        "--origin",
        dest="forecast_origin",
        default="live",
        choices=["live", "backtest", "imported_baseline"],
        help="Which resolved score_records to fit the LLM/agent side from (default: live)",
    )
    complementarity_parser.add_argument(
        "--min-sample",
        type=int,
        default=30,
        dest="min_sample",
        help="Minimum resolved market+LLM pairs before a weight is fitted (default: 30)",
    )
    complementarity_parser.add_argument("--json", action="store_true", help="Emit the raw report as JSON")
    complementarity_parser.set_defaults(_forecast_handler=_cmd_complementarity)

    ablation_parser = forecast_sub.add_parser(
        "ablation",
        help="AIA P2.2 — 2x2 search/judge Brier ablation over resolved binary backtest cases (read-only)",
    )
    ablation_parser.add_argument("--json", action="store_true", help="Emit the raw report as JSON")
    ablation_parser.set_defaults(_forecast_handler=_cmd_ablation)

    market_nightly_parser = forecast_sub.add_parser(
        "market-nightly",
        help="AIA P2.1 — foreknowledge-proof live benchmark: sample OPEN markets, forecast NOW, score on close",
    )
    mn_sub = market_nightly_parser.add_subparsers(dest="market_nightly_command")
    mn_sample = mn_sub.add_parser(
        "sample",
        help="Sample currently-OPEN markets (close STRICTLY in the future) from a markets JSON file and record pending entries (explicit/opt-in; never hits a live API)",
    )
    mn_sample.add_argument(
        "--markets-json",
        required=True,
        dest="markets_json",
        help="Path to a JSON array of market dicts (id, probability/yes_price, close_time/resolution_time, ...). No network is contacted.",
    )
    mn_sample.add_argument("--as-of", dest="as_of", default=None, help="Forecast instant (default: now). The invariant is close STRICTLY > as_of.")
    mn_sample.add_argument("-n", "--count", type=int, default=10, dest="count", help="Max markets to sample (default: 10)")
    mn_sample.add_argument("--seed", type=int, default=0, dest="rng_seed", help="Seed for the deterministic pick (default: 0)")
    mn_sample.add_argument(
        "--agent-prob",
        type=float,
        default=None,
        dest="agent_prob",
        help="Constant agent P(yes) for every sampled market (offline; for piloting the loop without an LLM call).",
    )
    mn_sample.add_argument(
        "--agent-prob-field",
        default=None,
        dest="agent_prob_field",
        help="Read each market's agent P(yes) from this field in the market dict (offline; no LLM call).",
    )
    mn_sample.add_argument("--json", action="store_true", help="Emit the run record as JSON")
    mn_sample.set_defaults(_forecast_handler=_cmd_market_nightly_sample)

    mn_run = mn_sub.add_parser(
        "run",
        help=(
            "LIVE proof: fetch currently-OPEN markets from a source adapter, forecast "
            "each NOW with the SEARCH-ENABLED informed agent (web search ON — the "
            "legitimate live path, NOT closed-book), and record agent-vs-market. The "
            "market-hidden ForecastBench result proved the closed-book LLM has NO "
            "intrinsic edge; the only way to beat the market is fresh information, "
            "provable ONLY forward (searching a resolved question leaks the answer)."
        ),
    )
    mn_run.add_argument("-n", "--count", type=int, default=10, dest="count", help="Max open markets to sample + forecast (default: 10).")
    mn_run.add_argument("--source", default="manifold", help="Open-market source adapter (manifold|metaculus|...). Default: manifold.")
    mn_run.add_argument("--model", default=None, help="Agent model id (overrides the resolved active model).")
    mn_run.add_argument(
        "--research-arm",
        dest="research_arm",
        choices=["plain", "voi", "both"],
        default=None,
        help=(
            "A/B research arm (default: config forecasting.market_nightly.research_arm, "
            "itself 'plain'). plain = the plain agent-protocol packet (the existing "
            "accrued record); voi = the research-disciplined packet (VOI research plan + "
            "adequacy floor); both = forecast EACH sampled market TWICE, once per arm "
            "(2x LLM calls) recording two pendings, so the voi-vs-plain lift is paired "
            "and attributable in `report`."
        ),
    )
    mn_run.add_argument("--seed", type=int, default=0, dest="rng_seed", help="Deterministic sampling seed (default: 0).")
    mn_run.add_argument("--max-iterations", type=int, default=None, dest="max_iterations", help="Agent tool-calling budget per market.")
    mn_run.add_argument(
        "--parallel",
        type=int,
        default=1,
        dest="parallel",
        help=(
            "Bounded concurrency over the per-market agent forecasts (default: 1 = "
            "sequential). N>1 forecasts up to N markets at once (each gets its own "
            "isolated agent); ledger writes stay serialized."
        ),
    )
    mn_run.add_argument("--json", action="store_true", help="Emit the run record as JSON.")
    mn_run.set_defaults(_forecast_handler=_cmd_market_nightly_run)

    mn_score = mn_sub.add_parser("score", help="Score any pending entry whose market has since resolved (reuses the ledger scoring machinery)")
    mn_score.add_argument("--now", default=None, help="Scoring instant (default: now)")
    mn_score.add_argument("--json", action="store_true", help="Emit the result as JSON")
    mn_score.set_defaults(_forecast_handler=_cmd_market_nightly_score)

    mn_report = mn_sub.add_parser("report", help="Read-only roll-up: pending/scored counts + paired agent-vs-market edge")
    mn_report.add_argument("--json", action="store_true", help="Emit the report as JSON")
    mn_report.set_defaults(_forecast_handler=_cmd_market_nightly_report)

    edge_parser = forecast_sub.add_parser(
        "edge",
        help=(
            "UPGRADE 2 — the deviation ledger: did the desk's named-edge deviations "
            "from the market beat it? n, win-rate vs market, mean Brier delta, "
            "paired-bootstrap CI, and a threshold RECOMMENDATION (never auto-applied)."
        ),
    )
    edge_parser.add_argument("--json", action="store_true", help="Emit the edge report as JSON")
    edge_parser.set_defaults(_forecast_handler=_cmd_edge)

    tail_audit_parser = forecast_sub.add_parser(
        "tail-audit",
        help=(
            "Probability-mass audit for a categorical distribution: flag UNEARNED tail "
            "mass (material outcomes with no named path — the outcome-space-anchoring failure)"
        ),
    )
    tail_audit_parser.add_argument(
        "--dist",
        dest="tail_audit_dist",
        required=True,
        help='Categorical distribution as JSON, e.g. \'{"A":0.55,"B":0.35,"C":0.1}\'',
    )
    tail_audit_parser.add_argument(
        "--outcome-path",
        dest="tail_audit_paths",
        action="append",
        default=[],
        metavar="OUTCOME=PATH",
        help="Name the causal path for an outcome (repeatable), e.g. --outcome-path 'A=leads polls'.",
    )
    tail_audit_parser.add_argument("--json", action="store_true")
    tail_audit_parser.set_defaults(_forecast_handler=_cmd_tail_audit)

    market_quality_parser = forecast_sub.add_parser(
        "market-quality",
        help=(
            "Stratify market readings by liquidity + recency into an advisory pooling "
            "weight, so a thin/stale market can't inflate a tail"
        ),
    )
    market_quality_parser.add_argument(
        "--markets",
        dest="market_quality_markets",
        required=True,
        help='JSON array of {source, volume?, updated_at?|age_days?, probability?} objects',
    )
    market_quality_parser.add_argument("--json", action="store_true")
    market_quality_parser.set_defaults(_forecast_handler=_cmd_market_quality)

    track_record_parser = forecast_sub.add_parser(
        "track-record",
        help=(
            "Measured Brier edge of each ensemble component / panel perspective "
            "over the committed aggregate, with advisory weights"
        ),
    )
    track_record_parser.add_argument(
        "--kind", choices=["all", "ensemble", "panel"], default="all",
        help="Restrict to ensemble components or panel perspectives",
    )
    track_record_parser.add_argument(
        "--origin",
        dest="forecast_origin",
        choices=["live", "backtest", "imported_baseline", "any"],
        default="live",
        help="Which snapshots count toward the record (default: live; 'any' = all origins)",
    )
    track_record_parser.add_argument(
        "--min-count", type=int, default=None,
        help="Observations required before a weight is recommended (default 5)",
    )
    track_record_parser.add_argument("--json", action="store_true")
    track_record_parser.set_defaults(_forecast_handler=_cmd_track_record)

    errors_parser = forecast_sub.add_parser("errors", help="Show domain error profile summary")
    errors_parser.add_argument("--domain")
    errors_parser.add_argument("--topic")
    errors_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum active learned-error review rows to print",
    )
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
    schedule_add.add_argument(
        "--next-run-at",
        help="First run timestamp; defaults to now so the review is due immediately",
    )
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
    schedule_dedupe = schedule_sub.add_parser(
        "dedupe",
        help="Collapse duplicate scheduled reviews (keeps one per scope + cadence + reason)",
    )
    schedule_dedupe.add_argument("--json", action="store_true", help="Emit machine-readable dedupe summary")
    schedule_dedupe.set_defaults(_forecast_handler=_cmd_schedule_dedupe)
    schedule_run = schedule_sub.add_parser("run", help="Run due scheduled self-checks")
    schedule_run.add_argument("--due", action="store_true", help="Run due reviews explicitly; this is the default")
    schedule_run.add_argument("--now")
    schedule_run.add_argument("--auto-score", action="store_true")
    schedule_run.add_argument("--auto-postmortem", action="store_true")
    schedule_run.set_defaults(_forecast_handler=_cmd_schedule_run)
    schedule_history = schedule_sub.add_parser("history", help="Show scheduled self-check run history")
    schedule_history.add_argument("--schedule", dest="scheduled_review_id")
    schedule_history.add_argument("--limit", type=int, default=20)
    schedule_history.add_argument("--json", action="store_true", help="Emit machine-readable run history JSON")
    schedule_history.set_defaults(_forecast_handler=_cmd_schedule_history)
    schedule_cron = schedule_sub.add_parser(
        "install-cron",
        help="Install a no-agent cron bridge for forecast self-checks",
    )
    schedule_cron.add_argument("--schedule", default="0 8 * * *")
    schedule_cron.add_argument("--name", default="Forecast self-check")
    schedule_cron.add_argument("--deliver", default="local")
    schedule_cron.add_argument("--profile")
    # Feature flags default ON so an operator-installed cron is as capable as the
    # auto-installed nightly routine (ensure_default_routines) — a bare install-cron
    # must not silently downgrade the desk's learning loop. `--no-*` opts out; the
    # positive flags are kept as no-ops for backward compatibility.
    schedule_cron.add_argument("--auto-score", dest="auto_score", action="store_true")
    schedule_cron.add_argument("--no-auto-score", dest="auto_score", action="store_false",
                               help="Do NOT auto-score resolved questions in the nightly sweep")
    schedule_cron.add_argument("--auto-postmortem", dest="auto_postmortem", action="store_true")
    schedule_cron.add_argument("--no-auto-postmortem", dest="auto_postmortem", action="store_false",
                               help="Do NOT auto-write postmortems in the nightly sweep")
    schedule_cron.add_argument(
        "--thesis-aggregate",
        dest="thesis_aggregate",
        action="store_true",
        help="Re-aggregate all theses (+ entity suitabilities) after each member review sweep",
    )
    schedule_cron.add_argument("--no-thesis-aggregate", dest="thesis_aggregate", action="store_false",
                               help="Do NOT re-aggregate theses in the nightly sweep")
    schedule_cron.add_argument("--synthesize-lessons", dest="synthesize_lessons", action="store_true",
                               help="Synthesize calibration lessons after the nightly sweep")
    schedule_cron.add_argument("--no-synthesize-lessons", dest="synthesize_lessons", action="store_false",
                               help="Do NOT synthesize calibration lessons in the nightly sweep")
    schedule_cron.add_argument("--refresh-market-models", dest="refresh_market_models", action="store_true",
                               help="Re-pull + recompute Market Models linked to open questions in the nightly sweep")
    schedule_cron.add_argument("--no-refresh-market-models", dest="refresh_market_models", action="store_false",
                               help="Do NOT refresh Market Models in the nightly sweep")
    schedule_cron.set_defaults(
        _forecast_handler=_cmd_schedule_install_cron,
        auto_score=True,
        auto_postmortem=True,
        thesis_aggregate=True,
        synthesize_lessons=True,
        refresh_market_models=True,
    )

    automode_cron = schedule_sub.add_parser(
        "automode-cron",
        help="Start/stop/status the continuous warning-automode cron (free tier + bounded paid tier)",
    )
    automode_cron_sub = automode_cron.add_subparsers(dest="automode_cron_command")
    ac_start = automode_cron_sub.add_parser(
        "start", help="Install the continuous warning-automode cron job (clean re-arm)"
    )
    ac_start.add_argument("--schedule", default="every 30 minutes")
    ac_start.add_argument("--name", default="Forecast warning automode")
    ac_start.add_argument("--deliver", default="local")
    ac_start.add_argument("--profile")
    ac_start.add_argument(
        "--no-agent",
        dest="agent",
        action="store_false",
        help="Free-tier-only continuous mode (do NOT wire the paid LLM tier)",
    )
    ac_start.set_defaults(agent=True)
    ac_start.add_argument(
        "--paid-budget", type=int, help="Per-cycle paid-tier agent-run cap (default 3)"
    )
    ac_start.add_argument(
        "--paid-min-interval-hours", type=float, help="Minimum hours between paid passes (default 6)"
    )
    ac_start.add_argument("--model")
    ac_start.add_argument("--provider")
    ac_start.add_argument("--max-iterations", type=int)
    ac_start.set_defaults(_forecast_handler=_cmd_automode_cron_start)
    ac_stop = automode_cron_sub.add_parser("stop", help="Remove the continuous warning-automode cron job")
    ac_stop.add_argument("--name", default="Forecast warning automode")
    ac_stop.set_defaults(_forecast_handler=_cmd_automode_cron_stop)
    ac_status = automode_cron_sub.add_parser("status", help="Show the continuous warning-automode cron status")
    ac_status.add_argument("--name", default="Forecast warning automode")
    ac_status.add_argument("--json", action="store_true")
    ac_status.set_defaults(_forecast_handler=_cmd_automode_cron_status)

    # `cycle`, not `desk` — `forecast desk` is the TUI desk launcher (a runtime
    # passthrough); this is the headless closed-loop cycle.
    cycle_parser = forecast_sub.add_parser("cycle", help="Run the closed-loop forecast cycle")
    cycle_sub = cycle_parser.add_subparsers(dest="cycle_command")
    cycle_run = cycle_sub.add_parser(
        "run",
        help="Run the full due cycle: reviews -> reconcile alerts -> re-aggregate theses -> synthesize lessons",
    )
    cycle_run.add_argument("--due", action="store_true", help="Run due reviews (the default)")
    cycle_run.add_argument("--now")
    cycle_run.add_argument("--no-thesis-aggregate", action="store_true", help="Skip re-aggregating theses")
    cycle_run.add_argument("--no-reconcile", action="store_true", help="Skip alert reconciliation")
    cycle_run.add_argument("--no-synthesize-lessons", action="store_true", help="Never synthesize lessons this run")
    cycle_run.add_argument("--synthesize-lessons", action="store_true", help="Force lesson synthesis every run")
    cycle_run.add_argument("--agent", action="store_true", help="Autonomously re-forecast the questions this sweep flags via the LLM update stage (runs before thesis + lesson phases so they see fresh snapshots)")
    cycle_run.add_argument("--model", help="--agent: model id for the reforecast agent")
    cycle_run.add_argument("--provider", help="--agent: provider for the reforecast agent")
    cycle_run.add_argument("--max-iterations", type=int, default=12, help="--agent: max agent iterations per question")
    cycle_run.add_argument("--max-questions", type=int, default=None, help="--agent: cap how many questions to reforecast in one sweep")
    cycle_run.add_argument("--force", action="store_true", help="--agent: reforecast even when the pipeline update stage is gated")
    cycle_run.set_defaults(_forecast_handler=_cmd_cycle_run)

    # Warning-resolution: drain the open alert_events backlog through REAL gated work
    # (a reforecast / autopilot recheck / score+postmortem) — never a bare ack.
    warnings_parser = forecast_sub.add_parser(
        "warnings",
        help="Resolve the open alert_events backlog through real gated work (never a bare ack)",
    )
    warnings_sub = warnings_parser.add_subparsers(dest="warnings_command")

    warnings_list = warnings_sub.add_parser(
        "list",
        help="Group the open warnings by reason (counts + priority order + recommended action); read-only",
    )
    warnings_list.add_argument("--reason", help="Filter to reasons containing this text")
    warnings_list.add_argument("--scope", help="Filter to a single question id / scope ref")
    warnings_list.add_argument("--limit", type=int, default=None, help="Cap the number of reason groups shown")
    warnings_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    warnings_list.set_defaults(_forecast_handler=_cmd_warnings_list)

    warnings_resolve = warnings_sub.add_parser(
        "resolve",
        help="Resolve ONE alert (or every open alert for a question) via the gated dispatcher",
    )
    warnings_resolve.add_argument("target", help="Alert id (al_*) or question/scope ref (fq_*)")
    warnings_resolve.add_argument(
        "--agent",
        action="store_true",
        help="Enable the autonomous LLM reforecast runner for REFORECAST alerts (otherwise they stay OPEN)",
    )
    warnings_resolve.add_argument("--model", help="--agent: model id for the reforecast agent")
    warnings_resolve.add_argument("--provider", help="--agent: provider for the reforecast agent")
    warnings_resolve.add_argument("--max-iterations", type=int, default=12, help="--agent: max agent iterations per question")
    warnings_resolve.add_argument(
        "--force",
        action="store_true",
        help="--agent: reforecast even when the pipeline update stage is gated",
    )
    warnings_resolve.add_argument("--now")
    warnings_resolve.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    warnings_resolve.set_defaults(_forecast_handler=_cmd_warnings_resolve)

    warnings_automode = warnings_sub.add_parser(
        "automode",
        help="Drain the backlog by priority: classify + dispatch each, then reconcile at the end",
    )
    warnings_automode.add_argument("--dry-run", action="store_true", help="Print the plan WITHOUT writing")
    warnings_automode.add_argument("--limit", type=int, default=None, help="Cap how many alerts to process this pass")
    warnings_automode.add_argument("--reason", help="Filter to reasons containing this text")
    warnings_automode.add_argument("--scope", help="Filter to a single question id / scope ref")
    warnings_automode.add_argument(
        "--tier",
        choices=["free", "reforecast"],
        help=(
            "Per-tier bulk pass: 'free' = the non-LLM kinds "
            "{bookkeeping,score,postmortem,material_change}; 'reforecast' = the "
            "opt-in LLM reforecast/evidence tier (pair with --agent)"
        ),
    )
    warnings_automode.add_argument(
        "--kinds",
        nargs="+",
        metavar="KIND",
        help=(
            "Restrict to these ResolutionKinds (e.g. --kinds score postmortem); "
            "UNIONed with --tier when both are given"
        ),
    )
    warnings_automode.add_argument(
        "--agent",
        action="store_true",
        help="Enable the autonomous LLM reforecast runner for REFORECAST alerts (otherwise they stay OPEN)",
    )
    warnings_automode.add_argument("--model", help="--agent: model id for the reforecast agent")
    warnings_automode.add_argument("--provider", help="--agent: provider for the reforecast agent")
    warnings_automode.add_argument("--max-iterations", type=int, default=12, help="--agent: max agent iterations per question")
    warnings_automode.add_argument("--max-questions", type=int, default=None, help="--agent: cap how many questions to reforecast in one sweep")
    warnings_automode.add_argument(
        "--force",
        action="store_true",
        help="--agent: reforecast even when the pipeline update stage is gated",
    )
    warnings_automode.add_argument("--no-reconcile", action="store_true", help="Skip the end-of-run reconcile_alerts pass")
    warnings_automode.add_argument("--now")
    warnings_automode.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    warnings_automode.set_defaults(_forecast_handler=_cmd_warnings_automode)

    watch_parser = forecast_sub.add_parser("watch", aliases=["source"], help="Manage watched sources for self-check alerts")
    watch_sub = watch_parser.add_subparsers(dest="watch_command")
    watch_add = watch_sub.add_parser("add", help="Watch a source for a question, domain, topic, or portfolio")
    watch_add.add_argument("source")
    watch_add.add_argument("--question", dest="question_id")
    watch_add.add_argument("--domain")
    watch_add.add_argument("--topic")
    watch_add.add_argument("--portfolio")
    watch_add.add_argument("--source-type", choices=sorted(WATCH_SOURCE_TYPES))
    watch_add.add_argument("--source-name", help="Human label for the watched source")
    watch_add.add_argument("--cadence", help="Expected check cadence for this watched source")
    watch_add.add_argument("--keyword", dest="keywords", action="append", default=[], help="RSS/Atom relevance keyword; repeatable or comma-separated")
    watch_add.add_argument("--exclude-keyword", dest="exclude_keywords", action="append", default=[], help="RSS/Atom exclusion keyword; repeatable or comma-separated")
    watch_add.add_argument("--materiality", choices=["low", "medium", "high"], help="Expected materiality when matching RSS/Atom items change")
    watch_add.add_argument("--direction", choices=["upward", "downward", "ambiguous"], help="Expected directional impact for matching RSS/Atom items")
    watch_add.add_argument("--affected-component", dest="affected_components", action="append", default=[], help="Forecast assumption or component affected by matching RSS/Atom items")
    watch_add.add_argument(
        "--role",
        choices=sorted(WATCH_SOURCE_ROLES),
        help="Source role: resolver/consensus/official_primary/leading_indicator/market_price/background_context",
    )
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

    # Information-triage: reach the three-way labeler / contested-routing / trust
    # gate for non-agent users + cron. Thin wrappers over the SAME tool actions
    # (forecast_ledger_tool), so the triage logic lives in exactly one place.
    triage_parser = forecast_sub.add_parser(
        "triage",
        help="Three-way relevance labeling on candidate readings (keep/skim/skip) before they become evidence",
    )
    triage_sub = triage_parser.add_subparsers(dest="triage_command")

    triage_label = triage_sub.add_parser("label", help="Auto-label candidate readings (three-way)")
    triage_label.add_argument("--question", dest="question_id")
    triage_label.add_argument(
        "--use-watched",
        action="store_true",
        help="Pull candidates from the question's watched sources (requires --question)",
    )
    triage_label.add_argument(
        "--candidates-json",
        help="JSON array of candidate readings [{title, summary?, source_type?, source?, url?, id?}]",
    )
    triage_label.add_argument("--rubric-ref", help="Explicit triage rubric id to apply")
    triage_label.add_argument("--model", help="Model id for the cheap auto-labeler (default $FORECAST_TRIAGE_MODEL)")
    triage_label.add_argument("--query", help="Optional query when pulling watched candidates")
    triage_label.add_argument("--limit", type=int, default=20)
    triage_label.add_argument(
        "--no-persist", action="store_true", help="Do not persist verdicts as triage_labels staging rows"
    )
    triage_label.set_defaults(_forecast_handler=_cmd_triage_label)

    triage_contested = triage_sub.add_parser(
        "contested", help="Route contested/boundary auto-labels to operator hand-labeling"
    )
    triage_contested.add_argument("--question", dest="question_id")
    triage_contested.add_argument(
        "--label-id", dest="label_ids", action="append", default=[], help="Specific triage_label id(s) to check"
    )
    triage_contested.add_argument(
        "--verifier-json",
        dest="verifier_json",
        help="Optional second-opinion labels [{candidate_ref|id, label}] to define disagreement",
    )
    triage_contested.add_argument("--disagreement-threshold", type=float)
    triage_contested.set_defaults(_forecast_handler=_cmd_triage_contested)

    triage_relabel = triage_sub.add_parser(
        "relabel", help="Record an operator expert label (adjudication) + ack its contested alert"
    )
    triage_relabel.add_argument("label_id", nargs="?")
    triage_relabel.add_argument("label", nargs="?", help="relevant_interesting | relevant_uninteresting | irrelevant")
    triage_relabel.add_argument(
        "--adjudications-json", help="JSON array [{label_id, label}] for bulk adjudication"
    )
    triage_relabel.set_defaults(_forecast_handler=_cmd_triage_relabel)

    triage_trust = triage_sub.add_parser("trust", help="Show the held-out trust gate for the auto-labeler")
    triage_trust.add_argument("--threshold", type=float)
    triage_trust.add_argument("--min-sample", type=int)
    triage_trust.set_defaults(_forecast_handler=_cmd_triage_trust)

    triage_set_rubric = triage_sub.add_parser("set-rubric", help="Store/replace a desk triage rubric for a scope")
    triage_set_rubric.add_argument("--scope-type", default="global")
    triage_set_rubric.add_argument("--scope-ref")
    triage_set_rubric.add_argument("--interesting", required=True, help="What counts as INTERESTING here (required)")
    triage_set_rubric.add_argument("--uninteresting", default="")
    triage_set_rubric.add_argument("--irrelevant", default="")
    triage_set_rubric.add_argument("--notes", default="")
    triage_set_rubric.set_defaults(_forecast_handler=_cmd_triage_set_rubric)

    triage_list_rubrics = triage_sub.add_parser("list-rubrics", help="List stored triage rubrics")
    triage_list_rubrics.add_argument("--scope-type")
    triage_list_rubrics.add_argument("--scope-ref")
    triage_list_rubrics.add_argument("--all", action="store_true", help="Include inactive rubrics")
    triage_list_rubrics.set_defaults(_forecast_handler=_cmd_triage_list_rubrics)

    # Cross-pollination links between forecasts.
    link_parser = forecast_sub.add_parser("link", help="Link related forecasts so they cross-pollinate context")
    link_sub = link_parser.add_subparsers(dest="link_command")
    link_add = link_sub.add_parser("add", help="Link two forecasts (related sibling, or component_of for hierarchy)")
    link_add.add_argument("from_ref", help="row number, id, or search words")
    link_add.add_argument("to_ref", help="row number, id, or search words")
    link_add.add_argument("--type", dest="link_type", default="related", choices=sorted(FORECAST_LINK_TYPES))
    link_add.add_argument("--rationale", default="")
    link_add.set_defaults(_forecast_handler=_cmd_link_add)
    link_list = link_sub.add_parser("list", help="List a forecast's links and related forecasts")
    link_list.add_argument("ref", help="row number, id, or search words")
    link_list.set_defaults(_forecast_handler=_cmd_link_list)
    link_remove = link_sub.add_parser("remove", help="Remove the link(s) between two forecasts")
    link_remove.add_argument("from_ref")
    link_remove.add_argument("to_ref")
    link_remove.add_argument("--type", dest="link_type", default=None, choices=sorted(FORECAST_LINK_TYPES))
    link_remove.set_defaults(_forecast_handler=_cmd_link_remove)
    # Flat aliases.
    links_parser = forecast_sub.add_parser("links", help="List a forecast's links and related forecasts")
    links_parser.add_argument("ref", help="row number, id, or search words")
    links_parser.set_defaults(_forecast_handler=_cmd_link_list)
    unlink_parser = forecast_sub.add_parser("unlink", help="Remove the link(s) between two forecasts")
    unlink_parser.add_argument("from_ref")
    unlink_parser.add_argument("to_ref")
    unlink_parser.add_argument("--type", dest="link_type", default=None, choices=sorted(FORECAST_LINK_TYPES))
    unlink_parser.set_defaults(_forecast_handler=_cmd_link_remove)

    # Thesis + factor domain — carved to forecasting/cli/thesis.py, registered
    # via the shared per-domain hook (the CLI-assembler pattern). The module is
    # imported at the bottom of this file (surface parity for
    # forecasting.cli._cmd_thesis_dashboard); registration order is preserved so
    # `forecast --help` stays byte-identical.
    _thesis_domain.register(forecast_sub)

    # Question curation — propose short-horizon contested binaries from the
    # prediction-market data plane as calibration fuel. Carved to
    # forecasting/cli/curate.py, registered via the shared per-domain hook.
    from forecasting.cli import curate as _curate_domain

    _curate_domain.register(forecast_sub)

    # Two-phase batch: run members first, then aggregate theses (lag ordering).
    run_all_parser = forecast_sub.add_parser(
        "run-all",
        help="Refresh every active member forecast, then aggregate every active thesis",
    )
    run_all_parser.add_argument("--limit", type=int, default=None, help="Cap the number of member forecasts run in phase 1")
    run_all_parser.add_argument("--rho", type=float, default=0.4)
    run_all_parser.add_argument("--dry-run", action="store_true", help="Print what would run without changing anything")
    run_all_parser.set_defaults(_forecast_handler=_cmd_run_all)

    autopilot_parser = forecast_sub.add_parser(
        "autopilot",
        help="Wire watched sources, schedules, materiality, and update proposals",
    )
    autopilot_sub = autopilot_parser.add_subparsers(dest="autopilot_command")
    autopilot_enable = autopilot_sub.add_parser("enable", help="Enable autonomous forecast maintenance")
    autopilot_enable.add_argument("id")
    autopilot_enable.add_argument("--source", action="append", default=[])
    autopilot_enable.add_argument("--sources", help="Comma-separated watched sources")
    autopilot_enable.add_argument("--required-source", action="append", default=[])
    autopilot_enable.add_argument("--required-sources", help="Comma-separated watched sources that block refresh if unavailable")
    autopilot_enable.add_argument("--cadence", required=True)
    autopilot_enable.add_argument("--next-run-at")
    autopilot_enable.add_argument(
        "--mode",
        choices=["propose", "auto-commit", "alert-only"],
        default="propose",
    )
    autopilot_enable.add_argument("--materiality-threshold", action="append", default=[])
    autopilot_enable.add_argument("--max-auto-delta", type=float)
    autopilot_enable.add_argument("--min-sources-for-auto-commit", type=int)
    autopilot_enable.add_argument("--notify")
    autopilot_enable.add_argument("--quiet-if-unchanged", action="store_true")
    autopilot_enable.add_argument("--created-by")
    autopilot_enable.add_argument("--allow-missing-resolution-source", action="store_true")
    autopilot_enable.set_defaults(_forecast_handler=_cmd_autopilot_enable)
    autopilot_disable = autopilot_sub.add_parser("disable", help="Disable active autopilot policy for a question")
    autopilot_disable.add_argument("id")
    autopilot_disable.set_defaults(_forecast_handler=_cmd_autopilot_disable)
    autopilot_status = autopilot_sub.add_parser("status", help="Show autopilot policy state")
    autopilot_status.add_argument("id")
    autopilot_status.set_defaults(_forecast_handler=_cmd_autopilot_status)
    autopilot_run = autopilot_sub.add_parser("run", help="Run autopilot source checks and proposal generation")
    autopilot_run.add_argument("id")
    autopilot_run.add_argument("--now")
    autopilot_run.add_argument("--trigger-reason", default="manual")
    autopilot_run.add_argument("--proposed-probability", type=float)
    autopilot_run.add_argument("--rationale")
    autopilot_run.set_defaults(_forecast_handler=_cmd_autopilot_run)
    autopilot_history = autopilot_sub.add_parser("history", help="Show autopilot run history")
    autopilot_history.add_argument("id")
    autopilot_history.add_argument("--limit", type=int, default=20)
    autopilot_history.set_defaults(_forecast_handler=_cmd_autopilot_history)
    autopilot_proposals = autopilot_sub.add_parser("proposals", help="List forecast update proposals")
    autopilot_proposals.add_argument("id", nargs="?")
    autopilot_proposals.add_argument("--all", action="store_true")
    autopilot_proposals.set_defaults(_forecast_handler=_cmd_autopilot_proposals)
    autopilot_approve = autopilot_sub.add_parser("approve", help="Approve a pending forecast update proposal")
    autopilot_approve.add_argument("proposal_id")
    autopilot_approve.add_argument("--reviewed-by")
    autopilot_approve.set_defaults(_forecast_handler=_cmd_autopilot_approve)
    autopilot_reject = autopilot_sub.add_parser("reject", help="Reject a pending forecast update proposal")
    autopilot_reject.add_argument("proposal_id")
    autopilot_reject.add_argument("--reviewed-by")
    autopilot_reject.set_defaults(_forecast_handler=_cmd_autopilot_reject)

    alerts_parser = forecast_sub.add_parser("alerts", help="List + reconcile forecast alerts")
    alerts_parser.add_argument("--all", action="store_true")
    alerts_parser.add_argument("--ack", dest="ack_alert_id")
    alerts_parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Auto-acknowledge alerts whose source-change has already been consumed (evidence imported + forecast updated since)",
    )
    alerts_parser.add_argument("--dry-run", action="store_true", help="With --reconcile/--collapse/--escalate, preview without writing")
    alerts_parser.add_argument(
        "--collapse",
        action="store_true",
        help="One-time: fold existing duplicate open-alert groups into the oldest row (keep oldest, fold counts)",
    )
    alerts_parser.add_argument(
        "--escalate",
        action="store_true",
        help="Escalate the severity of aged open alerts (7d->warning, 14d->high)",
    )
    alerts_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
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

    triggers_parser = forecast_sub.add_parser(
        "triggers",
        help="Evaluate a question's executable update_triggers against imported values",
    )
    triggers_parser.add_argument("id")
    triggers_parser.add_argument(
        "--observation",
        dest="observations",
        action="append",
        default=[],
        metavar="SOURCE_REF=VALUE",
        help="Override an observed value, e.g. --observation fred:CPIAUCSL=3.2 (repeatable). "
        "Omitted observations are derived from the question's imported evidence.",
    )
    triggers_parser.add_argument("--observations-json", default=None, help="JSON object of source_ref->value.")
    triggers_parser.add_argument("--now")
    triggers_parser.add_argument("--json", action="store_true")
    triggers_parser.set_defaults(_forecast_handler=_cmd_triggers)

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
    backtest_parser.add_argument(
        "--agent-prompt-jsonl",
        help=(
            "Write sanitized agent protocol prompt packets as JSONL for offline model runs; "
            "used with --prepare-agent-prompts and --probability-source agent-protocol."
        ),
    )
    backtest_parser.add_argument(
        "--prepare-agent-prompts",
        action="store_true",
        help="Only write --agent-prompt-jsonl packets for the selected dataset and do not run the backtest",
    )
    backtest_parser.add_argument("--agent-model", help="Model used for agent-protocol backtests")
    backtest_parser.add_argument("--agent-provider", help="Provider used for agent-protocol backtests")
    backtest_parser.add_argument("--agent-max-iterations", type=int, default=12)
    backtest_parser.add_argument(
        "--closed-book",
        action="store_true",
        help=(
            "Closed-book agent-protocol replay: disable the live web/search "
            "toolset so the agent forecasts from the question text and reasoning "
            "only. Use for historical questions whose outcome is googleable. "
            "Used only with --probability-source agent-protocol."
        ),
    )
    backtest_parser.add_argument(
        "--market-hidden",
        action="store_true",
        help=(
            "MARKET-HIDDEN ARM (agent-protocol only): withhold the freeze market "
            "baseline from the agent's PROMPT so no market price is shown to it, "
            "while the market baseline is STILL scored for the head-to-head + "
            "complementarity. Pair with --closed-book for a true intrinsic-only "
            "forecast (no tooling to look the price up). ForecastBench datasets only."
        ),
    )
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
    performance_parser.add_argument(
        "--live",
        action="store_true",
        help="Include resolved live forecast performance against scored imported baselines",
    )
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
        "--min-external-source-families",
        type=int,
        default=DEFAULT_MIN_EXTERNAL_SOURCE_FAMILIES_FOR_CLAIM,
        help="Required distinct external resolved-question source families for readiness accounting",
    )
    readiness_parser.add_argument(
        "--require-evidence",
        action="store_true",
        help="Exit nonzero when readiness requirements still have gaps",
    )
    readiness_parser.add_argument(
        "--run-safe-benchmarks",
        action="store_true",
        help="First run the OFFLINE builtin benchmark suite (no network / no paid LLM), then re-evaluate readiness and report the gaps that closed",
    )
    readiness_parser.add_argument(
        "--probability-source",
        choices=["forecast-engine", "baseline-ensemble"],
        default="forecast-engine",
        help="Generated probability source for --run-safe-benchmarks (default forecast-engine; 'naive' can't beat baselines so it's excluded, and agent-protocol isn't offline)",
    )
    readiness_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --run-safe-benchmarks: list the benchmarks that would run, without running them",
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
    pilot_parser.add_argument("--min-scheduled-review-runs", type=int, default=1)
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
    pilot_bundle_parser.add_argument("--min-scheduled-review-runs", type=int, default=1)
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
        "--min-external-source-families",
        type=int,
        default=DEFAULT_MIN_EXTERNAL_SOURCE_FAMILIES_FOR_CLAIM,
        help="Required distinct external resolved-question source families for readiness accounting",
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

    # jobs/admin domain — registered via the shared per-domain hook (the CLI
    # assembler pattern). Call-time import keeps core free of a load-time edge to
    # the domain module (no import cycle) and preserves registration order so
    # `forecast --help` is byte-identical.
    from forecasting.cli import jobs_admin as _jobs_admin

    _jobs_admin.register(forecast_sub)

    # slack/admin domain — same per-domain register hook (M1 of the multiplayer
    # harness): `forecast slack provision` + `forecast slack whoami`.
    from forecasting.cli import slack_admin as _slack_admin

    _slack_admin.register(forecast_sub)

    return parser


def cmd_forecast(args: argparse.Namespace) -> None:
    from forecasting.ledger import allow_ledger_writes

    handler = getattr(args, "_forecast_handler", None)
    try:
        if handler is None:
            _cmd_dashboard(args)
            return
        # The forecast CLI is a recognised legitimate writer (the operator's own
        # commit/onboard/score commands). Opening the write context here lets the
        # CLI commit through the same gated methods an ad-hoc script is refused.
        with allow_ledger_writes(reason="forecast_cli"):
            handler(args)
    except ForecastingError as exc:
        print(f"forecast: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def main(argv: list[str] | None = None, *, prog: str = CLI_SURFACE) -> None:
    """Standalone ``forecast`` console entrypoint.

    The forecast fork can keep `hermes forecast ...` during transition while
    also exposing `forecast ...` as the primary product command.
    """

    # Load the user dotenv so persisted API keys (`forecast api-key set ...`)
    # are active for subsequent invocations. Best-effort: a missing dotenv
    # dependency or unreadable file must not block the CLI.
    try:
        from hermes_cli.env_loader import load_hermes_dotenv

        load_hermes_dotenv()
    except Exception:  # pragma: no cover — defensive
        pass

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


def _forecast_status_payload(ledger: ForecastLedger) -> dict[str, Any]:
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
    autopilot_policies = ledger.list_autopilot_policies(enabled_only=False)
    autopilot_runs = ledger.list_autopilot_runs(limit=1000)
    autopilot_proposals = ledger.list_forecast_update_proposals(status=None, limit=1000)
    benchmarks = list_builtin_benchmarks()
    imported_benchmarks = ledger.list_benchmark_datasets()
    lessons = ledger.list_calibration_lessons()
    active_lessons = ledger.list_calibration_lessons(active_only=True)
    scores = ledger.list_scores(calibration_eligible=None, include_invalidated=True)
    calibration = ledger.calibration_summary(calibration_eligible=True)
    live_performance = ledger.live_performance_report()
    live_baselines = list(live_performance.get("baselines") or [])
    live_best_baseline = min(
        [row for row in live_baselines if row.get("mean_brier") is not None],
        key=lambda row: float(row.get("mean_brier")),
        default=None,
    )
    extensions = extension_registry.list()
    return {
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
        "autopilot_policy_count": len(autopilot_policies),
        "active_autopilot_policy_count": sum(1 for row in autopilot_policies if row.get("enabled")),
        "autopilot_run_count": len(autopilot_runs),
        "pending_autopilot_proposal_count": sum(
            1 for row in autopilot_proposals if row.get("status") == "pending"
        ),
        "score_count": len(scores),
        "calibration_eligible_score_count": calibration["count"],
        "calibration_mean_brier": calibration["mean_brier"],
        "live_performance": {
            "score_count": live_performance.get("score_count", 0),
            "agent_mean_brier": (live_performance.get("agent") or {}).get("mean_brier"),
            "baseline_count": len(live_baselines),
            "best_baseline": (
                {
                    "name": (
                        f"{live_best_baseline.get('baseline_type')}:{live_best_baseline.get('source')}"
                    ),
                    "mean_brier": live_best_baseline.get("mean_brier"),
                    "agent_edge_mean_brier": live_best_baseline.get(
                        "mean_brier_improvement_vs_baseline"
                    ),
                    "paired_count": live_best_baseline.get("paired_count", 0),
                    "paired_agent_wins": live_best_baseline.get("paired_agent_wins", 0),
                    "paired_baseline_wins": live_best_baseline.get("paired_baseline_wins", 0),
                    "paired_ties": live_best_baseline.get("paired_ties", 0),
                }
                if live_best_baseline is not None
                else None
            ),
            "claim_status": live_performance.get("claim_status"),
        },
        "calibration_lesson_count": len(lessons),
        "active_calibration_lesson_count": len(active_lessons),
        "builtin_benchmark_count": len(benchmarks),
        "imported_benchmark_count": len(imported_benchmarks),
        "extension_count": len(extensions),
        # Crux-promotion coverage (finding #4): promoted first-class cruxes + the
        # count still trapped inside panel blobs. Fail-safe — never take down status.
        "crux_promotion": _crux_promotion_stats_safe(ledger),
    }


def _crux_promotion_stats_safe(ledger: ForecastLedger) -> dict[str, Any]:
    try:
        return ledger.crux_promotion_stats()
    except Exception:  # noqa: BLE001 — a read probe must never take down status/doctor
        return {
            "promoted_total": 0,
            "promoted_from_panels": 0,
            "panel_embedded_distinct": 0,
            "unpromoted_panel_cruxes": 0,
        }


def _cmd_status(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    payload = _forecast_status_payload(ledger)
    question_counts = payload["question_counts"]
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
        f"autopilot: policies={payload['active_autopilot_policy_count']}/"
        f"{payload['autopilot_policy_count']}  runs={payload['autopilot_run_count']}  "
        f"pending_proposals={payload['pending_autopilot_proposal_count']}"
    )
    print(
        f"scores: total={payload['score_count']}  "
        f"calibration_eligible={payload['calibration_eligible_score_count']}  "
        f"mean_brier={_format_metric(payload['calibration_mean_brier'])}"
    )
    live_performance = payload["live_performance"]
    best_live_baseline = live_performance.get("best_baseline") or {}
    best_live_text = (
        f" best={best_live_baseline.get('name')} "
        f"edge={_format_delta(best_live_baseline.get('agent_edge_mean_brier'))} "
        f"wins={best_live_baseline.get('paired_agent_wins', 0)}/"
        f"{best_live_baseline.get('paired_baseline_wins', 0)}/"
        f"{best_live_baseline.get('paired_ties', 0)}"
        if best_live_baseline
        else ""
    )
    claim_status = (live_performance.get("claim_status") or {}).get("verdict") or "-"
    print(
        "live_performance: "
        f"scores={live_performance.get('score_count', 0)}  "
        f"agent_brier={_format_metric(live_performance.get('agent_mean_brier'))}  "
        f"baselines={live_performance.get('baseline_count', 0)}"
        f"{best_live_text}  claim={claim_status}"
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


def _cmd_bench(args: argparse.Namespace) -> None:
    """Print the read-only ForecastBench backtest scoreboard (agent vs market Brier)."""

    from forecasting.dashboard import build_bench_scoreboard

    ledger = _ledger(args)
    payload = build_bench_scoreboard(ledger=ledger, limit=args.limit)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    rows = payload["rows"]
    aggregate = payload["aggregate"]
    print(PRODUCT_NAME)
    print(
        f"bench: questions={payload['count']}  resolved={payload['resolved_count']}  "
        f"scored_pairs={aggregate['n']}"
    )
    if not rows:
        print("no ForecastBench questions found (ingest a forecastbench dataset first)")
        return

    header = (
        f"{'QUESTION':<40} {'SRC':<10} {'AGENT':>7} {'MARKET':>7} "
        f"{'OUT':>4} {'A.BRIER':>8} {'M.BRIER':>8} {'EDGE':>7}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        title = (row.get("title") or row.get("id") or "")[:39]
        source = (row.get("source") or "-")[:10]
        outcome = row.get("outcome")
        out_text = "-" if outcome is None else ("1" if outcome >= 0.5 else "0")
        print(
            f"{title:<40} {source:<10} "
            f"{row.get('agent_probability_display') or '-':>7} "
            f"{row.get('market_probability_display') or '-':>7} "
            f"{out_text:>4} "
            f"{_format_metric(row.get('agent_brier')):>8} "
            f"{_format_metric(row.get('market_brier')):>8} "
            f"{_format_delta(row.get('brier_edge')):>7}"
        )
    print("-" * len(header))
    print(
        f"aggregate: n={aggregate['n']}  "
        f"mean_agent_brier={_format_metric(aggregate['mean_agent_brier'])}  "
        f"mean_market_brier={_format_metric(aggregate['mean_market_brier'])}  "
        f"edge={_format_delta(aggregate['mean_brier_edge'])} "
        f"(positive = agent beat the market freeze)"
    )


#: The doctor flags a backup as STALE once the newest one is older than this.
DOCTOR_BACKUP_STALE_HOURS = 48.0


def _build_durability_section(
    ledger: ForecastLedger, *, stale_hours: float = DOCTOR_BACKUP_STALE_HOURS
) -> dict[str, Any]:
    """The doctor's integrity+backup section: last-backup age (``ok`` / ``stale`` /
    ``missing``), the integrity verdict, and the row-count snapshot.

    ``missing`` (no backup at all) and ``stale`` (>``stale_hours`` old) are the two
    WARN states — the surface that keeps the durability gap on the lazy path even
    when the backup cadence is operator-created."""

    latest = ledger.latest_backup()
    integ = ledger.integrity_check()
    if latest is None:
        backup_status = "missing"
    elif isinstance(latest.get("age_hours"), (int, float)) and latest["age_hours"] > stale_hours:
        backup_status = "stale"
    else:
        backup_status = "ok"
    return {
        "backup_status": backup_status,  # ok | stale | missing
        "stale_after_hours": stale_hours,
        "last_backup": latest,
        "backup_dir": str(ledger.default_backup_dir()),
        "integrity_ok": bool(integ.get("ok")),
        "violations": integ.get("violations") or [],
        "counts": integ.get("counts") or {},
    }


def _build_doctor_report(args: argparse.Namespace) -> dict[str, Any]:
    ledger = _ledger(args)
    status = _forecast_status_payload(ledger)
    pilot_report = ledger.pilot_report(
        min_questions=args.min_questions,
        min_structured_source_questions=args.min_structured_source_questions,
        min_scores=args.min_scores,
        min_postmortems=args.min_postmortems,
        min_scheduled_reviews=args.min_scheduled_reviews,
        min_scheduled_review_runs=args.min_scheduled_review_runs,
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
        min_external_source_families=max(args.min_external_source_families, 0),
    )
    pilot_ready = pilot_report["passed_checks"] == pilot_report["total_checks"]
    readiness_gaps = bool(evidence_status.get("gaps"))
    if not pilot_ready:
        doctor_status = "needs_tester_pilot_artifacts"
    elif readiness_gaps:
        doctor_status = "tester_handoff_ready_live_claim_unproven"
    else:
        doctor_status = "benchmark_evidence_ready_live_claim_unproven"

    from forecasting.protocol import PROCESS_VERSION

    # Measurement honesty: score aggregates BY COHORT (never a pooled headline) +
    # the pathological-row audit that separates ingestion artifacts from real
    # catastrophic misses. Both read-only + fail-safe, like every probe here.
    try:
        cohort_scoreboard = ledger.cohort_scoreboard()
    except Exception:
        cohort_scoreboard = None
    try:
        scores_audit = ledger.scores_audit()
    except Exception:
        scores_audit = None

    # A heuristic, read-only detector must NEVER take down the doctor audit.
    try:
        templated_batches = ledger.detect_templated_batches()
    except Exception:
        templated_batches = []

    # SLICE 5 fold: one place that shows ALL three "warning" models together — the
    # alert_events backlog (grouped by reason), the saturation/hook issues, and the
    # templated-batch clusters. Each sub-probe is read-only and fail-safe so a
    # heuristic can never take down the audit (mirrors templated_batches above).
    from forecasting.warnings import summarize_open_warnings

    try:
        alert_backlog = summarize_open_warnings(ledger)
    except Exception:
        alert_backlog = {"groups": [], "group_count": 0, "open_total": 0}
    try:
        from forecasting.hooks import finish_sweep

        active_ids = [q.id for q in ledger.list_questions(status="active")]
        saturation = finish_sweep(ledger, active_ids)
    except Exception:
        saturation = {"checked": 0, "clean": 0, "under_saturated": []}
    # ADHERENCE SCORECARD: per-gate pass rates over active questions, tallied from
    # the STORED saturation verdicts (read-only, no recompute). The glanceable trust
    # number — failed_block should be zero, failed_warn columns should be falling.
    try:
        from forecasting.hooks import adherence_scorecard

        hook_adherence = adherence_scorecard(ledger, question_ids=active_ids)
    except Exception:
        hook_adherence = {"questions_scored": 0, "rules_tracked": 0, "total_failed_block": 0, "rules": {}}
    warnings_fold = {
        "alert_backlog": alert_backlog,
        "saturation": saturation,
        "templated_batches": templated_batches,
    }

    # Triage trust gate: is the cheap auto-labeler good enough (held-out auto-vs-
    # expert accuracy) to be trusted to auto-filter, or still SUGGEST-ONLY? Read-
    # only + fail-safe, like every probe above.
    try:
        from forecasting.triage import build_triage_trust_gate

        triage_gate = build_triage_trust_gate(ledger)
    except Exception:
        triage_gate = None

    # SLICE S4 fold: cron health. Is the recurrence spine actually FIRING? Read the
    # installed forecast cron jobs' last_status/last_error/last_run_at and flag
    # errored or missed (last_run_at older than 2x cadence) jobs. Read-only +
    # fail-safe, like every probe above.
    try:
        from forecasting.scheduler import forecast_cron_health

        cron_health = forecast_cron_health()
    except Exception:
        cron_health = None

    # Free-tier warning DRAIN (nightly): the last drain count (from the state file
    # the run_due_reviews free-tier phase writes) + the LIVE remaining free-tier
    # backlog, so an operator can see the "free" alerts draining themselves at zero
    # token spend without re-running the sweep. Read-only + fail-safe, like every
    # probe above.
    try:
        from forecasting.cron_runner import read_free_tier_drain_state
        from forecasting.warnings import aggregate_open_warnings

        drain_state = read_free_tier_drain_state()
        remaining_free = int(
            (aggregate_open_warnings(ledger).get("headline") or {}).get("free", 0) or 0
        )
        free_tier_drain = {"last": drain_state or None, "remaining_free": remaining_free}
    except Exception:
        free_tier_drain = None

    # Gateway DUE-SWEEPER: is the sweeper closing the "due on the Desk vs actually
    # runs" gap between nightly cron runs? Read its config (enabled/interval), its
    # last-tick state file (the run_review_sweep writer), and the LIVE count of
    # reviews already due right now. Read-only + fail-safe, like every probe above.
    try:
        from forecasting.cron_runner import (
            read_review_sweeper_state,
            resolve_review_sweep_interval_minutes,
        )

        sweep_interval = resolve_review_sweep_interval_minutes()
        review_sweeper = {
            "enabled": sweep_interval > 0,
            "interval_minutes": sweep_interval,
            "last": read_review_sweeper_state() or None,
            "due_now": int(ledger.count_due_scheduled_reviews()),
        }
    except Exception:
        review_sweeper = None

    # Prediction-markets sibling (Arc 4): streaming readiness (ws lib +
    # cryptography + Kalshi key) and per-venue market-data availability. Read-
    # only + fail-safe, like every probe above; no network unless asked.
    try:
        from forecasting.pm.health import build_pm_doctor

        prediction_markets = build_pm_doctor()
    except Exception:
        prediction_markets = None

    # DURABILITY: the ledger IS the asset (months of judgment). Surface the last
    # backup age (WARN when >48h / none), the integrity verdict, and a row-count
    # snapshot so the lazy path can never silently lose the book. Read-only +
    # fail-safe, like every probe above.
    try:
        durability = _build_durability_section(ledger)
    except Exception:
        durability = None

    # SOURCE DIVERSITY (the monoculture guard): median distinct sources/question
    # + the single-source share across the book. The edge rests on ORTHOGONAL
    # signal, so a ledger collapsed to one source per question has nothing to
    # pool. Read-only + fail-safe, like every probe above.
    try:
        source_diversity = ledger.source_diversity_summary()
    except Exception:
        source_diversity = None

    # SECOND BRAIN: vault health — pages/orphans/broken-links/stale/tombstones,
    # section budget state, and the manifest's pending operator edits. Read-only
    # + fail-safe (the plugin import is call-time; a missing vault reports None).
    try:
        from plugins.obsidian.prune import build_vault_health
        from plugins.obsidian.vault import resolve_vault_path

        _vault = resolve_vault_path()
        vault_health = build_vault_health(_vault, ledger=ledger) if _vault else None
    except Exception:
        vault_health = None

    # PANEL-vs-SOLO ABLATION: does the 5-role panel + judge machinery actually
    # beat a lone panelist on the resolved book? A paired recenter-at-zero
    # bootstrap over resolved Brier-scoreable panels. Read-only + fail-safe;
    # honest n (a tiny/empty sample is reported as such). A weekly cron can
    # persist/surface this — the doctor is its read-only window.
    try:
        from forecasting.ablation_study import run_panel_vs_solo_ablation

        ablation = run_panel_vs_solo_ablation(ledger)
    except Exception:
        ablation = None

    # DEVIATION EDGE (UPGRADE 2): did the desk's named-edge deviations from the
    # market beat it, on resolved bets? The clean read on whether the whole
    # orthogonality thesis is paying off — n, win-rate, mean Brier delta + CI, and
    # a threshold recommendation (advisory only). Read-only + fail-safe.
    try:
        deviation_edge = ledger.deviation_bet_edge_report()
    except Exception:
        deviation_edge = None

    return {
        "product": PRODUCT_NAME,
        "process_version": PROCESS_VERSION,
        "generated_at": utc_now_iso(),
        "doctor_status": doctor_status,
        "tester_handoff_ready": pilot_ready,
        "claim_live_superforecasting": evidence_status.get("can_claim_live_superforecasting"),
        "triage_gate": triage_gate,
        "cron_health": cron_health,
        "free_tier_drain": free_tier_drain,
        "review_sweeper": review_sweeper,
        "prediction_markets": prediction_markets,
        "durability": durability,
        "source_diversity": source_diversity,
        "vault_health": vault_health,
        "panel_vs_solo_ablation": ablation,
        "deviation_edge": deviation_edge,
        "hook_adherence": hook_adherence,
        "status": status,
        "cohort_scoreboard": cohort_scoreboard,
        "scores_audit": scores_audit,
        "pilot_report": pilot_report,
        "readiness": {
            "last": max(args.last, 0),
            "dataset_filter": args.dataset,
            "run_count": len(summaries),
            "inspected_backtest_run_ids": [row["id"] for row in rows],
            "evidence_status": evidence_status,
        },
        "required_exit_gates": {
            "pilot_ready_required": bool(args.require_pilot_ready),
            "readiness_required": bool(args.require_readiness),
            "pilot_ready": pilot_ready,
            "readiness_gaps": readiness_gaps,
        },
        # Recent LIVE forecasts that look like a 'one template x N' batch (same method
        # + reasoning_methods + rationale tail) rather than per-question deliberation.
        # A heuristic flag for review, never a block — see skills/ledger-interaction.
        "templated_batches": templated_batches,
        # SLICE 5: the three warning models folded into one view (alert backlog by
        # reason + saturation/hook issues + templated batches).
        "warnings_fold": warnings_fold,
    }


def _cmd_lint(args: argparse.Namespace) -> None:
    """Run the forecast saturation hooks read-only against a forecast (or all of
    them) and print the score + per-rule verdict table."""
    ledger = _ledger(args)
    from forecasting.hooks import by_rule_sweep, finish_sweep, lint_forecast

    if getattr(args, "by_rule", False):
        table = by_rule_sweep(ledger)
        if args.json:
            print(json.dumps(table, ensure_ascii=False))
            return
        print(f"per-rule fire counts across {table['questions_scored']} active live forecasts:")
        print(f"  {'rule':<32} {'checked':>7} {'warn':>6} {'block':>6}")
        for rid, b in sorted(table["rules"].items(), key=lambda kv: -kv[1]["failed"]):
            if not b["failed"]:
                continue
            print(f"  {rid:<32} {b['checked']:>7} {b['failed_warn']:>6} {b['failed_block']:>6}")
        return

    if args.all:
        ids = [q.id for q in ledger.list_questions(status="active")]
        summary = finish_sweep(ledger, ids)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False))
            return
        print(f"saturation sweep: {summary['checked']} checked, {summary['clean']} clean, "
              f"{len(summary['under_saturated'])} under-saturated")
        for u in summary["under_saturated"]:
            tags = []
            if u["blocking"]:
                tags.append("blocking=" + ",".join(u["blocking"]))
            if u["warnings"]:
                tags.append("warnings=" + ",".join(u["warnings"]))
            print(f"  {u['question_id']}  {u['score']}/100  {'; '.join(tags)}")
        return

    qid = args.question_id
    if not qid:
        print("provide a question id, or --all to sweep every active forecast")
        return
    report = lint_forecast(ledger, qid)
    if report is None:
        print(f"{qid}: no committed snapshot to lint")
        return
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False))
        return
    d = report.to_dict()
    print(f"saturation {d['score']}/100  {'PASS' if d['passed'] else 'BLOCK'}")
    for v in report.verdicts:
        mark = "ok " if v.passed else ("ERR" if v.severity.blocks else "warn")
        line = f"  [{mark}] {v.rule_id}"
        if not v.passed:
            line += f"  -  {v.message[:90]}"
        print(line)


def _cmd_hooks_list(args: argparse.Namespace) -> None:
    from forecasting.hooks import Severity, resolve_severities
    ledger = _ledger(args)
    question = ledger.get_question(args.question_id) if getattr(args, "question_id", None) else None
    sev = resolve_severities(question, forecast_origin="live")
    if getattr(args, "json", False):
        print(json.dumps({k: v.value for k, v in sev.items()}, ensure_ascii=False))
        return
    print("active hook rules (resolved severity):")
    for rid, s in sev.items():
        print(f"  {s.value:5}  {rid}")


def _cmd_hooks_profiles(args: argparse.Namespace) -> None:
    from forecasting.hooks import HOOK_PROFILES
    for name, sevs in HOOK_PROFILES.items():
        print(f"{name}:")
        for rid, s in sevs.items():
            print(f"  {s.value:5}  {rid}")


def _cmd_hooks_explain(args: argparse.Namespace) -> None:
    from forecasting.hooks.dsl import signal_doc, signal_glossary
    name = getattr(args, "signal", None)
    if name:
        doc = signal_doc(name)
        if doc is None:
            print(f"unknown signal {name!r}. Run `forecast hooks explain` to list them.")
            return
        print(f"{name}\n  {doc}")
        return
    print("signals a user rule can test (name : kind):")
    for n, kind, doc in signal_glossary():
        print(f"  {n}  ({kind})\n      {doc}")


def _cmd_hooks_methods(args: argparse.Namespace) -> None:
    from forecasting.hooks.reasoning import REASONING_METHODS
    print("reasoning-method taxonomy (declare the ones you used in reasoning_methods):")
    for name, doc in REASONING_METHODS.items():
        print(f"  {name}\n      {doc}")


def _hooks_spec_from_file(path: str) -> dict:
    import os
    if not os.path.exists(path):
        raise SystemExit(f"spec file not found: {path}")
    import yaml
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    return raw or {}


def _cmd_hooks_set_severity(args: argparse.Namespace) -> None:
    from forecasting.hooks import store
    try:
        store.set_severity(args.rule_id, args.severity)
        print(f"{args.rule_id} -> {args.severity}")
    except store.HookWriteError as e:
        raise SystemExit(str(e))


def _cmd_hooks_set_profile(args: argparse.Namespace) -> None:
    from forecasting.hooks import store
    try:
        store.set_profile(args.profile)
        print(f"profile -> {args.profile}")
    except store.HookWriteError as e:
        raise SystemExit(str(e))


def _cmd_hooks_enable(args: argparse.Namespace) -> None:
    from forecasting.hooks import store
    try:
        store.enable(args.rule_id)
        print(f"{args.rule_id} enabled (reverted to profile severity)")
    except store.HookWriteError as e:
        raise SystemExit(str(e))


def _cmd_hooks_disable(args: argparse.Namespace) -> None:
    from forecasting.hooks import store
    store.disable(args.rule_id)
    print(f"{args.rule_id} disabled (off)")


def _cmd_hooks_add(args: argparse.Namespace) -> None:
    from forecasting.hooks import store
    try:
        res = store.save_rule(_hooks_spec_from_file(args.spec))
        print(f"saved user rule {res['id']}")
    except store.HookWriteError as e:
        print(f"refused: {e}")
        for i in e.issues:
            print(f"    {i.severity}: {i.field}: {i.message}" + (f"  -> {i.fix}" if i.fix else ""))
        raise SystemExit(1)


def _cmd_hooks_edit(args: argparse.Namespace) -> None:
    from forecasting.hooks import store
    try:
        store.edit_rule(args.rule_id, _hooks_spec_from_file(args.spec))
        print(f"edited user rule {args.rule_id}")
    except store.HookWriteError as e:
        print(f"refused: {e}")
        raise SystemExit(1)


def _cmd_hooks_remove(args: argparse.Namespace) -> None:
    from forecasting.hooks import store
    try:
        store.remove_rule(args.rule_id)
        print(f"removed user rule {args.rule_id}")
    except store.HookWriteError as e:
        raise SystemExit(str(e))


def _cmd_hooks_lint(args: argparse.Namespace) -> None:
    from forecasting.hooks.dsl import RuleSpec, validate_rule
    from forecasting.hooks.engine import load_hook_config
    from forecasting.hooks.loader import load_user_rule_specs
    specs = load_user_rule_specs(load_hook_config())
    if not specs:
        print("no user-defined rules configured (forecasting.hooks.rules / rules_file)")
        return
    known: set[str] = set()
    bad = 0
    for raw in specs:
        spec = RuleSpec.from_dict(raw)
        issues = validate_rule(spec, known_ids=known)
        errs = [i for i in issues if i.severity == "error"]
        if not errs:
            known.add(spec.id)  # mirror the loader: only valid ids count for dedup
        warns = [i for i in issues if i.severity != "error"]
        status = "OK" if not errs else "INVALID"
        if errs:
            bad += 1
        print(f"[{status}] {spec.id or '(no id)'}")
        for i in errs + warns:
            print(f"    {i.severity}: {i.field}: {i.message}" + (f"  -> {i.fix}" if i.fix else ""))
    print(f"\n{len(specs)} rule(s), {bad} invalid")


def _cmd_hooks_preview(args: argparse.Namespace) -> None:
    import os

    from forecasting.hooks.dsl import RuleSpec, compile_rule, validate_rule
    from forecasting.hooks.engine import run_hooks
    from forecasting.hooks.signals import build_context_from_ledger
    from forecasting.hooks.spec import Severity
    ledger = _ledger(args)
    path = args.spec
    if not os.path.exists(path):
        print(f"spec file not found: {path}")
        return
    import yaml
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    spec = RuleSpec.from_dict(raw or {})
    issues = validate_rule(spec)
    errs = [i for i in issues if i.severity == "error"]
    if errs:
        print(f"rule {spec.id or '(no id)'} is INVALID:")
        for i in errs:
            print(f"    {i.field}: {i.message}" + (f"  -> {i.fix}" if i.fix else ""))
        return
    rule = compile_rule(spec)
    would_pass = would_fail = n_a = 0
    failing: list[str] = []
    for q in ledger.list_questions(status="active"):
        try:
            if ledger.get_current_snapshot(q.id) is None:
                continue
            ctx = build_context_from_ledger(ledger, q.id, event="lint")
        except Exception:
            continue
        if not rule.applies(ctx):
            n_a += 1
            continue
        verdict = rule.evaluate(ctx, Severity(spec.severity) if spec.severity in ("off", "warn", "error") else Severity.WARN)
        if verdict.passed:
            would_pass += 1
        else:
            would_fail += 1
            failing.append(q.id)
    if getattr(args, "json", False):
        print(json.dumps({"rule": spec.id, "would_pass": would_pass, "would_fail": would_fail,
                          "not_applicable": n_a, "failing": failing}, ensure_ascii=False))
        return
    print(f"dry-run: {spec.id}  (severity: {spec.severity})")
    print(f"  applies to {would_pass + would_fail} forecasts; WOULD PASS {would_pass}, WOULD "
          f"{'BLOCK' if spec.severity == 'error' else 'WARN'} {would_fail}; n/a {n_a}")
    for qid in failing[:10]:
        print(f"    - {qid}")


def _cmd_doctor(args: argparse.Namespace) -> None:
    report = _build_doctor_report(args)
    pilot_report = report["pilot_report"]
    readiness = report["readiness"]["evidence_status"]
    status = report["status"]
    summary = pilot_report["summary"]
    should_fail = (
        args.require_pilot_ready
        and not report["tester_handoff_ready"]
    ) or (
        args.require_readiness
        and bool(readiness.get("gaps"))
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        if should_fail:
            raise SystemExit(1)
        return

    print(
        f"doctor {report['doctor_status']}: "
        f"pilot {pilot_report['passed_checks']}/{pilot_report['total_checks']} checks, "
        f"readiness {readiness.get('verdict')}"
    )
    print(f"process_version: {report['process_version']}")
    print(f"ledger: {status['ledger_path']}")
    print(
        "book: "
        f"active={status['question_counts'].get('active', 0)} "
        f"reviews={status['review_queue_count']} "
        f"alerts={status['open_alert_count']} "
        f"schedules={status['enabled_scheduled_review_count']}/{status['scheduled_review_count']} "
        f"schedule_runs={summary.get('scheduled_review_run_count', 0)} "
        f"autopilot={status['active_autopilot_policy_count']}/{status['autopilot_policy_count']} "
        f"autopilot_runs={status['autopilot_run_count']} "
        f"pending_proposals={status['pending_autopilot_proposal_count']}"
    )
    print(
        "learning: "
        f"live_scores={summary['score_counts_by_origin'].get('live', 0)} "
        f"postmortems={summary['postmortem_count']} "
        f"lessons={status['active_calibration_lesson_count']}/{status['calibration_lesson_count']} "
        # Labelled: this is the live calibration-eligible cohort's Brier, NOT a
        # pooled all-artifact number. The full by-cohort board prints below.
        f"live_elig_brier={_format_metric(status['calibration_mean_brier'])}"
    )
    board = report.get("cohort_scoreboard")
    if board:
        _print_cohort_scoreboard(board)
    audit = report.get("scores_audit")
    if audit:
        counts = audit.get("counts") or {}
        artifact_n = counts.get("artifact_degenerate_import", 0)
        real_cont = counts.get("real_continuous_miss", 0)
        real_bin = counts.get("real_binary_miss", 0)
        total = sum(counts.values())
        print(
            f"scores audit: {total} pathological row(s) — "
            f"artifact_degenerate_import={artifact_n} "
            f"real_continuous_miss={real_cont} real_binary_miss={real_bin}"
            + (
                "  — propose `forecast scoreboard quarantine` (dry-run)"
                if audit.get("proposed_quarantine")
                else ""
            )
        )
    crux = status.get("crux_promotion") or {}
    print(
        "cruxes: "
        f"promoted={crux.get('promoted_total', 0)} "
        f"(from_panels={crux.get('promoted_from_panels', 0)}) "
        f"unpromoted_panel_cruxes={crux.get('unpromoted_panel_cruxes', 0)}"
        + (
            "  — run `forecast crux backfill --apply`"
            if crux.get("unpromoted_panel_cruxes", 0)
            else ""
        )
    )
    print(f"claim_live_superforecasting: {report['claim_live_superforecasting']}")

    # SLICE 5 fold: one unified "warnings" line that folds all three models —
    # the alert_events backlog (by reason), the saturation/hook issues, and the
    # templated-batch clusters — so there is a single place to see every warning.
    fold = report.get("warnings_fold") or {}
    backlog = fold.get("alert_backlog") or {}
    backlog_groups = backlog.get("groups") or []
    sweep = fold.get("saturation") or {}
    under_saturated = sweep.get("under_saturated") or []
    fold_templated = fold.get("templated_batches") or []
    print(
        "warnings: "
        f"alerts={backlog.get('open_total', 0)} open across {backlog.get('group_count', 0)} reason(s); "
        f"saturation={len(under_saturated)} under/{sweep.get('checked', 0)} checked; "
        f"templated_batches={len(fold_templated)}"
    )
    for g in backlog_groups[:6]:
        tag = g.get("kind", "")
        if not g.get("auto_resolvable", True):
            tag += " NO_AUTO"
        print(f"  - alert x{g.get('count', 0):>3}  {(g.get('reason') or '')[:42]:<42} [{tag}]")
    for u in under_saturated[:4]:
        print(f"  - hook {u.get('question_id')}  {u.get('score')}/100 saturation")

    # Free-tier warning drain: the nightly zero-spend sweep's last result + the live
    # remaining free backlog (a sibling of cron_health).
    fdrain = report.get("free_tier_drain") or {}
    if fdrain:
        last = fdrain.get("last") or {}
        remaining = fdrain.get("remaining_free")
        remaining_text = f"{remaining} free alert(s) remain" if remaining is not None else "backlog unknown"
        if last:
            drained = f"last drain resolved {last.get('resolved', 0)}, errors {last.get('errors', 0)}"
            if last.get("cap_hit"):
                drained += f" (cap {last.get('cap')} hit — run `forecast warnings automode`)"
            print(f"free_tier_drain: {drained}; {remaining_text}")
        else:
            print(f"free_tier_drain: not yet run; {remaining_text}")

    # Gateway due-sweeper: whether the between-nightly-runs sweeper is enabled and
    # what its last tick did (a sibling of free_tier_drain / cron_health).
    rsweep = report.get("review_sweeper") or {}
    if rsweep:
        if not rsweep.get("enabled"):
            print(f"review_sweeper: disabled; {rsweep.get('due_now', 0)} review(s) due now")
        else:
            interval = rsweep.get("interval_minutes")
            due_now = rsweep.get("due_now", 0)
            last = rsweep.get("last") or {}
            if last:
                if last.get("ran"):
                    tail = (
                        f"last sweep refreshed {last.get('refreshed', 0)}, "
                        f"alerts {last.get('alerts', 0)}"
                    )
                else:
                    tail = f"last tick skipped ({last.get('skipped_reason') or 'none due'})"
            else:
                tail = "not yet run"
            print(
                f"review_sweeper: every {interval}m; {due_now} due now; {tail}"
            )

    # Durability: last-backup age (WARN >48h/none) + integrity verdict + counts —
    # the ledger is the whole asset, so this is the line that can't go missing.
    dur = report.get("durability") or {}
    if dur:
        integ_ok = dur.get("integrity_ok")
        integ_txt = "ok" if integ_ok else f"VIOLATIONS ({len(dur.get('violations') or [])})"
        status = dur.get("backup_status")
        last = dur.get("last_backup") or {}
        if status == "missing":
            btxt = "NO BACKUP YET — run `forecast backup run`"
        else:
            age = last.get("age_hours")
            age_txt = f"{age:.1f}h ago" if isinstance(age, (int, float)) else "age unknown"
            warn = "  WARN>48h" if status == "stale" else ""
            btxt = f"last {age_txt} ({last.get('bytes', 0)} bytes){warn}"
        counts = dur.get("counts") or {}
        counts_txt = " ".join(f"{k}={v}" for k, v in counts.items())
        print(f"durability: backup {btxt}; integrity {integ_txt}; {counts_txt}".rstrip("; "))
        for v in (dur.get("violations") or [])[:3]:
            print(f"  - integrity: {v[:80]}")

    # Source diversity (monoculture guard): median distinct sources/question +
    # the single-source share. A median of 1.0 = the whole book reads one source.
    div = report.get("source_diversity") or {}
    if div and div.get("questions_with_evidence"):
        median = div.get("median_sources_per_question")
        pct = div.get("single_source_pct")
        median_txt = f"{median:.1f}" if isinstance(median, (int, float)) else "-"
        pct_txt = f"{pct * 100:.0f}%" if isinstance(pct, (int, float)) else "-"
        warn = "  WARN monoculture" if isinstance(median, (int, float)) and median <= 1.0 else ""
        print(
            f"source_diversity: median {median_txt} sources/question; "
            f"{div.get('single_source_question_count', 0)}/{div['questions_with_evidence']} "
            f"single-source ({pct_txt}){warn}"
        )

    # Second brain: vault health — page counts, rot signals, budget state, and
    # pending operator edits awaiting triage-gated ingestion.
    vh = report.get("vault_health") or {}
    if vh and vh.get("pages"):
        rot_bits = []
        for key in ("orphans", "broken_links", "stale", "contradictions"):
            if vh.get(key):
                rot_bits.append(f"{vh[key]} {key.replace('_', ' ')}")
        over = vh.get("budget_overflows") or {}
        if over:
            rot_bits.append(
                "budget over: "
                + ", ".join(f"{s} +{v.get('over_by')}" for s, v in over.items())
            )
        rot_txt = "; ".join(rot_bits) if rot_bits else "no rot flagged"
        pending = vh.get("operator_edits_pending", 0)
        pending_txt = (
            f"; {pending} operator edit(s) pending ingest" if pending else ""
        )
        print(
            f"vault_health: {vh.get('pages', 0)} pages "
            f"({vh.get('tombstones', 0)} tombstones); {rot_txt}{pending_txt}"
        )

    # Panel-vs-solo ablation: is the panel machinery earning its cost?
    ablation = report.get("panel_vs_solo_ablation")
    if ablation is not None:
        from forecasting.ablation_study import format_ablation_line

        print(format_ablation_line(ablation))

    edge = report.get("deviation_edge")
    if isinstance(edge, dict) and (edge.get("n") or edge.get("n_open")):
        delta = edge.get("mean_brier_delta")
        delta_txt = f"{delta:+.4f}" if isinstance(delta, (int, float)) else "-"
        wr = edge.get("win_rate")
        wr_txt = f"{wr:.0%}" if isinstance(wr, (int, float)) else "-"
        print(
            f"deviation_edge: {edge.get('n', 0)} scored / {edge.get('n_open', 0)} open "
            f"named-edge bets; win-rate {wr_txt}, mean Brier delta {delta_txt} "
            f"[{edge.get('status')}]"
        )
        print(f"  {edge.get('recommendation')}")

    batches = report.get("templated_batches") or []
    if batches:
        flagged = sum(b["count"] for b in batches)
        print(f"templated_batches: {len(batches)} cluster(s), {flagged} live forecasts share a template (review for real per-question reasoning)")
        for b in batches[:5]:
            print(f"  - x{b['count']} method={b['method'][:40] or '(none)'!r} e.g. {b['members'][0]['title']!r}")

    pilot_gaps = [check for check in pilot_report["checks"] if not check["passed"]]
    if pilot_gaps:
        print("pilot_gaps:")
        for check in pilot_gaps[:7]:
            print(
                f"  - {check['id']}: {check['observed']}/{check['required']} "
                f"- {check['recommended_action']}"
            )

    readiness_actions = list(readiness.get("next_actions") or [])
    if readiness_actions:
        print("readiness_gaps:")
        for item in readiness_actions[:7]:
            print(f"  - {item.get('requirement_id')}: {item.get('action')}")

    if not pilot_gaps and not readiness_actions:
        print("next_actions: none")

    if should_fail:
        raise SystemExit(1)


def _cmd_backup_run(args: argparse.Namespace) -> None:
    """`forecast backup run` — take an online backup + integrity check now.

    Thin over the BACKUP job type: enqueues a durable job, waits for it, and prints
    the ``{path, integrity, counts}`` result. Exits nonzero when the backup failed
    or reported integrity violations."""

    from forecasting.jobs.types.backup import read_job, start_job

    spec = {
        "db": getattr(args, "db", None),
        "dest_dir": getattr(args, "dest_dir", None),
        "keep_recent": getattr(args, "keep_recent", None),
        "weekly_weeks": getattr(args, "weekly_weeks", None),
    }
    job_id = start_job(spec, wait=True)
    job = read_job(job_id)
    result = job.get("result") or {}
    integrity = result.get("integrity")
    failed = job.get("status") != "done" or integrity != "ok"

    if getattr(args, "json", False):
        print(json.dumps(job, indent=2, sort_keys=True))
        if failed:
            raise SystemExit(1)
        return

    if job.get("status") != "done":
        print(f"backup failed: {job.get('error') or 'unknown error'}")
        raise SystemExit(1)

    print(f"backup {result.get('path')}  ({result.get('bytes')} bytes)")
    print(f"integrity: {integrity}")
    counts = result.get("counts") or {}
    if counts:
        print("counts: " + " ".join(f"{k}={v}" for k, v in counts.items()))
    retention = result.get("retention") or {}
    if retention.get("pruned_count"):
        print(f"retention: pruned {retention['pruned_count']} old backup(s), {retention.get('kept')} kept")
    if integrity != "ok":
        for v in (result.get("violations") or [])[:5]:
            print(f"  violation: {v}")
        raise SystemExit(1)


def _cmd_backup_list(args: argparse.Namespace) -> None:
    """`forecast backup list` — the existing ledger backups, newest first."""

    ledger = _ledger(args)
    rows = ledger.list_backups(getattr(args, "dest_dir", None))
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, sort_keys=True))
        return
    if not rows:
        print(f"no backups yet in {ledger.default_backup_dir()} — run `forecast backup run`")
        return
    print(f"{len(rows)} backup(s) in {ledger.default_backup_dir()}:")
    for r in rows:
        print(f"  {r['created_at']}  {r['bytes']:>10} bytes  {r['path']}")


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
    ledger = _ledger(args)
    triggers = _parse_update_trigger_args(getattr(args, "update_triggers", None) or [])
    question = ledger.create_question(
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
        decision_owner=getattr(args, "decision_owner", None),
        decision_deadline=getattr(args, "decision_deadline", None),
        action_threshold=getattr(args, "action_threshold", None),
        update_triggers=triggers,
    )
    print(f"created forecast question {question.id}")
    print(f"title: {question.title}")
    print(f"status: {question.status}")
    if question.decision_owner or question.action_threshold or question.update_triggers:
        print(f"decision_owner: {question.decision_owner or '-'}")
        print(f"action_threshold: {question.action_threshold or '-'}")
        if question.update_triggers:
            print(f"update_triggers: {len(question.update_triggers)}")
    else:
        issues = ledger.decision_readiness_issues(question)
        if issues:
            print(f"decision_readiness: {', '.join(issues)}")
            print(
                f"  add: forecast set-decision {question.id} --decision-owner ... "
                "--action-threshold ... --update-trigger ..."
            )
    if args.source_plan or args.apply_source_plan:
        print("")
        _print_source_plan(ledger, question, apply_watch=args.apply_source_plan, limit=12)


def _run_triage_tool(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    """Call the SAME triage tool action the agent uses and return the parsed result.

    The CLI triage group is a thin surface over ``forecast_ledger_tool`` so the
    triage logic (labeler wiring, contested routing, trust gate) lives in exactly
    one place. Prints the structured result and raises SystemExit(1) on a tool error.
    """
    from tools.forecasting_tool import forecast_ledger_tool

    payload = {**payload, "db": getattr(args, "db", None)}
    out = forecast_ledger_tool(payload)
    result = json.loads(out)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("error") or result.get("success") is False:
        raise SystemExit(1)
    return result


def _cmd_triage_label(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {
        "action": "triage_label",
        "persist": not getattr(args, "no_persist", False),
        "limit": getattr(args, "limit", 20),
    }
    if getattr(args, "question_id", None):
        payload["question_id"] = args.question_id
    if getattr(args, "use_watched", False):
        payload["use_watched"] = True
    if getattr(args, "rubric_ref", None):
        payload["rubric_ref"] = args.rubric_ref
    if getattr(args, "model", None):
        payload["model"] = args.model
    if getattr(args, "query", None):
        payload["query"] = args.query
    if getattr(args, "candidates_json", None):
        try:
            payload["candidates"] = json.loads(args.candidates_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--candidates-json is not valid JSON: {exc}")
    _run_triage_tool(args, payload)


def _cmd_triage_contested(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {"action": "triage_contested"}
    if getattr(args, "question_id", None):
        payload["question_id"] = args.question_id
    if getattr(args, "label_ids", None):
        payload["label_ids"] = args.label_ids
    if getattr(args, "disagreement_threshold", None) is not None:
        payload["disagreement_threshold"] = args.disagreement_threshold
    if getattr(args, "verifier_json", None):
        try:
            payload["verifier_labels"] = json.loads(args.verifier_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--verifier-json is not valid JSON: {exc}")
    _run_triage_tool(args, payload)


def _cmd_triage_relabel(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {"action": "relabel_route"}
    if getattr(args, "adjudications_json", None):
        try:
            payload["adjudications"] = json.loads(args.adjudications_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--adjudications-json is not valid JSON: {exc}")
    elif getattr(args, "label_id", None) and getattr(args, "label", None):
        payload["label_id"] = args.label_id
        payload["label"] = args.label
    else:
        raise SystemExit("forecast triage relabel needs LABEL_ID LABEL (or --adjudications-json)")
    _run_triage_tool(args, payload)


def _cmd_triage_trust(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {"action": "triage_trust"}
    if getattr(args, "threshold", None) is not None:
        payload["threshold"] = args.threshold
    if getattr(args, "min_sample", None) is not None:
        payload["min_sample"] = args.min_sample
    _run_triage_tool(args, payload)


def _cmd_triage_set_rubric(args: argparse.Namespace) -> None:
    rubric = {
        "interesting_criteria": args.interesting,
        "uninteresting_criteria": getattr(args, "uninteresting", "") or "",
        "irrelevant_criteria": getattr(args, "irrelevant", "") or "",
        "notes": getattr(args, "notes", "") or "",
    }
    payload = {
        "action": "set_label_rubric",
        "scope_type": getattr(args, "scope_type", "global") or "global",
        "rubric": rubric,
    }
    if getattr(args, "scope_ref", None):
        payload["scope_ref"] = args.scope_ref
    _run_triage_tool(args, payload)


def _cmd_triage_list_rubrics(args: argparse.Namespace) -> None:
    payload: dict[str, Any] = {"action": "list_label_rubrics"}
    if getattr(args, "scope_type", None):
        payload["scope_type"] = args.scope_type
    if getattr(args, "scope_ref", None):
        payload["scope_ref"] = args.scope_ref
    if getattr(args, "all", False):
        payload["active_only"] = False
    _run_triage_tool(args, payload)


def _draft_resolution_criteria(spec: Any, *, model: str | None = None, provider: str | None = None) -> str | None:
    """One bounded, tool-less LLM call drafting auditable resolution criteria for
    the ``onboard --auto`` path (stage 0 of the autonomous pipeline). Fail-open:
    any error (no model configured, provider down, junk reply) returns ``None``
    and the caller falls back to the honest "fix these first" refusal. The draft
    is never trusted — it still passes the full spec validation before commit."""

    try:
        from hermes_cli.config import load_config
        from forecasting.quorum import make_aiagent_runner

        active = model or _resolve_active_model_id(load_config().get("model"))
        if not active:
            return None
        runner = make_aiagent_runner(max_iterations=1, toolsets=(), quiet=True, timeout=120)
        system = (
            "You draft resolution criteria for forecasting questions. Reply with ONE "
            "sentence only — no preamble, no quotes. The sentence must state the "
            "measurable condition, the authoritative source that adjudicates it, and "
            "the deadline, in the form: 'Resolves YES if <measurable condition> per "
            "<authoritative source> on or before <date>; otherwise NO.'"
        )
        user = (
            f'Question: "{spec.title}"\n'
            f"Deadline hint (use it if the question implies none): {spec.close_time or 'end of this year'}\n"
            "Draft the resolution criteria sentence."
        )
        text = (runner(active, system, user) or "").strip().strip('"')
        first_line = text.splitlines()[0].strip() if text.strip() else ""
        # a real criteria sentence is short prose; refuse obvious junk/refusals
        if not first_line or len(first_line) > 500 or "resolves" not in first_line.lower():
            return None
        return first_line
    except Exception:
        return None


def _cmd_onboard(args: argparse.Namespace) -> None:
    from forecasting.question_spec import (
        apply_recommended_defaults,
        recommended_clarifications,
        spec_from_dict,
        spec_quality,
        suggest_resolution_rule,
    )

    ledger = _ledger(args)
    if args.spec:
        with open(args.spec, encoding="utf-8") as fh:
            raw = json.load(fh)
    elif args.prompt:
        raw = {"title": args.prompt, "resolution_criteria": getattr(args, "criteria", None) or ""}
    else:
        raise SystemExit("forecast onboard needs a prompt or --spec FILE")

    spec = spec_from_dict(raw)

    if getattr(args, "auto", False):
        # Accept-defaults autonomous entry point: a single vague sentence becomes a
        # complete, committed, self-refreshing forecast. Apply the recommended
        # default of every gap/error clarification, commit the whole fan-out, then
        # chain research -> base_rate -> update through the SAME gated agent path a
        # manual run uses (no gate is weakened — error-severity issues still block
        # the commit below via spec.commit()).
        spec, applied = apply_recommended_defaults(spec)

        # Stage 0 of the autonomous pipeline: DRAFT the resolution criteria when the
        # bare sentence carries none. accept-defaults rightly refuses to fabricate
        # free text, but --auto already requires an LLM for the research/base_rate/
        # update chain below — so one bounded, tool-less drafting call is what makes
        # "one sentence in, a forecast out" actually true from the CLI. The draft
        # still faces the full spec validation: an unscoreable draft fails the same
        # honest error below, never a weaker commit.
        if not (spec.resolution_criteria or "").strip():
            drafted = _draft_resolution_criteria(spec, model=args.model, provider=args.provider)
            if drafted:
                from dataclasses import replace as _spec_replace

                spec = _spec_replace(spec, resolution_criteria=drafted)
                print(f'  drafted resolution criteria: "{drafted}"')
                # criteria text can pin the horizon — re-apply so close_time upgrades
                # from the end-of-year fallback to the criteria-implied deadline.
                spec, more = apply_recommended_defaults(spec)
                applied += more

        errs = [i for i in spec.errors()]
        if errs:
            # accept-defaults never fabricates past an un-defaultable error (e.g. an
            # unscoreable resolution criteria) — the commit gate is unchanged.
            print("cannot auto-forecast — fix these first:")
            for e in errs:
                print(f"  [error] {e.field}: {e.message}" + (f"  ({e.fix})" if e.fix else ""))
            raise SystemExit(1)

        # Duplicate routing: two lazy prompts of the same sentence must REFRESH the
        # existing question, not fork a rival. Reuse the tool's duplicate ranker — a
        # strong near-duplicate (score >= the warn threshold) routes the SAME stage
        # chain onto the existing id unless --force-new is set.
        from tools.forecasting_tool import _DUPLICATE_WARN_SCORE, _find_possible_duplicates

        duplicates = _find_possible_duplicates(ledger, spec.title)
        top = duplicates[0] if duplicates else None
        strong_dup = top is not None and top["score"] >= _DUPLICATE_WARN_SCORE
        force_new = getattr(args, "force_new", False)
        if strong_dup and not force_new:
            qid = top["id"]
            print(
                f"routed to existing forecast {qid} (\"{top['title']}\") — refreshing that "
                "instead of forking a rival (pass --force-new to create a new question)"
            )
        else:
            if strong_dup:
                print(
                    f"warning: you already track {top['id']} (\"{top['title']}\") — "
                    "committing a new rival question anyway (--force-new)"
                )
            result = spec.commit(ledger)
            qid = result["question_id"]
            print(f"created forecast question {qid} (accepted {len(applied)} defaults)")
            print(f"  watched_sources: {len(result['watched_sources'])}")
            print(f"  reference_classes: {len(result['reference_classes'])}")
            if result["readiness_gaps"]:
                print(f"  readiness gaps (waived): {', '.join(g['field'] for g in result['readiness_gaps'])}")
            # Feed the spine: an auto-path question usually commits with ZERO watched
            # sources, so the deterministic scheduled refresh has nothing to pull.
            # Auto-attach the top recommended watches via the SAME apply seam
            # `forecast sources --apply-watch` uses. Fail-open — a planner hiccup must
            # never block the forecast.
            if not spec.watched_sources and spec.allow_evidence_gathering:
                attached: list[dict[str, Any]] = []
                try:
                    question = ledger.get_question(qid)
                    recs = plan_sources_for_question(question)
                    candidates = [r for r in recs if not r.requires_user_source and r.watch_source][:3]
                    attached, _ = _apply_source_plan_watches(ledger, qid, candidates)
                except Exception:
                    attached = []
                if attached:
                    print(f"  attached {len(attached)} watched source(s) so this refreshes itself:")
                    for row in attached:
                        print(f"    {row['source_type']} {row['source']}")

        def _progress(stage: str, outcome: dict[str, Any]) -> None:
            mark = "committed" if outcome.get("committed") else outcome.get("status", "ran")
            detail = outcome.get("detail")
            line = f"  stage {stage:<10} [{mark}]"
            if outcome.get("forecast_id"):
                line += f" -> {outcome['forecast_id']}"
            if detail:
                line += f"  {detail}"
            print(line)

        print("chaining pipeline stages:")
        chain = run_forecast_chain(
            ledger,
            qid,
            model=args.model,
            provider=args.provider,
            max_iterations=args.max_iterations,
            on_stage=_progress,
        )
        if chain["committed"] and chain["snapshot"]:
            snap = chain["snapshot"]
            print(f"committed forecast {snap['forecast_id']}: {snap['probability_or_distribution']}")
        elif chain["update_blockers"]:
            print(f"forecast NOT committed — update still gated by: {', '.join(chain['update_blockers'])}")
        else:
            print("forecast NOT committed — the agent declined to commit a new snapshot")
        return

    issues = spec.validate()

    if args.commit:
        errs = [i for i in issues if i.severity == "error"]
        if errs:
            print("cannot commit — fix these first:")
            for e in errs:
                print(f"  [error] {e.field}: {e.message}" + (f"  ({e.fix})" if e.fix else ""))
            raise SystemExit(1)
        result = spec.commit(ledger)
        print(f"created forecast question {result['question_id']}")
        print(f"  watched_sources: {len(result['watched_sources'])}")
        print(f"  reference_classes: {len(result['reference_classes'])}")
        if result["readiness_gaps"]:
            print(f"  readiness gaps (waived): {', '.join(g['field'] for g in result['readiness_gaps'])}")
        return

    if args.json:
        print(
            json.dumps(
                {
                    "spec": spec.to_dict(),
                    "issues": [i.to_dict() for i in issues],
                    "recommended_clarifications": recommended_clarifications(spec),
                    "committable": spec.is_committable(),
                    "spec_quality": spec_quality(spec),
                    "suggested_resolution_rule": suggest_resolution_rule(spec),
                },
                indent=2,
            )
        )
        return

    # Human-readable proposal: the draft, its issues, and the clarifications to ask.
    print(f"proposed forecast question: {spec.title or '(untitled)'}")
    print(f"  outcome: {spec.outcome_type}   committable: {spec.is_committable()}")
    for label in ("error", "gap", "warn"):
        for i in (x for x in issues if x.severity == label):
            print(f"  [{label}] {i.field}: {i.message}")
    clarifications = recommended_clarifications(spec)
    if clarifications:
        print("clarify with the user:")
        for c in clarifications:
            choices = f"  [{' / '.join(c['choices'])}]" if c["choices"] else "  (free text)"
            print(f"  - {c['question']}{choices}")
    print("")
    print('fastest: forecast onboard "<your question>" --auto   (accepts every recommended')
    print("         default, drafts auditable criteria, then runs research -> base rate ->")
    print("         committed forecast autonomously; add --criteria to pin your own)")
    print("or edit a spec JSON and commit:  forecast onboard --spec spec.json --commit")
    print("(get the JSON skeleton with:  forecast onboard \"<your question>\" --json)")


def _parse_update_trigger_args(values: list[str]) -> list[Any]:
    """Parse repeated ``--update-trigger`` values into trigger payloads.

    Each value is JSON-decoded if it looks like an object; otherwise treated
    as a free-form mechanism string. Normalization happens downstream in the
    ledger.
    """

    parsed: list[Any] = []
    for raw in values:
        text = (raw or "").strip()
        if not text:
            continue
        if text.startswith("{"):
            try:
                parsed.append(json.loads(text))
                continue
            except json.JSONDecodeError as exc:
                raise SystemExit(f"--update-trigger JSON is invalid: {exc.msg}") from exc
        parsed.append(text)
    return parsed


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


def _cmd_next(args: argparse.Namespace) -> None:
    """Print the desk's VOI ranking — "what should I touch next?". Reads the SAME
    server-side voi scores/reasons the TUI Desk shows (build_workspace_payload), so
    the CLI, the agent, and the surface never disagree on the priority order."""

    from forecasting.dashboard import build_workspace_payload

    ledger = _ledger(args)
    payload = build_workspace_payload(ledger=ledger, include_related=False, include_lessons=False)
    limit = max(1, getattr(args, "limit", None) or 5)
    # The canonical desk-level top-5 rides in the payload; for a deeper --limit we
    # walk the same server-assigned voi.rank over the actionable book (identical
    # ordering, just not truncated to 5).
    forecasts = payload.get("forecasts") or []
    ranked = sorted(
        (f for f in forecasts if (f.get("voi") or {}).get("action") not in (None, "none")),
        key=lambda f: (f.get("voi") or {}).get("rank") or 10**9,
    )[:limit]
    rows = [
        {
            "question_id": f.get("id"),
            "title": f.get("title"),
            "action": (f.get("voi") or {}).get("action"),
            "reason": (f.get("voi") or {}).get("reason"),
            "score": (f.get("voi") or {}).get("score"),
            "rank": (f.get("voi") or {}).get("rank"),
        }
        for f in ranked
    ]
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, sort_keys=True))
        return
    print(PRODUCT_NAME)
    print("next best actions — value of information (what to touch next)")
    if not rows:
        print("nothing pressing: the book is fresh, sourced, and away from resolution.")
        return
    for index, row in enumerate(rows, start=1):
        score = row.get("score")
        score_text = f"{float(score):.2f}" if isinstance(score, (int, float)) else "-"
        print(f"{index}. [{row.get('action') or '-'}] {row.get('title') or row.get('question_id') or '-'}  (voi {score_text})")
        if row.get("reason"):
            print(f"   {row['reason']}")
        print(f"   forecast show {row.get('question_id')}")


def _cmd_search(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    query = " ".join(args.query).strip()
    matches = search_forecasts(
        ledger,
        query,
        status=args.status,
        domain=args.domain,
        topic=args.topic,
        limit=args.limit,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "query": query,
                    "status": args.status,
                    "domain": args.domain,
                    "topic": args.topic,
                    "matches": [match_to_dict(match) for match in matches],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    if not matches:
        print("No matching forecast questions found.")
        return
    print("FORECAST SEARCH")
    print(f"query: {query}")
    print("ID             Status     P(now)    AsOf                 Delta    Close                Domain     Score  Fields        Title")
    for match in matches:
        question = match.question
        snapshot = match.current_snapshot
        probability = _format_probability(snapshot.probability_or_distribution) if snapshot else "-"
        as_of = snapshot.as_of if snapshot else "-"
        delta = _format_delta(_question_delta(ledger, question.id))
        close = question.close_time or "-"
        domain = question.domain or "-"
        fields = ",".join(match.matched_fields[:3]) or "-"
        print(
            f"{question.id:<14} {question.status:<10} {probability:<9} {as_of:<20} "
            f"{delta:<8} {close:<20} {domain:<10} {match.score:<6} "
            f"{_truncate(fields, 13):<13} {question.title}"
        )
        for field, snippet in list(match.snippets.items())[:2]:
            print(f"  {field}: {snippet}")
        print(f"  open: forecast show {question.id}")


def _cmd_set_decision(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    triggers: Any = None
    if args.clear_triggers:
        triggers = []
    elif args.update_triggers is not None:
        triggers = _parse_update_trigger_args(args.update_triggers)
    question = ledger.update_question_decision(
        args.id,
        decision_owner=args.decision_owner,
        decision_deadline=args.decision_deadline,
        action_threshold=args.action_threshold,
        update_triggers=triggers,
    )
    print(f"question: {question.id}")
    print(f"decision_owner: {question.decision_owner or '-'}")
    print(f"decision_deadline: {question.decision_deadline or '-'}")
    print(f"action_threshold: {question.action_threshold or '-'}")
    print(f"update_triggers: {len(question.update_triggers)}")
    issues = ledger.decision_readiness_issues(question)
    if issues:
        print(f"decision_readiness: {', '.join(issues)}")
    else:
        print("decision_readiness: ready")


def _cmd_show(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    args.id = _resolve_question_id(ledger, args.id)
    question = ledger.get_question(args.id)
    snapshots = ledger.list_snapshots(args.id)
    evidence = ledger.list_evidence(args.id)
    baselines = ledger.list_baseline_comparisons(args.id)
    resolution = ledger.get_latest_resolution(args.id)
    print(f"{question.title}")
    print(f"id: {question.id}")
    print(f"status: {question.status}")
    print(f"domain: {question.domain or '-'}")
    print(f"outcome: {question.outcome_space.type} {question.outcome_space.choices}")
    print(f"close_time: {question.close_time or '-'}")
    print(f"resolution_time: {question.resolution_time or '-'}")
    print(f"resolution_criteria: {question.resolution_criteria}")
    if (
        question.decision_owner
        or question.decision_deadline
        or question.action_threshold
        or question.update_triggers
    ):
        print()
        print("decision_card:")
        print(f"  owner: {question.decision_owner or '-'}")
        print(f"  deadline: {question.decision_deadline or '-'}")
        print(f"  action_threshold: {question.action_threshold or '-'}")
        if question.update_triggers:
            print(f"  update_triggers: {len(question.update_triggers)}")
            for trigger in question.update_triggers[:5]:
                line = trigger.get("mechanism", "-")
                if trigger.get("threshold"):
                    line += f" [{trigger['threshold']}]"
                if trigger.get("action"):
                    line += f" -> {trigger['action']}"
                print(f"    - {line}")
        readiness = ledger.decision_readiness_issues(question)
        if readiness:
            print(f"  decision_readiness: {', '.join(readiness)}")
    print()
    current = ledger.get_current_snapshot(args.id)
    if current:
        print("current_forecast:")
        print(f"  id: {current.forecast_id}")
        print(f"  as_of: {current.as_of}")
        print(f"  probability: {_format_probability(current.probability_or_distribution)}")
        print(f"  confidence: {current.confidence if current.confidence is not None else '-'}")
        print(f"  origin: {current.forecast_origin}")
        print(f"  rationale: {current.rationale}")
        if current.reasons_up:
            print("  reasons_up:")
            for reason in current.reasons_up:
                print(f"    - {reason}")
        if current.reasons_down:
            print("  reasons_down:")
            for reason in current.reasons_down:
                print(f"    - {reason}")
        if current.change_my_mind:
            print("  change_my_mind:")
            for reason in current.change_my_mind:
                print(f"    - {reason}")
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
    print(f"baseline_comparisons: {len(baselines)}")
    if resolution:
        print(f"resolution: {resolution.outcome} ({resolution.resolution_status})")


def _write_analyst_brief(
    ledger: Any,
    question_id: str,
    snapshot: Any,
    *,
    previous: Any | None = None,
    evidence_only: bool = False,
    announce: bool = True,
) -> dict[str, Any] | None:
    """Generate + persist an analyst brief for a committed snapshot, then announce.

    Thin CLI wrapper over :func:`forecasting.writeup.write_brief` (best-effort,
    never raises) that prints the headline so the user sees the note was written.
    """

    try:
        from forecasting.writeup import write_brief

        record = write_brief(
            ledger,
            question_id,
            snapshot,
            previous=previous,
            evidence_only=evidence_only,
        )
        if record and announce:
            headline = record.get("headline") or record.get("body", "")
            if headline:
                print(f"analyst note: {headline[:80]}")
        return record
    except Exception:
        return None


def _write_retrospective(
    ledger: Any,
    question_id: str,
    *,
    score: Any | None = None,
    announce: bool = True,
) -> dict[str, Any] | None:
    """Generate + persist the resolution retrospective, then announce. Best-effort."""

    try:
        from forecasting.writeup import write_retrospective

        record = write_retrospective(ledger, question_id, score=score)
        if record and announce:
            headline = record.get("headline") or record.get("body", "")
            if headline:
                print(f"retrospective: {headline[:80]}")
        return record
    except Exception:
        return None


def _cmd_update(args: argparse.Namespace) -> None:
    components = _json_arg(args.component_json, "component-json")
    ledger = _ledger(args)
    question = ledger.get_question(args.id)
    rationale = _joined_arg(args.rationale)
    panel_estimates = _load_panel_estimates(args)
    panel_run_record: dict[str, Any] | None = None
    has_panel = panel_estimates is not None
    has_payload = (
        any(
            value is not None
            for value in (args.probability, args.numeric_value, args.distribution_json)
        )
        or bool(components)
        or has_panel
    )
    non_citation_update_fields = [
        rationale is not None,
        args.as_of is not None,
        args.confidence is not None,
        args.method is not None,
        bool(args.key_assumptions),
        bool(args.assumption_refs),
        bool(args.reference_class_refs),
        bool(args.evidence_refs),
        args.stale_evidence_days != 30,
        args.ack_stale_evidence,
        bool(args.model_run_refs),
        args.forecast_origin != "live",
        args.agent_model is not None,
        args.prompt_version is not None,
        args.protocol_version is not None,
        args.toolset_version is not None,
        bool(args.source_snapshot_refs),
        bool(getattr(args, "reasons_up", None)),
        bool(getattr(args, "reasons_down", None)),
        bool(getattr(args, "change_my_mind", None)),
        # NOTE: require_structured_reasoning / require_citations are now policies
        # that default ON for live forecasts (BooleanOptionalAction), so they no
        # longer signal "the user wants to save" — they're deliberately excluded
        # from update-intent detection. require_decision_readiness stays opt-in.
        getattr(args, "require_decision_readiness", False),
        args.evidence_cutoff is not None,
        args.backtest_run_id is not None,
        args.calibration_ineligible,
        args.calibration_weight != 1.0,
        bool(args.calibration_lesson_refs),
        args.calibration_adjustment_json != "{}",
        # NOTE: use_active_lessons now DEFAULTS ON (BooleanOptionalAction), so it no
        # longer signals "the user wants to save" — like require_citations, it is
        # excluded from update-intent detection. A bare `forecast update <id>` stays
        # a no-op inspection.
        args.preview,
    ]
    # require_citations now defaults ON for live forecasts, so it is no longer a
    # save-intent signal either; intent is a probability payload or a real content
    # change. A bare `forecast update <id>` stays a no-op inspection.
    update_fields = [has_payload, *non_citation_update_fields]
    if not any(update_fields):
        previous = ledger.get_current_snapshot(args.id)
        print(f"question: {question.id}")
        print(f"title: {question.title}")
        probability = _format_probability(previous.probability_or_distribution) if previous else "-"
        print(f"current_probability: {probability}")
        print(f"current_as_of: {previous.as_of if previous else '-'}")
        print(f"current_confidence: {_format_optional_float(previous.confidence) if previous else '-'}")
        if args.require_citations:
            print("citation_policy: required on next saved update")
            print(
                f"add: forecast update {args.id} --probability <p> --rationale <why> "
                "--evidence-ref <ref> --require-citations"
            )
        else:
            print(f"add: forecast update {args.id} --probability <p> --rationale <why>")
        print("probability unchanged")
        return
    if has_panel:
        panel_run_record = ledger.record_panel_run(
            question_id=args.id,
            estimates=panel_estimates,
            aggregation_method=getattr(args, "panel_method", "trimmed_geomean_odds"),
            trim=getattr(args, "panel_trim", 1),
            triggered_by=getattr(args, "panel_triggered_by", "manual"),
        )
        if args.probability is None and args.numeric_value is None and args.distribution_json is None:
            args.probability = panel_run_record["aggregate_probability"]
        if not components:
            components = {
                "components": [
                    {
                        "name": estimate["perspective"],
                        "probability": estimate["probability"],
                        "weight": estimate["weight"],
                        "source": f"panel:{estimate['perspective']}",
                    }
                    for estimate in panel_run_record["estimates"]
                    if not estimate.get("trimmed")
                ]
            }
        if args.method is None:
            args.method = panel_run_record["aggregation_method"]
    payload = _probability_payload(args, components)
    calibration_adjustment = _json_arg(args.calibration_adjustment_json, "calibration-adjustment-json")
    calibration_lesson_refs = list(args.calibration_lesson_refs)
    # Measured-bias correction applies BY DEFAULT for LIVE commits (S7);
    # --no-use-active-lessons opts out. backtest/imported_baseline are never auto-
    # adjusted (the live-derived correction would contaminate the closed-book
    # benchmark) — pass --use-active-lessons to opt in. Exploratory scratchpad
    # commits are never calibration-scored, so they are left untouched.
    # apply_active_lesson_adjustments records raw_probability before adjusting, so
    # net movement stays auditable.
    if should_apply_active_lessons(args.use_active_lessons, args.forecast_origin):
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
    if not rationale:
        raise SystemExit("forecast update requires --rationale when saving a snapshot")
    # An inline panel (--panel-estimates-json) IS the deliberative panel, so it
    # satisfies the panel formality; otherwise honor an explicit --panel-run-ref.
    panel_run_ref = (
        panel_run_record["id"]
        if panel_run_record is not None
        else getattr(args, "panel_run_ref", None)
    )
    snapshot = ledger.create_snapshot(
        question_id=args.id,
        probability_or_distribution=payload,
        rationale=rationale,
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
        stale_evidence_reason=args.stale_evidence_reason,
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
        reasons_up=getattr(args, "reasons_up", None) or None,
        reasons_down=getattr(args, "reasons_down", None) or None,
        change_my_mind=getattr(args, "change_my_mind", None) or None,
        require_structured_reasoning=getattr(args, "require_structured_reasoning", False),
        require_decision_readiness=getattr(args, "require_decision_readiness", False),
        require_panel=getattr(args, "require_panel", False),
        panel_run_ref=panel_run_ref,
        panel_skipped_reason=getattr(args, "panel_skipped_reason", None),
        outcome_paths=_parse_outcome_paths(getattr(args, "outcome_paths", None)),
        require_outcome_paths=getattr(args, "require_outcome_paths", False),
        # Record which related forecasts informed this one (server-side provenance).
        metadata={"cross_refs": _xrefs} if (_xrefs := ledger.build_cross_refs(args.id)) else None,
    )
    # create_snapshot links panel_run_ref itself; no separate attach needed.
    print(f"created forecast snapshot {snapshot.forecast_id}")
    print(f"question: {snapshot.question_id}")
    print(f"as_of: {snapshot.as_of}")
    print(f"probability: {_format_probability(snapshot.probability_or_distribution)}")
    if previous is not None:
        delta = _probability_delta(previous.probability_or_distribution, snapshot.probability_or_distribution)
        if delta is not None:
            print(f"previous_probability: {_format_probability(previous.probability_or_distribution)}")
            print(f"delta: {delta:+.3f}")
    if panel_run_record is not None:
        _print_panel_summary(panel_run_record)
    if components:
        _print_component_drivers(components, snapshot.probability_or_distribution)
    _print_calibration_adjustment_summary(calibration_lesson_refs, calibration_adjustment)
    # Standard step of the update process: write a time-indexed analyst brief for
    # the snapshot we just committed. Best-effort, after the ledger write.
    _write_analyst_brief(ledger, args.id, snapshot, previous=previous)
    _maybe_autorun_quorum(
        ledger, args.id, snapshot=snapshot,
        has_panel=panel_run_ref is not None,
        has_prior_snapshot=previous is not None,
        forecast_origin=args.forecast_origin,
    )


def _maybe_autorun_quorum(
    ledger: "ForecastLedger",
    question_id: str,
    *,
    snapshot: Any,
    has_panel: bool,
    has_prior_snapshot: bool,
    forecast_origin: str | None,
) -> None:
    """AUTO-RUN a quorum (detached) when one is auto-indicated but none attached.

    Thin CLI wrapper over :func:`forecasting.quorum_autorun.maybe_autorun_quorum` —
    the shared seam every commit surface uses (the agent tool's
    ``update_forecast`` calls the same function, so the autonomous paths get the
    same multi-model fusion a hand-typed ``forecast update`` does) — printing its
    progress lines. Fail-open by construction: the shared helper never raises.
    """

    from forecasting.quorum_autorun import maybe_autorun_quorum

    maybe_autorun_quorum(
        ledger,
        question_id,
        snapshot=snapshot,
        has_panel=has_panel,
        has_prior_snapshot=has_prior_snapshot,
        forecast_origin=forecast_origin,
        notify=print,
    )


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


def _cmd_import_packet(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    source_label = "stdin"
    try:
        if args.source == "-":
            text = sys.stdin.read()
        else:
            path = Path(args.source).expanduser()
            source_label = str(path)
            text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ForecastingError(f"could not read forecast packet {source_label}: {exc}") from exc
    try:
        packet = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ForecastingError(f"forecast packet is not valid JSON: {source_label}") from exc
    if not isinstance(packet, dict):
        raise ForecastingError(f"forecast packet must be a JSON object: {source_label}")

    summary = ledger.import_packet(packet, conflict=args.conflict)
    summary["source"] = source_label
    if args.json:
        print(json_dumps(summary))
        return
    print("imported forecast packet")
    print(f"source: {source_label}")
    print(f"conflict: {summary['conflict']}")
    print(f"imported_total: {summary['imported_total']}")
    for label, count in summary["imported"].items():
        print(f"{label}: {count}")
    print(f"skipped_existing: {summary['skipped_existing']}")
    print(f"replaced_existing: {summary['replaced_existing']}")
    print(f"duplicates_in_packet: {summary['duplicates_in_packet']}")


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
        _print_imported_benchmark_dataset(dataset, source=args.source)
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
        _print_imported_benchmark_dataset(dataset, source=args.source)
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
        _print_imported_benchmark_dataset(dataset, source=args.source)
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
        _print_imported_benchmark_dataset(dataset, source=args.source)
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
        _print_imported_benchmark_dataset(
            dataset,
            source=args.source,
            label="imported tournament benchmark dataset",
        )
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
        keywords = _cli_filter_terms(args.keywords)
        exclude_keywords = _cli_filter_terms(args.exclude_keywords)
        items = load_news_feed_items(
            args.source,
            limit=args.limit,
            since=args.since,
            keywords=keywords,
            exclude_keywords=exclude_keywords,
            dedupe=args.dedupe,
        )
        triage_metadata = _news_triage_metadata(args)
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
                        "dedupe": bool(args.dedupe),
                        **triage_metadata,
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
    if args.import_kind == "githubrepo":
        if not args.question_id:
            raise SystemExit("forecast import githubrepo requires --question")
        snapshots = load_github_repository_snapshots(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for snapshot in snapshots:
            stars = snapshot.stargazers_count if snapshot.stargazers_count is not None else "unknown"
            forks = snapshot.forks_count if snapshot.forks_count is not None else "unknown"
            open_issues = snapshot.open_issues_count if snapshot.open_issues_count is not None else "unknown"
            summary = (
                f"GitHub repository {snapshot.repo}: {stars} stars, {forks} forks, "
                f"{open_issues} open issues; default branch {snapshot.default_branch or 'unknown'}; "
                f"language {snapshot.language or 'unknown'}."
            )
            if snapshot.description:
                summary = f"{summary} Description: {snapshot.description}"
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=snapshot.html_url or snapshot.url or f"GitHub:{snapshot.repo}",
                    source_url=snapshot.html_url or snapshot.url,
                    source_name=snapshot.source_name,
                    source_type="adapter:githubrepo",
                    published_at=snapshot.updated_at or snapshot.pushed_at or snapshot.created_at,
                    available_at=snapshot.updated_at or snapshot.pushed_at or snapshot.created_at or args.as_of,
                    claim=f"GitHub repository snapshot: {snapshot.repo} {stars} stars {forks} forks",
                    summary=summary,
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "githubrepo",
                        "repo": snapshot.repo,
                        "repo_id": snapshot.repo_id,
                        "owner_login": snapshot.owner_login,
                        "description": snapshot.description,
                        "language": snapshot.language,
                        "default_branch": snapshot.default_branch,
                        "visibility": snapshot.visibility,
                        "license_spdx_id": snapshot.license_spdx_id,
                        "topics": snapshot.topics,
                        "archived": snapshot.archived,
                        "disabled": snapshot.disabled,
                        "fork": snapshot.fork,
                        "stargazers_count": snapshot.stargazers_count,
                        "watchers_count": snapshot.watchers_count,
                        "forks_count": snapshot.forks_count,
                        "open_issues_count": snapshot.open_issues_count,
                        "subscribers_count": snapshot.subscribers_count,
                        "network_count": snapshot.network_count,
                        "created_at": snapshot.created_at,
                        "updated_at": snapshot.updated_at,
                        "pushed_at": snapshot.pushed_at,
                        "api_base_url": args.api_base_url,
                        "raw": snapshot.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} githubrepo evidence item(s)")
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
    if args.import_kind == "imf":
        if not args.question_id:
            raise SystemExit("forecast import imf requires --question")
        observations = load_imf_datamapper_observations(
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
                    source_or_note=observation.source_url or f"IMF:{observation.indicator}/{observation.country}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:imf",
                    published_at=observation.published_at,
                    available_at=observation.published_at or args.as_of,
                    claim=(
                        f"{observation.indicator}/{observation.country} "
                        f"{observation.observation_date}: {observation.value}"
                    ),
                    summary=(
                        f"IMF DataMapper observation for {observation.country_name or observation.country} "
                        f"{observation.indicator_name or observation.indicator} "
                        f"on {observation.observation_date}: {observation.value}."
                    ),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "imf",
                        "indicator": observation.indicator,
                        "indicator_name": observation.indicator_name,
                        "country": observation.country,
                        "country_name": observation.country_name,
                        "observation_date": observation.observation_date,
                        "value": observation.value,
                        "api_base_url": args.api_base_url,
                        "raw": observation.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} imf evidence item(s)")
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
    if args.import_kind == "ckan":
        if not args.question_id:
            raise SystemExit("forecast import ckan requires --question")
        datasets = load_ckan_datasets(
            args.source,
            limit=args.limit,
            since=args.since,
            api_base_url=args.api_base_url,
        )
        evidence_items = []
        for dataset in datasets:
            tags = ", ".join(dataset.tags[:6])
            resource_count = len(dataset.resources)
            summary_parts = [
                f"CKAN dataset from {dataset.portal}: {dataset.title}.",
                f"Metadata updated {dataset.metadata_modified or dataset.metadata_created or 'unknown time'}.",
            ]
            if dataset.notes:
                summary_parts.append(dataset.notes)
            if dataset.organization:
                summary_parts.append(f"Organization: {dataset.organization}.")
            if tags:
                summary_parts.append(f"Tags: {tags}.")
            if resource_count:
                summary_parts.append(f"Resources: {resource_count}.")
            evidence_items.append(
                ledger.add_evidence(
                    question_id=args.question_id,
                    source_or_note=dataset.source_url or f"CKAN:{dataset.portal}/{dataset.name or dataset.package_id}",
                    source_url=dataset.source_url,
                    source_name=dataset.source_name,
                    source_type="adapter:ckan",
                    published_at=dataset.metadata_modified or dataset.metadata_created,
                    available_at=dataset.metadata_modified or dataset.metadata_created or args.as_of,
                    claim=f"CKAN dataset: {dataset.portal} {dataset.title}",
                    summary=" ".join(summary_parts),
                    reliability_rating=args.reliability,
                    relevance_rating=args.relevance,
                    stance="context",
                    claim_type=args.claim_type,
                    metadata={
                        "adapter": "ckan",
                        "portal": dataset.portal,
                        "package_id": dataset.package_id,
                        "name": dataset.name,
                        "url": dataset.url,
                        "organization": dataset.organization,
                        "groups": dataset.groups,
                        "tags": dataset.tags,
                        "license_title": dataset.license_title,
                        "metadata_created": dataset.metadata_created,
                        "metadata_modified": dataset.metadata_modified,
                        "resource_count": resource_count,
                        "resources": dataset.resources,
                        "api_base_url": args.api_base_url,
                        "raw": dataset.raw,
                    },
                )
            )
        print(f"captured {len(evidence_items)} ckan evidence item(s)")
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
            as_of=getattr(args, "as_of", None),
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


def _print_imported_benchmark_dataset(
    dataset: dict[str, Any],
    *,
    source: str | None = None,
    label: str = "imported benchmark dataset",
) -> None:
    evidence = build_benchmark_evidence_profile(
        f"imported:{dataset['id']}",
        dataset.get("cases") or [],
    )
    families = ", ".join(evidence.get("source_families") or []) or "-"
    print(f"{label} {dataset['id']}")
    print(f"name: {dataset['name']}")
    print(f"cases: {dataset['case_count']}")
    print(f"provenance: {evidence.get('provenance') or '-'}")
    print(f"source_families: {families}")
    if source:
        print(f"source: {source}")
    print(f"run: forecast backtest imported:{dataset['id']}")


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
    if args.plan and not args.question_id:
        raise SystemExit("forecast sources --plan requires --question <id>")
    if args.search_watched and not args.question_id:
        raise SystemExit("forecast sources --search-watched requires --question <id>")
    if args.search_watched and args.apply_watch:
        raise SystemExit("forecast sources --search-watched uses existing watches; run --apply-watch first if needed")
    if args.question_id:
        ledger = _ledger(args)
        question = ledger.get_question(args.question_id)
        if args.search_watched:
            result = search_watched_text_sources(
                ledger,
                question.id,
                query=args.query,
                limit=args.limit,
                since=args.since,
            )
            captured = (
                capture_watched_text_candidates(ledger, question.id, result.candidates, limit=args.limit)
                if args.capture_candidates
                else []
            )
            if args.json:
                payload = result.to_dict()
                payload["captured_candidates"] = [item.to_dict() for item in captured]
                print(json.dumps(payload, indent=2, sort_keys=True))
                return
            _print_watched_text_source_search(result, captured=[item.to_dict() for item in captured])
            return
        recommendations = plan_sources_for_question(question, limit=args.limit)
        if args.json:
            print(
                json.dumps(
                    {
                        "question_id": question.id,
                        "title": question.title,
                        "source_plan": [item.to_dict() for item in recommendations],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        _print_source_plan(
            ledger,
            question,
            recommendations=recommendations,
            apply_watch=args.apply_watch,
            limit=args.limit,
        )
        return
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


def _print_watched_text_source_search(
    result: WatchedTextSourceSearchResult,
    *,
    captured: list[dict[str, Any]] | None = None,
) -> None:
    captured = captured or []
    print(f"Watched text source search for {result.question_id}")
    print(f"query: {result.query or '-'}")
    print(f"searched_sources: {result.searched_sources}")
    print(f"candidates: {len(result.candidates)}")
    print("probability_unchanged: true")
    if result.errors:
        print(f"source_errors: {len(result.errors)}")
        for error in result.errors[:5]:
            print(f"  {error.get('watched_source_id')}: {error.get('error')}")
    if not result.candidates:
        print("No matching watched RSS/Atom evidence candidates.")
        print("Run `forecast sources --question <id> --apply-watch` to add concrete watched sources first.")
        return

    print("")
    print("Rank  Score  Published    Materiality Direction  Source                         Title")
    for index, candidate in enumerate(result.candidates, start=1):
        source = candidate.source_label[:28]
        title = candidate.title if len(candidate.title) <= 72 else f"{candidate.title[:69]}..."
        print(
            f"{index:<5} {candidate.relevance_score:<6} "
            f"{_short_date(candidate.published_at):<12} "
            f"{candidate.materiality:<11} {candidate.direction:<10} "
            f"{source:<30} {title}"
        )
        if candidate.matched_terms:
            print(f"  matched: {', '.join(candidate.matched_terms[:8])}")
        if candidate.url:
            print(f"  url: {candidate.url}")
        print(f"  import: {candidate.import_command}")

    if not captured:
        print("")
        print("Capture candidates with --capture-candidates; forecast probabilities only change via explicit updates.")
        return

    print("")
    print(f"captured_candidates: {len([item for item in captured if item.get('evidence')])}")
    skipped = [item for item in captured if item.get("skipped_reason")]
    if skipped:
        print(f"skipped_candidates: {len(skipped)}")
    for item in captured:
        evidence = item.get("evidence")
        if evidence:
            print(f"  {evidence['id']}: {item['candidate']['title']}")
        elif item.get("skipped_reason"):
            print(f"  skipped: {item['skipped_reason']}")


def _short_date(value: str | None) -> str:
    return str(value or "-")[:10]


def _print_source_plan(
    ledger: ForecastLedger,
    question,
    *,
    recommendations: list[SourceRecommendation] | None = None,
    apply_watch: bool = False,
    limit: int | None = None,
) -> None:
    plan = recommendations if recommendations is not None else plan_sources_for_question(question, limit=limit)
    if limit is not None:
        plan = plan[: max(int(limit), 0)]
    print(f"Source plan for {question.id}: {question.title}")
    if not plan:
        print("No source recommendations found.")
        return
    print("ID                         Label                                  Priority    Role                    Type    Source")
    for item in plan:
        source = item.watch_source or item.source
        source_display = source if len(source) <= 64 else f"{source[:61]}..."
        label = item.label if len(item.label) <= 38 else f"{item.label[:35]}..."
        print(
            f"{item.id:<26} {label:<39} {item.priority:<11} "
            f"{item.role:<23} {item.source_type:<7} {source_display}"
        )
        if item.keywords:
            print(f"  filters: keywords={', '.join(item.keywords)}")
        print(f"  why: {item.rationale}")
        if item.import_command:
            print(f"  import: {item.import_command}")
        if item.watch_command:
            print(f"  watch: {item.watch_command}")
        elif item.requires_user_source:
            print("  watch: add a concrete source before applying this recommendation")
    if not apply_watch:
        return
    created, skipped = _apply_source_plan_watches(ledger, question.id, plan)
    print(f"applied_watches: {len(created)}")
    if skipped:
        print(f"skipped_watches: {len(skipped)}")
    for row in created:
        print(f"  {row['id']}: {row['source_type']} {row['source']}")


def _apply_source_plan_watches(
    ledger: ForecastLedger,
    question_id: str,
    recommendations: list[SourceRecommendation],
) -> tuple[list[dict[str, Any]], list[SourceRecommendation]]:
    existing_sources = {
        row["source"]
        for row in ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status=None)
    }
    created: list[dict[str, Any]] = []
    skipped: list[SourceRecommendation] = []
    for item in recommendations:
        if item.requires_user_source or not item.watch_source or item.source_type not in WATCH_SOURCE_TYPES:
            skipped.append(item)
            continue
        if item.watch_source in existing_sources:
            skipped.append(item)
            continue
        metadata = _source_plan_watch_metadata(item)
        row = ledger.add_watched_source(
            scope_type="question",
            scope_ref=question_id,
            source=item.watch_source,
            source_type=item.source_type,
            metadata=metadata,
        )
        existing_sources.add(item.watch_source)
        created.append(row)
    return created, skipped


def _source_plan_watch_metadata(item: SourceRecommendation) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_plan_id": item.id,
        "source_plan_label": item.label,
        "role": item.role,
        "priority": item.priority,
        "materiality": item.materiality,
    }
    if item.keywords or item.exclude_keywords:
        metadata["relevance_filters"] = {
            "keywords": list(item.keywords),
            "exclude_keywords": list(item.exclude_keywords),
        }
    if item.source_type in {"rss", "gdelt"}:
        metadata["news_triage"] = {
            "materiality": item.materiality,
            "role": item.role,
            "no_silent_probability_mutation": True,
        }
    return metadata


def _cmd_research(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    current = ledger.get_current_snapshot(args.id)
    if not args.sources:
        evidence = ledger.list_evidence(args.id)
        new_items = _new_evidence_items(evidence, current)
        print(f"evidence_count: {len(evidence)}")
        print(f"new_since_current_forecast: {len(new_items)}")
        print(_research_change_summary(evidence, current))
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
    new_items = _new_evidence_items(created, current)
    print(f"captured {len(created)} evidence item(s)")
    print(f"new_since_current_forecast: {len(new_items)}")
    print(_research_change_summary(created, current))
    for item in created:
        print(
            f"{item.id} available_at={item.available_at} stance={item.stance} "
            f"claim_type={item.claim_type} reliability={_format_optional_float(item.reliability_rating)} "
            f"relevance={_format_optional_float(item.relevance_rating)}"
        )
    print("probability unchanged")


def _cmd_base_rate(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    add_fields = {
        "name": args.name,
        "inclusion_criteria": args.inclusion_criteria,
        "base_rate": args.base_rate,
    }
    if not any(value is not None for value in add_fields.values()):
        question = ledger.get_question(args.id)
        rows = ledger.list_reference_classes(args.id)
        print(f"reference_classes: {len(rows)}")
        if rows:
            print("ID             Status      BaseRate  Name")
            for row in rows[-5:]:
                print(
                    f"{row['id']:<14} {row['status']:<11} "
                    f"{_format_optional_float(row['base_rate']):<9} {row['name']}"
                )
        domain = question.domain or "the question domain"
        topic = question.topics[0] if question.topics else "the main outcome driver"
        horizon = question.close_time or question.resolution_time or "the target horizon"
        suggested_name = f"Comparable {domain} cases for {topic}"
        suggested_inclusion = (
            f"Resolved {domain} cases with {question.outcome_space.type} outcomes, "
            f"similar resolution criteria, and timing comparable to {horizon}."
        )
        suggested_exclusion = (
            "Exclude cases with materially different base populations, outcome definitions, "
            "or resolution sources."
        )
        print("suggested_reference_class:")
        print(f"name: {suggested_name}")
        print(f"inclusion_criteria: {suggested_inclusion}")
        print(f"exclusion_criteria: {suggested_exclusion}")
        print("estimate_next: compute numerator/denominator from timestamped evidence before saving a base rate")
        print(
            "add: forecast base-rate "
            f"{args.id} --name <name> --inclusion-criteria <criteria> --base-rate <p>"
        )
        print("probability unchanged")
        return
    missing = [name for name, value in add_fields.items() if value is None]
    if missing:
        raise SystemExit(
            "base-rate add requires --name, --inclusion-criteria, and --base-rate "
            f"(missing: {', '.join(missing)})"
        )
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


def _cmd_bayes(args: argparse.Namespace) -> None:
    from forecasting.bayes_toolkit import (
        BAYES_ACTIONS,
        ensure_industry_backends,
        run_bayes_action,
    )

    action = (args.bayes_action or "").strip()
    if not action:
        print("Bayesian scratchpad actions:")
        for name in sorted(BAYES_ACTIONS):
            print(f"  {name}: {BAYES_ACTIONS[name]}")
        print("\nusage: forecast bayes <action> --input '<json payload>' [--json]")
        print("example: forecast bayes lr_update --input '{\"prior_p\":0.62,\"lrs\":[0.85,0.7,1.25]}'")
        return

    if args.bayes_input_file:
        payload_text = Path(args.bayes_input_file).expanduser().read_text(encoding="utf-8")
    else:
        payload_text = args.bayes_input or "{}"
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        print(f"forecast bayes: invalid JSON payload: {exc}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(payload, dict):
        print("forecast bayes: payload must be a JSON object", file=sys.stderr)
        raise SystemExit(2)

    # Provision NumPy/SciPy on first use; the toolkit falls back to stdlib math
    # offline so this never blocks the command.
    ensure_industry_backends()
    outcome = run_bayes_action(action, payload)
    if args.bayes_json:
        print(json.dumps({"action": outcome["action"], "result": outcome["result"]}, indent=2, sort_keys=True))
    else:
        print(outcome["rationale"])


def _cmd_apikey_default(args: argparse.Namespace) -> None:
    """`forecast api-key` with no subcommand → show usage + list."""

    print("usage: forecast api-key {list|show|set|unset} ...")
    print("       forecast api-key list                    # show all known providers (redacted)")
    print("       forecast api-key set fred <key>          # persist + activate a key")
    print("       forecast api-key set fred --from-stdin   # read the value from stdin")
    print("       forecast api-key unset fred              # remove a key\n")
    _print_apikey_list(json_output=False)


def _print_apikey_list(*, json_output: bool) -> None:
    import textwrap

    from forecasting.api_keys import list_api_keys

    rows = list_api_keys()
    if json_output:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return
    # One tidy block per provider: a compact PROVIDER / ENV VAR / SET row, then
    # the description wrapped at a fixed width with a shallow hanging indent (so
    # it reads as a paragraph, not a deep ragged column), then the signup URL,
    # then a blank line so providers stay visually grouped. The deep 48-col
    # indent of the old layout is what forced the ugly mid-word wrapping.
    print(f"{'PROVIDER':14} {'ENV VAR':22} {'SET':4} VALUE / DESCRIPTION")
    for row in rows:
        flag = "set" if row["set"] else "—"
        print(f"{row['name']:14} {row['env_var']:22} {flag:4} {row['redacted']}")
        for wrapped in textwrap.wrap(
            row["description"], width=78, initial_indent="    ", subsequent_indent="    "
        ):
            print(wrapped)
        if row.get("signup_url") and not row["set"]:
            print(f"    get: {row['signup_url']}")
        print()


def _cmd_apikey_list(args: argparse.Namespace) -> None:
    _print_apikey_list(json_output=bool(getattr(args, "json", False)))


def _cmd_apikey_show(args: argparse.Namespace) -> None:
    from forecasting.api_keys import get_api_key, lookup_provider, redact

    try:
        provider = lookup_provider(args.provider)
    except ForecastingError as exc:
        print(f"forecast api-key: {exc}", file=sys.stderr)
        raise SystemExit(2)
    value = get_api_key(args.provider)
    row = {
        "name": provider.name,
        "env_var": provider.env_var,
        "set": bool(value),
        "redacted": redact(value),
        "description": provider.description,
        "signup_url": provider.signup_url,
    }
    if getattr(args, "json", False):
        print(json.dumps(row, indent=2, sort_keys=True))
        return
    print(f"provider: {row['name']}  ({row['env_var']})")
    print(f"set:      {'yes' if row['set'] else 'no'}")
    print(f"value:    {row['redacted']}")
    print(f"about:    {row['description']}")
    if row.get("signup_url") and not row["set"]:
        print(f"get key:  {row['signup_url']}")


def _cmd_apikey_set_kalshi(args: argparse.Namespace) -> None:
    """`forecast api-key set kalshi <key-id> --pem-file key.pem` — key id + PEM."""

    from forecasting.api_keys import default_env_path, redact, set_kalshi_key

    key_id = args.value
    pem: str | None = None
    if getattr(args, "pem_stdin", False):
        pem = sys.stdin.read()
    elif getattr(args, "pem_file", None):
        try:
            pem = Path(args.pem_file).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            print(f"forecast api-key set kalshi: cannot read PEM: {exc}", file=sys.stderr)
            raise SystemExit(2)
    if not key_id or not pem:
        print(
            "forecast api-key set kalshi: needs the access key id and a PEM.\n"
            "  forecast api-key set kalshi <key-id> --pem-file /path/to/key.pem\n"
            "  forecast api-key set kalshi <key-id> --pem-stdin  < key.pem",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        info = set_kalshi_key(key_id, pem)
    except ForecastingError as exc:
        print(f"forecast api-key: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print(f"set {info['key_id_var']} ({redact(key_id)}) in {default_env_path()}")
    print(f"wrote Kalshi private key (0600) to {info['pem_path']}")
    print("activated for this process; Kalshi websocket streaming is now available")


def _cmd_apikey_set(args: argparse.Namespace) -> None:
    from forecasting.api_keys import lookup_provider, set_api_key

    # Kalshi captures TWO secrets — the access key id AND an RSA private key PEM
    # (websocket streaming only; REST market data stays keyless). Route it to the
    # dedicated storage that writes the PEM 0600 and records both in .env.
    try:
        if lookup_provider(args.provider).name == "kalshi":
            _cmd_apikey_set_kalshi(args)
            return
    except ForecastingError:
        pass  # fall through to the generic path / normal error below

    value = args.value
    if args.from_stdin:
        value = sys.stdin.read().strip()
    if not value:
        print("forecast api-key set: provide a value or pipe it via --from-stdin", file=sys.stderr)
        raise SystemExit(2)
    try:
        provider = set_api_key(args.provider, value)
    except ForecastingError as exc:
        print(f"forecast api-key: {exc}", file=sys.stderr)
        raise SystemExit(2)
    from forecasting.api_keys import default_env_path, redact

    print(f"set {provider.env_var} ({redact(value)}) in {default_env_path()}")
    print("activated for this process; new agent runs will pick it up from .env")


def _cmd_apikey_unset(args: argparse.Namespace) -> None:
    from forecasting.api_keys import default_env_path, unset_api_key

    try:
        provider = unset_api_key(args.provider)
    except ForecastingError as exc:
        print(f"forecast api-key: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print(f"unset {provider.env_var} in {default_env_path()}")


def _cmd_config_doctor(args: argparse.Namespace) -> None:
    """`forecast config doctor` — read-only report over the layered config loader.

    Surfaces set-but-unknown (typo) vars, known-but-unset defaults in effect,
    secret presence (never values), file-vs-env precedence conflicts, and the
    Kalshi two-var trap. Delegates to :mod:`forecasting.appconfig` so the report
    logic stays pure and testable."""
    from forecasting import appconfig

    report = appconfig.build_doctor_report(appconfig.get_config())
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return
    print(appconfig.render_doctor_report(report))


def _cmd_model_build(args: argparse.Namespace) -> None:
    """`forecast model build <ref>` — build a deterministic Market Model as a
    forecast leg and link it to the question. ``<ref>`` may be an existing forecast
    (id or name) OR free-text quant question. Delegates to the forecast_ledger
    build_model action so the CLI and the agent share one code path."""
    from tools.forecasting_tool import forecast_ledger_tool

    ref = (args.build_question or "").strip()
    if not ref:
        raise SystemExit("forecast model build requires a question ref or quant question text")
    ledger = _ledger(args)
    tool_args: dict[str, Any] = {"action": "build_model", "db": getattr(args, "db", None)}
    # Attach to an existing forecast when the ref uniquely resolves; otherwise treat
    # it as free-text to build a standalone model for.
    resolution = resolve_question_ref(ledger, ref)
    if resolution.question is not None:
        tool_args["question_id"] = resolution.question.id
    else:
        tool_args["question"] = ref
    if args.depth:
        tool_args["depth"] = args.depth
    if args.analysis_type:
        tool_args["analysis_type"] = args.analysis_type
    result = json.loads(forecast_ledger_tool(tool_args))
    if not result.get("success"):
        raise SystemExit(f"model build failed: {result.get('error') or result}")
    rec = result.get("recommended_model") or {}
    print(f"model build: {result.get('model_id')} (v{result.get('version')}, {result.get('model_status')})")
    if result.get("question_id"):
        print(f"linked to question: {result['question_id']}")
    if rec:
        print(f"recommended: {rec.get('model_type')} — {rec.get('family')}")


def _cmd_model_skill(args: argparse.Namespace) -> None:
    """`forecast model skill [<mm_id | model_type>]` — measured model skill (R4).

    With no ref: the GLOBAL skill over every scored model_run. With an ``mm_...``
    ref: that Market Model's skill. Otherwise the ref is treated as a model_type.
    """
    ref = getattr(args, "build_question", None)
    kwargs: dict[str, Any] = {}
    label = "all scored model runs"
    if ref:
        if ref.startswith("mm_"):
            kwargs["market_model_id"] = ref
            label = f"market model {ref}"
        else:
            kwargs["model_type"] = ref
            label = f"model_type {ref}"
    skill = _ledger(args).model_skill(**kwargs)
    print(f"model skill — {label}")
    print(f"  status:            {skill['status']}")
    print(f"  scored runs:       {skill['n_scored']} (binary={skill['n_binary']}, numeric={skill['n_numeric']})")
    brier = skill.get("brier")
    coverage = skill.get("coverage")
    mae = skill.get("mae")
    print(f"  brier (binary):    {brier:.4f}" if isinstance(brier, (int, float)) else "  brier (binary):    n/a")
    print(f"  coverage (numeric):{coverage:.3f}" if isinstance(coverage, (int, float)) else "  coverage (numeric):n/a")
    print(f"  mae (numeric):     {mae:.4g}" if isinstance(mae, (int, float)) else "  mae (numeric):     n/a")
    print(f"  weight multiplier: {skill['weight_multiplier']:.3f} (min sample {skill['min_sample']})")


def _cmd_model(args: argparse.Namespace) -> None:
    # `forecast model build <ref>` sub-verb (M1 reachability): build a Market Model
    # as a forecast leg. The `build` sentinel is unambiguous — question ids are
    # `q_`-prefixed, so a forecast is never literally named "build".
    if args.id == "build":
        return _cmd_model_build(args)
    # `forecast model skill [<mm_id | model_type>]` sub-verb (R4): read a Market
    # Model's (or model_type's) measured skill from scored model_runs. The `skill`
    # sentinel is unambiguous — question ids are `q_`-prefixed.
    if args.id == "skill":
        return _cmd_model_skill(args)
    if not args.model_type:
        write_fields = [
            args.status != "success",
            args.input_json != "{}",
            args.parameters_json != "{}",
            args.output_json != "{}",
            args.diagnostics_json != "{}",
            args.prior is not None,
            args.likelihood_if_true is not None,
            args.likelihood_if_false is not None,
            args.series_json is not None,
            args.target_date is not None,
            args.target_x is not None,
            args.date_field != "date",
            args.value_field != "value",
            args.code_ref is not None,
            bool(args.artifact_paths),
            args.model_version is not None,
            args.prompt_version is not None,
            args.data_version is not None,
            args.evidence_cutoff is not None,
        ]
        if any(write_fields):
            raise SystemExit("model run add requires --type")
        rows = _ledger(args).list_model_runs(args.id)
        print(f"model_runs: {len(rows)}")
        if rows:
            print("ID             Status   Type              CreatedAt             Result")
            for row in rows[-5:]:
                result = ""
                output = row.get("output") or {}
                if "posterior" in output:
                    try:
                        result = f"posterior={float(output['posterior']):.3f}"
                    except (TypeError, ValueError):
                        result = f"posterior={output['posterior']}"
                elif "projected_value" in output:
                    try:
                        result = f"projected={float(output['projected_value']):.3f}"
                    except (TypeError, ValueError):
                        result = f"projected={output['projected_value']}"
                print(
                    f"{row['id']:<14} {row['status']:<8} {row['model_type']:<17} "
                    f"{row['created_at']:<21} {result}"
                )
        print(f"add: forecast model {args.id} --type <model_type> [model options]")
        print("probability unchanged")
        return
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


_PIPELINE_STATUS_MARKERS = {"done": "[x]", "ready": "->", "blocked": "..", "optional": "(o)"}


def _cmd_pipeline(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    args.id = _resolve_question_id(ledger, args.id)
    if getattr(args, "refresh", False):
        from tools.forecasting_tool import fetch_watched_source_payloads

        refresh = ledger.refresh_forecast(
            args.id,
            fetcher=lambda specs: fetch_watched_source_payloads(specs),
            trigger_reason="pipeline_refresh",
        )
        print(f"refresh: {refresh['status']}" + (f" -> {refresh.get('forecast_id')}" if refresh.get("forecast_id") else ""))
    status = build_pipeline_status(ledger, args.id)
    stage = getattr(args, "stage", None)

    if stage:
        block = pipeline_advance_block(status, stage)
        if block and not args.force:
            print(f"forecast: {block}", file=sys.stderr)
            raise SystemExit(1)
        messages = build_protocol_messages(ledger, args.id, stage=stage)
        if args.json:
            print(
                json.dumps(
                    {
                        "stage": stage,
                        "pipeline": status,
                        "messages": [message.__dict__ for message in messages],
                    },
                    indent=2,
                )
            )
            return
        for message in messages:
            print(f"## {message.role}")
            print(message.content)
            print()
        return

    if args.json:
        print(json.dumps(status, indent=2))
        return

    print(f"question: {status['question_id']}")
    print(f"next_stage: {status['next_stage'] or 'complete'}")
    print(f"update_ready: {status['update_ready']}")
    if status["update_blockers"]:
        print(f"update_blocked_by: {', '.join(status['update_blockers'])}")
    print("stages:")
    for entry in status["stages"]:
        marker = _PIPELINE_STATUS_MARKERS.get(entry["status"], "?")
        print(f"  {marker} {entry['stage']:<11} [{entry['status']}] {entry['detail']}")
    if status["decision_readiness_issues"]:
        print("decision_gaps: " + "; ".join(status["decision_readiness_issues"]))
    if status["next_stage"]:
        print(
            f"\nadvance: forecast pipeline {status['question_id']} --stage {status['next_stage']}"
        )


def _run_update_agent(
    ledger: ForecastLedger,
    question_id: str,
    *,
    model: str | None,
    provider: str | None,
    max_iterations: int,
    stage: str = "update",
    commit_policy: str | None = None,
    supplemental: str | None = None,
) -> dict[str, Any]:
    """Run the LLM agent for one question's pipeline stage and RETURN the structured
    result (no printing). The agent commits through the forecasting tool, whose commit
    hook writes the analyst brief — so the loop closes. Shared by `forecast agent`,
    `refresh --agent`, and the autonomous `cycle run --agent` sweep (run_agent is
    imported lazily here so the ledger/cron layers never depend on it).

    ``commit_policy="commit_material"`` is set by the autonomous re-forecast paths so
    the update stage COMMITS a material move instead of stopping at a preview (see
    ``forecasting.protocol._COMMIT_MATERIAL_POLICY``). ``supplemental`` injects a
    stage-scoped note (the chain's research re-run passes the adequacy gap list)."""
    messages = build_protocol_messages(
        ledger, question_id, stage=stage, commit_policy=commit_policy,
        supplemental=supplemental,
    )
    enabled_toolsets = _toolsets_for_stage(stage)
    from run_agent import AIAgent

    agent = AIAgent(
        model=model or "",
        provider=provider,
        max_iterations=max_iterations,
        enabled_toolsets=enabled_toolsets,
        platform="cli",
    )
    return agent.run_conversation(messages[1].content, system_message=messages[0].content)


# The default stage chain a lazy prompter's "just forecast this" runs through:
# gather evidence (research) → set an outside view (base_rate) → commit (update).
# `parse` is skipped — commit_spec already structured the question — and the later
# resolve/postmortem stages only run once the world resolves.
AUTO_FORECAST_STAGES: tuple[str, ...] = ("research", "base_rate", "update")


def auto_forecast_stages(question: Any) -> tuple[str, ...]:
    """Resolve the autonomous stage chain for THIS question's outcome shape.

    Numeric/distribution questions get the optional ``model`` stage between
    base_rate and update — a deterministic quant model (time-series trend,
    monte-carlo fan) is exactly what anchors a level/path forecast, and the
    lazy path must not silently skip the leg the machinery supports
    (``OPTIONAL_PIPELINE_STAGES`` already marks ``model`` optional, so a stage
    agent that finds no usable series simply moves on — the chain captures a
    non-committing stage without aborting). Binary/categorical keep the lighter
    3-stage chain: their outside view IS the base_rate stage."""

    outcome = getattr(getattr(question, "outcome_space", None), "type", None)
    if (outcome or "").strip().lower() in {"numeric", "distribution"}:
        return ("research", "base_rate", "model", "update")
    return AUTO_FORECAST_STAGES


def _snapshot_summary(snapshot: Any) -> dict[str, Any] | None:
    """Compact, JSON-safe view of a committed snapshot for chain results."""
    if snapshot is None:
        return None
    return {
        "forecast_id": getattr(snapshot, "forecast_id", None),
        "question_id": getattr(snapshot, "question_id", None),
        "probability_or_distribution": getattr(snapshot, "probability_or_distribution", None),
        "rationale": getattr(snapshot, "rationale", None),
        "created_at": getattr(snapshot, "created_at", None),
    }


def _format_research_gaps(audit: dict[str, Any]) -> str:
    """Render a research_audit result's gap list into the supplemental note the
    chain injects when it re-runs the research stage. Prose only."""
    gaps = audit.get("gaps") or []
    lines = [
        f"Your research is not yet adequate (score {audit.get('score')}/100, "
        f"threshold {audit.get('threshold')}). Close these specific gaps with fresh "
        "research + import_source_evidence, then finish:",
    ]
    for gap in gaps:
        detail = str(gap.get("detail") or gap.get("kind") or "").strip()
        queries = gap.get("suggested_queries") or []
        line = f"- {detail}"
        if queries:
            line += " Suggested searches: " + "; ".join(str(q) for q in queries[:3]) + "."
        lines.append(line)
    return "\n".join(lines)


def run_forecast_chain(
    ledger: ForecastLedger,
    question_id: str,
    *,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int = 12,
    stages: Sequence[str] | None = None,
    commit_policy: str | None = "commit_material",
    on_stage: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Drive one question through a sequence of pipeline stages, each via the same
    gated update agent (:func:`_run_update_agent`) a manual ``forecast agent --stage S``
    run uses. This is ORCHESTRATION ONLY — every stage runs the identical
    protocol/toolset/commit path, so the panel gate, analyst brief, and
    scheduled-review side-effects fire unchanged; nothing here weakens or bypasses a
    gate. The chain is what turns a lazy prompter's one committed question row into a
    researched, base-rated, committed forecast.

    A stage that raises is captured (``status="error"``) and the chain CONTINUES: a
    flaky research stage must not abort the run, and the update stage's own commit
    gate still refuses if prerequisites are genuinely missing (so a skipped/failed
    prerequisite surfaces as an un-committed, still-gated result — never a fabricated
    number). ``on_stage(stage, outcome)`` fires after each stage for progress
    reporting.

    Returns ``{question_id, stages:[per-stage outcome], committed, snapshot,
    update_ready, update_blockers}``.
    """
    if stages is None:
        # Outcome-shape-aware default: numeric/distribution questions include the
        # optional `model` stage so the lazy path gets the deterministic quant leg.
        stages = auto_forecast_stages(ledger.get_question(question_id))
    stage_results: list[dict[str, Any]] = []
    research_audit_final: dict[str, Any] | None = None
    research_audit_rounds = 0
    for stage in stages:
        prior = ledger.get_current_snapshot(question_id)
        outcome: dict[str, Any] = {"stage": stage, "status": "ran", "committed": False}
        try:
            result = _run_update_agent(
                ledger,
                question_id,
                model=model,
                provider=provider,
                max_iterations=max_iterations,
                stage=stage,
                commit_policy=commit_policy,
            )
        except Exception as exc:  # one bad stage must not abort the chain
            outcome["status"] = "error"
            outcome["detail"] = str(exc)[:200]
        else:
            post = ledger.get_current_snapshot(question_id)
            committed = post is not None and (prior is None or post.forecast_id != prior.forecast_id)
            outcome["committed"] = committed
            if committed:
                outcome["forecast_id"] = post.forecast_id
            response = result.get("final_response") if isinstance(result, dict) else None
            if response:
                outcome["detail"] = _truncate(str(response).strip(), 200)
        stage_results.append(outcome)
        if on_stage is not None:
            on_stage(stage, outcome)

        # VOI-directed research adequacy loop: after the research stage completes for
        # a LIVE (active) question, audit whether the evidence set covers the levers
        # that would move the forecast (deterministic — NO LLM runner, cheap). If it
        # is inadequate and rounds remain, re-run the research stage ONCE per round
        # with the concrete gap list injected. This is BOUNDED (max_audit_rounds
        # counts EXTRA passes) and fail-open: any audit error simply stops the loop.
        if stage == "research":
            research_audit_rounds, research_audit_final = _run_research_audit_loop(
                ledger, question_id,
                model=model, provider=provider, max_iterations=max_iterations,
                commit_policy=commit_policy, on_stage=on_stage,
                stage_results=stage_results,
            )

    final = ledger.get_current_snapshot(question_id)
    status = build_pipeline_status(ledger, question_id)
    return {
        "question_id": question_id,
        "stages": stage_results,
        "committed": any(s.get("committed") for s in stage_results),
        "snapshot": _snapshot_summary(final),
        "update_ready": status.get("update_ready"),
        "update_blockers": status.get("update_blockers") or [],
        "research_audit_rounds": research_audit_rounds,
        "research_audit": research_audit_final,
    }


def _run_research_audit_loop(
    ledger: ForecastLedger,
    question_id: str,
    *,
    model: str | None,
    provider: str | None,
    max_iterations: int,
    commit_policy: str | None,
    on_stage: Callable[[str, dict[str, Any]], None] | None,
    stage_results: list[dict[str, Any]],
) -> tuple[int, dict[str, Any] | None]:
    """Deterministic research-adequacy re-run loop (see run_forecast_chain). Returns
    ``(extra_rounds_run, final_audit)``. Fully fail-open: never raises."""
    from forecasting.research_audit import audit_research, research_stage_incomplete

    try:
        question = ledger.get_question(question_id)
    except Exception:
        return 0, None
    # Only live (active) questions get the extra research passes.
    if getattr(question, "status", None) != "active":
        try:
            return 0, audit_research(ledger, question)
        except Exception:
            return 0, None

    try:
        from hermes_cli.config import cfg_get, load_config_readonly

        max_rounds = int(cfg_get(load_config_readonly(), "forecasting", "research", "max_audit_rounds", default=2) or 0)
    except Exception:
        max_rounds = 2
    max_rounds = max(0, max_rounds)

    def _safe_audit(q: Any) -> dict[str, Any] | None:
        try:
            return audit_research(ledger, q)
        except Exception:
            return None

    audit = _safe_audit(question)
    rounds = 0
    # Re-run RESEARCH only for research-stage-controllable gaps (evidence floor,
    # independence, disconfirming, recency, trigger coverage). reference_class is the
    # base_rate stage's job (it runs after this checkpoint), so it never drives a
    # research re-run here.
    while research_stage_incomplete(audit) and rounds < max_rounds:
        rounds += 1
        prev_score = audit.get("score")
        supplemental = _format_research_gaps(audit)
        re_outcome: dict[str, Any] = {
            "stage": "research", "status": "ran", "committed": False,
            "audit_round": rounds, "audit_score": prev_score,
        }
        try:
            result = _run_update_agent(
                ledger, question_id,
                model=model, provider=provider, max_iterations=max_iterations,
                stage="research", commit_policy=commit_policy, supplemental=supplemental,
            )
        except Exception as exc:
            re_outcome["status"] = "error"
            re_outcome["detail"] = str(exc)[:200]
        else:
            response = result.get("final_response") if isinstance(result, dict) else None
            if response:
                re_outcome["detail"] = _truncate(str(response).strip(), 200)
        stage_results.append(re_outcome)
        if on_stage is not None:
            on_stage("research", re_outcome)
        try:
            question = ledger.get_question(question_id)
        except Exception:
            break
        audit = _safe_audit(question)
        # No-progress guard (spend bound): a re-run that did not RAISE the adequacy
        # score won't be helped by another identical pass — stop rather than burn the
        # remaining rounds on research that isn't finding anything.
        if (
            research_stage_incomplete(audit)
            and isinstance(audit.get("score"), (int, float))
            and isinstance(prev_score, (int, float))
            and audit["score"] <= prev_score
        ):
            break
    return rounds, audit


def _cmd_agent(args: argparse.Namespace) -> None:
    if args.dry_run:
        messages = build_protocol_messages(_ledger(args), args.id, stage=args.stage)
        enabled_toolsets = _toolsets_for_stage(args.stage)
        print(f"enabled_toolsets: {', '.join(enabled_toolsets)}")
        print()
        for message in messages:
            print(f"## {message.role}")
            print(message.content)
            print()
        return
    result = _run_update_agent(
        _ledger(args), args.id,
        model=args.model, provider=args.provider, max_iterations=args.max_iterations, stage=args.stage,
        commit_policy=getattr(args, "commit_policy", None),
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
    if args.source_or_note and args.source_or_note_option:
        raise SystemExit("use either positional source_or_note or --source, not both")
    source_or_note = args.source_or_note or args.source_or_note_option or ""
    if not source_or_note and not args.source_url:
        raise SystemExit("forecast evidence add requires a source/note argument, --source, or --url")
    ledger = _ledger(args)
    item = ledger.add_evidence(
        question_id=args.id,
        source_or_note=source_or_note,
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
    # New evidence is a thinking update: refresh the analyst's read on the current
    # forecast even though the probability has not moved. Best-effort; no-op if the
    # question has no forecast snapshot yet.
    _write_analyst_brief(
        ledger,
        args.id,
        ledger.get_current_snapshot(args.id),
        evidence_only=True,
    )


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
    ledger = _ledger(args)
    resolution = ledger.resolve_question(
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
        auto_score=args.auto_score,
    )
    print(f"recorded resolution {resolution.id}")
    print(f"status: {resolution.resolution_status}")
    print(f"criteria_satisfied: {resolution.criteria_satisfied}")
    score = None
    if (
        args.auto_score
        and resolution.resolution_status == "confirmed"
        and resolution.criteria_satisfied
        and not args.not_scoreable
    ):
        score = ledger.get_current_score(args.id)
        if score is not None:
            print(
                "auto_score: "
                f"brier={_format_metric(score.brier_score)} "
                f"log={_format_metric(score.log_score)} "
                f"origin={score.forecast_origin}"
            )
    # Once the question is finalized, write the closing retrospective into the same
    # time-indexed note stream. Best-effort, after the resolution is recorded.
    if resolution.resolution_status == "confirmed" and resolution.criteria_satisfied:
        _write_retrospective(ledger, args.id, score=score)


def _cmd_score(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    score = ledger.score_question(args.id, force=args.force)
    print(f"score: {score.id}")
    print(f"brier_score: {score.brier_score:.6f}" if score.brier_score is not None else "brier_score: -")
    print(f"log_score: {score.log_score:.6f}" if score.log_score is not None else "log_score: -")
    print(f"proper_score: {score.proper_score:.6f}" if score.proper_score is not None else "proper_score: -")
    print(f"score_rule: {score.score_rule or '-'}")
    print(f"bucket: {score.calibration_bucket or '-'}")
    print(f"origin: {score.forecast_origin}")
    if args.baselines:
        baselines = ledger.score_baseline_comparisons(args.id, force=args.force)
        if not baselines:
            print("baseline_scores: none")
        else:
            print(f"baseline_scores: {len(baselines)}")
            for baseline in baselines:
                baseline_score = baseline["score"]
                name = f"{baseline['baseline_type']}:{baseline['source']}"
                print(
                    f"  {baseline['id']} {name} "
                    f"brier={_format_metric(baseline_score.brier_score)} "
                    f"log={_format_metric(baseline_score.log_score)} "
                    f"origin={baseline_score.forecast_origin}"
                )


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


def _load_panel_estimates(args: argparse.Namespace) -> list[dict[str, Any]] | None:
    """Resolve panel-estimate JSON from --panel-estimates-json or --panel-estimates-file."""

    raw = getattr(args, "panel_estimates_json", None)
    if raw is None:
        path = getattr(args, "panel_estimates_file", None)
        if path:
            try:
                raw = Path(path).expanduser().read_text(encoding="utf-8")
            except OSError as exc:
                raise SystemExit(f"forecast update: cannot read --panel-estimates-file: {exc}") from exc
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"forecast update: invalid --panel-estimates-json: {exc.msg}") from exc
    if isinstance(data, dict) and "estimates" in data:
        data = data["estimates"]
    if not isinstance(data, list) or not data:
        raise SystemExit(
            "forecast update: --panel-estimates-json must be a non-empty JSON array of estimate objects"
        )
    return data


def _print_panel_summary(panel_run: dict[str, Any]) -> None:
    spread = panel_run.get("spread_summary") or {}
    print(f"panel_run: {panel_run['id']}")
    print(f"  method: {panel_run['aggregation_method']} (trim={panel_run['trim']})")
    print(f"  aggregate: {panel_run['aggregate_probability']:.3f}")
    if spread:
        print(
            f"  spread: min={spread.get('min', 0):.2f} median={spread.get('median', 0):.2f} "
            f"max={spread.get('max', 0):.2f} iqr={spread.get('iqr', 0):.2f}"
        )
    print(f"  perspectives: {len(panel_run.get('estimates', []))}")
    for estimate in panel_run.get("estimates", []):
        marker = "× " if estimate.get("trimmed") else "  "
        ci = ""
        if estimate.get("confidence_low") is not None and estimate.get("confidence_high") is not None:
            ci = f" [{estimate['confidence_low']:.2f}–{estimate['confidence_high']:.2f}]"
        print(
            f"  {marker}{estimate['perspective']:<10} p={estimate['probability']:.3f}{ci} "
            f"crux={estimate.get('crux') or '-'}"
        )
    for note in panel_run.get("notes") or []:
        print(f"  note: {note}")


def _cmd_panel_perspectives(args: argparse.Namespace) -> None:
    from forecasting.panel import (
        DEFAULT_PANEL_PERSPECTIVES,
        PANEL_PERSPECTIVES,
        build_perspective_prompts,
    )
    from forecasting.protocol import build_context_packet

    perspectives = args.perspectives or list(DEFAULT_PANEL_PERSPECTIVES)
    if args.question_id:
        ledger = _ledger(args)
        question = ledger.get_question(args.question_id)
        snapshot = ledger.get_current_snapshot(question.id)
        context = build_context_packet(ledger, question, snapshot)
        prompts = build_perspective_prompts(
            question_title=question.title,
            resolution_criteria=question.resolution_criteria,
            context_packet=context,
            perspectives=perspectives,
        )
    else:
        prompts = build_perspective_prompts(
            question_title="<question title>",
            resolution_criteria="<resolution criteria>",
            context_packet="<ledger context packet>",
            perspectives=perspectives,
        )
    if args.json:
        print(json.dumps(prompts, indent=2, sort_keys=True))
        return
    for name, prompt in prompts.items():
        label = PANEL_PERSPECTIVES.get(name, {}).get("label", name)
        print(f"=== {name} — {label} ===")
        print("[system]")
        print(prompt["system"])
        print()
        print("[user]")
        print(prompt["user"])
        print()


def _cmd_panel_aggregate(args: argparse.Namespace) -> None:
    from forecasting.panel import aggregate_panel_estimates

    raw = args.panel_input
    if raw is None and args.panel_input_file:
        try:
            raw = Path(args.panel_input_file).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"forecast panel aggregate: cannot read --input-file: {exc}") from exc
    if not raw or not raw.strip():
        raise SystemExit("forecast panel aggregate: --input or --input-file required")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"forecast panel aggregate: invalid JSON: {exc.msg}") from exc
    if isinstance(data, dict) and "estimates" in data:
        data = data["estimates"]
    aggregation = aggregate_panel_estimates(
        data,
        method=args.method,
        trim=args.trim,
    )
    if args.json:
        print(json.dumps(aggregation.to_dict(), indent=2, sort_keys=True))
        return
    print(f"method: {aggregation.method} (trim={aggregation.trim})")
    print(f"aggregate: {aggregation.aggregate_probability:.4f}")
    print("spread:")
    for key in ("min", "p25", "median", "p75", "max", "iqr", "range", "count"):
        if key in aggregation.spread:
            print(f"  {key}: {aggregation.spread[key]:.4f}")
    print(f"estimates ({len(aggregation.estimates)}):")
    for estimate in aggregation.estimates:
        marker = "× " if estimate.get("trimmed") else "  "
        print(f"  {marker}{estimate['perspective']:<12} p={estimate['probability']:.3f}")
    for note in aggregation.notes:
        print(f"note: {note}")


def _cmd_panel_record(args: argparse.Namespace) -> None:
    raw = args.panel_input
    if raw is None and args.panel_input_file:
        try:
            raw = Path(args.panel_input_file).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"forecast panel record: cannot read --input-file: {exc}") from exc
    if not raw or not raw.strip():
        raise SystemExit("forecast panel record: --input or --input-file required")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"forecast panel record: invalid JSON: {exc.msg}") from exc
    if isinstance(data, dict) and "estimates" in data:
        data = data["estimates"]
    ledger = _ledger(args)
    if getattr(args, "track_record_weights", False) and isinstance(data, list):
        weights = ledger.recommended_component_weights(kind="panel")
        applied = []
        for row in data:
            if not isinstance(row, dict) or "weight" in row:
                continue
            weight = weights.get(str(row.get("perspective", "")).strip())
            if weight is not None:
                row["weight"] = weight
                applied.append(f"{row['perspective']}={weight:.2f}")
        if applied:
            print("track-record weights applied: " + ", ".join(applied))
        else:
            print(
                "track-record weights: none applied (no measured perspectives yet "
                "— see `forecast track-record`)"
            )
    record = ledger.record_panel_run(
        question_id=args.question_id,
        estimates=data,
        aggregation_method=args.method,
        trim=args.trim,
        snapshot_id=args.snapshot_id,
        triggered_by=args.triggered_by,
    )
    _print_panel_summary(record)


def _cmd_panel_show(args: argparse.Namespace) -> None:
    record = _ledger(args).get_panel_run(args.panel_run_id)
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
        return
    _print_panel_summary(record)
    for estimate in record.get("estimates", []):
        print()
        print(f"[{estimate['perspective']}] {'(trimmed)' if estimate.get('trimmed') else ''}")
        if estimate.get("rationale"):
            print(f"  rationale: {estimate['rationale']}")
        for label in ("reasons_up", "reasons_down", "change_my_mind"):
            items = estimate.get(label) or []
            if items:
                print(f"  {label}:")
                for item in items:
                    print(f"    - {item}")


def _cmd_panel_list(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_panel_runs(question_id=args.question_id, limit=args.limit)
    if not rows:
        print("No panel runs found.")
        return
    print("ID             Created              Question        Method                  Trim  Aggregate  Spread")
    for row in rows:
        spread = row.get("spread_summary") or {}
        spread_text = (
            f"{spread.get('min', 0):.2f}-{spread.get('max', 0):.2f}"
            if spread
            else "-"
        )
        print(
            f"{row['id']:<14} {row['created_at']:<20} {row['question_id']:<15} "
            f"{row['aggregation_method']:<24} {row['trim']:<5} "
            f"{row['aggregate_probability']:.3f}     {spread_text}"
        )


def _cmd_quorum(args: argparse.Namespace) -> None:
    """Dispatch `forecast quorum …` (run | status | config | default)."""

    target = (args.target or "").strip()
    rest = [str(r) for r in (args.rest or [])]
    if target == "status":
        _quorum_status(args, rest)
        return
    if target == "config":
        _quorum_config(rest)
        return
    if target == "default":
        _quorum_default(rest, scope=args.scope)
        return
    if target == "calibration":
        _quorum_calibration(args)
        return
    if target == "bench":
        _quorum_bench(args)
        return
    if not target:
        _quorum_overview()
        return
    _quorum_run(args, question_id=target)


def _cmd_rerun(args: argparse.Namespace) -> None:
    """Dispatch `forecast rerun …` — start a detached mass reforecast over explicit
    ids, or `rerun status <run-id>` to poll one.

    The detached job runs :func:`run_forecast_chain` directly per question (it does
    NOT shell back to the CLI), so this handler only validates + enqueues; the full
    formal flow and every gate live in the shared chain."""

    ids = [str(i).strip() for i in (args.ids or []) if str(i).strip()]
    if ids and ids[0] == "status":
        _rerun_status(args, ids[1:])
        return
    if not ids:
        print("forecast rerun — mass LLM re-run over explicit question ids")
        print("usage:")
        print("  forecast rerun <id> [<id> ...] [--model M] [--max-iterations N] [--wait]")
        print("  forecast rerun status <run-id>")
        return

    from forecasting.jobs.types.reforecast import (
        DEFAULT_MAX_BATCH,
        read_job,
        start_job,
        validate_reforecast_ids,
    )
    from hermes_cli.config import cfg_get, load_config_readonly

    ledger = _ledger(args)
    try:
        max_batch = int(
            cfg_get(load_config_readonly(), "forecasting", "reforecast", "max_batch", default=DEFAULT_MAX_BATCH)
            or DEFAULT_MAX_BATCH
        )
    except (TypeError, ValueError):
        max_batch = DEFAULT_MAX_BATCH

    accepted, errors = validate_reforecast_ids(ledger, ids, max_batch=max_batch)
    if errors:
        raise SystemExit("forecast rerun: " + "; ".join(errors))

    spec = {
        "question_ids": accepted,
        "db": str(ledger.db_path) if getattr(ledger, "db_path", None) else getattr(args, "db", None),
        "model": args.model,
        "provider": args.provider,
        "max_iterations": int(getattr(args, "max_iterations", None) or 12),
        "triggered_by": "desk_mass_agent",
    }
    run_id = start_job(spec, wait=bool(args.wait))

    if args.wait:
        _print_rerun_job(read_job(run_id), json_output=args.json)
        return
    if args.json:
        print(json.dumps({"run_id": run_id, "status": "queued", "total": len(accepted)}, indent=2))
        return
    print(f"reforecast run started: {run_id} ({len(accepted)} question(s))")
    print(f"  poll with:  forecast rerun status {run_id}")


def _rerun_status(args: argparse.Namespace, rest: list[str]) -> None:
    from forecasting.jobs.types.reforecast import list_jobs, read_job

    if not rest:
        jobs = list_jobs()
        if args.json:
            print(json.dumps(jobs, indent=2))
            return
        if not jobs:
            print("No reforecast runs yet. Start one with `forecast rerun <id> [<id> ...]`.")
            return
        print("Run            Status   Done/Total  Updated")
        for job in jobs:
            done = f"{job.get('done_count', 0)}/{job.get('total', 0)}"
            print(f"{job['run_id']:<14} {job['status']:<8} {done:<11} {job.get('updated_at', '-')}")
        return
    try:
        job = read_job(rest[0])
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
    _print_rerun_job(job, json_output=args.json)


def _print_rerun_job(job: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(job, indent=2))
        return
    print(f"reforecast run {job['run_id']}: {job['status']}")
    print(f"  progress: {job.get('done_count', 0)}/{job.get('total', 0)}")
    current = job.get("current")
    if current:
        print(f"  current:  {current.get('question_id')} — {current.get('stage')}")
    if job.get("error"):
        print(f"  error:    {job['error']}")
    quorums = sum(1 for r in (job.get("results") or []) if r.get("quorum_autorun"))
    if quorums:
        print(f"  quorums started: {quorums}")
    for r in job.get("results") or []:
        state = "error" if r.get("error") else ("committed" if r.get("committed") else "no-commit")
        line = f"    {r.get('question_id')}: {state}"
        if r.get("forecast_id"):
            line += f" ({r['forecast_id']})"
        if r.get("error"):
            line += f" — {r['error']}"
        elif not r.get("committed") and r.get("update_blockers"):
            line += f" — gated: {', '.join(r['update_blockers'])}"
        print(line)


def _quorum_overview() -> None:
    from hermes_cli.config import load_config

    cfg = load_config().get("quorum", {})
    print("forecast quorum — model-diverse forecast panel with judge synthesis")
    print(f"  default_enabled: {bool(cfg.get('default_enabled'))}  "
          f"scope: {cfg.get('default_scope', 'high_impact')}")
    print(f"  preset: {cfg.get('preset', 'frontier')}  "
          f"pool: {cfg.get('pool_method', 'trimmed_geomean_odds')} (trim={cfg.get('trim', 1)})")
    print("usage:")
    print("  forecast quorum <question-id> [--preset frontier|budget|self] [--wait]")
    print("  forecast quorum status [run-id]")
    print("  forecast quorum config [set <key> <value>]")
    print("  forecast quorum default on|off [--scope high_impact|always|first_only]")
    print("  forecast quorum calibration   (how disagreement relates to realised error)")
    print("  forecast quorum bench         (ensemble-size variance-reduction curve, read-only)")


def _resolve_active_model_id(model_cfg: Any) -> str | None:
    """Canonical implementation lives in :mod:`forecasting.quorum_autorun` (single
    source of truth for every commit surface — the agent tool's auto-quorum uses
    the same resolver); this lazy alias keeps cli-internal callers and the
    module import weight unchanged."""

    from forecasting.quorum_autorun import resolve_active_model_id

    return resolve_active_model_id(model_cfg)


def _quorum_run(args: argparse.Namespace, *, question_id: str) -> None:
    from hermes_cli.config import load_config
    from forecasting.jobs.types.quorum import read_job, start_job

    cfg = load_config().get("quorum", {})
    active_model = _resolve_active_model_id(load_config().get("model"))

    # Fail fast if the question does not exist (immediate feedback before we
    # spawn a multi-minute background job).
    ledger = _ledger(args)
    question = ledger.get_question(question_id)

    from forecasting.models import ValidationError as _QuorumValidationError
    from forecasting.quorum import (
        available_provider_slugs,
        cap_preset_by_calls,
        cap_trials_by_calls,
        estimate_quorum_calls,
        preset_model_count,
        resolve_configured_panel,
        resolve_quorum_defaults,
        resolve_trial_count,
    )

    # Panel line-up precedence: explicit --models > QUORUM_PANEL_MODELS (appconfig,
    # operator-pinned) > quorum.models (legacy yaml). The pinned appconfig panel
    # takes PRECEDENCE over the connected-provider rebuild; a non-callable entry
    # fails fast HERE (naming itself) before any background job is spawned.
    models = None
    configured_judge: str | None = None
    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        try:
            configured = resolve_configured_panel()
        except _QuorumValidationError as exc:
            raise SystemExit(f"forecast quorum: {exc}") from exc
        if configured:
            models = configured["models"]
            configured_judge = configured.get("judge")
        elif cfg.get("models"):
            models = [str(m).strip() for m in cfg["models"] if str(m).strip()]

    # Default resolution (item 1). When the caller passed NO explicit --preset and
    # NO explicit model list, resolve the panel SHAPE from the question's
    # impact/type (single-key reality guarded) rather than a static config default —
    # so a bare `forecast quorum <id>` gets a right-sized panel. An explicit
    # --preset (or a model list) is honoured verbatim.
    samples_hint = args.samples or 3
    autonomous_preset = args.preset is None and not models
    resolution_note: str | None = None
    if autonomous_preset:
        defaults = resolve_quorum_defaults(
            question,
            available_providers=available_provider_slugs(),
            active_model=active_model,
            samples=samples_hint,
        )
        preset = defaults["preset"]
        default_delphi = int(defaults["delphi_rounds"])
        default_trim = int(defaults["trim"])
        resolution_note = defaults["reason"]
    else:
        preset = args.preset or cfg.get("preset") or "frontier"
        default_delphi = int(cfg.get("delphi_rounds", 0) or 0)
        default_trim = int(cfg.get("trim", 1))

    # --judge wins; else the pinned QUORUM_JUDGE_MODEL; else the legacy yaml judge.
    judge = args.judge or configured_judge or (cfg.get("judge") or None)
    # GATE 2 (AIA P1.1, live): the --supervisor-search flag wins when passed;
    # otherwise inherit the quorum.supervisor_search config (default OFF). Only a
    # truthy value goes into the spec, so the live default stays byte-identical.
    supervisor_search = (
        bool(args.supervisor_search)
        if getattr(args, "supervisor_search", None) is not None
        else bool(cfg.get("supervisor_search"))
    )
    pool_method = args.pool_method or cfg.get("pool_method") or "trimmed_geomean_odds"
    trim = args.trim if args.trim is not None else default_trim

    # Delphi revision rounds (v1: 0 or 1). Precedence: --delphi (=1) >
    # --delphi-rounds > resolved/config default > 0. --delphi with an explicit
    # --delphi-rounds 0 is a contradiction; fail fast.
    delphi_rounds_arg = getattr(args, "delphi_rounds", None)
    if args.delphi and delphi_rounds_arg is not None and delphi_rounds_arg == 0:
        raise SystemExit("forecast quorum: --delphi conflicts with --delphi-rounds 0")
    delphi_rounds = (
        1
        if args.delphi
        else delphi_rounds_arg
        if delphi_rounds_arg is not None
        else default_delphi
    )

    # Multi-trial per panelist (BLF A2): an explicit --trials wins; else K is
    # impact-driven (high-impact 3, else 1). ``1`` is byte-identical to pre-A2.
    if args.trials is not None:
        trials = max(1, int(args.trials))
    else:
        trials, _ = resolve_trial_count(question)

    # Cost cap (item 4): applies to any manual run WITHOUT an explicit --preset and
    # without an explicit model list — an oversized default preset is downgraded to
    # the largest that fits quorum.max_calls. An explicit --preset is respected.
    cap_note: str | None = None
    trials_note: str | None = None
    if args.preset is None and not models:
        max_calls = int(cfg.get("max_calls", 12) or 12)
        preset, delphi_rounds, samples_hint, est_calls, cap_note = cap_preset_by_calls(
            preset, delphi_rounds, max_calls=max_calls, samples=samples_hint
        )
        # Bound K to the SAME budget — extra trials of the same seats yield first.
        trials, trials_note = cap_trials_by_calls(
            preset=preset,
            delphi_rounds=delphi_rounds,
            samples=samples_hint,
            trials=trials,
            max_calls=max_calls,
        )

    if (resolution_note or cap_note or trials_note) and not args.json:
        model_count = preset_model_count(preset, samples=samples_hint)
        est = estimate_quorum_calls(
            model_count=model_count, delphi_rounds=delphi_rounds, trials=trials
        )
        trials_detail = "" if trials <= 1 else f", trials={trials}"
        detail = (
            f"↳ quorum defaults: preset {preset}: {model_count} models + judge, "
            f"delphi={delphi_rounds}{trials_detail}, ~{est} calls"
        )
        if resolution_note:
            detail += f" — {resolution_note}"
        print(detail)
        if cap_note:
            print(f"  cost cap: {cap_note}")
        if trials_note:
            print(f"  cost cap: {trials_note}")

    self_fusion = preset == "self" and not models
    if self_fusion:
        if not active_model:
            raise SystemExit(
                "forecast quorum: the 'self' preset needs a default model — set one "
                "with `--models <id>` or a config `model`."
            )
        # samples_hint carries the cost-cap's (possibly reduced) sample count, so a
        # capped self-fusion actually samples fewer times rather than silently
        # overrunning max_calls; for an uncapped run it is still args.samples or 3.
        samples = samples_hint
        models = [active_model] * samples
        judge = judge or active_model
        preset = None  # models now explicit

    spec = {
        "question_id": question_id,
        "db": getattr(args, "db", None),
        "preset": preset,
        "models": models,
        "judge": judge,
        "pool_method": pool_method,
        "trim": trim,
        "self_fusion": self_fusion,
        "samples": samples_hint if self_fusion else args.samples,
        "attach_snapshot": args.attach_snapshot,
        "triggered_by": args.triggered_by or "quorum",
        "active_model": active_model,
        "max_iterations": int(cfg.get("max_iterations", 30)),
        "model_timeout": int(cfg.get("model_timeout", 300)),
        "supervisor_search": supervisor_search,
        "delphi_rounds": delphi_rounds,
        "trials": trials,
    }

    run_id = start_job(spec, wait=bool(args.wait))

    if args.wait:
        job = read_job(run_id)
        _print_quorum_job(job, json_output=args.json)
        return
    if args.json:
        print(json.dumps({"run_id": run_id, "status": "queued"}, indent=2))
        return
    print(f"quorum run started: {run_id}")
    print(f"  poll with:  forecast quorum status {run_id}")


def _quorum_status(args: argparse.Namespace, rest: list[str]) -> None:
    from forecasting.jobs.types.quorum import list_jobs, read_job

    if not rest:
        jobs = list_jobs()
        if args.json:
            print(json.dumps(jobs, indent=2))
            return
        if not jobs:
            print("No quorum runs yet. Start one with `forecast quorum <question-id>`.")
            return
        print("Run            Status   Question        Updated")
        for job in jobs:
            print(
                f"{job['run_id']:<14} {job['status']:<8} "
                f"{(job.get('question_id') or '-'):<15} {job.get('updated_at', '-')}"
            )
        return
    try:
        job = read_job(rest[0])
    except FileNotFoundError as exc:
        raise SystemExit(f"forecast quorum status: {exc}") from exc
    _print_quorum_job(job, json_output=args.json)


def _print_quorum_job(job: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(job, indent=2, sort_keys=True))
        return
    print(f"quorum run: {job['run_id']}  [{job['status']}]")
    print(f"  question: {job.get('question_id')}")
    if job.get("panel_run_id"):
        print(f"  panel_run: {job['panel_run_id']}")
    if job.get("error"):
        print(f"  error: {job['error']}")
    for step in job.get("progress") or []:
        print(f"  · {step['stage']}: {step['detail']}")
    result = job.get("result")
    if not result:
        return
    if result.get("degraded"):
        print(f"  ⚠ DEGRADED PANEL: {result.get('degraded_reason') or 'fewer than 2 panelists survived'}")
    print(f"  pool: {result['aggregate_probability']:.3f}  "
          f"({result['pool_method']}, trim={result['trim']})")
    final_source = result.get("final_source", "pool")
    final_prob = result.get("final_probability", result["aggregate_probability"])
    delphi_rounds = int(result.get("delphi_rounds") or 0)
    if delphi_rounds:
        plural = "round" if delphi_rounds == 1 else "rounds"
        print(f"  delphi: {delphi_rounds} revision {plural}")
        rounds = ((result.get("delphi_audit") or {}).get("rounds")) or []
        for entry in rounds:
            r_dis = entry.get("disagreement") or {}
            r_prob = entry.get("aggregate_probability")
            prob_str = f"{r_prob:.3f}" if isinstance(r_prob, (int, float)) else "?"
            print(
                f"  round {entry.get('round_index', '?')} pool: {prob_str} "
                f"disagreement: {r_dis.get('disagreement_band', '?')}"
            )
    committed_label = (
        "committed (judge override)" if final_source == "judge_high" else "committed (pool)"
    )
    print(f"  {committed_label}: {final_prob:.3f}")
    dis = result.get("disagreement") or {}
    print(f"  disagreement: {dis.get('disagreement_band', '?')} "
          f"(index={dis.get('disagreement_index')}, sd_logit={dis.get('sd_logit')})")
    weights_used = result.get("model_weights_used") or {}
    if weights_used:
        print(
            "  track-record weights: "
            + ", ".join(f"{m}={w:.2f}" for m, w in sorted(weights_used.items()))
        )
    for f in result.get("forecasts") or []:
        if f.get("error"):
            print(f"    ✗ {f['model']}: {f['error']}")
        else:
            weight = f.get("weight")
            weight_str = (
                f" (weight {weight:.2f})"
                if isinstance(weight, (int, float)) and abs(float(weight) - 1.0) > 1e-9
                else ""
            )
            print(f"    • {f['model']}: {f['probability']:.3f}{weight_str}")
    judge = result.get("judge")
    if judge:
        if judge.get("probability") is not None:
            conf = judge.get("directional_confidence", "medium")
            print(
                f"  judge verdict: {judge['probability']:.3f} "
                f"[{conf} confidence] — {judge.get('rationale', '')}"
            )
        for spot in judge.get("blind_spots") or []:
            print(f"    blind spot: {spot}")


# The operator-pinned panel keys live in the layered appconfig loader (config.yaml
# `env:` section / env var / override), NOT the `quorum.*` yaml block — so a set of
# either name writes to the `env:` section and a show reads the RESOLVED value (with
# its source). Accepts the bare or `quorum.`-prefixed spelling.
_QUORUM_APPCONFIG_KEYS = {
    "QUORUM_PANEL_MODELS": "QUORUM_PANEL_MODELS",
    "QUORUM_JUDGE_MODEL": "QUORUM_JUDGE_MODEL",
    "PANEL_MODELS": "QUORUM_PANEL_MODELS",
    "JUDGE_MODEL": "QUORUM_JUDGE_MODEL",
}


def _quorum_config(rest: list[str]) -> None:
    from hermes_cli.config import load_config, set_config_value

    if rest and rest[0] == "set":
        if len(rest) < 3:
            raise SystemExit("forecast quorum config set <key> <value>")
        key, value = rest[1], rest[2]
        # An appconfig panel key (QUORUM_PANEL_MODELS / QUORUM_JUDGE_MODEL) is written
        # to the config.yaml `env:` section so the layered loader + the doctor see it;
        # everything else stays a `quorum.<key>` yaml knob as before.
        canonical = _QUORUM_APPCONFIG_KEYS.get(key.strip().upper().replace("QUORUM.", ""))
        if canonical is None and key.strip().upper() in _QUORUM_APPCONFIG_KEYS:
            canonical = _QUORUM_APPCONFIG_KEYS[key.strip().upper()]
        if canonical:
            # Validate a pinned panel eagerly so a bad set is rejected NAMING the entry
            # rather than failing silently at the next run.
            if canonical == "QUORUM_PANEL_MODELS":
                from forecasting.models import ValidationError
                from forecasting.quorum import parse_panel_models_config, validate_panel_models

                try:
                    validate_panel_models(parse_panel_models_config(value))
                except ValidationError as exc:
                    raise SystemExit(f"forecast quorum config set: {exc}") from exc
            set_config_value(f"env.{canonical}", value)
            print(f"✓ set {canonical} = {value}  (config.yaml env:)")
            return
        set_config_value(f"quorum.{key}", value)
        print(f"✓ set quorum.{key} = {value}")
        return
    cfg = load_config().get("quorum", {})
    print("quorum config:")
    for key in (
        "default_enabled", "default_scope", "preset", "models",
        "judge", "pool_method", "trim", "model_timeout", "max_iterations",
        "delphi_rounds",
    ):
        print(f"  {key}: {cfg.get(key)}")
    # Operator-pinned panel (appconfig layer) — show the RESOLVED value + source so an
    # operator sees whether a pin comes from the env: section, a shell var, or is unset.
    from forecasting import appconfig

    ac = appconfig.get_config()
    ac.reload()
    print("  ── operator-pinned panel (appconfig) ──")
    for name in ("QUORUM_PANEL_MODELS", "QUORUM_JUDGE_MODEL"):
        value = ac.get_str(name, None)
        source = ac.source_of(name)
        print(f"  {name}: {value if value else '(unset)'}  [{source}]")


def _quorum_default(rest: list[str], *, scope: str | None) -> None:
    from hermes_cli.config import load_config, set_config_value

    state = rest[0].strip().lower() if rest else None
    if state in {"on", "off"}:
        set_config_value("quorum.default_enabled", "true" if state == "on" else "false")
        print(f"✓ quorum-by-default {'enabled' if state == 'on' else 'disabled'}")
    elif state is not None:
        raise SystemExit("forecast quorum default on|off")
    if scope:
        set_config_value("quorum.default_scope", scope)
        print(f"✓ quorum default scope = {scope}")
    cfg = load_config().get("quorum", {})
    print(f"quorum default_enabled: {bool(cfg.get('default_enabled'))}  "
          f"scope: {cfg.get('default_scope', 'high_impact')}")


def _quorum_calibration(args: argparse.Namespace) -> None:
    """Report how quorum disagreement relates to realised forecast error."""

    from forecasting.quorum_analysis import disagreement_calibration

    report = disagreement_calibration(_ledger(args))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print(f"quorum disagreement → error  (n={report['n']} scored quorum forecasts)")
    if not report["n"]:
        print("  no scored quorum forecasts yet — resolve some and run again.")
        return
    corr = report["correlation"]
    print(f"  correlation(disagreement, brier): {corr if corr is not None else '—'}")
    for band in ("calm", "moderate", "high", "severe"):
        bucket = report["bands"].get(band)
        if bucket:
            print(f"    {band:<9} n={bucket['count']:<3} mean_brier={bucket['mean_brier']:.4f}")
    print(f"  → {report['interpretation']}")


def _quorum_bench(args: argparse.Namespace) -> None:
    """Read-only ensemble-size variance-reduction readout over resolved quorums.

    This NEVER changes any committed forecast or the live default ensemble size —
    it benchmarks how Brier variance falls as you add mean-pooled draws (AIA P1.4).
    """

    from forecasting.quorum_analysis import ensemble_bench

    seed = int(getattr(args, "seed", 0) or 0)
    draws_arg = getattr(args, "draws", None)
    draws = 500 if draws_arg is None else max(1, int(draws_arg))
    report = ensemble_bench(_ledger(args), seed=seed, draws=draws)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print(
        f"quorum ensemble-size bench  (n_runs={report['n_runs']} resolved quorum forecasts)"
    )
    if not report["n_runs"]:
        print("  no resolved quorum forecasts yet — resolve some and run again.")
        return
    curve = report["curve"]["curve"]
    print(f"  bootstrap: draws={report['draws']} seed={report['seed']}")
    print("  k   mean_brier   95% CI width")
    for point in curve:
        print(
            f"  {point['k']:<3} {point['mean_brier']:<11.4f} {point['ci95_width']:.4f}"
        )
    var = report["variance"]
    print(
        f"  variance: sampling(LLM)={var['sampling_variance']:.5f}  "
        f"question={var['question_variance']:.5f}"
    )
    print(
        f"  Brier-of-mean={var['mean_brier_of_mean']:.5f}  "
        f"mean-of-Brier={var['mean_mean_of_brier']:.5f}  "
        f"Jensen gap={var['jensen_gap']:+.5f}  (>= 0 — the accuracy the simple mean buys)"
    )


def _cmd_postmortem(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    postmortem = ledger.create_postmortem(
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
        failure_class=getattr(args, "failure_class", None),
    )
    print(f"postmortem: {postmortem['id']}")
    print(f"score_record: {postmortem['score_record_id']}")
    if postmortem.get("failure_class"):
        print(f"failure_class: {postmortem['failure_class']}")
    if args.lesson:
        print("calibration_lesson: created")
    # A postmortem is fresh learning: refresh the closing retrospective so it
    # digests the new lesson. Best-effort, appended to the same note stream.
    _write_retrospective(ledger, args.id, score=ledger.get_current_score(args.id))


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


def _cmd_resolver_rule(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    qid = _resolve_question_id(ledger, args.question)
    rule = ledger.set_resolution_rule(
        qid, field=args.field, comparator=args.comparator,
        threshold=args.threshold, source_role=args.source_role,
    )
    print(f"resolution rule on {qid}:")
    print(f"  propose YES when [{args.source_role}] {rule['field']} {rule['comparator']} {rule['threshold']}")
    print("  run `forecast resolver propose` once the source reports the value.")


def _cmd_resolver_propose(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    qid = _resolve_question_id(ledger, args.question)
    proposal = ledger.propose_resolution(qid)
    if getattr(args, "json", False):
        print(json.dumps(proposal, indent=2))
        return
    if proposal is None:
        print("No resolution rule on this question. Attach one with `forecast resolver rule`.")
        return
    if not proposal["determinable"]:
        print(f"undetermined: {proposal['rationale']} (NOT resolving — nothing fabricated)")
        return
    print(f"PROPOSED resolution: {proposal['outcome'].upper()}")
    print(f"  {proposal['rationale']}")
    print(f"  confirm with: forecast resolve {qid} --outcome {proposal['outcome']}")


def _cmd_resolver_propose_due(args: argparse.Namespace) -> None:
    dry = getattr(args, "dry_run", False)
    results = _ledger(args).propose_due_resolutions(dry_run=dry)
    if not results:
        print("No determinable resolutions to propose.")
        return
    for item in results:
        if dry:
            state = "would propose + alert"
        elif item.get("alerted"):
            state = "ALERTED for confirmation"
        else:
            state = "skipped (open proposal alert already exists)"
        print(f"{item['question_id']}: {str(item['outcome']).upper()} — {state}")


def _cmd_lesson_synthesize(args: argparse.Namespace) -> None:
    results = _ledger(args).synthesize_bias_lessons(
        scope=args.scope,
        since=args.since,
        recency_halflife_days=args.recency_halflife_days,
        enable_mechanical=args.mechanical,
        activate=not args.no_activate,
        dry_run=args.dry_run,
    )
    if not results:
        print("No scopes with scored forecasts to assess.")
        return
    mode = "DRY-RUN" if args.dry_run else ("MECHANICAL" if args.mechanical else "advisory")
    print(f"calibration-bias synthesis ({mode}); FDR q=0.10 across {len(results)} scope(s):")
    for r in results:
        scope = f"{r['scope_type']}:{r['scope_ref'] or '*'}"
        line = f"  {scope:<22} {r['status']:<20} ess={r['ess']:.1f} n={r['n']}"
        if r.get("sce_shrunk") is not None:
            line += f" sce={r['sce_shrunk'] * 100:+.1f}pp"
        if r.get("ci_low") is not None:
            line += f" ci=[{r['ci_low'] * 100:+.1f},{r['ci_high'] * 100:+.1f}]pp"
        line += f" bh={'yes' if r.get('bh_survived') else 'no'} -> {r.get('disposition', {}).get('lesson_status', '-')}"
        print(line)
        action = r.get("action", {})
        if action.get("written"):
            tail = f", retired {action['retired']}" if action.get("retired") else ""
            print(f"      wrote {action['lesson_id']} ({action['lesson_status']}){tail}")
        elif action.get("retired"):
            print(f"      retired {action['retired']}")


def _print_calibration_bias(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    if args.domain:
        scopes = [("domain", args.domain)]
    else:
        scopes = [("global", None)] + [("domain", d) for d in ledger._domains_with_scores()]
    print("Signed calibration bias (negative=under-confident, positive=over-confident):")
    print(f"{'scope':<22} {'status':<20} {'ess':>6} {'n':>4} {'sce(pp)':>9} {'ci(pp)':>18}  note")
    for scope_type, scope_ref in scopes:
        rep = ledger.calibration_bias(
            domain=scope_ref,
            scope_type=scope_type,
            since=args.since,
            recency_halflife_days=args.recency_halflife_days,
        )
        scope = f"{scope_type}:{scope_ref or '*'}"
        sce = "-" if rep["sce_shrunk"] is None else f"{rep['sce_shrunk'] * 100:+.1f}"
        ci = (
            "-"
            if rep["ci_low"] is None
            else f"[{rep['ci_low'] * 100:+.1f},{rep['ci_high'] * 100:+.1f}]"
        )
        if rep["status"] == "insufficient_evidence":
            need = max(1, int(rep["ess_min"] - rep["ess"]) + 1)
            note = f"need ~{need} more resolution(s)"
        elif rep["status"] == "calibrated":
            note = "within noise — no direction"
        else:
            note = (rep.get("advisory_text") or "")[:70]
        print(f"{scope:<22} {rep['status']:<20} {rep['ess']:>6.1f} {rep['n']:>4} {sce:>9} {ci:>18}  {note}")


def _parse_outcome_paths(raw: list[str] | None) -> dict[str, str] | None:
    """Parse repeated --outcome-path 'Outcome=path text' flags into a map."""
    if not raw:
        return None
    paths: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise SystemExit(
                f"forecast: --outcome-path expects OUTCOME=PATH, got {item!r}"
            )
        name, path = item.split("=", 1)
        name = name.strip()
        if name:
            paths[name] = path.strip()
    return paths or None


def _cmd_tail_audit(args: argparse.Namespace) -> None:
    from forecasting.tail_audit import (
        audit_outcomes,
        outcome_paths_from_inputs,
        render_audit_table,
    )

    try:
        dist_raw = json.loads(args.tail_audit_dist)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"forecast tail-audit: invalid --dist JSON: {exc.msg}") from exc
    if not isinstance(dist_raw, dict) or not dist_raw:
        raise SystemExit("forecast tail-audit: --dist must be a non-empty JSON object")
    try:
        dist = {str(k): float(v) for k, v in dist_raw.items()}
    except (TypeError, ValueError):
        raise SystemExit("forecast tail-audit: distribution probabilities must be numeric")

    paths = _parse_outcome_paths(getattr(args, "tail_audit_paths", None))
    audit = audit_outcomes(outcome_paths_from_inputs(dist, paths))
    if getattr(args, "json", False):
        print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_audit_table(audit))
    if not audit.passes:
        raise SystemExit(1)


def _cmd_market_quality(args: argparse.Namespace) -> None:
    from forecasting.market_quality import (
        MarketReading,
        classify_market,
        reading_from_evidence,
    )

    try:
        markets = json.loads(args.market_quality_markets)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"forecast market-quality: invalid --markets JSON: {exc.msg}") from exc
    if not isinstance(markets, list) or not markets:
        raise SystemExit("forecast market-quality: --markets must be a non-empty JSON array")

    results = []
    for row in markets:
        if not isinstance(row, dict):
            continue
        if row.get("age_days") is not None:
            reading = MarketReading(
                source=str(row.get("source") or "market"),
                probability=row.get("probability"),
                volume=row.get("volume"),
                age_days=row.get("age_days"),
            )
        else:
            reading = reading_from_evidence(row)
        results.append(classify_market(reading))

    if getattr(args, "json", False):
        print(json.dumps([r.to_dict() for r in results], indent=2, sort_keys=True))
        return
    print(f"{'source':<28} {'tier':<12} {'weight':>6}  why")
    print(f"{'-' * 28} {'-' * 12} {'-' * 6}  {'-' * 30}")
    for r in results:
        print(f"{r.source[:28]:<28} {r.tier:<12} {r.weight:>6.2f}  {'; '.join(r.reasons)[:50]}")


def _cmd_track_record(args: argparse.Namespace) -> None:
    origin = None if args.forecast_origin == "any" else args.forecast_origin
    records = _ledger(args).component_track_record(
        forecast_origin=origin,
        min_count=args.min_count,
    )
    if args.kind != "all":
        records = [row for row in records if row["kind"] == args.kind]
    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
        return
    if not records:
        print(
            "No component track record yet — it accrues as questions whose "
            "snapshots carry ensemble_components (or panel runs) resolve and score."
        )
        return
    print(f"{'kind':<9} {'component':<16} {'n':>3} {'comp_brier':>10} {'agg_brier':>10} {'edge':>8} {'shrunk':>8} {'weight':>7}  status")
    for row in records:
        print(
            f"{row['kind']:<9} {row['name']:<16} {row['count']:>3} "
            f"{row['component_brier_mean']:>10.4f} {row['aggregate_brier_mean']:>10.4f} "
            f"{row['edge_mean']:>+8.4f} {row['edge_shrunk']:>+8.4f} "
            f"{row['recommended_weight']:>7.2f}  {row['status']}"
        )
    print(
        "\nedge > 0 means the component beat the committed aggregate. Weights are "
        "advisory — apply with `forecast panel record --track-record-weights`."
    )


def _print_calibration_cockpit(args: argparse.Namespace) -> None:
    """The `forecast calibration status` cockpit: makes claim_live_superforecasting
    ACTIONABLE in one view — the live track record + readiness requirements (passed
    AND failing) + the concrete next actions/commands to close each gap."""
    ledger = _ledger(args)
    _rows, summaries = _recent_backtest_summaries(ledger, last=20, dataset=None)
    evidence_status = build_forecasting_evidence_status(ledger, summaries)
    verdict = evidence_status.get("verdict")
    print("=== calibration / readiness cockpit ===")
    print(f"claim_live_superforecasting: {'SUPPORTED' if verdict == 'pass' else 'NOT YET — see gaps below'}")
    _print_evidence_status(evidence_status, include_passed=True)
    if not evidence_status.get("gaps"):
        print("\nAll readiness requirements met.")
    else:
        print("\nClose the next_actions above; `forecast readiness` shows the full backtest breakdown.")


def _cmd_lessons_audit(args: argparse.Namespace) -> None:
    rows = _ledger(args).lesson_coverage()
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No active calibration lessons.")
        return
    print("Lesson coverage — is each learning actually being used?")
    print(f"{'Lesson':<15} {'Kind':<9} {'Scope':<22} {'InScope':<8} {'Applied':<8} Status")
    for r in rows:
        if r["dormant"]:
            status = "DORMANT — never in scope since creation"
        elif not r["enforceable"]:
            status = "advisory — prose only, will NOT bite"
        elif r["kind"] == "numeric" and r["application_rate"] < 1.0:
            status = f"applied {r['application_rate'] * 100:.0f}% of in-scope commits"
        else:
            status = "enforced"
        print(f"{r['lesson_id']:<15} {r['kind']:<9} {r['scope']:<22} {r['in_scope_count']:<8} {r['applied_count']:<8} {status}")
    dormant = [r for r in rows if r["dormant"]]
    advisory = [r for r in rows if not r["enforceable"]]
    if dormant:
        print(f"\n{len(dormant)} DORMANT lesson(s) — never encountered an in-scope forecast; retire or re-scope.")
    if advisory:
        print(f"{len(advisory)} ADVISORY lesson(s) — prose only; compile to a `rule` so they enforce instead of decorate.")


def _cmd_lessons_apply(args: argparse.Namespace) -> None:
    result = _ledger(args).apply_lesson(args.lesson_id, severity=args.severity)
    if not result["applied"]:
        print(f"{args.lesson_id}: not applied — {result['reason']}.")
        print("  Declare `enforcement_pattern` in the lesson's recommended_adjustment, or use a recognized process_rule.")
        return
    import json as _json

    print(f"{args.lesson_id}: applied pattern '{result['pattern']}' at {result['severity'].upper()} — it now enforces at commit for its scope.")
    print(f"  check: {_json.dumps(result['check'])}")


def _cmd_scores_board(args: argparse.Namespace) -> None:
    _print_cohort_scoreboard(_ledger(args).cohort_scoreboard())


def _cmd_scores_audit(args: argparse.Namespace) -> None:
    audit = _ledger(args).scores_audit()
    if getattr(args, "json", False):
        print(json.dumps(audit, indent=2, sort_keys=True))
        return
    counts = audit.get("counts") or {}
    total = sum(counts.values())
    print(f"scores audit: {total} pathological row(s) (Brier=1.0 or |log|>10)")
    for reason in sorted(counts):
        print(f"  {reason}: {counts[reason]}")
    proposed = audit.get("proposed_quarantine") or []
    if proposed:
        print(f"proposed quarantine (provable artifacts, {len(proposed)}):")
        for row in proposed[:12]:
            print(f"  - {row['score_id']}  {row['title']!r}  brier={row.get('brier_score')}")
        if len(proposed) > 12:
            print(f"  … and {len(proposed) - 12} more")
        print("  apply with: forecast scoreboard quarantine --apply")
    else:
        print("no provable artifacts to quarantine.")


def _cmd_scores_quarantine(args: argparse.Namespace) -> None:
    apply = getattr(args, "apply", False)
    report = _ledger(args).quarantine_artifact_scores(dry_run=not apply)
    verb = "quarantined" if apply else "would quarantine"
    print(f"{verb} {report['count']} artifact score row(s) (dry_run={report['dry_run']}).")
    for origin, impact in (report.get("cohort_impact") or {}).items():
        before = _format_metric(impact.get("mean_brier_before"))
        after = _format_metric(impact.get("mean_brier_after"))
        if before != after:
            print(f"  {origin}: mean_brier {before} -> {after}")
    if not apply and report["count"]:
        print("  confirm with: forecast scoreboard quarantine --apply")


def _cmd_scores_backfill_crps(args: argparse.Namespace) -> None:
    apply = getattr(args, "apply", False)
    report = _ledger(args).backfill_crps_scores(dry_run=not apply)
    counts = report.get("counts") or {}
    print(
        f"crps backfill (dry_run={report['dry_run']}): "
        f"crps_scored={counts.get('crps_scored', 0)} rescored={counts.get('rescored', 0)} "
        f"refused={counts.get('refused_not_representable', 0)} "
        f"active_no_resolution={counts.get('active_no_resolution', 0)}"
    )
    for detail in (report.get("details") or []):
        if detail.get("action") in {"would_score", "would_rescore", "scored", "rescored"}:
            crps = detail.get("crps")
            crps_txt = _format_metric(crps) if crps is not None else "-"
            print(f"  {detail['question_id']}  {detail['action']}  crps={crps_txt}  rule={detail.get('rule')}")


def _cmd_scores_postmortem_misses(args: argparse.Namespace) -> None:
    apply = getattr(args, "apply", False)
    report = _ledger(args).create_continuous_miss_postmortem_stubs(
        dry_run=not apply, min_crps=getattr(args, "min_crps", 0.0)
    )
    verb = "created" if apply else "would create"
    proposed = report.get("proposed") or []
    print(f"{verb} {report['created'] if apply else len(proposed)} continuous-miss postmortem STUB(s) (dry_run={report['dry_run']}).")
    for item in proposed:
        gap = item.get("gap")
        gap_txt = f"{gap:+.4g}" if gap is not None else "-"
        print(
            f"  {item['question_id']}  direction={item['direction']}  "
            f"central={item.get('forecast_central')} outcome={item.get('outcome')} "
            f"gap={gap_txt}  crps={_format_metric(item.get('crps'))}"
        )
    if not apply and proposed:
        print("  create the stubs with: forecast scoreboard postmortem-misses --apply")


def _print_hierarchical_calibration(args: argparse.Namespace) -> None:
    """Held-out per-cohort Brier: global vs hierarchical Platt (BLF A4).

    READ-ONLY. The numbers here are the operator's evidence for flipping
    ``FORECAST_HIERARCHICAL_CALIBRATION`` on: where a cohort's base-rate skew makes
    a per-cohort intercept beat the single global map on OUT-OF-SAMPLE Brier."""

    ledger = _ledger(args)
    report = ledger.validate_hierarchical_calibration(
        min_cohort_n=getattr(args, "min_cohort_n", None),
        folds=getattr(args, "folds", 5),
        split_by_venue=getattr(args, "split_by_venue", False),
        since=getattr(args, "since", None),
        recency_halflife_days=getattr(args, "recency_halflife_days", None),
    )
    if getattr(args, "as_json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    print("hierarchical Platt calibration — held-out per-cohort Brier (global vs per-cohort intercept)")
    print(f"  rows={report.get('n', 0)}  folds={report.get('folds')}  min_cohort_n={report.get('min_cohort_n')}")
    for note in report.get("notes", []):
        print(f"  note: {note}")
    if report.get("lambda") is not None:
        ceiling = " [pinned at grid ceiling — offsets unsupported]" if report.get("lambda_at_ceiling") else ""
        print(f"  ridge lambda (LOO-CV): {report['lambda']:g}{ceiling}")
    cohorts = report.get("cohorts") or {}
    if cohorts:
        print("  cohort                             n   identity    global   hierarch    delta  helps  offset")
        for name, row in cohorts.items():
            print(
                f"  {name:<32} {row['n']:>5.0f}  {row['brier_identity']:>8.4f} "
                f"{row['brier_global']:>8.4f} {row['brier_hierarchical']:>9.4f} "
                f"{row['delta_brier_global_minus_hier']:>+8.4f}  "
                f"{'yes' if row.get('materially_helps') else ' no':>5}  "
                f"{'yes' if row['has_offset'] else ' no':>5}"
            )
    overall = report.get("overall") or {}
    if overall:
        print(
            f"  overall: global={overall['brier_global']:.4f} "
            f"hierarchical={overall['brier_hierarchical']:.4f} "
            f"delta={overall['delta_brier_global_minus_hier']:+.4f} "
            f"(material bar {report.get('material_brier_delta', 0.001)})"
        )
    rec = report.get("recommendation", "insufficient_data")
    improved = report.get("large_cohorts_improved")
    tail = f" ({improved} offset-cohort(s) materially improve)" if improved is not None else ""
    print(f"  recommendation: {rec}{tail}")
    if rec == "flip_on":
        print("  → set FORECAST_HIERARCHICAL_CALIBRATION=on to activate the per-cohort intercepts.")
    elif rec == "marginal":
        print("  → gain is inside the noise; keep global (do not flip) until it clears the material bar.")


def _cmd_calibration(args: argparse.Namespace) -> None:
    if getattr(args, "hierarchical", False):
        _print_hierarchical_calibration(args)
        return
    if getattr(args, "operator", False):
        _print_operator_calibration(
            _ledger(args),
            window_days=getattr(args, "operator_window_days", None),
        )
        return
    if getattr(args, "mode", "summary") == "status":
        _print_calibration_cockpit(args)
        return
    if getattr(args, "bias", False):
        _print_calibration_bias(args)
        return
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
    ledger = _ledger(args)
    summary = ledger.calibration_summary(
        domain=args.domain,
        forecast_origin=args.forecast_origin,
        horizon=args.horizon,
        calibration_eligible=None if args.all else True,
    )
    # Cohort scoreboard FIRST — the honest, un-pooled default read. Only on the
    # unfiltered global view (a domain/origin/horizon filter is already a slice).
    if not (args.domain or args.forecast_origin or args.horizon):
        try:
            _print_cohort_scoreboard(ledger.cohort_scoreboard())
        except Exception:
            pass
    _print_calibration_summary(summary)
    # Plain-language read (S7): the measured signed-bias advisory teaching text for
    # this scope, then the active lessons CORRECTING forecasts here + whether they
    # are biting. Best-effort — a thin/legacy ledger simply prints nothing.
    try:
        report = ledger.calibration_bias(domain=args.domain)
        advisory = report.get("advisory_text")
        if advisory:
            print(f"advisory: {advisory}")
    except Exception:
        pass
    try:
        lessons = ledger.calibration_correcting_lessons(domain=args.domain)
    except Exception:
        lessons = []
    if lessons:
        print("lessons_correcting_this:")
        for row in lessons:
            cov = row.get("coverage") or {}
            adj = row.get("recommended_adjustment") or {}
            adj_bits = [
                f"{k}={v}"
                for k, v in adj.items()
                if k in ("probability_delta", "logit_shift", "logit_scale")
            ]
            adj_str = f" [{', '.join(adj_bits)}]" if adj_bits else ""
            dormant = " DORMANT" if row.get("dormant") else ""
            print(
                f"  {row['scope']}: {(row.get('lesson') or '')[:70]}{adj_str} "
                f"(applied {cov.get('applied_count', 0)}/{cov.get('in_scope_count', 0)}){dormant}"
            )


# ── Operator practice loop (R2) ──────────────────────────────────────────
# Tetlock training: score the OPERATOR, not just the system. `practice` records
# the human's own number (scored when the question resolves); `drill` replays
# resolved questions and scores on the spot; `calibration --operator` reports the
# human's own reliability + a vs-system pairing.


def _parse_operator_estimate(raw: str) -> Any:
    """Parse a CLI-entered operator estimate: a bare number in [0,1] for a
    binary, or a JSON distribution dict. Raises SystemExit with a clear message
    on bad input (so the interactive flow fails politely)."""

    text = (raw or "").strip()
    if not text:
        raise SystemExit("practice: no estimate entered")
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"practice: distribution is not valid JSON: {exc}")
        if not isinstance(payload, dict):
            raise SystemExit("practice: distribution must be a JSON object")
        return payload
    try:
        value = float(text)
    except ValueError:
        raise SystemExit(f"practice: '{text}' is not a number in [0, 1] or a JSON distribution")
    if not (0.0 <= value <= 1.0):
        raise SystemExit("practice: probability must be in [0, 1]")
    return value


def _print_operator_calibration(ledger: "ForecastLedger", *, window_days: int | None = None) -> None:
    summary = ledger.operator_calibration_summary(window_days=window_days)
    n = summary["n"]
    window_note = f" over the last {window_days}d" if window_days else ""
    print(f"operator calibration ({n} scored estimate(s)){window_note}:")
    print(f"  brier: {_format_metric(summary['brier'])}")
    vs = summary.get("vs_system") or {}
    if vs.get("shared_n"):
        print(
            f"  vs system (shared {vs['shared_n']} question(s)): "
            f"operator={_format_metric(vs.get('operator_brier'))} "
            f"system={_format_metric(vs.get('system_brier'))}"
        )
    trend = summary.get("trend") or {}
    if trend.get("direction"):
        print(f"  trend: {trend['direction']}")
    curve = [row for row in summary.get("calibration_curve", []) if row["count"]]
    if curve:
        print("  reliability curve (predicted -> observed):")
        for row in curve:
            print(
                f"    {row['bucket']}: n={row['count']} "
                f"predicted={_format_optional_float(row['mean_predicted'])} "
                f"observed={_format_optional_float(row['observed_frequency'])}"
            )
    if n == 0:
        print("  no scored operator estimates yet — try `forecast practice <id>` or `forecast drill`.")


def _cmd_practice(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    question_id = _resolve_question_id(ledger, args.question_ref)
    question = ledger.get_question(question_id)
    otype = question.outcome_space.type
    print(f"practice: {question.title}")
    print(f"  resolution: {question.resolution_criteria}")
    if otype == "binary":
        prompt = "your probability of YES (0-1): "
    else:
        prompt = f"your estimate ({otype}) — a number in [0,1] or a JSON distribution: "
    try:
        raw = input(prompt)
    except EOFError:
        raise SystemExit("practice: no input received (stdin closed)")
    value = _parse_operator_estimate(raw)
    estimate = ledger.record_operator_estimate(
        question_id, value, note=getattr(args, "note", None), context="practice"
    )
    print(
        f"recorded operator estimate {estimate['id']} — it will be scored when "
        f"'{question.title}' resolves. See `forecast calibration --operator`."
    )


# A desk drill on a question resolved within this window risks RECALL rather than
# calibration practice (the operator watched it resolve). We prefer older
# resolutions and warn when only recent ones remain. The ForecastBench corpus
# (obscure questions the operator has never seen) sidesteps the problem entirely.
_DRILL_MEMORY_WINDOW_DAYS = 30


def _resolution_age_days(resolution: Any, now: Any) -> float | None:
    """Age in days of a confirmed resolution, or None when undatable."""

    resolved_at = getattr(resolution, "resolved_at", None)
    if not resolved_at:
        return None
    try:
        resolved_dt = timestamp_to_datetime(resolved_at)
    except Exception:
        return None
    if resolved_dt is None or now is None:
        return None
    return (now - resolved_dt).total_seconds() / 86400.0


def _drill_candidates(
    ledger: "ForecastLedger", *, domain: str | None, limit: int
) -> list[tuple[Any, Any]]:
    """Resolved, scoreable, binary questions the operator has NOT yet estimated,
    each paired with its confirmed resolution.

    MEMORY-LEAK GUARD: a question the operator watched resolve is recall, not
    calibration practice. We therefore PREFER questions resolved more than
    :data:`_DRILL_MEMORY_WINDOW_DAYS` days ago (older = less contaminated) and only
    fall back to recent ones to fill the requested count."""

    now = timestamp_to_datetime(utc_now_iso())
    older: list[tuple[Any, Any]] = []
    recent: list[tuple[Any, Any]] = []
    for question in ledger.list_questions(status="resolved", domain=domain):
        if question.outcome_space.type != "binary":
            continue
        if ledger.list_operator_estimates(question.id):
            continue  # already drilled/practiced — no repeats
        resolution = ledger.get_latest_resolution(question.id, confirmed_only=True)
        if resolution is None:
            continue
        age = _resolution_age_days(resolution, now)
        if age is not None and age > _DRILL_MEMORY_WINDOW_DAYS:
            older.append((question, resolution))
        else:
            recent.append((question, resolution))
        if len(older) >= limit:
            break
    selected = older[:limit]
    if len(selected) < limit:
        selected += recent[: limit - len(selected)]
    return selected


def _forecastbench_drill_prompt_text(case: dict[str, Any]) -> str:
    """The EXACT text a corpus drill shows the operator for one case.

    Built ONLY from pre-freeze fields — the question, its background, the
    resolution criteria, and the case's freeze-pinned context evidence (which
    carries no live source URL). It NEVER reads ``case['outcome']`` (the answer)
    nor ``case['baselines']`` (the freeze market probability — an equally
    revealing answer leak). Because those fields are never consulted, the rendered
    text is invariant to them; the drill's leak tests assert exactly that."""

    lines: list[str] = [str(case.get("title") or "").strip()]
    background = str(case.get("description") or "").strip()
    if background:
        lines.append(f"  background: {background}")
    criteria = str(case.get("resolution_criteria") or "").strip()
    if criteria:
        lines.append(f"  resolution criteria: {criteria}")
    context_rows: list[str] = []
    for item in case.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or item.get("summary") or "").strip()
        if not claim:
            continue
        available_at = str(item.get("available_at") or "").strip()
        stamp = f"[{available_at}] " if available_at else ""
        context_rows.append(f"    - {stamp}{claim}")
    if context_rows:
        lines.append("  context available at the forecast freeze:")
        lines.extend(context_rows)
    return "\n".join(lines)


def _forecastbench_drill_cases(
    ledger: "ForecastLedger", *, date: str, limit: int
) -> list[dict[str, Any]] | None:
    """Resolved BINARY ForecastBench cases the operator has NOT yet drilled.

    Reuses the SAME loading seam the backtest uses
    (:func:`forecasting.forecastbench.load_forecastbench_cases`, which reads the
    on-disk cache and only touches the network for an uncached date). Returns
    ``None`` when no dataset can be loaded (so the caller can degrade politely);
    an empty list means the dataset loaded but every case is already drilled."""

    from forecasting.forecastbench import ForecastBenchError, load_forecastbench_cases

    try:
        report = load_forecastbench_cases(
            date, binary_only=True, resolved_only=True
        )
    except ForecastBenchError:
        return None
    cases = report.get("cases") or []
    drilled = {
        estimate["question_id"]
        for estimate in ledger.list_operator_estimates()
        if str(estimate.get("question_id", "")).startswith("fb:")
    }
    fresh: list[dict[str, Any]] = []
    for case in cases:
        if case.get("outcome") not in ("yes", "no"):
            continue  # scoreable binary outcomes only
        if f"fb:{case['id']}" in drilled:
            continue  # never repeat a case the operator has already seen
        fresh.append(case)
        if len(fresh) >= limit:
            break
    return fresh


def _resolve_drill_bench_date(requested: str | None) -> str:
    """Resolve the ForecastBench date for an EXPLICIT --corpus forecastbench.

    An explicit ``--date`` wins (including the literal 'latest', which fetches);
    otherwise prefer the newest locally-cached set so the common case stays
    offline, falling back to 'latest' only when nothing is cached."""

    from forecasting.forecastbench import available_forecastbench_dates

    requested = (requested or "").strip()
    if requested:
        return requested
    cached = available_forecastbench_dates()
    return cached[0] if cached else "latest"


def _run_forecastbench_drill(
    ledger: "ForecastLedger", *, date: str, limit: int
) -> None:
    """Deliberate-practice drill over obscure resolved ForecastBench questions."""

    cases = _forecastbench_drill_cases(ledger, date=date, limit=limit)
    if cases is None:
        print(
            "no benchmark dataset available for the drill — cache one with "
            "`forecast backtest --dataset forecastbench:latest ...`, or use "
            "`forecast drill --corpus desk`."
        )
        return
    if not cases:
        print(
            "no un-drilled ForecastBench cases available (you've drilled them all) "
            "— try a different --date or `forecast drill --corpus desk`."
        )
        return
    print(
        f"ForecastBench drill ({len(cases)} obscure resolved question(s)) — "
        "closed-book: you've never seen these, and neither the outcome nor the "
        "market price is shown."
    )
    drill_briers: list[float] = []
    for index, case in enumerate(cases, start=1):
        print(f"\n[{index}/{len(cases)}] {_forecastbench_drill_prompt_text(case)}")
        try:
            raw = input("  your probability of YES (0-1), or blank to stop: ")
        except EOFError:
            break
        if not raw.strip():
            break
        value = _parse_operator_estimate(raw)
        if not isinstance(value, (int, float)):
            print("  drill is binary-only — enter a probability in [0, 1].")
            continue
        estimate = ledger.record_and_score_corpus_drill(
            f"fb:{case['id']}", value, case["outcome"]
        )
        this_brier = estimate.get("brier")
        if this_brier is not None:
            drill_briers.append(float(this_brier))
        print(
            f"  outcome: {case['outcome']}  |  your Brier: {_format_metric(this_brier)}"
        )
    _finish_drill(ledger, drill_briers)


def _run_desk_drill(
    ledger: "ForecastLedger",
    candidates: list[tuple[Any, Any]],
    *,
    domain: str | None,
) -> None:
    """Drill the operator's OWN resolved questions (the recall-risk corpus)."""

    if not candidates:
        print(
            "no un-drilled resolved binary questions available"
            + (f" in domain '{domain}'" if domain else "")
            + " — resolve some binary forecasts first, or try "
            "`forecast drill --corpus forecastbench`."
        )
        return
    now = timestamp_to_datetime(utc_now_iso())
    only_recent = all(
        (_resolution_age_days(res, now) or 0.0) <= _DRILL_MEMORY_WINDOW_DAYS
        for _, res in candidates
    )
    if only_recent:
        print(
            "note: these resolved within the last "
            f"{_DRILL_MEMORY_WINDOW_DAYS} days — you may remember the outcomes, so "
            "this leans toward recall. For never-seen questions, try "
            "`forecast drill --corpus forecastbench`."
        )
    drill_briers: list[float] = []
    for index, (question, resolution) in enumerate(candidates, start=1):
        print(f"\n[{index}/{len(candidates)}] {question.title}")
        print(f"  resolution criteria: {question.resolution_criteria}")
        # Honest replay: show only evidence that existed BEFORE resolution, and
        # never the outcome. resolved_at bounds what was knowable at the time.
        resolved_at = resolution.resolved_at
        prior_evidence = [
            item
            for item in ledger.list_evidence(question.id)
            if item.available_at and resolved_at and item.available_at < resolved_at
        ]
        if prior_evidence:
            print("  evidence available before resolution:")
            for item in prior_evidence[:5]:
                source = item.source_url or item.source_name or item.source_type
                print(f"    - [{item.available_at}] {item.claim or item.summary} ({source})")
        else:
            print("  (no pre-resolution evidence recorded)")
        try:
            raw = input("  your probability of YES (0-1), or blank to stop: ")
        except EOFError:
            break
        if not raw.strip():
            break
        value = _parse_operator_estimate(raw)
        if not isinstance(value, (int, float)):
            print("  drill is binary-only — enter a probability in [0, 1].")
            continue
        estimate = ledger.record_operator_estimate(
            question.id, value, context="drill"
        )
        scored = ledger.score_operator_estimates(question.id, resolution.outcome)
        this_brier = next(
            (row["brier"] for row in scored if row["id"] == estimate["id"] and row["brier"] is not None),
            None,
        )
        if this_brier is None:
            # Fall back to a re-read in case scoring paired a different row.
            this_brier = ledger.get_operator_estimate(estimate["id"]).get("brier")
        if this_brier is not None:
            drill_briers.append(float(this_brier))
        print(
            f"  outcome: {resolution.outcome}  |  your Brier: {_format_metric(this_brier)}"
        )
    _finish_drill(ledger, drill_briers)


def _finish_drill(ledger: "ForecastLedger", drill_briers: list[float]) -> None:
    if drill_briers:
        running = sum(drill_briers) / len(drill_briers)
        print(f"\ndrill Brier (this session, {len(drill_briers)} scored): {running:.6f}")
    else:
        print("\nno estimates scored this session.")
    _print_operator_calibration(ledger)


def _cmd_drill(args: argparse.Namespace) -> None:
    # Non-interactive guard: a drill needs a live human at a TTY to enter numbers.
    if not sys.stdin.isatty():
        raise SystemExit(
            "forecast drill needs an interactive terminal (stdin is not a TTY). "
            "Run it from a shell, or use `forecast practice <id>` in a pipeline."
        )
    ledger = _ledger(args)
    limit = max(1, int(getattr(args, "n", 5) or 5))
    domain = getattr(args, "domain", None)
    corpus = (getattr(args, "corpus", None) or "").strip().lower() or None

    if corpus == "forecastbench":
        _run_forecastbench_drill(
            ledger, date=_resolve_drill_bench_date(getattr(args, "date", None)), limit=limit
        )
        return
    if corpus == "desk":
        _run_desk_drill(
            ledger, _drill_candidates(ledger, domain=domain, limit=limit), domain=domain
        )
        return

    # AUTO (no explicit --corpus): reach for the ForecastBench corpus when its
    # dataset is CACHED (no surprise network) AND the desk can't supply a full
    # never-drilled set — obscure, never-seen questions beat recall-contaminated
    # ones. Otherwise fall back to the desk.
    from forecasting.forecastbench import available_forecastbench_dates

    candidates = _drill_candidates(ledger, domain=domain, limit=limit)
    cached_dates = available_forecastbench_dates()
    if len(candidates) < limit and cached_dates:
        _run_forecastbench_drill(ledger, date=cached_dates[0], limit=limit)
        return
    _run_desk_drill(ledger, candidates, domain=domain)


def _cmd_complementarity(args: argparse.Namespace) -> None:
    """AIA P1.3 — fit the convex market+LLM Brier-minimizing blend over resolved
    questions and report the LOO additive value + bootstrap weight CI. READ-ONLY:
    it never edits a forecast or the live advisory weight; it only reports whether
    a fitted weight WOULD ship under the strict sample+LOO+CI gate."""
    from forecasting.market_ensemble import complementarity_report

    report = complementarity_report(
        _ledger(args),
        forecast_origin=args.forecast_origin,
        min_sample=max(int(args.min_sample), 2),
    )
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    def _fmt(value: Any) -> str:
        return f"{value:.4f}" if isinstance(value, (int, float)) else "-"

    print(f"resolved market+LLM pairs: {report['n']} (skipped: {report['skipped']})")
    weights = report.get("weights")
    if not weights:
        print("weights: not fitted (insufficient sample)")
    else:
        ci = report.get("bootstrap_ci_95") or {}
        for source in sorted(weights):
            lo, hi = (ci.get(source) or [None, None])[:2]
            band = f" [95% CI {lo:.3f}-{hi:.3f}]" if isinstance(lo, (int, float)) else ""
            print(f"  w[{source}] = {weights[source]:.4f}{band}")
    per = report.get("per_source_brier") or {}
    for source in sorted(per):
        print(f"  brier[{source}] = {_fmt(per[source])}")
    print(f"  ensemble_brier (in-sample) = {_fmt(report.get('ensemble_brier'))}")
    print(f"  loo_ensemble_brier (honest) = {_fmt(report.get('loo_ensemble_brier'))}")
    print(f"  blend beats BOTH inputs (LOO): {bool(report.get('beats_both'))}")
    decision = report.get("advisory_weight_decision") or {}
    ships = "WOULD SHIP" if decision.get("fitted") else "static weight kept"
    print(f"  advisory weight: {ships} — {decision.get('reason', '')}")
    for note in report.get("notes", []):
        print(f"  note: {note}")


def _cmd_ablation(args: argparse.Namespace) -> None:
    """AIA P2.2 — 2x2 search/judge ablation over resolved binary backtest cases.

    Reports per-cell mean Brier (search ON/OFF x judge ON/OFF) plus the marginal
    Brier *reduction* attributable to agentic-search and to the judge, and the
    non-additive interaction term. READ-ONLY: it groups cases by the arm that was
    ACTUALLY recorded (never a guessed arm), and never edits a forecast or the
    live default search/judge configuration."""
    from forecasting.search_ablation import ablation_report

    report = ablation_report(_ledger(args))
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    def _fmt(value: Any) -> str:
        return f"{value:+.6f}" if isinstance(value, (int, float)) else "-"

    print(f"binary backtest cases scanned: {report['n_cases']} (binned: {report['n_binned']})")
    coverage = report.get("coverage") or {}
    print(f"cells present: {coverage.get('present_count', 0)}/4 (complete: {bool(coverage.get('complete'))})")
    labels = {"00": "search OFF, judge OFF", "01": "search OFF, judge ON",
              "10": "search ON,  judge OFF", "11": "search ON,  judge ON"}
    cell_brier = report.get("cell_brier") or {}
    n_by_cell = coverage.get("n_by_cell") or {}
    for key in ("00", "01", "10", "11"):
        if key in cell_brier:
            print(f"  [{labels[key]}] mean_brier = {cell_brier[key]:.6f} (n={n_by_cell.get(key, 0)})")
        else:
            print(f"  [{labels[key]}] (no recorded cases)")
    print(f"  search_contribution (Brier reduction) = {_fmt(report.get('search_contribution'))}")
    print(f"  judge_contribution  (Brier reduction) = {_fmt(report.get('judge_contribution'))}")
    print(f"  interaction (non-additive) = {_fmt(report.get('interaction'))}")
    uncovered = report.get("uncovered") or {}
    if any(uncovered.values()):
        parts = ", ".join(f"{k}={v}" for k, v in sorted(uncovered.items()) if v)
        print(f"  uncovered (excluded, not guessed): {parts}")


def _cmd_market_nightly_run(args: argparse.Namespace) -> None:
    """AIA P2.1 — the LIVE, SEARCH-ENABLED proof: forecast OPEN markets NOW.

    The inverse of the closed-book backtest runner. ``sample`` (above) pilots the
    loop OFFLINE from a JSON file; ``run`` is the real forward proof:

      1. Fetch currently-OPEN markets from a SOURCE ADAPTER (manifold|metaculus|…).
      2. Keep only strictly-future-close markets (the foreknowledge filter) and
         take up to ``--count`` with a seeded deterministic pick.
      3. Forecast each with the SEARCH-ENABLED informed agent (web search ON — this
         is the legitimate live path, NOT closed-book) via
         :func:`build_informed_market_forecaster`.
      4. ``record_pending`` stamps everything at NOW (live availability) and records
         the agent forecast alongside the de-vigged market price as the baseline.

    The market-hidden ForecastBench result proved the closed-book LLM has NO
    intrinsic edge over the market; the only path to beating it is fresh
    information — provable ONLY forward, because searching a RESOLVED question
    leaks the answer. This command accrues that out-of-sample, overfit-proof
    record. No live LLM/market call is made under test (both seams are injected).
    """
    from forecasting.market_nightly import (
        default_market_devig,
        record_pending,
        sample_open_markets,
    )
    from forecasting.market_nightly_forecaster import (
        build_informed_market_forecaster,
        load_open_markets,
    )
    from hermes_cli.config import cfg_get, load_config

    # available_at / evidence stamping is NOW (live): the whole point is the agent
    # uses fresh search on an OPEN market whose outcome does not exist yet. There is
    # NO closed-book restriction here (the inverse of _backtest_agent_protocol_runner).
    as_of = utc_now_iso()
    n = max(0, int(getattr(args, "count", 10) or 0))
    source = getattr(args, "source", "manifold") or "manifold"
    seed = int(getattr(args, "rng_seed", 0) or 0)

    cfg = load_config()
    # Resolve the agent model with the SAME logic the quorum uses (config["model"]
    # is a structured dict since the codex auth overhaul).
    model = getattr(args, "model", None) or _resolve_active_model_id(cfg.get("model"))

    # A/B research arm: CLI flag wins, else config default (itself 'plain' so the
    # existing accrued record stays comparable). 'both' forecasts each market TWICE.
    arm_choice = getattr(args, "research_arm", None) or cfg_get(
        cfg, "forecasting", "market_nightly", "research_arm", default="plain"
    )
    arm_choice = str(arm_choice or "plain").strip().lower()
    if arm_choice == "both":
        arms = ["plain", "voi"]
    elif arm_choice == "voi":
        arms = ["voi"]
    else:
        arms = ["plain"]

    try:
        candidates = load_open_markets(source, limit=max(n * 4, n, 1))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"forecast market-nightly run: could not load open markets: {exc}") from exc

    picked = sample_open_markets(candidates, as_of, n, rng_seed=seed)

    # Bounded parallelism over the slow per-market agent calls. N>1 forecasts up to
    # N markets concurrently; each worker gets its OWN agent (fresh_agent_per_call)
    # since the reused single agent carries non-thread-safe conversation state.
    # record_pending keeps every ledger write serialized regardless; N=1 preserves
    # the sequential recorded/skipped SET (notes may differ only on a narrow
    # intra-batch-duplicate edge — see record_pending's docstring).
    max_workers = max(1, int(getattr(args, "parallel", 1) or 1))

    ledger = _ledger(args)
    runs: list[Any] = []
    for arm in arms:
        forecaster_kwargs: dict[str, Any] = {"model": model, "research_arm": arm}
        if getattr(args, "max_iterations", None) is not None:
            forecaster_kwargs["max_iterations"] = int(args.max_iterations)
        if max_workers > 1:
            forecaster_kwargs["fresh_agent_per_call"] = True
        forecaster = build_informed_market_forecaster(**forecaster_kwargs)
        runs.append(
            record_pending(
                ledger,
                picked["sampled"],
                as_of,
                forecaster,
                default_market_devig,
                max_workers=max_workers,
                arm=arm,
            )
        )

    if getattr(args, "json", False):
        out = {
            "as_of": as_of,
            "source": source,
            "model": model,
            "research_arm": arm_choice,
            "candidates": len(candidates),
            "admissible": picked["admissible"],
            "sampled": len(picked["sampled"]),
            "rejected_sampling": picked["rejected"],
            "runs": {run.arm: run.to_dict() for run in runs},
        }
        # Back-compat: single-arm runs keep the flat "run" key existing tooling reads.
        if len(runs) == 1:
            out["run"] = runs[0].to_dict()
        print(json.dumps(out, indent=2, sort_keys=True))
        return

    print(f"market-nightly run @ {as_of}  (source={source}, model={model or 'active default'}, arm={arm_choice})")
    print(f"  candidates fetched: {len(candidates)}  admissible (future close): {picked['admissible']}")
    for run in runs:
        print(f"  [arm {run.arm}] sampled: {len(picked['sampled'])}  recorded: {run.n_recorded}  "
              f"rejected: {run.n_rejected}  skipped: {len(run.skipped_ids)}")
        for row in run.recorded:
            print(f"    - {row['question_id']} market={row['market_id']} "
                  f"agent={row['agent_forecast']:.3f} market={row['market_devig_probability']:.3f} "
                  f"close={row['close_time']}")
        for note in run.notes:
            print(f"    note: {note}")


def _cmd_market_nightly_sample(args: argparse.Namespace) -> None:
    """AIA P2.1 — sample currently-OPEN markets and record pending benchmark entries.

    Markets are read from a LOCAL JSON file (``--markets-json``); this command
    NEVER contacts a live market API. The agent forecast for each market is an
    OFFLINE seam: a constant ``--agent-prob`` or a per-market ``--agent-prob-field``
    (so the loop can be piloted without an LLM call). The foreknowledge-proof
    filter keeps ONLY markets whose close is STRICTLY after ``as_of``; rejected
    candidates are counted, never stored."""
    from forecasting.market_nightly import record_pending, sample_open_markets

    path = Path(args.markets_json).expanduser()
    try:
        markets = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"could not read markets JSON {path}: {exc}")
    if not isinstance(markets, list):
        raise SystemExit("markets JSON must be a JSON array of market dicts")

    as_of = args.as_of or utc_now_iso()
    picked = sample_open_markets(markets, as_of, args.count, rng_seed=args.rng_seed)

    if args.agent_prob is not None:
        const = float(args.agent_prob)
        forecaster = lambda _market: const  # noqa: E731 - explicit offline seam
    elif args.agent_prob_field:
        field = args.agent_prob_field
        forecaster = lambda market: market.get(field)  # noqa: E731 - explicit offline seam
    else:
        raise SystemExit(
            "provide --agent-prob <p> or --agent-prob-field <name> (the agent forecaster "
            "is an explicit offline seam; no LLM/market call is made by default)"
        )

    run = record_pending(_ledger(args), picked["sampled"], picked["as_of"], forecaster)
    if getattr(args, "json", False):
        out = {"sample": {k: v for k, v in picked.items() if k != "sampled"}, "run": run.to_dict()}
        print(json.dumps(out, indent=2, sort_keys=True))
        return
    print(f"as_of: {picked['as_of']}")
    print(f"candidates: {len(markets)}  admissible (future close): {picked['admissible']}  rejected: {picked['rejected']}")
    print(f"recorded pending: {run.n_recorded}  rejected at store: {run.n_rejected}  skipped: {len(run.skipped_ids)}")
    for row in run.recorded:
        print(f"  - {row['question_id']} market={row['market_id']} agent={row['agent_forecast']:.3f} market={row['market_devig_probability']:.3f} close={row['close_time']}")
    for note in run.notes:
        print(f"  note: {note}")


def _cmd_market_nightly_score(args: argparse.Namespace) -> None:
    """AIA P2.1 — score pending benchmark entries whose market has since resolved."""
    from forecasting.market_nightly import score_matured

    result = score_matured(_ledger(args), now=args.now)
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    print(f"now: {result['now']}")
    print(f"scored: {result['n_scored']}  still pending: {result['n_still_pending']}")
    for row in result["scored"]:
        ab = row.get("agent_brier")
        mb = row.get("market_brier")
        ab_s = f"{ab:.4f}" if isinstance(ab, (int, float)) else "-"
        mb_s = f"{mb:.4f}" if isinstance(mb, (int, float)) else "-"
        print(f"  - {row['question_id']} outcome={row['outcome']} agent_brier={ab_s} market_brier={mb_s}")
    for note in result["notes"]:
        print(f"  note: {note}")


def _cmd_edge(args: argparse.Namespace) -> None:
    """UPGRADE 2 — read-only roll-up of the deviation ledger (named-edge bets vs market)."""
    report = _ledger(args).deviation_bet_edge_report()
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    def _fmt(value: Any) -> str:
        return f"{value:.4f}" if isinstance(value, (int, float)) else "-"

    n = report["n"]
    print(
        f"deviation bets — scored: {n}  open (pending resolution): {report.get('n_open', 0)}"
        f"  [{report['status']}]"
    )
    if n == 0:
        print(f"  {report['recommendation']}")
        return
    wr = report.get("win_rate")
    print(
        f"  win-rate vs market = "
        + (f"{wr:.0%} ({report['agent_wins']}/{n})" if isinstance(wr, (int, float)) else "-")
        + f"  (agent/market/ties = {report['agent_wins']}/{report['market_wins']}/{report['ties']})"
    )
    print(f"  mean Brier: ours = {_fmt(report.get('mean_brier_ours'))}  market = {_fmt(report.get('mean_brier_market'))}")
    edge = report.get("mean_brier_delta")
    lo = report.get("ci95_low")
    hi = report.get("ci95_high")
    band = (
        f" [95% CI {lo:+.4f}..{hi:+.4f}]"
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float))
        else ""
    )
    print(
        "  mean Brier delta (market - ours, +ve ⇒ we beat market) = "
        + (f"{edge:+.4f}{band}" if isinstance(edge, (int, float)) else "-")
    )
    p = report.get("p_value")
    if isinstance(p, (int, float)):
        print(f"  paired-bootstrap p-value = {p:.4f}")
    print(f"  RECOMMENDATION: {report['recommendation']}")


def _cmd_market_nightly_report(args: argparse.Namespace) -> None:
    """AIA P2.1 — read-only roll-up of the foreknowledge-proof live benchmark."""
    from forecasting.market_nightly import market_nightly_report

    report = market_nightly_report(_ledger(args))
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    def _fmt(value: Any) -> str:
        return f"{value:.4f}" if isinstance(value, (int, float)) else "-"

    n_contemp = report.get("n_contemporaneous", 0)
    n_frozen = report.get("n_frozen_excluded", 0)
    print(
        f"pending: {report['n_pending']}  scored: {report['n_scored']}"
        f"  (contemporaneous: {n_contemp}, frozen-excluded: {n_frozen})"
    )
    # HEADLINE agent-vs-market: CONTEMPORANEOUS baselines ONLY (frozen priors quarantined
    # — a stale freeze price cannot contaminate the "agent beats the market" claim). The
    # clean mean Briers and paired edge are all computed over the contemporaneous subset.
    print(f"  HEADLINE agent vs market [contemporaneous baselines only, n={n_contemp}]")
    print(f"    mean agent Brier  = {_fmt(report.get('contemporaneous_mean_agent_brier'))}")
    print(f"    mean market Brier = {_fmt(report.get('contemporaneous_mean_market_brier'))}")
    edge = report.get("paired_agent_edge_mean_brier")
    lo = report.get("paired_agent_edge_ci95_low")
    hi = report.get("paired_agent_edge_ci95_high")
    band = f" [95% CI {lo:.4f}..{hi:.4f}]" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else ""
    print(f"    paired agent edge (market_brier - agent_brier) = {edge:+.4f}{band}" if isinstance(edge, (int, float)) else "    paired agent edge = -")
    p = report.get("paired_p_value")
    print(f"    paired p-value = {p:.4f}" if isinstance(p, (int, float)) else "    paired p-value = -")
    print(f"    wins agent/market/ties = {report.get('paired_agent_wins', 0)}/{report.get('paired_baseline_wins', 0)}/{report.get('paired_ties', 0)}")
    # DIAGNOSTICS — surfaced for transparency, NEVER the headline edge.
    full = report.get("full_set") or {}
    if full.get("n_scored"):
        ue = full.get("paired_agent_edge_mean_brier")
        print(
            f"  [diagnostic] full set: all {full.get('n_scored', 0)} samples incl. "
            f"{n_frozen} frozen-baseline excluded from edge"
        )
        print(f"    mean agent Brier  = {_fmt(full.get('mean_agent_brier'))}")
        print(f"    mean market Brier = {_fmt(full.get('mean_market_brier'))}")
        print(
            f"    full-set edge (incl. frozen) = "
            + (f"{ue:+.4f}" if isinstance(ue, (int, float)) else "-")
        )
    frozen = report.get("frozen_diagnostic") or {}
    if frozen.get("n_scored"):
        fe = frozen.get("paired_agent_edge_mean_brier")
        print(
            f"  [diagnostic] agent-vs-FROZEN-prior edge (n={frozen.get('n_scored', 0)}, NOT the claim) = "
            + (f"{fe:+.4f}" if isinstance(fe, (int, float)) else "-")
        )

    # A/B ARM SPLIT — per-arm agent-vs-market (contemporaneous baselines only).
    by_arm = report.get("by_arm") or {}
    for arm in ("plain", "voi"):
        a = by_arm.get(arm) or {}
        if not a.get("n_scored"):
            continue
        edge = a.get("paired_agent_edge_mean_brier")
        edge_s = f"{edge:+.4f}" if isinstance(edge, (int, float)) else "-"
        print(
            f"  [arm {arm}] n={a['n_scored']}  mean agent Brier={_fmt(a.get('mean_agent_brier'))}"
            f"  vs market={_fmt(a.get('mean_market_brier'))}  agent-vs-market edge={edge_s}"
        )

    # THE A/B SCOREBOARD — paired voi-vs-plain Brier delta (markets with BOTH arms).
    vp = report.get("paired_voi_vs_plain") or {}
    if vp.get("n_paired"):
        d = vp.get("delta_mean_brier")
        p = vp.get("p_value")
        lo = vp.get("ci95_low")
        hi = vp.get("ci95_high")
        band = (
            f" [95% CI {lo:+.4f}..{hi:+.4f}]"
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float))
            else ""
        )
        d_s = f"{d:+.4f}" if isinstance(d, (int, float)) else "-"
        p_s = f"{p:.2f}" if isinstance(p, (int, float)) else "-"
        # Honest significance note: only claim significance at the seeded-bootstrap p.
        sig = "significant" if isinstance(p, (int, float)) and p < 0.05 else "not yet significant"
        print(
            f"  voi arm: n={vp['n_paired']} paired, ΔBrier(plain−voi, +=VOI better)={d_s}{band}, "
            f"p={p_s} — {sig}"
        )
        print(
            f"    wins voi/plain/ties = {vp.get('voi_wins', 0)}/{vp.get('plain_wins', 0)}/{vp.get('ties', 0)}"
        )


def _print_cohort_scoreboard(board: dict[str, Any]) -> None:
    """Print the score aggregates SEPARATED BY COHORT — the honest default. The
    live calibration-eligible stratum (the only skill-claim cohort) is kept apart
    from the market-visible baselines; the continuous (CRPS) class gets its own
    scorecard; the pooled Brier is shown only as a labelled diagnostic."""
    cohorts = board.get("cohorts") or {}
    print("scoreboard (by cohort — never a pooled skill claim):")
    order = [
        ("live_calibration_eligible", "live (calibration-eligible)"),
        ("backtest", "backtest (market-visible)"),
        ("imported_baseline", "imported_baseline (market-visible)"),
        ("market_nightly", "market_nightly (market-hidden bench)"),
    ]
    for key, label in order:
        row = cohorts.get(key) or {}
        domains = ", ".join(row.get("domains") or []) or "-"
        adjusted = row.get("mean_brier_difficulty_adjusted")
        adj_display = _format_metric(adjusted) if adjusted is not None else "n/a"
        print(
            f"  {label}: n={row.get('n_brier', 0)} "
            f"brier={_format_metric(row.get('mean_brier'))} "
            f"difficulty-adjusted={adj_display} domains=[{domains}]"
        )
    diff = board.get("difficulty_adjustment") or {}
    if diff:
        ref = diff.get("reference_difficulty")
        provenance = ", ".join(f"{k}={v}" for k, v in (diff.get("provenance") or {}).items()) or "-"
        print(
            "  difficulty adjustment (ABI-style — a hard-question desk is not punished): "
            f"reference={_format_metric(ref) if ref is not None else 'n/a'} "
            f"eligible={diff.get('n_eligible', 0)} no-anchor={diff.get('n_no_anchor', 0)} "
            f"[{provenance}]"
        )
    cont = board.get("continuous_scorecard") or {}
    print(
        f"  continuous scorecard (CRPS/log — a Brier cannot represent it): "
        f"n={cont.get('n', 0)} mean_crps={_format_metric(cont.get('mean_crps'))} "
        f"mean_log={_format_metric(cont.get('mean_log_score'))}"
    )
    by_rule = cont.get("by_rule") or {}
    for rule, stats in by_rule.items():
        print(f"    {rule}: n={stats.get('n', 0)} mean_crps={_format_metric(stats.get('mean_crps'))}")
    pooled = board.get("pooled_diagnostic") or {}
    print(
        f"  {pooled.get('label', 'pooled diagnostic')}: "
        f"n={pooled.get('n', 0)} brier={_format_metric(pooled.get('mean_brier'))}"
    )
    quarantined = board.get("quarantined") or {}
    if quarantined.get("n"):
        reasons = ", ".join(f"{k}={v}" for k, v in (quarantined.get("reasons") or {}).items())
        print(f"  quarantined (excluded from every cohort): n={quarantined['n']} [{reasons}]")


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
    ece = summary.get("expected_calibration_error")
    mce = summary.get("max_calibration_error")
    curve = summary.get("calibration_curve") or []
    populated = [row for row in curve if row["count"]]
    print(f"expected_calibration_error: {_format_metric(ece)}")
    print(f"max_calibration_error: {_format_metric(mce)}")
    print(f"calibration_curve_sample_count: {summary.get('calibration_curve_sample_count', 0)}")
    if populated:
        print("calibration_curve (P(yes): predicted vs observed):")
        for row in populated:
            print(
                f"  {row['bucket']}: n={row['count']} "
                f"predicted={_format_metric(row['mean_predicted'])} "
                f"observed={_format_metric(row['observed_frequency'])} "
                f"gap={_format_metric(row['calibration_gap'])} {row['sample_status']}"
            )
    print("buckets:")
    if not summary["buckets"]:
        print("  none")
    else:
        for bucket in summary["buckets"]:
            print(
                f"  {bucket['bucket']}: n={bucket['count']} "
                f"mean_brier={_format_metric(bucket['mean_brier'])} {bucket['sample_status']}"
            )
    trend = summary.get("calibration_trend") or {}
    windows = trend.get("windows") or []
    if windows:
        print(f"calibration_trend ({trend.get('direction', 'insufficient')}):")
        for window in windows:
            print(
                f"  {window['period']}: n={window['n']} "
                f"mean_brier={_format_metric(window.get('brier'))} "
                f"sce={_format_metric(window.get('sce'))}"
            )
    if label is not None:
        print()


def _cmd_errors(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    profiles = ledger.list_domain_error_profiles(domain=args.domain, topic=args.topic)
    summary = ledger.calibration_summary(domain=args.domain)
    active_reviews = _active_learned_error_review_rows(
        ledger,
        domain=args.domain,
        topic=args.topic,
        limit=args.limit,
    )
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
    if active_reviews:
        print("active_reviews:")
        for row in active_reviews:
            question = row["question"]
            alert = row["alert"]
            profile_id = row["profile_id"] or "-"
            topics = ",".join(question.topics) or "*"
            print(
                f"  {question.id} profile={profile_id} scope={question.domain or '*'}:{topics} "
                f"alert={alert.id}"
            )
            print(f"    next: {alert.recommended_action or _review_next_action(question.id, [alert.reason])}")
    if summary["mean_brier"] is None:
        print("recurring_errors: insufficient scored forecasts")
    elif summary["mean_brier"] > 0.25:
        print("recurring_errors: elevated average Brier score; inspect postmortems before adjusting priors")
    else:
        print("recurring_errors: no high-level pattern detected from scored forecasts")


def _cmd_review(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    rows = ledger.review_questions(
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
    _merge_learned_error_reviews(
        rows,
        ledger=ledger,
        domain=args.domain,
        topic=args.topic,
        horizon=args.horizon,
        confidence_below=args.confidence_below,
        confidence_above=args.confidence_above,
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


def _active_learned_error_review_rows(
    ledger: ForecastLedger,
    *,
    domain: str | None = None,
    topic: str | None = None,
    horizon: str | None = None,
    confidence_below: float | None = None,
    confidence_above: float | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if limit is not None and limit <= 0:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for alert in ledger.list_alerts(unresolved_only=True):
        if alert.scope_type != "question" or not is_learned_error_review_reason(alert.reason):
            continue
        key = (alert.scope_ref, alert.reason)
        if key in seen:
            continue
        seen.add(key)
        try:
            question = ledger.get_question(alert.scope_ref)
        except ForecastingError:
            continue
        if question.status != "active":
            continue
        snapshot = ledger.get_current_snapshot(question.id)
        if not _review_alert_matches_filters(
            ledger,
            question=question,
            snapshot=snapshot,
            domain=domain,
            topic=topic,
            horizon=horizon,
            confidence_below=confidence_below,
            confidence_above=confidence_above,
        ):
            continue
        rows.append(
            {
                "alert": alert,
                "question": question,
                "current_snapshot": snapshot,
                "profile_id": learned_error_profile_id(alert.reason),
            }
        )
        if limit is not None and len(rows) >= limit:
            break
    return rows


def _merge_learned_error_reviews(
    rows: list[dict[str, Any]],
    *,
    ledger: ForecastLedger,
    domain: str | None = None,
    topic: str | None = None,
    horizon: str | None = None,
    confidence_below: float | None = None,
    confidence_above: float | None = None,
) -> None:
    rows_by_id = {row["question"].id: row for row in rows}
    for learned_row in _active_learned_error_review_rows(
        ledger,
        domain=domain,
        topic=topic,
        horizon=horizon,
        confidence_below=confidence_below,
        confidence_above=confidence_above,
    ):
        question = learned_row["question"]
        alert = learned_row["alert"]
        existing = rows_by_id.get(question.id)
        if existing is not None:
            reasons = existing.setdefault("reasons", [])
            if alert.reason not in reasons:
                reasons.append(alert.reason)
            existing["priority"] = min(int(existing.get("priority") or 9), 4)
            continue
        row = {
            "question": question,
            "current_snapshot": learned_row["current_snapshot"],
            "reasons": [alert.reason],
            "priority": 4,
        }
        rows.append(row)
        rows_by_id[question.id] = row
    _sort_review_rows(rows)


def _review_alert_matches_filters(
    ledger: ForecastLedger,
    *,
    question: Any,
    snapshot: Any,
    domain: str | None,
    topic: str | None,
    horizon: str | None,
    confidence_below: float | None,
    confidence_above: float | None,
) -> bool:
    if domain and question.domain != domain:
        return False
    if topic and topic not in question.topics:
        return False
    if horizon and (
        snapshot is None or not ledger._horizon_matches(snapshot.forecast_horizon_days, horizon)
    ):
        return False
    if confidence_below is not None or confidence_above is not None:
        if snapshot is None or snapshot.confidence is None:
            return False
        if confidence_below is not None and snapshot.confidence >= confidence_below:
            return False
        if confidence_above is not None and snapshot.confidence <= confidence_above:
            return False
    return True


def _sort_review_rows(rows: list[dict[str, Any]]) -> None:
    rows.sort(
        key=lambda row: (
            int(row.get("priority") or 9),
            row["question"].close_time or row["question"].resolution_time or "9999-12-31T00:00:00Z",
            row["question"].title.lower(),
        )
    )


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


def _cmd_schedule_dedupe(args: argparse.Namespace) -> None:
    result = _ledger(args).dedupe_scheduled_reviews()
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    if result["disabled_count"] == 0:
        print("No duplicate scheduled reviews found.")
        return
    print(
        f"Collapsed {result['groups_collapsed']} duplicate group(s); "
        f"disabled {result['disabled_count']} redundant review(s)."
    )
    for review_id in result["disabled"]:
        print(f"  disabled {review_id}")


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


def _cmd_cycle_run(args: argparse.Namespace) -> None:
    # The single closed-loop entrypoint: reuses the cron cycle with full-cycle
    # defaults so a lazy operator gets the whole loop in one command — due reviews
    # (auto-scored + auto-postmortemed), alert reconciliation, thesis re-aggregation,
    # and calibration-lesson synthesis. The autonomous --agent reforecast + push
    # notifications are a further layer on top of this deterministic cycle.
    from forecasting import cron_runner

    synthesize: bool | None = None
    if getattr(args, "synthesize_lessons", False):
        synthesize = True
    elif getattr(args, "no_synthesize_lessons", False):
        synthesize = False

    reforecast_runner = _build_cycle_reforecast_runner(args) if getattr(args, "agent", False) else None

    report = cron_runner.run_due_reviews(
        db_path=str(_ledger(args).db_path),
        now=args.now,
        auto_score=True,
        auto_postmortem=True,
        thesis_aggregate=not getattr(args, "no_thesis_aggregate", False),
        reconcile_alerts=not getattr(args, "no_reconcile", False),
        synthesize_lessons=synthesize,
        reforecast_runner=reforecast_runner,
    )
    report = (report or "").strip()
    print(report if report else "Forecast cycle complete — nothing was due.")


def _build_cycle_reforecast_runner(args: argparse.Namespace):
    """The CLI-layer callable the cron cycle invokes to autonomously re-forecast the
    questions a sweep flagged. It validates each candidate is a LIVE question, honors
    the pipeline update gate (skip + report blockers unless --force), caps the count
    (--max-questions), runs the LLM update stage, and returns per-question result
    dicts. Lives here so run_agent is never imported by cron_runner/ledger.

    NOTE (deliberate deferred follow-up): the commit-material policy is enforced at
    the PROMPT layer (the agent owns the gated `update_forecast` commit) and this
    runner only REPORTS the outcome honestly — it classifies a committed snapshot by
    is_material_move and surfaces a marginal-delta commit as status "marginal", not
    as a material-move success. We intentionally do NOT build a flow-forces-commit
    HARD gate that captures the agent's freeform preview number and auto-commits it:
    that would have to parse a probability out of free text (brittle), could not
    re-run the saturation/structured-reasoning/panel gates the real commit path
    enforces, and would write a number the agent never actually decided to commit. A
    deterministic commit gate, if ever wanted, is a separate carefully-designed
    change — out of scope for a sweep. See _COMMIT_MATERIAL_POLICY in protocol.py."""
    from forecasting.warnings import is_material_move

    ledger = _ledger(args)
    model, provider = args.model, args.provider
    _mi = getattr(args, "max_iterations", None)
    max_iter = 12 if _mi is None else _mi
    max_q = getattr(args, "max_questions", None)
    force = getattr(args, "force", False)

    def _runner(question_ids: list[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        processed = 0  # questions an LLM run was actually started for (the expensive bit)
        for qid in question_ids:
            if max_q is not None and processed >= max_q:
                results.append({"question_id": qid, "status": "skipped", "detail": f"--max-questions {max_q} reached"})
                continue
            try:
                question = ledger.get_question(qid)
            except Exception:
                question = None
            if question is None or getattr(question, "status", None) != "active":
                results.append({"question_id": qid, "status": "skipped", "detail": "not an active question"})
                continue
            counted = False  # whether this question already consumed one of the max_q session budgets
            if not force:
                pstatus = build_pipeline_status(ledger, qid)
                if not pstatus.get("update_ready", True):
                    # BOOTSTRAP instead of skip: drive the missing prerequisite
                    # stages (research, then base_rate) through the SAME gated agent
                    # chain, then re-check the gate. This is what lets the cron sweep
                    # re-forecast a FRESH question an operator just dropped in — not
                    # only ones hand-researched already. Skip stays the honest
                    # fallback when bootstrap fails to satisfy the gate.
                    blockers = pstatus.get("update_blockers") or []
                    prereq_stages = [s for s in ("research", "base_rate") if s in blockers]
                    errored: list[str] = []
                    if prereq_stages:
                        # A bootstrap runs up to 2 real, multi-minute LLM stages, so it
                        # must COUNT against --max-questions the moment it starts —
                        # otherwise a batch of never-ready questions burns 2N uncounted
                        # sessions (each hits `continue` below without incrementing).
                        # Counting here (not after) bounds the expensive work honestly;
                        # `counted` then suppresses the pre-update increment so a
                        # question that bootstraps AND proceeds to update is charged once.
                        processed += 1
                        counted = True
                        # run_forecast_chain captures a raising stage per-stage (it
                        # never re-raises), so the sweep is not aborted by a flaky
                        # bootstrap; a still-closed gate below is the honest fallback.
                        boot = run_forecast_chain(
                            ledger, qid, model=model, provider=provider,
                            max_iterations=max_iter, stages=prereq_stages,
                            commit_policy="commit_material",
                        )
                        errored = [s["stage"] for s in boot["stages"] if s.get("status") == "error"]
                        pstatus = build_pipeline_status(ledger, qid)
                    if not pstatus.get("update_ready", True):
                        still = ", ".join(pstatus.get("update_blockers") or []) or "prerequisites missing"
                        detail = f"update gated after bootstrap: {still}"
                        if errored:
                            detail += f" (bootstrap stage error: {', '.join(errored)})"
                        results.append({"question_id": qid, "status": "skipped", "detail": detail})
                        continue
            prior = ledger.get_current_snapshot(qid)
            # Count BEFORE the agent runs: the cap bounds expensive multi-minute LLM
            # sessions, so a question that ran but declined to commit still counts.
            # A question that already paid for its budget in the bootstrap above
            # (counted=True) is not charged twice.
            if not counted:
                processed += 1
            try:
                _run_update_agent(
                    ledger, qid, model=model, provider=provider,
                    max_iterations=max_iter, commit_policy="commit_material",
                )
            except Exception as exc:  # one failure must not abort the sweep
                results.append({"question_id": qid, "status": "error", "detail": str(exc)[:160]})
                continue
            post = ledger.get_current_snapshot(qid)
            new_commit = post is not None and (prior is None or post.forecast_id != prior.forecast_id)
            if new_commit:
                # Classify the commit by MATERIALITY (the same is_material_move
                # primitive the prompt instructs the agent to apply): a MATERIAL
                # move is the success the auto-reforecast wants; a MARGINAL-delta
                # commit that slipped through the prompt-level policy is reported
                # HONESTLY as "marginal" — it is NOT tallied as a material-move
                # success, so the sweep's status counts and the result detail stay
                # truthful (and surface the Δp that justifies the classification).
                prior_p = prior.probability_or_distribution if prior is not None else None
                material = is_material_move(prior_p, post.probability_or_distribution)
                delta = None
                if isinstance(prior_p, (int, float)) and not isinstance(prior_p, bool) and isinstance(
                    post.probability_or_distribution, (int, float)
                ) and not isinstance(post.probability_or_distribution, bool):
                    delta = float(post.probability_or_distribution) - float(prior_p)
                if material:
                    detail = f"new snapshot {post.forecast_id}"
                    if delta is not None:
                        detail += f" (Δp {delta:+.3f})"
                    results.append({"question_id": qid, "status": "committed", "detail": detail})
                else:
                    detail = f"new snapshot {post.forecast_id} committed at a MARGINAL move"
                    if delta is not None:
                        detail += f" (Δp {delta:+.3f}, under the |Δp|>=0.03 material-move threshold)"
                    results.append({"question_id": qid, "status": "marginal", "detail": detail})
            else:
                results.append({"question_id": qid, "status": "skipped", "detail": "agent committed no new snapshot"})
        return results

    return _runner


# ---------------------------------------------------------------------------
# Warning resolution (the open alert_events backlog)
# ---------------------------------------------------------------------------

def _build_warning_runners(args: argparse.Namespace, ledger: ForecastLedger):
    """Wire the slice-1 dispatcher's injected runners to the REAL gated paths.

    Each runner performs genuine gated work and signals success by returning a
    truthy result (a committed snapshot / a non-failed autopilot run / a written
    postmortem). The dispatcher acks ONLY on that truthy result, so the
    load-bearing rule holds: no bare ack to make the number drop.
    """
    from forecasting.cron_runner import build_warning_runners

    # REFORECAST runner: only wired when --agent is set, because the real gated
    # work is an LLM update-stage run. Without --agent we leave REFORECAST alerts
    # OPEN (the dispatcher reports them "skipped") rather than bare-acking them.
    reforecast_runner = None
    evidence_search = None
    triage_runner = None
    triage_model = None
    if getattr(args, "agent", False):
        _inner = _build_cycle_reforecast_runner(args)

        def reforecast_runner(_led, warning):  # noqa: ARG001 — uses the closed-over runner
            if not warning.scope_ref:
                return None
            results = _inner([warning.scope_ref])
            # A landed snapshot is real gated work regardless of materiality, so the
            # alert resolves on either a "committed" (material) OR a "marginal" commit
            # — the material/marginal split is the cycle TALLY's honesty concern, not
            # the alert-ack decision. A gated/declined/errored run lands no snapshot
            # ("skipped"/"error") → falsy → the alert stays open (never bare-acked).
            landed = [r for r in results if r.get("status") in {"committed", "marginal"}]
            return landed[0] if landed else None

        # EVIDENCE_COLLECTION search: the LLM/web research-stage pass that
        # bootstraps a question with NO evidence yet (it searches + imports through
        # the gated import_source_evidence path). cron_runner wraps this in the
        # >= 1-new-row gate, so the alert acks ONLY when real evidence landed.
        evidence_search = _build_evidence_search(args)

        # PAID evidence-autopilot (S6.1): the CHEAP auto-labeler for the
        # MATERIAL_CHANGE path. Wired only under --agent so the free continuous tick
        # never spends; bounded to one small labeler call per material change.
        triage_runner, triage_model = build_triage_runner(model=getattr(args, "model", None))

    # The autopilot (MATERIAL_CHANGE) + score (POSTMORTEM) runners are the shared,
    # non-LLM gated paths — factored into cron_runner so the CLI, the cron phase,
    # the gateway, and the agent tool all wire identical "real work" semantics.
    return build_warning_runners(
        ledger,
        now=getattr(args, "now", None),
        reforecast_runner=reforecast_runner,
        evidence_search=evidence_search,
        triage_runner=triage_runner,
        triage_model=triage_model,
    )


def build_triage_runner(*, model: str | None = None):
    """Construct the CHEAP triage auto-labeler runner + resolved model id.

    Returns ``(runner, model)`` where ``runner`` has the injected labeler shape
    ``(model, system, user) -> str``. The SAME construction the ``triage_label``
    tool action uses (``forecasting.quorum.make_aiagent_runner``), so the CLI, the
    tool, and the evidence-autopilot all label with identical wiring. Accessed via
    the ``quorum`` module (not a ``from`` import) so tests can monkeypatch
    ``forecasting.quorum.make_aiagent_runner`` like ``tests/forecasting/test_triage.py``.
    """
    from forecasting import appconfig, quorum

    resolved = model or appconfig.get_str("FORECAST_TRIAGE_MODEL") or quorum.DEFAULT_JUDGE_MODEL
    runner = quorum.make_aiagent_runner(toolsets=(), max_iterations=2, quiet=True, timeout=180)
    return runner, resolved


def _build_evidence_search(args: argparse.Namespace):
    """The AGENT-tier callable the EVIDENCE_COLLECTION runner invokes to research +
    import evidence for a no-evidence question. Runs the LLM `research`-stage agent
    (web + forecasting toolsets), which imports readings through the gated
    `import_source_evidence` path. Lives here so run_agent is never imported by
    cron_runner/ledger; cron_runner owns the >= 1-new-row ack gate."""
    model, provider = args.model, args.provider
    _mi = getattr(args, "max_iterations", None)
    max_iter = 12 if _mi is None else _mi

    def _search(led, warning):  # noqa: ARG001 — uses the question id off the warning
        if warning.scope_type != "question" or not warning.scope_ref:
            return None
        return _run_update_agent(
            led, warning.scope_ref,
            model=model, provider=provider, max_iterations=max_iter, stage="research",
        )

    return _search


def build_cron_warning_agent_runners(
    *,
    db_path: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int | None = None,
    now: str | None = None,
):
    """Build the paid-tier (LLM) warning-automode runners for the no-agent cron
    entrypoint: returns ``(reforecast_runner, evidence_search)``.

    Lives in the CLI layer so ``run_agent`` is NEVER imported by
    ``forecasting.cron_runner`` (layer purity). ``cron_runner.main_warning_automode``
    imports this lazily only when ``--agent`` is set. The closures mirror the
    ``--agent`` wiring in :func:`_build_warning_runners` exactly (the reforecast
    closure is truthy ONLY when the agent committed a fresh snapshot; the evidence
    search is the research-stage import pass cron_runner wraps in its >=1-new-row
    ack gate)."""
    args = argparse.Namespace(
        db=db_path,
        model=model,
        provider=provider,
        max_iterations=max_iterations,
        now=now,
        agent=True,
        force=False,
        max_questions=None,
    )
    _inner = _build_cycle_reforecast_runner(args)

    def reforecast_runner(_led, warning):  # noqa: ARG001 — uses the closed-over runner
        if not warning.scope_ref:
            return None
        results = _inner([warning.scope_ref])
        # A landed snapshot is real gated work regardless of materiality (mirrors the
        # --agent wiring above): resolve the alert on a "committed" OR "marginal"
        # commit, leave it OPEN only when no snapshot landed.
        landed = [r for r in results if r.get("status") in {"committed", "marginal"}]
        return landed[0] if landed else None

    evidence_search = _build_evidence_search(args)
    return reforecast_runner, evidence_search


def _warning_plan_entry(warning, runners) -> dict[str, Any]:
    """Pure (no-write) preview of what ``resolve_alert`` WOULD do for ``warning``.

    Thin shim over :func:`forecasting.warnings.plan_alert` (kept for the existing
    callers/tests) so `automode --dry-run` shows the plan without spending a
    single gated runner call or acking anything.
    """
    from forecasting.warnings import plan_alert

    return plan_alert(warning, runners)


def _print_warning_result(result: dict[str, Any]) -> None:
    flag = {
        "resolved": "resolved",
        "surfaced": "surfaced",
        "failed": "open",
        "skipped": "open",
    }.get(result.get("status", ""), result.get("status", "?"))
    print(
        f"{result['alert_id']}  [{flag}] {result.get('kind', '?'):<15} "
        f"{result.get('reason', ''):<34} {result.get('detail', '')}"
    )


def _cmd_warnings_list(args: argparse.Namespace) -> None:
    from forecasting import warnings as fwarn

    ledger = _ledger(args)
    scope = getattr(args, "scope", None)
    # Shared summarizer: identical grouping/priority as the gateway's
    # forecast.warnings.list, so the desk + CLI can never drift.
    summary = fwarn.summarize_open_warnings(
        ledger, scope=scope, reason=getattr(args, "reason", None), limit=args.limit
    )
    ordered = summary["groups"]
    open_total = summary["open_total"]
    group_count = summary["group_count"]

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    if not ordered:
        print("No open warnings.")
        return

    print(f"{open_total} open warning(s) across {group_count} reason group(s) (worst/oldest first):")
    print(f"{'Count':>5}  {'Sev':<7} {'Kind':<15} {'Reason':<34} Recommended action")
    for group in ordered:
        action = (group["recommended_action"] or "").replace("\n", " ").strip()
        if len(action) > 60:
            action = action[:57] + "..."
        reason = group["reason"]
        if len(reason) > 34:
            reason = reason[:31] + "..."
        print(f"{group['count']:>5}  {group['severity']:<7} {group['kind']:<15} {reason:<34} {action}")


def _cmd_warnings_resolve(args: argparse.Namespace) -> None:
    from forecasting import warnings as fwarn
    from forecasting.ledger import allow_ledger_writes

    ledger = _ledger(args)
    runners = _build_warning_runners(args, ledger)
    target = (args.target or "").strip()

    open_alerts = ledger.list_alerts(unresolved_only=True)
    if target.startswith("al_"):
        selected = [a for a in open_alerts if a.id == target]
        if not selected:
            print(f"warnings resolve: no open alert with id {target}", file=sys.stderr)
            raise SystemExit(1)
    else:
        # Treat the target as a scope ref (question id) or scope_type: resolve every
        # open alert for it, worst/oldest first.
        selected = [
            w.alert
            for w in fwarn.iter_warnings(ledger, scope=target)
        ]
        if not selected:
            print(f"warnings resolve: no open alerts for scope {target}", file=sys.stderr)
            raise SystemExit(1)

    results: list[dict[str, Any]] = []
    with allow_ledger_writes(reason="forecast_warnings_resolve"):
        for alert in selected:
            results.append(
                fwarn.resolve_alert(ledger, alert, runners=runners, now=getattr(args, "now", None))
            )

    if args.json:
        print(json.dumps({"results": results, "count": len(results)}, indent=2, sort_keys=True))
        return
    for result in results:
        _print_warning_result(result)


def _cmd_warnings_automode(args: argparse.Namespace) -> None:
    from forecasting.cron_runner import run_warning_resolution

    ledger = _ledger(args)
    runners = _build_warning_runners(args, ledger)
    dry_run = bool(getattr(args, "dry_run", False))

    # Drive the SAME factored, gated, interruptible phase the cron job + gateway
    # background job use, so there is one loop, one set of gating semantics.
    summary = run_warning_resolution(
        ledger=ledger,
        now=getattr(args, "now", None),
        limit=args.limit,
        reason=getattr(args, "reason", None),
        scope=getattr(args, "scope", None),
        kinds=getattr(args, "kinds", None),
        tier=getattr(args, "tier", None),
        dry_run=dry_run,
        reconcile=not getattr(args, "no_reconcile", False),
        runners=runners,
    )
    results = summary["results"]
    tally = summary["tally"]

    if dry_run:
        if args.json:
            print(
                json.dumps(
                    {"dry_run": True, "plan": results, "count": len(results), "tally": tally},
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        if not results:
            print("DRY RUN — no open warnings match.")
            return
        print(f"DRY RUN — {len(results)} open warning(s) would be processed by priority (no writes):")
        for entry in results:
            reason = entry["reason"]
            if len(reason) > 34:
                reason = reason[:31] + "..."
            print(
                f"  {entry['alert_id']}  [{entry['planned']}] {entry['kind']:<15} "
                f"{reason:<34} {entry['detail']}"
            )
        print("plan: " + ", ".join(f"{status}={count}" for status, count in sorted(tally.items())))
        return

    reconcile = summary["reconcile"]
    if args.json:
        print(
            json.dumps(
                {
                    "results": results,
                    "count": len(results),
                    "tally": tally,
                    "reconcile": reconcile,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    if not results:
        print("No open warnings to process.")
    for result in results:
        _print_warning_result(result)
    if results:
        print("summary: " + ", ".join(f"{status}={count}" for status, count in sorted(tally.items())))
    if reconcile is not None:
        print(f"reconcile: acknowledged {reconcile.get('reconciled_count', 0)} stale alert(s)")


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
        if is_learning_review_reason(alert.reason)
    ]
    print(f"ran {len(results)} scheduled review(s)")
    print(f"created {total_alerts} alert(s)")
    print(f"scores_created: {len(score_events)}")
    print(f"postmortems_created: {len(postmortem_events)}")
    print(f"learning_reviews: {len(learning_review_events)}")
    for result in results:
        review = result["review"]
        run = result.get("run") or {}
        run_suffix = f" run={run['id']}" if run.get("id") else ""
        print(f"{review['id']} next_run_at={review['next_run_at']} alerts={len(result['alerts'])}{run_suffix}")
        for alert in result["alerts"]:
            print(f"  {alert.id} {alert.scope_type}:{alert.scope_ref} {alert.reason}")


def _cmd_schedule_history(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    rows = ledger.list_scheduled_review_runs(
        scheduled_review_id=args.scheduled_review_id,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps({"runs": rows, "count": len(rows)}, indent=2, sort_keys=True))
        return
    if not rows:
        print("No scheduled review runs found.")
        return
    print("Run ID         Schedule       Run at               Alerts  Scores  Postmortems  Learning  Next run")
    for row in rows:
        print(
            f"{row['id']:<14} {row['scheduled_review_id']:<14} {row['run_at']:<20} "
            f"{int(row.get('alert_count') or 0):<7} "
            f"{int(row.get('score_count') or 0):<7} "
            f"{int(row.get('postmortem_count') or 0):<12} "
            f"{int(row.get('learning_review_count') or 0):<9} "
            f"{row['next_run_at']}"
        )


def _cmd_schedule_install_cron(args: argparse.Namespace) -> None:
    from forecasting.scheduler import install_forecast_cron

    job = install_forecast_cron(
        schedule=args.schedule,
        name=args.name,
        deliver=args.deliver,
        profile=args.profile,
        db_path=args.db,
        auto_score=getattr(args, "auto_score", True),
        auto_postmortem=getattr(args, "auto_postmortem", True),
        thesis_aggregate=getattr(args, "thesis_aggregate", True),
        synthesize_lessons=getattr(args, "synthesize_lessons", True),
        refresh_market_models=getattr(args, "refresh_market_models", True),
    )
    print(f"cron_job: {job['id']}")
    print(f"name: {job['name']}")
    print(f"schedule: {job['schedule_display']}")
    print(f"script: {job['script']}")
    print(f"mode: {'no-agent' if job.get('no_agent') else 'agent'}")


def _cmd_automode_cron_start(args: argparse.Namespace) -> None:
    from forecasting.scheduler import install_warning_automode_cron

    job = install_warning_automode_cron(
        schedule=args.schedule,
        name=args.name,
        deliver=args.deliver,
        profile=args.profile,
        db_path=getattr(args, "db", None),
        agent=getattr(args, "agent", True),
        paid_budget=getattr(args, "paid_budget", None),
        paid_min_interval_hours=getattr(args, "paid_min_interval_hours", None),
        model=getattr(args, "model", None),
        provider=getattr(args, "provider", None),
        max_iterations=getattr(args, "max_iterations", None),
    )
    print(f"cron_job: {job['id']}")
    print(f"name: {job['name']}")
    print(f"schedule: {job['schedule_display']}")
    print(f"script: {job['script']}")
    print(f"paid_tier: {'on' if getattr(args, 'agent', True) else 'off (free-only)'}")


def _cmd_automode_cron_stop(args: argparse.Namespace) -> None:
    from forecasting.scheduler import remove_warning_automode_cron

    removed = remove_warning_automode_cron(name=args.name)
    print(f"removed {removed} warning-automode cron job(s)")


def _cmd_automode_cron_status(args: argparse.Namespace) -> None:
    from forecasting.scheduler import warning_automode_cron_status

    status = warning_automode_cron_status(name=args.name)
    if getattr(args, "json", False):
        print(json.dumps(status, indent=2, sort_keys=True, default=str))
        return
    if not status["installed"]:
        print("warning-automode cron: not installed")
        print(f"last_paid_run_at: {status.get('last_paid_run_at') or '(never)'}")
        return
    job = status["job"]
    print("warning-automode cron: installed")
    print(f"job_id: {job['id']}")
    print(f"name: {job.get('name')}")
    print(f"schedule: {job.get('schedule_display')}")
    print(f"enabled: {job.get('enabled', True)}")
    print(f"last_run_at: {job.get('last_run_at') or '(never)'}")
    print(f"last_paid_run_at: {status.get('last_paid_run_at') or '(never)'}")


def _cmd_link_add(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    from_id = _resolve_question_id(ledger, args.from_ref)
    to_id = _resolve_question_id(ledger, args.to_ref)
    row = ledger.add_forecast_link(
        from_id,
        to_id,
        link_type=args.link_type,
        rationale=args.rationale or "",
        created_by="cli",
    )
    print(f"forecast link {row['id']}")
    print(f"type: {row['link_type']}")
    print(f"from: {row['from_question_id']}")
    print(f"to: {row['to_question_id']}")
    if row.get("rationale"):
        print(f"rationale: {row['rationale']}")


def _cmd_link_list(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    qid = _resolve_question_id(ledger, args.ref)
    related, shared = ledger.related_forecast_views(qid)
    if not related:
        print("No related forecasts (no explicit links and no auto matches).")
    else:
        print("Relationship      Type        Forecast")
        for rel in related:
            print(f"{(rel['relationship'] or '-'):<17} {(rel['link_type'] or '-'):<11} {rel['id']}  {rel.get('title') or ''}")
    if shared:
        print(f"shared sources (independence check): {', '.join(shared)}")


def _cmd_link_remove(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    from_id = _resolve_question_id(ledger, args.from_ref)
    to_id = _resolve_question_id(ledger, args.to_ref)
    removed = ledger.remove_forecast_link(from_id, to_id, link_type=getattr(args, "link_type", None))
    print(f"removed {removed} link(s) between {from_id} and {to_id}")



def _run_one(ledger: "ForecastLedger", question_id: str, args: argparse.Namespace) -> bool:
    """Refresh a single member forecast via the SAME deterministic re-pool the
    `forecast refresh` handler uses. Tolerant: logs and returns False on any
    failure so a batch run keeps going.
    """

    from tools.forecasting_tool import fetch_watched_source_payloads

    try:
        result = ledger.refresh_forecast(
            question_id,
            fetcher=lambda specs: fetch_watched_source_payloads(specs, concurrency=4),
            re_estimate="deterministic",
            trigger_reason="run_all_batch",
        )
    except Exception as exc:  # pragma: no cover — network/data variability
        print(f"  {question_id}: refresh failed ({exc})", file=sys.stderr)
        return False
    status = result.get("status")
    committed = result.get("forecast_id")
    if committed:
        try:
            _write_analyst_brief(ledger, question_id, ledger.get_snapshot(committed))
        except Exception:
            pass
    print(f"  {question_id}: {status}")
    return True


def _cmd_run_all(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    active = ledger.list_questions(status="active")
    members = [q for q in active if not ledger.is_thesis(q)]
    theses = [q for q in active if ledger.is_thesis(q)]
    if args.limit is not None:
        members = members[: args.limit]

    if args.dry_run:
        print(f"dry-run: would refresh {len(members)} member forecast(s) (phase 1):")
        for question in members:
            print(f"  {question.id}  {question.title}")
        # Order theses: plain (non-nested) first, nested (member of another thesis) last.
        ordered = _order_theses(ledger, theses)
        print(f"dry-run: would aggregate {len(ordered)} thesis/theses (phase 2):")
        for thesis in ordered:
            print(f"  {thesis.id}  {thesis.title}")
        return

    # Phase 1: refresh every active member forecast (commits their snapshots).
    ran = 0
    failed = 0
    print(f"phase1: refreshing {len(members)} member forecast(s)")
    for question in members:
        if _run_one(ledger, question.id, args):
            ran += 1
        else:
            failed += 1

    # Phase 2 (AFTER phase 1 commits): aggregate theses. Plain theses before
    # nested ones so a thesis-of-theses reads its members' fresh snapshots.
    ordered = _order_theses(ledger, theses)
    aggregated = 0
    print(f"phase2: aggregating {len(ordered)} thesis/theses")
    for thesis in ordered:
        try:
            ledger.aggregate_thesis(thesis.id, rho=args.rho)
            aggregated += 1
            print(f"  {thesis.id}: aggregated")
        except Exception as exc:  # pragma: no cover — keep batch going
            print(f"  {thesis.id}: aggregate failed ({exc})", file=sys.stderr)

    print(f"phase1: {ran} members run ({failed} failed); phase2: {aggregated} theses aggregated")


def _order_theses(ledger: "ForecastLedger", theses: list[Any]) -> list[Any]:
    """Run plain theses before nested ones: a thesis that is itself a member of
    another thesis (``list_theses_for_member`` non-empty) is deferred to the end.
    """

    plain: list[Any] = []
    nested: list[Any] = []
    for thesis in theses:
        if ledger.list_theses_for_member(thesis.id):
            nested.append(thesis)
        else:
            plain.append(thesis)
    return plain + nested


def _cmd_crux_add(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    qid = _resolve_question_id(ledger, args.question)
    crux = ledger.add_crux(
        question_id=qid, crux_variable=args.variable, preferred_roles=args.roles or None,
        materiality=args.materiality, status=args.status, notes=args.notes,
    )
    print(f"crux {crux['id']}  [{crux['materiality']}/{crux['status']}]  {crux['crux_variable']}")
    if crux["preferred_roles"]:
        print("  preferred roles: " + ", ".join(crux["preferred_roles"]))


def _cmd_crux_list(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    rows = ledger.list_cruxes(_resolve_question_id(ledger, args.question))
    if not rows:
        print("No crux variables registered.")
        return
    for crux in rows:
        roles = ", ".join(crux["preferred_roles"]) or "-"
        print(f"{crux['id']:<15} [{crux['materiality']:<6}/{crux['status']:<13}] {crux['crux_variable']}  ({roles})")


def _cmd_crux_status(args: argparse.Namespace) -> None:
    crux = _ledger(args).set_crux_status(args.crux_id, args.status)
    print(f"crux {crux['id']} -> {crux['status']}")


def _cmd_crux_backfill(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    apply = bool(getattr(args, "apply", False))
    if apply:
        from forecasting.ledger import allow_ledger_writes

        with allow_ledger_writes(reason="forecast crux backfill --apply"):
            result = ledger.backfill_panel_cruxes(dry_run=False)
    else:
        result = ledger.backfill_panel_cruxes(dry_run=True)
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    mode = "APPLIED" if apply else "DRY-RUN (pass --apply to write)"
    print(f"crux backfill {mode}")
    print(
        f"  scanned {result['runs_scanned']} panel run(s); "
        f"{result['panels_with_cruxes']} carried a crux; "
        f"{result['candidate_cruxes']} candidate crux(es)"
    )
    verb = "promoted" if apply else "would promote"
    print(
        f"  {verb} {result['promoted']} new crux(es); "
        f"skipped {result['skipped_existing']} already present"
    )


def _backfill_intervals_scan(ledger) -> dict[str, Any]:
    """Scan every LIVE vote-share board and propose per-candidate intervals from its
    existing panel/model artifacts. Read-only. Classifies each derivable board by the
    provenance SOURCE the committer would use (panel > model > default), so the report
    mirrors what a real re-forecast would stamp."""
    from forecasting.hooks.candidate_intervals import compute_candidate_share_intervals
    from forecasting.hooks.distribution import candidate_shares

    proposals: list[dict[str, Any]] = []
    counts = {"panel": 0, "model": 0, "default": 0, "none": 0, "already_present": 0}
    scanned = 0
    for question in ledger.list_questions(status="active"):
        osp = question.outcome_space
        if not (osp.type == "distribution" and getattr(osp, "choices", None)):
            continue
        snap = ledger.get_current_snapshot(question.id)
        if snap is None or (getattr(snap, "forecast_origin", "live") or "live") != "live":
            continue
        payload = snap.probability_or_distribution
        if not (isinstance(payload, dict) and candidate_shares(payload) is not None):
            continue
        scanned += 1
        meta = snap.metadata or {}
        existing = meta.get("candidate_share_intervals_pp")
        if isinstance(existing, dict) and existing:
            counts["already_present"] += 1
            proposals.append({"question_id": question.id, "title": question.title, "status": "already_present", "source": None})
            continue
        try:
            evidence_count = len(ledger.list_evidence(question.id))
        except Exception:
            evidence_count = len(getattr(snap, "evidence_refs", None) or [])
        intervals, prov = compute_candidate_share_intervals(
            payload, components=snap.ensemble_components,
            evidence_count=evidence_count, bounds=getattr(osp, "bounds", None),
        )
        if intervals is None:
            counts["none"] += 1
            proposals.append({"question_id": question.id, "title": question.title, "status": "none", "source": None})
            continue
        source = (prov or {}).get("source", "default")
        counts[source] = counts.get(source, 0) + 1
        proposals.append({
            "question_id": question.id, "title": question.title, "snapshot_id": snap.forecast_id,
            "status": "derivable", "source": source, "provenance": prov,
            "intervals": intervals,
        })
    # "derivable" = a real spread (panel or model); "default-width" = evidence-tied.
    derivable = counts["panel"] + counts["model"]
    return {
        "scanned": scanned,
        "derivable": derivable,
        "default_width": counts["default"],
        "none": counts["none"],
        "already_present": counts["already_present"],
        "by_source": counts,
        "proposals": proposals,
    }


def _cmd_reference_class_relink(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    apply = bool(getattr(args, "apply", False))
    result = ledger.relink_orphaned_anchors(apply=apply)
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    mode = "APPLIED" if apply else "DRY-RUN (pass --apply to re-link)"
    print(f"orphaned-anchor re-link {mode}")
    print(
        f"  {result['scanned_with_reference_class']} question(s) carry a reference class; "
        f"{result['already_linked']} already cite one on the current snapshot"
    )
    verb = "re-linked" if apply else "would re-link"
    print(
        f"  {verb} {result['relinkable']} orphaned snapshot(s) to their existing class(es); "
        f"{result['ambiguous']} ambiguous (>1 distinct outside view) SKIPPED for a human"
    )
    if apply:
        print(f"  applied to {result.get('applied', 0)} snapshot(s)")
    for p in result["proposals"]:
        print(f"    [relink ] {p['question_id']}  {(p['title'] or '')[:52]}")
    for p in result["ambiguous_detail"]:
        names = "; ".join(dict.fromkeys(str(n) for n in (p.get('active_rc_names') or [])))
        print(f"    [SKIP   ] {p['question_id']}  {(p['title'] or '')[:40]}  → {names[:60]}")


def _cmd_intervals_backfill(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    apply = bool(getattr(args, "apply", False))
    result = _backfill_intervals_scan(ledger)
    if apply:
        from forecasting.ledger import allow_ledger_writes

        applied = 0
        with allow_ledger_writes(reason="forecast intervals backfill --apply"):
            for p in result["proposals"]:
                if p.get("status") != "derivable":
                    continue
                ledger.annotate_snapshot(p["snapshot_id"], {
                    "candidate_share_intervals_pp": p["intervals"],
                    "candidate_share_intervals_provenance": p["provenance"],
                })
                applied += 1
        result["applied"] = applied
    if getattr(args, "json", False):
        # Drop the bulky per-candidate interval maps from the default text-less JSON
        # unless the caller wants them; keep the provenance + counts.
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    mode = "APPLIED" if apply else "DRY-RUN (pass --apply to stamp)"
    print(f"vote-share interval backfill {mode}")
    print(
        f"  scanned {result['scanned']} live vote-share board(s); "
        f"{result['already_present']} already carry intervals"
    )
    verb = "stamped" if apply else "would stamp"
    print(
        f"  {verb} {result['derivable']} from panel/model spread "
        f"(panel={result['by_source']['panel']}, model={result['by_source']['model']}); "
        f"{result['default_width']} from evidence-tied default width; "
        f"{result['none']} not derivable"
    )
    if apply:
        print(f"  applied to {result.get('applied', 0)} snapshot(s)")
    for p in result["proposals"]:
        if p.get("status") == "derivable":
            print(f"    [{p['source']:<7}] {p['question_id']}  {(p['title'] or '')[:52]}")


def _cmd_evidence_map(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    result = ledger.evidence_map(_resolve_question_id(ledger, args.question))
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    if not result["cruxes"]:
        print("No crux variables registered. Add them with `forecast crux add <question> --variable ...`.")
        return
    print("Crux evidence status:")
    for crux in result["cruxes"]:
        mark = "OK " if crux["status"] == "current" else "!! "
        src = "" if crux["has_matching_source"] else "  · NO matching source watched"
        print(f"  [{crux['materiality'].upper():<6}] {mark}{crux['status']:<13} {crux['crux_variable']}{src}")
    if result["gap_count"]:
        print(f"\n{result['gap_count']} high-materiality crux gap(s) — the decisive evidence is missing/stale.")


def _cmd_watch_add(args: argparse.Namespace) -> None:
    scope_type, scope_ref = _watch_scope(args, required=True)
    row = _ledger(args).add_watched_source(
        scope_type=scope_type,
        scope_ref=scope_ref,
        source=args.source,
        source_type=args.source_type,
        role=getattr(args, "role", None),
        metadata=_watch_metadata_from_args(args),
    )
    print(f"watched source {row['id']}")
    print(f"scope: {_format_watch_scope(row)}")
    print(f"source_type: {row['source_type']}")
    if row.get("role"):
        print(f"role: {row['role']}")
    print(f"status: {row['status']}")
    filters = (row.get("metadata") or {}).get("relevance_filters") or {}
    if filters:
        print(f"filters: keywords={', '.join(filters.get('keywords') or [])}")


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
    print("ID             Scope                  Type    Role              Status    Source")
    for row in rows:
        print(
            f"{row['id']:<14} {_format_watch_scope(row):<22} "
            f"{row['source_type']:<7} {(row.get('role') or '-'):<17} {row['status']:<9} {row['source']}"
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
        if alert.recommended_action:
            print(f"  action: {alert.recommended_action}")


def _cmd_autopilot_enable(args: argparse.Namespace) -> None:
    sources = _autopilot_sources(args)
    required_sources = _autopilot_required_sources(args)
    materiality_policy = _autopilot_materiality_policy(args.materiality_threshold)
    guardrail_policy = _autopilot_guardrail_policy(args)
    notification_policy = {
        "destination": args.notify,
        "quiet_if_unchanged": bool(args.quiet_if_unchanged),
    }
    result = _ledger(args).enable_autopilot(
        question_id=args.id,
        sources=sources,
        cadence=args.cadence,
        mode=args.mode,
        materiality_policy=materiality_policy,
        guardrail_policy=guardrail_policy,
        notification_policy=notification_policy,
        required_sources=required_sources,
        next_run_at=args.next_run_at,
        created_by=args.created_by,
        allow_missing_resolution_source=args.allow_missing_resolution_source,
    )
    policy = result["policy"]
    print(f"Autopilot enabled for {args.id}")
    print(f"Policy: {policy['id']}")
    print(f"Sources: {len(result['watched_sources'])}")
    if required_sources:
        print(f"Required sources: {len(required_sources)}")
    print(f"Cadence: {policy['cadence']}")
    print(f"Mode: {policy['mode'].replace('_', '-')}")
    print(f"Next run: {result['scheduled_review']['next_run_at']}")
    warnings = result["readiness"].get("warnings") or []
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")


def _cmd_autopilot_disable(args: argparse.Namespace) -> None:
    policy = _ledger(args).disable_autopilot(args.id)
    print(f"autopilot disabled for {args.id}")
    print(f"policy: {policy['id']}")


def _cmd_autopilot_status(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    policies = ledger.list_autopilot_policies(question_id=args.id, enabled_only=False)
    if not policies:
        print("No autopilot policy found.")
        return
    watches = ledger.list_watched_sources(scope_type="question", scope_ref=args.id, status=None)
    proposals = ledger.list_forecast_update_proposals(question_id=args.id, status=None, limit=20)
    runs = ledger.list_autopilot_runs(question_id=args.id, limit=5)
    for policy in policies:
        print(
            f"{policy['id']} enabled={policy['enabled']} mode={policy['mode'].replace('_', '-')} "
            f"cadence={policy['cadence']} schedule={policy['scheduled_review_id']}"
        )
    print(f"sources: {len(watches)}")
    print(f"required_sources: {len([row for row in watches if row.get('metadata', {}).get('required')])}")
    print(f"pending_proposals: {len([row for row in proposals if row['status'] == 'pending'])}")
    if runs:
        latest = runs[0]
        print(
            f"latest_run: {latest['id']} status={latest['status']} "
            f"changed={latest['sources_changed']} material={latest['material_changes']}"
        )


def _resolve_question_id(ledger: "ForecastLedger", ref: str) -> str:
    """Resolve a question id OR a free-text name to an id, so the user never has
    to remember a UUID. Exits with a shortlist on ambiguity / no match."""
    resolution = resolve_question_ref(ledger, ref)
    if resolution.question is not None:
        return resolution.question.id
    if resolution.candidates:
        print(f"forecast: '{ref}' matched several forecasts — narrow it or pass the id:", file=sys.stderr)
        for match in resolution.candidates[:5]:
            print(f"  {match.question.id}  {match.question.title}", file=sys.stderr)
        raise SystemExit(2)
    print(
        f"forecast: no forecast matches '{ref}'. Try `forecast list` or `forecast search <words>`.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _cmd_refresh(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    args.id = _resolve_question_id(ledger, args.id)
    if args.agent:
        # Delegate to the full LLM update stage (forecast agent --stage update).
        # The agent commits through the forecasting tool, whose hook writes the brief.
        # This is the AUTONOMOUS re-forecast path: it commits a MATERIAL move rather
        # than stopping at a preview (the forecast-update commit is separate from the
        # decision-card ACTION threshold — see protocol._COMMIT_MATERIAL_POLICY).
        args.stage = "update"
        args.commit_policy = "commit_material"
        _cmd_agent(args)
        return
    from tools.forecasting_tool import fetch_watched_source_payloads

    concurrency = args.concurrency
    result = ledger.refresh_forecast(
        args.id,
        fetcher=lambda specs: fetch_watched_source_payloads(specs, concurrency=concurrency),
        now=args.now,
        re_estimate="carry_forward" if args.carry_forward else "deterministic",
        extremize=args.extremize,
        correlation=args.correlation,
        dry_run=args.dry_run,
        commit=args.commit,
        trigger_reason="manual_refresh",
    )
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return
    status = result["status"]
    print(f"status: {status}")
    if result.get("fetch_failures"):
        for failure in result["fetch_failures"]:
            print(f"  fetch_failed: {failure['source']} ({failure['error']})")
    if status in {"no_change", "no_watched_sources"}:
        print(result.get("message", ""))
        return
    changed = result.get("changed_readings") or []
    new_evidence = result.get("new_evidence_ids") or []
    evidence_note = f", +{len(new_evidence)} evidence" if new_evidence else ""
    print(f"refreshed {len(changed)} reading(s){evidence_note}")
    prior = result.get("prior_probability")
    proposed = result.get("proposed_probability")
    if isinstance(prior, (int, float)) and isinstance(proposed, (int, float)):
        print(f"probability: {float(prior):.4f} -> {float(proposed):.4f} (delta {float(proposed) - float(prior):+.4f})")
    for reason in result.get("reasons_up") or []:
        print(f"  up:   {reason}")
    for reason in result.get("reasons_down") or []:
        print(f"  down: {reason}")
    if result.get("unmatched_sources"):
        print(f"  unmatched (fetched but not wired to a component): {', '.join(result['unmatched_sources'])}")
    if result.get("triggers_fired"):
        print(f"  triggers_fired: {', '.join(result['triggers_fired'])}")
    if result.get("needs_agent"):
        print("  note: raw-data change carried forward — re-run with --agent for a re-reasoned estimate.")
    committed = result.get("forecast_id")
    if committed:
        print(f"committed snapshot {committed}")
        # Standard step of the refresh process: write an analyst brief for the
        # snapshot the deterministic re-pool just committed. Best-effort.
        try:
            _write_analyst_brief(ledger, args.id, ledger.get_snapshot(committed))
        except Exception:
            pass
    else:
        print("(preview only — not committed)")


def _cmd_freshen(args: argparse.Namespace) -> None:
    """One verb: put a forecast (or all) on a refresh cadence AND ensure the nightly
    self-check cron. Answers the lazy prompter's implicit ask — "keep this current"."""
    ledger = _ledger(args)
    cadence = (args.cadence or "daily").strip()
    if args.all:
        targets = [q.id for q in ledger.list_questions(status="active")]
    elif args.id:
        targets = [_resolve_question_id(ledger, args.id)]
    else:
        print("freshen: pass a question id or --all", file=sys.stderr)
        raise SystemExit(2)

    updated: list[str] = []
    errors: list[str] = []
    for qid in targets:
        try:
            ledger.update_question_config(qid, review_cadence=cadence)
            updated.append(qid)
        except Exception as exc:  # a bad cadence / missing question must not abort the sweep
            errors.append(f"{qid}: {exc}")

    # Ensure the nightly self-check cron (force past the auto_install config gate —
    # this is explicit operator intent). Idempotent: silent when already present.
    from forecasting.scheduler import ensure_default_routines

    routines = ensure_default_routines(db_path=getattr(args, "db", None), force=True)
    cron_state = "installed" if routines.get("created") else "present"

    if getattr(args, "json", False):
        print(json.dumps(
            {"updated": updated, "errors": errors, "cadence": cadence,
             "cron": cron_state, "routines": routines},
            indent=2, default=str,
        ))
        return
    if not updated and not errors:
        print("no active questions to freshen")
    for qid in updated:
        print(f"{qid}: refreshes {cadence}")
    for err in errors:
        print(f"  skipped {err}", file=sys.stderr)
    print(f"nightly self-check cron {cron_state}")


def _cmd_autopilot_run(args: argparse.Namespace) -> None:
    result = _ledger(args).run_autopilot(
        args.id,
        now=args.now,
        trigger_reason=args.trigger_reason,
        proposed_probability_or_distribution=args.proposed_probability,
        rationale=args.rationale,
    )
    run = result["run"]
    print(f"autopilot run {run['id']}")
    print(f"status: {run['status']}")
    print(f"checked: {run['sources_checked']}")
    print(f"changed: {run['sources_changed']}")
    print(f"material: {run['material_changes']}")
    required_failures = run.get("diagnostics", {}).get("required_source_failures") or []
    if required_failures:
        print(f"required_source_failures: {len(required_failures)}")
    proposal = result.get("proposal")
    if proposal:
        print(f"proposal: {proposal['id']} status={proposal['status']}")
        prior = proposal.get("prior_forecast_id") or ""
        print(f"prior_forecast: {prior}")
        print(f"proposed: {proposal['proposed_probability_or_distribution']}")
        print(f"approve: forecast autopilot approve {proposal['id']}")
    snapshot = result.get("forecast_snapshot")
    if snapshot:
        print(f"forecast_snapshot: {snapshot.forecast_id}")
    if not proposal and run["material_changes"] == 0:
        print("No material source changes detected.")


def _cmd_autopilot_history(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_autopilot_runs(question_id=args.id, limit=args.limit)
    if not rows:
        print("No autopilot runs found.")
        return
    print("Run ID         Started at           Status    Checked  Changed  Material  Proposal")
    for row in rows:
        print(
            f"{row['id']:<14} {row['started_at']:<20} {row['status']:<9} "
            f"{row['sources_checked']:<8} {row['sources_changed']:<8} "
            f"{row['material_changes']:<9} {row['proposal_id'] or ''}"
        )


def _cmd_autopilot_proposals(args: argparse.Namespace) -> None:
    rows = _ledger(args).list_forecast_update_proposals(
        question_id=args.id,
        status=None if args.all else "pending",
        limit=100,
    )
    if not rows:
        print("No forecast update proposals found.")
        return
    print("Proposal ID    Question       Status          Created at           Proposed")
    for row in rows:
        print(
            f"{row['id']:<14} {row['question_id']:<14} {row['status']:<15} "
            f"{row['created_at']:<20} {row['proposed_probability_or_distribution']}"
        )


def _cmd_autopilot_approve(args: argparse.Namespace) -> None:
    snapshot = _ledger(args).approve_forecast_update_proposal(
        args.proposal_id,
        reviewed_by=args.reviewed_by,
    )
    print(f"approved proposal {args.proposal_id}")
    print(f"created forecast snapshot {snapshot.forecast_id}")


def _cmd_autopilot_reject(args: argparse.Namespace) -> None:
    proposal = _ledger(args).reject_forecast_update_proposal(
        args.proposal_id,
        reviewed_by=args.reviewed_by,
    )
    print(f"rejected proposal {proposal['id']}")
    print(f"status: {proposal['status']}")


def _cmd_alerts(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    if getattr(args, "collapse", False):
        result = ledger.collapse_duplicate_alerts(dry_run=getattr(args, "dry_run", False))
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
            return
        verb = "would collapse" if result["dry_run"] else "collapsed"
        if result["groups_collapsed"] == 0:
            print("No duplicate open-alert groups to collapse.")
        else:
            print(
                f"{verb.capitalize()} {result['groups_collapsed']} duplicate group(s); "
                f"folded {result['rows_folded']} redundant row(s) into the oldest."
            )
        return
    if getattr(args, "escalate", False):
        result = ledger.escalate_aged_alerts(dry_run=getattr(args, "dry_run", False))
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
            return
        verb = "would escalate" if result["dry_run"] else "escalated"
        if result["escalated_count"] == 0:
            print("No aged alerts to escalate.")
        else:
            print(f"{verb.capitalize()} {result['escalated_count']} aged alert(s) by severity:")
            for entry in result["escalated"]:
                print(f"  {entry['id']}  {entry['reason']}  {entry['from']} -> {entry['to']} ({entry['age_days']}d)")
        return
    if getattr(args, "reconcile", False):
        result = ledger.reconcile_alerts(dry_run=getattr(args, "dry_run", False))
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
            return
        verb = "would acknowledge" if result["dry_run"] else "acknowledged"
        if result["reconciled_count"] == 0:
            print("No alerts to reconcile (none have both fresh evidence + a forecast update since they fired).")
        else:
            print(f"Reconciled {result['reconciled_count']} alert(s) — {verb} (source-change consumed):")
            for entry in result["reconciled"]:
                print(f"  {entry['id']}  {entry['reason']}")
        if result["still_open"]:
            print(f"\n{len(result['still_open'])} alert(s) still open:")
            for entry in result["still_open"]:
                print(f"  {entry['id']}  {entry['reason']} — {entry['open_because']}")
        return
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


def _cmd_triggers(args: argparse.Namespace) -> None:
    args.id = _resolve_question_id(_ledger(args), args.id)
    observations: dict[str, float] = {}
    if args.observations_json:
        parsed = _json_arg(args.observations_json, "observations-json")
        if not isinstance(parsed, dict):
            raise SystemExit("--observations-json must be a JSON object of source_ref->value")
        for key, value in parsed.items():
            try:
                observations[str(key)] = float(value)
            except (TypeError, ValueError):
                raise SystemExit(f"--observations-json value for {key!r} must be numeric")
    for item in args.observations:
        if "=" not in item:
            raise SystemExit(f"--observation must be SOURCE_REF=VALUE, got {item!r}")
        key, _, raw = item.partition("=")
        try:
            observations[key.strip()] = float(raw.strip())
        except ValueError:
            raise SystemExit(f"--observation value for {key!r} must be numeric")
    alerts = _ledger(args).check_update_triggers(
        question_id=args.id,
        observations=observations or None,
        now=args.now,
    )
    if args.json:
        print(json.dumps([alert.__dict__ for alert in alerts], indent=2))
        return
    if not alerts:
        print("No update triggers fired.")
        return
    print(f"fired {len(alerts)} trigger(s)")
    for alert in alerts:
        print(f"{alert.id}: {alert.reason}")
        print(f"  {alert.recommended_action}")


def _cmd_backtest(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    if args.agent_response_jsonl and args.probability_source != "agent-protocol":
        raise SystemExit("--agent-response-jsonl requires --probability-source agent-protocol")
    if args.agent_output_jsonl and args.probability_source != "agent-protocol":
        raise SystemExit("--agent-output-jsonl requires --probability-source agent-protocol")
    if args.agent_prompt_jsonl and args.probability_source != "agent-protocol":
        raise SystemExit("--agent-prompt-jsonl requires --probability-source agent-protocol")
    if getattr(args, "closed_book", False) and args.probability_source != "agent-protocol":
        raise SystemExit("--closed-book requires --probability-source agent-protocol")
    if getattr(args, "market_hidden", False) and args.probability_source != "agent-protocol":
        raise SystemExit("--market-hidden requires --probability-source agent-protocol")
    if args.agent_prompt_jsonl and not args.prepare_agent_prompts:
        raise SystemExit("--agent-prompt-jsonl requires --prepare-agent-prompts")
    if args.prepare_agent_prompts and args.probability_source != "agent-protocol":
        raise SystemExit("--prepare-agent-prompts requires --probability-source agent-protocol")
    if args.prepare_agent_prompts and not args.agent_prompt_jsonl:
        raise SystemExit("--prepare-agent-prompts requires --agent-prompt-jsonl")
    if args.prepare_agent_prompts and (args.agent_response_jsonl or args.agent_output_jsonl):
        raise SystemExit("--prepare-agent-prompts cannot be combined with agent response or output JSONL")
    if args.prepare_agent_prompts and (args.benchmarks or args.list or args.show):
        raise SystemExit("--prepare-agent-prompts requires a dataset or --all-benchmarks")
    if args.prepare_agent_prompts and args.dataset and args.all_benchmarks:
        raise SystemExit("--prepare-agent-prompts cannot combine a dataset with --all-benchmarks")
    if args.prepare_agent_prompts and not (args.dataset or args.all_benchmarks):
        raise SystemExit("--prepare-agent-prompts requires a dataset or --all-benchmarks")
    if args.benchmarks:
        rows = list_builtin_benchmarks()
        imported = ledger.list_benchmark_datasets()
        if not rows and not imported:
            print("No benchmarks found.")
            return
        print("Name                              Cases  Provenance        Source Families  Description")
        for row in rows:
            evidence = row.get("benchmark_evidence") or {}
            families = ",".join(evidence.get("source_families") or []) or "-"
            provenance = str(evidence.get("provenance") or "-")
            print(
                f"builtin:{row['name']:<25} "
                f"{row['case_count']:<6} "
                f"{provenance:<16} "
                f"{families:<16} "
                f"{row['description']}"
            )
        for row in imported:
            description = row.get("description") or f"Imported from {row['source']}"
            evidence = build_benchmark_evidence_profile(f"imported:{row['id']}", row.get("cases") or [])
            families = ",".join(evidence.get("source_families") or []) or "-"
            provenance = str(evidence.get("provenance") or "-")
            print(
                f"imported:{row['id']:<24} "
                f"{row['case_count']:<6} "
                f"{provenance:<16} "
                f"{families:<16} "
                f"{description}"
            )
        return
    if args.all_benchmarks:
        if args.dataset:
            raise SystemExit("forecast backtest --all-benchmarks cannot be combined with a dataset")
        rows = list_builtin_benchmarks()
        if not rows:
            print("No built-in benchmarks found.")
            return
        if args.prepare_agent_prompts:
            datasets: list[tuple[str, list[dict[str, Any]]]] = []
            for row in rows:
                dataset = f"builtin:{row['name']}"
                datasets.append((dataset, _load_backtest_cases(dataset, ledger=ledger)))
            path, total_cases = _write_agent_protocol_prompt_jsonl_for_datasets(
                args.agent_prompt_jsonl,
                datasets,
            )
            print(f"agent_protocol_prompts: {path}")
            print(f"benchmark_suite: builtin ({len(rows)} datasets)")
            print(f"cases: {total_cases}")
            for dataset, cases in datasets:
                print(f"  {dataset}: {len(cases)}")
            print("next: run the prompt packets through an agent, then replay responses with:")
            print(
                "  forecast backtest --all-benchmarks --probability-source agent-protocol "
                "--agent-response-jsonl <responses.jsonl>"
            )
            return
        agent_runner = (
            _backtest_agent_protocol_runner(args)
            if args.probability_source == "agent-protocol"
            else None
        )
        recorded_agent_model = _resolved_recorded_agent_model(args, agent_runner)
        print(f"benchmark_suite: builtin ({len(rows)} datasets)")
        print(f"probability_source: {args.probability_source}")
        suite_runs = 0
        suite_cases = 0
        suite_scored = 0
        for row in rows:
            dataset = f"builtin:{row['name']}"
            cases = _apply_backtest_probability_source(
                _load_backtest_cases(dataset, ledger=ledger),
                args.probability_source,
                agent_runner=agent_runner,
                agent_model=recorded_agent_model,
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
            suite_runs += 1
            suite_cases += int(summary.get("case_count", 0) or 0)
            suite_scored += int(summary.get("scored_cases", 0) or 0)
            print(
                f"{dataset} backtest_run={run['id']} "
                f"cases={summary.get('case_count', 0)} "
                f"scored={summary.get('scored_cases', 0)} "
                f"agent_mean_brier={_format_metric(summary.get('agent_mean_brier'))} "
                f"leakage={run['leakage_checks_passed']}"
            )
        print(f"suite_summary: runs={suite_runs} cases={suite_cases} scored={suite_scored}")
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
                    f"p={_format_pvalue(baseline.get('paired_p_value'))} "
                    f"floor={_format_metric(baseline.get('paired_brier_coin_flip_floor'))} "
                    f"wins={baseline.get('paired_agent_wins', 0)}/"
                    f"{baseline.get('paired_baseline_wins', 0)}/"
                    f"{baseline.get('paired_ties', 0)}"
                )
            win_rate = report.get("win_rate_vs_best") or {}
            if win_rate.get("win_rate_vs_best") is not None:
                print(
                    "  win_rate_vs_best="
                    f"{_format_win_rate(win_rate.get('win_rate_vs_best'), win_rate.get('win_rate_vs_best_n'))}"
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
    if args.prepare_agent_prompts:
        if not args.dataset:
            raise SystemExit("forecast backtest --prepare-agent-prompts requires a dataset")
        cases = _load_backtest_cases(
            args.dataset,
            ledger=ledger,
            hide_market_baseline=getattr(args, "market_hidden", False),
        )
        path = _write_agent_protocol_prompt_jsonl(args.agent_prompt_jsonl, cases, dataset=args.dataset)
        print(f"agent_protocol_prompts: {path}")
        print(f"cases: {len(cases)}")
        print("next: run the prompt packets through an agent, then replay responses with:")
        print(
            "  forecast backtest "
            f"{args.dataset} --probability-source agent-protocol "
            "--agent-response-jsonl <responses.jsonl>"
        )
        return
    if not args.dataset:
        raise SystemExit("forecast backtest requires a dataset, --list, or --show")
    agent_runner = (
        _backtest_agent_protocol_runner(args)
        if args.probability_source == "agent-protocol"
        else None
    )
    cases = _apply_backtest_probability_source(
        _load_backtest_cases(
            args.dataset,
            ledger=ledger,
            hide_market_baseline=getattr(args, "market_hidden", False),
        ),
        args.probability_source,
        agent_runner=agent_runner,
        agent_model=_resolved_recorded_agent_model(args, agent_runner),
        agent_provider=args.agent_provider,
    )
    market_hidden = bool(getattr(args, "market_hidden", False))
    run = ledger.run_backtest_dataset(
        dataset=args.dataset,
        cases=cases,
        default_forecast_time_cutoff=args.as_of,
        evidence_cutoff_policy=args.evidence_cutoff_policy,
        allow_calibration_memory=args.allow_calibration_memory,
        arm="market_hidden" if market_hidden else None,
    )
    print(f"backtest_run: {run['id']}")
    print(f"cases: {run['result_summary'].get('case_count', 0)}")
    print(f"scored_cases: {run['result_summary'].get('scored_cases', 0)}")
    print(f"leakage_checks_passed: {run['leakage_checks_passed']}")
    if market_hidden:
        _print_market_hidden_report(ledger, run["id"])


def _print_market_hidden_report(ledger: ForecastLedger, run_id: str) -> None:
    """Market-hidden arm scoring report: agent vs the WITHHELD market baseline.

    Reuses the run's :meth:`ForecastLedger.backtest_performance_report` for the
    agent Brier + market baseline Brier + P0.2 paired-bootstrap edge CI / p-value /
    win-rate (same cases), and :func:`market_ensemble.market_hidden_pool_report` for
    the equal-weight log-odds POOL Brier + the P1.3 fitted-simplex complementarity
    (does a market+agent blend beat both?). Read-only."""
    from forecasting.market_ensemble import market_hidden_pool_report

    perf = ledger.backtest_performance_report(run_id)
    pool = market_hidden_pool_report(ledger, run_id)
    agent_brier = (perf.get("agent") or {}).get("mean_brier")
    market_row = next(
        (b for b in perf.get("baselines") or [] if b.get("baseline_type") == "market"),
        None,
    )

    print("market-hidden arm (market price scored as baseline, WITHHELD from the agent):")
    print(f"  paired cases: {pool['n']}" + (f" (skipped {pool['skipped']})" if pool["skipped"] else ""))
    print(f"  agent Brier   = {_format_metric(agent_brier)}")
    if market_row is not None:
        print(f"  market Brier  = {_format_metric(market_row.get('mean_brier'))}")
        print(
            "  agent edge vs market (market_brier - agent_brier) = "
            f"{_format_delta(market_row.get('paired_agent_edge_mean_brier'))} "
            f"ci95={_format_ci95(market_row.get('paired_agent_edge_ci95_low'), market_row.get('paired_agent_edge_ci95_high'))} "
            f"p={_format_pvalue(market_row.get('paired_p_value'))}"
        )
        print(
            "  win-rate vs market = "
            f"{_format_win_rate(pool.get('win_rate_vs_market'), pool['n'])} "
            f"(wins/losses/ties {market_row.get('paired_agent_wins', 0)}/"
            f"{market_row.get('paired_baseline_wins', 0)}/{market_row.get('paired_ties', 0)})"
        )
    else:
        print("  market Brier  = - (no scored market baseline on this run)")
    print(
        "  pooled (agent+market log-odds) Brier = "
        f"{_format_metric(pool.get('pooled_brier'))}  "
        f"beats_both={bool(pool.get('pool_beats_both'))}"
    )
    fitted = pool.get("fitted") or {}
    weights = fitted.get("weights")
    if weights:
        wtxt = ", ".join(f"{name}={weights[name]:.3f}" for name in sorted(weights))
        print(f"  fitted simplex complementarity: weights[{wtxt}]")
    print(
        "    loo_ensemble_brier (honest) = "
        f"{_format_metric(fitted.get('loo_ensemble_brier'))}  "
        f"blend beats BOTH (LOO) = {bool(fitted.get('beats_both'))}"
    )
    for note in pool.get("notes") or []:
        print(f"  note: {note}")


def _cmd_performance(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    rows, summaries = _recent_backtest_summaries(
        ledger,
        last=args.last,
        dataset=getattr(args, "dataset", None),
    )
    evidence_status = build_forecasting_evidence_status(ledger, summaries)
    live_report = ledger.live_performance_report() if args.live else None

    if args.json:
        print(
            json.dumps(
                {
                    "last": max(args.last, 0),
                    "dataset_filter": args.dataset,
                    "live": live_report,
                    "run_count": len(summaries),
                    "evidence_status": evidence_status,
                    "runs": summaries,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if live_report is not None:
        _print_live_performance_report(live_report)

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
                f"{baseline.get('paired_ties', 0)} "
                f"p={_format_pvalue(baseline.get('paired_p_value'))} "
                f"floor={_format_metric(baseline.get('paired_brier_coin_flip_floor'))}"
            )
        if best is not None and best.get("win_rate_vs_best") is not None:
            print(
                "  win_rate_vs_best="
                f"{_format_win_rate(best.get('win_rate_vs_best'), best.get('win_rate_vs_best_n'))}"
            )
        if report["agent_by_domain"]:
            print(f"  domains {_format_score_breakdown(report['agent_by_domain'])}")
        if report["agent_by_horizon"]:
            print(f"  horizons {_format_score_breakdown(report['agent_by_horizon'])}")
        claim = report.get("claim_status") or {}
        if claim:
            print(f"  claim {claim.get('verdict')}: {claim.get('message')}")
    _print_evidence_status(evidence_status)


def _print_live_performance_report(report: dict[str, Any]) -> None:
    agent = report["agent"]
    print(
        "Live Performance "
        f"scores={report['score_count']} "
        f"agent_brier={_format_metric(agent.get('mean_brier'))} "
        f"baselines={len(report['baselines'])}"
    )
    for baseline in report["baselines"]:
        name = f"{baseline['baseline_type']}:{baseline['source']}"
        print(
            f"  live baseline {name} brier={_format_metric(baseline['mean_brier'])} "
            f"paired={baseline['paired_count']} "
            f"agent_edge={_format_delta(baseline['mean_brier_improvement_vs_baseline'])} "
            f"paired_brier_agent={_format_metric(baseline.get('paired_agent_mean_brier'))} "
            f"paired_brier_baseline={_format_metric(baseline.get('paired_baseline_mean_brier'))} "
            f"paired_edge={_format_delta(baseline.get('paired_agent_edge_mean_brier'))} "
            f"ci95={_format_ci95(baseline.get('paired_agent_edge_ci95_low'), baseline.get('paired_agent_edge_ci95_high'))} "
            f"wins={baseline.get('paired_agent_wins', 0)}/"
            f"{baseline.get('paired_baseline_wins', 0)}/"
            f"{baseline.get('paired_ties', 0)} "
            f"p={_format_pvalue(baseline.get('paired_p_value'))} "
            f"floor={_format_metric(baseline.get('paired_brier_coin_flip_floor'))}"
        )
    live_win_rate = report.get("win_rate_vs_best") or {}
    if live_win_rate.get("win_rate_vs_best") is not None:
        print(
            "  live win_rate_vs_best="
            f"{_format_win_rate(live_win_rate.get('win_rate_vs_best'), live_win_rate.get('win_rate_vs_best_n'))}"
        )
    if report["agent_by_domain"]:
        print(f"  live domains {_format_score_breakdown(report['agent_by_domain'])}")
    if report["agent_by_horizon"]:
        print(f"  live horizons {_format_score_breakdown(report['agent_by_horizon'])}")
    claim = report.get("claim_status") or {}
    if claim:
        print(f"  live claim {claim.get('verdict')}: {claim.get('message')}")


def _run_safe_benchmarks(ledger: ForecastLedger, probability_source: str) -> dict[str, Any]:
    """Run the OFFLINE builtin benchmark suite (no network / no paid LLM) via a
    deterministic generated probability source, persisting one backtest run per
    dataset so readiness evidence can advance unattended. Both external families
    (manifold + kalshi) are in the builtin set, so the external-families gap can
    close; the positive-edge gap is data-dependent (reported, not guaranteed)."""
    runs = cases = scored = 0
    results: list[dict[str, Any]] = []
    for row in list_builtin_benchmarks():
        dataset = f"builtin:{row['name']}"
        prepared = _apply_backtest_probability_source(
            _load_backtest_cases(dataset, ledger=ledger), probability_source,
        )
        run = ledger.run_backtest_dataset(dataset=dataset, cases=prepared)
        summary = run["result_summary"]
        runs += 1
        cases += int(summary.get("case_count", 0) or 0)
        scored += int(summary.get("scored_cases", 0) or 0)
        results.append({
            "dataset": dataset, "run_id": run["id"],
            "case_count": summary.get("case_count"), "scored_cases": summary.get("scored_cases"),
            "agent_mean_brier": summary.get("agent_mean_brier"), "leakage_checks_passed": run["leakage_checks_passed"],
        })
    return {"runs": runs, "cases": cases, "scored": scored, "results": results}


def _cmd_readiness(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    improve = getattr(args, "run_safe_benchmarks", False)
    # When improving, evaluate over ALL runs (ignore the --last truncation AND the
    # --dataset filter) so the freshly-run suite is visible and the closed/remaining
    # gap diff is honest — otherwise the 5 new runs can evict older ones from a narrow
    # --last window (a closed gap would look reopened) or a --dataset filter would hide
    # the suite entirely and report zero closed gaps.
    eval_last = 1_000_000 if improve else args.last
    eval_dataset = None if improve else getattr(args, "dataset", None)

    def _status() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        rows, summaries = _recent_backtest_summaries(ledger, last=eval_last, dataset=eval_dataset)
        status = build_forecasting_evidence_status(
            ledger, summaries,
            min_live_scores=max(args.min_live_scores, 0),
            min_agent_protocol_cases=max(args.min_agent_protocol_cases, 0),
            min_external_source_families=max(args.min_external_source_families, 0),
        )
        return rows, summaries, status

    improve_report: dict[str, Any] | None = None
    if improve:
        source = getattr(args, "probability_source", "forecast-engine")
        if source not in ("forecast-engine", "baseline-ensemble"):
            raise SystemExit(
                "--run-safe-benchmarks runs OFFLINE only (forecast-engine / baseline-ensemble); "
                "agent-protocol needs an LLM runner — use `forecast backtest --all-benchmarks "
                "--probability-source agent-protocol`."
            )
        planned = [f"builtin:{row['name']}" for row in list_builtin_benchmarks()]
        if getattr(args, "dry_run", False):
            if args.json:
                print(json.dumps({"dry_run": True, "probability_source": source, "would_run": planned}, indent=2, sort_keys=True))
            else:
                print(f"dry-run: would run {len(planned)} safe benchmark(s) via {source}:")
                for name in planned:
                    print(f"  - {name}")
            return
        pre_gaps = set(_status()[2].get("gaps") or [])
        ran = _run_safe_benchmarks(ledger, source)
        improve_report = {"probability_source": source, "pre_gaps": sorted(pre_gaps), **ran}

    rows, summaries, evidence_status = _status()
    evidence_gaps = bool(evidence_status.get("gaps"))
    if improve_report is not None:
        post_gaps = set(evidence_status.get("gaps") or [])
        improve_report["closed_gaps"] = sorted(set(improve_report["pre_gaps"]) - post_gaps)
        improve_report["remaining_gaps"] = sorted(post_gaps)

    if args.json:
        print(
            json.dumps(
                {
                    "last": max(args.last, 0),
                    "dataset_filter": args.dataset,
                    "run_count": len(summaries),
                    "inspected_backtest_run_ids": [row["id"] for row in rows],
                    "evidence_status": evidence_status,
                    "benchmarks_improve": improve_report,
                },
                indent=2,
                sort_keys=True,
            )
        )
        if args.require_evidence and evidence_gaps:
            raise SystemExit(1)
        return

    if improve_report is not None:
        print(
            f"ran {improve_report['runs']} safe benchmark(s) via {improve_report['probability_source']}: "
            f"cases={improve_report['cases']} scored={improve_report['scored']}"
        )
        for r in improve_report["results"]:
            print(f"  {r['dataset']} run={r['run_id']} cases={r['case_count']} agent_mean_brier={_format_metric(r['agent_mean_brier'])} leakage={r['leakage_checks_passed']}")
        closed = improve_report["closed_gaps"]
        print(f"closed_gaps: {', '.join(closed) if closed else 'none'}")

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
        f"datasets={backtests.get('distinct_dataset_count', 0)} "
        f"external_datasets={backtests.get('external_dataset_count', 0)} "
        f"external_source_families={backtests.get('external_source_family_count', 0)}"
    )
    for requirement in evidence_status.get("requirements") or []:
        passed = bool(requirement.get("passed"))
        if passed and not include_passed:
            continue
        print(
            f"  {'ok' if passed else 'gap'} {requirement.get('id')}: "
            f"{requirement.get('observed', 0)}/{requirement.get('required', 0)} "
            f"remaining={requirement.get('remaining', 0)}"
        )
    next_actions = list(evidence_status.get("next_actions") or [])
    if next_actions:
        print("next_actions:")
        for item in next_actions[:5]:
            print(f"  - {item.get('requirement_id')}: {item.get('action')}")
            commands = list(item.get("commands") or [])
            if commands:
                print(f"    command: {commands[0]}")


def _cmd_pilot_report(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    report = ledger.pilot_report(
        min_questions=args.min_questions,
        min_structured_source_questions=args.min_structured_source_questions,
        min_scores=args.min_scores,
        min_postmortems=args.min_postmortems,
        min_scheduled_reviews=args.min_scheduled_reviews,
        min_scheduled_review_runs=args.min_scheduled_review_runs,
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
        f"schedule_runs={summary.get('scheduled_review_run_count', 0)} "
        f"open_alerts={summary['open_alert_count']} "
        f"learned_error_reviews={summary.get('open_learned_error_review_alert_count', 0)}"
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
                # Batch cohort setup from a manifest: mechanically clean manifest
                # prose rather than block the whole cohort import on a stray em-dash.
                style_autofix=True,
                distribution_autofix=True,  # programmatic: auto-fix malformed bounds rather than block
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
                # A pilot cohort exists to RESOLVE + SCORE (calibration), so its
                # reviews auto-score + auto-postmortem — the loop closes itself and
                # the "0 live scored forecasts" gap fills without manual follow-up.
                auto_score=True,
                auto_postmortem=True,
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
        min_scheduled_review_runs=args.min_scheduled_review_runs,
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
        min_external_source_families=max(args.min_external_source_families, 0),
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
    scheduled_review_count = 0
    scheduled_review_run_count = 0
    non_structured_source_types = {"manual_note", "note"}

    for path in paths:
        packet = _load_pilot_export_packet(path)
        question_packets = _question_packets_from_export(packet, path)
        packet_schedules = packet.get("scheduled_reviews") if isinstance(packet.get("scheduled_reviews"), list) else None
        packet_schedule_runs = (
            packet.get("scheduled_review_runs")
            if isinstance(packet.get("scheduled_review_runs"), list)
            else None
        )
        packet_scheduled_review_count = len(packet_schedules or [])
        packet_scheduled_review_run_count = len(packet_schedule_runs or [])
        scheduled_review_count += packet_scheduled_review_count
        scheduled_review_run_count += packet_scheduled_review_run_count
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
            if packet_schedules is None:
                question_schedules = question_packet.get("scheduled_reviews") or []
                scheduled_review_count += len(question_schedules)
                packet_scheduled_review_count += len(question_schedules)
            if packet_schedule_runs is None:
                question_schedule_runs = question_packet.get("scheduled_review_runs") or []
                scheduled_review_run_count += len(question_schedule_runs)
                packet_scheduled_review_run_count += len(question_schedule_runs)
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
                "scheduled_review_count": packet_scheduled_review_count,
                "scheduled_review_run_count": packet_scheduled_review_run_count,
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
            "scheduled_review_count": scheduled_review_count,
            "scheduled_review_run_count": scheduled_review_run_count,
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


_BAYES_POOL_METHODS = {
    "log_odds_pool": "log_odds_pool",
    "log_odds": "log_odds_pool",
    "logit": "log_odds_pool",
    "logit_pool": "log_odds_pool",
    "geometric": "log_odds_pool",
    "geometric_pool": "log_odds_pool",
    "geometric_pool_odds": "log_odds_pool",
    "log_pool": "log_pool",
    "log_linear": "log_pool",
    "log_linear_pool": "log_pool",
}


def _pool_components_probability(args: argparse.Namespace, components: dict[str, Any]) -> float | None:
    """Combine ensemble components into a probability.

    Routes through the Bayesian toolkit (log-odds / log-linear pooling with
    optional extremization and correlation discounting) when the chosen method
    is a Bayesian pooling method; otherwise keeps the historic weighted-average
    behaviour so existing ``weighted_ensemble`` workflows are unchanged.
    """

    method = str(getattr(args, "method", None) or "").strip().lower()
    extremize = getattr(args, "extremize", None)
    correlation = getattr(args, "correlation", None)
    pooled_method = _BAYES_POOL_METHODS.get(method)
    if pooled_method is None and extremize is None and correlation is None:
        return weighted_binary_probability(components)

    rows = _component_rows(components)
    if not rows:
        return weighted_binary_probability(components)

    # Default to log-odds pooling when extremize/correlation requested without a method.
    pooled_method = pooled_method or "log_odds_pool"
    correlation_matrix: Any = None
    if correlation is not None:
        text = str(correlation).strip()
        if text.lower() in {"estimate", "auto"}:
            correlation_matrix = "estimate"
        elif text:
            try:
                correlation_matrix = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"--correlation must be 'estimate' or a JSON matrix: {exc}")

    from forecasting.bayes_toolkit import combine_forecasts, ensure_industry_backends

    ensure_industry_backends()
    result = combine_forecasts(
        rows,
        method=pooled_method,
        extremize=float(extremize) if extremize is not None else 1.0,
        correlation_matrix=correlation_matrix,
    )
    return result.probability


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
        probability = _pool_components_probability(args, components)
        if probability is not None:
            return probability
    if args.probability is None:
        raise SystemExit(
            "forecast update requires --probability, --numeric-value, --distribution-json, "
            "or weighted --component-json"
        )
    return args.probability


def _json_arg(raw: str, name: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--{name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"--{name} must be a JSON object")
    return parsed


def _cli_filter_terms(values: list[str] | None) -> list[str]:
    terms: list[str] = []
    for value in values or []:
        for chunk in str(value).split(","):
            term = chunk.strip()
            if term and term not in terms:
                terms.append(term)
    return terms


def _news_triage_metadata(args: argparse.Namespace) -> dict[str, Any]:
    keywords = _cli_filter_terms(getattr(args, "keywords", []))
    exclude_keywords = _cli_filter_terms(getattr(args, "exclude_keywords", []))
    affected_components = _cli_filter_terms(getattr(args, "affected_components", []))
    metadata: dict[str, Any] = {}
    if keywords or exclude_keywords:
        metadata["relevance_filters"] = {
            "keywords": keywords,
            "exclude_keywords": exclude_keywords,
        }
    impact: dict[str, Any] = {}
    if getattr(args, "direction", None):
        impact["direction"] = args.direction
    if affected_components:
        impact["affected_components"] = affected_components
    if getattr(args, "materiality", None):
        impact["materiality"] = args.materiality
    if impact:
        metadata["forecast_impact"] = impact
    if metadata:
        metadata["news_triage"] = {
            "state": "candidate_evidence",
            "no_silent_probability_mutation": True,
        }
    return metadata


def _watch_metadata_from_args(args: argparse.Namespace) -> dict[str, Any]:
    metadata = _json_arg(args.metadata_json, "metadata-json")
    if getattr(args, "source_name", None):
        metadata["source_name"] = args.source_name
    if getattr(args, "cadence", None):
        metadata["cadence"] = args.cadence
    keywords = _cli_filter_terms(getattr(args, "keywords", []))
    exclude_keywords = _cli_filter_terms(getattr(args, "exclude_keywords", []))
    affected_components = _cli_filter_terms(getattr(args, "affected_components", []))
    if keywords or exclude_keywords:
        metadata["relevance_filters"] = {
            "keywords": keywords,
            "exclude_keywords": exclude_keywords,
        }
    if keywords or exclude_keywords or getattr(args, "materiality", None) or getattr(args, "direction", None):
        metadata["news_triage"] = {
            "state": "candidate_evidence",
            "materiality": args.materiality or "medium",
            "direction": args.direction or "ambiguous",
            "affected_components": affected_components,
            "no_silent_probability_mutation": True,
        }
    return metadata


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
    return len(_new_evidence_items(evidence, current_snapshot))


def _new_evidence_items(evidence: list[Any], current_snapshot: Any) -> list[Any]:
    if current_snapshot is None:
        return []
    snapshot_dt = timestamp_to_datetime(current_snapshot.as_of)
    if snapshot_dt is None:
        return []
    new_items = []
    for item in evidence:
        available_dt = timestamp_to_datetime(item.available_at)
        if available_dt and available_dt > snapshot_dt:
            new_items.append(item)
    return new_items


def _research_change_summary(evidence: list[Any], current_snapshot: Any) -> str:
    if current_snapshot is None:
        return (
            "change_summary: no current forecast snapshot; "
            f"{len(evidence)} evidence item(s) are pre-update research context"
        )
    new_items = _new_evidence_items(evidence, current_snapshot)
    if not new_items:
        return f"change_summary: no evidence newer than current forecast as-of {current_snapshot.as_of}"
    stance_counts = Counter(str(getattr(item, "stance", "") or "unknown") for item in new_items)
    stance_summary = ", ".join(f"{stance}={count}" for stance, count in sorted(stance_counts.items()))
    latest = max(str(getattr(item, "available_at", "") or "-") for item in new_items)
    return (
        f"change_summary: {len(new_items)} evidence item(s) newer than current forecast "
        f"as-of {current_snapshot.as_of}; latest={latest}; stances={stance_summary}"
    )


def _review_next_action(question_id: str, reasons: list[str]) -> str:
    if any(reason.startswith("new_evidence:") for reason in reasons):
        return f"forecast research {question_id}; forecast update {question_id} --preview ..."
    if any(is_learned_error_review_reason(reason) for reason in reasons):
        return f"forecast show {question_id}; forecast update {question_id} --preview ..."
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


def _truncate(value: str, limit: int) -> str:
    if limit <= 0 or len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: max(limit - 3, 0)] + "..."


def _joined_arg(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return " ".join(str(item) for item in value).strip()
    return str(value).strip()


def _format_ci95(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "-"
    return f"[{low:+.3f},{high:+.3f}]"


def _format_pvalue(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def _format_win_rate(value: float | None, n: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}(n={n or 0})"


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


def _parse_rating(value: str) -> float:
    labels = {
        "low": 0.25,
        "medium": 0.50,
        "med": 0.50,
        "moderate": 0.50,
        "high": 0.75,
        "very-high": 0.90,
        "very_high": 0.90,
    }
    raw = str(value).strip().lower()
    if raw in labels:
        return labels[raw]
    try:
        score = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rating must be 0..1 or low/medium/high") from exc
    if not 0 <= score <= 1:
        raise argparse.ArgumentTypeError("rating must be between 0 and 1")
    return score


def _parse_stance(value: str) -> str:
    aliases = {
        "supports": "increases",
        "support": "increases",
        "positive": "increases",
        "increases": "increases",
        "opposes": "decreases",
        "oppose": "decreases",
        "negative": "decreases",
        "decreases": "decreases",
        "mixed": "mixed",
        "neutral": "context",
        "contextual": "context",
        "context": "context",
    }
    raw = str(value).strip().lower()
    if raw in aliases:
        return aliases[raw]
    raise argparse.ArgumentTypeError("stance must be increases/decreases/mixed/context or supports/opposes")


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


def _autopilot_sources(args: argparse.Namespace) -> list[str]:
    sources = _autopilot_source_values(args.source, args.sources)
    required_sources = _autopilot_required_sources(args)
    for source in required_sources:
        if source not in sources:
            sources.append(source)
    if not sources:
        raise SystemExit("autopilot enable requires --source, --sources, --required-source, or --required-sources")
    return sources


def _autopilot_required_sources(args: argparse.Namespace) -> list[str]:
    return _autopilot_source_values(args.required_source, args.required_sources)


def _autopilot_source_values(single_values: list[str], bulk_value: str | None) -> list[str]:
    sources = [item.strip() for item in (single_values or []) if item and item.strip()]
    if bulk_value:
        for item in re.split(r"[,;]", bulk_value):
            item = item.strip()
            if item:
                sources.append(item)
    return list(dict.fromkeys(sources))


def _autopilot_materiality_policy(thresholds: list[str]) -> dict[str, Any]:
    policy: dict[str, Any] = {"min_source_changes": 1}
    raw_rules = [item.strip() for item in thresholds if item and item.strip()]
    if raw_rules:
        policy["rules"] = raw_rules
    for rule in raw_rules:
        match = re.search(r"(?:source_changes|min_source_changes)\s*(?:>=|=)\s*(\d+)", rule)
        if match:
            policy["min_source_changes"] = max(int(match.group(1)), 1)
    return policy


def _autopilot_guardrail_policy(args: argparse.Namespace) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "require_no_critical_source_failures": True,
        "require_model_parse_success": True,
        "require_evidence_refs": True,
        "require_prior_forecast": True,
        "allow_resolution_auto_commit": False,
    }
    if args.max_auto_delta is not None:
        policy["max_single_run_probability_delta"] = args.max_auto_delta
    if args.min_sources_for_auto_commit is not None:
        policy["min_independent_sources_for_auto_commit"] = args.min_sources_for_auto_commit
    return policy


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
    return (
        source.startswith(("builtin:", "forecastbench:", "http://", "https://"))
        or Path(source).expanduser().is_file()
    )


def _should_use_metaculus_adapter(args: argparse.Namespace) -> bool:
    source = str(args.source or "").strip()
    manual_context = bool(args.title or args.resolution_criteria or args.baseline_probability is not None)
    if source.startswith(("id:", "http://", "https://")):
        return not manual_context or "metaculus.com" in source
    return source.isdigit() or not manual_context


def _load_backtest_cases(
    dataset: str,
    *,
    ledger: ForecastLedger | None = None,
    hide_market_baseline: bool = False,
) -> list[dict[str, Any]]:
    # Reject --market-hidden up front for any non-forecastbench dataset, BEFORE the
    # imported:/builtin: early-returns — otherwise the flag would silently no-op
    # there (the market baseline stays visible while the experimenter believes it
    # was withheld — a perceived foreknowledge leak).
    if hide_market_baseline and not dataset.startswith("forecastbench:"):
        raise SystemExit("--market-hidden only applies to forecastbench:<date> datasets")
    if dataset.startswith("imported:"):
        if ledger is None:
            raise SystemExit("imported benchmark datasets require a forecast ledger")
        return ledger.get_benchmark_dataset(dataset)["cases"]
    if dataset.startswith("builtin:"):
        try:
            return load_builtin_benchmark(dataset)
        except KeyError as exc:
            raise SystemExit(f"unknown built-in benchmark: {dataset}") from exc
    if dataset.startswith("forecastbench:"):
        from forecasting.forecastbench import ForecastBenchError, load_forecastbench_cases

        spec = dataset[len("forecastbench:") :]
        date_part, _, limit_part = spec.partition(":")
        date_part = date_part.strip()
        if not date_part:
            raise SystemExit(
                "forecastbench dataset needs a date, e.g. forecastbench:2026-06-07"
            )
        limit: int | None = None
        if limit_part.strip():
            try:
                limit = int(limit_part.strip())
            except ValueError as exc:
                raise SystemExit(
                    f"forecastbench limit must be an integer: {dataset}"
                ) from exc
        try:
            report = load_forecastbench_cases(
                date_part, limit=limit, hide_market_baseline=hide_market_baseline
            )
        except ForecastBenchError as exc:
            raise SystemExit(str(exc)) from exc
        return report["cases"]
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


def _resolved_recorded_agent_model(args: argparse.Namespace, agent_runner) -> str | None:
    """Model recorded on agent-protocol cases (drives the P2.4 cutoff gate).

    Prefer the explicit ``--agent-model``; otherwise fall back to the live
    agent's RESOLVED default model (exposed by ``_backtest_agent_protocol_runner``
    as ``resolved_agent_model``) so the model-cutoff gate still fires when
    ``--agent-model`` is omitted instead of recording an empty string.
    """

    explicit = getattr(args, "agent_model", None)
    if explicit:
        return explicit
    return getattr(agent_runner, "resolved_agent_model", None)


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

        # Replaying captured responses: no live agent, so the recorded model is
        # whatever the operator passed (the responses themselves carry agent_model).
        captured_runner.resolved_agent_model = args.agent_model or None
        return captured_runner

    from run_agent import AIAgent

    # Closed-book replay: the agent must have NO tool that can reach the now-known
    # outcome, so a historical question cannot be answered by fetching/reading it.
    # Dropping "web" is NOT enough, and neither is keeping "file": (a) the
    # "forecasting" toolset's forecast_ledger.import_source_evidence fetches the LIVE
    # current state of manifold/metaculus/polymarket/url sources (the answer), and
    # (b) the "file" toolset's read_file/search_files can read the on-disk
    # ForecastBench resolution-set cache (which holds resolved_to for every id). The
    # agent-protocol replay scores the agent's parsed JSON OUTPUT and needs NO tools
    # to emit a forecast, so closed-book runs with an EMPTY toolset — reason only.
    closed_book = bool(getattr(args, "closed_book", False))
    enabled_toolsets = [] if closed_book else ["forecasting", "file", "web"]

    agent = AIAgent(
        model=args.agent_model or "",
        provider=args.agent_provider,
        max_iterations=args.agent_max_iterations,
        enabled_toolsets=enabled_toolsets,
        platform="cli",
    )

    def live_runner(messages: list[dict[str, str]], case: dict[str, Any], index: int) -> Any:
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

    # P2.4 model-cutoff gate fires on the recorded agent_model; default it to the
    # agent's RESOLVED/default model so the gate works even when --agent-model is
    # omitted (agent.model is the resolved default, not the empty placeholder).
    live_runner.resolved_agent_model = (
        getattr(agent, "model", None) or args.agent_model or None
    )
    return live_runner


def _prepare_agent_protocol_output_jsonl(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def _write_agent_protocol_prompt_jsonl(path_value: str, cases: list[dict[str, Any]], *, dataset: str) -> Path:
    path, _ = _write_agent_protocol_prompt_jsonl_for_datasets(path_value, [(dataset, cases)])
    return path


def _write_agent_protocol_prompt_jsonl_for_datasets(
    path_value: str,
    datasets: list[tuple[str, list[dict[str, Any]]]],
) -> tuple[Path, int]:
    path = Path(path_value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    total_cases = 0
    with path.open("w", encoding="utf-8") as handle:
        for dataset, cases in datasets:
            for index, case in enumerate(cases):
                packet = build_agent_protocol_prompt_packet(case, case_index=index, dataset=dataset)
                handle.write(json.dumps(packet, sort_keys=True) + "\n")
                total_cases += 1
    return path, total_cases


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
    agent_skipped = 0
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
            except Exception as exc:  # noqa: BLE001 — a single bad/timed-out response
                # must NOT abort the whole backtest. Over a long run a flaky endpoint
                # would otherwise lose every case (the run never reaches persistence).
                # Skip this case + continue; the run still persists what succeeded.
                case_id = case.get("id") or f"index:{index}"
                agent_skipped += 1
                print(f"⚠️  skipped {case_id}: agent response invalid/failed ({type(exc).__name__}: {exc})")
                continue
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
    if agent_skipped:
        print(
            f"⚠️  {agent_skipped} case(s) skipped on invalid/failed agent responses; "
            f"persisting {len(transformed)} scored case(s)."
        )
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


# ── Carved subcommand domains ────────────────────────────────────────────────
# Imported back so `register_cli` can wire each domain's subparsers in order and
# so the handler names external callers import stay resolvable on this module.
from forecasting.cli import thesis as _thesis_domain  # noqa: E402

# test_thesis_dashboard imports forecasting.cli._cmd_thesis_dashboard directly.
_cmd_thesis_dashboard = _thesis_domain._cmd_thesis_dashboard
