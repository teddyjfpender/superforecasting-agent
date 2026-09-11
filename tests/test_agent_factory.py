"""build_agent() — the single resolve->construct path for an AIAgent. Tested without
importing the heavy run_agent module by patching the _aiagent_cls indirection."""

from __future__ import annotations

import agent.agent_factory as af
import pytest


def test_resolve_and_map_runtime_maps_and_drops_none():
    rt = {
        "provider": "anthropic", "base_url": "u", "api_key": "k", "api_mode": "messages",
        "command": None, "args": None, "credential_pool": None, "source": "env",
    }
    # the 7 mapped keys, None dropped (so the AIAgent default applies), 'source' ignored
    assert af.resolve_and_map_runtime(rt) == {
        "provider": "anthropic", "base_url": "u", "api_key": "k", "api_mode": "messages",
    }


def test_resolve_and_map_runtime_passes_callable_api_key_verbatim():
    token_provider = lambda: "tok"  # noqa: E731 (Azure Entra-ID style)
    mapped = af.resolve_and_map_runtime({"provider": "azure", "api_key": token_provider, "base_url": "u", "api_mode": "responses"})
    assert mapped["api_key"] is token_provider


def test_command_args_map_to_acp_kwargs():
    mapped = af.resolve_and_map_runtime({"provider": "copilot", "command": "cmd", "args": ["--x"], "base_url": "u", "api_key": "k", "api_mode": "m"})
    assert mapped["acp_command"] == "cmd" and mapped["acp_args"] == ["--x"]


def _fake_agent(monkeypatch):
    captured: dict = {}

    class _Fake:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(af, "_aiagent_cls", lambda: _Fake)
    return captured


def test_build_agent_forwards_runtime_and_kwargs(monkeypatch):
    captured = _fake_agent(monkeypatch)
    af.build_agent(
        {"provider": "anthropic", "base_url": "u", "api_key": "k", "api_mode": "messages"},
        model="m", enabled_toolsets=["x"], session_id="s", platform="tui",
    )
    assert captured["model"] == "m"
    assert captured["provider"] == "anthropic" and captured["base_url"] == "u"
    assert captured["enabled_toolsets"] == ["x"] and captured["session_id"] == "s" and captured["platform"] == "tui"


def test_build_agent_explicit_kwarg_wins_over_runtime(monkeypatch):
    captured = _fake_agent(monkeypatch)
    af.build_agent({"api_key": "runtime-key", "provider": "p"}, model="m", api_key="explicit-key")
    assert captured["api_key"] == "explicit-key"  # caller override beats the mapped runtime value


def test_build_agent_rejects_incompatible_codex_model_before_construction(monkeypatch):
    _fake_agent(monkeypatch)
    with pytest.raises(ValueError, match="not compatible with openai-codex"):
        af.build_agent(
            {"provider": "openai-codex"}, model="anthropic/claude-opus-4-8"
        )


def test_tenant_runtime_set_get_clear_isolated():
    import agent.tenant_runtime as tr

    assert tr.get_credential_context() is None  # unset = process-global default
    token = tr.set_tenant_runtime(credential={"provider": "anthropic", "api_key": "k"}, toggles={"VOICE": "1"})
    try:
        assert tr.get_credential_context() == {"provider": "anthropic", "api_key": "k"}
        assert tr.get_toggle("VOICE") == "1"
        assert tr.get_toggle("MODEL", "fallback") == "fallback"
    finally:
        tr.clear_tenant_runtime(token)
    assert tr.get_credential_context() is None and tr.get_toggle("VOICE") is None


def test_build_agent_reads_tenant_runtime_credential(monkeypatch):
    import agent.tenant_runtime as tr

    captured = _fake_agent(monkeypatch)
    calls = {}

    def _fake_resolve(*, requested=None, explicit_api_key=None, explicit_base_url=None, target_model=None):
        calls.update(requested=requested, explicit_api_key=explicit_api_key)
        return {"provider": requested, "api_key": "resolved", "base_url": "b", "api_mode": "messages"}

    monkeypatch.setattr("superforecasting_agent.runtime.runtime_provider.resolve_runtime_provider", _fake_resolve)
    token = tr.set_tenant_runtime(credential={"provider": "anthropic", "api_key": "tenant-A-key"})
    try:
        af.build_agent(model="m")  # no explicit credential_context -> reads the contextvar
    finally:
        tr.clear_tenant_runtime(token)
    assert calls["explicit_api_key"] == "tenant-A-key" and calls["requested"] == "anthropic"
    assert captured["api_key"] == "resolved"


def test_build_agent_resolves_when_runtime_none(monkeypatch):
    captured = _fake_agent(monkeypatch)
    calls = {}

    def _fake_resolve(*, requested=None, explicit_api_key=None, explicit_base_url=None, target_model=None):
        calls.update(requested=requested, explicit_api_key=explicit_api_key, explicit_base_url=explicit_base_url, target_model=target_model)
        return {"provider": "anthropic", "api_key": "resolved", "base_url": "b", "api_mode": "messages"}

    monkeypatch.setattr("superforecasting_agent.runtime.runtime_provider.resolve_runtime_provider", _fake_resolve)
    af.build_agent(model="m", requested_provider="anthropic", credential_context={"api_key": "tenant-key", "provider": "anthropic"})
    # credential_context feeds the resolver (per-tenant seam) and the resolved key is used
    assert calls["explicit_api_key"] == "tenant-key" and calls["requested"] == "anthropic"
    assert captured["api_key"] == "resolved"


def test_factory_and_legacy_import_share_runtime_state(monkeypatch):
    from agent import runtime
    import run_agent

    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(run_agent, 'AIAgent', fake_agent)
    assert runtime.AIAgent is fake_agent
    result = af.build_agent({'provider': 'fixture'}, model='fixture-model')
    assert result == {'provider': 'fixture', 'model': 'fixture-model'}
