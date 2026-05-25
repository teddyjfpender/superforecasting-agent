#!/usr/bin/env python3
"""Run the local tester-handoff gate for Superforecasting Agent."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


HANDOFF_TESTS = [
    "tests/forecasting/test_smoke_script.py",
    "tests/forecasting/test_package_identity.py",
    "tests/test_superforecasting_agent_cli.py",
    "tests/test_project_metadata.py",
]

COMPILE_DIRS = [
    "forecasting",
    "superforecasting_agent",
]

COMPILE_FILES = [
    "tools/forecasting_tool.py",
    "scripts/forecast_smoke_test.py",
    "scripts/tester_handoff_check.py",
]


class HandoffError(RuntimeError):
    """Raised when a handoff gate command fails."""


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that a fork snapshot is ready for a friendly tester handoff. "
            "This is a product-readiness gate, not evidence of live forecasting superiority."
        )
    )
    parser.add_argument("--skip-smoke", action="store_true", help="Skip scripts/forecast_smoke_test.py")
    parser.add_argument("--skip-tests", action="store_true", help="Skip focused pytest coverage")
    parser.add_argument("--skip-compile", action="store_true", help="Skip Python compile checks")
    parser.add_argument("--skip-diff-check", action="store_true", help="Skip git diff --check")
    parser.add_argument(
        "--include-website-build",
        action="store_true",
        help="Also run npm run build in website/. This may emit inherited localized broken-link warnings.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands that would run without executing them.",
    )
    return parser.parse_args(argv)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _git_snapshot(repo_root: Path) -> str:
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    suffix = ", dirty" if dirty else ""
    return f"{rev} ({branch}{suffix})" if branch else rev


def _print_step(message: str) -> None:
    print(f"[tester-handoff] {message}", flush=True)


def _command_text(command: list[str]) -> str:
    return shlex.join(command)


def _run(
    label: str,
    command: list[str],
    *,
    cwd: Path,
    dry_run: bool,
    env: dict[str, str] | None = None,
) -> None:
    _print_step(f"{label}: {_command_text(command)}")
    if dry_run:
        return
    result = subprocess.run(command, cwd=cwd, env=env)
    if result.returncode != 0:
        raise HandoffError(f"{label} failed with exit {result.returncode}")


def _verify_help(repo_root: Path, *, dry_run: bool) -> None:
    command = [sys.executable, "-m", "superforecasting_agent", "--help"]
    _print_step(f"identity help: {_command_text(command)}")
    if dry_run:
        return
    result = subprocess.run(command, cwd=repo_root, capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    if result.returncode != 0:
        print(output.rstrip())
        raise HandoffError(f"identity help failed with exit {result.returncode}")
    required = [
        "Superforecasting Agent",
        "forecast records",
        "pilot-report",
        "readiness",
        "self-check",
        "backtest",
    ]
    missing = [phrase for phrase in required if phrase not in output]
    if missing:
        raise HandoffError(f"identity help missing expected phrase(s): {', '.join(missing)}")


def run_handoff_check(args: argparse.Namespace) -> int:
    repo_root = _repo_root()
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")

    _print_step(f"snapshot: {_git_snapshot(repo_root)}")
    _print_step("claim: this gate verifies tester handoff plumbing, not live forecasting superiority")

    _verify_help(repo_root, dry_run=args.dry_run)

    if not args.skip_compile:
        _run(
            "compile packages",
            [sys.executable, "-m", "compileall", "-q", *COMPILE_DIRS],
            cwd=repo_root,
            dry_run=args.dry_run,
            env=env,
        )
        _run(
            "compile files",
            [sys.executable, "-m", "py_compile", *COMPILE_FILES],
            cwd=repo_root,
            dry_run=args.dry_run,
            env=env,
        )

    if not args.skip_tests:
        _run(
            "focused tests",
            ["scripts/run_tests.sh", *HANDOFF_TESTS, "-q"],
            cwd=repo_root,
            dry_run=args.dry_run,
            env=env,
        )

    if not args.skip_smoke:
        _run(
            "forecast smoke",
            [sys.executable, "scripts/forecast_smoke_test.py"],
            cwd=repo_root,
            dry_run=args.dry_run,
            env=env,
        )

    if not args.skip_diff_check:
        _run("diff whitespace", ["git", "diff", "--check"], cwd=repo_root, dry_run=args.dry_run)

    if args.include_website_build:
        _run("website build", ["npm", "run", "build"], cwd=repo_root / "website", dry_run=args.dry_run, env=env)

    _print_step("handoff gate passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return run_handoff_check(args)
    except HandoffError as exc:
        _print_step(f"handoff gate failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
