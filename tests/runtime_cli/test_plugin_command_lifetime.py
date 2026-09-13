"""Plugin coroutine completion includes cancellation cleanup and caller context."""

import asyncio
import contextvars
import threading

import pytest

from superforecasting_agent.runtime import plugins


@pytest.mark.parametrize('running_loop', [False, True])
def test_deadline_waits_for_async_cleanup(monkeypatch, running_loop):
    monkeypatch.setattr(plugins, '_PLUGIN_COMMAND_AWAIT_TIMEOUT_SECS', 0.01)
    cleaned = threading.Event()

    async def handler():
        try:
            await asyncio.sleep(0.2)
        finally:
            await asyncio.sleep(0.01)
            cleaned.set()

    def invoke():
        with pytest.raises(TimeoutError, match='cancellation finished'):
            plugins.resolve_plugin_command_result(handler())
        assert cleaned.is_set(), 'command returned before coroutine cleanup'
        assert not any(t.name == 'hermes-plugin-command-await' for t in threading.enumerate())

    async def caller():
        invoke()

    if running_loop:
        asyncio.run(caller())
    else:
        invoke()


def test_threaded_handler_inherits_context_without_mutating_caller():
    identity = contextvars.ContextVar('plugin-owner', default='missing')
    identity.set('parent')

    async def handler():
        value = identity.get()
        identity.set('child')
        return value

    async def caller():
        assert plugins.resolve_plugin_command_result(handler()) == 'parent'
        assert identity.get() == 'parent'

    asyncio.run(caller())


def test_handler_timeout_keeps_its_original_diagnostic():
    async def handler():
        raise TimeoutError('source-specific timeout')

    with pytest.raises(TimeoutError, match='source-specific timeout'):
        plugins.resolve_plugin_command_result(handler())


def test_failed_thread_start_closes_unstarted_coroutine(monkeypatch):
    import inspect

    async def handler():
        return 'not started'

    result = handler()
    monkeypatch.setattr(threading.Thread, 'start', lambda self: (_ for _ in ()).throw(RuntimeError('cannot start')))

    async def caller():
        with pytest.raises(RuntimeError, match='cannot start'):
            plugins.resolve_plugin_command_result(result)
        assert inspect.getcoroutinestate(result) == inspect.CORO_CLOSED

    asyncio.run(caller())


def test_cleanup_failure_is_not_replaced_by_deadline_message(monkeypatch):
    monkeypatch.setattr(plugins, '_PLUGIN_COMMAND_AWAIT_TIMEOUT_SECS', 0.01)

    async def handler():
        try:
            await asyncio.sleep(0.2)
        finally:
            raise TimeoutError('transport close failed')

    with pytest.raises(TimeoutError, match='transport close failed'):
        plugins.resolve_plugin_command_result(handler())
