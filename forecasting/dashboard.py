"""Forecast dashboard summaries shared by CLI, TUI, and web surfaces."""

from __future__ import annotations

import json
import math
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


def build_dashboard_summary(
    *, ledger: ForecastLedger | None = None, limit: int = 50, now: str | None = None
) -> dict[str, Any]:
    ledger = ledger or ForecastLedger()
    questions = ledger.list_questions(status="active", limit=limit)
    alerts = ledger.list_alerts(unresolved_only=True)
    alert_counts: dict[str, int] = {}
    for alert in alerts:
        if alert.scope_type == "question" and alert.scope_ref:
            alert_counts[alert.scope_ref] = alert_counts.get(alert.scope_ref, 0) + 1
    alert_rows = [summarize_alert(alert) for alert in alerts[: min(limit, 12)]]

    rows = []
    for question in questions:
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
            }
        )

    review_queue = []
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
            }
        )
    review_rows_by_id = {str(row["id"]): row for row in review_queue if row.get("id")}
    for alert in alerts:
        if not alert_promotes_to_review(alert.reason):
            continue
        question_id = alert.scope_ref if alert.scope_type == "question" else None
        if not question_id:
            continue
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

    closing_soon_count = sum(
        1
        for row in review_queue
        if any(is_close_review_reason(reason) for reason in row.get("reasons", []))
    )

    calibration = ledger.calibration_summary(calibration_eligible=True)
    backtest_summaries = []
    recent_backtests = []
    for run in ledger.list_backtest_runs()[: min(limit, 20)]:
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
        paired_wins = (
            {
                "paired_count": best.get("paired_brier_count"),
                "paired_agent_edge": best.get("paired_agent_edge_mean_brier"),
                "paired_agent_edge_ci95_low": best.get("paired_agent_edge_ci95_low"),
                "paired_agent_edge_ci95_high": best.get("paired_agent_edge_ci95_high"),
                "paired_agent_wins": best.get("paired_agent_wins"),
                "paired_baseline_wins": best.get("paired_baseline_wins"),
                "paired_ties": best.get("paired_ties"),
            }
            if best is not None
            else {
                "paired_count": 0,
                "paired_agent_edge": None,
                "paired_agent_edge_ci95_low": None,
                "paired_agent_edge_ci95_high": None,
                "paired_agent_wins": 0,
                "paired_baseline_wins": 0,
                "paired_ties": 0,
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

    evidence_status = build_forecasting_evidence_status(ledger, backtest_summaries)
    live_performance = ledger.live_performance_report()
    pilot_report = ledger.pilot_report()
    doctor = build_doctor_gate_summary(pilot_report, evidence_status)

    return {
        "product": PRODUCT_NAME,
        "active_count": len(questions),
        "open_alert_count": len(alerts),
        "review_queue_count": len(review_queue),
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
        "review_queue": review_queue,
        "alerts": alert_rows,
        "recent_backtests": recent_backtests,
    }


def build_workspace_payload(
    *,
    ledger: ForecastLedger | None = None,
    limit: int = 50,
    history_limit: int = 80,
    evidence_limit: int = 12,
    now: str | None = None,
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

    alerts = ledger.list_alerts(unresolved_only=True)
    alert_counts: dict[str, int] = {}
    for alert in alerts:
        if alert.scope_type == "question" and alert.scope_ref:
            alert_counts[alert.scope_ref] = alert_counts.get(alert.scope_ref, 0) + 1

    scores_by_question: dict[str, list[Any]] = {}
    for score in ledger.list_scores():
        scores_by_question.setdefault(score.question_id, []).append(score)

    closing_ids = {
        row["question"].id
        for row in ledger.review_questions(stale=False, now=now)
        if any(is_close_review_reason(reason) for reason in (row.get("reasons") or []))
    }

    closing_soon = 0
    forecasts: list[dict[str, Any]] = []
    for question in questions:
        snapshots = ledger.list_snapshots(question.id)
        current = snapshots[-1] if snapshots else None
        previous = snapshots[-2] if len(snapshots) >= 2 else None
        evidence_items = ledger.list_evidence(question.id)
        panel_runs = ledger.list_panel_runs(question.id, limit=1)
        resolution = ledger.get_latest_resolution(question.id)
        question_scores = scores_by_question.get(question.id, [])

        probability = current.probability_or_distribution if current else None
        closing = question.id in closing_ids
        if closing:
            closing_soon += 1

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
                "outcome_type": question.outcome_space.type,
                "outcome_choices": list(question.outcome_space.choices or []),
                "units": question.outcome_space.units,
                "probability": probability,
                "probability_display": format_probability(probability) if current else "-",
                "headline_probability": _headline_numeric(probability) if current else None,
                "delta": probability_delta(
                    previous.probability_or_distribution if previous else None,
                    probability,
                ),
                "confidence": current.confidence if current else None,
                "as_of": current.as_of if current else None,
                "method": current.method if current else None,
                "rationale": current.rationale if current else None,
                "reasons_up": list(current.reasons_up) if current else [],
                "reasons_down": list(current.reasons_down) if current else [],
                "change_my_mind": list(current.change_my_mind) if current else [],
                "decision_owner": question.decision_owner,
                "decision_deadline": question.decision_deadline,
                "action_threshold": question.action_threshold,
                "update_triggers": list(question.update_triggers or []),
                "decision_readiness_issues": ledger.decision_readiness_issues(question),
                "evidence_count": len(evidence_items),
                "open_alert_count": alert_counts.get(question.id, 0),
                "snapshot_count": len(snapshots),
                "freshness": format_freshness(current.as_of if current else None, now=now),
                "closing_soon": closing,
                "history": [_workspace_history_point(item) for item in snapshots[-history_limit:]],
                "evidence": [_workspace_evidence(item) for item in evidence_items[-evidence_limit:]],
                "panel": _workspace_panel(panel_runs[0]) if panel_runs else None,
                "scores": _workspace_scores(question_scores) if question_scores else None,
                "resolution": _workspace_resolution(resolution) if resolution else None,
            }
        )

    return {
        "product": PRODUCT_NAME,
        "generated_at": utc_now_iso(),
        "active_count": len(questions),
        "open_alert_count": len(alerts),
        "closing_soon_count": closing_soon,
        "forecasts": forecasts,
    }


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


def _workspace_history_point(snapshot: Any) -> dict[str, Any]:
    return {
        "forecast_id": snapshot.forecast_id,
        "as_of": snapshot.as_of,
        "created_at": snapshot.created_at,
        "probability": snapshot.probability_or_distribution,
        "headline_probability": _headline_numeric(snapshot.probability_or_distribution),
        "confidence": snapshot.confidence,
        "method": snapshot.method,
        "forecast_origin": snapshot.forecast_origin,
        "rationale": truncate(snapshot.rationale or "", 160),
        "reasons_up_count": len(snapshot.reasons_up or []),
        "reasons_down_count": len(snapshot.reasons_down or []),
    }


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
    return {
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
