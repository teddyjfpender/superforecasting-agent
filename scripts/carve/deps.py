"""Free-name dependency report for a set of functions being MOVED out of core.py.

Given the moved function names, compute every module-level name their bodies
reference that will REMAIN in core (imported symbols, constants, classes, shared
helpers) — i.e. exactly what the new domain module must import from
``forecasting.cli.core`` (bare) or hop via ``_core.`` (if monkeypatched).

Usage:  python scripts/carve/deps.py <fn1> <fn2> ...
"""
from __future__ import annotations

import ast
import builtins
import sys

FILE = "forecasting/cli/core.py"
# Names monkeypatched at the facade by tests -> MUST be reached via _core.<name>
# at call time so a patch on forecasting.cli.<name> reaches the moved call site.
PATCHED = {"_ledger", "_load_backtest_cases", "_apply_backtest_probability_source",
           "_run_update_agent", "list_builtin_benchmarks", "_draft_resolution_criteria"}
BUILTINS = set(dir(builtins))


def main() -> None:
    moved = set(sys.argv[1:])
    src = open(FILE, encoding="utf-8").read()
    tree = ast.parse(src)

    module_names: set[str] = set()
    func_nodes: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(node.name)
            func_nodes[node.name] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                module_names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                for sub in ast.walk(tgt):
                    if isinstance(sub, ast.Name):
                        module_names.add(sub.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            module_names.add(node.target.id)

    # Collect bound (local) names per moved function to exclude them.
    referenced: set[str] = set()
    for name in moved:
        node = func_nodes.get(name)
        if node is None:
            print(f"WARN: {name} not a top-level def", file=sys.stderr)
            continue
        local: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.arg):
                local.add(sub.arg)
            elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                local.add(sub.id)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                nm = sub.id
                if nm in BUILTINS or nm in local or nm in moved:
                    continue
                if nm in module_names:
                    referenced.add(nm)

    patched = sorted(n for n in referenced if n in PATCHED)
    bare = sorted(n for n in referenced if n not in PATCHED)
    print(f"MOVED: {sorted(moved)}\n")
    print(f"PATCHED (reach via _core.<name> hop):")
    for n in patched:
        print(f"  ~ {n}")
    print(f"\nBARE imports from forecasting.cli.core ({len(bare)}):")
    print("from forecasting.cli.core import (")
    for n in bare:
        print(f"    {n},")
    print(")")


if __name__ == "__main__":
    main()
