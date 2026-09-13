"""The canonical runner must actually admit only explicitly selected live suites."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name == 'nt', reason='canonical shell runner requires bash')
@pytest.mark.parametrize('selection,retained', [
    ([], []),
    (['--live-service=daytona'], ['DAYTONA_API_KEY']),
    (['--live-service', 'modal'], ['MODAL_TOKEN_ID', 'MODAL_TOKEN_SECRET']),
])
def test_runner_filters_credentials_and_selects_live_files(tmp_path, selection, retained):
    root = Path(__file__).resolve().parents[2]
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    shutil.copy2(root / 'scripts/run_tests.sh', scripts / 'run_tests.sh')
    bins = tmp_path / '.venv/bin'
    bins.mkdir(parents=True)
    (bins / 'activate').touch()
    python = bins / 'python'
    python.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
if '-m' in sys.argv:
    keys = ['DAYTONA_API_KEY', 'MODAL_TOKEN_ID', 'MODAL_TOKEN_SECRET', 'OPENAI_API_KEY']
    print('RECEIPT ' + json.dumps({'keys': [k for k in keys if os.environ.get(k)], 'args': sys.argv[1:]}))
''')
    python.chmod(0o755)
    env = {**os.environ, 'HOME': str(tmp_path),
           'DAYTONA_API_KEY': 'fixture', 'MODAL_TOKEN_ID': 'fixture',
           'MODAL_TOKEN_SECRET': 'fixture', 'OPENAI_API_KEY': 'unrelated-fixture'}
    result = subprocess.run(['bash', str(scripts / 'run_tests.sh'), *selection],
                            env=env, capture_output=True, text=True, check=True)
    receipt = json.loads(next(line.removeprefix('RECEIPT ') for line in result.stdout.splitlines() if line.startswith('RECEIPT ')))
    assert receipt['keys'] == retained
    marker = receipt['args'][receipt['args'].index('-m', 2) + 1]
    assert marker == ('integration' if selection else 'not integration')
    if selection:
        service = 'daytona' if 'DAYTONA_API_KEY' in retained else 'modal'
        assert f'tests/integration/test_{service}_terminal.py' in receipt['args']
        assert '--ignore=tests/integration' not in receipt['args']


@pytest.mark.skipif(os.name == 'nt', reason='canonical shell runner requires bash')
def test_missing_explicit_credentials_fail_before_tests(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if k != 'DAYTONA_API_KEY'}
    result = subprocess.run(['bash', str(root / 'scripts/run_tests.sh'), '--live-service=daytona'],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert 'requires DAYTONA_API_KEY' in result.stderr
