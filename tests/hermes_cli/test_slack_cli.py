"""Tests for Slack CLI helpers."""

from pathlib import Path

import pytest

import hermes_cli.slack_cli as slack_cli
from hermes_cli.slack_cli import _build_full_manifest


class TestSlackFullManifest:
    """Generated full Slack app manifest used by `superforecasting-agent slack manifest`."""

    def test_app_home_messages_are_writable(self):
        manifest = _build_full_manifest("Superforecast", "Your forecasting desk on Slack")

        assert manifest["features"]["app_home"] == {
            "home_tab_enabled": False,
            "messages_tab_enabled": True,
            "messages_tab_read_only_enabled": False,
        }

    def test_private_channel_directory_scope_is_included(self):
        manifest = _build_full_manifest("Superforecast", "Your forecasting desk on Slack")

        bot_scopes = manifest["oauth_config"]["scopes"]["bot"]
        assert "groups:read" in bot_scopes

    def test_assistant_features_remain_enabled(self):
        manifest = _build_full_manifest("Superforecast", "Your forecasting desk on Slack")

        assert "assistant_view" in manifest["features"]
        assert "assistant:write" in manifest["oauth_config"]["scopes"]["bot"]
        bot_events = manifest["settings"]["event_subscriptions"]["bot_events"]
        assert "assistant_thread_started" in bot_events


@pytest.mark.parametrize(
    ("env_name", "expected"),
    [
        ("SUPERFORECASTING_AGENT_HOME", "native"),
        ("FORECAST_HOME", "short"),
        ("HERMES_HOME", "legacy"),
    ],
)
def test_manifest_default_write_path_prefers_forecast_home_aliases(tmp_path, monkeypatch, env_name, expected):
    def fail_constants_home():
        raise RuntimeError("force fallback path")

    monkeypatch.setattr(slack_cli, "_manifest_home_from_constants", fail_constants_home)
    for name in ("SUPERFORECASTING_AGENT_HOME", "FORECAST_HOME", "HERMES_HOME"):
        monkeypatch.delenv(name, raising=False)
    target_home = tmp_path / expected
    monkeypatch.setenv(env_name, str(target_home))

    assert slack_cli._manifest_write_default_path() == target_home / "slack-manifest.json"


def test_manifest_default_write_path_falls_back_to_native_home(monkeypatch):
    def fail_constants_home():
        raise RuntimeError("force fallback path")

    monkeypatch.setattr(slack_cli, "_manifest_home_from_constants", fail_constants_home)
    for name in ("SUPERFORECASTING_AGENT_HOME", "FORECAST_HOME", "HERMES_HOME"):
        monkeypatch.delenv(name, raising=False)

    assert slack_cli._manifest_write_default_path() == Path.home() / ".superforecasting-agent" / "slack-manifest.json"
