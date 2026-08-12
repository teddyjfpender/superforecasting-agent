from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from forecasting.cron_runner import run_warning_resolution
from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError


def test_source_change_handoff_is_durable_deduplicated_and_consumed(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will an observed source change reach a worker exactly once?",
        resolution_criteria="Resolves yes if the source-change handoff is durable.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.4,
        rationale="Baseline before the watched source changed.",
    )
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source=str(source),
    )
    prior_signature = watch["last_seen_signature"]

    source.write_text("after", encoding="utf-8")
    first_alert = ledger.check_watched_sources(
        scope_type="question", scope_ref=question.id, now="2026-05-01T00:00:00Z"
    )[0]
    second_alert = ledger.check_watched_sources(
        scope_type="question", scope_ref=question.id, now="2026-05-01T00:01:00Z"
    )[0]

    events = ledger.list_source_change_events(question_id=question.id)
    tasks = ledger.list_operational_tasks(status="pending")
    assert first_alert.id == second_alert.id
    assert len(events) == 1
    assert len(tasks) == 1
    assert events[0]["status"] == "pending"
    assert events[0]["old_state"] == {"signature": prior_signature}
    assert events[0]["new_state"]["signature"] != prior_signature
    assert events[0]["new_source_snapshot_id"]
    assert tasks[0]["source_change_event_id"] == events[0]["id"]
    assert tasks[0]["alert_id"] == first_alert.id
    assert ledger.get_watched_source(watch["id"])["last_seen_signature"] == prior_signature

    result = ledger.run_source_change_router(
        owner="router-a", now="2026-05-01T00:02:00Z"
    )

    assert len(result) == 1
    assert ledger.get_watched_source(watch["id"])["last_seen_signature"] == prior_signature
    event = ledger.list_source_change_events(question_id=question.id)[0]
    task = ledger.list_operational_tasks()[0]
    assert event["status"] == "pending"
    assert event["state"] == "triaged"
    assert event["disposition"] == "estimator_required"
    assert task["status"] == "pending"
    assert task["lane"] == "normal_reforecast"


def test_source_router_uses_immutable_event_and_warning_sweep_does_not_repoll(
    tmp_path, monkeypatch
):
    from forecasting.cron_runner import run_warning_resolution

    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will the source queue preserve observation and judgment boundaries?",
        resolution_criteria="Resolves yes if the captured event is routed without another fetch.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.4,
        rationale="Baseline.",
    )
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    ledger.add_watched_source(
        scope_type="question", scope_ref=question.id, source=str(source)
    )
    source.write_text("after", encoding="utf-8")
    alert = ledger.check_watched_sources(
        scope_type="question", scope_ref=question.id, now="2026-05-01T00:00:00Z"
    )[0]
    monkeypatch.setattr(
        ledger,
        "_source_signature",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("source re-polled")),
    )

    routed = ledger.run_source_change_router(
        owner="router-a", now="2026-05-01T00:01:00Z"
    )

    assert len(routed) == 1
    assert routed[0]["event"]["state"] == "triaged"
    assert routed[0]["event"]["disposition"] == "estimator_required"
    assert routed[0]["task"]["lane"] == "normal_reforecast"
    assert routed[0]["task"]["status"] == "pending"
    sweep = run_warning_resolution(ledger=ledger, tier="free", reconcile=False)
    assert sweep["processed"] == 0
    assert ledger.get_alert(alert.id).acknowledged_at is None


def test_schema_recovers_successful_events_failed_by_legacy_question_recheck(tmp_path):
    db_path = tmp_path / "forecasting.db"
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will legacy batch failures be safely recoverable?",
        resolution_criteria="Resolves yes if a successful immutable event returns to its queue.",
    )
    ledger.create_snapshot(
        question_id=question.id, probability_or_distribution=0.5, rationale="Baseline."
    )
    source = tmp_path / "recover.txt"
    source.write_text("before", encoding="utf-8")
    ledger.add_watched_source(
        scope_type="question", scope_ref=question.id, source=str(source)
    )
    source.write_text("after", encoding="utf-8")
    ledger.check_watched_sources(scope_type="question", scope_ref=question.id)
    event = ledger.list_source_change_events(question_id=question.id)[0]
    task = ledger.list_operational_tasks()[0]
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE source_change_events SET status='failed', state='failed', "
            "disposition='source_failure', error='legacy recheck failed' WHERE id=?",
            (event["id"],),
        )
        conn.execute(
            "UPDATE operational_tasks SET status='failed', disposition='source_failure', "
            "error='legacy recheck failed' WHERE id=?",
            (task["id"],),
        )

    recovered = ForecastLedger(db_path)
    event_after = recovered.list_source_change_events(question_id=question.id)[0]
    task_after = recovered.list_operational_tasks()[0]
    assert event_after["status"] == "pending"
    assert event_after["state"] == "detected"
    assert event_after["disposition"] is None
    assert task_after["status"] == "pending"
    assert task_after["lane"] == "deterministic_critical"


def test_material_change_without_estimator_is_deferred_not_proposed(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    question = ledger.create_question(
        title="Will autopilot refuse to manufacture an unchanged estimate?",
        resolution_criteria="Resolves yes if an estimator is required.",
        resolution_source="fixture",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.6,
        rationale="Baseline.",
    )
    enabled = ledger.enable_autopilot(
        question_id=question.id,
        sources=[str(source)],
        cadence="1d",
    )
    source.write_text("after", encoding="utf-8")

    result = ledger.run_autopilot(question.id)

    assert result["run"]["status"] == "needs_estimation"
    assert result["proposal"] is None
    assert result["model_run"] is None
    assert any(alert.reason.startswith("autopilot_estimation_required:") for alert in result["alerts"])
    event = ledger.list_source_change_events(question_id=question.id)[0]
    task = ledger.list_operational_tasks()[0]
    assert event["status"] == "pending"
    assert event["disposition"] == "estimator_required"
    assert task["lane"] == "normal_reforecast"
    assert task["status"] == "pending"
    assert (
        ledger.get_watched_source(enabled["watched_sources"][0]["id"])[
            "last_seen_signature"
        ]
        == event["old_state"]["signature"]
    )


def test_estimator_worker_consumes_exact_event_without_repolling(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    question = ledger.create_question(
        title="Will the immutable source event reach the estimator?",
        resolution_criteria="Resolves yes if the exact captured event is estimated.",
        resolution_source="fixture",
    )
    baseline = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.4,
        rationale="Baseline.",
    )
    enabled = ledger.enable_autopilot(
        question_id=question.id,
        sources=[str(source)],
        cadence="1d",
        mode="auto_commit",
    )
    source.write_text("after", encoding="utf-8")
    ledger.run_autopilot(question.id, now="2026-05-01T00:00:00Z")
    event = ledger.list_source_change_events(question_id=question.id)[0]
    watch_id = enabled["watched_sources"][0]["id"]
    assert ledger.get_watched_source(watch_id)["last_seen_signature"] == event["old_state"]["signature"]

    monkeypatch.setattr(
        ledger,
        "_source_signature",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("re-polled source")),
    )

    seen = {}

    def estimator(payload):
        seen.update(payload)
        return {
            "proposed_probability_or_distribution": 0.57,
            "rationale": "The captured source update increases the chance of yes.",
            "model_version": "fixture-estimator",
            "usage": {
                "model_calls": 1,
                "input_tokens": 100,
                "output_tokens": 50,
                "cost_usd": 0.012,
                "latency_ms": 250,
            },
            "estimation_artifact": {
                "prior_probability": 0.4,
                "evidence_updates": [
                    {
                        "event_id": event["id"],
                        "likelihood_ratio": 1.8,
                        "correlation_cluster": "fixture-source",
                        "reliability_weight": 0.8,
                    }
                ],
                "raw_posterior": 0.57,
                "ensemble_components": {"bayesian_update": 0.57},
                "panel_result": {"status": "not_required"},
                "proposed_probability": 0.57,
                "materiality": "medium",
                "evidence_cutoff": "2026-05-01T00:00:00Z",
                "change_my_mind": ["The source update is reversed."],
                "guardrail_results": {},
            },
        }

    # Monitoring consent does not imply auto-commit consent. The estimator must
    # still create a reviewable proposal after the policy is disabled.
    ledger.disable_autopilot(question.id)
    result = ledger.run_estimator_tasks(
        owner="estimator-a", estimator=estimator, now="2026-05-01T00:01:00Z"
    )[0]

    assert seen["source_change_event"]["id"] == event["id"]
    assert seen["source_snapshot"]["id"] == event["new_source_snapshot_id"]
    assert seen["prior_forecast"]["forecast_id"] == baseline.forecast_id
    assert result["proposal"]["proposed_probability_or_distribution"] == 0.57
    assert result["proposal"]["evidence_refs"]
    assert seen["source_snapshot"]["parsed_values"]["changed_items"]
    assert result["task"]["status"] == "completed"
    assert result["event"]["status"] == "processed"
    assert result["event"]["state"] == "reconciled"
    assert ledger.get_current_snapshot(question.id).forecast_id == baseline.forecast_id
    assert ledger.get_watched_source(watch_id)["last_seen_signature"] == event["new_state"]["signature"]
    transitions = ledger.list_source_change_event_transitions(event["id"])
    assert [row["to_state"] for row in transitions] == [
        "detected",
        "triaged",
        "claimed",
        "researched",
        "estimated",
        "proposed",
        "reconciled",
    ]
    with ledger._connect() as conn:
        usage = dict(
            conn.execute(
                "SELECT * FROM operational_task_attempts WHERE task_id = ?",
                (result["task"]["id"],),
            ).fetchone()
        )
    assert usage["model_calls"] == 1
    assert usage["cost_usd"] == pytest.approx(0.012)
    cockpit = ledger.operational_cockpit(now="2026-05-01T00:02:00Z")
    assert cockpit["cost"]["total_usd"] == pytest.approx(0.012)
    assert cockpit["cost"]["per_material_update_usd"] == pytest.approx(0.012)
    assert cockpit["history"][-1]["arrivals"] == 1
    assert cockpit["history"][-1]["services"] == 1
    ledger.reject_forecast_update_proposal(
        result["proposal"]["id"], reviewed_by="reviewer-a"
    )
    proposal_task = next(
        task
        for task in ledger.list_operational_tasks(limit=100)
        if task["task_type"] == "review_forecast_proposal"
        and (task.get("result") or {}).get("proposal_id") == result["proposal"]["id"]
    )
    assert proposal_task["status"] == "completed"
    assert proposal_task["disposition"] == "rejected"
    transitions = ledger.list_source_change_event_transitions(event["id"])
    assert [row["to_state"] for row in transitions][-2:] == ["rejected", "reconciled"]


def test_estimator_coalesces_same_forecast_source_events_into_one_estimate(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    sources = [tmp_path / "one.txt", tmp_path / "two.txt"]
    for source in sources:
        source.write_text("before", encoding="utf-8")
    question = ledger.create_question(
        title="Will one estimate consume one forecast's source batch?",
        resolution_criteria="Resolves yes when all captured events share one audited estimate.",
        resolution_source="fixture",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.4,
        rationale="Baseline.",
    )
    ledger.enable_autopilot(
        question_id=question.id,
        sources=[str(source) for source in sources],
        cadence="1d",
        mode="propose",
    )
    for source in sources:
        source.write_text("after", encoding="utf-8")
    ledger.run_autopilot(question.id, now="2026-05-01T00:00:00Z")
    events = ledger.list_source_change_events(question_id=question.id)
    assert len(events) == 2
    estimation_alert = ledger.create_alert(
        severity="warning",
        scope_type="question",
        scope_ref=question.id,
        reason="forecast_estimation_required:mr_fixture",
        recommended_action="Estimate the captured source batch.",
        now="2026-05-01T00:00:00Z",
    )
    generic_task = ledger.enqueue_alert_operational_task(
        estimation_alert, lane="normal_reforecast", now="2026-05-01T00:00:00Z"
    )
    paid_calls = []
    paid = run_warning_resolution(
        ledger=ledger,
        tier="reforecast",
        reforecast_runner=lambda _ledger, warning: paid_calls.append(warning.id) or True,
        reconcile=False,
    )
    assert paid["processed"] == 0
    assert paid_calls == []
    calls = 0

    def estimator(payload):
        nonlocal calls
        calls += 1
        event_ids = [event["id"] for event in payload["source_change_events"]]
        assert set(event_ids) == {event["id"] for event in events}
        return {
            "proposed_probability_or_distribution": 0.56,
            "rationale": "The combined source batch increases the estimate.",
            "model_version": "fixture-estimator",
            "estimation_artifact": {
                "prior_probability": 0.4,
                "evidence_updates": [
                    {
                        "event_id": event_id,
                        "likelihood_ratio": 1.4,
                        "correlation_cluster": "fixture-batch",
                        "reliability_weight": 0.7,
                    }
                    for event_id in event_ids
                ],
                "raw_posterior": 0.56,
                "ensemble_components": {"bayesian_update": 0.56},
                "panel_result": {"status": "not_required"},
                "proposed_probability": 0.56,
                "materiality": "medium",
                "evidence_cutoff": "2026-05-01T00:00:00Z",
                "change_my_mind": ["The source revisions are reversed."],
                "guardrail_results": {},
            },
        }

    results = ledger.run_estimator_tasks(
        owner="estimator-a",
        estimator=estimator,
        now="2026-05-01T00:01:00Z",
        limit=1,
        question_id=question.id,
    )

    assert calls == 1
    assert len(results) == 1
    assert results[0]["coalesced_event_count"] == 1
    assert set(results[0]["proposal"]["source_snapshot_refs"]) == {
        event["new_source_snapshot_id"] for event in events
    }
    assert {event["status"] for event in ledger.list_source_change_events(question_id=question.id)} == {
        "processed"
    }
    assert {
        task["status"]
        for task in ledger.list_operational_tasks(limit=20)
        if task["source_change_event_id"] in {event["id"] for event in events}
    } == {"completed"}
    assert ledger.get_alert(estimation_alert.id).acknowledged_at is not None
    assert next(
        task
        for task in ledger.list_operational_tasks(limit=20)
        if task["id"] == generic_task["id"]
    )["status"] == "completed"


def test_source_claim_limit_backfills_past_same_question_siblings(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question_ids = []
    for index in range(2):
        sources = [tmp_path / f"{index}-{side}.txt" for side in ("a", "b")]
        for source in sources:
            source.write_text("before", encoding="utf-8")
        question = ledger.create_question(
            title=f"Will source claims span question {index}?",
            resolution_criteria="Resolves yes when the worker claims distinct questions.",
            resolution_source="fixture",
        )
        question_ids.append(question.id)
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="Baseline.",
        )
        ledger.enable_autopilot(
            question_id=question.id,
            sources=[str(source) for source in sources],
            cadence="1d",
        )
        for source in sources:
            source.write_text("after", encoding="utf-8")
        ledger.run_autopilot(question.id, now="2026-05-01T00:00:00Z")
    ledger.run_source_change_router(
        owner="router", now="2026-05-01T00:01:00Z", limit=10
    )

    claimed = ledger.claim_operational_tasks(
        owner="estimator",
        lane="normal_reforecast",
        task_type="process_source_change",
        now="2026-05-01T00:02:00Z",
        limit=2,
    )

    assert len(claimed) == 2
    assert {task["question_id"] for task in claimed} == set(question_ids)


def test_explicitly_immaterial_estimate_is_reconciled_without_a_proposal(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    question = ledger.create_question(
        title="Will an unchanged estimate close as immaterial?",
        resolution_criteria="Resolves yes if zero-delta estimates do not create proposals.",
        resolution_source="fixture",
    )
    baseline = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.4,
        rationale="Baseline.",
    )
    ledger.enable_autopilot(
        question_id=question.id,
        sources=[str(source)],
        cadence="1d",
        mode="propose",
        materiality_policy={"min_source_changes": 1, "min_probability_delta": 0.03},
    )
    source.write_text("after", encoding="utf-8")
    ledger.run_autopilot(question.id, now="2026-05-01T00:00:00Z")
    event = ledger.list_source_change_events(question_id=question.id)[0]

    def estimator(_payload):
        return {
            "proposed_probability_or_distribution": 0.6,
            "rationale": "The captured evidence does not change the estimate.",
            "model_version": "fixture-estimator",
            "estimation_artifact": {
                "prior_probability": 0.4,
                "evidence_updates": [
                    {
                        "event_id": event["id"],
                        "likelihood_ratio": 1.0,
                        "correlation_cluster": "fixture-source",
                        "reliability_weight": 0.8,
                    }
                ],
                "raw_posterior": 0.6,
                "ensemble_components": {"bayesian_update": 0.6},
                "panel_result": {"status": "not_required"},
                "proposed_probability": 0.6,
                "materiality": {"changed": False, "threshold_triggered": False},
                "evidence_cutoff": "2026-05-01T00:00:00Z",
                "change_my_mind": ["A larger source revision."],
                "guardrail_results": {},
            },
        }

    result = ledger.run_estimator_tasks(
        owner="estimator-a", estimator=estimator, now="2026-05-01T00:01:00Z"
    )[0]

    assert result["proposal"] is None
    assert result["task"]["disposition"] == "reviewed_immaterial"
    assert result["event"]["disposition"] == "reviewed_immaterial"
    assert result["event"]["state"] == "reconciled"
    assert ledger.get_current_snapshot(question.id).forecast_id == baseline.forecast_id
    assert ledger.list_forecast_update_proposals(question_id=question.id) == []


def test_estimator_worker_dead_letters_incomplete_artifact_without_retry(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    question = ledger.create_question(
        title="Will malformed estimates be rejected?",
        resolution_criteria="Resolves yes if incomplete artifacts cannot become proposals.",
        resolution_source="fixture",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Baseline.",
    )
    ledger.enable_autopilot(
        question_id=question.id, sources=[str(source)], cadence="1d"
    )
    source.write_text("after", encoding="utf-8")
    ledger.run_autopilot(question.id)

    result = ledger.run_estimator_tasks(
        owner="estimator-a",
        estimator=lambda _payload: {
            "proposed_probability_or_distribution": 0.6,
            "rationale": "Incomplete on purpose.",
            "estimation_artifact": {},
        },
    )[0]

    assert result["task"]["status"] == "dead_letter"
    assert result["task"]["attempt_count"] == 1
    assert result["task"]["disposition"] == "invalid_payload_dead_letter"
    assert "estimation artifact missing" in result["error"]
    assert ledger.list_forecast_update_proposals(question_id=question.id) == []
    event = ledger.list_source_change_events(question_id=question.id)[0]
    assert event["state"] == "failed"


def test_estimator_event_is_closed_when_a_new_forecast_supersedes_it(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    question = ledger.create_question(
        title="Will newer judgment supersede queued source work?",
        resolution_criteria="Resolves yes if stale estimator work cannot overwrite it.",
        resolution_source="fixture",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.4,
        rationale="Baseline.",
    )
    enabled = ledger.enable_autopilot(
        question_id=question.id, sources=[str(source)], cadence="1d"
    )
    source.write_text("after", encoding="utf-8")
    ledger.run_autopilot(question.id, now="2026-05-01T00:00:00Z")
    event = ledger.list_source_change_events(question_id=question.id)[0]
    newer = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.48,
        rationale="A newer manual forecast landed before the worker claimed the event.",
    )

    result = ledger.run_estimator_tasks(
        owner="estimator-a",
        estimator=lambda _payload: {},
        now="2026-05-01T00:01:00Z",
    )[0]

    assert result["superseded"] is True
    assert result["event"]["status"] == "processed"
    assert result["event"]["state"] == "superseded"
    assert result["event"]["forecast_snapshot_id"] == newer.forecast_id
    assert ledger.list_forecast_update_proposals(question_id=question.id) == []
    watch = ledger.get_watched_source(enabled["watched_sources"][0]["id"])
    assert watch["last_seen_signature"] == event["new_state"]["signature"]


def test_hosted_estimator_preserves_configured_model_and_measured_usage(monkeypatch):
    from forecasting.estimator_worker import build_agent_estimator

    captured = {}

    class FakeAgent:
        def run_conversation(self, user, system_message=None):
            captured["user"] = user
            captured["system"] = system_message
            return {
                "final_response": json.dumps(
                    {
                        "proposed_probability_or_distribution": {
                            "type": "distribution",
                            "distribution": {
                                "point_estimate": 0.6,
                                "epistemic_interval_80": [0.4, 0.8],
                            },
                        },
                        "rationale": "Fixture estimate.",
                        "usage": {"cost_usd": 999},
                        "estimation_artifact": {},
                    }
                ),
                "model": "configured-model",
                "api_calls": 2,
                "messages": [{"role": "tool"}],
                "input_tokens": 120,
                "output_tokens": 30,
                "estimated_cost_usd": 0.04,
                "cost_status": "estimated",
                "cost_source": "fixture-pricing",
            }

    def fake_build_agent(**kwargs):
        captured["kwargs"] = kwargs
        return FakeAgent()

    monkeypatch.setattr("agent.agent_factory.build_agent", fake_build_agent)
    estimator = build_agent_estimator(
        model="configured-model", provider="openai-codex", max_iterations=7
    )
    result = estimator(
        {
            "source_change_event": {"id": "sce_fixture"},
            "question": {"outcome_space": {"type": "binary"}},
        }
    )

    assert captured["kwargs"]["model"] == "configured-model"
    assert captured["kwargs"]["requested_provider"] == "openai-codex"
    assert captured["kwargs"]["max_iterations"] == 7
    assert result["model_version"] == "configured-model"
    assert result["proposed_probability_or_distribution"] == 0.6
    assert result["usage"] == {
        "model_calls": 2,
        "source_calls": 1,
        "input_tokens": 120,
        "output_tokens": 30,
        "cost_usd": 0.04,
        "cost_status": "estimated",
        "cost_source": "fixture-pricing",
    }


def test_numeric_estimator_envelope_strips_structural_fields():
    from forecasting.estimator_worker import normalize_estimator_forecast

    assert normalize_estimator_forecast(
        {
            "type": "numeric",
            "units": "US dollars per week",
            "bounds": [0, 5000],
            "estimate_status": "estimated",
            "mean": 1243,
            "q05": 1207,
            "q50": 1245,
            "q95": 1279,
        },
        outcome_type="numeric",
    ) == {"mean": 1243, "q05": 1207, "q50": 1245, "q95": 1279}


def test_signature_only_source_event_closes_without_estimator_call(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    question = ledger.create_question(
        title="Will a signature-only event avoid unsupported estimation?",
        resolution_criteria="Resolves yes when the estimator is not called.",
        resolution_source="fixture",
    )
    baseline = ledger.create_snapshot(
        question_id=question.id, probability_or_distribution=0.5, rationale="Baseline."
    )
    ledger.enable_autopilot(question_id=question.id, sources=[str(source)], cadence="1d")
    source.write_text("after", encoding="utf-8")
    ledger.run_autopilot(question.id)
    event = ledger.list_source_change_events(question_id=question.id)[0]
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE source_snapshots SET parsed_values = ? WHERE id = ?",
            (json.dumps({"signature": "legacy", "changed": True}), event["new_source_snapshot_id"]),
        )

    result = ledger.run_estimator_tasks(
        owner="estimator-a",
        estimator=lambda _payload: (_ for _ in ()).throw(AssertionError("must not run")),
    )[0]

    assert result["insufficient_content"] is True
    assert result["task"]["disposition"] == "insufficient_content"
    assert result["event"]["forecast_snapshot_id"] == baseline.forecast_id


def test_batch_source_failure_has_one_parent_and_terminal_children(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("before", encoding="utf-8")
    second.write_text("before", encoding="utf-8")
    question = ledger.create_question(
        title="Will batch failures avoid duplicated production errors?",
        resolution_criteria="Resolves yes when one refresh has one failure parent.",
        resolution_source="fixture",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Baseline.",
    )
    ledger.enable_autopilot(
        question_id=question.id,
        sources=[str(first), str(second)],
        cadence="1d",
    )
    first.write_text("after", encoding="utf-8")
    second.write_text("after", encoding="utf-8")
    ledger.run_autopilot(question.id, now="2026-05-01T00:00:00Z")
    events = ledger.list_source_change_events(question_id=question.id)

    from forecasting.ledger.workflow import complete_source_change_events

    complete_source_change_events(
        ledger,
        question_id=question.id,
        event_ids=[event["id"] for event in events],
        status="failed",
        disposition="source_failure",
        error="batch refresh failed",
        now="2026-05-01T00:01:00Z",
    )
    updated = ledger.list_source_change_events(question_id=question.id)
    parent = next(event for event in updated if event["status"] == "failed")
    children = [event for event in updated if event["status"] == "processed"]

    assert parent["disposition"] == "source_failure_batch"
    assert len(children) == 1
    assert children[0]["disposition"] == "source_failure_child"
    assert children[0]["metadata"]["source_failure_parent_id"] == parent["id"]


def test_cron_hosts_estimator_and_guarded_utility_calibration(
    tmp_path, monkeypatch, capsys
):
    from forecasting import cron_runner
    from forecasting import estimator_worker

    captured = {}
    monkeypatch.setattr(cron_runner, "run_due_reviews", lambda **_kwargs: "")

    def fake_worker(ledger, **kwargs):
        captured.update(kwargs)
        assert ledger.db_path == tmp_path / "forecasting.db"
        return [{"task": {"id": "ot_fixture"}}]

    monkeypatch.setattr(estimator_worker, "run_hosted_estimator_worker", fake_worker)

    code = cron_runner.main(
        [
            "--db",
            str(tmp_path / "forecasting.db"),
            "--estimate-source-changes",
            "--estimator-model",
            "configured-model",
            "--estimator-provider",
            "openai-codex",
            "--calibrate-utility",
        ]
    )

    assert code == 0
    assert captured["model"] == "configured-model"
    assert captured["provider"] == "openai-codex"
    output = capsys.readouterr().out
    assert '"estimator_tasks"' in output
    assert '"utility_calibration"' in output
    assert '"activated": false' in output.lower()


def test_watched_sources_share_adapter_account_token_bucket(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will adapter quotas be shared across watches?",
        resolution_criteria="Resolves yes if one account bucket governs both sources.",
    )
    calls = []
    monkeypatch.setattr(
        ledger,
        "_source_signature",
        lambda source, _source_type, metadata=None: calls.append(source) or "initial",
    )
    rate_limit = {
        "rate_limit": {
            "account_key": "shared-account",
            "capacity": 1,
            "refill_per_second": 0.000001,
        }
    }
    ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="https://example.test/one",
        source_type="url",
        metadata=rate_limit,
    )
    ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="https://example.test/two",
        source_type="url",
        metadata=rate_limit,
    )
    calls.clear()
    monkeypatch.setattr(
        ledger,
        "_source_signature",
        lambda source, _source_type, metadata=None: calls.append(source) or "changed",
    )

    alerts = ledger.check_watched_sources(
        scope_type="question", scope_ref=question.id, now="2026-05-01T00:00:00Z"
    )

    assert len(calls) == 1
    assert len(alerts) == 1
    bucket = ledger.list_source_token_buckets()[0]
    assert bucket["bucket"] == "url:shared-account"
    assert bucket["granted_count"] == 1
    assert bucket["denied_count"] == 1


def test_source_token_bucket_is_atomic_across_workers(tmp_path):
    path = tmp_path / "forecasting.db"
    ledger = ForecastLedger(path)
    watch = {
        "source_type": "url",
        "metadata": {
            "rate_limit": {
                "account_key": "atomic-account",
                "capacity": 1,
                "refill_per_second": 0.000001,
            }
        },
    }

    def acquire(_index):
        return ForecastLedger(path).acquire_watch_source_token(
            watch, now="2026-05-01T00:00:00Z"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(acquire, range(2)))

    assert sorted(result["granted"] for result in results) == [False, True]
    bucket = ledger.list_source_token_buckets()[0]
    assert bucket["granted_count"] == 1
    assert bucket["denied_count"] == 1


def test_operational_claims_are_utility_ranked_and_backtestable(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    high = ledger.create_question(
        title="Will high-impact urgent work rank first?",
        resolution_criteria="Resolves yes if utility ordering is enforced.",
        impact="critical",
        decision_deadline="2026-05-02T00:00:00Z",
    )
    low = ledger.create_question(
        title="Will low-impact distant work rank later?",
        resolution_criteria="Resolves yes if utility ordering is enforced.",
        impact="low",
        decision_deadline="2027-05-01T00:00:00Z",
    )
    sources = []
    for question in (low, high):
        path = tmp_path / f"{question.id}.txt"
        path.write_text("before", encoding="utf-8")
        ledger.add_watched_source(
            scope_type="question", scope_ref=question.id, source=str(path)
        )
        path.write_text("after", encoding="utf-8")
        sources.append(path)
    ledger.check_watched_sources(now="2026-05-01T00:00:00Z")

    tasks = ledger.list_operational_tasks(status="pending")
    assert [task["question_id"] for task in tasks] == [high.id, low.id]
    assert tasks[0]["utility_score"] > tasks[1]["utility_score"]
    claimed = ledger.claim_operational_tasks(
        owner="worker-a", now="2026-05-01T00:01:00Z", limit=2
    )
    by_question = {task["question_id"]: task for task in claimed}
    ledger.complete_operational_task(
        by_question[high.id]["id"], owner="worker-a", disposition="proposed"
    )
    ledger.complete_operational_task(
        by_question[low.id]["id"], owner="worker-a", disposition="no_material_change"
    )

    report = ledger.utility_backtest()
    assert report["sample_size"] == 2
    assert report["top_half_useful_rate"] == 1.0
    assert report["bottom_half_useful_rate"] == 0.0
    assert report["pairwise_concordance"] == 1.0

    high_components = dict(tasks[0]["utility_components"])
    low_components = dict(tasks[1]["utility_components"])
    with ledger._connect() as conn:
        for index in range(18):
            positive = index % 2 == 0
            conn.execute(
                """
                INSERT INTO operational_tasks (
                    id, task_type, lane, status, priority, utility_score,
                    utility_components, available_at, completed_at, idempotency_key,
                    disposition, created_at, updated_at
                ) VALUES (?, 'calibration_fixture', 'normal_reforecast', 'completed',
                          50, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"utility_fixture_{index}",
                    90 if positive else 10,
                    json.dumps(high_components if positive else low_components),
                    "2026-05-01T00:00:00Z",
                    "2026-05-01T00:01:00Z",
                    f"utility-fixture:{index}",
                    "proposed" if positive else "no_material_change",
                    "2026-05-01T00:00:00Z",
                    "2026-05-01T00:01:00Z",
                ),
            )

    calibration = ledger.calibrate_task_utility()
    assert calibration["activated"] is True
    assert calibration["sample_size"] == 20
    assert calibration["metrics"]["pairwise_concordance"] >= 0.9


def test_operational_task_retries_heartbeat_and_dead_letters(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    question = ledger.create_question(
        title="Will exhausted operational work dead-letter?",
        resolution_criteria="Resolves yes if retries are bounded.",
    )
    watch = ledger.add_watched_source(
        scope_type="question", scope_ref=question.id, source=str(source)
    )
    source.write_text("after", encoding="utf-8")
    ledger.check_watched_sources(scope_type="question", scope_ref=question.id)
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE operational_tasks SET max_attempts = 2 WHERE source_change_event_id IS NOT NULL"
        )

    first = ledger.claim_operational_tasks(owner="worker-a", limit=1)[0]
    renewed = ledger.heartbeat_operational_task(first["id"], owner="worker-a")
    assert renewed["lease_owner"] == "worker-a"
    retry = ledger.fail_operational_task(
        first["id"], owner="worker-a", error="transient", retry_delay_seconds=0
    )
    assert retry["status"] == "pending"
    assert retry["disposition"] == "failed_retrying"

    second = ledger.claim_operational_tasks(owner="worker-b", limit=1)[0]
    dead = ledger.fail_operational_task(second["id"], owner="worker-b", error="still broken")
    assert dead["status"] == "dead_letter"
    assert dead["disposition"] == "failed_dead_letter"
    assert ledger.claim_operational_tasks(owner="worker-c") == []
    with pytest.raises(ValueError):
        ledger.heartbeat_operational_task(dead["id"], owner="worker-b")


def test_dead_letter_recovery_reroutes_triggers_and_delays_transient_sources(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will dead letters receive an explicit recovery policy?",
        resolution_criteria="Resolves yes when each failure class is routed.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Baseline.",
    )
    watch = ledger.add_watched_source(
        scope_type="question", scope_ref=question.id, source="https://example.com/feed"
    )
    trigger = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref=question.id,
        reason="trigger_fired:fred:CPIAUCSL",
        recommended_action="Reforecast from the captured trigger.",
    )
    unavailable = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref=question.id,
        reason=f"watched_source_unavailable:{watch['id']}",
        recommended_action="Repair or replace the source.",
    )
    orphaned_change = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref=question.id,
        reason="watched_source_changed:ws_missing_exact_event",
        recommended_action="Inspect the missing exact-event worker.",
    )
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE operational_tasks SET status='dead_letter', attempt_count=max_attempts "
            "WHERE alert_id IN (?, ?, ?)",
            (trigger.id, unavailable.id, orphaned_change.id),
        )

    recovered = ledger.reconcile_operational_dead_letters(
        owner="recovery-a",
        now="2026-07-21T12:00:00Z",
        transient_retry_delay_seconds=3600,
    )

    assert {row["action"] for row in recovered} == {
        "recovered_to_reforecast",
        "source_monitor_retrying",
        "manual_dead_letter_review",
    }
    tasks = {task["alert_id"]: task for task in ledger.list_operational_tasks(limit=20)}
    assert tasks[trigger.id]["status"] == "pending"
    assert tasks[trigger.id]["lane"] == "urgent_forecast"
    assert tasks[unavailable.id]["status"] == "completed"
    assert tasks[unavailable.id]["disposition"] == "source_monitor_retrying"
    assert tasks[orphaned_change.id]["status"] == "dead_letter"
    assert tasks[orphaned_change.id]["disposition"] == "manual_dead_letter_review"
    assert ledger.get_alert(unavailable.id).acknowledged_at is None
    assert ledger.reconcile_operational_dead_letters(
        owner="recovery-b", now="2026-07-21T13:00:00Z"
    ) == []


def test_recovery_closes_legacy_source_warning_tasks_with_current_owners(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will each source alert have exactly one worker?",
        resolution_criteria="Resolves yes when legacy warning tasks are retired.",
    )
    watch = ledger.add_watched_source(
        scope_type="question", scope_ref=question.id, source="https://example.com/feed"
    )
    changed = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref=question.id,
        reason=f"watched_source_changed:{watch['id']}",
        recommended_action="Estimate the exact observed event.",
    )
    unavailable = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref=question.id,
        reason=f"watched_source_unavailable:{watch['id']}",
        recommended_action="Let the source monitor retry.",
    )
    profile_digest = ledger.create_alert(
        severity="high",
        scope_type="domain_error_profile",
        scope_ref="dep_fixture",
        reason="domain_error_profile_review",
        recommended_action="Keep the learned-error digest visible.",
    )
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO operational_tasks (
                id, task_type, lane, question_id, alert_id, status, priority,
                utility_score, utility_components, available_at, idempotency_key,
                created_at, updated_at
            ) VALUES (
                'ot_exact_source', 'process_source_change', 'normal_reforecast', ?, ?,
                'pending', 70, 0, '{}', '2026-07-21T12:00:00Z',
                'source:test-exact-owner', '2026-07-21T12:00:00Z',
                '2026-07-21T12:00:00Z'
            )
            """,
            (question.id, changed.id),
        )

    recovered = ledger.reconcile_operational_dead_letters(
        owner="recovery-a", now="2026-07-21T12:01:00Z"
    )

    assert {row["action"] for row in recovered} == {
        "profile_digest_visible",
        "source_event_worker_owns",
        "source_monitor_retrying",
    }
    tasks = ledger.list_operational_tasks(limit=20)
    changed_warning = next(
        row for row in tasks if row["alert_id"] == changed.id and row["task_type"] == "resolve_warning"
    )
    exact_worker = next(row for row in tasks if row["id"] == "ot_exact_source")
    unavailable_task = next(row for row in tasks if row["alert_id"] == unavailable.id)
    assert changed_warning["status"] == "completed"
    assert changed_warning["disposition"] == "source_event_worker_owns"
    assert exact_worker["status"] == "pending"
    assert unavailable_task["status"] == "completed"
    assert unavailable_task["disposition"] == "source_monitor_retrying"
    assert ledger.get_alert(changed.id).acknowledged_at is None
    assert ledger.get_alert(unavailable.id).acknowledged_at is None
    assert ledger.get_alert(profile_digest.id).acknowledged_at is None
    assert ledger.get_alert(profile_digest.id).severity == "info"
    digest_task = next(row for row in tasks if row["alert_id"] == profile_digest.id)
    assert digest_task["status"] == "completed"
    assert digest_task["disposition"] == "profile_digest_visible"


def test_recovery_coalesces_trigger_when_estimator_task_owns_question(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will recovered triggers avoid duplicate reforecasts?",
        resolution_criteria="Resolves yes when estimator ownership is unique.",
    )
    trigger = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref=question.id,
        reason="trigger_fired:fred:FIXTURE",
        recommended_action="Reforecast once.",
        now="2026-07-21T10:00:00Z",
    )
    estimator_alert = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref=question.id,
        reason="forecast_estimation_required:mr_fixture",
        recommended_action="Run the estimator.",
        now="2026-07-21T10:01:00Z",
    )
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE operational_tasks
            SET lane='urgent_forecast', status='pending',
                disposition='recovered_to_reforecast'
            WHERE alert_id=?
            """,
            (trigger.id,),
        )
        conn.execute(
            "UPDATE operational_tasks SET lane='normal_reforecast' WHERE alert_id=?",
            (estimator_alert.id,),
        )

    result = ledger.reconcile_operational_dead_letters(
        owner="recovery-a", now="2026-07-21T10:02:00Z"
    )
    trigger_task = next(
        task for task in ledger.list_operational_tasks() if task["alert_id"] == trigger.id
    )

    assert any(row["action"] == "reconcile_recovered_trigger" for row in result)
    assert trigger_task["status"] == "completed"
    assert trigger_task["disposition"] == "coalesced_to_estimator"
    assert ledger.get_alert(trigger.id).acknowledged_at == "2026-07-21T10:02:00Z"


def test_expired_task_reclaim_closes_abandoned_attempt(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("before", encoding="utf-8")
    question = ledger.create_question(
        title="Will a crashed worker leave a truthful attempt record?",
        resolution_criteria="Resolves yes if lease recovery records the abandoned attempt.",
    )
    ledger.add_watched_source(
        scope_type="question", scope_ref=question.id, source=str(source)
    )
    source.write_text("after", encoding="utf-8")
    ledger.check_watched_sources(
        scope_type="question",
        scope_ref=question.id,
        now="2026-05-01T00:00:00Z",
    )

    first = ledger.claim_operational_tasks(
        owner="worker-crashed",
        now="2026-05-01T00:01:00Z",
        lease_seconds=1,
        limit=1,
    )[0]
    recovered = ledger.claim_operational_tasks(
        owner="worker-recovered",
        now="2026-05-01T00:01:02Z",
        limit=1,
    )[0]

    assert recovered["id"] == first["id"]
    with ledger._connect() as conn:
        attempts = conn.execute(
            "SELECT owner, finished_at, outcome, code_revision, worktree_dirty "
            "FROM operational_task_attempts "
            "WHERE task_id = ? ORDER BY claimed_at",
            (first["id"],),
        ).fetchall()
    assert [row["owner"] for row in attempts] == [
        "worker-crashed",
        "worker-recovered",
    ]
    assert attempts[0]["finished_at"] == "2026-05-01T00:01:02Z"
    assert attempts[0]["outcome"] == "lease_expired"
    assert attempts[1]["finished_at"] is None
    assert all(row["code_revision"] for row in attempts)
    assert all(row["worktree_dirty"] in {0, 1} for row in attempts)


def test_pending_proposal_expires_and_cannot_commit(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will stale proposals be rejected automatically?",
        resolution_criteria="Resolves yes if proposal SLAs expire.",
    )
    baseline = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Baseline.",
    )
    proposal = ledger.create_forecast_update_proposal(
        question_id=question.id,
        run_id=None,
        prior_forecast_id=baseline.forecast_id,
        proposed_probability_or_distribution=0.55,
        rationale="Explicit estimate.",
        expires_at="2099-01-02T00:00:00Z",
    )
    proposed_alert = ledger.create_alert(
        severity="info",
        scope_type="question",
        scope_ref=question.id,
        reason=f"autopilot_update_proposed:{proposal['id']}",
        recommended_action="Review the proposal.",
    )

    assert ledger.expire_forecast_update_proposals(now="2099-01-01T23:30:00Z") == []
    assert any(
        alert.reason == f"forecast_update_proposal_expiring:{proposal['id']}"
        for alert in ledger.list_alerts(unresolved_only=True)
    )

    expired = ledger.expire_forecast_update_proposals(now="2099-01-03T00:00:00Z")

    assert [row["id"] for row in expired] == [proposal["id"]]
    assert expired[0]["status"] == "expired"
    assert expired[0]["reviewed_by"] == "lifecycle:expired"
    assert ledger.get_alert(proposed_alert.id).disposition == "expired"
    assert ledger.get_alert(proposed_alert.id).ack_note == "auto_close:proposal_expired"
    with pytest.raises(ValidationError):
        ledger.approve_forecast_update_proposal(proposal["id"])


def test_pending_proposal_is_superseded_by_newer_committed_forecast(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will stale proposal bases close immediately?",
        resolution_criteria="Resolves yes when stale proposals become superseded.",
    )
    baseline = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Baseline.",
    )
    proposal = ledger.create_forecast_update_proposal(
        question_id=question.id,
        run_id=None,
        prior_forecast_id=baseline.forecast_id,
        proposed_probability_or_distribution=0.55,
        rationale="Potential update.",
        expires_at="2099-01-02T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.6,
        rationale="A newer committed forecast supersedes the proposal base.",
    )

    assert ledger.expire_forecast_update_proposals(now="2099-01-01T00:00:00Z") == []
    updated = ledger.get_forecast_update_proposal(proposal["id"])
    review_task = next(
        task
        for task in ledger.list_operational_tasks(limit=100)
        if task["task_type"] == "review_forecast_proposal"
        and (task.get("result") or {}).get("proposal_id") == proposal["id"]
    )

    assert updated["status"] == "superseded"
    assert updated["reviewed_by"] == "lifecycle:newer_forecast"
    assert review_task["status"] == "completed"
    assert review_task["disposition"] == "superseded"


def test_proposal_approval_is_atomic_and_rejects_a_stale_empty_parent(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will approval stay atomic?",
        resolution_criteria="Resolves yes if proposal approval is atomic.",
    )
    proposal = ledger.create_forecast_update_proposal(
        question_id=question.id,
        run_id=None,
        prior_forecast_id=None,
        proposed_probability_or_distribution=0.55,
        rationale="Proposed first snapshot.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.45,
        rationale="A first snapshot landed before approval.",
    )

    with pytest.raises(ValidationError, match="superseded"):
        ledger.approve_forecast_update_proposal(proposal["id"])
    assert ledger.get_forecast_update_proposal(proposal["id"])["status"] == "superseded"
    assert len(ledger.list_snapshots(question.id)) == 1

    current = ledger.get_current_snapshot(question.id)
    retry = ledger.create_forecast_update_proposal(
        question_id=question.id,
        run_id=None,
        prior_forecast_id=current.forecast_id,
        proposed_probability_or_distribution=0.60,
        rationale="A second proposed update.",
    )

    def _fail_snapshot(**kwargs):
        raise RuntimeError("injected snapshot failure")

    monkeypatch.setattr(ledger, "create_snapshot", _fail_snapshot)
    with pytest.raises(RuntimeError, match="injected snapshot failure"):
        ledger.approve_forecast_update_proposal(retry["id"])
    assert ledger.get_forecast_update_proposal(retry["id"])["status"] == "pending"
    assert len(ledger.list_snapshots(question.id)) == 1


def test_service_modes_and_operational_cockpit_enforce_capacity_policy(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will portfolio capacity modes stop low-value work?",
        resolution_criteria="Resolves yes if inactive work is disabled by policy.",
    )
    resolver = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="official result",
        source_type="manual",
        role="resolver",
    )
    context = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="background notes",
        source_type="manual",
        role="background_context",
    )
    review = ledger.schedule_review(
        scope_type="question", scope_ref=question.id, cadence="daily"
    )

    result = ledger.set_question_service_mode(question.id, "resolution_only")

    by_watch = {row["id"]: row for row in result["watched_sources"]}
    assert by_watch[resolver["id"]]["status"] == "active"
    assert by_watch[context["id"]]["status"] == "inactive"
    assert ledger.get_scheduled_review(review["id"])["enabled"] == 0
    cockpit = ledger.operational_cockpit()
    assert cockpit["capacity"]["resolution_only"] == 1
    assert cockpit["coverage"]["active_without_schedule"] == 0
    assert cockpit["coverage"]["resolution_only_without_schedule"] == 0
    assert cockpit["coverage"]["service_mode_coverage_gaps"] == 0
    settlement = next(
        row for row in result["scheduled_reviews"]
        if row["trigger_reason"] == "resolution_only"
    )
    assert settlement["enabled"] == 1
    assert settlement["auto_score"] == 1
    assert settlement["auto_postmortem"] == 1


def test_active_book_classification_makes_maintenance_coverage_explicit(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    serviced = ledger.create_question(
        title="Will the serviced question keep a schedule?",
        resolution_criteria="Resolves yes if it remains actively serviced.",
        domain="forecastbench",
    )
    monitored = ledger.create_question(
        title="Will the monitored question keep its source only?",
        resolution_criteria="Resolves yes if it is classified monitor-only.",
        domain="forecastbench",
    )
    settlement = ledger.create_question(
        title="Will the dormant question be retained only for settlement?",
        resolution_criteria="Resolves yes if it is classified resolution-only.",
        domain="forecastbench",
    )
    ledger.schedule_review(
        scope_type="question", scope_ref=serviced.id, cadence="daily"
    )
    ledger.add_watched_source(
        scope_type="question",
        scope_ref=monitored.id,
        source="monitor feed",
        source_type="manual",
    )

    preview = ledger.classify_active_question_service_modes()
    assert preview["counts"] == {
        "actively_serviced": 1,
        "monitor_only": 1,
        "resolution_only": 1,
    }
    assert all(not (ledger.get_question(row["question_id"]).metadata or {}).get("service_mode") for row in preview["rows"])

    applied = ledger.classify_active_question_service_modes(dry_run=False)
    assert applied["classified"] == 3
    assert ledger.get_question(serviced.id).metadata["service_mode"] == "actively_serviced"
    assert ledger.get_question(monitored.id).metadata["service_mode"] == "monitor_only"
    assert ledger.get_question(settlement.id).metadata["service_mode"] == "resolution_only"
    cockpit = ledger.operational_cockpit()
    assert cockpit["coverage"]["unclassified_active"] == 0
    assert cockpit["coverage"]["actively_serviced_without_schedule"] == 0


def test_resolution_only_schedule_checks_settlement_without_staleness_noise(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will settlement-only service stay lightweight?",
        resolution_criteria="Resolves yes if only the resolution deadline is checked.",
        resolution_time="2026-05-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Old baseline intentionally lacking evidence.",
        as_of="2026-01-01T00:00:00Z",
    )
    ledger.set_question_service_mode(question.id, "resolution_only")

    runs = ledger.run_due_scheduled_reviews(now="2030-05-02T00:00:00Z")

    run = next(
        row for row in runs
        if row["review"]["trigger_reason"] == "resolution_only"
    )
    reasons = {alert.reason for alert in run["alerts"]}
    assert "resolution_check_due" in reasons
    assert "no_evidence" not in reasons
    assert not any(reason.startswith("last_update_") for reason in reasons)


def test_high_severity_alerts_get_urgent_sla_tasks_oldest_first(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    older = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref="fq_missing_old",
        reason="high_priority_old",
        recommended_action="Escalate oldest first.",
        now="2026-05-01T00:00:00Z",
    )
    newer = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref="fq_missing_new",
        reason="high_priority_new",
        recommended_action="Escalate after the older alert.",
        now="2026-05-01T00:30:00Z",
    )

    tasks = ledger.list_operational_tasks(lane="urgent_forecast")
    assert {task["alert_id"] for task in tasks} == {older.id, newer.id}
    claimed = ledger.claim_operational_tasks(
        owner="urgent-worker",
        lane="urgent_forecast",
        now="2026-05-01T02:00:00Z",
        limit=1,
    )
    assert claimed[0]["alert_id"] == older.id
    escalation = ledger.escalate_overdue_high_severity_tasks(
        now="2026-05-01T02:00:00Z"
    )
    assert escalation["escalated_count"] == 1
    escalated_task = next(
        task for task in ledger.list_operational_tasks(lane="urgent_forecast")
        if task["alert_id"] == newer.id
    )
    assert escalated_task["escalation_owner"] == "human:forecast-duty"
    assert escalated_task["disposition"] == "human_escalation_required"
    assert escalated_task["status"] == "awaiting_human"
    cockpit = ledger.operational_cockpit(now="2026-05-01T02:00:00Z")
    assert cockpit["high_severity"]["open"] == 2
    assert cockpit["high_severity"]["slo_breaches"] == 2
    assert cockpit["high_severity"]["oldest_first"] is True
    assert cockpit["high_severity"]["human_escalation"] == 1
    assert cockpit["high_severity"]["assigned_owner_count"] == 1
    assert cockpit["high_severity"]["awaiting_execution"] == 0
    assert cockpit["high_severity"]["awaiting_human"] == 1
    assert cockpit["high_severity"]["unclaimed"] == 0


def test_expired_human_escalation_lease_is_not_reclaimed_by_worker(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    alert = ledger.create_alert(
        severity="high",
        scope_type="global",
        scope_ref="lease-fixture",
        reason="human_lease_fixture",
        recommended_action="Review manually.",
        now="2026-05-01T00:00:00Z",
    )
    task = next(row for row in ledger.list_operational_tasks() if row["alert_id"] == alert.id)
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE operational_tasks
            SET status='leased', disposition='human_escalation_required',
                escalation_owner='human:forecast-duty', escalated_at='2026-05-01T00:30:00Z',
                lease_owner='stale-worker', lease_expires_at='2026-05-01T00:45:00Z'
            WHERE id=?
            """,
            (task["id"],),
        )

    reclaimed = ledger.reclaim_expired_operational_tasks(now="2026-05-01T01:00:00Z")
    updated = next(row for row in ledger.list_operational_tasks() if row["id"] == task["id"])

    assert reclaimed["awaiting_human"] == 1
    assert updated["status"] == "awaiting_human"
    assert ledger.claim_operational_tasks(
        owner="urgent-worker", lane="urgent_forecast", now="2026-05-01T01:00:00Z"
    ) == []


def test_human_inbox_supports_defer_reforecast_and_terminal_resolution(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    alert = ledger.create_alert(
        severity="high",
        scope_type="global",
        scope_ref="human-actions",
        reason="human_action_fixture",
        recommended_action="Review manually.",
        now="2026-05-01T00:00:00Z",
    )
    ledger.escalate_overdue_high_severity_tasks(now="2026-05-01T02:00:00Z")
    task = next(row for row in ledger.list_operational_tasks() if row["alert_id"] == alert.id)

    deferred = ledger.act_on_human_task(
        task["id"], action="defer", defer_hours=2, now="2026-05-01T02:00:00Z"
    )
    assert deferred["status"] == "awaiting_human"
    assert deferred["available_at"] == "2026-05-01T04:00:00Z"
    reforecast = ledger.act_on_human_task(
        task["id"], action="reforecast", now="2026-05-01T04:00:00Z"
    )
    assert reforecast["status"] == "pending"
    assert reforecast["lane"] == "urgent_forecast"
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE operational_tasks SET status='awaiting_human' WHERE id=?",
            (task["id"],),
        )
    resolved = ledger.act_on_human_task(
        task["id"], action="resolve", note="operator reviewed", now="2026-05-01T04:01:00Z"
    )
    assert resolved["status"] == "completed"
    assert ledger.get_alert(alert.id).acknowledged_at == "2026-05-01T04:01:00Z"


def test_closing_alert_completes_its_unclaimed_operational_task(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    alert = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref="fq_missing",
        reason="manual_review_complete",
        recommended_action="Review and close.",
    )
    task = next(
        row for row in ledger.list_operational_tasks(lane="urgent_forecast")
        if row["alert_id"] == alert.id
    )

    ledger.acknowledge_alert(
        alert.id,
        ack_note="reviewed with durable evidence",
        disposition="reviewed_no_change",
    )

    closed_task = next(
        row for row in ledger.list_operational_tasks(lane="urgent_forecast")
        if row["id"] == task["id"]
    )
    assert closed_task["status"] == "completed"
    assert closed_task["disposition"] == "alert_closed_elsewhere"


def test_closing_source_alert_reconciles_event_and_task_together(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will alert closure preserve source lifecycle consistency?",
        resolution_criteria="Resolves yes if the linked event and task close together.",
    )
    ledger.create_snapshot(
        question_id=question.id, probability_or_distribution=0.5, rationale="Baseline."
    )
    source = tmp_path / "linked.txt"
    source.write_text("before", encoding="utf-8")
    ledger.add_watched_source(
        scope_type="question", scope_ref=question.id, source=str(source)
    )
    source.write_text("after", encoding="utf-8")
    alert = ledger.check_watched_sources(
        scope_type="question", scope_ref=question.id
    )[0]

    ledger.acknowledge_alert(
        alert.id, disposition="reviewed_no_change", ack_note="human reviewed"
    )

    event = ledger.list_source_change_events(question_id=question.id)[0]
    task = next(
        row for row in ledger.list_operational_tasks()
        if row["source_change_event_id"] == event["id"]
    )
    assert event["status"] == "processed"
    assert event["state"] == "reconciled"
    assert event["disposition"] == "alert_closed_elsewhere"
    assert task["status"] == "completed"
    assert task["disposition"] == "alert_closed_elsewhere"
    assert ledger.list_source_change_event_transitions(event["id"])[-1]["to_state"] == "reconciled"
