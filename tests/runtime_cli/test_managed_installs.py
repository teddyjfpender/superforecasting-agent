from types import SimpleNamespace
from unittest.mock import patch

from superforecasting_agent.runtime.config import (
    format_managed_message,
    get_managed_system,
    recommended_update_command,
)
from superforecasting_agent.runtime.main import cmd_update
from tools.skills_hub import OptionalSkillSource


def test_get_managed_system_homebrew(monkeypatch):
    monkeypatch.setenv("HERMES_MANAGED", "homebrew")

    assert get_managed_system() == "Homebrew"
    assert recommended_update_command() == "brew upgrade superforecasting-agent"


def test_get_managed_system_prefers_forecast_native_alias(monkeypatch):
    monkeypatch.setenv("HERMES_MANAGED", "true")
    monkeypatch.setenv("FORECAST_MANAGED", "nix")
    monkeypatch.setenv("SUPERFORECASTING_AGENT_MANAGED", "homebrew")

    assert get_managed_system() == "Homebrew"


def test_format_managed_message_homebrew(monkeypatch):
    monkeypatch.setenv("HERMES_MANAGED", "homebrew")

    message = format_managed_message("update Superforecasting Agent")

    assert "managed by Homebrew" in message
    assert "brew upgrade superforecasting-agent" in message


def test_format_managed_message_uses_forecast_native_env_hint(monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_MANAGED", "true")

    message = format_managed_message("edit config")

    assert "managed by NixOS" in message
    assert "(SUPERFORECASTING_AGENT_MANAGED=true)" in message
    assert "HERMES_MANAGED=true" not in message


def test_recommended_update_command_defaults_to_superforecasting_update(monkeypatch):
    monkeypatch.delenv("SUPERFORECASTING_AGENT_MANAGED", raising=False)
    monkeypatch.delenv("FORECAST_MANAGED", raising=False)
    monkeypatch.delenv("HERMES_MANAGED", raising=False)

    # Also short-circuit the .managed marker path — CI runners may have an
    # ambient ~/.hermes/.managed if a prior test left HERMES_HOME pointing
    # somewhere with that marker, which would make get_managed_update_command()
    # return "Update your Nix flake input ..." instead of falling through to
    # detect_install_method().
    with patch("superforecasting_agent.runtime.config.get_managed_update_command", return_value=None), \
         patch("superforecasting_agent.runtime.config.detect_install_method", return_value="git"):
        assert recommended_update_command() == "superforecasting-agent update"


def test_cmd_update_blocks_managed_homebrew(monkeypatch, capsys):
    monkeypatch.setenv("HERMES_MANAGED", "homebrew")

    with patch("superforecasting_agent.runtime.main.subprocess.run") as mock_run:
        cmd_update(SimpleNamespace())

    assert not mock_run.called
    captured = capsys.readouterr()
    assert "managed by Homebrew" in captured.err
    assert "brew upgrade superforecasting-agent" in captured.err


def test_optional_skill_source_honors_forecast_env_override(monkeypatch, tmp_path):
    optional_dir = tmp_path / "optional-skills"
    optional_dir.mkdir()
    monkeypatch.delenv("HERMES_OPTIONAL_SKILLS", raising=False)
    monkeypatch.delenv("FORECAST_OPTIONAL_SKILLS", raising=False)
    monkeypatch.setenv("SUPERFORECASTING_AGENT_OPTIONAL_SKILLS", str(optional_dir))

    source = OptionalSkillSource()

    assert source._optional_dir == optional_dir


def test_optional_skill_source_honors_legacy_env_override(monkeypatch, tmp_path):
    optional_dir = tmp_path / "optional-skills"
    optional_dir.mkdir()
    monkeypatch.delenv("SUPERFORECASTING_AGENT_OPTIONAL_SKILLS", raising=False)
    monkeypatch.delenv("FORECAST_OPTIONAL_SKILLS", raising=False)
    monkeypatch.setenv("HERMES_OPTIONAL_SKILLS", str(optional_dir))

    source = OptionalSkillSource()

    assert source._optional_dir == optional_dir
