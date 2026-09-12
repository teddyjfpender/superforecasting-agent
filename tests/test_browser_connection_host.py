"""Connection commands must report incomplete cleanup without false success."""

import os
from types import SimpleNamespace

import pytest

from superforecasting_agent.hosting.browser_connection import change_browser_endpoint


def test_failed_initial_cleanup_preserves_setting():
    env = {"BROWSER_CDP_URL": "old"}
    def fail():
        raise OSError("still running")
    with pytest.raises(OSError):
        change_browser_endpoint(None, environment=env, cleanup=fail)
    assert env["BROWSER_CDP_URL"] == "old"


def test_failed_post_publication_cleanup_is_explicit():
    env = {"BROWSER_CDP_URL": "old"}
    observed = []
    def cleanup():
        observed.append(env.get("BROWSER_CDP_URL"))
        if len(observed) == 2:
            raise OSError("still running")
    with pytest.raises(RuntimeError, match="changed, but cleanup is incomplete"):
        change_browser_endpoint("new", environment=env, cleanup=cleanup)
    assert observed == ["old", "new"]
    assert env["BROWSER_CDP_URL"] == "new"


@pytest.mark.parametrize("interface", ["cli", "tui"])
def test_supervisor_failure_reaches_connection_consumer(monkeypatch, capsys, interface):
    from tools import browser_tool, browser_supervisor
    from superforecasting_agent.runtime.browser_commands import _handle_browser_command

    monkeypatch.setenv("BROWSER_CDP_URL", "http://existing:9222")
    monkeypatch.setattr(browser_tool, "_active_sessions", {})
    def fail():
        raise RuntimeError("supervisor still running")
    monkeypatch.setattr(browser_supervisor.SUPERVISOR_REGISTRY, "stop_all", fail)
    if interface == "cli":
        _handle_browser_command(SimpleNamespace(), "/browser disconnect")
        output = capsys.readouterr().out
        assert "disconnect failed" in output
        assert "Browser disconnected" not in output
    else:
        from tui_gateway import server
        response = server.handle_request({"id": 1, "method": "browser.manage", "params": {"action": "disconnect"}})
        assert response["error"]["code"] == 5031
        assert "supervisor still running" in response["error"]["message"]
        assert "result" not in response
    assert os.environ["BROWSER_CDP_URL"] == "http://existing:9222"


@pytest.mark.parametrize("interface", ["cli", "tui"])
def test_disconnect_suppresses_saved_endpoint_without_rewriting_profile(monkeypatch, tmp_path, interface):
    from tools import browser_tool
    from superforecasting_agent.runtime import browser_connect
    from superforecasting_agent.runtime.browser_commands import _handle_browser_command
    from tui_gateway import server

    profile = tmp_path / "profile"
    profile.mkdir()
    config = profile / "config.yaml"
    original = "browser:\n  cdp_url: ws://saved/devtools/browser/original\n"
    config.write_text(original, encoding="utf-8")
    monkeypatch.setattr(browser_connect, "get_agent_home", lambda: profile)
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    monkeypatch.setattr(browser_tool, "cleanup_all_browsers", lambda: None)
    assert browser_tool._get_cdp_override() == "ws://saved/devtools/browser/original"
    if interface == "cli":
        _handle_browser_command(SimpleNamespace(), "/browser disconnect")
    else:
        reply = server.handle_request({"id": 1, "method": "browser.manage", "params": {"action": "disconnect"}})
        assert reply["result"] == {"connected": False}
    assert browser_tool._get_cdp_override() == ""
    status = server.handle_request({"id": 2, "method": "browser.manage", "params": {"action": "status"}})
    assert status["result"] == {"connected": False, "url": ""}
    browser_connect.set_browser_endpoint("ws://new/devtools/browser/new")
    assert browser_tool._get_cdp_override() == "ws://new/devtools/browser/new"
    assert config.read_text(encoding="utf-8") == original
    # A new process starts without the runtime override and inherits config.
    monkeypatch.delenv("BROWSER_CDP_URL")
    assert browser_connect.get_browser_endpoint() == "ws://saved/devtools/browser/original"


def test_cli_retries_cleanup_after_failed_disconnect_publication(monkeypatch, capsys):
    from tools import browser_tool
    from superforecasting_agent.runtime.browser_commands import _handle_browser_command

    monkeypatch.setenv("BROWSER_CDP_URL", "http://old:9222")
    calls = []
    def cleanup():
        calls.append(os.environ.get("BROWSER_CDP_URL"))
        if len(calls) == 2:
            raise RuntimeError("stop pending")
    monkeypatch.setattr(browser_tool, "cleanup_all_browsers", cleanup)
    _handle_browser_command(SimpleNamespace(), "/browser disconnect")
    assert "cleanup is incomplete" in capsys.readouterr().out
    assert os.environ["BROWSER_CDP_URL"] == ""
    _handle_browser_command(SimpleNamespace(), "/browser disconnect")
    assert len(calls) == 4
    assert "failed" not in capsys.readouterr().out
