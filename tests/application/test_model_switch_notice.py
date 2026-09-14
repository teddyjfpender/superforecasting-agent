"""User model-selection notices do not impose a gate on automatic recovery."""

from superforecasting_agent.application.model_switch_notice import context_switch_notice


def test_large_context_warns_for_model_or_provider_change_only():
    args = dict(
        current_model="one",
        current_provider="provider",
        target_model="two",
        target_provider="provider",
        tokens=150000,
    )
    assert "150,000" in context_switch_notice(**args)
    assert "uncached" in context_switch_notice(**args)
    assert context_switch_notice(**{**args, "tokens": 100}) == ""
    assert context_switch_notice(**args, threshold=0) == ""
    assert context_switch_notice(**{**args, "target_model": "one"}) == ""
    assert context_switch_notice(**{
        **args,
        "target_model": "one",
        "target_provider": "other",
    })


def test_shared_notice_uses_context_accounting_once_and_preserves_existing_warning(
    monkeypatch,
):
    from types import SimpleNamespace

    from agent import context_usage
    from superforecasting_agent.application.model_switch_notice import (
        attach_context_warning,
    )
    from superforecasting_agent.runtime import config

    monkeypatch.setattr(
        config,
        "load_config",
        lambda: {"display": {"model_switch_warning_tokens": 1000}},
    )
    messages = [{"role": "user", "content": "history"}]
    agent = SimpleNamespace(model="old", provider="p", _session_messages=messages)
    calls = []

    def measured(owner, history):
        assert owner is agent and history is messages
        calls.append(True)
        return 2500

    monkeypatch.setattr(context_usage, "context_tokens", measured)
    result = SimpleNamespace(
        success=True,
        new_model="new",
        target_provider="p",
        warning_message="Existing warning",
    )
    attach_context_warning(result, agent)
    attach_context_warning(result, agent)
    assert len(calls) == 2
    assert result.warning_message.startswith("Existing warning\n")
    assert result.warning_message.count("2,500") == 1
    result.success = False
    attach_context_warning(result, agent)
    assert len(calls) == 2


def test_unavailable_accounting_does_not_block_manual_switch(monkeypatch):
    from types import SimpleNamespace
    from agent import context_usage
    from superforecasting_agent.application.model_switch_notice import (
        attach_context_warning,
    )
    from superforecasting_agent.runtime import config

    monkeypatch.setattr(config, "load_config", lambda: {})

    def unavailable(*args):
        raise ValueError("missing accounting baseline")

    monkeypatch.setattr(context_usage, "context_tokens", unavailable)
    result = SimpleNamespace(success=True, warning_message="Existing warning")
    attach_context_warning(result, SimpleNamespace())
    assert result.warning_message == "Existing warning"
