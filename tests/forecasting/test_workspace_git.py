from __future__ import annotations

import subprocess
from pathlib import Path

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


def test_managed_git_rejects_executable_remotes_and_local_drivers(tmp_path):
    managed = ManagedGit(timeout_seconds=10)
    with pytest.raises(ValidationError, match="HTTPS"):
        managed.clone("ext::sh -c touch /tmp/pwned", tmp_path / "checkout")

    _, remote = _remote(tmp_path)
    checkout = managed.clone(str(remote), tmp_path / "safe", branch="main")
    _git(checkout, "config", "filter.hostile.clean", "touch /tmp/pwned")
    with pytest.raises(ValidationError, match="unsafe Git configuration"):
        managed.status(checkout)


def test_managed_git_credentials_use_askpass_not_arguments(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs["env"]))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ManagedGit().run(
        ["fetch", "origin"],
        credential_callback=lambda: ("x-access-token", "github-secret-token"),
    )

    argv, env = calls[0]
    assert "github-secret-token" not in argv
    assert env["GIT_ASKPASS_REQUIRE"] == "force"
    assert env["SFA_GIT_PASSWORD"] == "github-secret-token"
    assert not Path(env["GIT_ASKPASS"]).exists()
