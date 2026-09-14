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


def test_idle_poller_recovers_durable_events_with_identity():
    stop = threading.Event()
    session = {"history_lock": threading.Lock(), "session_key": "owner"}
    pending = queue.Queue()
    event = {"session_key": "owner", "journal_event_id": "durable-event"}
    seen = []
    def dispatch(text, original):
        seen.append((text, original))
        stop.set()
    poll_notifications(stop, session, pending, consumed=lambda _: False,
                       format_event=lambda _: "recovered result", host_stopping=lambda: False,
                       dispatch=lambda _: pytest.fail("event identity was discarded"),
                       dispatch_event=dispatch, recover=lambda: [event])
    assert seen == [("recovered result", event)]


def test_profile_routing_distinguishes_identical_session_names(tmp_path):
    from superforecasting_agent.hosting.notifications import notification_profile_key, route_notification

    first = notification_profile_key(tmp_path / 'first')
    second = notification_profile_key(tmp_path / 'second')
    event = {'session_key': 'desk', 'profile_key': first}
    assert route_notification(event, 'desk', profile_key=first) == 'consume'
    assert route_notification(event, 'desk', profile_key=second) == 'requeue'
    assert route_notification(event, 'other', profile_key=first) == 'requeue'
    assert route_notification({'session_key': 'desk'}, 'desk', profile_key=second) == 'consume'
    assert str(tmp_path) not in first


def test_poller_preserves_another_profiles_result(monkeypatch):
    from superforecasting_agent.hosting import notifications

    monkeypatch.setattr(notifications, 'notification_profile_key', lambda: 'local')
    pending = queue.Queue()
    foreign = {'session_key': 'desk', 'profile_key': 'foreign'}
    local = {'session_key': 'desk', 'profile_key': 'local'}
    pending.put(foreign)
    pending.put(local)
    stop = threading.Event()
    seen = []
    def dispatch(text, event):
        seen.append(event)
        stop.set()
    poll_notifications(stop, {'session_key': 'desk', 'history_lock': threading.Lock()}, pending,
                       consumed=lambda _: False, format_event=lambda _: 'research',
                       host_stopping=lambda: False, dispatch=lambda _: None, dispatch_event=dispatch)
    assert seen == [local]
    assert pending.get_nowait() == foreign


def test_foreign_queue_cannot_starve_durable_recovery(monkeypatch):
    from superforecasting_agent.hosting import notifications

    monkeypatch.setattr(notifications, 'notification_profile_key', lambda: 'local')
    stop = threading.Event()
    pending = queue.Queue()
    foreign = {'session_key': 'desk', 'profile_key': 'foreign'}
    local = {'session_key': 'desk', 'profile_key': 'local', 'journal_event_id': 'saved'}
    pending.put(foreign)
    seen = []
    def dispatch(text, event):
        seen.append(event)
        stop.set()
    poll_notifications(stop, {'session_key': 'desk', 'history_lock': threading.Lock()}, pending,
                       consumed=lambda _: False, format_event=lambda _: 'saved research',
                       host_stopping=lambda: False, dispatch=lambda _: None,
                       dispatch_event=dispatch, recover=lambda: [local, {**local, 'journal_event_id': 'later'}])
    assert seen == [local]
    assert pending.qsize() == 1
    assert pending.get_nowait() == foreign


def test_receiving_admission_survives_ack_failure_and_database_reopen(tmp_path):
    from superforecasting_agent.hosting.notifications import admit_background_notification
    from superforecasting_agent.storage import turns
    from superforecasting_agent.storage.session import SessionDB

    path = tmp_path / 'state.db'
    event = {'session_key': 'desk', 'journal_event_id': 'result-1'}
    db = SessionDB(path)
    def fail_after_commit(event_id, session):
        assert turns.latest(db, session)['prompt'] == 'Saved research'
        raise OSError('source temporarily unavailable')
    try:
        turn, created = admit_background_notification(db, event, 'desk', 'Saved research', acknowledge=fail_after_commit)
        assert created
    finally:
        db.close()
    db = SessionDB(path)
    acknowledged = []
    try:
        assert admit_background_notification(db, event, 'desk', 'Saved research',
            acknowledge=lambda *args: acknowledged.append(args)) == (turn, False)
        assert acknowledged == [('result-1', 'desk')]
        assert turns.latest(db, 'desk')['status'] == 'starting'
        with pytest.raises(ValueError, match='conflicts'):
            admit_background_notification(db, event, 'desk', 'Altered payload', acknowledge=Mock())
    finally:
        db.close()


def test_receiving_admission_never_acknowledges_unpersisted_or_foreign_work():
    from superforecasting_agent.hosting.notifications import admit_background_notification

    acknowledged = Mock()
    event = {'session_key': 'desk', 'journal_event_id': 'result-1'}
    db = Mock()
    db._execute_write.side_effect = OSError('disk full')
    with pytest.raises(OSError, match='disk full'):
        admit_background_notification(db, event, 'desk', 'Research', acknowledge=acknowledged)
    db.reset_mock()
    with pytest.raises(ValueError, match='profile'):
        admit_background_notification(db, {**event, 'profile_key': 'foreign'}, 'desk', 'Research', acknowledge=acknowledged)
    with pytest.raises(ValueError, match='session'):
        admit_background_notification(db, event, 'other', 'Research', acknowledge=acknowledged)
    db._execute_write.assert_not_called()
    acknowledged.assert_not_called()
