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
