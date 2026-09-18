"""Idempotent scenario starts and interview-scoped status for interactive clients."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from forecasting.interviews.evaluation import prepare
from forecasting.interviews.store import InterviewStore
from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore
from forecasting.jobs.types.scenario import ScenarioJobSpec
from forecasting.models import ValidationError
from protocol.scenarios import ScenarioEvaluationOptions, ScenarioReport

if TYPE_CHECKING:
    from forecasting.ledger import ForecastLedger


def enqueue_evaluation(
    ledger: ForecastLedger,
    interview_id: str,
    revision: int,
    request_id: str,
    options: ScenarioEvaluationOptions,
) -> str:
    if not request_id.strip() or len(request_id) > 200:
        raise ValidationError(
            "scenario request identifier is required (at most 200 characters)"
        )
    spec = ScenarioJobSpec(
        interview_id=interview_id,
        revision=revision,
        options=options,
        db=str(ledger.db_path.resolve()),
        request_id=request_id,
    ).model_dump()
    encoded = json.dumps(spec, sort_keys=True, allow_nan=False)
    jobs = JobStore()
    with ledger.transaction(immediate=True) as conn:
        prior = conn.execute(
            "SELECT spec, job_id FROM forecast_interview_evaluation_requests WHERE interview_id = ? AND request_id = ?",
            (interview_id, request_id),
        ).fetchone()
        if prior:
            if prior["spec"] != encoded:
                raise ValidationError(
                    "scenario request identifier reused with different settings"
                )
            return str(prior["job_id"])
        previous_job = conn.execute(
            "SELECT job_id FROM forecast_interview_evaluation_requests WHERE interview_id = ? ORDER BY rowid DESC LIMIT 1",
            (interview_id,),
        ).fetchone()
        if previous_job:
            try:
                existing = jobs.read(previous_job["job_id"])
            except FileNotFoundError as exc:
                raise ValidationError(
                    "saved scenario job is missing; inspect the profile before starting another call"
                ) from exc
            if existing.status not in {"done", "error", "cancelled"}:
                raise ValidationError(
                    "a scenario evaluation is already active for this interview"
                )
        if InterviewStore(ledger).read(interview_id)["revision"] != revision:
            raise ValidationError("interview changed; reload before evaluating")
        # Validate and freeze before acknowledging any start. The worker checks
        # the committed receipt, so a rolled-back enqueue cannot spend credits.
        plan = prepare(ledger, interview_id, revision, options)
        job_id = jobs.new_id()
        record = JobRecord(job_id=job_id, type="forecast_scenarios", spec=spec)
        record.annotations["scenario_plan"] = plan
        jobs.write(record)
        conn.execute(
            "INSERT INTO forecast_interview_evaluation_requests VALUES (?, ?, ?, ?)",
            (interview_id, request_id, encoded, job_id),
        )
    return job_id


def evaluation_status(ledger: ForecastLedger, interview_id: str) -> dict:
    current = InterviewStore(ledger).read(interview_id)
    with ledger._connect() as conn:
        receipt = conn.execute(
            "SELECT job_id, request_id FROM forecast_interview_evaluation_requests WHERE interview_id = ? ORDER BY rowid DESC LIMIT 1",
            (interview_id,),
        ).fetchone()
    if receipt is None:
        return {
            "found": False,
            "job": None,
            "request_id": None,
            "report": None,
            "stale": False,
        }
    try:
        job = JobStore().read(receipt["job_id"])
    except FileNotFoundError as exc:
        raise ValidationError(
            "saved scenario job is missing; inspect the profile before starting another call"
        ) from exc
    if job.type != "forecast_scenarios" or job.spec.get("interview_id") != interview_id:
        raise ValidationError("scenario job identity does not match its receipt")
    report = (
        ScenarioReport.model_validate(job.result).model_dump()
        if job.status == "done"
        else None
    )
    plan = job.annotations.get("scenario_plan", {})
    baseline_changed = False
    if current["document"]["question_id"]:
        question = ledger.get_question(current["document"]["question_id"])
        baseline_changed = (
            question.current_forecast_id != current["document"]["baseline_forecast_id"]
        )
        live = asdict(question)
        baseline_changed = baseline_changed or any(
            live.get(key) != plan.get("contract", {}).get(key)
            for key in (
                "resolution_criteria",
                "resolution_source",
                "outcome_space",
                "close_time",
                "resolution_time",
                "status",
            )
        )
    return {
        "found": True,
        "job": job.to_dict(),
        "request_id": receipt["request_id"],
        "report": report,
        "stale": current["digest"] != plan.get("input_digest") or baseline_changed,
    }
