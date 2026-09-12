"""Bedrock inspection does not install optional dependencies at import time."""

import subprocess
import sys
from unittest.mock import MagicMock, patch


def test_import_never_invokes_dependency_installer():
    result = subprocess.run([sys.executable, '-c', '''
import sys
from types import ModuleType
calls = []
lazy = ModuleType('tools.lazy_deps')
lazy.ensure = lambda *args, **kwargs: calls.append((args, kwargs))
sys.modules['tools.lazy_deps'] = lazy
import agent.bedrock_adapter
assert calls == [], calls
assert 'boto3' not in sys.modules
'''], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_missing_credentials_probe_sdk_only_once():
    from agent.bedrock_adapter import has_aws_credentials

    session = MagicMock()
    session.get_credentials.return_value = None
    with patch.dict('sys.modules', {'botocore': MagicMock(), 'botocore.session': MagicMock()}):
        import botocore.session as sdk
        sdk.get_session = MagicMock(return_value=session)
        assert has_aws_credentials({}) is False
        sdk.get_session.assert_called_once()
        session.get_credentials.assert_called_once()


def test_discovery_owner_imports_no_execution_modules():
    result = subprocess.run([sys.executable, '-c', '''
import sys
from superforecasting_agent.hosting import aws_credentials
assert aws_credentials.has_aws_credentials({'AWS_PROFILE': 'fixture'})
for prefix in ('agent', 'tools', 'superforecasting_agent.runtime', 'boto3', 'botocore'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
'''], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_sdk_install_is_deferred_until_client_use(monkeypatch):
    import builtins
    from types import ModuleType
    from agent.bedrock_adapter import _require_boto3

    original_import = builtins.__import__
    installed = []
    sdk = ModuleType('boto3')
    lazy = ModuleType('tools.lazy_deps')
    lazy.ensure = lambda *args, **kwargs: installed.append((args, kwargs))
    monkeypatch.setitem(sys.modules, 'tools.lazy_deps', lazy)

    def importing(name, *args, **kwargs):
        if name == 'boto3':
            if not installed:
                raise ImportError('fixture SDK absent')
            return sdk
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', importing)
    assert _require_boto3() is sdk
    assert _require_boto3() is sdk
    assert installed == [(('provider.bedrock',), {'prompt': False})]
