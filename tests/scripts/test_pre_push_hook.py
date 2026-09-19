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
check_integration() { printf 'integration\\n' >> "$CALL_LOG"; }
check_vitest_changed() { printf 'frontend:%s\\n' "$1" >> "$CALL_LOG"; }
''')
    (tmp_path / 'scripts/push_plan.py').write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        "with Path(os.environ['CALL_LOG']).open('a') as log: log.write('destination:' + sys.argv[1] + '\\n')\n"
        "print('base-one head-one\\nbase-two head-two')\n"
    )
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
    result = subprocess.run(['bash', str(hooks / 'pre-push'), 'upstream', 'ssh://push-destination/repo'], env=env, cwd=tmp_path, capture_output=True, text=True)
    return result, log.read_text().splitlines() if log.exists() else []


def test_multiple_refs_run_integration_once_and_check_second_frontend_base(tmp_path):
    result, calls = hook_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    assert calls == ['destination:ssh://push-destination/repo', 'integration', 'frontend:base-two']


def test_different_tree_rejected_before_testing_wrong_checkout(tmp_path):
    result, calls = hook_fixture(tmp_path, denied='head-two')
    assert result.returncode != 0
    assert calls == ['destination:ssh://push-destination/repo']


def test_product_quality_enforces_same_integration_tier_without_renaming_check():
    import yaml

    workflow = yaml.safe_load((ROOT / '.github/workflows/product-quality.yml').read_text())
    assert workflow['name'] == 'Product quality'
    steps = workflow['jobs']['quality']['steps']
    assert any(step.get('run') == 'python3 scripts/dev.py verify --tier integration' for step in steps)
    assert any(step.get('if') == 'always()' and step.get('with', {}).get('path') == '.test-results/' for step in steps)
    # The push feedback change does not remove the complete Python CI gate.
    tests = yaml.safe_load((ROOT / '.github/workflows/tests.yml').read_text())
    assert any('scripts/run_tests.sh' in [line.strip() for line in step.get('run', '').splitlines()]
               for step in tests['jobs']['test']['steps'])


def test_frontend_gate_freezes_selection_and_handles_empty_full_and_failed_listing(tmp_path):
    import json

    frontend = tmp_path / 'ui-tui'
    binary = frontend / 'node_modules/.bin/vitest'
    binary.parent.mkdir(parents=True)
    for name in ('first test.ts', 'second.ts', 'third.ts'):
        (frontend / name).touch()
    log = tmp_path / 'calls.jsonl'
    binary.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1] == 'list':
    if '--changed' not in sys.argv or os.environ['SELECTION'] == 'full':
        print('first test.ts\\nsecond.ts\\nthird.ts')
    elif os.environ['SELECTION'] == 'subset':
        print('first test.ts\\nsecond.ts')
    elif os.environ['SELECTION'] == 'failure':
        sys.exit(2)
    elif os.environ['SELECTION'] == 'invalid':
        print('--watch')
else:
    assert '--changed' not in sys.argv
    assert sys.stdin.read() == ''
''')
    binary.chmod(0o755)
    script = '''
source "$CHECKS"
hook_note() { :; }
hook_fail() { printf '%s\\n' "$1" >&2; }
check_vitest_changed exact-base
'''
    for mode in ('subset', 'empty', 'full', 'failure', 'invalid'):
        log.unlink(missing_ok=True)
        env = {**os.environ, 'HOOKS_REPO_ROOT': str(tmp_path), 'CALL_LOG': str(log),
               'CHECKS': str(ROOT / '.githooks/lib/checks.sh'), 'SELECTION': mode}
        result = subprocess.run(['bash', '-c', script], env=env, cwd=tmp_path,
                                input='other-ref must not be consumed', capture_output=True, text=True)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        assert calls[0] == ['list', '--changed', 'exact-base', '--filesOnly']
        runs = [call for call in calls if call[0] == 'run']
        if mode == 'subset':
            assert result.returncode == 0, result.stderr
            assert runs == [['run', 'first test.ts', 'second.ts']]
        else:
            assert not runs
            assert (result.returncode == 0) == (mode == 'empty')
        if mode == 'full':
            assert 'full TUI suite' in result.stderr
