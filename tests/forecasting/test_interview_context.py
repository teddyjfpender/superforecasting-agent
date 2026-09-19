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


def test_lesson_selection_is_frozen_explainable_and_advisory(desk):
    ledger, question, _, _ = desk
    original = ledger.create_calibration_lesson(
        scope_type="global",
        scope_ref=None,
        lesson="Check the reference class.",
        status="active",
    )
    replacement = ledger.create_calibration_lesson(
        scope_type="global",
        scope_ref=None,
        lesson="Check independent reference classes.",
        status="active",
        supersedes_lesson_id=original["id"],
    )
    conditional = ledger.create_calibration_lesson(
        scope_type="global",
        scope_ref=None,
        lesson="Weather-only guidance.",
        status="active",
        recommended_adjustment={"applicability": {"topics_any": ["weather"]}},
    )
    record = InterviewService(ledger).begin("update", question_id=question.id)
    before = build_messages(ledger, record, InterviewGenerationOptions())
    packet = json.loads(before[1]["content"])
    selection = packet["lesson_selection"]
    assert [item["lesson_id"] for item in selection["records"]] == [replacement["id"]]
    item = selection["records"][0]
    assert item["advisory_only"] and item["support_score_count"] == 0
    assert item["independent_cluster_count"] is None
    assert len(item["content_digest"]) == 64
    exclusions = {item["lesson_id"]: item["reason"] for item in selection["exclusions"]}
    assert exclusions[original["id"]] == "superseded_in_scope"
    assert exclusions[conditional["id"]] == "topic_mismatch"
    ledger.update_calibration_lesson(replacement["id"], confidence=0.9)
    assert build_messages(ledger, record, InterviewGenerationOptions()) == before


def test_future_lesson_cannot_suppress_prior_guidance_or_leak_into_prompt(desk):
    ledger, question, _, _ = desk
    prior = ledger.create_calibration_lesson(
        scope_type="global",
        scope_ref=None,
        lesson="Available guidance",
        status="active",
    )
    future = ledger.create_calibration_lesson(
        scope_type="global",
        scope_ref=None,
        lesson="Future outcome secret",
        status="active",
        supersedes_lesson_id=prior["id"],
    )
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE calibration_lessons SET updated_at=? WHERE id=?",
            ("2999-01-01T00:00:00Z", future["id"]),
        )
    record = InterviewService(ledger).begin("update", question_id=question.id)
    messages = build_messages(ledger, record, InterviewGenerationOptions())
    selection = json.loads(messages[1]["content"])["lesson_selection"]
    assert [item["lesson_id"] for item in selection["records"]] == [prior["id"]]
    assert selection["exclusions"] == [
        {"lesson_id": future["id"], "reason": "post_cutoff_lesson_revision"}
    ]
    assert "Future outcome secret" not in messages[1]["content"]


def test_legacy_context_is_read_without_live_lesson_backfill(desk):
    import hashlib

    ledger, question, _, _ = desk
    record = InterviewService(ledger).begin("update", question_id=question.id)
    digest = record["document"]["context_digest"]
    context = read_context(ledger, record["interview_id"], digest)
    context.pop("lesson_selection")
    context["schema_version"] = 1
    document = json.dumps(
        context, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    legacy_digest = hashlib.sha256(document.encode()).hexdigest()
    # Construct an actual historical v1 context; ordinary application writes cannot replace it.
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE forecast_interview_contexts SET document=?,digest=? WHERE interview_id=?",
            (document, legacy_digest, record["interview_id"]),
        )
    record["document"]["context_digest"] = legacy_digest
    ledger.create_calibration_lesson(
        scope_type="global", scope_ref=None, lesson="New guidance", status="active"
    )
    packet = json.loads(
        build_messages(ledger, record, InterviewGenerationOptions())[1]["content"]
    )
    assert "lesson_selection" not in packet
    assert read_context(ledger, record["interview_id"], legacy_digest) == context


def test_missing_score_support_is_excluded_not_invented(desk):
    ledger, question, _, _ = desk
    lesson = ledger.create_calibration_lesson(
        scope_type="global",
        scope_ref=None,
        lesson="Unsupported learned correction",
        status="active",
        source_score_record_refs=["missing-score"],
    )
    record = InterviewService(ledger).begin("update", question_id=question.id)
    selection = json.loads(
        build_messages(ledger, record, InterviewGenerationOptions())[1]["content"]
    )["lesson_selection"]
    assert selection["records"] == []
    assert selection["exclusions"] == [
        {"lesson_id": lesson["id"], "reason": "missing_source_score"}
    ]


def test_missing_postmortem_support_is_not_used_as_guidance(desk):
    ledger, question, _, _ = desk
    lesson = ledger.create_calibration_lesson(
        scope_type="global",
        scope_ref=None,
        lesson="Unsupported postmortem correction",
        status="active",
        source_postmortem_refs=["missing-postmortem"],
    )
    record = InterviewService(ledger).begin("update", question_id=question.id)
    selection = json.loads(
        build_messages(ledger, record, InterviewGenerationOptions())[1]["content"]
    )["lesson_selection"]
    assert selection["records"] == []
    assert selection["exclusions"] == [
        {"lesson_id": lesson["id"], "reason": "missing_source_postmortem"}
    ]


def test_new_interview_freezes_general_lessons_without_inventing_question(desk):
    ledger, _, _, _ = desk
    general = ledger.create_calibration_lesson(
        scope_type="global",
        scope_ref=None,
        lesson="Ask for the reference class.",
        status="active",
    )
    conditional = ledger.create_calibration_lesson(
        scope_type="global",
        scope_ref=None,
        lesson="Binary-only guidance.",
        status="active",
        recommended_adjustment={"applicability": {"outcome_types": ["binary"]}},
    )
    ledger.create_calibration_lesson(
        scope_type="domain",
        scope_ref="weather",
        lesson="Weather-only source secret.",
        status="active",
    )
    service = InterviewService(ledger)
    record = service.begin("new-frozen", title="Will it rain?")
    context = read_context(ledger, "new-frozen", record["document"]["context_digest"])
    assert context["question"] is None and context["baseline"] is None
    before = build_messages(ledger, record, InterviewGenerationOptions())
    packet = json.loads(before[1]["content"])
    assert packet["lesson_target"]["domain"] is None
    assert [item["lesson_id"] for item in packet["lesson_selection"]["records"]] == [
        general["id"]
    ]
    assert {
        "lesson_id": conditional["id"],
        "reason": "outcome_type_mismatch",
    } in packet["lesson_selection"]["exclusions"]
    assert "Weather-only source secret" not in before[1]["content"]
    ledger.update_calibration_lesson(general["id"], confidence=0.99)
    assert build_messages(ledger, record, InterviewGenerationOptions()) == before
    assert service.begin("new-frozen", title="ignored retry") == record


def test_new_context_rolls_back_with_failed_draft_creation(desk, monkeypatch):
    ledger, _, _, _ = desk
    service = InterviewService(ledger)

    def fail(*args, **kwargs):
        raise RuntimeError("interrupted creation")

    monkeypatch.setattr(service.store, "save", fail)
    with pytest.raises(RuntimeError, match="interrupted creation"):
        service.begin("new-interrupted")
    with ledger._connect() as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM forecast_interview_contexts WHERE interview_id = ?",
                ("new-interrupted",),
            ).fetchone()
            is None
        )


def test_legacy_new_interview_does_not_gain_live_lessons(desk):
    ledger, _, _, _ = desk
    service = InterviewService(ledger)
    record = service.store.save(
        "legacy-new",
        InterviewDraft(mode="create", title="Legacy question"),
        expected_revision=0,
        request_id="legacy-create",
        actor="user",
    )
    before = build_messages(ledger, record, InterviewGenerationOptions())
    ledger.create_calibration_lesson(
        scope_type="global", scope_ref=None, lesson="Later guidance", status="active"
    )
    assert service.begin("legacy-new") == record
    assert build_messages(ledger, record, InterviewGenerationOptions()) == before
    assert "lesson_selection" not in json.loads(before[1]["content"])


def test_new_interview_context_cannot_be_replaced(desk):
    ledger, _, _, _ = desk
    service = InterviewService(ledger)
    record = service.begin("new-immutable")
    draft = InterviewDraft.model_validate(record["document"])
    draft.context_digest = None
    with pytest.raises(ValidationError, match="context is immutable"):
        service.store.save(
            "new-immutable",
            draft,
            expected_revision=1,
            request_id="replace",
            actor="user",
        )
    assert service.store.read("new-immutable") == record


def test_lesson_provenance_is_frozen_typed_and_explains_exclusions(desk):
    from protocol.rpc.interviews import InterviewLessonsResponse

    ledger, _, _, _ = desk
    included = ledger.create_calibration_lesson(
        scope_type="global",
        scope_ref=None,
        lesson="Inspect the reference class",
        status="active",
    )
    excluded = ledger.create_calibration_lesson(
        scope_type="global",
        scope_ref=None,
        lesson="Do not present rejected text",
        status="active",
        recommended_adjustment={"applicability": {"outcome_types": ["binary"]}},
    )
    service = InterviewService(ledger)
    record = service.begin("provenance")
    response = service.lessons("provenance", record["revision"])
    parsed = InterviewLessonsResponse.model_validate(response)
    assert parsed.context_digest == record["document"]["context_digest"]
    by_id = {item.lesson_id: item for item in parsed.lessons}
    assert by_id[included["id"]].guidance == "Inspect the reference class"
    assert by_id[included["id"]].independent_cluster_count is None
    assert by_id[excluded["id"]].guidance is None
    assert by_id[excluded["id"]].reason == "outcome_type_mismatch"
    ledger.update_calibration_lesson(included["id"], confidence=0.99)
    assert service.lessons("provenance", record["revision"]) == response
    with ledger.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE forecast_interview_contexts SET document='{}' WHERE interview_id='provenance'"
        )
    with pytest.raises(ValidationError, match="corrupt"):
        service.lessons("provenance")


def test_generation_and_all_scenario_calls_consult_same_frozen_lessons(desk):
    from forecasting.interviews.evaluation import prepare
    from protocol.interviews import InterviewScenario
    from protocol.scenarios import ScenarioEvaluationOptions

    ledger, question, _, _ = desk
    lesson = ledger.create_calibration_lesson(scope_type="global", scope_ref=None,
        lesson="Inspect independent reference classes.", status="active")
    service = InterviewService(ledger)
    record = service.begin("matched-lessons", question_id=question.id)
    record = service.answer("matched-lessons", expected_revision=record["revision"],
        request_id="drivers", question_id="drivers", status="answered", value="Official confirmation arrives")
    factor = record["document"]["assumptions"][0]["id"]
    record = service.save_scenario("matched-lessons", expected_revision=record["revision"],
        request_id="conditional", scenario=InterviewScenario(id="confirm", name="Confirmation", kind="conditional", conditions={factor: True}))
    packet = json.loads(build_messages(ledger, record, InterviewGenerationOptions())[1]["content"])
    expected = packet["lesson_selection"]
    assert [item["lesson_id"] for item in expected["records"]] == [lesson["id"]]
    ledger.update_calibration_lesson(lesson["id"], confidence=0.99, status="rejected")
    plan = prepare(ledger, "matched-lessons", record["revision"], ScenarioEvaluationOptions(scenario_ids=["confirm"]))
    assert len(plan["calls"]) == 2
    for call in plan["calls"]:
        actual = json.loads(call["messages"][1]["content"])
        assert actual["lesson_selection"] == expected
    assert ledger.get_current_snapshot(question.id) == desk[2]


def test_prompt_budget_rejects_without_truncating_durable_context(desk):
    ledger, question, _, _ = desk
    content = "Evidence detail. " * 15000
    ledger.add_evidence(question_id=question.id, source_or_note="Large controlled fixture",
        summary=content, archive_url_snapshot=False)
    record = InterviewService(ledger).begin("oversize", question_id=question.id)
    digest = record["document"]["context_digest"]
    before = read_context(ledger, "oversize", digest)
    assert any(item["summary"] == content for item in before["evidence"])
    with pytest.raises(ValidationError, match="exceeds the generation budget"):
        build_messages(ledger, record, InterviewGenerationOptions())
    assert read_context(ledger, "oversize", digest) == before
