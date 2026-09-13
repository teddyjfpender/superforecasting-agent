"""Installed extensions retain their old imports against canonical profile owners."""
import json


def test_legacy_plugin_imports_use_canonical_profile(tmp_path, monkeypatch):
    home = tmp_path / "native"
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "legacy"))
    from superforecasting_agent.runtime.config import ensure_hermes_home
    from superforecasting_agent.credentials.anthropic import (
        get_hermes_oauth_file, read_hermes_oauth_credentials,
        get_agent_oauth_file, read_agent_oauth_credentials,
    )
    ensure_hermes_home()
    assert get_hermes_oauth_file() == home / ".anthropic_oauth.json"
    get_hermes_oauth_file().write_text(json.dumps({"accessToken": "fixture-only"}))
    assert read_hermes_oauth_credentials() == read_agent_oauth_credentials()
    assert get_agent_oauth_file() == get_hermes_oauth_file()
    assert not (tmp_path / "legacy").exists()


def test_adapter_keeps_legacy_provider_imports():
    from agent import anthropic_adapter as adapter
    from superforecasting_agent.credentials import anthropic
    assert adapter.get_hermes_oauth_file is anthropic.get_agent_oauth_file
    assert adapter.read_hermes_oauth_credentials is anthropic.read_agent_oauth_credentials
    assert adapter.run_hermes_oauth_login_pure is adapter.run_agent_oauth_login_pure
