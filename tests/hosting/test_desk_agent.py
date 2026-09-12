"""Hosted launch policy works without an RPC server or terminal runtime."""

from unittest.mock import Mock

from superforecasting_agent.hosting.desk_agent import build_desk_agent, startup_runtime


def test_host_uses_supplied_launch_settings_and_borrows_resources(monkeypatch):
    from agent import agent_factory

    allocated = Mock()
    monkeypatch.setattr(agent_factory, '_aiagent_cls', lambda: allocated)
    resolver = Mock(return_value={'provider': 'fixture', 'api_key': 'fixture-key'})
    monkeypatch.setattr('superforecasting_agent.runtime.runtime_provider.resolve_runtime_provider', resolver)
    toolsets = Mock(return_value=['web'])
    monkeypatch.setattr('superforecasting_agent.tooling.startup_selection.resolve_startup_toolsets', toolsets)
    monkeypatch.setenv('SUPERFORECASTING_AGENT_MODEL', 'must-not-read-this')
    monkeypatch.setenv('SUPERFORECASTING_AGENT_TUI_MAX_TURNS', '999')
    config = {'model': {'default': 'saved'}, 'agent': {'max_turns': 4, 'system_prompt': 'desk instructions'}}
    database, callback = object(), object()
    warn = Mock()
    build_desk_agent(
        config, overrides={'model': 'launch-model', 'provider': 'fixture', 'max_turns': '7',
                           'ignore_rules': '1', 'pass_session_id': 'true',
                           'checkpoints': 'yes', 'tool_progress': 'verbose', 'toolsets': 'web'},
        session_id='durable-owner', session_db=database,
        callbacks={'stream_delta_callback': callback}, warn=warn,
    )
    options = allocated.call_args.kwargs
    assert options['model'] == 'launch-model'
    assert options['provider'] == 'fixture'
    assert options['max_iterations'] == 7
    assert options['session_id'] == 'durable-owner'
    assert options['session_db'] is database
    assert options['stream_delta_callback'] is callback
    assert options['enabled_toolsets'] == ['web']
    assert options['verbose_logging'] is True
    assert options['skip_context_files'] is options['skip_memory'] is True
    assert options['checkpoints_enabled'] is options['pass_session_id'] is True
    assert 'desk instructions' in options['ephemeral_system_prompt']
    assert resolver.call_args.kwargs['config']['agent']['max_turns'] == 4
    assert config == {'model': {'default': 'saved'}, 'agent': {'max_turns': 4, 'system_prompt': 'desk instructions'}}
    assert toolsets.call_args.kwargs['warn'] is warn


def test_static_detection_failure_retains_explicit_model(monkeypatch):
    detector = Mock(side_effect=RuntimeError('catalog unavailable'))
    monkeypatch.setattr('superforecasting_agent.runtime.models.detect_static_provider_for_model', detector)
    assert startup_runtime({'model': {'provider': 'saved-provider'}}, {'model': 'requested'}) == ('requested', None)
    detector.assert_called_once_with('requested', 'saved-provider')
