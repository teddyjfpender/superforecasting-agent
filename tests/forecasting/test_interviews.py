"""Interview durability and uncertainty semantics, with no model/network calls."""

import pytest
from pydantic import ValidationError as ModelError

from forecasting.interviews.models import InterviewDraft
from forecasting.interviews.store import InterviewStore
from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError


def draft(**changes):
    return InterviewDraft.model_validate({
        "mode": "create",
        "title": "Will the event occur by December?",
        "questions": [
            {
                "id": "belief",
                "section": "beliefs",
                "prompt": "Your probability?",
                "rationale": "Capture an independent estimate",
                "kind": "probability",
                "required": True,
            }
        ],
        **changes,
    })


def answer(actor="user", value=0.4):
    return {
        "question_id": "belief",
        "status": "answered",
        "value": value,
        "actor": actor,
    }


@pytest.fixture
def store(tmp_path):
    return InterviewStore(ForecastLedger(tmp_path / "ledger.db"))


def save(store, document, revision=0, request="first", actor="user"):
    return store.save(
        "interview",
        document,
        expected_revision=revision,
        request_id=request,
        actor=actor,
    )


def test_revisions_resume_retry_and_stale_write(store):
    first = save(store, draft())
    second = save(store, draft(answers=[answer()]), 1, "answer")
    assert save(store, draft(), request="first") == first
    assert store.read("interview") == second
    assert store.read("interview", 1) == first
    with pytest.raises(ValidationError, match="reload"):
        save(store, draft(answers=[answer(value=0.6)]), 1, "stale")
    with pytest.raises(ValidationError, match="reused"):
        save(store, draft(answers=[answer()]), request="first")
    assert store.ledger.list_questions() == []


def test_agents_cannot_impersonate_or_overwrite_user_answers(store):
    with pytest.raises(ValidationError, match="cannot invent"):
        save(store, draft(answers=[answer()]), actor="agent")
    save(store, draft(answers=[answer()]))
    for answers in ([], [answer(value=0.9)], [answer(actor="agent")]):
        with pytest.raises(ValidationError, match="cannot invent"):
            save(store, draft(answers=answers), 1, "agent", "agent")
    revised = draft(answers=[answer()], status="needs_research")
    assert save(store, revised, 1, "agent", "agent")["revision"] == 2


def test_answered_question_meaning_cannot_silently_change(store):
    original = draft(answers=[answer()])
    save(store, original)
    revised = original.model_dump()
    revised["questions"][0]["prompt"] = "Probability of the opposite outcome?"
    with pytest.raises(ValidationError, match="change meaning"):
        save(store, InterviewDraft.model_validate(revised), 1, "rewrite")


@pytest.mark.parametrize("value", [True, "0.4", -0.1, 1.1, float("nan"), float("inf")])
def test_bad_probabilities_are_rejected(value):
    with pytest.raises(ModelError):
        draft(answers=[answer(value=value)])


def test_unknown_is_not_false_and_required_answers_block_readiness():
    with pytest.raises(ModelError):
        draft(answers=[{**answer(), "status": "unknown"}])
    with pytest.raises(ModelError, match="unanswered"):
        draft(status="ready")
    assert draft(answers=[answer()], status="ready").status == "ready"


def test_ablation_and_conditioning_are_distinct():
    assumptions = [
        {
            "id": "health",
            "statement": "Candidate remains healthy",
            "uncertainty": "mixed",
        }
    ]
    conditional = {
        "id": "healthy",
        "name": "Healthy candidate",
        "kind": "conditional",
        "conditions": {"health": True},
    }
    ablation = {
        "id": "omit",
        "name": "Omit health factor",
        "kind": "ablation",
        "excluded_assumption_ids": ["health"],
    }
    assert (
        len(draft(assumptions=assumptions, scenarios=[conditional, ablation]).scenarios)
        == 2
    )
    for invalid in (
        {**conditional, "excluded_assumption_ids": ["health"]},
        {**ablation, "conditions": {"health": False}},
        {**conditional, "conditions": {"missing": True}},
        {**conditional, "conditions": {"health": "false"}},
    ):
        with pytest.raises(ModelError):
            draft(assumptions=assumptions, scenarios=[invalid])


def test_cancelled_interviews_remain_readable_but_cannot_be_edited(store):
    saved = save(store, draft(status="cancelled"))
    with pytest.raises(ValidationError, match="cancelled"):
        save(store, draft(), 1, "resume")
    assert store.read("interview") == saved


def test_outer_transaction_rollback_removes_revision(store):
    with pytest.raises(RuntimeError):
        with store.ledger.transaction(immediate=True):
            save(store, draft())
            raise RuntimeError("interrupt")
    with pytest.raises(ValidationError, match="not found"):
        store.read("interview")


def test_application_answers_adapt_resume_and_commit_once(store):
    from forecasting.interviews.service import InterviewService

    service = InterviewService(store.ledger)
    first = service.begin("flow")
    assert service.begin("flow") == first
    from forecasting.interviews.buffers import read_buffers, save_buffer
    from protocol.rpc.interviews import InterviewBufferSaveRequest

    save_buffer(store.ledger, InterviewBufferSaveRequest.model_validate({
        "interview_id": "flow", "question_id": "title", "base_revision": 1,
        "expected_buffer_revision": 0, "request_id": "draft-text",
        "buffer": {"text": "Unconfirmed scratch text"},
    }))
    record = first
    values = {
        "title": "Will June 2030 CPI exceed 3 percent?",
        "outcome": "binary",
        "criteria": "Resolves yes if the BLS June 2030 CPI YoY first release exceeds 3.0 percent.",
        "source": "https://www.bls.gov/cpi/",
        "deadline": "2030-07-15T00:00:00Z",
        "drivers": "Energy prices rise\nShelter inflation stays high",
        "belief": 0.4,
    }
    for key, value in values.items():
        record = service.answer(
            "flow",
            expected_revision=record["revision"],
            request_id=key,
            question_id=key,
            status="answered",
            value=value,
        )
    assert len(record["document"]["assumptions"]) == 2
    assert service.preview("flow", record["revision"])["committable"]
    assert len(store.list_latest()) == 1
    result = service.commit("flow", record["revision"])
    assert service.commit("flow", record["revision"]) == result
    assert read_buffers(store.ledger, "flow") == {"buffers": []}
    with store.ledger._connect() as conn:
        assert conn.execute("SELECT document FROM forecast_interview_buffers WHERE interview_id='flow'").fetchone()[0] is None
    assert store.list_latest() == []
    assert len(store.ledger.list_questions()) == 1
    created = store.ledger.get_question(result["question_id"])
    provenance = created.metadata["onboarding"]["clarifications"][-1]
    assert provenance["interview_id"] == "flow"
    assert provenance["revision"] == record["revision"]
    assert provenance["verification_status"] == "interview_context_not_settlement_verification"
    assert store.ledger.list_snapshots(result["question_id"]) == []
    review = service.begin("review", question_id=result["question_id"])
    assert review["document"]["mode"] == "update"
    assert review["document"]["assumptions"] == record["document"]["assumptions"]
    assert review["document"]["parent_interview"] == {
        key: record[key] for key in ("interview_id", "revision", "digest")
    }
    assert review["document"]["questions"][0]["id"] == "new_evidence"
    assert all(answer["actor"] == "agent" for answer in review["document"]["answers"])


def test_numeric_branch_and_cross_quantile_validation(store):
    from forecasting.interviews.service import InterviewService

    service = InterviewService(store.ledger)
    service.begin("numeric")
    record = service.answer(
        "numeric",
        expected_revision=1,
        request_id="outcome",
        question_id="outcome",
        status="answered",
        value="numeric",
    )
    assert "units" in {q["id"] for q in record["document"]["questions"]}
    assert "belief" not in {q["id"] for q in record["document"]["questions"]}
    for key, value in [("quantile_10", 10.0), ("quantile_50", 5.0)]:
        record = service.answer(
            "numeric",
            expected_revision=record["revision"],
            request_id=key,
            question_id=key,
            status="answered",
            value=value,
        )
    assert any(
        "Quantiles" in message
        for message in service.preview("numeric", record["revision"])["unanswered"]
    )


def test_answer_retry_does_not_overwrite_newer_answers(store):
    from forecasting.interviews.service import InterviewService

    service = InterviewService(store.ledger)
    service.begin("retry")
    args = dict(
        expected_revision=1,
        request_id="probability",
        question_id="belief",
        status="answered",
        value=0.3,
    )
    saved = service.answer("retry", **args)
    newer = service.answer(
        "retry",
        expected_revision=2,
        request_id="revision",
        question_id="belief",
        status="answered",
        value=0.4,
    )
    assert service.answer("retry", **args) == saved
    assert store.read("retry") == newer


def test_categorical_questions_require_coherent_probability_vector(store):
    from forecasting.interviews.service import InterviewService

    service = InterviewService(store.ledger)
    service.begin("categories")
    record = service.answer(
        "categories",
        expected_revision=1,
        request_id="outcome",
        question_id="outcome",
        status="answered",
        value="categorical",
    )
    record = service.answer(
        "categories",
        expected_revision=record["revision"],
        request_id="labels",
        question_id="categories",
        status="answered",
        value="Red\nBlue\nOther",
    )
    probabilities = [
        q
        for q in record["document"]["questions"]
        if q["id"].startswith("category_prob_")
    ]
    assert len(probabilities) == 3
    for question in probabilities:
        record = service.answer(
            "categories",
            expected_revision=record["revision"],
            request_id=question["id"],
            question_id=question["id"],
            status="answered",
            value=0.5,
        )
    assert (
        "Category probabilities must sum to 1."
        in service.preview("categories", record["revision"])["unanswered"]
    )


def test_choice_custom_answers_are_explicit_and_unknown_stays_empty(store):
    from forecasting.interviews.service import InterviewService
    base = draft().model_dump()
    base["questions"] = [{"id": "drivers", "section": "drivers", "prompt": "Which factors?",
                           "rationale": "Choose relevant mechanisms", "kind": "multiple",
                           "choices": [{"id": "health", "label": "Health"}], "allow_custom": True}]
    save(store, InterviewDraft.model_validate(base))
    service = InterviewService(store.ledger)
    custom = service.answer("interview", expected_revision=1, request_id="custom", question_id="drivers",
                            status="answered", value=["health"], custom_text="Supreme Court composition")
    assert custom["document"]["answers"][0]["custom_text"] == "Supreme Court composition"
    assert custom["document"]["answers"][0]["value"] == ["health"]
    with pytest.raises(ModelError, match="unknown/skipped"):
        service.answer("interview", expected_revision=2, request_id="bad", question_id="drivers",
                       status="unknown", custom_text="Must not hide an answer")
    with pytest.raises(ModelError, match="unknown choice"):
        service.answer("interview", expected_revision=2, request_id="bad-choice", question_id="drivers",
                       status="answered", value=["unregistered"])
    assert store.read("interview")["revision"] == 2


def test_scenario_operations_preserve_semantics_and_retry_identity(store):
    from forecasting.interviews.service import InterviewService
    document = draft(assumptions=[{"id": "health", "statement": "Candidate remains healthy"}])
    save(store, document)
    service = InterviewService(store.ledger)
    scenario = {"id": "illness", "name": "Health condition fails", "kind": "conditional", "conditions": {"health": False}}
    first = service.save_scenario("interview", expected_revision=1, request_id="condition", scenario=scenario)
    assert service.save_scenario("interview", expected_revision=1, request_id="condition", scenario=scenario) == first
    assert first["document"]["scenarios"][0]["conditions"] == {"health": False}
    ablation = {"id": "omit", "name": "Exclude health", "kind": "ablation", "excluded_assumption_ids": ["health"]}
    second = service.save_scenario("interview", expected_revision=2, request_id="exclude", scenario=ablation)
    assert second["document"]["scenarios"][1]["conditions"] == {}
    with pytest.raises(ModelError, match="unknown assumption"):
        service.save_scenario("interview", expected_revision=3, request_id="invalid",
                              scenario={**ablation, "excluded_assumption_ids": ["invented"]})
    deleted = service.delete_scenario("interview", expected_revision=3, request_id="delete", scenario_id="omit")
    assert service.delete_scenario("interview", expected_revision=3, request_id="delete", scenario_id="omit") == deleted
    assert len(deleted["document"]["scenarios"]) == 1
    assert service.ledger.list_questions() == []


def test_agent_scenarios_cannot_overwrite_user_selections(store):
    from forecasting.interviews.service import InterviewService
    save(store, draft(assumptions=[{"id": "health", "statement": "Candidate stays healthy"}]))
    service = InterviewService(store.ledger)
    scenario = {"id": "condition", "name": "Healthy", "kind": "conditional", "conditions": {"health": True}, "actor": "agent"}
    user = service.save_scenario("interview", expected_revision=1, request_id="user", scenario=scenario)
    assert user["document"]["scenarios"][0]["actor"] == "user"
    with pytest.raises(ValidationError, match="user scenarios"):
        service.save_scenario("interview", expected_revision=2, request_id="agent", scenario={**scenario, "conditions": {"health": False}}, actor="agent")
    with pytest.raises(ValidationError, match="user scenarios"):
        service.delete_scenario("interview", expected_revision=2, request_id="delete", scenario_id="condition", actor="agent")
    proposed = service.save_scenario("interview", expected_revision=2, request_id="proposal", scenario={**scenario, "id": "new"}, actor="agent")
    assert proposed["document"]["scenarios"][-1]["actor"] == "agent"


def test_assumption_edit_is_attributed_idempotent_and_preserves_history(store):
    from forecasting.interviews.service import InterviewService
    save(store, draft(assumptions=[{"id": "health", "statement": "Candidate stays healthy"}]))
    service = InterviewService(store.ledger)
    assumption = {"id": "health", "statement": "Candidate stays healthy", "probability": 0.65,
                  "uncertainty": "mixed", "rationale": "Health record incomplete", "actor": "agent"}
    result = service.save_assumption("interview", expected_revision=1, request_id="edit", assumption=assumption)
    assert result == service.save_assumption("interview", expected_revision=1, request_id="edit", assumption=assumption)
    assert result["document"]["assumptions"][0]["actor"] == "user"
    assert result["document"]["assumptions"][0]["probability"] == 0.65
    assert store.read("interview", 1)["document"]["assumptions"][0]["probability"] is None
    with pytest.raises(ValidationError, match="user assumptions"):
        service.save_assumption("interview", expected_revision=2, request_id="overwrite", assumption={**assumption, "probability": 0.8}, actor="agent")
    with pytest.raises(ValidationError, match="outside the frozen interview"):
        service.save_assumption("interview", expected_revision=2, request_id="bad-evidence", assumption={**assumption, "evidence_refs": ["invented"]})
    with pytest.raises(ModelError):
        service.save_assumption("interview", expected_revision=2, request_id="bad-p", assumption={**assumption, "probability": 65.0})
    assert store.read("interview")["revision"] == 2


def test_unknown_state_survives_later_answers(store):
    from forecasting.interviews.service import InterviewService

    service = InterviewService(store.ledger)
    record = service.begin("uncertain")
    for key, status, actor, value, expected in [
        ("base_rate", "unknown", "agent", None, "needs_research"),
        ("drivers", "answered", "agent", "Demand remains stable", "needs_research"),
        ("belief", "unknown", "user", None, "needs_user"),
        ("counterevidence", "answered", "user", "Demand may fall", "needs_user"),
        ("belief", "answered", "user", 0.5, "needs_research"),
    ]:
        record = service.answer(
            "uncertain",
            expected_revision=record["revision"],
            request_id=str(record["revision"]),
            question_id=key,
            status=status,
            actor=actor,
            value=value,
        )
        assert record["document"]["status"] == expected
    record = service.save_assumption(
        "uncertain", expected_revision=record["revision"], request_id="edit-assumption",
        assumption={"id": "new", "statement": "A new proposed factor"},
    )
    assert record["document"]["status"] == "needs_research"


@pytest.mark.parametrize("owner", ["answers", "assumptions"])
def test_direct_draft_writes_reject_invented_citations(store, owner):
    entries = (
        [dict(answer(), evidence_refs=["invented"])]
        if owner == "answers"
        else [{"id": "a", "statement": "A claim", "evidence_refs": ["invented"]}]
    )
    with pytest.raises(ModelError, match="outside the interview"):
        save(store, draft(**{owner: entries}))
    assert store.list_latest() == []


@pytest.mark.parametrize(
    "outcome,phrase",
    [
        ("numeric", "distribution"),
        ("categorical", "each category"),
        ("binary", "succeeded"),
    ],
)
def test_outside_view_matches_outcome_space(outcome, phrase):
    from forecasting.interviews.questions import core_questions

    questions = core_questions(outcome)
    assert phrase in next(q.prompt for q in questions if q.id == "base_rate")
    belief_id = {
        "numeric": "quantile_10",
        "categorical": "categories",
        "binary": "belief",
    }[outcome]
    assert next(i for i, q in enumerate(questions) if q.id == belief_id) < next(
        i for i, q in enumerate(questions) if q.id == "base_rate"
    )


def test_reconfirm_outcome_preserves_frozen_question_wording(store):
    from forecasting.interviews.questions import core_questions
    from forecasting.interviews.service import InterviewService
    from protocol.interviews import InterviewAnswer

    document = draft(
        questions=core_questions(),
        answers=[
            InterviewAnswer(
                question_id="outcome", status="answered", value="binary", actor="user"
            )
        ],
    )
    document.questions[0].prompt = "Historical title wording"
    save(store, document)
    record = InterviewService(store.ledger).answer(
        "interview",
        expected_revision=1,
        request_id="reconfirm",
        question_id="outcome",
        status="answered",
        value="binary",
    )
    assert record["document"]["questions"][0]["prompt"] == "Historical title wording"


def test_review_feedback_is_nonblocking_and_shared(store):
    import json

    from forecasting.interviews.generation import build_messages
    from forecasting.interviews.service import InterviewService
    from protocol.interviews import InterviewGenerationOptions

    service = InterviewService(store.ledger)
    record = service.begin("review-feedback")
    for key, value in [
        ("title", "Will the event occur?"),
        ("criteria", "Official confirmation by December 2030"),
        ("source", "Official registry"),
        ("deadline", "2030-12-01T00:00:00Z"),
        ("outcome", "binary"),
        ("belief", 1.0),
        ("base_rate", "One of two comparable cases"),
    ]:
        record = service.answer(
            "review-feedback",
            expected_revision=record["revision"],
            request_id=key,
            question_id=key,
            status="answered",
            value=value,
        )
    preview = service.preview("review-feedback", record["revision"])
    assert preview["committable"]
    packet = json.loads(
        build_messages(store.ledger, record, InterviewGenerationOptions())[1]["content"]
    )
    assert all(finding in preview["issues"] for finding in packet["elicitation_gaps"])
    assert any(f["field"] == "belief" for f in packet["elicitation_gaps"])
    assert any(
        f["field"] == "base_rate" and f["severity"] == "info"
        for f in packet["elicitation_gaps"]
    )
    assert store.ledger.list_questions() == []


def test_editing_answer_preserves_citations_unless_explicitly_replaced(store):
    from forecasting.interviews.service import InterviewService

    save(store, draft(evidence_refs=["source"], answers=[{**answer(), "evidence_refs": ["source"]}]))
    service = InterviewService(store.ledger)
    record = service.answer("interview", expected_revision=1, request_id="edit-note", question_id="belief", status="answered", value=0.5, note="Source may be revised")
    assert record["document"]["answers"][0]["evidence_refs"] == ["source"]
    assert record["document"]["answers"][0]["note"] == "Source may be revised"
    record = service.answer("interview", expected_revision=2, request_id="remove-ref", question_id="belief", status="unknown", evidence_refs=[])
    assert record["document"]["answers"][0]["evidence_refs"] == []


@pytest.mark.parametrize("link", ["scenario", "answered_question"])
def test_linked_assumptions_cannot_silently_change_meaning(store, link):
    from forecasting.interviews.service import InterviewService

    document = draft(assumptions=[{"id": "health", "statement": "Candidate stays healthy"}])
    if link == "scenario":
        from protocol.interviews import InterviewScenario
        document.scenarios = [InterviewScenario(id="healthy", name="Healthy", kind="conditional", conditions={"health": True}, actor="user")]
    else:
        document.questions[0].assumption_ids = ["health"]
        from protocol.interviews import InterviewAnswer
        document.answers = [InterviewAnswer.model_validate(answer())]
    save(store, document)
    service = InterviewService(store.ledger)
    with pytest.raises(ValidationError, match="linked assumptions cannot change meaning"):
        service.save_assumption("interview", expected_revision=1, request_id="rewrite", assumption={"id": "health", "statement": "Candidate withdraws"})
    assert store.read("interview")["revision"] == 1
    result = service.save_assumption("interview", expected_revision=1, request_id="belief", assumption={"id": "health", "statement": "Candidate stays healthy", "probability": 0.6})
    assert result["document"]["assumptions"][0]["probability"] == 0.6
