"""Tests for fork-native memory setup/status guidance."""

from types import SimpleNamespace

from hermes_cli import memory_setup


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
        "display_hermes_home",
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
        "display_hermes_home",
        lambda: "~/.superforecasting-agent",
    )
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"memory": {"provider": "mem0"}},
    )

    memory_setup.cmd_status(SimpleNamespace())

    out = capsys.readouterr().out
    assert "Plugin:    NOT installed" in out
    assert "Install the 'mem0' memory plugin to ~/.superforecasting-agent/plugins/" in out
    assert "~/.hermes/plugins" not in out
