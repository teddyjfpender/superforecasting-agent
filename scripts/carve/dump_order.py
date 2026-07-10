"""Emit the forecast subcommand names in REGISTRATION order (top-level + nested).

The real ``forecast --help`` lists subcommands in the order they were registered;
the structural dump (dump_help_tree.py) sorts them, so it would not catch an
accidental reordering when a carve moves a registration block. This gate pins the
order. A moves-only carve keeps it byte-identical.
"""
from __future__ import annotations
import argparse, sys


def walk(parser, path, out):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            names = list(dict.fromkeys(action._name_parser_map.keys()))
            out.append(f"{path}: " + " ".join(names))
            seen = set()
            for name, child in action._name_parser_map.items():
                if id(child) in seen:
                    continue
                seen.add(id(child))
                walk(child, f"{path} {name}", out)


def main():
    from forecasting.cli import register_cli
    root = argparse.ArgumentParser(prog="ROOT")
    sub = root.add_subparsers()
    register_cli(sub)
    fp = sub.choices["forecast"]
    out = []
    walk(fp, "forecast", out)
    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
