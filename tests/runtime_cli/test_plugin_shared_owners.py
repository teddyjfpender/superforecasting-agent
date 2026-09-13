"""Plugin policy reads and command conflicts use shared owners."""

from superforecasting_agent.runtime import commands, config, plugins


def test_plugin_settings_do_not_initialize_cli_configuration(tmp_path, monkeypatch):
    path = tmp_path / 'config.yaml'
    path.write_text('plugins:\n  enabled: [example]\n  disabled: [blocked]\n', encoding='utf-8')
    before = path.read_bytes()
    entries = set(tmp_path.iterdir())
    monkeypatch.setattr(plugins, 'get_agent_home', lambda: tmp_path)
    def forbidden():
        raise AssertionError('CLI loader must not run')
    monkeypatch.setattr(config, 'load_config', forbidden)
    assert plugins._get_enabled_plugins() == {'example'}
    assert plugins._get_disabled_plugins() == {'blocked'}
    assert path.read_bytes() == before
    assert set(tmp_path.iterdir()) == entries


def test_builtin_alias_conflicts_do_not_depend_on_cli_registry(monkeypatch):
    def forbidden(*args):
        raise AssertionError('CLI registry must not run')
    monkeypatch.setattr(commands, 'resolve_command', forbidden)
    manager = plugins.PluginManager()
    context = plugins.PluginContext(plugins.PluginManifest(name='example', source='user'), manager)
    context.register_command('provider', lambda args: args)
    assert 'provider' not in manager._plugin_commands
    context.register_command('example-action', lambda args: args)
    assert 'example-action' in manager._plugin_commands
