"""Theses domain (D8 carve — thesis/factor members, entities, aggregation).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns the whole THESIS surface:

* thesis-member CRUD (``add_thesis_member`` / ``remove_thesis_member`` /
  ``list_thesis_members`` / ``list_theses_for_member`` / ``theses_by_member``) +
  the belief helpers (``_belief_record`` / ``_thesis_member_belief``) and the
  ``_thesis_member_to_dict`` serializer;
* thesis-entity CRUD + weighting (``add_thesis_entity`` / ``set_entity_weight`` /
  ``remove_thesis_entity`` / ``list_thesis_entities`` / ``_normalize_entity_weights``
  / ``_compute_thesis_entities`` / ``_thesis_entity_to_dict``);
* correlation + event glue (``set_thesis_correlation`` / ``_thesis_correlation_matrix``
  / ``set_thesis_event`` / ``clear_thesis_event`` / ``_thesis_event_spec`` /
  ``_thesis_event_seed``);
* the aggregation engine — ``aggregate_thesis`` (with its Gaussian-copula event
  Monte-Carlo glue, run through ``forecasting.thesis``), ``_aggregate_factor`` (the
  factor-portfolio path), ``aggregate_all_theses``, the ``is_thesis`` / ``is_factor``
  predicates, and the member-commit re-aggregate cascade
  (``_cascade_reaggregate_parents`` + ``_thesis_auto_aggregate_enabled``);
* the module-level narrative helpers (``_thesis_narrative`` / ``_factor_narrative`` /
  ``_thesis_reason_lines`` / ``_thesis_member_label`` / ``_entity_stance`` /
  ``_thesis_entity_triggers``) that turn an aggregation into desk prose.

Each ``ForecastLedger`` method takes the instance first; ``core`` keeps a one-line
delegate per method so no caller changed. The module-level narratives + constants
move OUTRIGHT (no delegate — they were bare-name module fns).

Dependency direction (no cycle, per the D1 finding): this leaf owns its three
leaf-exclusive module names (``_CASCADE_TLS`` thread-local, ``THESIS_MEMBER_ROLES``
— re-exported on the package surface via ``__init__`` for parity —, and
``_THESIS_DEAD_STATUS``) and imports only ``forecasting.models`` + stdlib at load
time. It has NO load-time dependency on ``core`` and needs NO ``_core.`` hop and
NO write-gate import: the thesis tables are UNGATED, and the aggregation commit
path reaches ``create_snapshot`` (which owns the gate) + ``add_analyst_note`` /
``get_question`` / ``get_current_snapshot`` / ``list_questions`` through the
``ledger`` INSTANCE at call time. ``forecasting.thesis`` (the pure aggregation
math) is imported LOCALLY inside the methods that use it, so it travels with them.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
import uuid
from typing import Any

from forecasting.models import (
    LedgerNotFoundError,
    OutcomeSpace,
    ValidationError,
    json_dumps,
    json_loads,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

# Thread-local visited-set for the thesis/factor re-aggregate cascade. Module-
# level + thread-local so concurrent member commits (e.g. a shared ForecastLedger
# across the gateway's RPC thread pool) each get their OWN cycle guard, while the
# synchronous recursion within one commit still shares it. Avoids the race a plain
# instance attribute would have if a ledger were ever shared across threads.
_CASCADE_TLS = threading.local()

# Semantic roles a thesis member plays in the aggregate — so a thesis reads as
# decision intelligence (which signal LEADS, which is the BOTTLENECK, which is
# market VALIDATION) rather than an undifferentiated weighted pool.
THESIS_MEMBER_ROLES = {
    "leading_indicator",   # moves early, before the thesis resolves
    "confirming_signal",   # corroborates the thesis once underway
    "bottleneck_signal",   # a gating constraint the thesis depends on
    "market_validation",   # a market/price signal validating the thesis
    "disconfirming_signal",  # would cut against the thesis if it moves
}


_THESIS_DEAD_STATUS = {"stale", "missing", "unusable"}


def _thesis_member_label(component: dict[str, Any]) -> str:
    return str(component.get("title") or component.get("member_id") or "member")


def _thesis_reason_lines(agg: Any, kind: str) -> list[str]:
    """Top member contributions, as 'support' (lifting) or 'drag' (pulling down) lines."""

    usable = [
        c for c in agg.components
        if c.get("status") not in _THESIS_DEAD_STATUS and (c.get("w_norm") or 0) > 0
    ]
    if kind == "support":
        rows = sorted(
            (c for c in usable if float(c.get("s_i") or 0) >= 0.5),
            key=lambda c: -(float(c.get("contribution_pts") or 0)),
        )
    else:
        rows = sorted(
            (c for c in usable if float(c.get("s_i") or 0) < 0.5),
            key=lambda c: float(c.get("s_i") or 0),
        )
    lines: list[str] = []
    for c in rows[:4]:
        lines.append(
            f"{_thesis_member_label(c)}: signal {float(c.get('s_i') or 0):.0%}, "
            f"weight {float(c.get('w_norm') or 0):.0%}"
        )
    return lines


def _thesis_narrative(thesis: Any, agg: Any, event: Any = None) -> tuple[str, str, str, str, str]:
    """Build the rolling analyst note (headline, how_it_thinks, looking_for, be_aware, body)."""

    health = agg.health
    score = agg.thesis_score or 0.0
    # When a joint-event probability exists it is THE headline (the question the
    # thesis actually asks); the mean-index health becomes a diagnostic.
    has_event = event is not None and getattr(event, "event_probability", None) is not None
    if has_event:
        ev = event.event_probability
        kind = event.event.get("kind")
        k = event.event.get("threshold")
        label = f"≥{k} of {event.participants}" if kind == "count_threshold" else str(kind)
        headline = f"{thesis.title} — P(event) {ev:.0%} ({label})"
    elif health is not None:
        headline = f"{thesis.title} — health {health:.0%}"
    else:
        headline = f"{thesis.title} — withheld"

    usable = [c for c in agg.components if c.get("status") not in _THESIS_DEAD_STATUS]
    top = sorted(usable, key=lambda c: -(float(c.get("contribution_pts") or 0)))[:3]
    drivers = ", ".join(f"{_thesis_member_label(c)} ({float(c.get('s_i') or 0):.0%})" for c in top)
    how_it_thinks = (
        f"Weighted across {len(usable)} fresh member(s); score {score:.0f}/100."
        + (f" Top drivers: {drivers}." if drivers else "")
    )
    if has_event:
        cd = event.count_distribution or {}
        mean_ct = cd.get("mean")
        movers = event.top_sensitivities(1)
        biggest = movers[0] if movers else None
        parts_ev = [
            f"Event P={event.event_probability:.0%} via Gaussian-copula MC "
            f"({event.n_draws} draws, rho {event.rho:.2f})"
        ]
        if mean_ct is not None:
            parts_ev.append(
                f"expected count ~{mean_ct:.1f} (p10-p90 {cd.get('p10', 0):.0f}-{cd.get('p90', 0):.0f})"
            )
        if biggest is not None:
            parts_ev.append(
                f"biggest swing: {biggest.get('title') or biggest.get('member_id')} "
                f"(±2pp ⇒ {biggest.get('delta_p_event', 0.0):+.1%} on P)"
            )
        how_it_thinks += " " + "; ".join(parts_ev) + "."

    contested = [c for c in usable if abs(float(c.get("s_i") or 0.5) - 0.5) < 0.2]
    contested.sort(key=lambda c: abs(float(c.get("s_i") or 0.5) - 0.5))
    looking_for = (
        "; ".join(f"{_thesis_member_label(c)} is contested ({float(c.get('s_i') or 0):.0%})" for c in contested[:2])
        or "No single member is decisively contested."
    )

    stale = [c for c in agg.components if c.get("status") in {"stale", "missing"}]
    parts = [
        f"coverage {agg.coverage:.0%}",
        f"n_eff ~{agg.n_eff:.1f} of {len(agg.components)} (members co-move; rho {agg.rho:.2f})",
    ]
    if stale:
        parts.append(f"{len(stale)} member(s) stale/missing and down-weighted")
    be_aware = "; ".join(parts) + (("; " + "; ".join(agg.notes)) if agg.notes else "")

    body = f"{headline}. {how_it_thinks} Watching: {looking_for} Caveats: {be_aware}."
    return headline, how_it_thinks, looking_for, be_aware, body


def _entity_stance(
    suitability: float | None, delta: float | None, threshold: float | None = None
) -> tuple[str, str]:
    """Map an entity's 0..1 suitability + its move into a stance + trend.

    Generic across thesis kinds: a stock 'overweight', a candidate 'frontrunner',
    a currency 'long' all share the same suitability ladder. The optional
    per-entity ``threshold`` raises the overweight bar.
    """

    if suitability is None:
        return ("WITHHELD", "flat")
    over = threshold if (isinstance(threshold, (int, float)) and threshold > 0) else 0.65
    if suitability >= over:
        stance = "OVERWEIGHT"
    elif suitability >= 0.55:
        stance = "ADD"
    elif suitability >= 0.45:
        stance = "NEUTRAL"
    elif suitability >= 0.35:
        stance = "TRIM"
    else:
        stance = "UNDERWEIGHT"
    move = delta or 0.0
    trend = "rising" if move > 0.01 else "falling" if move < -0.01 else "flat"
    return (stance, trend)


def _thesis_entity_triggers(
    member_deltas: dict[str, float],
    entities: list[dict[str, Any]],
    member_map: dict[str, dict[str, Any]],
    *,
    min_move: float = 0.05,
) -> list[dict[str, Any]]:
    """The §10 "if signal X moves -> entities Y better/less suited" lines, generic.

    For each member signal that moved at least ``min_move`` since the prior
    aggregation, ranks the entities weighting it and splits them into helped vs
    hurt by the move's direction × the entity's weight direction.
    """

    triggers: list[dict[str, Any]] = []
    for member_id, delta in member_deltas.items():
        if abs(delta) < min_move:
            continue
        better: list[tuple[float, str]] = []
        less: list[tuple[float, str]] = []
        for entity in entities:
            for weight in entity.get("weights", []):
                if weight.get("member_id") != member_id or float(weight.get("weight", 0)) <= 0:
                    continue
                effect = (1 if delta > 0 else -1) * (1 if weight.get("direction", "support") == "support" else -1)
                (better if effect > 0 else less).append((float(weight.get("weight", 0)), entity.get("name", "?")))
                break
        if not better and not less:
            continue
        better.sort(reverse=True)
        less.sort(reverse=True)
        better_names = [name for _, name in better][:8]
        less_names = [name for _, name in less][:8]
        member = member_map.get(member_id, {})
        signal = member.get("member_title") or member.get("role") or member_id
        parts: list[str] = []
        if better_names:
            parts.append(f"{', '.join(better_names)} better suited")
        if less_names:
            parts.append(f"{', '.join(less_names)} less suited")
        triggers.append(
            {
                "member_id": member_id,
                "signal": signal,
                "delta": delta,
                "direction": "up" if delta > 0 else "down",
                "note": f"{signal} {'▲' if delta > 0 else '▼'} {delta * 100:+.0f}pp → " + "; ".join(parts),
                "better": better_names,
                "less": less_names,
            }
        )
    triggers.sort(key=lambda trigger: -abs(trigger["delta"]))
    return triggers


def _factor_narrative(factor: Any, agg: Any) -> tuple[str, str, str, str, str]:
    """Rolling note for a factor: basket return + volatility + downside (plain
    units; the factor question's `units` supply the scale for display)."""

    mean = agg.mean if agg.mean is not None else 0.0
    sd = agg.sd
    headline = (
        f"{factor.title} — μ {mean:.2f} · vol {sd:.2f}" if sd is not None else f"{factor.title} — μ {mean:.2f}"
    )
    usable = [c for c in agg.components if c.get("status") not in _THESIS_DEAD_STATUS]
    top = sorted(usable, key=lambda c: -abs(c.get("contribution") or 0))[:3]
    drivers = ", ".join(
        f"{(c.get('title') or c.get('member_id'))} ({(c.get('contribution') or 0):+.2f})" for c in top
    )
    how_it_thinks = (
        f"Weighted basket of {len(usable)} constituent return distribution(s)."
        + (f" Top contributors: {drivers}." if drivers else "")
    )
    looking_for = (
        f"90% return band {agg.q05:.2f} to {agg.q95:.2f}."
        if (agg.q05 is not None and agg.q95 is not None)
        else "Awaiting dispersion."
    )
    parts = [
        f"coverage {agg.coverage:.0%}",
        f"n_eff ~{agg.n_eff:.1f} of {len(agg.components)} (constituents co-move; rho {agg.rho:.2f})",
    ]
    if agg.downside is not None:
        parts.append(f"downside(5%) {agg.downside:.2f}")
    if agg.cvar is not None:
        parts.append(f"CVaR {agg.cvar:.2f}")
    be_aware = "; ".join(parts) + (("; " + "; ".join(agg.notes)) if agg.notes else "")
    body = f"{headline}. {how_it_thinks} {looking_for} Caveats: {be_aware}."
    return headline, how_it_thinks, looking_for, be_aware, body


def _thesis_auto_aggregate_enabled(ledger, thesis_id: str) -> bool:
    """Per-thesis opt-out of the member-commit re-aggregate cascade
    (metadata.forecast_hooks.auto_aggregate = false)."""
    try:
        q = ledger.get_question(thesis_id)
        meta = (getattr(q, "metadata", None) or {}).get("forecast_hooks") or {}
        return meta.get("auto_aggregate", True) is not False
    except Exception:
        return True


def _cascade_reaggregate_parents(ledger, member_id: str, *, as_of: str | None = None) -> None:
    """Re-aggregate every parent thesis/factor of a just-committed member so
    their stored member contributions + health track the live members
    (``aggregate_thesis`` auto-dispatches to the factor portfolio math, so one
    call covers both). Each parent's own aggregate commit re-enters this method
    via ``create_snapshot``, freshening grandparents up the DAG; a
    per-top-commit visited-set bounds the work and breaks cycles. Fail-open: a
    cascade error never breaks the member commit. Disable globally with
    ``FORECAST_DISABLE_THESIS_CASCADE``."""
    from forecasting import appconfig

    if appconfig.get_bool("FORECAST_DISABLE_THESIS_CASCADE"):
        return
    try:
        parents = ledger.list_theses_for_member(member_id)
    except Exception:
        return
    if not parents:
        return
    visited = getattr(_CASCADE_TLS, "visited", None)
    top = visited is None
    if top:
        visited = set()
        _CASCADE_TLS.visited = visited
    try:
        for parent in parents:
            pid = parent.get("thesis_id")
            if not pid or pid == member_id or pid in visited:
                continue
            visited.add(pid)
            if not ledger._thesis_auto_aggregate_enabled(pid):
                continue
            try:
                # analyst_note=False: a member move must not spam the parent's
                # analyst log with a re-aggregation brief on every commit.
                ledger.aggregate_thesis(pid, now=as_of, analyst_note=False)
            except Exception:
                logger.debug("thesis/factor cascade re-aggregate failed for parent %s", pid, exc_info=True)
    finally:
        if top:
            _CASCADE_TLS.visited = None


def is_thesis(ledger, question: Any) -> bool:
    """True when ``question`` (object or id) is a thesis question."""

    if isinstance(question, str):
        try:
            question = ledger.get_question(question)
        except LedgerNotFoundError:
            return False
    return getattr(question.outcome_space, "type", None) == "thesis"


def is_factor(ledger, question: Any) -> bool:
    """True when ``question`` is a FACTOR — a thesis whose members are a
    weighted basket of return distributions aggregated by portfolio math
    (mean/vol/downside) rather than the health-signal pool. Marked by
    ``metadata['aggregation'] == 'factor'`` so it reuses the thesis
    membership table, run-all, and cron wholesale."""

    if isinstance(question, str):
        try:
            question = ledger.get_question(question)
        except LedgerNotFoundError:
            return False
    if not ledger.is_thesis(question):
        return False
    meta = question.metadata if isinstance(question.metadata, dict) else {}
    return str(meta.get("aggregation") or "").lower() == "factor"


def _thesis_member_to_dict(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = json_loads(data.get("metadata"), {})
    data["hi_is_good"] = bool(data.get("hi_is_good", 1))
    return data


def add_thesis_member(
    ledger,
    thesis_id: str,
    member_id: str,
    *,
    direction: str = "support",
    weight: float = 1.0,
    role: str | None = None,
    target: float | None = None,
    hi_is_good: bool = True,
    max_age_days: float | None = None,
    rationale: str = "",
    created_by: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Tag ``member_id`` to the thesis ``thesis_id``. Upsert on (thesis, member)."""

    thesis = ledger.get_question(thesis_id)
    ledger.get_question(member_id)
    if not ledger.is_thesis(thesis):
        raise ValidationError("thesis_id must reference a question with outcome type 'thesis'")
    if thesis_id == member_id:
        raise ValidationError("a thesis cannot be a member of itself")
    if direction not in {"support", "inverted"}:
        raise ValidationError("direction must be 'support' or 'inverted'")
    if role is not None and role.strip() and role not in THESIS_MEMBER_ROLES:
        raise ValidationError("role must be one of: " + ", ".join(sorted(THESIS_MEMBER_ROLES)))
    if weight < 0:
        raise ValidationError("weight must be non-negative")
    with ledger._connect() as conn:
        existing = conn.execute(
            "SELECT id FROM thesis_members WHERE thesis_question_id = ? AND member_question_id = ?",
            (thesis_id, member_id),
        ).fetchone()
        if existing is not None:
            conn.execute(
                """
                UPDATE thesis_members SET direction = ?, weight = ?, role = ?, target = ?,
                    hi_is_good = ?, max_age_days = ?, rationale = ?, metadata = ?
                WHERE id = ?
                """,
                (
                    direction,
                    float(weight),
                    role,
                    target,
                    1 if hi_is_good else 0,
                    max_age_days,
                    rationale,
                    json_dumps(metadata or {}),
                    existing["id"],
                ),
            )
            member_pk = existing["id"]
        else:
            member_pk = f"tm_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO thesis_members (
                    id, thesis_question_id, member_question_id, direction, weight,
                    role, target, hi_is_good, max_age_days, rationale, created_by,
                    created_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    member_pk,
                    thesis_id,
                    member_id,
                    direction,
                    float(weight),
                    role,
                    target,
                    1 if hi_is_good else 0,
                    max_age_days,
                    rationale,
                    created_by,
                    utc_now_iso(),
                    json_dumps(metadata or {}),
                ),
            )
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM thesis_members WHERE id = ?", (member_pk,)).fetchone()
    return ledger._thesis_member_to_dict(row)


def remove_thesis_member(ledger, thesis_id: str, member_id: str) -> int:
    """Untag a member from a thesis. Returns the number of rows removed."""

    with ledger._connect() as conn:
        cur = conn.execute(
            "DELETE FROM thesis_members WHERE thesis_question_id = ? AND member_question_id = ?",
            (thesis_id, member_id),
        )
        return int(cur.rowcount or 0)


def list_thesis_members(ledger, thesis_id: str) -> list[dict[str, Any]]:
    """Members of a thesis, joined with each member's title + outcome type."""

    with ledger._connect() as conn:
        rows = conn.execute(
            """
            SELECT tm.*, q.title AS member_title, q.outcome_space AS member_outcome_space,
                   q.status AS member_status
            FROM thesis_members tm
            JOIN forecast_questions q ON q.id = tm.member_question_id
            WHERE tm.thesis_question_id = ?
            ORDER BY tm.weight DESC, tm.created_at ASC
            """,
            (thesis_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = ledger._thesis_member_to_dict(row)
        data["member_outcome_type"] = OutcomeSpace.from_json(data.pop("member_outcome_space", None)).type
        out.append(data)
    return out


def list_theses_for_member(ledger, member_id: str) -> list[dict[str, Any]]:
    """The theses a member belongs to (for the 'member of …' badge)."""

    with ledger._connect() as conn:
        rows = conn.execute(
            """
            SELECT tm.thesis_question_id AS thesis_id, tm.direction, tm.weight, tm.role,
                   q.title AS thesis_title
            FROM thesis_members tm
            JOIN forecast_questions q ON q.id = tm.thesis_question_id
            WHERE tm.member_question_id = ?
            ORDER BY q.title ASC
            """,
            (member_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def theses_by_member(ledger, member_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """member_id -> theses it belongs to (batched ``list_theses_for_member``).

    Collapses the per-member N+1 the desk's workspace payload used to fire
    (one ``list_theses_for_member`` connection per member question) into a
    single chunked query, mirroring ``snapshots_by_question`` /
    ``evidence_by_question``. Each absent member defaults to ``[]`` — the
    exact value the singular method produces for a non-member."""
    out: dict[str, list[dict[str, Any]]] = {}
    for chunk in ledger._chunk_ids(member_ids):
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        with ledger._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT tm.member_question_id AS member_id,
                       tm.thesis_question_id AS thesis_id, tm.direction, tm.weight, tm.role,
                       q.title AS thesis_title
                FROM thesis_members tm
                JOIN forecast_questions q ON q.id = tm.thesis_question_id
                WHERE tm.member_question_id IN ({placeholders})
                ORDER BY tm.member_question_id ASC, q.title ASC
                """,
                chunk,
            ).fetchall()
        for row in rows:
            data = dict(row)
            mid = data.pop("member_id")
            out.setdefault(mid, []).append(data)
    return out


def _belief_record(
    ledger,
    member_id: str,
    *,
    direction: str = "support",
    weight: float = 1.0,
    target: float | None = None,
    hi_is_good: bool = True,
    max_age_days: float | None = None,
    title: str | None = None,
    outcome_type: str | None = None,
) -> dict[str, Any]:
    """Resolve one question's current belief into the input dict that
    :func:`forecasting.thesis.aggregate_thesis` consumes. Shared by thesis
    membership AND per-entity weight vectors (the suitability layer reuses
    the exact same 0..1-signal reduction, just with a different weight set)."""

    # Lazy import: dashboard imports the ledger, so importing it at module
    # scope would be circular.
    from forecasting.dashboard import _distribution_view

    if outcome_type is None or title is None:
        try:
            question = ledger.get_question(member_id)
            outcome_type = outcome_type or question.outcome_space.type
            title = title or question.title
        except LedgerNotFoundError:
            outcome_type = outcome_type or "binary"
    snapshot = ledger.get_current_snapshot(member_id)
    belief = snapshot.probability_or_distribution if snapshot else None
    record: dict[str, Any] = {
        "member_id": member_id,
        "title": title,
        "direction": direction,
        "weight": float(weight),
        "as_of": snapshot.as_of if snapshot else None,
        "max_age_days": max_age_days,
        "target": target,
        "hi_is_good": bool(hi_is_good),
        "probability": None,
        "dist": None,
    }
    if belief is None:
        record["kind"] = "binary"  # unusable -> flagged missing downstream
    elif outcome_type == "binary" and isinstance(belief, (int, float)):
        record["kind"] = "binary"
        record["probability"] = float(belief)
    elif isinstance(belief, dict):
        record["kind"] = "distribution"
        record["dist"] = _distribution_view(belief) or {"mean": None}
    elif isinstance(belief, (int, float)):
        record["kind"] = "distribution"
        record["dist"] = {"mean": float(belief)}
    else:
        record["kind"] = "binary"  # unrecognized -> unusable
    return record


def _thesis_member_belief(ledger, member: dict[str, Any]) -> dict[str, Any]:
    """Resolve a membership row into the input dict that thesis.aggregate_thesis wants."""

    return ledger._belief_record(
        member["member_question_id"],
        direction=member.get("direction", "support"),
        weight=float(member.get("weight", 1.0)),
        target=member.get("target"),
        hi_is_good=bool(member.get("hi_is_good", True)),
        max_age_days=member.get("max_age_days"),
        title=member.get("member_title"),
        outcome_type=member.get("member_outcome_type") or "binary",
    )


def _thesis_entity_to_dict(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["weights"] = json_loads(data.get("weights"), [])
    data["metadata"] = json_loads(data.get("metadata"), {})
    return data


def _normalize_entity_weights(ledger, weights: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for weight in weights or []:
        if not isinstance(weight, dict):
            raise ValidationError("entity weight must be an object")
        member_id = str(weight.get("member_id") or "").strip()
        if not member_id:
            raise ValidationError("entity weight requires a member_id")
        ledger.get_question(member_id)  # must reference a real question
        direction = str(weight.get("direction") or "support")
        if direction not in {"support", "inverted"}:
            raise ValidationError("entity weight direction must be 'support' or 'inverted'")
        value = float(weight.get("weight", 1.0))
        if value < 0:
            raise ValidationError("entity weight must be non-negative")
        entry: dict[str, Any] = {"member_id": member_id, "weight": value, "direction": direction}
        if weight.get("role"):
            entry["role"] = str(weight["role"])
        if weight.get("hi_is_good") is not None:
            entry["hi_is_good"] = bool(weight["hi_is_good"])
        if weight.get("target") is not None:
            entry["target"] = float(weight["target"])
        out.append(entry)
    return out


def add_thesis_entity(
    ledger,
    thesis_id: str,
    name: str,
    *,
    label: str | None = None,
    kind: str = "entity",
    weights: Any = None,
    action_threshold: float | None = None,
    created_by: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register an entity under a thesis with a weighted signal vector. Upsert on (thesis, name)."""

    thesis = ledger.get_question(thesis_id)
    if not ledger.is_thesis(thesis):
        raise ValidationError("thesis_id must reference a question with outcome type 'thesis'")
    name = (name or "").strip()
    if not name:
        raise ValidationError("entity name is required")
    normalized = ledger._normalize_entity_weights(weights)
    with ledger._connect() as conn:
        existing = conn.execute(
            "SELECT id FROM thesis_entities WHERE thesis_question_id = ? AND name = ?",
            (thesis_id, name),
        ).fetchone()
        if existing is not None:
            conn.execute(
                "UPDATE thesis_entities SET label = ?, kind = ?, weights = ?, action_threshold = ?, metadata = ? WHERE id = ?",
                (label, kind, json_dumps(normalized), action_threshold, json_dumps(metadata or {}), existing["id"]),
            )
            entity_id = existing["id"]
        else:
            entity_id = f"te_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO thesis_entities (
                    id, thesis_question_id, name, label, kind, weights,
                    action_threshold, created_by, created_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id,
                    thesis_id,
                    name,
                    label,
                    kind,
                    json_dumps(normalized),
                    action_threshold,
                    created_by,
                    utc_now_iso(),
                    json_dumps(metadata or {}),
                ),
            )
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM thesis_entities WHERE id = ?", (entity_id,)).fetchone()
    return ledger._thesis_entity_to_dict(row)


def set_entity_weight(
    ledger,
    thesis_id: str,
    name: str,
    member_id: str,
    *,
    weight: float = 1.0,
    direction: str = "support",
    hi_is_good: bool = True,
    target: float | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """Add/replace a single signal weight on an entity (creates the entity if new)."""

    entities = {e["name"]: e for e in ledger.list_thesis_entities(thesis_id)}
    existing = entities.get(name)
    kept = [w for w in (existing["weights"] if existing else []) if w.get("member_id") != member_id]
    entry: dict[str, Any] = {"member_id": member_id, "weight": float(weight), "direction": direction}
    if role:
        entry["role"] = role
    entry["hi_is_good"] = bool(hi_is_good)
    if target is not None:
        entry["target"] = float(target)
    kept.append(entry)
    return ledger.add_thesis_entity(
        thesis_id,
        name,
        label=(existing.get("label") if existing else None),
        kind=(existing.get("kind") if existing else "entity"),
        weights=kept,
        action_threshold=(existing.get("action_threshold") if existing else None),
        metadata=(existing.get("metadata") if existing else None),
    )


def remove_thesis_entity(ledger, thesis_id: str, name: str) -> int:
    with ledger._connect() as conn:
        cur = conn.execute(
            "DELETE FROM thesis_entities WHERE thesis_question_id = ? AND name = ?",
            (thesis_id, name),
        )
        return int(cur.rowcount or 0)


def list_thesis_entities(ledger, thesis_id: str) -> list[dict[str, Any]]:
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM thesis_entities WHERE thesis_question_id = ? ORDER BY name ASC",
            (thesis_id,),
        ).fetchall()
    return [ledger._thesis_entity_to_dict(row) for row in rows]


def _compute_thesis_entities(
    ledger,
    thesis_id: str,
    *,
    rho: float | str,
    now: str,
    member_map: dict[str, dict[str, Any]],
    current_components: list[dict[str, Any]],
    prev_components: list[dict[str, Any]],
    prev_entities: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Per-entity suitability (reusing the thesis aggregator) + trade triggers."""

    from forecasting import thesis as thesis_math

    entities = ledger.list_thesis_entities(thesis_id)
    if not entities:
        return [], []

    prev_suit = {e.get("name"): e.get("suitability") for e in (prev_entities or [])}
    out: list[dict[str, Any]] = []
    for entity in entities:
        records = []
        for weight in entity.get("weights", []):
            member_id = weight["member_id"]
            member = member_map.get(member_id, {})
            records.append(
                ledger._belief_record(
                    member_id,
                    direction=weight.get("direction", "support"),
                    weight=float(weight.get("weight", 1.0)),
                    target=weight["target"] if "target" in weight else member.get("target"),
                    hi_is_good=weight["hi_is_good"]
                    if "hi_is_good" in weight
                    else bool(member.get("hi_is_good", True)),
                    max_age_days=member.get("max_age_days"),
                    title=member.get("member_title"),
                    outcome_type=member.get("member_outcome_type"),
                )
            )
        agg = thesis_math.aggregate_thesis(records, rho=rho, now=now)
        suitability = agg.health
        previous = prev_suit.get(entity["name"])
        delta = (
            suitability - previous
            if (suitability is not None and isinstance(previous, (int, float)))
            else None
        )
        stance, trend = _entity_stance(suitability, delta, entity.get("action_threshold"))
        usable = [c for c in agg.components if c.get("status") not in _THESIS_DEAD_STATUS]
        top = max(usable, key=lambda c: abs(c.get("contribution_pts") or 0), default=None)
        out.append(
            {
                "name": entity["name"],
                "label": entity.get("label") or entity["name"],
                "kind": entity.get("kind", "entity"),
                "suitability": suitability,
                "suitability_display": f"{suitability:.0%}" if suitability is not None else "—",
                "score": agg.thesis_score,
                "band": list(agg.band) if agg.band else None,
                "coverage": agg.coverage,
                "n_eff": agg.n_eff,
                "delta": delta,
                "stance": stance,
                "trend": trend,
                "action": f"{stance} ({trend})" if suitability is not None else "withheld",
                "top_driver": top.get("title") if top else None,
                "top_driver_id": top.get("member_id") if top else None,
                "weight_count": len(entity.get("weights", [])),
                "contributions": agg.components,
            }
        )

    # Trade triggers: member-signal moves since the prior aggregation, mapped
    # through each entity's weight vector to "better/less suited" lines.
    cur_sig = {c.get("member_id"): c.get("s_raw") for c in current_components}
    prev_sig = {c.get("member_id"): c.get("s_raw") for c in (prev_components or [])}
    member_deltas: dict[str, float] = {}
    for member_id, signal in cur_sig.items():
        previous_signal = prev_sig.get(member_id)
        if isinstance(signal, (int, float)) and isinstance(previous_signal, (int, float)):
            member_deltas[member_id] = signal - previous_signal
    triggers = _thesis_entity_triggers(member_deltas, entities, member_map)
    return out, triggers


def _aggregate_factor(
    ledger,
    factor: Any,
    *,
    rho: float | str,
    now: str | None,
    commit: bool,
    analyst_note: bool = True,
) -> dict[str, Any]:
    """Portfolio-aggregate a factor's constituent return distributions."""

    from forecasting import factor as factor_math
    from forecasting.dashboard import _distribution_view

    members = ledger.list_thesis_members(factor.id)
    as_of = now or utc_now_iso()
    constituents: list[dict[str, Any]] = []
    for member in members:
        member_id = member["member_question_id"]
        snapshot = ledger.get_current_snapshot(member_id)
        belief = snapshot.probability_or_distribution if snapshot else None
        mean: float | None = None
        sd: float | None = None
        if isinstance(belief, dict):
            view = _distribution_view(belief) or {}
            mean = view.get("mean")
            sd = view.get("sd")
        elif isinstance(belief, (int, float)):
            mean = float(belief)
        constituents.append(
            {
                "member_id": member_id,
                "title": member.get("member_title"),
                "weight": float(member.get("weight", 1.0)),
                "direction": "short" if member.get("direction") == "inverted" else "long",
                "as_of": snapshot.as_of if snapshot else None,
                "max_age_days": member.get("max_age_days"),
                "mean": mean,
                "sd": sd,
            }
        )
    agg = factor_math.aggregate_factor(constituents, rho=rho, now=as_of)
    payload = agg.to_payload()
    result: dict[str, Any] = {
        "thesis_id": factor.id,
        "title": factor.title,
        "aggregate": agg,
        "payload": payload,
        "member_count": len(members),
        "is_factor": True,
        "entities": [],
        "triggers": [],
        "snapshot_id": None,
    }
    if not commit:
        return result
    if payload.get("factor_mean") is None:
        if analyst_note:
            note = ledger.add_analyst_note(
                question_id=factor.id,
                body="; ".join(agg.notes) or "withheld: no usable constituent",
                kind="brief",
                headline=f"{factor.title} — withheld (insufficient fresh constituents)",
                be_aware="; ".join(agg.notes),
                generator="factor_aggregate",
                metadata={"coverage": agg.coverage, "member_count": len(members)},
            )
            result["analyst_note_id"] = note.get("id")
        return result
    rationale = (
        f"Portfolio aggregate of {len(members)} constituent return distribution(s) "
        f"(coverage {agg.coverage:.0%}, vol {agg.sd:.3f}, n_eff {agg.n_eff:.1f}, rho {agg.rho:.2f}). "
        "Computed after the constituents' latest runs; not LLM-led."
    )
    snapshot = ledger.create_snapshot(
        question_id=factor.id,
        probability_or_distribution=payload,
        rationale=rationale,
        as_of=as_of,
        confidence=round(max(0.0, min(1.0, agg.coverage)), 3),
        method="factor_aggregate",
        style_autofix=True,  # deterministic fold: mechanically clean generated prose
        distribution_autofix=True,  # programmatic: auto-fix malformed bounds rather than block
        ensemble_components={
            "components": agg.components,
            "rho": agg.rho,
            "n_eff": agg.n_eff,
            "coverage": agg.coverage,
        },
        forecast_origin="live",
        calibration_eligible=False,
        metadata={"factor_notes": agg.notes, "aggregation": "factor"},
    )
    result["snapshot_id"] = snapshot.forecast_id
    if analyst_note:
        headline, how_it_thinks, looking_for, be_aware, body = _factor_narrative(factor, agg)
        note = ledger.add_analyst_note(
            question_id=factor.id,
            body=body,
            kind="brief",
            headline=headline,
            how_it_thinks=how_it_thinks,
            looking_for=looking_for,
            be_aware=be_aware,
            forecast_id=snapshot.forecast_id,
            probability_at_write=payload,
            confidence_at_write=round(max(0.0, min(1.0, agg.coverage)), 3),
            generator="factor_aggregate",
            metadata={"coverage": agg.coverage, "n_eff": agg.n_eff, "rho": agg.rho},
        )
        result["analyst_note_id"] = note.get("id")
    return result


def set_thesis_correlation(ledger, thesis_id: str, member_a: str, member_b: str, rho: float) -> dict[str, float]:
    """Pin a pairwise correlation between two thesis members so the aggregate's
    honest band + effective-N use real co-movement PER PAIR rather than one
    scalar rho (members co-move unequally). Stored on the thesis metadata;
    both ids must be members. Idempotent on the unordered pair. Returns the
    full correlation map."""
    thesis = ledger.get_question(thesis_id)
    if not ledger.is_thesis(thesis):
        raise ValidationError("set_thesis_correlation requires a question with outcome type 'thesis'")
    if member_a == member_b:
        raise ValidationError("a member cannot be correlated with itself")
    if "|" in member_a or "|" in member_b:
        # The pair is stored as "a|b"; a literal '|' in an id would corrupt the
        # key. System ids never contain it, but reject loudly rather than silently
        # dropping the correlation at load time.
        raise ValidationError("member ids must not contain '|'")
    member_ids = {m["member_question_id"] for m in ledger.list_thesis_members(thesis_id)}
    for mid in (member_a, member_b):
        if mid not in member_ids:
            raise ValidationError(f"{mid} is not a member of this thesis")
    rho_val = float(rho)
    if not (0.0 <= rho_val <= 0.95):
        raise ValidationError("correlation must be within [0, 0.95]")
    meta = dict(thesis.metadata) if isinstance(thesis.metadata, dict) else {}
    corr = dict(meta.get("thesis_correlations") or {})
    corr["|".join(sorted([member_a, member_b]))] = rho_val
    meta["thesis_correlations"] = corr
    with ledger._connect() as conn:
        conn.execute("UPDATE forecast_questions SET metadata = ? WHERE id = ?", (json_dumps(meta), thesis_id))
    return corr


def _thesis_correlation_matrix(ledger, thesis: Any) -> dict[frozenset[str], float] | None:
    """Load the stored pairwise correlations into the {member_a, member_b} ->
    rho map the aggregation math consumes. None when none are pinned."""
    meta = thesis.metadata if isinstance(thesis.metadata, dict) else {}
    raw = meta.get("thesis_correlations")
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[frozenset[str], float] = {}
    for key, value in raw.items():
        parts = str(key).split("|")
        if len(parts) == 2:
            try:
                out[frozenset(parts)] = float(value)
            except (TypeError, ValueError):
                continue
    return out or None


def set_thesis_event(
    ledger,
    thesis_id: str,
    *,
    kind: str = "count_threshold",
    threshold: int | None = None,
) -> dict[str, Any]:
    """Configure a thesis as a JOINT THRESHOLD EVENT — P(#member successes ≥ K).

    A thesis headline is otherwise a mean index (damped, threshold-insensitive).
    With an event spec, ``aggregate_thesis`` ALSO runs a Gaussian-copula Monte
    Carlo (seeded deterministically) and stamps ``event_probability`` — the way
    a "Democrats take back the Senate" question is really scored. Stored on the
    thesis metadata beside ``thesis_correlations``; pass ``threshold=None`` (any
    kind) to CLEAR it. Returns the stored spec.
    """
    thesis = ledger.get_question(thesis_id)
    if not ledger.is_thesis(thesis):
        raise ValidationError("set_thesis_event requires a question with outcome type 'thesis'")
    kind = str(kind).lower()
    if kind not in {"count_threshold", "all", "any"}:
        raise ValidationError("event kind must be 'count_threshold', 'all' or 'any'")
    spec: dict[str, Any] | None
    if kind == "count_threshold":
        if threshold is None:
            raise ValidationError("count_threshold event requires an integer 'threshold'")
        k = int(threshold)
        if k < 0:
            raise ValidationError("threshold must be non-negative")
        spec = {"kind": kind, "threshold": k}
    else:
        spec = {"kind": kind}
    meta = dict(thesis.metadata) if isinstance(thesis.metadata, dict) else {}
    meta["thesis_event"] = spec
    with ledger._connect() as conn:
        conn.execute("UPDATE forecast_questions SET metadata = ? WHERE id = ?", (json_dumps(meta), thesis_id))
    return spec


def clear_thesis_event(ledger, thesis_id: str) -> bool:
    """Remove a thesis's event spec (reverts to the mean-index headline). True if one was set."""
    thesis = ledger.get_question(thesis_id)
    if not ledger.is_thesis(thesis):
        raise ValidationError("clear_thesis_event requires a question with outcome type 'thesis'")
    meta = dict(thesis.metadata) if isinstance(thesis.metadata, dict) else {}
    had = meta.pop("thesis_event", None) is not None
    if had:
        with ledger._connect() as conn:
            conn.execute("UPDATE forecast_questions SET metadata = ? WHERE id = ?", (json_dumps(meta), thesis_id))
    return had


def _thesis_event_spec(ledger, thesis: Any) -> dict[str, Any] | None:
    """Load the stored event spec ({kind, threshold?}) the MC consumes, or None."""
    meta = thesis.metadata if isinstance(thesis.metadata, dict) else {}
    raw = meta.get("thesis_event")
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind", "")).lower()
    if kind not in {"count_threshold", "all", "any"}:
        return None
    spec: dict[str, Any] = {"kind": kind}
    if kind == "count_threshold":
        try:
            spec["threshold"] = int(raw.get("threshold"))
        except (TypeError, ValueError):
            return None
    return spec


def _thesis_event_seed(thesis_id: str, as_of: str | None) -> int:
    """Deterministic MC seed from (thesis_id, as_of) — no Date.now / global RNG."""
    digest = hashlib.sha256(f"{thesis_id}|{as_of or ''}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def aggregate_thesis(
    ledger,
    thesis_id: str,
    *,
    rho: float | str = 0.4,
    now: str | None = None,
    commit: bool = True,
    analyst_note: bool = True,
) -> dict[str, Any]:
    """Deterministically aggregate a thesis's members into a fresh snapshot.

    Reads each member's CURRENT snapshot (so callers must run the members
    first — the thesis lags them), folds the beliefs via
    :func:`forecasting.thesis.aggregate_thesis`, and (when ``commit``)
    writes a thesis snapshot + a rolling analyst note.
    """

    from forecasting import thesis as thesis_math

    thesis = ledger.get_question(thesis_id)
    if not ledger.is_thesis(thesis):
        raise ValidationError("aggregate_thesis requires a question with outcome type 'thesis'")
    if ledger.is_factor(thesis):
        # A factor aggregates a weighted basket of return distributions via
        # portfolio math, not the health-signal pool.
        return ledger._aggregate_factor(thesis, rho=rho, now=now, commit=commit, analyst_note=analyst_note)
    members = ledger.list_thesis_members(thesis_id)
    beliefs = [ledger._thesis_member_belief(m) for m in members]
    as_of = now or utc_now_iso()
    correlation = ledger._thesis_correlation_matrix(thesis)
    agg = thesis_math.aggregate_thesis(
        beliefs, rho=rho, now=as_of,
        correlation_matrix=correlation,
    )

    # ── Event-probability layer ─────────────────────────────────────────
    # When the thesis is configured as a JOINT THRESHOLD EVENT (e.g. "Dems
    # take back the Senate" = P(#seats ≥ K)), run a Gaussian-copula MC over
    # the SAME binary member beliefs. The mean index is damped and
    # threshold-insensitive; the event probability is the number the
    # question actually asks. Seeded deterministically from (thesis_id,
    # as_of) so re-aggregation is reproducible. Stamped ALONGSIDE the mean
    # index (health/score/band stay as diagnostics; nothing removed).
    event_spec = ledger._thesis_event_spec(thesis)
    event_result = None
    # The snapshot's probability_or_distribution is validated to a FLAT numeric
    # dict, so only the numeric event_probability rides in the payload (it is
    # the headline). The structured detail (spec / count distribution / per-
    # member sensitivities) is stamped into the snapshot metadata below.
    event_payload: dict[str, Any] = {}
    if event_spec is not None:
        event_result = thesis_math.simulate_thesis_event(
            beliefs, event_spec,
            rho=rho,
            correlation_matrix=correlation,
            seed=ledger._thesis_event_seed(thesis_id, as_of),
        )
        if event_result.event_probability is not None:
            event_payload = {"event_probability": event_result.event_probability}

    def _thesis_payload() -> dict[str, Any]:
        return {**agg.to_payload(), **event_payload}

    # Entity suitability + trade triggers. Read the PRIOR snapshot first
    # (get_current_snapshot returns the latest before the new commit) so the
    # per-entity deltas + signal-move triggers compare against it.
    previous = ledger.get_current_snapshot(thesis_id)
    prev_components: list[dict[str, Any]] = []
    prev_entities: list[dict[str, Any]] = []
    if previous is not None:
        prev_ensemble = previous.ensemble_components if isinstance(previous.ensemble_components, dict) else {}
        prev_components = prev_ensemble.get("components") or []
        prev_meta = previous.metadata if isinstance(previous.metadata, dict) else {}
        prev_entities = prev_meta.get("entities") or []
    member_map = {m["member_question_id"]: m for m in members}
    entities, triggers = ledger._compute_thesis_entities(
        thesis_id,
        rho=rho,
        now=as_of,
        member_map=member_map,
        current_components=agg.components,
        prev_components=prev_components,
        prev_entities=prev_entities,
    )

    result: dict[str, Any] = {
        "thesis_id": thesis_id,
        "title": thesis.title,
        "aggregate": agg,
        "payload": _thesis_payload(),
        "event": event_result,
        "member_count": len(members),
        "entities": entities,
        "triggers": triggers,
        "snapshot_id": None,
    }
    if not commit:
        return result

    payload = _thesis_payload()
    if payload.get("health") is None:
        # No usable member signal: do not fabricate a number. Record the
        # withholding as an analyst note and skip the snapshot.
        if analyst_note:
            note = ledger.add_analyst_note(
                question_id=thesis_id,
                body="; ".join(agg.notes) or "withheld: no usable member signal",
                kind="brief",
                headline=f"{thesis.title} — withheld (insufficient fresh members)",
                be_aware="; ".join(agg.notes),
                generator="thesis_aggregate",
                metadata={"coverage": agg.coverage, "member_count": len(members)},
            )
            result["analyst_note_id"] = note.get("id")
        return result

    rationale = (
        f"Deterministic aggregate of {len(members)} member forecast(s) "
        f"(coverage {agg.coverage:.0%}, n_eff {agg.n_eff:.1f}, rho {agg.rho:.2f}). "
        "Computed after the members' latest runs; not LLM-led."
    )
    snapshot = ledger.create_snapshot(
        question_id=thesis_id,
        probability_or_distribution=payload,
        rationale=rationale,
        as_of=as_of,
        confidence=round(max(0.0, min(1.0, agg.coverage)), 3),
        method="thesis_aggregate",
        style_autofix=True,  # deterministic fold: mechanically clean generated prose
        distribution_autofix=True,  # programmatic: auto-fix malformed bounds rather than block
        ensemble_components={
            "components": agg.components,
            "rho": agg.rho,
            "n_eff": agg.n_eff,
            "coverage": agg.coverage,
            "spread": agg.spread,
        },
        forecast_origin="live",
        calibration_eligible=False,
        metadata={
            "thesis_notes": agg.notes + ((event_result.notes if event_result else [])),
            "thesis_spread": agg.spread,
            "entities": entities,
            "triggers": triggers,
            # Full event read (count distribution + per-member sensitivities +
            # excluded members) for the desk; the compact headline fields live
            # in the snapshot payload alongside the mean index.
            "event": {
                "event_probability": event_result.event_probability,
                "event": event_result.event,
                "count_distribution": event_result.count_distribution,
                "sensitivities": event_result.sensitivities,
                "excluded": event_result.excluded,
                "participants": event_result.participants,
                "backend": event_result.backend,
                "n_draws": event_result.n_draws,
                "rho": event_result.rho,
                "seed": event_result.seed,
            } if (event_result and event_result.event_probability is not None) else None,
        },
        reasons_up=_thesis_reason_lines(agg, "support"),
        reasons_down=_thesis_reason_lines(agg, "drag"),
    )
    result["snapshot_id"] = snapshot.forecast_id
    if analyst_note:
        headline, how_it_thinks, looking_for, be_aware, body = _thesis_narrative(thesis, agg, event_result)
        note = ledger.add_analyst_note(
            question_id=thesis_id,
            body=body,
            kind="brief",
            headline=headline,
            how_it_thinks=how_it_thinks,
            looking_for=looking_for,
            be_aware=be_aware,
            forecast_id=snapshot.forecast_id,
            probability_at_write=payload,
            confidence_at_write=round(max(0.0, min(1.0, agg.coverage)), 3),
            generator="thesis_aggregate",
            metadata={"coverage": agg.coverage, "n_eff": agg.n_eff, "rho": agg.rho},
        )
        result["analyst_note_id"] = note.get("id")
    return result


def aggregate_all_theses(
    ledger,
    *,
    now: str | None = None,
    rho: float | str = 0.4,
    limit: int = 500,
) -> dict[str, Any]:
    """Aggregate every active thesis (the trailing lag phase of a sweep).

    Runs nested theses last (a thesis whose members include another thesis
    re-aggregates after that member). Used by ``run-all`` Phase 2 and the
    daily cron so theses + their entity suitabilities refresh after the
    members. Each thesis is isolated: one failing thesis does not abort the rest.
    """

    now = now or utc_now_iso()
    theses = [q for q in ledger.list_questions(status="active", limit=limit) if ledger.is_thesis(q)]

    def _depends_on_thesis(thesis: Any) -> bool:
        return any(
            ledger.is_thesis(member["member_question_id"])
            for member in ledger.list_thesis_members(thesis.id)
        )

    ordered = [q for q in theses if not _depends_on_thesis(q)] + [q for q in theses if _depends_on_thesis(q)]
    results: list[dict[str, Any]] = []
    for thesis in ordered:
        try:
            result = ledger.aggregate_thesis(thesis.id, rho=rho, now=now)
            results.append(
                {
                    "id": thesis.id,
                    "title": thesis.title,
                    "ok": True,
                    "snapshot_id": result.get("snapshot_id"),
                    "withheld": result.get("snapshot_id") is None,
                    "health": (result.get("payload") or {}).get("health"),
                    "entity_count": len(result.get("entities") or []),
                    "trigger_count": len(result.get("triggers") or []),
                }
            )
        except Exception as exc:  # one bad thesis must not abort the sweep
            results.append({"id": thesis.id, "title": thesis.title, "ok": False, "error": str(exc)})
    return {"count": len(ordered), "results": results}
