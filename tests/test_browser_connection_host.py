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
