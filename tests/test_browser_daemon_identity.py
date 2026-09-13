"""Process identity and confirmed exit are prerequisites for retiring a daemon."""
import json
import subprocess
import sys
from unittest.mock import Mock

import psutil
import pytest

from superforecasting_agent.hosting.browser_processes import record_daemon, stop_daemon


def test_real_daemon_is_reaped_before_cleanup_returns(tmp_path):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        (tmp_path / 'desk.pid').write_text(str(child.pid), encoding='utf-8')
        record_daemon(tmp_path, 'desk')
        stop_daemon(tmp_path, 'desk')
        assert not psutil.pid_exists(child.pid)
        stop_daemon(tmp_path, 'desk')
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()


def test_reused_pid_is_not_signaled(tmp_path, monkeypatch):
    (tmp_path / 'desk.pid').write_text('123', encoding='utf-8')
    (tmp_path / 'desk.daemon_identity.json').write_text(json.dumps(
        {'version': 1, 'pid': 123, 'created': 1.0}), encoding='utf-8')
    process = Mock()
    process.create_time.return_value = 2.0
    monkeypatch.setattr(psutil, 'Process', lambda pid: process)
    with pytest.raises(RuntimeError, match='replaced'):
        stop_daemon(tmp_path, 'desk')
    process.terminate.assert_not_called()


def test_unconfirmed_exit_keeps_identity_for_retry(tmp_path, monkeypatch):
    (tmp_path / 'desk.pid').write_text('123', encoding='utf-8')
    process = Mock()
    process.create_time.return_value = 1.0
    process.wait.side_effect = [psutil.TimeoutExpired(3), None]
    monkeypatch.setattr(psutil, 'Process', lambda pid: process)
    record_daemon(tmp_path, 'desk')
    with pytest.raises(RuntimeError, match='pending'):
        stop_daemon(tmp_path, 'desk')
    assert (tmp_path / 'desk.daemon_identity.json').exists()
    stop_daemon(tmp_path, 'desk')


def test_legacy_live_pid_without_identity_is_not_signaled(tmp_path, monkeypatch):
    (tmp_path / 'desk.pid').write_text('123', encoding='utf-8')
    process = Mock()
    monkeypatch.setattr(psutil, 'Process', lambda pid: process)
    with pytest.raises(RuntimeError, match='unverified'):
        stop_daemon(tmp_path, 'desk')
    process.terminate.assert_not_called()
