"""The shared meeting summarizer (Teams + Meet) and the Google Meet meet_followup tool
that gathers the post-call TODO list. The LLM path is mocked to the deterministic
heuristic so tests are fast + reproducible."""

from __future__ import annotations

import json

from plugins.meeting_common.summarize import (
    MeetingSummary,
    heuristic_summary,
    parse_summary_json,
    summarize_transcript_sync,
)


def test_parse_summary_json_extracts_fields_from_wrapped_json():
    content = 'noise before {"summary": "s", "action_items": ["do x", " "], "risks": ["r"], "key_decisions": ["d"]} after'
    parsed = parse_summary_json(content)
    assert parsed["summary"] == "s"
    assert parsed["action_items"] == ["do x"]  # blanks dropped
    assert parsed["risks"] == ["r"] and parsed["key_decisions"] == ["d"]


def test_parse_summary_json_garbage_falls_back_to_heuristic():
    parsed = parse_summary_json("not json at all, Action: ship it")
    assert "action_items" in parsed  # heuristic shape, never raises


def test_heuristic_summary_picks_action_risk_decision_lines():
    transcript = (
        "We talked for a while about the launch.\n"
        "Action: send the deck to finance\n"
        "TODO: book the venue\n"
        "There is a risk the vendor slips.\n"
        "We decided to ship on Friday.\n"
    )
    h = heuristic_summary(transcript)
    joined = " ".join(h["action_items"]).lower()
    assert "send the deck" in joined and "book the venue" in joined
    assert any("vendor slips" in r.lower() for r in h["risks"])
    assert any("ship on friday" in d.lower() for d in h["key_decisions"])


def test_meeting_summary_to_dict_roundtrip():
    s = MeetingSummary(summary="x", action_items=["a"], risks=["r"])
    d = s.to_dict()
    assert d["summary"] == "x" and d["action_items"] == ["a"] and d["confidence"] == "medium"


def test_summarize_sync_falls_back_to_heuristic_without_llm(monkeypatch):
    import agent.auxiliary_client as aux

    async def _boom(**_kwargs):
        raise RuntimeError("no llm in test")

    monkeypatch.setattr(aux, "async_call_llm", _boom)
    s = summarize_transcript_sync("Action: ship the report\nWe decided to launch.", title="t")
    assert isinstance(s, MeetingSummary)
    assert any("ship the report" in item.lower() for item in s.action_items)


def test_meet_followup_gathers_the_todo_list(monkeypatch):
    import agent.auxiliary_client as aux
    import plugins.google_meet.tools as t

    async def _boom(**_kwargs):
        raise RuntimeError("no llm")

    monkeypatch.setattr(aux, "async_call_llm", _boom)
    monkeypatch.setattr(t, "_resolve_node_client", lambda node: (None, None))
    monkeypatch.setattr(
        t.pm, "transcript",
        lambda last=None: {"ok": True, "lines": ["Action: file the report", "We decided to launch."], "total": 2},
    )
    out = json.loads(t.handle_meet_followup({"title": "Sync"}))
    assert out["success"] is True
    assert any("file the report" in item.lower() for item in out["action_items"])  # the TODO list
    assert "next" in out  # the file/assign/dispatch guidance for the human-in-loop step
