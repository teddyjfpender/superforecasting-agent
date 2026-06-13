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


@dataclass
class OutcomePath:
    """One categorical outcome and the mechanism (if any) routed to it."""

    name: str
    probability: float
    path: str = ""  # the causal chain that resolves to this outcome
    classification: str = ""  # optional caller override; otherwise inferred
    evidence_strength: str = ""  # strong | mixed | weak | none

    @property
    def has_path(self) -> bool:
        return bool(self.path and self.path.strip())

    @property
    def is_residual(self) -> bool:
        return self.classification == "residual" or self.name.strip().lower() in _RESIDUAL_NAMES


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


@dataclass
class TailAudit:
    verdicts: list[OutcomeVerdict]
    total_mass: float
    unearned_mass: float
    threshold: float
    residual_cap: float
    passes: bool
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passes": self.passes,
            "total_mass": self.total_mass,
            "unearned_mass": self.unearned_mass,
            "threshold": self.threshold,
            "residual_cap": self.residual_cap,
            "issues": list(self.issues),
            "outcomes": [v.to_dict() for v in self.verdicts],
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

    passes = unearned_mass <= threshold and not any(i.startswith("probabilities sum") for i in issues)
    return TailAudit(
        verdicts=verdicts,
        total_mass=total_mass,
        unearned_mass=unearned_mass,
        threshold=threshold,
        residual_cap=residual_cap,
        passes=passes,
        issues=issues,
    )


def outcome_paths_from_inputs(
    distribution: dict[str, float],
    paths: dict[str, Any] | None,
) -> list[OutcomePath]:
    """Build OutcomePath rows from a categorical distribution dict plus an
    optional ``{outcome: path-info}`` map. Path-info may be a bare string (the
    path) or a dict with ``path`` / ``classification`` / ``evidence_strength``.
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
    for issue in audit.issues:
        rows.append(f"  - {issue}")
    return "\n".join(rows)
