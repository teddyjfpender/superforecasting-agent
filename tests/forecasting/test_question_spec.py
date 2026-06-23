"""Tests for the QuestionSpec onboarding staging object (types, validation, commit)."""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError
from forecasting.question_spec import (
    QuestionSpec,
    ReferenceClassSpec,
    UpdateTriggerSpec,
    WatchedSourceSpec,
    spec_from_dict,
    spec_to_dict,
)


def _make_ledger(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "spec.db"))
    ledger.initialize_schema()
    return ledger


def _good_spec(**overrides) -> QuestionSpec:
    base = dict(
        title="US CPI YoY for the June 2026 print",
        resolution_criteria="Resolves yes if the BLS June 2026 CPI YoY exceeds 3.0 percent.",
        decision_owner="me",
        action_threshold=">=70% act",
        update_triggers=(UpdateTriggerSpec(mechanism="CPI print", operator=">", threshold=3.0, source_ref="fred:CPIAUCSL"),),
        watched_sources=(WatchedSourceSpec(source="fred:CPIAUCSL", source_type="fred", reliability_prior=0.9, confidence_weight=2.0),),
        reference_classes=(ReferenceClassSpec(name="recent CPI prints", inclusion_criteria="monthly CPI since 2015", base_rate=0.4),),
    )
    base.update(overrides)
    return QuestionSpec(**base)


# ── validation ───────────────────────────────────────────────────────────────
def test_good_spec_has_no_errors_or_gaps():
    spec = _good_spec()
    assert spec.errors() == []
    assert spec.readiness_gaps() == []
    assert spec.is_committable() is True


@pytest.mark.parametrize(
    "overrides,bad_field",
    [
        ({"title": ""}, "title"),
        ({"title": "forecast"}, "title"),
        ({"resolution_criteria": "tbd later"}, "resolution_criteria"),
        ({"resolution_criteria": "yes"}, "resolution_criteria"),
        ({"resolution_criteria": "too short"}, "resolution_criteria"),
        ({"outcome_type": "bogus"}, "outcome_type"),
        ({"outcome_type": "binary", "choices": ("a", "b", "c")}, "choices"),
        ({"outcome_type": "numeric", "units": None}, "units"),
        ({"autonomy": "whatever"}, "autonomy"),
    ],
)
def test_validate_flags_errors(overrides, bad_field):
    spec = _good_spec(**overrides)
    errs = {e.field.split("[")[0] for e in spec.errors()}
    assert bad_field in errs


def test_validate_flags_bad_priors_and_triggers():
    spec = _good_spec(
        watched_sources=(WatchedSourceSpec(source="x", reliability_prior=1.4, confidence_weight=-1),),
        update_triggers=(UpdateTriggerSpec(mechanism="m", operator=">"),),  # no threshold
        reference_classes=(ReferenceClassSpec(name="r", inclusion_criteria="i", base_rate=2.0),),
    )
    fields = {e.field for e in spec.errors()}
    assert "watched_sources[0].reliability_prior" in fields
    assert "watched_sources[0].confidence_weight" in fields
    assert "update_triggers[0].threshold" in fields
    assert "reference_classes[0].base_rate" in fields


def test_missing_decision_card_is_a_gap_not_an_error():
    spec = _good_spec(decision_owner=None, action_threshold=None, update_triggers=())
    assert spec.errors() == []  # still committable
    gaps = {g.field for g in spec.readiness_gaps()}
    assert {"decision_owner", "action_threshold", "update_triggers"} <= gaps


def test_no_watched_sources_is_a_warn():
    spec = _good_spec(watched_sources=())
    warns = {i.field for i in spec.validate() if i.severity == "warn"}
    assert "watched_sources" in warns
    assert spec.is_committable() is True  # warn does not block


# ── transport ─────────────────────────────────────────────────────────────────
def test_dict_round_trip():
    spec = _good_spec()
    again = spec_from_dict(spec_to_dict(spec))
    assert again == spec


def test_spec_from_dict_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        spec_from_dict({"title": "x", "resolution_criteria": "y" * 30, "bogus_field": 1})


# ── commit fan-out ─────────────────────────────────────────────────────────────
def test_commit_creates_question_sources_refclass_and_metadata(tmp_path):
    ledger = _make_ledger(tmp_path)
    spec = _good_spec(panel_by_default=True, allow_evidence_gathering=False, autonomy="full")
    result = spec.commit(ledger)

    qid = result["question_id"]
    q = ledger.get_question(qid)
    assert q.title == spec.title
    # onboarding toggles persisted into question metadata
    onboarding = q.metadata["onboarding"]
    assert onboarding["panel_by_default"] is True
    assert onboarding["allow_evidence_gathering"] is False
    assert onboarding["autonomy"] == "full"

    # watched source carries the per-source priors in its metadata
    sources = ledger.list_watched_sources(scope_type="question", scope_ref=qid, status="active")
    assert len(sources) == 1
    meta = sources[0]["metadata"]
    assert meta["reliability_prior"] == 0.9
    assert meta["confidence_weight"] == 2.0

    # reference class exists (and seeds the base_rate artifact)
    refs = ledger.list_reference_classes(qid)
    assert len(refs) == 1
    assert refs[0]["name"] == "recent CPI prints"


def test_commit_auto_schedules_review_for_loop_coverage(tmp_path):
    # A lazy prompter shouldn't have to remember to schedule a review: committing a
    # serious question puts it on the cycle automatically (auto-scored + auto-
    # postmortemed), so "scheduled review runs = 0" can't happen for onboarded
    # questions. The schedule is created exactly once (idempotent), not duplicated.
    ledger = _make_ledger(tmp_path)
    result = _good_spec().commit(ledger)
    review = result["scheduled_review"]
    assert review is not None
    assert review["auto_score"] == 1 and review["auto_postmortem"] == 1
    on_loop = [r for r in ledger.list_scheduled_reviews() if r["scope_ref"] == result["question_id"]]
    assert len(on_loop) == 1


def test_commit_refuses_unscoreable_spec(tmp_path):
    ledger = _make_ledger(tmp_path)
    spec = _good_spec(resolution_criteria="tbd")
    with pytest.raises(ValidationError):
        spec.commit(ledger)
    # nothing was written
    assert ledger.list_questions() == [] or all(q.title != spec.title for q in ledger.list_questions())
