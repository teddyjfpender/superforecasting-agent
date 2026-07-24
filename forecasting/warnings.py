"""Warning-resolution dispatcher: the pure brain that turns an open ``alert_events``
backlog into *real gated work* (or an honest "surfaced, not resolved").

This module is deliberately **pure + dependency-injected**. It never reaches for a
live LLM, a network source, or a scoring run on its own — the actual gated actions
are passed in as runner callables (``reforecast_runner`` / ``autopilot_runner`` /
``score_runner`` / ``postmortem_runner``). That keeps the routing logic
unit-testable without a live model
and, more importantly, preserves the load-bearing invariant:

    NEVER bare-acknowledge a warning to make the number drop.

An alert is acknowledged here in exactly two cases:

1. The kind has a safe auto-fix and its injected runner **actually performed the
   real gated work** (returned a truthy result without raising). The runner is the
   thing that produces the snapshot / score / autopilot action the SQLite
   write-gate + forecast hooks vet — so acking is the *natural consequence* of a
   real fix, never a substitute for one.
2. The kind is genuine BOOKKEEPING (an ``autopilot_enabled`` notice, a
   ``review_due`` reminder) where the alert is informational and acking it is the
   correct close-out — there is no forecast to move.

Everything else stays OPEN:

* A failing / no-op runner does **not** ack (the condition still holds → re-surface).
* NO_AUTO classes (domain-error profiles, assumption / reference-class checks,
  central-in-band-without-recenter) have no safe auto-fix and are *surfaced* for a
  human, never auto-resolved.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Optional

from datetime import datetime

from forecasting.models import AlertEvent, timestamp_to_datetime

__all__ = [
    "ResolutionKind",
    "NormalizedWarning",
    "ResolutionRunners",
    "classify_warning",
    "iter_warnings",
    "select_open_warnings",
    "resolve_alert",
    "plan_alert",
    "summarize_open_warnings",
    "MATERIAL_MOVE_THRESHOLD",
    "is_material_move",
    "WARNING_TIERS",
    "coerce_kind",
    "expand_tier",
    "resolve_kind_filter",
    "AGGREGATE_TIER_FOR_KIND",
    "aggregate_open_warnings",
    "fold_warning_groups",
    "RESPEND_BACKOFF_BASE_HOURS",
    "RESPEND_BACKOFF_CAP_HOURS",
    "RESPEND_COOLDOWN_KINDS",
    "respend_backoff_hours",
    "is_alert_in_respend_cooldown",
]


# ---------------------------------------------------------------------------
# Reforecast COMMIT policy — materiality
# ---------------------------------------------------------------------------
#
# The auto-reforecast policy ("auto-reforecast commits material moves") needs a
# single, shared notion of *what counts as a material move* so the agent's commit
# instructions, the cron reforecast runner, and the tests all agree. This is the
# forecast-UPDATE commit threshold and is deliberately SEPARATE from a question's
# decision-card ACTION threshold (when to act on the number): a 0.46 -> 0.56 move
# is material enough to RECORD even if neither side crosses an action line.
MATERIAL_MOVE_THRESHOLD = 0.03


def is_material_move(
    prior: Any,
    proposed: Any,
    *,
    threshold: float = MATERIAL_MOVE_THRESHOLD,
) -> bool:
    """True when ``proposed`` is a *material* move versus ``prior``.

    For binary/scalar probabilities a move is material when ``|Δp| >= threshold``
    (default 3pp). When there is no prior comparable scalar (a genuinely first
    forecast, or a distribution/categorical payload), any change is treated as
    material — there is no marginal "noise" band to suppress, and a brand-new
    estimate is always worth recording. Two equal distributions are NOT material.
    """

    p_prev = _scalar_prob(prior)
    p_new = _scalar_prob(proposed)
    if p_prev is not None and p_new is not None:
        return abs(p_new - p_prev) >= threshold
    # Non-scalar (distribution / categorical) or no comparable prior: material
    # unless it is byte-for-byte the same payload (a true no-op re-pool).
    return prior != proposed


def _scalar_prob(payload: Any) -> Optional[float]:
    """The comparable scalar probability of a snapshot payload, or None.

    Mirrors ``ForecastLedger._numeric_probability``: a bool is not a probability,
    a bare int/float is, everything else (a distribution dict, a vote-share map)
    has no single comparable scalar."""

    if isinstance(payload, bool):
        return None
    if isinstance(payload, (int, float)):
        return float(payload)
    return None


class ResolutionKind(enum.Enum):
    """How an open warning *can* be resolved (if at all)."""

    REFORECAST = "reforecast"        # stale / new evidence / close-soon → re-run the forecast
    EVIDENCE_COLLECTION = "evidence_collection"  # NO evidence / NO snapshot yet → search+import evidence FIRST
    MATERIAL_CHANGE = "material_change"  # a watched source moved / trigger fired → check the source + reforecast
    SCORE = "score"                  # resolved question due a Brier score → real scoring work
    POSTMORTEM = "postmortem"        # resolved+scored question due a postmortem (score + write-up)
    BOOKKEEPING = "bookkeeping"      # informational notice; acking it is the correct close-out
    NO_AUTO = "no_auto"              # no safe auto-fix; surface for a human, never auto-resolve
    CONTESTED_LABEL = "contested_label"  # a triage auto-label the verifier disputes → operator hand-labels (never auto-resolved)


# ---------------------------------------------------------------------------
# Tiers — named folds over ResolutionKind for per-tier BULK actions
# ---------------------------------------------------------------------------
#
# A *tier* is just a named set of ResolutionKinds, so a caller can drain a whole
# class of backlog in one bulk pass without re-typing the member kinds. The split
# is operationally meaningful — NOT cosmetic:
#
#   * "free"       — the kinds whose injected runners are the NON-LLM gated paths
#                    (bookkeeping close-out, real scoring, score+postmortem, and
#                    the autopilot source re-check for a material change). None of
#                    these spend a paid LLM pass, so a `free` sweep is safe to run
#                    on every cron tick / unattended.
#   * "reforecast" — the heavy AGENT tier: its runners are the opt-in LLM passes
#                    (`automode --agent`). It holds BOTH heavy kinds — REFORECAST
#                    (the LLM update pass over a question that already HAS evidence)
#                    and EVIDENCE_COLLECTION (the LLM/web search+import pass that
#                    bootstraps a question with NO evidence / NO snapshot yet).
#                    Isolating them lets an operator say "only spend the model on
#                    the reforecast + evidence backlog" without also re-acking the
#                    cheap stuff (or vice versa). Both need a paid LLM pass, so they
#                    share the one agent tier (alias "agent").
#
# NO_AUTO is deliberately in NO tier: it is never auto-resolved (always surfaced),
# so folding it into a bulk action would be meaningless. A tier filter NEVER
# weakens the no-bare-ack invariant — it only narrows WHICH open alerts the same
# gated dispatcher considers this pass.
WARNING_TIERS: dict[str, "frozenset[ResolutionKind]"] = {
    "free": frozenset(
        {
            ResolutionKind.BOOKKEEPING,
            ResolutionKind.SCORE,
            ResolutionKind.POSTMORTEM,
            ResolutionKind.MATERIAL_CHANGE,
        }
    ),
    "reforecast": frozenset(
        {ResolutionKind.REFORECAST, ResolutionKind.EVIDENCE_COLLECTION}
    ),
}

# Operator-friendly aliases (the docs/prompt name them "run-free-pass" /
# "reforecast-tier"). Normalised to canonical keys; "-tier"/"-pass" decoration and
# hyphen/underscore styling are all accepted.
_TIER_ALIASES = {
    "free": "free",
    "run-free": "free",
    "run-free-pass": "free",
    "free-pass": "free",
    "reforecast": "reforecast",
    "reforecast-tier": "reforecast",
    "agent": "reforecast",
}


def coerce_kind(value: "ResolutionKind | str") -> ResolutionKind:
    """Coerce a ResolutionKind or its string form (enum ``value`` or ``name``,
    case-insensitive, ``-``/``_`` interchangeable) into a ResolutionKind.

    Raises ``ValueError`` on an unknown kind so a typo at the CLI / RPC boundary
    fails loudly rather than silently matching nothing (which would look like an
    empty backlog).
    """
    if isinstance(value, ResolutionKind):
        return value
    text = str(value).strip().lower().replace("-", "_")
    for kind in ResolutionKind:
        if text == kind.value or text == kind.name.lower():
            return kind
    raise ValueError(f"unknown ResolutionKind: {value!r}")


def expand_tier(tier: str) -> "frozenset[ResolutionKind]":
    """Expand a tier name (or alias) to its frozenset of ResolutionKinds.

    Raises ``ValueError`` on an unknown tier name.
    """
    key = str(tier).strip().lower().replace("_", "-")
    canonical = _TIER_ALIASES.get(key)
    if canonical is None:
        raise ValueError(
            f"unknown warning tier: {tier!r} (known: {sorted(WARNING_TIERS)})"
        )
    return WARNING_TIERS[canonical]


def resolve_kind_filter(
    *,
    kinds: "Iterable[ResolutionKind | str] | None" = None,
    tier: str | None = None,
) -> "frozenset[ResolutionKind] | None":
    """Fold an optional ``tier`` and/or explicit ``kinds`` list into a single
    frozenset of ResolutionKinds to keep — or ``None`` when neither is given
    (meaning "no kind filter", every kind passes).

    A tier and an explicit kinds list are UNIONed (the result keeps an alert whose
    kind is in either), so e.g. ``tier="free", kinds=["reforecast"]`` widens the
    free tier by one kind. An empty (but non-None) kinds iterable with no tier
    yields an empty frozenset — a deliberate "match nothing" the caller asked for,
    distinct from the ``None`` "match everything".
    """
    if kinds is None and tier is None:
        return None
    selected: set[ResolutionKind] = set()
    if tier is not None:
        selected |= set(expand_tier(tier))
    if kinds is not None:
        for value in kinds:
            selected.add(coerce_kind(value))
    return frozenset(selected)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# NO_AUTO prefixes are checked FIRST: these are human-judgment classes (a domain
# error profile applies, an assumption / reference class needs re-validation, a
# central-in-band forecast needs a deliberate recenter). They must never be
# swept up by the broader "stale" matching below.
_NO_AUTO_PREFIXES = (
    "domain_error",          # domain_error_profile_applies:* / domain_error_profile_review
    "assumption_check",      # assumption_check_due:*
    "assumption_invalidated",
    "assumption_stale",
    "reference_class",       # reference_class_*:*
    "central_in_band",
    "calibration_lesson",    # calibration_lesson_review — human-curated
    # The watch scheduler owns retries. Re-polling every source on the question
    # from the warning worker is slow and cannot repair a broken endpoint.
    "watched_source_unavailable",
)

# A triage auto-label the verifier disputes (Thinking Machines L8 contested
# routing). Its own MANUAL kind — surfaced for the operator to hand-label, never
# auto-resolved — so it shows as a distinct "contested" line, not folded into the
# generic NO_AUTO bucket.
_CONTESTED_LABEL_PREFIXES = ("contested_label",)

_MATERIAL_PREFIXES = (
    "watched_source_changed",
    "autopilot_source_failed",
    "autopilot_required_source_failed",
)

_BOOKKEEPING_PREFIXES = (
    "autopilot_enabled",
    "review_due",
)

# EVIDENCE_COLLECTION is checked BEFORE REFORECAST: a question with NO evidence /
# NO forecast snapshot cannot be re-forecast yet (the REFORECAST runner's
# update-gate hard-blocks on zero evidence), so these reasons route to a distinct
# kind whose runner SEARCHES FOR + IMPORTS evidence first, instead of being
# bucketed into REFORECAST and forever resolving to "skipped: update gated".
_EVIDENCE_COLLECTION_PREFIXES = (
    "no_evidence",
    "no_forecast_snapshot",
)

_REFORECAST_PREFIXES = (
    "forecast_estimation_required",
    # A threshold crossing already happened; re-polling the same source cannot
    # resolve it.  It needs fresh judgment over the captured signal.
    "trigger_fired",
    # A substantive learned-error review concluded that the forecast must move.
    "learned_error_update_required",
    "evidence_stale",        # evidence_stale_7d_plus, etc.
    "last_update",           # last_update_* staleness
    "new_evidence",          # new_evidence:*
    "close_time_within",     # close_time_within_*
    "under_saturated",       # Wave 3 H4: a live forecast scored below the saturation bar —
                             # the agent re-saturates it (re-run / added reasoning / decompose)
                             # and reconcile_alerts SCORE-clears it once the current snapshot's
                             # stored saturation score is back at/above the bar (evidence-free
                             # re-saturation counts); the deduped sweep re-raises if still low.
)


def classify_warning(reason: str | None) -> ResolutionKind:
    """Map an alert ``reason`` string to the resolution kind that *governs* it.

    Fail-safe: any unknown / empty reason maps to ``NO_AUTO`` so a never-before-seen
    alert is surfaced for a human rather than silently auto-acked.
    """
    text = (reason or "").strip()
    if not text:
        return ResolutionKind.NO_AUTO

    # 1. NO_AUTO — human-judgment classes, checked before generic matching.
    if text.startswith(_NO_AUTO_PREFIXES):
        return ResolutionKind.NO_AUTO

    # 1b. CONTESTED_LABEL — a triage auto-label the verifier disputes; the operator
    #     hand-labels it. A manual kind (surfaced, never auto-resolved), but tracked
    #     distinctly from NO_AUTO so the headline shows the contested-label backlog.
    if text.startswith(_CONTESTED_LABEL_PREFIXES):
        return ResolutionKind.CONTESTED_LABEL

    # 2. POSTMORTEM — covers both `postmortem_due` and `high_impact_postmortem_due`.
    if "postmortem_due" in text:
        return ResolutionKind.POSTMORTEM

    # 3. MATERIAL_CHANGE — a watched source moved / a trigger fired.
    if text.startswith(_MATERIAL_PREFIXES):
        return ResolutionKind.MATERIAL_CHANGE

    # 4. SCORE — a resolved question is due a Brier score (`score_due` /
    #    `high_impact_score_due`). Scoring IS real gated work (it computes +
    #    persists a score record), so it routes to the score runner and acks only
    #    on that truthy ScoreRecord — NEVER a bare-ack bookkeeping close-out.
    #    (Checked after POSTMORTEM so `postmortem_due` is never mistaken for it.)
    if "score_due" in text:
        return ResolutionKind.SCORE

    # 5. BOOKKEEPING — informational notices (autopilot enabled, review due).
    if text.startswith(_BOOKKEEPING_PREFIXES):
        return ResolutionKind.BOOKKEEPING

    # 6. EVIDENCE_COLLECTION — a question with NO evidence / NO snapshot yet. Must
    #    be checked BEFORE REFORECAST: re-forecasting needs evidence first, so these
    #    route to the search+import runner, not the (zero-evidence-gated) LLM update.
    if text.startswith(_EVIDENCE_COLLECTION_PREFIXES):
        return ResolutionKind.EVIDENCE_COLLECTION

    # 7. REFORECAST — staleness / new-evidence / close-soon (question already has
    #    evidence; the LLM update pass can run).
    if text.startswith(_REFORECAST_PREFIXES):
        return ResolutionKind.REFORECAST

    # Default fail-safe: unknown reason → surface, never auto-resolve.
    return ResolutionKind.NO_AUTO


# ---------------------------------------------------------------------------
# Normalisation + priority
# ---------------------------------------------------------------------------

_SEVERITY_RANK = {"high": 0, "warning": 1, "info": 2}

# Within a severity band, surface the most time-sensitive/actionable kind first.
# Material moves and re-forecasts are live + actionable; postmortems are
# retrospective; NO_AUTO needs a human; bookkeeping is least urgent.
_KIND_RANK = {
    ResolutionKind.MATERIAL_CHANGE: 0,
    ResolutionKind.EVIDENCE_COLLECTION: 1,  # bootstrap a no-evidence question first
    ResolutionKind.REFORECAST: 2,
    ResolutionKind.SCORE: 3,
    ResolutionKind.POSTMORTEM: 4,
    ResolutionKind.CONTESTED_LABEL: 5,  # manual, but actionable by the operator
    ResolutionKind.NO_AUTO: 6,
    ResolutionKind.BOOKKEEPING: 7,
}


@dataclass(frozen=True)
class NormalizedWarning:
    """A single open alert, enriched with its resolution kind + sort priority."""

    id: str
    created_at: str
    severity: str
    scope_type: str
    scope_ref: str
    reason: str
    recommended_action: str
    kind: ResolutionKind
    alert: AlertEvent
    last_attempted_at: str | None = None
    attempt_count: int = 0

    @property
    def is_auto_resolvable(self) -> bool:
        return self.kind not in (
            ResolutionKind.NO_AUTO,
            ResolutionKind.CONTESTED_LABEL,
        )


def _normalize(alert: AlertEvent) -> NormalizedWarning:
    return NormalizedWarning(
        id=alert.id,
        created_at=alert.created_at,
        severity=(alert.severity or "info"),
        scope_type=(alert.scope_type or ""),
        scope_ref=(alert.scope_ref or ""),
        reason=(alert.reason or ""),
        recommended_action=(alert.recommended_action or ""),
        kind=classify_warning(alert.reason),
        alert=alert,
        last_attempted_at=getattr(alert, "last_attempted_at", None),
        attempt_count=int(getattr(alert, "attempt_count", 0) or 0),
    )


def _alert_priority(w: NormalizedWarning) -> tuple[int, int, str]:
    """Sort key so the worst/oldest warning surfaces first (ascending sort).

    Ordering: severity (high > warning > info), then reason-importance (the kind
    rank above), then age (older ``created_at`` first — ISO timestamps sort
    lexicographically, so the smaller string is the older alert).
    """
    severity_rank = _SEVERITY_RANK.get((w.severity or "").strip().lower(), 99)
    kind_rank = _KIND_RANK.get(w.kind, 99)
    return (severity_rank, kind_rank, w.created_at or "")


def iter_warnings(
    ledger: Any,
    *,
    scope: str | None = None,
) -> Iterator[NormalizedWarning]:
    """Yield every *open* alert as a :class:`NormalizedWarning`, worst/oldest first.

    ``scope`` optionally filters to a single question (matches ``scope_ref``) or a
    scope_type (matches ``scope_type``) so a per-question caller can drain just its
    own backlog.
    """
    alerts = ledger.list_alerts(unresolved_only=True)
    normalized = [_normalize(a) for a in alerts]
    if scope is not None:
        normalized = [
            w for w in normalized if w.scope_ref == scope or w.scope_type == scope
        ]
    normalized.sort(key=_alert_priority)
    yield from normalized


# ---------------------------------------------------------------------------
# Re-spend cooldown — per-alert exponential backoff (Slice 8)
# ---------------------------------------------------------------------------
#
# The continuous paid (LLM) tier must NOT re-spend on the same gated/failing alert
# on every cron tick. When a paid runner attempts an alert and does NOT resolve it
# (the runner failed / raised / did no real gated work), the ledger stamps the
# alert with ``last_attempted_at`` + an incremented ``attempt_count`` (it stays
# OPEN — never a bare-ack) and we hold off retrying it until a backoff window
# passes. The window is EXPONENTIAL in the failure count (24h, 48h, 96h, …) so a
# persistently-failing alert backs off fast, while a one-off failure is retried
# the next day. The cooldown is scoped to the spendy AGENT-tier kinds only — the
# free, idempotent, zero-token kinds (bookkeeping / score / postmortem /
# material-change) are never throttled.
RESPEND_BACKOFF_BASE_HOURS = 24.0
# Cap the window so a long-failing alert still gets re-checked roughly fortnightly
# instead of receding past any practical horizon.
RESPEND_BACKOFF_CAP_HOURS = 24.0 * 14

# The spendy kinds the cooldown governs (== the paid "reforecast"/agent tier).
RESPEND_COOLDOWN_KINDS: "frozenset[ResolutionKind]" = WARNING_TIERS["reforecast"]


def respend_backoff_hours(
    attempt_count: int,
    *,
    base_hours: float = RESPEND_BACKOFF_BASE_HOURS,
    cap_hours: float = RESPEND_BACKOFF_CAP_HOURS,
) -> float:
    """The backoff window (hours) an alert must wait after ``attempt_count`` failed
    paid attempts before the paid tier may retry it.

    Zero (no wait) until the first failure; then exponential — ``base`` after the
    1st failure, ``2*base`` after the 2nd, and so on — capped at ``cap_hours``.
    """
    if attempt_count <= 0:
        return 0.0
    window = base_hours * (2.0 ** (attempt_count - 1))
    return min(window, cap_hours)


def is_alert_in_respend_cooldown(
    warning: NormalizedWarning,
    now_dt: datetime,
    *,
    base_hours: float = RESPEND_BACKOFF_BASE_HOURS,
    cap_hours: float = RESPEND_BACKOFF_CAP_HOURS,
) -> bool:
    """True when ``warning`` is still inside its post-failure backoff window and so
    must NOT be re-attempted by the paid tier yet.

    Fail-OPEN to *attemptable* (returns False) when there is no recorded attempt or
    the stamp is unparseable — a missing cooldown stamp must never silently suppress
    a real alert. An alert whose window has elapsed is attemptable again (and, if it
    fails once more, its ``attempt_count`` grows and the next window doubles).
    """
    if warning.attempt_count <= 0 or not warning.last_attempted_at:
        return False
    last_dt = timestamp_to_datetime(warning.last_attempted_at)
    if last_dt is None:
        return False
    try:
        elapsed_hours = (now_dt - last_dt).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return False
    return elapsed_hours < respend_backoff_hours(
        warning.attempt_count, base_hours=base_hours, cap_hours=cap_hours
    )


def _coerce_now_dt(now: "str | datetime | None") -> datetime:
    """Coerce a ``now`` (ISO string / datetime / None) into an aware UTC datetime."""
    if isinstance(now, datetime):
        dt = now
        if dt.tzinfo is None:
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    if isinstance(now, str) and now.strip():
        parsed = timestamp_to_datetime(now.strip())
        if parsed is not None:
            return parsed
    from hermes_time import now as hermes_now

    dt = hermes_now()
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def select_open_warnings(
    ledger: Any,
    *,
    scope: str | None = None,
    reason: "str | list[str] | None" = None,
    limit: int | None = None,
    kinds: "Iterable[ResolutionKind | str] | None" = None,
    tier: str | None = None,
    cooldown: bool = False,
    now: "str | datetime | None" = None,
) -> list[NormalizedWarning]:
    """Return the open backlog (priority order) after the common scope/reason/limit
    filters every driver (CLI, cron phase, gateway, tool) applies identically.

    ``reason`` is a case-insensitive substring filter; ``kinds``/``tier`` select by
    ResolutionKind (a ``tier`` like ``"free"``/``"reforecast"`` expands to its
    member kinds, optionally UNIONed with an explicit ``kinds`` list — see
    :func:`resolve_kind_filter`); ``limit`` caps how many alerts are returned (NOT
    how many reason-groups). The kind filter is applied BEFORE ``limit`` so a
    per-tier bulk pass caps the tier's backlog, not the whole one. Kept in one
    place so the automode loop, the dry-run plan, and the list summary can never
    drift apart.

    ``cooldown`` (Slice 8) drops any spendy AGENT-tier alert still inside its
    post-failure backoff window (see :func:`is_alert_in_respend_cooldown`) BEFORE
    ``limit`` is applied — so the continuous paid tier neither re-attempts a
    cooled-down alert NOR lets it occupy a capped selection slot and starve fresh
    work. It only ever filters the spendy kinds, so a free-tier sweep is unaffected.
    """
    # ``reason`` may be a single substring OR a list of reason substrings — a
    # sub-view tier (e.g. STALE) dismisses several specific reasons at once, so
    # the TUI sends a list. Match if a warning's reason contains ANY term.
    if isinstance(reason, (list, tuple, set)):
        reason_terms = [str(r).strip().lower() for r in reason if str(r).strip()]
    else:
        _r = (reason or "").strip().lower()
        reason_terms = [_r] if _r else []
    kind_filter = resolve_kind_filter(kinds=kinds, tier=tier)
    warnings = list(iter_warnings(ledger, scope=scope))
    if reason_terms:
        warnings = [w for w in warnings if any(t in (w.reason or "").lower() for t in reason_terms)]
    if kind_filter is not None:
        warnings = [w for w in warnings if w.kind in kind_filter]
    if cooldown:
        now_dt = _coerce_now_dt(now)
        warnings = [
            w
            for w in warnings
            if not (
                w.kind in RESPEND_COOLDOWN_KINDS
                and is_alert_in_respend_cooldown(w, now_dt)
            )
        ]
    if limit is not None:
        warnings = warnings[:limit]
    return warnings


def summarize_open_warnings(
    ledger: Any,
    *,
    scope: str | None = None,
    reason: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Group the open backlog by reason (counts + representative metadata),
    preserving the worst/oldest-first priority order (first sighting of a reason
    fixes its group rank). ``limit`` caps the number of GROUPS, while ``open_total``
    always reflects the full (unlimited) matching backlog. Shared by `warnings
    list` (CLI) and ``forecast.warnings.list`` (gateway) so both stay in lockstep.
    """
    # Group over the unlimited backlog; the group cap is applied to the ordered
    # groups afterwards (mirrors the CLI's original behaviour exactly).
    open_warnings = select_open_warnings(ledger, scope=scope, reason=reason, limit=None)
    groups: dict[str, dict[str, Any]] = {}
    for w in open_warnings:
        group = groups.get(w.reason)
        if group is None:
            group = groups[w.reason] = {
                "reason": w.reason,
                "kind": w.kind.value,
                "severity": w.severity,
                "recommended_action": w.recommended_action,
                "auto_resolvable": w.is_auto_resolvable,
                "count": 0,
                "scope_refs": [],
            }
        group["count"] += 1
        if len(group["scope_refs"]) < 5:
            group["scope_refs"].append(w.scope_ref)
    ordered = list(groups.values())
    if limit is not None:
        ordered = ordered[:limit]
    return {"groups": ordered, "group_count": len(groups), "open_total": len(open_warnings)}


# ---------------------------------------------------------------------------
# Aggregate fold — the 4 operator-facing tiers (dashboard headline)
# ---------------------------------------------------------------------------
#
# The aggregate view answers "how big is the backlog, and who has to act on it?"
# It folds the per-reason groups into three ACTION tiers (distinct from the bulk
# WARNING_TIERS above, which gate WHICH kinds a *sweep* drains):
#
#   * "free"   — the non-LLM gated close-outs (bookkeeping / score / postmortem /
#                material-change source re-check). A `free` sweep clears these.
#   * "agent"  — the opt-in LLM passes: REFORECAST (the update pass) AND
#                EVIDENCE_COLLECTION (the search+import pass that bootstraps a
#                no-evidence question). Both fold into the one agent tier.
#   * "manual" — NO_AUTO: a human must judge it; never auto-resolved.
#
# Any unknown / unmapped kind fails safe into "manual" (needs-a-human), never
# silently dropped from the total.
AGGREGATE_TIER_FOR_KIND: dict[ResolutionKind, str] = {
    ResolutionKind.BOOKKEEPING: "free",
    ResolutionKind.SCORE: "free",
    ResolutionKind.POSTMORTEM: "free",
    ResolutionKind.MATERIAL_CHANGE: "free",
    ResolutionKind.REFORECAST: "agent",
    ResolutionKind.EVIDENCE_COLLECTION: "agent",
    ResolutionKind.CONTESTED_LABEL: "manual",
    ResolutionKind.NO_AUTO: "manual",
}

# Reason prefixes that mark a REFORECAST (agent-tier) group as part of the STALE
# sub-bucket — the subset of the reforecast backlog driven by elapsed-time
# staleness (evidence aging out, no recent update, the close date drawing near)
# rather than a fresh evidence signal. Surfaced as a NAMED sub-bucket of the agent
# tier so an operator can see how much of the reforecast backlog is "just getting
# old" versus a new-evidence prompt. It is a VIEW over the agent tier, not a
# fourth tier: its reasons are still counted in agent.total.
_STALE_REASON_PREFIXES = (
    "evidence_stale",
    "last_update",
    "close_time_within",
)


def _aggregate_tier_for_kind_value(kind_value: Any) -> str:
    """Map a group's ``kind`` (a ResolutionKind value string, as emitted by
    :func:`summarize_open_warnings`) to its aggregate action tier. Unknown kinds
    fail safe into ``"manual"`` so their count is never lost from the headline."""
    try:
        kind = coerce_kind(kind_value)
    except ValueError:
        return "manual"
    return AGGREGATE_TIER_FOR_KIND.get(kind, "manual")


def fold_warning_groups(summary: dict[str, Any]) -> dict[str, Any]:
    """Fold a :func:`summarize_open_warnings` result into the 4 operator tiers.

    Pure: takes the grouped summary and returns the aggregate shape with per-tier
    and per-reason totals plus a ``headline`` ``{total, free, agent, manual}``. The
    agent tier carries a ``stale`` sub-bucket (the elapsed-time-staleness subset of
    its reforecast reasons). Reason groups keep their priority order (first sighting
    of a reason fixes its rank) within each tier.
    """
    tiers: dict[str, dict[str, Any]] = {
        "free": {"total": 0, "reasons": []},
        "agent": {"total": 0, "reasons": [], "stale": {"total": 0, "reasons": []}},
        "manual": {"total": 0, "reasons": []},
    }
    for group in summary.get("groups", []) or []:
        count = int(group.get("count", 0) or 0)
        tier_name = _aggregate_tier_for_kind_value(group.get("kind"))
        tier = tiers[tier_name]
        tier["total"] += count
        tier["reasons"].append(group)
        if tier_name == "agent" and str(group.get("reason", "")).startswith(
            _STALE_REASON_PREFIXES
        ):
            tier["stale"]["total"] += count
            tier["stale"]["reasons"].append(group)
    total = tiers["free"]["total"] + tiers["agent"]["total"] + tiers["manual"]["total"]
    return {
        "headline": {
            "total": total,
            "free": tiers["free"]["total"],
            "agent": tiers["agent"]["total"],
            "manual": tiers["manual"]["total"],
        },
        "free": tiers["free"],
        "agent": tiers["agent"],
        "manual": tiers["manual"],
    }


def aggregate_open_warnings(
    ledger: Any,
    *,
    scope: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Aggregate the FULL (untruncated) open backlog into the 4 operator tiers.

    Server-side fold over every matching reason-group (no ``limit`` — the headline
    must reflect the whole backlog, not a page of it). Shared by the
    ``forecast.warnings.aggregate`` gateway RPC."""
    summary = summarize_open_warnings(ledger, scope=scope, reason=reason, limit=None)
    return fold_warning_groups(summary)


# ---------------------------------------------------------------------------
# Resolution dispatch
# ---------------------------------------------------------------------------

# A runner is the injected, gated action. It receives ``(ledger, warning)`` and is
# expected to perform the real work (commit a snapshot / run autopilot / score +
# postmortem). It signals success by returning a **truthy** result and failure by
# returning a falsy value or raising. Returning falsy/no-op is itself meaningful:
# the dispatcher leaves the alert OPEN, so a genuinely-unresolved condition
# re-surfaces on the next pass.
Runner = Callable[[Any, NormalizedWarning], Any]


@dataclass(frozen=True)
class ResolutionRunners:
    """Injected gated actions, one family per auto-resolvable kind."""

    reforecast_runner: Optional[Runner] = None   # REFORECAST
    evidence_runner: Optional[Runner] = None     # EVIDENCE_COLLECTION (search+import)
    autopilot_runner: Optional[Runner] = None    # MATERIAL_CHANGE
    score_runner: Optional[Runner] = None        # SCORE (score the resolved question)
    postmortem_runner: Optional[Runner] = None   # POSTMORTEM (score + write the postmortem)


_KIND_RUNNER_ATTR = {
    ResolutionKind.REFORECAST: "reforecast_runner",
    ResolutionKind.EVIDENCE_COLLECTION: "evidence_runner",
    ResolutionKind.MATERIAL_CHANGE: "autopilot_runner",
    ResolutionKind.SCORE: "score_runner",
    ResolutionKind.POSTMORTEM: "postmortem_runner",
}


_DEFAULT_SURFACED_DETAIL = "no safe auto-fix — surfaced for human review"


def _surfaced_detail(warning: NormalizedWarning) -> str:
    """Human-facing detail for a NO_AUTO surfaced warning. Most NO_AUTO classes have
    no mechanical fix at all; the central-in-band class is the exception — there IS
    a real recenter fix path (``forecasting.distribution.recenter_distribution``) the
    operator/sheet CAN run when they explicitly choose to. We surface that the fix
    exists WITHOUT auto-applying it (the alert still stays OPEN), so the warning is
    no longer 'unresolvable' while the load-bearing no-bare-ack rule is preserved.
    """
    if (warning.reason or "").startswith("central_in_band"):
        return (
            "central tendency lies outside its band — surfaced for human review; "
            "a recenter fix (forecasting.distribution.recenter_distribution) is "
            "available to re-estimate the band, but is NOT auto-applied"
        )
    return _DEFAULT_SURFACED_DETAIL


def _result(
    warning: NormalizedWarning,
    *,
    status: str,
    acknowledged: bool,
    detail: str,
    runner_result: Any = None,
) -> dict[str, Any]:
    return {
        "alert_id": warning.id,
        "reason": warning.reason,
        "scope_ref": warning.scope_ref,
        "kind": warning.kind.value,
        "status": status,
        "acknowledged": acknowledged,
        "detail": detail,
        "runner_result": runner_result,
    }


def plan_alert(
    alert: AlertEvent | NormalizedWarning,
    runners: ResolutionRunners,
) -> dict[str, Any]:
    """Pure (no-write) preview of what :func:`resolve_alert` WOULD do for ``alert``.

    Mirrors the dispatcher's routing EXACTLY so a dry-run (CLI ``automode
    --dry-run`` / the gateway job / the tool action) can show the plan without
    spending a single gated runner call or acking anything. Returns the same
    ``planned`` vocabulary the dry-run surfaces rely on:
    ``surfaced`` | ``would_acknowledge`` | ``would_run`` | ``would_skip``.
    """
    warning = alert if isinstance(alert, NormalizedWarning) else _normalize(alert)
    kind = warning.kind
    if kind in (ResolutionKind.NO_AUTO, ResolutionKind.CONTESTED_LABEL):
        planned, detail = "surfaced", _surfaced_detail(warning)
    elif kind is ResolutionKind.BOOKKEEPING:
        planned, detail = "would_acknowledge", "bookkeeping notice — acked on run"
    else:
        attr = _KIND_RUNNER_ATTR.get(kind)
        if attr is None or getattr(runners, attr, None) is None:
            planned, detail = (
                "would_skip",
                f"no runner for {kind.value} (pass --agent to enable reforecast)",
            )
        else:
            planned, detail = "would_run", f"gated {kind.value} runner"
    return {
        "alert_id": warning.id,
        "reason": warning.reason,
        "scope_ref": warning.scope_ref,
        "kind": kind.value,
        "severity": warning.severity,
        "planned": planned,
        "detail": detail,
    }


def resolve_alert(
    ledger: Any,
    alert: AlertEvent | NormalizedWarning,
    *,
    runners: ResolutionRunners,
    now: str | None = None,
) -> dict[str, Any]:
    """Dispatch ONE open alert to its gated action and ack ONLY on real success.

    Returns a status dict (never raises for a normal runner failure):

    * ``status="resolved"``  — real gated work succeeded (or genuine bookkeeping);
      the alert was acknowledged.
    * ``status="surfaced"``  — NO_AUTO: no safe auto-fix; left OPEN for a human.
    * ``status="failed"``    — the runner returned falsy or raised; left OPEN.
    * ``status="skipped"``   — no runner was injected for this kind; left OPEN.
    """
    warning = alert if isinstance(alert, NormalizedWarning) else _normalize(alert)
    kind = warning.kind

    # NO_AUTO / CONTESTED_LABEL: surface, never auto-ack. A contested triage label
    # is closed only when the operator records a real expert label (relabel_route
    # acks it) — never bare-acknowledged by the automode.
    if kind in (ResolutionKind.NO_AUTO, ResolutionKind.CONTESTED_LABEL):
        return _result(
            warning,
            status="surfaced",
            acknowledged=False,
            detail=_surfaced_detail(warning),
        )

    # BOOKKEEPING: informational notice; acking is the correct close-out.
    if kind is ResolutionKind.BOOKKEEPING:
        ledger.acknowledge_alert(
            warning.id,
            acknowledged_at=now,
            disposition="not_actionable",
        )
        return _result(
            warning,
            status="resolved",
            acknowledged=True,
            detail="bookkeeping notice acknowledged",
        )

    # Auto-resolvable kinds: run the injected gated action, ack ONLY on success.
    runner_attr = _KIND_RUNNER_ATTR.get(kind)
    runner: Optional[Runner] = getattr(runners, runner_attr, None) if runner_attr else None
    if runner is None:
        return _result(
            warning,
            status="skipped",
            acknowledged=False,
            detail=f"no runner injected for kind {kind.value}",
        )

    try:
        outcome = runner(ledger, warning)
    except Exception as exc:  # a failing runner must NOT ack — re-surface next pass.
        return _result(
            warning,
            status="failed",
            acknowledged=False,
            detail=f"runner raised: {exc!r}",
        )

    if not outcome:
        # Runner ran but performed no real gated work (no snapshot/score/action).
        return _result(
            warning,
            status="failed",
            acknowledged=False,
            detail="runner performed no real gated work — left open",
            runner_result=outcome,
        )

    # Real gated work succeeded → acking is the natural consequence.
    dispositions = {
        ResolutionKind.REFORECAST: "resolved_by_forecast_update",
        ResolutionKind.EVIDENCE_COLLECTION: "resolved_by_forecast_update",
        ResolutionKind.MATERIAL_CHANGE: "resolved_by_forecast_update",
        ResolutionKind.SCORE: "resolved_by_resolution",
        ResolutionKind.POSTMORTEM: "resolved_by_resolution",
    }
    ledger.acknowledge_alert(
        warning.id,
        acknowledged_at=now,
        disposition=dispositions.get(kind, "not_actionable"),
    )
    return _result(
        warning,
        status="resolved",
        acknowledged=True,
        detail="gated action succeeded — alert acknowledged",
        runner_result=outcome,
    )
