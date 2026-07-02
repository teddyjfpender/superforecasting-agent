"""Tests for the QuestionSpec onboarding staging object (types, validation, commit)."""

from __future__ import annotations

import pytest

import datetime as _dt

from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError
from forecasting.question_spec import (
    QuestionSpec,
    ReferenceClassSpec,
    ResolutionRuleSpec,
    UpdateTriggerSpec,
    WatchedSourceSpec,
    apply_recommended_defaults,
    infer_close_time,
    recommended_clarifications,
    spec_from_dict,
    spec_quality,
    spec_to_dict,
    suggest_resolution_rule,
)


def _make_ledger(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "spec.db"))
    ledger.initialize_schema()
    return ledger


def _good_spec(**overrides) -> QuestionSpec:
    base = dict(
        title="US CPI YoY for the June 2026 print",
        resolution_criteria="Resolves yes if the BLS June 2026 CPI YoY exceeds 3.0 percent.",
        close_time="2026-07-15T00:00:00Z",
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


# ── deadline required-or-inferred ──────────────────────────────────────────────
def test_missing_deadline_is_a_gap_not_an_error():
    spec = _good_spec(close_time=None, resolution_time=None)
    assert spec.errors() == []  # gap does not block commit
    gaps = {g.field for g in spec.readiness_gaps()}
    assert "close_time" in gaps


def test_deadline_gap_waived_by_resolution_time():
    spec = _good_spec(close_time=None, resolution_time="2026-08-01T00:00:00Z")
    gaps = {g.field for g in spec.readiness_gaps()}
    assert "close_time" not in gaps


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Will X ship by September?", "-09-"),           # bare month -> next occurrence
        ("Metric in 2027", "2027-12-31"),                 # bare year
        ("Result by Q4 2026", "2026-12-31"),              # quarter
        ("Will it land by September 2026?", "2026-09-30"),  # month + year
        ("Happens within the next 12 months?", "-"),      # relative window (just non-None)
    ],
)
def test_infer_close_time_parses_horizons(title, expected):
    now = _dt.datetime(2026, 6, 1, tzinfo=_dt.timezone.utc)
    out = infer_close_time(title, "", now=now)
    assert out is not None
    assert expected in out


def test_infer_close_time_ignores_modal_may():
    # "may" as a modal verb must not be read as the month May.
    now = _dt.datetime(2026, 6, 1, tzinfo=_dt.timezone.utc)
    assert infer_close_time("The tally may exceed 50 percent", "") is None


def test_infer_close_time_explicit_year_beats_incidental_bare_month():
    # An explicit "in 2027" must NOT be shadowed by an incidental month name in the
    # criteria ("...the September legislative calendar"), which would otherwise commit
    # a wrong (often past) deadline on the accept-defaults path.
    now = _dt.datetime(2026, 6, 1, tzinfo=_dt.timezone.utc)
    out = infer_close_time(
        "Will the bill pass in 2027?",
        "Tracked via the September legislative calendar.",
        now=now,
    )
    assert out == "2027-12-31"


def test_deadline_clarification_carries_inferred_default():
    spec = _good_spec(close_time=None, resolution_time=None, resolution_criteria="Resolves yes if it ships by Q4 2026.")
    prompts = {p["field"]: p for p in recommended_clarifications(spec)}
    assert "close_time" in prompts
    assert "recommended" in prompts["close_time"]["choices"][0]
    assert "2026-12-31" in prompts["close_time"]["choices"][0]


# ── quality score ──────────────────────────────────────────────────────────────
def test_spec_quality_full_for_clean_spec():
    q = spec_quality(_good_spec())
    assert q["score"] == 100
    assert q["penalty_total"] == 0


def test_spec_quality_penalizes_issues_and_clamps():
    spec = QuestionSpec(title="forecast", resolution_criteria="tbd")
    q = spec_quality(spec)
    assert 0 <= q["score"] < 100
    assert q["counts"]["error"] >= 1
    assert q["breakdown"]  # itemized penalties


# ── resolution rule (auto-resolver reachability) ───────────────────────────────
def test_resolution_rule_validates_and_commits(tmp_path):
    ledger = _make_ledger(tmp_path)
    spec = _good_spec(
        resolution_rule=ResolutionRuleSpec(field="yoy_percent", comparator=">=", threshold=3.0, source_role="resolver"),
    )
    assert spec.errors() == []
    result = spec.commit(ledger)
    assert result["resolution_rule"]["field"] == "yoy_percent"
    q = ledger.get_question(result["question_id"])
    assert q.metadata["resolution_rule"]["comparator"] == ">="


def test_bad_resolution_rule_is_an_error():
    spec = _good_spec(resolution_rule=ResolutionRuleSpec(field="", comparator="~", threshold=None))
    fields = {e.field for e in spec.errors()}
    assert "resolution_rule" in fields


def test_bad_resolution_rule_source_role_is_an_error():
    spec = _good_spec(resolution_rule=ResolutionRuleSpec(field="v", comparator=">=", threshold=1.0, source_role="bogus"))
    assert any(e.field == "resolution_rule" and "source_role" in e.message for e in spec.errors())


def test_bad_resolution_rule_resolver_is_an_error_refused_up_front(tmp_path):
    # An unknown resolver must be caught at spec-time (mirroring source_role), not
    # raise MID-COMMIT after the question row + watches are already written.
    spec = _good_spec(
        resolution_rule=ResolutionRuleSpec(field="v", comparator=">=", threshold=1.0, resolver="bogus"),
    )
    assert any(e.field == "resolution_rule" and "resolver" in e.message for e in spec.errors())
    assert spec.is_committable() is False
    ledger = _make_ledger(tmp_path)
    with pytest.raises(ValidationError):
        spec.commit(ledger)
    # commit refused up-front — no half-created question row exists
    assert ledger.list_questions() == []


def test_suggest_resolution_rule_seeds_from_trigger():
    spec = _good_spec()  # binary + watched source + executable trigger
    suggestion = suggest_resolution_rule(spec)
    assert suggestion is not None
    assert suggestion["comparator"] == ">"
    assert suggestion["threshold"] == 3.0


def test_suggest_resolution_rule_none_when_rule_present_or_no_sources():
    assert suggest_resolution_rule(_good_spec(watched_sources=())) is None
    with_rule = _good_spec(resolution_rule=ResolutionRuleSpec(field="v", comparator=">=", threshold=1.0))
    assert suggest_resolution_rule(with_rule) is None


def test_resolution_rule_round_trips_through_dict():
    spec = _good_spec(resolution_rule=ResolutionRuleSpec(field="v", comparator="<", threshold=2.5, source_role="consensus"))
    again = spec_from_dict(spec_to_dict(spec))
    assert again == spec


# ── accept-defaults onboarding ─────────────────────────────────────────────────
def test_apply_recommended_defaults_fills_gaps_in_one_shot():
    # A casual ask: binary (defaults) but no deadline / owner / action threshold.
    spec = QuestionSpec(
        title="Will the Fed cut in September 2026?",
        resolution_criteria="Resolves yes if the FOMC lowers the target rate at or before its September 2026 meeting; otherwise no.",
    )
    assert spec.readiness_gaps()  # gaps exist before defaults are applied

    new_spec, applied = apply_recommended_defaults(spec)

    fields = {a["field"] for a in applied}
    assert {"close_time", "decision_owner", "action_threshold"} <= fields
    # concrete values landed on the spec
    assert new_spec.close_time == "2026-09-30"  # inferred from "September 2026"
    assert new_spec.decision_owner == "you"
    assert new_spec.action_threshold == ">=70% act"
    # the decision-readiness gaps those fields drove are now closed
    closed = {g.field for g in new_spec.readiness_gaps()}
    assert "close_time" not in closed and "decision_owner" not in closed and "action_threshold" not in closed
    # the auto-applied answers are recorded for the audit trail
    assert any(c.get("auto_default") for c in new_spec.clarifications)


def test_apply_recommended_defaults_never_fabricates_past_an_error():
    # An unscoreable criteria is a free-text (no-recommended) prompt — defaults must
    # NOT invent an auditable condition, so the error survives and still blocks.
    spec = QuestionSpec(title="forecast", resolution_criteria="tbd")
    new_spec, _applied = apply_recommended_defaults(spec)
    error_fields = {e.field for e in new_spec.errors()}
    assert "resolution_criteria" in error_fields
    assert not new_spec.is_committable()


def test_apply_recommended_defaults_preserves_explicit_choices():
    # An already-complete spec has no gap/error clarifications to default, so nothing
    # is applied and the explicit values are untouched.
    spec = _good_spec()
    new_spec, applied = apply_recommended_defaults(spec)
    assert applied == []
    assert new_spec == spec


def test_apply_recommended_defaults_falls_back_to_end_of_year_without_horizon():
    now = _dt.datetime(2026, 3, 1, tzinfo=_dt.timezone.utc)
    spec = QuestionSpec(
        title="Will the merger close?",
        resolution_criteria="Resolves yes if the acquisition formally completes; otherwise no.",
    )
    # no horizon phrase -> infer_close_time returns None; default is end of THIS year.
    assert infer_close_time(spec.title, spec.resolution_criteria, now=now) is None
    new_spec, applied = apply_recommended_defaults(spec)
    close = next(a for a in applied if a["field"] == "close_time")
    assert close["value"].endswith("-12-31")
