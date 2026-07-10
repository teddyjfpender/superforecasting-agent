"""Thesis / factor dashboard sections (carved from ``dashboard.py``).

The Wave-4 §W3.b ``thesis`` section: the thesis/factor health+score summaries
(``build_thesis_summary`` / ``build_factor_summary``), the per-candidate
vote-share ``_candidate_intervals``, the top event-sensitivity picker, and the
workspace thesis/factor detail sections (``_workspace_thesis`` /
``_workspace_factor`` + their history-point helpers). Imported back into
:mod:`forecasting.dashboard.core` (``build_workspace_payload`` calls the
workspace sections; the summaries feed the dashboard) and re-exported by the
façade unchanged. Shared distribution/formatting helpers (``_distribution_view``,
``_headline_numeric``, ``_workspace_analyst_note``, ``format_freshness``) stay in
core and are imported bare.
"""
from __future__ import annotations

from typing import Any

from forecasting.ledger import ForecastLedger
from forecasting.dashboard.core import (
    _distribution_view,
    _headline_numeric,
    _workspace_analyst_note,
    format_freshness,
)

def _top_event_sensitivities(event_detail: dict[str, Any] | None, k: int = 5) -> list[dict[str, Any]] | None:
    """The k members whose ±2pp move swings P(event) most (by |Δ|), or None."""

    if not event_detail:
        return None
    rows = event_detail.get("sensitivities") or []
    return sorted(rows, key=lambda s: -abs(s.get("delta_p_event") or 0.0))[:k]


def build_thesis_summary(
    *, ledger: ForecastLedger | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """A light per-thesis summary (health/score/delta/coverage) for the dashboard.

    Uncapped by default so it finds every thesis regardless of creation order;
    factors (aggregation='factor') are summarized separately by build_factor_summary.
    """

    ledger = ledger or ForecastLedger()
    out: list[dict[str, Any]] = []
    for question in ledger.list_questions(status="active", limit=limit):
        if not ledger.is_thesis(question) or ledger.is_factor(question):
            continue
        snapshots = ledger.list_snapshots(question.id)
        current = snapshots[-1] if snapshots else None
        payload = current.probability_or_distribution if current else {}
        payload = payload if isinstance(payload, dict) else {}
        previous = snapshots[-2].probability_or_distribution if len(snapshots) >= 2 else None
        previous_health = previous.get("health") if isinstance(previous, dict) else None
        health = payload.get("health")
        # A thesis configured as a JOINT THRESHOLD EVENT reports P(event) as its
        # headline (the question it actually asks); the mean-index health/score
        # stay as diagnostics. Fall back to health when no event is configured.
        # Only the numeric event_probability rides in the payload; the structured
        # detail (spec / count distribution / sensitivities) is in the metadata.
        event_probability = payload.get("event_probability")
        prev_event = previous.get("event_probability") if isinstance(previous, dict) else None
        headline = event_probability if event_probability is not None else health
        prev_headline = prev_event if event_probability is not None else previous_health
        cur_meta = current.metadata if current else {}
        cur_meta = cur_meta if isinstance(cur_meta, dict) else {}
        event_detail = cur_meta.get("event") if isinstance(cur_meta.get("event"), dict) else None
        out.append(
            {
                "id": question.id,
                "title": question.title,
                "domain": question.domain,
                "health_probability": health,
                "health_display": f"{health:.0%}" if health is not None else "-",
                "thesis_score": payload.get("thesis_score"),
                "event_probability": event_probability,
                "event_band": (
                    {"p10": payload.get("event_p10"), "p50": payload.get("event_p50"), "p90": payload.get("event_p90")}
                    if payload.get("event_p10") is not None and payload.get("event_p90") is not None
                    else None
                ),
                "event": event_detail.get("event") if event_detail else None,
                "count_distribution": event_detail.get("count_distribution") if event_detail else None,
                "top_sensitivities": _top_event_sensitivities(event_detail),
                "headline_probability": headline,
                "headline_display": f"{headline:.0%}" if headline is not None else "-",
                "coverage": payload.get("coverage"),
                "n_eff": payload.get("n_eff"),
                "delta": (headline - prev_headline)
                if (headline is not None and prev_headline is not None)
                else None,
                "member_count": len(ledger.list_thesis_members(question.id)),
                "as_of": current.as_of if current else None,
                "status": "withheld" if headline is None else "ok",
            }
        )
    return out


def build_factor_summary(
    *, ledger: ForecastLedger | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """A light per-factor summary (return/vol/downside/delta) for the dashboard."""

    ledger = ledger or ForecastLedger()
    out: list[dict[str, Any]] = []
    for question in ledger.list_questions(status="active", limit=limit):
        if not ledger.is_factor(question):
            continue
        snapshots = ledger.list_snapshots(question.id)
        current = snapshots[-1] if snapshots else None
        payload = current.probability_or_distribution if current else {}
        payload = payload if isinstance(payload, dict) else {}
        previous = snapshots[-2].probability_or_distribution if len(snapshots) >= 2 else None
        previous_mean = previous.get("factor_mean") if isinstance(previous, dict) else None
        mean = payload.get("factor_mean")
        out.append(
            {
                "id": question.id,
                "title": question.title,
                "domain": question.domain,
                "units": question.outcome_space.units,
                "mean": mean,
                "sd": payload.get("factor_sd"),
                "q05": payload.get("q05"),
                "q95": payload.get("q95"),
                "downside": payload.get("downside"),
                "cvar": payload.get("cvar"),
                "coverage": payload.get("coverage"),
                "delta": (mean - previous_mean)
                if (mean is not None and previous_mean is not None)
                else None,
                "member_count": len(ledger.list_thesis_members(question.id)),
                "as_of": current.as_of if current else None,
                "status": "withheld" if mean is None else "ok",
            }
        )
    return out


def _candidate_intervals(snapshot: Any) -> dict[str, dict[str, float]] | None:
    """Per-candidate 90% intervals for a vote-share PMF, read from the snapshot's
    ``candidate_share_intervals_pp`` metadata and normalized to
    ``{candidate: {lo, mid, hi}}`` (p05 / median / p95). Returns None when absent or
    malformed — the TUI draws per-candidate error bars only when present."""
    meta = getattr(snapshot, "metadata", None)
    if not isinstance(meta, dict):
        return None
    raw = meta.get("candidate_share_intervals_pp")
    if not isinstance(raw, dict):
        return None
    # The intervals are stored in percentage POINTS (0-100). Render them on the SAME
    # scale as the payload's candidate shares: a fraction-scale PMF (shares ~0-1) needs
    # them divided by 100 so the bar value and its [lo-hi] suffix don't mismatch. Detect
    # the scale by matching a candidate's payload share against its interval median.
    payload = getattr(snapshot, "probability_or_distribution", None)
    payload = payload if isinstance(payload, dict) else {}
    scale = 1.0

    def _num(value: Any) -> float | None:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    for candidate, interval in raw.items():
        share = _num(payload.get(candidate))
        median = _num(interval.get("median")) if isinstance(interval, dict) else None
        if share is not None and median is not None and abs(share) <= 1.5 < abs(median):
            scale = 0.01  # payload is fraction-scale, intervals are pp
            break

    out: dict[str, dict[str, float]] = {}
    for candidate, interval in raw.items():
        if not isinstance(interval, dict):
            continue
        pairs = (("lo", interval.get("p05")), ("mid", interval.get("median", interval.get("p50"))), ("hi", interval.get("p95")))
        vals = {k: round(_num(v) * scale, 6) for k, v in pairs if _num(v) is not None}
        if "lo" in vals and "hi" in vals and vals["lo"] <= vals["hi"]:
            out[str(candidate)] = vals
    return out or None


def _thesis_history_point(snapshot: Any) -> dict[str, Any]:
    """One point in a thesis's health/score time series (for the trend chart)."""

    payload = snapshot.probability_or_distribution
    payload = payload if isinstance(payload, dict) else {}
    # When the thesis is a joint-event, P(event) is the headline series; else the
    # mean-index health. Both are 0..1 so the trend chart never mixes scales — but
    # the SERIES SWITCHES the day an event is configured (health ~0.51 → event
    # ~0.35). A window delta straddling that switch is a lie, so each point is
    # STAMPED with its regime ("event" | "health") and the desk only compares
    # within the current regime (a baseline that predates the switch → honest '—').
    event_probability = payload.get("event_probability")
    headline_regime = "event" if event_probability is not None else "health"
    return {
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        "headline_probability": event_probability if event_probability is not None else payload.get("health"),
        "headline_regime": headline_regime,
        "health_probability": payload.get("health"),
        "event_probability": event_probability,
        "thesis_score": payload.get("thesis_score"),
        "score_low": payload.get("q05"),
        "score_high": payload.get("q95"),
        # The honest interval ON the event headline (second-order MC band). The
        # desk draws these as the band around the event series — the interval the
        # mean-index score band cannot give an all-binary thesis.
        "event_low": payload.get("event_p10"),
        "event_high": payload.get("event_p90"),
    }


def _workspace_thesis(
    ledger: ForecastLedger,
    question: Any,
    *,
    now: str | None = None,
    history_limit: int = 80,
) -> dict[str, Any]:
    """Bundle a thesis question with its aggregate read + member contributions.

    Reads the thesis's current aggregate snapshot (written by
    ``ledger.aggregate_thesis``) and enriches the stored component rows with each
    member's live headline so the desk can render the breakdown without a refetch.
    """

    snapshots = ledger.list_snapshots(question.id)
    current = snapshots[-1] if snapshots else None
    previous = snapshots[-2] if len(snapshots) >= 2 else None
    payload = current.probability_or_distribution if current else {}
    payload = payload if isinstance(payload, dict) else {}
    ensemble = current.ensemble_components if current else {}
    ensemble = ensemble if isinstance(ensemble, dict) else {}
    stored_components = ensemble.get("components") or []
    meta = current.metadata if current else {}
    meta = meta if isinstance(meta, dict) else {}

    members = {m["member_question_id"]: m for m in ledger.list_thesis_members(question.id)}

    component_views: list[dict[str, Any]] = []
    for comp in stored_components:
        member_id = comp.get("member_id")
        member = members.get(member_id, {})
        member_snapshot = ledger.get_current_snapshot(member_id) if member_id else None
        belief = member_snapshot.probability_or_distribution if member_snapshot else None
        outcome_type = member.get("member_outcome_type")
        headline = _headline_numeric(belief) if belief is not None else None
        if headline is None:
            belief_display = "-"
        elif outcome_type in {"binary", "categorical"}:
            belief_display = f"{headline:.0%}"
        else:
            belief_display = f"μ{headline:g}"
        component_views.append(
            {
                "id": member_id,
                "title": comp.get("title") or member.get("member_title"),
                "direction": comp.get("direction"),
                "role": member.get("role"),
                "weight": comp.get("weight"),
                "w_norm": comp.get("w_norm"),
                "s_raw": comp.get("s_raw"),
                "s_i": comp.get("s_i"),
                "sigma": comp.get("sigma"),
                "contribution_pts": comp.get("contribution_pts"),
                "marginal_health_delta": comp.get("marginal_health_delta"),
                "status": comp.get("status"),
                "flags": comp.get("flags") or [],
                "as_of": comp.get("as_of"),
                "outcome_type": outcome_type,
                "latest_belief_display": belief_display,
                "latest_headline": headline,
            }
        )

    health = payload.get("health")
    previous_payload = previous.probability_or_distribution if previous else None
    previous_health = previous_payload.get("health") if isinstance(previous_payload, dict) else None

    # Joint-event thesis: P(event) is the headline (the question it actually asks);
    # health/score remain diagnostics. Delta tracks whichever is the headline.
    event_probability = payload.get("event_probability")
    prev_event = previous_payload.get("event_probability") if isinstance(previous_payload, dict) else None
    headline = event_probability if event_probability is not None else health
    prev_headline = prev_event if event_probability is not None else previous_health
    delta = (headline - prev_headline) if (headline is not None and prev_headline is not None) else None
    # Full event read (count distribution + per-member sensitivities + excluded)
    # is written into the snapshot metadata by ledger.aggregate_thesis.
    event_meta = meta.get("event") if isinstance(meta.get("event"), dict) else None

    band = None
    if payload.get("q05") is not None and payload.get("q95") is not None:
        band = {"q05": payload.get("q05"), "q50": payload.get("q50"), "q95": payload.get("q95")}

    # The honest interval ON the P(event) headline (second-order MC band). This is
    # the interval an all-binary thesis CAN publish even though its mean-index
    # score band is withheld (binary members carry no calibrated 0..1 dispersion).
    event_band = None
    if payload.get("event_p10") is not None and payload.get("event_p90") is not None:
        event_band = {
            "p10": payload.get("event_p10"),
            "p50": payload.get("event_p50"),
            "p90": payload.get("event_p90"),
        }

    analyst_notes = ledger.list_analyst_notes(question.id)

    # Aggregate freshness: stale when a member moved after the last aggregate (or
    # the thesis has members but was never aggregated). The member-commit cascade
    # normally keeps this False; the desk badges it so a lagging thesis is honest.
    agg_as_of = current.as_of if current else None
    newer_members = 0
    for member_id, _m in members.items():
        msnap = ledger.get_current_snapshot(member_id)
        if msnap is not None and agg_as_of and (msnap.as_of or "") > (agg_as_of or ""):
            newer_members += 1
    aggregate_stale = newer_members > 0 or (current is None and bool(members))

    # Never-aggregated (or empty-component) thesis: synthesize member rows from the
    # live membership so the desk shows the members + their current beliefs instead
    # of a blank table.
    if not component_views and members:
        for member_id, member in members.items():
            msnap = ledger.get_current_snapshot(member_id)
            belief = msnap.probability_or_distribution if msnap else None
            ot = member.get("member_outcome_type")
            h = _headline_numeric(belief) if belief is not None else None
            disp = "-" if h is None else (f"{h:.0%}" if ot in {"binary", "categorical"} else f"μ{h:g}")
            component_views.append({
                "id": member_id,
                "title": member.get("member_title"),
                "direction": member.get("direction"),
                "role": member.get("role"),
                "weight": member.get("weight"),
                "status": "pending_aggregation",
                "outcome_type": ot,
                "latest_belief_display": disp,
                "latest_headline": h,
                "contribution_pts": None,
                "s_i": None,
            })

    return {
        "id": question.id,
        "title": question.title,
        "domain": question.domain,
        "topics": list(question.topics or []),
        "status": question.status,
        "as_of": current.as_of if current else None,
        "freshness": format_freshness(current.as_of if current else None, now=now),
        "health_probability": health,
        "health_display": f"{health:.0%}" if health is not None else "-",
        "thesis_score": payload.get("thesis_score"),
        # Joint-event headline (P(#member successes ≥ K)) when configured, plus the
        # count distribution + "which race matters" sensitivities for the desk.
        # Only event_probability rides in the payload; the structured detail is in
        # the snapshot metadata (event_meta).
        "event_probability": event_probability,
        "event": event_meta.get("event") if event_meta else None,
        "count_distribution": event_meta.get("count_distribution") if event_meta else None,
        "top_sensitivities": _top_event_sensitivities(event_meta),
        "event_detail": event_meta,
        "headline_probability": headline,
        "headline_display": f"{headline:.0%}" if headline is not None else "-",
        "score_band": band,
        # The 90% interval on the P(event) headline (p10/p50/p90), from the
        # second-order MC. None when no event is configured or no binary member
        # participates — withheld, never fabricated.
        "event_band": event_band,
        "coverage": payload.get("coverage"),
        "n_eff": payload.get("n_eff"),
        "rho": ensemble.get("rho"),
        "delta": delta,
        "member_count": len(members),
        "aggregate_stale": aggregate_stale,
        "components": component_views,
        "spread": ensemble.get("spread"),
        "history": [_thesis_history_point(snap) for snap in snapshots[-history_limit:]],
        "analyst_note": _workspace_analyst_note(analyst_notes[-1]) if analyst_notes else None,
        "rationale": current.rationale if current else None,
        "snapshot_count": len(snapshots),
        # Per-entity suitability + the §10 "signal moved -> entities affected"
        # trade triggers, written by ledger.aggregate_thesis into the snapshot.
        "entities": meta.get("entities") or [],
        "triggers": meta.get("triggers") or [],
        # Every question in the thesis ECOSYSTEM — its weighted members PLUS every
        # question any of its entities weights. The desk lens filters the book to
        # this set so selecting a thesis shows its full related view, not only the
        # health-driver members.
        "question_ids": sorted(
            {comp["id"] for comp in component_views if comp.get("id")}
            # The actual thesis membership (list_thesis_members) — the source of
            # truth behind member_count. Without it the ecosystem collapsed to the
            # snapshot's stored components, which are empty/stale until the thesis
            # is re-aggregated, so the desk lens showed zero member questions.
            | {mid for mid in members if mid}
            | {
                contribution.get("member_id")
                for entity in (meta.get("entities") or [])
                for contribution in (entity.get("contributions") or [])
                if contribution.get("member_id")
            }
        ),
    }


def _factor_history_point(snapshot: Any) -> dict[str, Any]:
    """One point in a factor's return-distribution time series (for the chart)."""

    payload = snapshot.probability_or_distribution
    payload = payload if isinstance(payload, dict) else {}
    return {
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        # The factor mean return is the headline series; the band is the return
        # 90% interval in the same units.
        "headline_probability": payload.get("factor_mean"),
        "band_low": payload.get("q05"),
        "band_high": payload.get("q95"),
        "volatility": payload.get("factor_sd"),
    }


def _workspace_factor(
    ledger: ForecastLedger,
    question: Any,
    *,
    now: str | None = None,
    history_limit: int = 80,
) -> dict[str, Any]:
    """Bundle a factor question with its portfolio aggregate + constituents."""

    snapshots = ledger.list_snapshots(question.id)
    current = snapshots[-1] if snapshots else None
    previous = snapshots[-2] if len(snapshots) >= 2 else None
    payload = current.probability_or_distribution if current else {}
    payload = payload if isinstance(payload, dict) else {}
    ensemble = current.ensemble_components if current else {}
    ensemble = ensemble if isinstance(ensemble, dict) else {}
    stored = ensemble.get("components") or []

    members = {m["member_question_id"]: m for m in ledger.list_thesis_members(question.id)}
    constituents: list[dict[str, Any]] = []
    for comp in stored:
        member_id = comp.get("member_id")
        member = members.get(member_id, {})
        constituents.append(
            {
                "id": member_id,
                "title": comp.get("title") or member.get("member_title"),
                "direction": comp.get("direction"),
                "weight": comp.get("weight"),
                "w_norm": comp.get("w_norm"),
                "mean": comp.get("mu"),
                "sd": comp.get("sigma"),
                "contribution": comp.get("contribution"),
                "status": comp.get("status"),
                "flags": comp.get("flags") or [],
            }
        )

    mean = payload.get("factor_mean")
    previous_payload = previous.probability_or_distribution if previous else None
    previous_mean = previous_payload.get("factor_mean") if isinstance(previous_payload, dict) else None
    delta = (mean - previous_mean) if (mean is not None and previous_mean is not None) else None

    analyst_notes = ledger.list_analyst_notes(question.id)

    # Aggregate freshness + live-constituent fallback (mirrors _workspace_thesis):
    # stale when a constituent moved after the last aggregate; synthesize rows from
    # live membership when the aggregate has none, so the desk is never blank.
    agg_as_of = current.as_of if current else None
    newer_members = 0
    for member_id, _m in members.items():
        msnap = ledger.get_current_snapshot(member_id)
        if msnap is not None and agg_as_of and (msnap.as_of or "") > (agg_as_of or ""):
            newer_members += 1
    aggregate_stale = newer_members > 0 or (current is None and bool(members))
    if not constituents and members:
        for member_id, member in members.items():
            msnap = ledger.get_current_snapshot(member_id)
            belief = msnap.probability_or_distribution if msnap else None
            view = _distribution_view(belief) if isinstance(belief, dict) else None
            constituents.append({
                "id": member_id,
                "title": member.get("member_title"),
                "direction": "short" if member.get("direction") == "inverted" else "long",
                "weight": member.get("weight"),
                "mean": (view or {}).get("mean") if view else (float(belief) if isinstance(belief, (int, float)) else None),
                "sd": (view or {}).get("sd") if view else None,
                "status": "pending_aggregation",
            })

    return {
        "id": question.id,
        "title": question.title,
        "domain": question.domain,
        "topics": list(question.topics or []),
        "units": question.outcome_space.units,
        "as_of": current.as_of if current else None,
        "freshness": format_freshness(current.as_of if current else None, now=now),
        "mean": mean,
        "sd": payload.get("factor_sd"),
        "volatility": payload.get("factor_sd"),
        "q05": payload.get("q05"),
        "q50": payload.get("q50"),
        "q95": payload.get("q95"),
        "downside": payload.get("downside"),
        "cvar": payload.get("cvar"),
        "coverage": payload.get("coverage"),
        "n_eff": payload.get("n_eff"),
        "delta": delta,
        "member_count": len(members),
        "aggregate_stale": aggregate_stale,
        "constituents": constituents,
        # The real membership (list_thesis_members) unioned with the snapshot's
        # stored constituents, so the desk lens filters to every constituent even
        # when the factor's snapshot components are empty/stale (same fix as the
        # thesis ecosystem).
        "question_ids": sorted(
            {c["id"] for c in constituents if c.get("id")} | {mid for mid in members if mid}
        ),
        "history": [_factor_history_point(snap) for snap in snapshots[-history_limit:]],
        "analyst_note": _workspace_analyst_note(analyst_notes[-1]) if analyst_notes else None,
        "rationale": current.rationale if current else None,
        "snapshot_count": len(snapshots),
    }
