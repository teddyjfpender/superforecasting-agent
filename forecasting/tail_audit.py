"""Probability-mass audit for categorical forecasts — force mass through a
mechanism filter so it can't be spread across answer-choice labels by default.

The failure this prevents (diagnosed from a real miss): a multi-outcome forecast
that assigns a non-trivial tail to a named-but-non-live option (a candidate with
no poll, no ballot path, no money) simply because the option appears in the
answer set. That is *outcome-space anchoring* — treating a listed outcome as a
live one. A senior forecast prices each outcome by the **path** that resolves it,
and any mass it cannot route through a named mechanism is **unearned**.

This module is pure logic: given the categorical distribution plus an optional
named path per outcome, it produces the audit table the forecaster (or the
commit gate) reasons over. The ledger does the IO and enforcement; keeping the
math here makes every threshold unit-testable.

Tail classification taxonomy (most→least live):
  live        — material mass with a strong, evidenced path.
  live_ish    — material mass with a mixed/weak path; defensible but watch it.
  remote_tail — possible but no live path; mass here is usually unearned.
  edge_case   — only resolves through a rule/definition edge, not normal dynamics.
  residual    — an explicit catch-all ("Other") bucket holding leftover mass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# Below this probability an outcome is negligible — no named path is demanded
# (you don't owe a mechanism for 0.1% of mass).
DEFAULT_MASS_THRESHOLD = 0.005  # 0.5%
# Evidence strengths, strongest first; "none" means a bare assertion.
EVIDENCE_STRENGTHS = ("strong", "mixed", "weak", "none")
# A residual/catch-all bucket may legitimately hold leftover mass without a
# specific path, but only up to this cap before it reads as tail padding.
DEFAULT_RESIDUAL_CAP = 0.05  # 5%
_RESIDUAL_NAMES = {"other", "others", "someone else", "field", "any other", "none of the above"}
# A residual bucket is often labelled "Other <something>" ("Other official
# candidates", "Other parties"), which exact-match missed — the exact class of
# hole that let unanchored mass ride on a named-looking residual. Prefix-match it.
_RESIDUAL_PREFIXES = ("other", "others", "any other", "someone else", "some other", "field", "none of the above")
# G1 default: a NAMED, non-residual outcome carrying more than this share of the
# mass must be backed by a cited base rate (outside view). Per-question tunable via
# the `named_outcome_anchor_share` threshold.
DEFAULT_NAMED_ANCHOR_SHARE = 0.10  # 10%


@dataclass
class OutcomePath:
    """One categorical outcome and the mechanism (if any) routed to it."""

    name: str
    probability: float
    path: str = ""  # the causal chain that resolves to this outcome
    classification: str = ""  # optional caller override; otherwise inferred
    evidence_strength: str = ""  # strong | mixed | weak | none
    base_rate: float | None = None  # G1: cited outside-view base rate for this outcome
    base_rate_source: str = ""      # G1: where the base rate came from (a reference class / prior result)

    @property
    def has_path(self) -> bool:
        return bool(self.path and self.path.strip())

    @property
    def is_residual(self) -> bool:
        if self.classification == "residual":
            return True
        name = self.name.strip().lower()
        if name in _RESIDUAL_NAMES:
            return True
        return any(name == prefix or name.startswith(prefix) for prefix in _RESIDUAL_PREFIXES)

    @property
    def is_anchored(self) -> bool:
        """G1: the outcome carries a cited outside-view anchor — a finite base rate
        AND a non-empty source. A path is a mechanism; an anchor is a NUMBER you can
        cite (the candidate's own prior vote shares), which is what a named tail owes."""
        return (
            self.base_rate is not None
            and isinstance(self.base_rate, (int, float))
            and math.isfinite(float(self.base_rate))
            and bool((self.base_rate_source or "").strip())
        )


@dataclass
class OutcomeVerdict:
    name: str
    probability: float
    classification: str
    has_path: bool
    evidence_strength: str
    path: str
    unearned: bool  # material mass with no named path (and not a capped residual)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "probability": self.probability,
            "classification": self.classification,
            "has_path": self.has_path,
            "evidence_strength": self.evidence_strength or "unspecified",
            "path": self.path,
            "unearned": self.unearned,
            "note": self.note,
        }


# The floor a no-path outcome gets under the sharper null model — "absent a
# named mechanism, an outcome starts near zero", per the agent's own rule.
DEFAULT_NULL_FLOOR = 0.003  # 0.3%
# How many times fatter the agent's no-path tail can be vs the null's before the
# richer model must explain the difference.
DEFAULT_NULL_TOLERANCE_RATIO = 2.0


@dataclass
class NullComparison:
    """The agent distribution vs a deliberately simple null model: outcomes
    WITH a named path keep their relative proportions; outcomes WITHOUT one are
    floored near zero. A richer model whose no-path tail is much fatter than the
    null's owes an explanation."""

    null_distribution: dict[str, float]
    agent_tail: float  # agent mass on no-path outcomes
    null_tail: float  # null mass on the same outcomes
    excess_tail: float  # agent_tail - null_tail
    ratio: float  # agent_tail / null_tail (inf when null_tail≈0 and agent_tail>0)
    floor: float
    within_tolerance: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "null_distribution": self.null_distribution,
            "agent_tail": self.agent_tail,
            "null_tail": self.null_tail,
            "excess_tail": self.excess_tail,
            "ratio": self.ratio,
            "floor": self.floor,
            "within_tolerance": self.within_tolerance,
        }


@dataclass
class TailAudit:
    verdicts: list[OutcomeVerdict]
    total_mass: float
    unearned_mass: float
    threshold: float
    residual_cap: float
    passes: bool
    issues: list[str] = field(default_factory=list)
    null_model: NullComparison | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passes": self.passes,
            "total_mass": self.total_mass,
            "unearned_mass": self.unearned_mass,
            "threshold": self.threshold,
            "residual_cap": self.residual_cap,
            "issues": list(self.issues),
            "outcomes": [v.to_dict() for v in self.verdicts],
            "null_model": self.null_model.to_dict() if self.null_model else None,
        }


def _infer_classification(outcome: OutcomePath, threshold: float, residual_cap: float) -> str:
    if outcome.classification in {"live", "live_ish", "remote_tail", "edge_case", "residual", "unpriced"}:
        return outcome.classification
    if outcome.is_residual:
        return "residual"
    if outcome.probability < threshold:
        # Negligible mass — a genuine remote tail; no mechanism owed.
        return "remote_tail"
    if not outcome.has_path:
        # Material mass with no mechanism named yet — not "remote", just
        # unpriced. The forecaster owes a path or must compress the mass.
        return "unpriced"
    strength = outcome.evidence_strength or "none"
    if strength == "strong":
        return "live"
    return "live_ish"  # has a path; mixed/weak/unspecified evidence — watch it


def compare_to_null(
    outcomes: list[OutcomePath],
    *,
    floor: float = DEFAULT_NULL_FLOOR,
    tolerance_ratio: float = DEFAULT_NULL_TOLERANCE_RATIO,
) -> NullComparison:
    """Build a sharper NULL model and compare the agent distribution to it.

    Null rule (the "deliberately simple model" the agent asks for): an outcome
    WITH a named path keeps its weight; an outcome WITHOUT one is floored near
    zero. The whole thing is renormalized to sum to 1. A residual catch-all
    bucket is treated as earned (it has an implicit "some other thing" path and
    is capped separately by the audit), so it is NOT part of the no-path tail.
    If the agent's mass on genuine no-path outcomes is much fatter than the
    null's, the richer model must justify the difference.
    """
    no_path = {o.name for o in outcomes if not o.has_path and not o.is_residual}
    raw: dict[str, float] = {}
    for o in outcomes:
        raw[o.name] = floor if (o.name in no_path) else max(float(o.probability), 0.0)
    total = sum(raw.values()) or 1.0
    null = {name: value / total for name, value in raw.items()}

    agent_tail = sum(float(o.probability) for o in outcomes if o.name in no_path)
    null_tail = sum(null[o.name] for o in outcomes if o.name in no_path)
    excess = agent_tail - null_tail
    if null_tail <= 1e-9:
        ratio = float("inf") if agent_tail > 1e-9 else 1.0
    else:
        ratio = agent_tail / null_tail
    within = ratio <= tolerance_ratio or agent_tail <= DEFAULT_MASS_THRESHOLD
    return NullComparison(
        null_distribution=null,
        agent_tail=agent_tail,
        null_tail=null_tail,
        excess_tail=excess,
        ratio=ratio,
        floor=floor,
        within_tolerance=within,
    )


def audit_outcomes(
    outcomes: list[OutcomePath],
    *,
    threshold: float = DEFAULT_MASS_THRESHOLD,
    residual_cap: float = DEFAULT_RESIDUAL_CAP,
) -> TailAudit:
    """Audit a categorical distribution for unearned tail mass.

    An outcome holds *unearned* mass when its probability is at or above
    ``threshold`` but it carries no named path — unless it is an explicit
    residual bucket within ``residual_cap``. ``passes`` is True only when no
    mass is unearned.
    """
    verdicts: list[OutcomeVerdict] = []
    issues: list[str] = []
    total_mass = 0.0
    unearned_mass = 0.0

    for outcome in outcomes:
        prob = float(outcome.probability)
        total_mass += prob
        classification = _infer_classification(outcome, threshold, residual_cap)
        unearned = False
        note = ""

        if prob >= threshold and not outcome.has_path:
            if outcome.is_residual:
                if prob > residual_cap:
                    unearned = True
                    unearned_mass += prob - residual_cap
                    note = (
                        f"residual bucket holds {prob:.1%} > {residual_cap:.0%} cap — "
                        "name the disruption path or compress it"
                    )
                else:
                    note = "residual bucket within cap"
            else:
                unearned = True
                unearned_mass += prob
                note = (
                    f"{prob:.1%} with no named path — outcome-space anchoring; "
                    "name the mechanism or move this mass onto supported outcomes"
                )
        elif prob >= threshold and outcome.has_path and (outcome.evidence_strength or "none") in {"weak", "none"}:
            note = "has a path but weak/unspecified evidence — justify the scale (why not 1/5 as likely?)"

        verdicts.append(
            OutcomeVerdict(
                name=outcome.name,
                probability=prob,
                classification=classification,
                has_path=outcome.has_path,
                evidence_strength=outcome.evidence_strength,
                path=outcome.path,
                unearned=unearned,
                note=note,
            )
        )

    if abs(total_mass - 1.0) > 0.02:
        issues.append(f"probabilities sum to {total_mass:.3f}, not ~1.0 — renormalize the distribution")
    if unearned_mass > threshold:
        issues.append(
            f"{unearned_mass:.1%} of probability is unearned tail mass (material outcomes with "
            "no named path) — compress it onto outcomes with a live mechanism"
        )

    null = compare_to_null(outcomes)
    if not null.within_tolerance:
        ratio_text = "∞" if null.ratio == float("inf") else f"{null.ratio:.1f}x"
        issues.append(
            f"no-path tail is {ratio_text} the sharper null model's "
            f"({null.agent_tail:.1%} vs {null.null_tail:.1%}) — the richer model must justify "
            "the extra mass or fall back to the simple one"
        )

    passes = unearned_mass <= threshold and not any(i.startswith("probabilities sum") for i in issues)
    return TailAudit(
        verdicts=verdicts,
        total_mass=total_mass,
        unearned_mass=unearned_mass,
        threshold=threshold,
        residual_cap=residual_cap,
        passes=passes,
        issues=issues,
        null_model=null,
    )


def audit_named_anchors(
    outcomes: list[OutcomePath],
    *,
    threshold: float = DEFAULT_NAMED_ANCHOR_SHARE,
) -> tuple[tuple[str, ...], float]:
    """G1 — the Binface gate. Return the NAMED, non-residual outcomes whose share
    exceeds ``threshold`` but which carry NO cited base rate (outside-view anchor),
    plus their total mass. Residual buckets are exempt — an unanchored tail belongs
    there, not on a named person. ``outcomes`` probabilities are fractions (0-1)."""
    offenders: list[str] = []
    mass = 0.0
    for o in outcomes:
        if o.is_residual:
            continue
        prob = float(o.probability)
        if prob <= threshold:
            continue
        if o.is_anchored:
            continue
        offenders.append(o.name)
        mass += prob
    return tuple(offenders), mass


def _coerce_base_rate(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def outcome_paths_from_inputs(
    distribution: dict[str, float],
    paths: dict[str, Any] | None,
) -> list[OutcomePath]:
    """Build OutcomePath rows from a categorical distribution dict plus an
    optional ``{outcome: path-info}`` map. Path-info may be a bare string (the
    path) or a dict with ``path`` / ``classification`` / ``evidence_strength`` /
    ``base_rate`` / ``base_rate_source`` (the G1 outside-view anchor).
    """
    paths = paths or {}
    rows: list[OutcomePath] = []
    for name, prob in distribution.items():
        info = paths.get(name)
        if isinstance(info, str):
            rows.append(OutcomePath(name=name, probability=float(prob), path=info))
        elif isinstance(info, dict):
            rows.append(
                OutcomePath(
                    name=name,
                    probability=float(prob),
                    path=str(info.get("path", "") or ""),
                    classification=str(info.get("classification", "") or ""),
                    evidence_strength=str(info.get("evidence_strength", "") or ""),
                    base_rate=_coerce_base_rate(info.get("base_rate")),
                    base_rate_source=str(info.get("base_rate_source", "") or ""),
                )
            )
        else:
            rows.append(OutcomePath(name=name, probability=float(prob)))
    return rows


def render_audit_table(audit: TailAudit) -> str:
    """Render the audit as the agent's probability-mass table — the artifact
    that makes unearned tail mass obvious at a glance."""
    rows = [
        f"{'outcome':<22} {'prob':>7}  {'class':<11} {'evidence':<9} path",
        f"{'-' * 22} {'-' * 7}  {'-' * 11} {'-' * 9} {'-' * 28}",
    ]
    for v in sorted(audit.verdicts, key=lambda x: -x.probability):
        flag = " !" if v.unearned else ""
        path = (v.path or ("residual" if v.classification == "residual" else "(no path)"))[:40]
        rows.append(
            f"{v.name[:22]:<22} {v.probability:>6.1%}  {v.classification:<11} "
            f"{(v.evidence_strength or '-'):<9} {path}{flag}"
        )
    rows.append("")
    verdict = "PASS" if audit.passes else "FAIL"
    rows.append(
        f"{verdict}: unearned tail mass {audit.unearned_mass:.1%} "
        f"(threshold {audit.threshold:.1%}); total mass {audit.total_mass:.3f}"
    )
    if audit.null_model is not None:
        nm = audit.null_model
        ratio_text = "∞" if nm.ratio == float("inf") else f"{nm.ratio:.1f}x"
        rows.append(
            f"null model: no-path tail {nm.agent_tail:.1%} vs simple-null {nm.null_tail:.1%} "
            f"({ratio_text})"
        )
    for issue in audit.issues:
        rows.append(f"  - {issue}")
    return "\n".join(rows)
