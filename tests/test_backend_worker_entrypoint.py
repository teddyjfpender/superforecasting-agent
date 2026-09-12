"""Backend worker startup owns plugins; domain execution owns job state."""

import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from superforecasting_agent.worker import main


@pytest.mark.parametrize('status, code', [
    ('done', 0), ('cancelled', 0), ('awaiting_approval', 0), ('failed', 1),
])
def test_plugins_are_initialized_before_domain_execution(monkeypatch, status, code):
    from forecasting.jobs import runtime
    from superforecasting_agent.runtime import plugins

    calls = []
    monkeypatch.setattr(plugins, 'discover_plugins', lambda: calls.append('plugins'))
    def run(job_id):
        calls.append(job_id)
        return SimpleNamespace(status=status)
    monkeypatch.setattr(runtime, 'run', run)
    assert main(['run', 'job-test']) == code
    assert calls == ['plugins', 'job-test']


def test_discovery_failure_is_diagnostic_and_does_not_replay_job(monkeypatch, caplog):
    from forecasting.jobs import runtime
    from superforecasting_agent.runtime import plugins

    calls = []
    def discover():
        raise RuntimeError('broken plugin')
    monkeypatch.setattr(plugins, 'discover_plugins', discover)
    monkeypatch.setattr(runtime, 'run', lambda job_id: calls.append(job_id) or SimpleNamespace(status='done'))
    assert main(['run', 'job-test']) == 0
    assert calls == ['job-test']
    assert 'Worker plugin discovery failed' in caplog.text
    assert 'broken plugin' in caplog.text


@pytest.mark.parametrize('module', ['superforecasting_agent.worker', 'forecasting.jobs'])
def test_backend_and_compatibility_entrypoints_validate_usage(module):
    result = subprocess.run([sys.executable, '-m', module], capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert f'usage: python -m {module} run <job_id>' in result.stderr


def test_detached_launcher_uses_backend_entrypoint_and_reaps_child(monkeypatch):
    from forecasting.jobs import detached

    waited = threading.Event()
    calls = []
    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(wait=waited.set)
    monkeypatch.setattr(detached.subprocess, 'Popen', popen)
    detached.spawn_detached_job('job-test')
    assert waited.wait(3)
    assert calls[0][0] == [sys.executable, '-m', 'superforecasting_agent.worker', 'run', 'job-test']
    assert calls[0][1]['close_fds'] is True
