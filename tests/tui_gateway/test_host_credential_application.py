"""Host credential refresh keeps model selection and credential generations aligned."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.credentials import refresh_credentials


@pytest.mark.parametrize("current", ["openai-codex", "openai", "codex"])
def test_refresh_preserves_model_and_replaces_pool_after_client_switch(current):
    old_pool, fresh_pool = object(), object()
    agent = SimpleNamespace(
        provider=current, model="selected-model", _credential_pool=old_pool
    )

    def switch(**kwargs):
        assert agent._credential_pool is old_pool
        assert kwargs == dict(
            new_model="selected-model",
            new_provider="openai-codex",
            api_key="fresh-token",
            base_url="https://example.test",
            api_mode="codex_responses",
        )

    agent.switch_model = Mock(side_effect=switch)
    resolve = Mock(
        return_value=dict(
            provider="openai-codex",
            api_key="fresh-token",
            base_url="https://example.test",
            api_mode="codex_responses",
            credential_pool=fresh_pool,
        )
    )
    assert refresh_credentials(agent, "openai-codex", resolve=resolve)
    resolve.assert_called_once_with(requested=current, target_model="selected-model")
    agent.switch_model.assert_called_once()
    assert agent._credential_pool is fresh_pool


@pytest.mark.parametrize(
    "authenticated,current",
    [
        ("openai-codex", "anthropic"),
        ("anthropic", "openai-codex"),
        ("", "openai-codex"),
    ],
)
def test_unrelated_sign_in_never_resolves_or_mutates_agent(authenticated, current):
    pool = object()
    agent = SimpleNamespace(
        provider=current, model="unchanged", _credential_pool=pool, switch_model=Mock()
    )
    resolve = Mock()
    assert not refresh_credentials(agent, authenticated, resolve=resolve)
    resolve.assert_not_called()
    agent.switch_model.assert_not_called()
    assert agent._credential_pool is pool


@pytest.mark.parametrize("failure", ["resolve", "switch"])
def test_failed_refresh_keeps_prior_pool_and_reports_failure(failure):
    pool = object()
    agent = SimpleNamespace(
        provider="openai-codex",
        model="selected-model",
        _credential_pool=pool,
        switch_model=Mock(
            side_effect=RuntimeError("switch failed") if failure == "switch" else None
        ),
    )
    resolve = Mock(
        return_value={"credential_pool": object()},
        side_effect=RuntimeError("resolve failed") if failure == "resolve" else None,
    )
    with pytest.raises(RuntimeError, match=failure + " failed"):
        refresh_credentials(agent, "openai-codex", resolve=resolve)
    assert agent._credential_pool is pool
    if failure == "resolve":
        agent.switch_model.assert_not_called()
