"""Storage lifetime can be exercised without importing any transport server."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from superforecasting_agent.hosting.storage import SessionStore
from superforecasting_agent.hosting.workers import HostStopping


def test_concurrent_initialization_opens_once_and_shutdown_blocks_reopen():
    opens, closes = [], []
    def factory():
        opens.append(1)
        return SimpleNamespace(close=lambda: closes.append(1))
    owner = SessionStore(factory)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: owner.get(), range(40)))
    assert all(value is results[0] for value in results)
    assert len(opens) == 1
    owner.close()
    owner.close()
    assert closes == [1]
    with pytest.raises(HostStopping):
        owner.get()
    assert len(opens) == 1
    owner.start()
    assert owner.get() is not results[0]
    owner.close()


def test_failed_initialization_preserves_diagnostic_and_retries():
    calls = []
    def factory():
        calls.append(1)
        if len(calls) == 1:
            raise OSError('fixture authorization failure')
        return SimpleNamespace(close=lambda: None)
    owner = SessionStore(factory)
    assert owner.get() is None
    assert owner.last_error == 'fixture authorization failure'
    assert owner.get() is not None
    assert owner.last_error is None
    owner.close()


def test_failed_close_retains_ownership_and_prevents_new_lifetime():
    calls = []
    def close():
        calls.append(1)
        if len(calls) == 1:
            raise OSError('fixture close failure')
    connection = SimpleNamespace(close=close)
    owner = SessionStore(lambda: connection)
    assert owner.get() is connection
    with pytest.raises(OSError):
        owner.close()
    assert owner.current is connection
    with pytest.raises(HostStopping):
        owner.get()
    with pytest.raises(RuntimeError, match='still owned'):
        owner.start()
    owner.close()
    assert owner.current is None
