"""Explicit release verification must fail when a required check cannot run."""

from pathlib import Path
import os
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("unavailable", [None, "protocol", "protocol-mode", "docgen", "tests", "tests-mode"])
def test_explicit_checks_require_available_toolchains(tmp_path, unavailable):
    repo = tmp_path / "candidate"
    for name in ["scripts/check-release-ready.sh", "pyproject.toml", "superforecasting_agent/runtime/__init__.py", "CHANGELOG.md"]:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / name, target)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Isolate tag/worktree inputs: unused version tag and a clean candidate.
    git = bin_dir / "git"
    git.write_text('#!/bin/sh\ncase "$1" in status) exit 0;; rev-parse) exit 1;; *) exit 2;; esac\n')
    git.chmod(0o755)
    python = bin_dir / "fixture-python"
    python.write_text("#!/bin/sh\nexit " + ("1" if unavailable == "docgen" else "0") + "\n")
    python.chmod(0o755)
    for name, filename in [("protocol", "check-protocol.sh"), ("tests", "run_tests.sh")]:
        path = repo / "scripts" / filename
        if unavailable == name:
            continue
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o644 if unavailable == name + "-mode" else 0o755)
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"], "PYTHON": str(python)}
    env.pop("GITHUB_REF", None)
    result = subprocess.run(["bash", "scripts/check-release-ready.sh", "--strict", "--with-tests"], cwd=repo, env=env, capture_output=True, text=True, timeout=30)
    if unavailable is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "can be released" in result.stdout
    else:
        assert result.returncode == 1, result.stdout + result.stderr
        assert "NOT READY" in result.stdout
        assert "can be released" not in result.stdout
