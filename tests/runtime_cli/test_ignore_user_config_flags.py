"""Tests for --ignore-user-config and --ignore-rules flags on forecast sessions.

Ported from openai/codex#18646 (`feat: add --ignore-user-config and --ignore-rules`).
Codex's flags fully isolate a run from user-level config and exec-policy .rules
files. In Hermes the equivalent isolation is:

* ``--ignore-user-config`` → skip runtime-home ``config.yaml`` in
  ``load_cli_config()`` (credentials in ``.env`` are still loaded).
* ``--ignore-rules`` → skip AGENTS.md / SOUL.md / .cursorrules auto-injection
  and persistent memory (maps to ``AIAgent(skip_context_files=True,
  skip_memory=True)``).

Both flags are wired via forecast-native env vars, with ``HERMES_*`` retained
as compatibility aliases, so they work cleanly across the argparse →
cmd_chat → cli.main() → HermesCLI → AIAgent call chain.
"""

from __future__ import annotations

import os
import textwrap
import importlib

import pytest

IGNORE_USER_CONFIG_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG",
    "FORECAST_IGNORE_USER_CONFIG",
    "HERMES_IGNORE_USER_CONFIG",
)
IGNORE_RULES_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_IGNORE_RULES",
    "FORECAST_IGNORE_RULES",
    "HERMES_IGNORE_RULES",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure the two env-var gates start AND end each test in a known state.

    Some tests here write directly to ``os.environ`` (mirroring the real
    ``cmd_chat`` logic), so ``monkeypatch.delenv`` alone isn't enough —
    those writes aren't tracked by monkeypatch and won't be undone by it.
    We add explicit cleanup on yield to prevent cross-test pollution.
    """
    for var in IGNORE_USER_CONFIG_ENV_NAMES + IGNORE_RULES_ENV_NAMES:
        monkeypatch.delenv(var, raising=False)
    yield
    for var in IGNORE_USER_CONFIG_ENV_NAMES + IGNORE_RULES_ENV_NAMES:
        os.environ.pop(var, None)


class TestIgnoreUserConfigEnvGate:
    """``load_cli_config()`` must honour fork-native ignore-config aliases.

    When the env var is set, user config at ``<hermes_home>/config.yaml`` is
    skipped even if present — the function returns only the built-in defaults
    (merged with the project-level ``cli-config.yaml`` fallback).
    """

    def _write_user_config(self, tmp_path, model_default):
        config_yaml = textwrap.dedent(
            f"""
            model:
              default: {model_default}
              provider: openrouter
            agent:
              system_prompt: "from user config"
            """
        ).lstrip()
        (tmp_path / "config.yaml").write_text(config_yaml)

    def _reload_cli(self, monkeypatch, tmp_path):
        """Point cli._hermes_home at tmp_path and return a fresh load_cli_config."""
        import cli
        monkeypatch.setattr(cli, "_hermes_home", tmp_path)
        return cli.load_cli_config

    def test_user_config_loaded_when_flag_unset(self, tmp_path, monkeypatch):
        self._write_user_config(tmp_path, "anthropic/claude-sonnet-4.6")
        load_cli_config = self._reload_cli(monkeypatch, tmp_path)

        cfg = load_cli_config()

        # User config value wins
        assert cfg["model"]["default"] == "anthropic/claude-sonnet-4.6"
        assert cfg["agent"]["system_prompt"] == "from user config"

    def test_user_config_skipped_when_flag_set(self, tmp_path, monkeypatch):
        """With SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG=1, config is ignored.

        The built-in default ``model.default`` is empty string (no user override),
        and the user's ``agent.system_prompt`` is not seen.
        """
        self._write_user_config(tmp_path, "anthropic/claude-sonnet-4.6")
        monkeypatch.setenv("SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG", "1")

        load_cli_config = self._reload_cli(monkeypatch, tmp_path)
        cfg = load_cli_config()

        # User-set "system_prompt: from user config" MUST NOT leak through
        assert cfg["agent"].get("system_prompt", "") != "from user config"

        # User-set model.default MUST NOT leak through — either the built-in
        # default ("" or unset) or a project-level fallback, but never the
        # user's value
        assert cfg["model"].get("default", "") != "anthropic/claude-sonnet-4.6"

    def test_user_config_skipped_when_legacy_alias_set(self, tmp_path, monkeypatch):
        self._write_user_config(tmp_path, "anthropic/claude-sonnet-4.6")
        monkeypatch.setenv("HERMES_IGNORE_USER_CONFIG", "1")

        load_cli_config = self._reload_cli(monkeypatch, tmp_path)
        cfg = load_cli_config()

        assert cfg["agent"].get("system_prompt", "") != "from user config"
        assert cfg["model"].get("default", "") != "anthropic/claude-sonnet-4.6"

    def test_fork_native_alias_precedence_can_disable_legacy(self, tmp_path, monkeypatch):
        self._write_user_config(tmp_path, "anthropic/claude-sonnet-4.6")
        monkeypatch.setenv("SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG", "0")
        monkeypatch.setenv("HERMES_IGNORE_USER_CONFIG", "1")

        load_cli_config = self._reload_cli(monkeypatch, tmp_path)
        cfg = load_cli_config()

        assert cfg["model"]["default"] == "anthropic/claude-sonnet-4.6"

    def test_flag_ignored_when_set_to_other_value(self, tmp_path, monkeypatch):
        """Only the literal value "1" activates the bypass, matching the yolo pattern."""
        self._write_user_config(tmp_path, "anthropic/claude-sonnet-4.6")
        monkeypatch.setenv("SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG", "true")

        load_cli_config = self._reload_cli(monkeypatch, tmp_path)
        cfg = load_cli_config()

        # "true" != "1", so user config IS loaded
        assert cfg["model"]["default"] == "anthropic/claude-sonnet-4.6"

    def test_load_config_skips_user_config_with_forecast_alias(self, tmp_path, monkeypatch):
        self._write_user_config(tmp_path, "anthropic/claude-sonnet-4.6")

        import superforecasting_agent.runtime.config as hc

        monkeypatch.setattr(hc, "ensure_hermes_home", lambda: None)
        monkeypatch.setattr(hc, "get_config_path", lambda: tmp_path / "config.yaml")
        monkeypatch.setenv("FORECAST_IGNORE_USER_CONFIG", "1")
        hc._LOAD_CONFIG_CACHE.clear()

        cfg = hc.load_config()

        rendered = repr(cfg)
        assert "anthropic/claude-sonnet-4.6" not in rendered
        assert "from user config" not in rendered


class TestIgnoreRulesEnvGate:
    """The constructor / env var must propagate to ``HermesCLI.ignore_rules``
    so ``AIAgent`` is built with ``skip_context_files=True`` and
    ``skip_memory=True``.
    """

    def test_env_var_enables_ignore_rules(self, monkeypatch):
        """Setting SUPERFORECASTING_AGENT_IGNORE_RULES=1 flips ignore_rules."""
        monkeypatch.setenv("SUPERFORECASTING_AGENT_IGNORE_RULES", "1")

        # Import HermesCLI lazily — cli.py has heavy module-init side effects
        # that we don't want to run at test collection time.
        import cli
        importlib.reload(cli)

        # Build only enough of HermesCLI to reach the ignore_rules assignment.
        # The full __init__ pulls in provider/auth/session DB, so we cheat:
        # create the object via object.__new__ and manually run the assignment
        # the same way the real constructor does.
        obj = object.__new__(cli.HermesCLI)
        # Replicate the exact logic from cli.py HermesCLI.__init__:
        ignore_rules = False  # constructor default
        obj.ignore_rules = ignore_rules or cli._env_flag_exact_one(cli._IGNORE_RULES_ENV_NAMES)

        assert obj.ignore_rules is True

    def test_legacy_env_var_enables_ignore_rules(self, monkeypatch):
        monkeypatch.setenv("HERMES_IGNORE_RULES", "1")
        import cli

        obj = object.__new__(cli.HermesCLI)
        ignore_rules = False
        obj.ignore_rules = ignore_rules or cli._env_flag_exact_one(cli._IGNORE_RULES_ENV_NAMES)
        assert obj.ignore_rules is True

    def test_fork_native_ignore_rules_alias_precedence(self, monkeypatch):
        monkeypatch.setenv("SUPERFORECASTING_AGENT_IGNORE_RULES", "0")
        monkeypatch.setenv("HERMES_IGNORE_RULES", "1")
        import cli

        obj = object.__new__(cli.HermesCLI)
        ignore_rules = False
        obj.ignore_rules = ignore_rules or cli._env_flag_exact_one(cli._IGNORE_RULES_ENV_NAMES)
        assert obj.ignore_rules is False

    def test_constructor_flag_alone_enables_ignore_rules(self, monkeypatch):
        for var in IGNORE_RULES_ENV_NAMES:
            monkeypatch.delenv(var, raising=False)
        import cli
        obj = object.__new__(cli.HermesCLI)
        ignore_rules = True  # constructor argument
        obj.ignore_rules = ignore_rules or cli._env_flag_exact_one(cli._IGNORE_RULES_ENV_NAMES)
        assert obj.ignore_rules is True

    def test_neither_flag_nor_env_leaves_rules_enabled(self, monkeypatch):
        for var in IGNORE_RULES_ENV_NAMES:
            monkeypatch.delenv(var, raising=False)
        import cli
        obj = object.__new__(cli.HermesCLI)
        ignore_rules = False
        obj.ignore_rules = ignore_rules or cli._env_flag_exact_one(cli._IGNORE_RULES_ENV_NAMES)
        assert obj.ignore_rules is False


class TestCmdChatWiring:
    """The wiring inside ``cmd_chat()`` in ``superforecasting_agent/runtime/main.py`` must set
    both env vars before importing ``cli`` (which evaluates
    ``load_cli_config()`` at module import).
    """

    def _simulate_cmd_chat_env_setup(self, args):
        """Replicate the exact snippet from cmd_chat in main.py."""
        import superforecasting_agent.runtime.main as hm

        if getattr(args, "ignore_user_config", False):
            hm._set_runtime_env_aliases(os.environ, "IGNORE_USER_CONFIG", "1")
        if getattr(args, "ignore_rules", False):
            hm._set_runtime_env_aliases(os.environ, "IGNORE_RULES", "1")

    def test_both_flags_set_both_env_vars(self, monkeypatch):
        for var in IGNORE_USER_CONFIG_ENV_NAMES + IGNORE_RULES_ENV_NAMES:
            monkeypatch.delenv(var, raising=False)

        class FakeArgs:
            ignore_user_config = True
            ignore_rules = True

        self._simulate_cmd_chat_env_setup(FakeArgs())

        for var in IGNORE_USER_CONFIG_ENV_NAMES + IGNORE_RULES_ENV_NAMES:
            assert os.environ.get(var) == "1"

    def test_only_ignore_user_config(self, monkeypatch):
        for var in IGNORE_USER_CONFIG_ENV_NAMES + IGNORE_RULES_ENV_NAMES:
            monkeypatch.delenv(var, raising=False)

        class FakeArgs:
            ignore_user_config = True
            ignore_rules = False

        self._simulate_cmd_chat_env_setup(FakeArgs())

        for var in IGNORE_USER_CONFIG_ENV_NAMES:
            assert os.environ.get(var) == "1"
        for var in IGNORE_RULES_ENV_NAMES:
            assert var not in os.environ

    def test_flags_absent_sets_nothing(self, monkeypatch):
        for var in IGNORE_USER_CONFIG_ENV_NAMES + IGNORE_RULES_ENV_NAMES:
            monkeypatch.delenv(var, raising=False)

        class FakeArgs:
            pass  # no attributes at all — getattr fallback must handle

        self._simulate_cmd_chat_env_setup(FakeArgs())

        for var in IGNORE_USER_CONFIG_ENV_NAMES + IGNORE_RULES_ENV_NAMES:
            assert var not in os.environ


class TestArgparseFlagsRegistered:
    """Verify the `chat` subparser actually exposes --ignore-user-config
    and --ignore-rules. This is the contract test for the CLI surface.
    """

    def test_flags_present_in_chat_parser(self):
        """Parse a synthetic chat invocation and check both attributes exist."""
        # Minimal argparse tree matching the real chat subparser shape for the
        # two flags under test. If someone removes the flag from main.py, this
        # test keeps passing in isolation — but the E2E test below catches it.
        import argparse
        parser = argparse.ArgumentParser(prog="hermes")
        subs = parser.add_subparsers(dest="command")
        chat = subs.add_parser("chat")
        chat.add_argument("--ignore-user-config", action="store_true", default=False)
        chat.add_argument("--ignore-rules", action="store_true", default=False)

        args = parser.parse_args(["chat", "--ignore-user-config", "--ignore-rules"])
        assert args.ignore_user_config is True
        assert args.ignore_rules is True

    def test_main_py_registers_both_flags(self):
        """E2E: the real hermes parser accepts both flags."""
        from superforecasting_agent.runtime._parser import build_top_level_parser

        parser, _subparsers, chat_parser = build_top_level_parser()

        top_dests = {a.dest for a in parser._actions}
        chat_dests = {a.dest for a in chat_parser._actions}
        assert "ignore_user_config" in top_dests
        assert "ignore_rules" in top_dests
        assert "ignore_user_config" in chat_dests
        assert "ignore_rules" in chat_dests

        # And the cmd_chat env-var wiring must be present
        import inspect
        import superforecasting_agent.runtime.main as hm
        src = inspect.getsource(hm)
        assert "_set_runtime_env_aliases" in src
        assert "IGNORE_USER_CONFIG" in src
        assert "IGNORE_RULES" in src
