"""Forecast panels and interactive model selection share provider syntax."""

import pytest

from forecasting.quorum.panels import _split_provider_model, validate_panel_models
from superforecasting_agent.runtime.models import parse_model_input


@pytest.mark.parametrize('value, expected', [
    ('glm:glm-5', ('zai', 'glm-5')),
    ('step:step-3.5-flash', ('stepfun', 'step-3.5-flash')),
    ('custom: local : qwen-model ', ('custom:local', 'qwen-model')),
    ('custom:qwen-model', ('custom', 'qwen-model')),
    ('custom:name:', ('custom', 'name:')),
    ('openrouter:vendor/model:preview', ('openrouter', 'vendor/model:preview')),
    ('vendor/model:preview', (None, 'vendor/model:preview')),
    ('http://localhost:8080/model', (None, 'http://localhost:8080/model')),
])
def test_explicit_model_syntax_matches_interactive_selection(value, expected):
    assert _split_provider_model(value) == expected
    assert parse_model_input(value, 'active') == (expected[0] or 'active', expected[1])


def test_panel_alias_is_validated_against_canonical_connected_provider():
    validate_panel_models(['glm:glm-5'], providers=[{'id': 'zai', 'authenticated': True}])


@pytest.mark.parametrize('two_turn', [False, True])
def test_named_endpoint_reaches_agent_construction_unchanged(monkeypatch, two_turn):
    from unittest.mock import Mock
    from agent import agent_factory
    from forecasting.quorum import make_aiagent_runner

    agent = Mock()
    agent.run_conversation.return_value = {'final_response': 'fixture answer'}
    factory = Mock(return_value=agent)
    monkeypatch.setattr(agent_factory, 'build_agent', factory)
    runner = make_aiagent_runner(requested_provider='fallback')
    if two_turn:
        assert runner.two_turn('custom:local:qwen-model', 'system', 'blind', lambda _: 'reconcile') == ('fixture answer', 'fixture answer')
    else:
        assert runner('custom:local:qwen-model', 'system', 'question') == 'fixture answer'
    assert factory.call_args.kwargs['requested_provider'] == 'custom:local'
    assert factory.call_args.kwargs['model'] == 'qwen-model'
    assert factory.call_count == 1
