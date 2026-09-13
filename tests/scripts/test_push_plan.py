"""Real repositories prove ref/base selection, including non-main remotes."""

import subprocess
from pathlib import Path

import pytest

from scripts import push_plan


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


@pytest.fixture
def repository(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "trunk")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "core.hooksPath", "/dev/null")
    (root / "backend.py").write_text("value = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial")
    first = git(root, "rev-parse", "HEAD")
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "--bare", str(root), str(remote))
    git(root, "remote", "add", "destination", str(remote))
    (root / "ui-tui").mkdir()
    (root / "ui-tui" / "view.ts").write_text("export const value = 1;\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "frontend")
    second = git(root, "rev-parse", "HEAD")
    (root / "backend.py").write_text("value = 2\n")
    git(root, "commit", "-am", "backend")
    third = git(root, "rev-parse", "HEAD")
    monkeypatch.chdir(root)
    return root, first, second, third


def test_new_branch_uses_actual_destination_default_not_tip_parent(repository):
    root, first, _, head = repository
    pairs = push_plan.plan(
        "destination",
        f"refs/heads/feature {head} refs/heads/feature {push_plan.ZERO}\n",
    )
    assert pairs == [(first, head)]
    assert "ui-tui/view.ts" in git(root, "diff", "--name-only", *pairs[0])


def test_multiple_refs_keep_their_own_heads_and_bases(repository):
    _, first, second, third = repository
    updates = f"refs/heads/one {second} refs/heads/one {first}\nrefs/heads/two {third} refs/heads/two {second}\n"
    assert push_plan.plan("destination", updates) == [(first, second), (second, third)]


def test_deleted_ref_does_not_query_unavailable_remote(repository):
    _, first, _, _ = repository
    assert (
        push_plan.plan(
            "missing-remote", f"(delete) {push_plan.ZERO} refs/heads/gone {first}\n"
        )
        == []
    )


def test_missing_old_object_inspects_all_files(repository):
    root, _, _, head = repository
    pairs = push_plan.plan(
        "destination", f"refs/heads/one {head} refs/heads/one {'1' * 40}\n"
    )
    assert "ui-tui/view.ts" in git(root, "diff", "--name-only", *pairs[0])
    assert "backend.py" in git(root, "diff", "--name-only", *pairs[0])


def test_empty_remote_inspects_entire_new_branch(repository, tmp_path):
    root, _, _, head = repository
    empty = tmp_path / "empty.git"
    git(tmp_path, "init", "--bare", str(empty))
    (pair,) = push_plan.plan(
        str(empty), f"refs/heads/one {head} refs/heads/one {push_plan.ZERO}\n"
    )
    assert "ui-tui/view.ts" in git(root, "diff", "--name-only", *pair)


def test_unreachable_destination_fails_closed(repository):
    _, _, _, head = repository
    with pytest.raises(subprocess.CalledProcessError):
        push_plan.plan(
            "missing-remote", f"refs/heads/one {head} refs/heads/one {push_plan.ZERO}\n"
        )
