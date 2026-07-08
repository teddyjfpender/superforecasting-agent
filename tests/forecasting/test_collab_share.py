"""Share-action tests (multiplayer M2): the share_forecast tool + `forecast slack
share` CLI verb post the current snapshot as an sfp/1 forecast card, gated by the
policy seam (decision logged), with the metadata carrying a round-trippable card.
"""

from __future__ import annotations

import argparse
import json

import pytest

from forecasting import ForecastLedger
from forecasting.identity import AgentIdentity
from protocol.collab import ForecastCardBody, canonical_json, parse_body, parse_envelope
from forecasting.collab.cards import build_forecast_card_body, criteria_hash
from tools.forecast_actions.share import execute_share, share_forecast
from tools.forecasting_tool import forecast_ledger_tool

CRITERIA = "BLS CPI-U YoY for July 2026 release exceeds 3.0%."


def _identity() -> AgentIdentity:
    return AgentIdentity(name="Ada", instance_id="inst-abc", team="T012ABC")


@pytest.fixture()
def seeded(tmp_path):
    db = str(tmp_path / "share.db")

    def tool(**a):
        return json.loads(forecast_ledger_tool({"db": db, **a}))

    created = tool(action="create_question", title="Will CPI YoY exceed 3.0%?",
                   resolution_criteria=CRITERIA, close_time="2026-12-31T00:00:00Z")
    qid = created["question"]["id"]
    tool(action="add_evidence", question_id=qid, source_or_note="BLS release",
         claim="June CPI printed 3.1% YoY")
    tool(action="update_forecast", question_id=qid, probability=0.62,
         rationale="Base effects favor a hot print.",
         reasons_up=["shelter sticky", "energy rebound"],
         # G3: a first commit needs a linked outside-view anchor.
         reference_class={"name": "CPI base rate", "inclusion_criteria": "prior monthly CPI prints", "base_rate": 0.5},
         require_components=False, require_structured_reasoning=False, require_panel=False)
    return db, qid


class _Poster:
    """Captures the args passed to the (stubbed) Slack tool."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, args):
        self.calls.append(args)
        return {"ok": True, "ts": "1700000000.000100"}


# ── the share action end-to-end (stubbed Slack) ───────────────────────────────

def test_share_forecast_posts_metadata_that_round_trips(seeded):
    db, qid = seeded
    ledger = ForecastLedger(db)
    poster = _Poster()

    out = execute_share(ledger, qid, "C123", identity=_identity(), poster=poster)

    assert out["success"] is True and out["shared"] is True
    assert out["policy"]["decision"] == "auto"  # decision resolved + logged
    assert out["event_type"] == "sfp.forecast.card"
    assert out["criteria_hash"] == criteria_hash(CRITERIA)
    assert out["slack_ts"] == "1700000000.000100"

    # Exactly one post, via post_with_metadata, with the correct metadata.
    assert len(poster.calls) == 1
    call = poster.calls[0]
    assert call["action"] == "post_with_metadata"
    assert call["channel"] == "C123"
    assert call["event_type"] == "sfp.forecast.card"

    # The posted event_payload round-trips to the card built from the snapshot.
    reparsed = parse_envelope(call["event_payload"])
    expected = build_forecast_card_body(ledger.get_current_snapshot(qid), ledger.get_question(qid))
    assert canonical_json(parse_body(reparsed)) == canonical_json(expected)


def test_share_forecast_threads_when_thread_ts_given(seeded):
    db, qid = seeded
    poster = _Poster()
    execute_share(ForecastLedger(db), qid, "C123", thread_ts="1699.1", identity=_identity(), poster=poster)
    assert poster.calls[0]["thread_ts"] == "1699.1"


def test_share_missing_snapshot_is_a_named_error(tmp_path):
    db = str(tmp_path / "empty.db")
    created = json.loads(forecast_ledger_tool({
        "db": db, "action": "create_question", "title": "no snapshot yet",
        "resolution_criteria": CRITERIA, "close_time": "2026-12-31T00:00:00Z",
    }))
    qid = created["question"]["id"]
    poster = _Poster()
    out = execute_share(ForecastLedger(db), qid, "C123", identity=_identity(), poster=poster)
    assert out["success"] is False and out["shared"] is False
    assert "no current snapshot" in out["error"]
    assert poster.calls == []  # nothing posted


# ── the policy seam ───────────────────────────────────────────────────────────

def test_policy_never_refuses_without_posting(seeded, monkeypatch):
    db, qid = seeded
    monkeypatch.setenv("FORECAST_POLICY_INTERACTIVE_NETWORK", "never")
    poster = _Poster()
    out = execute_share(ForecastLedger(db), qid, "C123", identity=_identity(), poster=poster)
    assert out["success"] is False and out["shared"] is False
    assert "never" in out["error"] and "FORECAST_POLICY_INTERACTIVE_NETWORK" in out["error"]
    assert poster.calls == []


def test_policy_ask_posts_nothing_and_reports_approval(seeded, monkeypatch):
    db, qid = seeded
    monkeypatch.setenv("FORECAST_POLICY_INTERACTIVE_NETWORK", "ask")
    poster = _Poster()
    out = execute_share(ForecastLedger(db), qid, "C123", identity=_identity(), poster=poster)
    assert out["success"] is True and out["shared"] is False
    assert "approval" in out["reason"]
    assert poster.calls == []


# ── the tool handler (share_forecast) over the real Slack tool, network stubbed ─

def test_tool_handler_posts_via_slack_tool(seeded, monkeypatch):
    db, qid = seeded
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("AGENT_NAME", "Ada")
    monkeypatch.setenv("AGENT_INSTANCE_ID", "inst-abc")

    captured: list[tuple] = []

    def fake_api(method, token, **params):
        captured.append((method, params))
        return {"ok": True, "ts": "1700000000.000200"}

    monkeypatch.setattr("tools.slack_tool._slack_api_call", fake_api)

    result = json.loads(forecast_ledger_tool({
        "db": db, "action": "share_forecast", "question_id": qid, "channel": "C999",
    }))
    assert result["success"] is True and result["shared"] is True
    assert result["event_type"] == "sfp.forecast.card"
    assert captured and captured[0][0] == "chat.postMessage"
    meta = json.loads(captured[0][1]["metadata"])
    assert meta["event_type"] == "sfp.forecast.card"
    assert meta["event_payload"]["sender"]["agent"] == "Ada"


# ── the CLI verb (forecast slack share) ───────────────────────────────────────

def test_cli_share_verb(seeded, monkeypatch, capsys):
    from forecasting.cli import slack_admin

    db, qid = seeded
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("AGENT_NAME", "Ada")
    monkeypatch.setenv("AGENT_INSTANCE_ID", "inst-abc")
    monkeypatch.setattr("tools.slack_tool._slack_api_call",
                        lambda method, token, **p: {"ok": True, "ts": "1700000000.000300"})

    ns = argparse.Namespace(db=db, question=qid, channel="C777", thread_ts=None,
                            team_id=None, json=True)
    slack_admin._cmd_slack_share(ns)

    out = json.loads(capsys.readouterr().out)
    assert out["shared"] is True
    assert out["channel"] == "C777"
    assert out["event_type"] == "sfp.forecast.card"
    assert out["criteria_hash"] == criteria_hash(CRITERIA)
