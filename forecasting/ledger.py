"""SQLite forecast ledger for the forecasting fork."""

from __future__ import annotations

import hashlib
import csv
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import uuid
from collections import Counter, defaultdict
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qsl, urlparse
from urllib.request import Request, urlopen

from hermes_constants import get_hermes_home

from forecasting.branding import (
    CORE_PRIMITIVE,
    FORK_CONTEXT_DOC,
    FORK_PRD_DOC,
    NORTH_STAR,
    PRODUCT_NAME,
    PRODUCT_SLUG,
)
from forecasting.benchmark_evidence import build_benchmark_evidence_profile
from forecasting.models import (
    ASSUMPTION_STATUSES,
    CALIBRATION_LESSON_STATUSES,
    EVIDENCE_CLAIM_TYPES,
    FAILURE_CLASSES,
    FORECAST_ORIGINS,
    QUESTION_STATUSES,
    REFERENCE_CLASS_STATUSES,
    RESOLUTION_STATUSES,
    AlertEvent,
    EvidenceItem,
    ForecastingError,
    ForecastQuestion,
    ForecastSnapshot,
    LedgerNotFoundError,
    OutcomeSpace,
    Resolution,
    ScoreRecord,
    ValidationError,
    evaluate_update_triggers,
    json_dumps,
    json_loads,
    normalize_update_triggers,
    parse_timestamp,
    question_decision_readiness_issues,
    timestamp_to_datetime,
    utc_now_iso,
)


logger = logging.getLogger(__name__)

FORECASTING_PROTOCOL_VERSION = "forecasting-ledger-v1"


def _normalize_reason_list(raw: Any, *, field: str) -> list[str]:
    """Coerce a reasons_up / reasons_down / change_my_mind payload to ``list[str]``.

    ``None`` is treated as empty. Strings are split on newlines when they
    contain them, allowing the CLI to pass either repeated ``--reason-up`` flags
    or a single multi-line block. Whitespace-only entries are dropped.
    """

    if raw is None:
        return []
    if isinstance(raw, str):
        items: list[str] = raw.splitlines() if "\n" in raw else [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise ValidationError(f"{field} must be a string or list of strings")
    cleaned: list[str] = []
    for entry in items:
        if entry is None:
            continue
        if not isinstance(entry, str):
            raise ValidationError(f"{field} entries must be strings")
        stripped = entry.strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned
WATCH_SCOPE_TYPES = {"question", "domain", "topic", "domain_topic", "portfolio"}
SCHEDULE_SCOPE_TYPES = {"question", "domain", "topic", "domain_topic", "portfolio", "horizon"}
AUTOPILOT_MODES = {"propose", "auto_commit", "alert_only"}
AUTOPILOT_PROPOSAL_STATUSES = {"pending", "approved", "rejected", "expired", "auto_committed"}
WATCH_SOURCE_TYPES = {
    "file",
    "url",
    "manual",
    "rss",
    "gdelt",
    "fivethirtyeight",
    "github",
    "githubrepo",
    "githubissues",
    "githubcommits",
    "githubactions",
    "coingecko",
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
    "pypi",
    "npm",
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
}


class _IngestHTMLParser(HTMLParser):
    """Small metadata/text extractor for generic forecast URL ingest."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.text_lines: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag != "meta":
            return
        attr_map = {name.lower(): value or "" for name, value in attrs}
        key = (attr_map.get("name") or attr_map.get("property") or "").strip().lower()
        content = attr_map.get("content", "").strip()
        if key and content:
            self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or self._skip_depth:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
            return
        if len(self.text_lines) < 40:
            self.text_lines.append(text)


def _export_metadata() -> dict[str, Any]:
    return {
        "product_name": PRODUCT_NAME,
        "product_slug": PRODUCT_SLUG,
        "core_primitive": CORE_PRIMITIVE,
        "north_star": NORTH_STAR,
        "context_doc": FORK_CONTEXT_DOC,
        "prd_doc": FORK_PRD_DOC,
    }


_PACKET_PRIMARY_KEYS = {
    "forecast_snapshots": "forecast_id",
}
_PACKET_JSON_FIELDS = {
    "forecast_questions": {"outcome_space", "tags", "topics", "metadata", "update_triggers"},
    "forecast_snapshots": {
        "probability_or_distribution",
        "ensemble_components",
        "key_assumptions",
        "assumption_refs",
        "reference_class_refs",
        "evidence_refs",
        "model_run_refs",
        "source_snapshot_refs",
        "calibration_lesson_refs",
        "calibration_adjustment",
        "metadata",
        "reasons_up",
        "reasons_down",
        "change_my_mind",
    },
    "evidence_items": {"metadata"},
    "ingest_candidates": {"outcome_space", "metadata"},
    "assumptions": {"evidence_refs"},
    "reference_classes": {"source_refs"},
    "model_runs": {"inputs", "parameters", "output", "diagnostics", "artifact_paths"},
    "resolutions": {"outcome"},
    "postmortems": {"calibration_adjustment"},
    "calibration_lessons": {
        "recommended_adjustment",
        "source_postmortem_refs",
        "source_score_record_refs",
        "metadata",
    },
    "forecast_corrections": {
        "old_value",
        "new_value",
        "patch",
        "affected_score_record_refs",
        "affected_postmortem_refs",
        "affected_calibration_lesson_refs",
    },
    "domain_error_profiles": {
        "calibration_summary",
        "recurring_errors",
        "recommended_adjustments",
    },
    "panel_runs": {
        "perspectives",
        "spread_summary",
        "notes",
    },
    "panel_estimates": {
        "reasons_up",
        "reasons_down",
        "change_my_mind",
        "metadata",
    },
    "baseline_comparisons": {"probability_or_distribution", "metadata"},
    "source_snapshots": {"parsed_values", "metadata"},
    "watched_sources": {"metadata"},
    "scheduled_review_runs": {"metadata"},
    "autopilot_policies": {"materiality_policy", "guardrail_policy", "notification_policy"},
    "autopilot_runs": {"diagnostics"},
    "forecast_update_proposals": {
        "proposed_probability_or_distribution",
        "evidence_refs",
        "source_snapshot_refs",
        "model_run_refs",
        "assumption_refs",
        "reference_class_refs",
    },
}
_PACKET_BOOL_FIELDS = {
    "evidence_items": {"admissible_for_backtests"},
    "resolutions": {"criteria_satisfied", "scoreable"},
    "score_records": {"calibration_eligible"},
    "postmortems": {"calibration_eligible"},
    "scheduled_reviews": {"enabled", "auto_score", "auto_postmortem"},
    "autopilot_policies": {"enabled"},
}
_PACKET_RECORD_LABELS = {
    "forecast_questions": "questions",
    "forecast_snapshots": "forecast_history",
    "evidence_items": "evidence",
    "ingest_candidates": "ingest_candidates",
    "assumptions": "assumptions",
    "reference_classes": "reference_classes",
    "model_runs": "model_runs",
    "resolutions": "resolutions",
    "score_records": "scores",
    "postmortems": "postmortems",
    "calibration_lessons": "calibration_lessons",
    "forecast_corrections": "corrections",
    "domain_error_profiles": "domain_error_profiles",
    "baseline_comparisons": "baseline_comparisons",
    "source_snapshots": "source_snapshots",
    "watched_sources": "watched_sources",
    "scheduled_reviews": "scheduled_reviews",
    "scheduled_review_runs": "scheduled_review_runs",
    "alert_events": "alerts",
    "autopilot_policies": "autopilot_policies",
    "autopilot_runs": "autopilot_runs",
    "forecast_update_proposals": "forecast_update_proposals",
}


class ForecastLedger:
    """Local-first SQLite ledger for questions, evidence, forecasts, and scores."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        configured_db = os.getenv("FORECAST_LEDGER_DB", "").strip()
        self.db_path = (
            Path(db_path).expanduser()
            if db_path
            else Path(configured_db).expanduser()
            if configured_db
            else get_hermes_home() / "forecasting" / "forecasting.db"
        )
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ForecastingError(
                "could not create forecast ledger directory "
                f"{self.db_path.parent}: {exc}. Set FORECAST_LEDGER_DB or "
                "pass --db with a writable path."
            ) from exc
        try:
            self.initialize_schema()
        except sqlite3.Error as exc:
            raise ForecastingError(
                "could not initialize forecast ledger "
                f"{self.db_path}: {exc}. Set FORECAST_LEDGER_DB or "
                "pass --db with a writable path."
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS forecast_questions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    resolution_criteria TEXT NOT NULL,
                    resolution_source TEXT,
                    created_at TEXT NOT NULL,
                    close_time TEXT,
                    resolution_time TEXT,
                    outcome_space TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    tags TEXT NOT NULL DEFAULT '[]',
                    domain TEXT,
                    topics TEXT NOT NULL DEFAULT '[]',
                    owner TEXT,
                    impact TEXT,
                    review_cadence TEXT,
                    next_review_at TEXT,
                    current_forecast_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS forecast_snapshots (
                    forecast_id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    probability_or_distribution TEXT NOT NULL,
                    confidence REAL,
                    forecast_horizon_days REAL,
                    method TEXT,
                    ensemble_components TEXT NOT NULL DEFAULT '{}',
                    rationale TEXT NOT NULL DEFAULT '',
                    key_assumptions TEXT NOT NULL DEFAULT '[]',
                    assumption_refs TEXT NOT NULL DEFAULT '[]',
                    reference_class_refs TEXT NOT NULL DEFAULT '[]',
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    model_run_refs TEXT NOT NULL DEFAULT '[]',
                    parent_forecast_id TEXT,
                    forecast_origin TEXT NOT NULL DEFAULT 'live',
                    agent_model TEXT,
                    prompt_version TEXT,
                    forecasting_protocol_version TEXT,
                    toolset_version TEXT,
                    source_snapshot_refs TEXT NOT NULL DEFAULT '[]',
                    evidence_cutoff TEXT,
                    backtest_run_id TEXT,
                    calibration_eligible INTEGER NOT NULL DEFAULT 1,
                    calibration_weight REAL NOT NULL DEFAULT 1.0,
                    calibration_lesson_refs TEXT NOT NULL DEFAULT '[]',
                    calibration_adjustment TEXT NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_question
                    ON forecast_snapshots(question_id, created_at);

                CREATE TABLE IF NOT EXISTS evidence_items (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    captured_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    source_url TEXT,
                    source_name TEXT,
                    source_type TEXT NOT NULL,
                    published_at TEXT,
                    claim TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    reliability_rating REAL,
                    relevance_rating REAL,
                    stance TEXT NOT NULL DEFAULT 'context',
                    claim_type TEXT NOT NULL DEFAULT 'fact',
                    snapshot_path TEXT,
                    admissible_for_backtests INTEGER NOT NULL DEFAULT 1,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_evidence_question_available
                    ON evidence_items(question_id, available_at);

                CREATE TABLE IF NOT EXISTS ingest_candidates (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    candidate_title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    resolution_criteria TEXT NOT NULL DEFAULT '',
                    resolution_source TEXT,
                    close_time TEXT,
                    resolution_time TEXT,
                    outcome_space TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    confirmed_question_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS assumptions (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    invalidated_at TEXT,
                    check_cadence TEXT,
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS reference_classes (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    inclusion_criteria TEXT NOT NULL DEFAULT '',
                    exclusion_criteria TEXT NOT NULL DEFAULT '',
                    base_rate REAL,
                    base_rate_uncertainty REAL,
                    source_refs TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    invalidated_at TEXT,
                    check_cadence TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS model_runs (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'success',
                    inputs TEXT NOT NULL DEFAULT '{}',
                    parameters TEXT NOT NULL DEFAULT '{}',
                    output TEXT NOT NULL DEFAULT '{}',
                    diagnostics TEXT NOT NULL DEFAULT '{}',
                    code_ref TEXT,
                    artifact_paths TEXT NOT NULL DEFAULT '[]',
                    model_version TEXT,
                    prompt_version TEXT,
                    data_version TEXT,
                    evidence_cutoff TEXT
                );

                CREATE TABLE IF NOT EXISTS resolutions (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    resolved_at TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    resolution_source TEXT,
                    resolution_source_snapshot_ref TEXT,
                    resolver_type TEXT NOT NULL DEFAULT 'manual',
                    resolution_status TEXT NOT NULL DEFAULT 'confirmed',
                    criteria_satisfied INTEGER NOT NULL DEFAULT 1,
                    confidence REAL,
                    confirmed_at TEXT,
                    confirmed_by TEXT,
                    resolver_notes TEXT,
                    disputed_at TEXT,
                    correction_ref TEXT,
                    scoreable INTEGER NOT NULL DEFAULT 1,
                    trusted_policy_id TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_resolutions_question_status
                    ON resolutions(question_id, resolution_status, resolved_at);

                CREATE TABLE IF NOT EXISTS score_records (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    forecast_id TEXT NOT NULL REFERENCES forecast_snapshots(forecast_id) ON DELETE CASCADE,
                    resolution_id TEXT NOT NULL REFERENCES resolutions(id) ON DELETE CASCADE,
                    scored_at TEXT NOT NULL,
                    brier_score REAL,
                    log_score REAL,
                    proper_score REAL,
                    score_rule TEXT,
                    calibration_bucket TEXT,
                    forecast_horizon_days REAL,
                    domain TEXT,
                    forecast_origin TEXT NOT NULL,
                    calibration_eligible INTEGER NOT NULL DEFAULT 1,
                    calibration_weight REAL NOT NULL DEFAULT 1.0,
                    baseline_ref TEXT,
                    invalidated_by_correction_id TEXT,
                    notes TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_score_records_domain_bucket
                    ON score_records(domain, calibration_bucket, forecast_origin);

                CREATE TABLE IF NOT EXISTS postmortems (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    forecast_id TEXT NOT NULL REFERENCES forecast_snapshots(forecast_id) ON DELETE CASCADE,
                    resolution_id TEXT NOT NULL REFERENCES resolutions(id) ON DELETE CASCADE,
                    score_record_id TEXT NOT NULL REFERENCES score_records(id) ON DELETE CASCADE,
                    forecast_origin TEXT NOT NULL,
                    calibration_eligible INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    what_happened TEXT NOT NULL DEFAULT '',
                    what_was_expected TEXT NOT NULL DEFAULT '',
                    missed_evidence TEXT NOT NULL DEFAULT '',
                    overweighted_evidence TEXT NOT NULL DEFAULT '',
                    base_rate_error TEXT NOT NULL DEFAULT '',
                    inside_view_error TEXT NOT NULL DEFAULT '',
                    resolution_error TEXT NOT NULL DEFAULT '',
                    lesson TEXT NOT NULL DEFAULT '',
                    calibration_adjustment TEXT NOT NULL DEFAULT '{}',
                    invalidated_by_correction_id TEXT
                );

                CREATE TABLE IF NOT EXISTS calibration_lessons (
                    id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'tentative',
                    confidence REAL,
                    lesson TEXT NOT NULL,
                    recommended_adjustment TEXT NOT NULL DEFAULT '{}',
                    source_postmortem_refs TEXT NOT NULL DEFAULT '[]',
                    source_score_record_refs TEXT NOT NULL DEFAULT '[]',
                    supersedes_lesson_id TEXT,
                    invalidated_by_correction_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS forecast_corrections (
                    id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT,
                    reason TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    patch TEXT,
                    affected_score_record_refs TEXT NOT NULL DEFAULT '[]',
                    affected_postmortem_refs TEXT NOT NULL DEFAULT '[]',
                    affected_calibration_lesson_refs TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'proposed'
                );

                CREATE TABLE IF NOT EXISTS trusted_resolver_policies (
                    id TEXT PRIMARY KEY,
                    resolver_plugin TEXT NOT NULL,
                    plugin_version TEXT,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    approved_by TEXT,
                    last_used_at TEXT,
                    audit_log_ref TEXT
                );

                CREATE TABLE IF NOT EXISTS baseline_comparisons (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    forecast_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
                    backtest_case_id TEXT,
                    source TEXT NOT NULL,
                    baseline_type TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    probability_or_distribution TEXT NOT NULL,
                    score_record_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id TEXT PRIMARY KEY,
                    dataset TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    default_forecast_time_cutoff TEXT,
                    evidence_cutoff_policy TEXT NOT NULL,
                    question_filter TEXT NOT NULL DEFAULT '{}',
                    model_profile TEXT NOT NULL DEFAULT '{}',
                    calibration_policy TEXT NOT NULL DEFAULT '{}',
                    result_summary TEXT NOT NULL DEFAULT '{}',
                    artifact_paths TEXT NOT NULL DEFAULT '[]',
                    leakage_checks_passed INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS benchmark_datasets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    case_count INTEGER NOT NULL,
                    description TEXT,
                    cases TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS backtest_cases (
                    id TEXT PRIMARY KEY,
                    backtest_run_id TEXT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
                    question_id TEXT REFERENCES forecast_questions(id) ON DELETE SET NULL,
                    simulated_forecast_time TEXT NOT NULL,
                    evidence_cutoff TEXT NOT NULL,
                    generated_forecast_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
                    baseline_comparison_refs TEXT NOT NULL DEFAULT '[]',
                    score_record_id TEXT,
                    leakage_check_status TEXT NOT NULL DEFAULT 'pending',
                    excluded_evidence_count INTEGER NOT NULL DEFAULT 0,
                    ambiguous_evidence_count INTEGER NOT NULL DEFAULT 0,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS scheduled_reviews (
                    id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT,
                    cadence TEXT NOT NULL,
                    stale_days INTEGER NOT NULL DEFAULT 7,
                    confidence_below REAL,
                    confidence_above REAL,
                    large_delta_threshold REAL,
                    next_run_at TEXT NOT NULL,
                    last_run_at TEXT,
                    trigger_reason TEXT NOT NULL DEFAULT 'scheduled',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    auto_score INTEGER NOT NULL DEFAULT 0,
                    auto_postmortem INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS scheduled_review_runs (
                    id TEXT PRIMARY KEY,
                    scheduled_review_id TEXT NOT NULL REFERENCES scheduled_reviews(id) ON DELETE CASCADE,
                    run_at TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    alert_count INTEGER NOT NULL DEFAULT 0,
                    score_count INTEGER NOT NULL DEFAULT 0,
                    postmortem_count INTEGER NOT NULL DEFAULT 0,
                    learning_review_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'completed',
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_scheduled_review_runs_review
                    ON scheduled_review_runs(scheduled_review_id, run_at DESC);

                CREATE TABLE IF NOT EXISTS watched_sources (
                    id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    last_seen_signature TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_watched_sources_scope
                    ON watched_sources(scope_type, scope_ref, status);

                CREATE TABLE IF NOT EXISTS source_snapshots (
                    id TEXT PRIMARY KEY,
                    question_id TEXT REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    watched_source_id TEXT REFERENCES watched_sources(id) ON DELETE SET NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT,
                    retrieved_at TEXT NOT NULL,
                    raw_payload_path TEXT,
                    raw_payload_sha256 TEXT,
                    parsed_values TEXT NOT NULL DEFAULT '{}',
                    adapter_version TEXT,
                    status TEXT NOT NULL DEFAULT 'success',
                    error_message TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_source_snapshots_question
                    ON source_snapshots(question_id, retrieved_at DESC);

                CREATE TABLE IF NOT EXISTS alert_events (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    acknowledged_at TEXT
                );

                CREATE TABLE IF NOT EXISTS autopilot_policies (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    mode TEXT NOT NULL DEFAULT 'propose',
                    cadence TEXT NOT NULL,
                    scheduled_review_id TEXT REFERENCES scheduled_reviews(id) ON DELETE SET NULL,
                    materiality_policy TEXT NOT NULL DEFAULT '{}',
                    guardrail_policy TEXT NOT NULL DEFAULT '{}',
                    notification_policy TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_autopilot_policies_question
                    ON autopilot_policies(question_id, enabled);

                CREATE TABLE IF NOT EXISTS autopilot_runs (
                    id TEXT PRIMARY KEY,
                    policy_id TEXT NOT NULL REFERENCES autopilot_policies(id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    sources_checked INTEGER NOT NULL DEFAULT 0,
                    sources_changed INTEGER NOT NULL DEFAULT 0,
                    material_changes INTEGER NOT NULL DEFAULT 0,
                    proposal_id TEXT,
                    forecast_snapshot_id TEXT,
                    alerts_created INTEGER NOT NULL DEFAULT 0,
                    diagnostics TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_autopilot_runs_policy
                    ON autopilot_runs(policy_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS forecast_update_proposals (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES autopilot_runs(id) ON DELETE SET NULL,
                    prior_forecast_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
                    proposed_probability_or_distribution TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    source_snapshot_refs TEXT NOT NULL DEFAULT '[]',
                    model_run_refs TEXT NOT NULL DEFAULT '[]',
                    assumption_refs TEXT NOT NULL DEFAULT '[]',
                    reference_class_refs TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewed_by TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_forecast_update_proposals_question
                    ON forecast_update_proposals(question_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS panel_runs (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    snapshot_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
                    aggregation_method TEXT NOT NULL DEFAULT 'trimmed_geomean_odds',
                    trim INTEGER NOT NULL DEFAULT 0,
                    aggregate_probability REAL NOT NULL,
                    perspectives TEXT NOT NULL DEFAULT '[]',
                    spread_summary TEXT NOT NULL DEFAULT '{}',
                    notes TEXT NOT NULL DEFAULT '[]',
                    triggered_by TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_panel_runs_question
                    ON panel_runs(question_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS panel_estimates (
                    id TEXT PRIMARY KEY,
                    panel_run_id TEXT NOT NULL REFERENCES panel_runs(id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    perspective TEXT NOT NULL,
                    probability REAL NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    trimmed INTEGER NOT NULL DEFAULT 0,
                    confidence_low REAL,
                    confidence_high REAL,
                    rationale TEXT NOT NULL DEFAULT '',
                    reasons_up TEXT NOT NULL DEFAULT '[]',
                    reasons_down TEXT NOT NULL DEFAULT '[]',
                    change_my_mind TEXT NOT NULL DEFAULT '[]',
                    crux TEXT,
                    agent_model TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_panel_estimates_run
                    ON panel_estimates(panel_run_id);

                CREATE TABLE IF NOT EXISTS domain_error_profiles (
                    id TEXT PRIMARY KEY,
                    domain TEXT,
                    topic TEXT,
                    forecast_horizon_bucket TEXT,
                    question_type TEXT,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    calibration_summary TEXT NOT NULL DEFAULT '{}',
                    recurring_errors TEXT NOT NULL DEFAULT '[]',
                    recommended_adjustments TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "model_runs", "status", "TEXT NOT NULL DEFAULT 'success'")
            self._ensure_column(conn, "forecast_snapshots", "metadata", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "evidence_items", "claim_type", "TEXT NOT NULL DEFAULT 'fact'")
            self._ensure_column(conn, "score_records", "invalidated_by_correction_id", "TEXT")
            self._ensure_column(conn, "score_records", "proper_score", "REAL")
            self._ensure_column(conn, "score_records", "score_rule", "TEXT")
            self._ensure_column(conn, "postmortems", "invalidated_by_correction_id", "TEXT")
            self._ensure_column(conn, "calibration_lessons", "invalidated_by_correction_id", "TEXT")
            self._ensure_column(conn, "resolutions", "trusted_policy_id", "TEXT")
            self._ensure_column(conn, "reference_classes", "check_cadence", "TEXT")
            self._ensure_column(conn, "scheduled_reviews", "auto_score", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "scheduled_reviews", "auto_postmortem", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "scheduled_reviews", "stale_days", "INTEGER NOT NULL DEFAULT 7")
            self._ensure_column(conn, "scheduled_reviews", "confidence_below", "REAL")
            self._ensure_column(conn, "scheduled_reviews", "confidence_above", "REAL")
            self._ensure_column(conn, "scheduled_reviews", "large_delta_threshold", "REAL")
            self._ensure_column(conn, "forecast_questions", "decision_owner", "TEXT")
            self._ensure_column(conn, "forecast_questions", "decision_deadline", "TEXT")
            self._ensure_column(conn, "forecast_questions", "action_threshold", "TEXT")
            self._ensure_column(conn, "forecast_questions", "update_triggers", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "forecast_snapshots", "reasons_up", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "forecast_snapshots", "reasons_down", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "forecast_snapshots", "change_my_mind", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "postmortems", "failure_class", "TEXT")

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_question(
        self,
        *,
        title: str,
        resolution_criteria: str,
        outcome_space: OutcomeSpace | None = None,
        description: str = "",
        resolution_source: str | None = None,
        close_time: str | None = None,
        resolution_time: str | None = None,
        tags: list[str] | None = None,
        domain: str | None = None,
        topics: list[str] | None = None,
        owner: str | None = None,
        impact: str | None = None,
        review_cadence: str | None = None,
        next_review_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        decision_owner: str | None = None,
        decision_deadline: str | None = None,
        action_threshold: str | None = None,
        update_triggers: Any = None,
    ) -> ForecastQuestion:
        title = title.strip()
        resolution_criteria = resolution_criteria.strip()
        if not title:
            raise ValidationError("forecast title is required")
        if not resolution_criteria:
            raise ValidationError("resolution criteria are required")

        outcome = outcome_space or OutcomeSpace()
        outcome.validate()
        scoreability_issues = self._scoreability_issues(title, resolution_criteria, outcome)
        if scoreability_issues:
            raise ValidationError(
                "ambiguous or unscoreable forecast question: " + "; ".join(scoreability_issues)
            )
        created_at = utc_now_iso()
        question_id = f"fq_{uuid.uuid4().hex[:12]}"
        parsed_next_review_at = parse_timestamp(next_review_at, field_name="next_review_at")
        parsed_decision_deadline = parse_timestamp(decision_deadline, field_name="decision_deadline")
        normalized_decision_owner = (decision_owner or "").strip() or None
        normalized_action_threshold = (action_threshold or "").strip() or None
        normalized_triggers = normalize_update_triggers(update_triggers)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO forecast_questions (
                    id, title, description, resolution_criteria, resolution_source,
                    created_at, close_time, resolution_time, outcome_space, status,
                    tags, domain, topics, owner, impact, review_cadence,
                    next_review_at, metadata,
                    decision_owner, decision_deadline, action_threshold, update_triggers
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question_id,
                    title,
                    description,
                    resolution_criteria,
                    resolution_source,
                    created_at,
                    parse_timestamp(close_time, field_name="close_time"),
                    parse_timestamp(resolution_time, field_name="resolution_time"),
                    outcome.to_json(),
                    json_dumps(tags or []),
                    domain,
                    json_dumps(topics or []),
                    owner,
                    impact,
                    review_cadence,
                    parsed_next_review_at,
                    json_dumps(metadata or {}),
                    normalized_decision_owner,
                    parsed_decision_deadline,
                    normalized_action_threshold,
                    json_dumps(normalized_triggers),
                ),
            )
        if review_cadence and parsed_next_review_at:
            self.schedule_review(
                scope_type="question",
                scope_ref=question_id,
                cadence=review_cadence,
                next_run_at=parsed_next_review_at,
                trigger_reason="question_review_cadence",
            )
        return self.get_question(question_id)

    def list_questions(
        self,
        *,
        status: str | None = None,
        domain: str | None = None,
        limit: int | None = None,
    ) -> list[ForecastQuestion]:
        if status and status not in QUESTION_STATUSES:
            raise ValidationError(f"status must be one of {', '.join(sorted(QUESTION_STATUSES))}")
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM forecast_questions {where} ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            return [self._row_to_question(row) for row in conn.execute(sql, params).fetchall()]

    def get_question(self, question_id: str) -> ForecastQuestion:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM forecast_questions WHERE id = ?", (question_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"forecast question not found: {question_id}")
        return self._row_to_question(row)

    def update_question_decision(
        self,
        question_id: str,
        *,
        decision_owner: str | None = None,
        decision_deadline: str | None = None,
        action_threshold: str | None = None,
        update_triggers: Any = None,
    ) -> ForecastQuestion:
        """Patch decision-card fields on an existing question.

        Pass ``None`` to leave a field untouched, an empty string to clear it.
        ``update_triggers`` is normalized through :func:`normalize_update_triggers`;
        pass ``[]`` to clear the list.
        """

        existing = self.get_question(question_id)
        sets: list[str] = []
        params: list[Any] = []
        if decision_owner is not None:
            value = decision_owner.strip() or None
            sets.append("decision_owner = ?")
            params.append(value)
        if decision_deadline is not None:
            value = parse_timestamp(decision_deadline, field_name="decision_deadline") if decision_deadline else None
            sets.append("decision_deadline = ?")
            params.append(value)
        if action_threshold is not None:
            value = action_threshold.strip() or None
            sets.append("action_threshold = ?")
            params.append(value)
        if update_triggers is not None:
            normalized = normalize_update_triggers(update_triggers)
            sets.append("update_triggers = ?")
            params.append(json_dumps(normalized))
        if not sets:
            return existing
        params.append(question_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE forecast_questions SET {', '.join(sets)} WHERE id = ?",
                params,
            )
        return self.get_question(question_id)

    def decision_readiness_issues(self, question: ForecastQuestion | str) -> list[str]:
        """Return decision-card gaps for ``question`` (id or object)."""

        if isinstance(question, str):
            question = self.get_question(question)
        return question_decision_readiness_issues(question)

    def create_snapshot(
        self,
        *,
        question_id: str,
        probability_or_distribution: Any,
        rationale: str,
        as_of: str | None = None,
        confidence: float | None = None,
        method: str | None = None,
        ensemble_components: dict[str, Any] | None = None,
        key_assumptions: list[str] | None = None,
        assumption_refs: list[str] | None = None,
        reference_class_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        model_run_refs: list[str] | None = None,
        forecast_origin: str = "live",
        agent_model: str | None = None,
        prompt_version: str | None = None,
        forecasting_protocol_version: str | None = None,
        toolset_version: str | None = None,
        source_snapshot_refs: list[str] | None = None,
        evidence_cutoff: str | None = None,
        backtest_run_id: str | None = None,
        calibration_eligible: bool = True,
        calibration_weight: float = 1.0,
        calibration_lesson_refs: list[str] | None = None,
        calibration_adjustment: dict[str, Any] | None = None,
        stale_evidence_days: int | None = None,
        acknowledge_stale_evidence: bool = False,
        require_citations: bool = False,
        metadata: dict[str, Any] | None = None,
        set_current: bool = True,
        reasons_up: list[str] | None = None,
        reasons_down: list[str] | None = None,
        change_my_mind: list[str] | None = None,
        require_decision_readiness: bool = False,
        require_structured_reasoning: bool = False,
        require_panel: bool = False,
        panel_run_ref: str | None = None,
        panel_skipped_reason: str | None = None,
    ) -> ForecastSnapshot:
        question = self.get_question(question_id)
        if forecast_origin not in FORECAST_ORIGINS:
            raise ValidationError(f"forecast_origin must be one of {', '.join(sorted(FORECAST_ORIGINS))}")
        # Exploratory forecasts are scratchpad thinking — never scored, and
        # exempt from the commit-time formalities below (the gates all key on
        # forecast_origin == "live"). Commit a live forecast to put it on the
        # record.
        if forecast_origin == "exploratory":
            calibration_eligible = False
        payload = self._validate_probability_payload(probability_or_distribution, question.outcome_space)
        if not rationale.strip():
            raise ValidationError("forecast rationale is required")
        if confidence is not None and not (0 <= confidence <= 1):
            raise ValidationError("confidence must be between 0 and 1")
        if calibration_weight < 0:
            raise ValidationError("calibration_weight must be non-negative")
        reasons_up_list = _normalize_reason_list(reasons_up, field="reasons_up")
        reasons_down_list = _normalize_reason_list(reasons_down, field="reasons_down")
        change_my_mind_list = _normalize_reason_list(change_my_mind, field="change_my_mind")
        if require_structured_reasoning and forecast_origin == "live":
            missing_reasoning = []
            if not reasons_up_list:
                missing_reasoning.append("reasons_up")
            if not reasons_down_list:
                missing_reasoning.append("reasons_down")
            if not change_my_mind_list:
                missing_reasoning.append("change_my_mind")
            if missing_reasoning:
                raise ValidationError(
                    "live forecast requires structured reasoning fields: "
                    + ", ".join(missing_reasoning)
                    + ". Provide reasons_up/reasons_down/change_my_mind, rerun with "
                    "require_structured_reasoning=false, or record it as "
                    "forecast_origin='exploratory'."
                )
        if require_decision_readiness and forecast_origin == "live":
            readiness_issues = question_decision_readiness_issues(question)
            if readiness_issues:
                raise ValidationError(
                    "forecast update blocked by missing decision context: "
                    + "; ".join(readiness_issues)
                    + ". Set decision_owner, action_threshold, and update_triggers "
                    "on the question, or rerun without require_decision_readiness."
                )

        now = utc_now_iso()
        as_of_ts = parse_timestamp(as_of, field_name="as_of") or now
        cutoff_ts = parse_timestamp(evidence_cutoff, field_name="evidence_cutoff")
        effective_cutoff = cutoff_ts or as_of_ts
        self._validate_evidence_refs(question_id, evidence_refs or [], effective_cutoff)
        snapshot_metadata = dict(metadata or {})

        # Panel formality. A deliberative panel — independent multi-perspective
        # estimates aggregated into a spread — is *indicated* for high-impact
        # questions and for the first forecast on any question (see
        # should_run_panel). For a high-impact live forecast we hard-require
        # evidence one ran (a panel run linked via panel_run_ref) OR an explicit
        # recorded reason for skipping it; the cost of a single-model miss is
        # highest there. For a non-high-impact first forecast the panel is only
        # recommended (recorded as a note), so routine and exploratory research
        # stays unencumbered. Exploratory snapshots are exempt entirely.
        if forecast_origin == "live":
            from forecasting.panel import should_run_panel  # local import avoids cycle

            if panel_run_ref:
                linked_panel = self.get_panel_run(panel_run_ref)
                if linked_panel["question_id"] != question_id:
                    raise ValidationError("panel_run_ref belongs to a different question")
            panel_skip = (panel_skipped_reason or "").strip()
            panel_indicated = should_run_panel(
                impact=question.impact,
                has_prior_snapshot=bool(question.current_forecast_id),
            )
            high_impact = (question.impact or "").strip().lower() == "high"
            if panel_indicated and not panel_run_ref and not panel_skip:
                if require_panel and high_impact:
                    raise ValidationError(
                        "high-impact live forecast requires a deliberative panel: run a "
                        "panel and pass panel_run_ref, record why you skipped it with "
                        "panel_skipped_reason, rerun with require_panel=false, or record "
                        "it as forecast_origin='exploratory'."
                    )
                # First-forecast panels on lower-impact questions are recommended,
                # not required — leave a note the agent/guidance can surface.
                snapshot_metadata["panel_recommended"] = True
            if panel_skip:
                snapshot_metadata["panel_skipped_reason"] = panel_skip

        if require_citations and forecast_origin == "live":
            citation_refs = [
                *(evidence_refs or []),
                *(model_run_refs or []),
                *(reference_class_refs or []),
                *(source_snapshot_refs or []),
                *(assumption_refs or []),
                *(calibration_lesson_refs or []),
            ]
            if not citation_refs:
                raise ValidationError(
                    "live forecast requires citations: add evidence/model/reference/source refs, "
                    "rerun with require_citations=false, or record it as forecast_origin='exploratory'"
                )
            snapshot_metadata["citation_policy"] = "required"
        if stale_evidence_days is not None and evidence_refs:
            stale_refs = self.find_stale_evidence_refs(
                question_id,
                evidence_refs,
                as_of=as_of_ts,
                stale_days=stale_evidence_days,
            )
            if stale_refs and not acknowledge_stale_evidence:
                refs = ", ".join(item.id for item in stale_refs)
                raise ValidationError(
                    f"stale evidence requires acknowledgement before update: {refs}"
                )
            if stale_refs:
                snapshot_metadata["stale_evidence_acknowledgement"] = {
                    "acknowledged_at": now,
                    "stale_evidence_days": stale_evidence_days,
                    "evidence_refs": [item.id for item in stale_refs],
                }
        self._validate_question_scoped_refs(question_id, assumption_refs or [], self.get_assumption, "assumption")
        self._validate_question_scoped_refs(
            question_id,
            reference_class_refs or [],
            self.get_reference_class,
            "reference class",
        )
        self._validate_question_scoped_refs(question_id, model_run_refs or [], self.get_model_run, "model run")
        for lesson_id in calibration_lesson_refs or []:
            lesson = self.get_calibration_lesson(lesson_id)
            if lesson["status"] != "active" or lesson.get("invalidated_by_correction_id"):
                raise ValidationError("calibration lesson refs must be active and non-invalidated")
        forecast_id = f"fs_{uuid.uuid4().hex[:12]}"
        horizon_days = self._forecast_horizon_days(question.close_time, as_of_ts)
        parent_forecast_id = question.current_forecast_id
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO forecast_snapshots (
                    forecast_id, question_id, created_at, as_of,
                    probability_or_distribution, confidence, forecast_horizon_days,
                    method, ensemble_components, rationale, key_assumptions,
                    assumption_refs, reference_class_refs, evidence_refs, model_run_refs,
                    parent_forecast_id, forecast_origin, agent_model, prompt_version,
                    forecasting_protocol_version, toolset_version, source_snapshot_refs,
                    evidence_cutoff, backtest_run_id, calibration_eligible,
                    calibration_weight, calibration_lesson_refs, calibration_adjustment,
                    metadata, reasons_up, reasons_down, change_my_mind
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    forecast_id,
                    question_id,
                    now,
                    as_of_ts,
                    json_dumps(payload),
                    confidence,
                    horizon_days,
                    method,
                    json_dumps(ensemble_components or {}),
                    rationale.strip(),
                    json_dumps(key_assumptions or []),
                    json_dumps(assumption_refs or []),
                    json_dumps(reference_class_refs or []),
                    json_dumps(evidence_refs or []),
                    json_dumps(model_run_refs or []),
                    parent_forecast_id,
                    forecast_origin,
                    agent_model,
                    prompt_version,
                    forecasting_protocol_version or FORECASTING_PROTOCOL_VERSION,
                    toolset_version,
                    json_dumps(source_snapshot_refs or []),
                    cutoff_ts,
                    backtest_run_id,
                    1 if calibration_eligible else 0,
                    calibration_weight,
                    json_dumps(calibration_lesson_refs or []),
                    json_dumps(calibration_adjustment or {}),
                    json_dumps(snapshot_metadata),
                    json_dumps(reasons_up_list),
                    json_dumps(reasons_down_list),
                    json_dumps(change_my_mind_list),
                ),
            )
            if set_current:
                conn.execute(
                    "UPDATE forecast_questions SET current_forecast_id = ? WHERE id = ?",
                    (forecast_id, question_id),
                )
        if panel_run_ref:
            self.attach_panel_to_snapshot(panel_run_ref, forecast_id)
        return self.get_snapshot(forecast_id)

    def get_snapshot(self, forecast_id: str) -> ForecastSnapshot:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forecast_snapshots WHERE forecast_id = ?",
                (forecast_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"forecast snapshot not found: {forecast_id}")
        return self._row_to_snapshot(row)

    def get_current_snapshot(self, question_id: str) -> ForecastSnapshot | None:
        question = self.get_question(question_id)
        if not question.current_forecast_id:
            return None
        return self.get_snapshot(question.current_forecast_id)

    def list_snapshots(self, question_id: str) -> list[ForecastSnapshot]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM forecast_snapshots WHERE question_id = ? ORDER BY created_at ASC",
                (question_id,),
            ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def add_evidence(
        self,
        *,
        question_id: str,
        source_or_note: str,
        claim: str = "",
        summary: str = "",
        source_url: str | None = None,
        source_name: str | None = None,
        source_type: str | None = None,
        published_at: str | None = None,
        available_at: str | None = None,
        reliability_rating: float | None = None,
        relevance_rating: float | None = None,
        stance: str = "context",
        claim_type: str = "fact",
        snapshot_path: str | None = None,
        admissible_for_backtests: bool = True,
        metadata: dict[str, Any] | None = None,
        archive_url_snapshot: bool = True,
    ) -> EvidenceItem:
        self.get_question(question_id)
        source_or_note = source_or_note.strip()
        if not source_or_note and not source_url:
            raise ValidationError("evidence requires a URL or note")
        if reliability_rating is not None and not (0 <= reliability_rating <= 1):
            raise ValidationError("reliability_rating must be between 0 and 1")
        if relevance_rating is not None and not (0 <= relevance_rating <= 1):
            raise ValidationError("relevance_rating must be between 0 and 1")
        if claim_type not in EVIDENCE_CLAIM_TYPES:
            raise ValidationError(f"claim_type must be one of {', '.join(sorted(EVIDENCE_CLAIM_TYPES))}")

        inferred_url = source_url
        inferred_summary = summary
        inferred_type = source_type
        source_file_path: Path | None = None
        if source_or_note.startswith(("http://", "https://")):
            inferred_url = inferred_url or source_or_note
            inferred_type = inferred_type or "url"
        elif Path(source_or_note).expanduser().is_file():
            evidence_path = Path(source_or_note).expanduser()
            source_file_path = evidence_path
            inferred_type = inferred_type or "file"
            source_name = source_name or str(evidence_path)
            inferred_summary = inferred_summary or f"File evidence: {evidence_path.name}"
        else:
            inferred_summary = inferred_summary or source_or_note
            inferred_type = inferred_type or "manual_note"

        now = utc_now_iso()
        available = (
            parse_timestamp(available_at, field_name="available_at")
            or parse_timestamp(published_at, field_name="published_at")
            or now
        )
        evidence_id = f"ev_{uuid.uuid4().hex[:12]}"
        evidence_metadata = dict(metadata or {})
        if source_file_path is not None and snapshot_path is None:
            snapshot_path = self._archive_file_evidence_snapshot(
                question_id=question_id,
                evidence_id=evidence_id,
                source_file_path=source_file_path,
            )
            evidence_metadata.setdefault("source_file_path", str(source_file_path))
        elif (
            inferred_url
            and snapshot_path is None
            and archive_url_snapshot
            # Structured source adapters (source_type="adapter:fred", etc.) already
            # capture the authoritative observation in metadata; fetching the
            # source's HTML page to archive a snapshot adds ~5s/row of latency and
            # no data value (and on batch imports surfaced as "FRED refresh timed
            # out"). Skip archival for adapter-sourced evidence.
            and not str(inferred_type or "").startswith("adapter:")
        ):
            archived_url_snapshot = self._archive_url_evidence_snapshot(
                question_id=question_id,
                evidence_id=evidence_id,
                source_url=inferred_url,
            )
            if archived_url_snapshot is not None:
                snapshot_path = archived_url_snapshot["snapshot_path"]
                evidence_metadata.setdefault("source_snapshot", archived_url_snapshot)
                if archived_url_snapshot.get("blocked"):
                    # Surface at top-level so list_evidence / show_question can
                    # see "blocked" without opening the snapshot file. The
                    # nested source_snapshot keeps the full diagnostic.
                    evidence_metadata.setdefault("blocked", True)
                    evidence_metadata.setdefault(
                        "block_reason", archived_url_snapshot.get("block_reason")
                    )
                    evidence_metadata.setdefault(
                        "block_signal", archived_url_snapshot.get("block_signal")
                    )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evidence_items (
                    id, question_id, captured_at, available_at, source_url,
                    source_name, source_type, published_at, claim, summary,
                    reliability_rating, relevance_rating, stance, claim_type, snapshot_path,
                    admissible_for_backtests, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    question_id,
                    now,
                    available,
                    inferred_url,
                    source_name,
                    inferred_type or "manual_note",
                    parse_timestamp(published_at, field_name="published_at"),
                    claim,
                    inferred_summary,
                    reliability_rating,
                    relevance_rating,
                    stance,
                    claim_type,
                    snapshot_path,
                    1 if admissible_for_backtests else 0,
                    json_dumps(evidence_metadata),
                ),
            )
        return self.get_evidence(evidence_id)

    def get_evidence(self, evidence_id: str) -> EvidenceItem:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evidence_items WHERE id = ?", (evidence_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"evidence item not found: {evidence_id}")
        return self._row_to_evidence(row)

    def list_evidence(self, question_id: str) -> list[EvidenceItem]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_items WHERE question_id = ? ORDER BY available_at ASC",
                (question_id,),
            ).fetchall()
        return [self._row_to_evidence(row) for row in rows]

    def existing_evidence_keys(self, question_id: str) -> set[tuple[str, str]]:
        """Return ``{(source_type, entry_id)}`` for evidence already imported for
        the question. Used to skip re-importing identical structured readings
        (e.g. the same FRED observation) on every refresh, which otherwise bloats
        the evidence table. Items without an ``entry_id`` (e.g. free-form notes)
        are never deduped."""
        keys: set[tuple[str, str]] = set()
        for item in self.list_evidence(question_id):
            entry_id = (item.metadata or {}).get("entry_id")
            if entry_id:
                keys.add((item.source_type or "", str(entry_id)))
        return keys

    def find_stale_evidence_refs(
        self,
        question_id: str,
        evidence_refs: list[str],
        *,
        as_of: str | None = None,
        stale_days: int = 30,
    ) -> list[EvidenceItem]:
        if stale_days < 0:
            raise ValidationError("stale_days must be non-negative")
        as_of_ts = parse_timestamp(as_of, field_name="as_of") or utc_now_iso()
        as_of_dt = timestamp_to_datetime(as_of_ts)
        assert as_of_dt is not None
        stale: list[EvidenceItem] = []
        for evidence_id in evidence_refs:
            evidence = self.get_evidence(evidence_id)
            if evidence.question_id != question_id:
                raise ValidationError(f"evidence item {evidence_id} does not belong to question {question_id}")
            available_dt = timestamp_to_datetime(evidence.available_at)
            if available_dt and (as_of_dt - available_dt).days >= stale_days:
                stale.append(evidence)
        return stale

    def create_ingest_candidate(
        self,
        *,
        source: str,
        title: str | None = None,
        description: str = "",
        resolution_criteria: str = "",
        resolution_source: str | None = None,
        outcome_space: OutcomeSpace | None = None,
        close_time: str | None = None,
        resolution_time: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source = source.strip()
        if not source:
            raise ValidationError("ingest source is required")
        candidate_id = f"ic_{uuid.uuid4().hex[:12]}"
        source_type = self._infer_ingest_source_type(source)
        extracted = self._extract_ingest_metadata(source, source_type)
        candidate_title = (
            title
            or extracted.get("title")
            or self._candidate_title_from_source(source, source_type)
        ).strip()
        candidate_description = description or str(extracted.get("description") or "")
        candidate_resolution_criteria = resolution_criteria or str(extracted.get("resolution_criteria") or "")
        candidate_resolution_source = resolution_source or extracted.get("resolution_source")
        candidate_close_time = close_time or extracted.get("close_time")
        candidate_resolution_time = resolution_time or extracted.get("resolution_time")
        extracted_outcome = extracted.get("outcome_space")
        outcome = outcome_space or (
            OutcomeSpace.from_dict(extracted_outcome) if isinstance(extracted_outcome, dict) else OutcomeSpace()
        )
        candidate_metadata = dict(extracted.get("metadata") or {})
        candidate_metadata.update(metadata or {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_candidates (
                    id, source, source_type, created_at, candidate_title,
                    description, resolution_criteria, resolution_source,
                    close_time, resolution_time, outcome_space, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    source,
                    source_type,
                    utc_now_iso(),
                    candidate_title,
                    candidate_description,
                    candidate_resolution_criteria,
                    candidate_resolution_source,
                    parse_timestamp(candidate_close_time, field_name="close_time"),
                    parse_timestamp(candidate_resolution_time, field_name="resolution_time"),
                    outcome.to_json(),
                    json_dumps(candidate_metadata),
                ),
            )
        return self.get_ingest_candidate(candidate_id)

    def get_ingest_candidate(self, candidate_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ingest_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"ingest candidate not found: {candidate_id}")
        return self._row_to_ingest_candidate(row)

    def list_ingest_candidates(self, *, status: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM ingest_candidates {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self._row_to_ingest_candidate(row) for row in rows]

    def confirm_ingest_candidate(
        self,
        candidate_id: str,
        *,
        title: str | None = None,
        resolution_criteria: str | None = None,
        domain: str | None = None,
        tags: list[str] | None = None,
        topics: list[str] | None = None,
    ) -> ForecastQuestion:
        candidate = self.get_ingest_candidate(candidate_id)
        if candidate["status"] != "proposed":
            raise ValidationError("only proposed ingest candidates can be confirmed")
        final_title = title or candidate["candidate_title"]
        final_criteria = resolution_criteria if resolution_criteria is not None else candidate["resolution_criteria"]
        if not final_criteria.strip():
            raise ValidationError("confirmation requires resolution criteria")
        outcome_space = OutcomeSpace.from_dict(candidate["outcome_space"])
        baseline_payloads = self._candidate_baseline_payloads(candidate["metadata"])
        for baseline in baseline_payloads:
            self._validate_probability_payload(self._baseline_probability_value(baseline), outcome_space)
        question = self.create_question(
            title=final_title,
            description=candidate["description"],
            resolution_criteria=final_criteria,
            resolution_source=candidate["resolution_source"],
            outcome_space=outcome_space,
            close_time=candidate["close_time"],
            resolution_time=candidate["resolution_time"],
            tags=tags or ["ingested"],
            domain=domain,
            topics=topics or [],
            metadata={"ingest_candidate_id": candidate_id, "ingest_source": candidate["source"]},
        )
        self.add_evidence(
            question_id=question.id,
            source_or_note=candidate["source"],
            claim="Original ingest source for forecast question.",
            source_type=candidate["source_type"],
            metadata={"ingest_candidate_id": candidate_id},
        )
        for baseline in baseline_payloads:
            self.add_baseline_comparison(
                question_id=question.id,
                source=str(baseline.get("source") or candidate["source_type"]),
                baseline_type=str(baseline.get("baseline_type") or "imported"),
                probability_or_distribution=self._baseline_probability_value(baseline),
                as_of=baseline.get("as_of"),
                metadata={"ingest_candidate_id": candidate_id, "ingest_source": candidate["source"]},
            )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ingest_candidates
                SET status = 'confirmed', confirmed_question_id = ?
                WHERE id = ?
                """,
                (question.id, candidate_id),
            )
        return question

    def add_assumption(
        self,
        *,
        question_id: str,
        text: str,
        status: str = "active",
        check_cadence: str | None = None,
        evidence_refs: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        self.get_question(question_id)
        if not text.strip():
            raise ValidationError("assumption text is required")
        if status not in ASSUMPTION_STATUSES:
            raise ValidationError(f"assumption status must be one of {', '.join(sorted(ASSUMPTION_STATUSES))}")
        assumption_id = f"as_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO assumptions (
                    id, question_id, text, status, created_at,
                    check_cadence, evidence_refs, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assumption_id,
                    question_id,
                    text.strip(),
                    status,
                    utc_now_iso(),
                    check_cadence,
                    json_dumps(evidence_refs or []),
                    notes,
                ),
            )
        return self.get_assumption(assumption_id)

    def update_assumption(
        self,
        assumption_id: str,
        *,
        status: str | None = None,
        last_checked_at: str | None = None,
        invalidated_at: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_assumption(assumption_id)
        new_status = status or current["status"]
        if new_status not in ASSUMPTION_STATUSES:
            raise ValidationError(f"assumption status must be one of {', '.join(sorted(ASSUMPTION_STATUSES))}")
        checked = parse_timestamp(last_checked_at, field_name="last_checked_at") if last_checked_at else current["last_checked_at"]
        invalidated = (
            parse_timestamp(invalidated_at, field_name="invalidated_at")
            if invalidated_at
            else current["invalidated_at"]
        )
        if new_status == "invalidated" and invalidated is None:
            invalidated = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE assumptions
                SET status = ?, last_checked_at = ?, invalidated_at = ?, notes = COALESCE(?, notes)
                WHERE id = ?
                """,
                (new_status, checked, invalidated, notes, assumption_id),
            )
        return self.get_assumption(assumption_id)

    def get_assumption(self, assumption_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM assumptions WHERE id = ?", (assumption_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"assumption not found: {assumption_id}")
        data = dict(row)
        data["evidence_refs"] = json_loads(data["evidence_refs"], [])
        return data

    def list_assumptions(self, question_id: str) -> list[dict[str, Any]]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM assumptions WHERE question_id = ? ORDER BY created_at ASC",
                (question_id,),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["evidence_refs"] = json_loads(data["evidence_refs"], [])
            result.append(data)
        return result

    def add_reference_class(
        self,
        *,
        question_id: str,
        name: str,
        inclusion_criteria: str,
        exclusion_criteria: str = "",
        base_rate: float | None = None,
        base_rate_uncertainty: float | None = None,
        source_refs: list[str] | None = None,
        check_cadence: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        self.get_question(question_id)
        if not name.strip():
            raise ValidationError("reference class name is required")
        if not inclusion_criteria.strip():
            raise ValidationError("reference class inclusion criteria are required")
        if base_rate is not None and not (0 <= base_rate <= 1):
            raise ValidationError("base_rate must be between 0 and 1")
        if base_rate_uncertainty is not None and base_rate_uncertainty < 0:
            raise ValidationError("base_rate_uncertainty must be non-negative")
        reference_class_id = f"rc_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reference_classes (
                    id, question_id, name, inclusion_criteria, exclusion_criteria,
                    base_rate, base_rate_uncertainty, source_refs, created_at,
                    check_cadence, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reference_class_id,
                    question_id,
                    name.strip(),
                    inclusion_criteria.strip(),
                    exclusion_criteria,
                    base_rate,
                    base_rate_uncertainty,
                    json_dumps(source_refs or []),
                    utc_now_iso(),
                    check_cadence,
                    notes,
                ),
            )
        return self.get_reference_class(reference_class_id)

    def update_reference_class(
        self,
        reference_class_id: str,
        *,
        status: str | None = None,
        last_checked_at: str | None = None,
        invalidated_at: str | None = None,
        check_cadence: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_reference_class(reference_class_id)
        new_status = status or current["status"]
        if new_status not in REFERENCE_CLASS_STATUSES:
            raise ValidationError(
                f"reference class status must be one of {', '.join(sorted(REFERENCE_CLASS_STATUSES))}"
            )
        checked = parse_timestamp(last_checked_at, field_name="last_checked_at") if last_checked_at else current["last_checked_at"]
        invalidated = (
            parse_timestamp(invalidated_at, field_name="invalidated_at")
            if invalidated_at
            else current["invalidated_at"]
        )
        if new_status == "invalidated" and invalidated is None:
            invalidated = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reference_classes
                SET status = ?, last_checked_at = ?, invalidated_at = ?,
                    check_cadence = COALESCE(?, check_cadence),
                    notes = COALESCE(?, notes)
                WHERE id = ?
                """,
                (new_status, checked, invalidated, check_cadence, notes, reference_class_id),
            )
        return self.get_reference_class(reference_class_id)

    def get_reference_class(self, reference_class_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reference_classes WHERE id = ?",
                (reference_class_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"reference class not found: {reference_class_id}")
        data = dict(row)
        data["source_refs"] = json_loads(data["source_refs"], [])
        return data

    def list_reference_classes(self, question_id: str) -> list[dict[str, Any]]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reference_classes WHERE question_id = ? ORDER BY created_at ASC",
                (question_id,),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["source_refs"] = json_loads(data["source_refs"], [])
            result.append(data)
        return result

    def record_model_run(
        self,
        *,
        question_id: str,
        model_type: str,
        status: str = "success",
        inputs: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
        code_ref: str | None = None,
        artifact_paths: list[str] | None = None,
        model_version: str | None = None,
        prompt_version: str | None = None,
        data_version: str | None = None,
        evidence_cutoff: str | None = None,
    ) -> dict[str, Any]:
        self.get_question(question_id)
        if not model_type.strip():
            raise ValidationError("model_type is required")
        if status not in {"success", "failure"}:
            raise ValidationError("model run status must be success or failure")
        model_run_id = f"mr_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_runs (
                    id, question_id, created_at, model_type, status, inputs, parameters,
                    output, diagnostics, code_ref, artifact_paths, model_version,
                    prompt_version, data_version, evidence_cutoff
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_run_id,
                    question_id,
                    utc_now_iso(),
                    model_type.strip(),
                    status,
                    json_dumps(inputs or {}),
                    json_dumps(parameters or {}),
                    json_dumps(output or {}),
                    json_dumps(diagnostics or {}),
                    code_ref,
                    json_dumps(artifact_paths or []),
                    model_version,
                    prompt_version,
                    data_version,
                    parse_timestamp(evidence_cutoff, field_name="evidence_cutoff"),
                ),
            )
        return self.get_model_run(model_run_id)

    def get_model_run(self, model_run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM model_runs WHERE id = ?", (model_run_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"model run not found: {model_run_id}")
        return self._row_to_model_run(row)

    def list_model_runs(self, question_id: str) -> list[dict[str, Any]]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_runs WHERE question_id = ? ORDER BY created_at ASC",
                (question_id,),
            ).fetchall()
        return [self._row_to_model_run(row) for row in rows]

    def resolve_question(
        self,
        *,
        question_id: str,
        outcome: Any,
        resolution_source: str | None = None,
        resolution_source_snapshot_ref: str | None = None,
        resolver_type: str = "manual",
        resolution_status: str = "confirmed",
        criteria_satisfied: bool = True,
        confidence: float | None = None,
        confirmed_by: str | None = None,
        resolver_notes: str | None = None,
        correction_ref: str | None = None,
        trusted_policy_id: str | None = None,
        scoreable: bool = True,
        auto_score: bool = True,
    ) -> Resolution:
        self.get_question(question_id)
        if resolution_status not in RESOLUTION_STATUSES:
            raise ValidationError(
                f"resolution_status must be one of {', '.join(sorted(RESOLUTION_STATUSES))}"
            )
        if confidence is not None and not (0 <= confidence <= 1):
            raise ValidationError("resolution confidence must be between 0 and 1")
        if resolution_status == "corrected" and not correction_ref:
            raise ValidationError("corrected resolutions require correction_ref")
        if trusted_policy_id:
            policy = self.get_trusted_resolver_policy(trusted_policy_id)
            if not policy["enabled"]:
                raise ValidationError("trusted resolver policy is disabled")
        now = utc_now_iso()
        resolution_id = f"rs_{uuid.uuid4().hex[:12]}"
        if resolution_source and resolution_source_snapshot_ref is None:
            source_path = Path(resolution_source).expanduser()
            if source_path.is_file():
                resolution_source_snapshot_ref = self._archive_resolution_source_snapshot(
                    question_id=question_id,
                    resolution_id=resolution_id,
                    source_file_path=source_path,
                )
        confirmed_at = now if resolution_status == "confirmed" and criteria_satisfied else None
        disputed_at = now if resolution_status == "disputed" else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO resolutions (
                    id, question_id, resolved_at, outcome, resolution_source,
                    resolution_source_snapshot_ref, resolver_type, resolution_status,
                    criteria_satisfied, confidence, confirmed_at, confirmed_by,
                    resolver_notes, disputed_at, correction_ref, scoreable,
                    trusted_policy_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolution_id,
                    question_id,
                    now,
                    json_dumps(outcome),
                    resolution_source,
                    resolution_source_snapshot_ref,
                    resolver_type,
                    resolution_status,
                    1 if criteria_satisfied else 0,
                    confidence,
                    confirmed_at,
                    confirmed_by,
                    resolver_notes,
                    disputed_at,
                    correction_ref,
                    1 if scoreable else 0,
                    trusted_policy_id,
                ),
            )
            if resolution_status == "confirmed" and criteria_satisfied:
                conn.execute(
                    "UPDATE forecast_questions SET status = 'resolved' WHERE id = ?",
                    (question_id,),
                )
            elif resolution_status == "proposed":
                conn.execute(
                    "UPDATE forecast_questions SET status = 'closed' WHERE id = ? AND status = 'active'",
                    (question_id,),
                )
            if trusted_policy_id and resolution_status == "confirmed":
                conn.execute(
                    "UPDATE trusted_resolver_policies SET last_used_at = ? WHERE id = ?",
                    (now, trusted_policy_id),
                )

        # Auto-score on a confirmed, criteria-satisfied, scoreable resolution so
        # a forecast cannot resolve without a Brier/log score — closing the
        # feedback loop (calibration, postmortems, lessons) automatically. Only
        # scores a committed forecast (origin != "exploratory"); exploratory
        # scratchpad snapshots are never scored. Best-effort: a scoring hiccup
        # must never break the resolution itself, and score_snapshot is
        # idempotent so a later explicit `score` is a no-op.
        if auto_score and resolution_status == "confirmed" and criteria_satisfied and scoreable:
            try:
                snapshot = self.get_current_snapshot(question_id)
                if snapshot is not None and snapshot.forecast_origin != "exploratory":
                    self.score_snapshot(snapshot.forecast_id)
            except Exception:
                logger.debug("auto-score on resolution failed for %s", question_id, exc_info=True)

        return self.get_resolution(resolution_id)

    def get_resolution(self, resolution_id: str) -> Resolution:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM resolutions WHERE id = ?", (resolution_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"resolution not found: {resolution_id}")
        return self._row_to_resolution(row)

    def get_latest_resolution(
        self,
        question_id: str,
        *,
        confirmed_only: bool = False,
    ) -> Resolution | None:
        clauses = ["question_id = ?"]
        params: list[Any] = [question_id]
        if confirmed_only:
            clauses.extend(["resolution_status = 'confirmed'", "criteria_satisfied = 1", "scoreable = 1"])
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM resolutions
                WHERE {' AND '.join(clauses)}
                ORDER BY resolved_at DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._row_to_resolution(row) if row else None

    def score_question(self, question_id: str, *, force: bool = False) -> ScoreRecord:
        snapshot = self.get_current_snapshot(question_id)
        if snapshot is None:
            raise ValidationError("cannot score a question with no forecast snapshot")
        return self.score_snapshot(snapshot.forecast_id, force=force)

    def get_current_score(self, question_id: str) -> ScoreRecord | None:
        """Return the score for the current snapshot against the confirmed
        resolution, if one has already been recorded; else None. Read-only —
        does not trigger scoring."""
        snapshot = self.get_current_snapshot(question_id)
        if snapshot is None:
            return None
        resolution = self.get_latest_resolution(question_id, confirmed_only=True)
        if resolution is None:
            return None
        return self._existing_score(snapshot.forecast_id, resolution.id)

    def score_snapshot(self, forecast_id: str, *, force: bool = False) -> ScoreRecord:
        snapshot = self.get_snapshot(forecast_id)
        question = self.get_question(snapshot.question_id)
        resolution = self.get_latest_resolution(snapshot.question_id, confirmed_only=True)
        if resolution is None:
            raise ValidationError(
                "cannot score until resolution is confirmed, criteria-satisfied, and scoreable"
            )

        if not force:
            existing = self._existing_score(snapshot.forecast_id, resolution.id)
            if existing is not None:
                return existing

        scoring = self._score_forecast_payload(
            snapshot.probability_or_distribution,
            resolution.outcome,
            question.outcome_space,
        )
        score_id = f"sc_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO score_records (
                    id, question_id, forecast_id, resolution_id, scored_at,
                    brier_score, log_score, proper_score, score_rule, calibration_bucket,
                    forecast_horizon_days, domain, forecast_origin,
                    calibration_eligible, calibration_weight, baseline_ref, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    score_id,
                    snapshot.question_id,
                    snapshot.forecast_id,
                    resolution.id,
                    utc_now_iso(),
                    scoring["brier_score"],
                    scoring["log_score"],
                    scoring["proper_score"],
                    scoring["score_rule"],
                    scoring["calibration_bucket"],
                    snapshot.forecast_horizon_days,
                    question.domain,
                    snapshot.forecast_origin,
                    1 if snapshot.calibration_eligible else 0,
                    snapshot.calibration_weight,
                    scoring["notes"],
                ),
            )
        score = self.get_score(score_id)
        if score.calibration_eligible and score.forecast_origin == "live":
            self.update_domain_error_profile(question)
        return score

    def get_score(self, score_id: str) -> ScoreRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM score_records WHERE id = ?", (score_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"score record not found: {score_id}")
        return self._row_to_score(row)

    def list_scores(
        self,
        *,
        domain: str | None = None,
        forecast_origin: str | None = None,
        calibration_eligible: bool | None = None,
        horizon: str | None = None,
        bucket: str | None = None,
        include_invalidated: bool = False,
    ) -> list[ScoreRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        if forecast_origin:
            clauses.append("forecast_origin = ?")
            params.append(forecast_origin)
        if calibration_eligible is not None:
            clauses.append("calibration_eligible = ?")
            params.append(1 if calibration_eligible else 0)
        if bucket:
            clauses.append("calibration_bucket = ?")
            params.append(bucket)
        if not include_invalidated:
            clauses.append("invalidated_by_correction_id IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM score_records {where} ORDER BY scored_at DESC",
                params,
            ).fetchall()
        return [
            score
            for score in (self._row_to_score(row) for row in rows)
            if self._horizon_matches(score.forecast_horizon_days, horizon)
        ]

    def calibration_summary(
        self,
        *,
        domain: str | None = None,
        forecast_origin: str | None = None,
        horizon: str | None = None,
        calibration_eligible: bool | None = True,
    ) -> dict[str, Any]:
        all_scores = self.list_scores(
            domain=domain,
            forecast_origin=forecast_origin,
            calibration_eligible=calibration_eligible,
        )
        scores = [
            score
            for score in all_scores
            if self._horizon_matches(score.forecast_horizon_days, horizon)
        ]
        buckets: dict[str, list[float]] = defaultdict(list)
        # Reliability-diagram accumulators, keyed by P(yes) decile (0..9). For
        # binary questions we record the forecast's P(yes) and the realized
        # outcome (1.0 yes / 0.0 no) so we can compare predicted vs observed
        # frequency and compute the Expected Calibration Error.
        curve_bins: dict[int, dict[str, list[float]]] = defaultdict(
            lambda: {"predicted": [], "observed": []}
        )
        sharpness_values: list[float] = []
        probability_movements: list[float] = []
        question_type_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "brier": [],
                "log": [],
                "proper": [],
                "sharpness": [],
                "score_rules": set(),
                "score_count": 0,
            }
        )
        component_stats: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: {
                "probability": [],
                "weight": [],
                "weight_share": [],
                "contribution": [],
                "distance_from_forecast": [],
            }
        )
        for score in scores:
            outcome_space = None
            try:
                outcome_space = self.get_question(score.question_id).outcome_space
                question_type = outcome_space.type
            except LedgerNotFoundError:
                question_type = "unknown"
            type_stats = question_type_stats[question_type]
            type_stats["score_count"] += 1
            if score.brier_score is not None:
                type_stats["brier"].append(score.brier_score)
            if score.log_score is not None:
                type_stats["log"].append(score.log_score)
            if score.proper_score is not None:
                type_stats["proper"].append(score.proper_score)
            if score.score_rule:
                type_stats["score_rules"].add(score.score_rule)
            if score.brier_score is not None:
                buckets[score.calibration_bucket or "unknown"].append(score.brier_score)
            try:
                snapshot = self.get_snapshot(score.forecast_id)
            except LedgerNotFoundError:
                continue
            if score.brier_score is None:
                continue
            sharpness = self._sharpness(snapshot.probability_or_distribution)
            if sharpness is not None:
                sharpness_values.append(sharpness)
                type_stats["sharpness"].append(sharpness)
            # Reliability point: bin the binary forecast by P(yes) and record the
            # realized outcome so observed frequency can be compared to it.
            if (
                outcome_space is not None
                and outcome_space.type == "binary"
                and isinstance(snapshot.probability_or_distribution, (int, float))
            ):
                observed = self._binary_outcome_value(score, outcome_space)
                if observed is not None:
                    p_yes = float(snapshot.probability_or_distribution)
                    decile = min(int(p_yes * 10), 9)
                    curve_bins[decile]["predicted"].append(p_yes)
                    curve_bins[decile]["observed"].append(observed)
            movement = self._score_probability_movement_before_close(score, snapshot)
            if movement is not None:
                probability_movements.append(movement)
            for component in self._snapshot_component_contributions(snapshot):
                stats = component_stats[component["name"]]
                stats["probability"].append(component["probability"])
                stats["weight"].append(component["weight"])
                stats["weight_share"].append(component["weight_share"])
                stats["contribution"].append(component["contribution"])
                if component["distance_from_forecast"] is not None:
                    stats["distance_from_forecast"].append(component["distance_from_forecast"])
        bucket_rows = []
        canonical_buckets = [f"{i / 10:.1f}-{(i + 1) / 10:.1f}" for i in range(10)]
        ordered_buckets = canonical_buckets + sorted(
            bucket for bucket in buckets if bucket not in canonical_buckets
        )
        for bucket in ordered_buckets:
            values = buckets.get(bucket, [])
            bucket_rows.append(
                {
                    "bucket": bucket,
                    "count": len(values),
                    "mean_brier": sum(values) / len(values) if values else None,
                    "sample_status": "empty" if not values else ("low_sample" if len(values) < 5 else "ok"),
                }
            )
        all_values = [score.brier_score for score in scores if score.brier_score is not None]
        log_values = [score.log_score for score in scores if score.log_score is not None]
        component_rows = [
            {
                "name": name,
                "count": len(stats["contribution"]),
                "mean_probability": self._mean(stats["probability"]),
                "mean_weight": self._mean(stats["weight"]),
                "mean_weight_share": self._mean(stats["weight_share"]),
                "mean_contribution": self._mean(stats["contribution"]),
                "mean_abs_distance_from_forecast": self._mean(
                    [abs(value) for value in stats["distance_from_forecast"]]
                ),
            }
            for name, stats in component_stats.items()
            if stats["contribution"]
        ]
        question_type_rows = [
            {
                "question_type": question_type,
                "count": int(stats["score_count"]),
                "brier_count": len(stats["brier"]),
                "mean_brier": self._mean(stats["brier"]),
                "mean_log_score": self._mean(stats["log"]),
                "mean_proper_score": self._mean(stats["proper"]),
                "mean_sharpness": self._mean(stats["sharpness"]),
                "score_rules": sorted(stats["score_rules"]),
            }
            for question_type, stats in question_type_stats.items()
        ]
        # Reliability curve on P(yes) + Expected/Max Calibration Error. ECE is the
        # sample-weighted mean gap between observed frequency and mean predicted
        # probability across the populated deciles; MCE is the worst single gap.
        curve_rows = []
        ece_numerator = 0.0
        ece_denominator = 0
        max_calibration_error = 0.0
        for index in range(10):
            data = curve_bins.get(index)
            predicted = data["predicted"] if data else []
            observed = data["observed"] if data else []
            count = len(observed)
            mean_predicted = sum(predicted) / count if count else None
            observed_frequency = sum(observed) / count if count else None
            gap = (
                abs(observed_frequency - mean_predicted)
                if count and mean_predicted is not None
                else None
            )
            curve_rows.append(
                {
                    "bucket": f"{index / 10:.1f}-{(index + 1) / 10:.1f}",
                    "count": count,
                    "mean_predicted": mean_predicted,
                    "observed_frequency": observed_frequency,
                    "calibration_gap": gap,
                    "sample_status": "empty"
                    if not count
                    else ("low_sample" if count < 5 else "ok"),
                }
            )
            if count and gap is not None:
                ece_numerator += count * gap
                ece_denominator += count
                max_calibration_error = max(max_calibration_error, gap)
        expected_calibration_error = (
            ece_numerator / ece_denominator if ece_denominator else None
        )
        curve_predicted = [
            value for data in curve_bins.values() for value in data["predicted"]
        ]
        curve_observed = [
            value for data in curve_bins.values() for value in data["observed"]
        ]
        return {
            "count": len(all_values),
            "mean_brier": sum(all_values) / len(all_values) if all_values else None,
            "mean_log_score": sum(log_values) / len(log_values) if log_values else None,
            "mean_sharpness": sum(sharpness_values) / len(sharpness_values) if sharpness_values else None,
            "probability_movement_count": len(probability_movements),
            "mean_probability_movement_before_close": (
                sum(probability_movements) / len(probability_movements)
                if probability_movements
                else None
            ),
            "mean_abs_probability_movement_before_close": (
                sum(abs(value) for value in probability_movements) / len(probability_movements)
                if probability_movements
                else None
            ),
            "ensemble_component_contributions": sorted(
                component_rows,
                key=lambda row: (-row["count"], -(row["mean_contribution"] or 0.0), row["name"]),
            ),
            "question_type_breakdown": sorted(
                question_type_rows,
                key=lambda row: (-row["count"], row["question_type"]),
            ),
            "buckets": bucket_rows,
            "calibration_curve": curve_rows,
            "expected_calibration_error": expected_calibration_error,
            "max_calibration_error": max_calibration_error if ece_denominator else None,
            "calibration_curve_sample_count": ece_denominator,
            "mean_predicted": (
                sum(curve_predicted) / len(curve_predicted) if curve_predicted else None
            ),
            "observed_frequency": (
                sum(curve_observed) / len(curve_observed) if curve_observed else None
            ),
            "domain": domain,
            "forecast_origin": forecast_origin,
            "horizon": horizon,
            "calibration_eligible": calibration_eligible,
        }

    def create_postmortem(
        self,
        *,
        question_id: str,
        summary: str = "",
        what_happened: str = "",
        what_was_expected: str = "",
        missed_evidence: str = "",
        overweighted_evidence: str = "",
        base_rate_error: str = "",
        inside_view_error: str = "",
        resolution_error: str = "",
        lesson: str = "",
        calibration_adjustment: dict[str, Any] | None = None,
        failure_class: str | None = None,
    ) -> dict[str, Any]:
        question = self.get_question(question_id)
        if failure_class is not None:
            failure_class = failure_class.strip().lower() or None
            if failure_class and failure_class not in FAILURE_CLASSES:
                raise ValidationError(
                    f"failure_class must be one of {', '.join(sorted(FAILURE_CLASSES))}"
                )
        score = self.score_question(question_id)
        snapshot = self.get_snapshot(score.forecast_id)
        resolution = self.get_resolution(score.resolution_id)
        postmortem_id = f"pm_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO postmortems (
                    id, question_id, forecast_id, resolution_id, score_record_id,
                    forecast_origin, calibration_eligible, created_at, summary,
                    what_happened, what_was_expected, missed_evidence,
                    overweighted_evidence, base_rate_error, inside_view_error,
                    resolution_error, lesson, calibration_adjustment, failure_class
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    postmortem_id,
                    question_id,
                    snapshot.forecast_id,
                    resolution.id,
                    score.id,
                    score.forecast_origin,
                    1 if score.calibration_eligible else 0,
                    utc_now_iso(),
                    summary or f"Resolved outcome was {resolution.outcome!r}.",
                    what_happened or f"Resolution recorded outcome {resolution.outcome!r}.",
                    what_was_expected or f"Forecast probability was {snapshot.probability_or_distribution!r}.",
                    missed_evidence,
                    overweighted_evidence,
                    base_rate_error,
                    inside_view_error,
                    resolution_error,
                    lesson,
                    json_dumps(calibration_adjustment or {}),
                    failure_class,
                ),
            )
        postmortem = self.get_postmortem(postmortem_id)
        if lesson and score.calibration_eligible:
            self.create_calibration_lesson(
                scope_type="domain" if question.domain else "global",
                scope_ref=question.domain,
                lesson=lesson,
                confidence=0.5,
                recommended_adjustment=calibration_adjustment or {},
                source_postmortem_refs=[postmortem_id],
                source_score_record_refs=[score.id],
                status="tentative",
            )
        self.update_domain_error_profile(question)
        return postmortem

    def get_postmortem(self, postmortem_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM postmortems WHERE id = ?", (postmortem_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"postmortem not found: {postmortem_id}")
        data = dict(row)
        data["calibration_eligible"] = bool(data["calibration_eligible"])
        data["calibration_adjustment"] = json_loads(data["calibration_adjustment"], {})
        data.setdefault("failure_class", None)
        return data

    def list_postmortems(
        self,
        question_id: str | None = None,
        *,
        include_invalidated: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        if not include_invalidated:
            clauses.append("invalidated_by_correction_id IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM postmortems {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["calibration_eligible"] = bool(data["calibration_eligible"])
            data["calibration_adjustment"] = json_loads(data["calibration_adjustment"], {})
            data.setdefault("failure_class", None)
            result.append(data)
        return result

    # ── Forecast panel ─────────────────────────────────────────────────────

    def record_panel_run(
        self,
        *,
        question_id: str,
        estimates: list[dict[str, Any]],
        aggregation_method: str = "trimmed_geomean_odds",
        trim: int = 1,
        snapshot_id: str | None = None,
        triggered_by: str | None = None,
        perspectives: list[str] | None = None,
    ) -> dict[str, Any]:
        """Aggregate a panel of perspective estimates and persist the artifact.

        Returns the panel-run record dict (including aggregate_probability,
        spread_summary, trimmed flags, and per-estimate ids). The caller
        typically passes the resulting ``aggregate_probability`` into
        :meth:`create_snapshot` and the panel run id into the snapshot's
        ``ensemble_components`` or ``metadata``.
        """

        from forecasting.panel import aggregate_panel_estimates  # local import to avoid cycle

        self.get_question(question_id)
        if snapshot_id is not None:
            self.get_snapshot(snapshot_id)
        aggregation = aggregate_panel_estimates(
            estimates,
            method=aggregation_method,
            trim=trim,
        )
        now = utc_now_iso()
        run_id = f"pr_{uuid.uuid4().hex[:12]}"
        requested = perspectives if perspectives is not None else [
            row["perspective"] for row in aggregation.estimates
        ]
        estimate_records: list[dict[str, Any]] = []
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO panel_runs (
                    id, question_id, created_at, snapshot_id,
                    aggregation_method, trim, aggregate_probability,
                    perspectives, spread_summary, notes, triggered_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    question_id,
                    now,
                    snapshot_id,
                    aggregation.method,
                    aggregation.trim,
                    float(aggregation.aggregate_probability),
                    json_dumps(list(requested)),
                    json_dumps(aggregation.spread),
                    json_dumps(aggregation.notes),
                    triggered_by,
                ),
            )
            for row in aggregation.estimates:
                estimate_id = f"pe_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO panel_estimates (
                        id, panel_run_id, question_id, created_at, perspective,
                        probability, weight, trimmed, confidence_low, confidence_high,
                        rationale, reasons_up, reasons_down, change_my_mind, crux,
                        agent_model, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        estimate_id,
                        run_id,
                        question_id,
                        now,
                        row["perspective"],
                        float(row["probability"]),
                        float(row["weight"]),
                        1 if row.get("trimmed") else 0,
                        row.get("confidence_low"),
                        row.get("confidence_high"),
                        row.get("rationale") or "",
                        json_dumps(row.get("reasons_up") or []),
                        json_dumps(row.get("reasons_down") or []),
                        json_dumps(row.get("change_my_mind") or []),
                        row.get("crux"),
                        row.get("agent_model"),
                        json_dumps(row.get("metadata") or {}),
                    ),
                )
                estimate_records.append({"id": estimate_id, **row})
        return self.get_panel_run(run_id)

    def get_panel_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM panel_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise LedgerNotFoundError(f"panel run not found: {run_id}")
            estimates = conn.execute(
                """
                SELECT * FROM panel_estimates
                WHERE panel_run_id = ?
                ORDER BY perspective ASC
                """,
                (run_id,),
            ).fetchall()
        return self._panel_run_dict(row, estimates)

    def list_panel_runs(
        self,
        question_id: str | None = None,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM panel_runs {where} ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                estimates = conn.execute(
                    """
                    SELECT * FROM panel_estimates
                    WHERE panel_run_id = ?
                    ORDER BY perspective ASC
                    """,
                    (row["id"],),
                ).fetchall()
                results.append(self._panel_run_dict(row, estimates))
        return results

    def attach_panel_to_snapshot(self, panel_run_id: str, snapshot_id: str) -> dict[str, Any]:
        self.get_panel_run(panel_run_id)
        self.get_snapshot(snapshot_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE panel_runs SET snapshot_id = ? WHERE id = ?",
                (snapshot_id, panel_run_id),
            )
        return self.get_panel_run(panel_run_id)

    def _panel_run_dict(
        self,
        row: sqlite3.Row,
        estimates_rows: list[sqlite3.Row],
    ) -> dict[str, Any]:
        data = dict(row)
        data["perspectives"] = json_loads(data["perspectives"], [])
        data["spread_summary"] = json_loads(data["spread_summary"], {})
        data["notes"] = json_loads(data["notes"], [])
        data["estimates"] = [self._panel_estimate_dict(e) for e in estimates_rows]
        return data

    def _panel_estimate_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["trimmed"] = bool(data["trimmed"])
        data["reasons_up"] = json_loads(data["reasons_up"], [])
        data["reasons_down"] = json_loads(data["reasons_down"], [])
        data["change_my_mind"] = json_loads(data["change_my_mind"], [])
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def create_calibration_lesson(
        self,
        *,
        scope_type: str,
        scope_ref: str | None,
        lesson: str,
        confidence: float | None = None,
        recommended_adjustment: dict[str, Any] | None = None,
        source_postmortem_refs: list[str] | None = None,
        source_score_record_refs: list[str] | None = None,
        status: str = "tentative",
        supersedes_lesson_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if scope_type not in {"domain", "topic", "horizon", "question_type", "model_component", "global"}:
            raise ValidationError("invalid calibration lesson scope_type")
        if status not in CALIBRATION_LESSON_STATUSES:
            raise ValidationError(
                f"calibration lesson status must be one of {', '.join(sorted(CALIBRATION_LESSON_STATUSES))}"
            )
        if not lesson.strip():
            raise ValidationError("calibration lesson text is required")
        if confidence is not None and not (0 <= confidence <= 1):
            raise ValidationError("calibration lesson confidence must be between 0 and 1")
        now = utc_now_iso()
        lesson_id = f"cl_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO calibration_lessons (
                    id, scope_type, scope_ref, created_at, updated_at, status,
                    confidence, lesson, recommended_adjustment,
                    source_postmortem_refs, source_score_record_refs,
                    supersedes_lesson_id, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lesson_id,
                    scope_type,
                    scope_ref,
                    now,
                    now,
                    status,
                    confidence,
                    lesson.strip(),
                    json_dumps(recommended_adjustment or {}),
                    json_dumps(source_postmortem_refs or []),
                    json_dumps(source_score_record_refs or []),
                    supersedes_lesson_id,
                    json_dumps(metadata or {}),
                ),
            )
        return self.get_calibration_lesson(lesson_id)

    def get_calibration_lesson(self, lesson_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM calibration_lessons WHERE id = ?",
                (lesson_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"calibration lesson not found: {lesson_id}")
        return self._row_to_calibration_lesson(row)

    def update_calibration_lesson(
        self,
        lesson_id: str,
        *,
        status: str | None = None,
        confidence: float | None = None,
        recommended_adjustment: dict[str, Any] | None = None,
        supersedes_lesson_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.get_calibration_lesson(lesson_id)
        new_status = status or current["status"]
        if new_status not in CALIBRATION_LESSON_STATUSES:
            raise ValidationError(
                f"calibration lesson status must be one of {', '.join(sorted(CALIBRATION_LESSON_STATUSES))}"
            )
        if confidence is not None and not (0 <= confidence <= 1):
            raise ValidationError("calibration lesson confidence must be between 0 and 1")
        if current.get("invalidated_by_correction_id") and new_status == "active":
            raise ValidationError("invalidated calibration lessons cannot be activated")
        if supersedes_lesson_id:
            self.get_calibration_lesson(supersedes_lesson_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE calibration_lessons
                SET status = ?, confidence = COALESCE(?, confidence),
                    recommended_adjustment = ?,
                    supersedes_lesson_id = COALESCE(?, supersedes_lesson_id),
                    metadata = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_status,
                    confidence,
                    json_dumps(recommended_adjustment if recommended_adjustment is not None else current["recommended_adjustment"]),
                    supersedes_lesson_id,
                    json_dumps(metadata if metadata is not None else current["metadata"]),
                    utc_now_iso(),
                    lesson_id,
                ),
            )
        return self.get_calibration_lesson(lesson_id)

    def list_calibration_lessons(
        self,
        *,
        scope_type: str | None = None,
        scope_ref: str | None = None,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if scope_type:
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if scope_ref:
            clauses.append("scope_ref = ?")
            params.append(scope_ref)
        if active_only:
            clauses.append("status = 'active'")
            clauses.append("invalidated_by_correction_id IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM calibration_lessons {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [self._row_to_calibration_lesson(row) for row in rows]

    def create_correction(
        self,
        *,
        target_type: str,
        target_id: str,
        reason: str,
        created_by: str | None = None,
        old_value: Any = None,
        new_value: Any = None,
        patch: dict[str, Any] | None = None,
        status: str = "proposed",
    ) -> dict[str, Any]:
        allowed = {
            "forecast_snapshot",
            "evidence_item",
            "assumption",
            "reference_class",
            "resolution",
            "score_record",
            "postmortem",
            "calibration_lesson",
        }
        if target_type not in allowed:
            raise ValidationError(f"target_type must be one of {', '.join(sorted(allowed))}")
        if status not in {"proposed", "applied", "rejected"}:
            raise ValidationError("correction status must be proposed, applied, or rejected")
        if not reason.strip():
            raise ValidationError("correction reason is required")
        correction_id = f"fc_{uuid.uuid4().hex[:12]}"
        affected_scores, affected_postmortems, affected_lessons = self._affected_records_for_correction(
            target_type,
            target_id,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO forecast_corrections (
                    id, target_type, target_id, created_at, created_by, reason,
                    old_value, new_value, patch, affected_score_record_refs,
                    affected_postmortem_refs, affected_calibration_lesson_refs,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    correction_id,
                    target_type,
                    target_id,
                    utc_now_iso(),
                    created_by,
                    reason.strip(),
                    json_dumps(old_value),
                    json_dumps(new_value),
                    json_dumps(patch or {}),
                    json_dumps(affected_scores),
                    json_dumps(affected_postmortems),
                    json_dumps(affected_lessons),
                    status,
                ),
            )
            if status == "applied":
                self._invalidate_learning_records_for_correction(
                    conn,
                    correction_id=correction_id,
                    score_refs=affected_scores,
                    postmortem_refs=affected_postmortems,
                    lesson_refs=affected_lessons,
                )
        if affected_scores or affected_postmortems or affected_lessons:
            self.create_alert(
                severity="high",
                scope_type=target_type,
                scope_ref=target_id,
                reason="correction_affects_learning_records",
                recommended_action="Review affected scores, postmortems, and calibration lessons before relying on them.",
            )
        return self.get_correction(correction_id)

    def get_correction(self, correction_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forecast_corrections WHERE id = ?",
                (correction_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"correction not found: {correction_id}")
        data = dict(row)
        for field in (
            "old_value",
            "new_value",
            "patch",
            "affected_score_record_refs",
            "affected_postmortem_refs",
            "affected_calibration_lesson_refs",
        ):
            data[field] = json_loads(data[field], {} if field in {"old_value", "new_value", "patch"} else [])
        return data

    def list_corrections(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if target_type:
            clauses.append("target_type = ?")
            params.append(target_type)
        if target_id:
            clauses.append("target_id = ?")
            params.append(target_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM forecast_corrections {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self.get_correction(row["id"]) for row in rows]

    def create_trusted_resolver_policy(
        self,
        *,
        resolver_plugin: str,
        plugin_version: str | None,
        scope_type: str,
        scope_ref: str | None = None,
        enabled: bool = False,
        approved_by: str | None = None,
        audit_log_ref: str | None = None,
    ) -> dict[str, Any]:
        if not resolver_plugin.strip():
            raise ValidationError("resolver_plugin is required")
        if scope_type not in {"domain", "topic", "source", "question_type", "global"}:
            raise ValidationError("resolver policy scope_type must be domain, topic, source, question_type, or global")
        policy_id = f"trp_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trusted_resolver_policies (
                    id, resolver_plugin, plugin_version, scope_type, scope_ref,
                    enabled, created_at, approved_by, audit_log_ref
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    resolver_plugin.strip(),
                    plugin_version,
                    scope_type,
                    scope_ref,
                    1 if enabled else 0,
                    utc_now_iso(),
                    approved_by,
                    audit_log_ref,
                ),
            )
        return self.get_trusted_resolver_policy(policy_id)

    def get_trusted_resolver_policy(self, policy_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trusted_resolver_policies WHERE id = ?",
                (policy_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"trusted resolver policy not found: {policy_id}")
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        return data

    def list_trusted_resolver_policies(
        self,
        *,
        resolver_plugin: str | None = None,
        scope_type: str | None = None,
        enabled: bool | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if resolver_plugin:
            clauses.append("resolver_plugin = ?")
            params.append(resolver_plugin)
        if scope_type:
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if enabled is not None:
            clauses.append("enabled = ?")
            params.append(1 if enabled else 0)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM trusted_resolver_policies {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["enabled"] = bool(data["enabled"])
            result.append(data)
        return result

    def update_domain_error_profile(self, question: ForecastQuestion) -> dict[str, Any] | None:
        domain = question.domain
        if not domain:
            return None
        domain_scores = self.list_scores(domain=domain, calibration_eligible=True)
        domain_profile = self._write_error_profile(
            domain=domain,
            topic=None,
            question_type=question.outcome_space.type,
            scores=domain_scores,
        )
        for topic in question.topics:
            topic_scores = [
                score
                for score in domain_scores
                if topic in self.get_question(score.question_id).topics
            ]
            self._write_error_profile(
                domain=domain,
                topic=topic,
                question_type=question.outcome_space.type,
                scores=topic_scores,
            )
        return domain_profile

    def _write_error_profile(
        self,
        *,
        domain: str,
        topic: str | None,
        question_type: str,
        scores: list[ScoreRecord],
    ) -> dict[str, Any]:
        brier_values = [score.brier_score for score in scores if score.brier_score is not None]
        postmortems = self._postmortems_for_error_profile(domain=domain, topic=topic)
        error_counts = self._error_counts_for_profile(scores=scores, postmortems=postmortems)
        summary = {
            "count": len(brier_values),
            "mean_brier": sum(brier_values) / len(brier_values) if brier_values else None,
            "postmortem_count": len(postmortems),
            "error_counts": dict(sorted(error_counts.items())),
        }
        recurring_errors: list[str] = []
        if summary["mean_brier"] is not None and summary["mean_brier"] > 0.25:
            recurring_errors.append("elevated_mean_brier")
        recurring_errors.extend(self._recurring_error_tags(error_counts))
        recurring_errors = list(dict.fromkeys(recurring_errors))
        recommended_adjustments = self._recommended_adjustments_for_errors(recurring_errors)
        sample_count = len(brier_values)
        profile_id = self._domain_error_profile_id(domain, topic, None, question_type)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO domain_error_profiles (
                    id, domain, topic, forecast_horizon_bucket, question_type,
                    sample_count, calibration_summary, recurring_errors,
                    recommended_adjustments, updated_at
                )
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    domain,
                    topic,
                    question_type,
                    sample_count,
                    json_dumps(summary),
                    json_dumps(recurring_errors),
                    json_dumps(recommended_adjustments),
                    utc_now_iso(),
                ),
            )
        return self.get_domain_error_profile(profile_id)

    def _postmortems_for_error_profile(
        self,
        *,
        domain: str,
        topic: str | None,
    ) -> list[dict[str, Any]]:
        scoped: list[dict[str, Any]] = []
        for postmortem in self.list_postmortems():
            if not postmortem.get("calibration_eligible"):
                continue
            try:
                question = self.get_question(postmortem["question_id"])
            except LedgerNotFoundError:
                continue
            if question.domain != domain:
                continue
            if topic and topic not in question.topics:
                continue
            scoped.append(postmortem)
        return scoped

    def _error_counts_for_profile(
        self,
        *,
        scores: list[ScoreRecord],
        postmortems: list[dict[str, Any]],
    ) -> Counter[str]:
        counts: Counter[str] = Counter()
        score_tags_by_id: dict[str, set[str]] = defaultdict(set)
        for score in scores:
            if score.brier_score is not None and score.brier_score > 0.25:
                counts["high_brier_miss"] += 1
                score_tags_by_id[score.id].add("high_brier_miss")
            if score.brier_score is not None and score.brier_score >= 0.36:
                try:
                    snapshot = self.get_snapshot(score.forecast_id)
                except LedgerNotFoundError:
                    snapshot = None
                if snapshot is not None:
                    sharpness = self._sharpness(snapshot.probability_or_distribution)
                    if sharpness is not None and sharpness >= 0.6:
                        counts["overconfidence"] += 1
                        score_tags_by_id[score.id].add("overconfidence")
                    for model_run_ref in snapshot.model_run_refs:
                        try:
                            model_run = self.get_model_run(model_run_ref)
                        except LedgerNotFoundError:
                            continue
                        if model_run["status"] == "failure":
                            counts["model_family_failure"] += 1

        field_tags = {
            "missed_evidence": "missed_evidence",
            "overweighted_evidence": "overweighted_evidence",
            "base_rate_error": "base_rate_error",
            "inside_view_error": "inside_view_error",
            "resolution_error": "resolution_error",
        }
        for postmortem in postmortems:
            for field, tag in field_tags.items():
                if str(postmortem.get(field) or "").strip():
                    counts[tag] += 1
            adjustment = postmortem.get("calibration_adjustment") or {}
            if isinstance(adjustment, dict):
                score_id = str(postmortem.get("score_record_id") or "")
                for tag in adjustment.get("error_tags") or []:
                    if not isinstance(tag, str) or not tag.strip():
                        continue
                    normalized = tag.strip()
                    if normalized in score_tags_by_id.get(score_id, set()):
                        continue
                    counts[normalized] += 1
        return counts

    def _recurring_error_tags(self, error_counts: Counter[str]) -> list[str]:
        ordered = [
            "overconfidence",
            "base_rate_error",
            "missed_evidence",
            "overweighted_evidence",
            "inside_view_error",
            "resolution_error",
            "model_family_failure",
            "late_evidence_update",
            "stale_base_rate",
            "high_brier_miss",
        ]
        ordered_set = set(ordered)
        tags = [tag for tag in ordered if error_counts.get(tag, 0) > 0]
        tags.extend(
            tag
            for tag, count in sorted(error_counts.items())
            if count > 0 and tag not in ordered_set
        )
        return tags

    def _recommended_adjustments_for_errors(self, recurring_errors: list[str]) -> list[str]:
        recommendations_by_error = {
            "elevated_mean_brier": "Review postmortems before increasing confidence in this scope.",
            "overconfidence": (
                "Temper high-confidence updates in this scope; require explicit outside-view, "
                "base-rate, and counterevidence checks before extreme probabilities."
            ),
            "base_rate_error": "Refresh reference classes and base rates before updating similar questions.",
            "stale_base_rate": "Shorten base-rate refresh cadence and verify stale reference classes before updates.",
            "missed_evidence": "Expand the source checklist and add watched sources for missing evidence classes.",
            "late_evidence_update": "Shorten review cadence for active questions with fast-moving evidence.",
            "overweighted_evidence": "Downweight single-source narratives until checked against base rates and counterevidence.",
            "inside_view_error": "Separate inside-view arguments from outside-view priors and record the reconciliation.",
            "resolution_error": "Re-read resolution criteria and resolver sources before forecasting similar questions.",
            "model_family_failure": "Review failed model runs before relying on that model family in this scope.",
            "high_brier_miss": "Inspect high-Brier misses before making adjacent forecasts.",
        }
        return [
            recommendations_by_error[tag]
            for tag in recurring_errors
            if tag in recommendations_by_error
        ]

    def get_domain_error_profile(self, profile_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM domain_error_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"domain error profile not found: {profile_id}")
        return self._row_to_domain_error_profile(row)

    def list_domain_error_profiles(
        self,
        *,
        domain: str | None = None,
        topic: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        if topic:
            clauses.append("topic = ?")
            params.append(topic)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM domain_error_profiles {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [self._row_to_domain_error_profile(row) for row in rows]

    def add_baseline_comparison(
        self,
        *,
        question_id: str,
        source: str,
        baseline_type: str,
        probability_or_distribution: Any,
        as_of: str | None = None,
        forecast_id: str | None = None,
        backtest_case_id: str | None = None,
        score_record_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        question = self.get_question(question_id)
        payload = self._validate_probability_payload(probability_or_distribution, question.outcome_space)
        if score_record_id is not None:
            self.get_score(score_record_id)
        baseline_id = f"bc_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO baseline_comparisons (
                    id, question_id, forecast_id, backtest_case_id, source,
                    baseline_type, as_of, probability_or_distribution,
                    score_record_id, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    baseline_id,
                    question_id,
                    forecast_id,
                    backtest_case_id,
                    source,
                    baseline_type,
                    parse_timestamp(as_of, field_name="as_of") or utc_now_iso(),
                    json_dumps(payload),
                    score_record_id,
                    json_dumps(metadata or {}),
                ),
            )
            if score_record_id is not None:
                conn.execute(
                    "UPDATE score_records SET baseline_ref = ? WHERE id = ?",
                    (baseline_id, score_record_id),
                )
        return self.get_baseline_comparison(baseline_id)

    def get_baseline_comparison(self, baseline_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM baseline_comparisons WHERE id = ?",
                (baseline_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"baseline comparison not found: {baseline_id}")
        data = dict(row)
        data["probability_or_distribution"] = json_loads(data["probability_or_distribution"], None)
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def list_baseline_comparisons(self, question_id: str) -> list[dict[str, Any]]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM baseline_comparisons WHERE question_id = ? ORDER BY as_of ASC",
                (question_id,),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["probability_or_distribution"] = json_loads(data["probability_or_distribution"], None)
            data["metadata"] = json_loads(data["metadata"], {})
            result.append(data)
        return result

    def score_baseline_comparisons(self, question_id: str, *, force: bool = False) -> list[dict[str, Any]]:
        """Score imported baselines for a resolved live question without moving the current forecast."""

        self.get_question(question_id)
        if self.get_latest_resolution(question_id, confirmed_only=True) is None:
            raise ValidationError(
                "cannot score baseline comparisons until resolution is confirmed, criteria-satisfied, and scoreable"
            )
        scored: list[dict[str, Any]] = []
        for baseline in self.list_baseline_comparisons(question_id):
            if baseline.get("score_record_id") and not force:
                scored.append({**baseline, "score": self.get_score(baseline["score_record_id"])})
                continue
            forecast_id = baseline.get("forecast_id")
            if not forecast_id:
                snapshot = self.create_snapshot(
                    question_id=question_id,
                    probability_or_distribution=baseline["probability_or_distribution"],
                    rationale=f"Imported baseline from {baseline.get('source') or 'unknown source'}.",
                    as_of=baseline.get("as_of"),
                    method=str(baseline.get("baseline_type") or "imported"),
                    forecast_origin="imported_baseline",
                    calibration_eligible=False,
                    calibration_weight=0.0,
                    metadata={
                        "baseline_comparison_id": baseline["id"],
                        "baseline_source": baseline.get("source"),
                    },
                    set_current=False,
                )
                forecast_id = snapshot.forecast_id
            score = self.score_snapshot(forecast_id, force=force)
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE baseline_comparisons
                    SET forecast_id = ?, score_record_id = ?
                    WHERE id = ?
                    """,
                    (forecast_id, score.id, baseline["id"]),
                )
                conn.execute(
                    "UPDATE score_records SET baseline_ref = ? WHERE id = ?",
                    (baseline["id"], score.id),
                )
            updated = self.get_baseline_comparison(baseline["id"])
            scored.append({**updated, "score": score})
        return scored

    def import_benchmark_dataset(
        self,
        *,
        source: str,
        cases: list[dict[str, Any]],
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(cases, list):
            raise ValidationError("benchmark dataset cases must be a list")
        valid_cases = [case for case in cases if isinstance(case, dict)]
        if len(valid_cases) != len(cases):
            raise ValidationError("benchmark dataset cases must be objects")
        dataset_id = f"bd_{uuid.uuid4().hex[:12]}"
        dataset_name = name or Path(str(source)).stem or str(source)
        imported_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO benchmark_datasets (
                    id, name, source, imported_at, case_count,
                    description, cases, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    dataset_name,
                    source,
                    imported_at,
                    len(valid_cases),
                    description,
                    json_dumps(valid_cases),
                    json_dumps(metadata or {}),
                ),
            )
        return self.get_benchmark_dataset(dataset_id)

    def get_benchmark_dataset(self, dataset_id: str) -> dict[str, Any]:
        lookup = dataset_id.removeprefix("imported:")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM benchmark_datasets WHERE id = ?",
                (lookup,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"benchmark dataset not found: {dataset_id}")
        return self._row_to_benchmark_dataset(row)

    def list_benchmark_datasets(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM benchmark_datasets ORDER BY imported_at DESC",
            ).fetchall()
        return [self._row_to_benchmark_dataset(row) for row in rows]

    def run_backtest_dataset(
        self,
        *,
        dataset: str,
        cases: list[dict[str, Any]],
        default_forecast_time_cutoff: str | None = None,
        evidence_cutoff_policy: str = "available_at_lte_cutoff",
        calibration_policy: dict[str, Any] | None = None,
        allow_calibration_memory: bool = False,
    ) -> dict[str, Any]:
        run_id = f"bt_{uuid.uuid4().hex[:12]}"
        default_cutoff = parse_timestamp(
            default_forecast_time_cutoff,
            field_name="default_forecast_time_cutoff",
        )
        created_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO backtest_runs (
                    id, dataset, created_at, default_forecast_time_cutoff,
                    evidence_cutoff_policy, calibration_policy,
                    leakage_checks_passed
                )
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    run_id,
                    dataset,
                    created_at,
                    default_cutoff,
                    evidence_cutoff_policy,
                    json_dumps(
                        calibration_policy
                        or {"allow_calibration_memory": allow_calibration_memory}
                    ),
                ),
            )

        case_rows: list[dict[str, Any]] = []
        leakage_passed = True
        for case in cases:
            case_row = self._run_backtest_case(
                run_id=run_id,
                case=case,
                default_cutoff=default_cutoff,
                allow_calibration_memory=allow_calibration_memory,
            )
            case_rows.append(case_row)
            if case_row["leakage_check_status"] != "passed":
                leakage_passed = False

        result_summary = {
            "case_count": len(case_rows),
            "benchmark_evidence": build_benchmark_evidence_profile(dataset, cases),
            "leakage_checks_passed": leakage_passed,
            "scored_cases": sum(1 for row in case_rows if row.get("score_record_id")),
        }
        agent_brier_scores = [
            row["score_brier"]
            for row in case_rows
            if row.get("score_brier") is not None
        ]
        if agent_brier_scores:
            result_summary["agent_mean_brier"] = sum(agent_brier_scores) / len(agent_brier_scores)
        probability_sources = sorted(
            {
                str(case.get("probability_source"))
                for case in cases
                if case.get("probability_source")
            }
        )
        if probability_sources:
            result_summary["probability_sources"] = probability_sources
        if not leakage_passed:
            self._disable_backtest_calibration(run_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE backtest_runs
                SET result_summary = ?, leakage_checks_passed = ?
                WHERE id = ?
                """,
                (json_dumps(result_summary), 1 if leakage_passed else 0, run_id),
            )
        run = self.get_backtest_run(run_id)
        run["cases"] = case_rows
        return run

    def get_backtest_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"backtest run not found: {run_id}")
        data = dict(row)
        for field in ("question_filter", "model_profile", "calibration_policy", "result_summary"):
            data[field] = json_loads(data[field], {})
        data["artifact_paths"] = json_loads(data["artifact_paths"], [])
        data["leakage_checks_passed"] = bool(data["leakage_checks_passed"])
        return data

    def list_backtest_runs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_runs ORDER BY created_at DESC",
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            for field in ("question_filter", "model_profile", "calibration_policy", "result_summary"):
                data[field] = json_loads(data[field], {})
            data["artifact_paths"] = json_loads(data["artifact_paths"], [])
            data["leakage_checks_passed"] = bool(data["leakage_checks_passed"])
            result.append(data)
        return result

    def list_backtest_cases(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_cases WHERE backtest_run_id = ? ORDER BY simulated_forecast_time ASC",
                (run_id,),
            ).fetchall()
        return [self._row_to_backtest_case(row) for row in rows]

    def backtest_performance_report(self, run_id: str) -> dict[str, Any]:
        run = self.get_backtest_run(run_id)
        cases = self.list_backtest_cases(run_id)
        agent_scores: list[ScoreRecord] = []
        baseline_scores: dict[tuple[str, str], list[ScoreRecord]] = defaultdict(list)
        paired_scores: dict[tuple[str, str], list[tuple[ScoreRecord, ScoreRecord]]] = defaultdict(list)
        for case in cases:
            agent_score = self.get_score(case["score_record_id"]) if case.get("score_record_id") else None
            if agent_score is not None:
                agent_scores.append(agent_score)
            for baseline_id in case.get("baseline_comparison_refs") or []:
                baseline = self.get_baseline_comparison(baseline_id)
                if not baseline.get("score_record_id"):
                    continue
                baseline_score = self.get_score(baseline["score_record_id"])
                key = (baseline["baseline_type"], baseline["source"])
                baseline_scores[key].append(baseline_score)
                if agent_score is not None:
                    paired_scores[key].append((agent_score, baseline_score))

        baselines = []
        for key in sorted(baseline_scores):
            baseline_type, source = key
            pairs = paired_scores.get(key, [])
            paired_brier = self._paired_brier_summary(pairs)
            baselines.append(
                {
                    "baseline_type": baseline_type,
                    "source": source,
                    **self._score_summary(baseline_scores[key]),
                    "paired_count": len(pairs),
                    **paired_brier,
                    "mean_brier_improvement_vs_baseline": self._mean(
                        [
                            baseline.brier_score - agent.brier_score
                            for agent, baseline in pairs
                            if agent.brier_score is not None and baseline.brier_score is not None
                        ]
                    ),
                    "mean_log_improvement_vs_baseline": self._mean(
                        [
                            baseline.log_score - agent.log_score
                            for agent, baseline in pairs
                            if agent.log_score is not None and baseline.log_score is not None
                        ]
                    ),
                }
            )
        return {
            "run_id": run["id"],
            "dataset": run["dataset"],
            "case_count": len(cases),
            "leakage_checks_passed": run["leakage_checks_passed"],
            "agent": self._score_summary(agent_scores),
            "baselines": baselines,
            "agent_by_domain": self._score_breakdown(agent_scores, lambda score: score.domain or "unknown"),
            "agent_by_horizon": self._score_breakdown(agent_scores, self._score_horizon_bucket),
        }

    def live_performance_report(self, *, domain: str | None = None) -> dict[str, Any]:
        """Compare scored live forecasts against scored imported baselines."""

        live_scores = self.list_scores(
            domain=domain,
            forecast_origin="live",
            calibration_eligible=None,
        )
        baseline_scores: dict[tuple[str, str], list[ScoreRecord]] = defaultdict(list)
        paired_scores: dict[tuple[str, str], list[tuple[ScoreRecord, ScoreRecord]]] = defaultdict(list)
        for live_score in live_scores:
            for baseline in self.list_baseline_comparisons(live_score.question_id):
                if not baseline.get("score_record_id"):
                    continue
                baseline_score = self.get_score(baseline["score_record_id"])
                key = (baseline["baseline_type"], baseline["source"])
                baseline_scores[key].append(baseline_score)
                paired_scores[key].append((live_score, baseline_score))

        baselines = []
        for key in sorted(baseline_scores):
            baseline_type, source = key
            pairs = paired_scores.get(key, [])
            baselines.append(
                {
                    "baseline_type": baseline_type,
                    "source": source,
                    **self._score_summary(baseline_scores[key]),
                    "paired_count": len(pairs),
                    **self._paired_brier_summary(pairs),
                    "mean_brier_improvement_vs_baseline": self._mean(
                        [
                            baseline.brier_score - agent.brier_score
                            for agent, baseline in pairs
                            if agent.brier_score is not None and baseline.brier_score is not None
                        ]
                    ),
                    "mean_log_improvement_vs_baseline": self._mean(
                        [
                            baseline.log_score - agent.log_score
                            for agent, baseline in pairs
                            if agent.log_score is not None and baseline.log_score is not None
                        ]
                    ),
                }
            )
        return {
            "score_count": len(live_scores),
            "agent": self._score_summary(live_scores),
            "baselines": baselines,
            "agent_by_domain": self._score_breakdown(live_scores, lambda score: score.domain or "unknown"),
            "agent_by_horizon": self._score_breakdown(live_scores, self._score_horizon_bucket),
            "claim_status": {
                "verdict": "live_comparison_evidence" if baselines else "no_scored_live_baselines",
                "can_claim_live_superforecasting": False,
                "message": (
                    "Resolved live forecasts have scored imported baselines for comparison; "
                    "superforecasting claims still require enough prospective volume and coverage."
                    if baselines
                    else "No scored imported baselines are available for live comparison yet."
                ),
            },
        }

    def review_questions(
        self,
        *,
        stale: bool = False,
        last_days: int | None = None,
        domain: str | None = None,
        topic: str | None = None,
        horizon: str | None = None,
        confidence_below: float | None = None,
        confidence_above: float | None = None,
        large_delta_threshold: float | None = None,
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_confidence_filters(
            confidence_below=confidence_below,
            confidence_above=confidence_above,
        )
        self._validate_probability_threshold(
            large_delta_threshold,
            field_name="large_delta_threshold",
        )
        questions = self.list_questions(status="active", domain=domain)
        if topic:
            questions = [question for question in questions if topic in question.topics]
        now_dt = timestamp_to_datetime(parse_timestamp(now, field_name="now") or utc_now_iso())
        assert now_dt is not None
        rows: list[dict[str, Any]] = []
        for question in questions:
            snapshot = self.get_current_snapshot(question.id)
            if horizon and (
                snapshot is None
                or not self._horizon_matches(snapshot.forecast_horizon_days, horizon)
            ):
                continue
            if confidence_below is not None or confidence_above is not None:
                if snapshot is None or snapshot.confidence is None:
                    continue
                if confidence_below is not None and snapshot.confidence >= confidence_below:
                    continue
                if confidence_above is not None and snapshot.confidence <= confidence_above:
                    continue
            reasons: list[str] = []
            evidence_items = self.list_evidence(question.id)
            if snapshot is None:
                reasons.append("no_forecast_snapshot")
            else:
                snapshot_as_of = timestamp_to_datetime(snapshot.as_of)
                for item in evidence_items:
                    available_dt = timestamp_to_datetime(item.available_at)
                    if snapshot_as_of and available_dt and available_dt > snapshot_as_of:
                        reasons.append(f"new_evidence:{item.id}")
            if question.next_review_at:
                next_review = timestamp_to_datetime(question.next_review_at)
                if next_review and next_review <= now_dt:
                    reasons.append("review_due")
            if question.close_time:
                close_time = timestamp_to_datetime(question.close_time)
                if close_time and close_time <= now_dt:
                    reasons.append("close_time_passed")
                elif stale and last_days is not None and close_time and close_time <= now_dt + timedelta(days=last_days):
                    reasons.append(f"close_time_within_{last_days}d")
            if question.resolution_time:
                resolution_time = timestamp_to_datetime(question.resolution_time)
                if resolution_time and resolution_time <= now_dt:
                    reasons.append("resolution_check_due")
            if stale and snapshot is not None and last_days is not None:
                as_of = timestamp_to_datetime(snapshot.as_of)
                if as_of and (now_dt - as_of).days >= last_days:
                    reasons.append(f"last_update_{last_days}d_plus")
                if not evidence_items:
                    reasons.append("no_evidence")
                else:
                    latest_available = max(
                        (
                            timestamp_to_datetime(item.available_at)
                            for item in evidence_items
                            if timestamp_to_datetime(item.available_at) is not None
                        ),
                        default=None,
                    )
                    if latest_available and (now_dt - latest_available).days >= last_days:
                        reasons.append(f"evidence_stale_{last_days}d_plus")
            for assumption in self.list_assumptions(question.id):
                if assumption["status"] == "invalidated":
                    reasons.append(f"assumption_invalidated:{assumption['id']}")
                elif assumption["status"] == "stale":
                    reasons.append(f"assumption_stale:{assumption['id']}")
                elif self._cadence_due(
                    assumption.get("last_checked_at") or assumption.get("created_at"),
                    assumption.get("check_cadence"),
                    now_dt,
                ):
                    reasons.append(f"assumption_check_due:{assumption['id']}")
            for reference_class in self.list_reference_classes(question.id):
                if reference_class["status"] == "invalidated":
                    reasons.append(f"reference_class_invalidated:{reference_class['id']}")
                elif reference_class["status"] in {"stale", "superseded"}:
                    reasons.append(f"reference_class_stale:{reference_class['id']}")
                elif self._cadence_due(
                    reference_class.get("last_checked_at") or reference_class.get("created_at"),
                    reference_class.get("check_cadence"),
                    now_dt,
                ):
                    reasons.append(f"reference_class_check_due:{reference_class['id']}")
            if large_delta_threshold is not None:
                delta = self._latest_forecast_delta(question.id)
                if delta is not None and abs(delta) >= large_delta_threshold:
                    reasons.append(f"large_forecast_delta:{delta:+.3f}")
            if reasons or not stale:
                rows.append(
                    {
                        "question": question,
                        "current_snapshot": snapshot,
                        "reasons": reasons,
                        "priority": self._review_priority(reasons),
                    }
                )
        return sorted(
            rows,
            key=lambda row: (
                row["priority"],
                row["question"].close_time or row["question"].resolution_time or "9999-12-31T00:00:00Z",
                row["question"].title.lower(),
            ),
        )

    def schedule_review(
        self,
        *,
        scope_type: str,
        scope_ref: str | None,
        cadence: str,
        next_run_at: str | None = None,
        trigger_reason: str = "scheduled",
        enabled: bool = True,
        auto_score: bool = False,
        auto_postmortem: bool = False,
        stale_days: int = 7,
        confidence_below: float | None = None,
        confidence_above: float | None = None,
        large_delta_threshold: float | None = None,
    ) -> dict[str, Any]:
        if scope_type not in SCHEDULE_SCOPE_TYPES:
            raise ValidationError(
                "scope_type must be question, domain, topic, domain_topic, portfolio, or horizon"
            )
        if scope_type == "horizon":
            if not scope_ref:
                raise ValidationError("horizon scheduled reviews require scope_ref")
            self._horizon_matches(0.0, scope_ref)
        if not cadence.strip():
            raise ValidationError("cadence is required")
        if stale_days < 0:
            raise ValidationError("stale_days must be non-negative")
        self._validate_confidence_filters(
            confidence_below=confidence_below,
            confidence_above=confidence_above,
        )
        self._validate_probability_threshold(
            large_delta_threshold,
            field_name="large_delta_threshold",
        )
        review_id = f"sr_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_reviews (
                    id, scope_type, scope_ref, cadence, stale_days, next_run_at,
                    trigger_reason, enabled, auto_score, auto_postmortem,
                    confidence_below, confidence_above, large_delta_threshold
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    scope_type,
                    scope_ref,
                    cadence,
                    int(stale_days),
                    parse_timestamp(next_run_at, field_name="next_run_at") or utc_now_iso(),
                    trigger_reason,
                    1 if enabled else 0,
                    1 if auto_score else 0,
                    1 if auto_postmortem else 0,
                    confidence_below,
                    confidence_above,
                    large_delta_threshold,
                ),
            )
        return self.get_scheduled_review(review_id)

    def get_scheduled_review(self, review_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM scheduled_reviews WHERE id = ?", (review_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"scheduled review not found: {review_id}")
        return dict(row)

    def list_scheduled_reviews(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_reviews ORDER BY next_run_at ASC",
            ).fetchall()
        return [dict(row) for row in rows]

    def list_scheduled_review_runs(
        self,
        *,
        scheduled_review_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        limit = max(int(limit), 1)
        clauses: list[str] = []
        params: list[Any] = []
        if scheduled_review_id:
            clauses.append("scheduled_review_id = ?")
            params.append(scheduled_review_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM scheduled_review_runs
                {where}
                ORDER BY run_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_scheduled_review_run(row) for row in rows]

    def add_watched_source(
        self,
        *,
        scope_type: str,
        scope_ref: str | None,
        source: str,
        source_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_watch_scope(scope_type, scope_ref)
        source = source.strip()
        if not source:
            raise ValidationError("watched source is required")
        inferred_type = source_type or self._infer_watch_source_type(source)
        if inferred_type == "manual_note":
            inferred_type = "manual"
        if inferred_type not in WATCH_SOURCE_TYPES:
            raise ValidationError(
                "source_type must be file, url, manual, rss, gdelt, fivethirtyeight, github, githubrepo, githubissues, githubcommits, githubactions, coingecko, pypi, npm, hackernews, reddit, bluesky, mastodon, reliefweb, federalregister, courtlistener, nvd, cisakev, openmeteo, airquality, weatherhistory, usgs, eonet, nws, clinicaltrials, openfda, pubmed, owid, whogho, fema, fred, eia, treasury, bls, worldbank, imf, census, socrata, ckan, stooq, yahoo, "
                "sec, secfacts, arxiv, openalex, crossref, wikipedia, wikipediapageviews, manifold, metaculus, polymarket, or kalshi"
            )

        watch_id = f"ws_{uuid.uuid4().hex[:12]}"
        created_at = utc_now_iso()
        signature = self._source_signature(source, inferred_type, metadata=metadata)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watched_sources (
                    id, scope_type, scope_ref, source, source_type, created_at,
                    last_checked_at, last_seen_signature, status, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    watch_id,
                    scope_type,
                    scope_ref,
                    source,
                    inferred_type,
                    created_at,
                    created_at if signature is not None else None,
                    signature,
                    "active",
                    json_dumps(metadata or {}),
                ),
            )
        return self.get_watched_source(watch_id)

    def get_watched_source(self, watch_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM watched_sources WHERE id = ?", (watch_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"watched source not found: {watch_id}")
        return self._row_to_watched_source(row)

    def list_watched_sources(
        self,
        *,
        scope_type: str | None = None,
        scope_ref: str | None = None,
        status: str | None = "active",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if scope_type:
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if scope_ref:
            clauses.append("scope_ref = ?")
            params.append(scope_ref)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM watched_sources {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self._row_to_watched_source(row) for row in rows]

    def list_source_snapshots(
        self,
        *,
        question_id: str | None = None,
        watched_source_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        if watched_source_id:
            clauses.append("watched_source_id = ?")
            params.append(watched_source_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(int(limit), 1))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM source_snapshots
                {where}
                ORDER BY retrieved_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_source_snapshot(row) for row in rows]

    def autopilot_readiness(
        self,
        question_id: str,
        *,
        sources: list[str] | None = None,
        allow_missing_resolution_source: bool = False,
    ) -> dict[str, Any]:
        question = self.get_question(question_id)
        hard_blockers: list[str] = []
        warnings: list[str] = []
        if question.status != "active":
            hard_blockers.append("question is not active")
        if not question.resolution_criteria.strip():
            hard_blockers.append("missing resolution criteria")
        if not question.resolution_source and not allow_missing_resolution_source:
            hard_blockers.append("missing resolution source")
        if question.outcome_space.type not in {"binary", "categorical", "numeric", "distribution"}:
            hard_blockers.append(f"unsupported outcome type: {question.outcome_space.type}")
        if self.get_current_snapshot(question_id) is None:
            hard_blockers.append("no baseline forecast snapshot")
        if sources is not None and not sources:
            hard_blockers.append("at least one watched source is required")
        for source in sources or []:
            source_type = self._infer_watch_source_type(source.strip())
            if source_type == "manual_note":
                source_type = "manual"
            if source_type not in WATCH_SOURCE_TYPES:
                hard_blockers.append(f"no source adapter available for {source!r}")
            elif source_type == "manual":
                hard_blockers.append(f"no pollable source adapter available for {source!r}")
        if not self.list_reference_classes(question_id):
            warnings.append("no reference class recorded")
        if not self.list_scores():
            warnings.append("no calibration or scoring history")
        stale_assumptions = [
            row["id"]
            for row in self.list_assumptions(question_id)
            if row.get("status") in {"stale", "invalidated"}
        ]
        if stale_assumptions:
            warnings.append("stale assumptions: " + ", ".join(stale_assumptions))
        return {
            "question_id": question_id,
            "ready": not hard_blockers,
            "hard_blockers": hard_blockers,
            "warnings": warnings,
        }

    def enable_autopilot(
        self,
        *,
        question_id: str,
        sources: list[str],
        cadence: str,
        mode: str = "propose",
        materiality_policy: dict[str, Any] | None = None,
        guardrail_policy: dict[str, Any] | None = None,
        notification_policy: dict[str, Any] | None = None,
        required_sources: list[str] | None = None,
        next_run_at: str | None = None,
        created_by: str | None = None,
        allow_missing_resolution_source: bool = False,
    ) -> dict[str, Any]:
        mode = mode.replace("-", "_")
        if mode not in AUTOPILOT_MODES:
            raise ValidationError("autopilot mode must be propose, auto-commit, or alert-only")
        sources = list(dict.fromkeys(source.strip() for source in sources if source.strip()))
        required_sources = list(
            dict.fromkeys(source.strip() for source in (required_sources or []) if source.strip())
        )
        for source in required_sources:
            if source not in sources:
                sources.append(source)
        required_source_set = set(required_sources)
        readiness = self.autopilot_readiness(
            question_id,
            sources=sources,
            allow_missing_resolution_source=allow_missing_resolution_source,
        )
        if readiness["hard_blockers"]:
            raise ValidationError("autopilot readiness failed: " + "; ".join(readiness["hard_blockers"]))
        if not cadence.strip():
            raise ValidationError("autopilot cadence is required")

        policy_id = f"ap_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        schedule = self.schedule_review(
            scope_type="question",
            scope_ref=question_id,
            cadence=cadence,
            next_run_at=next_run_at,
            trigger_reason="autopilot",
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO autopilot_policies (
                    id, question_id, enabled, mode, cadence, scheduled_review_id,
                    materiality_policy, guardrail_policy, notification_policy,
                    created_at, updated_at, created_by
                )
                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    question_id,
                    mode,
                    cadence,
                    schedule["id"],
                    json_dumps(materiality_policy or {}),
                    json_dumps(guardrail_policy or {}),
                    json_dumps(notification_policy or {}),
                    now,
                    now,
                    created_by,
                ),
            )
        watches = [
            self.add_watched_source(
                scope_type="question",
                scope_ref=question_id,
                source=source,
                metadata={
                    "autopilot_policy_id": policy_id,
                    "required": source in required_source_set,
                },
            )
            for source in sources
        ]
        alert = self.create_alert(
            severity="info",
            scope_type="question",
            scope_ref=question_id,
            reason=f"autopilot_enabled:{policy_id}",
            recommended_action=f"Run `forecast autopilot status {question_id}` to inspect the maintenance policy.",
        )
        return {
            "policy": self.get_autopilot_policy(policy_id),
            "scheduled_review": schedule,
            "watched_sources": watches,
            "readiness": readiness,
            "audit_alert": alert,
        }

    def disable_autopilot(self, question_id: str) -> dict[str, Any]:
        policy = self.get_active_autopilot_policy(question_id)
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE autopilot_policies SET enabled = 0, updated_at = ? WHERE id = ?",
                (now, policy["id"]),
            )
            if policy.get("scheduled_review_id"):
                conn.execute(
                    "UPDATE scheduled_reviews SET enabled = 0 WHERE id = ?",
                    (policy["scheduled_review_id"],),
                )
        return self.get_autopilot_policy(policy["id"])

    def get_autopilot_policy(self, policy_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM autopilot_policies WHERE id = ?", (policy_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"autopilot policy not found: {policy_id}")
        return self._row_to_autopilot_policy(row)

    def get_active_autopilot_policy(self, question_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM autopilot_policies
                WHERE question_id = ? AND enabled = 1
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (question_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"active autopilot policy not found for {question_id}")
        return self._row_to_autopilot_policy(row)

    def list_autopilot_policies(
        self,
        *,
        question_id: str | None = None,
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        if enabled_only:
            clauses.append("enabled = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM autopilot_policies {where} ORDER BY created_at DESC, id DESC",
                params,
            ).fetchall()
        return [self._row_to_autopilot_policy(row) for row in rows]

    def list_autopilot_runs(
        self,
        *,
        question_id: str | None = None,
        policy_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        if policy_id:
            clauses.append("policy_id = ?")
            params.append(policy_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(int(limit), 1))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM autopilot_runs
                {where}
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_autopilot_run(row) for row in rows]

    def list_forecast_update_proposals(
        self,
        *,
        question_id: str | None = None,
        status: str | None = "pending",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(int(limit), 1))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM forecast_update_proposals
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_forecast_update_proposal(row) for row in rows]

    def create_forecast_update_proposal(
        self,
        *,
        question_id: str,
        run_id: str | None,
        prior_forecast_id: str | None,
        proposed_probability_or_distribution: Any,
        rationale: str,
        evidence_refs: list[str] | None = None,
        source_snapshot_refs: list[str] | None = None,
        model_run_refs: list[str] | None = None,
        assumption_refs: list[str] | None = None,
        reference_class_refs: list[str] | None = None,
        status: str = "pending",
    ) -> dict[str, Any]:
        question = self.get_question(question_id)
        if status not in AUTOPILOT_PROPOSAL_STATUSES:
            raise ValidationError("proposal status is invalid")
        payload = self._validate_probability_payload(
            proposed_probability_or_distribution,
            question.outcome_space,
        )
        if not rationale.strip():
            raise ValidationError("proposal rationale is required")
        proposal_id = f"fup_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO forecast_update_proposals (
                    id, question_id, run_id, prior_forecast_id,
                    proposed_probability_or_distribution, rationale, evidence_refs,
                    source_snapshot_refs, model_run_refs, assumption_refs,
                    reference_class_refs, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    question_id,
                    run_id,
                    prior_forecast_id,
                    json_dumps(payload),
                    rationale.strip(),
                    json_dumps(evidence_refs or []),
                    json_dumps(source_snapshot_refs or []),
                    json_dumps(model_run_refs or []),
                    json_dumps(assumption_refs or []),
                    json_dumps(reference_class_refs or []),
                    status,
                    utc_now_iso(),
                ),
            )
        return self.get_forecast_update_proposal(proposal_id)

    def get_forecast_update_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forecast_update_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"forecast update proposal not found: {proposal_id}")
        return self._row_to_forecast_update_proposal(row)

    def approve_forecast_update_proposal(
        self,
        proposal_id: str,
        *,
        reviewed_by: str | None = None,
        status: str = "approved",
    ) -> ForecastSnapshot:
        if status not in {"approved", "auto_committed"}:
            raise ValidationError("approved proposal status must be approved or auto_committed")
        proposal = self.get_forecast_update_proposal(proposal_id)
        if proposal["status"] != "pending" and status != "auto_committed":
            raise ValidationError("only pending proposals can be approved")
        snapshot = self.create_snapshot(
            question_id=proposal["question_id"],
            probability_or_distribution=proposal["proposed_probability_or_distribution"],
            rationale=proposal["rationale"],
            method="autopilot",
            evidence_refs=proposal["evidence_refs"],
            source_snapshot_refs=proposal["source_snapshot_refs"],
            model_run_refs=proposal["model_run_refs"],
            assumption_refs=proposal["assumption_refs"],
            reference_class_refs=proposal["reference_class_refs"],
            require_citations=True,
            metadata={"autopilot_proposal_id": proposal_id},
        )
        reviewed_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE forecast_update_proposals
                SET status = ?, reviewed_at = ?, reviewed_by = ?
                WHERE id = ?
                """,
                (status, reviewed_at, reviewed_by, proposal_id),
            )
            if proposal.get("run_id"):
                conn.execute(
                    "UPDATE autopilot_runs SET forecast_snapshot_id = ? WHERE id = ?",
                    (snapshot.forecast_id, proposal["run_id"]),
                )
        return snapshot

    def reject_forecast_update_proposal(
        self,
        proposal_id: str,
        *,
        reviewed_by: str | None = None,
    ) -> dict[str, Any]:
        proposal = self.get_forecast_update_proposal(proposal_id)
        if proposal["status"] != "pending":
            raise ValidationError("only pending proposals can be rejected")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE forecast_update_proposals
                SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
                WHERE id = ?
                """,
                (utc_now_iso(), reviewed_by, proposal_id),
            )
        return self.get_forecast_update_proposal(proposal_id)

    # Canonical pooling-method aliases so a re-pool matches the snapshot's
    # original recipe. Mirrors the CLI's bayes-method handling.
    _REFRESH_POOL_METHODS = {
        "log_odds_pool": "log_odds_pool",
        "log_odds": "log_odds_pool",
        "logit": "log_odds_pool",
        "geometric": "log_odds_pool",
        "geo_mean_odds": "log_odds_pool",
        "log_pool": "log_pool",
        "log_linear": "log_pool",
        "linear_pool": "linear_pool",
        "linear": "linear_pool",
    }

    @classmethod
    def _refresh_pool_method(cls, method: str | None) -> str:
        """Map a stored snapshot.method to a combine_forecasts pooling method,
        defaulting to log-odds pooling (the desk default for disagreeing sources)."""
        key = (method or "").strip().lower()
        return cls._REFRESH_POOL_METHODS.get(key, "log_odds_pool")

    @staticmethod
    def _refresh_source_keys(source_type: str, source: str) -> set[str]:
        """The identifiers a fresh reading can match a component / prior
        observation by (same scheme as _derive_trigger_observations)."""
        keys = {source.strip().lower(), f"{source_type}:{source}".strip().lower()}
        keys.discard("")
        return keys

    def refresh_forecast(
        self,
        question_id: str,
        *,
        fetcher: Any,
        now: str | None = None,
        re_estimate: str = "deterministic",
        extremize: float = 1.0,
        correlation: Any | None = None,
        dry_run: bool = False,
        commit: bool = True,
        trigger_reason: str = "manual_refresh",
    ) -> dict[str, Any]:
        """Pull the latest watched-source readings, import the new values as
        evidence, deterministically re-pool the forecast, and (by default)
        auto-commit a new live snapshot.

        ``fetcher(specs) -> [{source_type, source, success, payloads, error}]``
        is injected by the caller (CLI / tool layer) so the ledger never imports
        the adapter/tool layer; ``payloads`` are kwargs for :meth:`add_evidence`.
        ``re_estimate="deterministic"`` re-pools the prior snapshot's
        probability-bearing components after refreshing market/crowd readings;
        ``"carry_forward"`` keeps the prior probability and flags that agent /
        manual re-reasoning is needed (also the automatic fallback for
        non-binary questions or raw-data-only sources). With ``commit`` and not
        ``dry_run`` the re-estimate is written through :meth:`create_snapshot`
        as a scored ``forecast_origin="live"`` snapshot; otherwise nothing is
        persisted and a preview is returned.
        """

        if re_estimate not in {"deterministic", "carry_forward"}:
            raise ValidationError("re_estimate must be 'deterministic' or 'carry_forward'")
        question = self.get_question(question_id)
        current = self.get_current_snapshot(question_id)
        if current is None:
            raise ValidationError("refresh requires a baseline forecast snapshot")
        run_at = parse_timestamp(now, field_name="now") or utc_now_iso()
        persist = bool(commit) and not dry_run

        watches = self.list_watched_sources(
            scope_type="question", scope_ref=question_id, status="active"
        )
        if not watches:
            return {
                "status": "no_watched_sources",
                "committed": None,
                "message": (
                    "no active watched sources — add one with `forecast watch add`, "
                    "or re-run with --agent to collect evidence via the LLM update stage."
                ),
            }

        prior_observations = self._derive_trigger_observations(question_id)

        # 1) Re-fetch every active watched source (parallel, injected fetcher).
        specs = []
        for watch in watches:
            control_keys = {"autopilot_policy_id", "required", "auto_watch", "from_action", "source_ref"}
            adapter_args = {
                key: value
                for key, value in (watch.get("metadata") or {}).items()
                if key not in control_keys
            }
            specs.append(
                {"source_type": watch["source_type"], "source": watch["source"], "args": adapter_args}
            )
        fetched = fetcher(specs)

        # 2) Reduce each fetched reading to its latest numeric value + keys, and
        #    decide which readings actually changed vs the last imported value.
        fresh_market_readings: list[dict[str, Any]] = []
        fresh_values: dict[str, float] = {}
        changed_readings: list[dict[str, Any]] = []
        fetch_failures: list[dict[str, str]] = []
        new_evidence_ids: list[str] = []
        for result in fetched or []:
            if not result.get("success"):
                fetch_failures.append(
                    {"source": f"{result.get('source_type')}:{result.get('source')}", "error": result.get("error") or "fetch failed"}
                )
                continue
            stype = str(result.get("source_type") or "")
            source = str(result.get("source") or "")
            keys = self._refresh_source_keys(stype, source)
            for payload in result.get("payloads") or []:
                item = (payload.get("metadata") or {}).get("adapter_item") or {}
                market_p = self._numeric_probability(item.get("probability"))
                raw_value = self._refresh_reading_value(item)
                reading = market_p if market_p is not None else raw_value
                if market_p is not None:
                    # One reading, one entry (with all its identity keys) so the
                    # same reading is never double-counted as matched + unmatched.
                    fresh_market_readings.append(
                        {"keys": set(keys), "probability": market_p, "label": f"{stype}:{source}"}
                    )
                for key in keys:
                    if reading is not None:
                        fresh_values[key] = reading
                # A reading is "changed" if new or different from the last import.
                is_changed = reading is None or any(
                    key not in prior_observations or abs(prior_observations[key] - reading) > 1e-9
                    for key in keys
                )
                if is_changed:
                    changed_readings.append({"source_type": stype, "source": source, "value": reading, "payload": payload})
                    if persist:
                        evidence = self.add_evidence(
                            question_id=question_id, archive_url_snapshot=False, **payload
                        )
                        new_evidence_ids.append(evidence.id)

        # 3) Re-estimate.
        prior_rows = self._ensemble_component_rows(current.ensemble_components)
        binary = question.outcome_space.type == "binary" and isinstance(
            current.probability_or_distribution, (int, float)
        )
        updated_components, unmatched_sources = self._apply_fresh_market_probabilities(
            current.ensemble_components, fresh_market_readings
        )
        can_repool = (
            re_estimate == "deterministic"
            and binary
            and bool(prior_rows)
            and bool(updated_components["matched"])
        )

        prior_prob = float(current.probability_or_distribution) if binary else None
        new_prob: Any = current.probability_or_distribution
        new_components = current.ensemble_components
        diff_dict: dict[str, Any] | None = None
        reasons_up: list[str] = []
        reasons_down: list[str] = []
        needs_agent = not can_repool

        if can_repool:
            from forecasting.bayes_toolkit import (  # local import avoids cycle / heavy import at module load
                combine_forecasts,
                ensure_industry_backends,
                forecast_diff,
            )

            ensure_industry_backends()
            method = self._refresh_pool_method(current.method)
            pool = combine_forecasts(
                updated_components["rows"],
                method=method,
                extremize=extremize,
                correlation_matrix=correlation,
            )
            new_prob = pool.probability
            new_components = {"components": updated_components["rows"]}
            diff = forecast_diff(
                previous=prior_prob,
                current=float(new_prob),
                components=updated_components["diff_components"],
            )
            diff_dict = diff.to_dict()
            for driver in diff.drivers:
                pts = driver.get("contribution_pts")
                if pts is None:
                    continue
                label = f"{driver.get('name', 'component')} ({pts:+.1f} pts)"
                (reasons_up if pts >= 0 else reasons_down).append(label)

        prob_changed = (
            binary
            and isinstance(new_prob, (int, float))
            and abs(float(new_prob) - prior_prob) > 1e-9
        )

        # 4) No-op guard: nothing fetched-changed and probability unchanged.
        if not changed_readings and not prob_changed:
            return {
                "status": "no_change",
                "committed": None,
                "message": "no new readings and probability unchanged — nothing committed.",
                "prior_probability": current.probability_or_distribution,
                "fetch_failures": fetch_failures,
                "unmatched_sources": unmatched_sources,
            }

        # 5) Fire executable update_triggers against the fresh values (idempotent).
        trigger_alerts: list[AlertEvent] = []
        if persist:
            trigger_alerts = self.check_update_triggers(
                question_id=question_id, observations=fresh_values or None, now=run_at
            )

        # 6) Auto rationale (no human in the loop).
        rationale = self._default_refresh_rationale(
            changed_readings=changed_readings,
            unmatched_sources=unmatched_sources,
            new_prob=new_prob,
            prior_prob=current.probability_or_distribution,
            re_estimate="deterministic" if can_repool else "carry_forward",
            needs_agent=needs_agent,
        )

        preview = {
            "status": "carry_forward" if needs_agent else "re_pooled",
            "committed": None,
            "prior_probability": current.probability_or_distribution,
            "proposed_probability": new_prob,
            "diff": diff_dict,
            "reasons_up": reasons_up,
            "reasons_down": reasons_down,
            "rationale": rationale,
            "changed_readings": [
                {"source_type": r["source_type"], "source": r["source"], "value": r["value"]}
                for r in changed_readings
            ],
            "unmatched_sources": unmatched_sources,
            "fetch_failures": fetch_failures,
            "needs_agent": needs_agent,
            "triggers_fired": [alert.reason for alert in trigger_alerts],
        }

        if not persist:
            preview["message"] = "preview only — re-run without --dry-run/--no-commit to commit."
            return preview

        # 7) Record a model run as the audit + citation anchor, then commit.
        change_my_mind = [
            "A reversal in the strongest refreshed driver would move this back",
            "A watched source going stale or failing on the next refresh",
        ]
        model_run = self.record_model_run(
            question_id=question_id,
            model_type="forecast_refresh",
            inputs={
                "trigger_reason": trigger_reason,
                "prior_forecast_id": current.forecast_id,
                "new_evidence_ids": new_evidence_ids,
            },
            parameters={
                "re_estimate": "deterministic" if can_repool else "carry_forward",
                "method": self._refresh_pool_method(current.method),
                "extremize": extremize,
            },
            output={"proposed_probability": new_prob, "diff": diff_dict},
            diagnostics={"changed_readings": len(changed_readings), "fetch_failures": fetch_failures},
        )

        snapshot = self.create_snapshot(
            question_id=question_id,
            probability_or_distribution=new_prob,
            rationale=rationale,
            method=current.method,
            ensemble_components=new_components,
            forecast_origin="live",
            evidence_refs=new_evidence_ids,
            model_run_refs=[model_run["id"]],
            reasons_up=reasons_up or ["Refreshed watched-source readings"],
            reasons_down=reasons_down or ["Counter-signals in the refreshed sources"],
            change_my_mind=change_my_mind,
            require_citations=True,
            panel_skipped_reason=(
                "automated forecast refresh — deterministic re-pool of existing components; "
                "panel not required for a programmatic re-estimate"
            ),
            evidence_cutoff=run_at,
            metadata={
                "refresh": {
                    "trigger_reason": trigger_reason,
                    "re_estimate": "deterministic" if can_repool else "carry_forward",
                    "prior_forecast_id": current.forecast_id,
                    "needs_agent": needs_agent,
                    "diff": diff_dict,
                }
            },
        )

        return {
            **preview,
            "status": "committed",
            "committed": snapshot.__dict__,
            "forecast_id": snapshot.forecast_id,
            "model_run": model_run,
            "new_evidence_ids": new_evidence_ids,
            "message": None,
        }

    def _refresh_reading_value(self, item: dict[str, Any]) -> float | None:
        """Extract the latest numeric reading from an adapter item (the same
        canonical keys the trigger evaluator reads)."""
        for key in self._TRIGGER_VALUE_KEYS:
            raw = item.get(key)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
        return None

    def _apply_fresh_market_probabilities(
        self, components: dict[str, Any], fresh_readings: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], list[str]]:
        """Update each prior component's probability with a freshly-fetched
        market/crowd reading that matches it. ``fresh_readings`` is a list of
        ``{"keys": set[str], "probability": float, "label": str}``. Returns
        ``{"rows", "diff_components", "matched"}`` and the list of reading
        labels that did not match any component."""

        raw_rows = (
            list(components.get("components"))
            if isinstance(components.get("components"), list)
            else [
                {"name": name, **(value if isinstance(value, dict) else {"probability": value})}
                for name, value in (components or {}).items()
            ]
        )
        rows: list[dict[str, Any]] = []
        diff_components: list[dict[str, Any]] = []
        matched_labels: set[str] = set()
        for index, raw in enumerate(raw_rows, start=1):
            if not isinstance(raw, dict):
                continue
            prior_p = self._numeric_probability(raw.get("probability"))
            weight = self._numeric_probability(raw.get("weight", 1.0))
            if prior_p is None or weight is None or weight < 0:
                continue
            name = str(raw.get("name") or raw.get("source") or f"component_{index}")
            identity = {str(raw.get("source") or "").lower(), name.lower()}
            identity.discard("")
            new_p = prior_p
            for reading in fresh_readings:
                keys = reading["keys"]
                if keys & identity or any(
                    key in token or token in key for key in keys for token in identity
                ):
                    new_p = reading["probability"]
                    matched_labels.add(reading["label"])
                    break
            # Preserve every original component key (esp. `source`) so the
            # component stays matchable on the NEXT refresh; only the probability
            # is overwritten. combine_forecasts ignores the extra keys.
            row = dict(raw)
            row["name"] = name
            row["probability"] = new_p
            row["weight"] = weight
            rows.append(row)
            diff_components.append(
                {"name": name, "previous_p": prior_p, "current_p": new_p, "weight": weight}
            )
        unmatched = sorted({r["label"] for r in fresh_readings} - matched_labels)
        return {"rows": rows, "diff_components": diff_components, "matched": sorted(matched_labels)}, unmatched

    @staticmethod
    def _default_refresh_rationale(
        *,
        changed_readings: list[dict[str, Any]],
        unmatched_sources: list[str],
        new_prob: Any,
        prior_prob: Any,
        re_estimate: str,
        needs_agent: bool,
    ) -> str:
        sources = ", ".join(
            sorted({f"{r['source_type']}:{r['source']}" for r in changed_readings})
        ) or "no changed readings"
        if re_estimate == "deterministic":
            head = (
                f"Automated refresh: re-pooled components after refreshing {sources}. "
                f"Probability {prior_prob} -> {new_prob}."
            )
        else:
            head = (
                f"Automated refresh: imported fresh readings from {sources} and carried the prior "
                f"probability {prior_prob} forward"
                + (" — run with --agent for a re-reasoned estimate." if needs_agent else ".")
            )
        if unmatched_sources:
            head += f" Unmatched fresh readings (not wired to a component): {', '.join(unmatched_sources)}."
        return head

    def run_autopilot(
        self,
        question_id: str,
        *,
        now: str | None = None,
        trigger_reason: str = "manual",
        proposed_probability_or_distribution: Any | None = None,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        policy = self.get_active_autopilot_policy(question_id)
        current = self.get_current_snapshot(question_id)
        if current is None:
            raise ValidationError("autopilot requires a baseline forecast snapshot")
        run_at = parse_timestamp(now, field_name="now") or utc_now_iso()
        watches = self.list_watched_sources(scope_type="question", scope_ref=question_id, status="active")
        source_snapshots: list[dict[str, Any]] = []
        changed: list[dict[str, Any]] = []
        required_source_failures: list[str] = []
        alerts: list[AlertEvent] = []

        for watch in watches:
            previous_signature = watch.get("last_seen_signature")
            current_signature = self._source_signature(
                watch["source"],
                watch["source_type"],
                metadata=watch.get("metadata"),
            )
            status = "success"
            error_message = None
            if current_signature is None or str(current_signature).startswith("missing:"):
                status = "failed"
                error_message = str(current_signature or "source unavailable")
            did_change = (
                status == "success"
                and previous_signature is not None
                and current_signature is not None
                and current_signature != previous_signature
            )
            source_snapshot = self._record_source_snapshot(
                question_id=question_id,
                watch=watch,
                retrieved_at=run_at,
                signature=current_signature,
                previous_signature=previous_signature,
                changed=did_change,
                status=status,
                error_message=error_message,
            )
            source_snapshots.append(source_snapshot)
            if did_change:
                changed.append(source_snapshot)
            if status == "failed":
                is_required = bool((watch.get("metadata") or {}).get("required"))
                if is_required:
                    required_source_failures.append(source_snapshot["id"])
                alerts.append(
                    self.create_alert(
                        severity="high" if is_required else "warning",
                        scope_type="question",
                        scope_ref=question_id,
                        reason=(
                            f"autopilot_required_source_failed:{watch['id']}"
                            if is_required
                            else f"autopilot_source_failed:{watch['id']}"
                        ),
                        recommended_action=(
                            "Required autopilot source failed; forecast refresh is blocked until it recovers. "
                            f"Inspect the source and rerun `forecast autopilot run {question_id}`."
                            if is_required
                            else (
                                "Inspect the watched source and rerun "
                                f"`forecast autopilot run {question_id}` after the adapter recovers."
                            )
                        ),
                    )
                )
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE watched_sources
                    SET last_checked_at = ?, last_seen_signature = ?
                    WHERE id = ?
                    """,
                    (run_at, current_signature, watch["id"]),
                )

        blocked_by_required_source_failure = bool(required_source_failures)
        material_changes = 0
        if not blocked_by_required_source_failure and self._autopilot_material_change(policy, changed):
            material_changes = len(changed)
        proposal: dict[str, Any] | None = None
        snapshot: ForecastSnapshot | None = None
        model_run: dict[str, Any] | None = None
        source_failures = [row["id"] for row in source_snapshots if row["status"] == "failed"]
        if blocked_by_required_source_failure:
            status = "failed"
        elif source_failures:
            status = "partial"
        else:
            status = "skipped" if material_changes == 0 else "success"
        diagnostics: dict[str, Any] = {
            "mode": policy["mode"],
            "source_snapshot_ids": [row["id"] for row in source_snapshots],
            "changed_source_snapshot_ids": [row["id"] for row in changed],
            "source_failures": source_failures,
            "required_source_failures": required_source_failures,
            "forecast_refresh_blocked": blocked_by_required_source_failure,
            "materiality_policy": policy["materiality_policy"],
            "guardrail_policy": policy["guardrail_policy"],
        }

        if material_changes:
            proposed_payload = (
                proposed_probability_or_distribution
                if proposed_probability_or_distribution is not None
                else current.probability_or_distribution
            )
            proposal_rationale = rationale or self._default_autopilot_rationale(
                changed=changed,
                current=current,
            )
            model_run = self.record_model_run(
                question_id=question_id,
                model_type="autopilot_refresh",
                inputs={
                    "trigger_reason": trigger_reason,
                    "prior_forecast_id": current.forecast_id,
                    "source_snapshot_refs": [row["id"] for row in source_snapshots],
                },
                parameters={
                    "materiality_policy": policy["materiality_policy"],
                    "guardrail_policy": policy["guardrail_policy"],
                },
                output={
                    "proposed_probability_or_distribution": proposed_payload,
                    "rationale": proposal_rationale,
                },
                diagnostics=diagnostics,
                model_version=FORECASTING_PROTOCOL_VERSION,
                evidence_cutoff=run_at,
            )
            proposal = self.create_forecast_update_proposal(
                question_id=question_id,
                run_id=None,
                prior_forecast_id=current.forecast_id,
                proposed_probability_or_distribution=proposed_payload,
                rationale=proposal_rationale,
                source_snapshot_refs=[row["id"] for row in source_snapshots],
                model_run_refs=[model_run["id"]],
            )
            if policy["mode"] == "alert_only":
                alerts.append(
                    self.create_alert(
                        severity="warning",
                        scope_type="question",
                        scope_ref=question_id,
                        reason=f"autopilot_material_change:{policy['id']}",
                        recommended_action=f"Review proposal {proposal['id']} before updating the forecast.",
                    )
                )
            elif policy["mode"] == "auto_commit":
                violations = self._autopilot_guardrail_violations(
                    policy=policy,
                    prior_payload=current.probability_or_distribution,
                    proposed_payload=proposed_payload,
                    source_snapshots=source_snapshots,
                )
                diagnostics["guardrail_violations"] = violations
                if violations:
                    alerts.append(
                        self.create_alert(
                            severity="high",
                            scope_type="question",
                            scope_ref=question_id,
                            reason=f"autopilot_guardrail_review:{policy['id']}",
                            recommended_action=(
                                "Autopilot update requires review: "
                                + "; ".join(violations)
                                + f". Approve manually with `forecast autopilot approve {proposal['id']}`."
                            ),
                        )
                    )
                else:
                    snapshot = self.approve_forecast_update_proposal(
                        proposal["id"],
                        status="auto_committed",
                    )
            else:
                alerts.append(
                    self.create_alert(
                        severity="info",
                        scope_type="question",
                        scope_ref=question_id,
                        reason=f"autopilot_update_proposed:{proposal['id']}",
                        recommended_action=f"Review with `forecast autopilot approve {proposal['id']}` or reject it.",
                    )
                )

        run = self._record_autopilot_run(
            policy_id=policy["id"],
            question_id=question_id,
            started_at=run_at,
            finished_at=utc_now_iso(),
            status=status,
            trigger_reason=trigger_reason,
            sources_checked=len(watches),
            sources_changed=len(changed),
            material_changes=material_changes,
            proposal_id=proposal["id"] if proposal else None,
            forecast_snapshot_id=snapshot.forecast_id if snapshot else None,
            alerts_created=len(alerts),
            diagnostics=diagnostics,
        )
        if proposal and proposal.get("run_id") is None:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE forecast_update_proposals SET run_id = ? WHERE id = ?",
                    (run["id"], proposal["id"]),
                )
            proposal = self.get_forecast_update_proposal(proposal["id"])
        return {
            "policy": policy,
            "run": run,
            "source_snapshots": source_snapshots,
            "proposal": proposal,
            "forecast_snapshot": snapshot,
            "model_run": model_run,
            "alerts": alerts,
        }

    def check_watched_sources(
        self,
        *,
        scope_type: str | None = None,
        scope_ref: str | None = None,
        now: str | None = None,
    ) -> list[AlertEvent]:
        now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
        watches = self.list_watched_sources(scope_type=scope_type, scope_ref=scope_ref, status="active")
        alerts: list[AlertEvent] = []
        for watch in watches:
            source_type = watch["source_type"]
            current_signature = self._source_signature(
                watch["source"],
                source_type,
                metadata=watch.get("metadata"),
            )
            previous_signature = watch.get("last_seen_signature")
            should_alert = (
                source_type
                in {
                    "file",
                    "url",
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
                }
                and previous_signature is not None
                and current_signature is not None
                and current_signature != previous_signature
            )
            if should_alert:
                reason = "watched_source_unavailable" if current_signature.startswith("missing:") else "watched_source_changed"
                alerts.append(
                    self.create_alert(
                        severity="warning" if reason == "watched_source_unavailable" else "info",
                        scope_type=watch["scope_type"],
                        scope_ref=watch["scope_ref"] or watch["id"],
                        reason=f"{reason}:{watch['id']}",
                        recommended_action=self._watched_source_action(watch),
                    )
                )
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE watched_sources
                    SET last_checked_at = ?, last_seen_signature = ?
                    WHERE id = ?
                    """,
                    (now_ts, current_signature, watch["id"]),
                )
        # Executable update_triggers: compare the question's triggers against the
        # latest imported values and emit `trigger_fired` alerts. Scoped to the
        # questions whose watched sources we just checked.
        for question_id in {
            watch["scope_ref"]
            for watch in watches
            if watch.get("scope_type") == "question" and watch.get("scope_ref")
        }:
            alerts.extend(self.check_update_triggers(question_id=question_id))
        return alerts

    # Canonical numeric-value keys an adapter item may expose, newest-relevant
    # first. Used to derive the latest observation for an executable trigger and
    # for refresh change-detection. "probability" covers market/crowd adapters
    # (manifold/metaculus/polymarket/kalshi) whose reading IS a probability.
    _TRIGGER_VALUE_KEYS = (
        "value",
        "observed_value",
        "latest_value",
        "level",
        "close_price",
        "close",
        "price",
        "rate",
        "yield",
        "index_value",
        "views",
        "count",
        "probability",
    )

    def _derive_trigger_observations(self, question_id: str) -> dict[str, float]:
        """Best-effort map of source_ref -> latest numeric value, derived from the
        question's imported evidence. The newest evidence per source wins. Used
        when the caller does not supply observations explicitly."""

        latest: dict[str, tuple[str, float]] = {}
        for evidence in self.list_evidence(question_id):
            meta = evidence.metadata or {}
            item = meta.get("adapter_item")
            if not isinstance(item, dict):
                continue
            value: float | None = None
            for key in self._TRIGGER_VALUE_KEYS:
                raw = item.get(key)
                if raw is None or isinstance(raw, bool):
                    continue
                try:
                    value = float(raw)
                    break
                except (TypeError, ValueError):
                    continue
            if value is None:
                continue
            adapter = meta.get("adapter")
            source = meta.get("source")
            keys = set()
            if source:
                keys.add(str(source))
                if adapter:
                    keys.add(f"{adapter}:{source}")
            if meta.get("source_ref"):
                keys.add(str(meta["source_ref"]))
            # Rank by the OBSERVATION date, not the import time: a single batch
            # import stamps every observation in a series with the same
            # available_at, so using available_at would pick an arbitrary
            # mid-series reading (e.g. a stale peak) instead of the latest
            # observation. entry_id ("DCOILWTICO:2026-05-18") and
            # observation_date carry the real series date; fall back to
            # available_at for sources that have neither.
            entry_id = str(meta.get("entry_id") or "")
            obs_date = str(item.get("observation_date") or item.get("date") or "")
            entry_suffix = entry_id.split(":", 1)[1] if ":" in entry_id else ""
            stamp = obs_date or entry_suffix or evidence.available_at or evidence.captured_at or ""
            for key in keys:
                if key not in latest or stamp >= latest[key][0]:
                    latest[key] = (stamp, value)
        return {key: value for key, (_, value) in latest.items()}

    def check_update_triggers(
        self,
        *,
        question_id: str,
        observations: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> list[AlertEvent]:
        """Evaluate a question's executable update_triggers against imported
        values and emit (idempotent) ``trigger_fired`` alerts. ``observations``
        (source_ref -> value) overrides values derived from imported evidence."""

        question = self.get_question(question_id)
        merged = dict(self._derive_trigger_observations(question_id))
        for key, value in (observations or {}).items():
            merged[str(key)] = value
        fired = evaluate_update_triggers(question.update_triggers, merged)
        if not fired:
            return []
        open_reasons = {
            alert.reason
            for alert in self.list_alerts(unresolved_only=True)
            if alert.scope_type == "question" and alert.scope_ref == question_id
        }
        alerts: list[AlertEvent] = []
        for entry in fired:
            reason = f"trigger_fired:{entry['source_ref']}"
            if reason in open_reasons:
                continue  # one open alert per source until acknowledged
            alerts.append(
                self.create_alert(
                    severity="warning",
                    scope_type="question",
                    scope_ref=question_id,
                    reason=reason,
                    recommended_action=(
                        f"Update trigger fired: {entry['mechanism']} "
                        f"({entry['source_ref']} {entry['operator']} {entry['threshold']}; "
                        f"observed {entry['observed']}). Re-run the forecast: "
                        f"`forecast pipeline {question_id} --stage update`."
                    ),
                )
            )
        return alerts

    def run_due_scheduled_reviews(
        self,
        *,
        now: str | None = None,
        auto_score: bool = False,
        auto_postmortem: bool = False,
    ) -> list[dict[str, Any]]:
        now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scheduled_reviews
                WHERE enabled = 1 AND next_run_at <= ?
                ORDER BY next_run_at ASC
                """,
                (now_ts,),
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            review = dict(row)
            scope_type = review["scope_type"]
            scope_ref = review["scope_ref"]
            stale_days = int(review.get("stale_days") or 7)
            confidence_below = review.get("confidence_below")
            confidence_above = review.get("confidence_above")
            large_delta_threshold = review.get("large_delta_threshold")
            if scope_type == "question":
                alerts = self.self_check(
                    question_id=scope_ref,
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
            elif scope_type == "domain":
                alerts = self.self_check(
                    domain=scope_ref,
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
            elif scope_type == "topic":
                alerts = self.self_check(
                    topic=scope_ref,
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
            elif scope_type == "domain_topic":
                scope_filter = json_loads(scope_ref, {})
                alerts = self.self_check(
                    domain=scope_filter.get("domain"),
                    topic=scope_filter.get("topic"),
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
            elif scope_type == "portfolio":
                alerts = self.self_check(
                    portfolio=scope_ref,
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
            else:
                alerts = self.self_check(
                    horizon=scope_ref,
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
            next_run_at = self._advance_cadence(now_ts, review["cadence"])
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE scheduled_reviews
                    SET last_run_at = ?, next_run_at = ?
                    WHERE id = ?
                    """,
                    (now_ts, next_run_at, review["id"]),
                )
            run = self._record_scheduled_review_run(
                review=review,
                run_at=now_ts,
                next_run_at=next_run_at,
                alerts=alerts,
            )
            results.append(
                {
                    "review": self.get_scheduled_review(review["id"]),
                    "run": run,
                    "alerts": alerts,
                }
            )
        return results

    def _record_scheduled_review_run(
        self,
        *,
        review: dict[str, Any],
        run_at: str,
        next_run_at: str,
        alerts: list[AlertEvent],
    ) -> dict[str, Any]:
        score_count = sum(1 for alert in alerts if alert.reason.startswith("score_created:"))
        postmortem_count = sum(1 for alert in alerts if alert.reason.startswith("postmortem_created:"))
        learning_review_count = sum(1 for alert in alerts if self._is_learning_alert_reason(alert.reason))
        run_id = f"srr_{uuid.uuid4().hex[:12]}"
        metadata = {
            "scope_type": review.get("scope_type"),
            "scope_ref": review.get("scope_ref"),
            "cadence": review.get("cadence"),
            "trigger_reason": review.get("trigger_reason"),
            "auto_score": bool(review.get("auto_score")),
            "auto_postmortem": bool(review.get("auto_postmortem")),
            "alert_reasons": [alert.reason for alert in alerts],
            "alert_ids": [alert.id for alert in alerts],
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_review_runs (
                    id, scheduled_review_id, run_at, next_run_at, alert_count,
                    score_count, postmortem_count, learning_review_count,
                    status, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    review["id"],
                    run_at,
                    next_run_at,
                    len(alerts),
                    score_count,
                    postmortem_count,
                    learning_review_count,
                    "completed",
                    json_dumps(metadata),
                ),
            )
        return self.list_scheduled_review_runs(scheduled_review_id=review["id"], limit=1)[0]

    def _record_source_snapshot(
        self,
        *,
        question_id: str,
        watch: dict[str, Any],
        retrieved_at: str,
        signature: str | None,
        previous_signature: str | None,
        changed: bool,
        status: str,
        error_message: str | None,
    ) -> dict[str, Any]:
        snapshot_id = f"ss_{uuid.uuid4().hex[:12]}"
        parsed_values = {
            "signature": signature,
            "previous_signature": previous_signature,
            "changed": changed,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO source_snapshots (
                    id, question_id, watched_source_id, source_type, source_url,
                    retrieved_at, raw_payload_sha256, parsed_values,
                    adapter_version, status, error_message, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    question_id,
                    watch["id"],
                    watch["source_type"],
                    watch["source"],
                    retrieved_at,
                    signature,
                    json_dumps(parsed_values),
                    f"{watch['source_type']}-watch-v1",
                    status,
                    error_message,
                    json_dumps(
                        {
                            "autopilot_policy_id": watch.get("metadata", {}).get("autopilot_policy_id"),
                            "required": bool((watch.get("metadata") or {}).get("required")),
                        }
                    ),
                ),
            )
        return self.list_source_snapshots(watched_source_id=watch["id"], limit=1)[0]

    def _record_autopilot_run(
        self,
        *,
        policy_id: str,
        question_id: str,
        started_at: str,
        finished_at: str,
        status: str,
        trigger_reason: str,
        sources_checked: int,
        sources_changed: int,
        material_changes: int,
        proposal_id: str | None,
        forecast_snapshot_id: str | None,
        alerts_created: int,
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = f"apr_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO autopilot_runs (
                    id, policy_id, question_id, started_at, finished_at, status,
                    trigger_reason, sources_checked, sources_changed,
                    material_changes, proposal_id, forecast_snapshot_id,
                    alerts_created, diagnostics
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    policy_id,
                    question_id,
                    started_at,
                    finished_at,
                    status,
                    trigger_reason,
                    sources_checked,
                    sources_changed,
                    material_changes,
                    proposal_id,
                    forecast_snapshot_id,
                    alerts_created,
                    json_dumps(diagnostics),
                ),
            )
        return self.list_autopilot_runs(policy_id=policy_id, limit=1)[0]

    @staticmethod
    def _autopilot_material_change(policy: dict[str, Any], changed: list[dict[str, Any]]) -> bool:
        minimum = int((policy.get("materiality_policy") or {}).get("min_source_changes") or 1)
        return len(changed) >= max(minimum, 1)

    @staticmethod
    def _default_autopilot_rationale(
        *,
        changed: list[dict[str, Any]],
        current: ForecastSnapshot,
    ) -> str:
        drivers = ", ".join(
            f"{row['source_type']}:{row['watched_source_id']}"
            for row in changed[:3]
        )
        return (
            "Autopilot detected material watched-source changes "
            f"({drivers or 'source change'}) after prior forecast {current.forecast_id}. "
            "This proposal preserves the previous probability until an explicit model or operator "
            "adjustment supplies a different distribution."
        )

    def _autopilot_guardrail_violations(
        self,
        *,
        policy: dict[str, Any],
        prior_payload: Any,
        proposed_payload: Any,
        source_snapshots: list[dict[str, Any]],
    ) -> list[str]:
        guardrails = policy.get("guardrail_policy") or {}
        violations: list[str] = []
        if guardrails.get("require_no_critical_source_failures", True):
            failures = [row["id"] for row in source_snapshots if row.get("status") == "failed"]
            if failures:
                violations.append("critical source failures: " + ", ".join(failures))
        required_sources = int(guardrails.get("min_independent_sources_for_auto_commit") or 0)
        successful_sources = len([row for row in source_snapshots if row.get("status") == "success"])
        if required_sources and successful_sources < required_sources:
            violations.append(
                f"successful sources {successful_sources} below required {required_sources}"
            )
        max_delta = guardrails.get("max_single_run_probability_delta")
        if max_delta is None:
            max_delta = guardrails.get("max_auto_delta")
        if max_delta is not None:
            prior_probability = self._numeric_probability(prior_payload)
            proposed_probability = self._numeric_probability(proposed_payload)
            if prior_probability is not None and proposed_probability is not None:
                delta = abs(proposed_probability - prior_probability)
                if delta > float(max_delta):
                    violations.append(
                        f"proposed probability delta {delta:.3f} exceeds max {float(max_delta):.3f}"
                    )
        return violations

    @staticmethod
    def _is_learning_alert_reason(reason: str | None) -> bool:
        text = str(reason or "")
        return text in {"calibration_lesson_review", "domain_error_profile_review"} or text.startswith(
            "domain_error_profile_applies:"
        )

    def create_alert(
        self,
        *,
        severity: str,
        scope_type: str,
        scope_ref: str,
        reason: str,
        recommended_action: str,
    ) -> AlertEvent:
        alert_id = f"al_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_events (
                    id, created_at, severity, scope_type, scope_ref, reason,
                    recommended_action
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    utc_now_iso(),
                    severity,
                    scope_type,
                    scope_ref,
                    reason,
                    recommended_action,
                ),
            )
        return self.get_alert(alert_id)

    def get_alert(self, alert_id: str) -> AlertEvent:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM alert_events WHERE id = ?", (alert_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"alert not found: {alert_id}")
        return self._row_to_alert(row)

    def list_alerts(self, *, unresolved_only: bool = True) -> list[AlertEvent]:
        where = "WHERE acknowledged_at IS NULL" if unresolved_only else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM alert_events {where} ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_alert(row) for row in rows]

    def acknowledge_alert(self, alert_id: str, *, acknowledged_at: str | None = None) -> AlertEvent:
        self.get_alert(alert_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE alert_events SET acknowledged_at = ? WHERE id = ?",
                (parse_timestamp(acknowledged_at, field_name="acknowledged_at") or utc_now_iso(), alert_id),
            )
        return self.get_alert(alert_id)

    def self_check(
        self,
        *,
        question_id: str | None = None,
        domain: str | None = None,
        topic: str | None = None,
        horizon: str | None = None,
        portfolio: str | None = None,
        stale_days: int = 7,
        now: str | None = None,
        auto_score: bool = False,
        auto_postmortem: bool = False,
        confidence_below: float | None = None,
        confidence_above: float | None = None,
        large_delta_threshold: float | None = None,
    ) -> list[AlertEvent]:
        self._validate_confidence_filters(
            confidence_below=confidence_below,
            confidence_above=confidence_above,
        )
        self._validate_probability_threshold(
            large_delta_threshold,
            field_name="large_delta_threshold",
        )
        if question_id:
            questions = [self.get_question(question_id)]
        else:
            questions = self.list_questions(domain=domain)
            if topic:
                questions = [q for q in questions if topic in q.topics]
            if horizon:
                questions = [
                    q
                    for q in questions
                    if (snapshot := self.get_current_snapshot(q.id)) is not None
                    and self._horizon_matches(snapshot.forecast_horizon_days, horizon)
                ]
            if portfolio:
                questions = [q for q in questions if self._question_in_portfolio(q, portfolio)]
        if confidence_below is not None or confidence_above is not None:
            questions = [
                q
                for q in questions
                if self._question_matches_confidence(
                    q.id,
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                )
            ]

        alerts: list[AlertEvent] = []
        for row in self.review_questions(
            stale=True,
            last_days=stale_days,
            domain=domain,
            topic=topic,
            horizon=horizon,
            confidence_below=confidence_below,
            confidence_above=confidence_above,
            large_delta_threshold=large_delta_threshold,
            now=now,
        ):
            question = row["question"]
            if question_id and question.id != question_id:
                continue
            if portfolio and not self._question_in_portfolio(question, portfolio):
                continue
            for reason in row["reasons"]:
                action = self._recommended_action(reason)
                alerts.append(
                    self.create_alert(
                        severity="warning" if reason != "resolution_check_due" else "high",
                        scope_type="question",
                        scope_ref=question.id,
                        reason=reason,
                        recommended_action=action,
                    )
                )
        for question in questions:
            if question.status != "resolved":
                continue
            if self.get_latest_resolution(question.id, confirmed_only=True) is None:
                continue
            current = self.get_current_snapshot(question.id)
            scores = [score for score in self.list_scores() if score.question_id == question.id]
            if current is not None and not scores:
                if auto_score:
                    try:
                        score = self.score_question(question.id)
                    except ForecastingError as exc:
                        alerts.append(
                            self.create_alert(
                                severity="high",
                                scope_type="question",
                                scope_ref=question.id,
                                reason="score_blocked",
                                recommended_action=f"Inspect resolution and scoring setup: {exc}",
                            )
                        )
                        continue
                    alerts.append(
                        self.create_alert(
                            severity="info",
                            scope_type="question",
                            scope_ref=question.id,
                            reason=f"score_created:{score.id}",
                            recommended_action="Run `forecast postmortem` so the score can update calibration memory.",
                        )
                    )
                    scores = [score]
                else:
                    high_impact = self._is_high_impact_question(question)
                    alerts.append(
                        self.create_alert(
                            severity="high",
                            scope_type="question",
                            scope_ref=question.id,
                            reason="high_impact_score_due" if high_impact else "score_due",
                            recommended_action=(
                                "Prioritize scoring this high-impact confirmed resolution before updating calibration memory."
                                if high_impact
                                else "Run `forecast score` for the confirmed resolution."
                            ),
                        )
                    )
                    continue
            if scores and not self.list_postmortems(question.id):
                if auto_postmortem:
                    latest_score = scores[0]
                    postmortem = self.create_postmortem(
                        question_id=question.id,
                        summary="Auto-created by forecast self-check after confirmed resolution and scoring.",
                        what_happened="The forecast resolved and was scored during a scheduled or manual self-check.",
                        what_was_expected="See the linked forecast snapshot and score record for the prior probability.",
                        lesson=self._auto_postmortem_lesson(question, latest_score),
                        calibration_adjustment=self._auto_postmortem_adjustment(question, latest_score),
                    )
                    alerts.append(
                        self.create_alert(
                            severity="info",
                            scope_type="question",
                            scope_ref=question.id,
                            reason=f"postmortem_created:{postmortem['id']}",
                            recommended_action=(
                                "Review the auto-created postmortem and any tentative calibration lesson "
                                "before relying on it for future updates."
                            ),
                        )
                    )
                    continue
                high_impact = self._is_high_impact_question(question)
                alerts.append(
                    self.create_alert(
                        severity="high" if high_impact else "warning",
                        scope_type="question",
                        scope_ref=question.id,
                        reason="high_impact_postmortem_due" if high_impact else "postmortem_due",
                        recommended_action=(
                            "Prioritize a postmortem for this high-impact resolution before reusing the lesson."
                            if high_impact
                            else "Run `forecast postmortem` so the resolved forecast can update learning artifacts."
                        ),
                    )
                )
        alerts.extend(self._domain_error_profile_alerts(domain=domain, topic=topic, questions=questions))
        alerts.extend(
            self._calibration_lesson_review_alerts(
                domain=domain,
                topic=topic,
                questions=questions,
            )
        )
        if not any([question_id, domain, topic, horizon, portfolio]):
            alerts.extend(self._benchmark_evidence_alerts())
        watch_scope_type, watch_scope_ref = self._self_check_watch_scope(
            question_id=question_id,
            domain=domain,
            topic=topic,
            portfolio=portfolio,
        )
        alerts.extend(
            self.check_watched_sources(
                scope_type=watch_scope_type,
                scope_ref=watch_scope_ref,
                now=now,
            )
        )
        # Fire executable update_triggers for in-scope questions against their
        # latest imported values (idempotent — one open alert per source).
        for question in questions:
            if any(trigger.get("operator") for trigger in question.update_triggers):
                alerts.extend(self.check_update_triggers(question_id=question.id, now=now))
        return alerts

    def pilot_report(
        self,
        *,
        min_questions: int = 3,
        min_structured_source_questions: int = 1,
        min_scores: int = 1,
        min_postmortems: int = 1,
        min_scheduled_reviews: int = 1,
        min_scheduled_review_runs: int = 1,
    ) -> dict[str, Any]:
        """Summarize whether a tester ledger has the artifacts needed for a pilot."""

        min_questions = max(int(min_questions), 0)
        min_structured_source_questions = max(int(min_structured_source_questions), 0)
        min_scores = max(int(min_scores), 0)
        min_postmortems = max(int(min_postmortems), 0)
        min_scheduled_reviews = max(int(min_scheduled_reviews), 0)
        min_scheduled_review_runs = max(int(min_scheduled_review_runs), 0)

        questions = self.list_questions()
        status_counts = Counter(question.status for question in questions)
        domain_counts = Counter(question.domain or "unscoped" for question in questions)
        topic_counts: Counter[str] = Counter()
        source_type_counts: Counter[str] = Counter()
        score_origin_counts: Counter[str] = Counter()
        question_rows: list[dict[str, Any]] = []
        questions_with_forecasts = 0
        questions_with_evidence = 0
        questions_with_structured_sources = 0
        questions_with_models = 0
        questions_with_reference_classes = 0

        non_manual_source_types = {"manual_note", "note"}
        for question in questions:
            snapshots = self.list_snapshots(question.id)
            evidence = self.list_evidence(question.id)
            model_runs = self.list_model_runs(question.id)
            reference_classes = self.list_reference_classes(question.id)
            resolution = self.get_latest_resolution(question.id, confirmed_only=False)
            postmortems = self.list_postmortems(question.id)
            scores = [score for score in self.list_scores() if score.question_id == question.id]
            source_types = Counter(item.source_type or "unknown" for item in evidence)
            structured_source_types = sorted(
                source_type for source_type in source_types if source_type not in non_manual_source_types
            )

            if snapshots:
                questions_with_forecasts += 1
            if evidence:
                questions_with_evidence += 1
            if structured_source_types:
                questions_with_structured_sources += 1
            if model_runs:
                questions_with_models += 1
            if reference_classes:
                questions_with_reference_classes += 1
            for topic in question.topics:
                topic_counts[topic] += 1
            source_type_counts.update(source_types)

            question_rows.append(
                {
                    "id": question.id,
                    "title": question.title,
                    "status": question.status,
                    "domain": question.domain,
                    "topics": question.topics,
                    "forecast_count": len(snapshots),
                    "evidence_count": len(evidence),
                    "source_types": dict(sorted(source_types.items())),
                    "structured_source_types": structured_source_types,
                    "reference_class_count": len(reference_classes),
                    "model_run_count": len(model_runs),
                    "score_count": len(scores),
                    "postmortem_count": len(postmortems),
                    "resolved": resolution is not None,
                }
            )

        scores = self.list_scores()
        score_origin_counts.update(score.forecast_origin for score in scores)
        postmortems = self.list_postmortems()
        schedules = self.list_scheduled_reviews()
        scheduled_review_runs = self.list_scheduled_review_runs(limit=1000)
        watched_sources = self.list_watched_sources(status=None)
        autopilot_policies = self.list_autopilot_policies(enabled_only=False)
        autopilot_runs = self.list_autopilot_runs(limit=1000)
        forecast_update_proposals = self.list_forecast_update_proposals(status=None, limit=1000)
        alerts = self.list_alerts(unresolved_only=False)
        open_alert_count = sum(1 for alert in alerts if alert.acknowledged_at is None)
        open_learned_error_review_alerts = [
            alert
            for alert in alerts
            if alert.acknowledged_at is None
            and str(alert.reason or "").startswith("domain_error_profile_applies:")
        ]
        lessons = self.list_calibration_lessons()
        active_lessons = [lesson for lesson in lessons if lesson["status"] == "active"]

        def check(
            check_id: str,
            label: str,
            observed: int,
            required: int,
            action: str,
        ) -> dict[str, Any]:
            passed = observed >= required
            return {
                "id": check_id,
                "label": label,
                "observed": observed,
                "required": required,
                "passed": passed,
                "recommended_action": "" if passed else action,
            }

        def max_check(
            check_id: str,
            label: str,
            observed: int,
            maximum: int,
            action: str,
        ) -> dict[str, Any]:
            passed = observed <= maximum
            return {
                "id": check_id,
                "label": label,
                "observed": observed,
                "required": maximum,
                "passed": passed,
                "recommended_action": "" if passed else action,
            }

        checks = [
            check(
                "questions_created",
                "scoreable questions created",
                len(questions),
                min_questions,
                "Create more scoreable questions with `forecast new ...`.",
            ),
            check(
                "forecast_updates_recorded",
                "questions with at least one forecast update",
                questions_with_forecasts,
                min_questions,
                "Record probability updates with `forecast update <id> ...`.",
            ),
            check(
                "evidence_recorded",
                "questions with timestamped evidence",
                questions_with_evidence,
                min_questions,
                "Add evidence with `forecast evidence add <id> ...` or `forecast import ... --question <id>`.",
            ),
            check(
                "structured_sources_used",
                "questions with non-manual source evidence",
                questions_with_structured_sources,
                min_structured_source_questions,
                "Import at least one structured source with `forecast sources` then `forecast import ... --question <id>`.",
            ),
            check(
                "scheduled_self_checks",
                "scheduled self-checks configured",
                len([row for row in schedules if row.get("enabled")]),
                min_scheduled_reviews,
                "Schedule review work with `forecast schedule add --question <id> ...`.",
            ),
            check(
                "scheduled_self_check_runs",
                "scheduled self-checks run",
                len(scheduled_review_runs),
                min_scheduled_review_runs,
                "Run due schedule rows with `forecast schedule run --due`, or install the cron bridge with `forecast schedule install-cron`.",
            ),
            check(
                "live_scores_recorded",
                "resolved live forecasts scored",
                score_origin_counts.get("live", 0),
                min_scores,
                "Resolve and score at least one forecast with `forecast resolve <id> ...` and `forecast score <id>`.",
            ),
            check(
                "postmortems_recorded",
                "postmortems recorded",
                len(postmortems),
                min_postmortems,
                "Write at least one postmortem with `forecast postmortem <id> ...`.",
            ),
            max_check(
                "learned_error_reviews_cleared",
                "open learned-error profile review alerts",
                len(open_learned_error_review_alerts),
                0,
                "Review active forecasts flagged by learned error profiles, then acknowledge the alerts with `forecast alerts --ack <id>`.",
            ),
        ]
        passed_count = sum(1 for row in checks if row["passed"])
        next_actions = [row["recommended_action"] for row in checks if row["recommended_action"]]
        pilot_status = "pilot_exit_ready" if passed_count == len(checks) else "collecting_pilot_evidence"

        return {
            "product": _export_metadata(),
            "generated_at": utc_now_iso(),
            "pilot_status": pilot_status,
            "passed_checks": passed_count,
            "total_checks": len(checks),
            "checks": checks,
            "next_actions": next_actions,
            "summary": {
                "question_count": len(questions),
                "question_status_counts": dict(sorted(status_counts.items())),
                "questions_with_forecasts": questions_with_forecasts,
                "questions_with_evidence": questions_with_evidence,
                "questions_with_structured_sources": questions_with_structured_sources,
                "questions_with_models": questions_with_models,
                "questions_with_reference_classes": questions_with_reference_classes,
                "score_counts_by_origin": dict(sorted(score_origin_counts.items())),
                "postmortem_count": len(postmortems),
                "scheduled_review_count": len(schedules),
                "enabled_scheduled_review_count": len([row for row in schedules if row.get("enabled")]),
                "scheduled_review_run_count": len(scheduled_review_runs),
                "watched_source_count": len(watched_sources),
                "autopilot_policy_count": len(autopilot_policies),
                "active_autopilot_policy_count": len(
                    [row for row in autopilot_policies if row.get("enabled")]
                ),
                "autopilot_run_count": len(autopilot_runs),
                "pending_autopilot_proposal_count": len(
                    [row for row in forecast_update_proposals if row.get("status") == "pending"]
                ),
                "alert_count": len(alerts),
                "open_alert_count": open_alert_count,
                "open_learned_error_review_alert_count": len(open_learned_error_review_alerts),
                "calibration_lesson_count": len(lessons),
                "active_calibration_lesson_count": len(active_lessons),
            },
            "domains": dict(sorted(domain_counts.items())),
            "topics": dict(sorted(topic_counts.items())),
            "source_types": dict(sorted(source_type_counts.items())),
            "questions": question_rows,
        }

    def export_question(self, question_id: str, *, fmt: str = "markdown") -> str:
        question = self.get_question(question_id)
        snapshots = self.list_snapshots(question_id)
        evidence = self.list_evidence(question_id)
        assumptions = self.list_assumptions(question_id)
        reference_classes = self.list_reference_classes(question_id)
        model_runs = self.list_model_runs(question_id)
        source_snapshots = self.list_source_snapshots(question_id=question_id, limit=1000)
        watched_sources = self.list_watched_sources(scope_type="question", scope_ref=question_id, status=None)
        scheduled_reviews = [
            row
            for row in self.list_scheduled_reviews()
            if row.get("scope_type") == "question" and row.get("scope_ref") == question_id
        ]
        scheduled_review_runs = [
            run
            for review in scheduled_reviews
            for run in self.list_scheduled_review_runs(scheduled_review_id=review["id"], limit=100)
        ]
        autopilot_policies = self.list_autopilot_policies(question_id=question_id, enabled_only=False)
        autopilot_runs = self.list_autopilot_runs(question_id=question_id, limit=100)
        forecast_update_proposals = self.list_forecast_update_proposals(question_id=question_id, status=None, limit=100)
        postmortems = self.list_postmortems(question_id, include_invalidated=True)
        baselines = self.list_baseline_comparisons(question_id)
        resolution = self.get_latest_resolution(question_id)
        scores = [s for s in self.list_scores(include_invalidated=True) if s.question_id == question_id]
        calibration_lessons = self._calibration_lessons_for_question(scores, postmortems)
        domain_error_profiles = self._domain_error_profiles_for_question(question)
        corrections = self._corrections_for_question(
            question_id=question_id,
            snapshots=snapshots,
            evidence=evidence,
            assumptions=assumptions,
            reference_classes=reference_classes,
            model_runs=model_runs,
            resolution=resolution,
            scores=scores,
            postmortems=postmortems,
            calibration_lessons=calibration_lessons,
        )
        if fmt == "json":
            return json_dumps(
                {
                    "product": _export_metadata(),
                    "generated_at": utc_now_iso(),
                    "question": self._question_to_dict(question),
                    "forecast_history": [self._snapshot_to_dict(snapshot) for snapshot in snapshots],
                    "evidence": [self._evidence_to_dict(item) for item in evidence],
                    "assumptions": assumptions,
                    "reference_classes": reference_classes,
                    "model_runs": model_runs,
                    "source_snapshots": source_snapshots,
                    "watched_sources": watched_sources,
                    "scheduled_reviews": scheduled_reviews,
                    "scheduled_review_runs": scheduled_review_runs,
                    "autopilot_policies": autopilot_policies,
                    "autopilot_runs": autopilot_runs,
                    "forecast_update_proposals": forecast_update_proposals,
                    "baseline_comparisons": baselines,
                    "resolution": self._resolution_to_dict(resolution) if resolution else None,
                    "scores": [self._score_to_dict(score) for score in scores],
                    "postmortems": postmortems,
                    "calibration_lessons": calibration_lessons,
                    "domain_error_profiles": domain_error_profiles,
                    "corrections": corrections,
                    "panel_runs": self.list_panel_runs(question_id, limit=20),
                }
            )
        if fmt != "markdown":
            raise ValidationError("export format must be markdown or json")
        lines = [
            f"# Forecast Packet: {question.title}",
            "",
            f"- Product: {PRODUCT_NAME}",
            f"- North star: {NORTH_STAR}",
            f"- ID: `{question.id}`",
            f"- Generated at: {utc_now_iso()}",
            f"- Status: {question.status}",
            f"- Domain: {question.domain or ''}",
            f"- Close time: {question.close_time or ''}",
            f"- Resolution time: {question.resolution_time or ''}",
            f"- Resolution criteria: {question.resolution_criteria}",
            "",
            "## Current Forecast",
        ]
        current = snapshots[-1] if snapshots else None
        if current:
            lines.extend(
                [
                    f"- Forecast ID: `{current.forecast_id}`",
                    f"- As of: {current.as_of}",
                    f"- Probability/distribution: `{current.probability_or_distribution}`",
                    f"- Confidence: {current.confidence if current.confidence is not None else ''}",
                    f"- Rationale: {current.rationale}",
                    "",
                ]
            )
        else:
            lines.extend(["No forecast snapshot recorded.", ""])
        lines.append("## Forecast History")
        if snapshots:
            for snapshot in snapshots:
                lines.append(
                    f"- {snapshot.as_of}: `{snapshot.probability_or_distribution}` "
                    f"({snapshot.method or 'unspecified'}) - {snapshot.rationale}"
                )
        else:
            lines.append("- None")
        lines.extend(["", "## Evidence"])
        if evidence:
            for item in evidence:
                label = item.source_url or item.source_name or "manual note"
                lines.append(f"- {item.available_at}: {label} - {item.claim or item.summary}")
        else:
            lines.append("- None")
        lines.extend(["", "## Assumptions"])
        if assumptions:
            for item in assumptions:
                lines.append(f"- {item['status']}: {item['text']}")
        else:
            lines.append("- None")
        lines.extend(["", "## Reference Classes"])
        if reference_classes:
            for item in reference_classes:
                lines.append(
                    f"- {item['name']}: base_rate={item['base_rate']} "
                    f"uncertainty={item['base_rate_uncertainty']}"
                )
        else:
            lines.append("- None")
        lines.extend(["", "## Model Runs"])
        if model_runs:
            for item in model_runs:
                lines.append(f"- {item['created_at']}: {item['model_type']} `{item['id']}`")
        else:
            lines.append("- None")
        lines.extend(["", "## Watched Sources"])
        if watched_sources:
            for item in watched_sources:
                lines.append(f"- {item['id']} {item['scope_type']}:{item['scope_ref']} {item['source_type']} {item['source']}")
        else:
            lines.append("- None")
        lines.extend(["", "## Scheduled Self-Checks"])
        if scheduled_reviews:
            for item in scheduled_reviews:
                lines.append(
                    f"- {item['id']} {item['scope_type']}:{item['scope_ref']} "
                    f"cadence={item['cadence']} next={item['next_run_at']} "
                    f"learning=score:{bool(item.get('auto_score'))}/postmortem:{bool(item.get('auto_postmortem'))}"
                )
        else:
            lines.append("- None")
        lines.extend(["", "## Scheduled Self-Check Runs"])
        if scheduled_review_runs:
            for item in scheduled_review_runs:
                lines.append(
                    f"- {item['id']} schedule={item['scheduled_review_id']} "
                    f"run_at={item['run_at']} alerts={item['alert_count']} "
                    f"scores={item['score_count']} postmortems={item['postmortem_count']} "
                    f"learning_reviews={item['learning_review_count']} next={item['next_run_at']}"
                )
        else:
            lines.append("- None")
        lines.extend(["", "## Autopilot"])
        if autopilot_policies:
            for item in autopilot_policies:
                lines.append(
                    f"- {item['id']} mode={item['mode']} cadence={item['cadence']} "
                    f"enabled={item['enabled']}"
                )
        else:
            lines.append("- None")
        if forecast_update_proposals:
            lines.append("")
            lines.append("### Update Proposals")
            for item in forecast_update_proposals:
                lines.append(
                    f"- {item['id']} {item['status']}: prior={item['prior_forecast_id']} "
                    f"run={item['run_id']}"
                )
        lines.extend(["", "## Resolution"])
        if resolution:
            lines.append(
                f"- {resolution.resolved_at}: `{resolution.outcome}` "
                f"({resolution.resolution_status}, criteria_satisfied={resolution.criteria_satisfied})"
            )
        else:
            lines.append("- Unresolved")
        lines.extend(["", "## Scores"])
        if scores:
            for score in scores:
                suffix = f", invalidated_by={score.invalidated_by_correction_id}" if score.invalidated_by_correction_id else ""
                lines.append(
                    f"- {score.scored_at}: Brier={score.brier_score}, "
                    f"bucket={score.calibration_bucket}, origin={score.forecast_origin}{suffix}"
                )
        else:
            lines.append("- None")
        lines.extend(["", "## Postmortems"])
        if postmortems:
            for item in postmortems:
                suffix = f" invalidated_by={item['invalidated_by_correction_id']}" if item.get("invalidated_by_correction_id") else ""
                lines.append(f"- {item['created_at']}: {item['summary']}{suffix}")
        else:
            lines.append("- None")
        lines.extend(["", "## Calibration Lessons"])
        if calibration_lessons:
            for item in calibration_lessons:
                suffix = f" invalidated_by={item['invalidated_by_correction_id']}" if item.get("invalidated_by_correction_id") else ""
                lines.append(f"- {item['id']} {item['status']}: {item['lesson']}{suffix}")
        else:
            lines.append("- None")
        lines.extend(["", "## Corrections"])
        if corrections:
            for item in corrections:
                lines.append(f"- {item['id']} {item['status']}: {item['target_type']} `{item['target_id']}` - {item['reason']}")
        else:
            lines.append("- None")
        return "\n".join(lines) + "\n"

    def export_all(self, *, fmt: str = "markdown") -> str:
        questions = self.list_questions()
        if fmt == "json":
            return json_dumps(
                {
                    "product": _export_metadata(),
                    "generated_at": utc_now_iso(),
                    "questions": [
                        json_loads(self.export_question(question.id, fmt="json"), {})
                        for question in questions
                    ],
                    "ingest_candidates": self.list_ingest_candidates(),
                    "source_snapshots": self.list_source_snapshots(),
                    "watched_sources": self.list_watched_sources(status=None),
                    "scheduled_reviews": self.list_scheduled_reviews(),
                    "scheduled_review_runs": self.list_scheduled_review_runs(limit=1000),
                    "autopilot_policies": self.list_autopilot_policies(enabled_only=False),
                    "autopilot_runs": self.list_autopilot_runs(limit=1000),
                    "forecast_update_proposals": self.list_forecast_update_proposals(status=None),
                    "domain_error_profiles": self.list_domain_error_profiles(),
                    "alerts": [alert.__dict__ for alert in self.list_alerts(unresolved_only=False)],
                }
            )
        if fmt != "markdown":
            raise ValidationError("export format must be markdown or json")
        lines = [
            "# Forecast Portfolio Export",
            "",
            f"- Product: {PRODUCT_NAME}",
            f"- North star: {NORTH_STAR}",
            f"- Generated at: {utc_now_iso()}",
            f"- Questions: {len(questions)}",
            "",
        ]
        for question in questions:
            lines.append(self.export_question(question.id, fmt="markdown"))
        return "\n".join(lines)

    def import_packet(self, packet: dict[str, Any], *, conflict: str = "error") -> dict[str, Any]:
        """Import a JSON packet produced by ``export_question`` or ``export_all``."""

        if conflict not in {"error", "skip", "replace"}:
            raise ValidationError("conflict must be error, skip, or replace")
        if not isinstance(packet, dict):
            raise ValidationError("forecast packet must be a JSON object")

        question_packets = self._question_packets_from_import(packet)
        if not question_packets and not any(
            isinstance(packet.get(key), list)
            for key in (
                "ingest_candidates",
                "watched_sources",
                "source_snapshots",
                "scheduled_reviews",
                "scheduled_review_runs",
                "autopilot_policies",
                "autopilot_runs",
                "forecast_update_proposals",
                "domain_error_profiles",
                "alerts",
            )
        ):
            raise ValidationError("forecast packet has no importable records")

        summary: dict[str, Any] = {
            "product": _export_metadata(),
            "imported_at": utc_now_iso(),
            "source_product": packet.get("product") if isinstance(packet.get("product"), dict) else None,
            "source_generated_at": packet.get("generated_at"),
            "conflict": conflict,
            "imported": defaultdict(int),
            "skipped_existing": 0,
            "replaced_existing": 0,
            "duplicates_in_packet": 0,
        }
        seen: set[tuple[str, str]] = set()

        with self._connect() as conn:
            for question_packet in question_packets:
                self._import_question_packet(conn, question_packet, conflict=conflict, summary=summary, seen=seen)
            self._import_packet_rows(
                conn,
                "ingest_candidates",
                packet.get("ingest_candidates"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "watched_sources",
                packet.get("watched_sources"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "source_snapshots",
                packet.get("source_snapshots"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "scheduled_reviews",
                packet.get("scheduled_reviews"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "scheduled_review_runs",
                packet.get("scheduled_review_runs"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "autopilot_policies",
                packet.get("autopilot_policies"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "autopilot_runs",
                packet.get("autopilot_runs"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "forecast_update_proposals",
                packet.get("forecast_update_proposals"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "domain_error_profiles",
                packet.get("domain_error_profiles"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "alert_events",
                packet.get("alerts"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )

        imported = dict(sorted(summary["imported"].items()))
        summary["imported"] = imported
        summary["imported_total"] = sum(imported.values())
        return summary

    def _question_packets_from_import(self, packet: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(packet.get("question"), dict):
            return [packet]
        questions = packet.get("questions")
        if questions is None:
            return []
        if not isinstance(questions, list):
            raise ValidationError("forecast packet questions field must be a list")
        result: list[dict[str, Any]] = []
        for index, question_packet in enumerate(questions):
            if not isinstance(question_packet, dict):
                raise ValidationError(f"forecast packet question entry {index} must be an object")
            result.append(question_packet)
        return result

    def _import_question_packet(
        self,
        conn: sqlite3.Connection,
        packet: dict[str, Any],
        *,
        conflict: str,
        summary: dict[str, Any],
        seen: set[tuple[str, str]],
    ) -> None:
        question = packet.get("question")
        if not isinstance(question, dict):
            raise ValidationError("question packet must include a question object")
        self._insert_packet_row(conn, "forecast_questions", question, conflict=conflict, summary=summary, seen=seen)
        for table, key in (
            ("assumptions", "assumptions"),
            ("reference_classes", "reference_classes"),
            ("model_runs", "model_runs"),
            ("evidence_items", "evidence"),
            ("forecast_snapshots", "forecast_history"),
            ("resolutions", "resolution"),
            ("score_records", "scores"),
            ("postmortems", "postmortems"),
            ("calibration_lessons", "calibration_lessons"),
            ("forecast_corrections", "corrections"),
            ("baseline_comparisons", "baseline_comparisons"),
            ("watched_sources", "watched_sources"),
            ("source_snapshots", "source_snapshots"),
            ("scheduled_reviews", "scheduled_reviews"),
            ("scheduled_review_runs", "scheduled_review_runs"),
            ("autopilot_policies", "autopilot_policies"),
            ("autopilot_runs", "autopilot_runs"),
            ("forecast_update_proposals", "forecast_update_proposals"),
            ("domain_error_profiles", "domain_error_profiles"),
        ):
            self._import_packet_rows(conn, table, packet.get(key), conflict=conflict, summary=summary, seen=seen)

    def _import_packet_rows(
        self,
        conn: sqlite3.Connection,
        table: str,
        rows: Any,
        *,
        conflict: str,
        summary: dict[str, Any],
        seen: set[tuple[str, str]],
    ) -> None:
        if rows is None:
            return
        if isinstance(rows, dict):
            rows_to_import = [rows]
        elif isinstance(rows, list):
            rows_to_import = rows
        else:
            raise ValidationError(f"{_PACKET_RECORD_LABELS[table]} must be an object or list")
        for index, row in enumerate(rows_to_import):
            if row is None:
                continue
            if not isinstance(row, dict):
                raise ValidationError(f"{_PACKET_RECORD_LABELS[table]} entry {index} must be an object")
            self._insert_packet_row(conn, table, row, conflict=conflict, summary=summary, seen=seen)

    def _insert_packet_row(
        self,
        conn: sqlite3.Connection,
        table: str,
        row: dict[str, Any],
        *,
        conflict: str,
        summary: dict[str, Any],
        seen: set[tuple[str, str]],
    ) -> None:
        pk = _PACKET_PRIMARY_KEYS.get(table, "id")
        record_id = str(row.get(pk) or "").strip()
        if not record_id:
            raise ValidationError(f"{_PACKET_RECORD_LABELS[table]} import row is missing {pk}")
        seen_key = (table, record_id)
        if seen_key in seen:
            summary["duplicates_in_packet"] += 1
            return
        seen.add(seen_key)

        existing = conn.execute(f"SELECT 1 FROM {table} WHERE {pk} = ?", (record_id,)).fetchone()
        if existing is not None:
            if conflict == "error":
                raise ValidationError(f"{_PACKET_RECORD_LABELS[table]} record already exists: {record_id}")
            if conflict == "skip":
                summary["skipped_existing"] += 1
                return
            conn.execute(f"DELETE FROM {table} WHERE {pk} = ?", (record_id,))
            summary["replaced_existing"] += 1

        table_columns = [column["name"] for column in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        columns = [column for column in table_columns if column in row]
        if pk not in columns:
            raise ValidationError(f"{_PACKET_RECORD_LABELS[table]} import row is missing {pk}")
        json_fields = _PACKET_JSON_FIELDS.get(table, set())
        bool_fields = _PACKET_BOOL_FIELDS.get(table, set())
        values: list[Any] = []
        for column in columns:
            value = row[column]
            if column in json_fields:
                value = json_dumps(value)
            elif column in bool_fields:
                value = 1 if bool(value) else 0
            values.append(value)
        placeholders = ", ".join("?" for _ in columns)
        conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        summary["imported"][_PACKET_RECORD_LABELS[table]] += 1

    def _existing_score(self, forecast_id: str, resolution_id: str) -> ScoreRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM score_records
                WHERE forecast_id = ? AND resolution_id = ?
                  AND invalidated_by_correction_id IS NULL
                ORDER BY scored_at DESC
                LIMIT 1
                """,
                (forecast_id, resolution_id),
            ).fetchone()
        return self._row_to_score(row) if row else None

    def _validate_evidence_refs(
        self,
        question_id: str,
        evidence_refs: list[str],
        evidence_cutoff: str | None,
    ) -> None:
        if not evidence_refs:
            return
        cutoff_dt = timestamp_to_datetime(evidence_cutoff)
        for evidence_id in evidence_refs:
            evidence = self.get_evidence(evidence_id)
            if evidence.question_id != question_id:
                raise ValidationError(f"evidence {evidence_id} does not belong to question {question_id}")
            if cutoff_dt is None:
                continue
            available_dt = timestamp_to_datetime(evidence.available_at)
            if available_dt and available_dt > cutoff_dt:
                raise ValidationError(
                    f"evidence {evidence_id} was available after the evidence cutoff"
                )

    def _validate_question_scoped_refs(
        self,
        question_id: str,
        refs: list[str],
        getter,
        label: str,
    ) -> None:
        for ref in refs:
            obj = getter(ref)
            if obj["question_id"] != question_id:
                raise ValidationError(f"{label} {ref} does not belong to question {question_id}")

    def _affected_records_for_correction(
        self,
        target_type: str,
        target_id: str,
    ) -> tuple[list[str], list[str], list[str]]:
        score_refs: list[str] = []
        postmortem_refs: list[str] = []
        lesson_refs: list[str] = []
        with self._connect() as conn:
            if target_type == "resolution":
                score_refs = [
                    row["id"]
                    for row in conn.execute(
                        "SELECT id FROM score_records WHERE resolution_id = ?",
                        (target_id,),
                    ).fetchall()
                ]
                postmortem_refs = [
                    row["id"]
                    for row in conn.execute(
                        "SELECT id FROM postmortems WHERE resolution_id = ?",
                        (target_id,),
                    ).fetchall()
                ]
            elif target_type == "score_record":
                score_refs = [target_id]
                postmortem_refs = [
                    row["id"]
                    for row in conn.execute(
                        "SELECT id FROM postmortems WHERE score_record_id = ?",
                        (target_id,),
                    ).fetchall()
                ]
            elif target_type == "postmortem":
                postmortem_refs = [target_id]
            elif target_type == "calibration_lesson":
                lesson_refs = [target_id]

            if postmortem_refs:
                all_lessons = conn.execute("SELECT id, source_postmortem_refs FROM calibration_lessons").fetchall()
                postmortem_set = set(postmortem_refs)
                for row in all_lessons:
                    refs = set(json_loads(row["source_postmortem_refs"], []))
                    if refs & postmortem_set:
                        lesson_refs.append(row["id"])
            if score_refs:
                all_lessons = conn.execute("SELECT id, source_score_record_refs FROM calibration_lessons").fetchall()
                score_set = set(score_refs)
                for row in all_lessons:
                    refs = set(json_loads(row["source_score_record_refs"], []))
                    if refs & score_set:
                        lesson_refs.append(row["id"])
        return sorted(set(score_refs)), sorted(set(postmortem_refs)), sorted(set(lesson_refs))

    def _invalidate_learning_records_for_correction(
        self,
        conn: sqlite3.Connection,
        *,
        correction_id: str,
        score_refs: list[str],
        postmortem_refs: list[str],
        lesson_refs: list[str],
    ) -> None:
        if score_refs:
            conn.executemany(
                "UPDATE score_records SET invalidated_by_correction_id = ? WHERE id = ?",
                [(correction_id, score_id) for score_id in score_refs],
            )
        if postmortem_refs:
            conn.executemany(
                "UPDATE postmortems SET invalidated_by_correction_id = ? WHERE id = ?",
                [(correction_id, postmortem_id) for postmortem_id in postmortem_refs],
            )
        if lesson_refs:
            conn.executemany(
                """
                UPDATE calibration_lessons
                SET invalidated_by_correction_id = ?, status = 'superseded', updated_at = ?
                WHERE id = ?
                """,
                [(correction_id, utc_now_iso(), lesson_id) for lesson_id in lesson_refs],
            )

    def _disable_backtest_calibration(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE forecast_snapshots
                SET calibration_eligible = 0, calibration_weight = 0
                WHERE backtest_run_id = ? AND forecast_origin = 'backtest'
                """,
                (run_id,),
            )
            conn.execute(
                """
                UPDATE score_records
                SET calibration_eligible = 0, calibration_weight = 0
                WHERE forecast_origin = 'backtest'
                  AND forecast_id IN (
                    SELECT forecast_id FROM forecast_snapshots WHERE backtest_run_id = ?
                  )
                """,
                (run_id,),
            )

    def _run_backtest_case(
        self,
        *,
        run_id: str,
        case: dict[str, Any],
        default_cutoff: str | None,
        allow_calibration_memory: bool,
    ) -> dict[str, Any]:
        simulated_time = parse_timestamp(
            case.get("simulated_forecast_time") or case.get("as_of") or default_cutoff,
            field_name="simulated_forecast_time",
        )
        if simulated_time is None:
            raise ValidationError("each backtest case needs simulated_forecast_time, as_of, or --as-of")
        evidence_cutoff = parse_timestamp(
            case.get("evidence_cutoff") or simulated_time,
            field_name="evidence_cutoff",
        )
        assert evidence_cutoff is not None

        outcome_data = case.get("outcome_space") or {}
        outcome_space = OutcomeSpace.from_dict(outcome_data) if outcome_data else OutcomeSpace()
        question = self.create_question(
            title=str(case.get("title") or "Untitled backtest case"),
            description=str(case.get("description") or ""),
            resolution_criteria=str(case.get("resolution_criteria") or "Backtest dataset supplied resolution criteria."),
            resolution_source=case.get("resolution_source"),
            outcome_space=outcome_space,
            close_time=case.get("close_time"),
            resolution_time=case.get("resolution_time"),
            tags=list(case.get("tags") or ["backtest"]),
            domain=case.get("domain"),
            topics=list(case.get("topics") or []),
            metadata={"backtest_run_id": run_id, "external_id": case.get("id")},
        )

        excluded = 0
        ambiguous = 0
        evidence_refs: list[str] = []
        cutoff_dt = timestamp_to_datetime(evidence_cutoff)
        for item in case.get("evidence") or []:
            available_raw = item.get("available_at") or item.get("published_at")
            if not available_raw:
                ambiguous += 1
                continue
            available = parse_timestamp(available_raw, field_name="available_at")
            available_dt = timestamp_to_datetime(available)
            if cutoff_dt and available_dt and available_dt > cutoff_dt:
                excluded += 1
                continue
            source_or_note = str(
                item.get("source")
                or item.get("url")
                or item.get("note")
                or item.get("summary")
                or item.get("claim")
                or "backtest evidence"
            )
            evidence = self.add_evidence(
                question_id=question.id,
                source_or_note=source_or_note,
                claim=str(item.get("claim") or ""),
                summary=str(item.get("summary") or ""),
                source_url=item.get("url"),
                source_name=item.get("source_name"),
                source_type=item.get("source_type"),
                published_at=item.get("published_at"),
                available_at=available,
                reliability_rating=item.get("reliability_rating"),
                relevance_rating=item.get("relevance_rating"),
                stance=item.get("stance") or "context",
                claim_type=item.get("claim_type") or "fact",
                metadata={"backtest_run_id": run_id},
            )
            evidence_refs.append(evidence.id)

        generated_forecast_id = None
        score_record_id = None
        if "outcome" in case:
            self.resolve_question(
                question_id=question.id,
                outcome=case["outcome"],
                resolution_source=case.get("resolution_source"),
                resolver_type="source_adapter",
                resolution_status="confirmed",
                criteria_satisfied=True,
            )
        probability = case.get("probability", case.get("forecast_probability"))
        distribution = case.get("distribution")
        if probability is not None or distribution is not None:
            calibration_eligible = allow_calibration_memory and ambiguous == 0
            snapshot = self.create_snapshot(
                question_id=question.id,
                probability_or_distribution=distribution if distribution is not None else probability,
                rationale=str(case.get("rationale") or "Backtest dataset forecast replay."),
                as_of=simulated_time,
                confidence=self._optional_unit_float(case.get("confidence")),
                method=str(case.get("method") or "backtest_replay"),
                ensemble_components=self._backtest_snapshot_components(case),
                evidence_refs=evidence_refs,
                forecast_origin="backtest",
                agent_model=case.get("agent_model"),
                prompt_version=case.get("prompt_version"),
                forecasting_protocol_version=case.get("forecasting_protocol_version"),
                evidence_cutoff=evidence_cutoff,
                backtest_run_id=run_id,
                calibration_eligible=calibration_eligible,
                calibration_weight=1.0 if calibration_eligible else 0.0,
                metadata=self._backtest_snapshot_metadata(case),
            )
            generated_forecast_id = snapshot.forecast_id
            if "outcome" in case:
                score = self.score_question(question.id)
                score_record_id = score.id

        baseline_refs = []
        for baseline in self._backtest_case_baselines(case, outcome_space):
            if "probability" not in baseline and "distribution" not in baseline:
                continue
            baseline_forecast_id = None
            baseline_score_id = None
            if "outcome" in case:
                baseline_snapshot = self.create_snapshot(
                    question_id=question.id,
                    probability_or_distribution=baseline.get("distribution", baseline.get("probability")),
                    rationale=f"Imported baseline from {baseline.get('source') or 'dataset'}.",
                    as_of=baseline.get("as_of") or simulated_time,
                    method=str(baseline.get("baseline_type") or "imported"),
                    forecast_origin="imported_baseline",
                    backtest_run_id=run_id,
                    calibration_eligible=False,
                    calibration_weight=0.0,
                    set_current=False,
                )
                baseline_forecast_id = baseline_snapshot.forecast_id
                baseline_score_id = self.score_snapshot(baseline_forecast_id).id
            comparison = self.add_baseline_comparison(
                question_id=question.id,
                source=str(baseline.get("source") or "dataset"),
                baseline_type=str(baseline.get("baseline_type") or "imported"),
                probability_or_distribution=baseline.get("distribution", baseline.get("probability")),
                as_of=baseline.get("as_of") or simulated_time,
                forecast_id=baseline_forecast_id,
                score_record_id=baseline_score_id,
                metadata={"backtest_run_id": run_id, "generated_forecast_id": generated_forecast_id},
            )
            baseline_refs.append(comparison["id"])

        leakage_status = "passed" if ambiguous == 0 else "ambiguous_evidence"
        case_id = f"btc_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO backtest_cases (
                    id, backtest_run_id, question_id, simulated_forecast_time,
                    evidence_cutoff, generated_forecast_id, baseline_comparison_refs,
                    score_record_id, leakage_check_status, excluded_evidence_count,
                    ambiguous_evidence_count, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    run_id,
                    question.id,
                    simulated_time,
                    evidence_cutoff,
                    generated_forecast_id,
                    json_dumps(baseline_refs),
                    score_record_id,
                    leakage_status,
                    excluded,
                    ambiguous,
                    case.get("notes"),
                ),
            )
        row = self.get_backtest_case(case_id)
        if score_record_id:
            row["score_brier"] = self.get_score(score_record_id).brier_score
        return row

    def get_backtest_case(self, case_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM backtest_cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"backtest case not found: {case_id}")
        return self._row_to_backtest_case(row)

    @staticmethod
    def _backtest_snapshot_components(case: dict[str, Any]) -> dict[str, Any]:
        components = case.get("ensemble_components")
        if isinstance(components, dict):
            return components
        component_forecasts = case.get("component_forecasts")
        if isinstance(component_forecasts, dict):
            return component_forecasts
        if not isinstance(component_forecasts, list):
            return {}
        normalized: dict[str, Any] = {}
        for index, component in enumerate(component_forecasts, start=1):
            if isinstance(component, dict):
                name = component.get("name") or component.get("source") or f"component_{index}"
                normalized[str(name)] = component
            else:
                normalized[f"component_{index}"] = component
        return normalized

    @staticmethod
    def _backtest_snapshot_metadata(case: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(case.get("forecast_metadata") or {})
        if case.get("probability_source"):
            metadata["probability_source"] = case["probability_source"]
        if case.get("id"):
            metadata["external_case_id"] = case["id"]
        return metadata

    @staticmethod
    def _optional_unit_float(value: Any) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                return None
        else:
            return None
        if 0 <= number <= 1:
            return number
        return None

    def _backtest_case_baselines(
        self,
        case: dict[str, Any],
        outcome_space: OutcomeSpace,
    ) -> list[dict[str, Any]]:
        baselines = [dict(row) for row in case.get("baselines") or [] if isinstance(row, dict)]
        has_explicit_baselines = bool(baselines)
        if not has_explicit_baselines and outcome_space.type == "binary" and not self._has_baseline(baselines, "naive_0_5", "auto"):
            baselines.append(
                {
                    "source": "auto",
                    "baseline_type": "naive_0_5",
                    "probability": 0.5,
                    "as_of": case.get("simulated_forecast_time") or case.get("as_of"),
                }
            )
        elif (
            not has_explicit_baselines
            and outcome_space.type == "categorical"
            and outcome_space.choices
            and not self._has_baseline(baselines, "uniform", "auto")
        ):
            probability = 1.0 / len(outcome_space.choices)
            baselines.append(
                {
                    "source": "auto",
                    "baseline_type": "uniform",
                    "distribution": {choice: probability for choice in outcome_space.choices},
                    "as_of": case.get("simulated_forecast_time") or case.get("as_of"),
                }
            )
        base_rate = case.get("base_rate")
        if base_rate is None:
            base_rate = case.get("base_rate_probability")
        if base_rate is not None and not self._has_baseline(baselines, "base_rate", "dataset"):
            baselines.append(
                {
                    "source": "dataset",
                    "baseline_type": "base_rate",
                    "probability": base_rate,
                    "as_of": case.get("simulated_forecast_time") or case.get("as_of"),
                }
            )
        return baselines

    def _has_baseline(self, baselines: list[dict[str, Any]], baseline_type: str, source: str) -> bool:
        return any(
            str(baseline.get("baseline_type") or "") == baseline_type
            and str(baseline.get("source") or "") == source
            for baseline in baselines
        )

    def _validate_probability_payload(self, value: Any, outcome_space: OutcomeSpace | None = None) -> Any:
        outcome_type = (outcome_space.type if outcome_space else "binary")
        if isinstance(value, bool):
            raise ValidationError("probability must be numeric, not boolean")
        if isinstance(value, (int, float)):
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValidationError("forecast value must be finite")
            if outcome_type == "numeric":
                return numeric
            if not (0 <= numeric <= 1):
                raise ValidationError("probability must be between 0 and 1")
            return numeric
        if isinstance(value, dict):
            if not value:
                raise ValidationError("forecast distribution cannot be empty")
            normalized: dict[str, float] = {}
            for key, raw in value.items():
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    raise ValidationError("distribution values must be numeric")
                numeric = float(raw)
                if not math.isfinite(numeric):
                    raise ValidationError("distribution values must be finite")
                if outcome_type not in {"numeric", "distribution"} and not (0 <= numeric <= 1):
                    raise ValidationError("distribution values must be between 0 and 1")
                normalized[str(key)] = numeric
            return normalized
        raise ValidationError("forecast update requires a probability or distribution")

    def _scoreability_issues(
        self,
        title: str,
        resolution_criteria: str,
        outcome_space: OutcomeSpace,
    ) -> list[str]:
        issues: list[str] = []
        criteria = resolution_criteria.strip().lower()
        title_lower = title.strip().lower()
        vague_markers = (
            r"\btbd\b",
            r"\btodo\b",
            r"\bunknown\b",
            r"\bunclear\b",
            r"\bnot\s+sure\b",
            r"\bto\s+be\s+decided\b",
            r"\bfigure\s+out\s+later\b",
        )
        if any(re.search(marker, criteria) for marker in vague_markers):
            issues.append("resolution criteria contain placeholder or vague language")
        if criteria in {"yes", "no", "maybe", "n/a", "na"}:
            issues.append("resolution criteria are too short to audit")
        if len(criteria.split()) < 5:
            issues.append("resolution criteria need an auditable condition")
        if outcome_space.type in {"numeric", "distribution"} and not outcome_space.units:
            issues.append("numeric or distributional forecasts need units")
        if outcome_space.type == "categorical" and len({choice.lower() for choice in outcome_space.choices}) != len(outcome_space.choices):
            issues.append("categorical outcome choices must be unique")
        if title_lower in {"will it happen?", "what will happen?", "forecast"}:
            issues.append("title is too generic")
        return issues

    def _binary_outcome_value(
        self, score: ScoreRecord, outcome_space: OutcomeSpace
    ) -> float | None:
        """Return 1.0 if the score's question resolved yes, 0.0 if no, else None
        (unknown/ambiguous outcome). Used for the reliability curve."""

        try:
            resolution = self.get_resolution(score.resolution_id)
        except LedgerNotFoundError:
            return None
        label = str(resolution.outcome).strip().lower()
        yes_labels = {"yes", "y", "true", "1", "occurred", "success"}
        no_labels = {"no", "n", "false", "0", "not_occurred", "failed"}
        choices = [str(choice).lower() for choice in outcome_space.choices]
        if label in yes_labels or (choices and label == choices[0]):
            return 1.0
        if label in no_labels or (len(choices) > 1 and label == choices[1]):
            return 0.0
        return None

    def _probability_for_outcome(
        self,
        probability_or_distribution: Any,
        outcome: Any,
        outcome_space: OutcomeSpace,
    ) -> float:
        outcome_label = str(outcome).strip().lower()
        if isinstance(probability_or_distribution, (int, float)):
            yes_labels = {"yes", "y", "true", "1", "occurred", "success"}
            no_labels = {"no", "n", "false", "0", "not_occurred", "failed"}
            if outcome_label in yes_labels or outcome_label == str(outcome_space.choices[0]).lower():
                return float(probability_or_distribution)
            if outcome_label in no_labels or outcome_label == str(outcome_space.choices[1]).lower():
                return 1.0 - float(probability_or_distribution)
            raise ValidationError(f"binary outcome is not recognized: {outcome}")
        if isinstance(probability_or_distribution, dict):
            lowered = {str(key).lower(): float(value) for key, value in probability_or_distribution.items()}
            if outcome_label not in lowered:
                raise ValidationError(f"outcome {outcome!r} is not present in the forecast distribution")
            return lowered[outcome_label]
        raise ValidationError("unsupported probability payload")

    def _score_forecast_payload(
        self,
        probability_or_distribution: Any,
        outcome: Any,
        outcome_space: OutcomeSpace,
    ) -> dict[str, Any]:
        if outcome_space.type in {"binary", "categorical"}:
            probability = self._probability_for_outcome(
                probability_or_distribution,
                outcome,
                outcome_space,
            )
            brier = self._brier_score(
                probability_or_distribution,
                outcome,
                outcome_space,
            )
            log_score = self._log_score(probability)
            return {
                "brier_score": brier,
                "log_score": log_score,
                "proper_score": brier,
                "score_rule": "brier",
                "calibration_bucket": self._probability_bucket(probability),
                "notes": "Brier score against confirmed resolution.",
            }

        if outcome_space.type == "numeric":
            forecast_value = self._numeric_forecast_point(probability_or_distribution)
            outcome_value = self._numeric_outcome(outcome)
            score, rule = self._numeric_squared_error(forecast_value, outcome_value, outcome_space)
            return {
                "brier_score": None,
                "log_score": None,
                "proper_score": score,
                "score_rule": rule,
                "calibration_bucket": self._numeric_bucket(forecast_value, outcome_space),
                "notes": f"{rule} against confirmed numeric resolution.",
            }

        if outcome_space.type == "distribution":
            if isinstance(probability_or_distribution, (int, float)):
                forecast_value = self._numeric_forecast_point(probability_or_distribution)
                outcome_value = self._numeric_outcome(outcome)
                score, rule = self._numeric_squared_error(forecast_value, outcome_value, outcome_space)
                return {
                    "brier_score": None,
                    "log_score": None,
                    "proper_score": score,
                    "score_rule": rule,
                    "calibration_bucket": self._numeric_bucket(forecast_value, outcome_space),
                    "notes": f"{rule} for distributional point summary against confirmed resolution.",
                }
            if isinstance(probability_or_distribution, dict):
                normal = self._normal_distribution_score(probability_or_distribution, outcome, outcome_space)
                if normal is not None:
                    return normal
                probability = self._probability_for_outcome(
                    probability_or_distribution,
                    outcome,
                    outcome_space,
                )
                brier = self._brier_score(
                    probability_or_distribution,
                    outcome,
                    outcome_space,
                )
                log_score = self._log_score(probability)
                return {
                    "brier_score": brier,
                    "log_score": log_score,
                    "proper_score": log_score,
                    "score_rule": "discrete_distribution_log_score",
                    "calibration_bucket": self._probability_bucket(probability),
                    "notes": "Discrete distribution log score against confirmed resolution.",
                }

        raise ValidationError(f"scoring is not implemented for outcome type: {outcome_space.type}")

    def _brier_score(
        self,
        probability_or_distribution: Any,
        outcome: Any,
        outcome_space: OutcomeSpace,
    ) -> float:
        if isinstance(probability_or_distribution, (int, float)):
            probability = float(probability_or_distribution)
            yes_labels = {"yes", "y", "true", "1", "occurred", "success"}
            outcome_label = str(outcome).strip().lower()
            observed = 1.0 if outcome_label in yes_labels or outcome_label == str(outcome_space.choices[0]).lower() else 0.0
            return (probability - observed) ** 2
        if isinstance(probability_or_distribution, dict):
            outcome_label = str(outcome).strip().lower()
            lowered = {str(key).lower(): float(value) for key, value in probability_or_distribution.items()}
            labels = {str(choice).lower() for choice in outcome_space.choices}
            labels.update(lowered.keys())
            return sum(
                (lowered.get(label, 0.0) - (1.0 if label == outcome_label else 0.0)) ** 2
                for label in labels
            )
        raise ValidationError("unsupported probability payload")

    def _log_score(self, resolved_probability: float) -> float:
        return -math.log(max(min(resolved_probability, 1.0), 1e-15))

    def _numeric_forecast_point(self, probability_or_distribution: Any) -> float:
        if isinstance(probability_or_distribution, bool):
            raise ValidationError("numeric forecast value must be numeric, not boolean")
        if isinstance(probability_or_distribution, (int, float)):
            value = float(probability_or_distribution)
        elif isinstance(probability_or_distribution, dict):
            for key in ("mean", "expected", "value", "point"):
                if key in probability_or_distribution:
                    value = float(probability_or_distribution[key])
                    break
            else:
                raise ValidationError("numeric distribution requires a mean, expected, value, or point field")
        else:
            raise ValidationError("numeric forecast value must be numeric")
        if not math.isfinite(value):
            raise ValidationError("numeric forecast value must be finite")
        return value

    def _numeric_outcome(self, outcome: Any) -> float:
        if isinstance(outcome, bool):
            raise ValidationError("numeric outcome must be numeric, not boolean")
        try:
            value = float(outcome)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"numeric outcome is not recognized: {outcome!r}") from exc
        if not math.isfinite(value):
            raise ValidationError("numeric outcome must be finite")
        return value

    def _numeric_squared_error(
        self,
        forecast_value: float,
        outcome_value: float,
        outcome_space: OutcomeSpace,
    ) -> tuple[float, str]:
        error = forecast_value - outcome_value
        bounds = outcome_space.bounds or []
        if len(bounds) == 2:
            low, high = float(bounds[0]), float(bounds[1])
            if math.isfinite(low) and math.isfinite(high) and high > low:
                return (error / (high - low)) ** 2, "normalized_squared_error"
        return error**2, "squared_error"

    def _numeric_bucket(self, value: float, outcome_space: OutcomeSpace) -> str:
        bounds = outcome_space.bounds or []
        if len(bounds) == 2:
            low, high = float(bounds[0]), float(bounds[1])
            if math.isfinite(low) and math.isfinite(high) and high > low:
                ratio = min(max((value - low) / (high - low), 0.0), 0.999999)
                return self._probability_bucket(ratio)
        return "numeric"

    def _normal_distribution_score(
        self,
        probability_or_distribution: dict[str, Any],
        outcome: Any,
        outcome_space: OutcomeSpace,
    ) -> dict[str, Any] | None:
        mean_key = next((key for key in ("mean", "expected", "value", "point") if key in probability_or_distribution), None)
        sd_key = next((key for key in ("sd", "std", "sigma", "stdev") if key in probability_or_distribution), None)
        if mean_key is None or sd_key is None:
            return None
        mean = float(probability_or_distribution[mean_key])
        sd = float(probability_or_distribution[sd_key])
        outcome_value = self._numeric_outcome(outcome)
        if not math.isfinite(mean) or not math.isfinite(sd) or sd <= 0:
            raise ValidationError("normal distribution scoring requires finite mean and positive standard deviation")
        variance = sd * sd
        negative_log_likelihood = 0.5 * math.log(2 * math.pi * variance) + ((outcome_value - mean) ** 2) / (2 * variance)
        mean_error, mean_rule = self._numeric_squared_error(mean, outcome_value, outcome_space)
        return {
            "brier_score": None,
            "log_score": negative_log_likelihood,
            "proper_score": negative_log_likelihood,
            "score_rule": "normal_negative_log_likelihood",
            "calibration_bucket": self._numeric_bucket(mean, outcome_space),
            "notes": f"Normal-distribution negative log likelihood; mean {mean_rule}={mean_error:.6g}.",
        }

    def _probability_bucket(self, probability: float) -> str:
        lower = min(int(probability * 10), 9) / 10
        upper = lower + 0.1
        return f"{lower:.1f}-{upper:.1f}"

    def _horizon_matches(self, horizon_days: float | None, horizon: str | None) -> bool:
        if horizon is None:
            return True
        if horizon_days is None:
            return False
        raw = horizon.strip().lower()
        if not raw:
            return True
        if raw.endswith("d"):
            raw = raw[:-1]
        try:
            if "-" in raw:
                start, end = raw.split("-", 1)
                return float(start) <= horizon_days <= float(end)
            return horizon_days <= float(raw)
        except ValueError as exc:
            raise ValidationError("horizon must be a day count or range like 30 or 30-90") from exc

    def _sharpness(self, probability_or_distribution: Any) -> float | None:
        if isinstance(probability_or_distribution, (int, float)):
            return abs(float(probability_or_distribution) - 0.5) * 2
        if isinstance(probability_or_distribution, dict) and probability_or_distribution:
            numeric = [
                float(value)
                for value in probability_or_distribution.values()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            ]
            if numeric:
                return max(numeric)
        return None

    def _archive_file_evidence_snapshot(
        self,
        *,
        question_id: str,
        evidence_id: str,
        source_file_path: Path,
    ) -> str:
        snapshot_dir = self.db_path.parent / "evidence_snapshots" / question_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{evidence_id}{source_file_path.suffix}"
        shutil.copy2(source_file_path, snapshot_path)
        return str(snapshot_path)

    def _archive_url_evidence_snapshot(
        self,
        *,
        question_id: str,
        evidence_id: str,
        source_url: str,
    ) -> dict[str, Any] | None:
        if not source_url.startswith(("http://", "https://")):
            return None
        snapshot_dir = self.db_path.parent / "evidence_snapshots" / question_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{evidence_id}.html"
        metadata_path = snapshot_dir / f"{evidence_id}.snapshot.json"
        request = Request(source_url, headers={"User-Agent": f"{PRODUCT_SLUG}/1"})
        try:
            with urlopen(request, timeout=5) as response:
                content = response.read(2_000_000)
                status = getattr(response, "status", None)
                content_type = response.headers.get("Content-Type")
        except (OSError, URLError, TimeoutError):
            return None
        snapshot_path.write_bytes(content)
        # Detect bot-block / interstitial pages disguised as HTTP 200
        # (Cloudflare challenge, DataDome, cookie wall, JS-required, …) so
        # downstream consumers don't treat the block markup as evidence.
        block_info = None
        try:
            from forecasting.source_adapters import detect_block_page

            decoded: str
            if isinstance(content_type, str) and ("text" in content_type.lower() or "html" in content_type.lower() or "json" in content_type.lower()):
                decoded = content.decode("utf-8", errors="replace")
            elif content_type is None:
                decoded = content[:8192].decode("utf-8", errors="replace")
            else:
                decoded = ""
            if decoded:
                block_info = detect_block_page(decoded, status=status)
        except Exception:
            block_info = None
        metadata = {
            "url": source_url,
            "captured_at": utc_now_iso(),
            "status": status,
            "content_type": content_type,
            "snapshot_path": str(snapshot_path),
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
        if block_info is not None:
            metadata["blocked"] = True
            metadata["block_reason"] = block_info["reason"]
            metadata["block_signal"] = block_info["signal"]
        metadata_path.write_text(json_dumps(metadata), encoding="utf-8")
        metadata["metadata_path"] = str(metadata_path)
        return metadata

    def _archive_resolution_source_snapshot(
        self,
        *,
        question_id: str,
        resolution_id: str,
        source_file_path: Path,
    ) -> str:
        snapshot_dir = self.db_path.parent / "resolution_snapshots" / question_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{resolution_id}{source_file_path.suffix}"
        shutil.copy2(source_file_path, snapshot_path)
        return str(snapshot_path)

    def _calibration_lessons_for_question(
        self,
        scores: list[ScoreRecord],
        postmortems: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        score_ids = {score.id for score in scores}
        postmortem_ids = {postmortem["id"] for postmortem in postmortems}
        lessons = []
        for lesson in self.list_calibration_lessons():
            if score_ids & set(lesson["source_score_record_refs"]):
                lessons.append(lesson)
            elif postmortem_ids & set(lesson["source_postmortem_refs"]):
                lessons.append(lesson)
        return lessons

    def _domain_error_profiles_for_question(self, question: ForecastQuestion) -> list[dict[str, Any]]:
        if not question.domain:
            return []
        profiles = []
        for profile in self.list_domain_error_profiles(domain=question.domain):
            profile_topic = profile.get("topic")
            if profile_topic and profile_topic not in question.topics:
                continue
            profile_type = profile.get("question_type")
            if profile_type and profile_type != question.outcome_space.type:
                continue
            profiles.append(profile)
        return profiles

    def _corrections_for_question(
        self,
        *,
        question_id: str,
        snapshots: list[ForecastSnapshot],
        evidence: list[EvidenceItem],
        assumptions: list[dict[str, Any]],
        reference_classes: list[dict[str, Any]],
        model_runs: list[dict[str, Any]],
        resolution: Resolution | None,
        scores: list[ScoreRecord],
        postmortems: list[dict[str, Any]],
        calibration_lessons: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        del model_runs
        ids_by_type = {
            "forecast_snapshot": {snapshot.forecast_id for snapshot in snapshots},
            "evidence_item": {item.id for item in evidence},
            "assumption": {item["id"] for item in assumptions},
            "reference_class": {item["id"] for item in reference_classes},
            "resolution": {resolution.id} if resolution else set(),
            "score_record": {score.id for score in scores},
            "postmortem": {item["id"] for item in postmortems},
            "calibration_lesson": {item["id"] for item in calibration_lessons},
        }
        corrections = []
        for correction in self.list_corrections():
            if correction["target_type"] in ids_by_type and correction["target_id"] in ids_by_type[correction["target_type"]]:
                corrections.append(correction)
        return corrections

    def _score_summary(self, scores: list[ScoreRecord]) -> dict[str, Any]:
        return {
            "count": len(scores),
            "mean_brier": self._mean([score.brier_score for score in scores]),
            "mean_log_score": self._mean([score.log_score for score in scores]),
        }

    def _score_breakdown(
        self,
        scores: list[ScoreRecord],
        key_fn,
    ) -> dict[str, dict[str, Any]]:
        buckets: dict[str, list[ScoreRecord]] = defaultdict(list)
        for score in scores:
            buckets[str(key_fn(score))].append(score)
        return {key: self._score_summary(bucket_scores) for key, bucket_scores in sorted(buckets.items())}

    def _score_horizon_bucket(self, score: ScoreRecord) -> str:
        horizon = score.forecast_horizon_days
        if horizon is None:
            return "unknown"
        if horizon <= 7:
            return "0-7d"
        if horizon <= 30:
            return "8-30d"
        if horizon <= 90:
            return "31-90d"
        if horizon <= 365:
            return "91-365d"
        return "365d+"

    def _paired_brier_summary(
        self,
        pairs: list[tuple[ScoreRecord, ScoreRecord]],
    ) -> dict[str, Any]:
        deltas: list[float] = []
        agent_scores: list[float] = []
        baseline_scores: list[float] = []
        agent_wins = baseline_wins = ties = 0
        for agent, baseline in pairs:
            if agent.brier_score is None or baseline.brier_score is None:
                continue
            agent_brier = float(agent.brier_score)
            baseline_brier = float(baseline.brier_score)
            agent_scores.append(agent_brier)
            baseline_scores.append(baseline_brier)
            deltas.append(baseline_brier - agent_brier)
            if agent_brier < baseline_brier:
                agent_wins += 1
            elif agent_brier > baseline_brier:
                baseline_wins += 1
            else:
                ties += 1

        count = len(deltas)
        mean_delta = self._mean(deltas)
        ci_low = ci_high = None
        if count > 1 and mean_delta is not None:
            variance = sum((delta - mean_delta) ** 2 for delta in deltas) / (count - 1)
            margin = 1.96 * math.sqrt(variance / count)
            ci_low = mean_delta - margin
            ci_high = mean_delta + margin
        return {
            "paired_brier_count": count,
            "paired_agent_mean_brier": self._mean(agent_scores),
            "paired_baseline_mean_brier": self._mean(baseline_scores),
            "paired_agent_edge_mean_brier": mean_delta,
            "paired_agent_edge_ci95_low": ci_low,
            "paired_agent_edge_ci95_high": ci_high,
            "paired_agent_wins": agent_wins,
            "paired_baseline_wins": baseline_wins,
            "paired_ties": ties,
        }

    def _mean(self, values: list[float | None]) -> float | None:
        clean = [value for value in values if value is not None]
        return sum(clean) / len(clean) if clean else None

    def _forecast_horizon_days(self, close_time: str | None, as_of: str) -> float | None:
        close_dt = timestamp_to_datetime(close_time)
        as_of_dt = timestamp_to_datetime(as_of)
        if not close_dt or not as_of_dt:
            return None
        return max((close_dt - as_of_dt).total_seconds() / 86400.0, 0.0)

    def _review_priority(self, reasons: list[str]) -> int:
        if any(reason.startswith("new_evidence:") for reason in reasons):
            return 0
        if any(
            reason in {"resolution_check_due", "close_time_passed"}
            or reason.startswith("close_time_within_")
            for reason in reasons
        ):
            return 1
        if any(reason.startswith(("assumption_invalidated:", "reference_class_invalidated:")) for reason in reasons):
            return 2
        if any(
            reason in {"review_due", "no_forecast_snapshot", "no_evidence"}
            or reason.startswith(("large_forecast_delta:", "assumption_check_due:", "reference_class_check_due:", "assumption_stale:", "reference_class_stale:"))
            for reason in reasons
        ):
            return 3
        if any(reason.startswith(("last_update_", "evidence_stale_")) for reason in reasons):
            return 4
        return 9

    def _recommended_action(self, reason: str) -> str:
        if reason.startswith("assumption_invalidated:"):
            return "Update the forecast or replace the invalidated assumption."
        if reason.startswith("assumption_stale:") or reason.startswith("assumption_check_due:"):
            return "Re-check the assumption and record fresh evidence or mark it resolved/invalidated."
        if reason.startswith("reference_class_invalidated:"):
            return "Replace the reference class or rerun the base-rate estimate before updating probability."
        if reason.startswith("reference_class_stale:") or reason.startswith("reference_class_check_due:"):
            return "Refresh the reference class and base-rate evidence."
        if reason == "no_evidence":
            return "Run `forecast research` or add evidence before trusting the current probability."
        if reason.startswith("new_evidence:"):
            return "Review the new evidence and append a forecast update if it changes the probability."
        if reason.startswith("evidence_stale_"):
            return "Refresh evidence and decide whether a new forecast snapshot is warranted."
        if reason.startswith("large_forecast_delta:"):
            return "Review the large probability move; record what changed and whether assumptions or calibration lessons need updates."
        if reason.startswith("close_time_within_"):
            return "Review evidence and prepare for close/resolution before the question closes."
        return {
            "no_forecast_snapshot": "Run `forecast update` to create an explicit probability.",
            "review_due": "Run a research pass or update the forecast rationale.",
            "close_time_passed": "Check whether the question should be closed or resolved.",
            "resolution_check_due": "Confirm resolution criteria and score if resolved.",
        }.get(reason, "Review the forecast and decide whether a new snapshot is warranted.")

    def _auto_postmortem_lesson(self, question: ForecastQuestion, score: ScoreRecord) -> str:
        if not score.calibration_eligible or score.forecast_origin not in {"live", "backtest"}:
            return ""
        if score.brier_score is None or score.brier_score < 0.25:
            return ""
        scope = question.domain or "global"
        origin_prefix = (
            "Recent"
            if score.forecast_origin == "live"
            else f"Eligible {score.forecast_origin} replay"
        )
        tags = self._auto_postmortem_error_tags(score)
        if "overconfidence" in tags:
            return (
                f"{origin_prefix} high-confidence miss in {scope}; require explicit base-rate, "
                "counterevidence, and assumption-staleness checks before similar extreme probabilities."
            )
        return (
            f"{origin_prefix} high-Brier resolved forecast in {scope}; check base rates, "
            "missed evidence, and confidence before similar updates."
        )

    def _auto_postmortem_adjustment(self, question: ForecastQuestion, score: ScoreRecord) -> dict[str, Any]:
        if not score.calibration_eligible or score.forecast_origin not in {"live", "backtest"}:
            return {}
        tags = self._auto_postmortem_error_tags(score)
        if not tags:
            return {}
        checklist = [
            "Compare against a current reference class before changing probability.",
            "Look for counterevidence from at least one independent source class.",
            "Re-check active assumptions and evidence freshness before the next update.",
        ]
        return {
            "error_tags": tags,
            "forecast_origin": score.forecast_origin,
            "requires_review_before_live_use": score.forecast_origin != "live",
            "review_checklist": checklist,
            "scope": question.domain or "global",
        }

    def _auto_postmortem_error_tags(self, score: ScoreRecord) -> list[str]:
        if score.brier_score is None or score.brier_score < 0.25:
            return []
        tags = ["high_brier_miss"]
        try:
            snapshot = self.get_snapshot(score.forecast_id)
        except LedgerNotFoundError:
            return tags
        sharpness = self._sharpness(snapshot.probability_or_distribution)
        if sharpness is not None and sharpness >= 0.6:
            tags.insert(0, "overconfidence")
        return tags

    def _question_in_portfolio(self, question: ForecastQuestion, portfolio: str) -> bool:
        portfolio = portfolio.strip()
        if not portfolio:
            return True
        expected_tags = {portfolio, f"portfolio:{portfolio}", f"portfolio={portfolio}"}
        if any(tag in expected_tags for tag in question.tags):
            return True
        metadata_portfolio = question.metadata.get("portfolio")
        if isinstance(metadata_portfolio, str) and metadata_portfolio == portfolio:
            return True
        metadata_portfolios = question.metadata.get("portfolios")
        if isinstance(metadata_portfolios, list) and portfolio in metadata_portfolios:
            return True
        return False

    def _question_matches_confidence(
        self,
        question_id: str,
        *,
        confidence_below: float | None,
        confidence_above: float | None,
    ) -> bool:
        if confidence_below is None and confidence_above is None:
            return True
        snapshot = self.get_current_snapshot(question_id)
        if snapshot is None or snapshot.confidence is None:
            return False
        if confidence_below is not None and snapshot.confidence >= confidence_below:
            return False
        if confidence_above is not None and snapshot.confidence <= confidence_above:
            return False
        return True

    @staticmethod
    def _validate_confidence_filters(
        *,
        confidence_below: float | None,
        confidence_above: float | None,
    ) -> None:
        for label, value in (
            ("confidence_below", confidence_below),
            ("confidence_above", confidence_above),
        ):
            if value is not None and not 0 <= value <= 1:
                raise ValidationError(f"{label} must be between 0 and 1")

    @staticmethod
    def _validate_probability_threshold(value: float | None, *, field_name: str) -> None:
        if value is not None and not 0 <= value <= 1:
            raise ValidationError(f"{field_name} must be between 0 and 1")

    def _latest_forecast_delta(self, question_id: str) -> float | None:
        snapshots = self.list_snapshots(question_id)
        if len(snapshots) < 2:
            return None
        previous, current = snapshots[-2], snapshots[-1]
        return self._probability_delta(
            previous.probability_or_distribution,
            current.probability_or_distribution,
        )

    @staticmethod
    def _probability_delta(previous: Any, current: Any) -> float | None:
        if isinstance(previous, bool) or isinstance(current, bool):
            return None
        if isinstance(previous, (int, float)) and isinstance(current, (int, float)):
            return float(current) - float(previous)
        return None

    def _score_probability_movement_before_close(
        self,
        score: ScoreRecord,
        scored_snapshot: ForecastSnapshot,
    ) -> float | None:
        """Return final-minus-initial probability movement for the scored forecast path."""

        try:
            question = self.get_question(score.question_id)
        except LedgerNotFoundError:
            return None
        scored_as_of = timestamp_to_datetime(scored_snapshot.as_of)
        close_time = timestamp_to_datetime(question.close_time) if question.close_time else None
        cutoff = close_time or scored_as_of
        numeric_snapshots: list[ForecastSnapshot] = []
        for snapshot in self.list_snapshots(score.question_id):
            if snapshot.forecast_origin != scored_snapshot.forecast_origin:
                continue
            if snapshot.backtest_run_id != scored_snapshot.backtest_run_id:
                continue
            snapshot_as_of = timestamp_to_datetime(snapshot.as_of)
            if cutoff and snapshot_as_of and snapshot_as_of > cutoff:
                continue
            if scored_as_of and snapshot_as_of and snapshot_as_of > scored_as_of:
                continue
            if self._numeric_probability(snapshot.probability_or_distribution) is None:
                continue
            numeric_snapshots.append(snapshot)
        if len(numeric_snapshots) < 2:
            return None
        first = self._numeric_probability(numeric_snapshots[0].probability_or_distribution)
        last = self._numeric_probability(numeric_snapshots[-1].probability_or_distribution)
        if first is None or last is None:
            return None
        return last - first

    @staticmethod
    def _numeric_probability(payload: Any) -> float | None:
        if isinstance(payload, bool):
            return None
        if isinstance(payload, (int, float)):
            return float(payload)
        return None

    def _snapshot_component_contributions(self, snapshot: ForecastSnapshot) -> list[dict[str, Any]]:
        forecast_probability = self._numeric_probability(snapshot.probability_or_distribution)
        rows = self._ensemble_component_rows(snapshot.ensemble_components)
        total_weight = sum(row["weight"] for row in rows)
        if total_weight <= 0:
            return []
        contributions: list[dict[str, Any]] = []
        for row in rows:
            weight_share = row["weight"] / total_weight
            contribution = row["probability"] * weight_share
            distance = (
                row["probability"] - forecast_probability
                if forecast_probability is not None
                else None
            )
            contributions.append(
                {
                    "name": row["name"],
                    "probability": row["probability"],
                    "weight": row["weight"],
                    "weight_share": weight_share,
                    "contribution": contribution,
                    "distance_from_forecast": distance,
                }
            )
        return contributions

    def _ensemble_component_rows(self, components: dict[str, Any]) -> list[dict[str, Any]]:
        raw_rows: list[Any]
        if isinstance(components.get("components"), list):
            raw_rows = components["components"]
        else:
            raw_rows = [
                {"name": name, **value}
                if isinstance(value, dict)
                else {"name": name, "probability": value}
                for name, value in components.items()
            ]
        rows: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_rows, start=1):
            if not isinstance(raw, dict):
                continue
            probability = self._numeric_probability(raw.get("probability"))
            weight = self._numeric_probability(raw.get("weight", 1.0))
            if probability is None or weight is None or weight < 0:
                continue
            rows.append(
                {
                    "name": str(raw.get("name") or raw.get("source") or f"component_{index}"),
                    "probability": probability,
                    "weight": weight,
                }
            )
        return rows

    @staticmethod
    def _is_high_impact_question(question: ForecastQuestion) -> bool:
        return (question.impact or "").strip().lower() in {"high", "critical", "material"}

    def _domain_error_profile_alerts(
        self,
        *,
        domain: str | None,
        topic: str | None,
        questions: list[ForecastQuestion],
    ) -> list[AlertEvent]:
        profile_filters: set[tuple[str | None, str | None]] = set()
        if domain or topic:
            profile_filters.add((domain, topic))
        for question in questions:
            if question.domain:
                profile_filters.add((question.domain, None))
                for question_topic in question.topics:
                    profile_filters.add((question.domain, question_topic))
        alerts: list[AlertEvent] = []
        seen_profiles: set[str] = set()
        for profile_domain, profile_topic in profile_filters:
            for profile in self.list_domain_error_profiles(domain=profile_domain, topic=profile_topic):
                if profile["id"] in seen_profiles:
                    continue
                if not profile["recurring_errors"] and not profile["recommended_adjustments"]:
                    continue
                seen_profiles.add(profile["id"])
                matching_questions = self._active_questions_for_error_profile(profile, questions)
                matching_ids = [question.id for question in matching_questions[:5]]
                matching_summary = (
                    f" Active matching forecasts: {', '.join(matching_ids)}."
                    if matching_ids
                    else ""
                )
                alerts.append(
                    self.create_alert(
                        severity="info",
                        scope_type="domain_error_profile",
                        scope_ref=profile["id"],
                        reason="domain_error_profile_review",
                        recommended_action=(
                            "Review active forecasts in this scope against recurring errors: "
                            + ", ".join(profile["recurring_errors"] or profile["recommended_adjustments"])
                            + "."
                            + matching_summary
                        ),
                    )
                )
                for question in matching_questions:
                    alerts.append(
                        self.create_alert(
                            severity="warning",
                            scope_type="question",
                            scope_ref=question.id,
                            reason=f"domain_error_profile_applies:{profile['id']}",
                            recommended_action=self._error_profile_question_action(profile, question),
                        )
                    )
        return alerts

    def _active_questions_for_error_profile(
        self,
        profile: dict[str, Any],
        questions: list[ForecastQuestion],
    ) -> list[ForecastQuestion]:
        profile_domain = profile.get("domain")
        profile_topic = profile.get("topic")
        profile_question_type = profile.get("question_type")
        result: list[ForecastQuestion] = []
        seen: set[str] = set()
        for question in questions:
            if question.id in seen or question.status != "active":
                continue
            if profile_domain and question.domain != profile_domain:
                continue
            if profile_topic and profile_topic not in question.topics:
                continue
            if profile_question_type and question.outcome_space.type != profile_question_type:
                continue
            result.append(question)
            seen.add(question.id)
        return result

    def _error_profile_question_action(
        self,
        profile: dict[str, Any],
        question: ForecastQuestion,
    ) -> str:
        recurring = list(profile.get("recurring_errors") or profile.get("recommended_adjustments") or [])
        patterns = ", ".join(str(item) for item in recurring[:4]) or "recent misses"
        return (
            "Review this active forecast against learned error patterns "
            f"({patterns}). Inspect `forecast show {question.id}`, refresh evidence, "
            "and save any probability change explicitly with `forecast update`."
        )

    def _calibration_lesson_review_alerts(
        self,
        *,
        domain: str | None,
        topic: str | None,
        questions: list[ForecastQuestion],
    ) -> list[AlertEvent]:
        candidates: dict[str, dict[str, Any]] = {}

        def add_lesson(lesson: dict[str, Any]) -> None:
            if lesson.get("status") != "tentative":
                return
            if lesson.get("invalidated_by_correction_id"):
                return
            candidates[lesson["id"]] = lesson

        if domain:
            for lesson in self.list_calibration_lessons(scope_type="domain", scope_ref=domain):
                add_lesson(lesson)
        if topic:
            for lesson in self.list_calibration_lessons(scope_type="topic", scope_ref=topic):
                add_lesson(lesson)

        all_scores = self.list_scores()
        for question in questions:
            if question.domain:
                for lesson in self.list_calibration_lessons(scope_type="domain", scope_ref=question.domain):
                    add_lesson(lesson)
            for question_topic in question.topics:
                for lesson in self.list_calibration_lessons(scope_type="topic", scope_ref=question_topic):
                    add_lesson(lesson)
            question_scores = [score for score in all_scores if score.question_id == question.id]
            postmortems = self.list_postmortems(question.id)
            for lesson in self._calibration_lessons_for_question(question_scores, postmortems):
                add_lesson(lesson)

        if not any([domain, topic, questions]):
            for lesson in self.list_calibration_lessons(scope_type="global", scope_ref=None):
                add_lesson(lesson)

        alerts: list[AlertEvent] = []
        for lesson in sorted(candidates.values(), key=lambda item: item["updated_at"], reverse=True):
            alerts.append(
                self.create_alert(
                    severity="info",
                    scope_type="calibration_lesson",
                    scope_ref=lesson["id"],
                    reason="calibration_lesson_review",
                    recommended_action=(
                        f"Review tentative lesson {lesson['id']} with `forecast lesson status {lesson['id']} "
                        "--status active` or reject/supersede it before relying on it for future updates."
                    ),
                )
            )
        return alerts

    def _benchmark_evidence_alerts(self) -> list[AlertEvent]:
        from forecasting.backtesting import (
            build_backtest_performance_summaries,
            build_forecasting_evidence_status,
        )

        rows = self.list_backtest_runs()[:20]
        status = build_forecasting_evidence_status(
            self,
            build_backtest_performance_summaries(self, rows),
        )
        gaps = list(status.get("gaps") or [])
        if not gaps:
            return []
        command_hints = [
            commands[0]
            for action in list(status.get("next_actions") or [])[:3]
            if (commands := list(action.get("commands") or []))
        ]
        command_hint = (
            f" Suggested commands: {'; '.join(command_hints)}."
            if command_hints
            else ""
        )
        return [
            self.create_alert(
                severity="warning",
                scope_type="global",
                scope_ref="benchmark_evidence",
                reason="benchmark_evidence_gaps",
                recommended_action=(
                    "Run `forecast performance --json` and close evidence gaps: "
                    f"{', '.join(gaps[:5])}. Collect live scored forecasts and "
                    "agent-protocol held-out runs, and include external resolved-question "
                    "corpora from at least two source families before claiming live "
                    f"superiority.{command_hint}"
                ),
            )
        ]

    def _advance_cadence(self, now_ts: str, cadence: str) -> str:
        now_dt = timestamp_to_datetime(now_ts)
        assert now_dt is not None
        delta = self._cadence_delta(cadence)
        return (now_dt + delta).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _cadence_due(self, last_checked_at: str | None, cadence: str | None, now_dt) -> bool:
        if not last_checked_at or not cadence:
            return False
        last_dt = timestamp_to_datetime(last_checked_at)
        if last_dt is None:
            return False
        return last_dt + self._cadence_delta(cadence) <= now_dt

    def _cadence_delta(self, cadence: str) -> timedelta:
        raw = re.sub(r"\s+", " ", cadence.strip().lower())
        if raw.startswith("every "):
            raw = raw[len("every "):].strip()
        if raw in {"daily", "1d"}:
            return timedelta(days=1)
        elif raw in {"weekly", "1w"}:
            return timedelta(days=7)
        elif raw == "hourly":
            return timedelta(hours=1)
        elif raw == "minutely":
            return timedelta(minutes=1)

        match = re.fullmatch(
            r"(?P<count>\d*)\s*(?P<unit>w|week|weeks|d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes)",
            raw,
        )
        if match:
            count = max(int(match.group("count") or "1"), 1)
            unit = match.group("unit")
            if unit in {"w", "week", "weeks"}:
                return timedelta(days=count * 7)
            if unit in {"d", "day", "days"}:
                return timedelta(days=count)
            if unit in {"h", "hr", "hrs", "hour", "hours"}:
                return timedelta(hours=count)
            return timedelta(minutes=count)
        return timedelta(days=1)

    def _row_to_question(self, row: sqlite3.Row) -> ForecastQuestion:
        row_keys = row.keys()
        return ForecastQuestion(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            resolution_criteria=row["resolution_criteria"],
            resolution_source=row["resolution_source"],
            created_at=row["created_at"],
            close_time=row["close_time"],
            resolution_time=row["resolution_time"],
            outcome_space=OutcomeSpace.from_json(row["outcome_space"]),
            status=row["status"],
            tags=json_loads(row["tags"], []),
            domain=row["domain"],
            topics=json_loads(row["topics"], []),
            owner=row["owner"],
            impact=row["impact"],
            review_cadence=row["review_cadence"],
            next_review_at=row["next_review_at"],
            current_forecast_id=row["current_forecast_id"],
            metadata=json_loads(row["metadata"], {}),
            decision_owner=row["decision_owner"] if "decision_owner" in row_keys else None,
            decision_deadline=row["decision_deadline"] if "decision_deadline" in row_keys else None,
            action_threshold=row["action_threshold"] if "action_threshold" in row_keys else None,
            update_triggers=(
                json_loads(row["update_triggers"], []) if "update_triggers" in row_keys else []
            ),
        )

    def _row_to_snapshot(self, row: sqlite3.Row) -> ForecastSnapshot:
        row_keys = row.keys()
        return ForecastSnapshot(
            forecast_id=row["forecast_id"],
            question_id=row["question_id"],
            created_at=row["created_at"],
            as_of=row["as_of"],
            probability_or_distribution=json_loads(row["probability_or_distribution"], None),
            confidence=row["confidence"],
            forecast_horizon_days=row["forecast_horizon_days"],
            method=row["method"],
            ensemble_components=json_loads(row["ensemble_components"], {}),
            rationale=row["rationale"],
            key_assumptions=json_loads(row["key_assumptions"], []),
            assumption_refs=json_loads(row["assumption_refs"], []),
            reference_class_refs=json_loads(row["reference_class_refs"], []),
            evidence_refs=json_loads(row["evidence_refs"], []),
            model_run_refs=json_loads(row["model_run_refs"], []),
            parent_forecast_id=row["parent_forecast_id"],
            forecast_origin=row["forecast_origin"],
            agent_model=row["agent_model"],
            prompt_version=row["prompt_version"],
            forecasting_protocol_version=row["forecasting_protocol_version"],
            toolset_version=row["toolset_version"],
            source_snapshot_refs=json_loads(row["source_snapshot_refs"], []),
            evidence_cutoff=row["evidence_cutoff"],
            backtest_run_id=row["backtest_run_id"],
            calibration_eligible=bool(row["calibration_eligible"]),
            calibration_weight=row["calibration_weight"],
            calibration_lesson_refs=json_loads(row["calibration_lesson_refs"], []),
            calibration_adjustment=json_loads(row["calibration_adjustment"], {}),
            metadata=json_loads(row["metadata"], {}),
            reasons_up=json_loads(row["reasons_up"], []) if "reasons_up" in row_keys else [],
            reasons_down=json_loads(row["reasons_down"], []) if "reasons_down" in row_keys else [],
            change_my_mind=(
                json_loads(row["change_my_mind"], []) if "change_my_mind" in row_keys else []
            ),
        )

    def _row_to_evidence(self, row: sqlite3.Row) -> EvidenceItem:
        return EvidenceItem(
            id=row["id"],
            question_id=row["question_id"],
            captured_at=row["captured_at"],
            available_at=row["available_at"],
            source_url=row["source_url"],
            source_name=row["source_name"],
            source_type=row["source_type"],
            published_at=row["published_at"],
            claim=row["claim"],
            summary=row["summary"],
            reliability_rating=row["reliability_rating"],
            relevance_rating=row["relevance_rating"],
            stance=row["stance"],
            claim_type=row["claim_type"],
            snapshot_path=row["snapshot_path"],
            admissible_for_backtests=bool(row["admissible_for_backtests"]),
            metadata=json_loads(row["metadata"], {}),
        )

    def _row_to_ingest_candidate(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["outcome_space"] = json_loads(data["outcome_space"], {})
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def _row_to_resolution(self, row: sqlite3.Row) -> Resolution:
        return Resolution(
            id=row["id"],
            question_id=row["question_id"],
            resolved_at=row["resolved_at"],
            outcome=json_loads(row["outcome"], row["outcome"]),
            resolution_source=row["resolution_source"],
            resolution_source_snapshot_ref=row["resolution_source_snapshot_ref"],
            resolver_type=row["resolver_type"],
            resolution_status=row["resolution_status"],
            criteria_satisfied=bool(row["criteria_satisfied"]),
            confidence=row["confidence"],
            confirmed_at=row["confirmed_at"],
            confirmed_by=row["confirmed_by"],
            resolver_notes=row["resolver_notes"],
            disputed_at=row["disputed_at"],
            correction_ref=row["correction_ref"],
            scoreable=bool(row["scoreable"]),
            trusted_policy_id=row["trusted_policy_id"],
        )

    def _row_to_score(self, row: sqlite3.Row) -> ScoreRecord:
        return ScoreRecord(
            id=row["id"],
            question_id=row["question_id"],
            forecast_id=row["forecast_id"],
            resolution_id=row["resolution_id"],
            scored_at=row["scored_at"],
            brier_score=row["brier_score"],
            log_score=row["log_score"],
            proper_score=row["proper_score"],
            score_rule=row["score_rule"],
            calibration_bucket=row["calibration_bucket"],
            forecast_horizon_days=row["forecast_horizon_days"],
            domain=row["domain"],
            forecast_origin=row["forecast_origin"],
            calibration_eligible=bool(row["calibration_eligible"]),
            calibration_weight=row["calibration_weight"],
            baseline_ref=row["baseline_ref"],
            invalidated_by_correction_id=row["invalidated_by_correction_id"],
            notes=row["notes"],
        )

    def _row_to_alert(self, row: sqlite3.Row) -> AlertEvent:
        return AlertEvent(
            id=row["id"],
            created_at=row["created_at"],
            severity=row["severity"],
            scope_type=row["scope_type"],
            scope_ref=row["scope_ref"],
            reason=row["reason"],
            recommended_action=row["recommended_action"],
            acknowledged_at=row["acknowledged_at"],
        )

    def _row_to_scheduled_review_run(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def _row_to_model_run(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for field in ("inputs", "parameters", "output", "diagnostics"):
            data[field] = json_loads(data[field], {})
        data["artifact_paths"] = json_loads(data["artifact_paths"], [])
        return data

    def _row_to_calibration_lesson(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["recommended_adjustment"] = json_loads(data["recommended_adjustment"], {})
        data["source_postmortem_refs"] = json_loads(data["source_postmortem_refs"], [])
        data["source_score_record_refs"] = json_loads(data["source_score_record_refs"], [])
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def _row_to_domain_error_profile(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["calibration_summary"] = json_loads(data["calibration_summary"], {})
        data["recurring_errors"] = json_loads(data["recurring_errors"], [])
        data["recommended_adjustments"] = json_loads(data["recommended_adjustments"], [])
        return data

    def _row_to_watched_source(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def _row_to_source_snapshot(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["parsed_values"] = json_loads(data["parsed_values"], {})
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def _row_to_autopilot_policy(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        data["materiality_policy"] = json_loads(data["materiality_policy"], {})
        data["guardrail_policy"] = json_loads(data["guardrail_policy"], {})
        data["notification_policy"] = json_loads(data["notification_policy"], {})
        return data

    def _row_to_autopilot_run(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["diagnostics"] = json_loads(data["diagnostics"], {})
        return data

    def _row_to_forecast_update_proposal(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["proposed_probability_or_distribution"] = json_loads(
            data["proposed_probability_or_distribution"],
            None,
        )
        for field in (
            "evidence_refs",
            "source_snapshot_refs",
            "model_run_refs",
            "assumption_refs",
            "reference_class_refs",
        ):
            data[field] = json_loads(data[field], [])
        return data

    def _row_to_backtest_case(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["baseline_comparison_refs"] = json_loads(data["baseline_comparison_refs"], [])
        return data

    def _row_to_benchmark_dataset(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["cases"] = json_loads(data["cases"], [])
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def _domain_error_profile_id(
        self,
        domain: str | None,
        topic: str | None,
        horizon: str | None,
        question_type: str | None,
    ) -> str:
        raw = "|".join([domain or "", topic or "", horizon or "", question_type or ""])
        return "dep_" + uuid.uuid5(uuid.NAMESPACE_URL, raw).hex[:12]

    def _infer_ingest_source_type(self, source: str) -> str:
        if source.startswith(("http://", "https://")):
            return "url"
        if Path(source).expanduser().is_file():
            return "file"
        return "manual_note"

    def _extract_ingest_metadata(self, source: str, source_type: str) -> dict[str, Any]:
        if source_type == "url":
            return self._extract_url_ingest_metadata(source)
        if source_type != "file":
            return {}
        path = Path(source).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValidationError(f"could not read ingest file: {path}") from exc
        suffix = path.suffix.lower()
        if suffix == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"ingest file is not valid JSON: {path}") from exc
            if not isinstance(payload, dict):
                raise ValidationError("ingest JSON file must contain an object")
            return self._metadata_from_ingest_payload(payload)
        if suffix == ".csv":
            rows = list(csv.DictReader(text.splitlines()))
            if not rows:
                raise ValidationError("ingest CSV file must contain at least one row")
            return self._metadata_from_ingest_payload(rows[0])
        return self._metadata_from_text_source(text)

    def _extract_url_ingest_metadata(self, source: str) -> dict[str, Any]:
        request = Request(source, headers={"User-Agent": "superforecasting-agent/0.1"})
        try:
            with urlopen(request, timeout=8) as response:
                content_type = response.headers.get("content-type", "")
                raw = response.read(512 * 1024)
        except (OSError, URLError) as exc:
            return {"metadata": {"source_fetch_error": str(exc)}}
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")

        if "json" in content_type.lower() or urlparse(source).path.lower().endswith(".json"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                return {"metadata": {"source_fetch_error": f"invalid JSON response: {exc}"}}
            if isinstance(payload, dict):
                return self._metadata_from_ingest_payload(payload)
            return {"metadata": {"source_fetch_error": "JSON response was not an object"}}

        html_metadata = self._metadata_from_html_source(text)
        html_metadata.setdefault("metadata", {})
        html_metadata["metadata"]["source_content_type"] = content_type
        return html_metadata

    def _metadata_from_ingest_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        baselines: list[dict[str, Any]] = []
        raw_baselines = payload.get("baselines")
        if isinstance(raw_baselines, list):
            baselines.extend(self._normalize_ingest_baseline(item) for item in raw_baselines if isinstance(item, dict))
        baseline = payload.get("baseline")
        if isinstance(baseline, dict):
            baselines.append(self._normalize_ingest_baseline(baseline))

        explicit_probability_fields = (
            ("baseline_probability", payload.get("baseline_type") or "imported", "baseline"),
            ("crowd_probability", "crowd", "crowd"),
            ("market_probability", "market", "market"),
            ("prior_probability", "prior", "prior"),
            ("posterior_probability", "posterior", "posterior"),
            ("forecast_probability", "imported_forecast", "forecast"),
        )
        for field, baseline_type, prefix in explicit_probability_fields:
            if payload.get(field) is None:
                continue
            baselines.append(
                {
                    "source": (
                        payload.get(f"{prefix}_source")
                        or payload.get("baseline_source")
                        or payload.get("source_name")
                        or payload.get("platform")
                        or "ingest_file"
                    ),
                    "baseline_type": baseline_type,
                    "probability_or_distribution": self._coerce_ingest_probability(payload[field]),
                    "as_of": payload.get(f"{prefix}_as_of") or payload.get("baseline_as_of") or payload.get("as_of"),
                }
            )
        if not baselines and payload.get("probability") is not None:
            baselines.append(
                {
                    "source": payload.get("baseline_source") or payload.get("source_name") or "ingest_file",
                    "baseline_type": payload.get("baseline_type") or "imported",
                    "probability_or_distribution": self._coerce_ingest_probability(payload["probability"]),
                    "as_of": payload.get("baseline_as_of") or payload.get("as_of"),
                }
            )
        baselines = self._dedupe_ingest_baselines(baselines)
        if baselines:
            metadata["baselines"] = baselines
            metadata["baseline"] = baselines[0]
        result = {
            "title": payload.get("title") or payload.get("question") or payload.get("question_title"),
            "description": payload.get("description") or payload.get("body") or "",
            "resolution_criteria": payload.get("resolution_criteria") or payload.get("criteria") or "",
            "resolution_source": payload.get("resolution_source"),
            "close_time": payload.get("close_time") or payload.get("close_date"),
            "resolution_time": payload.get("resolution_time") or payload.get("resolution_date"),
            "outcome_space": payload.get("outcome_space"),
            "metadata": metadata,
        }
        return {key: value for key, value in result.items() if value not in (None, "")}

    def _coerce_ingest_probability(self, value: Any) -> Any:
        if isinstance(value, str):
            raw = value.strip()
            if raw == "":
                return value
            if raw.endswith("%"):
                try:
                    return float(raw[:-1].strip()) / 100.0
                except ValueError:
                    return value
            try:
                return float(raw)
            except ValueError:
                return value
        return value

    def _dedupe_ingest_baselines(self, baselines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for baseline in baselines:
            if "probability_or_distribution" not in baseline and "probability" not in baseline:
                continue
            key = json_dumps(
                {
                    "source": baseline.get("source"),
                    "baseline_type": baseline.get("baseline_type"),
                    "as_of": baseline.get("as_of"),
                    "probability": self._baseline_probability_value(baseline),
                }
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(dict(baseline))
        return deduped

    def _candidate_baseline_payloads(self, metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(metadata, dict):
            return []
        baselines: list[dict[str, Any]] = []
        raw_baselines = metadata.get("baselines")
        if isinstance(raw_baselines, list):
            baselines.extend(self._normalize_ingest_baseline(item) for item in raw_baselines if isinstance(item, dict))
        baseline = metadata.get("baseline")
        if isinstance(baseline, dict):
            baselines.append(self._normalize_ingest_baseline(baseline))
        return self._dedupe_ingest_baselines(baselines)

    def _baseline_probability_value(self, baseline: dict[str, Any]) -> Any:
        return baseline.get("probability_or_distribution", baseline.get("probability"))

    def _normalize_ingest_baseline(self, baseline: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(baseline)
        if "probability_or_distribution" in normalized:
            normalized["probability_or_distribution"] = self._coerce_ingest_probability(
                normalized["probability_or_distribution"]
            )
        if "probability" in normalized:
            normalized["probability"] = self._coerce_ingest_probability(normalized["probability"])
        return normalized

    def _metadata_from_text_source(self, text: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        description_lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if line.startswith("#") and "title" not in result:
                result["title"] = line.lstrip("#").strip()
                continue
            for label, field in (
                ("title:", "title"),
                ("question:", "title"),
                ("resolution criteria:", "resolution_criteria"),
                ("criteria:", "resolution_criteria"),
                ("resolution source:", "resolution_source"),
                ("close time:", "close_time"),
                ("close date:", "close_time"),
                ("resolution time:", "resolution_time"),
                ("resolution date:", "resolution_time"),
            ):
                if lowered.startswith(label):
                    result[field] = line[len(label):].strip()
                    break
            else:
                if len(description_lines) < 3:
                    description_lines.append(line)
        if "description" not in result and description_lines:
            result["description"] = "\n".join(description_lines)
        return result

    def _metadata_from_html_source(self, text: str) -> dict[str, Any]:
        parser = _IngestHTMLParser()
        try:
            parser.feed(text)
        except Exception:
            return self._metadata_from_text_source(text)
        result = self._metadata_from_text_source("\n".join(parser.text_lines))
        if parser.title and "title" not in result:
            result["title"] = parser.title.strip()
        description = parser.meta.get("description") or parser.meta.get("og:description")
        if description and not result.get("description"):
            result["description"] = description.strip()
        og_title = parser.meta.get("og:title")
        if og_title and not result.get("title"):
            result["title"] = og_title.strip()
        return result

    def _infer_watch_source_type(self, source: str) -> str:
        if source.startswith(("rss:", "atom:")):
            return "rss"
        if source.startswith("gdelt:"):
            return "gdelt"
        if source.startswith(("fivethirtyeight:", "538:")):
            return "fivethirtyeight"
        if source.startswith("github:"):
            return "github"
        if source.startswith("githubrepo:"):
            return "githubrepo"
        if source.startswith("githubissues:"):
            return "githubissues"
        if source.startswith("githubcommits:"):
            return "githubcommits"
        if source.startswith("githubactions:"):
            return "githubactions"
        if source.startswith("coingecko:"):
            return "coingecko"
        if source.startswith("pypi:"):
            return "pypi"
        if source.startswith("npm:"):
            return "npm"
        if source.startswith("hackernews:"):
            return "hackernews"
        if source.startswith("reddit:"):
            return "reddit"
        if source.startswith("bluesky:"):
            return "bluesky"
        if source.startswith("mastodon:"):
            return "mastodon"
        if source.startswith("federalregister:"):
            return "federalregister"
        if source.startswith("courtlistener:"):
            return "courtlistener"
        if source.startswith("nvd:"):
            return "nvd"
        if source.startswith("cisakev:"):
            return "cisakev"
        if source.startswith("openmeteo:"):
            return "openmeteo"
        if source.startswith("airquality:"):
            return "airquality"
        if source.startswith("weatherhistory:"):
            return "weatherhistory"
        if source.startswith("usgs:"):
            return "usgs"
        if source.startswith("eonet:"):
            return "eonet"
        if source.startswith("nws:"):
            return "nws"
        if source.startswith("clinicaltrials:"):
            return "clinicaltrials"
        if source.startswith("openfda:"):
            return "openfda"
        if source.startswith("pubmed:"):
            return "pubmed"
        if source.startswith("owid:"):
            return "owid"
        if source.startswith("whogho:"):
            return "whogho"
        if source.startswith("fema:"):
            return "fema"
        if source.startswith("fred:"):
            return "fred"
        if source.startswith("eia:"):
            return "eia"
        if source.startswith("treasury:"):
            return "treasury"
        if source.startswith("bls:"):
            return "bls"
        if source.startswith("worldbank:"):
            return "worldbank"
        if source.startswith("imf:"):
            return "imf"
        if source.startswith("census:"):
            return "census"
        if source.startswith("socrata:"):
            return "socrata"
        if source.startswith("ckan:"):
            return "ckan"
        if source.startswith("stooq:"):
            return "stooq"
        if source.startswith("yahoo:"):
            return "yahoo"
        if source.startswith("sec:"):
            return "sec"
        if source.startswith("secfacts:"):
            return "secfacts"
        if source.startswith("arxiv:"):
            return "arxiv"
        if source.startswith("openalex:"):
            return "openalex"
        if source.startswith("crossref:"):
            return "crossref"
        if source.startswith("reliefweb:"):
            return "reliefweb"
        if source.startswith("wikipedia:"):
            return "wikipedia"
        if source.startswith("wikipediapageviews:"):
            return "wikipediapageviews"
        if source.startswith("manifold:"):
            return "manifold"
        if source.startswith("metaculus:"):
            return "metaculus"
        if source.startswith("polymarket:"):
            return "polymarket"
        if source.startswith("kalshi:"):
            return "kalshi"
        source_type = self._infer_ingest_source_type(source)
        return "manual" if source_type == "manual_note" else source_type

    def _rss_relevance_filters(self, metadata: dict[str, Any]) -> dict[str, list[str]]:
        raw_filters = metadata.get("relevance_filters") if isinstance(metadata, dict) else {}
        if not isinstance(raw_filters, dict):
            raw_filters = {}
        return {
            "keywords": self._rss_filter_terms(raw_filters.get("keywords")),
            "exclude_keywords": self._rss_filter_terms(raw_filters.get("exclude_keywords")),
        }

    def _rss_filter_terms(self, value: Any) -> list[str]:
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

    def _rss_filter_cli_args(self, filters: dict[str, list[str]]) -> str:
        parts: list[str] = []
        for term in filters.get("keywords") or []:
            parts.append(f" --keyword {self._shell_arg(term)}")
        for term in filters.get("exclude_keywords") or []:
            parts.append(f" --exclude-keyword {self._shell_arg(term)}")
        return "".join(parts)

    def _shell_arg(self, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_./:+=,@%-]+", value):
            return value
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _source_signature(
        self,
        source: str,
        source_type: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        if source_type == "rss":
            return self._rss_source_signature(source, metadata=metadata)
        if source_type == "gdelt":
            return self._gdelt_source_signature(source)
        if source_type == "fivethirtyeight":
            return self._fivethirtyeight_source_signature(source)
        if source_type == "github":
            return self._github_source_signature(source)
        if source_type == "githubrepo":
            return self._github_repo_metadata_source_signature(source)
        if source_type == "githubissues":
            return self._github_issues_source_signature(source)
        if source_type == "githubcommits":
            return self._github_commits_source_signature(source)
        if source_type == "githubactions":
            return self._github_actions_source_signature(source)
        if source_type == "coingecko":
            return self._coingecko_source_signature(source)
        if source_type == "pypi":
            return self._pypi_source_signature(source)
        if source_type == "npm":
            return self._npm_source_signature(source)
        if source_type == "hackernews":
            return self._hackernews_source_signature(source)
        if source_type == "reddit":
            return self._reddit_source_signature(source)
        if source_type == "bluesky":
            return self._bluesky_source_signature(source)
        if source_type == "mastodon":
            return self._mastodon_source_signature(source)
        if source_type == "federalregister":
            return self._federalregister_source_signature(source)
        if source_type == "courtlistener":
            return self._courtlistener_source_signature(source)
        if source_type == "nvd":
            return self._nvd_source_signature(source)
        if source_type == "cisakev":
            return self._cisa_kev_source_signature(source)
        if source_type == "openmeteo":
            return self._openmeteo_source_signature(source)
        if source_type == "airquality":
            return self._airquality_source_signature(source)
        if source_type == "weatherhistory":
            return self._weatherhistory_source_signature(source)
        if source_type == "usgs":
            return self._usgs_source_signature(source)
        if source_type == "eonet":
            return self._eonet_source_signature(source)
        if source_type == "nws":
            return self._nws_source_signature(source)
        if source_type == "clinicaltrials":
            return self._clinicaltrials_source_signature(source)
        if source_type == "openfda":
            return self._openfda_source_signature(source)
        if source_type == "pubmed":
            return self._pubmed_source_signature(source)
        if source_type == "owid":
            return self._owid_source_signature(source)
        if source_type == "whogho":
            return self._who_gho_source_signature(source)
        if source_type == "fema":
            return self._fema_source_signature(source)
        if source_type == "fred":
            return self._fred_source_signature(source)
        if source_type == "eia":
            return self._eia_source_signature(source)
        if source_type == "treasury":
            return self._treasury_source_signature(source)
        if source_type == "bls":
            return self._bls_source_signature(source)
        if source_type == "worldbank":
            return self._worldbank_source_signature(source)
        if source_type == "imf":
            return self._imf_source_signature(source)
        if source_type == "census":
            return self._census_source_signature(source)
        if source_type == "socrata":
            return self._socrata_source_signature(source)
        if source_type == "ckan":
            return self._ckan_source_signature(source)
        if source_type == "stooq":
            return self._stooq_source_signature(source)
        if source_type == "yahoo":
            return self._yahoo_source_signature(source)
        if source_type == "sec":
            return self._sec_source_signature(source)
        if source_type == "secfacts":
            return self._sec_company_facts_source_signature(source)
        if source_type == "arxiv":
            return self._arxiv_source_signature(source)
        if source_type == "openalex":
            return self._openalex_source_signature(source)
        if source_type == "crossref":
            return self._crossref_source_signature(source)
        if source_type == "reliefweb":
            return self._reliefweb_source_signature(source)
        if source_type == "wikipedia":
            return self._wikipedia_source_signature(source)
        if source_type == "wikipediapageviews":
            return self._wikipediapageviews_source_signature(source)
        if source_type == "manifold":
            return self._manifold_source_signature(source)
        if source_type == "metaculus":
            return self._metaculus_source_signature(source)
        if source_type == "polymarket":
            return self._polymarket_source_signature(source)
        if source_type == "kalshi":
            return self._kalshi_source_signature(source)
        if source_type == "url":
            return self._url_source_signature(source)
        if source_type != "file":
            return None
        path = Path(source).expanduser()
        if not path.is_file():
            return f"missing:{path}"
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return f"missing:{path}"
        stat = path.stat()
        return f"file:{stat.st_size}:{digest.hexdigest()}"

    def _url_source_signature(self, source: str) -> str:
        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return f"missing:url:{source}:invalid"
        request = Request(source, headers={"User-Agent": f"{PRODUCT_SLUG}/forecast-watch"})
        digest = hashlib.sha256()
        total = 0
        try:
            with urlopen(request, timeout=10) as response:
                while total < 2 * 1024 * 1024:
                    chunk = response.read(min(1024 * 1024, 2 * 1024 * 1024 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    digest.update(chunk)
                headers = response.headers
                return ":".join(
                    [
                        "url",
                        str(response.getcode()),
                        str(headers.get("ETag") or ""),
                        str(headers.get("Last-Modified") or ""),
                        str(headers.get("Content-Length") or ""),
                        str(total),
                        digest.hexdigest(),
                    ]
                )
        except (OSError, URLError, ValueError) as exc:
            return f"missing:url:{source}:{exc.__class__.__name__}"

    def _rss_source_signature(self, source: str, *, metadata: dict[str, Any] | None = None) -> str:
        feed_source = source.split(":", 1)[1] if source.startswith(("rss:", "atom:")) else source
        filters = self._rss_relevance_filters(metadata or {})
        try:
            from forecasting.source_adapters import load_news_feed_items

            items = load_news_feed_items(
                feed_source,
                limit=50,
                keywords=filters["keywords"],
                exclude_keywords=filters["exclude_keywords"],
            )
        except Exception as exc:
            return f"missing:rss:{feed_source}:{exc.__class__.__name__}"
        payload = {
            "filters": filters,
            "items": [
                {
                    "entry_id": item.entry_id,
                    "published_at": item.published_at,
                    "title": item.title,
                    "url": item.url,
                }
                for item in items
            ],
        }
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"rss:{len(items)}:{digest}"

    def _gdelt_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("gdelt:") else source.strip()
        if not query:
            return "missing:gdelt:empty-query"
        try:
            from forecasting.source_adapters import load_gdelt_articles

            articles = load_gdelt_articles(query, limit=50)
        except Exception as exc:
            return f"missing:gdelt:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": article.entry_id,
                "published_at": article.published_at,
                "title": article.title,
                "url": article.url,
                "domain": article.domain,
            }
            for article in articles
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"gdelt:{len(payload)}:{digest}"

    def _fivethirtyeight_source_signature(self, source: str) -> str:
        source_value = (
            source.split(":", 1)[1].strip()
            if source.startswith(("fivethirtyeight:", "538:"))
            else source.strip()
        )
        if not source_value:
            return "missing:fivethirtyeight:empty-source"
        try:
            from forecasting.source_adapters import load_fivethirtyeight_polls

            observations = load_fivethirtyeight_polls(source_value, limit=50)
        except Exception as exc:
            return f"missing:fivethirtyeight:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dataset": observation.dataset,
                "poll_id": observation.poll_id,
                "question_id": observation.question_id,
                "pollster": observation.pollster,
                "state": observation.state,
                "cycle": observation.cycle,
                "candidate_name": observation.candidate_name,
                "answer": observation.answer,
                "pct": observation.pct,
                "sample_size": observation.sample_size,
                "end_date": observation.end_date,
                "published_at": observation.published_at,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"fivethirtyeight:{len(payload)}:{digest}"

    def _github_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("github:") else source.strip()
        if not source_value:
            return "missing:github:empty-repo"
        try:
            from forecasting.source_adapters import load_github_releases

            releases = load_github_releases(source_value, limit=50)
        except Exception as exc:
            return f"missing:github:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "created_at": release.created_at,
                "draft": release.draft,
                "entry_id": release.entry_id,
                "prerelease": release.prerelease,
                "published_at": release.published_at,
                "release_id": release.release_id,
                "repo": release.repo,
                "tag_name": release.tag_name,
            }
            for release in releases
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"github:{len(payload)}:{digest}"

    def _github_repo_metadata_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubrepo:") else source.strip()
        if not source_value:
            return "missing:githubrepo:empty-repo"
        try:
            from forecasting.source_adapters import load_github_repository_snapshots

            snapshots = load_github_repository_snapshots(source_value, limit=1)
        except Exception as exc:
            return f"missing:githubrepo:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "repo": item.repo,
                "default_branch": item.default_branch,
                "stargazers_count": item.stargazers_count,
                "watchers_count": item.watchers_count,
                "forks_count": item.forks_count,
                "open_issues_count": item.open_issues_count,
                "subscribers_count": item.subscribers_count,
                "network_count": item.network_count,
                "updated_at": item.updated_at,
                "pushed_at": item.pushed_at,
                "archived": item.archived,
                "disabled": item.disabled,
            }
            for item in snapshots
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"githubrepo:{len(payload)}:{digest}"

    def _github_issues_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubissues:") else source.strip()
        if not source_value:
            return "missing:githubissues:empty-repo"
        try:
            from forecasting.source_adapters import load_github_issues

            issues = load_github_issues(source_value, limit=50)
        except Exception as exc:
            return f"missing:githubissues:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "closed_at": issue.closed_at,
                "comments": issue.comments,
                "entry_id": issue.entry_id,
                "is_pull_request": issue.is_pull_request,
                "issue_number": issue.issue_number,
                "labels": issue.labels,
                "state": issue.state,
                "title": issue.title,
                "updated_at": issue.updated_at,
            }
            for issue in issues
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"githubissues:{len(payload)}:{digest}"

    def _github_commits_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubcommits:") else source.strip()
        if not source_value:
            return "missing:githubcommits:empty-repo"
        try:
            from forecasting.source_adapters import load_github_commits

            commits = load_github_commits(source_value, limit=50)
        except Exception as exc:
            return f"missing:githubcommits:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "author_login": commit.author_login,
                "committed_at": commit.committed_at,
                "entry_id": commit.entry_id,
                "message": commit.message,
                "repo": commit.repo,
                "sha": commit.sha,
            }
            for commit in commits
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"githubcommits:{len(payload)}:{digest}"

    def _github_actions_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubactions:") else source.strip()
        if not source_value:
            return "missing:githubactions:empty-repo"
        try:
            from forecasting.source_adapters import load_github_workflow_runs

            runs = load_github_workflow_runs(source_value, limit=50)
        except Exception as exc:
            return f"missing:githubactions:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "conclusion": run.conclusion,
                "display_title": run.display_title,
                "entry_id": run.entry_id,
                "event": run.event,
                "head_branch": run.head_branch,
                "head_sha": run.head_sha,
                "name": run.name,
                "repo": run.repo,
                "run_id": run.run_id,
                "status": run.status,
                "updated_at": run.updated_at,
            }
            for run in runs
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"githubactions:{len(payload)}:{digest}"

    def _coingecko_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("coingecko:") else source.strip()
        if not source_value:
            return "missing:coingecko:empty-source"
        try:
            from forecasting.source_adapters import load_coingecko_market_snapshots

            snapshots = load_coingecko_market_snapshots(source_value, limit=50)
        except Exception as exc:
            return f"missing:coingecko:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "coin_id": snapshot.coin_id,
                "symbol": snapshot.symbol,
                "vs_currency": snapshot.vs_currency,
                "current_price": snapshot.current_price,
                "market_cap": snapshot.market_cap,
                "market_cap_rank": snapshot.market_cap_rank,
                "total_volume": snapshot.total_volume,
                "price_change_percentage_24h": snapshot.price_change_percentage_24h,
                "last_updated": snapshot.last_updated,
            }
            for snapshot in snapshots
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"coingecko:{len(payload)}:{digest}"

    def _pypi_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("pypi:") else source.strip()
        if not source_value:
            return "missing:pypi:empty-package"
        try:
            from forecasting.source_adapters import load_pypi_releases

            releases = load_pypi_releases(source_value, limit=50)
        except Exception as exc:
            return f"missing:pypi:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": release.entry_id,
                "file_count": release.file_count,
                "latest_upload_at": release.latest_upload_at,
                "package": release.package,
                "package_types": release.package_types,
                "python_versions": release.python_versions,
                "uploaded_at": release.uploaded_at,
                "version": release.version,
                "yanked": release.yanked,
                "yanked_reason": release.yanked_reason,
            }
            for release in releases
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"pypi:{len(payload)}:{digest}"

    def _npm_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("npm:") else source.strip()
        if not source_value:
            return "missing:npm:empty-package"
        try:
            from forecasting.source_adapters import load_npm_package_versions

            versions = load_npm_package_versions(source_value, limit=50)
        except Exception as exc:
            return f"missing:npm:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dependency_count": version.dependency_count,
                "deprecated": version.deprecated,
                "entry_id": version.entry_id,
                "license": version.license,
                "package": version.package,
                "published_at": version.published_at,
                "version": version.version,
            }
            for version in versions
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"npm:{len(payload)}:{digest}"

    def _hackernews_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("hackernews:") else source.strip()
        if not query:
            return "missing:hackernews:empty-query"
        try:
            from forecasting.source_adapters import load_hackernews_items

            items = load_hackernews_items(query, limit=50)
        except Exception as exc:
            return f"missing:hackernews:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "comments": item.comments,
                "created_at": item.created_at,
                "entry_id": item.entry_id,
                "object_id": item.object_id,
                "points": item.points,
                "title": item.title,
                "url": item.url,
            }
            for item in items
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"hackernews:{len(payload)}:{digest}"

    def _reddit_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("reddit:") else source.strip()
        if not query:
            return "missing:reddit:empty-query"
        try:
            from forecasting.source_adapters import load_reddit_posts

            posts = load_reddit_posts(query, limit=50)
        except Exception as exc:
            return f"missing:reddit:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "comments": post.comments,
                "created_at": post.created_at,
                "entry_id": post.entry_id,
                "post_id": post.post_id,
                "score": post.score,
                "subreddit": post.subreddit,
                "title": post.title,
                "url": post.url,
                "upvote_ratio": post.upvote_ratio,
            }
            for post in posts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"reddit:{len(payload)}:{digest}"

    def _bluesky_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("bluesky:") else source.strip()
        if not query:
            return "missing:bluesky:empty-query"
        try:
            from forecasting.source_adapters import load_bluesky_posts

            posts = load_bluesky_posts(query, limit=50)
        except Exception as exc:
            return f"missing:bluesky:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "created_at": post.created_at,
                "entry_id": post.entry_id,
                "indexed_at": post.indexed_at,
                "like_count": post.like_count,
                "post_uri": post.post_uri,
                "reply_count": post.reply_count,
                "repost_count": post.repost_count,
                "text": post.text,
                "url": post.url,
            }
            for post in posts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"bluesky:{len(payload)}:{digest}"

    def _mastodon_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("mastodon:") else source.strip()
        if not source_value:
            return "missing:mastodon:empty-source"
        try:
            from forecasting.source_adapters import load_mastodon_statuses

            statuses = load_mastodon_statuses(source_value, limit=40)
        except Exception as exc:
            return f"missing:mastodon:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "account_acct": status.account_acct,
                "content_text": status.content_text,
                "created_at": status.created_at,
                "entry_id": status.entry_id,
                "favourites_count": status.favourites_count,
                "reblogs_count": status.reblogs_count,
                "replies_count": status.replies_count,
                "status_id": status.status_id,
                "url": status.url,
            }
            for status in statuses
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"mastodon:{len(payload)}:{digest}"

    def _federalregister_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("federalregister:") else source.strip()
        if not query:
            return "missing:federalregister:empty-query"
        try:
            from forecasting.source_adapters import load_federal_register_documents

            documents = load_federal_register_documents(query, limit=50)
        except Exception as exc:
            return f"missing:federalregister:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "agencies": document.agencies,
                "document_number": document.document_number,
                "document_type": document.document_type,
                "entry_id": document.entry_id,
                "published_at": document.published_at,
                "title": document.title,
                "url": document.url,
            }
            for document in documents
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"federalregister:{len(payload)}:{digest}"

    def _courtlistener_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("courtlistener:") else source.strip()
        if not query:
            return "missing:courtlistener:empty-query"
        try:
            from forecasting.source_adapters import load_courtlistener_search_results

            results = load_courtlistener_search_results(query, limit=50)
        except Exception as exc:
            return f"missing:courtlistener:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "citation": result.citation,
                "court_id": result.court_id,
                "date_filed": result.date_filed,
                "docket_number": result.docket_number,
                "entry_id": result.entry_id,
                "result_id": result.result_id,
                "status": result.status,
                "title": result.title,
                "url": result.url,
            }
            for result in results
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"courtlistener:{len(payload)}:{digest}"

    def _nvd_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("nvd:") else source.strip()
        if not query:
            return "missing:nvd:empty-query"
        try:
            from forecasting.source_adapters import load_nvd_cves

            cves = load_nvd_cves(query, limit=50)
        except Exception as exc:
            return f"missing:nvd:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "base_score": cve.base_score,
                "cve_id": cve.cve_id,
                "entry_id": cve.entry_id,
                "last_modified_at": cve.last_modified_at,
                "published_at": cve.published_at,
                "severity": cve.severity,
                "vuln_status": cve.vuln_status,
            }
            for cve in cves
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"nvd:{len(payload)}:{digest}"

    def _cisa_kev_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("cisakev:") else source.strip()
        if not query:
            return "missing:cisakev:empty-query"
        try:
            from forecasting.source_adapters import load_cisa_kev_vulnerabilities

            vulnerabilities = load_cisa_kev_vulnerabilities(query, limit=50)
        except Exception as exc:
            return f"missing:cisakev:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "cve_id": vulnerability.cve_id,
                "date_added": vulnerability.date_added,
                "due_date": vulnerability.due_date,
                "entry_id": vulnerability.entry_id,
                "product": vulnerability.product,
                "ransomware_use": vulnerability.ransomware_use,
                "vendor_project": vulnerability.vendor_project,
                "vulnerability_name": vulnerability.vulnerability_name,
            }
            for vulnerability in vulnerabilities
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"cisakev:{len(payload)}:{digest}"

    def _openmeteo_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("openmeteo:") else source.strip()
        if not source_value:
            return "missing:openmeteo:empty-coordinates"
        try:
            from forecasting.source_adapters import load_openmeteo_daily_forecasts

            forecasts = load_openmeteo_daily_forecasts(source_value, limit=16, forecast_days=16)
        except Exception as exc:
            return f"missing:openmeteo:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": forecast.entry_id,
                "forecast_date": forecast.forecast_date,
                "precipitation_sum": forecast.precipitation_sum,
                "temperature_2m_max": forecast.temperature_2m_max,
                "temperature_2m_min": forecast.temperature_2m_min,
                "wind_speed_10m_max": forecast.wind_speed_10m_max,
            }
            for forecast in forecasts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"openmeteo:{len(payload)}:{digest}"

    def _airquality_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("airquality:") else source.strip()
        if not source_value:
            return "missing:airquality:empty-coordinates"
        try:
            from forecasting.source_adapters import load_openmeteo_air_quality_forecasts

            forecasts = load_openmeteo_air_quality_forecasts(source_value, limit=48, forecast_days=5)
        except Exception as exc:
            return f"missing:airquality:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": forecast.entry_id,
                "forecast_time": forecast.forecast_time,
                "carbon_monoxide": forecast.carbon_monoxide,
                "european_aqi": forecast.european_aqi,
                "nitrogen_dioxide": forecast.nitrogen_dioxide,
                "ozone": forecast.ozone,
                "pm10": forecast.pm10,
                "pm2_5": forecast.pm2_5,
                "us_aqi": forecast.us_aqi,
            }
            for forecast in forecasts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"airquality:{len(payload)}:{digest}"

    def _weatherhistory_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("weatherhistory:") else source.strip()
        if not source_value:
            return "missing:weatherhistory:empty-source"
        try:
            from forecasting.source_adapters import load_openmeteo_historical_weather

            observations = load_openmeteo_historical_weather(source_value, limit=366)
        except Exception as exc:
            return f"missing:weatherhistory:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": observation.entry_id,
                "observation_date": observation.observation_date,
                "precipitation_sum": observation.precipitation_sum,
                "temperature_2m_mean": observation.temperature_2m_mean,
                "temperature_2m_max": observation.temperature_2m_max,
                "temperature_2m_min": observation.temperature_2m_min,
                "wind_speed_10m_max": observation.wind_speed_10m_max,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"weatherhistory:{len(payload)}:{digest}"

    def _usgs_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("usgs:") else source.strip()
        if not source_value:
            return "missing:usgs:empty-query"
        try:
            from forecasting.source_adapters import load_usgs_earthquakes

            events = load_usgs_earthquakes(source_value, limit=50)
        except Exception as exc:
            return f"missing:usgs:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "depth_km": event.depth_km,
                "entry_id": event.entry_id,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "latitude": event.latitude,
                "longitude": event.longitude,
                "magnitude": event.magnitude,
                "place": event.place,
                "significance": event.significance,
                "status": event.status,
                "time": event.time,
                "updated_at": event.updated_at,
            }
            for event in events
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"usgs:{len(payload)}:{digest}"

    def _eonet_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("eonet:") else source.strip()
        if not source_value:
            return "missing:eonet:empty-query"
        try:
            from forecasting.source_adapters import load_nasa_eonet_events

            events = load_nasa_eonet_events(source_value, limit=50)
        except Exception as exc:
            return f"missing:eonet:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "categories": event.categories,
                "closed_at": event.closed_at,
                "entry_id": event.entry_id,
                "event_id": event.event_id,
                "latest_geometry_at": event.latest_geometry_at,
                "latitude": event.latitude,
                "longitude": event.longitude,
                "source_names": event.source_names,
                "status": event.status,
                "title": event.title,
            }
            for event in events
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"eonet:{len(payload)}:{digest}"

    def _nws_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("nws:") else source.strip()
        if not source_value:
            return "missing:nws:empty-query"
        try:
            from forecasting.source_adapters import load_nws_alerts

            alerts = load_nws_alerts(source_value, limit=50)
        except Exception as exc:
            return f"missing:nws:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "alert_id": alert.alert_id,
                "area_desc": alert.area_desc,
                "certainty": alert.certainty,
                "effective_at": alert.effective_at,
                "ends_at": alert.ends_at,
                "event": alert.event,
                "expires_at": alert.expires_at,
                "headline": alert.headline,
                "severity": alert.severity,
                "status": alert.status,
                "urgency": alert.urgency,
            }
            for alert in alerts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"nws:{len(payload)}:{digest}"

    def _clinicaltrials_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("clinicaltrials:") else source.strip()
        if not source_value:
            return "missing:clinicaltrials:empty-query"
        try:
            from forecasting.source_adapters import load_clinicaltrials_studies

            studies = load_clinicaltrials_studies(source_value, limit=50)
        except Exception as exc:
            return f"missing:clinicaltrials:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "completion_date": study.completion_date,
                "conditions": study.conditions,
                "entry_id": study.entry_id,
                "has_results": study.has_results,
                "last_update_posted_at": study.last_update_posted_at,
                "nct_id": study.nct_id,
                "phases": study.phases,
                "primary_completion_date": study.primary_completion_date,
                "status": study.status,
                "title": study.brief_title,
            }
            for study in studies
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"clinicaltrials:{len(payload)}:{digest}"

    def _openfda_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("openfda:") else source.strip()
        if not source_value:
            return "missing:openfda:empty-query"
        try:
            from forecasting.source_adapters import load_openfda_drug_applications

            applications = load_openfda_drug_applications(source_value, limit=50)
        except Exception as exc:
            return f"missing:openfda:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "application_number": application.application_number,
                "brand_names": application.brand_names,
                "entry_id": application.entry_id,
                "generic_names": application.generic_names,
                "latest_submission_status": application.latest_submission_status,
                "latest_submission_status_date": application.latest_submission_status_date,
                "latest_submission_type": application.latest_submission_type,
                "marketing_statuses": application.marketing_statuses,
                "sponsor_name": application.sponsor_name,
            }
            for application in applications
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"openfda:{len(payload)}:{digest}"

    def _pubmed_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("pubmed:") else source.strip()
        if not source_value:
            return "missing:pubmed:empty-query"
        try:
            from forecasting.source_adapters import load_pubmed_articles

            articles = load_pubmed_articles(source_value, limit=50)
        except Exception as exc:
            return f"missing:pubmed:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "doi": article.doi,
                "entry_id": article.entry_id,
                "journal": article.journal,
                "pmid": article.pmid,
                "publication_types": article.publication_types,
                "published_at": article.published_at,
                "revised_at": article.revised_at,
                "title": article.title,
            }
            for article in articles
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"pubmed:{len(payload)}:{digest}"

    def _owid_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("owid:") else source.strip()
        if not source_value:
            return "missing:owid:empty-source"
        try:
            from forecasting.source_adapters import load_owid_observations

            observations = load_owid_observations(source_value, limit=50)
        except Exception as exc:
            return f"missing:owid:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "code": observation.code,
                "entity": observation.entity,
                "entry_id": observation.entry_id,
                "observation_date": observation.observation_date,
                "slug": observation.slug,
                "value": observation.value,
                "value_column": observation.value_column,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"owid:{len(payload)}:{digest}"

    def _who_gho_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("whogho:") else source.strip()
        if not source_value:
            return "missing:whogho:empty-source"
        try:
            from forecasting.source_adapters import load_who_gho_observations

            observations = load_who_gho_observations(source_value, limit=50)
        except Exception as exc:
            return f"missing:whogho:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dim1": observation.dim1,
                "dim2": observation.dim2,
                "dim3": observation.dim3,
                "entry_id": observation.entry_id,
                "high": observation.high,
                "indicator": observation.indicator,
                "low": observation.low,
                "numeric_value": observation.numeric_value,
                "published_at": observation.published_at,
                "spatial_dim": observation.spatial_dim,
                "time_dim": observation.time_dim,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"whogho:{len(payload)}:{digest}"

    def _fema_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("fema:") else source.strip()
        if not source_value:
            return "missing:fema:empty-source"
        try:
            from forecasting.source_adapters import load_fema_disaster_declarations

            declarations = load_fema_disaster_declarations(source_value, limit=50)
        except Exception as exc:
            return f"missing:fema:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "declaration_date": declaration.declaration_date,
                "declaration_string": declaration.declaration_string,
                "declaration_type": declaration.declaration_type,
                "designated_area": declaration.designated_area,
                "disaster_number": declaration.disaster_number,
                "entry_id": declaration.entry_id,
                "fiscal_year": declaration.fiscal_year,
                "incident_begin_date": declaration.incident_begin_date,
                "incident_end_date": declaration.incident_end_date,
                "incident_type": declaration.incident_type,
                "last_refresh": declaration.last_refresh,
                "state": declaration.state,
                "title": declaration.title,
            }
            for declaration in declarations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"fema:{len(payload)}:{digest}"

    def _fred_source_signature(self, source: str) -> str:
        series_id = source.split(":", 1)[1].strip() if source.startswith("fred:") else source.strip()
        if not series_id:
            return "missing:fred:empty-series"
        try:
            from forecasting.source_adapters import load_fred_observations

            observations = load_fred_observations(series_id, limit=50)
        except Exception as exc:
            return f"missing:fred:{series_id}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": observation.entry_id,
                "observation_date": observation.observation_date,
                "published_at": observation.published_at,
                "series_id": observation.series_id,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"fred:{len(payload)}:{digest}"

    def _eia_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("eia:") else source.strip()
        if not source_value:
            return "missing:eia:empty-source"
        try:
            from forecasting.source_adapters import load_eia_observations

            observations = load_eia_observations(source_value, limit=50)
        except Exception as exc:
            return f"missing:eia:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": observation.entry_id,
                "observation_period": observation.observation_period,
                "published_at": observation.published_at,
                "series_id": observation.series_id,
                "unit": observation.unit,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"eia:{len(payload)}:{digest}"

    def _treasury_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("treasury:") else source.strip()
        if not source_value:
            return "missing:treasury:empty-source"
        try:
            from forecasting.source_adapters import load_treasury_records

            records = load_treasury_records(source_value, limit=50)
        except Exception as exc:
            return f"missing:treasury:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dataset": record.dataset,
                "entry_id": record.entry_id,
                "published_at": record.published_at,
                "record_date": record.record_date,
                "value": record.value,
                "value_field": record.value_field,
            }
            for record in records
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"treasury:{len(payload)}:{digest}"

    def _bls_source_signature(self, source: str) -> str:
        series_id = source.split(":", 1)[1].strip() if source.startswith("bls:") else source.strip()
        if not series_id:
            return "missing:bls:empty-series"
        try:
            from forecasting.source_adapters import load_bls_observations

            observations = load_bls_observations(series_id, limit=50)
        except Exception as exc:
            return f"missing:bls:{series_id}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": observation.entry_id,
                "observation_date": observation.observation_date,
                "period": observation.period,
                "published_at": observation.published_at,
                "series_id": observation.series_id,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"bls:{len(payload)}:{digest}"

    def _worldbank_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("worldbank:") else source.strip()
        if not source_value:
            return "missing:worldbank:empty-source"
        try:
            from forecasting.source_adapters import load_worldbank_observations

            observations = load_worldbank_observations(source_value, limit=50)
        except Exception as exc:
            return f"missing:worldbank:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "country": observation.country,
                "entry_id": observation.entry_id,
                "indicator": observation.indicator,
                "observation_date": observation.observation_date,
                "published_at": observation.published_at,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"worldbank:{len(payload)}:{digest}"

    def _imf_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("imf:") else source.strip()
        if not source_value:
            return "missing:imf:empty-source"
        try:
            from forecasting.source_adapters import load_imf_datamapper_observations

            observations = load_imf_datamapper_observations(source_value, limit=50)
        except Exception as exc:
            return f"missing:imf:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "country": observation.country,
                "entry_id": observation.entry_id,
                "indicator": observation.indicator,
                "observation_date": observation.observation_date,
                "published_at": observation.published_at,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"imf:{len(payload)}:{digest}"

    def _census_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("census:") else source.strip()
        if not source_value:
            return "missing:census:empty-source"
        try:
            from forecasting.source_adapters import load_census_records

            records = load_census_records(source_value, limit=50)
        except Exception as exc:
            return f"missing:census:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dataset": record.dataset,
                "entry_id": record.entry_id,
                "geography": record.geography,
                "observation_date": record.observation_date,
                "published_at": record.published_at,
                "values": record.values,
            }
            for record in records
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"census:{len(payload)}:{digest}"

    def _socrata_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("socrata:") else source.strip()
        if not source_value:
            return "missing:socrata:empty-source"
        try:
            from forecasting.source_adapters import load_socrata_records

            records = load_socrata_records(source_value, limit=50)
        except Exception as exc:
            return f"missing:socrata:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dataset_id": record.dataset_id,
                "domain": record.domain,
                "entry_id": record.entry_id,
                "observation_time": record.observation_time,
                "row_id": record.row_id,
                "updated_at": record.updated_at,
                "values": record.values,
            }
            for record in records
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"socrata:{len(payload)}:{digest}"

    def _ckan_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("ckan:") else source.strip()
        if not source_value:
            return "missing:ckan:empty-source"
        try:
            from forecasting.source_adapters import load_ckan_datasets

            datasets = load_ckan_datasets(source_value, limit=50)
        except Exception as exc:
            return f"missing:ckan:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": dataset.entry_id,
                "metadata_created": dataset.metadata_created,
                "metadata_modified": dataset.metadata_modified,
                "name": dataset.name,
                "package_id": dataset.package_id,
                "portal": dataset.portal,
                "resource_count": len(dataset.resources),
                "tags": dataset.tags,
                "title": dataset.title,
            }
            for dataset in datasets
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"ckan:{len(payload)}:{digest}"

    def _stooq_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("stooq:") else source.strip()
        if not source_value:
            return "missing:stooq:empty-source"
        try:
            from forecasting.source_adapters import load_stooq_prices

            observations = load_stooq_prices(source_value, limit=50)
        except Exception as exc:
            return f"missing:stooq:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "close_price": observation.close_price,
                "entry_id": observation.entry_id,
                "interval": observation.interval,
                "observation_date": observation.observation_date,
                "published_at": observation.published_at,
                "symbol": observation.symbol,
                "volume": observation.volume,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"stooq:{len(payload)}:{digest}"

    def _yahoo_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("yahoo:") else source.strip()
        if not source_value:
            return "missing:yahoo:empty-symbol"
        try:
            from forecasting.source_adapters import load_yahoo_finance_prices

            observations = load_yahoo_finance_prices(source_value, limit=50)
        except Exception as exc:
            return f"missing:yahoo:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "close_price": observation.close_price,
                "currency": observation.currency,
                "entry_id": observation.entry_id,
                "interval": observation.interval,
                "observation_time": observation.observation_time,
                "symbol": observation.symbol,
                "volume": observation.volume,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"yahoo:{len(payload)}:{digest}"

    def _sec_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("sec:") else source.strip()
        if not source_value:
            return "missing:sec:empty-cik"
        try:
            from forecasting.source_adapters import load_sec_filings

            filings = load_sec_filings(source_value, limit=50)
        except Exception as exc:
            return f"missing:sec:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "accession_number": filing.accession_number,
                "cik": filing.cik,
                "filing_date": filing.filing_date,
                "form": filing.form,
                "published_at": filing.published_at,
                "report_date": filing.report_date,
            }
            for filing in filings
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"sec:{len(payload)}:{digest}"

    def _sec_company_facts_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("secfacts:") else source.strip()
        if not source_value:
            return "missing:secfacts:empty-source"
        try:
            from forecasting.source_adapters import load_sec_company_facts

            facts = load_sec_company_facts(source_value, limit=50)
        except Exception as exc:
            return f"missing:secfacts:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "accession_number": fact.accession_number,
                "cik": fact.cik,
                "concept": fact.concept,
                "entry_id": fact.entry_id,
                "filed_at": fact.filed_at,
                "frame": fact.frame,
                "observation_date": fact.observation_date,
                "published_at": fact.published_at,
                "taxonomy": fact.taxonomy,
                "unit": fact.unit,
                "value": fact.value,
            }
            for fact in facts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"secfacts:{len(payload)}:{digest}"

    def _arxiv_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("arxiv:") else source.strip()
        if not query:
            return "missing:arxiv:empty-query"
        try:
            from forecasting.source_adapters import load_arxiv_papers

            papers = load_arxiv_papers(query, limit=50)
        except Exception as exc:
            return f"missing:arxiv:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "arxiv_id": paper.arxiv_id,
                "categories": paper.categories,
                "entry_id": paper.entry_id,
                "published_at": paper.published_at,
                "title": paper.title,
                "updated_at": paper.updated_at,
            }
            for paper in papers
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"arxiv:{len(payload)}:{digest}"

    def _openalex_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("openalex:") else source.strip()
        if not query:
            return "missing:openalex:empty-query"
        try:
            from forecasting.source_adapters import load_openalex_works

            works = load_openalex_works(query, limit=50)
        except Exception as exc:
            return f"missing:openalex:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "concepts": work.concepts,
                "doi": work.doi,
                "entry_id": work.entry_id,
                "published_at": work.published_at,
                "title": work.title,
                "updated_at": work.updated_at,
                "work_id": work.work_id,
            }
            for work in works
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"openalex:{len(payload)}:{digest}"

    def _crossref_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("crossref:") else source.strip()
        if not query:
            return "missing:crossref:empty-query"
        try:
            from forecasting.source_adapters import load_crossref_works

            works = load_crossref_works(query, limit=50)
        except Exception as exc:
            return f"missing:crossref:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "cited_by_count": work.cited_by_count,
                "container_title": work.container_title,
                "doi": work.doi,
                "entry_id": work.entry_id,
                "published_at": work.published_at,
                "publisher": work.publisher,
                "reference_count": work.reference_count,
                "title": work.title,
                "updated_at": work.updated_at,
                "work_type": work.work_type,
            }
            for work in works
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"crossref:{len(payload)}:{digest}"

    def _reliefweb_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("reliefweb:") else source.strip()
        if not query:
            return "missing:reliefweb:empty-query"
        try:
            from forecasting.source_adapters import load_reliefweb_reports

            reports = load_reliefweb_reports(query, limit=50)
        except Exception as exc:
            return f"missing:reliefweb:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "changed_at": report.changed_at,
                "countries": report.countries,
                "disasters": report.disasters,
                "entry_id": report.entry_id,
                "published_at": report.published_at,
                "report_id": report.report_id,
                "sources": report.sources,
                "title": report.title,
                "url": report.url,
            }
            for report in reports
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"reliefweb:{len(payload)}:{digest}"

    def _wikipedia_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("wikipedia:") else source.strip()
        if not query:
            return "missing:wikipedia:empty-query"
        try:
            from forecasting.source_adapters import load_wikipedia_pages

            pages = load_wikipedia_pages(query, limit=50)
        except Exception as exc:
            return f"missing:wikipedia:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": page.entry_id,
                "page_id": page.page_id,
                "title": page.title,
                "updated_at": page.updated_at,
                "url": page.url,
            }
            for page in pages
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"wikipedia:{len(payload)}:{digest}"

    def _wikipediapageviews_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("wikipediapageviews:") else source.strip()
        if not source_value:
            return "missing:wikipediapageviews:empty-source"
        try:
            from forecasting.source_adapters import load_wikimedia_pageviews

            observations = load_wikimedia_pageviews(source_value, limit=50)
        except Exception as exc:
            return f"missing:wikipediapageviews:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "access": observation.access,
                "agent": observation.agent,
                "article": observation.article,
                "entry_id": observation.entry_id,
                "granularity": observation.granularity,
                "observation_date": observation.observation_date,
                "project": observation.project,
                "views": observation.views,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"wikipediapageviews:{len(payload)}:{digest}"

    def _manifold_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("manifold:") else source.strip()
        if not source_value:
            return "missing:manifold:empty-source"
        try:
            from forecasting.source_adapters import load_manifold_market

            market = load_manifold_market(source_value)
        except Exception as exc:
            return f"missing:manifold:{source_value}:{exc.__class__.__name__}"
        payload = {
            "close_time": market.close_time,
            "distribution": market.distribution,
            "is_resolved": market.is_resolved,
            "market_id": market.market_id,
            "probability": market.probability,
            "question": market.question,
            "resolution": market.resolution,
            "resolution_time": market.resolution_time,
            "slug": market.slug,
            "url": market.url,
        }
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"manifold:1:{digest}"

    def _metaculus_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("metaculus:") else source.strip()
        if not source_value:
            return "missing:metaculus:empty-source"
        try:
            from forecasting.source_adapters import load_metaculus_question

            question = load_metaculus_question(source_value)
        except Exception as exc:
            return f"missing:metaculus:{source_value}:{exc.__class__.__name__}"
        payload = {
            "close_time": question.close_time,
            "distribution": question.distribution,
            "probability": question.probability,
            "question_id": question.question_id,
            "resolution": question.resolution,
            "resolution_time": question.resolution_time,
            "status": question.status,
            "title": question.title,
            "url": question.url,
        }
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"metaculus:1:{digest}"

    def _polymarket_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("polymarket:") else source.strip()
        if not source_value:
            return "missing:polymarket:empty-source"
        try:
            from forecasting.source_adapters import load_polymarket_market

            market = load_polymarket_market(source_value)
        except Exception as exc:
            return f"missing:polymarket:{source_value}:{exc.__class__.__name__}"
        payload = {
            "close_time": market.close_time,
            "distribution": market.distribution,
            "market_id": market.market_id,
            "probability": market.probability,
            "question": market.question,
            "resolution_time": market.resolution_time,
            "slug": market.slug,
            "url": market.url,
        }
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"polymarket:1:{digest}"

    def _kalshi_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("kalshi:") else source.strip()
        if not source_value:
            return "missing:kalshi:empty-source"
        try:
            from forecasting.source_adapters import load_kalshi_market

            market = load_kalshi_market(source_value)
        except Exception as exc:
            return f"missing:kalshi:{source_value}:{exc.__class__.__name__}"
        payload = {
            "close_time": market.close_time,
            "event_ticker": market.event_ticker,
            "probability": market.probability,
            "question": market.question,
            "resolution_time": market.resolution_time,
            "result": market.result,
            "status": market.status,
            "ticker": market.ticker,
            "url": market.url,
        }
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"kalshi:1:{digest}"

    def _validate_watch_scope(self, scope_type: str, scope_ref: str | None) -> None:
        if scope_type not in WATCH_SCOPE_TYPES:
            raise ValidationError("scope_type must be question, domain, topic, domain_topic, or portfolio")
        if not scope_ref:
            raise ValidationError("scope_ref is required for watched sources")
        if scope_type == "question":
            self.get_question(scope_ref)
        if scope_type == "domain_topic":
            payload = json_loads(scope_ref, {})
            if not payload.get("domain") or not payload.get("topic"):
                raise ValidationError("domain_topic watched sources require domain and topic")

    def _self_check_watch_scope(
        self,
        *,
        question_id: str | None,
        domain: str | None,
        topic: str | None,
        portfolio: str | None,
    ) -> tuple[str | None, str | None]:
        if question_id:
            return "question", question_id
        if portfolio:
            return "portfolio", portfolio
        if domain and topic:
            return "domain_topic", json_dumps({"domain": domain, "topic": topic})
        if domain:
            return "domain", domain
        if topic:
            return "topic", topic
        return None, None

    def _watched_source_action(self, watch: dict[str, Any]) -> str:
        source = watch["source"]
        scope_type = watch["scope_type"]
        scope_ref = watch["scope_ref"]
        if watch["source_type"] == "rss" and scope_type == "question" and scope_ref:
            feed_source = source.split(":", 1)[1] if source.startswith(("rss:", "atom:")) else source
            filters = self._rss_relevance_filters(watch.get("metadata") or {})
            filter_args = self._rss_filter_cli_args(filters)
            since_arg = f" --since {watch['last_checked_at']}" if watch.get("last_checked_at") else ""
            return (
                f"Run `forecast import news {self._shell_arg(feed_source)} --question {scope_ref}"
                f"{since_arg}{filter_args}` to capture filtered RSS evidence candidates, "
                "then review the evidence and update only if the probability should move."
            )
        if watch["source_type"] == "gdelt" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("gdelt:") else source
            return (
                f"Run `forecast import gdelt \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "fivethirtyeight" and scope_type == "question" and scope_ref:
            source_value = (
                source.split(":", 1)[1].strip()
                if source.startswith(("fivethirtyeight:", "538:"))
                else source
            )
            return (
                f"Run `forecast import fivethirtyeight {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "github" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("github:") else source
            return (
                f"Run `forecast import github {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "githubrepo" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("githubrepo:") else source
            return (
                f"Run `forecast import githubrepo {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "githubissues" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("githubissues:") else source
            return (
                f"Run `forecast import githubissues {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "githubcommits" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("githubcommits:") else source
            return (
                f"Run `forecast import githubcommits {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "githubactions" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("githubactions:") else source
            return (
                f"Run `forecast import githubactions {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "coingecko" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("coingecko:") else source
            return (
                f"Run `forecast import coingecko {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "pypi" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("pypi:") else source
            return (
                f"Run `forecast import pypi {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "npm" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("npm:") else source
            return (
                f"Run `forecast import npm {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "hackernews" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("hackernews:") else source
            return (
                f"Run `forecast import hackernews \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "reddit" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("reddit:") else source
            return (
                f"Run `forecast import reddit \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "bluesky" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("bluesky:") else source
            return (
                f"Run `forecast import bluesky \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "mastodon" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("mastodon:") else source
            return (
                f"Run `forecast import mastodon \"{source_value}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "reliefweb" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("reliefweb:") else source
            return (
                f"Run `forecast import reliefweb \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "federalregister" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("federalregister:") else source
            return (
                f"Run `forecast import federalregister \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "courtlistener" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("courtlistener:") else source
            return (
                f"Run `forecast import courtlistener \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "nvd" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("nvd:") else source
            return (
                f"Run `forecast import nvd \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "cisakev" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("cisakev:") else source
            return (
                f"Run `forecast import cisakev \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "openmeteo" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("openmeteo:") else source
            return (
                f"Run `forecast import openmeteo {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "airquality" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("airquality:") else source
            return (
                f"Run `forecast import airquality {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "weatherhistory" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("weatherhistory:") else source
            location, query = (source_value.split("?", 1) + [""])[:2] if "?" in source_value else (source_value, "")
            params = dict(parse_qsl(query, keep_blank_values=False))
            start_date = params.get("start") or params.get("start_date")
            end_date = params.get("end") or params.get("end_date")
            date_args = f" --start-date {start_date} --end-date {end_date}" if start_date and end_date else ""
            return (
                f"Run `forecast import weatherhistory {location}{date_args} --question {scope_ref}` and then append "
                "a forecast update if the historical base rate should move."
            )
        if watch["source_type"] == "usgs" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("usgs:") else source
            return (
                f"Run `forecast import usgs \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "eonet" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("eonet:") else source
            return (
                f"Run `forecast import eonet \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "nws" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("nws:") else source
            return (
                f"Run `forecast import nws \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "clinicaltrials" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("clinicaltrials:") else source
            return (
                f"Run `forecast import clinicaltrials \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "openfda" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("openfda:") else source
            return (
                f"Run `forecast import openfda \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "pubmed" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("pubmed:") else source
            return (
                f"Run `forecast import pubmed \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "owid" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("owid:") else source
            return (
                f"Run `forecast import owid {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "whogho" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("whogho:") else source
            return (
                f"Run `forecast import whogho {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "fema" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("fema:") else source
            return (
                f"Run `forecast import fema {self._cli_arg(source_value)} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "fred" and scope_type == "question" and scope_ref:
            series_id = source.split(":", 1)[1].strip() if source.startswith("fred:") else source
            return (
                f"Run `forecast import fred {series_id} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "eia" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("eia:") else source
            return (
                f"Run `forecast import eia {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "treasury" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("treasury:") else source
            return (
                f"Run `forecast import treasury {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "bls" and scope_type == "question" and scope_ref:
            series_id = source.split(":", 1)[1].strip() if source.startswith("bls:") else source
            return (
                f"Run `forecast import bls {series_id} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "worldbank" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("worldbank:") else source
            return (
                f"Run `forecast import worldbank {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "imf" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("imf:") else source
            return (
                f"Run `forecast import imf {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "census" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("census:") else source
            return (
                f"Run `forecast import census \"{source_value}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "socrata" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("socrata:") else source
            return (
                f"Run `forecast import socrata \"{source_value}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "ckan" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("ckan:") else source
            return (
                f"Run `forecast import ckan {self._cli_arg(source_value)} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "stooq" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("stooq:") else source
            return (
                f"Run `forecast import stooq {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "yahoo" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("yahoo:") else source
            return (
                f"Run `forecast import yahoo {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "sec" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("sec:") else source
            return (
                f"Run `forecast import sec {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "secfacts" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("secfacts:") else source
            return (
                f"Run `forecast import secfacts {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "arxiv" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("arxiv:") else source
            return (
                f"Run `forecast import arxiv \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "openalex" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("openalex:") else source
            return (
                f"Run `forecast import openalex \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "crossref" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("crossref:") else source
            return (
                f"Run `forecast import crossref \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "wikipedia" and scope_type == "question" and scope_ref:
            query = source.split(":", 1)[1].strip() if source.startswith("wikipedia:") else source
            return (
                f"Run `forecast import wikipedia \"{query}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] == "wikipediapageviews" and scope_type == "question" and scope_ref:
            source_value = source.split(":", 1)[1].strip() if source.startswith("wikipediapageviews:") else source
            return (
                f"Run `forecast import wikipediapageviews {source_value} --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if watch["source_type"] in {"manifold", "metaculus", "polymarket", "kalshi"} and scope_type == "question" and scope_ref:
            source_type = watch["source_type"]
            source_value = source.split(":", 1)[1].strip() if source.startswith(f"{source_type}:") else source
            return (
                f"Run `forecast import {source_type} \"{source_value}\" --question {scope_ref}` and then append "
                "a forecast update if the probability should move."
            )
        if scope_type == "question" and scope_ref:
            return (
                f"Run `forecast research {scope_ref} {source}` and then append "
                "a forecast update if the probability should move."
            )
        if scope_type == "domain":
            domain_arg = self._cli_arg(scope_ref)
            return (
                f"Run `forecast self-check --domain {domain_arg} --auto-score --auto-postmortem`, "
                f"then run `forecast review --domain {domain_arg}` and update affected forecasts explicitly."
            )
        if scope_type == "topic":
            topic_arg = self._cli_arg(scope_ref)
            return (
                f"Run `forecast self-check --topic {topic_arg} --auto-score --auto-postmortem`, "
                "then review impacted active questions and calibration lessons."
            )
        if scope_type == "portfolio":
            portfolio_arg = self._cli_arg(scope_ref)
            return (
                f"Run `forecast self-check --portfolio {portfolio_arg} --auto-score --auto-postmortem`, "
                "then review impacted active questions and calibration lessons."
            )
        if scope_type == "domain_topic":
            payload = json_loads(scope_ref, {})
            domain_arg = self._cli_arg(str(payload.get("domain", "")))
            topic_arg = self._cli_arg(str(payload.get("topic", "")))
            return (
                f"Run `forecast self-check --domain {domain_arg} --topic {topic_arg} "
                "--auto-score --auto-postmortem`, then review impacted active questions and calibration lessons."
            )
        return "Review the watched source and update affected forecasts explicitly."

    def _cli_arg(self, value: str) -> str:
        text = str(value or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_./:@%+=,-]+", text):
            return text
        return json.dumps(text)

    def _candidate_title_from_source(self, source: str, source_type: str) -> str:
        if source_type == "url":
            parsed = urlparse(source)
            path = parsed.path.strip("/").split("/")[-1]
            label = path.replace("-", " ").replace("_", " ").strip()
            return label or parsed.netloc or "Ingested forecast candidate"
        if source_type == "file":
            return Path(source).expanduser().stem.replace("-", " ").replace("_", " ") or "Ingested forecast candidate"
        return source[:80] or "Ingested forecast candidate"

    def _question_to_dict(self, question: ForecastQuestion) -> dict[str, Any]:
        data = question.__dict__.copy()
        data["outcome_space"] = question.outcome_space.to_dict()
        return data

    def _snapshot_to_dict(self, snapshot: ForecastSnapshot) -> dict[str, Any]:
        return snapshot.__dict__.copy()

    def _evidence_to_dict(self, item: EvidenceItem) -> dict[str, Any]:
        return item.__dict__.copy()

    def _resolution_to_dict(self, resolution: Resolution) -> dict[str, Any]:
        return resolution.__dict__.copy()

    def _score_to_dict(self, score: ScoreRecord) -> dict[str, Any]:
        return score.__dict__.copy()
