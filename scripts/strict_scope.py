"""Check protected strict Python ownership and report its measured source scope.

Run --record after adding strict owners. This only adds protected paths; retiring
one requires an explicit reason in strict-scope-policy.json, reviewed with the move.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = "scripts/strict-scope-policy.json"
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


def scope(root: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse((root / "scripts/dev.py").read_text(encoding="utf-8"))
    prefixes: tuple[str, ...] | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "STRICT_PYTHON"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if not isinstance(value, tuple) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError("STRICT_PYTHON must be a literal tuple of paths")
            prefixes = value
    if not prefixes:
        raise ValueError("strict Python scope is missing")
    tracked = set(
        subprocess.check_output(["git", "ls-files", "-z"], cwd=root, text=True).split(
            "\0"
        )
    )
    files = {
        name for name in tracked if name.endswith(".py") and (root / name).is_file()
    }
    covered = {
        name
        for name in files
        if any(name == prefix or name.startswith(prefix + "/") for prefix in prefixes)
    }
    return files, covered


def read_policy(root: Path) -> tuple[set[str], dict[str, str]]:
    value = json.loads((root / POLICY).read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ValueError("unsupported strict scope policy")
    protected = value.get("protected_files")
    retired = value.get("retired", {})
    if not isinstance(protected, list) or not all(
        isinstance(item, str) for item in protected
    ):
        raise ValueError("protected_files must contain paths")
    if len(set(protected)) != len(protected):
        raise ValueError("duplicate protected paths")
    if not isinstance(retired, dict) or not all(
        isinstance(path, str) and isinstance(reason, str) and len(reason.strip()) >= 20
        for path, reason in retired.items()
    ):
        raise ValueError(
            "each retirement requires a meaningful review reason (20+ characters)"
        )
    if set(retired) - set(protected):
        raise ValueError("retirement must reference a protected path")
    return set(protected), retired


def verify(root: Path, *, record: bool = False) -> dict[str, object]:
    files, covered = scope(root)
    protected, retired = read_policy(root)
    missing = protected - covered - set(retired)
    if missing:
        raise ValueError(
            "strict ownership lost; cover the replacement and record an explicit retirement: "
            + ", ".join(sorted(missing))
        )
    if set(retired) & covered:
        raise ValueError(
            "remove obsolete retirement reasons for files restored to strict coverage"
        )
    added = covered - protected
    if added and not record:
        raise ValueError(
            "new strict owners need protection; run python3 scripts/strict_scope.py --record: "
            + ", ".join(sorted(added))
        )
    if record:
        (root / POLICY).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "protected_files": sorted(protected | covered),
                    "retired": retired,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    runtime = {name for name in files if name.startswith(RUNTIME) or "/" not in name}
    strict_runtime = runtime & covered

    def lines(paths: set[str]) -> int:
        return sum(
            len((root / name).read_text(encoding="utf-8").splitlines())
            for name in paths
        )

    return {
        "schema_version": 1,
        "source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "measurement": "Current tracked worktree Python; physical lines include blanks/comments. Runtime scope matches the engineering audit. This is not diagnostic count or test coverage.",
        "strict_files_all": len(covered),
        "runtime_files": len(runtime),
        "runtime_lines": lines(runtime),
        "strict_runtime_files": len(strict_runtime),
        "strict_runtime_lines": lines(strict_runtime),
        "retired": retired,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        action="store_true",
        help="Add current strict paths; never silently remove protection",
    )
    args = parser.parse_args()
    try:
        print(json.dumps(verify(ROOT, record=args.record), indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Strict scope failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
