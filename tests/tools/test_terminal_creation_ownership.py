"""A retired sandbox creator cannot publish or use replacement session state."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from tools import terminal_tool as terminal


def test_cleanup_invalidates_creator_and_waiters_without_touching_replacement(monkeypatch, tmp_path):
    entered = threading.Event()
    finish_creation = threading.Event()
    waiter_ready = threading.Event()
    original, replacement = Mock(), Mock()

    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()

        def __enter__(self):
            if self.lock.locked():
                waiter_ready.set()
            self.lock.acquire()

        def __exit__(self, *args):
            self.lock.release()

    task = 'creation-owner'
    old_lock = ObservedLock()
    monkeypatch.setattr(terminal, '_active_environments', {})
    monkeypatch.setattr(terminal, '_last_activity', {})
    monkeypatch.setattr(terminal, '_creation_locks', {task: old_lock})
    monkeypatch.setattr(terminal, '_resolve_container_task_id', lambda task_id: task_id)
    monkeypatch.setattr(terminal, '_get_env_config', lambda: {
        'env_type': 'local', 'cwd': str(tmp_path), 'timeout': 5,
    })
    monkeypatch.setattr(terminal, '_start_cleanup_thread', lambda: None)
    monkeypatch.setattr('tools.file_tools.clear_file_ops_cache', Mock())

    def create(**kwargs):
        entered.set()
        assert finish_creation.wait(3)
        return original

    factory = Mock(side_effect=create)
    monkeypatch.setattr(terminal, '_create_environment', factory)

    def call():
        return json.loads(terminal.terminal_tool('echo fixture', task_id=task, force=True))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(call)
        try:
            assert entered.wait(3)
            waiting = pool.submit(call)
            assert waiter_ready.wait(3)
            terminal.cleanup_vm(task)
            replacement_lock = threading.Lock()
            with terminal._env_lock, terminal._creation_locks_lock:
                terminal._active_environments[task] = replacement
                terminal._creation_locks[task] = replacement_lock
        finally:
            finish_creation.set()
        assert first.result(timeout=3)['status'] == 'cancelled'
        assert waiting.result(timeout=3)['status'] == 'cancelled'

    factory.assert_called_once()
    original.cleanup.assert_called_once()
    original.execute.assert_not_called()
    replacement.cleanup.assert_not_called()
    replacement.execute.assert_not_called()
    assert terminal._active_environments[task] is replacement
    assert terminal._creation_locks[task] is replacement_lock
