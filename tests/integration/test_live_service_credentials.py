"""Exercise restoration through the real hermetic fixture, without a network call."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace


def test_live_restore_is_opt_in_and_service_scoped(monkeypatch):
    spec = importlib.util.spec_from_file_location('integration_credential_policy', Path(__file__).with_name('conftest.py'))
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    monkeypatch.setenv('DAYTONA_API_KEY', 'fixture-daytona')
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-unrelated')
    config = SimpleNamespace(stash={}, getoption=lambda _: ['daytona'])
    policy.pytest_configure(config)
    assert config.stash[policy._CREDENTIALS] == {'daytona': {'DAYTONA_API_KEY': 'fixture-daytona'}}
    monkeypatch.delenv('DAYTONA_API_KEY')
    request = SimpleNamespace(config=config, node=SimpleNamespace(path='test_daytona_terminal.py'))
    policy._selected_live_service_credentials.__wrapped__(request, None, monkeypatch)
    assert os.environ['DAYTONA_API_KEY'] == 'fixture-daytona'
    # Neither other service credentials nor unrelated provider secrets are captured.
    assert 'modal' not in config.stash[policy._CREDENTIALS]
