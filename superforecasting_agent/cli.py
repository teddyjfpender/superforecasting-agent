"""Fork-native CLI entrypoint for Superforecasting Agent."""

from __future__ import annotations

import argparse
import os
import sys
from functools import lru_cache
from typing import Sequence

from forecasting.cli import cmd_forecast, main as forecast_main, register_cli

_PROFILE_FLAGS = {"-p", "--profile"}
_LEGACY_ENTRYPOINTS = {"hermes-agent"}
_TUI_ENV_VARS = ("SUPERFORECASTING_AGENT_TUI", "FORECAST_TUI", "HERMES_TUI")
_ENV_TRUE_VALUES = {"1", "true", "yes", "on"}
_legacy_entrypoint_notice_shown = False


@lru_cache(maxsize=1)
def _forecast_command_names() -> frozenset[str]:
    parser = argparse.ArgumentParser(prog="superforecasting-agent", add_help=False)
    subparsers = parser.add_subparsers(dest="_forecast_root")
    forecast_parser = register_cli(subparsers)
    for action in forecast_parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return frozenset(action.choices)
    return frozenset()


def _strip_profile_args(argv: Sequence[str]) -> tuple[list[str], str | None]:
    args: list[str] = []
    profile_name: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in _PROFILE_FLAGS and i + 1 < len(argv):
            profile_name = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--profile="):
            profile_name = arg.split("=", 1)[1]
            i += 1
            continue
        args.append(arg)
        i += 1
    return args, profile_name


def _first_command_index(argv: Sequence[str]) -> int | None:
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--db":
            i += 2
            continue
        if arg.startswith("--db="):
            i += 1
            continue
        if arg in {"-h", "--help"}:
            return None
        return i
    return None


def _forecast_argv(argv: Sequence[str]) -> list[str] | None:
    args = list(argv)
    first_index = _first_command_index(args)
    if first_index is None:
        return args
    first = args[first_index]
    if first == "forecast":
        return args[:first_index] + args[first_index + 1 :]
    if first in _forecast_command_names():
        return args
    return None


def _hoist_forecast_global_args(argv: Sequence[str]) -> list[str]:
    """Accept forecast-global options before or after the subcommand.

    ``forecasting.cli`` owns the real parser and expects ``--db`` before the
    lifecycle command. The fork-native wrapper can be more forgiving because
    users naturally try ``superforecasting-agent status --db path``.
    """

    global_args: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--db" and i + 1 < len(argv):
            global_args.extend([arg, argv[i + 1]])
            i += 2
            continue
        if arg.startswith("--db="):
            global_args.append(arg)
            i += 1
            continue
        rest.append(arg)
        i += 1
    return [*global_args, *rest]


def _tui_env_enabled() -> bool:
    for name in _TUI_ENV_VARS:
        value = os.environ.get(name, "").strip().lower()
        if value:
            return value in _ENV_TRUE_VALUES
    return False


def _apply_profile(profile_name: str | None) -> None:
    if not profile_name:
        configured_home = (
            os.environ.get("SUPERFORECASTING_AGENT_HOME", "").strip()
            or os.environ.get("FORECAST_HOME", "").strip()
            or os.environ.get("HERMES_HOME", "").strip()
        )
        if configured_home:
            os.environ["HERMES_HOME"] = configured_home
        else:
            from hermes_constants import get_native_hermes_home

            os.environ["HERMES_HOME"] = str(get_native_hermes_home())
        return
    try:
        from hermes_cli.profiles import resolve_profile_env

        os.environ["HERMES_HOME"] = resolve_profile_env(profile_name)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _exit_with_missing_runtime_dependency(exc: ModuleNotFoundError) -> None:
    missing_name = exc.name or str(exc)
    print(
        "Error: this inherited runtime command needs optional CLI runtime "
        f"dependencies that are not installed ({missing_name}).",
        file=sys.stderr,
    )
    print(
        "Use `forecast ...` or `superforecasting-agent status` for the "
        "forecast desk, or run `uv pip install -e \".[all,dev]\"` from "
        "the checkout before using chat, dashboard, setup, model, gateway, "
        "or other compatibility runtime commands.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


def _run_inherited_runtime(argv: Sequence[str]) -> None:
    try:
        from hermes_cli.main import main as inherited_main
    except ModuleNotFoundError as exc:
        _exit_with_missing_runtime_dependency(exc)

    previous_argv = sys.argv[:]
    try:
        sys.argv = ["superforecasting-agent", *argv]
        try:
            inherited_main()
        except ModuleNotFoundError as exc:
            _exit_with_missing_runtime_dependency(exc)
    finally:
        sys.argv = previous_argv


def _warn_legacy_entrypoint_if_needed(argv_was_supplied: bool) -> None:
    """Nudge direct legacy-entrypoint invocations toward fork-native commands."""

    global _legacy_entrypoint_notice_shown
    if argv_was_supplied or _legacy_entrypoint_notice_shown:
        return
    invoked_as = os.path.basename(sys.argv[0])
    if invoked_as not in _LEGACY_ENTRYPOINTS:
        return
    print(
        f"Warning: `{invoked_as}` is a compatibility alias. "
        "Use `superforecasting-agent` or `forecast` for new workflows.",
        file=sys.stderr,
    )
    _legacy_entrypoint_notice_shown = True


def main(argv: list[str] | None = None) -> None:
    """Run the fork-native CLI.

    Forecast lifecycle commands are available as shorthand, e.g.
    ``superforecasting-agent new ...``, and through the explicit namespace,
    e.g. ``superforecasting-agent forecast new ...``. Inherited runtime
    commands such as ``dashboard``, ``setup``, and ``model`` are delegated to
    the compatibility CLI so users do not need to reach for the legacy
    ``hermes`` binary.
    """

    _warn_legacy_entrypoint_if_needed(argv is not None)
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    forecast_candidate_argv, profile_name = _strip_profile_args(raw_argv)
    if not forecast_candidate_argv and _tui_env_enabled():
        _run_inherited_runtime([*raw_argv, "chat"])
        return
    normalized_forecast_argv = _forecast_argv(forecast_candidate_argv)
    if normalized_forecast_argv is not None:
        _apply_profile(profile_name)
        normalized_forecast_argv = _hoist_forecast_global_args(normalized_forecast_argv)
        forecast_main(normalized_forecast_argv, prog="superforecasting-agent")
        return
    _run_inherited_runtime(raw_argv)


main_forecast = forecast_main

__all__ = ["cmd_forecast", "forecast_main", "main", "main_forecast", "register_cli"]
