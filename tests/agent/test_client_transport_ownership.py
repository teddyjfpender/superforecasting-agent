"""SDK close owns transport resources; agent cleanup never sweeps private sockets."""

import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from openai import OpenAI

from agent.openai_clients import _close_openai_client


def test_close_uses_only_client_owner():
    class Client:
        close = Mock()

        @property
        def _client(self):
            raise AssertionError("private transport traversal")

    client = Client()
    agent = SimpleNamespace(_client_log_context=lambda: "test")
    _close_openai_client(agent, client, reason="test", shared=True)
    client.close.assert_called_once_with()


def test_sdk_close_releases_real_keepalive_connection():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)
    closed = threading.Event()
    failures = []

    def serve():
        try:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(5)
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        raise AssertionError("request ended before headers")
                    data += chunk
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\nOK")
                assert conn.recv(1) == b""
                closed.set()
        except Exception as exc:
            failures.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    http = httpx.Client(trust_env=False, timeout=3)
    client = OpenAI(api_key="local-test", http_client=http)
    agent = SimpleNamespace(_client_log_context=lambda: "test")
    try:
        assert http.get(f"http://127.0.0.1:{listener.getsockname()[1]}").text == "OK"
        assert not closed.is_set()
        _close_openai_client(agent, client, reason="test", shared=True)
        assert closed.wait(3)
        assert http.is_closed
        # Repeated public close cannot act on a subsequently allocated socket.
        with socket.socket() as replacement:
            replacement.bind(("127.0.0.1", 0))
            _close_openai_client(agent, client, reason="test", shared=True)
            assert replacement.getsockname()[1] > 0
    finally:
        client.close()
        listener.close()
        thread.join(6)
    assert not thread.is_alive()
    assert failures == []


def test_sdk_transport_failure_remains_pending_despite_closed_flag(monkeypatch):
    import pytest
    from agent import session_lifecycle
    from superforecasting_agent.hosting.sessions import dispose_session
    from tools import process_registry

    class FailingTransport(httpx.BaseTransport):
        calls = 0

        def close(self):
            self.calls += 1
            raise OSError('injected transport close failure')

    transport = FailingTransport()
    http = httpx.Client(transport=transport, trust_env=False)
    client = OpenAI(api_key='fixture-only', http_client=http)
    agent = SimpleNamespace(
        session_id='failed-sdk-cleanup', client=client,
        _resource_close_lock=threading.RLock(),
        _active_children_lock=threading.Lock(), _active_children=[],
        _client_log_context=lambda: 'fixture',
    )
    agent._close_openai_client = lambda client, **kwargs: _close_openai_client(agent, client, **kwargs)
    agent.close = lambda: session_lifecycle.close(agent)
    session = {'agent': agent}
    monkeypatch.setattr(process_registry.process_registry, 'kill_all', Mock())
    monkeypatch.setattr(session_lifecycle, 'cleanup_vm', Mock())
    monkeypatch.setattr(session_lifecycle, 'cleanup_browser', Mock())

    with pytest.raises(RuntimeError, match='SDK client cleanup failed'):
        dispose_session(session, release_notifications=lambda: None)
    assert http.is_closed
    assert agent.client is None
    assert agent._failed_client_closes == [client]
    assert session['_cleanup_pending']
    assert 'agent' not in session['_disposed_resources']

    # Reproduce the actual SDK limitation: this returns normally without
    # retrying the failed transport, so it cannot prove resource disposal.
    client.close()
    assert transport.calls == 1
    with pytest.raises(RuntimeError, match='SDK client cleanup failed'):
        dispose_session(session, release_notifications=lambda: None)
    assert session['_cleanup_pending']
    assert transport.calls == 1
    process_registry.process_registry.kill_all.assert_called_once()


def test_failed_sdk_close_is_retained_once_and_does_not_touch_replacement():
    from agent.openai_clients import require_client_cleanup_complete
    import pytest

    failed = Mock()
    failed.close.side_effect = OSError('cleanup failed')
    replacement = Mock()
    agent = SimpleNamespace(client=replacement, _client_log_context=lambda: 'fixture')
    _close_openai_client(agent, failed, reason='replacement', shared=True)
    _close_openai_client(agent, failed, reason='retry', shared=True)
    assert agent._failed_client_closes == [failed]
    failed.close.assert_called_once()
    assert agent.client is replacement
    replacement.close.assert_not_called()
    with pytest.raises(RuntimeError, match='SDK client cleanup failed'):
        require_client_cleanup_complete(agent)
