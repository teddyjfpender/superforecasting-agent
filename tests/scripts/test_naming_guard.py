"""New legacy branding needs a narrow reviewed exception, including filenames."""

import json
import subprocess

import pytest

from scripts.check_naming import POLICY, violations


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    git("config", "core.hooksPath", "/dev/null")
    policy = tmp_path / POLICY
    policy.parent.mkdir()
    policy.write_text(
        json.dumps({
            "exceptions": [
                {
                    "category": "compatibility",
                    "paths": ["compat.py"],
                    "token": "HERMES_HOME",
                    "reason": "Existing profile environment alias",
                }
            ]
        })
    )
    (tmp_path / "existing.py").write_text('old = "Hermes"\n')
    git("add", ".")
    git("commit", "-m", "initial")
    return tmp_path, git


def test_new_branding_and_legacy_filename_are_rejected(repo):
    root, git = repo
    (root / "view.py").write_text('label = "Hermes Agent"\n')
    (root / "hermes_new.py").write_text("value = 1\n")
    git("add", ".")
    errors = violations("HEAD", "WORKTREE", root=root)
    assert any("view.py" in error for error in errors)
    assert any("hermes_new.py" in error for error in errors)


def test_exception_is_limited_to_token_and_owner(repo):
    root, git = repo
    for name in ("compat.py", "view.py"):
        (root / name).write_text('key = "HERMES_HOME"\n')
    git("add", ".")
    errors = violations("HEAD", "WORKTREE", root=root)
    assert len(errors) == 1 and errors[0].startswith("view.py:")


def test_existing_reference_can_move_but_cannot_multiply(repo):
    root, git = repo
    existing = root / "existing.py"
    existing.write_text('\n\nold = "Hermes"\n')
    assert violations("HEAD", "WORKTREE", root=root) == []
    existing.write_text('old = "Hermes"\nnew = "Hermes"\n')
    assert violations("HEAD", "WORKTREE", root=root)


def test_committed_range_cannot_be_hidden_by_clean_worktree(repo):
    root, git = repo
    (root / "view.py").write_text('label = "Hermes"\n')
    git("add", ".")
    git("commit", "-m", "new")
    assert violations("HEAD^", "HEAD", root=root)
