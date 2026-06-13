from __future__ import annotations

import sys
import types

from forecasting import writeup


def test_sanitize_strips_em_and_en_dashes():
    out = writeup.sanitize_writeup_text("Talarico leads — by three points")
    assert "—" not in out
    assert "—" not in out
    assert "leads, by three points" in out


def test_sanitize_strips_figure_and_other_dashes_and_spaced_double_hyphen():
    assert "–" not in writeup.sanitize_writeup_text("range 3–5")
    assert writeup.sanitize_writeup_text("range 3–5") == "range 3-5"
    assert writeup.sanitize_writeup_text("polls move -- fast") == "polls move, fast"


def test_sanitize_collapses_whitespace_and_tightens_punctuation():
    assert writeup.sanitize_writeup_text("a    b") == "a b"
    assert writeup.sanitize_writeup_text("word , next") == "word, next"
    assert writeup.sanitize_writeup_text("") == ""


def test_parse_handles_fenced_json_and_builds_body():
    raw = (
        "```json\n"
        '{"headline":"R favored","how_it_feels":"Comfortable.","how_it_thinks":"Fundamentals.",'
        '"looking_for":"Polls.","be_aware":"Early.","stance":"lean_yes"}\n'
        "```"
    )
    out = writeup.parse_writeup_response(raw)
    assert out is not None
    assert out["headline"] == "R favored"
    assert out["stance"] == "lean_yes"
    assert out["body"] == "Comfortable.\n\nFundamentals.\n\nPolls.\n\nEarly."


def test_parse_handles_bare_json_with_surrounding_prose():
    raw = 'Sure, here you go:\n{"how_it_feels":"Fine."}\nhope that helps'
    out = writeup.parse_writeup_response(raw)
    assert out is not None
    assert out["how_it_feels"] == "Fine."


def test_parse_sanitizes_dashes_inside_fields():
    out = writeup.parse_writeup_response('{"how_it_feels":"a — b","headline":"x — y"}')
    assert out is not None
    assert "—" not in out["how_it_feels"]
    assert "—" not in out["headline"]


def test_parse_returns_none_on_garbage_or_empty():
    assert writeup.parse_writeup_response("not json at all") is None
    assert writeup.parse_writeup_response("") is None
    assert writeup.parse_writeup_response("{}") is None  # no body, no headline


def test_build_writeup_messages_shape_and_style_constraints():
    question = types.SimpleNamespace(title="Texas Senate winner?")
    snapshot = types.SimpleNamespace(probability_or_distribution=0.59, confidence=0.66, method="ensemble")
    messages = writeup.build_writeup_messages(
        question, snapshot, "SHARED CONTEXT", prior_probability=0.58, delta=0.01
    )
    assert messages[0]["role"] == "system"
    assert "FiveThirtyEight" in messages[0]["content"]
    assert "em-dashes" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "Texas Senate winner?" in messages[1]["content"]
    assert "SHARED CONTEXT" in messages[1]["content"]
    assert "0.59" in messages[1]["content"]


def test_build_writeup_messages_evidence_only_framing():
    question = types.SimpleNamespace(title="Q?")
    snapshot = types.SimpleNamespace(probability_or_distribution=0.5, confidence=None, method=None)
    messages = writeup.build_writeup_messages(question, snapshot, "CTX", evidence_only=True)
    assert "thinking update" in messages[1]["content"].lower()


def test_build_retrospective_messages_include_outcome_and_score():
    question = types.SimpleNamespace(title="Q?")
    snapshot = types.SimpleNamespace(probability_or_distribution=0.59)
    resolution = types.SimpleNamespace(outcome="Republican candidate")
    score = types.SimpleNamespace(brier_score=0.21, log_score=-0.4, proper_score=None, score_rule="brier", calibration_bucket="0.5-0.6")
    messages = writeup.build_retrospective_messages(question, snapshot, resolution, score, "a postmortem", "CTX")
    assert messages[0]["role"] == "system"
    assert "retrospective" in messages[0]["content"].lower()
    assert "Republican candidate" in messages[1]["content"]
    assert "brier=0.21" in messages[1]["content"]


def test_generate_writeup_returns_none_when_context_build_fails(monkeypatch):
    import forecasting.protocol as protocol

    def boom(*_args, **_kwargs):
        raise RuntimeError("context unavailable")

    monkeypatch.setattr(protocol, "build_context_packet", boom)
    # Never raises; degrades to None so the caller commits the forecast anyway.
    assert writeup.generate_writeup(object(), object(), object()) is None


def test_generate_writeup_returns_none_when_provider_missing(monkeypatch):
    import forecasting.protocol as protocol

    monkeypatch.setattr(protocol, "build_context_packet", lambda *a, **k: "CTX")

    fake = types.ModuleType("agent.auxiliary_client")

    def call_llm(**_kwargs):
        raise RuntimeError("No LLM provider configured")

    fake.call_llm = call_llm
    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", fake)

    question = types.SimpleNamespace(title="Q?")
    snapshot = types.SimpleNamespace(probability_or_distribution=0.5, confidence=None, method=None)
    assert writeup.generate_writeup(object(), question, snapshot) is None


def test_generate_writeup_parses_a_successful_response(monkeypatch):
    import forecasting.protocol as protocol

    monkeypatch.setattr(protocol, "build_context_packet", lambda *a, **k: "CTX")

    payload = (
        '{"headline":"Lean R","how_it_feels":"Steady — but watchful.","how_it_thinks":"Base rates.",'
        '"looking_for":"Polls.","be_aware":"Early.","stance":"lean_yes"}'
    )
    message = types.SimpleNamespace(content=payload)
    choice = types.SimpleNamespace(message=message)
    response = types.SimpleNamespace(choices=[choice], model="test-model")

    fake = types.ModuleType("agent.auxiliary_client")
    fake.call_llm = lambda **_kwargs: response
    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", fake)

    question = types.SimpleNamespace(title="Q?")
    snapshot = types.SimpleNamespace(probability_or_distribution=0.59, confidence=0.66, method="ensemble")
    out = writeup.generate_writeup(object(), question, snapshot)
    assert out is not None
    assert out["headline"] == "Lean R"
    assert out["stance"] == "lean_yes"
    assert "—" not in out["how_it_feels"]  # sanitized
    assert out["agent_model"] == "test-model"
    assert out["prompt_version"] == writeup.PROMPT_VERSION


def test_tail_audit_summary_flags_failing_categorical():
    snap = types.SimpleNamespace(
        metadata={
            "tail_audit": {
                "passes": False,
                "unearned_mass": 0.017,
                "outcomes": [
                    {"name": "Conway", "unearned": True},
                    {"name": "Lasher", "unearned": False},
                ],
                "null_model": {"within_tolerance": False, "ratio": 4.3},
            }
        }
    )
    summary = writeup.tail_audit_summary(snap)
    assert "tail audit FAIL" in summary
    assert "1.7%" in summary
    assert "Conway" in summary
    assert "4.3x" in summary


def test_tail_audit_summary_empty_when_passing_or_absent():
    assert writeup.tail_audit_summary(types.SimpleNamespace(metadata={"tail_audit": {"passes": True}})) == ""
    assert writeup.tail_audit_summary(types.SimpleNamespace(metadata={})) == ""
    assert writeup.tail_audit_summary(types.SimpleNamespace()) == ""


def test_writeup_prompt_injects_audit_block_only_on_failure():
    failing = types.SimpleNamespace(
        metadata={"tail_audit": {"passes": False, "unearned_mass": 0.06, "outcomes": [{"name": "X", "unearned": True}]}},
        probability_or_distribution={"A": 0.6}, confidence=0.5, method="panel",
    )
    msgs = writeup.build_writeup_messages(types.SimpleNamespace(title="Q"), failing, "ctx")
    assert "Probability-Mass Audit" in msgs[1]["content"]
    assert "be_aware" in msgs[1]["content"]

    passing = types.SimpleNamespace(
        metadata={"tail_audit": {"passes": True}},
        probability_or_distribution=0.5, confidence=None, method=None,
    )
    msgs2 = writeup.build_writeup_messages(types.SimpleNamespace(title="Q"), passing, "ctx")
    assert "Probability-Mass Audit" not in msgs2[1]["content"]
