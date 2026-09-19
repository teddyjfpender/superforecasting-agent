"""Reproduce static audit inventory without importing application code.

Run from the repository root with Python 3.11+. Source line counts include
comments/blank lines. Decision counts are an AST heuristic, not McCabe complexity.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

if sys.version_info < (3, 11):
    raise SystemExit("Use Python 3.11+ to parse the supported runtime grammar")

ROOT = Path.cwd()
RUNTIME = (
    "agent/",
    "forecasting/",
    "superforecasting_agent/",
    "gateway/",
    "tui_gateway/",
    "tools/",
    "protocol/",
    "cron/",
    "acp_adapter/",
    "providers/",
)
files = subprocess.check_output(["git", "ls-files", "-z"], text=True).split("\0")
texts = {}
for name in files:
    p = ROOT / name
    if name and p.is_file() and p.suffix in {".py", ".ts", ".tsx"}:
        texts[name] = p.read_text(encoding="utf-8", errors="replace")


def runtime(name):
    return name.startswith(RUNTIME) or ("/" not in name and name.endswith(".py"))


def tui(name):
    return (
        name.startswith("ui-tui/src/")
        and "/__tests__/" not in name
        and "/testing/" not in name
        and "/protocol/generated." not in name
    )


strict = []
for node in ast.parse((ROOT / "scripts/dev.py").read_text(encoding="utf-8")).body:
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "STRICT_PYTHON" for t in node.targets
    ):
        strict = ast.literal_eval(node.value)


def covered(name):
    return any(name == prefix or name.startswith(prefix + "/") for prefix in strict)


functions = []
errors = []
for name, source in texts.items():
    if not name.endswith(".py") or not runtime(name):
        continue
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        errors.append({"path": name, "error": str(exc)})
        continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Include branches in nested functions; explicitly a prioritization heuristic.
            decisions = sum(
                isinstance(
                    n,
                    (
                        ast.If,
                        ast.For,
                        ast.AsyncFor,
                        ast.While,
                        ast.ExceptHandler,
                        ast.IfExp,
                        ast.comprehension,
                    ),
                )
                for n in ast.walk(node)
            )
            functions.append({
                "path": name,
                "name": node.name,
                "line": node.lineno,
                "lines": node.end_lineno - node.lineno + 1,
                "decision_nodes": decisions,
                "strict_gate": covered(name),
            })


def counts(pred):
    return {
        "files": sum(pred(p) for p in texts),
        "lines": sum(len(s.splitlines()) for p, s in texts.items() if pred(p)),
    }


source_files = [
    {
        "path": p,
        "lines": len(s.splitlines()),
        "strict_gate": covered(p) if p.endswith(".py") else None,
    }
    for p, s in texts.items()
    if runtime(p) or tui(p)
]
result = {
    "python_version": sys.version.split()[0],
    "source_sha": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip(),
    "method": "Tracked .py/.ts/.tsx files; physical lines. Runtime Python excludes plugins/skills/tests/scripts; TUI excludes tests/testing/generated protocol. Branch metric counts selected AST nodes, includes nested functions, and is not McCabe complexity.",
    "tracked_files": len([f for f in files if f]),
    "tracked_source": counts(lambda p: True),
    "runtime_python": counts(lambda p: p.endswith(".py") and runtime(p)),
    "strict_runtime_python": counts(
        lambda p: p.endswith(".py") and runtime(p) and covered(p)
    ),
    "tui_authored_source": counts(tui),
    "python_tests": counts(lambda p: p.startswith("tests/") and p.endswith(".py")),
    "tui_tests": counts(lambda p: p.startswith("ui-tui/src/__tests__/")),
    "root_directory_file_counts": dict(
        Counter(p.split("/")[0] if "/" in p else "(root)" for p in files if p)
    ),
    "largest_files": sorted(source_files, key=lambda x: x["lines"], reverse=True)[:20],
    "longest_python_functions": sorted(
        functions, key=lambda x: x["lines"], reverse=True
    )[:20],
    "most_branched_python_functions": sorted(
        functions, key=lambda x: x["decision_nodes"], reverse=True
    )[:20],
    "parse_errors": errors,
}
print(json.dumps(result, indent=2))
