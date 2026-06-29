"""Typed staging object for forecast-question onboarding/curation.

A ``QuestionSpec`` is the plan-before-commit object the agent fills in while
curating a new forecast question with the user (the forecasting analogue of
Claude Code's plan/clarify loop). It mirrors-and-extends ``create_question``'s
arguments plus the attach-after-creation payloads (watched sources, reference
classes) and a few onboarding-only toggles, validates itself against the same
rules the ledger enforces, and commits in one fan-out so a question is *born*
with sources to refresh on re-run.

The module deliberately depends only on :mod:`forecasting.models` at import
time; the ledger is passed in to :meth:`QuestionSpec.commit`, so there is no
import cycle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from forecasting.models import (
    OUTCOME_TYPES,
    TRIGGER_OPERATORS,
    OutcomeSpace,
    ValidationError,
    normalize_update_triggers,
)

OnboardingStatus = Literal["draft", "needs_clarification", "ready", "committed"]

# Severity for a single spec issue surfaced to the agent/user.
#   error -> refuse to commit;  gap -> blocks convergence (readiness);  warn -> advisory.
IssueSeverity = Literal["error", "gap", "warn"]

# Placeholder/vague markers and generic titles mirror ledger._scoreability_issues
# so the spec gives the same feedback before the ledger's own hard gate fires.
_VAGUE_MARKERS = ("tbd", "todo", "unknown", "unclear", "not sure", "to be decided", "figure out later")
_BARE_CRITERIA = {"yes", "no", "maybe", "n/a", "na"}
_GENERIC_TITLES = {"will it happen?", "what will happen?", "forecast"}


@dataclass(frozen=True)
class SpecIssue:
    """A single validation finding with a suggested fix."""

    field: str
    severity: IssueSeverity
    message: str
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WatchedSourceSpec:
    """A source to watch so re-runs can refresh it automatically.

    ``reliability_prior`` seeds the default ``reliability_rating`` for evidence
    imported from this source, and ``confidence_weight`` seeds its ensemble
    component weight — the user's per-source confidence, captured up front.
    """

    source: str
    source_type: str | None = None
    source_name: str | None = None
    cadence: str | None = None
    reliability_prior: float = 0.7
    confidence_weight: float = 1.0
    keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    materiality: str | None = None
    direction: str | None = None
    rationale: str = ""

    def watch_metadata(self) -> dict[str, Any]:
        """The metadata dict persisted onto the watched_sources row."""
        meta: dict[str, Any] = {
            "reliability_prior": self.reliability_prior,
            "confidence_weight": self.confidence_weight,
        }
        if self.cadence:
            meta["cadence"] = self.cadence
        if self.keywords:
            meta["keywords"] = list(self.keywords)
        if self.exclude_keywords:
            meta["exclude_keywords"] = list(self.exclude_keywords)
        if self.materiality:
            meta["materiality"] = self.materiality
        if self.direction:
            meta["direction"] = self.direction
        if self.rationale:
            meta["rationale"] = self.rationale
        if self.source_name:
            meta["source_name"] = self.source_name

        return meta


@dataclass(frozen=True)
class ReferenceClassSpec:
    """A reference class to seed so the base_rate pipeline artifact exists up front."""

    name: str
    inclusion_criteria: str
    exclusion_criteria: str = ""
    base_rate: float | None = None
    base_rate_uncertainty: float | None = None
    source_refs: tuple[str, ...] = ()
    check_cadence: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class UpdateTriggerSpec:
    """A decision-card update trigger; executable when operator+threshold+source_ref are set."""

    mechanism: str
    operator: str | None = None
    threshold: float | None = None
    source_ref: str | None = None
    action: str | None = None
    window: str | None = None
    notes: str | None = None

    def to_trigger(self) -> dict[str, Any]:
        out: dict[str, Any] = {"mechanism": self.mechanism}
        for key in ("operator", "threshold", "source_ref", "action", "window", "notes"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value

        return out


@dataclass(frozen=True)
class QuestionSpec:
    """A complete, typed staging object for a forecast question."""

    # core question (maps to create_question)
    title: str
    resolution_criteria: str
    outcome_type: str = "binary"
    choices: tuple[str, ...] = ("yes", "no")
    units: str | None = None
    bounds: tuple[float, float] | None = None
    resolution_parser: str | None = None
    description: str = ""
    resolution_source: str | None = None
    close_time: str | None = None
    resolution_time: str | None = None
    tags: tuple[str, ...] = ()
    domain: str | None = None
    topics: tuple[str, ...] = ()
    owner: str | None = None
    impact: str | None = None
    review_cadence: str | None = None
    next_review_at: str | None = None

    # decision card
    decision_owner: str | None = None
    decision_deadline: str | None = None
    action_threshold: str | None = None
    update_triggers: tuple[UpdateTriggerSpec, ...] = ()

    # attach-after-creation payloads
    watched_sources: tuple[WatchedSourceSpec, ...] = ()
    reference_classes: tuple[ReferenceClassSpec, ...] = ()

    # onboarding-only toggles
    allow_evidence_gathering: bool = True
    panel_by_default: bool = False
    autonomy: str = "ask"  # "ask" | "auto_low_stakes" | "full"

    # meta
    status: OnboardingStatus = "draft"
    clarifications: tuple[dict[str, Any], ...] = ()
    spec_version: int = 1

    # ── outcome space ────────────────────────────────────────────────────────
    def outcome_space(self) -> OutcomeSpace:
        return OutcomeSpace(
            type=self.outcome_type,
            choices=list(self.choices) if self.choices else (["yes", "no"] if self.outcome_type == "binary" else []),
            units=self.units,
            bounds=list(self.bounds) if self.bounds is not None else None,
            resolution_parser=self.resolution_parser,
        )

    # ── validation ───────────────────────────────────────────────────────────
    def validate(self) -> list[SpecIssue]:
        """Return all issues (error/gap/warn). Empty error-list => committable."""
        issues: list[SpecIssue] = []

        title = (self.title or "").strip()
        criteria = (self.resolution_criteria or "").strip()
        if not title:
            issues.append(SpecIssue("title", "error", "title is required", "Give the question a specific title."))
        elif title.lower() in _GENERIC_TITLES:
            issues.append(SpecIssue("title", "error", "title is too generic", "Name the specific event/metric and horizon."))

        crit_lower = criteria.lower()
        if not criteria:
            issues.append(SpecIssue("resolution_criteria", "error", "resolution criteria are required", "State the measurable condition + source."))
        else:
            if any(marker in crit_lower for marker in _VAGUE_MARKERS):
                issues.append(SpecIssue("resolution_criteria", "error", "criteria contain placeholder/vague language", "Replace tbd/unclear with a concrete threshold."))
            if crit_lower in _BARE_CRITERIA:
                issues.append(SpecIssue("resolution_criteria", "error", "criteria are too short to audit", "Describe exactly what counts as YES vs NO."))
            elif len(crit_lower.split()) < 5:
                issues.append(SpecIssue("resolution_criteria", "error", "criteria need an auditable condition", "Add the threshold, source, and timeframe."))

        # outcome space — reuse the ledger's source-of-truth validator.
        if self.outcome_type not in OUTCOME_TYPES:
            issues.append(SpecIssue("outcome_type", "error", f"outcome_type must be one of {', '.join(sorted(OUTCOME_TYPES))}", ""))
        else:
            try:
                self.outcome_space().validate()
            except ValidationError as exc:
                issues.append(SpecIssue("choices", "error", str(exc), "Fix the choices/units/bounds for this outcome type."))
            if self.outcome_type in {"numeric", "distribution"} and not self.units:
                issues.append(SpecIssue("units", "error", "numeric/distribution forecasts need units", "Set units (e.g. '%', 'USD')."))
            if self.outcome_type == "categorical":
                lowered = [c.strip().lower() for c in self.choices]
                if len(set(lowered)) != len(lowered):
                    issues.append(SpecIssue("choices", "error", "categorical choices must be unique", "Remove duplicate choices."))

        # priors / base rates ranges
        for i, ws in enumerate(self.watched_sources):
            if not (ws.source or "").strip():
                issues.append(SpecIssue(f"watched_sources[{i}].source", "error", "watched source requires a non-empty source", ""))
            if not (0.0 <= ws.reliability_prior <= 1.0):
                issues.append(SpecIssue(f"watched_sources[{i}].reliability_prior", "error", "reliability_prior must be in [0,1]", ""))
            if ws.confidence_weight < 0:
                issues.append(SpecIssue(f"watched_sources[{i}].confidence_weight", "error", "confidence_weight must be >= 0", ""))
        for i, rc in enumerate(self.reference_classes):
            if not (rc.name or "").strip() or not (rc.inclusion_criteria or "").strip():
                issues.append(SpecIssue(f"reference_classes[{i}]", "error", "reference class needs a name and inclusion_criteria", ""))
            if rc.base_rate is not None and not (0.0 <= rc.base_rate <= 1.0):
                issues.append(SpecIssue(f"reference_classes[{i}].base_rate", "error", "base_rate must be in [0,1]", ""))
            if rc.base_rate_uncertainty is not None and rc.base_rate_uncertainty < 0:
                issues.append(SpecIssue(f"reference_classes[{i}].base_rate_uncertainty", "error", "base_rate_uncertainty must be >= 0", ""))

        # triggers — operator requires a numeric threshold; operator must be known.
        for i, tr in enumerate(self.update_triggers):
            if not (tr.mechanism or "").strip():
                issues.append(SpecIssue(f"update_triggers[{i}].mechanism", "error", "trigger mechanism is required", ""))
            if tr.operator is not None:
                if tr.operator not in TRIGGER_OPERATORS:
                    issues.append(SpecIssue(f"update_triggers[{i}].operator", "error", f"operator must be one of {', '.join(sorted(TRIGGER_OPERATORS))}", ""))
                if tr.threshold is None:
                    issues.append(SpecIssue(f"update_triggers[{i}].threshold", "error", "operator requires a numeric threshold", "Set a numeric threshold or drop the operator."))

        if self.autonomy not in {"ask", "auto_low_stakes", "full"}:
            issues.append(SpecIssue("autonomy", "error", "autonomy must be ask | auto_low_stakes | full", ""))

        # decision-readiness gaps (block convergence, not create_question itself).
        if not (self.decision_owner or "").strip():
            issues.append(SpecIssue("decision_owner", "gap", "no decision owner — who acts on this?", "Set decision_owner, or waive to track-only."))
        if not (self.action_threshold or "").strip():
            issues.append(SpecIssue("action_threshold", "gap", "no action threshold — when does this change a decision?", "Set action_threshold, or waive."))
        if not self.update_triggers:
            issues.append(SpecIssue("update_triggers", "gap", "no update triggers — what would force a re-look?", "Add an executable trigger, or waive."))

        # re-run mandate: a question with no watched sources has nothing to refresh.
        if not self.watched_sources:
            issues.append(SpecIssue("watched_sources", "warn", "no watched sources — re-runs will have nothing to refresh", "Add at least one source (markets/FRED/RSS)."))

        return issues

    def errors(self) -> list[SpecIssue]:
        return [i for i in self.validate() if i.severity == "error"]

    def readiness_gaps(self) -> list[SpecIssue]:
        return [i for i in self.validate() if i.severity == "gap"]

    def is_committable(self) -> bool:
        return not self.errors()

    # ── transport ────────────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return spec_to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuestionSpec:
        return spec_from_dict(data)

    def with_status(self, status: OnboardingStatus) -> QuestionSpec:
        return replace(self, status=status)

    # ── commit fan-out ───────────────────────────────────────────────────────
    def commit(self, ledger: Any) -> dict[str, Any]:
        """Create the question + watched sources + reference classes + decision card.

        Raises :class:`ValidationError` if the spec has error-severity issues, so
        an underspecified question never reaches the ledger. Returns a structured
        result describing everything created.
        """
        errs = self.errors()
        if errs:
            raise ValidationError(
                "question spec is not committable: "
                + "; ".join(f"{e.field}: {e.message}" for e in errs)
            )

        onboarding_meta = {
            "allow_evidence_gathering": self.allow_evidence_gathering,
            "panel_by_default": self.panel_by_default,
            "autonomy": self.autonomy,
            "spec_version": self.spec_version,
        }
        if self.clarifications:
            onboarding_meta["clarifications"] = list(self.clarifications)
        gaps = self.readiness_gaps()
        if gaps:
            onboarding_meta["waived_readiness"] = [g.field for g in gaps]

        question = ledger.create_question(
            title=self.title.strip(),
            resolution_criteria=self.resolution_criteria.strip(),
            outcome_space=self.outcome_space(),
            description=self.description,
            resolution_source=self.resolution_source,
            close_time=self.close_time,
            resolution_time=self.resolution_time,
            tags=list(self.tags),
            domain=self.domain,
            topics=list(self.topics),
            owner=self.owner,
            impact=self.impact,
            review_cadence=self.review_cadence,
            next_review_at=self.next_review_at,
            metadata={"onboarding": onboarding_meta},
            decision_owner=self.decision_owner,
            decision_deadline=self.decision_deadline,
            action_threshold=self.action_threshold,
            update_triggers=normalize_update_triggers([t.to_trigger() for t in self.update_triggers]) if self.update_triggers else None,
        )
        question_id = question.id if hasattr(question, "id") else question["id"]

        watched: list[dict[str, Any]] = []
        for ws in self.watched_sources:
            watched.append(
                ledger.add_watched_source(
                    scope_type="question",
                    scope_ref=question_id,
                    source=ws.source.strip(),
                    source_type=ws.source_type,
                    metadata=ws.watch_metadata(),
                )
            )

        ref_classes: list[dict[str, Any]] = []
        for rc in self.reference_classes:
            ref_classes.append(
                ledger.add_reference_class(
                    question_id=question_id,
                    name=rc.name.strip(),
                    inclusion_criteria=rc.inclusion_criteria.strip(),
                    exclusion_criteria=rc.exclusion_criteria,
                    base_rate=rc.base_rate,
                    base_rate_uncertainty=rc.base_rate_uncertainty,
                    source_refs=list(rc.source_refs) or None,
                    check_cadence=rc.check_cadence,
                    notes=rc.notes,
                )
            )

        # Loop coverage: a committed (serious) question is put on the review cycle
        # so it is actually re-checked + auto-scored/postmortemed without the
        # operator remembering to schedule it (the "review runs = 0" pain). The spec
        # only stored review_cadence on the question; nothing created the schedule
        # row the cycle reads. Idempotent (schedule_review dedups), so a re-commit
        # or an explicit schedule won't spawn a duplicate. Fail-open: a scheduling
        # hiccup must never block the commit.
        #
        # trigger_reason="question_review_cadence" deliberately MATCHES the reason
        # create_question uses for the weekly review it now auto-creates for eligible
        # live questions. schedule_review is idempotent on
        # (scope_type, scope_ref, cadence, trigger_reason), so this UPSERTS the
        # auto_score/auto_postmortem flags onto that single row instead of spawning a
        # second question-scoped review.
        scheduled_review = None
        scheduled_review_error = None
        try:
            scheduled_review = ledger.schedule_review(
                scope_type="question",
                scope_ref=question_id,
                cadence=(self.review_cadence or "weekly"),
                trigger_reason="question_review_cadence",
                auto_score=True,
                auto_postmortem=True,
            )
        except Exception as exc:
            # Fail-open: a scheduling hiccup must never block the commit. But record
            # WHY rather than swallowing it silently, so a real misconfiguration
            # (e.g. a bad cadence) surfaces in the commit result instead of vanishing.
            scheduled_review = None
            scheduled_review_error = str(exc)

        question_dict = dict(question.__dict__) if hasattr(question, "__dict__") else dict(question)
        # OutcomeSpace is the one non-JSON-serializable field on the question.
        outcome = question_dict.get("outcome_space")
        if hasattr(outcome, "to_dict"):
            question_dict["outcome_space"] = outcome.to_dict()

        return {
            "question_id": question_id,
            "question": question_dict,
            "watched_sources": watched,
            "reference_classes": ref_classes,
            "scheduled_review": scheduled_review,
            "scheduled_review_error": scheduled_review_error,
            "readiness_gaps": [g.to_dict() for g in gaps],
        }


# ── onboarding settings (read at run/re-run time) ────────────────────────────
ONBOARDING_DEFAULTS = {"allow_evidence_gathering": True, "panel_by_default": False, "autonomy": "ask"}


def onboarding_settings(question_metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Extract the onboarding toggles from a question's metadata, with defaults.

    These were stashed under ``metadata['onboarding']`` at commit time and are
    consumed by the run/re-run paths (evidence permission, panel default, the
    clarify-autonomy level).
    """
    raw = (question_metadata or {}).get("onboarding") or {}

    return {
        "allow_evidence_gathering": bool(raw.get("allow_evidence_gathering", ONBOARDING_DEFAULTS["allow_evidence_gathering"])),
        "panel_by_default": bool(raw.get("panel_by_default", ONBOARDING_DEFAULTS["panel_by_default"])),
        "autonomy": raw.get("autonomy") or ONBOARDING_DEFAULTS["autonomy"],
    }


# ── recommended clarifications (drives the curation dialog) ──────────────────
def recommended_clarifications(spec: QuestionSpec) -> list[dict[str, Any]]:
    """Ready-to-fire clarify prompts in the §2 priority order.

    Each item is ``{field, question, choices}`` where ``choices`` are plain
    strings (the clarify tool auto-appends "Other"); the first choice carries a
    "(recommended)" marker so the user can one-key accept. Issue-derived prompts
    only appear when that field is an actual error/gap/warn; the two preference
    prompts (evidence permission, panel) always appear so the user sets them.
    """
    issues = spec.validate()
    by_field = {i.field.split("[")[0]: i for i in issues}
    out: list[dict[str, Any]] = []

    if "outcome_type" in by_field or "choices" in by_field or "units" in by_field:
        out.append({
            "field": "outcome_type",
            "question": "How should this question resolve?",
            "choices": ["Yes/No binary (recommended)", "Numeric value with units", "Categorical buckets", "Distribution"],
        })
    if "resolution_criteria" in by_field or "title" in by_field:
        out.append({
            "field": "resolution_criteria",
            "question": "The criteria are too vague to score — what measurable condition + source resolves this?",
            "choices": [],  # free text
        })
    if "decision_owner" in by_field:
        out.append({
            "field": "decision_owner",
            "question": "Who owns the decision this forecast informs?",
            "choices": ["You (recommended)", "Team/desk", "No owner — track only"],
        })
    if "action_threshold" in by_field:
        out.append({
            "field": "action_threshold",
            "question": "At what probability does this change your action?",
            "choices": [">=70% act (recommended)", ">=50%", "Custom threshold", "No action threshold"],
        })
    if "update_triggers" in by_field:
        out.append({
            "field": "update_triggers",
            "question": "What observation should force a re-look (an executable source + threshold)?",
            "choices": [],  # free text
        })

    # Standing preference prompts (not validation-derived).
    out.append({
        "field": "allow_evidence_gathering",
        "question": "May I autonomously fetch evidence from the web/data feeds on each run?",
        "choices": ["Yes — auto-fetch (recommended)", "Yes, but ask before each fetch", "No — I'll add evidence manually"],
    })
    if "watched_sources" in by_field:
        out.append({
            "field": "watched_sources",
            "question": "No watched sources yet — re-runs need something to refresh. Add the sources I propose?",
            "choices": ["Add all (recommended)", "Let me pick", "Add none"],
        })
    out.append({
        "field": "panel_by_default",
        "question": "Run a multi-model panel on this question by default? (slower, higher quality)",
        "choices": ["No — single model (recommended)", "Yes, first run only", "Yes, every scheduled run"],
    })

    return out


# ── dict round-trip (transport for CLI/gateway/TUI) ──────────────────────────
def _tuple(value: Any) -> tuple:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)

    return (value,)


def spec_to_dict(spec: QuestionSpec) -> dict[str, Any]:
    data = asdict(spec)
    # asdict turns nested dataclasses into dicts and tuples into lists already.
    return data


def spec_from_dict(data: dict[str, Any]) -> QuestionSpec:
    """Coerce an untyped dict (agent/CLI JSON) into a QuestionSpec, rejecting unknown keys."""
    if not isinstance(data, dict):
        raise ValidationError("question spec must be an object")

    known = set(QuestionSpec.__dataclass_fields__)
    unknown = set(data) - known
    if unknown:
        raise ValidationError(f"unknown question spec fields: {', '.join(sorted(unknown))}")

    bounds = data.get("bounds")
    spec = QuestionSpec(
        title=str(data.get("title") or ""),
        resolution_criteria=str(data.get("resolution_criteria") or ""),
        outcome_type=str(data.get("outcome_type") or "binary"),
        choices=_tuple(data.get("choices")) or ("yes", "no"),
        units=data.get("units"),
        bounds=(float(bounds[0]), float(bounds[1])) if bounds and len(bounds) == 2 else None,
        resolution_parser=data.get("resolution_parser"),
        description=str(data.get("description") or ""),
        resolution_source=data.get("resolution_source"),
        close_time=data.get("close_time"),
        resolution_time=data.get("resolution_time"),
        tags=_tuple(data.get("tags")),
        domain=data.get("domain"),
        topics=_tuple(data.get("topics")),
        owner=data.get("owner"),
        impact=data.get("impact"),
        review_cadence=data.get("review_cadence"),
        next_review_at=data.get("next_review_at"),
        decision_owner=data.get("decision_owner"),
        decision_deadline=data.get("decision_deadline"),
        action_threshold=data.get("action_threshold"),
        update_triggers=tuple(
            UpdateTriggerSpec(
                mechanism=str(t.get("mechanism") or ""),
                operator=t.get("operator"),
                threshold=(float(t["threshold"]) if t.get("threshold") is not None else None),
                source_ref=t.get("source_ref"),
                action=t.get("action"),
                window=t.get("window"),
                notes=t.get("notes"),
            )
            for t in (data.get("update_triggers") or [])
        ),
        watched_sources=tuple(
            WatchedSourceSpec(
                source=str(w.get("source") or ""),
                source_type=w.get("source_type"),
                source_name=w.get("source_name"),
                cadence=w.get("cadence"),
                reliability_prior=float(w["reliability_prior"]) if w.get("reliability_prior") is not None else 0.7,
                confidence_weight=float(w["confidence_weight"]) if w.get("confidence_weight") is not None else 1.0,
                keywords=_tuple(w.get("keywords")),
                exclude_keywords=_tuple(w.get("exclude_keywords")),
                materiality=w.get("materiality"),
                direction=w.get("direction"),
                rationale=str(w.get("rationale") or ""),
            )
            for w in (data.get("watched_sources") or [])
        ),
        reference_classes=tuple(
            ReferenceClassSpec(
                name=str(r.get("name") or ""),
                inclusion_criteria=str(r.get("inclusion_criteria") or ""),
                exclusion_criteria=str(r.get("exclusion_criteria") or ""),
                base_rate=(float(r["base_rate"]) if r.get("base_rate") is not None else None),
                base_rate_uncertainty=(float(r["base_rate_uncertainty"]) if r.get("base_rate_uncertainty") is not None else None),
                source_refs=_tuple(r.get("source_refs")),
                check_cadence=r.get("check_cadence"),
                notes=r.get("notes"),
            )
            for r in (data.get("reference_classes") or [])
        ),
        allow_evidence_gathering=bool(data.get("allow_evidence_gathering", True)),
        panel_by_default=bool(data.get("panel_by_default", False)),
        autonomy=str(data.get("autonomy") or "ask"),
        status=data.get("status") or "draft",
        clarifications=_tuple(data.get("clarifications")),
        spec_version=int(data.get("spec_version") or 1),
    )

    return spec
