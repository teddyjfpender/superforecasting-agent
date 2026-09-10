"""Registered plugin platforms inherit core and platform-specific tools."""

from types import SimpleNamespace

from gateway.platform_registry import platform_registry
from superforecasting_agent.tooling import toolsets
from superforecasting_agent.tooling.catalogs.core import _CORE_TOOLS
from tools.registry import registry


def test_plugin_platform_fallback_keeps_core_and_own_tools(monkeypatch):
    monkeypatch.setattr(platform_registry, "is_registered", lambda name: name == "fixture-platform")
    monkeypatch.setattr(registry, "_tools", {
        "own": SimpleNamespace(name="fixture_tool", toolset="fixture-platform"),
        "other": SimpleNamespace(name="unrelated_tool", toolset="other-platform"),
    })

    resolved = toolsets.resolve_toolset("hermes-fixture-platform")

    assert set(resolved) == set(_CORE_TOOLS) | {"fixture_tool"}
    assert toolsets.resolve_toolset("hermes-missing-platform") == []
