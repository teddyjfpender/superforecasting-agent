"""Core forecast ledger domain models."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


OUTCOME_TYPES = {"binary", "categorical", "numeric", "distribution", "thesis"}
QUESTION_STATUSES = {"active", "closed", "resolved", "archived"}
# "exploratory" is the scratchpad origin: a forecast the agent is thinking
# out loud with, NOT committing. It is exempt from the commit-time formalities
# (structured reasoning, citations, decision readiness) and is never
# calibration-scored. Commit a "live" forecast to put it on the record.
# "market_nightly" is the AIA P2.1 foreknowledge-proof live benchmark origin: a
# forecast committed NOW against a currently-OPEN market that resolves in the
# FUTURE, scored only when the market closes. It is segregated from the agent's
# curated "live" book (it never updates the live calibration profile and is
# exempt from the live commit-time formalities) so the benchmark cannot pollute,
# or be polluted by, the live desk.
FORECAST_ORIGINS = {"live", "exploratory", "backtest", "imported_baseline", "market_nightly"}
RESOLUTION_STATUSES = {"proposed", "confirmed", "disputed", "corrected"}
ASSUMPTION_STATUSES = {"active", "stale", "invalidated", "resolved"}
REFERENCE_CLASS_STATUSES = {"active", "stale", "invalidated", "superseded"}
EVIDENCE_CLAIM_TYPES = {"fact", "estimate", "rumor", "opinion", "assumption"}
CALIBRATION_LESSON_STATUSES = {"tentative", "active", "superseded", "rejected"}
FAILURE_CLASSES = {
    "base_rate",
    "inside_view",
    "definition",
    "timing",
    "aggregation",
    "motivated_reasoning",
    "tail",
    "noise",
    "other",
}


# AIA P2.4 — best-effort pretraining-cutoff registry for known base models.
#
# UNCERTAIN / BEST-EFFORT: these dates are the providers' publicly stated (or
# widely reported) knowledge cutoffs, normalized to an ISO date. They are NOT
# authoritative and a model may have absorbed later data via RLHF / tool use.
# The registry exists for ONE narrow purpose: a backtest must reject a base
# model whose cutoff lands at-or-after the event being predicted (the model may
# already "know" the answer), mirroring the AIA paper rejecting a too-fresh base
# model for a liquid-market benchmark. Keys are matched as case-insensitive
# substrings of the case ``agent_model`` so version suffixes still resolve.
MODEL_PRETRAINING_CUTOFF: dict[str, str] = {
    "gpt-4o": "2023-10-01",
    "gpt-4-turbo": "2023-12-01",
    "gpt-4": "2023-04-01",
    "gpt-4.1": "2024-06-01",
    # gpt-5.5 cutoff confirmed by the operator (2025-12-01); gpt-5 family takes the
    # same conservative date as a longest-substring fallback for other gpt-5.x.
    "gpt-5.5": "2025-12-01",
    "gpt-5": "2025-12-01",
    "gpt-3.5": "2021-09-01",
    "o1": "2023-10-01",
    "o3": "2024-06-01",
    "claude-3-opus": "2023-08-01",
    "claude-3-5-sonnet": "2024-04-01",
    "claude-3.5-sonnet": "2024-04-01",
    "claude-3-7-sonnet": "2024-10-01",
    "claude-3.7-sonnet": "2024-10-01",
    "claude-opus-4": "2025-03-01",
    "claude-sonnet-4": "2025-03-01",
    "gemini-1.5-pro": "2023-11-01",
    "gemini-2.0": "2024-08-01",
    "gemini-2.5": "2025-01-01",
    "llama-3": "2023-12-01",
    "llama-3.1": "2023-12-01",
    "mistral-large": "2023-12-01",
    "deepseek-v3": "2024-07-01",
    "deepseek-r1": "2024-07-01",
    "grok-2": "2024-07-01",
    "grok-3": "2024-11-01",
}


def lookup_model_pretraining_cutoff(agent_model: str | None) -> str | None:
    """Best-effort pretraining cutoff (ISO date) for ``agent_model`` or ``None``.

    Matches the longest known registry key that is a case-insensitive substring
    of ``agent_model`` so that e.g. ``"openai/gpt-4o-2024-08-06"`` resolves to
    the ``gpt-4o`` entry. Returns ``None`` for unknown / empty models so the
    cutoff gate is a strict no-op when we cannot make a confident claim.
    """
    if not agent_model:
        return None
    needle = str(agent_model).strip().lower()
    if not needle:
        return None
    best_key: str | None = None
    for key in MODEL_PRETRAINING_CUTOFF:
        if key in needle and (best_key is None or len(key) > len(best_key)):
            best_key = key
    return MODEL_PRETRAINING_CUTOFF[best_key] if best_key is not None else None


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


def recency_halflife_weight(age_days: float, halflife_days: float | None) -> float:
    """Deterministic exponential recency weight: ``0.5 ** (age_days / halflife)``.

    The single source of truth for the half-life recency weighting used by the
    calibration-bias loop (``ledger._bias_observations``) and the evidence
    capture-quality stamp (``source_search``). A non-positive half-life, a
    non-positive age, or an unusable input returns ``1.0`` (no down-weighting) so
    the caller degrades to "treat as fresh" rather than error.
    """
    try:
        halflife = float(halflife_days) if halflife_days is not None else 0.0
        age = float(age_days)
    except (TypeError, ValueError):
        return 1.0
    if halflife <= 0 or age <= 0:
        return 1.0
    return 0.5 ** (age / halflife)


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
    decision_owner: str | None = None
    decision_deadline: str | None = None
    action_threshold: str | None = None
    update_triggers: list[dict[str, Any]] = field(default_factory=list)


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
    reasons_up: list[str] = field(default_factory=list)
    reasons_down: list[str] = field(default_factory=list)
    change_my_mind: list[str] = field(default_factory=list)


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


# Comparison operators that make an update trigger *executable* — i.e. checkable
# against an imported numeric observation, not just a free-form note.
TRIGGER_OPERATORS = {">", ">=", "<", "<=", "==", "!="}


def normalize_update_triggers(raw: Any) -> list[dict[str, Any]]:
    """Coerce ``update_triggers`` payload into a validated list of dicts.

    Each trigger requires a non-empty ``mechanism`` (free-form text or a source
    identifier such as ``fred:CPIAUCSL``). ``threshold``, ``action``, and
    ``window`` are optional. Strings are treated as ``{"mechanism": value}``.

    A trigger becomes *executable* when it carries an ``operator`` (one of
    :data:`TRIGGER_OPERATORS`) plus a ``source_ref`` and a numeric ``threshold``:
    the loop can then compare it against the latest imported value for that
    source and fire an alert. Setting ``operator`` requires a numeric
    ``threshold``; without an operator the trigger stays a free-form note.
    """

    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValidationError("update_triggers must be a list of objects")
    out: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        if isinstance(entry, str):
            entry = {"mechanism": entry.strip()}
        if not isinstance(entry, dict):
            raise ValidationError(
                f"update_triggers[{index}] must be a string or object"
            )
        mechanism = str(entry.get("mechanism") or "").strip()
        if not mechanism:
            raise ValidationError(
                f"update_triggers[{index}] requires a non-empty mechanism"
            )
        normalized: dict[str, Any] = {"mechanism": mechanism}
        for key in ("threshold", "action", "window", "source_ref", "notes"):
            value = entry.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            normalized[key] = value
        operator = entry.get("operator")
        if operator is not None:
            operator = str(operator).strip()
            if operator not in TRIGGER_OPERATORS:
                raise ValidationError(
                    f"update_triggers[{index}] operator must be one of "
                    + ", ".join(sorted(TRIGGER_OPERATORS))
                )
            if "threshold" not in normalized:
                raise ValidationError(
                    f"update_triggers[{index}] with an operator requires a numeric threshold"
                )
            try:
                normalized["threshold"] = float(normalized["threshold"])
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"update_triggers[{index}] threshold must be numeric when an operator is set"
                ) from exc
            normalized["operator"] = operator
        out.append(normalized)
    return out


def _compare_trigger(observed: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return observed > threshold
    if operator == ">=":
        return observed >= threshold
    if operator == "<":
        return observed < threshold
    if operator == "<=":
        return observed <= threshold
    if operator == "==":
        return observed == threshold
    if operator == "!=":
        return observed != threshold
    return False


def evaluate_update_triggers(
    triggers: list[dict[str, Any]] | None,
    observations: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the executable triggers that fire for the given observations.

    ``observations`` maps a ``source_ref`` to its latest numeric value. Only
    triggers with an ``operator``, a ``source_ref`` present in ``observations``,
    and a numeric ``threshold`` are evaluated; free-form triggers are ignored.
    Each fired entry records mechanism, source_ref, operator, threshold, and the
    observed value so the caller can build an actionable alert.
    """

    fired: list[dict[str, Any]] = []
    for trigger in triggers or []:
        source_ref = trigger.get("source_ref")
        operator = trigger.get("operator")
        threshold = trigger.get("threshold")
        if not source_ref or operator not in TRIGGER_OPERATORS:
            continue
        if not isinstance(threshold, (int, float)):
            continue
        if source_ref not in observations:
            continue
        try:
            observed = float(observations[source_ref])
        except (TypeError, ValueError):
            continue
        if _compare_trigger(observed, operator, float(threshold)):
            fired.append(
                {
                    "mechanism": trigger["mechanism"],
                    "source_ref": source_ref,
                    "operator": operator,
                    "threshold": float(threshold),
                    "observed": observed,
                }
            )
    return fired


def question_decision_readiness_issues(question: "ForecastQuestion") -> list[str]:
    """Return missing-decision-context issues, in priority order.

    Returns an empty list when the question carries a decision owner, an
    action threshold, and at least one update trigger. Suitable for both the
    parse stage's audit and the update stage's optional refuse-to-snapshot
    gate.
    """

    issues: list[str] = []
    if not (question.decision_owner or "").strip():
        issues.append("missing decision_owner")
    if not (question.action_threshold or "").strip():
        issues.append("missing action_threshold")
    if not question.update_triggers:
        issues.append("missing update_triggers")
    return issues


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
    # Dismissal audit trail (Slice 5). A dismissal is an explicit, RECORDED human
    # silence — NOT a resolution. It sets ``acknowledged_at`` (so the alert drops
    # out of the open backlog) but ALSO stamps these fields, which is what makes a
    # dismissal visibly + auditably distinct from a runner-resolution (the latter
    # leaves ``dismissed_at`` NULL). A dismissed group re-surfaces after the TTL.
    dismissed_at: str | None = None
    dismiss_note: str | None = None
    dismiss_actor: str | None = None
    dismiss_reason: str | None = None
    dismiss_ttl_days: int | None = None
    # Re-spend cooldown (Slice 8). A paid-tier (LLM) resolution attempt that did
    # NOT resolve the alert stamps these — ``last_attempted_at`` (when the spendy
    # runner last fired for this alert) and ``attempt_count`` (how many times it
    # has failed). They drive an exponential backoff so the continuous paid tier
    # does NOT re-spend on the same gated/failing alert every cycle. They are the
    # opposite of an ack: the alert stays OPEN (never bare-acked) but COOLED DOWN
    # until its backoff window passes. A successful resolution acks the alert (it
    # drops out of the open backlog), so these never gate a forecast that moved.
    last_attempted_at: str | None = None
    attempt_count: int = 0

    @property
    def is_dismissed(self) -> bool:
        """True when this alert was silenced by an explicit recorded human dismissal
        (as opposed to acked by a real gated resolution)."""
        return bool(self.dismissed_at)
