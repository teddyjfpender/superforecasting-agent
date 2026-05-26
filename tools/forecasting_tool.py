"""Forecast ledger tool for forecast-stage agents."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from typing import Any

from forecasting import ForecastLedger, PRODUCT_NAME, PRODUCT_SLUG
from forecasting.backtesting import (
    DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM,
    DEFAULT_MIN_EXTERNAL_SOURCE_FAMILIES_FOR_CLAIM,
    DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM,
    build_backtest_performance_summaries,
    build_forecasting_evidence_status,
)
from forecasting.ensembles import linear_trend_projection, weighted_binary_probability
from forecasting.learning import apply_active_lesson_adjustments
from forecasting.models import ForecastingError, OutcomeSpace, utc_now_iso
from forecasting.protocol import build_protocol_messages
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
    load_news_feed_items,
    load_mastodon_statuses,
    load_npm_package_versions,
    load_nvd_cves,
    load_nasa_eonet_events,
    load_nws_alerts,
    load_openalex_works,
    load_openfda_drug_applications,
    load_openmeteo_air_quality_forecasts,
    load_openmeteo_daily_forecasts,
    load_openmeteo_historical_weather,
    load_owid_observations,
    load_pubmed_articles,
    load_pypi_releases,
    load_reddit_posts,
    load_reliefweb_reports,
    load_sec_company_facts,
    load_sec_filings,
    load_socrata_records,
    load_stooq_prices,
    load_treasury_records,
    load_usgs_earthquakes,
    load_wikimedia_pageviews,
    load_wikipedia_pages,
    load_who_gho_observations,
    load_worldbank_observations,
    load_yahoo_finance_prices,
)
from tools.registry import registry, tool_error, tool_result


FORECAST_LEDGER_SCHEMA = {
    "name": "forecast_ledger",
    "description": (
        "Operate on the forecast ledger: create questions, add evidence, append "
        "forecast snapshots, resolve, score, review, self-check, and render "
        "forecast protocol context. Forecast snapshots are append-only; autopilot "
        "actions maintain watched-source update proposals through the ledger."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create_question",
                    "list_questions",
                    "show_question",
                    "add_evidence",
                    "import_source_evidence",
                    "add_baseline_comparison",
                    "list_baseline_comparisons",
                    "add_assumption",
                    "list_assumptions",
                    "update_assumption",
                    "add_reference_class",
                    "list_reference_classes",
                    "update_reference_class",
                    "record_model_run",
                    "list_model_runs",
                    "update_forecast",
                    "resolve",
                    "score",
                    "list_scores",
                    "review",
                    "self_check",
                    "list_alerts",
                    "acknowledge_alert",
                    "calibration_summary",
                    "list_domain_error_profiles",
                    "run_backtest_dataset",
                    "list_backtest_runs",
                    "backtest_performance_report",
                    "evidence_readiness",
                    "doctor_report",
                    "pilot_report",
                    "add_watched_source",
                    "list_watched_sources",
                    "check_watched_sources",
                    "autopilot_readiness",
                    "enable_autopilot",
                    "disable_autopilot",
                    "autopilot_status",
                    "run_autopilot",
                    "list_autopilot_policies",
                    "list_autopilot_runs",
                    "list_forecast_update_proposals",
                    "approve_forecast_update_proposal",
                    "reject_forecast_update_proposal",
                    "schedule_review",
                    "list_scheduled_reviews",
                    "run_scheduled_reviews",
                    "list_calibration_lessons",
                    "update_calibration_lesson",
                    "postmortem",
                    "list_postmortems",
                    "create_correction",
                    "list_corrections",
                    "create_trusted_resolver_policy",
                    "list_trusted_resolver_policies",
                    "export_question",
                    "export_all",
                    "import_packet",
                    "protocol",
                ],
            },
            "question_id": {"type": "string"},
            "title": {"type": "string"},
            "resolution_criteria": {"type": "string"},
            "resolution_source": {"type": "string"},
            "description": {"type": "string"},
            "domain": {"type": "string"},
            "target_type": {
                "type": "string",
                "enum": [
                    "forecast_snapshot",
                    "evidence_item",
                    "assumption",
                    "reference_class",
                    "resolution",
                    "score_record",
                    "postmortem",
                    "calibration_lesson",
                ],
            },
            "target_id": {"type": "string"},
            "reason": {"type": "string"},
            "created_by": {"type": "string"},
            "resolver_plugin": {"type": "string"},
            "plugin_version": {"type": "string"},
            "approved_by": {"type": "string"},
            "audit_log_ref": {"type": "string"},
            "old_value": {},
            "new_value": {},
            "patch": {"type": "object"},
            "forecast_origin": {
                "type": "string",
                "enum": ["live", "backtest", "imported_baseline"],
            },
            "horizon": {"type": "string"},
            "bucket": {"type": "string"},
            "calibration_eligible": {"type": "boolean"},
            "status": {"type": "string"},
            "topic": {"type": "string"},
            "portfolio": {"type": "string"},
            "outcome_type": {
                "type": "string",
                "enum": ["binary", "categorical", "numeric", "distribution"],
            },
            "choices": {"type": "array", "items": {"type": "string"}},
            "units": {"type": "string"},
            "bounds": {"type": "array", "items": {"type": "number"}},
            "close_time": {"type": "string"},
            "resolution_time": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "topics": {"type": "array", "items": {"type": "string"}},
            "owner": {"type": "string"},
            "impact": {"type": "string"},
            "review_cadence": {"type": "string"},
            "next_review_at": {"type": "string"},
            "name": {"type": "string"},
            "dataset": {"type": "string"},
            "limit": {"type": "integer"},
            "since": {"type": "string"},
            "api_base_url": {"type": "string"},
            "appname": {"type": "string"},
            "range_value": {"type": "string"},
            "timespan": {"type": "string"},
            "search_type": {"type": "string"},
            "state": {"type": "string"},
            "candidate": {"type": "string"},
            "pollster": {"type": "string"},
            "cycle": {"type": "integer"},
            "office_type": {"type": "string"},
            "incident_type": {"type": "string"},
            "declaration_type": {"type": "string"},
            "source_country": {"type": "string"},
            "source_lang": {"type": "string"},
            "start_year": {"type": "integer"},
            "end_year": {"type": "integer"},
            "forecast_days": {"type": "integer"},
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
            "entity": {"type": "string"},
            "value_column": {"type": "string"},
            "date_field": {"type": "string"},
            "value_field": {"type": "string"},
            "vs_currency": {"type": "string"},
            "concept": {"type": "string"},
            "taxonomy": {"type": "string"},
            "unit": {"type": "string"},
            "access": {"type": "string"},
            "agent": {"type": "string"},
            "format": {"type": "string", "enum": ["json", "markdown"]},
            "packet": {"type": "object"},
            "conflict": {"type": "string", "enum": ["error", "skip", "replace"]},
            "cases": {"type": "array", "items": {"type": "object"}},
            "run_id": {"type": "string"},
            "policy_id": {"type": "string"},
            "forecast_id": {"type": "string"},
            "backtest_case_id": {"type": "string"},
            "score_record_id": {"type": "string"},
            "default_forecast_time_cutoff": {"type": "string"},
            "evidence_cutoff_policy": {"type": "string"},
            "allow_calibration_memory": {"type": "boolean"},
            "inclusion_criteria": {"type": "string"},
            "exclusion_criteria": {"type": "string"},
            "base_rate": {"type": "number"},
            "uncertainty": {"type": "number"},
            "source_refs": {"type": "array", "items": {"type": "string"}},
            "model_type": {"type": "string"},
            "model_status": {"type": "string", "enum": ["success", "failure"]},
            "inputs": {"type": "object"},
            "parameters": {"type": "object"},
            "output": {"type": "object"},
            "diagnostics": {"type": "object"},
            "series": {"type": "array", "items": {}},
            "target_date": {"type": "string"},
            "target_x": {"type": "number"},
            "date_field": {"type": "string"},
            "value_field": {"type": "string"},
            "code_ref": {"type": "string"},
            "artifact_paths": {"type": "array", "items": {"type": "string"}},
            "model_version": {"type": "string"},
            "data_version": {"type": "string"},
            "metadata": {"type": "object"},
            "probability": {"type": "number"},
            "probability_or_distribution": {},
            "proposed_probability": {"type": "number"},
            "proposed_probability_or_distribution": {},
            "baseline_type": {"type": "string"},
            "components": {"type": "object"},
            "method": {"type": "string"},
            "rationale": {"type": "string"},
            "text": {"type": "string"},
            "assumption_id": {"type": "string"},
            "reference_class_id": {"type": "string"},
            "notes": {"type": "string"},
            "check_cadence": {"type": "string"},
            "last_checked_at": {"type": "string"},
            "invalidated_at": {"type": "string"},
            "as_of": {"type": "string"},
            "agent_model": {"type": "string"},
            "prompt_version": {"type": "string"},
            "forecasting_protocol_version": {"type": "string"},
            "protocol_version": {"type": "string"},
            "toolset_version": {"type": "string"},
            "source_or_note": {"type": "string"},
            "source": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string"}},
            "required_source": {"type": "string"},
            "required_sources": {"type": "array", "items": {"type": "string"}},
            "source_url": {"type": "string"},
            "source_name": {"type": "string"},
            "mode": {
                "type": "string",
                "enum": ["propose", "auto-commit", "auto_commit", "alert-only", "alert_only"],
            },
            "sort": {"type": "string", "enum": ["latest", "top"]},
            "author": {"type": "string"},
            "lang": {"type": "string"},
            "link_domain": {"type": "string"},
            "url_filter": {"type": "string"},
            "local": {"type": "boolean"},
            "only_media": {"type": "boolean"},
            "source_type": {
                "type": "string",
                "enum": [
                    "file",
                    "url",
                    "manual",
                    "manual_note",
                    "rss",
                    "gdelt",
                    "fivethirtyeight",
                    "github",
                    "githubrepo",
                    "githubissues",
                    "githubcommits",
                    "githubactions",
                    "coingecko",
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
                    "sec",
                    "secfacts",
                    "arxiv",
                    "openalex",
                    "crossref",
                    "wikipedia",
                    "wikipediapageviews",
                    "manifold",
                    "metaculus",
                    "polymarket",
                    "kalshi",
                ],
            },
            "scope_type": {
                "type": "string",
                "enum": [
                    "question",
                    "domain",
                    "topic",
                    "domain_topic",
                    "portfolio",
                    "horizon",
                    "source",
                    "question_type",
                    "global",
                ],
            },
            "scope_ref": {"type": "string"},
            "lesson_id": {"type": "string"},
            "lesson_status": {
                "type": "string",
                "enum": ["tentative", "active", "superseded", "rejected"],
            },
            "confidence": {"type": "number"},
            "confidence_below": {"type": "number"},
            "confidence_above": {"type": "number"},
            "large_delta_threshold": {"type": "number"},
            "claim": {"type": "string"},
            "claim_type": {
                "type": "string",
                "enum": ["fact", "estimate", "rumor", "opinion", "assumption"],
            },
            "summary": {"type": "string"},
            "published_at": {"type": "string"},
            "what_happened": {"type": "string"},
            "what_was_expected": {"type": "string"},
            "missed_evidence": {"type": "string"},
            "overweighted_evidence": {"type": "string"},
            "base_rate_error": {"type": "string"},
            "inside_view_error": {"type": "string"},
            "resolution_error": {"type": "string"},
            "available_at": {"type": "string"},
            "reliability_rating": {"type": "number"},
            "relevance_rating": {"type": "number"},
            "stance": {
                "type": "string",
                "enum": ["supports", "opposes", "mixed", "context"],
            },
            "snapshot_path": {"type": "string"},
            "admissible_for_backtests": {"type": "boolean"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "model_run_refs": {"type": "array", "items": {"type": "string"}},
            "key_assumptions": {"type": "array", "items": {"type": "string"}},
            "assumption_refs": {"type": "array", "items": {"type": "string"}},
            "reference_class_refs": {"type": "array", "items": {"type": "string"}},
            "source_snapshot_refs": {"type": "array", "items": {"type": "string"}},
            "calibration_lesson_refs": {"type": "array", "items": {"type": "string"}},
            "calibration_adjustment": {"type": "object"},
            "calibration_weight": {"type": "number"},
            "use_active_lessons": {"type": "boolean"},
            "alert_id": {"type": "string"},
            "acknowledged_at": {"type": "string"},
            "proposal_id": {"type": "string"},
            "proposal_status": {
                "type": "string",
                "enum": ["pending", "approved", "rejected", "expired", "auto_committed"],
            },
            "reviewed_by": {"type": "string"},
            "include_reviewed": {"type": "boolean"},
            "stale_evidence_days": {"type": "integer"},
            "ack_stale_evidence": {"type": "boolean"},
            "require_citations": {"type": "boolean"},
            "evidence_cutoff": {"type": "string"},
            "backtest_run_id": {"type": "string"},
            "outcome": {"type": "string"},
            "resolution_source_snapshot_ref": {"type": "string"},
            "resolver_type": {
                "type": "string",
                "enum": ["manual", "source_adapter", "scheduled_check"],
            },
            "resolution_status": {
                "type": "string",
                "enum": ["proposed", "confirmed", "disputed", "corrected"],
            },
            "criteria_satisfied": {"type": "boolean"},
            "confirmed_by": {"type": "string"},
            "resolver_notes": {"type": "string"},
            "correction_ref": {"type": "string"},
            "trusted_policy_id": {"type": "string"},
            "scoreable": {"type": "boolean"},
            "stale": {"type": "boolean"},
            "last_days": {"type": "integer"},
            "stale_days": {"type": "integer"},
            "last": {"type": "integer"},
            "min_live_scores": {"type": "integer"},
            "min_agent_protocol_cases": {"type": "integer"},
            "min_external_source_families": {"type": "integer"},
            "min_questions": {"type": "integer"},
            "min_structured_source_questions": {"type": "integer"},
            "min_scores": {"type": "integer"},
            "min_postmortems": {"type": "integer"},
            "min_scheduled_reviews": {"type": "integer"},
            "min_scheduled_review_runs": {"type": "integer"},
            "auto_score": {"type": "boolean"},
            "auto_postmortem": {"type": "boolean"},
            "cadence": {"type": "string"},
            "next_run_at": {
                "type": "string",
                "description": "First run timestamp for schedule_review or enable_autopilot; defaults to now when omitted.",
            },
            "trigger_reason": {"type": "string"},
            "materiality_policy": {"type": "object"},
            "guardrail_policy": {"type": "object"},
            "notification_policy": {"type": "object"},
            "min_source_changes": {"type": "integer"},
            "max_auto_delta": {"type": "number"},
            "min_sources_for_auto_commit": {"type": "integer"},
            "notify": {"type": "string"},
            "quiet_if_unchanged": {"type": "boolean"},
            "allow_missing_resolution_source": {"type": "boolean"},
            "enabled": {"type": "boolean"},
            "now": {"type": "string"},
            "include_inactive": {"type": "boolean"},
            "include_invalidated": {"type": "boolean"},
            "unresolved_only": {"type": "boolean"},
            "active_only": {"type": "boolean"},
            "stage": {
                "type": "string",
                "enum": ["parse", "research", "base_rate", "model", "update", "resolve", "postmortem", "self_check"],
            },
            "lesson": {"type": "string"},
            "db": {"type": "string"},
        },
        "required": ["action"],
    },
}


def check_forecasting_requirements() -> bool:
    return True


def forecast_ledger_tool(args: dict[str, Any]) -> str:
    ledger = ForecastLedger(args.get("db"))
    action = args.get("action")
    try:
        if action == "create_question":
            question = ledger.create_question(
                title=args.get("title") or "",
                description=args.get("description") or "",
                resolution_criteria=args.get("resolution_criteria") or "",
                resolution_source=args.get("resolution_source"),
                domain=args.get("domain"),
                outcome_space=OutcomeSpace(
                    type=args.get("outcome_type") or "binary",
                    choices=args.get("choices") or ["yes", "no"],
                    units=args.get("units"),
                    bounds=args.get("bounds"),
                ),
                close_time=args.get("close_time"),
                resolution_time=args.get("resolution_time"),
                tags=args.get("tags") or [],
                topics=args.get("topics") or [],
                owner=args.get("owner"),
                impact=args.get("impact"),
                review_cadence=args.get("review_cadence"),
                next_review_at=args.get("next_review_at"),
            )
            return tool_result(success=True, question=_question_dict(question))

        if action == "list_questions":
            questions = ledger.list_questions(status=args.get("status"), domain=args.get("domain"))
            return tool_result(success=True, questions=[_question_dict(q) for q in questions])

        if action == "show_question":
            question_id = _required(args, "question_id")
            question = ledger.get_question(question_id)
            current = ledger.get_current_snapshot(question_id)
            postmortems = ledger.list_postmortems(question_id, include_invalidated=True)
            scores = [
                score.__dict__
                for score in ledger.list_scores(include_invalidated=True)
                if score.question_id == question_id
            ]
            return tool_result(
                success=True,
                question=_question_dict(question),
                current_forecast=current.__dict__ if current else None,
                forecast_history=[snapshot.__dict__ for snapshot in ledger.list_snapshots(question_id)],
                evidence=[item.__dict__ for item in ledger.list_evidence(question_id)],
                assumptions=ledger.list_assumptions(question_id),
                reference_classes=ledger.list_reference_classes(question_id),
                model_runs=ledger.list_model_runs(question_id),
                baseline_comparisons=ledger.list_baseline_comparisons(question_id),
                scores=scores,
                postmortems=postmortems,
            )

        if action == "add_evidence":
            item = ledger.add_evidence(
                question_id=_required(args, "question_id"),
                source_or_note=_required(args, "source_or_note"),
                claim=args.get("claim") or "",
                source_url=args.get("source_url"),
                source_name=args.get("source_name"),
                source_type=args.get("source_type"),
                published_at=args.get("published_at"),
                claim_type=args.get("claim_type") or "fact",
                summary=args.get("summary") or "",
                available_at=args.get("available_at"),
                reliability_rating=args.get("reliability_rating"),
                relevance_rating=args.get("relevance_rating"),
                stance=args.get("stance") or "context",
                snapshot_path=args.get("snapshot_path"),
                admissible_for_backtests=bool(args.get("admissible_for_backtests", True)),
                metadata=args.get("metadata") or {},
            )
            return tool_result(success=True, evidence=item.__dict__)

        if action == "import_source_evidence":
            question_id = _required(args, "question_id")
            adapter = _required(args, "source_type")
            source = _required(args, "source")
            imported = []
            for item in _load_source_adapter_items(adapter, source, args):
                evidence_payload = _source_adapter_evidence_payload(adapter, source, item, args)
                evidence = ledger.add_evidence(question_id=question_id, **evidence_payload)
                imported.append(
                    {
                        "evidence": evidence.__dict__,
                        "adapter_item": _adapter_item_dict(item),
                    }
                )
            return tool_result(
                success=True,
                source_type=adapter,
                source=source,
                imported_count=len(imported),
                imported=imported,
            )

        if action == "add_baseline_comparison":
            baseline = ledger.add_baseline_comparison(
                question_id=_required(args, "question_id"),
                source=_required(args, "source"),
                baseline_type=args.get("baseline_type") or "imported",
                probability_or_distribution=args.get("probability_or_distribution", args.get("probability")),
                as_of=args.get("as_of"),
                forecast_id=args.get("forecast_id"),
                backtest_case_id=args.get("backtest_case_id"),
                score_record_id=args.get("score_record_id"),
                metadata=args.get("metadata") or {},
            )
            return tool_result(success=True, baseline_comparison=baseline)

        if action == "list_baseline_comparisons":
            baselines = ledger.list_baseline_comparisons(_required(args, "question_id"))
            return tool_result(success=True, baseline_comparisons=baselines)

        if action == "add_assumption":
            assumption = ledger.add_assumption(
                question_id=_required(args, "question_id"),
                text=_required(args, "text"),
                status=args.get("status") or "active",
                check_cadence=args.get("check_cadence"),
                evidence_refs=args.get("evidence_refs") or [],
                notes=args.get("notes"),
            )
            return tool_result(success=True, assumption=assumption)

        if action == "list_assumptions":
            assumptions = ledger.list_assumptions(_required(args, "question_id"))
            return tool_result(success=True, assumptions=assumptions)

        if action == "update_assumption":
            assumption = ledger.update_assumption(
                _required(args, "assumption_id"),
                status=args.get("status"),
                last_checked_at=args.get("last_checked_at"),
                invalidated_at=args.get("invalidated_at"),
                notes=args.get("notes"),
            )
            return tool_result(success=True, assumption=assumption)

        if action == "add_reference_class":
            reference_class = ledger.add_reference_class(
                question_id=_required(args, "question_id"),
                name=_required(args, "name"),
                inclusion_criteria=_required(args, "inclusion_criteria"),
                exclusion_criteria=args.get("exclusion_criteria") or "",
                base_rate=args.get("base_rate"),
                base_rate_uncertainty=args.get("uncertainty"),
                source_refs=args.get("source_refs") or [],
                check_cadence=args.get("check_cadence"),
                notes=args.get("notes"),
            )
            model_run = ledger.record_model_run(
                question_id=_required(args, "question_id"),
                model_type="base_rate",
                inputs={
                    "reference_class_id": reference_class["id"],
                    "inclusion_criteria": reference_class["inclusion_criteria"],
                    "exclusion_criteria": reference_class["exclusion_criteria"],
                },
                output={
                    "base_rate": reference_class["base_rate"],
                    "uncertainty": reference_class["base_rate_uncertainty"],
                },
                diagnostics={"source_refs": reference_class["source_refs"]},
            )
            return tool_result(success=True, reference_class=reference_class, model_run=model_run)

        if action == "list_reference_classes":
            reference_classes = ledger.list_reference_classes(_required(args, "question_id"))
            return tool_result(success=True, reference_classes=reference_classes)

        if action == "update_reference_class":
            reference_class = ledger.update_reference_class(
                _required(args, "reference_class_id"),
                status=args.get("status"),
                last_checked_at=args.get("last_checked_at"),
                invalidated_at=args.get("invalidated_at"),
                check_cadence=args.get("check_cadence"),
                notes=args.get("notes"),
            )
            return tool_result(success=True, reference_class=reference_class)

        if action == "record_model_run":
            model_type = _required(args, "model_type")
            inputs = args.get("inputs") or {}
            parameters = args.get("parameters") or {}
            output = args.get("output") or {}
            if model_type == "trend_projection":
                series = args.get("series") or inputs.get("series")
                if series:
                    target_date = args.get("target_date") or parameters.get("target_date")
                    target_x = args.get("target_x")
                    if target_x is None:
                        target_x = parameters.get("target_x")
                    date_field = args.get("date_field") or parameters.get("date_field") or "date"
                    value_field = args.get("value_field") or parameters.get("value_field") or "value"
                    projection = linear_trend_projection(
                        series,
                        target_date=target_date,
                        target_x=target_x,
                        date_field=date_field,
                        value_field=value_field,
                    )
                    inputs.setdefault("series", series)
                    parameters.setdefault("target_date", target_date)
                    parameters.setdefault("target_x", target_x)
                    parameters.setdefault("date_field", date_field)
                    parameters.setdefault("value_field", value_field)
                    for key, value in projection.items():
                        output.setdefault(key, value)
            model_run = ledger.record_model_run(
                question_id=_required(args, "question_id"),
                model_type=model_type,
                status=args.get("model_status") or "success",
                inputs=inputs,
                parameters=parameters,
                output=output,
                diagnostics=args.get("diagnostics") or {},
                code_ref=args.get("code_ref"),
                artifact_paths=args.get("artifact_paths") or [],
                model_version=args.get("model_version"),
                prompt_version=args.get("prompt_version"),
                data_version=args.get("data_version"),
                evidence_cutoff=args.get("evidence_cutoff"),
            )
            return tool_result(success=True, model_run=model_run)

        if action == "list_model_runs":
            model_runs = ledger.list_model_runs(_required(args, "question_id"))
            return tool_result(success=True, model_runs=model_runs)

        if action == "update_forecast":
            question_id = _required(args, "question_id")
            components = args.get("components") or {}
            probability = args.get("probability")
            if probability is None and components:
                probability = weighted_binary_probability(components)
            calibration_lesson_refs = args.get("calibration_lesson_refs") or []
            calibration_adjustment = args.get("calibration_adjustment") or {}
            if args.get("use_active_lessons"):
                probability, calibration_lesson_refs, calibration_adjustment = apply_active_lesson_adjustments(
                    ledger=ledger,
                    question=ledger.get_question(question_id),
                    payload=probability,
                    calibration_lesson_refs=calibration_lesson_refs,
                    calibration_adjustment=calibration_adjustment,
                )
            snapshot = ledger.create_snapshot(
                question_id=question_id,
                probability_or_distribution=probability,
                rationale=_required(args, "rationale"),
                as_of=args.get("as_of"),
                confidence=args.get("confidence"),
                method=args.get("method"),
                ensemble_components=components,
                key_assumptions=args.get("key_assumptions") or [],
                assumption_refs=args.get("assumption_refs") or [],
                reference_class_refs=args.get("reference_class_refs") or [],
                evidence_refs=args.get("evidence_refs") or [],
                model_run_refs=args.get("model_run_refs") or [],
                forecast_origin=args.get("forecast_origin") or "live",
                agent_model=args.get("agent_model"),
                prompt_version=args.get("prompt_version"),
                forecasting_protocol_version=args.get("forecasting_protocol_version") or args.get("protocol_version"),
                toolset_version=args.get("toolset_version"),
                source_snapshot_refs=args.get("source_snapshot_refs") or [],
                evidence_cutoff=args.get("evidence_cutoff"),
                backtest_run_id=args.get("backtest_run_id"),
                calibration_eligible=bool(args.get("calibration_eligible", True)),
                calibration_weight=args.get("calibration_weight") if args.get("calibration_weight") is not None else 1.0,
                stale_evidence_days=args.get("stale_evidence_days", 30),
                acknowledge_stale_evidence=bool(args.get("ack_stale_evidence", False)),
                require_citations=bool(args.get("require_citations", False)),
                calibration_lesson_refs=calibration_lesson_refs,
                calibration_adjustment=calibration_adjustment,
                metadata=args.get("metadata") or {},
            )
            return tool_result(success=True, forecast_snapshot=snapshot.__dict__)

        if action == "resolve":
            resolution = ledger.resolve_question(
                question_id=_required(args, "question_id"),
                outcome=_required(args, "outcome"),
                resolution_source=args.get("resolution_source"),
                resolution_source_snapshot_ref=args.get("resolution_source_snapshot_ref"),
                resolver_type=args.get("resolver_type") or "manual",
                resolution_status=args.get("resolution_status") or "confirmed",
                criteria_satisfied=bool(args.get("criteria_satisfied", True)),
                confidence=args.get("confidence"),
                confirmed_by=args.get("confirmed_by"),
                resolver_notes=args.get("resolver_notes"),
                correction_ref=args.get("correction_ref"),
                trusted_policy_id=args.get("trusted_policy_id"),
                scoreable=bool(args.get("scoreable", True)),
            )
            return tool_result(success=True, resolution=resolution.__dict__)

        if action == "score":
            score = ledger.score_question(_required(args, "question_id"))
            return tool_result(success=True, score=score.__dict__)

        if action == "list_scores":
            scores = ledger.list_scores(
                domain=args.get("domain"),
                forecast_origin=args.get("forecast_origin"),
                calibration_eligible=args.get("calibration_eligible"),
                horizon=args.get("horizon"),
                bucket=args.get("bucket"),
                include_invalidated=bool(args.get("include_invalidated", False)),
            )
            return tool_result(success=True, scores=[score.__dict__ for score in scores])

        if action == "review":
            rows = ledger.review_questions(
                stale=bool(args.get("stale", False)),
                last_days=args.get("last_days") or 7,
                domain=args.get("domain"),
                topic=args.get("topic"),
                horizon=args.get("horizon"),
                confidence_below=args.get("confidence_below"),
                confidence_above=args.get("confidence_above"),
                large_delta_threshold=args.get("large_delta_threshold"),
                now=args.get("now"),
            )
            return tool_result(success=True, review=[_review_row(row) for row in rows])

        if action == "self_check":
            alerts = ledger.self_check(
                question_id=args.get("question_id"),
                domain=args.get("domain"),
                topic=args.get("topic"),
                horizon=args.get("horizon"),
                portfolio=args.get("portfolio"),
                stale_days=args.get("last_days") or 7,
                now=args.get("now"),
                confidence_below=args.get("confidence_below"),
                confidence_above=args.get("confidence_above"),
                large_delta_threshold=args.get("large_delta_threshold"),
                auto_score=bool(args.get("auto_score", False)),
                auto_postmortem=bool(args.get("auto_postmortem", False)),
            )
            return tool_result(success=True, alerts=[alert.__dict__ for alert in alerts])

        if action == "list_alerts":
            alerts = ledger.list_alerts(unresolved_only=bool(args.get("unresolved_only", True)))
            return tool_result(success=True, alerts=[alert.__dict__ for alert in alerts])

        if action == "acknowledge_alert":
            alert = ledger.acknowledge_alert(
                _required(args, "alert_id"),
                acknowledged_at=args.get("acknowledged_at"),
            )
            return tool_result(success=True, alert=alert.__dict__)

        if action == "calibration_summary":
            summary = ledger.calibration_summary(
                domain=args.get("domain"),
                forecast_origin=args.get("forecast_origin"),
                horizon=args.get("horizon"),
                calibration_eligible=args.get("calibration_eligible"),
            )
            return tool_result(success=True, calibration=summary)

        if action == "list_domain_error_profiles":
            profiles = ledger.list_domain_error_profiles(
                domain=args.get("domain"),
                topic=args.get("topic"),
            )
            return tool_result(success=True, domain_error_profiles=profiles)

        if action == "run_backtest_dataset":
            run = ledger.run_backtest_dataset(
                dataset=_required(args, "dataset"),
                cases=args.get("cases") or [],
                default_forecast_time_cutoff=args.get("default_forecast_time_cutoff"),
                evidence_cutoff_policy=args.get("evidence_cutoff_policy") or "available_at_lte_cutoff",
                allow_calibration_memory=bool(args.get("allow_calibration_memory", False)),
            )
            return tool_result(success=True, backtest_run=run)

        if action == "list_backtest_runs":
            return tool_result(success=True, backtest_runs=ledger.list_backtest_runs())

        if action == "backtest_performance_report":
            report = ledger.backtest_performance_report(_required(args, "run_id"))
            return tool_result(success=True, backtest_performance=report)

        if action == "evidence_readiness":
            rows, summaries, evidence_status, _last = _forecast_readiness_payload(ledger, args)
            return tool_result(
                success=True,
                evidence_status=evidence_status,
                backtest_summaries=summaries,
                inspected_backtest_run_ids=[row["id"] for row in rows],
            )

        if action == "doctor_report":
            rows, summaries, evidence_status, last = _forecast_readiness_payload(ledger, args)
            pilot_report = ledger.pilot_report(
                min_questions=int(args.get("min_questions", 3) or 0),
                min_structured_source_questions=int(
                    args.get("min_structured_source_questions", 1) or 0
                ),
                min_scores=int(args.get("min_scores", 1) or 0),
                min_postmortems=int(args.get("min_postmortems", 1) or 0),
                min_scheduled_reviews=int(args.get("min_scheduled_reviews", 1) or 0),
                min_scheduled_review_runs=int(args.get("min_scheduled_review_runs", 1) or 0),
            )
            pilot_ready = pilot_report["passed_checks"] == pilot_report["total_checks"]
            readiness_gaps = bool(evidence_status.get("gaps"))
            if not pilot_ready:
                doctor_status = "needs_tester_pilot_artifacts"
            elif readiness_gaps:
                doctor_status = "tester_handoff_ready_live_claim_unproven"
            else:
                doctor_status = "benchmark_evidence_ready_live_claim_unproven"

            operational_status = _forecast_operational_status(ledger, pilot_report)
            return tool_result(
                success=True,
                product=PRODUCT_NAME,
                generated_at=utc_now_iso(),
                doctor_status=doctor_status,
                tester_handoff_ready=pilot_ready,
                claim_live_superforecasting=evidence_status.get("can_claim_live_superforecasting"),
                status=operational_status,
                operational_status=operational_status,
                pilot_report=pilot_report,
                readiness={
                    "last": last,
                    "dataset_filter": args.get("dataset"),
                    "run_count": len(summaries),
                    "inspected_backtest_run_ids": [row["id"] for row in rows],
                    "evidence_status": evidence_status,
                },
                evidence_status=evidence_status,
                backtest_summaries=summaries,
                inspected_backtest_run_ids=[row["id"] for row in rows],
                required_exit_gates={
                    "pilot_ready_required": False,
                    "readiness_required": False,
                    "pilot_ready": pilot_ready,
                    "readiness_gaps": readiness_gaps,
                },
            )

        if action == "pilot_report":
            return tool_result(
                success=True,
                pilot_report=ledger.pilot_report(
                    min_questions=int(args.get("min_questions", 3) or 0),
                    min_structured_source_questions=int(
                        args.get("min_structured_source_questions", 1) or 0
                    ),
                    min_scores=int(args.get("min_scores", 1) or 0),
                    min_postmortems=int(args.get("min_postmortems", 1) or 0),
                    min_scheduled_reviews=int(args.get("min_scheduled_reviews", 1) or 0),
                    min_scheduled_review_runs=int(args.get("min_scheduled_review_runs", 1) or 0),
                ),
            )

        if action == "add_watched_source":
            watch = ledger.add_watched_source(
                scope_type=args.get("scope_type") or ("question" if args.get("question_id") else ""),
                scope_ref=args.get("scope_ref") or args.get("question_id"),
                source=_required(args, "source"),
                source_type=args.get("source_type"),
                metadata=args.get("metadata") or {},
            )
            return tool_result(success=True, watched_source=watch)

        if action == "list_watched_sources":
            watches = ledger.list_watched_sources(
                scope_type=args.get("scope_type"),
                scope_ref=args.get("scope_ref") or args.get("question_id"),
                status=None if args.get("include_inactive") else "active",
            )
            return tool_result(success=True, watched_sources=watches)

        if action == "check_watched_sources":
            alerts = ledger.check_watched_sources(
                scope_type=args.get("scope_type"),
                scope_ref=args.get("scope_ref") or args.get("question_id"),
            )
            return tool_result(success=True, alerts=[alert.__dict__ for alert in alerts])

        if action == "autopilot_readiness":
            question_id = _required(args, "question_id")
            readiness = ledger.autopilot_readiness(
                question_id,
                sources=_tool_autopilot_sources(args, required=False),
                allow_missing_resolution_source=bool(args.get("allow_missing_resolution_source", False)),
            )
            return tool_result(success=True, readiness=readiness)

        if action == "enable_autopilot":
            result = ledger.enable_autopilot(
                question_id=_required(args, "question_id"),
                sources=_tool_autopilot_sources(args, required=True) or [],
                cadence=_required(args, "cadence"),
                mode=args.get("mode") or "propose",
                materiality_policy=_tool_autopilot_materiality_policy(args),
                guardrail_policy=_tool_autopilot_guardrail_policy(args),
                notification_policy=_tool_autopilot_notification_policy(args),
                required_sources=_tool_autopilot_required_sources(args),
                next_run_at=args.get("next_run_at"),
                created_by=args.get("created_by"),
                allow_missing_resolution_source=bool(args.get("allow_missing_resolution_source", False)),
            )
            return tool_result(success=True, **_plain(result))

        if action == "disable_autopilot":
            policy = ledger.disable_autopilot(_required(args, "question_id"))
            return tool_result(success=True, autopilot_policy=policy)

        if action == "autopilot_status":
            question_id = _required(args, "question_id")
            policies = ledger.list_autopilot_policies(question_id=question_id, enabled_only=False)
            watches = ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status=None)
            runs = ledger.list_autopilot_runs(
                question_id=question_id,
                limit=int(args.get("limit") or 5),
            )
            proposals = ledger.list_forecast_update_proposals(
                question_id=question_id,
                status=None,
                limit=int(args.get("limit") or 20),
            )
            return tool_result(
                success=True,
                question_id=question_id,
                active_policy=next((row for row in policies if row.get("enabled")), None),
                autopilot_policies=policies,
                watched_sources=watches,
                autopilot_runs=runs,
                forecast_update_proposals=proposals,
                pending_proposal_count=len([row for row in proposals if row.get("status") == "pending"]),
            )

        if action == "run_autopilot":
            result = ledger.run_autopilot(
                _required(args, "question_id"),
                now=args.get("now"),
                trigger_reason=args.get("trigger_reason") or "manual",
                proposed_probability_or_distribution=_tool_proposed_probability(args),
                rationale=args.get("rationale"),
            )
            return tool_result(success=True, **_plain(result))

        if action == "list_autopilot_policies":
            policies = ledger.list_autopilot_policies(
                question_id=args.get("question_id"),
                enabled_only=not bool(args.get("include_inactive", False)),
            )
            return tool_result(success=True, autopilot_policies=policies)

        if action == "list_autopilot_runs":
            runs = ledger.list_autopilot_runs(
                question_id=args.get("question_id"),
                policy_id=args.get("policy_id"),
                limit=int(args.get("limit") or 20),
            )
            return tool_result(success=True, autopilot_runs=runs)

        if action == "list_forecast_update_proposals":
            proposal_status = args.get("proposal_status", args.get("status", "pending"))
            proposals = ledger.list_forecast_update_proposals(
                question_id=args.get("question_id"),
                status=None if args.get("include_reviewed") else proposal_status,
                limit=int(args.get("limit") or 20),
            )
            return tool_result(success=True, forecast_update_proposals=proposals)

        if action == "approve_forecast_update_proposal":
            proposal_id = _required(args, "proposal_id")
            snapshot = ledger.approve_forecast_update_proposal(
                proposal_id,
                reviewed_by=args.get("reviewed_by"),
            )
            return tool_result(
                success=True,
                forecast_snapshot=snapshot.__dict__,
                forecast_update_proposal=ledger.get_forecast_update_proposal(proposal_id),
            )

        if action == "reject_forecast_update_proposal":
            proposal = ledger.reject_forecast_update_proposal(
                _required(args, "proposal_id"),
                reviewed_by=args.get("reviewed_by"),
            )
            return tool_result(success=True, forecast_update_proposal=proposal)

        if action == "schedule_review":
            schedule = ledger.schedule_review(
                scope_type=args.get("scope_type") or _infer_schedule_scope_type(args),
                scope_ref=args.get("scope_ref") or _infer_schedule_scope_ref(args),
                cadence=_required(args, "cadence"),
                next_run_at=args.get("next_run_at"),
                trigger_reason=args.get("trigger_reason") or "scheduled",
                enabled=bool(args.get("enabled", True)),
                auto_score=bool(args.get("auto_score", False)),
                auto_postmortem=bool(args.get("auto_postmortem", False)),
                stale_days=int(args.get("stale_days") or args.get("last_days") or 7),
                confidence_below=args.get("confidence_below"),
                confidence_above=args.get("confidence_above"),
                large_delta_threshold=args.get("large_delta_threshold"),
            )
            return tool_result(success=True, scheduled_review=schedule)

        if action == "list_scheduled_reviews":
            return tool_result(success=True, scheduled_reviews=ledger.list_scheduled_reviews())

        if action == "run_scheduled_reviews":
            results = ledger.run_due_scheduled_reviews(
                now=args.get("now"),
                auto_score=bool(args.get("auto_score", False)),
                auto_postmortem=bool(args.get("auto_postmortem", False)),
            )
            return tool_result(success=True, scheduled_review_results=[_scheduled_result(row) for row in results])

        if action == "list_calibration_lessons":
            lessons = ledger.list_calibration_lessons(
                scope_type=args.get("scope_type"),
                scope_ref=args.get("scope_ref"),
                active_only=bool(args.get("active_only", False)),
            )
            return tool_result(success=True, calibration_lessons=lessons)

        if action == "update_calibration_lesson":
            lesson = ledger.update_calibration_lesson(
                _required(args, "lesson_id"),
                status=args.get("lesson_status"),
                confidence=args.get("confidence"),
            )
            return tool_result(success=True, calibration_lesson=lesson)

        if action == "postmortem":
            postmortem = ledger.create_postmortem(
                question_id=_required(args, "question_id"),
                summary=args.get("summary") or "",
                what_happened=args.get("what_happened") or "",
                what_was_expected=args.get("what_was_expected") or "",
                missed_evidence=args.get("missed_evidence") or "",
                overweighted_evidence=args.get("overweighted_evidence") or "",
                base_rate_error=args.get("base_rate_error") or "",
                inside_view_error=args.get("inside_view_error") or "",
                resolution_error=args.get("resolution_error") or "",
                lesson=args.get("lesson") or "",
                calibration_adjustment=args.get("calibration_adjustment") or {},
            )
            return tool_result(success=True, postmortem=postmortem)

        if action == "list_postmortems":
            postmortems = ledger.list_postmortems(
                question_id=args.get("question_id"),
                include_invalidated=bool(args.get("include_invalidated", False)),
            )
            return tool_result(success=True, postmortems=postmortems)

        if action == "create_correction":
            correction = ledger.create_correction(
                target_type=_required(args, "target_type"),
                target_id=_required(args, "target_id"),
                reason=_required(args, "reason"),
                created_by=args.get("created_by"),
                old_value=args.get("old_value"),
                new_value=args.get("new_value"),
                patch=args.get("patch") or {},
                status=args.get("status") or "proposed",
            )
            return tool_result(success=True, correction=correction)

        if action == "list_corrections":
            corrections = ledger.list_corrections(
                target_type=args.get("target_type"),
                target_id=args.get("target_id"),
                status=args.get("status"),
            )
            return tool_result(success=True, corrections=corrections)

        if action == "create_trusted_resolver_policy":
            policy = ledger.create_trusted_resolver_policy(
                resolver_plugin=_required(args, "resolver_plugin"),
                plugin_version=args.get("plugin_version"),
                scope_type=_required(args, "scope_type"),
                scope_ref=args.get("scope_ref"),
                enabled=bool(args.get("enabled", False)),
                approved_by=args.get("approved_by"),
                audit_log_ref=args.get("audit_log_ref"),
            )
            return tool_result(success=True, trusted_resolver_policy=policy)

        if action == "list_trusted_resolver_policies":
            policies = ledger.list_trusted_resolver_policies(
                resolver_plugin=args.get("resolver_plugin"),
                scope_type=args.get("scope_type"),
                enabled=args.get("enabled"),
            )
            return tool_result(success=True, trusted_resolver_policies=policies)

        if action == "export_question":
            fmt = args.get("format") or "json"
            exported = ledger.export_question(_required(args, "question_id"), fmt=fmt)
            if fmt == "json":
                return tool_result(success=True, format=fmt, packet=json.loads(exported))
            return tool_result(success=True, format=fmt, export=exported)

        if action == "export_all":
            fmt = args.get("format") or "json"
            exported = ledger.export_all(fmt=fmt)
            if fmt == "json":
                return tool_result(success=True, format=fmt, packet=json.loads(exported))
            return tool_result(success=True, format=fmt, export=exported)

        if action == "import_packet":
            packet = args.get("packet")
            if not isinstance(packet, dict):
                return tool_error("import_packet requires a packet object", success=False)
            summary = ledger.import_packet(packet, conflict=args.get("conflict") or "error")
            return tool_result(success=True, import_summary=summary)

        if action == "protocol":
            messages = build_protocol_messages(
                ledger,
                _required(args, "question_id"),
                stage=args.get("stage") or "update",
            )
            return tool_result(success=True, messages=[message.__dict__ for message in messages])

        return tool_error(f"unknown forecast_ledger action: {action}", success=False)
    except ForecastingError as exc:
        return tool_error(str(exc), success=False)
    except ValueError as exc:
        return tool_error(str(exc), success=False)


def _required(args: dict[str, Any], key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _tool_autopilot_sources(args: dict[str, Any], *, required: bool) -> list[str] | None:
    sources = _tool_autopilot_source_values(args.get("source"), args.get("sources"))
    for source in _tool_autopilot_required_sources(args):
        if source not in sources:
            sources.append(source)
    unique_sources = list(dict.fromkeys(sources))
    if required and not unique_sources:
        raise ValueError("sources, source, required_sources, or required_source is required")
    return unique_sources if unique_sources else None


def _tool_autopilot_required_sources(args: dict[str, Any]) -> list[str]:
    return _tool_autopilot_source_values(args.get("required_source"), args.get("required_sources"))


def _tool_autopilot_source_values(single_source: Any, raw_sources: Any) -> list[str]:
    sources: list[str] = []
    if isinstance(single_source, str) and single_source.strip():
        sources.append(single_source.strip())
    elif isinstance(single_source, list):
        sources.extend(str(item).strip() for item in single_source if str(item).strip())
    if isinstance(raw_sources, str):
        sources.extend(item.strip() for item in raw_sources.replace(";", ",").split(",") if item.strip())
    elif isinstance(raw_sources, list):
        sources.extend(str(item).strip() for item in raw_sources if str(item).strip())
    return list(dict.fromkeys(sources))


def _tool_autopilot_materiality_policy(args: dict[str, Any]) -> dict[str, Any]:
    policy = dict(args.get("materiality_policy") or {})
    if args.get("min_source_changes") is not None:
        policy["min_source_changes"] = max(int(args["min_source_changes"]), 1)
    return policy


def _tool_autopilot_guardrail_policy(args: dict[str, Any]) -> dict[str, Any]:
    policy = {
        "require_no_critical_source_failures": True,
        "require_model_parse_success": True,
        "require_evidence_refs": True,
        "require_prior_forecast": True,
        "allow_resolution_auto_commit": False,
    }
    policy.update(dict(args.get("guardrail_policy") or {}))
    if args.get("max_auto_delta") is not None:
        policy["max_single_run_probability_delta"] = args["max_auto_delta"]
    if args.get("min_sources_for_auto_commit") is not None:
        policy["min_independent_sources_for_auto_commit"] = int(args["min_sources_for_auto_commit"])
    return policy


def _tool_autopilot_notification_policy(args: dict[str, Any]) -> dict[str, Any]:
    policy = dict(args.get("notification_policy") or {})
    if args.get("notify"):
        policy["destination"] = args["notify"]
    if args.get("quiet_if_unchanged") is not None:
        policy["quiet_if_unchanged"] = bool(args["quiet_if_unchanged"])
    return policy


def _tool_proposed_probability(args: dict[str, Any]) -> Any:
    for key in (
        "proposed_probability_or_distribution",
        "probability_or_distribution",
        "proposed_probability",
        "probability",
    ):
        if key in args and args[key] is not None:
            return args[key]
    return None


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _forecast_readiness_payload(
    ledger: ForecastLedger,
    args: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], int]:
    rows = ledger.list_backtest_runs()
    dataset = args.get("dataset")
    if dataset:
        rows = [row for row in rows if str(dataset) in str(row.get("dataset", ""))]
    last = max(int(args.get("last", 20) or 0), 0)
    rows = rows[:last]
    summaries = build_backtest_performance_summaries(ledger, rows)
    evidence_status = build_forecasting_evidence_status(
        ledger,
        summaries,
        min_live_scores=max(
            int(args.get("min_live_scores", DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM) or 0),
            0,
        ),
        min_agent_protocol_cases=max(
            int(
                args.get(
                    "min_agent_protocol_cases",
                    DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM,
                )
                or 0
            ),
            0,
        ),
        min_external_source_families=max(
            int(
                args.get(
                    "min_external_source_families",
                    DEFAULT_MIN_EXTERNAL_SOURCE_FAMILIES_FOR_CLAIM,
                )
                or 0
            ),
            0,
        ),
    )
    return rows, summaries, evidence_status, last


def _forecast_operational_status(
    ledger: ForecastLedger,
    pilot_report: dict[str, Any],
) -> dict[str, Any]:
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
    schedules = ledger.list_scheduled_reviews()
    watches = ledger.list_watched_sources(status=None)
    scores = ledger.list_scores(calibration_eligible=None, include_invalidated=True)
    lessons = ledger.list_calibration_lessons()
    active_lessons = ledger.list_calibration_lessons(active_only=True)
    calibration = ledger.calibration_summary(calibration_eligible=True)
    return {
        "product": PRODUCT_NAME,
        "slug": PRODUCT_SLUG,
        "ledger_path": str(ledger.db_path),
        "question_counts": question_counts,
        "active_question_count": question_counts["active"],
        "active_assumption_count": sum(1 for row in active_assumptions if row.get("status") == "active"),
        "stale_assumption_count": sum(
            1 for row in active_assumptions if row.get("status") in {"stale", "invalidated"}
        ),
        "review_queue_count": len(ledger.review_questions(stale=True, last_days=7)),
        "open_alert_count": len(ledger.list_alerts(unresolved_only=True)),
        "scheduled_review_count": len(schedules),
        "enabled_scheduled_review_count": sum(1 for row in schedules if row.get("enabled")),
        "scheduled_review_run_count": pilot_report["summary"].get("scheduled_review_run_count", 0),
        "watched_source_count": len(watches),
        "active_watched_source_count": sum(1 for row in watches if row.get("status") == "active"),
        "score_count": len(scores),
        "calibration_eligible_score_count": calibration["count"],
        "calibration_mean_brier": calibration["mean_brier"],
        "calibration_lesson_count": len(lessons),
        "active_calibration_lesson_count": len(active_lessons),
    }


def _infer_schedule_scope_type(args: dict[str, Any]) -> str:
    if args.get("question_id"):
        return "question"
    if args.get("domain") and args.get("topic"):
        return "domain_topic"
    if args.get("domain"):
        return "domain"
    if args.get("topic"):
        return "topic"
    if args.get("portfolio"):
        return "portfolio"
    if args.get("horizon"):
        return "horizon"
    raise ValueError("schedule scope requires scope_type/scope_ref or question_id/domain/topic/portfolio/horizon")


def _infer_schedule_scope_ref(args: dict[str, Any]) -> str:
    if args.get("question_id"):
        return str(args["question_id"])
    if args.get("domain") and args.get("topic"):
        return json.dumps({"domain": args["domain"], "topic": args["topic"]}, sort_keys=True)
    if args.get("domain"):
        return str(args["domain"])
    if args.get("topic"):
        return str(args["topic"])
    if args.get("portfolio"):
        return str(args["portfolio"])
    if args.get("horizon"):
        return str(args["horizon"])
    raise ValueError("schedule scope requires scope_type/scope_ref or question_id/domain/topic/portfolio/horizon")


def _question_dict(question) -> dict[str, Any]:
    data = question.__dict__.copy()
    data["outcome_space"] = question.outcome_space.to_dict()
    return data


def _review_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": _question_dict(row["question"]),
        "current_snapshot": row["current_snapshot"].__dict__ if row["current_snapshot"] else None,
        "reasons": row["reasons"],
    }


def _scheduled_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "review": row["review"],
        "alerts": [alert.__dict__ for alert in row["alerts"]],
    }


def _load_source_adapter_items(adapter: str, source: str, args: dict[str, Any]) -> list[Any]:
    adapter_name = adapter.removeprefix("adapter:").strip().lower()
    limit = int(args.get("limit") or 10)
    since = args.get("since")
    api_base_url = args.get("api_base_url")

    if adapter_name in {"rss", "news"}:
        return load_news_feed_items(source, limit=limit, since=since)
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
    raise ValueError(f"source_type is not a supported import adapter: {adapter}")


def _source_adapter_evidence_payload(
    adapter: str,
    source: str,
    item: Any,
    args: dict[str, Any],
) -> dict[str, Any]:
    adapter_name = adapter.removeprefix("adapter:").strip().lower()
    data = _adapter_item_dict(item)
    source_url = _first_adapter_value(data, "source_url", "url", "html_url", "hn_url", "permalink", "pdf_url")
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
        or ("estimate" if adapter_name in {"fivethirtyeight", "imf", "openmeteo", "airquality"} else "fact"),
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
    for key in ("summary", "abstract", "extract", "body", "description", "selftext", "text", "content_text"):
        value = data.get(key)
        if value:
            return str(value)
    return json.dumps(
        {key: value for key, value in data.items() if key != "raw" and value not in (None, "")},
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
        value_text = ", ".join(f"{key}={value}" for key, value in values.items()) if isinstance(values, dict) else values
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
    if adapter == "sec":
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
        number = f"#{data.get('issue_number')}" if data.get("issue_number") is not None else data.get("entry_id")
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
        magnitude_label = f"M{magnitude:g}" if isinstance(magnitude, (int, float)) else "event"
        return f"USGS {data.get('event_type') or 'event'} {magnitude_label}: {data.get('place') or data.get('title')}"
    if adapter == "eonet":
        categories = data.get("categories")
        category_label = ", ".join(categories) if isinstance(categories, list) and categories else "event"
        return f"NASA EONET {category_label}: {data.get('title')}"
    if adapter == "nws":
        return f"NWS {data.get('event')}: {data.get('headline')}"
    if adapter == "clinicaltrials":
        return f"ClinicalTrials.gov {data.get('nct_id')}: {data.get('status') or 'study'} - {data.get('brief_title')}"
    if adapter == "openfda":
        brand_names = data.get("brand_names")
        brand = ", ".join(brand_names[:3]) if isinstance(brand_names, list) and brand_names else "drug application"
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
        number = f" {data.get('disaster_number')}" if data.get("disaster_number") is not None else ""
        return f"FEMA{number}{geography}{area}: {data.get('incident_type') or data.get('title')}"
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


registry.register(
    name="forecast_ledger",
    toolset="forecasting",
    schema=FORECAST_LEDGER_SCHEMA,
    handler=lambda args, **kw: forecast_ledger_tool(args),
    check_fn=check_forecasting_requirements,
    emoji="F",
)
