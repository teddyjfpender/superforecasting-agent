"""Stdlib Telegram transport: token probe, chat capture, message send — all
driven against a stubbed HTTP seam (no network)."""

from __future__ import annotations

import pytest

from forecasting.transports import telegram as tg


@pytest.fixture()
def fake_api(monkeypatch):
    calls: list = []

    def _install(handler):
        def _call(token, method, timeout=15.0, **params):
            calls.append((method, params))
            return handler(method, params)
        monkeypatch.setattr(tg, "_telegram_api_call", _call)
        return calls

    return _install


def test_get_me_ok(fake_api):
    fake_api(lambda m, p: {"ok": True, "result": {"id": 42, "username": "deskbot", "first_name": "Desk"}})
    me = tg.get_me("T")
    assert me == {"ok": True, "id": 42, "username": "deskbot", "name": "Desk"}


def test_get_me_rejected(fake_api):
    fake_api(lambda m, p: {"ok": False, "description": "Unauthorized"})
    me = tg.get_me("bad")
    assert me["ok"] is False and me["error"] == "Unauthorized"


def test_capture_chat_picks_newest(fake_api):
    updates = {
        "ok": True,
        "result": [
            {"update_id": 10, "message": {"chat": {"id": 111, "type": "private", "first_name": "Ann"}}},
            {"update_id": 12, "message": {"chat": {"id": 222, "type": "private", "username": "bob"}}},
        ],
    }
    fake_api(lambda m, p: updates)
    got = tg.capture_chat("T")
    assert got["chat_id"] == "222"
    assert got["update_id"] == 12


def test_capture_chat_none_when_empty(fake_api):
    fake_api(lambda m, p: {"ok": True, "result": []})
    assert tg.capture_chat("T") is None


def test_capture_chat_respects_offset(fake_api):
    calls = fake_api(lambda m, p: {"ok": True, "result": []})
    tg.capture_chat("T", after_update_id=5)
    # getUpdates must be called with offset = after+1 so acknowledged updates drop
    assert calls[0][0] == "getUpdates"
    assert calls[0][1].get("offset") == 6


def test_send_message_ok(fake_api):
    calls = fake_api(lambda m, p: {"ok": True, "result": {"message_id": 7}})
    res = tg.send_message("T", "999", "hello", thread_id="4")
    assert res == {"ok": True, "message_id": 7}
    sent = calls[0][1]
    assert sent["chat_id"] == "999" and sent["message_thread_id"] == "4"


def test_send_message_omits_general_topic_thread(fake_api):
    calls = fake_api(lambda m, p: {"ok": True, "result": {"message_id": 1}})
    tg.send_message("T", "999", "hi", thread_id="1")  # General topic → no thread kwarg
    assert "message_thread_id" not in calls[0][1]


def test_send_message_retries_plain_on_parse_error(fake_api):
    seq = [
        {"ok": False, "description": "Bad Request: can't parse entities"},
        {"ok": True, "result": {"message_id": 9}},
    ]
    fake_api(lambda m, p: seq.pop(0))
    res = tg.send_message("T", "1", "under_score *bad markdown")
    assert res == {"ok": True, "message_id": 9}


def test_send_message_truncates_overlong(fake_api):
    calls = fake_api(lambda m, p: {"ok": True, "result": {"message_id": 1}})
    tg.send_message("T", "1", "x" * (tg.MAX_MESSAGE_LENGTH + 500))
    assert len(calls[0][1]["text"]) <= tg.MAX_MESSAGE_LENGTH


def test_resolve_bot_token_prefers_explicit(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-tok")
    assert tg.resolve_bot_token("explicit") == "explicit"
    assert tg.resolve_bot_token(None) == "env-tok"
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert tg.resolve_bot_token(None) is None
