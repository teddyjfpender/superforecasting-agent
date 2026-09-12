"""Global browser changes drain and exclude task lifecycle operations."""

import threading

import pytest

from superforecasting_agent.hosting.browser_connection import change_browser_endpoint
from superforecasting_agent.hosting.browser_sessions import (
    browser_endpoint_transition,
    browser_session_lifecycle,
)


def test_transition_drains_old_operations_and_blocks_new_ones():
    active, release_active = threading.Event(), threading.Event()
    cleaning, release_cleanup = threading.Event(), threading.Event()
    newcomer = threading.Event()
    environment = {"BROWSER_CDP_URL": "old"}
    failures = []
    def guarded(fn):
        def run():
            try:
                fn()
            except BaseException as exc:
                failures.append(exc)
        return run
    def operation():
        with browser_session_lifecycle("old-task"):
            active.set()
            assert release_active.wait(3)
    def cleanup():
        # The transition can call its own nested global and per-task cleanup.
        with browser_endpoint_transition(), browser_session_lifecycle("old-task"):
            cleaning.set()
            assert release_cleanup.wait(3)
    def change():
        change_browser_endpoint("new", environment=environment, cleanup=cleanup)
    def new_operation():
        with browser_session_lifecycle("new-task"):
            newcomer.set()
            assert environment["BROWSER_CDP_URL"] == "new"
    old = threading.Thread(target=guarded(operation))
    transition = threading.Thread(target=guarded(change))
    new = threading.Thread(target=guarded(new_operation))
    old.start()
    try:
        assert active.wait(3)
        transition.start()
        assert not cleaning.wait(0.2)
        release_active.set()
        assert cleaning.wait(3)
        new.start()
        assert not newcomer.wait(0.2)
        assert environment["BROWSER_CDP_URL"] == "old"
    finally:
        release_active.set()
        release_cleanup.set()
        for worker in (old, transition, new):
            if worker.ident is not None:
                worker.join(3)
    assert not failures
    assert all(not worker.is_alive() for worker in (old, transition, new))
    assert newcomer.is_set()


def test_task_cannot_deadlock_by_upgrading_to_global_transition():
    with browser_session_lifecycle("task"):
        with pytest.raises(RuntimeError, match="during a task operation"):
            with browser_endpoint_transition():
                pytest.fail("upgrade must not be admitted")
    with browser_endpoint_transition(), browser_session_lifecycle("task"):
        pass
