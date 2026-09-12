"""Prompt callback scopes restore policy without crossing worker ownership."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from superforecasting_agent.tooling import prompt_callbacks as callbacks


def test_nested_callback_scope_restores_parent_after_interruption():
    previous = callbacks.get_approval_callback()
    parent = lambda *args: 'deny'
    child = lambda *args: 'session'
    callbacks.set_approval_callback(parent)
    try:
        with pytest.raises(KeyboardInterrupt):
            with callbacks.temporary_approval_callback(child):
                with callbacks.temporary_approval_callback(None):
                    assert callbacks.get_approval_callback() is None
                assert callbacks.get_approval_callback() is child
                raise KeyboardInterrupt()
        assert callbacks.get_approval_callback() is parent
    finally:
        callbacks.set_approval_callback(previous)


def test_concurrent_callback_scopes_remain_thread_owned():
    barrier = threading.Barrier(2)
    def run(value):
        original = callbacks.get_approval_callback()
        callback = lambda *args: value
        with callbacks.temporary_approval_callback(callback):
            barrier.wait(timeout=3)
            assert callbacks.get_approval_callback() is callback
        assert callbacks.get_approval_callback() is original
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, ['deny', 'session']))
