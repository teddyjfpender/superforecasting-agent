"""Explicit, idempotent promotion of one unconditional baseline through ledger gates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast

from forecasting.interviews.evaluation import assert_matched, validate_estimate
from forecasting.interviews.store import InterviewStore
from forecasting.jobs.store import JobStore
from forecasting.models import ValidationError, utc_now_iso
from protocol.scenarios import ScenarioReport

if TYPE_CHECKING:
    from forecasting.ledger import ForecastLedger


def _candidate(
    ledger: ForecastLedger, job_id: str, repetition: int
) -> tuple[dict, dict]:
    if type(repetition) is not int or repetition < 0:
        raise ValidationError("select an unconditional baseline repetition")
    job = JobStore().read(job_id)
    if job.type != "forecast_scenarios" or job.status != "done" or job.cancel_requested:
        raise ValidationError("only completed scenario evaluations can be promoted")
    if job.spec.get("db") != str(ledger.db_path.resolve()):
        raise ValidationError("scenario evaluation belongs to another ledger")
    report = ScenarioReport.model_validate(job.result)
    plan = job.annotations.get("scenario_plan") or {}
    if (plan.get("interview_id"), plan.get("revision"), plan.get("input_digest")) != (
        report.interview_id,
        report.revision,
        report.input_digest,
    ):
        raise ValidationError("evaluation report does not match its frozen inputs")
    raw_results = [item.model_dump() for item in report.results]
    if raw_results != job.annotations.get("scenario_results"):
        raise ValidationError(
            "evaluation results do not match the durable call records"
        )
    assert_matched(raw_results)
    for item in report.results:
        validate_estimate(item.estimate, plan)
    record = InterviewStore(ledger).read(report.interview_id)
    if (
        record["digest"] != report.input_digest
        or record["document"]["status"] == "cancelled"
    ):
        raise ValidationError(
            "interview changed; evaluate its current revision before promotion"
        )
    question_id = record["document"]["question_id"]
    if question_id is None:
        with ledger._connect() as conn:
            receipt = conn.execute(
                "SELECT question_id, revision FROM forecast_interview_commits WHERE interview_id = ?",
                (report.interview_id,),
            ).fetchone()
        if receipt is None or receipt["revision"] != report.revision:
            raise ValidationError(
                "create the reviewed question before promoting its forecast"
            )
        question_id = receipt["question_id"]
    question = ledger.get_question(question_id)
    if question.status != "active":
        raise ValidationError("only active questions can receive a forecast")
    if question.current_forecast_id != record["document"]["baseline_forecast_id"]:
        raise ValidationError("active forecast changed; start a new update interview")
    contract = plan["contract"]
    current = asdict(question)
    keys = ("resolution_criteria", "resolution_source", "close_time", "outcome_space")
    if any(current.get(key) != contract.get(key) for key in keys):
        raise ValidationError("resolution contract changed; evaluate a new interview")
    if (
        "resolution_time" in contract
        and current["resolution_time"] != contract["resolution_time"]
    ):
        raise ValidationError("resolution period changed; evaluate a new interview")
    matches = [
        item
        for item in report.results
        if item.kind == "baseline"
        and item.variant_id == "baseline"
        and item.repetition == repetition
    ]
    if len(matches) != 1:
        raise ValidationError("select one completed unconditional baseline repetition")
    selected = matches[0]
    estimate = selected.estimate
    if estimate.outcome_type == "binary":
        payload = estimate.probability
    elif estimate.outcome_type == "categorical":
        payload = estimate.categories
    else:
        payload = {
            "q10": estimate.q10,
            "q50": estimate.q50,
            "q90": estimate.q90,
            "median": estimate.q50,
        }
    args = {
        "question_id": question_id,
        "probability_or_distribution": payload,
        "rationale": estimate.rationale,
        "as_of": selected.created_at,
        "method": "interview_unconditional_baseline",
        "key_assumptions": [item.statement for item in report.assumptions],
        "evidence_refs": estimate.evidence_refs,
        "agent_model": selected.response_model,
        "prompt_version": "scenario-evaluation-v1",
        "forecast_origin": "live",
        "require_citations": True,
        "metadata": {
            "interview_evaluation": {
                "job_id": job_id,
                "interview_id": report.interview_id,
                "revision": report.revision,
                "input_digest": report.input_digest,
                "baseline_forecast_id": record["document"]["baseline_forecast_id"],
                "selected_result": selected.model_dump(),
                "assumptions": [item.model_dump() for item in report.assumptions],
                "selection": "explicit_user_selection_of_unconditional_baseline",
            }
        },
    }
    return args, {
        "job_id": job_id,
        "repetition": repetition,
        "question_id": question_id,
    }


def preview_promotion(ledger: ForecastLedger, job_id: str, repetition: int = 0) -> dict:
    with ledger._connect() as conn:
        receipt = conn.execute(
            "SELECT * FROM forecast_interview_promotions WHERE job_id = ?", (job_id,)
        ).fetchone()
    if receipt:
        snapshot = ledger.get_snapshot(receipt["forecast_id"])
        return {
            "job_id": job_id,
            "repetition": receipt["repetition"],
            "question_id": receipt["question_id"],
            "candidate": snapshot.probability_or_distribution,
            "would_commit": False,
            "blockers": [],
            "preview_digest": receipt["preview_digest"],
            "promoted_forecast_id": snapshot.forecast_id,
        }
    args, identity = _candidate(ledger, job_id, repetition)
    result = ledger.create_snapshot(**args, preview=True)
    if not isinstance(result, dict):
        raise ValidationError("ledger preview returned an unexpected snapshot")
    checked = cast(dict[str, Any], result)
    candidate = checked.get(
        "probability_or_distribution", args["probability_or_distribution"]
    )
    blockers = checked.get("blockers", [])
    body = {
        **identity,
        "candidate": candidate,
        "would_commit": bool(checked["would_commit"]),
        "promoted_forecast_id": None,
        "blockers": blockers,
    }
    body["preview_digest"] = hashlib.sha256(
        json.dumps(
            {"args": args, "preview": body}, sort_keys=True, allow_nan=False
        ).encode()
    ).hexdigest()
    return body


def promote(
    ledger: ForecastLedger, job_id: str, repetition: int, preview_digest: str
) -> dict:
    from forecasting.ledger import allow_ledger_writes

    with ledger.transaction(immediate=True) as conn:
        receipt = conn.execute(
            "SELECT * FROM forecast_interview_promotions WHERE job_id = ?", (job_id,)
        ).fetchone()
        if receipt:
            if (
                receipt["repetition"] != repetition
                or receipt["preview_digest"] != preview_digest
            ):
                raise ValidationError(
                    "this evaluation already promoted a different reviewed candidate"
                )
            return {
                "question_id": receipt["question_id"],
                "forecast_id": receipt["forecast_id"],
            }
        preview = preview_promotion(ledger, job_id, repetition)
        if preview["preview_digest"] != preview_digest:
            raise ValidationError("promotion preview changed; review it again")
        if not preview["would_commit"]:
            raise ValidationError(
                "promotion blocked: " + "; ".join(preview["blockers"])
            )
        args, _ = _candidate(ledger, job_id, repetition)
        with allow_ledger_writes(reason="explicit interview baseline promotion"):
            snapshot = ledger.create_snapshot(**args)
            if isinstance(snapshot, dict):
                raise ValidationError("ledger commit returned an unexpected preview")
        conn.execute(
            "INSERT INTO forecast_interview_promotions VALUES (?, ?, ?, ?, ?, ?)",
            (
                job_id,
                repetition,
                preview_digest,
                snapshot.question_id,
                snapshot.forecast_id,
                utc_now_iso(),
            ),
        )
        return {
            "question_id": snapshot.question_id,
            "forecast_id": snapshot.forecast_id,
        }
