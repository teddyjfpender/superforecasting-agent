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
    assert store.list_latest() == []
    assert len(store.ledger.list_questions()) == 1
    assert store.ledger.list_snapshots(result["question_id"]) == []
    review = service.begin("review", question_id=result["question_id"])
    assert review["document"]["mode"] == "update"
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
