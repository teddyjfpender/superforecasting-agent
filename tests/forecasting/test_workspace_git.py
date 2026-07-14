from __future__ import annotations

import subprocess

import pytest

from forecasting.models import ValidationError
from forecasting.workspace.git import ManagedGit, managed_checkout_path


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True, capture_output=True
    ).stdout.strip()


def _remote(tmp_path):
    source = tmp_path / "source;not-a-shell-command"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "tests@example.com")
    _git(source, "config", "user.name", "Forecast Tests")
    (source / "forecast-workspace.yaml").write_text("format_version: 1\n")
    _git(source, "add", "forecast-workspace.yaml")
    _git(source, "commit", "-m", "initial")
    bare = tmp_path / "remote.git"
    _git(tmp_path, "clone", "--bare", str(source), str(bare))
    return source, bare


def test_managed_git_uses_literal_argv_and_reports_dirty_state(tmp_path):
    _, remote = _remote(tmp_path)
    managed = ManagedGit(timeout_seconds=10)
    checkout = managed.clone(str(remote), tmp_path / "checkout", branch="main")
    assert managed.status(checkout)["dirty"] is False
    (checkout / "forecast-workspace.yaml").write_text("changed: true\n")
    assert managed.status(checkout)["dirty"] is True
    with pytest.raises(ValidationError, match="dirty"):
        managed.pull_ff_only(checkout)


def test_managed_git_fast_forwards_clean_checkout(tmp_path):
    source, remote = _remote(tmp_path)
    managed = ManagedGit(timeout_seconds=10)
    checkout = managed.clone(str(remote), tmp_path / "checkout", branch="main")
    (source / "README.md").write_text("Forecast workspace\n")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "update")
    _git(source, "push", str(remote), "main")
    status = managed.pull_ff_only(checkout)
    assert status["dirty"] is False
    assert (checkout / "README.md").is_file()


def test_managed_checkout_path_rejects_traversal():
    with pytest.raises(ValidationError, match="unsafe"):
        managed_checkout_path("../outside")
