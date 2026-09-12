"""Host notification admission can run without a transport or agent."""

import queue
import threading
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.notifications import poll_notifications


@pytest.mark.parametrize("fails", [False, True])
def test_host_dispatch_reserves_session_and_reports_failure(fails, caplog):
    stop = threading.Event()
    session = {"history_lock": threading.Lock(), "session_key": "owner"}
    pending = queue.Queue()
    pending.put({"session_key": "owner"})
    delivered = []

    def dispatch(text):
        assert session["running"] is True
        delivered.append(text)
        stop.set()
        if fails:
            raise RuntimeError("injected dispatch failure")

    poll_notifications(stop, session, pending, consumed=lambda _: False,
                       format_event=lambda _: "completed", host_stopping=lambda: False,
                       dispatch=dispatch)
    assert delivered == ["completed"]
    assert pending.empty()  # Dispatch may have started: no blind replay.
    assert session["running"] is not fails
    if fails:
        assert "injected dispatch failure" in caplog.text


def test_broken_queue_is_not_silently_spun_forever():
    stop = threading.Event()
    pending = Mock()
    pending.get.side_effect = RuntimeError("queue unavailable")
    with pytest.raises(RuntimeError, match="queue unavailable"):
        poll_notifications(stop, {}, pending, consumed=lambda _: False,
                           format_event=lambda _: "unused", host_stopping=lambda: False,
                           dispatch=Mock())
    pending.get.assert_called_once()
