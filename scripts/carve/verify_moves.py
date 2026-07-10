"""Mechanical MOVES-ONLY verifier for a CLI (or ledger) carve slice.

Enforces the CONTRIBUTING "Moves-only refactor slices" law: a carve is method
bodies moved OUT of a shrinking file plus one-line delegates / imports / façade
re-bindings — and *every added line in the shrinking file* must be one of those.
This categorizer diffs the shrinking file at ``--base`` (default: git HEAD) against
the working tree and fails (exit 1) on any added line that is not an allowed
façade construct.

Allowed added-line categories (the Arc-D / thesis-slice grammar):
  - blank / whitespace-only
  - comment (``# ...``)
  - import of the carved domain (``from forecasting.cli import X as _Y`` / ``import ...``)
  - the shared register hook call (``_Y.register(...)`` / ``X.register(...)``)
  - a façade re-binding of a moved name (``_cmd_foo = _Y._cmd_foo``)
  - a one-line delegate body (``return _core.foo(...)`` etc.)

Usage:
    python scripts/carve/verify_moves.py --file forecasting/cli/core.py \
        [--base HEAD] [--moved-into forecasting/cli/doctor_admin.py]
"""
from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys

ALLOWED = [
    re.compile(r"^\s*$"),                                   # blank
    re.compile(r"^\s*#"),                                   # comment
    re.compile(r"^\s*from\s+[\w.]+\s+import\s+.+$"),        # import-from
    re.compile(r"^\s*import\s+[\w.]+(\s+as\s+\w+)?\s*$"),   # import
    # register* hook — bare (CLI) or the sibling `register(sys.modules[__name__])`
    # idiom (pm_rpc/jobs_rpc; the reload-safe tui_gateway family-carve seam).
    re.compile(r"^\s*\w[\w.]*\.register\w*\((sys\.modules\[__name__\]|[\w.]*)\)\s*$"),
    re.compile(r"^\s*_?\w+\s*=\s*_\w+\.[\w.]+\s*$"),        # facade re-bind
    re.compile(r"^\s*return\s+_\w+\.[\w.]+\(.*\)\s*$"),     # one-line delegate
    re.compile(r"^\s*noqa.*$"),
]


def _git_show(base: str, path: str) -> list[str]:
    out = subprocess.run(
        ["git", "show", f"{base}:{path}"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.splitlines(keepends=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--moved-into", action="append", default=[])
    args = ap.parse_args()

    old = _git_show(args.base, args.file)
    with open(args.file, encoding="utf-8") as fh:
        new = fh.readlines()

    added: list[str] = []
    removed = 0
    for line in difflib.unified_diff(old, new, n=0):
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("-"):
            removed += 1

    unexpected = [ln for ln in added if not any(p.match(ln) for p in ALLOWED)]

    print(f"[verify_moves] {args.file}: -{removed} +{len(added)} lines "
          f"({len(unexpected)} unexpected added)")
    if args.moved_into:
        for dest in args.moved_into:
            try:
                with open(dest, encoding="utf-8") as fh:
                    print(f"[verify_moves] moved-into {dest}: {sum(1 for _ in fh)} lines")
            except OSError as exc:
                print(f"[verify_moves] WARN cannot stat {dest}: {exc}")

    if unexpected:
        print("\nUNEXPECTED added lines (not delegate/import/re-bind/comment):",
              file=sys.stderr)
        for ln in unexpected:
            print("  + " + ln.rstrip("\n"), file=sys.stderr)
        return 1
    print("[verify_moves] OK — every added line is a façade construct (MOVES-ONLY)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
