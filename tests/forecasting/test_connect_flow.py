"""Connect flows (P2.2/P2.3): the Telegram connect state machine, the Slack
connect sequencing, the surface listing, and the deferred-surface notices —
all driven with injected transports (no network, no live bot)."""

from __future__ import annotations

import pytest

from forecasting import notify
from forecasting.cli import connect_admin as ca


# ── a fake telegram transport module ──────────────────────────────────────────


class FakeTelegram:
    def __init__(self, *, valid=True, chats=None):
        self.valid = valid
        self.chats = list(chats or [])
        self.sent: list = []

    def get_me(self, token):
        if self.valid:
            return {"ok": True, "id": 1, "username": "deskbot", "name": "Desk"}
        return {"ok": False, "error": "Unauthorized"}

    def capture_chat(self, token, after_update_id=None):
        return self.chats.pop(0) if self.chats else None

    def send_message(self, token, chat_id, text, thread_id=None, **kw):
        self.sent.append((chat_id, text))
        return {"ok": True, "message_id": 1}


def _router(tmp_path):
    store = notify.RouteStore(path=tmp_path / "routes.json")
    log = notify.DeliveryLog(path=tmp_path / "deliveries.json")

    def _sender(route, event):
        return notify.DeliveryResult(route_id=route.id, surface=route.surface, target=route.target, ok=True)

    return notify.NotifyRouter(store=store, log=log, senders={"telegram": _sender, "slack": _sender}), store


# ── telegram connect state machine ────────────────────────────────────────────


def test_telegram_connect_non_interactive_happy_path(tmp_path):
    tokens: list = []
    router, store = _router(tmp_path)
    result = ca.run_telegram_connect(
        token="123:ABC", chat_id="555", events=("cycle_digest", "alert"),
        interactive=False, do_test=True,
        tg=FakeTelegram(), router=router, store=store,
        set_token=tokens.append, emit=lambda _m: None,
    )
    assert result["ok"] is True
    assert result["route_id"] == "telegram:555"
    assert result["test_ok"] is True
    assert tokens == ["123:ABC"]  # token persisted
    assert store.get("telegram:555").events == ("cycle_digest", "alert")


def test_telegram_connect_invalid_token_stops(tmp_path):
    router, store = _router(tmp_path)
    result = ca.run_telegram_connect(
        token="bad", chat_id="1", events=(notify.ALL,), interactive=False,
        tg=FakeTelegram(valid=False), router=router, store=store,
        set_token=lambda _t: None, emit=lambda _m: None,
    )
    assert result["ok"] is False and result["stage"] == "validate"
    assert store.get("telegram:1") is None  # nothing bound on a bad token


def test_telegram_connect_non_interactive_requires_chat(tmp_path):
    router, store = _router(tmp_path)
    result = ca.run_telegram_connect(
        token="123:ABC", chat_id=None, events=(notify.ALL,), interactive=False,
        tg=FakeTelegram(), router=router, store=store,
        set_token=lambda _t: None, emit=lambda _m: None,
    )
    assert result["ok"] is False and result["stage"] == "bind"


def test_telegram_connect_interactive_captures_chat(tmp_path):
    router, store = _router(tmp_path)
    fake = FakeTelegram(chats=[{"chat_id": "777", "chat_type": "private"}])
    prompts = iter(["", ""])  # press-enter prompts
    result = ca.run_telegram_connect(
        token="123:ABC", chat_id=None, events=(notify.ALL,),
        interactive=True, do_test=False,
        tg=fake, router=router, store=store, set_token=lambda _t: None,
        emit=lambda _m: None, prompt=lambda _p: next(prompts), sleep=lambda _s: None,
    )
    assert result["ok"] is True
    assert result["chat_id"] == "777"
    assert store.get("telegram:777") is not None


def test_telegram_connect_capture_times_out(tmp_path):
    router, store = _router(tmp_path)
    fake = FakeTelegram(chats=[])  # operator never messages the bot
    result = ca.run_telegram_connect(
        token="123:ABC", chat_id=None, events=(notify.ALL,),
        interactive=True, tg=fake, router=router, store=store,
        set_token=lambda _t: None, emit=lambda _m: None,
        prompt=lambda _p: "", poll_attempts=2, sleep=lambda _s: None,
    )
    assert result["ok"] is False and result["stage"] == "capture"


# ── slack connect sequencing ──────────────────────────────────────────────────


def test_slack_connect_happy_path(tmp_path):
    tokens: list = []
    router, store = _router(tmp_path)
    result = ca.run_slack_connect(
        token="xoxb-1", channel="C0DESK", events=("cycle_digest",),
        interactive=False, do_test=True,
        auth_test=lambda t: {"ok": True, "user": "deskbot", "team": "Acme", "team_id": "T1"},
        router=router, store=store, set_token=tokens.append, emit=lambda _m: None,
    )
    assert result["ok"] is True
    assert result["team_id"] == "T1" and result["bot_user"] == "deskbot"
    assert result["bound"] is True and result["route_id"] == "slack:C0DESK"
    assert result["test_ok"] is True
    assert tokens == ["xoxb-1"]


def test_slack_connect_auth_test_red_stops(tmp_path):
    router, store = _router(tmp_path)
    result = ca.run_slack_connect(
        token="xoxb-bad", channel="C1", events=(notify.ALL,), interactive=False,
        auth_test=lambda t: {"ok": False, "error": "invalid_auth"},
        router=router, store=store, set_token=lambda _t: None, emit=lambda _m: None,
    )
    assert result["ok"] is False and result["stage"] == "verify"
    assert store.get("slack:C1") is None  # no binding without a green whoami


def test_slack_connect_verified_but_no_channel(tmp_path):
    router, store = _router(tmp_path)
    result = ca.run_slack_connect(
        token="xoxb-1", channel=None, events=(notify.ALL,), interactive=False,
        auth_test=lambda t: {"ok": True, "user": "b", "team": "Acme", "team_id": "T1"},
        router=router, store=store, set_token=lambda _t: None, emit=lambda _m: None,
    )
    assert result["ok"] is True and result["bound"] is False


# ── surface listing + deferred notices ────────────────────────────────────────


def test_connect_listing_marks_available_and_deferred(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    listing = {row["surface"]: row for row in ca.build_connect_listing()}
    assert listing["telegram"]["status"] == "available"
    assert listing["signal"]["status"] == "expert-only"
    assert listing["whatsapp"]["status"] == "expert-only"


def test_connect_listing_marks_connected(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    store = notify.RouteStore(path=tmp_path / "notify" / "routes.json")
    store.upsert(notify.NotifyRoute(surface="telegram", target="555", events=(notify.ALL,)))
    listing = {row["surface"]: row for row in ca.build_connect_listing()}
    assert listing["telegram"]["status"] == "connected"
    assert "555" in listing["telegram"]["bound"]


def test_deferred_notice_is_one_honest_line():
    for surface in ("signal", "whatsapp"):
        notice = ca.build_deferred_notice(surface)
        assert notice.startswith(surface)
        assert "expert-only" in notice


def test_parse_events_rejects_unknown():
    with pytest.raises(ValueError):
        ca.parse_events("cycle_digest,bogus")
    assert ca.parse_events("all") == (notify.ALL,)
    assert ca.parse_events("") == (notify.ALL,)
