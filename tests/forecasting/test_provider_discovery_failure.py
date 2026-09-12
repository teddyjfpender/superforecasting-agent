"""A failed discovery cannot prove a single-provider forecasting environment."""

import pytest

from forecasting.quorum import panels
from superforecasting_agent.configuration.provider_catalog import ProviderEntry
from superforecasting_agent.runtime import auth, models


@pytest.fixture
def partial_discovery(monkeypatch):
    monkeypatch.setattr(models, 'CANONICAL_PROVIDERS', [
        ProviderEntry('anthropic', 'Anthropic', ''),
        ProviderEntry('gemini', 'Gemini', ''),
    ])
    monkeypatch.setattr(models, '_get_custom_base_url', lambda: '')

    def status(provider):
        if provider == 'gemini':
            raise OSError('fixture credential store unavailable')
        return {'configured': True}

    monkeypatch.setattr(auth, 'get_auth_status', status)


def test_partial_discovery_does_not_claim_only_one_provider(partial_discovery):
    assert panels.available_provider_slugs() is None
    assert panels.available_providers_detail() is None
    result = panels.resolve_connected_panel('frontier', active_model='claude')
    assert result['rebuilt'] is False
    assert result['self_fusion'] is False


def test_inventory_reports_the_failed_provider(partial_discovery):
    with pytest.raises(RuntimeError, match='gemini'):
        models.list_available_providers()



def test_confirmed_disconnection_still_allows_single_provider_panel(monkeypatch, partial_discovery):
    monkeypatch.setattr(auth, 'get_auth_status', lambda provider: {'configured': provider == 'anthropic'})
    assert panels.available_provider_slugs() == {'anthropic'}
    result = panels.resolve_connected_panel('frontier', active_model='claude')
    assert result['rebuilt'] is True
    assert result['self_fusion'] is True
