"""Fixtures for tests which start and stop complete runtime host lifetimes."""
import threading

import pytest

from superforecasting_agent.hosting.runtime import RuntimeHost


@pytest.fixture
def isolated_runtime_host(monkeypatch):
    from tui_gateway import server
    monkeypatch.setattr(server, '_host', RuntimeHost())
    monkeypatch.setattr(server, '_auth_flow', {})
    monkeypatch.setattr(server, '_cron_ticker_stop', threading.Event())
    monkeypatch.setattr(server, '_cron_ticker_thread', None)
    yield
    assert server.shutdown_runtime(2), 'test left runtime workers active'
