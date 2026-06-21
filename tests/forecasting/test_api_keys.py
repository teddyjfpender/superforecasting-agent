"""Tests for the API-key registry, .env read/write/activate, and the CLI surface."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from forecasting import api_keys
from forecasting.cli import register_cli
from forecasting.models import ValidationError


def _isolated_env(monkeypatch, tmp_path) -> Path:
    """Point api_keys at a temp .env and clear known env vars."""
    env_path = tmp_path / ".env"
    monkeypatch.setattr(api_keys, "default_env_path", lambda: env_path)
    for provider in api_keys.API_KEY_PROVIDERS:
        monkeypatch.delenv(provider.env_var, raising=False)
    return env_path


# ── Module-level: set / unset / list / lookup ───────────────────────────────


def test_set_writes_env_file_and_activates_in_process(monkeypatch, tmp_path):
    env_path = _isolated_env(monkeypatch, tmp_path)
    provider = api_keys.set_api_key("fred", "abcd1234efgh5678ijkl", env_path=env_path)
    assert provider.env_var == "FRED_API_KEY"
    assert "FRED_API_KEY=abcd1234efgh5678ijkl" in env_path.read_text()
    assert os.environ["FRED_API_KEY"] == "abcd1234efgh5678ijkl"


def test_set_replaces_existing_value_without_duplicating(monkeypatch, tmp_path):
    env_path = _isolated_env(monkeypatch, tmp_path)
    api_keys.set_api_key("fred", "first-value", env_path=env_path)
    api_keys.set_api_key("fred", "second-value", env_path=env_path)
    text = env_path.read_text()
    assert text.count("FRED_API_KEY=") == 1
    assert "FRED_API_KEY=second-value" in text


def test_set_preserves_other_lines(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=keep-me\n# comment line\nEIA_API_KEY=existing\n")
    monkeypatch.setattr(api_keys, "default_env_path", lambda: env_path)
    api_keys.set_api_key("fred", "new-fred", env_path=env_path)
    text = env_path.read_text()
    assert "OTHER=keep-me" in text
    assert "# comment line" in text
    assert "EIA_API_KEY=existing" in text
    assert "FRED_API_KEY=new-fred" in text


def test_unset_removes_value_from_file_and_environment(monkeypatch, tmp_path):
    env_path = _isolated_env(monkeypatch, tmp_path)
    api_keys.set_api_key("fred", "to-be-removed", env_path=env_path)
    api_keys.unset_api_key("fred", env_path=env_path)
    assert "FRED_API_KEY" not in env_path.read_text()
    assert "FRED_API_KEY" not in os.environ


def test_lookup_resolves_friendly_name_env_var_and_aliases():
    assert api_keys.lookup_provider("fred").env_var == "FRED_API_KEY"
    assert api_keys.lookup_provider("FRED_API_KEY").env_var == "FRED_API_KEY"
    assert api_keys.lookup_provider("parallel-web").env_var == "PARALLEL_API_KEY"
    assert api_keys.lookup_provider("brave-search").env_var == "BRAVE_API_KEY"


def test_bls_is_a_known_addable_data_provider():
    # BLS's optional registration key must be addable through the api-key flow.
    assert any(p.env_var == "BLS_API_KEY" for p in api_keys.API_KEY_PROVIDERS)
    assert api_keys.lookup_provider("bls").env_var == "BLS_API_KEY"
    assert api_keys.lookup_provider("BLS_API_KEY").env_var == "BLS_API_KEY"


def test_lookup_accepts_custom_uppercase_env_var():
    provider = api_keys.lookup_provider("MY_CUSTOM_KEY")
    assert provider.env_var == "MY_CUSTOM_KEY"
    assert provider.name == "my_custom_key"


def test_lookup_rejects_invalid_provider():
    with pytest.raises(ValidationError):
        api_keys.lookup_provider("not a valid name")


def test_set_rejects_empty_value(monkeypatch, tmp_path):
    env_path = _isolated_env(monkeypatch, tmp_path)
    with pytest.raises(ValidationError):
        api_keys.set_api_key("fred", "   ", env_path=env_path)


def test_quoted_values_for_special_chars(monkeypatch, tmp_path):
    env_path = _isolated_env(monkeypatch, tmp_path)
    api_keys.set_api_key("MY_TOKEN", 'has "quotes" and spaces #here', env_path=env_path)
    text = env_path.read_text()
    # Value must be quoted to survive python-dotenv parsing.
    assert 'MY_TOKEN="has \\"quotes\\" and spaces #here"' in text


def test_redact_hides_most_of_value():
    assert api_keys.redact(None) == "(not set)"
    assert api_keys.redact("") == "(not set)"
    assert api_keys.redact("abcd1234efgh") == "abcd…efgh (12 chars)"
    assert api_keys.redact("short") == "•••••"


def test_list_api_keys_marks_set_status(monkeypatch, tmp_path):
    env_path = _isolated_env(monkeypatch, tmp_path)
    api_keys.set_api_key("fred", "value-1234ABCD", env_path=env_path)
    rows = {row["name"]: row for row in api_keys.list_api_keys()}
    assert rows["fred"]["set"] is True
    # redact() shows first 4 + last 4 chars + length; never the middle.
    assert rows["fred"]["redacted"].startswith("valu")
    assert rows["fred"]["redacted"].endswith("(14 chars)")
    assert "1234" not in rows["fred"]["redacted"]  # middle hidden
    assert rows["eia"]["set"] is False
    assert rows["eia"]["redacted"] == "(not set)"


# ── CLI surface ─────────────────────────────────────────────────────────────


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forecast-test")
    subparsers = parser.add_subparsers(dest="command")
    register_cli(subparsers)
    return parser


def _run(argv: list[str]) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    args.func(args)


def test_cli_api_key_list_shows_providers(monkeypatch, tmp_path, capsys):
    _isolated_env(monkeypatch, tmp_path)
    _run(["forecast", "api-key", "list"])
    out = capsys.readouterr().out
    assert "FRED_API_KEY" in out
    assert "EIA_API_KEY" in out
    assert "(not set)" in out


def test_cli_api_key_set_persists_and_redacts(monkeypatch, tmp_path, capsys):
    env_path = _isolated_env(monkeypatch, tmp_path)
    _run(["forecast", "api-key", "set", "fred", "secret-value-abcdef123456"])
    out = capsys.readouterr().out
    # Output must NOT echo the raw value, only the redacted form.
    assert "secret-value-abcdef123456" not in out
    assert "FRED_API_KEY" in out
    assert env_path.read_text().count("FRED_API_KEY=secret-value-abcdef123456") == 1
    assert os.environ["FRED_API_KEY"] == "secret-value-abcdef123456"


def test_cli_api_key_set_from_stdin(monkeypatch, tmp_path, capsys):
    import io

    env_path = _isolated_env(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("piped-key-value-XYZ\n"))
    _run(["forecast", "api-key", "set", "fred", "--from-stdin"])
    assert "FRED_API_KEY=piped-key-value-XYZ" in env_path.read_text()


def test_cli_api_key_unset(monkeypatch, tmp_path, capsys):
    env_path = _isolated_env(monkeypatch, tmp_path)
    api_keys.set_api_key("fred", "to-remove", env_path=env_path)
    _run(["forecast", "api-key", "unset", "fred"])
    assert "FRED_API_KEY" not in env_path.read_text()
    assert "FRED_API_KEY" not in os.environ


def test_cli_api_key_show_redacts(monkeypatch, tmp_path, capsys):
    env_path = _isolated_env(monkeypatch, tmp_path)
    api_keys.set_api_key("fred", "secret-XYZ-abcdef12345", env_path=env_path)
    _run(["forecast", "api-key", "show", "fred"])
    out = capsys.readouterr().out
    assert "set:      yes" in out
    assert "secret-XYZ-abcdef12345" not in out  # never echo raw


def test_cli_api_key_unknown_provider_exits_2(monkeypatch, tmp_path, capsys):
    _isolated_env(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run(["forecast", "api-key", "set", "not a real provider name", "value"])
    assert exc.value.code == 2
