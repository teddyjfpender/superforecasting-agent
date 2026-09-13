"""Exercise the hook orchestration with controlled gates, never a nested suite."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def hook_fixture(tmp_path, denied=''):
    hooks = tmp_path / '.githooks'
    (hooks / 'lib').mkdir(parents=True)
    (tmp_path / 'scripts').mkdir()
    shutil.copyfile(ROOT / '.githooks/pre-push', hooks / 'pre-push')
    (hooks / 'lib/common.sh').write_text('''
HOOKS_REPO_ROOT="$FIXTURE_ROOT"
hook_honor_global_skip() { return 1; }
hook_python() { printf '%s\\n' "$FIXTURE_PYTHON"; }
hook_note() { :; }
hook_fail() { :; }
''')
    (hooks / 'lib/checks.sh').write_text('''
check_snapshot() { [ "$2" != "$DENIED_HEAD" ]; }
check_quality() { printf 'quality:%s\\n' "$*" >> "$CALL_LOG"; }
check_vitest_changed() { printf 'frontend:%s\\n' "$1" >> "$CALL_LOG"; }
''')
    (tmp_path / 'scripts/push_plan.py').write_text("print('base-one head-one\\nbase-two head-two')\n")
    (tmp_path / 'scripts/check_naming.py').write_text('')
    runner = tmp_path / 'scripts/run_tests.sh'
    runner.write_text('#!/bin/sh\nprintf "suite\\n" >> "$CALL_LOG"\n')
    runner.chmod(0o755)
    bins = tmp_path / 'bin'
    bins.mkdir()
    git = bins / 'git'
    # Only the second pushed ref changes the frontend.
    git.write_text('#!/bin/sh\nif [ "$3" = "base-two" ]; then echo ui-tui/src/app.tsx; else echo agent/runtime.py; fi\n')
    git.chmod(0o755)
    log = tmp_path / 'calls'
    env = {**os.environ, 'FIXTURE_ROOT': str(tmp_path), 'FIXTURE_PYTHON': sys.executable,
           'PATH': str(bins) + os.pathsep + os.environ['PATH'], 'CALL_LOG': str(log), 'DENIED_HEAD': denied}
    result = subprocess.run(['bash', str(hooks / 'pre-push'), 'upstream'], env=env, cwd=tmp_path, capture_output=True, text=True)
    return result, log.read_text().splitlines() if log.exists() else []


def test_multiple_refs_run_suite_once_and_check_second_frontend_base(tmp_path):
    result, calls = hook_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    assert calls == ['quality:', 'suite', 'frontend:base-two']


def test_different_tree_rejected_before_testing_wrong_checkout(tmp_path):
    result, calls = hook_fixture(tmp_path, denied='head-two')
    assert result.returncode != 0
    assert calls == []
