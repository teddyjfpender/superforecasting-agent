"""Tests for fork-native proxy command guidance."""

from types import SimpleNamespace

import pytest

from hermes_cli.proxy import cli as proxy_cli


class _FakeAdapter:
    name = "fake"
    display_name = "Fake OAuth"

    def __init__(self, authenticated: bool = False, auth_hint: str | None = None):
        self._authenticated = authenticated
        if auth_hint is not None:
            self.auth_hint = auth_hint

    def is_authenticated(self) -> bool:
        return self._authenticated

    def get_credential(self):
        return SimpleNamespace(expires_at=None)


def test_proxy_help_uses_forecast_native_commands(capsys):
    rc = proxy_cli.cmd_proxy(SimpleNamespace(proxy_command=None))

    assert rc == 0
    err = capsys.readouterr().err
    assert "superforecasting-agent proxy" in err
    assert "hermes proxy" not in err


def test_proxy_status_uses_forecast_native_start_hint(monkeypatch, capsys):
    monkeypatch.setattr(proxy_cli, "ADAPTERS", {"fake": object()})
    monkeypatch.setattr(proxy_cli, "get_adapter", lambda name: _FakeAdapter())

    rc = proxy_cli.cmd_proxy_status(SimpleNamespace())

    assert rc == 0
    out = capsys.readouterr().out
    assert "Superforecasting Agent proxy upstream adapters" in out
    assert "superforecasting-agent proxy start" in out
    assert "Hermes proxy" not in out
    assert "hermes proxy" not in out


def test_proxy_missing_aiohttp_uses_forecast_native_install_hint(monkeypatch, capsys):
    monkeypatch.setattr(proxy_cli, "AIOHTTP_AVAILABLE", False)

    rc = proxy_cli.cmd_proxy_start(SimpleNamespace(provider="fake"))

    assert rc == 1
    err = capsys.readouterr().err
    assert "superforecasting-agent proxy requires aiohttp" in err
    assert "superforecasting-agent[messaging]" in err
    assert "hermes-agent[messaging]" not in err


def test_proxy_unauthenticated_default_hint_is_forecast_native(monkeypatch, capsys):
    monkeypatch.setattr(proxy_cli, "AIOHTTP_AVAILABLE", True)
    monkeypatch.setattr(proxy_cli, "get_adapter", lambda name: _FakeAdapter())

    rc = proxy_cli.cmd_proxy_start(SimpleNamespace(provider="fake"))

    assert rc == 2
    err = capsys.readouterr().err
    assert "Run `superforecasting-agent login fake` first." in err
    assert "hermes login" not in err


def test_proxy_server_missing_aiohttp_message_is_forecast_native(monkeypatch):
    from hermes_cli.proxy import server as proxy_server

    monkeypatch.setattr(proxy_server, "AIOHTTP_AVAILABLE", False)

    with pytest.raises(RuntimeError) as exc:
        proxy_server.create_app(_FakeAdapter())

    message = str(exc.value)
    assert "`superforecasting-agent proxy`" in message
    assert "superforecasting-agent[messaging]" in message
    assert "`hermes proxy`" not in message
