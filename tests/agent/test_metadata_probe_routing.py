"""Native metadata discovery must respect endpoint protocol identity."""

from unittest.mock import Mock

import pytest

from agent import model_metadata as metadata


@pytest.mark.parametrize('url', [
    'https://api.openai.com/v1', 'https://api.anthropic.com',
    'https://openrouter.ai/api/v1', 'https://chatgpt.com/backend-api/codex',
    'https://api.minimax.io/anthropic', 'https://api.minimax.chat/v1',
])
def test_known_non_ollama_endpoint_never_allocates_probe_client(monkeypatch, url):
    client = Mock(side_effect=AssertionError('unsupported native probe'))
    monkeypatch.setattr('httpx.Client', client)
    assert metadata._query_ollama_api_show('model', url, api_key='fixture') is None
    client.assert_not_called()


@pytest.mark.parametrize('url,provider', [
    ('https://api.openai.com:443/v1', 'openai'),
    ('https://API.OPENAI.COM./v1', 'openai'),
    ('https://token-plan-cn.xiaomimimo.com/v1', 'xiaomi'),
    ('https://api.minimaxi.com/anthropic', 'minimax-cn'),
    ('https://api.openai.com.proxy.invalid/v1', None),
    ('https://notapi.openai.com/v1', None),
    ('https://api.openai.com@proxy.invalid/v1', None),
    ('https://proxy.invalid/api.openai.com/v1', None),
])
def test_provider_identity_uses_host_boundaries(url, provider):
    assert metadata._infer_provider_from_url(url) == provider


@pytest.mark.parametrize('url', [
    'https://ollama.com/v1', 'http://localhost:11434/v1',
    'https://private-models.example/v1',
])
def test_ollama_local_and_custom_discovery_remains_available(monkeypatch, url):
    client = Mock()
    client.post.return_value = Mock(status_code=200, json=lambda: {'model_info': {'llama.context_length': 65536}})
    context = Mock(__enter__=Mock(return_value=client), __exit__=Mock(return_value=False))
    factory = Mock(return_value=context)
    monkeypatch.setattr('httpx.Client', factory)
    assert metadata._query_ollama_api_show('model', url, api_key='fixture') == 65536
    client.post.assert_called_once_with(url.removesuffix('/v1') + '/api/show', json={'name': 'model'})


def test_context_resolution_uses_provider_catalog_without_native_probe(monkeypatch):
    client = Mock(side_effect=AssertionError('unsupported native probe'))
    lookup = Mock(return_value=131072)
    monkeypatch.setattr('httpx.Client', client)
    monkeypatch.setattr(metadata, 'get_cached_context_length', lambda *args: None)
    monkeypatch.setattr('agent.models_dev.lookup_models_dev_context', lookup)

    assert metadata.get_model_context_length(
        'fixture-openai-model', base_url='https://api.openai.com/v1', provider='openai',
    ) == 131072
    lookup.assert_called_once_with('openai', 'fixture-openai-model')
    client.assert_not_called()
