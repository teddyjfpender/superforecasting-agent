"""Panel policy runs with an explicit snapshot and no discovery side effects."""
import builtins

import pytest

from forecasting.panel_selection import select_connected_panel


def test_selection_uses_only_supplied_snapshot(monkeypatch):
    original_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.startswith(('superforecasting_agent.runtime', 'agent', 'tools', 'tui_gateway')):
            raise AssertionError(f'policy attempted discovery: {name}')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded)
    rows = [
        {'id': 'anthropic', 'default_model': 'claude'},
        {'id': 'gemini', 'default_model': 'gemini-native'},
        {'id': 'anthropic', 'default_model': 'duplicate'},
        {'id': 'deepseek', 'default_model': 'deepseek-native'},
    ]
    result = select_connected_panel(rows, panel_size=2, active_model='claude', active_provider='gemini')
    assert result['models'] == ['anthropic:claude', 'gemini:gemini-native']
    assert result['judge'] == 'gemini:gemini-native'
    assert result['providers_used'] == ['anthropic', 'gemini']
    assert rows[0] == {'id': 'anthropic', 'default_model': 'claude'}


@pytest.mark.parametrize('status', [False, None, 'false', 'true', 1])
@pytest.mark.parametrize('provider', ['openrouter', 'gemini'])
def test_negative_or_malformed_auth_cannot_change_panel(status, provider):
    result = select_connected_panel([
        {'id': 'anthropic', 'default_model': 'claude', 'authenticated': True},
        {'id': provider, 'default_model': 'other', 'authenticated': status},
    ], panel_size=3, active_model='claude', samples=2)
    assert result['self_fusion'] is True
    assert result['models'] == ['claude', 'claude']
    assert result['providers_used'] == ['anthropic']


@pytest.mark.parametrize('rows', [None, [], [{'id': 'gemini', 'authenticated': False}]])
def test_absent_credential_evidence_does_not_claim_a_rebuilt_panel(rows):
    result = select_connected_panel(rows, panel_size=3, active_model='claude')
    assert result['rebuilt'] is False
    assert result['models'] is None
    assert result['providers_used'] == []


def test_resolver_does_not_lookup_defaults_for_unauthenticated_rows(monkeypatch):
    from forecasting.quorum import panels

    looked_up = []
    def default(slug):
        looked_up.append(slug)
        return 'native'
    monkeypatch.setattr(panels, '_provider_default_model', default)
    result = panels.resolve_connected_panel('frontier', active_model='native', providers=[
        {'id': 'anthropic', 'authenticated': True},
        {'id': 'openrouter', 'authenticated': False},
    ])
    assert looked_up == ['anthropic']
    assert result['self_fusion'] is True


def test_resolver_preserves_explicit_model_snapshot(monkeypatch):
    from forecasting.quorum import panels

    def unexpected_lookup(slug):
        raise AssertionError(f'live catalog read for frozen provider {slug}')

    monkeypatch.setattr(panels, '_provider_default_model', unexpected_lookup)
    rows = [
        {'id': 'anthropic', 'default_model': 'frozen-claude'},
        {'id': 'gemini', 'default_model': 'frozen-gemini'},
        {'id': 'deepseek', 'default_model': None},
    ]
    result = panels.resolve_connected_panel('frontier', active_model='native', providers=rows)
    assert result['models'] == ['anthropic:frozen-claude', 'gemini:frozen-gemini']
    assert rows[-1]['default_model'] is None


@pytest.mark.parametrize('bad_model', [None, '', '  ', 42, {'id': 'plausible-model'}])
def test_incomplete_catalog_cannot_claim_single_provider_fusion(bad_model):
    result = select_connected_panel([
        {'id': 'anthropic', 'default_model': 'claude'},
        {'id': 'gemini', 'default_model': bad_model},
    ], panel_size=3, active_model='claude', active_provider='anthropic')
    assert result['rebuilt'] is False
    assert result['self_fusion'] is False
    assert result['models'] is None
    assert result['providers_used'] == ['anthropic', 'gemini']


def test_single_provider_does_not_rebuild_with_another_active_provider():
    result = select_connected_panel([
        {'id': 'anthropic', 'default_model': 'claude'},
    ], panel_size=3, active_model='gemini-model', active_provider='gemini')
    assert result['rebuilt'] is False
    assert result['models'] is None


def test_active_single_provider_does_not_require_a_catalog_default():
    result = select_connected_panel([
        {'id': 'custom:desk', 'default_model': None},
    ], panel_size=3, active_model='custom:desk:local-model', active_provider='custom:desk')
    assert result['self_fusion'] is True
    assert result['models'] == ['custom:desk:local-model'] * 3
    assert result['providers_used'] == ['custom:desk']


def test_active_provider_alias_uses_the_shared_identity_policy():
    rows = [{'id': 'gemini', 'default_model': 'gemini-native'}]
    single = select_connected_panel(rows, panel_size=3, active_model='gemini-native', active_provider='google')
    assert single['self_fusion'] is True
    multi = select_connected_panel([
        {'id': 'anthropic', 'default_model': 'claude'}, *rows,
    ], panel_size=3, active_model='gemini-native', active_provider='google')
    assert multi['judge'] == 'gemini:gemini-native'
