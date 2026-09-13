"""Environment metadata has one owner without requiring CLI initialization."""

import subprocess
import sys

from superforecasting_agent.configuration import environment_catalog
from superforecasting_agent.runtime import config


def test_runtime_compatibility_preserves_catalog_identity(monkeypatch):
    assert config.OPTIONAL_ENV_VARS is environment_catalog.OPTIONAL_ENV_VARS
    assert config.REQUIRED_ENV_VARS is environment_catalog.REQUIRED_ENV_VARS
    assert config._EXTRA_ENV_KEYS is environment_catalog._EXTRA_ENV_KEYS
    monkeypatch.setitem(config.OPTIONAL_ENV_VARS, 'TEST_PLUGIN_CATALOG_KEY', {'password': True})
    assert environment_catalog.OPTIONAL_ENV_VARS['TEST_PLUGIN_CATALOG_KEY']['password'] is True


def test_catalog_import_does_not_initialize_runtime():
    result = subprocess.run([sys.executable, '-c', '''
import sys
from superforecasting_agent.configuration.environment_catalog import OPTIONAL_ENV_VARS
assert 'OPENROUTER_API_KEY' in OPTIONAL_ENV_VARS
assert not any(n == 'superforecasting_agent.runtime' or n.startswith('superforecasting_agent.runtime.') for n in sys.modules)
'''], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
