"""Forecast ledger tool for forecast-stage agents."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import os
from typing import Any

from forecasting import ForecastLedger, PRODUCT_NAME, PRODUCT_SLUG
from forecasting.ledger import (
    FORECAST_LINK_TYPES,
    allow_ledger_writes_decorator,
)
from forecasting.backtesting import (
    DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM,
    DEFAULT_MIN_EXTERNAL_SOURCE_FAMILIES_FOR_CLAIM,
    DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM,
    build_backtest_performance_summaries,
    build_forecasting_evidence_status,
)
from forecasting.ensembles import linear_trend_projection, weighted_binary_probability
from forecasting.hooks import SaturationBlocked, saturation_summary
from forecasting.learning import apply_active_lesson_adjustments, should_apply_active_lessons
from forecasting.marketdata import MarketDataService, SeriesRef
from forecasting.models import ForecastingError, OutcomeSpace, utc_now_iso
from forecasting.pm import PMService
from forecasting.protocol import build_protocol_messages
from forecasting.search import match_to_dict, search_forecasts
from forecasting.source_planner import SourceRecommendation, plan_sources_for_question
from forecasting.source_search import capture_watched_text_candidates, search_watched_text_sources
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
    load_manifold_market,
    load_metaculus_question,
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
    load_wikimedia_pageviews,
    load_wikipedia_pages,
    load_who_gho_observations,
    load_worldbank_observations,
    load_yahoo_finance_prices,
)
from tools.registry import registry, tool_error, tool_result


# Deterministic model families routed through the SINGLE forecasting.market_compute
# engine in the record_model_run action (M3). ``trend_projection`` keeps its own
# alias path (which itself delegates to market_compute via linear_trend_projection),
# so it is intentionally NOT listed here. Kept as literals (not imported) so the
# tool module stays cheap to import; market_compute.MODEL_TYPES is the source of truth.
_MARKET_COMPUTE_MODEL_TYPES = frozenset(
    {"ols", "multivariate", "loglinear", "timeseries_trend", "correlation", "montecarlo",
     "scenario", "cointegration", "event_study", "arima", "backtest"}
)


FORECAST_LEDGER_SCHEMA = {
    "name": "forecast_ledger",
    "description": (
        "Operate on the forecast ledger: create questions, add evidence, append "
        "forecast snapshots, resolve, score, review, self-check, and render "
        "forecast protocol context. Search actions can locate questions by title, "
        "topic, rationale, and evidence without requiring IDs. Forecast snapshots "
        "are append-only; source actions can plan and search watched RSS/Atom "
        "evidence candidates without moving probabilities; autopilot actions "
        "maintain watched-source update proposals through the ledger. The "
        "action='bayes' family runs an auditable Bayesian scratchpad "
        "(likelihood-ratio updates, log-odds pooling of disagreeing sources, "
        "evidence weighting that discounts correlated/biased signals, "
        "reference-class base-rate blending, poll→probability conversion, "
        "market de-vigging, sensitivity/tornado analysis, and forecast-diff "
        "decomposition) so probability moves are transparent rather than ad hoc."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create_question",
                    "propose_spec",
                    "commit_spec",
                    "full_forecast",
                    "set_resolution_rule",
                    "propose_resolution",
                    "propose_resolutions",
                    "list_resolution_proposals",
                    "backfill_market_ids",
                    "set_decision",
                    "configure",
                    "keep_fresh",
                    "rename_question",
                    "list_questions",
                    "search_questions",
                    "show_question",
                    "source_plan",
                    "source_search",
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
                    "build_model",
                    "update_forecast",
                    "resolve",
                    "score",
                    "list_scores",
                    "review",
                    "self_check",
                    "list_alerts",
                    "acknowledge_alert",
                    "resolve_warning",
                    "run_warning_automode",
                    "calibration_summary",
                    "list_domain_error_profiles",
                    "run_backtest_dataset",
                    "list_backtest_runs",
                    "backtest_performance_report",
                    "evidence_readiness",
                    "doctor_report",
                    "pilot_report",
                    "detect_templated_batches",
                    "forecast_complementarity",
                    "thesis_dashboard",
                    "add_watched_source",
                    "add_watched_sources",
                    "list_watched_sources",
                    "check_watched_sources",
                    "autopilot_readiness",
                    "enable_autopilot",
                    "disable_autopilot",
                    "autopilot_status",
                    "run_autopilot",
                    "refresh_forecast",
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
                    "pipeline",
                    "check_update_triggers",
                    "bayes",
                    "workflow_report",
                    "import_source_evidence_batch",
                    "record_panel",
                    "aggregate_panel",
                    "show_panel",
                    "list_panel",
                    "start_quorum",
                    "show_quorum_status",
                    "panel_perspectives",
                    "component_track_record",
                    "tail_audit",
                    "market_quality",
                    "pm_query",
                    "market_query",
                    "research_plan",
                    "research_audit",
                    "link_forecasts",
                    "list_links",
                    "unlink_forecasts",
                    "label_score",
                    "triage_label",
                    "set_label_rubric",
                    "list_label_rubrics",
                    "triage_contested",
                    "relabel_route",
                    "triage_trust",
                    "record_operator_estimate",
                    "operator_calibration",
                ],
            },
            "question_id": {"type": "string"},
            "from_question_id": {"type": "string", "description": "For link/unlink: the source forecast id."},
            "to_question_id": {"type": "string", "description": "For link/unlink: the target forecast id."},
            "link_type": {
                "type": "string",
                "enum": sorted(FORECAST_LINK_TYPES),
                "description": "related (symmetric sibling) or component_of (from=child, to=parent).",
            },
            "title": {"type": "string"},
            "actor": {"type": "string", "description": "Who is making the change (recorded in audit trails, e.g. rename_question)."},
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
                "enum": ["live", "exploratory", "backtest", "imported_baseline"],
                "description": "'live' commits a scored forecast with commit-time formalities "
                "enforced; 'exploratory' is a scratchpad forecast — exempt from those "
                "formalities and never calibration-scored.",
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
            "decision_owner": {
                "type": "string",
                "description": "Who owns the decision this forecast informs (e.g. 'ops lead').",
            },
            "decision_deadline": {
                "type": "string",
                "description": "ISO-8601 timestamp by which the decision must be made.",
            },
            "action_threshold": {
                "type": "string",
                "description": "Probability/threshold that triggers an action (e.g. 'evacuate if P > 0.05').",
            },
            "update_triggers": {
                "type": "array",
                "description": (
                    "List of mechanism/threshold triggers that should prompt a review. "
                    "Each entry is either a free-form mechanism string or an object with "
                    "mechanism, threshold, action, window, source_ref, or notes keys. A "
                    "trigger becomes EXECUTABLE (checkable via action='check_update_triggers') "
                    "when it sets operator (>, >=, <, <=, ==, !=) plus a source_ref and a "
                    "numeric threshold — then it fires automatically when the imported value "
                    "for that source crosses the threshold."
                ),
                "items": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "properties": {
                                "mechanism": {"type": "string"},
                                "threshold": {"type": ["string", "number"]},
                                "operator": {
                                    "type": "string",
                                    "enum": [">", ">=", "<", "<=", "==", "!="],
                                    "description": "Comparison that makes the trigger executable; requires a numeric threshold.",
                                },
                                "action": {"type": "string"},
                                "window": {"type": "string"},
                                "source_ref": {"type": "string"},
                                "notes": {"type": "string"},
                            },
                            "required": ["mechanism"],
                        },
                    ]
                },
            },
            "hooks": {
                "type": "object",
                "description": (
                    "For action='configure': per-forecast saturation-hook settings. "
                    "{profile?: standard|strict|exploratory-lenient, "
                    "overrides?: {<gate_id>: off|warn|error}, "
                    "thresholds?: {min_perspectives|min_reasoning_methods|max_width_ratio|"
                    "min_sharpness|null_excess_tolerance: <number>}}. lesson:* gates are NOT "
                    "settable here (they stay non-demotable). A LOOSER override is allowed but "
                    "flagged in resolve_question_config."
                ),
                "properties": {
                    "profile": {"type": "string"},
                    "overrides": {"type": "object"},
                    "thresholds": {"type": "object"},
                    "auto_aggregate": {"type": "boolean"},
                },
            },
            "reasons_up": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete reasons the probability should be HIGHER.",
            },
            "reasons_down": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete reasons the probability should be LOWER.",
            },
            "change_my_mind": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific observations that would force a material update.",
            },
            "reasoning_methods": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "The named reasoning methods you actually used, from the taxonomy "
                    "(outside_view, inside_view, base_rate, bayesian, decomposition, causality, "
                    "analogy, comparative, fermi, conditional, trend_extrapolation, mean_reversion, "
                    "extremizing, systems, game_theory, dialectics, calibration, disconfirmation, "
                    "pre_mortem, steelmanning, deductive, inductive, abductive, reductive, "
                    "question_framing). Serious forecasts compose several. The reasoning-composition "
                    "hook checks these against the active profile."
                ),
            },
            "require_structured_reasoning": {
                "type": "boolean",
                "description": (
                    "Refuse to save the snapshot unless reasons_up, reasons_down, and "
                    "change_my_mind are all populated. Defaults true for live forecasts."
                ),
            },
            "require_components": {
                "type": "boolean",
                "description": (
                    "Refuse to save a live snapshot unless ensemble_components is populated "
                    "(the pooled drivers — base rate, mechanism, market/crowd, case-specific — "
                    "each with a stable source slug). Defaults true; stops a serious forecast "
                    "collapsing into a bare number. Set false or use forecast_origin="
                    "'exploratory' for scratch work."
                ),
            },
            "require_decision_readiness": {
                "type": "boolean",
                "description": (
                    "Refuse to save the snapshot unless the question has decision_owner, "
                    "action_threshold, and at least one update_trigger."
                ),
            },
            "require_panel": {
                "type": "boolean",
                "description": (
                    "For a high-impact live forecast, refuse to save unless a deliberative "
                    "panel/quorum run is linked (panel_run_ref) or panel_skipped_reason is "
                    "recorded. Defaults true; lower-impact first forecasts are nudged "
                    "(panel_recommended), not blocked. Run a panel/quorum for serious "
                    "forecasts regardless — see the process discipline."
                ),
            },
            "preview": {
                "type": "boolean",
                "description": (
                    "update_forecast: PREVIEW FIRST. Run every gate and saturation scoring "
                    "WITHOUT writing a snapshot — the result carries the saturation score, its "
                    "advisories, and any blockers a commit would raise. See them, FIX them "
                    "(add the panel / components / structured reasoning / clean the style), "
                    "THEN commit ONCE with preview omitted. Never commit-then-remediate: do "
                    "not save a snapshot just to read its advisories and immediately re-save a "
                    "cleaned one. A preview starts NO quorum, writes NO brief, and pins the "
                    "snapshot count. Returns {preview:true, would_commit, saturation, blockers}."
                ),
            },
            "panel_run_ref": {
                "type": "string",
                "description": (
                    "ID of a panel run to link to this snapshot as the deliberative-panel "
                    "evidence for the forecast (satisfies the high-impact panel formality)."
                ),
            },
            "panel_skipped_reason": {
                "type": "string",
                "description": (
                    "Recorded reason for committing a panel-indicated forecast without a panel "
                    "(the escape valve for the panel formality). Stored on the snapshot."
                ),
            },
            "outcome_paths": {
                "type": "object",
                "description": (
                    "CATEGORICAL forecasts: a {outcome_label: path-info} map naming the causal "
                    "PATH that routes mass to each material outcome. path-info is a string (the "
                    "path) or an object {path, classification, evidence_strength: strong|mixed|weak}. "
                    "Used by the probability-mass audit (also the `tail_audit` action) to flag "
                    "UNEARNED tail mass — material outcomes (>=0.5%) with no named mechanism, the "
                    "outcome-space-anchoring failure. The audit is always recorded on the snapshot."
                ),
            },
            "require_outcome_paths": {
                "type": "boolean",
                "description": (
                    "Categorical live forecasts: refuse to save when any material outcome holds "
                    "mass with no named path (unearned tail mass). Provide outcome_paths, compress "
                    "the mass, set false, or record as exploratory. Default false."
                ),
            },
            "distribution": {
                "type": "object",
                "description": (
                    "For the `tail_audit` action: the categorical distribution to audit as "
                    "{outcome_label: probability}. (For update_forecast, pass the distribution via "
                    "probability_or_distribution instead.) The audit also returns a NULL-MODEL "
                    "comparison: your no-path tail vs a deliberately simple model that floors any "
                    "outcome without a named path — if yours is much fatter, justify it or compress."
                ),
            },
            "markets": {
                "type": "array",
                "description": (
                    "For the `market_quality` action: market readings to stratify by liquidity + "
                    "recency, each {source, volume?, updated_at? (ISO) or age_days?, probability?}. "
                    "Returns an advisory pooling weight in [0,1] per market so a thin/stale price "
                    "can't inflate a tail — multiply it into the component weight, never drop silently."
                ),
                "items": {"type": "object"},
            },
            "failure_class": {
                "type": "string",
                "enum": sorted(["base_rate", "inside_view", "definition", "timing", "aggregation", "motivated_reasoning", "tail", "noise", "other"]),
                "description": "Dominant failure mode assigned in a postmortem.",
            },
            "panel_run_id": {"type": "string"},
            "snapshot_id": {"type": "string"},
            "perspectives": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Panel perspectives to use, e.g. outside, inside, market, red_team, sanity."
                ),
            },
            "estimates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "perspective": {"type": "string"},
                        "probability": {"type": "number"},
                        "weight": {"type": "number"},
                        "confidence_low": {"type": "number"},
                        "confidence_high": {"type": "number"},
                        "rationale": {"type": "string"},
                        "reasons_up": {"type": "array", "items": {"type": "string"}},
                        "reasons_down": {"type": "array", "items": {"type": "string"}},
                        "change_my_mind": {"type": "array", "items": {"type": "string"}},
                        "crux": {"type": "string"},
                        "agent_model": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["perspective", "probability"],
                },
                "description": "Per-perspective panel estimates.",
            },
            "trim": {
                "type": "integer",
                "minimum": 0,
                "description": "Drop N highest + N lowest panel estimates before pooling.",
            },
            "method": {
                "type": "string",
                "enum": sorted(["trimmed_geomean_odds", "log_odds_pool", "median", "mean"]),
                "description": "Panel aggregation method ('mean' is the convexity baseline; default trimmed_geomean_odds).",
            },
            "triggered_by": {"type": "string"},
            "question_title": {"type": "string"},
            "context": {"type": "string"},
            "note": {"type": "string", "description": "record_operator_estimate: an optional rationale for the operator's number."},
            "name": {"type": "string"},
            "dataset": {"type": "string"},
            "limit": {"type": "integer"},
            "since": {"type": "string"},
            "limit_timeline": {"type": "integer", "description": "workflow_report: cap the chronological events list to the most recent N (default 25)."},
            "sources": {
                "type": "array",
                "description": "import_source_evidence_batch: array of per-source specs, each like {source_type, source, [limit, since, auto_watch, api_base_url, …]}. Fetched in parallel under `concurrency`.",
                "items": {"type": "object"},
            },
            "concurrency": {"type": "integer", "description": "import_source_evidence_batch: max parallel fetch workers (default 4, capped at 8)."},
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
            "forms": {
                "type": "string",
                "description": "For source_type=secsearch: comma-separated SEC form types to restrict the EDGAR full-text search (e.g. '8-K,10-Q').",
            },
            "access": {"type": "string"},
            "agent": {"type": "string"},
            "format": {"type": "string", "enum": ["json", "markdown"]},
            "packet": {"type": "object"},
            "conflict": {"type": "string", "enum": ["error", "skip", "replace"]},
            "cases": {"type": "array", "items": {"type": "object"}},
            "run_id": {"type": "string"},
            "preset": {
                "type": "string",
                "enum": ["frontier", "budget", "self", "wide"],
                "description": "start_quorum: model panel preset.",
            },
            "models": {
                "type": "array",
                "items": {"type": "string"},
                "description": "start_quorum: explicit provider/model panelist ids (overrides the preset).",
            },
            "judge": {"type": "string", "description": "start_quorum: provider/model id for the judge synthesis pass."},
            "pool_method": {
                "type": "string",
                "enum": sorted(["trimmed_geomean_odds", "log_odds_pool", "median", "mean"]),
                "description": "start_quorum: panel aggregation method (default trimmed_geomean_odds).",
            },
            "delphi_rounds": {
                "type": "integer",
                "enum": [0, 1],
                "description": "start_quorum: 0 (default) runs the standard sealed quorum; 1 adds one anonymous Delphi revision round.",
            },
            "supervisor_search": {
                "type": "boolean",
                "description": "start_quorum: opt into the live fresh-search supervisor loop (fails closed for historical cutoffs).",
            },
            "wait": {
                "type": "boolean",
                "description": "start_quorum: run inline to completion and return the finished job (default false = detached).",
            },
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
            "sample_size": {"type": "integer", "description": "n observations behind the base rate (how strong the outside view is)."},
            "source_refs": {"type": "array", "items": {"type": "string"}},
            "model_type": {"type": "string"},
            "model_status": {"type": "string", "enum": ["success", "failure"]},
            "inputs": {"type": "object"},
            "parameters": {"type": "object"},
            "output": {"type": "object"},
            "diagnostics": {"type": "object"},
            "series": {"type": "array", "items": {}},
            "market_series": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "market_query: explicit series refs to read, each "
                    "{provider, symbol, name?, category?, unit?, line?} "
                    "(e.g. {'provider':'frankfurter','symbol':'EUR'} or "
                    "{'provider':'bea','symbol':'T20305','line':'1'})."
                ),
            },
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "market_query shorthand: symbols paired with `provider`/`providers`.",
            },
            "providers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "market_query shorthand: one provider applies to all `symbols`, else zipped.",
            },
            "target_date": {"type": "string"},
            "target_x": {"type": "number"},
            "date_field": {"type": "string"},
            "value_field": {"type": "string"},
            "payload": {
                "type": "object",
                "description": (
                    "record_model_run: the market_compute payload for a deterministic family "
                    "(ols/loglinear/timeseries_trend/montecarlo/correlation/arima/...) — e.g. "
                    "{\"x\":[...],\"y\":[...]} for ols, {\"values\":[...],\"horizon\":6} for timeseries_trend. "
                    "Its summary + block are merged into the model_run output via the single market_compute engine."
                ),
            },
            "market_model_id": {"type": "string", "description": "Link a model_run (or build_model result) to a Market Model."},
            "params": {
                "type": "object",
                "description": "build_model: Market Model build params (depth, analysis_type, tickers, horizon, target_year, assumptions).",
            },
            "analysis_type": {"type": "string", "description": "build_model: preferred model family (overrides the recommender)."},
            "depth": {"type": "string", "description": "build_model: research depth (quick|standard|deep|ultra)."},
            "question": {"type": "string", "description": "build_model: the quant question text (defaults to the linked question's title/description when question_id is given)."},
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
            "components": {
                "type": "object",
                "description": (
                    "update_forecast: the structured ensemble you pooled, as "
                    "{\"components\":[{name, probability, weight, source}]}. PERSIST THIS on any "
                    "snapshot that combines sources — do not leave the pool in prose or a model_run. "
                    "Give each market/crowd component a stable `source` slug (e.g. "
                    "'polymarket:<slug>') so `forecast refresh` can match and re-pool it next run."
                ),
            },
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
            "watches": {
                "type": "array",
                "description": (
                    "For add_watched_sources (BULK): one entry per watch — "
                    "{question_id (or scope_type+scope_ref), source, source_type?, "
                    "role?, label?}. ONE call covers a whole thesis (e.g. 35 races "
                    "x 7 sources); prefer this over scripting loops."
                ),
                "items": {"type": "object"},
                "maxItems": 400,
            },
            "query": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string"}},
            "required_source": {"type": "string"},
            "required_sources": {"type": "array", "items": {"type": "string"}},
            "source_url": {"type": "string"},
            "source_name": {"type": "string"},
            "apply_watch": {"type": "boolean"},
            "accept_defaults": {
                "type": "boolean",
                "description": (
                    "propose_spec/commit_spec: auto-apply the recommended default of every "
                    "gap/error clarification and commit in one shot (for a vague/casual ask). "
                    "Only error-severity issues still surface and block; the applied choices "
                    "come back as `applied_defaults` to echo in a one-line summary."
                ),
            },
            "allow_duplicate": {
                "type": "boolean",
                "description": (
                    "full_forecast: by default a strong near-duplicate routes the stage chain "
                    "onto the EXISTING question (routed_to_existing=true) instead of forking a "
                    "rival. Set true to force a NEW question anyway (the duplicate warning is "
                    "surfaced either way)."
                ),
            },
            "prompt": {
                "type": "string",
                "description": (
                    "propose_spec/full_forecast: the user's plain-language question. "
                    "full_forecast turns this one sentence into a committed forecast — it "
                    "structures + commits the question (accept-defaults) then autonomously "
                    "chains research -> base_rate -> update through the gated pipeline."
                ),
            },
            "spec": {
                "type": "object",
                "description": "propose_spec/commit_spec/full_forecast: an explicit QuestionSpec draft (overrides `prompt` when both are given).",
            },
            "provider": {
                "type": "string",
                "description": "full_forecast: provider the chained pipeline stages run on (default: house model).",
            },
            "max_iterations": {
                "type": "integer",
                "description": "full_forecast: agent tool-calling budget per chained stage (default 12).",
            },
            "keywords": {"type": "array", "items": {"type": "string"}},
            "exclude_keywords": {"type": "array", "items": {"type": "string"}},
            "dedupe": {"type": "boolean"},
            "capture_candidates": {"type": "boolean"},
            "materiality": {"type": "string", "enum": ["low", "medium", "high"]},
            "direction": {"type": "string", "enum": ["upward", "downward", "ambiguous"]},
            "affected_components": {"type": "array", "items": {"type": "string"}},
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
                    "secsearch",
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
            "reference_class": {
                "type": "object",
                "description": "Inline outside-view anchor: create + link a reference class to THIS forecast in one call (alternative to a separate add_reference_class). Reuses an existing same-name class on the question if present.",
                "required": ["name", "inclusion_criteria"],
                "properties": {
                    "name": {"type": "string"},
                    "inclusion_criteria": {"type": "string"},
                    "exclusion_criteria": {"type": "string"},
                    "base_rate": {"type": "number"},
                    "uncertainty": {"type": "number"},
                    "sample_size": {"type": "integer"},
                    "source_refs": {"type": "array", "items": {"type": "string"}},
                },
            },
            "source_snapshot_refs": {"type": "array", "items": {"type": "string"}},
            "calibration_lesson_refs": {"type": "array", "items": {"type": "string"}},
            "calibration_adjustment": {"type": "object"},
            "calibration_weight": {"type": "number"},
            "use_active_lessons": {"type": "boolean", "description": "update_forecast: apply the ledger's measured calibration-bias correction (active in-scope lessons) to the committed probability. DEFAULT TRUE for LIVE commits only — the learned correction lands automatically and the pre-adjustment raw_probability is recorded for audit. backtest/imported_baseline are NEVER auto-adjusted (the correction is live-derived and would contaminate the closed-book benchmark); pass true to opt in explicitly. Pass false to opt out (commit your raw number). Exploratory commits are never adjusted."},
            "alert_id": {"type": "string"},
            "acknowledged_at": {"type": "string"},
            "ref": {"type": "string", "description": "resolve_warning: an al_* alert id (resolve that one) or a scope/question ref (resolve every open alert for it)."},
            "scope": {"type": "string", "description": "run_warning_automode: restrict the sweep to a single question/scope ref."},
            "tier": {"type": "string", "enum": ["free", "reforecast"], "description": "run_warning_automode: per-tier bulk pass. 'free' = non-LLM kinds {bookkeeping,score,postmortem,material_change}; 'reforecast' = the opt-in LLM reforecast/evidence tier."},
            "kinds": {"type": "array", "items": {"type": "string"}, "description": "run_warning_automode: restrict to these ResolutionKinds (e.g. ['score','postmortem']); UNIONed with tier when both are given."},
            "proposal_id": {"type": "string"},
            "proposal_status": {
                "type": "string",
                "enum": ["pending", "approved", "rejected", "expired", "auto_committed"],
            },
            "reviewed_by": {"type": "string"},
            "include_reviewed": {"type": "boolean"},
            "stale_evidence_days": {"type": "integer"},
            "ack_stale_evidence": {"type": "boolean"},
            "stale_evidence_reason": {"type": "string", "description": "If ack_stale_evidence is set, WHY nothing material changed since the prior forecast. Recorded + clears the stale_evidence_justified WARN; otherwise the bypass is flagged."},
            "window_days": {"type": "integer", "description": "detect_templated_batches: look-back window (default 7)."},
            "min_cluster": {"type": "integer", "description": "detect_templated_batches: min forecasts sharing a template to flag a cluster (default 3)."},
            "run_safe_benchmarks": {"type": "boolean", "description": "evidence_readiness: first run the OFFLINE builtin benchmark suite (no network / no paid LLM) to advance readiness, then evaluate."},
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
            "field": {
                "type": "string",
                "description": "For set_resolution_rule: the parsed source value to read (e.g. 'yoy_percent').",
            },
            "comparator": {
                "type": "string",
                "enum": [">=", ">", "<=", "<", "==", "!="],
                "description": "For set_resolution_rule: how the observed value is compared to threshold.",
            },
            "threshold": {
                "type": "number",
                "description": "For set_resolution_rule: the numeric threshold the observed value is compared against.",
            },
            "source_role": {
                "type": "string",
                "description": "For set_resolution_rule: which watched-source role supplies the value (default 'resolver').",
            },
            "resolver": {
                "type": "string",
                "description": "For set_resolution_rule: the resolver engine (default 'metric_threshold').",
            },
            "correction_ref": {"type": "string"},
            "trusted_policy_id": {"type": "string"},
            "scoreable": {"type": "boolean"},
            "auto_score": {
                "type": "boolean",
                "description": "On a confirmed, criteria-satisfied resolution, automatically score the current live snapshot (Brier/log score). Defaults true; set false to resolve without scoring yet.",
            },
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
            "re_estimate": {
                "type": "string",
                "enum": ["deterministic", "carry_forward"],
                "description": "refresh_forecast: 'deterministic' re-pools the prior components after refreshing market/crowd readings; 'carry_forward' keeps the prior probability and flags that agent re-reasoning is needed.",
            },
            "extremize": {"type": "number", "description": "refresh_forecast: extremization factor applied during the deterministic re-pool (default 1.0)."},
            "correlation": {"type": "string", "description": "refresh_forecast: pass 'estimate' to correlation-adjust pooling weights when sources overlap."},
            "dry_run": {"type": "boolean", "description": "refresh_forecast: preview the re-estimate without importing evidence or committing a snapshot."},
            "commit": {"type": "boolean", "description": "refresh_forecast: write the re-estimate as a new live snapshot (default true)."},
            "materiality_policy": {"type": "object"},
            "guardrail_policy": {"type": "object"},
            "notification_policy": {"type": "object"},
            "min_source_changes": {"type": "integer"},
            "max_auto_delta": {"type": "number"},
            "min_sources_for_auto_commit": {"type": "integer"},
            "notify": {"type": "string"},
            "quiet_if_unchanged": {"type": "boolean"},
            "auto_watch": {
                "type": "boolean",
                "description": "For import_source_evidence: after a successful import, also attach the (source_type, source) tuple as a watched source on the question so future reruns start from the known identifier instead of broad search. Deduped — a no-op if an identical watch already exists.",
            },
            "dedupe": {
                "type": "boolean",
                "description": "For import_source_evidence / import_source_evidence_batch: skip a reading already imported for this question (same source_type + adapter entry_id), so repeated refreshes don't pile up duplicate observations. Default true; the response reports skipped_duplicates. Free-form notes (no entry_id) are never deduped.",
            },
            "allow_missing_resolution_source": {"type": "boolean"},
            "enabled": {"type": "boolean"},
            "now": {"type": "string"},
            "observations": {
                "type": "object",
                "description": (
                    "For action='check_update_triggers': map of source_ref -> latest numeric "
                    "value to evaluate executable update_triggers against. Omitted values are "
                    "derived from the question's imported evidence."
                ),
                "additionalProperties": {"type": "number"},
            },
            "include_inactive": {"type": "boolean"},
            "include_invalidated": {"type": "boolean"},
            "unresolved_only": {"type": "boolean"},
            "active_only": {"type": "boolean"},
            "stage": {
                "type": "string",
                "enum": ["parse", "research", "base_rate", "model", "update", "resolve", "postmortem", "self_check"],
            },
            "force": {
                "type": "boolean",
                "description": (
                    "For action='pipeline' with a stage: bypass the sequencing gate that "
                    "refuses advancing to 'update' before research+base_rate produced refs."
                ),
            },
            "lesson": {"type": "string"},
            "db": {"type": "string"},
            "view": {
                "type": "string",
                "enum": ["full", "summary"],
                "description": "show_question preset: 'summary' returns just question essentials + current forecast + counts (no arrays); 'full' (default) returns everything.",
            },
            "last_evidence": {"type": "integer", "description": "show_question: cap evidence to the most recent N items."},
            "last_history": {"type": "integer", "description": "show_question: cap forecast_history to the most recent N snapshots."},
            "last_model_runs": {"type": "integer", "description": "show_question: cap model_runs to the most recent N items."},
            "include_history": {"type": "boolean", "description": "show_question: include the forecast_history array (default true)."},
            "include_evidence": {"type": "boolean", "description": "show_question: include the evidence array (default true)."},
            "include_model_runs": {"type": "boolean", "description": "show_question: include the model_runs array (default true)."},
            "include_assumptions": {"type": "boolean", "description": "show_question: include the assumptions array (default true)."},
            "include_reference_classes": {"type": "boolean", "description": "show_question: include the reference_classes array (default true)."},
            "include_baselines": {"type": "boolean", "description": "show_question: include the baseline_comparisons array (default true)."},
            "include_scores": {"type": "boolean", "description": "show_question: include the scores array (default true)."},
            "include_postmortems": {"type": "boolean", "description": "show_question: include the postmortems array (default true)."},
            "bayes_action": {
                "type": "string",
                "description": (
                    "For action='bayes': which Bayesian toolkit routine to run — "
                    "lr_update, decompose_update, combine, evidence_weight, "
                    "evidence_cluster, blend_base_rates, poll_to_prob, polls, "
                    "devig, normalize_market, combine_markets, sensitivity, forecast_diff."
                ),
            },
            "bayes_payload": {
                "type": "object",
                "description": (
                    "For action='bayes': the inputs for the chosen bayes_action "
                    "(e.g. {prior_p, lrs} for lr_update; {components, method, "
                    "extremize, correlation_matrix} for combine; {previous, current, "
                    "components} for forecast_diff)."
                ),
            },
            "predictions": {
                "type": "array",
                "description": "label_score: predicted labels as [{id, label}, ...] (the auto-labeler's output).",
                "items": {"type": "object"},
            },
            "gold": {
                "type": "array",
                "description": "label_score: gold labels as [{id, label}, ...] (the expert/ground-truth labels).",
                "items": {"type": "object"},
            },
            "task_type": {
                "type": "string",
                "enum": ["relevance", "truncation"],
                "description": "label_score: 'relevance' (multi-class classification, headline=accuracy) or 'truncation' (cut-point extraction, headline=exact-match).",
            },
            "positive_class": {
                "type": "string",
                "description": "label_score: optional class to treat as positive for a binary confusion matrix + positive-class F1 (e.g. 'relevant_interesting').",
            },
            "cost": {
                "type": "number",
                "description": "label_score: optional total inference cost for the scored batch; reported as cost_per_task.",
            },
            "candidates": {
                "type": "array",
                "description": "triage_label: candidate readings to classify as [{title, summary?, source_type?, source?, url?, id?}, ...] (pre-ingest, before they become evidence).",
                "items": {"type": "object"},
            },
            "use_watched": {
                "type": "boolean",
                "description": "triage_label: instead of `candidates`, pull candidate readings from the question's watched sources (requires question_id).",
            },
            "rubric": {
                "type": "object",
                "description": "set_label_rubric: the desk taste {interesting_criteria (required), uninteresting_criteria?, irrelevant_criteria?, examples?:[{title,label,why}], notes?}.",
            },
            "rubric_ref": {
                "type": "string",
                "description": "triage_label: explicit triage rubric id to apply (else the most-specific active rubric for the question, else the default macro-desk rubric).",
            },
            "model": {
                "type": "string",
                "description": "triage_label: model id for the cheap auto-labeler (default $FORECAST_TRIAGE_MODEL or the house judge model). research_audit: optional model for the advisory change_my_mind-coverage check (omit for deterministic-only).",
            },
            "persist": {
                "type": "boolean",
                "description": "triage_label: persist the verdicts as triage_labels staging rows (label_source='auto'). Default true.",
            },
            "label_ids": {
                "type": "array",
                "description": "triage_contested: specific triage_label row ids to check (else all auto-labeled, un-adjudicated rows for question_id).",
                "items": {"type": "string"},
            },
            "verifier_labels": {
                "type": "array",
                "description": "triage_contested: optional second-opinion labels [{candidate_ref|id, label}]; an item is CONTESTED where the verifier disagrees with the auto-label (the L8 trick). Without it, the labeler's own boundary/conflict cases are flagged.",
                "items": {"type": "object"},
            },
            "disagreement_threshold": {
                "type": "number",
                "description": "triage_contested: relevance band around 0.5 within which an auto-label is treated as boundary/uncertain and flagged for review (default 0.15; used only when no verifier_labels).",
            },
            "adjudications": {
                "type": "array",
                "description": "relabel_route: operator expert labels [{label_id, label}] for contested items.",
                "items": {"type": "object"},
            },
            "label_id": {
                "type": "string",
                "description": "relabel_route: single triage_label id to adjudicate (with `label`).",
            },
            "label": {
                "type": "string",
                "description": "relabel_route: the operator's expert three-way label (relevant_interesting|relevant_uninteresting|irrelevant).",
            },
            "min_sample": {
                "type": "integer",
                "description": "triage_trust: minimum adjudicated labels before the labeler can be trusted to auto-filter (default 20 / $FORECAST_TRIAGE_TRUST_MIN_SAMPLE).",
            },
            "pm_mode": {
                "type": "string",
                "enum": ["search", "event", "book", "history"],
                "description": (
                    "pm_query: which read to run. 'search' → list live events + de-vigged "
                    "distributions across Polymarket+Kalshi (market priors); 'event' → one "
                    "event's full outcome distribution (categorical buckets, de-vigged to sum "
                    "to ~1); 'book' → an outcome market's YES order book (bid/ask depth as a "
                    "liquidity signal); 'history' → the price-probability time series."
                ),
            },
            "venue": {
                "type": "string",
                "enum": ["polymarket", "kalshi"],
                "description": "pm_query: which prediction-market venue. Omit on mode='search' to query both.",
            },
            "event_id": {
                "type": "string",
                "description": "pm_query mode='event': the venue event id (Polymarket Gamma event id or Kalshi event ticker).",
            },
            "market_id": {
                "type": "string",
                "description": "pm_query mode='book'|'history': the outcome-market id (Polymarket clobTokenId or Kalshi market ticker).",
            },
            "range": {
                "type": "string",
                "description": "pm_query mode='history': lookback window (e.g. '1d', '1w', '1m'). Default '1w'.",
            },
            "series_ticker": {
                "type": "string",
                "description": "pm_query mode='history' on Kalshi: the parent series ticker (required by Kalshi's candlesticks endpoint).",
            },
            "tag": {
                "type": "string",
                "description": "pm_query mode='search': optional Polymarket tag/category filter.",
            },
        },
        "required": ["action"],
    },
}


def check_forecasting_requirements() -> bool:
    return True


# Duplicate-detection thresholds over the search ranker's integer scores. The floor
# keeps a single trivial token hit from surfacing as a "duplicate"; the higher warn
# threshold is roughly a title-substring-level match (the ranker gives title weight
# 18, ×3 for substring containment) and only nudges — it never blocks a commit.
_DUPLICATE_SCORE_FLOOR = 18
_DUPLICATE_WARN_SCORE = 54


def _find_possible_duplicates(ledger: Any, title: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Rank existing active questions against a draft title and return the top few
    above a sane score floor. Pure reuse of the forecast search ranker — no new
    subsystem. Empty when the title is blank/trivial or nothing scores."""
    title = (title or "").strip()
    if not title:
        return []
    matches = search_forecasts(ledger, title, status="active", limit=limit)
    out: list[dict[str, Any]] = []
    for match in matches:
        if match.score < _DUPLICATE_SCORE_FLOOR:
            continue
        out.append({
            "id": match.question.id,
            "title": match.question.title,
            "score": match.score,
            "status": match.question.status,
        })
    return out


# One process-wide PMService so its TTL caches persist across pm_query calls
# within a session. Injectable for tests via set_pm_service().
_PM_SERVICE_HOLDER: dict[str, Any] = {"svc": None}


def _pm_service() -> PMService:
    if _PM_SERVICE_HOLDER["svc"] is None:
        _PM_SERVICE_HOLDER["svc"] = PMService()
    return _PM_SERVICE_HOLDER["svc"]


def set_pm_service(service) -> None:
    """Test seam: inject a stub PMService for pm_query without touching network."""
    _PM_SERVICE_HOLDER["svc"] = service


_MARKET_DATA_HOLDER: dict[str, Any] = {"svc": None}


def _market_data_service() -> MarketDataService:
    if _MARKET_DATA_HOLDER["svc"] is None:
        _MARKET_DATA_HOLDER["svc"] = MarketDataService()
    return _MARKET_DATA_HOLDER["svc"]


def set_market_data_service(service) -> None:
    """Test seam: inject a stub MarketDataService for market_query (no network)."""
    _MARKET_DATA_HOLDER["svc"] = service


def _market_query_refs(args: dict[str, Any]) -> list[SeriesRef]:
    """Build the requested :class:`SeriesRef` list from ``series`` (full refs)
    or ``symbols`` + ``provider(s)`` (a shorthand: one provider → all symbols,
    else zipped)."""

    raw = args.get("market_series") or args.get("series")
    refs: list[SeriesRef] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                try:
                    refs.append(SeriesRef.from_dict(item))
                except ValueError:
                    continue
    if refs:
        return refs

    symbols = args.get("symbols")
    symbols = [str(s) for s in symbols] if isinstance(symbols, list) else []
    provs = args.get("providers")
    provs = [str(p) for p in provs] if isinstance(provs, list) else []
    single = args.get("provider")
    if single and not provs:
        provs = [str(single)]
    if not symbols or not provs:
        return []
    if len(provs) == 1:
        return [SeriesRef(provider=provs[0], symbol=sym, name=sym) for sym in symbols]
    return [SeriesRef(provider=p, symbol=sym, name=sym) for p, sym in zip(provs, symbols)]


@allow_ledger_writes_decorator("forecast_ledger_tool")
def forecast_ledger_tool(args: dict[str, Any]) -> str:
    # This IS the gated commit flow: every forecast-producing action here runs
    # through create_snapshot / create_question / record_panel_run, which apply
    # the calibration / panel / evidence gates. Opening the write context for the
    # whole dispatch is what lets those gated writes through; an ad-hoc script
    # that imports ForecastLedger and calls them directly stays refused.
    ledger = ForecastLedger(args.get("db"))
    action = args.get("action")
    # Lazy import breaks the facade<->action-module import cycle: the
    # tools.forecast_actions submodules import helpers from THIS module, so
    # they can only load after it is fully initialised -- guaranteed here at
    # first call.  ACTIONS maps every action name to handler(args, ledger).
    from tools.forecast_actions import ACTIONS
    try:
        handler = ACTIONS.get(action)
        if handler is not None:
            return handler(args, ledger)
        return tool_error(f"unknown forecast_ledger action: {action}", success=False)
    except SaturationBlocked as blocked:
        # A commit was refused by the forecast hooks. Instead of a bare error,
        # hand the agent a precise, machine-checked to-do list so it self-remediates
        # (collect evidence / run a panel / decompose / compress tails / rewrite
        # prose) WITHOUT the user re-prompting, then re-calls update_forecast.
        rep = blocked.report
        failing = [
            {
                "rule_id": v.rule_id,
                "message": v.message,
                "remediation": (v.remediation.action if v.remediation else "none"),
                "directive": (v.remediation.directive if v.remediation else ""),
                "stage": (v.remediation.target_stage if v.remediation else None),
            }
            for v in rep.blocking_failures()
        ]
        return tool_result(
            success=False,
            error=str(blocked),
            saturation_block={
                "blocked": True,
                "failing_rules": failing,
                "next_actions": [r.action for r in rep.remediations()],
                "guidance": (
                    "This forecast is under-saturated. You own saturating it: perform the "
                    "remediation(s) above (collect fresh evidence, run the decomposition panel, "
                    "decompose into components, name a path for tail mass, or rewrite the prose "
                    "in house style), then call update_forecast again. Do not ask the user."
                ),
            },
        )
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


def _tool_filter_terms(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    terms: list[str] = []
    for item in values:
        for chunk in str(item).split(","):
            term = chunk.strip()
            if term and term not in terms:
                terms.append(term)
    return terms


def _tool_news_triage_metadata(args: dict[str, Any]) -> dict[str, Any]:
    keywords = _tool_filter_terms(args.get("keywords"))
    exclude_keywords = _tool_filter_terms(args.get("exclude_keywords"))
    affected_components = _tool_filter_terms(args.get("affected_components"))
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


def _tool_watch_metadata(args: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(args.get("metadata") or {})
    if args.get("source_name"):
        metadata["source_name"] = args["source_name"]
    if args.get("cadence"):
        metadata["cadence"] = args["cadence"]
    keywords = _tool_filter_terms(args.get("keywords"))
    exclude_keywords = _tool_filter_terms(args.get("exclude_keywords"))
    affected_components = _tool_filter_terms(args.get("affected_components"))
    if keywords or exclude_keywords:
        metadata["relevance_filters"] = {
            "keywords": keywords,
            "exclude_keywords": exclude_keywords,
        }
    if keywords or exclude_keywords or args.get("materiality") or args.get("direction"):
        metadata["news_triage"] = {
            "state": "candidate_evidence",
            "materiality": args.get("materiality") or "medium",
            "direction": args.get("direction") or "ambiguous",
            "affected_components": affected_components,
            "no_silent_probability_mutation": True,
        }
    return metadata


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


def _safe_templated_batches(ledger: ForecastLedger) -> list[dict[str, Any]]:
    """detect_templated_batches() is a heuristic, read-only flag — it must never take
    down a report. Swallow any error and return no clusters."""
    try:
        return ledger.detect_templated_batches()
    except Exception:
        return []


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


def _show_question_payload(ledger: "ForecastLedger", args: dict[str, Any]) -> str:
    """Build the show_question response with compact / capped views.

    Controls (all optional, default to the full historic payload):

    - ``view`` = "summary" → return question essentials + current forecast +
      counts of every related collection (no arrays). Cuts the response by
      orders of magnitude when the agent only wants to verify state.
    - ``last_evidence`` / ``last_history`` / ``last_model_runs`` (ints) → cap
      the corresponding list to its most recent N items.
    - ``include_history`` / ``include_evidence`` / ``include_model_runs`` /
      ``include_assumptions`` / ``include_reference_classes`` /
      ``include_baselines`` / ``include_scores`` / ``include_postmortems``
      (booleans) → drop those collections entirely.
    """

    def _flag(name: str, default: bool = True) -> bool:
        value = args.get(name)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}

    def _cap(name: str) -> int | None:
        value = args.get(name)
        if value is None:
            return None
        try:
            limit = int(value)
        except (TypeError, ValueError):
            return None
        return max(limit, 0) if limit >= 0 else None

    question_id = _required(args, "question_id")
    question = ledger.get_question(question_id)
    current = ledger.get_current_snapshot(question_id)
    view = str(args.get("view") or "full").strip().lower()

    history = ledger.list_snapshots(question_id)
    evidence = ledger.list_evidence(question_id)
    assumptions = ledger.list_assumptions(question_id)
    reference_classes = ledger.list_reference_classes(question_id)
    model_runs = ledger.list_model_runs(question_id)
    baselines = ledger.list_baseline_comparisons(question_id)
    postmortems = ledger.list_postmortems(question_id, include_invalidated=True)
    scores = [s.__dict__ for s in ledger.list_scores(include_invalidated=True) if s.question_id == question_id]

    counts = {
        "history": len(history),
        "evidence": len(evidence),
        "assumptions": len(assumptions),
        "reference_classes": len(reference_classes),
        "model_runs": len(model_runs),
        "baseline_comparisons": len(baselines),
        "scores": len(scores),
        "postmortems": len(postmortems),
    }

    if view == "summary":
        return tool_result(
            success=True,
            view="summary",
            question=_question_dict(question),
            current_forecast=current.__dict__ if current else None,
            counts=counts,
        )

    last_evidence = _cap("last_evidence")
    last_history = _cap("last_history")
    last_model_runs = _cap("last_model_runs")

    payload: dict[str, Any] = {
        "question": _question_dict(question),
        "current_forecast": current.__dict__ if current else None,
        "counts": counts,
    }
    if _flag("include_history"):
        rows = [s.__dict__ for s in history]
        payload["forecast_history"] = rows[-last_history:] if last_history is not None else rows
    if _flag("include_evidence"):
        rows = [e.__dict__ for e in evidence]
        payload["evidence"] = rows[-last_evidence:] if last_evidence is not None else rows
    if _flag("include_assumptions"):
        payload["assumptions"] = assumptions
    if _flag("include_reference_classes"):
        payload["reference_classes"] = reference_classes
    if _flag("include_model_runs"):
        rows = model_runs
        payload["model_runs"] = rows[-last_model_runs:] if last_model_runs is not None else rows
    if _flag("include_baselines"):
        payload["baseline_comparisons"] = baselines
    if _flag("include_scores"):
        payload["scores"] = scores
    if _flag("include_postmortems"):
        payload["postmortems"] = postmortems

    return tool_result(success=True, **payload)


def _import_source_evidence_batch_payload(ledger: "ForecastLedger", args: dict[str, Any]) -> str:
    """Parallel-fetch + sequential-write batch importer.

    Fetches every entry in ``sources`` concurrently (the slow, network-bound
    part) under a bounded ``concurrency`` cap, then writes evidence rows to the
    ledger sequentially in the main thread to keep SQLite single-writer.
    Per-source failures are captured in ``results`` without aborting the batch
    — exactly the lever the agent was missing when one slow FRED endpoint
    stalled a whole sequential terminal loop.
    """

    import time
    from concurrent.futures import ThreadPoolExecutor

    question_id = _required(args, "question_id")
    sources = args.get("sources")
    if not isinstance(sources, list) or not sources:
        return tool_error("import_source_evidence_batch requires `sources`: a non-empty array", success=False)
    try:
        concurrency = max(1, min(8, int(args.get("concurrency", 4))))
    except (TypeError, ValueError):
        concurrency = 4

    # Per-source args inherit batch-level defaults the agent set once.
    inherited_keys = ("limit", "since", "api_base_url", "claim", "summary", "stance", "claim_type",
                      "source_name", "reliability_rating", "relevance_rating", "auto_watch")
    inherited = {k: args[k] for k in inherited_keys if k in args}

    def _fetch_one(index: int, spec: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(spec, dict):
            return {"index": index, "success": False, "error": "each source spec must be an object"}
        merged: dict[str, Any] = {**inherited, **spec}
        source_type = str(merged.get("source_type") or "").strip()
        source = str(merged.get("source") or "").strip()
        if not source_type or not source:
            return {"index": index, "success": False, "error": "source_type and source are required",
                    "source_type": source_type or None, "source": source or None}
        started = time.time()
        try:
            items = _load_source_adapter_items(source_type, source, merged)
            payloads = [_source_adapter_evidence_payload(source_type, source, item, merged) for item in items]
            return {
                "index": index, "success": True, "source_type": source_type, "source": source,
                "items": items, "payloads": payloads, "merged_args": merged,
                "elapsed_s": round(time.time() - started, 3),
            }
        except Exception as exc:
            return {
                "index": index, "success": False, "source_type": source_type, "source": source,
                "error": str(exc), "elapsed_s": round(time.time() - started, 3),
            }

    # Bounded-parallel fetch.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        fetched = list(pool.map(lambda pair: _fetch_one(*pair), enumerate(sources)))

    # Sequential ledger writes (keeps SQLite single-writer; cheap once the
    # network fetches are done).
    dedupe = bool(args.get("dedupe", True))
    seen_keys = ledger.existing_evidence_keys(question_id) if dedupe else set()
    results: list[dict[str, Any]] = []
    total_imported = 0
    total_skipped = 0
    for fetch in fetched:
        if not fetch.get("success"):
            results.append({k: fetch[k] for k in ("index", "source_type", "source", "error", "elapsed_s") if k in fetch} | {"success": False, "imported_count": 0})
            continue
        evidence_rows: list[dict[str, Any]] = []
        skipped_here = 0
        for payload in fetch["payloads"]:
            entry_id = (payload.get("metadata") or {}).get("entry_id")
            dedupe_key = (payload.get("source_type") or "", str(entry_id)) if entry_id else None
            if dedupe and dedupe_key and dedupe_key in seen_keys:
                skipped_here += 1
                continue
            ev = ledger.add_evidence(question_id=question_id, archive_url_snapshot=False, **payload)
            if dedupe_key:
                seen_keys.add(dedupe_key)
            evidence_rows.append({"id": ev.id, "source_url": ev.source_url, "claim": ev.claim})
        total_skipped += skipped_here
        # Optional auto_watch (same dedup as the single-source path).
        watch_note = None
        watch_record: dict[str, Any] | None = None
        if evidence_rows and bool(fetch["merged_args"].get("auto_watch")):
            watch_type = fetch["source_type"].removeprefix("adapter:").strip().lower()
            try:
                existing = ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status="active")
            except Exception:
                existing = []
            duplicate = next((w for w in existing if w.get("source") == fetch["source"]
                              and (w.get("source_type") or "").lower() == watch_type), None)
            if duplicate:
                watch_record = duplicate
                watch_note = "already watched (no-op)"
            else:
                try:
                    watch_record = ledger.add_watched_source(
                        scope_type="question", scope_ref=question_id,
                        source=fetch["source"], source_type=watch_type,
                        metadata={"auto_watch": True, "from_action": "import_source_evidence_batch"},
                    )
                    watch_note = "attached"
                except Exception as exc:
                    watch_note = f"auto_watch skipped: {exc}"
        total_imported += len(evidence_rows)
        results.append({
            "index": fetch["index"], "success": True,
            "source_type": fetch["source_type"], "source": fetch["source"],
            "imported_count": len(evidence_rows), "skipped_duplicates": skipped_here,
            "evidence": evidence_rows,
            "watched_source": watch_record, "auto_watch_note": watch_note,
            "elapsed_s": fetch["elapsed_s"],
        })

    return tool_result(
        success=True,
        question_id=question_id,
        imported_count=total_imported,
        skipped_duplicates=total_skipped,
        results=results,
        concurrency=concurrency,
    )


def _workflow_report_payload(ledger: "ForecastLedger", args: dict[str, Any]) -> str:
    """Aggregate per-question ledger activity into a compact workflow report.

    Pulls evidence / snapshots / model runs / watched sources / alerts /
    postmortems for one question, groups them by source-type and status,
    extracts blocked-source diagnostics tagged at evidence-add time, builds a
    chronological timeline, and emits a few heuristic adapter-improvement
    suggestions. Useful for postmortems and to spot what slowed a session.
    """

    from datetime import datetime, timezone
    from collections import Counter
    from urllib.parse import urlparse

    def _ts(value: Any) -> str | None:
        if not value:
            return None
        text = str(value)
        return text

    def _parse(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _short(text: Any, n: int = 80) -> str:
        if not text:
            return ""
        s = str(text).strip().replace("\n", " ")
        return s if len(s) <= n else s[: n - 1] + "…"

    def _opt_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _as_dict(value: Any) -> dict[str, Any]:
        # Evidence metadata / source_snapshot can arrive as a dict, a JSON
        # string (older rows), or None — coerce so `.get()` never explodes
        # ('str' object has no attribute 'get').
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except (ValueError, TypeError):
                return {}
        return {}

    question_id = _required(args, "question_id")
    question = ledger.get_question(question_id)
    since_dt = _parse(args.get("since"))
    limit_timeline = args.get("limit_timeline")
    try:
        timeline_cap = int(limit_timeline) if limit_timeline is not None else 25
    except (TypeError, ValueError):
        timeline_cap = 25

    def _in_window(value: Any) -> bool:
        if since_dt is None:
            return True
        ts = _parse(value)
        return ts is None or ts >= since_dt

    evidence = [e for e in ledger.list_evidence(question_id) if _in_window(e.captured_at)]
    snapshots = [s for s in ledger.list_snapshots(question_id) if _in_window(s.as_of)]
    model_runs = [m for m in ledger.list_model_runs(question_id) if _in_window(m.get("created_at") if isinstance(m, dict) else getattr(m, "created_at", None))]
    watched = ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status=None)
    alerts_all = ledger.list_alerts() if hasattr(ledger, "list_alerts") else []
    alerts = [
        a for a in alerts_all
        if (getattr(a, "scope_type", None) == "question" and getattr(a, "scope_ref", None) == question_id)
        and _in_window(getattr(a, "created_at", None))
    ]
    postmortems = [p for p in ledger.list_postmortems(question_id, include_invalidated=True) if _in_window(p.get("created_at") if isinstance(p, dict) else None)]

    # ── Evidence breakdown ──────────────────────────────────────────────────
    source_type_counts = Counter((e.source_type or "(unknown)") for e in evidence)
    blocked_items: list[dict[str, Any]] = []
    domain_counts: Counter[str] = Counter()
    for item in evidence:
        meta = _as_dict(item.metadata)
        blocked_flag = bool(meta.get("blocked") or _as_dict(meta.get("source_snapshot")).get("blocked"))
        if blocked_flag:
            snap = _as_dict(meta.get("source_snapshot"))
            blocked_items.append({
                "evidence_id": item.id,
                "source_url": item.source_url,
                "source_type": item.source_type,
                "reason": meta.get("block_reason") or snap.get("block_reason"),
                "signal": meta.get("block_signal") or snap.get("block_signal"),
                "captured_at": item.captured_at,
            })
        if item.source_url:
            try:
                host = urlparse(item.source_url).netloc.lower()
                if host:
                    domain_counts[host] += 1
            except Exception:
                pass
    blocked_reasons = Counter(b["reason"] for b in blocked_items if b.get("reason"))

    # ── Snapshot deltas ─────────────────────────────────────────────────────
    snapshot_deltas: list[dict[str, Any]] = []
    sorted_snaps = sorted(snapshots, key=lambda s: s.as_of or "")
    for prev, curr in zip(sorted_snaps, sorted_snaps[1:]):
        prev_p = _opt_float(prev.probability_or_distribution)
        curr_p = _opt_float(curr.probability_or_distribution)
        if prev_p is None or curr_p is None:
            continue
        snapshot_deltas.append({
            "from": prev.forecast_id, "to": curr.forecast_id,
            "from_p": round(prev_p, 4), "to_p": round(curr_p, 4),
            "delta_pts": round((curr_p - prev_p) * 100, 2),
            "as_of": curr.as_of,
        })

    # ── Watched / alerts / model-runs by group ──────────────────────────────
    watched_by_type = Counter((w.get("source_type") or "(unknown)") for w in watched)
    alert_by_severity = Counter(getattr(a, "severity", "info") for a in alerts)
    open_alerts = sum(1 for a in alerts if getattr(a, "status", "open") == "open")
    def _mr_field(m: Any, key: str) -> Any:
        return m.get(key) if isinstance(m, dict) else getattr(m, key, None)
    model_by_type = Counter((_mr_field(m, "model_type") or "(unknown)") for m in model_runs)

    # ── Timeline (chronological, capped) ────────────────────────────────────
    events: list[tuple[str, str, str, str]] = []
    for e in evidence:
        summary = _short(e.claim or e.summary or e.source_url, 100)
        kind = "blocked" if _as_dict(e.metadata).get("blocked") else "evidence"
        events.append((e.captured_at or "", kind, e.id, summary))
    for s in snapshots:
        prob = _opt_float(s.probability_or_distribution)
        prob_text = f"p={prob:.3f}" if prob is not None else "p=?"
        events.append((s.as_of or "", "snapshot", s.forecast_id, f"{prob_text}  {_short(s.rationale, 80)}"))
    for m in model_runs:
        kind = _mr_field(m, "model_type") or "?"
        events.append((_mr_field(m, "created_at") or "", "model_run", _mr_field(m, "id") or "?", f"type={kind}"))
    for a in alerts:
        events.append((getattr(a, "created_at", "") or "", "alert", getattr(a, "id", "?"), f"{getattr(a, 'severity', 'info')}: {_short(getattr(a, 'reason', ''), 80)}"))
    events.sort(key=lambda row: row[0])
    timeline = [
        {"at": at, "kind": kind, "ref": ref, "summary": summary}
        for at, kind, ref, summary in events[-timeline_cap:]
    ]

    # ── Heuristic suggestions ───────────────────────────────────────────────
    suggestions: list[str] = []
    if blocked_items:
        breakdown = ", ".join(f"{c} {r}" for r, c in blocked_reasons.most_common())
        suggestions.append(
            f"{len(blocked_items)} blocked evidence row(s) detected ({breakdown}). "
            "Prefer the structured adapter (e.g. import_source_evidence source_type=fred|polymarket|kalshi) "
            "or an authenticated path (FRED_API_KEY) over scraping a blocked HTML page."
        )
    repeated_domains = {host: n for host, n in domain_counts.items() if n >= 2}
    unwatched = {
        host for host in repeated_domains
        if not any(host in (w.get("source") or "") for w in watched)
    }
    if unwatched:
        listing = ", ".join(f"{h} (×{repeated_domains[h]})" for h in sorted(unwatched))
        suggestions.append(
            f"Multiple evidence rows reference unwatched domain(s): {listing}. "
            "Pass auto_watch=true on the next import_source_evidence call for these sources "
            "so reruns start from the known identifier."
        )
    fred_evidence = [e for e in evidence if (e.source_type or "").lower() == "adapter:fred"]
    fred_blocked_or_failed = [b for b in blocked_items if "fred" in (b.get("source_url") or "").lower()]
    if (fred_evidence or fred_blocked_or_failed) and not os.environ.get("FRED_API_KEY"):
        suggestions.append(
            "FRED is in use but FRED_API_KEY is not set. The public CSV endpoint is flaky from some networks; "
            "set the key (free) for the reliable official API: `forecast api-key set fred <key>`."
        )
    if not watched and len(evidence) >= 3:
        suggestions.append(
            "No watched sources attached to this question. Pass auto_watch=true on key market/feed imports "
            "to seed the watchlist so future reruns avoid broad search."
        )

    return tool_result(
        success=True,
        question={
            "id": question.id,
            "title": question.title,
            "status": question.status,
            "domain": question.domain,
        },
        window={
            "since": args.get("since"),
            "now": datetime.now(timezone.utc).isoformat(),
        },
        forecast_snapshots={
            "count": len(snapshots),
            "latest_id": sorted_snaps[-1].forecast_id if sorted_snaps else None,
            "latest_probability": (_opt_float(sorted_snaps[-1].probability_or_distribution) if sorted_snaps else None),
            "deltas": snapshot_deltas[-10:],
        },
        evidence={
            "count": len(evidence),
            "by_source_type": dict(source_type_counts.most_common()),
            "blocked": {
                "count": len(blocked_items),
                "reasons": dict(blocked_reasons.most_common()),
                "items": blocked_items[:10],
            },
            "by_domain": dict(domain_counts.most_common(10)),
        },
        model_runs={"count": len(model_runs), "by_type": dict(model_by_type.most_common())},
        watched_sources={"count": len(watched), "by_type": dict(watched_by_type.most_common())},
        alerts={
            "count": len(alerts),
            "open": open_alerts,
            "by_severity": dict(alert_by_severity.most_common()),
        },
        postmortems={"count": len(postmortems)},
        timeline=timeline,
        suggestions=suggestions,
    )


def _question_dict(question) -> dict[str, Any]:
    data = question.__dict__.copy()
    data["outcome_space"] = question.outcome_space.to_dict()
    return data


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
        if item.requires_user_source or not item.watch_source:
            skipped.append(item)
            continue
        if item.watch_source in existing_sources:
            skipped.append(item)
            continue
        row = ledger.add_watched_source(
            scope_type="question",
            scope_ref=question_id,
            source=item.watch_source,
            source_type=item.source_type,
            metadata=_source_plan_watch_metadata(item),
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
        return load_news_feed_items(
            source,
            limit=limit,
            since=since,
            keywords=_tool_filter_terms(args.get("keywords")),
            exclude_keywords=_tool_filter_terms(args.get("exclude_keywords")),
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
    if adapter_name in {"rss", "news"}:
        metadata.update(_tool_news_triage_metadata(args))
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


def fetch_watched_source_payloads(
    specs: list[dict[str, Any]], *, concurrency: int = 4
) -> list[dict[str, Any]]:
    """Re-fetch a list of watched sources and build add_evidence payloads.

    This is the dependency injected into ``ForecastLedger.refresh_forecast`` so
    the ledger (data layer) never imports the tool layer. Each spec is
    ``{"source_type": <adapter name>, "source": <id/slug>, "args"?: {...}}``.
    Returns, per spec, ``{"source_type", "source", "success", "payloads",
    "error"}`` where ``payloads`` is a list of kwargs dicts for
    ``ledger.add_evidence`` (each carrying ``metadata.adapter_item``). Pure
    fetch — performs NO ledger writes (preserves SQLite's single writer).
    """

    from concurrent.futures import ThreadPoolExecutor

    def _one(spec: dict[str, Any]) -> dict[str, Any]:
        adapter = str(spec.get("source_type") or "").strip()
        source = str(spec.get("source") or "").strip()
        adapter_args = dict(spec.get("args") or {})
        result = {"source_type": adapter, "source": source, "success": False, "payloads": [], "error": None}
        try:
            items = _load_source_adapter_items(adapter, source, adapter_args)
            result["payloads"] = [
                _source_adapter_evidence_payload(adapter, source, item, adapter_args) for item in items
            ]
            result["success"] = True
        except Exception as exc:  # noqa: BLE001 — one bad source must not abort the refresh
            result["error"] = str(exc)
        return result

    if not specs:
        return []
    workers = max(1, min(int(concurrency), len(specs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Iterate in submission order so imported evidence is deterministic.
        return list(pool.map(_one, specs))


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
    if adapter in {"polymarket", "kalshi", "manifold", "metaculus"}:
        label = {"polymarket": "Polymarket", "kalshi": "Kalshi", "manifold": "Manifold", "metaculus": "Metaculus"}[adapter]
        question = data.get("question") or data.get("title") or "market"
        probability = data.get("probability")
        if isinstance(probability, (int, float)) and not isinstance(probability, bool):
            return f"{label} market-implied probability {float(probability):.3f}: {question}"
        distribution = data.get("distribution")
        if isinstance(distribution, dict) and distribution:
            numeric = {k: v for k, v in distribution.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
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


registry.register(
    name="forecast_ledger",
    toolset="forecasting",
    schema=FORECAST_LEDGER_SCHEMA,
    handler=lambda args, **kw: forecast_ledger_tool(args),
    check_fn=check_forecasting_requirements,
    emoji="F",
)
