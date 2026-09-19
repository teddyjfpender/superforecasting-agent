"""Update interviews retain their exact ledger baseline across edits and retries."""

import json

import pytest

from forecasting.interviews.context import read_context
from forecasting.interviews.generation import build_messages
from forecasting.interviews.service import InterviewService
from forecasting.ledger import ForecastLedger, allow_ledger_writes
from forecasting.models import ValidationError
from protocol.interviews import InterviewDraft, InterviewGenerationOptions


@pytest.fixture
def desk(tmp_path):
    ledger = ForecastLedger(tmp_path / "desk.db")
    with allow_ledger_writes(reason="fixture"):
        question = ledger.create_question(
            title="Will the event occur?",
            resolution_criteria="Official confirmation by December 2030.",
        )
        snapshot = ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.3,
            rationale="Initial reasoning",
            forecast_origin="exploratory",
        )
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="Initial report",
        claim="Original claim",
        summary="Original summary",
        archive_url_snapshot=False,
        metadata={"independence_key": "publisher", "verification_status": "unverified"},
    )
    return ledger, question, snapshot, evidence


def test_generation_uses_frozen_context_after_live_changes(desk, monkeypatch):
    ledger, question, snapshot, evidence = desk
    service = InterviewService(ledger)
    record = service.begin("update", question_id=question.id)
    original = build_messages(ledger, record, InterviewGenerationOptions())
    with allow_ledger_writes(reason="fixture"):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.8,
            rationale="Later reasoning",
            forecast_origin="exploratory",
        )
    ledger.add_evidence(
        question_id=question.id,
        source_or_note="Later report",
        claim="Later claim",
        archive_url_snapshot=False,
    )
    assert service.begin("update", question_id=question.id) == record

    def no_live_reads(*args, **kwargs):
        raise AssertionError("generation must not read mutable ledger inputs")

    for name in ("get_question", "get_snapshot", "get_evidence", "list_evidence"):
        monkeypatch.setattr(ledger, name, no_live_reads)
    assert build_messages(ledger, record, InterviewGenerationOptions()) == original
    packet = json.loads(original[1]["content"])
    assert packet["frozen_baseline"]["forecast_id"] == snapshot.forecast_id
    assert packet["frozen_baseline"]["rationale"] == "Initial reasoning"
    assert [item["id"] for item in packet["evidence"]] == [evidence.id]
    assert packet["evidence"][0]["metadata"]["independence_key"] == "publisher"


def test_context_cannot_be_replaced_or_extended_in_place(desk):
    ledger, question, _, _ = desk
    service = InterviewService(ledger)
    record = service.begin("update", question_id=question.id)
    draft = InterviewDraft.model_validate(record["document"])
    draft.context_digest = "0" * 64
    with pytest.raises(ValidationError, match="immutable"):
        service.store.save(
            "update", draft, expected_revision=1, request_id="replace", actor="user"
        )
    draft = InterviewDraft.model_validate(record["document"])
    draft.evidence_refs.append("new-evidence")
    with pytest.raises(ValidationError, match="new frozen interview"):
        service.store.save(
            "update", draft, expected_revision=1, request_id="extend", actor="user"
        )


def test_capture_rolls_back_with_failed_begin(desk, monkeypatch):
    ledger, question, _, _ = desk
    service = InterviewService(ledger)

    def fail(*args, **kwargs):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(service.store, "save", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        service.begin("update", question_id=question.id)
    with ledger._connect() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM forecast_interview_contexts").fetchone()[
                0
            ]
            == 0
        )


def test_corrupt_context_fails_closed(desk):
    ledger, question, _, _ = desk
    record = InterviewService(ledger).begin("update", question_id=question.id)
    with ledger.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE forecast_interview_contexts SET document = '{}' WHERE interview_id = 'update'"
        )
    with pytest.raises(ValidationError, match="corrupt"):
        read_context(ledger, "update", record["document"]["context_digest"])


def test_updates_inherit_attributed_assumptions_without_reanswering(desk):
    from protocol.interviews import InterviewScenario

    ledger, question, _, _ = desk
    service = InterviewService(ledger)
    first = service.begin("first", question_id=question.id)
    first = service.answer(
        "first",
        expected_revision=first["revision"],
        request_id="drivers",
        question_id="drivers",
        status="answered",
        value="Candidate stays healthy",
    )
    assumption = first["document"]["assumptions"][0]
    first = service.save_scenario(
        "first",
        expected_revision=first["revision"],
        request_id="scenario",
        scenario=InterviewScenario(
            id="health",
            name="Healthy candidate",
            kind="conditional",
            conditions={assumption["id"]: True},
        ),
    )
    second = service.begin("second", question_id=question.id)
    doc = second["document"]
    assert doc["parent_interview"] == {
        key: first[key] for key in ("interview_id", "revision", "digest")
    }
    assert doc["assumptions"] == first["document"]["assumptions"]
    assert doc["scenarios"] == first["document"]["scenarios"]
    assert not any(answer["actor"] == "user" for answer in doc["answers"])
    packet = json.loads(
        build_messages(ledger, second, InterviewGenerationOptions())[1]["content"]
    )
    assert (
        packet["prior_interview"]["document"]["answers"] == first["document"]["answers"]
    )
    # An agent may carry inherited user content, but cannot change it afterwards.
    draft = InterviewDraft.model_validate(doc)
    draft.assumptions[0].statement = "Fabricated replacement"
    with pytest.raises(ValidationError, match="user assumptions"):
        service.store.save(
            "second", draft, expected_revision=1, request_id="tamper", actor="agent"
        )
    # Editing the first interview cannot rewrite the second interview's history.
    service.answer(
        "first",
        expected_revision=first["revision"],
        request_id="later-belief",
        question_id="belief",
        status="answered",
        value=0.7,
    )
    again = json.loads(
        build_messages(ledger, second, InterviewGenerationOptions())[1]["content"]
    )
    assert again["prior_interview"] == packet["prior_interview"]


def test_cancelled_prior_interviews_are_not_inherited(desk):
    ledger, question, _, _ = desk
    service = InterviewService(ledger)
    first = service.begin("first", question_id=question.id)
    draft = InterviewDraft.model_validate(first["document"])
    draft.status = "cancelled"
    service.store.save(
        "first", draft, expected_revision=1, request_id="cancel", actor="user"
    )
    assert (
        service.begin("second", question_id=question.id)["document"]["parent_interview"]
        is None
    )


def test_parent_reference_is_not_caller_selectable(desk):
    from protocol.interviews import InterviewParent

    ledger, question, _, _ = desk
    service = InterviewService(ledger)
    first = service.begin("first", question_id=question.id)
    draft = InterviewDraft.model_validate(first["document"])
    draft.parent_interview = InterviewParent(
        interview_id="unrelated", revision=1, digest="0" * 64
    )
    with pytest.raises(ValidationError, match="immutable"):
        service.store.save(
            "first", draft, expected_revision=1, request_id="forge", actor="user"
        )
