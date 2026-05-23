"""Fork-native CLI entrypoint for Superforecasting Agent."""

from __future__ import annotations

import argparse
import os
import sys
from functools import lru_cache
from typing import Sequence

from forecasting.cli import cmd_forecast, main as forecast_main, register_cli

_PROFILE_FLAGS = {"-p", "--profile"}


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


def _apply_profile(profile_name: str | None) -> None:
    if not profile_name:
        configured_home = (
            os.environ.get("SUPERFORECASTING_AGENT_HOME", "").strip()
            or os.environ.get("FORECAST_HOME", "").strip()
            or os.environ.get("HERMES_HOME", "").strip()
        )
        if configured_home:
            os.environ["HERMES_HOME"] = configured_home
        return
    try:
        from hermes_cli.profiles import resolve_profile_env

        os.environ["HERMES_HOME"] = resolve_profile_env(profile_name)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _run_inherited_runtime(argv: Sequence[str]) -> None:
    from hermes_cli.main import main as inherited_main

    previous_argv = sys.argv[:]
    try:
        sys.argv = ["superforecasting-agent", *argv]
        inherited_main()
    finally:
        sys.argv = previous_argv


def main(argv: list[str] | None = None) -> None:
    """Run the fork-native CLI.

    Forecast lifecycle commands are available as shorthand, e.g.
    ``superforecasting-agent new ...``, and through the explicit namespace,
    e.g. ``superforecasting-agent forecast new ...``. Inherited runtime
    commands such as ``dashboard``, ``setup``, and ``model`` are delegated to
    the compatibility CLI so users do not need to reach for the legacy
    ``hermes`` binary.
    """

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    forecast_candidate_argv, profile_name = _strip_profile_args(raw_argv)
    normalized_forecast_argv = _forecast_argv(forecast_candidate_argv)
    if normalized_forecast_argv is not None:
        _apply_profile(profile_name)
        forecast_main(normalized_forecast_argv, prog="superforecasting-agent")
        return
    _run_inherited_runtime(raw_argv)


main_forecast = forecast_main

__all__ = ["cmd_forecast", "forecast_main", "main", "main_forecast", "register_cli"]
