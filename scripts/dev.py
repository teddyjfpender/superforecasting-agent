#!/usr/bin/env python3
"""Bootstrap and run the repository's shared, blocking quality checks.

Fresh checkout: python3 scripts/dev.py bootstrap
Existing checkout: python3 scripts/dev.py check
Python-only fast path: python3 scripts/dev.py check --python-only
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The stricter scope grows with ownership extractions. Legacy code still runs
# the repository-wide encoding gate; no silent baseline hides new-layer errors.
STRICT_PYTHON = ("forecasting/application", "forecasting/interfaces", "scripts/dev.py")


def run(*command: str, cwd: Path = ROOT) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def executable(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise RuntimeError(
            f"Required tool {name!r} is missing; install it before bootstrap"
        )
    return found


def venv_tool(name: str) -> str:
    directory = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    path = directory / (name + ".exe" if os.name == "nt" else name)
    if not path.is_file():
        raise RuntimeError(f"Missing {path}; run python3 scripts/dev.py bootstrap")
    return str(path)


def check(*, python_only: bool = False) -> None:
    run(venv_tool("ruff"), "check", ".")
    run(venv_tool("ruff"), "check", "--select", "E4,E7,E9,F,I", *STRICT_PYTHON)
    run(venv_tool("ruff"), "format", "--check", *STRICT_PYTHON)
    run(venv_tool("ty"), "check", *STRICT_PYTHON)
    run(venv_tool("lint-imports"))
    run(venv_tool("python"), "-m", "protocol.codegen", "--check")
    if not python_only:
        npm = executable("npm")
        run(npm, "run", "lint", cwd=ROOT / "ui-tui")
        run(npm, "run", "type-check", cwd=ROOT / "ui-tui")


def bootstrap() -> None:
    # --frozen consumes the checked-in dependency resolution; it cannot silently
    # update the lockfile while setting up a contributor or CI worker.
    run(executable("uv"), "sync", "--frozen", "--extra", "dev")
    npm = executable("npm")
    run(npm, "ci", cwd=ROOT / "ui-tui")
    run(npm, "run", "build", cwd=ROOT / "ui-tui")
    run(executable("git"), "config", "core.hooksPath", ".githooks")
    run(executable("git"), "config", "blame.ignoreRevsFile", ".git-blame-ignore-revs")
    check()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "check"))
    parser.add_argument(
        "--python-only",
        action="store_true",
        help="Check Python/contracts without requiring Node",
    )
    args = parser.parse_args()
    if args.command == "bootstrap" and args.python_only:
        parser.error("--python-only applies to check, not bootstrap")
    try:
        if args.command == "bootstrap":
            bootstrap()
        else:
            check(python_only=args.python_only)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Development gate failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
