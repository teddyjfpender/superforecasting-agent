"""Scoring domain (D9 carve — resolution scoring, calibration, lesson application).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns the SCORING surface:

* score compute + readers (``score_question`` / ``score_snapshot`` /
  ``get_score`` / ``get_current_score`` / ``list_scores`` / ``_existing_score`` /
  ``_log_score``) and the ``_row_to_score`` / ``_score_to_dict`` serializers;
* the Brier / distribution scoring helpers (``_brier_score`` /
  ``_vote_share_vector_score`` / ``_normal_distribution_score`` / ``_numeric_bucket``
  / ``_probability_bucket`` / ``_score_summary`` / ``_score_breakdown`` /
  ``_score_horizon_bucket`` / ``_score_probability_movement_before_close``) and the
  seeded paired-bootstrap edge test (``_paired_brier_summary`` / ``_paired_bootstrap``
  / ``_percentile``);
* calibration display (``calibration_summary`` + ``_snapshot_component_contributions``
  / ``_calibration_trend`` / ``operator_calibration_summary`` + ``_operator_vs_system``
  / ``_operator_binary_observed`` / ``calibration_bias`` / ``_bias_observations`` /
  ``_live_score_count`` / ``_domains_with_scores``);
* lesson APPLICATION auditing (``_audit_unapplied_lessons`` /
  ``_record_lesson_applications`` — the two commit-cascade helpers D4 left for D9).

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed.

Dependency direction (no cycle, per the D1 finding): this leaf owns its two
leaf-exclusive paired-bootstrap constants (``PAIRED_BOOTSTRAP_SEED`` /
``PAIRED_BOOTSTRAP_DRAWS`` — re-exported on the package surface via ``__init__``
for parity) and imports only ``forecasting.models`` + stdlib at load time. Its
ONE ``_core.`` hop is the SHARED ``BRIER_COIN_FLIP_FLOOR`` (also read by the
stayed ``rescore_backtest_run``), reached as ``_core.BRIER_COIN_FLIP_FLOOR`` at
call time — the module handle binds a partial ``core`` safely (mirrors D4's
``_core.FORECASTING_PROTOCOL_VERSION``). The scores table is UNGATED, so there is
no write-gate import; every cross-domain read (``get_question`` /
``get_current_snapshot`` / ``get_snapshot`` / ``get_resolution`` /
``get_latest_resolution`` / ``list_snapshots`` / ``list_operator_estimates`` /
``list_calibration_lessons`` / ``_score_forecast_payload`` (the shared scoring
gate that stays in core, D5/D6) / ``_binary_outcome_value`` / ``_horizon_matches``
/ the numeric primitives ``_mean`` / ``_numeric_probability`` / ``_numeric_outcome``
/ ``_sharpness``) resolves through the ``ledger`` INSTANCE.
"""

from __future__ import annotations

import logging
import math
import random
import re
import sqlite3
import statistics
import uuid
from collections import defaultdict
from datetime import timedelta
from typing import Any

from forecasting.ledger import core as _core
from forecasting.models import (
    ForecastSnapshot,
    LedgerNotFoundError,
    OutcomeSpace,
    ScoreRecord,
    ValidationError,
    recency_halflife_weight,
    timestamp_to_datetime,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

# AIA P0.2 — paired bootstrap significance.
#
# The paired Brier edge (per resolved question: baseline_brier - agent_brier,
# POSITIVE = agent better) is tested for significance with a SEEDED, deterministic
# paired bootstrap so the p-value and CI reproduce byte-for-byte across runs.
# PAIRED_BOOTSTRAP_SEED fixes the random.Random stream; PAIRED_BOOTSTRAP_DRAWS
# is the number of resample-means drawn for both the recenter-at-zero p-value and
# the uncentered percentile CI.
PAIRED_BOOTSTRAP_SEED = 0xA1A02
PAIRED_BOOTSTRAP_DRAWS = 10000


def _audit_unapplied_lessons(
    ledger,
    question: Any,
    committed_payload: Any,
    calibration_adjustment: dict[str, Any] | None,
) -> int:
    """Count active in-scope NUMERIC calibration lessons the committed forecast
    did NOT actually apply.

    "Applied" means the committed number net-MOVED from the recorded pre-lesson
    raw payload (the trusted marker ``apply_active_lesson_adjustments`` writes) —
    NOT that a lesson ref was stapled on. So citation-stapling no longer satisfies
    the gate, and an in-scope lesson the agent simply ignored is counted as
    unapplied. Prose lessons (no numeric key) are not counted here; they are
    enforced as compiled rules in a later slice. Best-effort: any failure returns
    0 so the audit can never break a commit."""
    try:
        from forecasting.learning import active_lessons_for_question

        active = active_lessons_for_question(ledger, question)
    except Exception:
        return 0
    if not active:
        return 0
    adjustment = calibration_adjustment or {}
    applied_ids = {
        item.get("id")
        for item in (adjustment.get("applied_active_lessons") or [])
        if isinstance(item, dict)
    }
    raw = adjustment.get("raw_probability")
    committed = (
        committed_payload
        if isinstance(committed_payload, (int, float)) and not isinstance(committed_payload, bool)
        else None
    )
    unapplied = 0
    for lesson in active:
        recommended = lesson.get("recommended_adjustment") or {}
        is_numeric = any(k in recommended for k in ("probability_delta", "logit_shift", "logit_scale"))
        if not is_numeric:
            continue
        net_moved = (
            lesson["id"] in applied_ids
            and isinstance(raw, (int, float))
            and committed is not None
            and abs(committed - float(raw)) > 1e-9
        )
        if not net_moved:
            unapplied += 1
    return unapplied


def _record_lesson_applications(
    ledger,
    question: Any,
    snapshot_id: str | None,
    committed_payload: Any,
    calibration_adjustment: dict[str, Any] | None,
) -> None:
    """Coverage ledger: one row per active in-scope lesson at a successful commit
    (kind + whether it was applied). Best-effort — never raises into the commit."""
    try:
        from forecasting.learning import active_lessons_for_question

        active = active_lessons_for_question(ledger, question)
        if not active:
            return
        adjustment = calibration_adjustment or {}
        applied_ids = {
            item.get("id")
            for item in (adjustment.get("applied_active_lessons") or [])
            if isinstance(item, dict)
        }
        raw = adjustment.get("raw_probability")
        committed = (
            committed_payload
            if isinstance(committed_payload, (int, float)) and not isinstance(committed_payload, bool)
            else None
        )
        now = utc_now_iso()
        rows = []
        for lesson in active:
            recommended = lesson.get("recommended_adjustment") or {}
            if isinstance(recommended.get("rule"), dict):
                # The commit SUCCEEDED, so an error-severity lesson rule passed
                # (it would otherwise have blocked); recorded as applied.
                kind, applied = "rule", 1
            elif any(k in recommended for k in ("probability_delta", "logit_shift", "logit_scale")):
                kind = "numeric"
                applied = 1 if (
                    lesson["id"] in applied_ids
                    and isinstance(raw, (int, float))
                    and committed is not None
                    and abs(committed - float(raw)) > 1e-9
                ) else 0
            else:
                kind, applied = "advisory", 0
            rows.append((f"la_{uuid.uuid4().hex[:12]}", lesson["id"], question.id, snapshot_id, kind, applied, now))
        if rows:
            with ledger._connect() as conn:
                conn.executemany(
                    "INSERT INTO lesson_applications (id, lesson_id, question_id, snapshot_id, kind, applied, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
    except Exception:
        logger.debug("lesson-application coverage recording failed (non-fatal)", exc_info=True)


def score_question(ledger, question_id: str, *, force: bool = False) -> ScoreRecord:
    snapshot = ledger.get_current_snapshot(question_id)
    if snapshot is None:
        raise ValidationError("cannot score a question with no forecast snapshot")
    return ledger.score_snapshot(snapshot.forecast_id, force=force)


def get_current_score(ledger, question_id: str) -> ScoreRecord | None:
    """Return the score for the current snapshot against the confirmed
    resolution, if one has already been recorded; else None. Read-only —
    does not trigger scoring."""
    snapshot = ledger.get_current_snapshot(question_id)
    if snapshot is None:
        return None
    resolution = ledger.get_latest_resolution(question_id, confirmed_only=True)
    if resolution is None:
        return None
    return ledger._existing_score(snapshot.forecast_id, resolution.id)


def score_snapshot(ledger, forecast_id: str, *, force: bool = False) -> ScoreRecord:
    snapshot = ledger.get_snapshot(forecast_id)
    question = ledger.get_question(snapshot.question_id)
    resolution = ledger.get_latest_resolution(snapshot.question_id, confirmed_only=True)
    if resolution is None:
        raise ValidationError(
            "cannot score until resolution is confirmed, criteria-satisfied, and scoreable"
        )

    if not force:
        existing = ledger._existing_score(snapshot.forecast_id, resolution.id)
        if existing is not None:
            return existing

    scoring = ledger._score_forecast_payload(
        snapshot.probability_or_distribution,
        resolution.outcome,
        question.outcome_space,
    )
    score_id = f"sc_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO score_records (
                id, question_id, forecast_id, resolution_id, scored_at,
                brier_score, log_score, proper_score, score_rule, calibration_bucket,
                forecast_horizon_days, domain, forecast_origin,
                calibration_eligible, calibration_weight, baseline_ref, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                score_id,
                snapshot.question_id,
                snapshot.forecast_id,
                resolution.id,
                utc_now_iso(),
                scoring["brier_score"],
                scoring["log_score"],
                scoring["proper_score"],
                scoring["score_rule"],
                scoring["calibration_bucket"],
                snapshot.forecast_horizon_days,
                question.domain,
                snapshot.forecast_origin,
                1 if snapshot.calibration_eligible else 0,
                snapshot.calibration_weight,
                scoring["notes"],
            ),
        )
    score = ledger.get_score(score_id)
    if score.calibration_eligible and score.forecast_origin == "live":
        ledger.update_domain_error_profile(question)
    return score


def backfill_crps_scores(ledger, *, dry_run: bool = True) -> dict[str, Any]:
    """Score (or re-score) the distribution / numeric / thesis class with CRPS.

    Walks every non-binary question, and for its current snapshot against a
    confirmed+scoreable resolution decides:

    * ``crps_scored`` — the snapshot is a representable predictive distribution;
      CRPS is computed. When ``dry_run`` is False and the existing recorded score
      is not already a CRPS rule, the old non-invalidated score row is replaced.
    * ``refused_not_representable`` — a candidate-share vote dict or a bare point
      (scored by the vector / squared-error rule, not CRPS) — never fabricated.
    * ``active_no_resolution`` — no confirmed resolution yet: cannot be scored
      (there is no outcome), so CRPS will apply automatically when it resolves.
    * ``no_snapshot`` — no current forecast to score.

    Read-only when ``dry_run`` (the default). Returns the counts + per-question
    detail rows so the caller can report exactly what would change."""
    counts = {
        "crps_scored": 0,
        "rescored": 0,
        "refused_not_representable": 0,
        "active_no_resolution": 0,
        "no_snapshot": 0,
        "errors": 0,
    }
    details: list[dict[str, Any]] = []
    for question in ledger.list_questions():
        outcome_space = question.outcome_space
        if outcome_space.type not in {"distribution", "numeric", "thesis"}:
            continue
        snapshot = ledger.get_current_snapshot(question.id)
        if snapshot is None:
            counts["no_snapshot"] += 1
            continue
        resolution = ledger.get_latest_resolution(question.id, confirmed_only=True)
        if resolution is None:
            counts["active_no_resolution"] += 1
            continue
        try:
            scoring = ledger._score_forecast_payload(
                snapshot.probability_or_distribution, resolution.outcome, outcome_space
            )
        except Exception:
            counts["errors"] += 1
            continue
        rule = scoring.get("score_rule") or ""
        if not str(rule).startswith("crps"):
            counts["refused_not_representable"] += 1
            details.append({"question_id": question.id, "rule": rule, "action": "refused"})
            continue
        counts["crps_scored"] += 1
        existing = ledger._existing_score(snapshot.forecast_id, resolution.id)
        is_rescore = existing is not None and not str(existing.score_rule or "").startswith("crps")
        if is_rescore:
            counts["rescored"] += 1
        detail = {
            "question_id": question.id,
            "forecast_id": snapshot.forecast_id,
            "rule": rule,
            "crps": scoring.get("proper_score"),
            "prior_rule": existing.score_rule if existing else None,
            "action": "would_rescore" if is_rescore else ("would_score" if existing is None else "unchanged"),
        }
        if not dry_run and (existing is None or is_rescore):
            with ledger._connect() as conn:
                conn.execute(
                    "DELETE FROM score_records WHERE forecast_id = ? AND resolution_id = ? "
                    "AND invalidated_by_correction_id IS NULL",
                    (snapshot.forecast_id, resolution.id),
                )
            rescored = ledger.score_snapshot(snapshot.forecast_id, force=False)
            detail["action"] = "rescored" if is_rescore else "scored"
            detail["score_id"] = rescored.id
        details.append(detail)
    return {"dry_run": dry_run, "counts": counts, "details": details}


def get_score(ledger, score_id: str) -> ScoreRecord:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM score_records WHERE id = ?", (score_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"score record not found: {score_id}")
    return ledger._row_to_score(row)


def list_scores(
    ledger,
    *,
    domain: str | None = None,
    forecast_origin: str | None = None,
    calibration_eligible: bool | None = None,
    horizon: str | None = None,
    bucket: str | None = None,
    include_invalidated: bool = False,
) -> list[ScoreRecord]:
    clauses: list[str] = []
    params: list[Any] = []
    if domain:
        clauses.append("domain = ?")
        params.append(domain)
    if forecast_origin:
        clauses.append("forecast_origin = ?")
        params.append(forecast_origin)
    if calibration_eligible is not None:
        clauses.append("calibration_eligible = ?")
        params.append(1 if calibration_eligible else 0)
    if bucket:
        clauses.append("calibration_bucket = ?")
        params.append(bucket)
    if not include_invalidated:
        clauses.append("invalidated_by_correction_id IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM score_records {where} ORDER BY scored_at DESC",
            params,
        ).fetchall()
    return [
        score
        for score in (ledger._row_to_score(row) for row in rows)
        if ledger._horizon_matches(score.forecast_horizon_days, horizon)
    ]


def calibration_summary(
    ledger,
    *,
    domain: str | None = None,
    forecast_origin: str | None = None,
    horizon: str | None = None,
    calibration_eligible: bool | None = True,
) -> dict[str, Any]:
    all_scores = ledger.list_scores(
        domain=domain,
        forecast_origin=forecast_origin,
        calibration_eligible=calibration_eligible,
    )
    scores = [
        score
        for score in all_scores
        if ledger._horizon_matches(score.forecast_horizon_days, horizon)
    ]
    buckets: dict[str, list[float]] = defaultdict(list)
    # Reliability-diagram accumulators, keyed by P(yes) decile (0..9). For
    # binary questions we record the forecast's P(yes) and the realized
    # outcome (1.0 yes / 0.0 no) so we can compare predicted vs observed
    # frequency and compute the Expected Calibration Error.
    curve_bins: dict[int, dict[str, list[float]]] = defaultdict(
        lambda: {"predicted": [], "observed": []}
    )
    sharpness_values: list[float] = []
    probability_movements: list[float] = []
    # Time-bucketed calibration trend points (keyed on scored_at). Each row is
    # {scored_at, brier, p_yes, outcome} — p_yes/outcome present only for binary
    # forecasts so the rolling SCE can be computed per window.
    trend_points: list[dict[str, Any]] = []
    question_type_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "brier": [],
            "log": [],
            "proper": [],
            "sharpness": [],
            "score_rules": set(),
            "score_count": 0,
        }
    )
    component_stats: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {
            "probability": [],
            "weight": [],
            "weight_share": [],
            "contribution": [],
            "distance_from_forecast": [],
        }
    )
    for score in scores:
        outcome_space = None
        try:
            outcome_space = ledger.get_question(score.question_id).outcome_space
            question_type = outcome_space.type
        except LedgerNotFoundError:
            question_type = "unknown"
        type_stats = question_type_stats[question_type]
        type_stats["score_count"] += 1
        if score.brier_score is not None:
            type_stats["brier"].append(score.brier_score)
        if score.log_score is not None:
            type_stats["log"].append(score.log_score)
        if score.proper_score is not None:
            type_stats["proper"].append(score.proper_score)
        if score.score_rule:
            type_stats["score_rules"].add(score.score_rule)
        if score.brier_score is not None:
            buckets[score.calibration_bucket or "unknown"].append(score.brier_score)
        try:
            snapshot = ledger.get_snapshot(score.forecast_id)
        except LedgerNotFoundError:
            continue
        if score.brier_score is None:
            continue
        sharpness = ledger._sharpness(snapshot.probability_or_distribution)
        if sharpness is not None:
            sharpness_values.append(sharpness)
            type_stats["sharpness"].append(sharpness)
        # Trend point (all scoreable): rolling mean-Brier keyed on scored_at.
        trend_point: dict[str, Any] = {
            "scored_at": score.scored_at,
            "brier": float(score.brier_score),
            "p_yes": None,
            "outcome": None,
        }
        # Reliability point: bin the binary forecast by P(yes) and record the
        # realized outcome so observed frequency can be compared to it.
        if (
            outcome_space is not None
            and outcome_space.type == "binary"
            and isinstance(snapshot.probability_or_distribution, (int, float))
        ):
            observed = ledger._binary_outcome_value(score, outcome_space)
            if observed is not None:
                p_yes = float(snapshot.probability_or_distribution)
                decile = min(int(p_yes * 10), 9)
                curve_bins[decile]["predicted"].append(p_yes)
                curve_bins[decile]["observed"].append(observed)
                # p_yes/outcome feed the per-window signed calibration error.
                trend_point["p_yes"] = p_yes
                trend_point["outcome"] = observed
        trend_points.append(trend_point)
        movement = ledger._score_probability_movement_before_close(score, snapshot)
        if movement is not None:
            probability_movements.append(movement)
        for component in ledger._snapshot_component_contributions(snapshot):
            stats = component_stats[component["name"]]
            stats["probability"].append(component["probability"])
            stats["weight"].append(component["weight"])
            stats["weight_share"].append(component["weight_share"])
            stats["contribution"].append(component["contribution"])
            if component["distance_from_forecast"] is not None:
                stats["distance_from_forecast"].append(component["distance_from_forecast"])
    bucket_rows = []
    canonical_buckets = [f"{i / 10:.1f}-{(i + 1) / 10:.1f}" for i in range(10)]
    ordered_buckets = canonical_buckets + sorted(
        bucket for bucket in buckets if bucket not in canonical_buckets
    )
    for bucket in ordered_buckets:
        values = buckets.get(bucket, [])
        bucket_rows.append(
            {
                "bucket": bucket,
                "count": len(values),
                "mean_brier": sum(values) / len(values) if values else None,
                "sample_status": "empty" if not values else ("low_sample" if len(values) < 5 else "ok"),
            }
        )
    all_values = [score.brier_score for score in scores if score.brier_score is not None]
    log_values = [score.log_score for score in scores if score.log_score is not None]
    component_rows = [
        {
            "name": name,
            "count": len(stats["contribution"]),
            "mean_probability": ledger._mean(stats["probability"]),
            "mean_weight": ledger._mean(stats["weight"]),
            "mean_weight_share": ledger._mean(stats["weight_share"]),
            "mean_contribution": ledger._mean(stats["contribution"]),
            "mean_abs_distance_from_forecast": ledger._mean(
                [abs(value) for value in stats["distance_from_forecast"]]
            ),
        }
        for name, stats in component_stats.items()
        if stats["contribution"]
    ]
    question_type_rows = [
        {
            "question_type": question_type,
            "count": int(stats["score_count"]),
            "brier_count": len(stats["brier"]),
            "mean_brier": ledger._mean(stats["brier"]),
            "mean_log_score": ledger._mean(stats["log"]),
            "mean_proper_score": ledger._mean(stats["proper"]),
            "mean_sharpness": ledger._mean(stats["sharpness"]),
            "score_rules": sorted(stats["score_rules"]),
        }
        for question_type, stats in question_type_stats.items()
    ]
    # Reliability curve on P(yes) + Expected/Max Calibration Error. ECE is the
    # sample-weighted mean gap between observed frequency and mean predicted
    # probability across the populated deciles; MCE is the worst single gap.
    curve_rows = []
    ece_numerator = 0.0
    ece_denominator = 0
    max_calibration_error = 0.0
    for index in range(10):
        data = curve_bins.get(index)
        predicted = data["predicted"] if data else []
        observed = data["observed"] if data else []
        count = len(observed)
        mean_predicted = sum(predicted) / count if count else None
        observed_frequency = sum(observed) / count if count else None
        gap = (
            abs(observed_frequency - mean_predicted)
            if count and mean_predicted is not None
            else None
        )
        curve_rows.append(
            {
                "bucket": f"{index / 10:.1f}-{(index + 1) / 10:.1f}",
                "count": count,
                "mean_predicted": mean_predicted,
                "observed_frequency": observed_frequency,
                "calibration_gap": gap,
                "sample_status": "empty"
                if not count
                else ("low_sample" if count < 5 else "ok"),
            }
        )
        if count and gap is not None:
            ece_numerator += count * gap
            ece_denominator += count
            max_calibration_error = max(max_calibration_error, gap)
    expected_calibration_error = (
        ece_numerator / ece_denominator if ece_denominator else None
    )
    curve_predicted = [
        value for data in curve_bins.values() for value in data["predicted"]
    ]
    curve_observed = [
        value for data in curve_bins.values() for value in data["observed"]
    ]
    return {
        "count": len(all_values),
        "mean_brier": sum(all_values) / len(all_values) if all_values else None,
        "mean_log_score": sum(log_values) / len(log_values) if log_values else None,
        "mean_sharpness": sum(sharpness_values) / len(sharpness_values) if sharpness_values else None,
        "probability_movement_count": len(probability_movements),
        "mean_probability_movement_before_close": (
            sum(probability_movements) / len(probability_movements)
            if probability_movements
            else None
        ),
        "mean_abs_probability_movement_before_close": (
            sum(abs(value) for value in probability_movements) / len(probability_movements)
            if probability_movements
            else None
        ),
        "ensemble_component_contributions": sorted(
            component_rows,
            key=lambda row: (-row["count"], -(row["mean_contribution"] or 0.0), row["name"]),
        ),
        "question_type_breakdown": sorted(
            question_type_rows,
            key=lambda row: (-row["count"], row["question_type"]),
        ),
        "buckets": bucket_rows,
        "calibration_curve": curve_rows,
        "expected_calibration_error": expected_calibration_error,
        "max_calibration_error": max_calibration_error if ece_denominator else None,
        "calibration_curve_sample_count": ece_denominator,
        "mean_predicted": (
            sum(curve_predicted) / len(curve_predicted) if curve_predicted else None
        ),
        "observed_frequency": (
            sum(curve_observed) / len(curve_observed) if curve_observed else None
        ),
        "calibration_trend": ledger._calibration_trend(trend_points),
        "domain": domain,
        "forecast_origin": forecast_origin,
        "horizon": horizon,
        "calibration_eligible": calibration_eligible,
    }


def _calibration_trend(
    ledger,
    points: list[dict[str, Any]],
    *,
    windows: tuple[int, ...] = (30, 90),
    now: str | None = None,
) -> dict[str, Any]:
    """Rolling mean-Brier + signed calibration error over recency windows.

    Each window reports ``{period, n, brier, sce}`` computed over the scored
    forecasts whose ``scored_at`` falls within the trailing window; ``sce`` is
    the signed calibration error over the window's binary forecasts (negative
    ⇒ under-confident, positive ⇒ over-confident), reusing the same estimator
    as the bias loop. ``direction`` compares the shortest to the longest
    window's mean Brier (lower Brier = better): ``improving`` when the recent
    window scores materially better, ``worsening`` when materially worse,
    ``stable`` within noise, ``insufficient`` when either window is too thin.
    Emits nothing misleading on thin data by construction."""
    from forecasting.calibration_bias import Observation, signed_calibration_error

    now_dt = timestamp_to_datetime(now or utc_now_iso())
    # Pre-parse each point's scored_at once; drop unparseable timestamps.
    parsed: list[tuple[Any, dict[str, Any]]] = []
    for point in points:
        try:
            dt = timestamp_to_datetime(point["scored_at"])
        except Exception:  # noqa: BLE001 — a garbage timestamp must not break the summary
            continue
        if dt is not None:
            parsed.append((dt, point))

    window_rows: list[dict[str, Any]] = []
    means: dict[int, float | None] = {}
    counts: dict[int, int] = {}
    for days in windows:
        cutoff = now_dt - timedelta(days=days)
        in_window = [p for dt, p in parsed if dt >= cutoff]
        briers = [p["brier"] for p in in_window if p.get("brier") is not None]
        observations = [
            Observation(p_yes=float(p["p_yes"]), outcome=float(p["outcome"]))
            for p in in_window
            if p.get("p_yes") is not None and p.get("outcome") is not None
        ]
        sce = signed_calibration_error(observations) if observations else None
        mean_brier = sum(briers) / len(briers) if briers else None
        means[days] = mean_brier
        counts[days] = len(briers)
        window_rows.append(
            {
                "period": f"{days}d",
                "n": len(briers),
                "brier": mean_brier,
                "sce": sce,
            }
        )

    # Direction: shortest vs longest window, both needing a floor sample.
    short, long = min(windows), max(windows)
    direction = "insufficient"
    if (
        short != long
        and counts.get(short, 0) >= 3
        and counts.get(long, 0) >= 3
        and means.get(short) is not None
        and means.get(long) is not None
    ):
        delta = means[short] - means[long]  # negative ⇒ recent Brier lower ⇒ better
        if delta < -0.01:
            direction = "improving"
        elif delta > 0.01:
            direction = "worsening"
        else:
            direction = "stable"
    return {"windows": window_rows, "direction": direction}


def _operator_binary_observed(
    ledger, resolved_outcome: Any, outcome_space: OutcomeSpace
) -> float | None:
    """1.0 yes / 0.0 no / None ambiguous — the realized value of a scored
    operator estimate, from the stored resolved_outcome."""

    label = str(resolved_outcome).strip().lower()
    yes_labels = {"yes", "y", "true", "1", "occurred", "success"}
    no_labels = {"no", "n", "false", "0", "not_occurred", "failed"}
    choices = [str(choice).lower() for choice in outcome_space.choices]
    if label in yes_labels or (choices and label == choices[0]):
        return 1.0
    if label in no_labels or (len(choices) > 1 and label == choices[1]):
        return 0.0
    return None


def _operator_vs_system(
    ledger, estimates: list[dict[str, Any]]
) -> dict[str, Any]:
    """Pair each question that has a scored operator estimate with the
    system's own snapshot Brier on the SAME question, and report the shared
    sample + mean Brier on each side. The operator brier for a question is
    the mean over its estimates; the system brier is its best-available
    (calibration-eligible, else latest) non-invalidated snapshot score."""

    operator_by_question: dict[str, list[float]] = defaultdict(list)
    for estimate in estimates:
        if estimate["brier"] is not None:
            operator_by_question[estimate["question_id"]].append(float(estimate["brier"]))
    operator_shared: list[float] = []
    system_shared: list[float] = []
    with ledger._connect() as conn:
        for question_id, briers in operator_by_question.items():
            row = conn.execute(
                """
                SELECT brier_score FROM score_records
                WHERE question_id = ?
                  AND brier_score IS NOT NULL
                  AND invalidated_by_correction_id IS NULL
                ORDER BY calibration_eligible DESC, scored_at DESC
                LIMIT 1
                """,
                (question_id,),
            ).fetchone()
            if row is None or row["brier_score"] is None:
                continue
            operator_shared.append(sum(briers) / len(briers))
            system_shared.append(float(row["brier_score"]))
    return {
        "shared_n": len(operator_shared),
        "operator_brier": ledger._mean(operator_shared),
        "system_brier": ledger._mean(system_shared),
    }


def operator_calibration_summary(
    ledger, window_days: int | None = None
) -> dict[str, Any]:
    """Operator calibration: n, mean Brier, a reliability curve over the
    operator's binary estimates, a recency trend, and a vs-system pairing.

    Only SCORED estimates with a numeric Brier feed the curve/trend/mean;
    ``window_days`` (when set) restricts to estimates scored within the
    trailing window."""

    estimates = [
        estimate
        for estimate in ledger.list_operator_estimates()
        if estimate["scored_at"] is not None and estimate["brier"] is not None
    ]
    if window_days:
        cutoff = timestamp_to_datetime(utc_now_iso()) - timedelta(days=window_days)
        windowed: list[dict[str, Any]] = []
        for estimate in estimates:
            try:
                scored_dt = timestamp_to_datetime(estimate["scored_at"])
            except Exception:
                continue
            if scored_dt is not None and scored_dt >= cutoff:
                windowed.append(estimate)
        estimates = windowed

    briers = [float(estimate["brier"]) for estimate in estimates]
    curve_bins: dict[int, dict[str, list[float]]] = defaultdict(
        lambda: {"predicted": [], "observed": []}
    )
    trend_points: list[dict[str, Any]] = []
    for estimate in estimates:
        payload = estimate["probability_or_distribution"]
        trend_point: dict[str, Any] = {
            "scored_at": estimate["scored_at"],
            "brier": float(estimate["brier"]),
            "p_yes": None,
            "outcome": None,
        }
        if isinstance(payload, (int, float)) and estimate["resolved_outcome"] is not None:
            try:
                outcome_space = ledger.get_question(estimate["question_id"]).outcome_space
            except LedgerNotFoundError:
                # A corpus drill (question_id is a 'fb:<case-id>' ref with no
                # forecast_questions row) — do NOT crash the whole summary
                # joining it against the desk. Fall back to a binary outcome
                # space so its yes/no resolution still maps into the
                # reliability curve, exactly like a desk drill.
                outcome_space = OutcomeSpace(type="binary", choices=["yes", "no"])
            observed = (
                ledger._operator_binary_observed(estimate["resolved_outcome"], outcome_space)
                if outcome_space is not None
                else None
            )
            if observed is not None:
                p_yes = float(payload)
                decile = min(int(p_yes * 10), 9)
                curve_bins[decile]["predicted"].append(p_yes)
                curve_bins[decile]["observed"].append(observed)
                trend_point["p_yes"] = p_yes
                trend_point["outcome"] = observed
        trend_points.append(trend_point)

    curve_rows = []
    for index in range(10):
        data = curve_bins.get(index)
        predicted = data["predicted"] if data else []
        observed = data["observed"] if data else []
        count = len(observed)
        mean_predicted = sum(predicted) / count if count else None
        observed_frequency = sum(observed) / count if count else None
        gap = (
            abs(observed_frequency - mean_predicted)
            if count and mean_predicted is not None
            else None
        )
        curve_rows.append(
            {
                "bucket": f"{index / 10:.1f}-{(index + 1) / 10:.1f}",
                "count": count,
                "mean_predicted": mean_predicted,
                "observed_frequency": observed_frequency,
                "calibration_gap": gap,
                "sample_status": "empty"
                if not count
                else ("low_sample" if count < 5 else "ok"),
            }
        )

    return {
        "n": len(briers),
        "brier": ledger._mean(briers),
        "calibration_curve": curve_rows,
        "trend": ledger._calibration_trend(trend_points),
        "vs_system": ledger._operator_vs_system(estimates),
        "window_days": window_days,
    }


def _bias_observations(
    ledger,
    *,
    domain: str | None,
    since: str | None = None,
    recency_halflife_days: float | None = None,
    forecast_origin: str | None = "live",
    now: str | None = None,
) -> list[Any]:
    """Reduce scored binary forecasts to ``calibration_bias.Observation`` rows.

    Uses the *raw* pre-adjustment probability when a lesson previously moved
    the number (contamination control), records whether a lesson was in
    context (``lesson_active`` → kept off the derivation stratum upstream),
    and attaches a recency weight when a half-life is supplied.
    """

    from datetime import datetime, timezone

    from forecasting.calibration_bias import Observation

    def _parse(ts: Any) -> "datetime | None":
        if not ts:
            return None
        raw = str(ts).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    now_dt = _parse(now) or datetime.now(timezone.utc)
    scores = ledger.list_scores(
        domain=domain,
        forecast_origin=forecast_origin,
        calibration_eligible=True,
    )
    observations: list[Any] = []
    for score in scores:
        try:
            question = ledger.get_question(score.question_id)
        except LedgerNotFoundError:
            continue
        if question.outcome_space.type != "binary":
            continue
        try:
            snapshot = ledger.get_snapshot(score.forecast_id)
        except LedgerNotFoundError:
            continue
        adjustment = snapshot.calibration_adjustment or {}
        raw = adjustment.get("raw_probability")
        committed = snapshot.probability_or_distribution
        probability = raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else committed
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            continue
        observed = ledger._binary_outcome_value(score, question.outcome_space)
        if observed is None:
            continue
        resolved_at = None
        try:
            resolved_at = ledger.get_resolution(score.resolution_id).resolved_at
        except LedgerNotFoundError:
            pass
        if since and resolved_at and str(resolved_at) < str(since):
            continue
        weight = 1.0
        if recency_halflife_days and recency_halflife_days > 0:
            resolved_dt = _parse(resolved_at)
            if resolved_dt is not None:
                age_days = (now_dt - resolved_dt).total_seconds() / 86400.0
                weight = recency_halflife_weight(age_days, recency_halflife_days)
        observations.append(
            Observation(
                p_yes=float(probability),
                outcome=float(observed),
                weight=weight,
                lesson_active=bool(snapshot.calibration_lesson_refs),
                horizon_days=score.forecast_horizon_days,
            )
        )
    return observations


def calibration_bias(
    ledger,
    *,
    domain: str | None = None,
    scope_type: str | None = None,
    since: str | None = None,
    recency_halflife_days: float | None = None,
    lesson_free_only: bool = True,
    forecast_origin: str | None = "live",
    enable_mechanical: bool = False,
    shrink_prior: float = 0.0,
    prior_scale: float | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Signed calibration-bias report for one scope (global or a domain).

    Returns the ``CalibrationBiasReport`` payload — including ``status``
    (``insufficient_evidence`` until enough effective sample accrues), the
    signed/shrunk SCE, its CI and p-value, the curve shape, and advisory
    text. Emits nothing actionable on thin or noisy data by construction.
    """

    from forecasting.calibration_bias import assess_bias

    scope = scope_type or ("domain" if domain else "global")
    observations = ledger._bias_observations(
        domain=domain,
        since=since,
        recency_halflife_days=recency_halflife_days,
        forecast_origin=forecast_origin,
        now=now,
    )
    report = assess_bias(
        observations,
        scope_type=scope,
        scope_ref=domain,
        lesson_free_only=lesson_free_only,
        enable_mechanical=enable_mechanical,
        prior_scale=prior_scale,
        shrink_prior=shrink_prior,
    )
    return report.to_payload()


def _live_score_count(ledger, domain: str | None) -> int:
    """Fast COUNT of live, calibration-eligible, non-invalidated score records
    (optionally in one domain). A cheap necessary-condition gate for the
    resolve-time bias synthesis: ESS <= count, so a count below the ESS floor
    guarantees the estimator would emit nothing — skip the O(n) scan."""
    clauses = [
        "forecast_origin = 'live'",
        "calibration_eligible = 1",
        "invalidated_by_correction_id IS NULL",
    ]
    params: list[Any] = []
    if domain:
        clauses.append("domain = ?")
        params.append(domain)
    with ledger._connect() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) FROM score_records WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
    return int(row[0]) if row else 0


def _domains_with_scores(ledger, *, forecast_origin: str | None = "live") -> list[str]:
    clauses = ["domain IS NOT NULL", "invalidated_by_correction_id IS NULL"]
    params: list[Any] = []
    if forecast_origin:
        clauses.append("forecast_origin = ?")
        params.append(forecast_origin)
    where = " AND ".join(clauses)
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT domain FROM score_records WHERE {where} ORDER BY domain",
            params,
        ).fetchall()
    return [str(row[0]) for row in rows if row[0]]


def _existing_score(ledger, forecast_id: str, resolution_id: str) -> ScoreRecord | None:
    with ledger._connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM score_records
            WHERE forecast_id = ? AND resolution_id = ?
              AND invalidated_by_correction_id IS NULL
            ORDER BY scored_at DESC
            LIMIT 1
            """,
            (forecast_id, resolution_id),
        ).fetchone()
    return ledger._row_to_score(row) if row else None


def _brier_score(
    ledger,
    probability_or_distribution: Any,
    outcome: Any,
    outcome_space: OutcomeSpace,
) -> float:
    if isinstance(probability_or_distribution, (int, float)):
        probability = float(probability_or_distribution)
        yes_labels = {"yes", "y", "true", "1", "occurred", "success"}
        outcome_label = str(outcome).strip().lower()
        observed = 1.0 if outcome_label in yes_labels or outcome_label == str(outcome_space.choices[0]).lower() else 0.0
        return (probability - observed) ** 2
    if isinstance(probability_or_distribution, dict):
        outcome_label = str(outcome).strip().lower()
        lowered = {str(key).lower(): float(value) for key, value in probability_or_distribution.items()}
        labels = {str(choice).lower() for choice in outcome_space.choices}
        labels.update(lowered.keys())
        return sum(
            (lowered.get(label, 0.0) - (1.0 if label == outcome_label else 0.0)) ** 2
            for label in labels
        )
    raise ValidationError("unsupported probability payload")


def _log_score(ledger, resolved_probability: float) -> float:
    return -math.log(max(min(resolved_probability, 1.0), 1e-15))


def _numeric_bucket(ledger, value: float, outcome_space: OutcomeSpace) -> str:
    bounds = outcome_space.bounds or []
    if len(bounds) == 2:
        low, high = float(bounds[0]), float(bounds[1])
        if math.isfinite(low) and math.isfinite(high) and high > low:
            ratio = min(max((value - low) / (high - low), 0.0), 0.999999)
            return ledger._probability_bucket(ratio)
    return "numeric"


def _vote_share_vector_score(ledger, forecast: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any] | None:
    """Vector MAE/RMSE (percentage points) for a candidate-SHARE forecast scored
    against a candidate-SHARE outcome. Forecast values may be probabilities (0-1,
    auto-scaled to pp) or already pp; outcome values are pp (0-100). Returns None
    when there are no shared numeric candidate keys, so the caller falls through
    to the existing scorer. This is an ACCURACY metric (100 - MAE), not a strictly
    proper score — labeled as such; it makes vote-share forecasts machine-scoreable
    instead of mis-read as categorical labels (lesson cl_ec9059c809ba)."""
    def _numeric_shares(raw: dict[str, Any]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, value in raw.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[str(key).strip().lower()] = float(value)
        return out

    f_shares = _numeric_shares(forecast)
    o_shares = _numeric_shares(outcome)
    shared = sorted(set(f_shares) & set(o_shares))
    if not shared:
        return None
    # Forecast in [0,1] -> scale to pp; if it already looks like pp, leave it.
    scale = 100.0 if max(f_shares[k] for k in shared) <= 1.5 else 1.0
    diffs = [abs(f_shares[k] * scale - o_shares[k]) for k in shared]
    mae = sum(diffs) / len(diffs)
    rmse = math.sqrt(sum(d * d for d in diffs) / len(diffs))
    return {
        "brier_score": None,
        "log_score": None,
        "proper_score": max(0.0, 100.0 - mae),
        "score_rule": "vector_mae_percentage_points",
        "calibration_bucket": None,
        "notes": f"Vector accuracy across {len(shared)} candidate share(s): MAE={mae:.2f}pp, RMSE={rmse:.2f}pp (accuracy, not a proper score).",
    }


def _normal_distribution_score(
    ledger,
    probability_or_distribution: dict[str, Any],
    outcome: Any,
    outcome_space: OutcomeSpace,
) -> dict[str, Any] | None:
    mean_key = next((key for key in ("mean", "expected", "value", "point") if key in probability_or_distribution), None)
    sd_key = next((key for key in ("sd", "std", "sigma", "stdev") if key in probability_or_distribution), None)
    if mean_key is None or sd_key is None:
        return None
    mean = float(probability_or_distribution[mean_key])
    sd = float(probability_or_distribution[sd_key])
    outcome_value = ledger._numeric_outcome(outcome)
    if not math.isfinite(mean) or not math.isfinite(sd) or sd <= 0:
        raise ValidationError("normal distribution scoring requires finite mean and positive standard deviation")
    variance = sd * sd
    negative_log_likelihood = 0.5 * math.log(2 * math.pi * variance) + ((outcome_value - mean) ** 2) / (2 * variance)
    mean_error, mean_rule = ledger._numeric_squared_error(mean, outcome_value, outcome_space)
    return {
        "brier_score": None,
        "log_score": negative_log_likelihood,
        "proper_score": negative_log_likelihood,
        "score_rule": "normal_negative_log_likelihood",
        "calibration_bucket": ledger._numeric_bucket(mean, outcome_space),
        "notes": f"Normal-distribution negative log likelihood; mean {mean_rule}={mean_error:.6g}.",
    }


# ── CRPS (Continuous Ranked Probability Score) ──────────────────────────────
#
# A proper score for the distribution/numeric outcome class the market can't
# cover (beating-the-market-strategy.md:586-588 — "needs CRPS, not Brier").
# We score ONLY what a snapshot actually stores and REFUSE (None, never a
# fabricated number) anything not representable as an ordered predictive
# distribution over a scalar outcome. Precedence, richest-faithful-first:
#
#   crps_discrete_cdf  — explicit CDF-threshold keys (``p_below_X`` /
#       ``bucket_le_X`` / ``cdf_X``), quantile keys (``qNN`` / ``quantile_NN`` /
#       ``percentile_NN``), or central-interval keys (``interval_W_low/high``)
#       + ``median``: build the (threshold, F) constraint points and sum the
#       squared CDF differences vs the outcome step, Σ_k (F_k − 1{y ≤ t_k})² —
#       the ordered/RPS form of CRPS the fix names, proper for ordered outcomes.
#   crps_discrete_pmf  — a genuine PMF over ordered NUMERIC bucket labels
#       (mass ≈ 1): cumulate to a CDF and score the same way.
#   crps_gaussian      — only ``mean`` + ``sd`` (finite, sd>0): the exact
#       closed-form normal CRPS.
#
# 1/√π, the CRPS of a standard normal at its own mean's tail constant.
_CRPS_INV_SQRT_PI = 1.0 / math.sqrt(math.pi)

_CRPS_MEAN_KEYS = ("mean", "expected", "value", "point")
_CRPS_SD_KEYS = ("sd", "std", "sigma", "stdev")


def _crps_num_from_suffix(raw: Any) -> float | None:
    """Parse a numeric threshold from a key suffix where the decimal point is
    written as an underscore or dash (``4_18`` → 4.18, ``3_0`` → 3.0, ``10`` →
    10.0). Returns None when nothing numeric can be recovered."""
    s = str(raw).strip().lower()
    # An underscore/dash is the decimal point in these keys (``4_18`` → 4.18).
    # Try that reading FIRST — bare ``float("3_0")`` treats the underscore as a
    # digit separator and yields 30.0, which is wrong here.
    for candidate in (s.replace("_", ".").replace("-", "."), s):
        try:
            value = float(candidate)
        except ValueError:
            continue
        if math.isfinite(value):
            return value
    return None


def _crps_cdf_points(payload: dict[str, Any]) -> list[tuple[float, float]]:
    """Collect ``(threshold, cumulative_probability)`` constraint points on the
    predictive CDF from UNAMBIGUOUS keys: explicit CDF thresholds, quantiles,
    central intervals, and the median. Bare ``pNN`` keys are deliberately NOT
    read as quantiles — they collide with count-PMF mass labels (``p0``/``p1``),
    which the PMF branch owns. Deduped by threshold; sorted ascending."""
    points: dict[float, float] = {}

    def _add(threshold: float | None, cdf: Any) -> None:
        if threshold is None or not isinstance(cdf, (int, float)) or isinstance(cdf, bool):
            return
        cdf_value = float(cdf)
        if not (math.isfinite(threshold) and math.isfinite(cdf_value)):
            return
        if 0.0 <= cdf_value <= 1.0:
            points.setdefault(float(threshold), cdf_value)

    for raw_key, raw_value in payload.items():
        if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
            continue
        key = str(raw_key).strip().lower()
        value = float(raw_value)
        # 1) Explicit CDF-threshold keys: F(X) = value (value is a probability).
        cdf_match = re.match(r"^(?:p_below|prob_below|p_lt|p_le|cdf|bucket_le|bucket_lt|le_below)[_-]?(.+)$", key)
        if cdf_match:
            _add(_crps_num_from_suffix(cdf_match.group(1)), value)
            continue
        # 2) Quantile keys (q-/quantile-/percentile-/pct-prefixed): F(value)=NN/100.
        q_match = re.match(r"^(?:q|quantile|percentile|pct)[_-]?(\d{1,3})$", key)
        if q_match:
            pct = int(q_match.group(1))
            if 1 <= pct <= 99 and math.isfinite(value):
                points.setdefault(value, pct / 100.0)
            continue
        # 3) Central-interval keys: interval_W_low → (1-W/100)/2, high → 1-that.
        iv_match = re.match(r"^(?:interval|ci|hdi|pi)[_-]?(\d{1,2})[_-]?(low|lo|l|high|hi|h)$", key)
        if iv_match:
            width = int(iv_match.group(1))
            if 0 < width < 100 and math.isfinite(value):
                frac = (1.0 - width / 100.0) / 2.0
                side_low = iv_match.group(2) in ("low", "lo", "l")
                points.setdefault(value, frac if side_low else 1.0 - frac)
            continue
        # 4) Median → F(median) = 0.5.
        if key == "median" and math.isfinite(value):
            points.setdefault(value, 0.5)
    return sorted(points.items())


def _crps_pmf_points(payload: dict[str, Any]) -> list[tuple[float, float]] | None:
    """Cumulative-CDF points from a genuine PMF over ordered NUMERIC bucket
    labels (count labels ``p0``/``p1``/``p6_plus`` or numeric strings) whose mass
    sums to ≈ 1. Returns None when the payload is not such a PMF."""
    masses: dict[float, float] = {}
    for raw_key, raw_value in payload.items():
        if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
            continue
        mass = float(raw_value)
        if not (0.0 <= mass <= 1.0) or not math.isfinite(mass):
            return None
        key = str(raw_key).strip().lower()
        count = re.match(r"^p_?(\d+)(?:_?plus|\+)?$", key)
        if count:
            value = float(count.group(1))
        else:
            value = _crps_num_from_suffix(key)
            if value is None:
                return None
        masses[value] = masses.get(value, 0.0) + mass
    total = sum(masses.values())
    if len(masses) < 2 or not (0.9 <= total <= 1.1):
        return None
    cumulative = 0.0
    points: list[tuple[float, float]] = []
    for value, mass in sorted(masses.items()):
        cumulative += mass / total
        points.append((value, min(cumulative, 1.0)))
    return points


def _crps_gaussian_params(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    """Extract (mean, sd) from the moment keys or an ``equivalent_normal_*``
    summary — the inputs to the closed-form normal CRPS + the log score."""
    def _first(keys: tuple[str, ...], prefix: str = "") -> float | None:
        for key in keys:
            value = payload.get(prefix + key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                return float(value)
        return None

    mean = _first(_CRPS_MEAN_KEYS)
    if mean is None:
        mean = _first(("mean",), prefix="equivalent_normal_")
    sd = _first(_CRPS_SD_KEYS)
    if sd is None:
        sd = _first(("sd",), prefix="equivalent_normal_")
    return mean, sd


def _crps_discrete(points: list[tuple[float, float]], outcome: float) -> float:
    """Σ_k (F_k − 1{outcome ≤ t_k})² over the (threshold, CDF) points — the
    ordered / ranked form of CRPS ("sum of squared CDF differences")."""
    return sum((cdf - (1.0 if outcome <= threshold else 0.0)) ** 2 for threshold, cdf in points)


def _crps_normal(mean: float, sd: float, outcome: float) -> float:
    """Closed-form CRPS of N(mean, sd) at ``outcome`` (Gneiting & Raftery)."""
    z = (outcome - mean) / sd
    cdf = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    return sd * (z * (2.0 * cdf - 1.0) + 2.0 * pdf - _CRPS_INV_SQRT_PI)


def _crps_score(
    ledger,
    probability_or_distribution: Any,
    outcome: Any,
    outcome_space: OutcomeSpace,
) -> dict[str, Any] | None:
    """CRPS score dict for a distributional dict payload, or None when the
    forecast is not representable as an ordered predictive distribution over a
    scalar outcome (a candidate-share dict → the vote-share vector scorer owns
    it; a bare mean → the point squared-error path owns it). None is never a
    fabricated score — the caller falls through to the existing scorers."""
    if not isinstance(probability_or_distribution, dict) or not probability_or_distribution:
        return None
    try:
        y = ledger._numeric_outcome(outcome)
    except ValidationError:
        return None  # non-scalar outcome (vote-share dict) — refuse CRPS.

    points = _crps_cdf_points(probability_or_distribution)
    rule: str | None = None
    crps: float | None = None
    if len(points) >= 2:
        crps = _crps_discrete(points, y)
        rule = "crps_discrete_cdf"
    else:
        pmf_points = _crps_pmf_points(probability_or_distribution)
        if pmf_points and len(pmf_points) >= 2:
            crps = _crps_discrete(pmf_points, y)
            rule = "crps_discrete_pmf"

    mean, sd = _crps_gaussian_params(probability_or_distribution)
    if rule is None:
        if mean is not None and sd is not None and sd > 0:
            crps = _crps_normal(mean, sd, y)
            rule = "crps_gaussian"
        else:
            return None  # no ordered distributional shape — refuse.

    # Keep the Gaussian negative log likelihood in the log_score column when the
    # snapshot carries a finite mean+sd, so the log-score surface stays populated.
    log_score: float | None = None
    if mean is not None and sd is not None and sd > 0:
        variance = sd * sd
        log_score = 0.5 * math.log(2 * math.pi * variance) + ((y - mean) ** 2) / (2 * variance)

    bucket_input = mean
    if bucket_input is None:
        median = probability_or_distribution.get("median")
        if isinstance(median, (int, float)) and not isinstance(median, bool):
            bucket_input = float(median)
    calibration_bucket = (
        ledger._numeric_bucket(bucket_input, outcome_space) if bucket_input is not None else None
    )
    return {
        "brier_score": None,
        "log_score": log_score,
        "proper_score": crps,
        "score_rule": rule,
        "calibration_bucket": calibration_bucket,
        "notes": f"CRPS ({rule}) against confirmed resolution; lower is better.",
    }


def _probability_bucket(ledger, probability: float) -> str:
    lower = min(int(probability * 10), 9) / 10
    upper = lower + 0.1
    return f"{lower:.1f}-{upper:.1f}"


def _score_summary(ledger, scores: list[ScoreRecord]) -> dict[str, Any]:
    return {
        "count": len(scores),
        "mean_brier": ledger._mean([score.brier_score for score in scores]),
        "mean_log_score": ledger._mean([score.log_score for score in scores]),
    }


def _score_breakdown(
    ledger,
    scores: list[ScoreRecord],
    key_fn,
) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[ScoreRecord]] = defaultdict(list)
    for score in scores:
        buckets[str(key_fn(score))].append(score)
    return {key: ledger._score_summary(bucket_scores) for key, bucket_scores in sorted(buckets.items())}


def _score_horizon_bucket(ledger, score: ScoreRecord) -> str:
    horizon = score.forecast_horizon_days
    if horizon is None:
        return "unknown"
    if horizon <= 7:
        return "0-7d"
    if horizon <= 30:
        return "8-30d"
    if horizon <= 90:
        return "31-90d"
    if horizon <= 365:
        return "91-365d"
    return "365d+"


def _paired_brier_summary(
    ledger,
    pairs: list[tuple[ScoreRecord, ScoreRecord]],
) -> dict[str, Any]:
    deltas: list[float] = []
    agent_scores: list[float] = []
    baseline_scores: list[float] = []
    agent_wins = baseline_wins = ties = 0
    for agent, baseline in pairs:
        if agent.brier_score is None or baseline.brier_score is None:
            continue
        agent_brier = float(agent.brier_score)
        baseline_brier = float(baseline.brier_score)
        agent_scores.append(agent_brier)
        baseline_scores.append(baseline_brier)
        deltas.append(baseline_brier - agent_brier)
        if agent_brier < baseline_brier:
            agent_wins += 1
        elif agent_brier > baseline_brier:
            baseline_wins += 1
        else:
            ties += 1

    count = len(deltas)
    # Point estimate is UNCHANGED from the prior parametric implementation:
    # the mean paired Brier edge. Only the significance statistics around it
    # (CI + p-value) move from the normal approximation to a seeded bootstrap.
    mean_delta = ledger._mean(deltas)
    bootstrap = ledger._paired_bootstrap(deltas, mean_delta)
    return {
        "paired_brier_count": count,
        "paired_agent_mean_brier": ledger._mean(agent_scores),
        "paired_baseline_mean_brier": ledger._mean(baseline_scores),
        "paired_agent_edge_mean_brier": mean_delta,
        "paired_agent_edge_ci95_low": bootstrap["ci_low"],
        "paired_agent_edge_ci95_high": bootstrap["ci_high"],
        "paired_p_value": bootstrap["p_value"],
        "paired_bootstrap_draws": PAIRED_BOOTSTRAP_DRAWS,
        "paired_brier_coin_flip_floor": _core.BRIER_COIN_FLIP_FLOOR,
        "paired_agent_wins": agent_wins,
        "paired_baseline_wins": baseline_wins,
        "paired_ties": ties,
    }


def _paired_bootstrap(
    ledger,
    deltas: list[float],
    mean_delta: float | None,
) -> dict[str, float | None]:
    """Seeded paired bootstrap over per-question Brier deltas.

    deltas[i] = baseline_brier_i - agent_brier_i (POSITIVE = agent better).

    - Two-sided p-value tests H0: no paired difference. We recenter the deltas
      at zero (d0 = x - mean_delta), draw PAIRED_BOOTSTRAP_DRAWS resample-means
      of d0, and report the fraction whose magnitude is >= |mean_delta|.
    - The 95% CI is the 2.5/97.5 percentiles of the UNCENTERED resample-means.
    - n < 2, no mean, or a degenerate all-equal-deltas spread -> p=None, ci=None.

    Deterministic: a single seeded random.Random(PAIRED_BOOTSTRAP_SEED) drives
    every draw, so identical inputs always yield identical p-value and CI.
    """

    none_result: dict[str, float | None] = {"p_value": None, "ci_low": None, "ci_high": None}
    count = len(deltas)
    if count < 2 or mean_delta is None:
        return none_result
    # Degenerate: every paired delta identical. The recentered series is all
    # zeros, so every bootstrap mean is exactly 0. If the edge itself is 0 the
    # data carry no signal at all (p undefined); if the edge is non-zero but
    # variance-free, the bootstrap cannot characterize it either.
    spread = max(deltas) - min(deltas)
    if spread == 0.0:
        return none_result

    observed = abs(mean_delta)
    d0 = [x - mean_delta for x in deltas]
    rng = random.Random(PAIRED_BOOTSTRAP_SEED)
    ge_count = 0
    uncentered_means: list[float] = []
    for _ in range(PAIRED_BOOTSTRAP_DRAWS):
        # One shared index draw per iteration keeps the recentered (p-value)
        # and uncentered (CI) resamples on the same deterministic stream.
        idx = [rng.randrange(count) for _ in range(count)]
        boot_centered = statistics.fmean(d0[i] for i in idx)
        if abs(boot_centered) >= observed:
            ge_count += 1
        uncentered_means.append(statistics.fmean(deltas[i] for i in idx))

    # Add-one (plus-one) correction so a Monte-Carlo p-value is never exactly
    # 0.0 — the true tail is bounded below by ~1/B, not 0.
    p_value = (ge_count + 1) / (PAIRED_BOOTSTRAP_DRAWS + 1)
    uncentered_means.sort()
    return {
        "p_value": p_value,
        "ci_low": ledger._percentile(uncentered_means, 2.5),
        "ci_high": ledger._percentile(uncentered_means, 97.5),
    }


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolated percentile over an ascending list (pct in 0..100)."""

    if not sorted_values:
        raise ValueError("percentile of empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[low]
    frac = rank - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac


def _score_probability_movement_before_close(
    ledger,
    score: ScoreRecord,
    scored_snapshot: ForecastSnapshot,
) -> float | None:
    """Return final-minus-initial probability movement for the scored forecast path."""

    try:
        question = ledger.get_question(score.question_id)
    except LedgerNotFoundError:
        return None
    scored_as_of = timestamp_to_datetime(scored_snapshot.as_of)
    close_time = timestamp_to_datetime(question.close_time) if question.close_time else None
    cutoff = close_time or scored_as_of
    numeric_snapshots: list[ForecastSnapshot] = []
    for snapshot in ledger.list_snapshots(score.question_id):
        if snapshot.forecast_origin != scored_snapshot.forecast_origin:
            continue
        if snapshot.backtest_run_id != scored_snapshot.backtest_run_id:
            continue
        snapshot_as_of = timestamp_to_datetime(snapshot.as_of)
        if cutoff and snapshot_as_of and snapshot_as_of > cutoff:
            continue
        if scored_as_of and snapshot_as_of and snapshot_as_of > scored_as_of:
            continue
        if ledger._numeric_probability(snapshot.probability_or_distribution) is None:
            continue
        numeric_snapshots.append(snapshot)
    if len(numeric_snapshots) < 2:
        return None
    first = ledger._numeric_probability(numeric_snapshots[0].probability_or_distribution)
    last = ledger._numeric_probability(numeric_snapshots[-1].probability_or_distribution)
    if first is None or last is None:
        return None
    return last - first


def _snapshot_component_contributions(ledger, snapshot: ForecastSnapshot) -> list[dict[str, Any]]:
    forecast_probability = ledger._numeric_probability(snapshot.probability_or_distribution)
    rows = ledger._ensemble_component_rows(snapshot.ensemble_components)
    total_weight = sum(row["weight"] for row in rows)
    if total_weight <= 0:
        return []
    contributions: list[dict[str, Any]] = []
    for row in rows:
        weight_share = row["weight"] / total_weight
        contribution = row["probability"] * weight_share
        distance = (
            row["probability"] - forecast_probability
            if forecast_probability is not None
            else None
        )
        contributions.append(
            {
                "name": row["name"],
                "probability": row["probability"],
                "weight": row["weight"],
                "weight_share": weight_share,
                "contribution": contribution,
                "distance_from_forecast": distance,
            }
        )
    return contributions


def _row_to_score(ledger, row: sqlite3.Row) -> ScoreRecord:
    return ScoreRecord(
        id=row["id"],
        question_id=row["question_id"],
        forecast_id=row["forecast_id"],
        resolution_id=row["resolution_id"],
        scored_at=row["scored_at"],
        brier_score=row["brier_score"],
        log_score=row["log_score"],
        proper_score=row["proper_score"],
        score_rule=row["score_rule"],
        calibration_bucket=row["calibration_bucket"],
        forecast_horizon_days=row["forecast_horizon_days"],
        domain=row["domain"],
        forecast_origin=row["forecast_origin"],
        calibration_eligible=bool(row["calibration_eligible"]),
        calibration_weight=row["calibration_weight"],
        baseline_ref=row["baseline_ref"],
        invalidated_by_correction_id=row["invalidated_by_correction_id"],
        notes=row["notes"],
    )


def _score_to_dict(ledger, score: ScoreRecord) -> dict[str, Any]:
    return score.__dict__.copy()
