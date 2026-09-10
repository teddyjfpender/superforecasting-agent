"""Exact, read-only market-study observations shared by CLI and analysis scripts."""

from __future__ import annotations

import json
import math


def market_evaluation_records(conn):
    """Bind the original agent snapshot to its frozen baseline and resolution.

    Never infer an outcome from a score (ambiguous at p=.5), or substitute a
    later forecast. Unresolved/unverified pairs remain visible with a reason.
    """
    records = []
    for row in conn.execute("""
        SELECT f.forecast_id, f.question_id, q.title, f.as_of, f.created_at AS forecast_recorded_at,
               f.evidence_cutoff,
               f.probability_or_distribution AS agent_p, f.metadata AS forecast_metadata,
               b.id AS baseline_id, b.forecast_id AS baseline_forecast_id, b.as_of AS baseline_as_of,
               b.probability_or_distribution AS market_p, b.metadata AS baseline_metadata,
               b.source, b.score_record_id AS market_score_id,
               r.id AS resolution_id, r.resolved_at, r.outcome, q.outcome_space,
               s.id AS score_id, s.brier_score AS agent_brier,
               ms.brier_score AS market_brier, ms.resolution_id AS market_resolution_id,
               ms.question_id AS market_question_id, ms.forecast_id AS market_forecast_id,
               ms.invalidated_by_correction_id AS market_invalidated,
               ms.audit_quarantine_reason AS market_quarantine
        FROM forecast_snapshots f JOIN forecast_questions q ON q.id = f.question_id
        LEFT JOIN baseline_comparisons b ON b.id = (
            SELECT id FROM baseline_comparisons WHERE question_id = f.question_id
              AND baseline_type = 'market_price'
              AND (json_extract(metadata, '$.agent_forecast_id') = f.forecast_id
                   OR (json_extract(metadata, '$.agent_forecast_id') IS NULL
                       AND (SELECT count(*) FROM baseline_comparisons bc
                            WHERE bc.question_id = f.question_id AND bc.baseline_type = 'market_price') = 1))
            ORDER BY as_of, id LIMIT 1)
        LEFT JOIN resolutions r ON r.id = (
            SELECT id FROM resolutions WHERE question_id = q.id
              AND resolution_status = 'confirmed' AND criteria_satisfied = 1
              AND scoreable = 1 ORDER BY resolved_at DESC, rowid DESC LIMIT 1)
        LEFT JOIN score_records s ON s.id = (
            SELECT id FROM score_records WHERE forecast_id = f.forecast_id
              AND question_id = q.id AND resolution_id = r.id
              AND invalidated_by_correction_id IS NULL AND audit_quarantine_reason IS NULL
            ORDER BY scored_at DESC, id DESC LIMIT 1)
        LEFT JOIN score_records ms ON ms.id = b.score_record_id
        WHERE f.forecast_origin = 'market_nightly'
        ORDER BY f.as_of, f.forecast_id
    """):
        r = dict(row)
        r["qid"] = r.pop("question_id")
        reason = None
        for key in ("agent_p", "market_p"):
            try:
                value = json.loads(r[key])
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("not a probability")
                r[key] = float(value)
            except (ValueError, TypeError):
                r[key] = None
                reason = "missing_or_invalid_probability"
        raw_outcome = json.loads(r["outcome"]) if r["outcome"] is not None else None
        choices = json.loads(r.pop("outcome_space")).get("choices") or ["yes", "no"]
        label = str(raw_outcome).strip().lower()
        outcome = (float(raw_outcome) if isinstance(raw_outcome, (int, float)) and raw_outcome in (0, 1) else
                   1.0 if label in {"yes", "true", "1", str(choices[0]).lower()} else
                   0.0 if label in {"no", "false", "0", str(choices[-1]).lower()} else None)
        r["agent_valid"] = bool(
            r["score_id"] and outcome is not None and r["agent_p"] is not None
            and r["agent_brier"] is not None and math.isfinite(r["agent_brier"])
            and math.isclose(r["agent_brier"], (r["agent_p"] - outcome) ** 2, abs_tol=1e-8)
        )
        if reason is None:
            if outcome is None:
                reason = "unresolved_or_invalid_outcome"
            elif (not r["score_id"] or not r["market_score_id"]
                  or r["market_resolution_id"] != r["resolution_id"]
                  or r["market_question_id"] != r["qid"]
                  or r["market_forecast_id"] != r["baseline_forecast_id"]
                  or r["market_invalidated"] or r["market_quarantine"]):
                reason = "missing_or_mismatched_score_pair"
            elif any(r[k] is None or not math.isfinite(r[k]) or
                     not math.isclose(r[k], (r[p] - outcome) ** 2, abs_tol=1e-8)
                     for k, p in (("agent_brier", "agent_p"), ("market_brier", "market_p"))):
                reason = "score_payload_mismatch"
        r["outcome"] = outcome if reason is None else None
        r["exclusion_reason"] = reason
        for key in ("forecast_metadata", "baseline_metadata"):
            r[key] = json.loads(r[key] or "{}")
        from forecasting.market_nightly import baseline_is_contemporaneous

        r["contemporaneous"] = baseline_is_contemporaneous(
            metadata=r["baseline_metadata"], forecast_as_of=r["as_of"],
            market_id_str=r["forecast_metadata"].get("market_id"), source=r["source"] or "",
        )
        records.append(r)
    return records
