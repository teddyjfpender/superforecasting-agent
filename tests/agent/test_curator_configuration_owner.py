"""Curator settings read the owning profile without CLI configuration setup."""

from agent import curator, curator_backup
from superforecasting_agent.runtime import config


def test_readers_use_explicit_profile_without_cli_setup(tmp_path, monkeypatch):
    path = tmp_path / 'config.yaml'
    path.write_text('curator:\n  enabled: false\n  interval_hours: 13\n  backup:\n    enabled: false\n    keep: 9\n', encoding='utf-8')
    before = path.read_bytes()
    entries_before = set(tmp_path.iterdir())
    monkeypatch.setattr(curator, 'get_agent_home', lambda: tmp_path)
    monkeypatch.setattr(curator_backup, 'get_agent_home', lambda: tmp_path)
    def forbidden():
        raise AssertionError('CLI configuration must not initialize')
    monkeypatch.setattr(config, 'load_config', forbidden)
    assert curator.is_enabled() is False
    assert curator.get_interval_hours() == 13
    assert curator_backup.is_enabled() is False
    assert curator_backup._load_config()['keep'] == 9
    assert path.read_bytes() == before
    assert set(tmp_path.iterdir()) == entries_before
