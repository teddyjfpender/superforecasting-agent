"""End-to-end CLI dispatch for `forecast connect` / `forecast notify`, the doctor
`connections` section, and the acceptance path: a fresh operator connects
Telegram in ONE guided command and a real digest reaches the wire (HTTP stubbed)."""

from __future__ import annotations

import argparse
import json

import pytest

from forecasting import notify
from forecasting.cli import register_cli


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forecast-test")
    sub = parser.add_subparsers(dest="command")
    register_cli(sub)
    return parser


def _run(argv: list[str]):
    parser = _parser()
    args = parser.parse_args(argv)
    args.func(args)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    return tmp_path


@pytest.fixture()
def stub_wire(monkeypatch):
    """Stub the Telegram HTTP seam; record every method + params sent."""
    from forecasting.transports import telegram as tg

    sent: list = []

    def _call(token, method, timeout=15.0, **params):
        sent.append((method, params))
        if method == "getMe":
            return {"ok": True, "result": {"id": 1, "username": "deskbot", "first_name": "Desk"}}
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": len(sent)}}
        if method == "getUpdates":
            return {"ok": True, "result": []}
        return {"ok": True, "result": {}}

    monkeypatch.setattr(tg, "_telegram_api_call", _call)
    return sent


# ── notify CLI ────────────────────────────────────────────────────────────────


def test_notify_add_list_remove(home, capsys):
    _run(["forecast", "notify", "add", "telegram", "999", "--events", "cycle_digest,alert"])
    assert "added binding telegram:999" in capsys.readouterr().out

    _run(["forecast", "notify", "list", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert any(r["id"] == "telegram:999" and r["events"] == ["cycle_digest", "alert"] for r in rows)

    _run(["forecast", "notify", "remove", "telegram:999"])
    assert "removed binding telegram:999" in capsys.readouterr().out

    _run(["forecast", "notify", "list", "--json"])
    assert json.loads(capsys.readouterr().out) == []


def test_notify_test_delivers_via_stubbed_wire(home, stub_wire, capsys, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    _run(["forecast", "notify", "add", "telegram", "555"])
    capsys.readouterr()
    _run(["forecast", "notify", "test", "telegram:555"])
    out = capsys.readouterr().out
    assert "delivered a test to telegram:555" in out
    assert any(m == "sendMessage" and p["chat_id"] == "555" for m, p in stub_wire)


def test_notify_test_unknown_target_exits_nonzero(home, capsys):
    with pytest.raises(SystemExit) as exc:
        _run(["forecast", "notify", "test", "discord:x"])
    assert exc.value.code == 1


# ── connect CLI ───────────────────────────────────────────────────────────────


def test_connect_list_shows_all_surfaces(home, capsys):
    _run(["forecast", "connect"])
    out = capsys.readouterr().out
    for surface in ("telegram", "slack", "signal", "whatsapp"):
        assert surface in out
    assert "expert-only" in out


def test_connect_signal_prints_deferred(home, capsys):
    _run(["forecast", "connect", "signal"])
    out = capsys.readouterr().out
    assert out.startswith("signal:") and "expert-only" in out


# ── ACCEPTANCE: one guided command → real (stubbed) delivery ──────────────────


def test_acceptance_connect_telegram_one_command_then_digest(home, stub_wire, capsys):
    # ONE command: paste token + bind chat + prove live (HTTP stubbed to the wire).
    _run([
        "forecast", "connect", "telegram",
        "--token", "123:ABC", "--chat-id", "555",
        "--non-interactive", "--json",
    ])
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["route_id"] == "telegram:555"
    assert result["test_ok"] is True

    # the test delivery actually hit the Telegram sendMessage wire
    assert any(m == "sendMessage" and p["chat_id"] == "555" for m, p in stub_wire)

    # the binding persisted, and a subsequent nightly digest reaches the same chat
    report = notify.deliver_digest("Forecast self-check: 3 questions refreshed.", event_id="sweep-1")
    assert report.delivered and report.delivered[0].route_id == "telegram:555"
    digest_sends = [p for m, p in stub_wire if m == "sendMessage" and p["chat_id"] == "555"]
    assert any("Forecast self-check" in p["text"] for p in digest_sends)


# ── doctor connections section ────────────────────────────────────────────────


def test_config_doctor_has_connections_section(home):
    from forecasting import appconfig

    store = notify.RouteStore(path=home / "notify" / "routes.json")
    store.upsert(notify.NotifyRoute(surface="telegram", target="555", events=("cycle_digest",)))

    report = appconfig.build_doctor_report(appconfig.get_config(), inventory=set())
    assert "connections" in report
    ids = [row["id"] for row in report["connections"]["routes"]]
    assert "telegram:555" in ids

    rendered = appconfig.render_doctor_report(report)
    assert "NOTIFICATION connections" in rendered
    assert "telegram:555" in rendered
