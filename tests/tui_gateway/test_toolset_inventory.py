"""Tool inspection reflects the same selection before and after agent build."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.runtime import RuntimeHost
from tui_gateway import server


@pytest.mark.parametrize("method", ["tools.list", "toolsets.list", "superforecasting_agent.tooling.toolsets.list"])
@pytest.mark.parametrize("agent,configured,expected", [
    (None, ["forecasting"], [True, False]),
    (None, [], [False, False]),
    (SimpleNamespace(enabled_toolsets=[]), ["forecasting"], [False, False]),
    (SimpleNamespace(enabled_toolsets=["web"]), ["forecasting"], [False, True]),
    (SimpleNamespace(enabled_toolsets=None), [], [True, True]),
])
def test_inventory_uses_current_selection(monkeypatch, method, agent, configured, expected):
    monkeypatch.setattr(server, "_host", RuntimeHost())
    server._host.sessions["fixture"] = {"agent": agent}
    monkeypatch.setattr(server, "_load_enabled_toolsets", lambda: configured)
    monkeypatch.setattr("superforecasting_agent.tooling.toolsets.get_all_toolsets", lambda: {"forecasting": {}, "web": {}})
    monkeypatch.setattr("superforecasting_agent.tooling.toolsets.get_toolset_info", lambda name: {
        "description": name, "tool_count": 1, "resolved_tools": [name + "_tool"],
    })
    build = Mock(side_effect=AssertionError("inspection must not build an agent"))
    monkeypatch.setattr(server, "_start_agent_build", build)
    response = server.handle_request({"id": 1, "method": method, "params": {"session_id": "fixture"}})
    assert [item["enabled"] for item in response["result"]["toolsets"]] == expected
    build.assert_not_called()


@pytest.mark.parametrize("agent,expected", [(None, ["forecasting"]), (SimpleNamespace(enabled_toolsets=[]), [])])
def test_tools_show_passes_the_same_selection_to_resolution(monkeypatch, agent, expected):
    monkeypatch.setattr(server, "_host", RuntimeHost())
    server._host.sessions["fixture"] = {"agent": agent}
    monkeypatch.setattr(server, "_load_enabled_toolsets", lambda: ["forecasting"])
    resolve = Mock(return_value=[])
    monkeypatch.setattr("superforecasting_agent.tooling.runtime.get_tool_definitions", resolve)
    response = server.handle_request({"id": 1, "method": "tools.show", "params": {"session_id": "fixture"}})
    assert "error" not in response
    resolve.assert_called_once_with(enabled_toolsets=expected, quiet_mode=True)
