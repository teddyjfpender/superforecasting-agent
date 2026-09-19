"""Moving or changing ownership cannot silently retire protected strict checks."""

import json
import subprocess

import pytest

from scripts.strict_scope import POLICY, verify


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Scope Test")
    git("config", "user.email", "scope@example.invalid")
    git("config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (tmp_path / "scripts").mkdir()
    (tmp_path / "forecasting").mkdir()
    (tmp_path / "scripts/dev.py").write_text(
        'STRICT_PYTHON = ("forecasting/owned.py",)\n'
    )
    (tmp_path / "forecasting/owned.py").write_text("# comment\n\nvalue = 1\n")
    (tmp_path / "forecasting/legacy.py").write_text("value = 2\n")
    (tmp_path / POLICY).write_text(
        json.dumps({"schema_version": 1, "protected_files": [], "retired": {}})
    )
    git("add", ".")
    git("commit", "-qm", "initial fixture")
    verify(tmp_path, record=True)
    return tmp_path, git


def test_report_distinguishes_runtime_scope_from_test_coverage(repo):
    root, _ = repo
    report = verify(root)
    assert report["runtime_files"] == 2
    assert report["runtime_lines"] == 4
    assert report["strict_runtime_files"] == 1
    assert report["strict_runtime_lines"] == 3
    assert "not diagnostic count or test coverage" in report["measurement"]


@pytest.mark.parametrize("move", [False, True])
def test_lost_owner_fails_even_when_recording_new_scope(repo, move):
    root, git = repo
    if move:
        git("mv", "forecasting/owned.py", "forecasting/moved.py")
    else:
        (root / "scripts/dev.py").write_text(
            'STRICT_PYTHON = ("forecasting/legacy.py",)\n'
        )
    with pytest.raises(ValueError, match="strict ownership lost"):
        verify(root, record=True)


def test_added_owner_requires_protection_and_record_never_deletes_old_entries(repo):
    root, _ = repo
    (root / "scripts/dev.py").write_text('STRICT_PYTHON = ("forecasting",)\n')
    with pytest.raises(ValueError, match="new strict owners"):
        verify(root)
    verify(root, record=True)
    policy = json.loads((root / POLICY).read_text())
    assert policy["protected_files"] == [
        "forecasting/legacy.py",
        "forecasting/owned.py",
    ]


def test_move_requires_explicit_retirement_and_protected_replacement(repo):
    root, git = repo
    git("mv", "forecasting/owned.py", "forecasting/moved.py")
    (root / "scripts/dev.py").write_text('STRICT_PYTHON = ("forecasting/moved.py",)\n')
    path = root / POLICY
    policy = json.loads(path.read_text())
    policy["retired"] = {
        "forecasting/owned.py": "Moved into forecasting/moved.py with the same strict gates."
    }
    path.write_text(json.dumps(policy))
    verify(root, record=True)
    assert verify(root)["strict_runtime_files"] == 1
    assert json.loads(path.read_text())["protected_files"] == [
        "forecasting/moved.py",
        "forecasting/owned.py",
    ]


def test_empty_retirement_reason_cannot_hide_missing_checks(repo):
    root, _ = repo
    path = root / POLICY
    policy = json.loads(path.read_text())
    policy["retired"] = {"forecasting/owned.py": ""}
    path.write_text(json.dumps(policy))
    with pytest.raises(ValueError, match="meaningful review reason"):
        verify(root)
