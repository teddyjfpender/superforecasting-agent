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
    json_loads,
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
        item = next((i for i in adjustment.get("applied_active_lessons", [])
                     if isinstance(i, dict) and i.get("id") == lesson["id"]), {})
        if item.get("numeric_adjustment_skipped") == "more_specific_calibration_bias_applied":
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
        snapshot = ledger.get_snapshot(snapshot_id) if snapshot_id else None
        decisions = (snapshot.metadata or {}).get("lesson_decisions", []) if snapshot else []
        # Legacy/direct calls without a recorded verdict are unverified, never
        # inferred successful from the existence of the snapshot.
        by_id = {row["lesson_id"]: row for row in decisions}
        now = utc_now_iso()
        rows = []
        for lesson in active:
            decision = by_id.get(lesson["id"], {})
            recommended = lesson.get("recommended_adjustment") or {}
            kind = decision.get("kind") or (
                "rule" if isinstance(recommended.get("rule"), dict) else
                "numeric" if any(k in recommended for k in ("probability_delta", "logit_shift", "logit_scale")) else "advisory"
            )
            rows.append((f"la_{uuid.uuid4().hex[:12]}", lesson["id"], question.id, snapshot_id,
                         kind, int(bool(decision.get("applied"))), now))
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
    with ledger.transaction(immediate=True):
        snapshot = ledger.get_snapshot(forecast_id)
        question = ledger.get_question(snapshot.question_id)
        resolution = ledger.get_latest_resolution(snapshot.question_id, confirmed_only=True)
        if resolution is None:
            raise ValidationError(
                "cannot score until resolution is confirmed, criteria-satisfied, and scoreable"
            )

        existing = ledger._existing_score(snapshot.forecast_id, resolution.id)
        if existing is not None:
            if not force:
                return existing
            ledger.create_correction(
                target_type="score_record", target_id=existing.id, status="applied",
                reason="Explicit score recomputation; retain prior score and invalidate derived learning.",
            )

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
                    1 if snapshot.calibration_eligible and question.outcome_space.censoring is None else 0,
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
      is not already the current rule version, the old score is retained and invalidated.
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
        is_rescore = existing is not None and existing.score_rule != rule
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
            if existing is not None:
                correction = ledger.create_correction(
                    target_type="score_record", target_id=existing.id,
                    reason=f"Recompute proper score: {existing.score_rule} -> {rule}; retain old score and invalidate derived lessons.",
                    status="applied",
                )
                detail["correction_id"] = correction["id"]
            rescored = ledger.score_snapshot(snapshot.forecast_id, force=False)
            detail["action"] = "rescored" if is_rescore else "scored"
            detail["score_id"] = rescored.id
            if is_rescore:
                postmortem = ledger.create_postmortem(question_id=question.id,
                    summary=f"Score recomputed with {rule}; prior score and derived learning invalidated by correction.")
                detail["postmortem_id"] = postmortem["id"]
        details.append(detail)
    return {"dry_run": dry_run, "counts": counts, "details": details}


# ── Cohort scoreboard + scores audit (measurement honesty) ──────────────────
#
# A pooled all-artifact Brier is a category error: it sums the market-VISIBLE
# baselines (backtest / imported_baseline / market_nightly — calibration-
# ineligible by construction) with the tiny live calibration-eligible stratum,
# and it silently drops the continuous (CRPS / log) class a Brier cannot even
# represent. So the DEFAULT everywhere a score aggregate surfaces is BY COHORT:
# each stratum reports its own mean, the continuous class gets a SEPARATE
# scorecard, and the pooled number survives ONLY as an explicitly-labelled
# ledger-wide DIAGNOSTIC ("all-artifact Brier — not a skill claim").

# The origins that carry a BINARY Brier, in surfacing order. ``live`` is split
# out into its calibration-eligible subset below; the rest are baselines.
_BASELINE_COHORT_ORIGINS = ("backtest", "imported_baseline", "market_nightly")

# Pathological thresholds — a degenerate Brier or a log score at/over the clamp
# territory. |log|>10 catches both the binary clamp floor (~34.54 = −ln(1e-15))
# and a fat-tailed Gaussian NLL; the classifier below separates the two.
_PATHOLOGICAL_BRIER = 0.9999
_PATHOLOGICAL_ABS_LOG = 10.0


def _is_continuous_rule(rule: Any) -> bool:
    """True for the ordered/numeric proper-score rules (CRPS families + the
    Gaussian NLL) — the class a Brier cannot represent, scored separately."""
    text = str(rule or "")
    return text.startswith("crps") or text == "normal_negative_log_likelihood"


# BLF A6 — difficulty adjustment (ABI-style). 62% of ForecastBench score variance
# is question DIFFICULTY (their mixed-effects finding). The cohort split fixed the
# *composition* lie; this fixes the *hardness* lie so a desk that takes hard
# questions is not punished against one that farms easy ones.
#
# The honest, single difficulty proxy per binary question is the recorded
# market/crowd anchor's OWN Brier against the outcome:
#
#     difficulty d = (p_market - y)^2      y in {0, 1}
#
# which folds together BOTH base uncertainty (a crowd priced at 0.5 → d≈0.25, a
# genuine coin-flip) and resolution surprise (a crowd confidently WRONG → d≈0.81).
# This is exactly the reference forecaster's error that ForecastBench-style
# difficulty adjustment controls for. Provenance is honest per row:
#
#   * ``forecastbench_published`` — the anchor is the ForecastBench freeze crowd
#     price we INGESTED (its published difficulty signal; FB rows carry domain
#     ``forecastbench`` / metadata ``source_dataset`` ``forecastbench:*``);
#   * ``market_anchor_derived``  — a market baseline we recorded on a non-FB
#     question (same formula, our own crowd/market dispersion).
#
# The adjustment re-centres each cohort's raw Brier by the difficulty of its OWN
# question mix against a shared reference D̄ (the pooled mean difficulty over every
# difficulty-eligible row):
#
#     adjusted = mean_brier(eligible) - mean_difficulty(eligible) + D̄
#             = D̄ + mean(brier_i - d_i)        (excess-over-crowd, re-scaled)
#
# so a desk that beats a hard crowd lands BELOW D̄ and a desk that merely matches
# an easy crowd lands AT D̄ — hard and easy question mixes are placed on one scale.
# The LIMIT is explicit: a row with NO recorded market/crowd anchor has NO
# derivable difficulty — it is EXCLUDED from the adjustment and shown in raw Brier
# only, flagged. We NEVER fabricate a difficulty for an anchorless row.
_DIFFICULTY_ADJUSTMENT_METHOD = (
    "difficulty d = (market/crowd anchor - outcome)^2 per binary question; "
    "adjusted mean Brier = raw - mean_difficulty + reference_difficulty. "
    "FB rows use the published ForecastBench freeze crowd price; non-FB rows use a "
    "recorded market anchor. Rows with no recorded anchor are shown unadjusted, flagged."
)
_DIFFICULTY_ADJUSTMENT_LIMITS = (
    "The adjusted column is meaningful only RELATIVE to the shared reference "
    "difficulty (surfaced here); it requires a recorded market/crowd anchor and a "
    "clean binary outcome. Anchorless rows are never given a fabricated adjustment."
)


# The canonical market/crowd baseline vocabulary used across the codebase
# (market_ensemble, market_nightly.MARKET_BASELINE_TYPE, jobs/quorum): FB ingests
# its freeze crowd price as ``market``; the live-edge / market_nightly harness
# records its venue price as ``market_price``; imported market snapshots use
# ``imported_market``. All three are genuine 0..1 YES probabilities.
_MARKET_ANCHOR_BASELINE_TYPES = ("market", "market_price", "imported_market")


def _market_anchors(conn) -> dict[str, float]:
    """Map ``question_id -> recorded market/crowd probability`` — the difficulty
    signal. Reads the ``baseline_comparisons`` market rows (FB ingests the freeze
    crowd price here; live/nightly questions record their venue price). Keeps a
    single 0..1 scalar per question (latest by ``as_of`` when several exist);
    non-scalar / out-of-range payloads are skipped (difficulty is binary-only)."""
    placeholders = ",".join("?" for _ in _MARKET_ANCHOR_BASELINE_TYPES)
    anchors: dict[str, float] = {}
    for row in conn.execute(
        f"""
        SELECT question_id, probability_or_distribution
        FROM baseline_comparisons
        WHERE baseline_type IN ({placeholders})
        ORDER BY as_of ASC
        """,
        _MARKET_ANCHOR_BASELINE_TYPES,
    ).fetchall():
        payload = json_loads(row["probability_or_distribution"], None)
        if isinstance(payload, (int, float)) and not isinstance(payload, bool):
            value = float(payload)
            if 0.0 <= value <= 1.0:
                anchors[row["question_id"]] = value  # last (latest as_of) wins
    return anchors


def _difficulty_provenance(row: dict[str, Any]) -> str:
    """``forecastbench_published`` when the anchor is an ingested ForecastBench
    freeze crowd price, else ``market_anchor_derived``."""
    if str(row["domain"] or "") == "forecastbench":
        return "forecastbench_published"
    meta = json_loads(row.get("question_metadata"), {}) or {}
    if str(meta.get("source_dataset") or "").startswith("forecastbench"):
        return "forecastbench_published"
    return "market_anchor_derived"


def _annotate_difficulty(ledger, rows: list[dict[str, Any]], anchors: dict[str, float]) -> None:
    """Attach ``_difficulty`` + ``_difficulty_provenance`` to each clean binary
    row that HAS a market anchor and a clean binary outcome; ``None`` otherwise.
    Never fabricated — an anchorless / ambiguous row keeps ``_difficulty = None``."""
    for row in rows:
        row["_difficulty"] = None
        row["_difficulty_provenance"] = None
        if row["brier_score"] is None:
            continue
        anchor = anchors.get(row["question_id"])
        if anchor is None:
            continue
        outcome_space = OutcomeSpace.from_json(row.get("outcome_space"))
        raw_outcome = row.get("resolution_outcome")
        outcome = json_loads(raw_outcome, raw_outcome)  # resolutions.outcome is JSON-encoded
        observed = _operator_binary_observed(ledger, outcome, outcome_space)
        if observed is None:  # fractional / ambiguous outcome → not a clean binary
            continue
        row["_difficulty"] = (anchor - observed) ** 2
        row["_difficulty_provenance"] = _difficulty_provenance(row)


def _cohort_bucket(rows: list[dict[str, Any]], reference_difficulty: float | None) -> dict[str, Any]:
    """Summarize one binary cohort: n, brier count, mean Brier (None on empty —
    never a fabricated 0), the domains it spans, and the difficulty-adjusted mean
    Brier (None when the cohort has no difficulty-eligible row)."""
    briers = [float(r["brier_score"]) for r in rows if r["brier_score"] is not None]
    domains = sorted({r["domain"] for r in rows if r["domain"]})
    bucket = {
        "n": len(rows),
        "n_brier": len(briers),
        "mean_brier": (sum(briers) / len(briers)) if briers else None,
        "domains": domains,
    }
    bucket.update(_difficulty_adjust(rows, reference_difficulty))
    return bucket


def _difficulty_adjust(rows: list[dict[str, Any]], reference_difficulty: float | None) -> dict[str, Any]:
    """The difficulty-adjusted fields for one cohort. Adjusts ONLY the rows that
    carry a derivable difficulty (a recorded anchor + clean binary outcome); rows
    without one are counted in ``n_unadjusted`` and flagged, never adjusted."""
    n_brier = sum(1 for r in rows if r["brier_score"] is not None)
    eligible = [
        (float(r["brier_score"]), float(r["_difficulty"]))
        for r in rows
        if r["brier_score"] is not None and r.get("_difficulty") is not None
    ]
    n_difficulty = len(eligible)
    if n_difficulty == 0 or reference_difficulty is None:
        return {
            "n_difficulty": 0,
            "n_unadjusted": n_brier,
            "mean_difficulty": None,
            "mean_brier_difficulty_adjusted": None,
            "difficulty_note": (
                "no market/crowd anchor recorded — shown unadjusted (never a fabricated adjustment)"
                if n_brier
                else None
            ),
        }
    mean_brier_eligible = sum(b for b, _ in eligible) / n_difficulty
    mean_difficulty = sum(d for _, d in eligible) / n_difficulty
    n_unadjusted = n_brier - n_difficulty
    return {
        "n_difficulty": n_difficulty,
        "n_unadjusted": n_unadjusted,
        "mean_difficulty": mean_difficulty,
        "mean_brier_difficulty_adjusted": mean_brier_eligible - mean_difficulty + reference_difficulty,
        "difficulty_note": (
            f"{n_unadjusted} row(s) had no market/crowd anchor — excluded from the "
            "adjustment, shown in raw Brier only"
            if n_unadjusted
            else None
        ),
    }


def cohort_scoreboard(ledger) -> dict[str, Any]:
    """Score aggregates SEPARATED BY COHORT — the honest default surface.

    Returns:

    * ``cohorts`` — one binary-Brier bucket per stratum:
      ``live_calibration_eligible`` (the ONLY skill-claim stratum: live +
      calibration_eligible), and the market-visible baselines ``backtest`` /
      ``imported_baseline`` / ``market_nightly``. Each: n, n_brier, mean_brier
      (None on empty), domains.
    * ``continuous_scorecard`` — the CRPS / log class, scored SEPARATELY (a
      Brier cannot represent it): n, mean_crps, mean_log_score, a per-rule
      breakdown, the live calibration-eligible subset, and domains.
    * ``pooled_diagnostic`` — the pooled all-artifact Brier, retained ONLY as an
      explicitly-labelled ledger-wide diagnostic ("not a skill claim").
    * ``quarantined`` — count + per-reason of the audit-quarantined rows that
      every cohort above EXCLUDES.

    A ``difficulty_adjustment`` block (BLF A6 / ABI) and a per-cohort
    ``mean_brier_difficulty_adjusted`` column re-centre each cohort's raw Brier by
    the difficulty of its own question mix (the recorded market/crowd anchor's
    Brier against the outcome), so a hard-question desk is not punished against an
    easy-farmer. Rows with no recorded anchor are shown unadjusted, flagged.

    Read-only. Quarantined rows (``audit_quarantine_reason`` set) are excluded
    from every cohort and from the pooled diagnostic, and reported apart."""
    with ledger._connect() as conn:
        # Join the resolution outcome + question outcome_space/metadata so the
        # difficulty proxy (market-anchor Brier vs the outcome) can be computed.
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT s.question_id AS question_id, s.forecast_origin,
                       s.calibration_eligible, s.brier_score, s.proper_score,
                       s.log_score, s.score_rule, s.domain, s.audit_quarantine_reason,
                       r.outcome AS resolution_outcome,
                       q.outcome_space AS outcome_space,
                       q.metadata AS question_metadata
                FROM score_records s
                JOIN resolutions r ON r.id = s.resolution_id
                JOIN forecast_questions q ON q.id = s.question_id
                WHERE s.invalidated_by_correction_id IS NULL
                """
            ).fetchall()
        ]
        anchors = _market_anchors(conn)

    quarantined = [r for r in rows if r["audit_quarantine_reason"]]
    clean = [r for r in rows if not r["audit_quarantine_reason"]]

    # Difficulty per clean binary row (market anchor + clean binary outcome), and
    # the shared reference difficulty D̄ = pooled mean over every eligible row.
    _annotate_difficulty(ledger, clean, anchors)
    all_difficulties = [r["_difficulty"] for r in clean if r.get("_difficulty") is not None]
    reference_difficulty = (
        (sum(all_difficulties) / len(all_difficulties)) if all_difficulties else None
    )

    # Binary cohorts. A row belongs to a binary cohort when it carries a Brier;
    # the continuous class (CRPS / NLL) never does, so the two never overlap.
    live_eligible = [
        r for r in clean
        if r["forecast_origin"] == "live" and r["calibration_eligible"] and r["brier_score"] is not None
    ]
    cohorts: dict[str, Any] = {
        "live_calibration_eligible": _cohort_bucket(live_eligible, reference_difficulty)
    }
    for origin in _BASELINE_COHORT_ORIGINS:
        cohorts[origin] = _cohort_bucket(
            [r for r in clean if r["forecast_origin"] == origin and r["brier_score"] is not None],
            reference_difficulty,
        )

    # Continuous scorecard — CRPS / log, kept apart from every Brier.
    continuous = [
        r for r in clean if _is_continuous_rule(r["score_rule"]) and r["proper_score"] is not None
    ]
    crps_values = [float(r["proper_score"]) for r in continuous]
    log_values = [float(r["log_score"]) for r in continuous if r["log_score"] is not None]
    by_rule: dict[str, dict[str, Any]] = {}
    for r in continuous:
        rule = str(r["score_rule"])
        bucket = by_rule.setdefault(rule, {"n": 0, "_crps": []})
        bucket["n"] += 1
        bucket["_crps"].append(float(r["proper_score"]))
    continuous_scorecard = {
        "n": len(continuous),
        "mean_crps": (sum(crps_values) / len(crps_values)) if crps_values else None,
        "mean_log_score": (sum(log_values) / len(log_values)) if log_values else None,
        "live_calibration_eligible_n": sum(
            1 for r in continuous if r["forecast_origin"] == "live" and r["calibration_eligible"]
        ),
        "domains": sorted({r["domain"] for r in continuous if r["domain"]}),
        "by_rule": {
            rule: {"n": bucket["n"], "mean_crps": sum(bucket["_crps"]) / len(bucket["_crps"])}
            for rule, bucket in sorted(by_rule.items())
        },
    }

    # Pooled diagnostic — explicitly NOT a skill claim.
    pooled_briers = [float(r["brier_score"]) for r in clean if r["brier_score"] is not None]
    pooled_diagnostic = {
        "label": "all-artifact Brier — pooled ledger-wide diagnostic, NOT a skill claim",
        "n": len(pooled_briers),
        "mean_brier": (sum(pooled_briers) / len(pooled_briers)) if pooled_briers else None,
    }

    reason_counts: dict[str, int] = {}
    for r in quarantined:
        reason = str(r["audit_quarantine_reason"])
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    provenance: dict[str, int] = {}
    for r in clean:
        prov = r.get("_difficulty_provenance")
        if prov is not None:
            provenance[prov] = provenance.get(prov, 0) + 1
    n_no_anchor = sum(
        1 for r in clean if r["brier_score"] is not None and r.get("_difficulty") is None
    )
    difficulty_adjustment = {
        "method": _DIFFICULTY_ADJUSTMENT_METHOD,
        "reference_difficulty": reference_difficulty,
        "n_eligible": len(all_difficulties),
        "n_no_anchor": n_no_anchor,
        "provenance": provenance,
        "limits": _DIFFICULTY_ADJUSTMENT_LIMITS,
    }

    return {
        "cohorts": cohorts,
        "continuous_scorecard": continuous_scorecard,
        "pooled_diagnostic": pooled_diagnostic,
        "difficulty_adjustment": difficulty_adjustment,
        "quarantined": {"n": len(quarantined), "reasons": reason_counts},
    }


def _classify_pathological(row: dict[str, Any]) -> str:
    """Reason-classify one pathological score row.

    * ``real_continuous_miss`` — a CRPS / NLL row whose large |log| is the
      fat-tailed Gaussian negative-log-likelihood at a genuine outcome, NOT an
      artifact (its proper score is the CRPS, honestly large).
    * ``artifact_degenerate_import`` — an imported baseline whose forecast is a
      DEGENERATE binary probability (0.0 / 1.0) that resolved against it: the
      synthetic target-price ingestion pattern. Provably not a real forecast.
    * ``real_binary_miss`` — a genuine binary forecast that was confidently
      wrong. A real miss, kept and scored.
    * ``unclassified`` — pathological but none of the above; left for review."""
    if _is_continuous_rule(row["score_rule"]):
        return "real_continuous_miss"
    prob = row.get("_probability")
    is_degenerate = isinstance(prob, (int, float)) and not isinstance(prob, bool) and (
        prob <= 1e-9 or prob >= 1.0 - 1e-9
    )
    if row["forecast_origin"] == "imported_baseline" and is_degenerate:
        return "artifact_degenerate_import"
    if isinstance(prob, (int, float)) and not isinstance(prob, bool):
        return "real_binary_miss"
    return "unclassified"


def scores_audit(ledger) -> dict[str, Any]:
    """READ-ONLY audit of PATHOLOGICAL score rows (Brier ≥ 1.0 or |log| > 10),
    each classified by reason so an ingestion artifact is never confused with a
    real catastrophic miss.

    Returns ``{counts, rows, proposed_quarantine}``: ``rows`` carries every
    pathological row with its ``reason`` + whether it is ``already_quarantined``;
    ``proposed_quarantine`` is the subset provably an artifact
    (``artifact_degenerate_import``) not yet quarantined — the gated
    :func:`quarantine_artifact_scores` acts ONLY on these, and only when the
    operator confirms (dry-run first)."""
    with ledger._connect() as conn:
        raw = conn.execute(
            """
            SELECT s.id, s.question_id, s.forecast_origin, s.brier_score,
                   s.log_score, s.proper_score, s.score_rule, s.domain,
                   s.audit_quarantine_reason,
                   fs.probability_or_distribution AS payload,
                   q.title AS title
            FROM score_records s
            JOIN forecast_snapshots fs ON fs.forecast_id = s.forecast_id
            JOIN forecast_questions q ON q.id = s.question_id
            WHERE s.invalidated_by_correction_id IS NULL
              AND (s.brier_score >= ? OR ABS(s.log_score) > ?)
            ORDER BY s.forecast_origin, s.id
            """,
            (_PATHOLOGICAL_BRIER, _PATHOLOGICAL_ABS_LOG),
        ).fetchall()

    from forecasting.models import json_loads

    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    proposed: list[dict[str, Any]] = []
    for r in raw:
        row = dict(r)
        payload = json_loads(row.pop("payload"), None)
        row["_probability"] = payload if isinstance(payload, (int, float)) else None
        reason = _classify_pathological(row)
        already = bool(row["audit_quarantine_reason"])
        entry = {
            "score_id": row["id"],
            "question_id": row["question_id"],
            "forecast_origin": row["forecast_origin"],
            "brier_score": row["brier_score"],
            "log_score": row["log_score"],
            "score_rule": row["score_rule"],
            "title": (row["title"] or "")[:80],
            "reason": reason,
            "already_quarantined": already,
        }
        rows.append(entry)
        counts[reason] = counts.get(reason, 0) + 1
        if reason == "artifact_degenerate_import" and not already:
            proposed.append(entry)
    return {"counts": counts, "rows": rows, "proposed_quarantine": proposed}


def quarantine_artifact_scores(
    ledger,
    *,
    dry_run: bool = True,
    reasons: tuple[str, ...] = ("artifact_degenerate_import",),
) -> dict[str, Any]:
    """Gated quarantine of provable ingestion artifacts surfaced by
    :func:`scores_audit`.

    Read-only when ``dry_run`` (the default): returns the proposal + the cohort
    impact so the operator can confirm before anything is written. When
    ``dry_run`` is False, each targeted row is marked
    ``audit_quarantine_reason=<reason>`` and forced ``calibration_eligible=0`` —
    excluding it from every cohort aggregate. Idempotent: rows already
    quarantined are skipped, so a re-apply reports ``count=0``."""
    audit = scores_audit(ledger)
    targets = [
        row for row in audit["rows"]
        if row["reason"] in reasons and not row["already_quarantined"]
    ]
    target_ids = {row["score_id"] for row in targets}

    def _baseline_means(exclude: set[str]) -> dict[str, float | None]:
        with ledger._connect() as conn:
            out: dict[str, float | None] = {}
            for origin in _BASELINE_COHORT_ORIGINS:
                vals = [
                    float(r[0])
                    for r in conn.execute(
                        "SELECT brier_score, id FROM score_records "
                        "WHERE forecast_origin = ? AND brier_score IS NOT NULL "
                        "AND invalidated_by_correction_id IS NULL "
                        "AND audit_quarantine_reason IS NULL",
                        (origin,),
                    ).fetchall()
                    if r[1] not in exclude
                ]
                out[origin] = (sum(vals) / len(vals)) if vals else None
            return out

    before = _baseline_means(set())
    projected = _baseline_means(target_ids)  # before any write — the honest "would-be".

    if not dry_run and targets:
        with ledger._connect() as conn:
            conn.executemany(
                "UPDATE score_records SET audit_quarantine_reason = ?, "
                "calibration_eligible = 0 WHERE id = ?",
                [(row["reason"], row["score_id"]) for row in targets],
            )

    return {
        "dry_run": dry_run,
        "count": len(targets),
        "proposed": targets,
        "cohort_impact": {
            origin: {
                "mean_brier_before": before[origin],
                "mean_brier_after": projected[origin],
            }
            for origin in _BASELINE_COHORT_ORIGINS
        },
    }


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
    # One independent outcome per question, using its latest scored forecast.
    # Repeated updates must not manufacture effective sample size.
    observations: dict[str, tuple[tuple[Any, ...], Any]] = {}
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
        rank = (snapshot.as_of, snapshot.created_at, snapshot.forecast_id, score.scored_at, score.id)
        if score.question_id in observations and observations[score.question_id][0] >= rank:
            continue
        observations[score.question_id] = (
            rank, Observation(
                p_yes=float(probability),
                outcome=float(observed),
                weight=weight,
                lesson_active=bool(snapshot.calibration_lesson_refs),
                horizon_days=score.forecast_horizon_days,
                score_record_id=score.id,
            )
        )
    return [observation for _, observation in observations.values()]


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


# ── Hierarchical Platt calibration — cohort-tagged resolved rows (BLF A4) ────
# The scoreboard STRATA (cohort_scoreboard) become the calibration cohorts: the
# per-cohort intercept offset delta_s wants exactly the base-rate skew those
# strata expose. This reader is the READ-ONLY glue between the ledger and the
# pure fit in ``forecasting.hierarchical_calibration``.

# The scoreboard strata that carry a per-cohort intercept. ``live`` is only a
# skill-claim stratum when calibration-eligible, matching cohort_scoreboard.
_HIER_BASELINE_ORIGINS = ("backtest", "imported_baseline", "market_nightly")


def _cohort_venue(question: Any) -> str | None:
    """Best-effort market venue for a question (``metadata.market_source`` or the
    ``<venue>:<id>`` prefix of ``metadata.market_id``); ``None`` when unknown."""

    meta = getattr(question, "metadata", None)
    if not isinstance(meta, dict):
        return None
    src = meta.get("market_source")
    if isinstance(src, str) and src.strip():
        return src.strip().lower()
    market_id = meta.get("market_id")
    if isinstance(market_id, str) and ":" in market_id:
        prefix = market_id.split(":", 1)[0].strip().lower()
        if prefix:
            return prefix
    return None


def _cohort_key(score: ScoreRecord, question: Any, *, split_by_venue: bool) -> str | None:
    """Scoreboard-stratum cohort key for a resolved row (``None`` ⇒ excluded)."""

    origin = score.forecast_origin
    if origin == "live":
        if not score.calibration_eligible:
            return None
        base = "live_calibration_eligible"
    elif origin in _HIER_BASELINE_ORIGINS:
        base = origin
    else:
        return None
    if split_by_venue:
        venue = _cohort_venue(question)
        if venue:
            return f"{base}:{venue}"
    return base


def hierarchical_calibration_rows(
    ledger,
    *,
    since: str | None = None,
    recency_halflife_days: float | None = None,
    split_by_venue: bool = False,
    now: str | None = None,
) -> list[Any]:
    """Reduce resolved binary forecasts to cohort-tagged calibration rows.

    Returns :class:`forecasting.hierarchical_calibration.CohortObservation` rows —
    one per resolved binary forecast across the scoreboard strata (live +
    calibration-eligible, backtest, imported_baseline, market_nightly), each
    carrying the *raw* pre-adjustment P(yes) (contamination control, mirroring
    :func:`_bias_observations`), its {0,1} outcome, the cohort key, and an optional
    recency weight. ``split_by_venue`` refines a stratum to ``<origin>:<venue>``
    where the question exposes a market venue (finer splits where the data exists).
    READ-ONLY — pulls scores/snapshots/resolutions, mutates nothing."""

    from datetime import datetime, timezone

    from forecasting.hierarchical_calibration import CohortObservation

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
    scores = ledger.list_scores(calibration_eligible=None)
    rows: list[Any] = []
    for score in scores:
        if score.brier_score is None:
            continue
        try:
            question = ledger.get_question(score.question_id)
        except LedgerNotFoundError:
            continue
        if question.outcome_space.type != "binary":
            continue
        cohort = _cohort_key(score, question, split_by_venue=split_by_venue)
        if cohort is None:
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
        rows.append(
            CohortObservation(
                raw_p=float(probability),
                outcome=float(observed),
                cohort=cohort,
                weight=weight,
            )
        )
    return rows


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


def _validated_shares(raw):
    """Reject ambiguous or non-finite vector values, never silently drop them."""
    if not isinstance(raw, dict) or not raw:
        raise ValidationError("share vector must be a nonempty object")
    values = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ValidationError("share labels must be nonempty strings")
        label = key.strip().lower()
        if label in values:
            raise ValidationError("share labels must be unique ignoring case and whitespace")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValidationError("share values must be finite nonnegative numbers, not strings or booleans")
        values[label] = float(value)
    return values


def _vote_share_vector_score(ledger, forecast: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any] | None:
    """Vector MAE/RMSE (percentage points) for a candidate-SHARE forecast scored
    against a candidate-SHARE outcome. Forecast values may be probabilities (0-1,
    auto-scaled to pp) or already pp; outcome values are pp (0-100). Requires matching, complete, finite numeric candidate vectors. This is an ACCURACY metric (100 - MAE), not a strictly
    proper score — labeled as such; it makes vote-share forecasts machine-scoreable
    instead of mis-read as categorical labels (lesson cl_ec9059c809ba)."""
    f_shares = _validated_shares(forecast)
    o_shares = _validated_shares(outcome)
    if set(f_shares) != set(o_shares):
        raise ValidationError("forecast and resolved share labels must match exactly; partial-vector scoring is not allowed")
    shared = sorted(f_shares)
    if any(value > 100 for value in o_shares.values()):
        raise ValidationError("resolved shares must be percentages between 0 and 100")
    # Infer the legacy forecast representation from its total, not its largest
    # candidate (many tiny percentage shares must never be multiplied by 100).
    total = sum(f_shares.values())
    if math.isclose(total, 1.0, abs_tol=0.005):
        scale = 100.0
    elif math.isclose(total, 100.0, abs_tol=0.5):
        scale = 1.0
    else:
        raise ValidationError("forecast shares must sum to 1 (fractions) or 100 (percentages)")
    if not math.isclose(sum(o_shares.values()), 100.0, abs_tol=0.5):
        raise ValidationError("resolved percentage shares must sum to 100 (within 0.5 rounding tolerance)")
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
#   crps_piecewise_linear_cdf_v2 — explicit CDF-threshold keys (``p_below_X`` /
#       ``bucket_le_X`` / ``cdf_X``), quantile keys (``qNN`` / ``quantile_NN`` /
#       ``percentile_NN``), or central-interval keys (``interval_W_low/high``)
#       + ``median``: integrate squared CDF error over outcome distance, with
#       linear interpolation and remaining tail mass at endpoint thresholds.
#   crps_discrete_pmf_v2 — a genuine PMF over ordered NUMERIC bucket labels
#       (mass ≈ 1): integrate its step CDF exactly.
#   crps_gaussian      — only ``mean`` + ``sd`` (finite, sd>0): the exact
#       closed-form normal CRPS.
#
# 1/√π, the CRPS of a standard normal at its own mean's tail constant.
_CRPS_INV_SQRT_PI = 1.0 / math.sqrt(math.pi)

_CRPS_MEAN_KEYS = ("mean", "expected", "value", "point")
_CRPS_SD_KEYS = ("sd", "std", "sigma", "stdev", "standard_deviation")


def _crps_num_from_suffix(raw: Any) -> float | None:
    """Parse a numeric threshold from a key suffix where the decimal point is
    written as an underscore or dash (``4_18`` → 4.18, ``3_0`` → 3.0, ``10`` →
    10.0). Returns None when nothing numeric can be recovered."""
    s = str(raw).strip().lower()
    # An underscore/dash is the decimal point in these keys (``4_18`` → 4.18).
    # Try that reading FIRST — bare ``float("3_0")`` treats the underscore as a
    # digit separator and yields 30.0, which is wrong here.
    sign = "-" if s.startswith("-") else ""
    magnitude = s[1:] if sign else s
    for candidate in (sign + magnitude.replace("_", ".").replace("-", "."), s):
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
    """Exact integral CRPS for a finite-support PMF (CDF constant between atoms).

    Gneiting and Raftery (2007), equation 20, loss orientation. Distances carry
    the outcome's units; an unweighted sum over arbitrary thresholds is not CRPS.
    """
    return _crps_integral(points, outcome, linear=False)


def _crps_integral(points, outcome, *, linear):
    if not points or any(not math.isfinite(x) or not 0 <= f <= 1 for x, f in points):
        raise ValidationError("CRPS requires finite ordered CDF points")
    if any(x1 >= x2 or f1 > f2 for (x1, f1), (x2, f2) in zip(points, points[1:])):
        raise ValidationError("CRPS requires a monotone CDF")
    # Complete sparse CDFs on finite support: missing lower/upper probability
    # mass sits at the extreme supplied thresholds. This interpolation convention
    # is explicit in the rule version; it is not an inferred Gaussian tail.
    score = max(points[0][0] - outcome, 0.0) + max(outcome - points[-1][0], 0.0)
    for (left, fleft), (right, fright) in zip(points, points[1:]):
        cuts = [left] + ([outcome] if left < outcome < right else []) + [right]
        for a, b in zip(cuts, cuts[1:]):
            observed = float(a >= outcome)
            fa = fleft + (fright-fleft)*(a-left)/(right-left) if linear else fleft
            fb = fleft + (fright-fleft)*(b-left)/(right-left) if linear else fleft
            u, v = fa-observed, fb-observed
            score += (b-a)*(u*u+u*v+v*v)/3.0
    return score


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
        crps = _crps_integral(points, y, linear=True)
        rule = "crps_piecewise_linear_cdf_v2"
    else:
        pmf_points = _crps_pmf_points(probability_or_distribution)
        if pmf_points and len(pmf_points) >= 2:
            crps = _crps_discrete(pmf_points, y)
            rule = "crps_discrete_pmf_v2"

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
        "notes": f"CRPS ({rule}) against confirmed resolution; lower is better. " + (
            "Sparse CDF: linear interpolation with remaining tail mass at endpoint thresholds."
            if rule == "crps_piecewise_linear_cdf_v2" else ""
        ),
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
    inv_count = 1.0 / count
    for _ in range(PAIRED_BOOTSTRAP_DRAWS):
        # One shared index stream per iteration keeps the recentered (p-value)
        # and uncentered (CI) resamples deterministic. Avoid materializing the
        # sampled indexes; readiness runs many benchmark reports under a 30s cap.
        boot_centered = sum(d0[rng.randrange(count)] for _ in range(count)) * inv_count
        if abs(boot_centered) >= observed:
            ge_count += 1
        uncentered_means.append(boot_centered + mean_delta)

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
        audit_quarantine_reason=row["audit_quarantine_reason"],
    )


def _score_to_dict(ledger, score: ScoreRecord) -> dict[str, Any]:
    return score.__dict__.copy()


def _score_forecast_payload(ledger, probability_or_distribution, outcome, outcome_space):
    from forecasting.censoring import is_censored, score
    if is_censored(outcome) or outcome_space.censoring is not None:
        return score(probability_or_distribution, outcome, outcome_space)
    if outcome_space.type in {"binary", "categorical"}:
        probability = ledger._probability_for_outcome(
            probability_or_distribution,
            outcome,
            outcome_space,
        )
        brier = ledger._brier_score(
            probability_or_distribution,
            outcome,
            outcome_space,
        )
        log_score = ledger._log_score(probability)
        return {
            "brier_score": brier,
            "log_score": log_score,
            "proper_score": brier,
            "score_rule": "brier",
            "calibration_bucket": ledger._probability_bucket(probability),
            "notes": "Brier score against confirmed resolution.",
        }

    if outcome_space.type == "numeric":
        # A dict payload with real distributional shape (quantiles / CDF
        # thresholds / mean+sd) is scored with CRPS — a proper score for the
        # whole predictive distribution, not just its mean point.
        if isinstance(probability_or_distribution, dict):
            crps = ledger._crps_score(probability_or_distribution, outcome, outcome_space)
            if crps is not None:
                return crps
        forecast_value = ledger._numeric_forecast_point(probability_or_distribution)
        outcome_value = ledger._numeric_outcome(outcome)
        score, rule = ledger._numeric_squared_error(forecast_value, outcome_value, outcome_space)
        return {
            "brier_score": None,
            "log_score": None,
            "proper_score": score,
            "score_rule": rule,
            "calibration_bucket": ledger._numeric_bucket(forecast_value, outcome_space),
            "notes": f"{rule} against confirmed numeric resolution.",
        }

    if outcome_space.type in {"distribution", "thesis"}:
        if isinstance(probability_or_distribution, (int, float)):
            forecast_value = ledger._numeric_forecast_point(probability_or_distribution)
            outcome_value = ledger._numeric_outcome(outcome)
            score, rule = ledger._numeric_squared_error(forecast_value, outcome_value, outcome_space)
            return {
                "brier_score": None,
                "log_score": None,
                "proper_score": score,
                "score_rule": rule,
                "calibration_bucket": ledger._numeric_bucket(forecast_value, outcome_space),
                "notes": f"{rule} for distributional point summary against confirmed resolution.",
            }
        if isinstance(probability_or_distribution, dict):
            # CRPS is the proper score for a continuous predictive
            # distribution; it REFUSES (None) a candidate-share vote dict,
            # which falls through to the vote-share vector scorer below.
            crps = ledger._crps_score(probability_or_distribution, outcome, outcome_space)
            if crps is not None:
                return crps
            normal = ledger._normal_distribution_score(probability_or_distribution, outcome, outcome_space)
            if normal is not None:
                return normal
            # Vote-share pattern: a candidate-SHARE dict forecast scored against a
            # candidate-SHARE dict outcome (e.g. {"Lasher": .39, ...} vs certified
            # {"Lasher": 39.2, ...}). The fallthrough below treats the dict OUTCOME
            # as a categorical label, which mis-scores / fails — the bug behind the
            # hand-rolled manual scores. Score it as a vector MAE/RMSE in
            # percentage points so vote-share forecasts are machine-scoreable
            # (lesson cl_ec9059c809ba). None -> no shared candidates -> fall through.
            if isinstance(outcome, dict):
                vector = ledger._vote_share_vector_score(probability_or_distribution, outcome)
                if vector is not None:
                    return vector
            probability = ledger._probability_for_outcome(
                probability_or_distribution,
                outcome,
                outcome_space,
            )
            brier = ledger._brier_score(
                probability_or_distribution,
                outcome,
                outcome_space,
            )
            log_score = ledger._log_score(probability)
            return {
                "brier_score": brier,
                "log_score": log_score,
                "proper_score": log_score,
                "score_rule": "discrete_distribution_log_score",
                "calibration_bucket": ledger._probability_bucket(probability),
                "notes": "Discrete distribution log score against confirmed resolution.",
            }

    raise ValidationError(f"scoring is not implemented for outcome type: {outcome_space.type}")
