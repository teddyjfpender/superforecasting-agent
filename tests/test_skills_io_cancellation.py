"""Cancel actual pending HTTP bodies without leaving I/O workers behind."""
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from superforecasting_agent.tooling.http_io import HubCancelled, cancellation_scope, get


def test_cancel_interrupted_body_closes_connection_and_preserves_other_scope():
    stop = threading.Event()
    received = threading.Event()
    disconnected = threading.Event()
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(3)
    errors = []
    def serve():
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(3)
                request = b''
                while b'\r\n\r\n' not in request:
                    request += connection.recv(4096)
                connection.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nx')
                received.set()
                assert connection.recv(1) == b''
                disconnected.set()
        except Exception as exc:
            errors.append(exc)
    server = threading.Thread(target=serve)
    server.start()
    def run():
        with cancellation_scope(stop):
            get(f'http://127.0.0.1:{listener.getsockname()[1]}', timeout=3)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run)
            assert received.wait(3)
            stop.set()
            with pytest.raises(HubCancelled):
                future.result(timeout=3)
        assert disconnected.wait(3)
        with cancellation_scope(threading.Event()):
            pass
    finally:
        listener.close()
        server.join(4)
    assert not server.is_alive()
    assert not errors


def test_precancelled_scope_never_starts_io():
    stop = threading.Event()
    stop.set()
    with pytest.raises(HubCancelled):
        with cancellation_scope(stop):
            raise AssertionError('operation admitted after cancellation')
