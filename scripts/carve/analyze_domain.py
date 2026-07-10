"""Caller-exclusivity analyzer for a CLI carve slice.

Given ``core.py`` and a set of SEED handler names (the ``_cmd_*`` functions for a
domain), report which OTHER top-level names in the module are referenced *only*
by the domain closure — i.e. safe to MOVE with the handlers — versus names that
are also used elsewhere and must STAY in core (imported bare / hopped via
``_core.``). Membership is caller-exclusivity, never adjacency (the Arc-D rule).

Usage:
    python scripts/carve/analyze_domain.py <seed1> <seed2> ...
"""
from __future__ import annotations

import ast
import sys

FILE = "forecasting/cli/core.py"


def load() -> tuple[ast.Module, dict[str, ast.AST]]:
    src = open(FILE, encoding="utf-8").read()
    tree = ast.parse(src)
    top: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            top[node.name] = node
    return tree, top


def names_in(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
            pass
    return out


def main() -> None:
    seeds = set(sys.argv[1:])
    if not seeds:
        print("usage: analyze_domain.py <seed_handler> ...", file=sys.stderr)
        raise SystemExit(2)
    tree, top = load()

    # refs[name] = set of identifiers that function references
    refs = {name: names_in(node) for name, node in top.items()}

    # Closure: transitively pull in private (_-prefixed) top-level funcs referenced
    # only via the seeds. Start conservative: BFS over private helpers.
    closure = set(seeds)
    changed = True
    while changed:
        changed = False
        for fn in list(closure):
            for ref in refs.get(fn, ()):
                if ref in top and ref.startswith("_") and ref not in closure:
                    closure.add(ref)
                    changed = True

    # A helper STAYS if it has any referrer outside the closure. That "staying"
    # property then propagates INWARD: anything a staying function references must
    # also stay (a helper reachable only through a shared helper is NOT movable).
    def referrers_outside(target: str) -> list[str]:
        out = []
        for name in top:
            if name in closure or name in seeds:
                continue
            if target in refs[name]:
                out.append(name)
        return out

    staying: dict[str, list[str]] = {}
    for fn in closure - seeds:
        outside = referrers_outside(fn)
        if outside:
            staying[fn] = outside
    changed = True
    while changed:
        changed = False
        for fn in list(staying):
            for ref in refs.get(fn, ()):
                if ref in closure and ref not in seeds and ref not in staying:
                    staying[ref] = [f"(via staying {fn})"]
                    changed = True

    print(f"SEEDS ({len(seeds)}): {sorted(seeds)}\n")
    movable, shared = [], []
    for fn in sorted(closure - seeds):
        if fn in staying:
            shared.append((fn, staying[fn]))
        else:
            movable.append((fn, []))

    print("MOVABLE private helpers (referenced only within the domain closure):")
    for fn, _ in movable:
        print(f"  + {fn}")
    print("\nSHARED helpers (also used outside — STAY in core, import bare):")
    for fn, outside in shared:
        print(f"  ~ {fn}   <- also used by: {sorted(outside)[:6]}")

    # Names the seeds reference that are top-level in core but NOT in closure
    # (shared funcs/constants they must import from core).
    ext = set()
    for fn in closure:
        for ref in refs.get(fn, ()):
            if ref in top and ref not in closure:
                ext.add(ref)
    print("\nCORE top-level funcs the domain calls (import bare / hop):")
    for name in sorted(ext):
        print(f"  -> {name}")


if __name__ == "__main__":
    main()
