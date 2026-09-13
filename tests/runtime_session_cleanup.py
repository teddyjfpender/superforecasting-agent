"""Retire isolated test sessions without invoking unrelated memory/plugin hooks.

These fixtures own all producers. Verify their workers have exited, then use the
same resource disposal and registry retirement operations as the runtime host.
"""

from superforecasting_agent.hosting.sessions import dispose_session


def retire_test_session(server, sid):
    session = server._host.sessions.get(sid)
    if session is None:
        return None
    stop = session.get('_notif_stop')
    if stop is not None:
        stop.set()
    workers = server._host.workers
    with workers._condition:
        assert workers._condition.wait_for(lambda: workers._active == 0, timeout=3), (
            'test session still has active runtime workers'
        )
    def release_notifications():
        key = session.get('session_key')
        if key:
            from tools.approval import unregister_gateway_notify
            unregister_gateway_notify(key)
    return server._host.sessions.retire(
        sid,
        lambda value: dispose_session(value, release_notifications=release_notifications),
        drained=True,
    )


def retire_test_sessions(server):
    for session in server._host.sessions.values():
        stop = session.get('_notif_stop')
        if stop is not None:
            stop.set()
    for sid in tuple(server._host.sessions):
        retire_test_session(server, sid)
