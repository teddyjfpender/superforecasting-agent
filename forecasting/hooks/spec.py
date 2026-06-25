"""Forecast Hooks — the rule model + context + report dataclasses.

A "hook" is a commit-time check that tests a SIGNAL about a forecast and either
passes, warns, or blocks. The engine evaluates a set of rules against a
``HookContext`` (assembled ONCE per commit so rules stay pure + cheap — no IO in
``check``) and returns a ``SaturationReport``: a 0-100 saturation score plus a
per-rule verdict table. ``create_snapshot`` is the single fail-closed chokepoint
that runs the engine; nothing under-saturated ever persists.

This module is stdlib-only (mirroring the dependency-light discipline of
``forecasting/tail_audit.py``): the ledger does IO, the engine does logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from forecasting.models import ValidationError


class Severity(str, Enum):
    OFF = "off"      # not evaluated
    WARN = "warn"    # evaluated + scored + surfaced, does NOT block
    ERROR = "error"  # evaluated + scored + BLOCKS the commit

    @property
    def blocks(self) -> bool:
        return self is Severity.ERROR


class Category(str, Enum):
    STYLE = "style"
    SATURATION = "saturation"
    CALIBRATION = "calibration"
    DECISION = "decision"
    OUTPUT = "output"
    QUORUM = "quorum"
    CONFIDENCE = "confidence"
    REASONING = "reasoning"
    CUSTOM = "custom"


# Remediation actions the engine knows how to drive (Phase 2/3 wire the executor).
REMEDIATION_ACTIONS = (
    "collect_evidence",
    "run_panel",
    "decompose",
    "compress_tails",
    "sanitize_style",
    "fix_distribution",
    "sharpen",
    "run_quorum",
    "tag_reasoning",
    "run_aggregate",
    "add_reference_class",
    "none",
)


@dataclass(frozen=True)
class RemediationDescriptor:
    """How a failing rule can be auto-fixed. ``mechanical`` runs inline anywhere
    (no LLM); ``agentic`` needs reasoning/research and maps to a protocol stage."""

    kind: str            # "mechanical" | "agentic"
    action: str          # one of REMEDIATION_ACTIONS
    directive: str       # natural-language instruction for an agent
    target_stage: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookContext:
    """Everything the rules need, assembled once. Holds the CANDIDATE commit plus
    the prior live state and the precomputed read-only saturation signals. Rules
    read this and nothing else (no ledger handle in ``check``)."""

    question_id: str
    forecast_origin: str
    event: str                       # "update" | "refresh" | "autopilot" | "aggregate" | "finish_sweep" | "lint"
    impact: str | None = None        # "high" | "medium" | "low" | None
    has_prior: bool = False          # question.current_forecast_id is set
    is_categorical: bool = False

    # candidate-commit presence signals (bools keep rules trivially pure)
    has_reasons_up: bool = False
    has_reasons_down: bool = False
    has_change_my_mind: bool = False
    has_components: bool = False
    component_count: int = 0
    has_citations: bool = False
    panel_linked: bool = False       # panel_run_ref set on this commit
    panel_skipped: bool = False      # panel_skipped_reason set
    panel_run_count: int = 0

    # evidence / freshness
    evidence_count: int = 0
    fresh_evidence_count: int = 0
    has_fresh_evidence: bool = True  # newer than prior (only meaningful when has_prior)
    acknowledge_stale_evidence: bool = False
    stale_evidence_acknowledged: bool = False  # acknowledged WITHOUT a stale_evidence_reason
    stale_evidence_count: int = 0
    prior_forecast_id: str | None = None   # for the fresh-evidence message
    prior_as_of: str | None = None

    # decomposition / decision / calibration
    reference_class_count: int = 0
    watched_source_count: int = 0
    decision_gaps: tuple[str, ...] = ()
    active_lessons_unapplied: int = 0
    calibration_bias_status: str | None = None
    # committed winner probability (binary p / leading categorical mass) + whether a
    # derived vote-share child forecast is linked — so a lesson can require a >X%
    # winner call to be backed by a vote-share model (the NY-12 structural lesson).
    committed_winner_prob: float | None = None
    derived_child_present: bool = False
    # Whether a candidate-share (vote-share) forecast is born machine-scoreable —
    # it carries numeric shares keyed to the question's candidates (so the vector
    # scorer can grade it, not the agent by hand). True for non-share questions.
    machine_scoreable: bool = True

    # tail audit (categorical)
    tail_audit_passes: bool | None = None
    tail_unearned_mass: float = 0.0
    tail_offenders: tuple[str, ...] = ()

    # style
    style_clean: bool = True
    style_offending_fields: tuple[str, ...] = ()

    # output / uncertainty structure (v2)
    is_distribution: bool = False          # payload parses as a continuous distribution
    distribution_renderable: bool = True   # central tendency + >=1 ordered interval
    bounds_well_formed: bool = True         # ordered + nested + finite + non-degenerate
    bounds_in_range: bool = True            # within OutcomeSpace bounds
    interval_width_ratio: float | None = None  # widest interval / question range
    has_units: bool = True
    distribution_issues: tuple[str, ...] = ()

    # confidence lean (v2)
    sharpness: float | None = None          # 0 = max hedge (0.5 binary / flat PMF), 1 = committed
    categorical_top_mass: float | None = None
    calibration_under_confident: bool = False  # ledger measured chronic under-confidence for the scope
    uncertainty_justified: bool = False     # explicit "genuine maximum uncertainty" escape recorded
    tail_null_excess: float = 0.0           # mass above the null-model tail (overweighting no-path outcomes)

    # quorum / panel participation (v2)
    is_quorum: bool = False
    panel_perspective_count: int = 0
    quorum_model_count: int = 0
    quorum_judged: bool = False

    # reasoning composition (v2)
    reasoning_methods: tuple[str, ...] = ()
    required_reasoning_methods: tuple[str, ...] = ()   # resolved from the profile
    min_reasoning_methods: int = 0

    # thesis / factor aggregate freshness (v3): is the parent aggregate stale vs
    # its members (a member moved after the last aggregate)? Surfaces the desk
    # badge + cron pickup; the member-commit cascade keeps it fresh by default.
    is_thesis_or_factor: bool = False
    aggregate_stale: bool = False
    newer_member_count: int = 0

    # domain / outcome type for user-rule applies_to filters
    domain: str | None = None
    outcome_type: str | None = None

    @property
    def reasoning_method_count(self) -> int:
        return len(self.reasoning_methods)

    @property
    def is_live(self) -> bool:
        return self.forecast_origin == "live"

    @property
    def high_impact(self) -> bool:
        return (self.impact or "").strip().lower() == "high"


@dataclass(frozen=True)
class Verdict:
    rule_id: str
    category: Category
    severity: Severity
    passed: bool
    score_penalty: float = 0.0       # points off the 0-100 score when failed
    message: str = ""                # human-facing refusal/advice (byte-identical to legacy gate when blocking)
    remediation: RemediationDescriptor | None = None
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule_id": self.rule_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "passed": self.passed,
        }
        if not self.passed:
            out["message"] = self.message
            if self.remediation is not None:
                out["remediation"] = self.remediation.action
            if self.facts:
                out["facts"] = self.facts
        return out


@dataclass
class SaturationReport:
    question_id: str
    event: str
    score: float                     # 0..100
    passed: bool                     # no ERROR-severity verdict failed
    verdicts: list[Verdict]

    def blocking_failures(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.severity.blocks and not v.passed]

    def warnings(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.severity is Severity.WARN and not v.passed]

    def remediations(self) -> list[RemediationDescriptor]:
        seen: set[str] = set()
        out: list[RemediationDescriptor] = []
        for v in self.verdicts:
            if v.passed or v.remediation is None or v.remediation.action == "none":
                continue
            key = v.remediation.action
            if key not in seen:
                seen.add(key)
                out.append(v.remediation)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "passed": self.passed,
            "event": self.event,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "blocking": [v.rule_id for v in self.blocking_failures()],
            "warnings": [v.rule_id for v in self.warnings()],
        }


# A Rule is a small bundle of metadata + an applies() scope predicate + a pure
# check(). Built-ins are constructed via SimpleRule; user rules compile to the
# same shape in Phase 5.
@dataclass(frozen=True)
class SimpleRule:
    id: str
    category: Category
    default_severity: Severity
    weight: float
    check_fn: Callable[[HookContext], tuple[bool, str, dict[str, Any]]]
    applies_fn: Callable[[HookContext], bool] = lambda ctx: True
    remediation_fn: Callable[[HookContext], RemediationDescriptor | None] = lambda ctx: None

    def applies(self, ctx: HookContext) -> bool:
        return self.applies_fn(ctx)

    def evaluate(self, ctx: HookContext, severity: Severity) -> Verdict:
        passed, message, facts = self.check_fn(ctx)
        return Verdict(
            rule_id=self.id,
            category=self.category,
            severity=severity,
            passed=passed,
            score_penalty=0.0 if passed else self.weight,
            message="" if passed else message,
            remediation=None if passed else self.remediation_fn(ctx),
            facts={} if passed else facts,
        )


class SaturationBlocked(ValidationError):
    """A commit refused because it failed a blocking (error-severity) hook. Carries
    the full report so the interactive tool can hand the agent a precise to-do list
    and the programmatic path can record/escalate it. Subclasses ValidationError so
    existing ``except ValidationError`` / ``pytest.raises(ValidationError)`` keep
    working unchanged (the message is byte-identical to the legacy gate)."""

    def __init__(self, report: SaturationReport):
        self.report = report
        blockers = report.blocking_failures()
        super().__init__(blockers[0].message if blockers else "forecast failed saturation hooks")


# Map of remediation action -> (kind, default protocol stage), so an inline gate
# can attach the right remediation to its single-rule block.
_REMEDIATION_KIND = {
    "collect_evidence": ("agentic", "research"),
    "run_panel": ("agentic", "model"),
    "decompose": ("agentic", "update"),
    "compress_tails": ("agentic", "update"),
    "sanitize_style": ("mechanical", None),
    "fix_distribution": ("mechanical", None),
    "sharpen": ("agentic", "update"),
    "run_quorum": ("agentic", "model"),
    "tag_reasoning": ("agentic", "update"),
    "run_aggregate": ("mechanical", None),
    "add_reference_class": ("agentic", "research"),
    "none": ("mechanical", None),
}


def single_block(
    rule_id: str,
    message: str,
    *,
    action: str = "none",
    category: Category = Category.SATURATION,
    weight: float = 15.0,
    facts: dict[str, Any] | None = None,
) -> SaturationBlocked:
    """Build a SaturationBlocked carrying a one-verdict report for an inline gate.
    The message is byte-identical to the legacy ValidationError, so tests that
    match on the substring keep passing; the report adds the structured rule id +
    remediation the interactive tool / programmatic escalator consume."""
    kind, stage = _REMEDIATION_KIND.get(action, ("agentic", None))
    rem = None if action == "none" else RemediationDescriptor(kind, action, message, target_stage=stage)
    verdict = Verdict(
        rule_id=rule_id,
        category=category,
        severity=Severity.ERROR,
        passed=False,
        score_penalty=weight,
        message=message,
        remediation=rem,
        facts=facts or {},
    )
    report = SaturationReport(question_id="", event="update", score=0.0, passed=False, verdicts=[verdict])
    return SaturationBlocked(report)
