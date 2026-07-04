"""Render ``docs/reference/cli-reference.md`` by walking the CLI argparse tree.

Source of truth: ``forecasting/cli.py`` — ``register_cli(subparsers)`` builds the
whole ``forecast`` command tree. We introspect the live parser (the same one the
CLI runs), so a new subcommand shows up here automatically.
"""

from __future__ import annotations

import argparse
from typing import Any

from scripts.docgen.common import header

SOURCE = "forecasting/cli.py (register_cli argparse tree)"


def _forecast_parser() -> argparse.ArgumentParser:
    from forecasting.cli import register_cli

    root = argparse.ArgumentParser(prog="forecast", add_help=False)
    sub = root.add_subparsers(dest="_root")
    return register_cli(sub)


def _subparsers_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _sub_help(action: argparse._SubParsersAction) -> dict[str, str]:
    """name -> help text for each choice of a subparsers action."""

    out: dict[str, str] = {}
    for pseudo in getattr(action, "_choices_actions", []):
        out[pseudo.dest] = (pseudo.help or "").strip()
    return out


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def _arguments(parser: argparse.ArgumentParser) -> list[tuple[str, str]]:
    """(identifier, help) for each real argument (skips -h and subparsers)."""

    args: list[tuple[str, str]] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            continue
        if action.option_strings and set(action.option_strings) <= {"-h", "--help"}:
            continue
        if action.option_strings:
            ident = "/".join(action.option_strings)
        else:
            ident = str(action.metavar or action.dest)
        args.append((ident, _one_line(action.help or "")))
    return args


def _render_args_block(parser: argparse.ArgumentParser, indent: str = "") -> list[str]:
    args = _arguments(parser)
    if not args:
        return []
    lines = [f"{indent}| argument | help |", f"{indent}| --- | --- |"]
    for ident, help_text in args:
        lines.append(f"{indent}| `{ident}` | {help_text} |")
    lines.append("")
    return lines


def _render_command(name_path: str, parser: argparse.ArgumentParser, level: int) -> list[str]:
    """Recursively render a command, its arguments, and any nested subcommands."""

    heading = "#" * min(level, 6)
    out = [f"{heading} `{name_path}`", ""]
    out.extend(_render_args_block(parser))

    action = _subparsers_action(parser)
    if action is not None:
        helps = _sub_help(action)
        for child_name in sorted(action.choices):
            child_help = helps.get(child_name, "")
            child_path = f"{name_path} {child_name}"
            out.append(f"- **`{child_path}`** — {child_help}")
        out.append("")
        for child_name in sorted(action.choices):
            out.extend(
                _render_command(
                    f"{name_path} {child_name}", action.choices[child_name], level + 1
                )
            )
    return out


def render() -> str:
    forecast = _forecast_parser()
    top = _subparsers_action(forecast)
    assert top is not None, "forecast parser has no subcommands"
    helps = _sub_help(top)
    commands = sorted(top.choices)

    blocks: list[str] = [
        header(
            "CLI Reference",
            SOURCE,
            blurb=(
                f"The full `forecast` command tree — **{len(commands)} top-level"
                f" commands** (also reachable as `superforecasting-agent <command>`)."
                f" This is the exhaustive reference; for task-oriented walkthroughs"
                f" see [cli.md](../cli.md)."
            ),
        )
    ]

    # ── index ────────────────────────────────────────────────────────────────
    blocks.append("## Commands\n")
    index = ["| command | summary |", "| --- | --- |"]
    for name in commands:
        index.append(f"| [`forecast {name}`](#forecast-{name}) | {_one_line(helps.get(name, ''))} |")
    blocks.append("\n".join(index))

    # ── per-command detail ───────────────────────────────────────────────────
    for name in commands:
        blocks.append("\n".join(_render_command(f"forecast {name}", top.choices[name], 2)).rstrip())

    return "\n\n".join(blocks) + "\n"
