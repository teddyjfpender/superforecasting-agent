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


@pytest.mark.parametrize('provider', ['openrouter', 'nous', 'ai-gateway'])
def test_aggregator_does_not_validate_an_explicit_different_provider(provider):
    from forecasting.models import ValidationError

    with pytest.raises(ValidationError, match='anthropic:fixture'):
        validate_panel_models(['anthropic:fixture'], providers=[{'id': provider}])
    validate_panel_models([f'{provider}:vendor/fixture', 'vendor/fixture'], providers=[{'id': provider}])


def test_unauthenticated_catalog_row_cannot_validate_a_pinned_provider():
    from forecasting.models import ValidationError

    with pytest.raises(ValidationError, match='zai:fixture'):
        validate_panel_models(['zai:fixture'], providers=[{'id': 'zai', 'authenticated': False}])


def test_named_endpoint_requires_its_exact_provider_identity():
    from forecasting.models import ValidationError

    with pytest.raises(ValidationError, match='custom:local:fixture'):
        validate_panel_models(['custom:local:fixture'], providers=[{'id': 'custom'}])
    validate_panel_models(['custom:local:fixture'], providers=[{'id': 'custom:local'}])


def test_configured_panel_checks_judge_against_same_snapshot(monkeypatch):
    from forecasting.models import ValidationError
    from forecasting.quorum import panels

    calls = []
    def changing_credentials():
        calls.append(True)
        return [{'id': 'anthropic' if len(calls) == 1 else 'openai-codex'}]
    monkeypatch.setattr(panels, 'available_providers_detail', changing_credentials)
    with pytest.raises(ValidationError, match='openai-codex:judge'):
        panels.resolve_configured_panel(
            panel_models='anthropic:panelist', judge_model='openai-codex:judge',
        )
    assert len(calls) == 1


def test_pure_panel_routes_need_no_catalog_or_credentials():
    from forecasting.models import ValidationError
    from forecasting.panel_selection import validate_panel_routes

    names = {'glm', 'zai', 'custom', 'openrouter'}
    validate_panel_routes(['glm:fixture'], [{'id': 'zai'}], known_providers=names)
    validate_panel_routes(['vendor/model:preview'], [], known_providers=names)
    validate_panel_routes(['custom:Desk:fixture'], [{'id': 'custom:Desk'}], known_providers=names)
    with pytest.raises(ValidationError, match='custom:local:fixture'):
        validate_panel_routes(['custom:local:fixture'], [{'id': 'custom'}], known_providers=names)
    with pytest.raises(ValidationError, match='zai:fixture'):
        validate_panel_routes(['zai:fixture'], [{'id': 'zai', 'authenticated': 'true'}], known_providers=names)
