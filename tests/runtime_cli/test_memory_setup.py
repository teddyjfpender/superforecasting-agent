"""Tests for fork-native memory setup/status guidance."""

from types import SimpleNamespace

from superforecasting_agent.runtime import memory_setup


def test_setup_provider_missing_uses_forecast_native_command(monkeypatch, capsys):
    monkeypatch.setattr(memory_setup, "_get_available_providers", lambda: [])

    memory_setup.cmd_setup_provider("missing-provider")

    out = capsys.readouterr().out
    assert "Run 'superforecasting-agent memory setup' to see available providers." in out
    assert "hermes memory" not in out


def test_setup_without_providers_uses_display_home(monkeypatch, capsys):
    monkeypatch.setattr(memory_setup, "_get_available_providers", lambda: [])
    monkeypatch.setattr(
        memory_setup,
        "display_agent_home",
        lambda: "~/.superforecasting-agent/profiles/research",
    )

    memory_setup.cmd_setup(SimpleNamespace())

    out = capsys.readouterr().out
    assert "No memory provider plugins detected." in out
    assert "Install a plugin to ~/.superforecasting-agent/profiles/research/plugins/" in out
    assert "~/.hermes/plugins" not in out


def test_status_missing_plugin_uses_display_home(monkeypatch, capsys):
    monkeypatch.setattr(memory_setup, "_get_available_providers", lambda: [])
    monkeypatch.setattr(
        memory_setup,
        "display_agent_home",
        lambda: "~/.superforecasting-agent",
    )
    monkeypatch.setattr(
        "superforecasting_agent.runtime.config.load_config",
        lambda: {"memory": {"provider": "mem0"}},
    )

    memory_setup.cmd_status(SimpleNamespace())

    out = capsys.readouterr().out
    assert "Plugin:    NOT installed" in out
    assert "Install the 'mem0' memory plugin to ~/.superforecasting-agent/plugins/" in out
    assert "~/.hermes/plugins" not in out


def test_memory_credentials_use_shared_validation_and_preserve_other_keys(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.delenv('MEMORY_TEST_API_KEY', raising=False)
    path = tmp_path / '.env'
    path.write_text('OTHER_API_KEY=keep\n')
    memory_setup._write_env_vars(path, {'MEMORY_TEST_API_KEY': 'first\nsecond'})
    assert path.read_text() == 'OTHER_API_KEY=keep\nMEMORY_TEST_API_KEY=firstsecond\n'
    with pytest.raises(ValueError, match='Invalid environment variable'):
        memory_setup._write_env_vars(path, {'INVALID KEY': 'bad'})
    with pytest.raises(ValueError, match='active profile'):
        memory_setup._write_env_vars(tmp_path / 'elsewhere.env', {'MEMORY_TEST_API_KEY': 'bad'})
