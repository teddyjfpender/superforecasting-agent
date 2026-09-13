"""Scheduled warning runners share durable admission and conservative policy."""

from types import SimpleNamespace

import pytest

from forecasting.application import warning_runners
from forecasting.cron_runner import gated_evidence_collection
from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError


def test_scheduled_reforecast_and_evidence_share_proposal_only_policy(
    tmp_path, monkeypatch
):
    path = tmp_path / "ledger.db"
    ledger = ForecastLedger(path)
    question = ledger.create_question(
        title="Will CPI YoY be below 3% in July 2026?",
        resolution_criteria="Resolves yes if the BLS July 2026 CPI-U year-over-year release is below 3%; otherwise no.",
    )
    prior = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.4,
        rationale="Initial",
        require_panel=False,
    )
    warning = SimpleNamespace(scope_type="question", scope_ref=question.id)
    calls = []

    def stage(led, qid, *, stage="update", **kwargs):
        assert kwargs["commit_policy"] == "proposal_only"
        calls.append(stage)
        if stage == "update":
            led.create_forecast_update_proposal(
                question_id=qid,
                run_id=None,
                prior_forecast_id=prior.forecast_id,
                proposed_probability_or_distribution=0.6,
                rationale="New information",
            )
        elif not led.list_evidence(qid):
            led.add_evidence(
                question_id=qid,
                source_or_note="New observation",
                archive_url_snapshot=False,
            )
        return {"success": True}

    monkeypatch.setattr(
        warning_runners, "build_pipeline_status", lambda *_: {"update_ready": True}
    )
    reforecast, search = warning_runners.build_cron_warning_agent_runners(
        db_path=str(path),
        stage_runner=stage,
    )
    assert reforecast(ledger, warning)["status"] == "proposed"
    assert len(ledger.list_forecast_update_proposals(question_id=question.id)) == 1
    result = gated_evidence_collection(ledger, warning, evidence_search=search)
    assert result["new_evidence"] == 1
    # A successful model reply alone is not enough to acknowledge another warning.
    assert gated_evidence_collection(ledger, warning, evidence_search=search) is None
    assert ledger.get_current_snapshot(question.id).forecast_id == prior.forecast_id
    assert calls == ["update", "research", "research"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_iterations": 0},
        {"max_iterations": True},
        {"max_iterations": "12"},
        {"max_questions": -1},
        {"max_questions": False},
        {"force": "false"},
        {"commit_policy": "unknown"},
    ],
)
def test_invalid_runner_options_are_rejected_before_storage_or_execution(kwargs):
    with pytest.raises(ValidationError):
        warning_runners.build_cycle_reforecast_runner(None, **kwargs)
