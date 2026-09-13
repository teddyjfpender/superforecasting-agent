"""Shared and compatibility imports must never fork routing context state."""
import asyncio
import subprocess
import sys

import pytest

from superforecasting_agent import session_context


def test_legacy_import_is_same_owner():
    import gateway.session_context as legacy
    assert legacy is session_context
    assert legacy._VAR_MAP is session_context._VAR_MAP
    tokens = legacy.set_session_vars(platform='fixture', chat_id='one')
    try:
        assert session_context.get_session_env('FORECAST_SESSION_CHAT_ID') == 'one'
    finally:
        session_context.clear_session_vars(tokens)
    assert legacy.get_session_env('HERMES_SESSION_CHAT_ID') == ''


@pytest.mark.asyncio
async def test_cancelled_scope_does_not_clear_another_task_or_executor(monkeypatch):
    monkeypatch.setenv('HERMES_SESSION_CHAT_ID', 'stale-environment')
    ready = asyncio.Event()
    release = asyncio.Event()
    async def cancelled():
        tokens = session_context.set_session_vars(chat_id='cancelled')
        try:
            ready.set()
            await release.wait()
        finally:
            session_context.clear_session_vars(tokens)
            assert session_context.get_session_env('HERMES_SESSION_CHAT_ID') == ''
    task = asyncio.create_task(cancelled())
    await ready.wait()
    tokens = session_context.set_session_vars(chat_id='survivor')
    try:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(session_context.get_session_env, 'FORECAST_SESSION_CHAT_ID') == 'survivor'
        assert session_context.get_session_env('SUPERFORECASTING_AGENT_SESSION_CHAT_ID') == 'survivor'
    finally:
        session_context.clear_session_vars(tokens)


def test_context_import_does_not_initialize_a_gateway():
    code = '''
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'gateway' or name.startswith(('gateway.', 'tui_gateway')) or name == 'cli':
        raise AssertionError('session context imported presentation: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from superforecasting_agent.session_context import set_session_vars, get_session_env, clear_session_vars
tokens = set_session_vars(chat_id='isolated')
assert get_session_env('FORECAST_SESSION_CHAT_ID') == 'isolated'
clear_session_vars(tokens)
assert get_session_env('FORECAST_SESSION_CHAT_ID') == ''
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
