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
