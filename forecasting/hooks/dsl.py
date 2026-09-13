"""User-defined rule DSL — a SAFE, declarative rule language.

Rules are authored as data (YAML/JSON), never code: a rule's ``check`` is a
declarative predicate over a FIXED vocabulary of saturation signals with a small
set of operators. This is the safety property — a config file can never execute
arbitrary Python (no eval), every rule is statically validatable at author time
(unknown signals are caught and the valid list is shown), and a rule is a pure
function of the HookContext (so it can be dry-run / previewed against the ledger).

A user rule compiles to the same ``SimpleRule`` the built-ins use, so the engine
treats them uniformly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from forecasting.hooks.builtins import BUILTIN_RULE_IDS
from forecasting.hooks.spec import _REMEDIATION_KIND as _HINT_KIND
from forecasting.hooks.spec import (
    REMEDIATION_ACTIONS as _REMEDIATION_ACTIONS,  # single source of truth
)
from forecasting.hooks.spec import (
    Category,
    HookContext,
    RemediationDescriptor,
    Severity,
    SimpleRule,
)

# ── signal vocabulary ─────────────────────────────────────────────────────────
# name -> (accessor(ctx) -> value, kind, one-line doc). This is the entire
# surface a user rule can test; `forecast hooks explain` prints it verbatim.
_SIGNALS: dict[str, tuple[Callable[[HookContext], Any], str, str]] = {
    "components.count": (
        lambda c: c.component_count,
        "number",
        "Number of pooled drivers in ensemble_components.",
    ),
    "components.present": (
        lambda c: c.has_components,
        "bool",
        "Whether any ensemble_components are present.",
    ),
    "evidence.count": (
        lambda c: c.evidence_count,
        "number",
        "Total evidence items on the question.",
    ),
    "reasons.up_present": (
        lambda c: c.has_reasons_up,
        "bool",
        "Whether reasons_up is populated.",
    ),
    "reasons.down_present": (
        lambda c: c.has_reasons_down,
        "bool",
        "Whether reasons_down is populated.",
    ),
    "reasons.complete": (
        lambda c: c.has_reasons_up and c.has_reasons_down and c.has_change_my_mind,
        "bool",
        "Whether reasons_up + reasons_down + change_my_mind are ALL present.",
    ),
    "reference_classes.count": (
        lambda c: c.reference_class_count,
        "number",
        "Number of reference classes (outside view).",
    ),
    "panel.linked": (
        lambda c: c.panel_linked,
        "bool",
        "Whether a deliberative panel run is linked (or skip recorded).",
    ),
    "panel.run_count": (
        lambda c: c.panel_run_count,
        "number",
        "Historical panel runs for the question.",
    ),
    "evidence.stale_acknowledged_unexplained": (
        lambda c: c.stale_evidence_acknowledged,
        "bool",
        "Stale evidence was acknowledged to skip the freshness gate WITHOUT a recorded reason.",
    ),
    "watched_sources.count": (
        lambda c: c.watched_source_count,
        "number",
        "Active watched sources on the question.",
    ),
    "readiness.score": (
        lambda c: c.readiness_score if c.readiness_score is not None else 100.0,
        "number",
        "Machine-readiness (Desk RDY) composite 0..100; 100 when not computed so a null score never trips a floor.",
    ),
    "decision.ready": (
        lambda c: not c.decision_gaps,
        "bool",
        "Whether the decision card has no missing fields.",
    ),
    "decision.gap_count": (
        lambda c: len(c.decision_gaps),
        "number",
        "Count of missing decision-card fields.",
    ),
    "tail.unearned_mass": (
        lambda c: c.tail_unearned_mass,
        "number",
        "Categorical: fraction of mass on outcomes with no named path (0..1).",
    ),
    "tail.passes": (
        lambda c: True if c.tail_audit_passes is None else c.tail_audit_passes,
        "bool",
        "Categorical tail audit passes (no unearned mass).",
    ),
    # G1 — distribution-tail base rates (the Binface gate)
    "tail.named_unanchored_mass": (
        lambda c: c.share_named_unanchored_mass,
        "number",
        "Fraction of mass on named, non-residual outcomes above the anchor-share threshold with NO cited base rate (0..1).",
    ),
    "tail.named_unanchored_count": (
        lambda c: len(c.share_named_unanchored),
        "number",
        "Count of named, non-residual outcomes above the anchor-share threshold with no cited base rate.",
    ),
    "outcome.candidate_share": (
        lambda c: c.is_candidate_share,
        "bool",
        "The payload is a candidate-share (vote-share) PMF: named numeric shares summing to ~1 / ~100.",
    ),
    # G2 — per-candidate interval coherence
    "intervals.candidate_coverage": (
        lambda c: (
            c.candidate_interval_coverage
            if c.candidate_interval_coverage is not None
            else 1.0
        ),
        "number",
        "Named non-residual candidates with a per-candidate interval / total (0..1); 1.0 when not a share board.",
    ),
    "intervals.candidate_coherent": (
        lambda c: c.candidate_intervals_coherent,
        "bool",
        "Per-candidate vote-share intervals (when present) are coherent (finite p05<=median<=p95, median near share, in bounds).",
    ),
    "style.clean": (
        lambda c: c.style_clean,
        "bool",
        "Prose is house-clean (no em-dashes / formatting issues).",
    ),
    "calibration.lessons_unapplied": (
        lambda c: c.active_lessons_unapplied,
        "number",
        "Active calibration lessons not applied to this commit.",
    ),
    "confidence.winner_prob": (
        lambda c: (
            c.committed_winner_prob if c.committed_winner_prob is not None else 0.0
        ),
        "number",
        "Committed winner probability: binary p, or the leading categorical outcome's mass.",
    ),
    "links.derived_child_present": (
        lambda c: c.derived_child_present,
        "bool",
        "A derived component child forecast (e.g. a vote-share model linked component_of) is present, live, and has a current snapshot.",
    ),
    "outcome.machine_scoreable": (
        lambda c: c.machine_scoreable,
        "bool",
        "A candidate-share (vote-share) forecast carries numeric shares keyed to the question's candidates, so it can be machine-scored (born scoreable).",
    ),
    # v2 — output / uncertainty structure
    "distribution.renderable": (
        lambda c: c.distribution_renderable,
        "bool",
        "Distribution has a central tendency + >=1 ordered interval the charts can draw.",
    ),
    "bounds.well_formed": (
        lambda c: c.bounds_well_formed,
        "bool",
        "Intervals are ordered, nested (ci50 in ci90), finite, non-degenerate.",
    ),
    "bounds.in_range": (
        lambda c: c.bounds_in_range,
        "bool",
        "All interval bounds sit within the question's OutcomeSpace bounds.",
    ),
    "bounds.width_ratio": (
        lambda c: c.interval_width_ratio if c.interval_width_ratio is not None else 0.0,
        "number",
        "Widest interval width as a fraction of the question range (absurd if large).",
    ),
    # v2 — confidence lean
    "confidence.sharpness": (
        lambda c: c.sharpness if c.sharpness is not None else 1.0,
        "number",
        "Distance from maximum hedging: 0 = at 0.5 / flat PMF, 1 = committed.",
    ),
    "confidence.under_confident": (
        lambda c: c.calibration_under_confident,
        "bool",
        "Ledger measured chronic under-confidence for this scope.",
    ),
    "tails.null_excess": (
        lambda c: c.tail_null_excess,
        "number",
        "Probability mass above the null-model tail (overweighting no-path outcomes).",
    ),
    # v2 — quorum / panel participation
    "panel.perspective_count": (
        lambda c: c.panel_perspective_count,
        "number",
        "Distinct perspectives/personas on the linked panel run.",
    ),
    "quorum.model_count": (
        lambda c: c.quorum_model_count,
        "number",
        "Distinct models in the linked quorum run.",
    ),
    "quorum.judged": (
        lambda c: c.quorum_judged,
        "bool",
        "The quorum run carries a judge synthesis (consensus + contradictions).",
    ),
    # v2 — reasoning composition
    "reasoning.method_count": (
        lambda c: c.reasoning_method_count,
        "number",
        "Number of distinct declared reasoning methods.",
    ),
    # v3 — thesis / factor aggregate freshness
    "aggregate.stale": (
        lambda c: c.aggregate_stale,
        "bool",
        "Thesis/factor aggregate is stale vs its members (a member moved since the last aggregate).",
    ),
    "members.newer_count": (
        lambda c: c.newer_member_count,
        "number",
        "Count of members whose current snapshot is newer than the aggregate.",
    ),
    # v3 — VOI-directed research adequacy
    "research.adequate": (
        lambda c: c.research_adequate,
        "bool",
        "Research covers the levers that would move the forecast (reference class, evidence floor, independent + disconfirming + fresh evidence, watched triggers).",
    ),
    "research.adequacy_score": (
        lambda c: (
            c.research_adequacy_score
            if c.research_adequacy_score is not None
            else 100.0
        ),
        "number",
        "Research-adequacy score 0..100 from the deterministic research_audit checks.",
    ),
    # P3 gates — cruxes (G7), market anchor (G8), cadence (G5)
    "cruxes.count": (
        lambda c: c.crux_count,
        "number",
        "Registered cruxes on the question (question_cruxes rows) — the variables that would most change the call.",
    ),
    "market.linked": (
        lambda c: c.has_linked_market,
        "bool",
        "The question watches a market source (a market-prefixed component, an active watched market source, or a market baseline comparison).",
    ),
    "market.comparison_recorded": (
        lambda c: c.market_comparison_recorded,
        "bool",
        "The commit records the market price + deviation (a linked quorum panel run's market_anchor, or metadata.market_comparison).",
    ),
    "cadence.overdue_ratio": (
        lambda c: c.cadence_overdue_ratio,
        "number",
        "age(current snapshot) / review cadence period; >1 is past cadence (SWEEP-SIDE only; 0.0 at commit time).",
    ),
}

SIGNAL_NAMES: tuple[str, ...] = tuple(sorted(_SIGNALS))

_NUMERIC_OPS = {">", ">=", "<", "<=", "==", "!="}
_BOOL_OPS = {"is_true", "is_false", "==", "!="}
_SET_OPS = {"in", "not_in"}
ALL_OPS = _NUMERIC_OPS | _BOOL_OPS | _SET_OPS

_CATEGORIES = {c.value for c in Category}
_MAX_DEPTH = 5


def signal_doc(name: str) -> str | None:
    entry = _SIGNALS.get(name)
    return entry[2] if entry else None


def signal_glossary() -> list[tuple[str, str, str]]:
    """(name, kind, doc) for every signal — for `forecast hooks explain`."""
    return [(n, _SIGNALS[n][1], _SIGNALS[n][2]) for n in SIGNAL_NAMES]


@dataclass(frozen=True)
class RuleIssue:
    field: str
    severity: str  # "error" (reject) | "warn" (save+flag) | "info" (teach)
    message: str
    fix: str = ""


@dataclass(frozen=True)
class RuleSpec:
    id: str
    description: str = ""
    category: str = "custom"
    severity: str = "warn"
    applies_to: dict[str, Any] = field(default_factory=dict)
    check: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    remediation_hint: str = "none"

    _parse_issues: tuple[RuleIssue, ...] = field(default=(), repr=False)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "RuleSpec":
        if not isinstance(d, dict):
            return RuleSpec(
                id="",
                _parse_issues=(
                    RuleIssue(
                        "rule",
                        "error",
                        "rule must be an object",
                        "provide a rule mapping",
                    ),
                ),
            )
        issues = []
        values: dict[str, Any] = {}
        for name, default in (
            ("id", ""),
            ("description", ""),
            ("category", "custom"),
            ("severity", "warn"),
            ("message", ""),
            ("remediation_hint", "none"),
        ):
            value = d.get(name)
            if value is None:
                value = default
            if not isinstance(value, str):
                issues.append(RuleIssue(name, "error", f"{name} must be a string"))
                value = default
            values[name] = value
        for name in ("applies_to", "check"):
            value = d.get(name)
            if value is None:
                value = {}
            if not isinstance(value, dict):
                issues.append(RuleIssue(name, "error", f"{name} must be an object"))
                value = {}
            values[name] = value
        values["id"] = values["id"].strip()
        values["severity"] = values["severity"].lower()
        return RuleSpec(**values, _parse_issues=tuple(issues))


def _validate_predicate(node: Any, issues: list[RuleIssue], depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        issues.append(
            RuleIssue(
                "check",
                "error",
                f"predicate nesting exceeds max depth {_MAX_DEPTH}",
                "flatten the conditions",
            )
        )
        return
    if not isinstance(node, dict):
        issues.append(
            RuleIssue(
                "check",
                "error",
                "each predicate must be an object",
                "use {signal, op, value} or {all:[...]}",
            )
        )
        return
    combiners = [name for name in ("all", "any", "not") if name in node]
    if len(combiners) > 1 or (
        combiners and any(key in node for key in ("signal", "op", "value"))
    ):
        issues.append(
            RuleIssue("check", "error", "predicate must use one combiner or one leaf")
        )
        return
    for combiner in ("all", "any"):
        if combiner in node:
            branches = node[combiner]
            if not isinstance(branches, list) or not branches:
                issues.append(
                    RuleIssue(
                        "check",
                        "error",
                        f"`{combiner}` must be a non-empty list",
                        f"add conditions under `{combiner}`",
                    )
                )
                return
            for b in branches:
                _validate_predicate(b, issues, depth + 1)
            return
    if "not" in node:
        _validate_predicate(node["not"], issues, depth + 1)
        return
    # leaf
    signal = node.get("signal")
    op = node.get("op")
    if not isinstance(signal, str) or signal not in _SIGNALS:
        issues.append(
            RuleIssue(
                "check",
                "error",
                f"unknown signal {signal!r}",
                "valid signals: " + ", ".join(SIGNAL_NAMES),
            )
        )
        return
    kind = _SIGNALS[signal][1]
    if not isinstance(op, str) or op not in ALL_OPS:
        issues.append(
            RuleIssue(
                "check",
                "error",
                f"unknown operator {op!r}",
                "operators: " + ", ".join(sorted(ALL_OPS)),
            )
        )
        return
    if kind == "bool" and op not in _BOOL_OPS:
        issues.append(
            RuleIssue(
                "check",
                "error",
                f"operator {op!r} is invalid for boolean signal {signal!r}",
                "use is_true / is_false / == / !=",
            )
        )
    if kind == "number" and op in (_BOOL_OPS - {"==", "!="}):
        issues.append(
            RuleIssue(
                "check",
                "error",
                f"operator {op!r} is invalid for numeric signal {signal!r}",
                "use a comparison (>, >=, <, <=, ==, !=)",
            )
        )
    if op in _SET_OPS and not isinstance(node.get("value"), list):
        issues.append(
            RuleIssue(
                "check",
                "error",
                f"operator {op!r} needs a list value",
                "value: [a, b, c]",
            )
        )
    if kind == "number" and op in _NUMERIC_OPS:
        value = node.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            issues.append(
                RuleIssue(
                    "check",
                    "error",
                    f"{signal!r} {op} needs a finite numeric value",
                    "value: 3",
                )
            )
    if (
        kind == "bool"
        and op in {"==", "!="}
        and not isinstance(node.get("value"), bool)
    ):
        issues.append(
            RuleIssue(
                "check",
                "error",
                f"{signal!r} {op} needs a boolean value",
                "value: true",
            )
        )


def validate_rule(
    spec: RuleSpec, *, known_ids: set[str] | None = None
) -> list[RuleIssue]:
    """Author-time validation: hard errors reject the rule; warns save+flag; infos
    teach. Designed so the error message itself documents the fix (e.g. an unknown
    signal lists every valid signal)."""
    if spec._parse_issues:
        return list(spec._parse_issues)
    issues: list[RuleIssue] = []
    known_ids = known_ids or set()

    if not spec.id:
        issues.append(
            RuleIssue(
                "id",
                "error",
                "rule id is required",
                "give the rule a short unique slug",
            )
        )
    elif spec.id in BUILTIN_RULE_IDS:
        issues.append(
            RuleIssue(
                "id",
                "error",
                f"id {spec.id!r} collides with a built-in rule",
                "choose a different slug",
            )
        )
    elif spec.id in known_ids:
        issues.append(
            RuleIssue(
                "id", "error", f"duplicate rule id {spec.id!r}", "ids must be unique"
            )
        )

    if spec.severity not in ("off", "warn", "error"):
        issues.append(
            RuleIssue(
                "severity",
                "error",
                f"severity must be off|warn|error, got {spec.severity!r}",
                "",
            )
        )
    if spec.category not in _CATEGORIES:
        issues.append(
            RuleIssue(
                "category",
                "warn",
                f"unknown category {spec.category!r}; treated as custom",
                "categories: " + ", ".join(sorted(_CATEGORIES)),
            )
        )
    if spec.remediation_hint not in _REMEDIATION_ACTIONS:
        issues.append(
            RuleIssue(
                "remediation_hint",
                "error",
                f"unknown remediation_hint {spec.remediation_hint!r}",
                "one of: " + ", ".join(_REMEDIATION_ACTIONS),
            )
        )

    # applies_to hardening (§4.5): _applies only honors a fixed set of keys, so a
    # hand-written filter on an unknown key (e.g. `question_type:` instead of
    # `outcome_type:`) silently matches EVERYTHING — the documented silent-kill gotcha.
    # WARN (save + flag) listing the valid keys so the author fixes it deliberately.
    _VALID_APPLIES_KEYS = ("origin", "impact", "domain", "outcome_type")
    for key in spec.applies_to or {}:
        if key not in _VALID_APPLIES_KEYS:
            issues.append(
                RuleIssue(
                    "applies_to",
                    "warn",
                    f"unknown applies_to key {key!r} is IGNORED — the rule will match every commit's scope on it",
                    "valid applies_to keys: " + ", ".join(_VALID_APPLIES_KEYS),
                )
            )

    if not spec.check:
        issues.append(
            RuleIssue(
                "check",
                "error",
                "a rule needs a check predicate",
                "add {signal, op, value}",
            )
        )
    else:
        _validate_predicate(spec.check, issues)

    # Teach: a blocking rule with no auto-fix path means the forecaster must fix it
    # by hand — warn so the author chooses deliberately.
    if spec.severity == "error" and spec.remediation_hint == "none":
        issues.append(
            RuleIssue(
                "remediation_hint",
                "warn",
                "severity=error with remediation_hint=none will BLOCK commits with no auto-fix path",
                "set a remediation_hint, or use severity=warn",
            )
        )
    return issues


def _eval_leaf(node: dict, ctx: HookContext) -> bool:
    accessor = _SIGNALS[node["signal"]][0]
    actual = accessor(ctx)
    op = node["op"]
    value = node.get("value")
    if op == "is_true":
        return bool(actual)
    if op == "is_false":
        return not bool(actual)
    if op == "==":
        return actual == value
    if op == "!=":
        return actual != value
    if op == "in":
        return actual in (value or [])
    if op == "not_in":
        return actual not in (value or [])
    try:
        if op == ">":
            return actual > value
        if op == ">=":
            return actual >= value
        if op == "<":
            return actual < value
        if op == "<=":
            return actual <= value
    except TypeError:
        return False
    return False


def evaluate_predicate(node: Any, ctx: HookContext) -> bool:
    if not isinstance(node, dict):
        return True
    if "all" in node:
        return all(evaluate_predicate(b, ctx) for b in node["all"])
    if "any" in node:
        return any(evaluate_predicate(b, ctx) for b in node["any"])
    if "not" in node:
        return not evaluate_predicate(node["not"], ctx)
    return _eval_leaf(node, ctx)


def _applies(spec: RuleSpec) -> Callable[[HookContext], bool]:
    f = spec.applies_to or {}

    def applies(ctx: HookContext) -> bool:
        if "origin" in f and ctx.forecast_origin not in f["origin"]:
            return False
        if "impact" in f and (ctx.impact or "").lower() not in [
            str(x).lower() for x in f["impact"]
        ]:
            return False
        if "domain" in f and (ctx.domain or "") not in f["domain"]:
            return False
        if "outcome_type" in f and (ctx.outcome_type or "") not in f["outcome_type"]:
            return False
        return True

    return applies


# Single source of truth (includes the v2 actions fix_distribution/sharpen/
# run_quorum/tag_reasoning); kept in sync with the validator's REMEDIATION_ACTIONS.


def compile_rule(spec: RuleSpec) -> SimpleRule:
    """Turn a validated RuleSpec into a SimpleRule the engine evaluates. A rule
    PASSES when its check predicate is True."""
    errors = [issue for issue in validate_rule(spec) if issue.severity == "error"]
    if errors:
        raise ValueError(
            f"invalid rule {spec.id!r}: {errors[0].field}: {errors[0].message}"
        )
    try:
        category = Category(spec.category)
    except ValueError:
        category = Category.CUSTOM
    default_sev = (
        Severity(spec.severity)
        if spec.severity in ("off", "warn", "error")
        else Severity.WARN
    )
    msg = spec.message or f"user rule {spec.id} failed"
    hint = (
        spec.remediation_hint
        if spec.remediation_hint in _REMEDIATION_ACTIONS
        else "none"
    )

    def check_fn(ctx: HookContext):
        if evaluate_predicate(spec.check, ctx):
            return True, "", {}
        # interpolate a couple of common signals into the message for context
        rendered = msg
        for name, (acc, _kind, _doc) in _SIGNALS.items():
            token = "{" + name + "}"
            if token in rendered:
                try:
                    rendered = rendered.replace(token, str(acc(ctx)))
                except Exception:
                    pass
        return False, rendered, {"rule": spec.id}

    def remediation_fn(_ctx: HookContext):
        if hint == "none":
            return None
        kind, stage = _HINT_KIND[hint]
        return RemediationDescriptor(kind, hint, msg, target_stage=stage)

    return SimpleRule(
        id=spec.id,
        category=category,
        default_severity=default_sev,
        weight=8.0,
        check_fn=check_fn,
        applies_fn=_applies(spec),
        remediation_fn=remediation_fn,
    )
