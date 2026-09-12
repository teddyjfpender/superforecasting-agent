"""Malformed platform manifests cannot hide other plugins' environment settings."""

from superforecasting_agent.configuration.plugin_environment import environment_metadata
from superforecasting_agent.storage.plugin_environment import read_platform_environment


def test_metadata_skips_invalid_entries_and_preserves_required_precedence():
    result = environment_metadata({
        'label': 'Example',
        'requires_env': [None, {'name': []}, {'name': ''}, 'EXAMPLE_TOKEN',
                         {'name': 'PUBLIC_KEY', 'password': False}],
        'optional_env': [{'name': 'EXAMPLE_TOKEN', 'password': False}],
    }, fallback_label='fallback')
    assert set(result) == {'EXAMPLE_TOKEN', 'PUBLIC_KEY'}
    assert result['EXAMPLE_TOKEN']['password'] is True
    assert result['PUBLIC_KEY']['password'] is False
    assert environment_metadata([], fallback_label='bad') == {}
    assert environment_metadata({'requires_env': 'TOKEN'}, fallback_label='bad') == {}


def test_bad_manifest_does_not_hide_later_plugins(tmp_path):
    for name, text in [('a-invalid', '- not-a-mapping\n'), ('b-syntax', '{broken'),
                       ('c-good', 'requires_env:\n  - VALID_TOKEN\n')]:
        child = tmp_path / name
        child.mkdir()
        (child / 'plugin.yaml').write_text(text, encoding='utf-8')
        (child / '__init__.py').write_text('raise AssertionError("must not import")\n', encoding='utf-8')
    assert read_platform_environment(tmp_path)['VALID_TOKEN']['password'] is True


def test_runtime_extension_preserves_builtin_metadata(tmp_path, monkeypatch):
    from superforecasting_agent.runtime import config
    directory = tmp_path / 'plugins' / 'platforms' / 'example'
    directory.mkdir(parents=True)
    (directory / 'plugin.yml').write_text('requires_env:\n  - OPENROUTER_API_KEY\n  - NEW_PLATFORM_TOKEN\n', encoding='utf-8')
    original = {'description': 'built-in wins'}
    catalog = {'OPENROUTER_API_KEY': original}
    monkeypatch.setattr(config, 'OPTIONAL_ENV_VARS', catalog)
    monkeypatch.setattr(config, '_platform_plugin_env_vars_injected', False)
    monkeypatch.setattr(config, 'get_install_root', lambda: tmp_path)
    config._inject_platform_plugin_env_vars()
    assert catalog['OPENROUTER_API_KEY'] is original
    assert catalog['NEW_PLATFORM_TOKEN']['password'] is True
