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
from typing import Any, Callable, Iterator, Optional

from forecasting.models import AlertEvent

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
]


class ResolutionKind(enum.Enum):
    """How an open warning *can* be resolved (if at all)."""

    REFORECAST = "reforecast"        # stale / missing / new evidence / close-soon → re-run the forecast
    MATERIAL_CHANGE = "material_change"  # a watched source moved / trigger fired → check the source + reforecast
    SCORE = "score"                  # resolved question due a Brier score → real scoring work
    POSTMORTEM = "postmortem"        # resolved+scored question due a postmortem (score + write-up)
    BOOKKEEPING = "bookkeeping"      # informational notice; acking it is the correct close-out
    NO_AUTO = "no_auto"              # no safe auto-fix; surface for a human, never auto-resolve


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
)

_MATERIAL_PREFIXES = (
    "watched_source_changed",
    "watched_source_unavailable",
    "trigger_fired",         # trigger_fired:fred:DGS10 — a watched indicator crossed a threshold
)

_BOOKKEEPING_PREFIXES = (
    "autopilot_enabled",
    "autopilot_source_failed",
    "review_due",
)

_REFORECAST_PREFIXES = (
    "evidence_stale",        # evidence_stale_7d_plus, etc.
    "last_update",           # last_update_* staleness
    "new_evidence",          # new_evidence:*
    "no_evidence",
    "no_forecast_snapshot",
    "close_time_within",     # close_time_within_*
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

    # 6. REFORECAST — staleness / missing-evidence / new-evidence / close-soon.
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
    ResolutionKind.REFORECAST: 1,
    ResolutionKind.SCORE: 2,
    ResolutionKind.POSTMORTEM: 3,
    ResolutionKind.NO_AUTO: 4,
    ResolutionKind.BOOKKEEPING: 5,
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

    @property
    def is_auto_resolvable(self) -> bool:
        return self.kind is not ResolutionKind.NO_AUTO


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


def select_open_warnings(
    ledger: Any,
    *,
    scope: str | None = None,
    reason: str | None = None,
    limit: int | None = None,
) -> list[NormalizedWarning]:
    """Return the open backlog (priority order) after the common scope/reason/limit
    filters every driver (CLI, cron phase, gateway, tool) applies identically.

    ``reason`` is a case-insensitive substring filter; ``limit`` caps how many
    alerts are returned (NOT how many reason-groups). Kept in one place so the
    automode loop, the dry-run plan, and the list summary can never drift apart.
    """
    reason_filter = (reason or "").strip().lower()
    warnings = list(iter_warnings(ledger, scope=scope))
    if reason_filter:
        warnings = [w for w in warnings if reason_filter in (w.reason or "").lower()]
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
    autopilot_runner: Optional[Runner] = None    # MATERIAL_CHANGE
    score_runner: Optional[Runner] = None        # SCORE (score the resolved question)
    postmortem_runner: Optional[Runner] = None   # POSTMORTEM (score + write the postmortem)


_KIND_RUNNER_ATTR = {
    ResolutionKind.REFORECAST: "reforecast_runner",
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
    if kind is ResolutionKind.NO_AUTO:
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

    # NO_AUTO: surface, never ack.
    if kind is ResolutionKind.NO_AUTO:
        return _result(
            warning,
            status="surfaced",
            acknowledged=False,
            detail=_surfaced_detail(warning),
        )

    # BOOKKEEPING: informational notice; acking is the correct close-out.
    if kind is ResolutionKind.BOOKKEEPING:
        ledger.acknowledge_alert(warning.id, acknowledged_at=now)
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
    ledger.acknowledge_alert(warning.id, acknowledged_at=now)
    return _result(
        warning,
        status="resolved",
        acknowledged=True,
        detail="gated action succeeded — alert acknowledged",
        runner_result=outcome,
    )
