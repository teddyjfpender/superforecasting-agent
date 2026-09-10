"""Fork-native CLI entrypoint for Superforecasting Agent."""

from __future__ import annotations

import argparse
import os
import sys
from functools import lru_cache
from typing import Sequence

_PROFILE_FLAGS = {"-p", "--profile"}
_VERSION_FLAGS = {"--version", "-V"}
_LEGACY_ENTRYPOINTS = {"hermes", "hermes-agent"}
_TUI_ENV_VARS = ("SUPERFORECASTING_AGENT_TUI", "FORECAST_TUI", "HERMES_TUI")
_ENV_TRUE_VALUES = {"1", "true", "yes", "on"}
_legacy_entrypoint_notice_shown = False


# ``forecasting.cli`` re-exports (``cmd_forecast``, ``forecast_main``,
# ``register_cli``, ``main_forecast``) are provided lazily via module
# ``__getattr__`` below so that fast paths (``--version``) never pay the
# import cost. ``main()`` resolves ``forecast_main`` through the module
# dict first, so tests can still monkeypatch ``fork_cli.forecast_main``.
_LAZY_FORECAST_EXPORTS = {
    "cmd_forecast": "cmd_forecast",
    "forecast_main": "main",
    "main_forecast": "main",
    "register_cli": "register_cli",
}


def __getattr__(name: str):
    target = _LAZY_FORECAST_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import forecasting.cli as _forecasting_cli

    value = getattr(_forecasting_cli, target)
    globals()[name] = value
    return value


def _resolve_forecast_main():
    """Return ``forecast_main`` honoring monkeypatched module attributes."""
    fn = globals().get("forecast_main")
    if fn is None:
        from forecasting.cli import main as fn  # type: ignore[no-redef]

        globals()["forecast_main"] = fn
    return fn


@lru_cache(maxsize=1)
def _forecast_command_names() -> frozenset[str]:
    from forecasting.cli import register_cli

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
    # Forecast config owns only diagnostics; runtime config owns set/edit/show.
    if first == "config" and args[first_index + 1 : first_index + 2] != ["doctor"]:
        return None
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


def _tui_shorthand_argv(argv: Sequence[str]) -> list[str] | None:
    """Map ``superforecasting-agent tui`` to the inherited TUI flag path."""

    args = list(argv)
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in _PROFILE_FLAGS and i + 1 < len(args):
            i += 2
            continue
        if arg.startswith("--profile="):
            i += 1
            continue
        if arg == "tui":
            return [*args[:i], "--tui", *args[i + 1 :]]
        return None
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
        else:
            from superforecasting_agent.constants import get_native_agent_home

            os.environ["HERMES_HOME"] = str(get_native_agent_home())
        return
    try:
        from superforecasting_agent.runtime.profiles import resolve_profile_env

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
        "the checkout before using desk/chat, dashboard, setup, model, gateway, "
        "or other compatibility runtime commands.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


def _print_version() -> None:
    """Print version info without importing the heavy CLI runtime.

    Mirrors ``superforecasting_agent.runtime.main.cmd_version`` output. ``superforecasting_agent.runtime``'s package
    ``__init__`` is intentionally light (version constants only), so this
    path skips ``superforecasting_agent.runtime.main`` / ``forecasting.cli`` entirely.
    """

    from pathlib import Path

    import superforecasting_agent.runtime

    project_root = Path(superforecasting_agent.runtime.__file__).resolve().parent.parent
    print(
        f"Superforecasting Agent v{superforecasting_agent.runtime.__version__} "
        f"({superforecasting_agent.runtime.__release_date__})"
    )
    print(f"Project: {project_root}")
    print(f"Python: {sys.version.split()[0]}")
    # Metadata lookup (~2ms) instead of ``import openai`` (~800ms).
    try:
        from importlib.metadata import PackageNotFoundError, version as _pkg_version

        try:
            print(f"OpenAI SDK: {_pkg_version('openai')}")
        except PackageNotFoundError:
            print("OpenAI SDK: Not installed")
    except ImportError:
        print("OpenAI SDK: Not installed")
    # Update status, same as cmd_version (best effort, never fatal).
    try:
        from superforecasting_agent.runtime.banner import check_for_updates
        from superforecasting_agent.runtime.config import recommended_update_command

        behind = check_for_updates()
        if behind and behind > 0:
            commits_word = "commit" if behind == 1 else "commits"
            print(
                f"Update available: {behind} {commits_word} behind — "
                f"run '{recommended_update_command()}'"
            )
        elif behind == 0:
            print("Up to date")
    except Exception:
        pass


def _run_inherited_runtime(argv: Sequence[str]) -> None:
    try:
        from superforecasting_agent.runtime.main import main as inherited_main
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
    # Fast path: ``--version`` / ``-V`` short-circuits before any heavy
    # import (forecasting.cli parser build, superforecasting_agent.runtime.main runtime).
    if len(raw_argv) == 1 and raw_argv[0] in _VERSION_FLAGS:
        _print_version()
        return
    forecast_candidate_argv, profile_name = _strip_profile_args(raw_argv)
    tui_shorthand = _tui_shorthand_argv(raw_argv)
    if tui_shorthand is not None:
        _run_inherited_runtime(tui_shorthand)
        return
    if not forecast_candidate_argv and _tui_env_enabled():
        _run_inherited_runtime([*raw_argv, "desk"])
        return
    normalized_forecast_argv = _forecast_argv(forecast_candidate_argv)
    if normalized_forecast_argv is not None:
        _apply_profile(profile_name)
        normalized_forecast_argv = _hoist_forecast_global_args(normalized_forecast_argv)
        _resolve_forecast_main()(normalized_forecast_argv, prog="superforecasting-agent")
        return
    _run_inherited_runtime(raw_argv)


__all__ = ["cmd_forecast", "forecast_main", "main", "main_forecast", "register_cli"]
