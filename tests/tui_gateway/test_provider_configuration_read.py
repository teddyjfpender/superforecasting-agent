"""Configuration inspection must not execute credential discovery."""

from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from tui_gateway import server


def test_provider_configuration_is_not_authentication(monkeypatch):
    from superforecasting_agent.runtime import models

    monkeypatch.setattr(server._host.configuration, 'last_error', None)
    discovery = Mock(side_effect=AssertionError('credential discovery during config read'))
    monkeypatch.setattr(models, 'list_available_providers', discovery)
    monkeypatch.setattr(server, '_load_cfg', lambda: {
        'model': {'default': 'anthropic/claude-example', 'provider': 'openrouter'},
    })
    monkeypatch.setattr(server, '_desk_launch_overrides', lambda: {})
    monkeypatch.setattr(server, '_resolve_model', lambda *args: 'anthropic/claude-example')
    result = server.handle_request({
        'id': 'read', 'method': 'config.get', 'params': {'key': 'provider'},
    })
    assert 'error' not in result, result
    payload = result['result']
    assert payload['provider'] == 'openrouter'
    assert payload['authentication_status'] == 'not_checked'
    assert payload['providers']
    assert all(row['authenticated'] is None for row in payload['providers'])
    discovery.assert_not_called()
    from protocol.rpc.config import ConfigProviderResponse
    assert ConfigProviderResponse.model_validate(payload).provider == 'openrouter'



def test_unreadable_configuration_does_not_report_auto(tmp_path, monkeypatch):
    from superforecasting_agent.hosting.configuration import ProfileConfiguration

    tmp_path = tmp_path / 'profile'
    tmp_path.mkdir()
    path = tmp_path / 'config.yaml'
    path.write_text('model: [', encoding='utf-8')
    monkeypatch.setattr(server, '_hermes_home', tmp_path)
    monkeypatch.setattr(server._host, 'configuration', ProfileConfiguration())
    response = server.handle_request({
        'id': 'read', 'method': 'config.get', 'params': {'key': 'provider'},
    })
    assert response['error']['code'] == 5013
    assert path.read_text(encoding='utf-8') == 'model: ['
    assert sorted(p.name for p in tmp_path.iterdir()) == ['config.yaml']



def test_unchecked_configuration_cannot_claim_authentication():
    from protocol.rpc.config import ConfigProviderEntry

    with pytest.raises(ValidationError):
        ConfigProviderEntry(id='openrouter', label='OpenRouter', aliases=[], authenticated=True)
