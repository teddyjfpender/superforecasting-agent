"""Forecast CLI value reads do not initialize or mutate CLI configuration."""
from types import SimpleNamespace

import pytest


@pytest.fixture
def profile(tmp_path, monkeypatch):
    from superforecasting_agent import constants
    from superforecasting_agent.runtime import config

    home = tmp_path / 'reader-profile'
    home.mkdir()
    monkeypatch.setattr(constants, 'get_agent_home', lambda: home)
    def forbidden(*args, **kwargs):
        raise AssertionError('CLI configuration loader was invoked')
    monkeypatch.setattr(config, 'load_config', forbidden)
    monkeypatch.setattr(config, 'load_config_readonly', forbidden)
    path = home / 'config.yaml'
    path.write_text('model:\n  default: fixture-model\nforecasting:\n  reforecast:\n    max_batch: 3\n', encoding='utf-8')
    original = path.read_bytes()
    yield home
    assert path.read_bytes() == original
    assert sorted(p.name for p in home.iterdir()) == ['config.yaml']


def test_resolution_draft_reads_active_model_without_cli_initialization(profile, monkeypatch):
    from forecasting.cli import core
    from forecasting import quorum

    calls = []
    def runner(model, system, user):
        calls.append(model)
        return 'Resolves YES if the official source confirms the event before the deadline; otherwise NO.'
    monkeypatch.setattr(quorum, 'make_aiagent_runner', lambda **kwargs: runner)
    result = core._draft_resolution_criteria(SimpleNamespace(title='Fixture question', close_time='2030-01-01'))
    assert result.startswith('Resolves YES')
    assert calls == ['fixture-model']


def test_rerun_reads_profile_batch_limit_before_starting_work(profile, monkeypatch):
    from forecasting.cli import refresh_cycle
    from forecasting.jobs.types import reforecast

    monkeypatch.setattr(refresh_cycle, '_ledger', lambda args: object())
    captured = []
    def validate(ledger, ids, *, max_batch):
        captured.append(max_batch)
        return [], ['fixture validation stop']
    monkeypatch.setattr(reforecast, 'validate_reforecast_ids', validate)
    with pytest.raises(SystemExit, match='fixture validation stop'):
        refresh_cycle._cmd_rerun(SimpleNamespace(ids=['q1']))
    assert captured == [3]
