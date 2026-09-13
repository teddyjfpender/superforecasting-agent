"""Shared search routing and cancellation behavior, with local fake providers."""

import json

import pytest
from types import SimpleNamespace

from agent import web_search_registry as registry
from tools import web_tools


def test_explicit_search_provider_is_not_silently_replaced(monkeypatch):
    calls = []
    config = {"search_backend": "tavily", "backend": "firecrawl"}

    def provider(name, available):
        def search(query, limit):
            calls.append(name)
            return {"success": False, "error": f"{name} credential expired"}
        return SimpleNamespace(name=name, supports_search=lambda: True,
                               is_available=lambda: available, search=search)

    monkeypatch.setattr(registry, "_providers", {"tavily": provider("tavily", False), "firecrawl": provider("firecrawl", True)})
    monkeypatch.setattr(registry, "_read_config_key", lambda *path: config.get(path[-1]))
    monkeypatch.setattr(web_tools, "_load_web_config", lambda: config)
    monkeypatch.setattr(web_tools, "_is_backend_available", lambda name: name == "firecrawl")
    result = json.loads(web_tools.web_search_tool("test"))
    assert calls == ["tavily"]
    assert result == {"success": False, "error": "tavily credential expired"}


@pytest.mark.parametrize("surface", ["application", "tool", "supervisor"])
@pytest.mark.parametrize("mode", ["before", "during", "exception"])
def test_cancelled_search_cannot_supply_evidence(monkeypatch, surface, mode):
    from forecasting.supervisor_search import build_supervisor_search_runner
    from superforecasting_agent.tooling.web_search import search_web
    from tools.interrupt import set_interrupt

    calls = []
    def search(query, limit):
        calls.append(query)
        set_interrupt(True)
        if mode == "exception":
            raise RuntimeError("interrupted stream")
        return {"success": True, "data": {"web": [{"title": "late evidence", "url": "https://example.org/report"}]}}
    monkeypatch.setattr(registry, "get_active_search_provider", lambda: SimpleNamespace(name="local", search=search))
    try:
        set_interrupt(mode == "before")
        if surface == "supervisor":
            assert build_supervisor_search_runner()(["query"]) == []
        else:
            result = search_web("query") if surface == "application" else json.loads(web_tools.web_search_tool("query"))
            assert result == {"success": False, "error": "Interrupted"}
        assert calls == ([] if mode == "before" else ["query"])
    finally:
        set_interrupt(False)


def test_diagnostic_failure_does_not_discard_search(monkeypatch):
    result = {"success": True, "data": {"web": []}}
    monkeypatch.setattr(registry, "get_active_search_provider", lambda: SimpleNamespace(name="local", search=lambda *args: result))
    def fail():
        raise OSError("diagnostic volume full")
    monkeypatch.setattr(web_tools._debug, "save", fail)
    assert json.loads(web_tools.web_search_tool("query")) == result


@pytest.mark.parametrize("payload", [[], {"success": "false", "data": {"web": []}}, {"success": True, "data": None}, {"success": True, "data": {"web": "not rows"}}])
def test_malformed_provider_results_are_failures(monkeypatch, payload):
    from superforecasting_agent.tooling.web_search import search_web
    monkeypatch.setattr(registry, "get_active_search_provider", lambda: SimpleNamespace(name="local", search=lambda *args: payload))
    result = search_web("query")
    assert result.get("success") is not True
    assert "Search provider returned" in result["error"]


def test_provider_error_cannot_supply_supervisor_evidence(monkeypatch):
    from forecasting.supervisor_search import build_supervisor_search_runner
    result = {"success": True, "error": "partial failure", "data": {"web": [{"title": "unusable", "url": "https://example.org/report"}]}}
    monkeypatch.setattr(registry, "get_active_search_provider", lambda: SimpleNamespace(name="local", search=lambda *args: result))
    assert build_supervisor_search_runner()(["query"]) == []


@pytest.mark.parametrize("configured", ["tavily", "TAVILY"])
def test_registry_reads_profile_search_override(monkeypatch, tmp_path, configured):
    from superforecasting_agent import constants, profile_paths
    from superforecasting_agent.tooling.web_search import search_web

    (tmp_path / "config.yaml").write_text(f"web:\n  backend: firecrawl\n  search_backend: {configured}\n", encoding="utf-8")
    monkeypatch.setattr(constants, "get_agent_home", lambda: tmp_path)
    monkeypatch.setattr(profile_paths, "ignore_user_config_requested", lambda: False)
    calls = []
    def provider(name):
        def search(*args):
            calls.append(name)
            return {"success": True, "data": {"web": []}}
        return SimpleNamespace(name=name, search=search, supports_search=lambda: True, is_available=lambda: True)
    monkeypatch.setattr(registry, "_providers", {name: provider(name) for name in ("tavily", "firecrawl")})
    assert search_web("query")["success"] is True
    assert calls == ["tavily"]
