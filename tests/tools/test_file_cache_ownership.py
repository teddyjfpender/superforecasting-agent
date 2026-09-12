"""File adapters belong to environment objects, not reusable task identifiers."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import file_tools, terminal_tool


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(file_tools, '_file_ops_cache', {})
    monkeypatch.setattr(terminal_tool, '_active_environments', {})
    monkeypatch.setattr(terminal_tool, '_last_activity', {})
    monkeypatch.setattr(terminal_tool, '_creation_locks', {})
    monkeypatch.setattr(terminal_tool, '_resolve_container_task_id', lambda task_id: task_id)


def test_delayed_cleanup_preserves_replacement_adapter(isolated):
    original, replacement = object(), object()
    adapter = SimpleNamespace(env=replacement)
    file_tools._file_ops_cache['task'] = adapter
    file_tools.clear_file_ops_cache('task', expected_env=original)
    assert file_tools._file_ops_cache['task'] is adapter
    file_tools.clear_file_ops_cache('task', expected_env=replacement)
    assert 'task' not in file_tools._file_ops_cache


def test_empty_task_cleanup_does_not_clear_other_sessions(isolated):
    adapter = SimpleNamespace(env=object())
    file_tools._file_ops_cache.update({'': adapter, 'other': adapter})
    file_tools.clear_file_ops_cache('')
    assert file_tools._file_ops_cache == {'other': adapter}


def test_stale_adapter_is_not_reused_for_replacement_environment(isolated):
    old, replacement = SimpleNamespace(cwd='/old'), SimpleNamespace(cwd='/new')
    file_tools._file_ops_cache['task'] = SimpleNamespace(env=old)
    terminal_tool._active_environments['task'] = replacement
    assert file_tools._get_live_tracking_cwd('task') == '/new'
    result = file_tools._get_file_ops('task')
    assert result.env is replacement
    assert file_tools._file_ops_cache['task'] is result


def test_file_creator_cannot_publish_after_cleanup(isolated, monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    old = Mock()
    replacement = SimpleNamespace(cwd=str(tmp_path))
    adapter = SimpleNamespace(env=replacement)
    monkeypatch.setattr(terminal_tool, '_get_env_config', lambda: {
        'env_type': 'local', 'cwd': str(tmp_path), 'timeout': 5,
    })
    monkeypatch.setattr(terminal_tool, '_start_cleanup_thread', lambda: None)

    def create(**kwargs):
        entered.set()
        assert release.wait(3)
        return old

    monkeypatch.setattr(terminal_tool, '_create_environment', create)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(file_tools._get_file_ops, 'task')
        try:
            assert entered.wait(3)
            terminal_tool.cleanup_vm('task')
            terminal_tool._active_environments['task'] = replacement
            terminal_tool._creation_locks['task'] = threading.Lock()
            file_tools._file_ops_cache['task'] = adapter
        finally:
            release.set()
        with pytest.raises(RuntimeError, match='cancelled'):
            future.result(timeout=3)
    old.cleanup.assert_called_once()
    assert terminal_tool._active_environments['task'] is replacement
    assert file_tools._file_ops_cache['task'] is adapter
