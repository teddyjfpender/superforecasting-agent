"""Startup loading preserves plugin keys without loading CLI configuration."""

import subprocess
import sys


def test_loading_plugin_credentials_does_not_import_runtime(tmp_path):
    home = tmp_path / 'profile'
    home.mkdir()
    (home / '.env').write_text('PLUGIN_TOKEN=firstOPENAI_API_KEY=second\n', encoding='utf-8')
    plugin = tmp_path / 'plugins' / 'platforms' / 'example'
    plugin.mkdir(parents=True)
    (plugin / 'plugin.yaml').write_text('requires_env:\n  - PLUGIN_TOKEN\n', encoding='utf-8')
    (plugin / '__init__.py').write_text('raise AssertionError("plugin imported")\n', encoding='utf-8')
    result = subprocess.run([sys.executable, '-c', '''
import os, sys
from pathlib import Path
from superforecasting_agent import paths, startup_environment
root = Path(sys.argv[1])
paths.get_install_root = lambda: root
loaded = startup_environment.load_forecast_dotenv(hermes_home=root / 'profile')
assert loaded == [root / 'profile' / '.env']
assert os.environ['PLUGIN_TOKEN'] == 'first'
assert os.environ['OPENAI_API_KEY'] == 'second'
assert not any(n == 'superforecasting_agent.runtime' or n.startswith('superforecasting_agent.runtime.') for n in sys.modules)
''', str(tmp_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_legacy_import_shares_the_same_mutable_owner():
    from superforecasting_agent import startup_environment
    from superforecasting_agent.runtime import env_loader
    assert env_loader is startup_environment
    assert env_loader._SECRET_SOURCES is startup_environment._SECRET_SOURCES
    assert env_loader._WARNED_KEYS is startup_environment._WARNED_KEYS
