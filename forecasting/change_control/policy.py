"""Deterministic risk classification and human-review quorum."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from forecasting.change_control.models import LedgerOperation
from forecasting.models import ValidationError


_HIGH_RISK_KINDS = frozenset(
    {"question.criteria.update", "resolution.create", "lesson.activate"}
)
_MEDIUM_RISK_KINDS = frozenset(
    {
        "forecast.create",
        "forecast.update",
        "assumption.upsert",
        "reference_class.upsert",
        "thesis.update",
    }
)
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
_OWNER_ROLES = frozenset({"forecast_owner", "domain_steward"})


@dataclass(frozen=True)
class RiskAssessment:
    tier: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class QuorumResult:
    satisfied: bool
    required_humans: int
    approved_owner_ids: tuple[str, ...]
    owner_or_steward_present: bool
    reasons: tuple[str, ...]


def _probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, Mapping):
        candidate = value.get("probability", value.get("yes"))
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            return None
        result = float(candidate)
    else:
        return None
    return result if 0.0 <= result <= 1.0 else None


def classify_operations(
    operations: Sequence[LedgerOperation],
    *,
    materiality_threshold: float = 0.10,
    risk_overrides: Mapping[str, str] | None = None,
    hook_results: Iterable[Mapping[str, Any]] = (),
) -> RiskAssessment:
    if not 0.0 <= materiality_threshold <= 1.0:
        raise ValidationError("materiality_threshold must be between 0 and 1")
    tier = "low"
    reasons: list[str] = []
    overrides = dict(risk_overrides or {})
    unknown_tiers = sorted(set(overrides.values()) - set(_RISK_ORDER))
    if unknown_tiers:
        raise ValidationError(f"unknown risk tier override: {unknown_tiers[0]}")
    for operation in operations:
        operation_tier = "low"
        if operation.kind in _HIGH_RISK_KINDS:
            operation_tier = "high"
            reasons.append(f"protected operation:{operation.kind}")
        elif operation.kind in _MEDIUM_RISK_KINDS:
            operation_tier = "medium"
            reasons.append(f"forecast-bearing operation:{operation.kind}")
        if operation.kind == "forecast.update":
            before = _probability(operation.preconditions.get("prior_probability"))
            after = _probability(operation.payload.get("probability_or_distribution"))
            if before is not None and after is not None:
                delta = abs(after - before)
                # Decimal percentages arrive through binary floats; treat an
                # exact 10pp move as material even when represented as
                # 0.09999999999999998.
                if delta >= materiality_threshold - 1e-12:
                    operation_tier = "high"
                    reasons.append(
                        f"probability delta {delta:.6f} >= {materiality_threshold:.6f}"
                    )
        if operation.payload.get("protected") or operation.preconditions.get("protected"):
            operation_tier = "high"
            reasons.append(f"protected target:{operation.target_ref}")
        override = overrides.get(operation.kind)
        if override and _RISK_ORDER[override] > _RISK_ORDER[operation_tier]:
            operation_tier = override
            reasons.append(f"workspace policy raised {operation.kind} to {override}")
        if _RISK_ORDER[operation_tier] > _RISK_ORDER[tier]:
            tier = operation_tier
    for hook in hook_results:
        requested = hook.get("minimum_risk_tier")
        if requested in _RISK_ORDER and _RISK_ORDER[str(requested)] > _RISK_ORDER[tier]:
            tier = str(requested)
            reasons.append(f"hook raised changeset to {requested}")
    return RiskAssessment(tier=tier, reasons=tuple(dict.fromkeys(reasons)))


def evaluate_quorum(
    *,
    risk_tier: str,
    reviews: Iterable[Mapping[str, Any]],
    changeset_digest: str,
    head_sha: str | None = None,
    author_owner_ids: Iterable[str] = (),
) -> QuorumResult:
    if risk_tier not in _RISK_ORDER:
        raise ValidationError(f"unknown risk tier: {risk_tier}")
    required = {"low": 0, "medium": 1, "high": 2}[risk_tier]
    authors = {str(value) for value in author_owner_ids if str(value)}
    approvals: dict[str, Mapping[str, Any]] = {}
    for review in reviews:
        owner_id = str(review.get("owner_id") or "")
        if not owner_id or owner_id in authors:
            continue
        if review.get("actor_kind") != "human" or review.get("decision") != "approve":
            continue
        if review.get("stale_at") or review.get("changeset_digest") != changeset_digest:
            continue
        review_head = review.get("head_sha")
        if head_sha and review_head != head_sha:
            continue
        approvals[owner_id] = review
    owner_or_steward = any(
        str(review.get("role") or "") in _OWNER_ROLES for review in approvals.values()
    )
    reasons: list[str] = []
    if len(approvals) < required:
        reasons.append(f"human approvals {len(approvals)}/{required}")
    if risk_tier == "high" and not owner_or_steward:
        reasons.append("forecast owner or domain steward approval required")
    return QuorumResult(
        satisfied=not reasons,
        required_humans=required,
        approved_owner_ids=tuple(sorted(approvals)),
        owner_or_steward_present=owner_or_steward,
        reasons=tuple(reasons),
    )


__all__ = ["QuorumResult", "RiskAssessment", "classify_operations", "evaluate_quorum"]
