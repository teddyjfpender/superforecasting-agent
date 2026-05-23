"""Core forecast ledger domain models."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


OUTCOME_TYPES = {"binary", "categorical", "numeric", "distribution"}
QUESTION_STATUSES = {"active", "closed", "resolved", "archived"}
FORECAST_ORIGINS = {"live", "backtest", "imported_baseline"}
RESOLUTION_STATUSES = {"proposed", "confirmed", "disputed", "corrected"}
ASSUMPTION_STATUSES = {"active", "stale", "invalidated", "resolved"}
REFERENCE_CLASS_STATUSES = {"active", "stale", "invalidated", "superseded"}
EVIDENCE_CLAIM_TYPES = {"fact", "estimate", "rumor", "opinion", "assumption"}
CALIBRATION_LESSON_STATUSES = {"tentative", "active", "superseded", "rejected"}


class ForecastingError(Exception):
    """Base exception for forecasting package errors."""


class ValidationError(ForecastingError):
    """Raised when user-supplied forecast data is not valid."""


class LedgerNotFoundError(ForecastingError):
    """Raised when a ledger object cannot be found."""


def utc_now_iso() -> str:
    """Return a compact UTC timestamp suitable for append-only records."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str | None, *, field_name: str = "timestamp") -> str | None:
    """Validate an ISO-ish timestamp and normalize UTC offsets to ``Z``."""

    if value is None or value == "":
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def timestamp_to_datetime(value: str | None) -> datetime | None:
    """Convert a stored timestamp into an aware ``datetime``."""

    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def json_dumps(value: Any) -> str:
    """Dump JSON deterministically for SQLite text columns."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def json_loads(value: str | bytes | None, default: Any) -> Any:
    """Load JSON from SQLite text columns with a caller-supplied default."""

    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


@dataclass(frozen=True)
class OutcomeSpace:
    """Represents the scoreable outcome space for a forecast question."""

    type: str = "binary"
    choices: list[str] = field(default_factory=lambda: ["yes", "no"])
    units: str | None = None
    bounds: list[float] | None = None
    resolution_parser: str | None = None

    def validate(self) -> None:
        if self.type not in OUTCOME_TYPES:
            raise ValidationError(
                f"outcome type must be one of {', '.join(sorted(OUTCOME_TYPES))}"
            )
        if self.type == "binary":
            choices = self.choices or ["yes", "no"]
            if len(choices) != 2:
                raise ValidationError("binary outcome spaces must have exactly two choices")
        if self.type == "categorical" and len(self.choices) < 2:
            raise ValidationError("categorical outcome spaces require at least two choices")
        if self.bounds is not None and len(self.bounds) != 2:
            raise ValidationError("bounds must contain exactly [min, max]")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "type": self.type,
            "choices": self.choices,
            "units": self.units,
            "bounds": self.bounds,
            "resolution_parser": self.resolution_parser,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OutcomeSpace":
        if not data:
            return cls()
        outcome = cls(
            type=str(data.get("type") or "binary"),
            choices=list(data.get("choices") or (["yes", "no"] if data.get("type", "binary") == "binary" else [])),
            units=data.get("units"),
            bounds=data.get("bounds"),
            resolution_parser=data.get("resolution_parser"),
        )
        outcome.validate()
        return outcome

    @classmethod
    def from_json(cls, value: str | None) -> "OutcomeSpace":
        return cls.from_dict(json_loads(value, {}))

    def to_json(self) -> str:
        return json_dumps(self.to_dict())


@dataclass(frozen=True)
class ForecastQuestion:
    id: str
    title: str
    description: str
    resolution_criteria: str
    resolution_source: str | None
    created_at: str
    close_time: str | None
    resolution_time: str | None
    outcome_space: OutcomeSpace
    status: str
    tags: list[str]
    domain: str | None
    topics: list[str]
    owner: str | None
    impact: str | None
    review_cadence: str | None
    next_review_at: str | None
    current_forecast_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ForecastSnapshot:
    forecast_id: str
    question_id: str
    created_at: str
    as_of: str
    probability_or_distribution: Any
    confidence: float | None
    forecast_horizon_days: float | None
    method: str | None
    ensemble_components: dict[str, Any]
    rationale: str
    key_assumptions: list[str]
    assumption_refs: list[str]
    reference_class_refs: list[str]
    evidence_refs: list[str]
    model_run_refs: list[str]
    parent_forecast_id: str | None
    forecast_origin: str
    agent_model: str | None
    prompt_version: str | None
    forecasting_protocol_version: str | None
    toolset_version: str | None
    source_snapshot_refs: list[str]
    evidence_cutoff: str | None
    backtest_run_id: str | None
    calibration_eligible: bool
    calibration_weight: float
    calibration_lesson_refs: list[str]
    calibration_adjustment: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    question_id: str
    captured_at: str
    available_at: str
    source_url: str | None
    source_name: str | None
    source_type: str
    published_at: str | None
    claim: str
    summary: str
    reliability_rating: float | None
    relevance_rating: float | None
    stance: str
    claim_type: str
    snapshot_path: str | None
    admissible_for_backtests: bool
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Resolution:
    id: str
    question_id: str
    resolved_at: str
    outcome: Any
    resolution_source: str | None
    resolution_source_snapshot_ref: str | None
    resolver_type: str
    resolution_status: str
    criteria_satisfied: bool
    confidence: float | None
    confirmed_at: str | None
    confirmed_by: str | None
    resolver_notes: str | None
    disputed_at: str | None
    correction_ref: str | None
    scoreable: bool
    trusted_policy_id: str | None


@dataclass(frozen=True)
class ScoreRecord:
    id: str
    question_id: str
    forecast_id: str
    resolution_id: str
    scored_at: str
    brier_score: float | None
    log_score: float | None
    proper_score: float | None
    score_rule: str | None
    calibration_bucket: str | None
    forecast_horizon_days: float | None
    domain: str | None
    forecast_origin: str
    calibration_eligible: bool
    calibration_weight: float
    baseline_ref: str | None
    invalidated_by_correction_id: str | None
    notes: str | None


@dataclass(frozen=True)
class AlertEvent:
    id: str
    created_at: str
    severity: str
    scope_type: str
    scope_ref: str
    reason: str
    recommended_action: str
    acknowledged_at: str | None
