#!/usr/bin/env python3
"""Exercise the durable source-event pipeline against an operator-selected ledger."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from forecasting.ledger import ForecastLedger, allow_ledger_writes


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def run_canary(db_path: Path) -> dict[str, object]:
    base = datetime.now(timezone.utc).replace(microsecond=0)
    with tempfile.TemporaryDirectory(prefix="forecast-workflow-canary-") as temp_dir:
        source = Path(temp_dir) / "source.txt"
        source.write_text("before", encoding="utf-8")
        with allow_ledger_writes("source workflow live canary"):
            ledger = ForecastLedger(db_path)
            question = ledger.create_question(
                title=f"Source workflow recovery canary {_iso(base)}",
                resolution_criteria=(
                    "Canary only: archive after retry, expired-lease recovery, and "
                    "immaterial reconciliation are persisted."
                ),
                resolution_source="local canary fixture",
                domain="operations_canary",
                impact="critical",
                metadata={"operations_canary": True, "calibration_eligible": False},
            )
            baseline = ledger.create_snapshot(
                question_id=question.id,
                probability_or_distribution=0.5,
                rationale="Neutral canary baseline; excluded from calibration.",
                forecast_origin="exploratory",
                calibration_eligible=False,
                calibration_weight=0.0,
            )
            ledger.enable_autopilot(
                question_id=question.id,
                sources=[str(source)],
                cadence="1d",
                mode="propose",
                materiality_policy={
                    "min_source_changes": 1,
                    "min_probability_delta": 0.03,
                },
            )
            source.write_text("after", encoding="utf-8")
            autopilot = ledger.run_autopilot(question.id, now=_iso(base))
            if autopilot["run"]["status"] != "needs_estimation":
                raise RuntimeError("canary did not enter needs_estimation")
            event = ledger.list_source_change_events(question_id=question.id)[0]

            failed = ledger.run_estimator_tasks(
                owner="canary-invalid-estimator",
                estimator=lambda _payload: {
                    "proposed_probability_or_distribution": 0.5,
                    "rationale": "Deliberately incomplete retry canary.",
                    "estimation_artifact": {},
                },
                now=_iso(base + timedelta(seconds=1)),
                limit=1,
            )[0]
            if failed["task"]["status"] != "pending":
                raise RuntimeError("malformed estimate did not become retryable")
            task_id = failed["task"]["id"]

            crashed = ledger.claim_operational_tasks(
                owner="canary-crashed-worker",
                lane="normal_reforecast",
                task_type="process_source_change",
                now=_iso(base + timedelta(seconds=62)),
                lease_seconds=1,
                limit=1,
            )
            if not crashed or crashed[0]["id"] != task_id:
                raise RuntimeError("canary task could not be claimed for crash simulation")

            def unchanged_estimate(_payload):
                return {
                    "proposed_probability_or_distribution": 0.5,
                    "rationale": "The captured change was reviewed and is immaterial.",
                    "model_version": "deterministic-canary-v1",
                    "usage": {
                        "model_calls": 0,
                        "source_calls": 0,
                        "cost_usd": 0.0,
                        "cost_status": "measured",
                        "cost_source": "deterministic_canary",
                    },
                    "estimation_artifact": {
                        "prior_probability": 0.5,
                        "evidence_updates": [
                            {
                                "event_id": event["id"],
                                "likelihood_ratio": 1.0,
                                "correlation_cluster": "operations-canary",
                                "reliability_weight": 1.0,
                            }
                        ],
                        "raw_posterior": 0.5,
                        "ensemble_components": {"canary_review": 0.5},
                        "panel_result": {"status": "not_required"},
                        "proposed_probability": 0.5,
                        "materiality": "none",
                        "evidence_cutoff": _iso(base),
                        "change_my_mind": ["A material source value change."],
                        "guardrail_results": {},
                    },
                }

            recovered = ledger.run_estimator_tasks(
                owner="canary-recovery-worker",
                estimator=unchanged_estimate,
                now=_iso(base + timedelta(seconds=64)),
                limit=1,
            )[0]
            if recovered["task"]["id"] != task_id:
                raise RuntimeError("recovery worker claimed the wrong task")
            if recovered["task"]["disposition"] != "reviewed_immaterial":
                raise RuntimeError("unchanged estimate did not reconcile as immaterial")
            if recovered["event"]["state"] != "reconciled":
                raise RuntimeError("source event did not reconcile")
            if recovered.get("proposal") is not None:
                raise RuntimeError("immaterial canary created a proposal")

            with ledger._connect() as conn:
                attempts = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT owner, claimed_at, finished_at, outcome, error "
                        "FROM operational_task_attempts WHERE task_id = ? "
                        "ORDER BY claimed_at, rowid",
                        (task_id,),
                    ).fetchall()
                ]
            if [row["outcome"] for row in attempts] != [
                "failed_retrying",
                "lease_expired",
                "reviewed_immaterial",
            ]:
                raise RuntimeError("canary attempt history is incomplete")
            ledger.set_question_service_mode(question.id, "archived")

    return {
        "ok": True,
        "question_id": question.id,
        "baseline_forecast_id": baseline.forecast_id,
        "source_change_event_id": event["id"],
        "operational_task_id": task_id,
        "final_event_state": recovered["event"]["state"],
        "final_disposition": recovered["task"]["disposition"],
        "proposal_created": False,
        "attempts": attempts,
        "question_status": ledger.get_question(question.id).status,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_canary(args.db.expanduser().resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
