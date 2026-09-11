"""Configuration edits share value semantics and the latest-file merge owner."""
import pytest
import yaml
from superforecasting_agent.constants import parse_fast_mode_command, parse_service_tier


@pytest.mark.parametrize('raw,expected', [('', 'status'), ('status', 'status'), ('on', 'fast'), ('off', 'normal'), ('fast', 'fast'), ('normal', 'normal'), ('toggle', 'fast')])
def test_fast_command_semantics(raw, expected):
    assert parse_fast_mode_command(raw, current_fast=False) == expected


def test_fast_toggle_and_invalid_argument():
    assert parse_fast_mode_command('toggle', current_fast=True) == 'normal'
    with pytest.raises(ValueError, match='unknown fast mode: typo'):
        parse_fast_mode_command('typo', current_fast=False)


@pytest.mark.parametrize('raw,expected', [('on','priority'), ('priority','priority'), ('FAST','priority'), ('off',None), ('default',None), ('garbage',None)])
def test_shared_service_tier(raw, expected):
    assert parse_service_tier(raw) == expected


def test_tui_setting_merges_latest_config_and_preserves_comments(tmp_path, monkeypatch):
    from tui_gateway import server
    monkeypatch.setattr(server, '_hermes_home', tmp_path)
    monkeypatch.setattr(server._configuration, '_snapshot', None)
    path = tmp_path / 'config.yaml'
    path.write_text('# personal settings\nagent:\n  service_tier: normal\n')
    server._load_cfg()  # Cache predates an independent editor's update.
    path.write_text('# personal settings\nagent:\n  service_tier: normal\ndisplay:\n  skin: mono\n')
    server._write_config_key('agent.service_tier', 'fast')
    assert yaml.safe_load(path.read_text()) == {'agent': {'service_tier': 'fast'}, 'display': {'skin': 'mono'}}
    assert '# personal settings' in path.read_text()
    assert server._load_cfg()['agent']['service_tier'] == 'fast'


def test_tui_invalid_yaml_is_not_replaced(tmp_path, monkeypatch):
    from tui_gateway import server
    monkeypatch.setattr(server, '_hermes_home', tmp_path)
    path = tmp_path / 'config.yaml'
    path.write_text('- invalid root\n')
    with pytest.raises(ValueError, match='root must be a mapping'):
        server._write_config_key('agent.service_tier', 'fast')
    assert path.read_text() == '- invalid root\n'
