"""The contributor command must fail closed before claiming a clean checkout."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "dev.py"


def test_missing_tool_is_a_failed_check_not_a_clean_report(tmp_path):
    script = tmp_path / "scripts" / "dev.py"
    script.parent.mkdir()
    shutil.copyfile(SOURCE, script)
    result = subprocess.run([sys.executable, str(script), "check", "--python-only"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "bootstrap" in result.stderr
    assert "Development gate failed" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture; Windows missing-tool path is covered above")
def test_linter_process_failure_stops_the_quality_pipeline(tmp_path):
    script = tmp_path / "scripts" / "dev.py"
    script.parent.mkdir()
    shutil.copyfile(SOURCE, script)
    tool = tmp_path / ".venv" / "bin" / "ruff"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\necho 'fixture lint rejection' >&2\nexit 17\n", encoding="utf-8")
    tool.chmod(0o755)
    # Isolate linter rejection after successful naming and platform admission.
    tool.with_name("python").symlink_to(sys.executable)
    (script.parent / "check_naming.py").write_text("", encoding="utf-8")
    (script.parent / "check-windows-footguns.py").write_text("", encoding="utf-8")
    result = subprocess.run([sys.executable, str(script), "check", "--python-only"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "fixture lint rejection" in result.stderr
    assert "17" in result.stderr
    assert "protocol.codegen" not in result.stdout


@pytest.fixture
def snapshot_repo(tmp_path):
    script = tmp_path / "scripts" / "dev.py"
    script.parent.mkdir()
    shutil.copyfile(SOURCE, script)
    for name in ("push_plan.py", "check_naming.py"):
        shutil.copyfile(SOURCE.parent / name, script.parent / name)
    # The fixture owns a new history, not the production compatibility baseline.
    (script.parent / "legacy-naming-policy.json").write_text(
        '{"exceptions": []}\n', encoding="utf-8"
    )

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Gate Test")
    git("config", "user.email", "gate@example.invalid")
    git("config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "initial")

    def check(*args):
        return subprocess.run([sys.executable, str(script), "snapshot", *args],
                              capture_output=True, text=True)
    return tmp_path, git, check


def test_snapshot_rejects_unstaged_fix_hiding_staged_bug(snapshot_repo):
    root, git, check = snapshot_repo
    module = root / "module.py"
    module.write_text("value = invalid syntax\n", encoding="utf-8")
    git("add", "module.py")
    staged = git("show", ":module.py")
    module.write_text("value = 2\n", encoding="utf-8")
    result = check()
    assert result.returncode != 0
    assert "Unstaged" in result.stderr
    assert git("show", ":module.py") == staged
    assert module.read_text(encoding="utf-8") == "value = 2\n"
    git("add", "module.py")
    assert check().returncode == 0


def test_snapshot_rejects_pushing_a_different_tree(snapshot_repo):
    root, git, check = snapshot_repo
    original = git("rev-parse", "HEAD")
    assert check("--ref", original).returncode == 0
    (root / "module.py").write_text("value = 2\n", encoding="utf-8")
    git("add", "module.py")
    result = check("--ref", original)
    assert result.returncode != 0
    assert "pushed tree differs" in result.stderr
    git("commit", "-qm", "change")
    assert check("--ref", "HEAD").returncode == 0
    assert check("--ref", original).returncode != 0


def test_snapshot_rejects_untracked_import_shadow(snapshot_repo):
    root, git, check = snapshot_repo
    (root / "json.py").write_text("raise RuntimeError('shadow')\n", encoding="utf-8")
    assert check().returncode != 0
    failure = check()
    assert "Untracked" in failure.stderr
    assert "'json.py'" in failure.stderr
    (root / "json.py").unlink()
    (root / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    git("add", ".gitignore")
    (root / ".venv").mkdir()
    (root / ".venv" / "dependency").touch()
    assert check().returncode == 0


@pytest.mark.skipif(os.name == "nt", reason="Git hook execution uses POSIX bash")
def test_pre_push_checks_second_ref_before_running_quality(snapshot_repo):
    root, git, check = snapshot_repo
    shutil.copytree(SOURCE.parents[1] / ".githooks", root / ".githooks",
                    ignore=shutil.ignore_patterns("skips.log"))
    git("add", ".githooks")
    git("commit", "-qm", "hooks")
    old = git("rev-parse", "HEAD")
    (root / "module.py").write_text("value = 2\n", encoding="utf-8")
    git("add", "module.py")
    git("commit", "-qm", "change")
    current = git("rev-parse", "HEAD")
    refs = (f"refs/heads/current {current} refs/heads/current {old}\n"
            f"refs/heads/old {old} refs/heads/old {old}\n")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("HERMES_HOOKS_SKIP")}
    result = subprocess.run(["bash", ".githooks/pre-push"], input=refs,
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "pushed tree differs" in result.stderr, (
        result.stderr + "\nFixture status: " + git("status", "--short", "--untracked-files=all")
    )
    assert "Missing" not in result.stderr  # Never reached the missing linter.


def test_local_desk_fixture_import_does_not_modify_runtime(monkeypatch):
    import runpy
    import socket
    from tui_gateway import server

    monkeypatch.delenv("FORECAST_TEST_GATEWAY_PID", raising=False)
    connect, make_agent = socket.socket.connect, server._make_agent
    setup_status, get_db = server._methods["setup.status"], server._get_db
    runpy.run_path(str(SOURCE.parents[1] / "tests/fixtures/runtime/local_desk_gateway.py"))
    assert socket.socket.connect is connect
    assert server._make_agent is make_agent
    assert server._methods["setup.status"] is setup_status
    assert server._get_db is get_db


@pytest.mark.skipif(os.name == "nt", reason="Git hooks execute with POSIX bash")
@pytest.mark.parametrize("suite_status", [0, 1])
@pytest.mark.parametrize("changed", ["tui_gateway/commands.py", "README.md"])
def test_pre_push_runs_integration_and_propagates_failure(snapshot_repo, suite_status, changed):
    root, git, _ = snapshot_repo
    shutil.copytree(SOURCE.parents[1] / ".githooks", root / ".githooks",
                    ignore=shutil.ignore_patterns("skips.log"))
    checks = root / ".githooks/lib/checks.sh"
    with checks.open("a", encoding="utf-8") as stream:
        stream.write("\ncheck_snapshot() { return 0; }\n")
    (root / "scripts/dev.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path('suite-arguments').write_text(' '.join(sys.argv[1:]))\n"
        + f"sys.exit({suite_status})\n", encoding="utf-8"
    )
    git("add", ".")
    git("commit", "-qm", "gate fixture")
    base = git("rev-parse", "HEAD")
    target = root / changed
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n", encoding="utf-8")
    git("add", changed)
    git("commit", "-qm", "change")
    current = git("rev-parse", "HEAD")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("HERMES_HOOKS_SKIP")}
    result = subprocess.run(
        ["bash", ".githooks/pre-push"],
        input=f"refs/heads/current {current} refs/heads/current {base}\n",
        cwd=root, env=env, capture_output=True, text=True,
    )
    assert (root / "suite-arguments").read_text(encoding="utf-8").strip() == "verify --tier integration"
    assert result.returncode == suite_status
    if suite_status:
        assert "Integration tier failed" in result.stderr


def test_canonical_check_runs_reference_freshness_and_propagates_rejection(monkeypatch):
    from scripts import dev

    calls = []
    monkeypatch.setattr(dev, "venv_tool", lambda name: name)

    def run(*args, **kwargs):
        calls.append(args)
        if args == ("python", "-m", "scripts.docgen", "--check"):
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(dev, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        dev.check(python_only=True)
    assert ("python", "-m", "scripts.docgen", "--check") in calls
