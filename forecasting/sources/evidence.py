"""Translate parsed source records into evidence payloads without IO or writes."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from forecasting.sources.filters import normalize_filter_terms


def news_triage_metadata(args: dict[str, Any]) -> dict[str, Any]:
    keywords = normalize_filter_terms(args.get("keywords"))
    exclude_keywords = normalize_filter_terms(args.get("exclude_keywords"))
    affected_components = normalize_filter_terms(args.get("affected_components"))
    metadata: dict[str, Any] = {"dedupe": bool(args.get("dedupe", True))}
    if keywords or exclude_keywords:
        metadata["relevance_filters"] = {
            "keywords": keywords,
            "exclude_keywords": exclude_keywords,
        }
    impact: dict[str, Any] = {}
    if args.get("direction"):
        impact["direction"] = args["direction"]
    if affected_components:
        impact["affected_components"] = affected_components
    if args.get("materiality"):
        impact["materiality"] = args["materiality"]
    if impact:
        metadata["forecast_impact"] = impact
    if keywords or exclude_keywords or impact:
        metadata["news_triage"] = {
            "state": "candidate_evidence",
            "no_silent_probability_mutation": True,
        }
    return metadata


def source_evidence_payload(
    adapter: str,
    source: str,
    item: Any,
    args: dict[str, Any],
) -> dict[str, Any]:
    adapter_name = adapter.removeprefix("adapter:").strip().lower()
    data = _adapter_item_dict(item)
    source_url = _first_adapter_value(
        data, "source_url", "url", "html_url", "hn_url", "permalink", "pdf_url"
    )
    claim = args.get("claim") or _adapter_claim(adapter_name, data)
    summary = args.get("summary") or _adapter_summary(data)
    published_at = _first_adapter_value(
        data,
        "published_at",
        "revised_at",
        "latest_upload_at",
        "uploaded_at",
        "time",
        "latest_geometry_at",
        "sent_at",
        "last_update_posted_at",
        "last_update_submitted_at",
        "latest_submission_status_date",
        "declaration_date",
        "last_refresh",
        "run_started_at",
        "updated_at",
        "last_updated",
        "metadata_modified",
        "metadata_created",
        "observation_time",
        "committed_at",
        "authored_at",
        "created_at",
        "date_added",
        "due_date",
        "date_filed",
        "date_argued",
        "observation_date",
        "observation_time",
        "forecast_time",
        "forecast_date",
        "filing_date",
    )
    available_at = args.get("available_at") or published_at
    source_name = args.get("source_name") or data.get("source_name") or adapter_name
    metadata = {
        "adapter": adapter_name,
        "source": source,
        "entry_id": data.get("entry_id"),
        "adapter_item": data,
    }
    if adapter_name in {"rss", "news"}:
        metadata.update(news_triage_metadata(args))
    metadata.update(args.get("metadata") or {})
    return {
        "source_or_note": source_url or claim or f"{adapter_name}:{source}",
        "source_url": source_url,
        "source_name": str(source_name),
        "source_type": f"adapter:{adapter_name}",
        "published_at": published_at,
        "available_at": available_at,
        "claim": str(claim or ""),
        "summary": str(summary or ""),
        "reliability_rating": args.get("reliability_rating"),
        "relevance_rating": args.get("relevance_rating"),
        "stance": args.get("stance") or "context",
        "claim_type": args.get("claim_type")
        or (
            "estimate"
            if adapter_name in {"fivethirtyeight", "imf", "openmeteo", "airquality"}
            else "fact"
        ),
        "snapshot_path": args.get("snapshot_path"),
        "admissible_for_backtests": bool(args.get("admissible_for_backtests", True)),
        "metadata": metadata,
    }


def _adapter_item_dict(item: Any) -> dict[str, Any]:
    if is_dataclass(item):
        return asdict(item)
    if isinstance(item, dict):
        return dict(item)
    return dict(getattr(item, "__dict__", {}))


def _first_adapter_value(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _adapter_summary(data: dict[str, Any]) -> str:
    for key in (
        "summary",
        "abstract",
        "extract",
        "body",
        "description",
        "selftext",
        "text",
        "content_text",
    ):
        value = data.get(key)
        if value:
            return str(value)
    return json.dumps(
        {
            key: value
            for key, value in data.items()
            if key != "raw" and value not in (None, "")
        },
        sort_keys=True,
    )


def _adapter_claim(adapter: str, data: dict[str, Any]) -> str:
    if adapter == "fred":
        return f"FRED {data.get('series_id')} was {data.get('value')} on {data.get('observation_date')}"
    if adapter == "eia":
        unit = f" {data.get('unit')}" if data.get("unit") else ""
        return f"EIA {data.get('series_id')} was {data.get('value')}{unit} for {data.get('observation_period')}"
    if adapter == "treasury":
        field = data.get("value_field")
        value = f"{field}={data.get('value')}" if field else data.get("value")
        return f"Treasury {data.get('dataset')} {data.get('record_date')}: {value}"
    if adapter == "bls":
        return f"BLS {data.get('series_id')} was {data.get('value')} for {data.get('period_name') or data.get('period')}"
    if adapter == "worldbank":
        label = data.get("indicator_name") or data.get("indicator")
        return f"World Bank {label} was {data.get('value')} for {data.get('country_name') or data.get('country')} in {data.get('observation_date')}"
    if adapter == "imf":
        label = data.get("indicator_name") or data.get("indicator")
        return f"IMF DataMapper {label} was {data.get('value')} for {data.get('country_name') or data.get('country')} in {data.get('observation_date')}"
    if adapter == "census":
        values = data.get("values")
        value_text = (
            ", ".join(f"{key}={value}" for key, value in values.items())
            if isinstance(values, dict)
            else values
        )
        geography = data.get("geography")
        geography_text = (
            ", ".join(f"{key}={value}" for key, value in geography.items())
            if isinstance(geography, dict) and geography
            else "all geographies"
        )
        return f"Census {data.get('dataset')} {geography_text}: {value_text}"
    if adapter == "socrata":
        return f"Socrata row {data.get('domain')}/{data.get('dataset_id')} {data.get('row_id') or data.get('entry_id')}"
    if adapter == "ckan":
        return f"CKAN dataset {data.get('portal')} {data.get('title') or data.get('name') or data.get('package_id')}"
    if adapter == "stooq":
        return f"Stooq {data.get('symbol')} close was {data.get('close_price')} on {data.get('observation_date')}"
    if adapter == "yahoo":
        currency = f" {data.get('currency')}" if data.get("currency") else ""
        return f"Yahoo Finance {data.get('symbol')} close was {data.get('close_price')}{currency} at {data.get('observation_time')}"
    if adapter in ("sec", "secsearch"):
        return f"SEC {data.get('form')} filing for {data.get('company_name') or data.get('cik')} on {data.get('filing_date')}"
    if adapter == "secfacts":
        label = data.get("label") or data.get("concept")
        return (
            f"SEC Company Facts {data.get('company_name') or data.get('cik')} {label} "
            f"was {data.get('value')} {data.get('unit')} for {data.get('observation_date')}"
        )
    if adapter == "fivethirtyeight":
        subject = data.get("candidate_name") or data.get("answer") or "poll answer"
        pct = f"{data.get('pct')}%" if data.get("pct") is not None else "unknown share"
        geography = data.get("state") or "national"
        return f"FiveThirtyEight poll {data.get('dataset')}: {subject} {pct} in {geography}"
    if adapter == "wikipediapageviews":
        return f"Wikimedia pageviews for {data.get('article')} were {data.get('views')} on {data.get('observation_date')}"
    if adapter == "github":
        return f"GitHub release {data.get('repo')} {data.get('tag_name')}: {data.get('name')}"
    if adapter == "githubrepo":
        return (
            f"GitHub repository {data.get('repo')}: {data.get('stargazers_count')} stars, "
            f"{data.get('forks_count')} forks, {data.get('open_issues_count')} open issues"
        )
    if adapter == "githubissues":
        issue_kind = "pull request" if data.get("is_pull_request") else "issue"
        number = (
            f"#{data.get('issue_number')}"
            if data.get("issue_number") is not None
            else data.get("entry_id")
        )
        return f"GitHub {issue_kind} {data.get('repo')} {number}: {data.get('title')}"
    if adapter == "githubcommits":
        return f"GitHub commit {data.get('repo')} {data.get('short_sha')}: {data.get('message')}"
    if adapter == "githubactions":
        status = data.get("conclusion") or data.get("status") or "state unknown"
        return f"GitHub Actions run {data.get('repo')} {data.get('run_id')}: {status}"
    if adapter == "coingecko":
        currency = str(data.get("vs_currency") or "").upper()
        return (
            f"CoinGecko {data.get('coin_id')} price was "
            f"{data.get('current_price')} {currency} at {data.get('last_updated')}"
        )
    if adapter == "pypi":
        return f"PyPI release {data.get('package')} {data.get('version')}: {data.get('summary') or 'package release'}"
    if adapter == "npm":
        return f"npm package {data.get('package')} {data.get('version')}: {data.get('description') or 'package version'}"
    if adapter == "hackernews":
        return f"Hacker News: {data.get('title')}"
    if adapter == "reddit":
        return f"Reddit: {data.get('title')}"
    if adapter == "bluesky":
        text = str(data.get("text") or data.get("post_uri") or "")
        return f"Bluesky: {text[:140]}"
    if adapter == "mastodon":
        text = str(data.get("content_text") or data.get("status_id") or "")
        return f"Mastodon: {text[:140]}"
    if adapter == "reliefweb":
        return f"ReliefWeb: {data.get('title')}"
    if adapter == "courtlistener":
        court = f" {data.get('court_id')}" if data.get("court_id") else ""
        filed = f" filed {data.get('date_filed')}" if data.get("date_filed") else ""
        return f"CourtListener{court}{filed}: {data.get('title')}"
    if adapter == "nvd":
        return f"NVD {data.get('cve_id')}: {data.get('severity') or data.get('vuln_status') or 'record'}"
    if adapter == "cisakev":
        product = data.get("product") or "affected product"
        return f"CISA KEV {data.get('cve_id')}: {data.get('vendor_project') or ''} {product}".strip()
    if adapter == "openmeteo":
        return f"Open-Meteo daily forecast for {data.get('latitude')},{data.get('longitude')} on {data.get('forecast_date')}"
    if adapter == "airquality":
        return (
            f"Open-Meteo air quality forecast for {data.get('latitude')},{data.get('longitude')} "
            f"at {data.get('forecast_time')}: US AQI {data.get('us_aqi')}, PM2.5 {data.get('pm2_5')}"
        )
    if adapter == "weatherhistory":
        return (
            f"Open-Meteo historical weather for {data.get('latitude')},{data.get('longitude')} "
            f"on {data.get('observation_date')}: mean {data.get('temperature_2m_mean')}, "
            f"precip {data.get('precipitation_sum')}"
        )
    if adapter == "usgs":
        magnitude = data.get("magnitude")
        magnitude_label = (
            f"M{magnitude:g}" if isinstance(magnitude, (int, float)) else "event"
        )
        return f"USGS {data.get('event_type') or 'event'} {magnitude_label}: {data.get('place') or data.get('title')}"
    if adapter == "eonet":
        categories = data.get("categories")
        category_label = (
            ", ".join(categories)
            if isinstance(categories, list) and categories
            else "event"
        )
        return f"NASA EONET {category_label}: {data.get('title')}"
    if adapter == "nws":
        return f"NWS {data.get('event')}: {data.get('headline')}"
    if adapter == "clinicaltrials":
        return f"ClinicalTrials.gov {data.get('nct_id')}: {data.get('status') or 'study'} - {data.get('brief_title')}"
    if adapter == "openfda":
        brand_names = data.get("brand_names")
        brand = (
            ", ".join(brand_names[:3])
            if isinstance(brand_names, list) and brand_names
            else "drug application"
        )
        return f"openFDA {data.get('application_number')}: {data.get('latest_submission_status') or 'application'} - {brand}"
    if adapter == "pubmed":
        return f"PubMed {data.get('pmid')}: {data.get('title')}"
    if adapter == "crossref":
        doi = f" ({data.get('doi')})" if data.get("doi") else ""
        return f"Crossref work{doi}: {data.get('title')}"
    if adapter == "owid":
        return f"OWID {data.get('slug')} {data.get('entity') or ''} {data.get('value_column')} was {data.get('value')} on {data.get('observation_date')}"
    if adapter == "whogho":
        geography = f" {data.get('spatial_dim')}" if data.get("spatial_dim") else ""
        time_label = f" {data.get('time_dim')}" if data.get("time_dim") else ""
        return f"WHO GHO {data.get('indicator')}{geography}{time_label}: {data.get('value')}"
    if adapter == "fema":
        geography = f" {data.get('state')}" if data.get("state") else ""
        area = f" {data.get('designated_area')}" if data.get("designated_area") else ""
        number = (
            f" {data.get('disaster_number')}"
            if data.get("disaster_number") is not None
            else ""
        )
        return f"FEMA{number}{geography}{area}: {data.get('incident_type') or data.get('title')}"
    if adapter in {"polymarket", "kalshi", "manifold", "metaculus"}:
        label = {
            "polymarket": "Polymarket",
            "kalshi": "Kalshi",
            "manifold": "Manifold",
            "metaculus": "Metaculus",
        }[adapter]
        question = data.get("question") or data.get("title") or "market"
        probability = data.get("probability")
        if isinstance(probability, (int, float)) and not isinstance(probability, bool):
            return f"{label} market-implied probability {float(probability):.3f}: {question}"
        distribution = data.get("distribution")
        if isinstance(distribution, dict) and distribution:
            numeric = {
                k: v
                for k, v in distribution.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
            if numeric:
                top_outcome, top_value = max(numeric.items(), key=lambda kv: kv[1])
                return f"{label} top outcome {top_outcome} at {float(top_value):.3f}: {question}"
        return f"{label}: {question}"
    return str(
        _first_adapter_value(
            data,
            "title",
            "name",
            "question",
            "cve_id",
            "entry_id",
        )
        or f"{adapter} evidence item"
    )
