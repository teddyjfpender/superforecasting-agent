"""Tests for the information-triage labeler, rubric storage, and actions."""

from __future__ import annotations

import json

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.triage import (
    DEFAULT_TRIAGE_RUBRIC,
    IRRELEVANT,
    RELEVANT_INTERESTING,
    RELEVANT_UNINTERESTING,
    active_rubric_for_question,
    build_triage_prompt,
    normalize_label,
    parse_triage_response,
    triage_candidates,
    verdict_for_label,
)


# ── pure labeler ──────────────────────────────────────────────────────────


def test_normalize_label_aliases():
    assert normalize_label("Relevant & Interesting".replace(" & ", "_and_")) == RELEVANT_INTERESTING
    assert normalize_label("interesting") == RELEVANT_INTERESTING
    assert normalize_label("relevant-but-uninteresting") == RELEVANT_UNINTERESTING
    assert normalize_label("IRRELEVANT") == IRRELEVANT
    # unknown / missing -> conservative skim default
    assert normalize_label("") == RELEVANT_UNINTERESTING
    assert normalize_label("banana") == RELEVANT_UNINTERESTING


def test_verdict_mapping():
    assert verdict_for_label(RELEVANT_INTERESTING) == "keep"
    assert verdict_for_label(RELEVANT_UNINTERESTING) == "skim"
    assert verdict_for_label(IRRELEVANT) == "skip"


def test_build_prompt_includes_rubric_and_candidates():
    system, user = build_triage_prompt(
        [{"title": "Fed pauses", "summary": "surprise", "source_type": "rss"}],
        DEFAULT_TRIAGE_RUBRIC,
    )
    assert "triage labeler" in system.lower()
    assert "DESK RUBRIC" in user
    assert "Fed pauses" in user
    assert "[0]" in user
    assert "relevant_interesting" in user


def test_parse_good_response():
    candidates = [{"title": "A"}, {"title": "B"}]
    raw = json.dumps(
        {
            "labels": [
                {"index": 0, "triage_label": "relevant_interesting", "relevance": 0.9, "materiality": "high", "rationale": "macro"},
                {"index": 1, "triage_label": "irrelevant", "relevance": 0.1, "materiality": "low", "rationale": "off-topic"},
            ]
        }
    )
    verdicts = parse_triage_response(raw, candidates)
    assert verdicts[0]["triage_label"] == RELEVANT_INTERESTING
    assert verdicts[0]["verdict"] == "keep"
    assert verdicts[0]["relevance"] == 0.9
    assert verdicts[0]["materiality"] == "high"
    assert verdicts[1]["triage_label"] == IRRELEVANT
    assert verdicts[1]["verdict"] == "skip"


def test_parse_missing_row_defaults_to_skim():
    candidates = [{"title": "A"}, {"title": "B"}]
    raw = json.dumps({"labels": [{"index": 0, "triage_label": "irrelevant"}]})
    verdicts = parse_triage_response(raw, candidates)
    assert verdicts[1]["triage_label"] == RELEVANT_UNINTERESTING  # no row -> skim
    assert verdicts[1]["verdict"] == "skim"


def test_parse_garbled_response_degrades():
    candidates = [{"title": "A"}]
    verdicts = parse_triage_response("not json at all", candidates)
    assert len(verdicts) == 1
    assert verdicts[0]["verdict"] == "skim"


def test_parse_fenced_json():
    candidates = [{"title": "A"}]
    raw = "```json\n" + json.dumps({"labels": [{"index": 0, "triage_label": "keep"}]}) + "\n```"
    verdicts = parse_triage_response(raw, candidates)
    assert verdicts[0]["triage_label"] == RELEVANT_INTERESTING


def test_triage_candidates_with_fake_runner():
    candidates = [{"title": "Fed surprise", "id": "c1"}, {"title": "tiny IPO", "id": "c2"}]

    def fake_runner(model, system, user):
        assert model == "cheap-1"
        return json.dumps(
            {
                "labels": [
                    {"index": 0, "triage_label": "relevant_interesting"},
                    {"index": 1, "triage_label": "relevant_uninteresting"},
                ]
            }
        )

    verdicts = triage_candidates(candidates, runner=fake_runner, model="cheap-1")
    assert [v["verdict"] for v in verdicts] == ["keep", "skim"]
    assert verdicts[0]["candidate_ref"] == "c1"
    assert verdicts[0]["model"] == "cheap-1"
    assert all(v["label_source"] == "auto" for v in verdicts)


def test_triage_candidates_empty():
    assert triage_candidates([], runner=lambda *a: "", model="m") == []


# ── rubric storage + scope walk ───────────────────────────────────────────


@pytest.fixture
def ledger(tmp_path):
    return ForecastLedger(db_path=str(tmp_path / "triage.db"))


def test_set_get_list_rubric(ledger):
    stored = ledger.set_triage_rubric(
        scope_type="global",
        interesting_criteria="macro surprises",
        uninteresting_criteria="small IPOs",
        examples=[{"title": "x", "label": "irrelevant", "why": "y"}],
    )
    assert stored["scope_type"] == "global"
    assert stored["interesting_criteria"] == "macro surprises"
    assert ledger.get_triage_rubric(stored["id"])["id"] == stored["id"]
    rubrics = ledger.list_triage_rubrics(scope_type="global")
    assert len(rubrics) == 1


def test_set_rubric_upserts_same_scope(ledger):
    first = ledger.set_triage_rubric(scope_type="domain", scope_ref="politics", interesting_criteria="v1")
    second = ledger.set_triage_rubric(scope_type="domain", scope_ref="politics", interesting_criteria="v2")
    assert first["id"] == second["id"]  # updated in place, not duplicated
    assert ledger.get_triage_rubric(first["id"])["interesting_criteria"] == "v2"
    assert len(ledger.list_triage_rubrics(scope_type="domain", scope_ref="politics")) == 1


def test_rubric_scope_validation(ledger):
    from forecasting.models import ValidationError

    with pytest.raises(ValidationError):
        ledger.set_triage_rubric(scope_type="domain", scope_ref=None, interesting_criteria="x")
    with pytest.raises(ValidationError):
        ledger.set_triage_rubric(scope_type="domain_topic", scope_ref="no-colon", interesting_criteria="x")
    with pytest.raises(ValidationError):
        ledger.set_triage_rubric(scope_type="bogus", scope_ref="x", interesting_criteria="x")


def test_active_rubric_for_question_scope_walk(ledger):
    question = ledger.create_question(
        title="Will X happen?",
        resolution_criteria="Resolves yes if the official tally exceeds 50%; otherwise no.",
    )
    qtype = question.outcome_space.type
    # global first
    ledger.set_triage_rubric(scope_type="global", interesting_criteria="global-rubric")
    got = active_rubric_for_question(ledger, question)
    assert got["interesting_criteria"] == "global-rubric"
    # a question_type rubric is more specific and wins
    ledger.set_triage_rubric(scope_type="question_type", scope_ref=qtype, interesting_criteria="qtype-rubric")
    got = active_rubric_for_question(ledger, question)
    assert got["interesting_criteria"] == "qtype-rubric"


def test_active_rubric_none_when_empty(ledger):
    question = ledger.create_question(
        title="Q?",
        resolution_criteria="Resolves yes if the official tally exceeds 50%; otherwise no.",
    )
    assert active_rubric_for_question(ledger, question) is None


# ── triage_labels staging rows ─────────────────────────────────────────────


def test_record_and_list_triage_labels(ledger):
    verdicts = [
        {"triage_label": "relevant_interesting", "title": "A", "verdict": "keep", "relevance": 0.8, "materiality": "high"},
        {"triage_label": "irrelevant", "title": "B", "verdict": "skip"},
    ]
    stored = ledger.record_triage_labels(question_id=None, verdicts=verdicts)
    assert len(stored) == 2
    assert stored[0]["auto_label"] == "relevant_interesting"
    assert stored[0]["triage_label"] == "relevant_interesting"
    assert stored[0]["label_source"] == "auto"
    assert stored[0]["expert_label"] is None
    assert stored[0]["contested"] is False
    listed = ledger.list_triage_labels()
    assert len(listed) == 2


def test_update_triage_label_adjudication(ledger):
    [row] = ledger.record_triage_labels(
        verdicts=[{"triage_label": "irrelevant", "title": "A"}]
    )
    updated = ledger.update_triage_label(
        row["id"],
        expert_label="relevant_interesting",
        triage_label="relevant_interesting",
        label_source="expert",
        contested=True,
        adjudicated_at="2026-06-30T00:00:00Z",
    )
    assert updated["expert_label"] == "relevant_interesting"
    assert updated["triage_label"] == "relevant_interesting"
    assert updated["label_source"] == "expert"
    assert updated["contested"] is True


# ── actions ────────────────────────────────────────────────────────────────


def _fake_make_runner(label="relevant_interesting"):
    def factory(**kwargs):
        def runner(model, system, user):
            return json.dumps({"labels": [{"index": 0, "triage_label": label, "relevance": 0.9, "materiality": "high", "rationale": "x"}]})

        return runner

    return factory


def test_set_and_list_label_rubric_actions(tmp_path):
    from tools.forecasting_tool import forecast_ledger_tool

    db = str(tmp_path / "t.db")
    out = forecast_ledger_tool(
        {
            "action": "set_label_rubric",
            "db": db,
            "scope_type": "global",
            "rubric": {"interesting_criteria": "macro surprises", "uninteresting_criteria": "small IPOs"},
        }
    )
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["rubric"]["interesting_criteria"] == "macro surprises"

    out2 = forecast_ledger_tool({"action": "list_label_rubrics", "db": db})
    payload2 = json.loads(out2)
    assert payload2["count"] == 1


def test_set_label_rubric_requires_interesting(tmp_path):
    from tools.forecasting_tool import forecast_ledger_tool

    out = forecast_ledger_tool(
        {"action": "set_label_rubric", "db": str(tmp_path / "t.db"), "rubric": {"notes": "x"}}
    )
    payload = json.loads(out)
    assert payload.get("error")
    assert "interesting_criteria" in payload["error"]


def test_triage_label_action_end_to_end(tmp_path, monkeypatch):
    import forecasting.quorum as quorum_mod
    from tools.forecasting_tool import forecast_ledger_tool

    monkeypatch.setattr(quorum_mod, "make_aiagent_runner", _fake_make_runner("relevant_interesting"))
    db = str(tmp_path / "t.db")
    out = forecast_ledger_tool(
        {
            "action": "triage_label",
            "db": db,
            "candidates": [{"title": "Fed surprise pause", "summary": "off consensus"}],
            "persist": True,
        }
    )
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["summary"] == {"keep": 1, "skim": 0, "skip": 0, "n": 1}
    assert payload["verdicts"][0]["auto_label"] == "relevant_interesting"
    # persisted as a staging row
    ledger = ForecastLedger(db_path=db)
    assert len(ledger.list_triage_labels()) == 1


def test_triage_label_requires_candidates(tmp_path):
    from tools.forecasting_tool import forecast_ledger_tool

    out = forecast_ledger_tool({"action": "triage_label", "db": str(tmp_path / "t.db")})
    payload = json.loads(out)
    assert payload.get("error")
    assert "candidates" in payload["error"]
