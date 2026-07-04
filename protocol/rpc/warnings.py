"""Wire models for the ``forecast.warnings.*`` RPC family (Arc A3).

Transcribed faithfully from the SERVER's actual emission —
``forecasting/warnings.py`` (``summarize_open_warnings`` / ``fold_warning_groups`` /
``resolve_alert``) and the ``forecast.warnings.{list,aggregate,resolve,dismiss}``
handlers in ``tui_gateway/server.py`` — and cross-checked against the hand-written
mirrors in ``ui-tui/src/gatewayTypes.ts``. The ``TS_NAME`` of each model equals the
mirror's interface name so the generated type is a drop-in replacement.

Modelling choices (documented per the arc's "pragmatic big-payload" rule):
* Response models are ``extra='ignore'`` tolerant (the ``WireModel`` default): the
  server's dict is the source of truth and the gateway wrapper VALIDATES but never
  re-serialises the forecast family (it returns the original result untouched), so
  a richer real frame validates and the wire can never regress.
* Optional keys use ``wire_optional()`` (``field?: T``); keys that may be absent OR
  ``null`` use ``wire_optional(nullable=True)`` (``field?: null | T``) — matching the
  mirrors field-for-field. The group members ARE always emitted server-side, but the
  mirror typed them optional; we preserve the mirror's permissive shape (no consumer
  breaks, and validation stays tolerant).

``forecast.warnings.automode.run`` is an Arc-B ALIAS handled by
``tui_gateway/jobs_rpc.py`` over the detached-job runtime; its trivial response is
modelled + registered here only so the TUI references a generated type.
"""

from __future__ import annotations

from typing import Any

from protocol.types import WireModel, wire_optional


# ── forecast.warnings.list ────────────────────────────────────────────────────


class ForecastWarningGroup(WireModel):
    TS_NAME = "ForecastWarningGroup"

    reason: str | None = wire_optional()
    kind: str | None = wire_optional()
    severity: str | None = wire_optional()
    recommended_action: str | None = wire_optional()
    auto_resolvable: bool | None = wire_optional()
    count: int | None = wire_optional()
    scope_refs: list[str] | None = wire_optional()


class ForecastWarningsListRequest(WireModel):
    TS_NAME = "ForecastWarningsListRequest"

    scope: str | None = None
    reason: str | None = None
    limit: int | None = None


class ForecastWarningsListResponse(WireModel):
    TS_NAME = "ForecastWarningsListResponse"

    groups: list[ForecastWarningGroup] | None = wire_optional()
    group_count: int | None = wire_optional()
    open_total: int | None = wire_optional()


# ── forecast.warnings.aggregate ───────────────────────────────────────────────


class ForecastWarningsTier(WireModel):
    TS_NAME = "ForecastWarningsTier"

    total: int | None = wire_optional()
    reasons: list[ForecastWarningGroup] | None = wire_optional()


class ForecastWarningsAgentTier(WireModel):
    """The agent tier + its ``stale`` sub-bucket (a view over the tier, not a
    fourth tier). Modelled flat (no TS ``extends``) — the fields match the mirror."""

    TS_NAME = "ForecastWarningsAgentTier"

    total: int | None = wire_optional()
    reasons: list[ForecastWarningGroup] | None = wire_optional()
    stale: ForecastWarningsTier | None = wire_optional()


class ForecastWarningsHeadline(WireModel):
    TS_NAME = "ForecastWarningsHeadline"

    total: int | None = wire_optional()
    free: int | None = wire_optional()
    agent: int | None = wire_optional()
    manual: int | None = wire_optional()


class ForecastWarningsAggregateRequest(WireModel):
    TS_NAME = "ForecastWarningsAggregateRequest"

    scope: str | None = None
    reason: str | None = None


class ForecastWarningsAggregateResponse(WireModel):
    TS_NAME = "ForecastWarningsAggregateResponse"

    headline: ForecastWarningsHeadline | None = wire_optional()
    free: ForecastWarningsTier | None = wire_optional()
    agent: ForecastWarningsAgentTier | None = wire_optional()
    manual: ForecastWarningsTier | None = wire_optional()


# ── forecast.warnings.resolve ─────────────────────────────────────────────────


class ForecastWarningResolveResult(WireModel):
    TS_NAME = "ForecastWarningResolveResult"

    alert_id: str | None = wire_optional()
    reason: str | None = wire_optional()
    scope_ref: str | None = wire_optional()
    kind: str | None = wire_optional()
    status: str | None = wire_optional()
    acknowledged: bool | None = wire_optional()
    detail: str | None = wire_optional()


class ForecastWarningsResolveRequest(WireModel):
    TS_NAME = "ForecastWarningsResolveRequest"

    alert_id: str | None = None
    now: str | None = None


class ForecastWarningsResolveResponse(WireModel):
    TS_NAME = "ForecastWarningsResolveResponse"

    results: list[ForecastWarningResolveResult] | None = wire_optional()
    count: int | None = wire_optional()


# ── forecast.warnings.dismiss ─────────────────────────────────────────────────


class ForecastWarningDismissedItem(WireModel):
    TS_NAME = "ForecastWarningDismissedItem"

    alert_id: str | None = wire_optional()
    reason: str | None = wire_optional()
    scope_ref: str | None = wire_optional()
    dismissed_at: str | None = wire_optional()
    dismiss_note: str | None = wire_optional()
    dismiss_actor: str | None = wire_optional()
    dismiss_reason: str | None = wire_optional()
    dismiss_ttl_days: int | None = wire_optional()


class ForecastWarningsDismissRequest(WireModel):
    TS_NAME = "ForecastWarningsDismissRequest"

    note: str | None = None
    actor: str | None = None
    scope: str | None = None
    reason: str | None = None
    kind: Any | None = None
    kinds: Any | None = None
    alert_id: str | None = None
    alert_ids: list[str] | None = None
    ttl_days: int | None = None
    now: str | None = None


class ForecastWarningsDismissResponse(WireModel):
    TS_NAME = "ForecastWarningsDismissResponse"

    dismissed: list[ForecastWarningDismissedItem] | None = wire_optional()
    count: int | None = wire_optional()
    matched: int | None = wire_optional()


# ── forecast.warnings.automode.run (Arc-B alias; jobs_rpc owns the handler) ────


class ForecastWarningsAutomodeRunRequest(WireModel):
    TS_NAME = "ForecastWarningsAutomodeRunRequest"

    dry_run: bool | None = None
    session_id: str | None = None
    reason: str | None = None
    scope: str | None = None
    limit: int | None = None


class ForecastWarningsAutomodeRunResponse(WireModel):
    TS_NAME = "ForecastWarningsAutomodeRunResponse"

    job_id: str | None = wire_optional()
    dry_run: bool | None = wire_optional()


__all__ = [
    "ForecastWarningGroup",
    "ForecastWarningsListRequest",
    "ForecastWarningsListResponse",
    "ForecastWarningsTier",
    "ForecastWarningsAgentTier",
    "ForecastWarningsHeadline",
    "ForecastWarningsAggregateRequest",
    "ForecastWarningsAggregateResponse",
    "ForecastWarningResolveResult",
    "ForecastWarningsResolveRequest",
    "ForecastWarningsResolveResponse",
    "ForecastWarningDismissedItem",
    "ForecastWarningsDismissRequest",
    "ForecastWarningsDismissResponse",
    "ForecastWarningsAutomodeRunRequest",
    "ForecastWarningsAutomodeRunResponse",
]
