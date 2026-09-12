"""Provider identity does not require catalog discovery or authentication."""

import subprocess
import sys

import pytest

from superforecasting_agent.configuration.providers import (
    PROVIDER_ALIASES,
    normalize_provider,
    configured_provider,
)


@pytest.mark.parametrize('alias,canonical', list(PROVIDER_ALIASES.items()))
def test_aliases_normalize_consistently(alias, canonical):
    assert normalize_provider(f' {alias.upper()} ') == canonical
    assert normalize_provider(canonical) == canonical


@pytest.mark.parametrize('value,expected', [(None, 'openrouter'), ('', 'openrouter'), ('auto', 'auto'), ('custom:Desk', 'custom:desk'), ('plugin-new', 'plugin-new')])
def test_identity_preserves_unresolved_and_custom_providers(value, expected):
    assert normalize_provider(value) == expected


def test_import_does_not_discover_providers_or_load_runtime():
    result = subprocess.run([sys.executable, '-c', '''
import sys
from superforecasting_agent.configuration.providers import normalize_provider
assert normalize_provider('claude') == 'anthropic'
for prefix in ('superforecasting_agent.runtime', 'providers', 'agent', 'tui_gateway'):
    assert not any(n == prefix or n.startswith(prefix + '.') for n in sys.modules), prefix
'''], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('config,override,environment,expected', [
    ({'model': {'default': 'anthropic/claude', 'provider': 'openrouter'}}, '', '', 'openrouter'),
    ({'model': 'anthropic/claude'}, '', '', 'auto'),
    ({'model': {'provider': 'auto'}}, '', 'gemini', 'auto'),
    ({'model': {'provider': 'openrouter'}}, ' claude ', 'gemini', 'anthropic'),
    ({'model': {'provider': ''}}, '', 'gemini', 'gemini'),
    ({}, '', '', 'auto'),
])
def test_configured_provider_is_not_inferred_from_model(config, override, environment, expected):
    assert configured_provider(config, override=override, environment=environment) == expected


@pytest.mark.parametrize('value', [False, 1, [], {}])
def test_malformed_provider_selection_is_not_silently_auto(value):
    with pytest.raises(ValueError, match='model.provider'):
        configured_provider({'model': {'provider': value}})
