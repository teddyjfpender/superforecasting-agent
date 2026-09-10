"""Regression tests for agent-home override propagation onto the MCP loop.

Tasks scheduled via run_coroutine_threadsafe are created inside the MCP
event-loop thread, so they copy THAT thread's context — not the scheduling
thread's. A per-request profile scope (e.g. an MCP "Test server" probe
under ?profile=) would silently vanish for anything resolving
get_agent_home() inside the coroutine, most visibly OAuth token-store
paths. _run_on_mcp_loop now wraps scheduled coroutines with the caller's
override (mcp_tool._wrap_with_home_override).

Fork note: our agent home env has three alias names
(SUPERFORECASTING_AGENT_HOME / FORECAST_HOME / HERMES_HOME, resolved in
that order by superforecasting_agent.constants.get_agent_home). The override itself is a
contextvar, so it is alias-agnostic; these tests pin the process home via
the highest-priority alias and clear the others so ambient env can't
shadow it.
"""
import os

import pytest

_HOME_ALIASES = ("SUPERFORECASTING_AGENT_HOME", "FORECAST_HOME", "HERMES_HOME")


def _pin_process_home(monkeypatch, path):
    for name in _HOME_ALIASES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(_HOME_ALIASES[0], str(path))


@pytest.fixture
def mcp_loop():
    import tools.mcp_tool as mcp_tool

    mcp_tool._ensure_mcp_loop()
    yield mcp_tool
    mcp_tool._stop_mcp_loop()


def test_override_propagates_to_mcp_loop(tmp_path, monkeypatch, mcp_loop):
    from superforecasting_agent.constants import (
        get_agent_home,
        reset_agent_home_override,
        set_agent_home_override,
    )

    process_home = tmp_path / "proc-home"
    profile_home = tmp_path / "profile-home"
    process_home.mkdir()
    profile_home.mkdir()
    _pin_process_home(monkeypatch, process_home)

    async def read_home():
        return str(get_agent_home())

    # Unscoped: the loop task sees the process home.
    assert mcp_loop._run_on_mcp_loop(read_home(), timeout=10) == str(process_home)

    # Scoped: the caller's override must reach the loop task.
    token = set_agent_home_override(str(profile_home))
    try:
        assert mcp_loop._run_on_mcp_loop(read_home(), timeout=10) == str(profile_home)
        # Factory form must be wrapped too.
        assert mcp_loop._run_on_mcp_loop(lambda: read_home(), timeout=10) == str(
            profile_home
        )
    finally:
        reset_agent_home_override(token)

    # The loop thread's default context is untouched afterwards.
    assert mcp_loop._run_on_mcp_loop(read_home(), timeout=10) == str(process_home)


def test_oauth_token_paths_follow_override(tmp_path, monkeypatch, mcp_loop):
    """The actual symptom path: HermesTokenStorage resolving inside the
    probe's MCP-loop coroutine must land in the selected profile's
    mcp-tokens dir, not the process home's."""
    from superforecasting_agent.constants import (
        reset_agent_home_override,
        set_agent_home_override,
    )

    process_home = tmp_path / "proc-home"
    profile_home = tmp_path / "profile-home"
    process_home.mkdir()
    profile_home.mkdir()
    _pin_process_home(monkeypatch, process_home)

    async def token_path():
        from tools.mcp_oauth import HermesTokenStorage

        return str(HermesTokenStorage("probe-srv")._tokens_path())

    token = set_agent_home_override(str(profile_home))
    try:
        path = mcp_loop._run_on_mcp_loop(token_path(), timeout=10)
    finally:
        reset_agent_home_override(token)
    assert path.startswith(str(profile_home))
    assert os.path.join("mcp-tokens", "probe-srv.json") in path


def test_concurrent_scopes_do_not_interfere(tmp_path, monkeypatch, mcp_loop):
    """Two threads carrying DIFFERENT overrides scheduling onto the same
    loop must each see their own home — the wrapper is task-local."""
    import threading

    from superforecasting_agent.constants import (
        get_agent_home,
        reset_agent_home_override,
        set_agent_home_override,
    )

    process_home = tmp_path / "proc-home"
    home_a = tmp_path / "profile-a"
    home_b = tmp_path / "profile-b"
    for h in (process_home, home_a, home_b):
        h.mkdir()
    _pin_process_home(monkeypatch, process_home)

    async def read_home():
        return str(get_agent_home())

    results: dict = {}

    def scoped_call(key, home):
        token = set_agent_home_override(str(home))
        try:
            results[key] = mcp_loop._run_on_mcp_loop(read_home(), timeout=10)
        finally:
            reset_agent_home_override(token)

    threads = [
        threading.Thread(target=scoped_call, args=("a", home_a)),
        threading.Thread(target=scoped_call, args=("b", home_b)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert results == {"a": str(home_a), "b": str(home_b)}


def test_wrap_is_noop_without_override(mcp_loop):
    """No active override → the coroutine passes through unwrapped."""

    async def trivial():
        return 42

    coro = trivial()
    wrapped = mcp_loop._wrap_with_home_override(coro)
    assert wrapped is coro
    coro.close()
