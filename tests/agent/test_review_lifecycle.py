"""Background work must finish before parent resources can be disposed."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.review_lifecycle import ReviewLifecycle, reviews_for
from agent import session_lifecycle
from superforecasting_agent.hosting.workers import HostStopping


def test_close_interrupts_review_but_preserves_parent_resources_until_exit(monkeypatch):
    parent = SimpleNamespace(session_id='parent', _resource_close_lock=threading.RLock())
    owner = reviews_for(parent)
    entered, leave = threading.Event(), threading.Event()
    child = SimpleNamespace(interrupt=Mock(), shutdown_memory_provider=Mock(), close=Mock())
    def work():
        assert owner.register(child)
        entered.set()
        assert leave.wait(5)
        owner.dispose(child)
    thread = owner.workers.start(work, name='owned-review-test')
    cleanup = Mock()
    monkeypatch.setattr(session_lifecycle, '_close_resources', cleanup)
    try:
        assert entered.wait(5)
        with pytest.raises(RuntimeError, match='still running'):
            session_lifecycle.close(parent)
        child.interrupt.assert_called_once()
        child.close.assert_not_called()
        cleanup.assert_not_called()
        assert not getattr(parent, '_resources_closed', False)
        with pytest.raises(HostStopping):
            owner.workers.start(lambda: None, name='late-review')
    finally:
        leave.set()
        thread.join(5)
    assert not thread.is_alive()
    session_lifecycle.close(parent)
    session_lifecycle.close(parent)
    cleanup.assert_called_once()
    child.close.assert_called_once()


def test_shutdown_during_construction_rejects_child_before_run():
    owner = ReviewLifecycle()
    entered, leave = threading.Event(), threading.Event()
    child = SimpleNamespace(interrupt=Mock(), shutdown_memory_provider=Mock(), close=Mock())
    admitted = []
    def construct():
        entered.set()
        assert leave.wait(5)
        admitted.append(owner.register(child))
        owner.dispose(child)
    thread = owner.workers.start(construct, name='construct-review-test')
    try:
        assert entered.wait(5)
        with pytest.raises(RuntimeError, match='still running'):
            owner.stop()
    finally:
        leave.set()
        thread.join(5)
    assert admitted == [False]
    owner.stop()
    child.close.assert_called_once()
    child.interrupt.assert_not_called()


def test_failed_child_cleanup_retains_handle_and_retries_only_incomplete_steps():
    owner = ReviewLifecycle()
    child = SimpleNamespace(interrupt=Mock(), shutdown_memory_provider=Mock(), close=Mock(side_effect=[OSError('close failed'), False, None]))
    assert owner.register(child)
    owner.dispose(child)
    with pytest.raises(RuntimeError, match='cleanup incomplete'):
        owner.stop()
    owner.stop()
    owner.stop()
    assert child.close.call_count == 3
    child.shutdown_memory_provider.assert_called_once()
    child.interrupt.assert_not_called()
