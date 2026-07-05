"""The agent-facing Slack Web API tool — action dispatch + token resolution. The HTTP
call is mocked, so no network."""

from __future__ import annotations

import json

from tools import slack_tool as st


def test_no_token_returns_error(monkeypatch):
    monkeypatch.setattr(st, "_resolve_bot_token", lambda team_id=None: None)
    out = json.loads(st.slack_tool({"action": "post_message", "channel": "C1", "text": "hi"}))
    assert out["success"] is False and "token" in out["error"]


def _stub(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(st, "_resolve_bot_token", lambda team_id=None: "xoxb-test")

    def _api(method, token, **params):
        calls["method"] = method
        calls["token"] = token
        calls["params"] = params
        return {"ok": True}

    monkeypatch.setattr(st, "_slack_api_call", _api)
    return calls


def test_post_message_calls_chat_postmessage(monkeypatch):
    calls = _stub(monkeypatch)
    out = json.loads(st.slack_tool({"action": "post_message", "channel": "C1", "text": "hi", "thread_ts": "123"}))
    assert out["success"] is True
    assert calls["method"] == "chat.postMessage" and calls["token"] == "xoxb-test"
    assert calls["params"]["channel"] == "C1" and calls["params"]["text"] == "hi" and calls["params"]["thread_ts"] == "123"


def test_search_messages(monkeypatch):
    calls = _stub(monkeypatch)
    st.slack_tool({"action": "search_messages", "query": "deploy"})
    assert calls["method"] == "search.messages" and calls["params"]["query"] == "deploy"


def test_add_reaction_and_pin(monkeypatch):
    calls = _stub(monkeypatch)
    st.slack_tool({"action": "add_reaction", "channel": "C1", "timestamp": "1.2", "name": "white_check_mark"})
    assert calls["method"] == "reactions.add" and calls["params"]["name"] == "white_check_mark"
    st.slack_tool({"action": "pin_message", "channel": "C1", "timestamp": "1.2"})
    assert calls["method"] == "pins.add"


def test_missing_required_arg_fails(monkeypatch):
    _stub(monkeypatch)
    out = json.loads(st.slack_tool({"action": "post_message", "channel": "C1"}))  # no text
    assert out["success"] is False and "text" in out["error"]


def test_unknown_action(monkeypatch):
    _stub(monkeypatch)
    out = json.loads(st.slack_tool({"action": "frobnicate"}))
    assert out["success"] is False and "unknown action" in out["error"]


def test_resolve_token_prefers_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-env")
    assert st._resolve_bot_token() == "xoxb-env"


def test_resolve_token_from_file(monkeypatch, tmp_path):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    tokens = tmp_path / "slack_tokens.json"
    tokens.write_text(json.dumps({"T1": {"token": "xoxb-file", "team_name": "Acme"}}))
    import hermes_constants

    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    assert st._resolve_bot_token("T1") == "xoxb-file"
    assert st._resolve_bot_token() == "xoxb-file"  # first entry when no team_id


# ── M1 collab verbs ──────────────────────────────────────────────────────────

def test_post_blocks_serializes_blocks_and_keeps_text_fallback(monkeypatch):
    calls = _stub(monkeypatch)
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}]
    st.slack_tool({"action": "post_blocks", "channel": "C1", "blocks": blocks, "text": "hi", "thread_ts": "9"})
    assert calls["method"] == "chat.postMessage"
    assert json.loads(calls["params"]["blocks"]) == blocks  # blocks JSON-encoded
    assert calls["params"]["text"] == "hi" and calls["params"]["thread_ts"] == "9"


def test_post_blocks_requires_blocks(monkeypatch):
    _stub(monkeypatch)
    out = json.loads(st.slack_tool({"action": "post_blocks", "channel": "C1"}))
    assert out["success"] is False and "blocks" in out["error"]


def test_post_with_metadata_round_trips_payload(monkeypatch):
    calls = _stub(monkeypatch)
    payload = {"v": 1, "kind": "forecast.card", "p": 0.34}
    st.slack_tool({
        "action": "post_with_metadata", "channel": "C1",
        "event_type": "sfp_forecast_card", "event_payload": payload, "text": "34%",
    })
    assert calls["method"] == "chat.postMessage"
    meta = json.loads(calls["params"]["metadata"])
    assert meta["event_type"] == "sfp_forecast_card"
    assert meta["event_payload"] == payload  # byte-equal round-trip through metadata


def test_post_with_metadata_requires_event_payload(monkeypatch):
    _stub(monkeypatch)
    out = json.loads(st.slack_tool({"action": "post_with_metadata", "channel": "C1", "event_type": "e"}))
    assert out["success"] is False and "event_payload" in out["error"]


def test_upload_file_uses_content_and_maps_channel(monkeypatch):
    calls = _stub(monkeypatch)
    st.slack_tool({"action": "upload_file", "channel": "C1", "content": "hello", "filename": "e.txt"})
    assert calls["method"] == "files.upload"
    assert calls["params"]["channels"] == "C1"  # channel → channels
    assert calls["params"]["content"] == "hello" and calls["params"]["filename"] == "e.txt"


def test_upload_file_requires_content(monkeypatch):
    _stub(monkeypatch)
    out = json.loads(st.slack_tool({"action": "upload_file", "channel": "C1"}))
    assert out["success"] is False and "content" in out["error"]


def test_read_thread_calls_conversations_replies(monkeypatch):
    calls = _stub(monkeypatch)
    st.slack_tool({"action": "read_thread", "channel": "C1", "thread_ts": "1.2"})
    assert calls["method"] == "conversations.replies"
    assert calls["params"]["channel"] == "C1" and calls["params"]["ts"] == "1.2"
    assert calls["params"]["include_all_metadata"] is True


def test_read_thread_requires_a_ts(monkeypatch):
    _stub(monkeypatch)
    out = json.loads(st.slack_tool({"action": "read_thread", "channel": "C1"}))
    assert out["success"] is False and "thread_ts" in out["error"]
