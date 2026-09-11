"""Embedded HTTP hosts release their own transport bindings in any order."""

from unittest.mock import Mock

import pytest

from tui_gateway import http_server, server


@pytest.mark.parametrize('alongside', [False, True])
@pytest.mark.parametrize('older_first', [False, True])
def test_hosts_close_in_any_order_without_restoring_closed_sinks(monkeypatch, alongside, older_first):
    original = Mock()
    original.write.return_value = True
    monkeypatch.setattr(server, '_stdio_transport', original)
    monkeypatch.setattr(http_server, '_event_log_enabled', lambda: False)
    older = http_server.make_server(port=0, alongside_stdio=alongside)
    newer = http_server.make_server(port=0, alongside_stdio=alongside)
    first, survivor = (older, newer) if older_first else (newer, older)
    try:
        first.server_close()
        first.restore_transport()  # Legacy callers still explicitly restore.
        inbox = survivor.hub.subscribe()
        server._emit('ownership.probe', '', {'value': 1})
        frame = inbox.get(timeout=1)
        assert frame['params']['type'] == 'ownership.probe'
        survivor.server_close()
        assert server._stdio_transport is original
        first.server_close()
        assert server._stdio_transport is original
        original.close.assert_not_called()
    finally:
        older.server_close()
        newer.server_close()


def test_stale_close_does_not_overwrite_external_owner(monkeypatch):
    monkeypatch.setattr(http_server, '_event_log_enabled', lambda: False)
    original = Mock()
    monkeypatch.setattr(server, '_stdio_transport', original)
    host = http_server.make_server(port=0)
    replacement = Mock()
    server._stdio_transport = replacement
    host.server_close()
    assert server._stdio_transport is replacement
    # A fresh registration captures the new baseline, not the obsolete original.
    next_host = http_server.make_server(port=0)
    next_host.server_close()
    assert server._stdio_transport is replacement
    replacement.close.assert_not_called()


def test_bind_failure_never_changes_the_live_sink(monkeypatch):
    monkeypatch.setattr(http_server, '_event_log_enabled', lambda: False)
    host = http_server.make_server(port=0)
    try:
        installed = server._stdio_transport
        with pytest.raises(OSError):
            http_server.make_server(port=host.server_address[1])
        assert server._stdio_transport is installed
        inbox = host.hub.subscribe()
        server._emit('after.bind.failure', '', {})
        assert inbox.get(timeout=1)['params']['type'] == 'after.bind.failure'
    finally:
        host.server_close()


def test_concurrent_transport_registrations_keep_every_live_sink():
    from concurrent.futures import ThreadPoolExecutor
    from tui_gateway.transport import TransportBindings

    base = Mock()
    base.write.return_value = True
    slot = [base]
    owner = TransportBindings(lambda: slot[0], lambda sink: slot.__setitem__(0, sink))
    sinks = [Mock() for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda sink: owner.attach(sink, alongside=True), sinks))
        frame = {'event': 'all hosts'}
        assert slot[0].write(frame)
        for sink in sinks:
            sink.write.assert_called_once_with(frame)
        list(pool.map(owner.detach, tokens))
    assert slot[0] is base
    base.close.assert_not_called()
