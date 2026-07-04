"""Forecast dashboard summaries shared by CLI, TUI, and web surfaces."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from forecasting.backtesting import (
    benchmark_claim_status,
    best_baseline,
    build_forecasting_evidence_status,
)
from forecasting.branding import PRODUCT_NAME
from forecasting.ledger import ForecastLedger
from forecasting.models import LedgerNotFoundError, utc_now_iso


def _snapshot_tail_audit(snapshot: Any) -> dict[str, Any] | None:
    """The probability-mass audit recorded on a categorical snapshot (None for
    binary/numeric/older snapshots). Carried onto each desk row so the rail,
    book, and status strip can flag a forecast with UNEARNED tail mass — the
    glanceable text agrees with the detail pane's Tail Audit section."""
    metadata = getattr(snapshot, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    audit = metadata.get("tail_audit")
    return audit if isinstance(audit, dict) else None


def _snapshot_saturation_score(snapshot: Any) -> float | None:
    """The observe-mode saturation score (0-100) recorded on this snapshot's
    metadata, or None when no report was stored. Read from the metadata the
    payload builder ALREADY holds — never a per-question query (the desk N+1 was
    a hard-won perf fix)."""
    metadata = getattr(snapshot, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    saturation = metadata.get("saturation")
    if not isinstance(saturation, dict):
        return None
    score = saturation.get("score")
    return float(score) if isinstance(score, (int, float)) else None


def build_dashboard_summary(
    *,
    ledger: ForecastLedger | None = None,
    limit: int = 50,
    now: str | None = None,
    fast: bool = False,
) -> dict[str, Any]:
    ledger = ledger or ForecastLedger()
    # The detailed question ROWS are capped at `limit` for display, but the
    # COUNTS must reflect true totals — otherwise a large book under-reports.
    all_active = ledger.list_questions(status="active", limit=None)
    theses_active = [q for q in all_active if ledger.is_thesis(q) and not ledger.is_factor(q)]
    factors_active = [q for q in all_active if ledger.is_factor(q)]
    book_active = [q for q in all_active if not ledger.is_thesis(q)]
    entity_count = sum(len(ledger.list_thesis_entities(t.id)) for t in theses_active)
    questions = book_active[:limit]
    alerts = ledger.list_alerts(unresolved_only=True)
    alert_counts: dict[str, int] = {}
    for alert in alerts:
        if alert.scope_type == "question" and alert.scope_ref:
            alert_counts[alert.scope_ref] = alert_counts.get(alert.scope_ref, 0) + 1
    alert_rows = [summarize_alert(alert) for alert in alerts[: min(limit, 12)]]

    rows = []
    for question in questions:
        # Theses are aggregates of the other questions — summarized separately.
        if ledger.is_thesis(question):
            continue
        current = ledger.get_current_snapshot(question.id)
        snapshots = ledger.list_snapshots(question.id)
        probability = current.probability_or_distribution if current else None
        previous = snapshots[-2].probability_or_distribution if len(snapshots) >= 2 else None
        evidence_items = ledger.list_evidence(question.id)
        latest_evidence = evidence_items[-1] if evidence_items else None
        assumptions = ledger.list_assumptions(question.id)
        stale_assumptions = [
            item for item in assumptions if item.get("status") in {"stale", "invalidated"}
        ]
        reference_classes = ledger.list_reference_classes(question.id)
        stale_reference_classes = [
            item
            for item in reference_classes
            if item.get("status") in {"stale", "invalidated", "superseded"}
        ]
        rows.append(
            {
                "id": question.id,
                "title": question.title,
                "status": question.status,
                "domain": question.domain,
                "topics": question.topics,
                "close_time": question.close_time,
                "resolution_time": question.resolution_time,
                "probability": probability,
                "delta": probability_delta(previous, probability),
                "confidence": current.confidence if current else None,
                "as_of": current.as_of if current else None,
                "latest_rationale": current.rationale if current else None,
                "latest_evidence_at": latest_evidence.available_at if latest_evidence else None,
                "latest_evidence_claim": latest_evidence.claim if latest_evidence else None,
                "latest_evidence_summary": latest_evidence.summary if latest_evidence else None,
                "evidence_count": len(evidence_items),
                "baseline_count": len(ledger.list_baseline_comparisons(question.id)),
                "open_assumption_count": len(
                    [item for item in assumptions if item.get("status") == "active"]
                ),
                "stale_assumption_count": len(stale_assumptions),
                "open_reference_class_count": len(
                    [item for item in reference_classes if item.get("status") == "active"]
                ),
                "stale_reference_class_count": len(stale_reference_classes),
                "open_alert_count": alert_counts.get(question.id, 0),
                "tail_audit": _snapshot_tail_audit(current),
            }
        )

    review_queue = []
    review_question_ids: set[str] = set()
    if fast:
        review_limit = min(limit, 12)
        for alert in alerts:
            if not alert_promotes_to_review(alert.reason):
                continue
            question_id = alert.scope_ref if alert.scope_type == "question" else None
            if not question_id:
                continue
            review_question_ids.add(question_id)
            if len(review_queue) >= review_limit:
                continue
            try:
                question = ledger.get_question(question_id)
            except LedgerNotFoundError:
                continue
            if question.status != "active":
                continue
            snapshot = ledger.get_current_snapshot(question.id)
            review_queue.append(
                {
                    "id": question.id,
                    "title": question.title,
                    "domain": question.domain,
                    "close_time": question.close_time,
                    "resolution_time": question.resolution_time,
                    "probability": snapshot.probability_or_distribution if snapshot else None,
                    "as_of": snapshot.as_of if snapshot else None,
                    "latest_rationale": snapshot.rationale if snapshot else None,
                    "latest_evidence_at": None,
                    "latest_evidence_claim": None,
                    "latest_evidence_summary": None,
                    "priority": alert_review_priority(alert.reason),
                    "reasons": [alert.reason],
                    "next_action": alert.recommended_action or review_next_action(question.id, [alert.reason]),
                    "tail_audit": _snapshot_tail_audit(snapshot),
                }
            )
    else:
        for row in ledger.review_questions(stale=True, last_days=7, now=now)[: min(limit, 12)]:
            question = row["question"]
            snapshot = row["current_snapshot"]
            reasons = list(row.get("reasons") or [])
            evidence_items = ledger.list_evidence(question.id)
            latest_evidence = evidence_items[-1] if evidence_items else None
            review_queue.append(
                {
                    "id": question.id,
                    "title": question.title,
                    "domain": question.domain,
                    "close_time": question.close_time,
                    "resolution_time": question.resolution_time,
                    "probability": snapshot.probability_or_distribution if snapshot else None,
                    "as_of": snapshot.as_of if snapshot else None,
                    "latest_rationale": snapshot.rationale if snapshot else None,
                    "latest_evidence_at": latest_evidence.available_at if latest_evidence else None,
                    "latest_evidence_claim": latest_evidence.claim if latest_evidence else None,
                    "latest_evidence_summary": latest_evidence.summary if latest_evidence else None,
                    "priority": row.get("priority", 9),
                    "reasons": reasons,
                    "next_action": review_next_action(question.id, reasons),
                    "tail_audit": _snapshot_tail_audit(snapshot),
                }
            )
    review_rows_by_id = {str(row["id"]): row for row in review_queue if row.get("id")}
    if not fast:
        for alert in alerts:
            if not alert_promotes_to_review(alert.reason):
                continue
            question_id = alert.scope_ref if alert.scope_type == "question" else None
            if not question_id:
                continue
            review_question_ids.add(question_id)
            existing = review_rows_by_id.get(question_id)
            if existing is not None:
                reasons = existing.setdefault("reasons", [])
                if alert.reason not in reasons:
                    reasons.append(alert.reason)
                existing["priority"] = min(
                    int(existing.get("priority") or 9),
                    alert_review_priority(alert.reason),
                )
                continue
            try:
                question = ledger.get_question(question_id)
            except LedgerNotFoundError:
                continue
            if question.status != "active":
                continue
            snapshot = ledger.get_current_snapshot(question.id)
            evidence_items = ledger.list_evidence(question.id)
            latest_evidence = evidence_items[-1] if evidence_items else None
            row = {
                "id": question.id,
                "title": question.title,
                "domain": question.domain,
                "close_time": question.close_time,
                "resolution_time": question.resolution_time,
                "probability": snapshot.probability_or_distribution if snapshot else None,
                "as_of": snapshot.as_of if snapshot else None,
                "latest_rationale": snapshot.rationale if snapshot else None,
                "latest_evidence_at": latest_evidence.available_at if latest_evidence else None,
                "latest_evidence_claim": latest_evidence.claim if latest_evidence else None,
                "latest_evidence_summary": latest_evidence.summary if latest_evidence else None,
                "priority": alert_review_priority(alert.reason),
                "reasons": [alert.reason],
                "next_action": alert.recommended_action or review_next_action(question.id, [alert.reason]),
            }
            review_queue.append(row)
            review_rows_by_id[question.id] = row
    review_queue.sort(key=lambda row: int(row.get("priority") or 9))

    if fast:
        closing_ids = set(ledger.closing_question_ids(now=now))
        review_question_ids.update(closing_ids)
        closing_soon_count = len(closing_ids)
    else:
        closing_soon_count = sum(
            1
            for row in review_queue
            if any(is_close_review_reason(reason) for reason in row.get("reasons", []))
        )

    calibration = ledger.calibration_summary(calibration_eligible=True)
    backtest_summaries = []
    recent_backtests = []
    for run in ([] if fast else ledger.list_backtest_runs()[: min(limit, 20)]):
        report = ledger.backtest_performance_report(run["id"])
        agent_brier = report["agent"]["mean_brier"]
        best = best_baseline(report["baselines"])
        best_name = None
        best_brier = None
        agent_edge = None
        if best is not None:
            best_name = f"{best['baseline_type']}:{best['source']}"
            best_brier = best["mean_brier"]
            if agent_brier is not None and best_brier is not None:
                agent_edge = best_brier - agent_brier
        win_rate_vs_best = report.get("win_rate_vs_best") or {}
        paired_wins = (
            {
                "paired_count": best.get("paired_brier_count"),
                "paired_agent_edge": best.get("paired_agent_edge_mean_brier"),
                "paired_agent_edge_ci95_low": best.get("paired_agent_edge_ci95_low"),
                "paired_agent_edge_ci95_high": best.get("paired_agent_edge_ci95_high"),
                "paired_p_value": best.get("paired_p_value"),
                "paired_brier_coin_flip_floor": best.get("paired_brier_coin_flip_floor"),
                "paired_agent_wins": best.get("paired_agent_wins"),
                "paired_baseline_wins": best.get("paired_baseline_wins"),
                "paired_ties": best.get("paired_ties"),
                "win_rate_vs_best": win_rate_vs_best.get("win_rate_vs_best"),
                "win_rate_vs_best_n": win_rate_vs_best.get("win_rate_vs_best_n", 0),
            }
            if best is not None
            else {
                "paired_count": 0,
                "paired_agent_edge": None,
                "paired_agent_edge_ci95_low": None,
                "paired_agent_edge_ci95_high": None,
                "paired_p_value": None,
                "paired_brier_coin_flip_floor": None,
                "paired_agent_wins": 0,
                "paired_baseline_wins": 0,
                "paired_ties": 0,
                "win_rate_vs_best": win_rate_vs_best.get("win_rate_vs_best"),
                "win_rate_vs_best_n": win_rate_vs_best.get("win_rate_vs_best_n", 0),
            }
        )
        claim_status = benchmark_claim_status(run, report)
        backtest_summaries.append(
            {
                "id": report["run_id"],
                "dataset": report["dataset"],
                "case_count": report["case_count"],
                "leakage_checks_passed": report["leakage_checks_passed"],
                "agent": report["agent"],
                "best_baseline": (
                    {
                        "baseline_type": best["baseline_type"],
                        "source": best["source"],
                        "mean_brier": best["mean_brier"],
                        "agent_edge_mean_brier": agent_edge,
                    }
                    if best is not None
                    else None
                ),
                "claim_status": claim_status,
            }
        )
        if len(recent_backtests) >= 3:
            continue
        recent_backtests.append(
            {
                "id": report["run_id"],
                "dataset": report["dataset"],
                "case_count": report["case_count"],
                "probability_sources": list(run.get("result_summary", {}).get("probability_sources") or ["dataset"]),
                "agent_mean_brier": agent_brier,
                "best_baseline": best_name,
                "best_baseline_brier": best_brier,
                "agent_edge": agent_edge,
                "leakage_checks_passed": report["leakage_checks_passed"],
                "claim_status": claim_status,
                **paired_wins,
            }
        )

    open_assumption_count = sum(int(row.get("open_assumption_count") or 0) for row in rows)
    stale_assumption_count = sum(int(row.get("stale_assumption_count") or 0) for row in rows)
    open_reference_class_count = sum(
        int(row.get("open_reference_class_count") or 0) for row in rows
    )
    stale_reference_class_count = sum(
        int(row.get("stale_reference_class_count") or 0) for row in rows
    )
    scheduled_review_runs = [
        summarize_scheduled_review_run(row)
        for row in ledger.list_scheduled_review_runs(limit=min(limit, 8))
    ]

    evidence_status = None if fast else build_forecasting_evidence_status(ledger, backtest_summaries)
    live_performance = None if fast else ledger.live_performance_report()
    pilot_report = None if fast else ledger.pilot_report()
    doctor = None if fast else build_doctor_gate_summary(pilot_report, evidence_status)

    return {
        "product": PRODUCT_NAME,
        # active_count is the forecast BOOK (active, non-aggregate) — the thesis +
        # factor aggregates are counted separately in the layer fields below.
        "active_count": len(book_active),
        "question_total": len(all_active),
        "thesis_count": len(theses_active),
        "factor_count": len(factors_active),
        "entity_count": entity_count,
        "open_alert_count": len(alerts),
        "review_queue_count": len(review_question_ids) if fast else len(review_queue),
        "closing_soon_count": closing_soon_count,
        "open_assumption_count": open_assumption_count,
        "stale_assumption_count": stale_assumption_count,
        "open_reference_class_count": open_reference_class_count,
        "stale_reference_class_count": stale_reference_class_count,
        "calibration": calibration,
        "doctor": doctor,
        "evidence_status": evidence_status,
        "live_performance": live_performance,
        "learning": build_learning_summary(ledger=ledger),
        "scheduled_review_run_count": len(scheduled_review_runs),
        "scheduled_review_runs": scheduled_review_runs,
        "questions": rows,
        "theses": build_thesis_summary(ledger=ledger),
        "factors": build_factor_summary(ledger=ledger),
        "review_queue": review_queue,
        "alerts": alert_rows,
        "recent_backtests": recent_backtests,
    }


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


# ── VOI-driven desk attention ────────────────────────────────────────────────
# "What should I touch next?" — a transparent, explainable priority per forecast.
# The score answers value-of-information, NOT thesis membership: it is an ADDITIVE
# BASE every question earns (cadence-relative staleness + resolution/review
# proximity + open-alert pressure) times a thesis-sensitivity AMPLIFIER for the
# members whose ±2pp move swings a thesis event. So a stale, near-resolution
# NON-thesis question outranks a fresh, low-value thesis member (a naive product
# would zero out the two-thirds of the book that are not thesis members). Every
# component rides in the payload so the UI can EXPLAIN the rank ("stale 6d ×
# moves the AI-infra thesis 4.20pp").
#
# Base weights (sum to 1.0) — staleness is the primary VOI driver (a forecast
# only earns re-touch value by going stale relative to ITS OWN cadence), then the
# deadline pull of an approaching resolution/review, then open-alert pressure.
VOI_W_STALE = 0.55
VOI_W_PROX = 0.30
VOI_W_ALERT = 0.15
# Sensitivity amplifier: score = base · (1 + min(k·|Δpp|, cap)). A member whose
# ±2pp move swings P(event) by 10pp (k=0.05) amplifies its base by 0.50; the cap
# bounds the boost at 2× so sensitivity tilts the ranking without dominating it.
VOI_SENS_K = 0.05
VOI_SENS_AMP_CAP = 1.0
# Normalization anchors (each raw base component maps to [0, 1] against these):
VOI_DEFAULT_CADENCE_DAYS = 7.0   # cadence assumed when a question has none set
VOI_PROX_HORIZON_DAYS = 30.0     # an event >30d out contributes no proximity pull
VOI_ALERT_FULL = 3.0             # 3+ open alerts on a question = full alert pressure
VOI_RESOLVE_SOON_DAYS = 3.0      # resolution/close within 3d (or passed) → review_due
VOI_NO_SOURCE_DAMPEN = 0.5       # zero watched sources → an update re-pools nothing
VOI_ACTION_FLOOR = 0.12          # base below this → action 'none' (nothing pressing)


def _cadence_days(cadence: str | None) -> float:
    """A review cadence approximated as a day count (self-contained; mirrors the
    ledger's cadence vocabulary). Unknown / missing → :data:`VOI_DEFAULT_CADENCE_DAYS`.
    Bare ``m`` is minutes (the ledger convention); months are ``mo``/``month``."""

    if not cadence:
        return VOI_DEFAULT_CADENCE_DAYS
    raw = re.sub(r"\s+", " ", str(cadence).strip().lower())
    if raw.startswith("every "):
        raw = raw[len("every "):].strip()
    named = {
        "minutely": 1.0 / 1440.0, "hourly": 1.0 / 24.0,
        "daily": 1.0, "1d": 1.0, "weekly": 7.0, "1w": 7.0,
        "monthly": 30.0, "1mo": 30.0, "quarterly": 90.0, "yearly": 365.0,
    }
    if raw in named:
        return named[raw]
    match = re.fullmatch(
        r"(?P<count>\d*)\s*(?P<unit>w|week|weeks|d|day|days|h|hr|hrs|hour|hours"
        r"|mo|month|months|m|min|mins|minute|minutes)",
        raw,
    )
    if match:
        count = max(int(match.group("count") or "1"), 1)
        unit = match.group("unit")
        if unit in {"w", "week", "weeks"}:
            return count * 7.0
        if unit in {"d", "day", "days"}:
            return float(count)
        if unit in {"mo", "month", "months"}:
            return count * 30.0
        if unit in {"h", "hr", "hrs", "hour", "hours"}:
            return count / 24.0
        return count / 1440.0  # minutes
    return VOI_DEFAULT_CADENCE_DAYS


def _days_until(now_dt: datetime, iso: str | None) -> float | None:
    """Days from ``now_dt`` to the ISO instant (negative when already passed), or
    None when unparseable / absent."""

    ts = _parse_datetime(iso)
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (ts - now_dt).total_seconds() / 86400.0


def _voi_sensitivity_map(theses: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-member the BIGGEST thesis it moves: member_id → {abs_delta, delta_p_event,
    thesis_id, thesis_title}. Reads each thesis's stored event sensitivities (the
    finite-difference ∂P(event)/∂p_i already computed by the event MC)."""

    out: dict[str, dict[str, Any]] = {}
    for thesis in theses:
        detail = thesis.get("event_detail") if isinstance(thesis.get("event_detail"), dict) else None
        rows = (detail.get("sensitivities") if detail else None) or thesis.get("top_sensitivities") or []
        for row in rows:
            member_id = row.get("member_id")
            delta = row.get("delta_p_event")
            if not member_id or not isinstance(delta, (int, float)) or isinstance(delta, bool):
                continue
            abs_delta = abs(float(delta))
            prev = out.get(member_id)
            if prev is None or abs_delta > prev["abs_delta"]:
                out[member_id] = {
                    "abs_delta": abs_delta,
                    "delta_p_event": float(delta),
                    "thesis_id": thesis.get("id"),
                    "thesis_title": thesis.get("title"),
                }
    return out


def _voi_for_forecast(
    forecast: dict[str, Any], sens_map: dict[str, dict[str, Any]], now_dt: datetime
) -> dict[str, Any]:
    """The VOI block for one forecast: base·amplifier·readiness score + the honest
    action split, with every component carried so the UI can explain the rank."""

    # (a) staleness — cadence-relative (a weekly question 6d old is due; a monthly
    # one is not). A never-forecast question is maximally stale (a first forecast is
    # high value). Overdue saturates the normalized component at 1.0.
    cadence_days = _cadence_days(forecast.get("review_cadence"))
    age_days: float | None = None
    parsed = _parse_datetime(forecast.get("as_of"))
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now_dt - parsed).total_seconds() / 86400.0)
    if age_days is None:
        stale_ratio, stale_norm = 1.0, 1.0
    else:
        stale_ratio = age_days / cadence_days if cadence_days > 0 else 0.0
        stale_norm = min(1.0, stale_ratio)

    # (c in the spec: event/resolution proximity) — the soonest approaching pull of
    # resolution_time / close_time / next_review_at. resolve_days (resolution/close
    # only) drives the review_due action; days_until (incl. the review) drives prox.
    d_res = _days_until(now_dt, forecast.get("resolution_time"))
    d_close = _days_until(now_dt, forecast.get("close_time"))
    d_review = _days_until(now_dt, forecast.get("next_review_at"))
    resolve_candidates = [d for d in (d_res, d_close) if d is not None]
    resolve_days = min(resolve_candidates) if resolve_candidates else None
    upcoming = [d for d in (d_res, d_close, d_review) if d is not None]
    days_until = min(upcoming) if upcoming else None
    prox_norm = 0.0 if days_until is None else max(0.0, min(1.0, 1.0 - days_until / VOI_PROX_HORIZON_DAYS))

    # open-alert pressure — an unresolved alert is a standing "look at me".
    alert_count = int(forecast.get("open_alert_count") or 0)
    alert_norm = min(1.0, alert_count / VOI_ALERT_FULL) if VOI_ALERT_FULL else 0.0

    base = VOI_W_STALE * stale_norm + VOI_W_PROX * prox_norm + VOI_W_ALERT * alert_norm

    # (b) thesis sensitivity — the AMPLIFIER, not a base term: it multiplies the
    # value of touching a STALE mover, never manufactures value for a fresh one.
    sens = sens_map.get(forecast.get("id"))
    sens_pp = (sens["abs_delta"] * 100.0) if sens else 0.0
    amplifier = 1.0 + min(VOI_SENS_K * sens_pp, VOI_SENS_AMP_CAP)

    # (d) readiness — zero watched sources means an update just re-pools the same
    # priors (no fuel), so we dampen the update value and route to add_sources.
    src_count = int(forecast.get("src_count") or 0)
    has_sources = src_count > 0
    dampen = 1.0 if has_sources else VOI_NO_SOURCE_DAMPEN
    score = base * amplifier * dampen

    # Action split (uses the PRE-dampen base so a stale no-source question still
    # earns add_sources): a pending resolution wins (it needs no sources); else a
    # no-source question routes to add_sources; else an in-play question updates.
    resolve_due = resolve_days is not None and resolve_days <= VOI_RESOLVE_SOON_DAYS
    if base < VOI_ACTION_FLOOR and not resolve_due:
        action = "none"
    elif resolve_due:
        action = "review_due"
    elif not has_sources:
        action = "add_sources"
    else:
        action = "update"

    voi = {
        "score": round(score, 4),
        "action": action,
        "components": {
            "base": round(base, 4),
            "amplifier": round(amplifier, 4),
            "staleness": {
                "age_days": round(age_days, 2) if age_days is not None else None,
                "cadence_days": round(cadence_days, 3),
                "ratio": round(stale_ratio, 3),
                "norm": round(stale_norm, 3),
                "weighted": round(VOI_W_STALE * stale_norm, 4),
            },
            "proximity": {
                "days_until": round(days_until, 2) if days_until is not None else None,
                "resolve_days": round(resolve_days, 2) if resolve_days is not None else None,
                "horizon_days": VOI_PROX_HORIZON_DAYS,
                "norm": round(prox_norm, 3),
                "weighted": round(VOI_W_PROX * prox_norm, 4),
            },
            "alerts": {
                "count": alert_count,
                "norm": round(alert_norm, 3),
                "weighted": round(VOI_W_ALERT * alert_norm, 4),
            },
            "sensitivity": {
                "abs_pp": round(sens_pp, 2),
                "delta_p_event": sens["delta_p_event"] if sens else None,
                "thesis_id": sens["thesis_id"] if sens else None,
                "thesis_title": sens["thesis_title"] if sens else None,
            },
            "readiness": {
                "src_count": src_count,
                "has_sources": has_sources,
                "dampen": dampen,
            },
        },
    }
    voi["reason"] = _voi_reason(forecast, voi)
    return voi


def _cap_first(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _voi_reason(forecast: dict[str, Any], voi: dict[str, Any]) -> str:
    """One human sentence explaining the rank, led by the chosen action. The
    add_sources reason states the honest no-op plainly ("U would re-pool nothing")."""

    comp = voi["components"]
    action = voi["action"]
    stale, sens, prox = comp["staleness"], comp["sensitivity"], comp["proximity"]

    age = stale.get("age_days")
    if age is None:
        stale_clause = "never forecast"
    elif stale["norm"] >= 0.5:
        stale_clause = f"stale {int(round(age))}d ({stale['ratio']:.2f}× cadence)"
    else:
        stale_clause = None

    sens_clause = (
        f"moves “{sens['thesis_title']}” {sens['abs_pp']:.2f}pp"
        if sens.get("thesis_title") and sens["abs_pp"] >= 0.5
        else None
    )

    days_until = prox.get("days_until")
    prox_clause = None
    if days_until is not None:
        prox_clause = "event due now" if days_until <= 0 else f"event in {int(round(days_until))}d"

    if action == "add_sources":
        lead = stale_clause or sens_clause or "on the desk"
        return f"{_cap_first(lead)}, but no watched sources — U would re-pool nothing; add a source first"
    if action == "review_due":
        resolve_days = prox.get("resolve_days")
        when = "now" if (resolve_days is None or resolve_days <= 0) else f"in {int(round(resolve_days))}d"
        return f"Resolves {when} — verify the outcome"

    # update: lead with staleness/sensitivity, add proximity only when it's a real pull.
    parts = [p for p in (stale_clause, sens_clause) if p]
    if prox_clause and (not parts or prox["norm"] >= 0.5):
        parts.append(prox_clause)
    if not parts:
        parts = ["due for a refresh"]
    sentence = _cap_first(parts[0])
    if len(parts) > 1:
        sentence += " and " + ", ".join(parts[1:])
    return sentence


def _attach_voi(
    forecasts: list[dict[str, Any]], theses: list[dict[str, Any]], now_dt: datetime, *, k: int = 5
) -> list[dict[str, Any]]:
    """Stamp a ``voi`` block onto every forecast (in place), rank them by score, and
    return the desk-level top-``k`` next_actions (server-side, so the CLI/agent and
    the TUI read the SAME ranking)."""

    sens_map = _voi_sensitivity_map(theses)
    for forecast in forecasts:
        forecast["voi"] = _voi_for_forecast(forecast, sens_map, now_dt)
    # Rank by score desc; ties keep book order (stable). Rank spans the whole book.
    order = sorted(range(len(forecasts)), key=lambda i: -forecasts[i]["voi"]["score"])
    for rank, idx in enumerate(order, start=1):
        forecasts[idx]["voi"]["rank"] = rank
    actionable = sorted(
        (f for f in forecasts if f["voi"]["action"] != "none"),
        key=lambda f: -f["voi"]["score"],
    )
    return [
        {
            "question_id": f.get("id"),
            "title": f.get("title"),
            "action": f["voi"]["action"],
            "reason": f["voi"]["reason"],
            "score": f["voi"]["score"],
        }
        for f in actionable[:k]
    ]


def build_workspace_payload(
    *,
    ledger: ForecastLedger | None = None,
    limit: int = 50,
    history_limit: int = 80,
    evidence_limit: int = 12,
    now: str | None = None,
    include_related: bool = True,
    include_lessons: bool = True,
) -> dict[str, Any]:
    """Assemble the navigable forecasts-workspace payload in one round trip.

    Returns the list of active forecasts, each bundled with the data the
    detail pane needs — probability time-series (for charting), recent
    evidence, latest multi-perspective panel run, score summary, decision
    card, and structured reasoning — so the TUI can move the highlight with
    arrow keys and render detail instantly without a per-row refetch.
    """

    ledger = ledger or ForecastLedger()
    questions = ledger.list_questions(status="active", limit=limit)
    # Theses are first-class questions but they are aggregates of the others, so
    # they get their own payload section rather than polluting the forecast book.
    member_questions = [q for q in questions if q.outcome_space.type != "thesis"]
    aggregate_questions = [q for q in questions if q.outcome_space.type == "thesis"]
    # Factors (basket return distributions) are theses with aggregation="factor";
    # they get their own payload section, distinct from health theses.
    factor_questions = [q for q in aggregate_questions if ledger.is_factor(q)]
    thesis_questions = [q for q in aggregate_questions if not ledger.is_factor(q)]

    alerts = ledger.list_alerts(unresolved_only=True)
    alert_counts: dict[str, int] = {}
    for alert in alerts:
        if alert.scope_type == "question" and alert.scope_ref:
            alert_counts[alert.scope_ref] = alert_counts.get(alert.scope_ref, 0) + 1

    scores_by_question: dict[str, list[Any]] = {}
    for score in ledger.list_scores():
        scores_by_question.setdefault(score.question_id, []).append(score)

    # The live next-update schedule per question (self-advancing) for the desk's
    # NEXT column — one batched query, not the stale question.next_review_at column.
    next_reviews = ledger.next_review_by_question()

    # "Closing soon" = the close-review reasons review_questions(stale=False)
    # would emit (close_time_passed / resolution_check_due). With stale=False
    # those reduce to close_time<=now OR resolution_time<=now, so a single cheap
    # filter replaces the heavy per-question review walk (~0.8s) with no change
    # in semantics. (is_close_review_reason is kept imported for the close badge
    # contract elsewhere in this module.)
    closing_ids = ledger.closing_question_ids(now=now)

    # Collapse the per-question N+1: fetch every per-question dataset the loop
    # needs in ONE batched query each (keyed by question_id), mirroring the
    # already-batched scores_by_question above. Each lookup defaults to the same
    # empty value the singular method would have produced.
    member_ids = [question.id for question in member_questions]
    snapshots_by_q = ledger.snapshots_by_question(member_ids)
    evidence_by_q = ledger.evidence_by_question(member_ids)
    panel_by_q = ledger.latest_panel_run_by_question(member_ids)
    resolution_by_q = ledger.latest_resolution_by_question(member_ids)
    notes_by_q = ledger.analyst_notes_by_question(member_ids)
    theses_by_member = ledger.theses_by_member(member_ids)

    # Machine-readiness composite (the operator's hidden-parameter visibility): two
    # more batched GROUP BYs — active watched-source counts + active reference-class
    # counts, keyed by question id. Every OTHER readiness dimension is already in
    # memory (structured components off the current snapshot, executable triggers on
    # the question row, an enabled scheduled review is presence in next_reviews, and
    # close_time/impact/resolution_criteria are question columns) — so this adds ONLY
    # these two queries for the WHOLE book, never one per question.
    from forecasting.readiness_lens import question_machine_readiness

    watch_counts = ledger.active_watched_source_counts(member_ids)
    ref_class_counts = ledger.active_reference_class_counts(member_ids)

    # Saturation visibility (Wave 3 H4): the under-saturation bar, read ONCE for the
    # whole page (config forecasting.hooks.sweep_alert_threshold, default 60). Each
    # forecast row carries its stored observe-mode score + a below-threshold flag so
    # the desk can badge under-saturated forecasts; the score is read from the
    # current snapshot's metadata already in memory (no added query).
    from forecasting.hooks import sweep_alert_threshold as _sweep_alert_threshold

    saturation_threshold = _sweep_alert_threshold()

    # In-flight auto-quorum runs keyed by question (ONE jobs-dir scan for the whole
    # page) so the desk can badge a "quorum running" chip on the row whose commit
    # just kicked one off + poll forecast.quorum.status by the surfaced run_id.
    try:
        from forecasting.jobs.types.quorum import active_jobs_by_question

        active_quorum_by_q = active_jobs_by_question()
    except Exception:
        active_quorum_by_q = {}

    closing_soon = 0
    forecasts: list[dict[str, Any]] = []
    for question in member_questions:
        snapshots = snapshots_by_q.get(question.id, [])
        current = snapshots[-1] if snapshots else None
        previous = snapshots[-2] if len(snapshots) >= 2 else None
        evidence_items = evidence_by_q.get(question.id, [])
        panel_run = panel_by_q.get(question.id)
        panel_runs = [panel_run] if panel_run is not None else []
        resolution = resolution_by_q.get(question.id)
        analyst_notes = notes_by_q.get(question.id, [])
        question_scores = scores_by_question.get(question.id, [])

        probability = current.probability_or_distribution if current else None
        closing = question.id in closing_ids
        if closing:
            closing_soon += 1

        # Machine-readiness: the desk's visibility into the hidden per-question
        # workability parameters. src_count is the ACTIVE watched-source count;
        # readiness is the 0-100 composite + the exact-fix gap list. All inputs
        # are already in memory here (only watch/ref-class counts were batched).
        _watch_count = watch_counts.get(question.id, 0)
        _components = current.ensemble_components if current else None
        readiness = question_machine_readiness(
            question_id=question.id,
            watch_count=_watch_count,
            has_components=bool(_components) if isinstance(_components, dict) else False,
            ref_class_count=ref_class_counts.get(question.id, 0),
            update_triggers=question.update_triggers,
            has_scheduled_review=question.id in next_reviews,
            close_time=question.close_time,
            impact=question.impact,
            resolution_rule=question.resolution_criteria,
        )

        outcome_type = question.outcome_space.type
        distribution = _distribution_view(probability) if current else None
        # A distribution forecast tracks a continuous central tendency (a mean
        # in the outcome's units); binary/categorical track a probability.
        headline_kind = "distribution" if (outcome_type == "distribution" and distribution) else "probability"

        # Lessons that should STRUCTURE this forecast (scope-matched: domain / topic /
        # domain_topic / question_type) — the same retrieval the agent reads + that
        # compiles to commit rules. This is "what shaped / should shape this forecast",
        # distinct from the source-derived lessons this question's own miss produced.
        # Gated: active_lessons_for_question fires ~8 scope queries per question and
        # is only read by the detail modal (forecast.question carries it instead).
        # Skipping it for the navigable LIST is the bulk of the desk's load speedup.
        relevant_lessons: list[dict[str, Any]] = []
        if include_lessons:
            try:
                from forecasting.learning import active_lessons_for_question

                relevant_lessons = [
                    {
                        "id": lesson["id"],
                        "lesson": (lesson.get("lesson") or "")[:200],
                        "scope_type": lesson.get("scope_type"),
                        "scope_ref": lesson.get("scope_ref"),
                        "confidence": lesson.get("confidence"),
                    }
                    for lesson in active_lessons_for_question(ledger, question)
                ]
            except Exception:
                relevant_lessons = []

        forecasts.append(
            {
                "id": question.id,
                "title": question.title,
                "status": question.status,
                "domain": question.domain,
                "topics": list(question.topics or []),
                "impact": question.impact,
                "close_time": question.close_time,
                "resolution_time": question.resolution_time,
                "resolution_criteria": question.resolution_criteria,
                "outcome_type": outcome_type,
                "outcome_choices": list(question.outcome_space.choices or []),
                "units": question.outcome_space.units,
                "headline_kind": headline_kind,
                "probability": probability,
                "probability_display": format_probability(probability) if current else "-",
                "headline_probability": _headline_numeric(probability) if current else None,
                "distribution": distribution,
                # Per-candidate 90% intervals for a vote-share PMF (from metadata) so
                # the TUI can draw per-candidate error bars; None when not supplied.
                "candidate_intervals": _candidate_intervals(current) if current else None,
                # Movement of the headline value (probability for binary/categorical,
                # mean for distribution) since the previous snapshot, in headline units.
                "delta": _headline_delta(
                    previous.probability_or_distribution if previous else None,
                    probability if current else None,
                ),
                "confidence": current.confidence if current else None,
                "as_of": current.as_of if current else None,
                "method": current.method if current else None,
                "rationale": current.rationale if current else None,
                "reasons_up": list(current.reasons_up) if current else [],
                "reasons_down": list(current.reasons_down) if current else [],
                "change_my_mind": list(current.change_my_mind) if current else [],
                "tail_audit": _snapshot_tail_audit(current),
                # Observe-mode saturation score (0-100) recorded on the current
                # snapshot + whether it is under the alert bar — glanceable desk
                # signal that this forecast is under-saturated. None when unscored.
                "saturation_score": (_sat_score := _snapshot_saturation_score(current) if current else None),
                "saturation_below_threshold": (
                    _sat_score is not None and _sat_score < saturation_threshold
                ),
                "decision_owner": question.decision_owner,
                "decision_deadline": question.decision_deadline,
                "action_threshold": question.action_threshold,
                "update_triggers": list(question.update_triggers or []),
                "decision_readiness_issues": ledger.decision_readiness_issues(question),
                "evidence_count": len(evidence_items),
                "open_alert_count": alert_counts.get(question.id, 0),
                # Run id + status of an in-flight auto-quorum for this question, else
                # None — the desk chip polls forecast.quorum.status by this run_id.
                "quorum_run": active_quorum_by_q.get(question.id),
                "relevant_lessons": relevant_lessons,
                "lessons_count": len(relevant_lessons),
                "snapshot_count": len(snapshots),
                "freshness": format_freshness(current.as_of if current else None, now=now),
                # The live next auto-reforecast time + cadence (the desk's NEXT column).
                "next_review_at": (next_reviews.get(question.id) or {}).get("next_run_at"),
                "review_cadence": (next_reviews.get(question.id) or {}).get("cadence"),
                "closing_soon": closing,
                "history": [
                    _workspace_history_point(item, is_distribution=headline_kind == "distribution")
                    for item in snapshots[-history_limit:]
                ],
                "evidence": [_workspace_evidence(item) for item in evidence_items[-evidence_limit:]],
                "panel": _workspace_panel(panel_runs[0]) if panel_runs else None,
                "scores": _workspace_scores(question_scores) if question_scores else None,
                "resolution": _workspace_resolution(resolution) if resolution else None,
                # The analyst write-up stream: the latest brief drives the desk
                # quick-read, the full list is the reviewable time series, and the
                # retrospective (if any) is the terminal note.
                "analyst_note": _workspace_analyst_note(analyst_notes[-1]) if analyst_notes else None,
                "analyst_notes": [_workspace_analyst_note(note) for note in analyst_notes[-history_limit:]],
                "retrospective": _workspace_analyst_note(
                    next((note for note in reversed(analyst_notes) if note.get("kind") == "retrospective"), None)
                ),
                # Cross-pollination: related forecasts' world-views, the "informed
                # by" provenance of the current snapshot, and shared-source flags.
                # Gated: related_forecast_views is an N^2 same-domain rescan per
                # question (~59% of build time) and only the detail modal reads it,
                # so the LIST skips it and forecast.question carries it instead.
                "related": _workspace_related(ledger, question, current) if include_related else None,
                # The theses this question is a weighted member of (the "member
                # of: AI infra thesis" badge). Batched (theses_by_member) to
                # collapse the per-member N+1 — same value as
                # list_theses_for_member(question.id), one query for the page.
                "thesis_ids": theses_by_member.get(question.id, []),
                # Machine-readiness (the operator's hidden-parameter visibility):
                # the active watched-source count + the 0-100 composite with an
                # exact-fix gap list per missing dimension.
                "src_count": _watch_count,
                "readiness": readiness,
            }
        )

    theses = [
        _workspace_thesis(ledger, question, now=now, history_limit=history_limit)
        for question in thesis_questions
    ]
    factors = [
        _workspace_factor(ledger, question, now=now, history_limit=history_limit)
        for question in factor_questions
    ]

    # VOI-driven desk attention: stamp a per-forecast voi block (rank + explainable
    # components + action) and build the desk-level next_actions, once the forecasts
    # AND theses are in memory (the sensitivity amplifier reads the thesis event MC).
    now_dt = _parse_datetime(now) if isinstance(now, str) else None
    now_dt = now_dt or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    next_actions = _attach_voi(forecasts, theses, now_dt)

    return {
        "product": PRODUCT_NAME,
        "generated_at": utc_now_iso(),
        "active_count": len(member_questions),
        "open_alert_count": len(alerts),
        "closing_soon_count": closing_soon,
        "forecasts": forecasts,
        # VOI-driven "what should I touch next?": the top-5 highest-value actions
        # across the book, each with a one-sentence reason + its action verb.
        "next_actions": next_actions,
        # Thesis layer: macro forecasts that aggregate the weighted beliefs of
        # their tagged members (computed after the members' latest runs).
        "thesis_count": len(thesis_questions),
        "theses": theses,
        # Factor layer: weighted baskets aggregated by portfolio math into a
        # return distribution + volatility + downside.
        "factor_count": len(factor_questions),
        "factors": factors,
        # ForecastBench backtest replays resolve immediately, so they live OUTSIDE
        # the active workspace forecast list. The desk's read-only Bench lens keys
        # its visibility off this count (the scoreboard itself loads via forecast.bench).
        "bench_count": len(ledger.list_questions(domain="forecastbench")),
    }


def _bench_binary_prob_yes(payload: Any, choices: list[str] | None) -> float | None:
    """Pull the P(yes) scalar out of a binary forecast/baseline payload.

    Binary snapshots and ForecastBench market baselines store a bare float that is
    already P(first-choice) — the "yes" leg — so a scalar is returned verbatim. A
    dict payload (defensive: a {"yes": .., "no": ..} categorical) is read by the
    first choice label. Anything else → None (uncomputable, never faked)."""

    if isinstance(payload, bool):  # bool is an int subclass — reject before float
        return None
    if isinstance(payload, (int, float)):
        return float(payload)
    if isinstance(payload, dict):
        keys = [str(choices[0])] if choices else []
        keys += ["yes", "y", "true"]
        lowered = {str(k).lower(): v for k, v in payload.items()}
        for key in keys:
            value = lowered.get(str(key).lower())
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _bench_outcome_binary(outcome: Any, choices: list[str] | None) -> float | None:
    """Map a confirmed binary resolution label to the 0.0/1.0 the brier uses.

    Mirrors ``ledger._brier_score``'s yes/no convention: the first outcome-space
    choice (or a yes/true/1 synonym) → 1.0, else 0.0. Unrecognized → None."""

    if outcome is None:
        return None
    if isinstance(outcome, bool):
        return 1.0 if outcome else 0.0
    if isinstance(outcome, (int, float)):
        if abs(float(outcome) - 1.0) < 1e-9:
            return 1.0
        if abs(float(outcome) - 0.0) < 1e-9:
            return 0.0
        return None
    label = str(outcome).strip().lower()
    yes_labels = {"yes", "y", "true", "1", "occurred", "success"}
    no_labels = {"no", "n", "false", "0", "not_occurred", "failed"}
    first_choice = str(choices[0]).lower() if choices else "yes"
    if label in yes_labels or label == first_choice:
        return 1.0
    if label in no_labels or (choices and len(choices) > 1 and label == str(choices[1]).lower()):
        return 0.0
    return None


def _bench_brier(prob_yes: float | None, outcome_binary: float | None) -> float | None:
    """Pure binary Brier = (p − y)². Read-only: never touches the ledger / scoring."""

    if prob_yes is None or outcome_binary is None:
        return None
    return round((float(prob_yes) - float(outcome_binary)) ** 2, 6)


def _bench_market_baseline(ledger: ForecastLedger, question_id: str) -> dict[str, Any] | None:
    """The de-vigged market freeze baseline for a bench question (read-only).

    Prefers the ``market`` baseline_type (the ForecastBench freeze_datetime_value
    carried by ``forecastbench.build_forecastbench_case``); the most recent one
    wins when several exist. Returns the raw comparison dict or None."""

    market: dict[str, Any] | None = None
    for comparison in ledger.list_baseline_comparisons(question_id):
        if str(comparison.get("baseline_type") or "") == "market":
            market = comparison  # list is as_of ASC → last assignment is newest
    return market


def build_bench_scoreboard(
    *,
    ledger: ForecastLedger | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Assemble the READ-ONLY ForecastBench backtest scoreboard.

    For every question with ``domain == "forecastbench"`` (or tag ``bench`` /
    ``forecastbench`` as a fallback) this reads — never mutates — the question's
    current agent snapshot, its de-vigged market freeze baseline, its confirmed
    resolution, and the recorded agent score, and emits one row carrying the
    agent probability, the market freeze price, the resolved 0/1 outcome, and the
    agent vs market Brier. The aggregate is the mean agent Brier vs the mean
    market Brier over the rows where BOTH are computable, plus the paired count.

    Pure: uses only ``list_questions`` / ``list_snapshots`` /
    ``get_latest_resolution`` / ``list_baseline_comparisons`` / ``get_current_score``.
    The agent Brier comes from the already-recorded ``ScoreRecord`` when present
    (force=False, so no scoring is triggered); the market Brier is computed in
    Python from the stored baseline probability + the resolved outcome, so a
    scoreboard renders even before baselines have been separately scored."""

    ledger = ledger or ForecastLedger()

    # Domain isolation is the primary selector (forecastbench.py sets it on every
    # ingested case); the tag fallback catches any hand-built bench question that
    # carries "bench"/"forecastbench" tags but a different domain. De-duplicated by id.
    questions = list(ledger.list_questions(domain="forecastbench"))
    seen = {q.id for q in questions}
    for question in ledger.list_questions():
        if question.id in seen:
            continue
        tags = {str(tag).lower() for tag in (question.tags or [])}
        if tags & {"bench", "forecastbench"}:
            questions.append(question)
            seen.add(question.id)

    rows: list[dict[str, Any]] = []
    for question in questions:
        snapshots = ledger.list_snapshots(question.id)
        # The agent forecast is the most recent NON-baseline snapshot (a scored
        # baseline rides as an imported_baseline snapshot on the same question).
        agent_snapshot = next(
            (s for s in reversed(snapshots) if s.forecast_origin != "imported_baseline"),
            None,
        )
        resolution = ledger.get_latest_resolution(question.id, confirmed_only=True)
        choices = list(question.outcome_space.choices or [])

        agent_prob = (
            _bench_binary_prob_yes(agent_snapshot.probability_or_distribution, choices)
            if agent_snapshot
            else None
        )
        market_comparison = _bench_market_baseline(ledger, question.id)
        market_prob = (
            _bench_binary_prob_yes(market_comparison.get("probability_or_distribution"), choices)
            if market_comparison
            else None
        )
        outcome_label = resolution.outcome if resolution else None
        outcome_binary = _bench_outcome_binary(outcome_label, choices)

        # The agent Brier: prefer the recorded ScoreRecord (no rescoring); fall
        # back to the pure formula so a row scores even if scoring hasn't run.
        recorded = ledger.get_current_score(question.id)
        agent_brier = recorded.brier_score if recorded and recorded.brier_score is not None else None
        if agent_brier is None:
            agent_brier = _bench_brier(agent_prob, outcome_binary)
        market_brier = _bench_brier(market_prob, outcome_binary)

        source = (
            (question.metadata or {}).get("forecastbench_source")
            or (question.topics[0] if question.topics else None)
        )

        rows.append(
            {
                "id": question.id,
                "title": question.title,
                "source": source,
                "domain": question.domain,
                "topics": list(question.topics or []),
                "as_of": agent_snapshot.as_of if agent_snapshot else None,
                "resolved_at": resolution.resolved_at if resolution else None,
                "agent_probability": agent_prob,
                "agent_probability_display": format_probability(agent_prob) if agent_prob is not None else "-",
                "market_probability": market_prob,
                "market_probability_display": format_probability(market_prob) if market_prob is not None else "-",
                "outcome": outcome_binary,
                "outcome_label": str(outcome_label) if outcome_label is not None else None,
                "resolved": outcome_binary is not None,
                "agent_brier": agent_brier,
                "market_brier": market_brier,
                # Per-row edge: positive = agent beat the market freeze on Brier.
                "brier_edge": (
                    round(market_brier - agent_brier, 6)
                    if agent_brier is not None and market_brier is not None
                    else None
                ),
            }
        )

    # Newest-resolved first, then newest-forecast, so the freshest backtests lead.
    rows.sort(key=lambda r: (r.get("resolved_at") or "", r.get("as_of") or ""), reverse=True)
    if limit is not None and limit >= 0:
        rows = rows[:limit]

    paired = [
        r for r in rows if r.get("agent_brier") is not None and r.get("market_brier") is not None
    ]
    mean_agent = (
        round(sum(r["agent_brier"] for r in paired) / len(paired), 6) if paired else None
    )
    mean_market = (
        round(sum(r["market_brier"] for r in paired) / len(paired), 6) if paired else None
    )
    resolved_count = sum(1 for r in rows if r.get("resolved"))

    return {
        "product": PRODUCT_NAME,
        "generated_at": utc_now_iso(),
        "count": len(rows),
        "resolved_count": resolved_count,
        "rows": rows,
        "aggregate": {
            "n": len(paired),
            "mean_agent_brier": mean_agent,
            "mean_market_brier": mean_market,
            # Positive = the agent's mean Brier is lower than the market freeze's
            # (lower Brier is better), i.e. the agent beat the honest baseline.
            "mean_brier_edge": (
                round(mean_market - mean_agent, 6)
                if mean_agent is not None and mean_market is not None
                else None
            ),
        },
    }


def _thesis_history_point(snapshot: Any) -> dict[str, Any]:
    """One point in a thesis's health/score time series (for the trend chart)."""

    payload = snapshot.probability_or_distribution
    payload = payload if isinstance(payload, dict) else {}
    # When the thesis is a joint-event, P(event) is the headline series; else the
    # mean-index health. Both are 0..1 so the trend chart never mixes scales.
    event_probability = payload.get("event_probability")
    return {
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        "headline_probability": event_probability if event_probability is not None else payload.get("health"),
        "health_probability": payload.get("health"),
        "event_probability": event_probability,
        "thesis_score": payload.get("thesis_score"),
        "score_low": payload.get("q05"),
        "score_high": payload.get("q95"),
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


def _headline_delta(previous: Any, current: Any) -> float | None:
    """Change in the headline value (probability or mean) between two snapshots."""

    prev = _headline_numeric(previous)
    curr = _headline_numeric(current)
    if prev is None or curr is None:
        return None
    return curr - prev


def _finite_number(value: Any) -> float | None:
    """Return ``value`` as a finite float, or ``None`` for bool/NaN/Inf/non-numeric.

    Non-finite values (NaN, ±Inf) are rejected because they corrupt the
    time-series chart. Finite values outside [0, 1] are kept on purpose:
    numeric / distribution outcomes (e.g. a CPI mean of 3.1) legitimately
    exceed the probability range.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _headline_numeric(payload: Any) -> float | None:
    """Pick one finite numeric value per forecast for time-series charting.

    Binary/numeric forecasts are a bare float. Probability dicts collapse to
    the max outcome probability; ``{mean: ...}`` distributions to the mean.
    Returns ``None`` when nothing finite can be extracted.
    """

    scalar = _finite_number(payload)
    if scalar is not None:
        return scalar
    if isinstance(payload, dict):
        for key in ("mean", "mu", "expected", "value"):
            candidate = _finite_number(payload.get(key))
            if candidate is not None:
                return candidate
        numeric = [
            number
            for value in payload.values()
            if (number := _finite_number(value)) is not None
        ]
        if numeric and all(0.0 <= value <= 1.0 for value in numeric):
            return max(numeric)
        if numeric:
            return numeric[0]
    return None


_MOMENT_MEAN_KEYS = ("mean", "mu", "expected")
_MOMENT_SD_KEYS = ("sd", "sigma", "std", "stdev")
_NON_PMF_KEYS = {
    "mean",
    "mu",
    "expected",
    "median",
    "mode",
    "sd",
    "sigma",
    "std",
    "stdev",
    "variance",
    "var",
    "skew",
    "skewness",
    "kurtosis",
    "value",
}
_Z90 = 1.6449  # standard-normal quantile for a 90% central interval
_Z50 = 0.6745  # ...and 50%


def _distribution_view(payload: Any) -> dict[str, Any] | None:
    """Split a distribution payload into moments / intervals / bucket PMF.

    A distribution forecast (e.g. CPI YoY) stores a continuous summary
    (``mean``/``median``/``sd``, ``interval_50_*``/``interval_90_*``,
    ``equivalent_normal_*``) *and* a discrete bucket PMF
    (``bucket_le_4_0``…``bucket_ge_4_4``) in one dict, mixing probability and
    outcome-unit values. This separates them so the TUI can chart the mean in
    its units, draw the PMF as its own histogram, and show the moments as a
    stat block — instead of plotting everything on one nonsensical scale.

    Returns ``None`` for scalars / non-dict payloads (binary forecasts) or
    dicts with no recoverable mean (plain categorical PMFs are handled
    elsewhere).
    """

    if not isinstance(payload, dict):
        return None

    moments: dict[str, float] = {}
    intervals: dict[str, list[float | None]] = {}
    equivalent: dict[str, float] = {}
    pmf: dict[str, float] = {}
    quantiles: dict[int, float] = {}

    for raw_key, raw_value in payload.items():
        value = _finite_number(raw_value)
        if value is None:
            continue
        key = str(raw_key).lower()

        interval = re.match(r"^(?:interval|ci|hdi|pi)[_-]?(\d{1,2})[_-]?(low|lo|l|high|hi|h)$", key)
        if interval:
            pctile = interval.group(1)
            side = 0 if interval.group(2) in ("low", "lo", "l") else 1
            intervals.setdefault(pctile, [None, None])[side] = value
            continue
        # Quantile keys (q05/q50/q95, quantile_25, percentile_90) — a common
        # distribution representation the model uses. Parse BEFORE the PMF catch
        # so percent-valued quantiles (e.g. CPI's q05=0.05, in [0,1]) aren't
        # mistaken for probability mass. Bare pNN keys stay PMF (count buckets).
        qmatch = re.match(r"^(?:q|quantile|percentile)[_-]?(\d{1,3})$", key)
        if qmatch:
            pct = int(qmatch.group(1))
            if 1 <= pct <= 99:
                quantiles[pct] = value
            continue
        if key.startswith("equivalent_normal_"):
            equivalent[key[len("equivalent_normal_") :]] = value
            continue
        if key in _MOMENT_MEAN_KEYS:
            moments.setdefault("mean", value)
            continue
        if key == "median":
            moments["median"] = value
            continue
        if key in _MOMENT_SD_KEYS:
            moments.setdefault("sd", value)
            continue
        if key in _NON_PMF_KEYS:
            continue
        # Remaining numeric entries that look like probability mass.
        if 0.0 <= value <= 1.0:
            pmf[str(raw_key)] = value

    # Fold quantiles into the canonical shape: q50 -> median, q25/q75 -> 50%
    # interval, q05/q95 -> 90% interval, and a normal-equivalent sd from the
    # widest available pair so the stat block + chart band always render.
    if quantiles:
        if 50 in quantiles:
            moments.setdefault("median", quantiles[50])
            moments.setdefault("mean", quantiles[50])
        if 25 in quantiles and 75 in quantiles:
            existing = intervals.setdefault("50", [None, None])
            existing[0] = existing[0] if existing[0] is not None else quantiles[25]
            existing[1] = existing[1] if existing[1] is not None else quantiles[75]
        if 5 in quantiles and 95 in quantiles:
            existing = intervals.setdefault("90", [None, None])
            existing[0] = existing[0] if existing[0] is not None else quantiles[5]
            existing[1] = existing[1] if existing[1] is not None else quantiles[95]
        if "sd" not in moments:
            if 5 in quantiles and 95 in quantiles:
                moments["sd"] = (quantiles[95] - quantiles[5]) / 3.2897
            elif 10 in quantiles and 90 in quantiles:
                moments["sd"] = (quantiles[90] - quantiles[10]) / 2.5631
            elif 25 in quantiles and 75 in quantiles:
                moments["sd"] = (quantiles[75] - quantiles[25]) / 1.349

    # Count distributions (p0, p1, ..., p6_plus) carry their uncertainty in the
    # PMF, not in quantile keys, so derive the median / 90% interval / sd from the
    # discrete CDF. Without this the chart band falls back to a degenerate
    # confidence-score band (e.g. +/- 0.06) that misrepresents a Poisson count.
    # Only when EVERY pmf label is count-like and no interval is already present
    # (so the CPI bucket-mixture, which ships interval_* keys, is untouched).
    if pmf and not intervals and "sd" not in moments:
        counts: dict[int, float] = {}
        all_counts = True
        for label, prob in pmf.items():
            match = re.match(r"^p_?(\d+)(?:_?plus|\+)?$", str(label).lower())
            if match:
                counts[int(match.group(1))] = counts.get(int(match.group(1)), 0.0) + prob
            else:
                all_counts = False
                break
        total = sum(counts.values()) if all_counts else 0.0
        if all_counts and counts and total > 0:
            ordered = sorted(counts.items())
            expected = sum(value * (prob / total) for value, prob in ordered)
            variance = sum((value - expected) ** 2 * (prob / total) for value, prob in ordered)
            cdf = 0.0
            q05 = q50 = q95 = None
            for value, prob in ordered:
                cdf += prob / total
                if q05 is None and cdf >= 0.05:
                    q05 = value
                if q50 is None and cdf >= 0.5:
                    q50 = value
                if q95 is None and cdf >= 0.95:
                    q95 = value
            if q50 is not None:
                moments.setdefault("median", float(q50))
            moments.setdefault("mean", expected)
            moments["sd"] = variance ** 0.5
            if q05 is not None and q95 is not None:
                intervals.setdefault("90", [float(q05), float(q95)])

    mean = moments.get("mean")
    if mean is None:
        mean = equivalent.get("mean")
    sd = moments.get("sd")
    if sd is None:
        sd = equivalent.get("sd")
    median = moments.get("median")

    pmf_rows: list[dict[str, Any]] | None = None
    if len(pmf) >= 2:
        total = sum(pmf.values())
        if 0.8 <= total <= 1.2:  # a genuine probability mass, not stray fields
            pmf_rows = [
                {"label": label, "probability": value}
                for label, value in sorted(pmf.items(), key=lambda kv: kv[1], reverse=True)
            ]

    if mean is None and pmf_rows is None:
        return None

    def _interval(pctile: str, z: float) -> list[float] | None:
        existing = intervals.get(pctile)
        if existing and existing[0] is not None and existing[1] is not None:
            return [existing[0], existing[1]]
        if mean is not None and sd is not None:
            return [mean - z * sd, mean + z * sd]
        return None

    return {
        "mean": mean,
        "median": median,
        "sd": sd,
        "ci50": _interval("50", _Z50),
        "ci90": _interval("90", _Z90),
        "pmf": pmf_rows,
    }


def _workspace_history_point(snapshot: Any, *, is_distribution: bool = False) -> dict[str, Any]:
    payload = snapshot.probability_or_distribution
    point: dict[str, Any] = {
        "forecast_id": snapshot.forecast_id,
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        "probability": payload,
        "headline_probability": _headline_numeric(payload),
        "confidence": snapshot.confidence,
        "method": snapshot.method,
        "forecast_origin": snapshot.forecast_origin,
        "rationale": truncate(snapshot.rationale or "", 160),
        "reasons_up_count": len(snapshot.reasons_up or []),
        "reasons_down_count": len(snapshot.reasons_down or []),
        "band_low": None,
        "band_high": None,
    }
    if is_distribution:
        view = _distribution_view(payload)
        # Band tracks the snapshot's OWN 90% interval (in outcome units) — never
        # a panel probability spread, which lives on a different scale.
        if view and view.get("ci90"):
            point["band_low"], point["band_high"] = view["ci90"]
        if view and view.get("mean") is not None:
            point["headline_probability"] = view["mean"]
    return point


def _workspace_evidence(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "available_at": item.available_at,
        "published_at": item.published_at,
        "source": item.source_url or item.source_name or item.source_type,
        "source_type": item.source_type,
        "claim": item.claim,
        "summary": item.summary,
        "stance": item.stance,
        "claim_type": item.claim_type,
        "reliability_rating": item.reliability_rating,
        "relevance_rating": item.relevance_rating,
    }


def _workspace_panel(run: dict[str, Any]) -> dict[str, Any]:
    estimates = [
        {
            "perspective": row.get("perspective"),
            "probability": row.get("probability"),
            "weight": row.get("weight"),
            "trimmed": bool(row.get("trimmed")),
            "crux": row.get("crux"),
            "confidence_low": row.get("confidence_low"),
            "confidence_high": row.get("confidence_high"),
        }
        for row in (run.get("estimates") or [])
    ]
    return {
        "id": run.get("id"),
        "created_at": run.get("created_at"),
        "aggregation_method": run.get("aggregation_method"),
        "trim": run.get("trim"),
        "aggregate_probability": run.get("aggregate_probability"),
        # AIA P0.3: which branch produced the committed aggregate
        # ('pool' | 'judge_high'), defaulting to 'pool' for pre-P0.3 runs.
        "final_source": run.get("final_source") or "pool",
        "spread": run.get("spread_summary") or {},
        "estimates": estimates,
    }


def _workspace_scores(scores: list[Any]) -> dict[str, Any]:
    briers = [s.brier_score for s in scores if isinstance(s.brier_score, (int, float))]
    logs = [s.log_score for s in scores if isinstance(s.log_score, (int, float))]
    latest = scores[0] if scores else None
    return {
        "count": len(scores),
        "mean_brier": (sum(briers) / len(briers)) if briers else None,
        "mean_log_score": (sum(logs) / len(logs)) if logs else None,
        "last_bucket": latest.calibration_bucket if latest else None,
        "last_scored_at": latest.scored_at if latest else None,
    }


def _workspace_resolution(resolution: Any) -> dict[str, Any]:
    return {
        "outcome": resolution.outcome,
        "resolution_status": resolution.resolution_status,
        "resolved_at": resolution.resolved_at,
        "scoreable": resolution.scoreable,
    }


def _workspace_analyst_note(note: dict[str, Any] | None) -> dict[str, Any] | None:
    if not note:
        return None
    return {
        "as_of": note.get("as_of"),
        "created_at": note.get("created_at"),
        "kind": note.get("kind"),
        "headline": note.get("headline"),
        "body": note.get("body"),
        "how_it_feels": note.get("how_it_feels"),
        "how_it_thinks": note.get("how_it_thinks"),
        "looking_for": note.get("looking_for"),
        "be_aware": note.get("be_aware"),
        "stance": note.get("stance"),
        "verdict": note.get("verdict"),
        "forecast_id": note.get("forecast_id"),
        "generator": note.get("generator"),
    }


def _workspace_related_one(rel: dict[str, Any]) -> dict[str, Any]:
    prob = rel.get("probability_or_distribution")
    dist = _distribution_view(prob)
    if dist and dist.get("mean") is not None:
        headline_kind = "distribution"
        headline_probability = dist.get("mean")
        probability_display = f"μ {float(dist['mean']):.4g}"
    elif isinstance(prob, (int, float)) and not isinstance(prob, bool) and 0.0 <= prob <= 1.0:
        headline_kind = "probability"
        headline_probability = float(prob)
        probability_display = f"{round(prob * 100)}%"
    else:
        headline_kind = "probability"
        headline_probability = _headline_numeric(prob)
        probability_display = (
            f"{headline_probability:.4g}" if isinstance(headline_probability, (int, float)) else "-"
        )
    return {
        "id": rel.get("id"),
        "title": rel.get("title"),
        "relationship": rel.get("relationship"),
        "link_type": "auto" if rel.get("link_type") == "auto" else "explicit",
        "link_label": rel.get("link_label"),
        "headline_kind": headline_kind,
        "headline_probability": headline_probability,
        "probability_display": probability_display,
        "as_of": rel.get("as_of"),
        "note_headline": rel.get("headline"),
        "be_aware": rel.get("be_aware"),
        "stance": rel.get("stance"),
        "verdict": rel.get("verdict"),
        "reasons_up": list(rel.get("reasons_up") or []),
        "reasons_down": list(rel.get("reasons_down") or []),
    }


def _workspace_related(ledger: Any, question: Any, current: Any) -> dict[str, Any] | None:
    related, shared = ledger.related_forecast_views(question)
    metadata = getattr(current, "metadata", None) if current else None
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    informed = list(((metadata or {}).get("cross_refs") or {}).get("informed_by") or [])
    if not related and not informed and not shared:
        return None
    return {
        "forecasts": [_workspace_related_one(rel) for rel in related],
        "informed_by": informed,
        "shared_sources": [{"source": s, "kind": "watched_source", "shared_with": []} for s in shared],
    }


def render_dashboard_text(summary: dict[str, Any]) -> str:
    rows = list(summary.get("questions") or [])
    lines = [
        str(summary.get("product") or PRODUCT_NAME),
        (
            f"active: {summary.get('active_count', 0)}  "
            f"open_alerts: {summary.get('open_alert_count', 0)}  "
            f"review_queue: {summary.get('review_queue_count', 0)}  "
            f"closing_soon: {summary.get('closing_soon_count', 0)}  "
            f"assumptions: {summary.get('open_assumption_count', 0)}/{summary.get('stale_assumption_count', 0)}  "
            f"refs: {summary.get('open_reference_class_count', 0)}/{summary.get('stale_reference_class_count', 0)}  "
            f"calibration_n: {(summary.get('calibration') or {}).get('count', 0)}"
        ),
        "",
    ]
    if not rows:
        lines.append("ACTIVE FORECASTS")
        lines.append("No active forecasts.")
    else:
        lines.append("ACTIVE FORECASTS")
        lines.append(
            f"{'ID':<14} {'P(now)':<12} {'AsOf':<20} {'Delta':<8} {'Conf':<6} {'Close':<20} "
            f"{'Ev':>3} {'Base':>4} {'Refs':>5} {'Assump':>7} {'Alerts':>6}  Question"
        )
        for row in rows:
            assumptions = f"{row.get('open_assumption_count', 0)}/{row.get('stale_assumption_count', 0)}"
            references = (
                f"{row.get('open_reference_class_count', 0)}/"
                f"{row.get('stale_reference_class_count', 0)}"
            )
            lines.append(
                f"{row.get('id', '-'):<14} "
                f"{format_probability(row.get('probability')):<12} "
                f"{str(row.get('as_of') or '-'):<20} "
                f"{format_delta(row.get('delta')):<8} "
                f"{format_confidence(row.get('confidence')):<6} "
                f"{str(row.get('close_time') or '-'):<20} "
                f"{int(row.get('evidence_count') or 0):>3} "
                f"{int(row.get('baseline_count') or 0):>4} "
                f"{references:>5} "
                f"{assumptions:>7} "
                f"{int(row.get('open_alert_count') or 0):>6}  "
                f"{row.get('title') or ''}"
            )
    theses = list(summary.get("theses") or [])
    if theses:
        lines.extend(["", "THESIS HEALTH"])
        lines.append(
            f"{'ID':<14} {'Health':<8} {'Score':<7} {'Delta':<7} {'Cov':<6} {'n_eff':<6} {'Mem':>3}  Thesis"
        )
        for th in theses:
            score = f"{th['thesis_score']:.0f}" if th.get("thesis_score") is not None else "-"
            delta = f"{th['delta'] * 100:+.0f}pp" if th.get("delta") is not None else "-"
            cov = f"{th['coverage']:.0%}" if th.get("coverage") is not None else "-"
            n_eff = f"{th['n_eff']:.1f}" if th.get("n_eff") is not None else "-"
            lines.append(
                f"{th.get('id', '-'):<14} "
                f"{th.get('health_display', '-'):<8} "
                f"{score:<7} "
                f"{delta:<7} "
                f"{cov:<6} "
                f"{n_eff:<6} "
                f"{int(th.get('member_count') or 0):>3}  "
                f"{th.get('title') or ''}"
            )

    review_queue = list(summary.get("review_queue") or [])
    if review_queue:
        lines.extend(["", "Review Queue"])
        lines.append(
            f"{'ID':<14} {'P(now)':<12} {'AsOf':<20} {'Close':<20} {'Priority':<8} Reasons"
        )
        for row in review_queue:
            reasons = ",".join(row.get("reasons") or [])
            lines.append(
                f"{row.get('id', '-'):<14} "
                f"{format_probability(row.get('probability')):<12} "
                f"{str(row.get('as_of') or '-'):<20} "
                f"{str(row.get('close_time') or '-'):<20} "
                f"{int(row.get('priority') or 9):<8} "
                f"{reasons}"
            )
            if row.get("next_action"):
                lines.append(f"  next: {row['next_action']}")
    alerts = list(summary.get("alerts") or [])
    if alerts:
        lines.extend(["", "Open Alerts"])
        lines.append(f"{'ID':<14} {'Severity':<8} {'Scope':<18} Reason")
        for row in alerts:
            scope = f"{row.get('scope_type') or '-'}:{row.get('scope_ref') or '-'}"
            lines.append(
                f"{row.get('id', '-'):<14} "
                f"{str(row.get('severity') or '-'):<8} "
                f"{truncate(scope, 18):<18} "
                f"{truncate(str(row.get('reason') or '-'), 80)}"
            )
            if row.get("recommended_action"):
                lines.append(f"  next: {row['recommended_action']}")
    scheduled_runs = list(summary.get("scheduled_review_runs") or [])
    if scheduled_runs:
        lines.extend(["", "Scheduled Self-Checks"])
        lines.append(
            f"{'Run':<14} {'Schedule':<14} {'Scope':<22} {'Alerts':>6} {'Scores':>6} {'PMs':>4} {'Learn':>5} Next"
        )
        for row in scheduled_runs:
            lines.append(
                f"{row.get('id', '-'):<14} "
                f"{row.get('scheduled_review_id', '-'):<14} "
                f"{truncate(format_schedule_run_scope(row), 22):<22} "
                f"{int(row.get('alert_count') or 0):>6} "
                f"{int(row.get('score_count') or 0):>6} "
                f"{int(row.get('postmortem_count') or 0):>4} "
                f"{int(row.get('learning_review_count') or 0):>5} "
                f"{row.get('next_run_at') or '-'}"
            )
    calibration = dict(summary.get("calibration") or {})
    if calibration:
        lines.extend(["", "Calibration"])
        lines.append(f"count: {calibration.get('count', 0)}")
        lines.append(f"mean_brier: {format_metric(calibration.get('mean_brier'))}")
        lines.append(f"mean_log_score: {format_metric(calibration.get('mean_log_score'))}")
        lines.append(f"mean_sharpness: {format_metric(calibration.get('mean_sharpness'))}")
        lines.append(
            "mean_abs_movement_before_close: "
            f"{format_metric(calibration.get('mean_abs_probability_movement_before_close'))}"
        )
        components = list(calibration.get("ensemble_component_contributions") or [])
        if components:
            lines.append("ensemble_component_contributions:")
            for row in components[:5]:
                lines.append(
                    "  "
                    f"{row.get('name') or '-'}: "
                    f"n={int(row.get('count') or 0)} "
                    f"mean_contribution={format_metric(row.get('mean_contribution'))} "
                    f"weight_share={format_metric(row.get('mean_weight_share'))} "
                    f"mean_probability={format_metric(row.get('mean_probability'))}"
                )
        question_types = list(calibration.get("question_type_breakdown") or [])
        if question_types:
            lines.append("question_type_breakdown:")
            for row in question_types[:5]:
                lines.append(
                    "  "
                    f"{row.get('question_type') or '-'}: "
                    f"n={int(row.get('count') or 0)} "
                    f"brier_n={int(row.get('brier_count') or 0)} "
                    f"mean_brier={format_metric(row.get('mean_brier'))} "
                    f"mean_proper_score={format_metric(row.get('mean_proper_score'))}"
                )
    learning = dict(summary.get("learning") or {})
    if learning:
        lines.extend(["", "Learning Memory"])
        lines.append(
            f"lessons: {int(learning.get('total_lessons') or 0)}  "
            f"active: {int(learning.get('active_lessons') or 0)}  "
            f"tentative: {int(learning.get('tentative_lessons') or 0)}  "
            f"invalidated: {int(learning.get('invalidated_lessons') or 0)}"
        )
        profiles = list(learning.get("top_error_profiles") or [])
        if profiles:
            lines.append(f"{'Scope':<24} {'N':>4} {'Brier':<10} Errors")
            for row in profiles:
                scope = format_error_profile_scope(row)
                errors = ",".join(row.get("recurring_errors") or []) or "-"
                lines.append(
                    f"{scope:<24} "
                    f"{int(row.get('sample_count') or 0):>4} "
                    f"{format_metric(row.get('mean_brier')):<10} "
                    f"{errors}"
                )
        lessons = list(learning.get("recent_lessons") or [])
        if lessons:
            lines.append("Recent Lessons")
            for row in lessons:
                scope = f"{row.get('scope_type') or 'global'}:{row.get('scope_ref') or '*'}"
                lines.append(
                    f"- {row.get('status') or '-'} {scope} "
                    f"{truncate(str(row.get('lesson') or ''), 96)}"
                )
    doctor = dict(summary.get("doctor") or {})
    if doctor:
        lines.extend(["", "Doctor Gate"])
        lines.append(
            f"status: {doctor.get('doctor_status') or '-'}  "
            f"pilot: {int(doctor.get('pilot_passed_checks') or 0)}/"
            f"{int(doctor.get('pilot_total_checks') or 0)}  "
            f"readiness: {doctor.get('readiness_verdict') or '-'}  "
            f"gaps: {int(doctor.get('readiness_gap_count') or 0)}  "
            f"schedule_runs: {int(doctor.get('scheduled_review_run_count') or 0)}  "
            f"claim_live_superforecasting: {bool(doctor.get('claim_live_superforecasting'))}"
        )
        next_actions = list(doctor.get("next_actions") or [])
        for item in next_actions[:3]:
            requirement = item.get("requirement_id") or item.get("source") or "doctor"
            action = item.get("action") or "-"
            lines.append(f"  next {requirement}: {action}")
    evidence_status = dict(summary.get("evidence_status") or {})
    if evidence_status:
        score_counts = dict(evidence_status.get("score_counts") or {})
        backtest_counts = dict(evidence_status.get("backtests") or {})
        lines.extend(["", "Evidence Status"])
        lines.append(
            f"verdict: {evidence_status.get('verdict') or '-'}  "
            f"live_scored: {score_counts.get('live', 0)}  "
            f"agent_protocol_scored: {backtest_counts.get('agent_protocol_scored_count', 0)}  "
            f"leakage_free_runs: {backtest_counts.get('leakage_free_run_count', 0)}  "
            f"positive_edge_runs: {backtest_counts.get('positive_best_baseline_edge_run_count', 0)}  "
            f"datasets: {backtest_counts.get('distinct_dataset_count', 0)}  "
            f"external_datasets: {backtest_counts.get('external_dataset_count', 0)}  "
            f"external_source_families: {backtest_counts.get('external_source_family_count', 0)}"
        )
        gaps = list(evidence_status.get("gaps") or [])
        if gaps:
            lines.append(f"gaps: {', '.join(gaps[:5])}")
        next_actions = list(evidence_status.get("next_actions") or [])
        for item in next_actions[:3]:
            requirement = item.get("requirement_id") or "evidence"
            action = item.get("action") or "-"
            lines.append(f"  next {requirement}: {action}")
    live_performance = dict(summary.get("live_performance") or {})
    if live_performance and (
        int(live_performance.get("score_count") or 0)
        or list(live_performance.get("baselines") or [])
    ):
        agent = dict(live_performance.get("agent") or {})
        baselines = list(live_performance.get("baselines") or [])
        lines.extend(["", "Live Performance"])
        lines.append(
            f"scores: {int(live_performance.get('score_count') or 0)}  "
            f"agent_brier: {format_metric(agent.get('mean_brier'))}  "
            f"baselines: {len(baselines)}  "
            f"claim: {format_claim_status((live_performance.get('claim_status') or {}))}"
        )
        if baselines:
            lines.append(
                f"{'Baseline':<24} {'Brier':<10} {'Paired':>6} {'Edge':<8} {'CI95':<19} {'W/L/T':<7}"
            )
            for baseline in baselines:
                name = f"{baseline.get('baseline_type') or '-'}:{baseline.get('source') or '-'}"
                lines.append(
                    f"{truncate(name, 24):<24} "
                    f"{format_metric(baseline.get('mean_brier')):<10} "
                    f"{int(baseline.get('paired_count') or 0):>6} "
                    f"{format_delta(baseline.get('mean_brier_improvement_vs_baseline')):<8} "
                    f"{format_ci95(baseline.get('paired_agent_edge_ci95_low'), baseline.get('paired_agent_edge_ci95_high')):<19} "
                    f"{format_wins(baseline):<7}"
                )
    backtests = list(summary.get("recent_backtests") or [])
    if backtests:
        lines.extend(["", "Recent Backtests"])
        lines.append(
            f"{'ID':<14} {'AgentBrier':<11} {'Source':<16} {'BestBaseline':<24} {'Edge':<8} {'W/L/T':<7} {'Claim':<20} Dataset"
        )
        for row in backtests:
            baseline = row.get("best_baseline") or "-"
            baseline_brier = format_metric(row.get("best_baseline_brier"))
            wins = format_wins(row)
            claim = format_claim_status(row.get("claim_status"))
            sources = ",".join(row.get("probability_sources") or ["dataset"])
            lines.append(
                f"{row.get('id', '-'):<14} "
                f"{format_metric(row.get('agent_mean_brier')):<11} "
                f"{sources[:16]:<16} "
                f"{(baseline + '=' + baseline_brier)[:24]:<24} "
                f"{format_delta(row.get('agent_edge')):<8} "
                f"{wins:<7} "
                f"{claim:<20} "
                f"{row.get('dataset') or '-'}"
            )
    return "\n".join(lines)


def build_doctor_gate_summary(
    pilot_report: dict[str, Any],
    evidence_status: dict[str, Any],
) -> dict[str, Any]:
    pilot_ready = pilot_report.get("passed_checks") == pilot_report.get("total_checks")
    readiness_gaps = list(evidence_status.get("gaps") or [])
    if not pilot_ready:
        doctor_status = "needs_tester_pilot_artifacts"
    elif readiness_gaps:
        doctor_status = "tester_handoff_ready_live_claim_unproven"
    else:
        doctor_status = "benchmark_evidence_ready_live_claim_unproven"

    pilot_gaps = [row for row in pilot_report.get("checks", []) if not row.get("passed")]
    pilot_next_actions = list(pilot_report.get("next_actions") or [])
    readiness_next_actions = list(evidence_status.get("next_actions") or [])
    next_actions: list[dict[str, str | None]] = []
    for row in pilot_gaps:
        action = row.get("recommended_action")
        if action:
            next_actions.append(
                {
                    "source": "pilot",
                    "requirement_id": row.get("id"),
                    "action": str(action),
                }
            )
    if not next_actions:
        for action in pilot_next_actions:
            next_actions.append(
                {
                    "source": "pilot",
                    "requirement_id": "pilot",
                    "action": str(action),
                }
            )
    for item in readiness_next_actions:
        next_actions.append(
            {
                "source": "readiness",
                "requirement_id": item.get("requirement_id"),
                "action": item.get("action"),
            }
        )
    first_action = next_actions[0] if next_actions else {}

    return {
        "doctor_status": doctor_status,
        "tester_handoff_ready": pilot_ready,
        "claim_live_superforecasting": bool(evidence_status.get("can_claim_live_superforecasting")),
        "pilot_status": pilot_report.get("pilot_status"),
        "pilot_passed_checks": int(pilot_report.get("passed_checks") or 0),
        "pilot_total_checks": int(pilot_report.get("total_checks") or 0),
        "pilot_gap_count": len(pilot_gaps),
        "readiness_verdict": evidence_status.get("verdict"),
        "readiness_gap_count": len(readiness_gaps),
        "scheduled_review_run_count": int(
            (pilot_report.get("summary") or {}).get("scheduled_review_run_count") or 0
        ),
        "next_actions": next_actions[:5],
        "next_action": first_action.get("action"),
        "next_requirement": first_action.get("requirement_id"),
    }


def build_learning_summary(*, ledger: ForecastLedger, limit: int = 5) -> dict[str, Any]:
    lessons = ledger.list_calibration_lessons(active_only=False)
    active_lessons = [
        row
        for row in lessons
        if row.get("status") == "active" and not row.get("invalidated_by_correction_id")
    ]
    tentative_lessons = [
        row
        for row in lessons
        if row.get("status") == "tentative" and not row.get("invalidated_by_correction_id")
    ]
    invalidated_lessons = [row for row in lessons if row.get("invalidated_by_correction_id")]
    profiles = sorted(
        ledger.list_domain_error_profiles(),
        key=lambda row: (
            int(row.get("sample_count") or 0),
            _metric_number((row.get("calibration_summary") or {}).get("mean_brier")),
            str(row.get("updated_at") or ""),
        ),
        reverse=True,
    )
    return {
        "total_lessons": len(lessons),
        "active_lessons": len(active_lessons),
        "tentative_lessons": len(tentative_lessons),
        "invalidated_lessons": len(invalidated_lessons),
        "top_error_profiles": [summarize_error_profile(row) for row in profiles[:limit]],
        "recent_lessons": [summarize_calibration_lesson(row) for row in lessons[:limit]],
    }


def summarize_error_profile(row: dict[str, Any]) -> dict[str, Any]:
    calibration = dict(row.get("calibration_summary") or {})
    return {
        "id": row.get("id"),
        "domain": row.get("domain"),
        "topic": row.get("topic"),
        "question_type": row.get("question_type"),
        "sample_count": int(row.get("sample_count") or 0),
        "mean_brier": calibration.get("mean_brier"),
        "recurring_errors": list(row.get("recurring_errors") or []),
        "recommended_adjustments": list(row.get("recommended_adjustments") or []),
        "updated_at": row.get("updated_at"),
    }


def summarize_calibration_lesson(row: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "id": row.get("id"),
        "status": row.get("status"),
        "scope_type": row.get("scope_type"),
        "scope_ref": row.get("scope_ref"),
        "confidence": row.get("confidence"),
        "lesson": row.get("lesson"),
        "recommended_adjustment": dict(row.get("recommended_adjustment") or {}),
        "source_postmortem_count": len(row.get("source_postmortem_refs") or []),
        "source_score_count": len(row.get("source_score_record_refs") or []),
        "updated_at": row.get("updated_at"),
    }
    # Surface the signed-bias provenance so dashboards can show direction /
    # magnitude / convergence trajectory for self-correcting lessons.
    metadata = dict(row.get("metadata") or {})
    if metadata.get("source") == "calibration_bias":
        sce = metadata.get("sce_shrunk")
        summary["bias"] = {
            "direction": metadata.get("direction"),
            "sce_shrunk_pp": None if sce is None else round(float(sce) * 100, 1),
            "ess": metadata.get("ess"),
            "n": metadata.get("n"),
            "ci_pp": [
                None if v is None else round(float(v) * 100, 1)
                for v in (metadata.get("ci") or [None, None])
            ],
            "trajectory_pp": [round(float(v) * 100, 1) for v in (metadata.get("sce_trajectory") or [])],
            "horizon_label": metadata.get("horizon_label"),
            "suppressed": bool(metadata.get("suppressed")),
        }
    return summary


def summarize_alert(alert: Any) -> dict[str, Any]:
    return {
        "id": alert.id,
        "created_at": alert.created_at,
        "severity": alert.severity,
        "scope_type": alert.scope_type,
        "scope_ref": alert.scope_ref,
        "reason": alert.reason,
        "recommended_action": alert.recommended_action,
        "acknowledged_at": alert.acknowledged_at,
    }


def summarize_scheduled_review_run(row: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(row.get("metadata") or {})
    return {
        "id": row.get("id"),
        "scheduled_review_id": row.get("scheduled_review_id"),
        "run_at": row.get("run_at"),
        "next_run_at": row.get("next_run_at"),
        "alert_count": int(row.get("alert_count") or 0),
        "score_count": int(row.get("score_count") or 0),
        "postmortem_count": int(row.get("postmortem_count") or 0),
        "learning_review_count": int(row.get("learning_review_count") or 0),
        "status": row.get("status"),
        "scope_type": metadata.get("scope_type"),
        "scope_ref": metadata.get("scope_ref"),
        "cadence": metadata.get("cadence"),
        "auto_score": bool(metadata.get("auto_score")),
        "auto_postmortem": bool(metadata.get("auto_postmortem")),
        "alert_reasons": list(metadata.get("alert_reasons") or []),
    }


def format_error_profile_scope(row: dict[str, Any]) -> str:
    scope = str(row.get("domain") or "global")
    if row.get("topic"):
        scope = f"{scope}/{row['topic']}"
    if row.get("question_type"):
        scope = f"{scope}:{row['question_type']}"
    return truncate(scope, 24)


def format_schedule_run_scope(row: dict[str, Any]) -> str:
    scope_type = str(row.get("scope_type") or "schedule")
    scope_ref = row.get("scope_ref")
    if scope_type == "domain_topic" and isinstance(scope_ref, str):
        try:
            payload = json.loads(scope_ref)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            return f"domain:{payload.get('domain', '*')}/{payload.get('topic', '*')}"
    return f"{scope_type}:{scope_ref or '*'}"


def truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max(0, max_length - 3)] + "..."


def _metric_number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return -1.0


def probability_delta(previous: Any, current: Any) -> float | None:
    if isinstance(previous, (int, float)) and isinstance(current, (int, float)):
        return float(current) - float(previous)
    return None


def format_probability(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.3f}"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    if value is None:
        return "-"
    return str(value)


def format_delta(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):+.3f}"
    return "-"


def format_confidence(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}"
    return "-"


def format_freshness(value: str | None, *, now: datetime | str | None = None) -> str:
    if not value:
        return "no as-of"

    timestamp = _parse_datetime(value)
    if not timestamp:
        return "as-of set"

    now_dt = _parse_datetime(now) if isinstance(now, str) else now
    now_dt = now_dt or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    age_days = max(0, int((now_dt - timestamp).total_seconds() // 86400))
    if age_days == 0:
        return "fresh today"
    if age_days == 1:
        return "1d old"
    if age_days < 31:
        return f"{age_days}d old"
    return f"{age_days // 30}mo old"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def render_forecast_book_text(summary: dict[str, Any], *, now: datetime | str | None = None) -> str:
    rows = list(summary.get("questions") or [])
    lines = [
        str(summary.get("product") or PRODUCT_NAME),
        (
            f"active: {summary.get('active_count', 0)}  "
            f"open_alerts: {summary.get('open_alert_count', 0)}  "
            f"review_queue: {summary.get('review_queue_count', 0)}"
        ),
        "",
        "FORECAST QUESTIONS",
    ]

    if not rows:
        lines.append("No active forecasts.")
        return "\n".join(lines)

    lines.append(
        f"{'Row':<5} {'P(now)':<12} {'Delta':<8} {'Freshness':<12} {'AsOf':<12} "
        f"{'Close':<12} {'Conf':<6} {'Ev':>3} {'Status':<12} Question"
    )
    for index, row in enumerate(rows, start=1):
        status = question_status(row)
        lines.append(
            f"{index:<5} "
            f"{format_probability(row.get('probability')):<12} "
            f"{format_delta(row.get('delta')):<8} "
            f"{format_freshness(row.get('as_of'), now=now):<12} "
            f"{short_date(row.get('as_of')):<12} "
            f"{short_date(row.get('close_time')):<12} "
            f"{format_confidence(row.get('confidence')):<6} "
            f"{int(row.get('evidence_count') or 0):>3} "
            f"{status:<12} "
            f"{row.get('title') or ''}"
        )
    lines.extend(
        [
            "",
            (
                "Open details with /questions <row> or /book <row>; "
                "use /questions <words> or /find <words> to search; "
                "use /questions list 50 for more rows."
            ),
        ]
    )
    return "\n".join(lines)


def short_date(value: str | None) -> str:
    return str(value or "-")[:10]


def question_status(row: dict[str, Any]) -> str:
    alerts = int(row.get("open_alert_count") or 0)
    stale_assumptions = int(row.get("stale_assumption_count") or 0)
    stale_references = int(row.get("stale_reference_class_count") or 0)
    if alerts > 0:
        return f"{alerts} alert" if alerts == 1 else f"{alerts} alerts"
    if stale_assumptions > 0:
        return "stale asm"
    if stale_references > 0:
        return "stale ref" if stale_references == 1 else "stale refs"
    if row.get("probability") is None:
        return "needs p"
    return str(row.get("status") or "active")


def format_metric(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.6f}"
    return "-"


def format_wins(row: dict[str, Any]) -> str:
    return (
        f"{int(row.get('paired_agent_wins') or 0)}/"
        f"{int(row.get('paired_baseline_wins') or 0)}/"
        f"{int(row.get('paired_ties') or 0)}"
    )


def format_ci95(low: Any, high: Any) -> str:
    if isinstance(low, (int, float)) and isinstance(high, (int, float)):
        return f"[{float(low):+.3f},{float(high):+.3f}]"
    return "-"


def format_claim_status(value: Any) -> str:
    if not isinstance(value, dict):
        return "-"
    verdict = str(value.get("verdict") or "").strip()
    if verdict == "benchmark_replay_only":
        return "replay only"
    return verdict.replace("_", " ")[:20] if verdict else "-"


def review_next_action(question_id: str, reasons: list[str]) -> str:
    if any(reason.startswith("new_evidence:") for reason in reasons):
        return f"forecast research {question_id}; forecast update {question_id} --preview ..."
    if any(reason.startswith("domain_error_profile_applies:") for reason in reasons):
        return f"forecast show {question_id}; forecast update {question_id} --preview ..."
    if "no_forecast_snapshot" in reasons:
        return f"forecast update {question_id} --preview ..."
    if any(
        reason in {"resolution_check_due", "close_time_passed"}
        or reason.startswith("close_time_within_")
        for reason in reasons
    ):
        return f"forecast resolve {question_id} --outcome <value>"
    if "no_evidence" in reasons or any(reason.startswith("evidence_stale_") for reason in reasons):
        return f"forecast research {question_id}"
    if any(reason.startswith(("assumption_", "reference_class_")) for reason in reasons):
        return f"forecast protocol {question_id} --stage self_check"
    if "review_due" in reasons or any(reason.startswith("last_update_") for reason in reasons):
        return f"forecast research {question_id}; forecast update {question_id} --preview ..."
    return f"forecast show {question_id}"


def is_close_review_reason(reason: str) -> bool:
    return (
        reason in {"resolution_check_due", "close_time_passed"}
        or reason.startswith("close_time_within_")
    )


def alert_promotes_to_review(reason: str | None) -> bool:
    return str(reason or "").startswith("domain_error_profile_applies:")


def alert_review_priority(reason: str | None) -> int:
    if str(reason or "").startswith("domain_error_profile_applies:"):
        return 4
    return 7
