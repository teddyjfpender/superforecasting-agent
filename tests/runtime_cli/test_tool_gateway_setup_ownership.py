"""Subscription prompts belong to setup; provider eligibility stays noninteractive."""
import pytest

from superforecasting_agent.runtime import nous_subscription, oauth_setup, setup


@pytest.mark.parametrize('choice, expected', [(0, {'web', 'tts'}), (1, {'web'}), (2, set())])
def test_prompt_preserves_selection_and_persistence(choice, expected, monkeypatch, capsys):
    from superforecasting_agent.runtime import config

    settings = {'model': {'provider': 'nous'}}
    monkeypatch.setattr(nous_subscription, 'get_gateway_eligible_tools', lambda cfg: (['web'], ['tts'], ['browser']))
    captured = []
    persisted = []

    def choose(title, choices, default, **kwargs):
        assert default == 2  # Preserve existing direct credentials by default.
        assert len(choices) == 3
        assert 'using Tool Gateway' in kwargs['description']
        return choice

    def apply(cfg, keys):
        assert cfg is settings
        captured.append(set(keys))
        return set(keys) & {'web', 'tts'}

    monkeypatch.setattr(setup, 'prompt_choice', choose)
    monkeypatch.setattr(nous_subscription, 'apply_gateway_defaults', apply)
    monkeypatch.setattr(config, 'save_config', lambda cfg: persisted.append(cfg))
    assert oauth_setup.prompt_enable_tool_gateway(settings) == expected
    assert len(persisted) == bool(expected)
    if choice == 0:
        assert captured == [set(nous_subscription._ALL_GATEWAY_KEYS)]
    elif choice == 1:
        assert captured == [{'web'}]
    else:
        assert captured == []
        assert capsys.readouterr().out == ''


@pytest.mark.parametrize('failure', [KeyboardInterrupt, EOFError, OSError, SystemExit])
def test_interrupted_offer_never_changes_settings(failure, monkeypatch):
    monkeypatch.setattr(nous_subscription, 'get_gateway_eligible_tools', lambda cfg: (['web'], [], []))
    def interrupted(*args, **kwargs):
        raise failure()
    def unexpected(*args, **kwargs):
        pytest.fail('interrupted prompt attempted to change settings')
    monkeypatch.setattr(setup, 'prompt_choice', interrupted)
    monkeypatch.setattr(nous_subscription, 'apply_gateway_defaults', unexpected)
    assert oauth_setup.prompt_enable_tool_gateway({}) == set()


def test_ineligible_subscription_does_not_prompt(monkeypatch):
    monkeypatch.setattr(nous_subscription, 'get_gateway_eligible_tools', lambda cfg: ([], [], []))
    def unexpected(*args, **kwargs):
        pytest.fail('ineligible subscription prompted')
    monkeypatch.setattr(setup, 'prompt_choice', unexpected)
    assert oauth_setup.prompt_enable_tool_gateway({}) == set()


def test_profile_identity_imports_no_management_or_presentation(tmp_path):
    import os
    import subprocess
    import sys

    code = '''
import builtins
original_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.startswith(('superforecasting_agent.runtime', 'gateway', 'tui_gateway')) or name == 'cli':
        raise AssertionError('profile identity imported management: ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
from superforecasting_agent.constants import get_active_profile_name
assert get_active_profile_name() == 'analyst'
'''
    env = dict(os.environ)
    for name in ('FORECAST_HOME', 'HERMES_HOME'):
        env.pop(name, None)
    env['SUPERFORECASTING_AGENT_HOME'] = str(tmp_path / 'profiles' / 'analyst')
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
