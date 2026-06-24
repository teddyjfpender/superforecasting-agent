"""Resolver engine — pure, ledger-free proposal logic.

Resolution is manual-heavy today, which does not scale (feedback #9). The three
high-value resolvers the user wants — earnings segment-beat, benchmark-leaderboard,
infrastructure-announcement — are all the SAME shape underneath: capture a metric
from a watched source, compare it to a threshold/consensus, and PROPOSE a YES/NO
(the user explicitly accepts propose-then-confirm, not blind auto-resolution).

This module is the generic ``metric_threshold`` engine behind that shape. It is
deliberately ledger-free: the ledger gathers the latest observed value from the
ingested source snapshots and calls :func:`propose_metric_threshold`. Domain
resolvers are thin configs over this (which source role, which field, comparator,
threshold) rather than three bespoke parsers. Keeping the decision logic pure makes
it exhaustively testable and keeps the "never fabricate" guarantee explicit:
without an observed value we return an UNDETERMINED proposal, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

RESOLVER_TYPES = {"metric_threshold"}

# Comparators a threshold rule may use. Kept tiny + total: an unknown comparator is
# a rule error, surfaced loudly, not silently coerced.
_COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


@dataclass(frozen=True)
class ResolutionProposal:
    """A PROPOSED resolution — never auto-committed. ``determinable`` is False when
    there is no observed value yet (the desk should keep watching, not resolve)."""

    question_id: str
    resolver: str
    determinable: bool
    outcome: str | None            # "yes" / "no" when determinable, else None
    observed_value: float | None
    comparator: str | None
    threshold: float | None
    confidence: float
    rationale: str
    source_ref: str | None = None

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "resolver": self.resolver,
            "determinable": self.determinable,
            "outcome": self.outcome,
            "observed_value": self.observed_value,
            "comparator": self.comparator,
            "threshold": self.threshold,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "source_ref": self.source_ref,
        }


def validate_metric_threshold_rule(rule: Mapping) -> list[str]:
    """Return a list of human-readable problems with a metric_threshold rule
    (empty == valid). Used at rule-set time so a lazy prompter is told exactly
    what is missing rather than discovering it silently at resolution."""
    issues: list[str] = []
    comparator = rule.get("comparator")
    if comparator not in _COMPARATORS:
        issues.append("comparator must be one of: " + ", ".join(sorted(_COMPARATORS)))
    if not isinstance(rule.get("threshold"), (int, float)):
        issues.append("threshold must be a number")
    if not str(rule.get("field") or "").strip():
        issues.append("field is required (which parsed value to read)")
    return issues


def propose_metric_threshold(
    *,
    question_id: str,
    rule: Mapping,
    observed_value: float | None,
    source_ref: str | None = None,
) -> ResolutionProposal:
    """Compare an observed metric to the rule's threshold and PROPOSE an outcome.

    ``observed_value`` is None when the watched source has not yet reported the
    field — we return an explicitly UNDETERMINED proposal (never a fabricated YES).
    """
    comparator = str(rule.get("comparator"))
    threshold = rule.get("threshold")
    op = _COMPARATORS.get(comparator)
    if op is None or not isinstance(threshold, (int, float)):
        return ResolutionProposal(
            question_id=question_id, resolver="metric_threshold", determinable=False,
            outcome=None, observed_value=observed_value, comparator=comparator,
            threshold=threshold if isinstance(threshold, (int, float)) else None,
            confidence=0.0, rationale="rule is not evaluable (bad comparator/threshold)",
            source_ref=source_ref,
        )
    if observed_value is None:
        return ResolutionProposal(
            question_id=question_id, resolver="metric_threshold", determinable=False,
            outcome=None, observed_value=None, comparator=comparator, threshold=float(threshold),
            confidence=0.0, rationale="no observed value yet from the resolver source; keep watching",
            source_ref=source_ref,
        )
    hit = op(float(observed_value), float(threshold))
    outcome = "yes" if hit else "no"
    return ResolutionProposal(
        question_id=question_id, resolver="metric_threshold", determinable=True,
        outcome=outcome, observed_value=float(observed_value), comparator=comparator,
        threshold=float(threshold), confidence=1.0,
        rationale=f"observed {observed_value} {comparator} {threshold} -> {outcome}",
        source_ref=source_ref,
    )
