"""Silencing a worker never steals another thread's stream or closes its owner."""

import io
import sys
import threading

from agent.thread_scoped_output import thread_scoped_silence


def test_other_thread_remains_visible_and_borrowed_stream_stays_open(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    entered = threading.Event()
    finish = threading.Event()

    def worker():
        with thread_scoped_silence():
            print("hidden-before")
            entered.set()
            assert finish.wait(2)
            with thread_scoped_silence():
                print("hidden-nested")
            print("hidden-after")

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(2)
    print("visible-main")
    finish.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    sys.stdout.close()
    assert not output.closed
    print("visible-after")
    assert output.getvalue() == "visible-main\nvisible-after\n"
