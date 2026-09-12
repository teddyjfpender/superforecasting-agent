"""Structured source acquisition, independent of agent tools and ledger writes.

Source-specific fetchers/parsers own measurement semantics. This module owns
adapter selection and forwarding request options; callers decide how to persist
or use the returned records.
"""

from __future__ import annotations

from typing import Any

from forecasting.source_adapters import (
    load_arxiv_papers,
    load_bls_observations,
    load_bluesky_posts,
    load_census_records,
    load_cisa_kev_vulnerabilities,
    load_ckan_datasets,
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
    load_github_issues,
    load_github_releases,
    load_github_repository_snapshots,
    load_github_workflow_runs,
    load_hackernews_items,
    load_imf_datamapper_observations,
    load_kalshi_market,
    load_manifold_market,
    load_mastodon_statuses,
    load_metaculus_question,
    load_nasa_eonet_events,
    load_news_feed_items,
    load_npm_package_versions,
    load_nvd_cves,
    load_nws_alerts,
    load_openalex_works,
    load_openfda_drug_applications,
    load_openmeteo_air_quality_forecasts,
    load_openmeteo_daily_forecasts,
    load_openmeteo_historical_weather,
    load_owid_observations,
    load_polymarket_market,
    load_pubmed_articles,
    load_pypi_releases,
    load_reddit_posts,
    load_reliefweb_reports,
    load_sec_company_facts,
    load_sec_filings,
    load_sec_full_text_search,
    load_socrata_records,
    load_stooq_prices,
    load_treasury_records,
    load_usgs_earthquakes,
    load_who_gho_observations,
    load_wikimedia_pageviews,
    load_wikipedia_pages,
    load_worldbank_observations,
    load_yahoo_finance_prices,
)
from forecasting.sources.filters import normalize_filter_terms as normalize_filter_terms


def load_source_items(adapter: str, source: str, args: dict[str, Any]) -> list[Any]:
    adapter_name = adapter.removeprefix("adapter:").strip().lower()
    limit = int(args.get("limit") or 10)
    since = args.get("since")
    api_base_url = args.get("api_base_url")
    kwargs: dict[str, Any]

    if adapter_name in {"rss", "news"}:
        return load_news_feed_items(
            source,
            limit=limit,
            since=since,
            keywords=normalize_filter_terms(args.get("keywords")),
            exclude_keywords=normalize_filter_terms(args.get("exclude_keywords")),
            dedupe=bool(args.get("dedupe", True)),
        )
    if adapter_name == "gdelt":
        kwargs = {
            "limit": limit,
            "since": since,
            "timespan": args.get("timespan"),
            "source_country": args.get("source_country"),
            "source_lang": args.get("source_lang"),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_gdelt_articles(source, **kwargs)
    if adapter_name == "fivethirtyeight":
        kwargs = {
            "limit": limit,
            "since": since,
            "state": args.get("state"),
            "candidate": args.get("candidate"),
            "pollster": args.get("pollster"),
            "cycle": args.get("cycle"),
            "office_type": args.get("office_type"),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_fivethirtyeight_polls(source, **kwargs)
    if adapter_name == "fred":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_fred_observations(source, **kwargs)
    if adapter_name == "eia":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_eia_observations(source, **kwargs)
    if adapter_name == "treasury":
        kwargs = {
            "limit": limit,
            "since": since,
            "date_field": args.get("date_field") or "record_date",
        }
        if args.get("value_field"):
            kwargs["value_field"] = args.get("value_field")
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_treasury_records(source, **kwargs)
    if adapter_name == "bls":
        kwargs = {
            "limit": limit,
            "since": since,
            "start_year": args.get("start_year"),
            "end_year": args.get("end_year"),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_bls_observations(source, **kwargs)
    if adapter_name == "worldbank":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_worldbank_observations(source, **kwargs)
    if adapter_name == "imf":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_imf_datamapper_observations(source, **kwargs)
    if adapter_name == "census":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_census_records(source, **kwargs)
    if adapter_name == "socrata":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_socrata_records(source, **kwargs)
    if adapter_name == "ckan":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_ckan_datasets(source, **kwargs)
    if adapter_name == "stooq":
        kwargs = {
            "limit": limit,
            "since": since,
            "interval": args.get("interval") or "d",
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_stooq_prices(source, **kwargs)
    if adapter_name == "yahoo":
        kwargs = {
            "limit": limit,
            "since": since,
            "range_value": args.get("range_value") or args.get("range") or "1mo",
            "interval": args.get("interval") or "1d",
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_yahoo_finance_prices(source, **kwargs)
    if adapter_name == "sec":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_sec_filings(source, **kwargs)
    if adapter_name == "secfacts":
        kwargs = {
            "limit": limit,
            "since": since,
            "concept": args.get("concept"),
            "taxonomy": args.get("taxonomy") or "us-gaap",
            "unit": args.get("unit"),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_sec_company_facts(source, **kwargs)
    if adapter_name == "secsearch":
        kwargs = {"limit": limit, "since": since, "forms": args.get("forms")}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_sec_full_text_search(source, **kwargs)
    if adapter_name == "arxiv":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_arxiv_papers(source, **kwargs)
    if adapter_name == "openalex":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_openalex_works(source, **kwargs)
    if adapter_name == "crossref":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_crossref_works(source, **kwargs)
    if adapter_name == "wikipedia":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_wikipedia_pages(source, **kwargs)
    if adapter_name == "wikipediapageviews":
        kwargs = {
            "limit": limit,
            "since": since,
            "access": args.get("access") or "all-access",
            "agent": args.get("agent") or "user",
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_wikimedia_pageviews(source, **kwargs)
    if adapter_name == "github":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_github_releases(source, **kwargs)
    if adapter_name == "githubrepo":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_github_repository_snapshots(source, **kwargs)
    if adapter_name == "githubissues":
        kwargs = {
            "limit": limit,
            "since": since,
            "state": args.get("state") or "all",
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_github_issues(source, **kwargs)
    if adapter_name == "githubcommits":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_github_commits(source, **kwargs)
    if adapter_name == "githubactions":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_github_workflow_runs(source, **kwargs)
    if adapter_name == "coingecko":
        kwargs = {
            "limit": limit,
            "since": since,
            "vs_currency": args.get("vs_currency") or "usd",
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_coingecko_market_snapshots(source, **kwargs)
    if adapter_name == "pypi":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_pypi_releases(source, **kwargs)
    if adapter_name == "npm":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_npm_package_versions(source, **kwargs)
    if adapter_name == "hackernews":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_hackernews_items(source, **kwargs)
    if adapter_name == "reddit":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_reddit_posts(source, **kwargs)
    if adapter_name == "bluesky":
        kwargs = {
            "limit": limit,
            "since": since,
            "sort": args.get("sort") or "latest",
            "author": args.get("author"),
            "lang": args.get("lang"),
            "link_domain": args.get("link_domain"),
            "url_filter": args.get("url_filter"),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_bluesky_posts(source, **kwargs)
    if adapter_name == "mastodon":
        kwargs = {
            "limit": limit,
            "since": since,
            "local": bool(args.get("local", False)),
            "only_media": bool(args.get("only_media", False)),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_mastodon_statuses(source, **kwargs)
    if adapter_name == "reliefweb":
        kwargs = {"limit": limit, "since": since, "appname": args.get("appname")}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_reliefweb_reports(source, **kwargs)
    if adapter_name == "federalregister":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_federal_register_documents(source, **kwargs)
    if adapter_name == "courtlistener":
        kwargs = {
            "limit": limit,
            "since": since,
            "search_type": args.get("search_type") or "o",
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_courtlistener_search_results(source, **kwargs)
    if adapter_name == "nvd":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_nvd_cves(source, **kwargs)
    if adapter_name == "cisakev":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_cisa_kev_vulnerabilities(source, **kwargs)
    if adapter_name == "openmeteo":
        kwargs = {
            "limit": limit,
            "since": since,
            "forecast_days": int(args.get("forecast_days") or 7),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_openmeteo_daily_forecasts(source, **kwargs)
    if adapter_name == "airquality":
        kwargs = {
            "limit": limit,
            "since": since,
            "forecast_days": int(args.get("forecast_days") or 5),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_openmeteo_air_quality_forecasts(source, **kwargs)
    if adapter_name == "weatherhistory":
        kwargs = {
            "limit": limit,
            "since": since,
            "start_date": args.get("start_date"),
            "end_date": args.get("end_date"),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_openmeteo_historical_weather(source, **kwargs)
    if adapter_name == "usgs":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_usgs_earthquakes(source, **kwargs)
    if adapter_name == "eonet":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_nasa_eonet_events(source, **kwargs)
    if adapter_name == "nws":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_nws_alerts(source, **kwargs)
    if adapter_name == "clinicaltrials":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_clinicaltrials_studies(source, **kwargs)
    if adapter_name == "openfda":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_openfda_drug_applications(source, **kwargs)
    if adapter_name == "pubmed":
        kwargs = {"limit": limit, "since": since}
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_pubmed_articles(source, **kwargs)
    if adapter_name == "owid":
        kwargs = {
            "limit": limit,
            "since": since,
            "entity": args.get("entity"),
            "value_column": args.get("value_column"),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_owid_observations(source, **kwargs)
    if adapter_name == "whogho":
        kwargs = {
            "limit": limit,
            "since": since,
            "country": args.get("country"),
            "dimensions": args.get("dimensions") or args.get("dimension"),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_who_gho_observations(source, **kwargs)
    if adapter_name == "fema":
        kwargs = {
            "limit": limit,
            "since": since,
            "state": args.get("state"),
            "incident_type": args.get("incident_type"),
            "declaration_type": args.get("declaration_type"),
        }
        if api_base_url:
            kwargs["api_base_url"] = api_base_url
        return load_fema_disaster_declarations(source, **kwargs)
    # Prediction-market / forecasting-platform adapters. Each takes a specific
    # market identifier (URL, slug, id, or ticker) and returns one market
    # import. Wiring these here means the agent imports a Polymarket/Kalshi/
    # Manifold/Metaculus price through the bounded adapter instead of writing
    # ad-hoc urllib/curl in the terminal (which hangs to the command timeout).
    if adapter_name == "polymarket":
        kwargs = {"api_base_url": api_base_url} if api_base_url else {}
        return [load_polymarket_market(source, **kwargs)]
    if adapter_name == "kalshi":
        kwargs = {"api_base_url": api_base_url} if api_base_url else {}
        return [load_kalshi_market(source, **kwargs)]
    if adapter_name == "manifold":
        kwargs = {"api_base_url": api_base_url} if api_base_url else {}
        return [load_manifold_market(source, **kwargs)]
    if adapter_name == "metaculus":
        kwargs = {"api_base_url": api_base_url} if api_base_url else {}
        return [load_metaculus_question(source, **kwargs)]
    if adapter_name in {"url", "http", "https", "web", "page", "html", "link"}:
        raise ValueError(
            f"source_type '{adapter}' is not a structured adapter. For a raw web page, use the "
            "'ingest' action (or capture it as evidence with source_or_note=<url>) instead of "
            "import_source_evidence, which is for structured feeds (fred/bls/polymarket/kalshi/...)."
        )
    raise ValueError(f"source_type is not a supported import adapter: {adapter}")
