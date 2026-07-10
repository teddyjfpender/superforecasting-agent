"""Dump the full ``forecast`` parser tree deterministically (carve acceptance gate).

Walks every subparser reachable from ``forecasting.cli.register_cli`` and emits a
stable, structural representation of each node: its path, description, every
argument's shape (option strings, dest, help, metavar, choices, nargs, default,
required, type), and its ordered subcommand choice names. This is a strictly
stronger equivalence than ``format_help()`` text (it captures registration order,
defaults, and handler wiring) and it does not crash on help strings containing a
literal ``%`` (which argparse's lazy ``help % params`` expansion mishandles).

A moves-only CLI carve MUST leave this dump byte-identical.

Usage:  python scripts/carve/dump_help_tree.py > tree.txt
"""
from __future__ import annotations

import argparse
import io
import sys


def _fmt(value: object) -> str:
    if value is argparse.SUPPRESS:
        return "SUPPRESS"
    if callable(value):
        return getattr(value, "__name__", repr(value))
    return repr(value)


def _emit_action(action: argparse.Action, out: io.StringIO) -> None:
    if isinstance(action, argparse._SubParsersAction):
        out.write(f"  [subparsers dest={action.dest!r}]\n")
        return
    handler = None
    # _forecast_handler / func live in the parser defaults, handled per-node.
    parts = [
        f"opts={list(action.option_strings)!r}",
        f"dest={action.dest!r}",
        f"nargs={_fmt(action.nargs)}",
        f"metavar={_fmt(action.metavar)}",
        f"choices={sorted(action.choices) if action.choices else None!r}",
        f"required={action.required!r}",
        f"default={_fmt(action.default)}",
        f"type={_fmt(action.type)}",
        f"cls={type(action).__name__}",
        f"help={action.help!r}",
    ]
    out.write("  arg " + " ".join(parts) + "\n")


def _walk(parser: argparse.ArgumentParser, path: str, out: io.StringIO) -> None:
    out.write(f"\n===== {path} =====\n")
    out.write(f"description={parser.description!r}\n")
    defaults = {
        k: _fmt(v)
        for k, v in sorted(parser._defaults.items())
        if k in ("func", "_forecast_handler")
    }
    out.write(f"defaults={defaults!r}\n")
    for action in parser._actions:
        _emit_action(action, out)
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in sorted(action.choices.items(), key=lambda kv: kv[0]):
                _walk(child, f"{path} {name}", out)


def build_forecast_parser() -> argparse.ArgumentParser:
    from forecasting.cli import register_cli

    root = argparse.ArgumentParser(prog="ROOT")
    sub = root.add_subparsers()
    register_cli(sub)
    for action in root._actions:
        if isinstance(action, argparse._SubParsersAction):
            fp = action.choices.get("forecast")
            if fp is not None:
                return fp
    raise SystemExit("forecast parser not found")


def main() -> None:
    out = io.StringIO()
    _walk(build_forecast_parser(), "forecast", out)
    sys.stdout.write(out.getvalue())


if __name__ == "__main__":
    main()
