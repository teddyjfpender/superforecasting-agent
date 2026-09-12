"""Activation policy must preserve opt-in and explicit-disable precedence."""

import pytest

from superforecasting_agent.application.plugins import plugin_activation
from superforecasting_agent.configuration.plugin_manifest import PluginManifest


@pytest.mark.parametrize("kind", ["standalone", "backend", "platform", "exclusive", "model-provider"])
@pytest.mark.parametrize("source", ["bundled", "user", "project", "entrypoint", "extension:0"])
def test_explicit_disable_overrides_every_activation_path(kind, source):
    manifest = PluginManifest(name="obsidian", key="category/obsidian", kind=kind, source=source)
    for disabled in ({manifest.name}, {manifest.key}):
        decision = plugin_activation(manifest, enabled={manifest.key}, disabled=disabled)
        assert not decision.load
        assert not decision.enabled
        assert decision.reason == "disabled via config"


@pytest.mark.parametrize("kind", ["standalone", "backend", "platform"])
@pytest.mark.parametrize("source", ["user", "project", "entrypoint", "extension:0"])
def test_unbundled_code_requires_opt_in(kind, source):
    manifest = PluginManifest(name="example", key="category/example", kind=kind, source=source)
    for enabled in (None, set(), {"unrelated"}):
        decision = plugin_activation(manifest, enabled=enabled, disabled=set())
        assert not decision.load
        assert not decision.enabled
        assert "plugins enable category/example`" in decision.reason
    for enabled in ({manifest.name}, {manifest.key}):
        decision = plugin_activation(manifest, enabled=enabled, disabled=set())
        assert decision.load and decision.enabled
        assert decision.reason is None


def test_bundled_and_delegated_kinds_have_distinct_execution_ownership():
    for kind in ("backend", "platform"):
        assert plugin_activation(PluginManifest(name="example", kind=kind, source="bundled"), enabled=None, disabled=()).load
    assert plugin_activation(PluginManifest(name="obsidian", source="bundled"), enabled=None, disabled=()).load
    assert not plugin_activation(PluginManifest(name="example", source="bundled"), enabled=None, disabled=()).load
    model = plugin_activation(PluginManifest(name="example", kind="model-provider"), enabled=None, disabled=())
    assert model.enabled and not model.load
    exclusive = plugin_activation(PluginManifest(name="example", kind="exclusive"), enabled={"example"}, disabled=())
    assert not exclusive.enabled and not exclusive.load
    assert "<category>.provider" in exclusive.reason
