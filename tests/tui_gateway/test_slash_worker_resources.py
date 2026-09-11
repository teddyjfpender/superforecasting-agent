"""Real child pipes are reaped and closed by their worker, including failure."""
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.fixture
def child_processes(monkeypatch):
    from tui_gateway import server
    original = subprocess.Popen
    children = []
    def spawn(*args, **kwargs):
        child = original([sys.executable, '-u', '-c',
            'import json,signal,sys\n'
            'if sys.platform != "win32": signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
            'print(json.dumps({"ready":True}),flush=True)\n'
            'for line in sys.stdin: pass\n'], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(server.subprocess, 'Popen', spawn)
    yield children
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


def test_repeated_concurrent_close_reaps_child_and_all_pipes(child_processes):
    from tui_gateway import server
    worker = server._SlashWorker('fixture', '')
    assert worker.stdout_queue.get(timeout=3) == {'ready': True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: worker.close(), range(2)))
    child = child_processes[0]
    assert child.poll() is not None
    if os.name != 'nt':
        assert child.returncode == -9  # SIGTERM ignored: force-kill must be reaped.
    assert all(stream.closed for stream in (child.stdin, child.stdout, child.stderr))
    assert not any(reader.is_alive() for reader in worker._readers)


def test_reader_start_failure_does_not_orphan_child_or_pipes(child_processes, monkeypatch):
    from tui_gateway import server
    original_start = threading.Thread.start
    calls = []
    def start(thread):
        calls.append(thread)
        if len(calls) == 2:
            raise RuntimeError('injected reader start failure')
        original_start(thread)
    monkeypatch.setattr(threading.Thread, 'start', start)
    with pytest.raises(RuntimeError, match='reader start failure'):
        server._SlashWorker('fixture', '')
    child = child_processes[0]
    assert child.poll() is not None
    assert all(stream.closed for stream in (child.stdin, child.stdout, child.stderr))
    assert not calls[0].is_alive()
