"""Credential ownership must hold independently of interactive products."""

import subprocess
import sys
from unittest.mock import Mock

import pytest


def test_credentials_import_without_runtime_or_presentation():
    script = '''
import sys
from superforecasting_agent.credentials import auth, catalog, anthropic, copilot, azure
assert callable(auth.get_auth_status)
assert callable(catalog.list_available_providers)
for prefix in ('superforecasting_agent.runtime', 'cli', 'tui_gateway', 'gateway', 'forecasting.cli'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
'''
    result = subprocess.run([sys.executable, "-c", script], text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("token", [None, "", "  ", 42, False])
def test_mint_rejects_missing_or_nontext_token_before_network(token):
    from superforecasting_agent.credentials.auth import AuthError, _mint_agent_key

    client = Mock()
    with pytest.raises(AuthError, match="Missing access token"):
        _mint_agent_key(client=client, portal_base_url="https://invalid.example", access_token=token, min_ttl_seconds=60)
    client.post.assert_not_called()


def test_interactive_compatibility_exports_share_credential_functions():
    from superforecasting_agent.credentials import auth, copilot
    from superforecasting_agent.runtime import auth as interactive_auth
    from superforecasting_agent.runtime import copilot_auth

    assert interactive_auth.get_auth_status is auth.get_auth_status
    assert interactive_auth.resolve_nous_runtime_credentials is auth.resolve_nous_runtime_credentials
    assert copilot_auth.resolve_copilot_token is copilot.resolve_copilot_token
    assert callable(interactive_auth.login_command)
    assert callable(copilot_auth.copilot_device_code_login)
