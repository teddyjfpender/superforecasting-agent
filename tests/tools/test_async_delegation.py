"""Tests for async (background) delegation — tools/async_delegation.py.

Covers the dispatch handle, non-blocking behavior, completion-event delivery
onto the shared process_registry.completion_queue, the rich re-injection block
formatting, capacity rejection, and crash handling.
"""

import queue
import threading
import time

import pytest

from tools import async_delegation as ad
from tools.process_registry import process_registry, format_process_notification


@pytest.fixture(autouse=True)
def _clean_state():
    ad._reset_for_tests()
    while not process_registry.completion_queue.empty():
        process_registry.completion_queue.get_nowait()
    yield
    ad._reset_for_tests()
    while not process_registry.completion_queue.empty():
        process_registry.completion_queue.get_nowait()


def _drain_one(timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_registry.completion_queue.empty():
            return process_registry.completion_queue.get_nowait()
        time.sleep(0.02)
    return None


def test_dispatch_returns_immediately_without_blocking():
    gate = threading.Event()

    def runner():
        gate.wait(timeout=5)
        return {"status": "completed", "summary": "done", "api_calls": 1,
                "duration_seconds": 0.1, "model": "m"}

    t0 = time.monotonic()
    res = ad.dispatch_async_delegation(
        goal="g", context=None, toolsets=None, role="leaf", model="m",
        session_key="", runner=runner, max_async_children=3,
    )
    elapsed = time.monotonic() - t0

    assert res["status"] == "dispatched"
    assert res["delegation_id"].startswith("deleg_")
    # Non-blocking invariant: dispatch returned while the runner is still
    # gated (active), so it cannot have waited on the gate. The active_count
    # check is the environment-independent proof; the generous wall-clock
    # bound is a loose sanity backstop, not the primary assertion (a loaded
    # CI runner can be slow but never anywhere near the runner's 5s gate).
    assert ad.active_count() == 1
    assert elapsed < 4.0, f"dispatch blocked {elapsed:.2f}s (gate is 5s)"
    gate.set()


def test_async_executor_workers_are_daemon_threads():
    gate = threading.Event()

    def runner():
        gate.wait(timeout=5)
        return {"status": "completed", "summary": "done"}

    res = ad.dispatch_async_delegation(
        goal="daemon check", context=None, toolsets=None, role="leaf", model="m",
        session_key="", runner=runner, max_async_children=1,
    )
    assert res["status"] == "dispatched"

    deadline = time.monotonic() + 2
    worker = None
    while time.monotonic() < deadline:
        worker = next(
            (t for t in threading.enumerate() if t.name.startswith("async-delegate")),
            None,
        )
        if worker is not None:
            break
        time.sleep(0.02)
    assert worker is not None
    assert worker.daemon is True
    gate.set()
    assert _drain_one() is not None


def test_completion_event_lands_on_shared_queue_with_session_key():
    def runner():
        return {"status": "completed", "summary": "the result",
                "api_calls": 3, "duration_seconds": 2.0, "model": "test-model"}

    res = ad.dispatch_async_delegation(
        goal="compute X", context="some context", toolsets=["web", "file"],
        role="leaf", model="test-model", session_key="agent:main:cli:dm:local",
        runner=runner, max_async_children=3,
    )
    assert res["status"] == "dispatched"

    evt = _drain_one()
    assert evt is not None
    assert evt["type"] == "async_delegation"
    assert evt["summary"] == "the result"
    assert evt["session_key"] == "agent:main:cli:dm:local"
    assert evt["delegation_id"] == res["delegation_id"]


def test_rich_reinjection_block_is_self_contained():
    def runner():
        return {"status": "completed", "summary": "The answer is 42.",
                "api_calls": 7, "duration_seconds": 3.5, "model": "test-model"}

    ad.dispatch_async_delegation(
        goal="Compute the meaning of life",
        context="User is a philosopher. Respond tersely.",
        toolsets=["web"], role="leaf", model="test-model",
        session_key="", runner=runner, max_async_children=3,
    )
    evt = _drain_one()
    assert evt is not None
    text = format_process_notification(evt)
    assert text is not None
    for needle in [
        "ASYNC DELEGATION COMPLETE",
        "Compute the meaning of life",
        "User is a philosopher",
        "Toolsets: web",
        "The answer is 42.",
        "Status: completed",
        "API calls: 7",
    ]:
        assert needle in text, f"missing {needle!r}"


def test_dispatch_rejected_at_capacity():
    ev = threading.Event()

    def blocker():
        ev.wait(timeout=5)
        return {"status": "completed", "summary": "x"}

    for i in range(2):
        r = ad.dispatch_async_delegation(
            goal=f"task{i}", context=None, toolsets=None, role="leaf",
            model="m", session_key="", runner=blocker, max_async_children=2,
        )
        assert r["status"] == "dispatched"

    r3 = ad.dispatch_async_delegation(
        goal="task3", context=None, toolsets=None, role="leaf", model="m",
        session_key="", runner=blocker, max_async_children=2,
    )
    assert r3["status"] == "rejected"
    assert "capacity reached" in r3["error"]
    ev.set()


def test_crashed_runner_produces_error_completion():
    def boom():
        raise RuntimeError("subagent exploded")

    r = ad.dispatch_async_delegation(
        goal="risky", context=None, toolsets=None, role="leaf", model="m",
        session_key="", runner=boom, max_async_children=3,
    )
    assert r["status"] == "dispatched"
    evt = _drain_one()
    assert evt is not None
    assert evt["status"] == "error"
    text = format_process_notification(evt)
    assert text is not None
    assert "did not complete successfully" in text
    assert "subagent exploded" in text


def test_interrupt_all_signals_running_children():
    ev = threading.Event()
    interrupted = {"count": 0}

    def blocker():
        ev.wait(timeout=5)
        return {"status": "interrupted", "summary": None,
                "error": "cancelled"}

    def interrupt_fn():
        interrupted["count"] += 1
        ev.set()

    ad.dispatch_async_delegation(
        goal="long task", context=None, toolsets=None, role="leaf",
        model="m", session_key="", runner=blocker,
        interrupt_fn=interrupt_fn, max_async_children=3,
    )
    n = ad.interrupt_all(reason="test")
    assert n == 1
    assert interrupted["count"] == 1
    # child still emits a completion event after interrupt
    evt = _drain_one()
    assert evt is not None
    assert evt["status"] == "interrupted"


def test_completed_records_pruned_to_cap():
    # Run more than the retention cap quickly; ensure list doesn't grow forever.
    for i in range(ad._MAX_RETAINED_COMPLETED + 10):
        ad.dispatch_async_delegation(
            goal=f"t{i}", context=None, toolsets=None, role="leaf", model="m",
            session_key="", runner=lambda: {"status": "completed", "summary": "ok"},
            max_async_children=ad._MAX_RETAINED_COMPLETED + 20,
        )
    # let workers finish
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and ad.active_count() > 0:
        time.sleep(0.05)
    assert len(ad.list_async_delegations()) <= ad._MAX_RETAINED_COMPLETED


# ---------------------------------------------------------------------------
# Integration: delegate_task(background=True) routing
# ---------------------------------------------------------------------------


# ── Fork-adapted integration tests ─────────────────────────────────────────


@pytest.mark.parametrize("reject_second", [False, True])
def test_public_background_batch_delivers_independent_and_grouped_results(monkeypatch, reject_second):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock
    import tools.delegate_tool as dt

    parent = SimpleNamespace(_delegate_depth=0, _active_children=[])
    gates = [threading.Event() for _ in range(3)]
    finished = [threading.Event() for _ in range(3)]
    monkeypatch.setattr(dt, "is_spawn_paused", lambda **_: False)
    monkeypatch.setattr(dt, "_delegation_session_key", lambda _: "s")
    monkeypatch.setattr(dt, "_load_config", lambda: {})
    monkeypatch.setattr(dt, "_get_max_async_children", lambda: 3)
    monkeypatch.setattr(dt, "_get_max_concurrent_children", lambda: 3)
    monkeypatch.setattr(dt, "_get_max_spawn_depth", lambda: 2)
    monkeypatch.setattr(dt, "_resolve_delegation_credentials", lambda *_: dict.fromkeys(
        ["model", "provider", "base_url", "api_key", "api_mode"]
    ))
    monkeypatch.setattr(dt, "_apply_summary_budget", lambda *_: None)
    def build(**kwargs):
        child = Mock()
        parent._active_children.append(child)
        return child
    def run(index, goal, child, parent):
        try:
            assert gates[index].wait(5)
            return {"status": "completed", "summary": goal}
        finally:
            child.close()
            finished[index].set()
    monkeypatch.setattr(dt, "_build_child_agent", build)
    monkeypatch.setattr(dt, "_run_single_child", run)
    if reject_second:
        executor = ad._get_executor(3)
        submit = executor.submit
        submitted = []
        def limited(operation):
            submitted.append(True)
            if len(submitted) == 2:
                finished[1].set()
                raise RuntimeError("controlled second-member scheduling failure")
            return submit(operation)
        monkeypatch.setattr(executor, "submit", limited)
    try:
        result = json.loads(dt.delegate_task(tasks=[
            {"goal": "independent"},
            {"goal": "first", "delivery_group": "group"},
            {"goal": "second", "delivery_group": "group"},
        ], background=True, parent_agent=parent))
        assert result["status"] == ("partial" if reject_second else "dispatched")
        assert len(result["delegations"]) == 3 and ad.active_count() == (2 if reject_second else 3)
        if reject_second:
            early_failure = _drain_one()
            assert early_failure["delivery_kind"] == "member_failure"
            assert early_failure["status"] == "rejected"
        gates[0].set()
        assert _drain_one()["summary"] == "independent"
        gates[1].set()
        assert finished[1].wait(3)
        deadline = time.monotonic() + 3
        while ad.active_count() != 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ad.active_count() == 1
        assert process_registry.completion_queue.empty()
        gates[2].set()
        grouped = _drain_one()
        assert grouped["delivery_kind"] == "group_complete"
        assert [member["goal"] for member in json.loads(grouped["summary"])] == ["first", "second"]
        assert process_registry.completion_queue.empty()
    finally:
        for gate in gates:
            gate.set()
        for done in finished:
            done.wait(3)



def test_gateway_formatter_renders_async_block():
    """The gateway notification formatter renders an async_delegation event."""
    from gateway.run import _format_gateway_process_notification

    evt = {
        "type": "async_delegation",
        "delegation_id": "deleg_x",
        "goal": "Investigate Y",
        "status": "completed",
        "summary": "all done",
        "dispatched_at": 1000.0,
        "completed_at": 1010.0,
    }
    text = _format_gateway_process_notification(evt)
    assert text is not None
    assert "ASYNC DELEGATION COMPLETE" in text
    assert "Investigate Y" in text
    assert "all done" in text


def test_reserved_batch_capacity_is_atomic_and_release_is_idempotent():
    reservation = ad.CapacityReservation(2, 3)
    try:
        with pytest.raises(ValueError, match="capacity reached"):
            ad.CapacityReservation(2, 3)
        spare = ad.CapacityReservation(1, 3)
        try:
            with pytest.raises(ValueError, match="capacity reached"):
                ad.CapacityReservation(1, 3)
        finally:
            spare.release()
            spare.release()
    finally:
        reservation.release()
    assert not ad._reservations


def test_reservation_converts_to_running_without_releasing_capacity():
    reserved = ad.CapacityReservation(2, 2)
    gate = threading.Event()
    try:
        result = ad.dispatch_async_delegation(
            goal="first", context=None, toolsets=None, role="leaf", model=None,
            session_key="session", runner=lambda: gate.wait(5) and {"status": "completed"},
            max_async_children=2, reservation=reserved,
        )
        assert result["status"] == "dispatched"
        assert reserved.remaining == 1
        with pytest.raises(ValueError, match="capacity reached"):
            ad.CapacityReservation(1, 2)
    finally:
        reserved.release()
        gate.set()
        _drain_one()


@pytest.mark.parametrize("failure", ["capacity", "executor"])
def test_public_admission_never_orphans_unstarted_children(monkeypatch, failure):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from tools import delegate_tool as delegate

    parent = SimpleNamespace(_delegate_depth=0, _active_children=[])
    built = []
    child = Mock()

    def build(**kwargs):
        built.append(child)
        parent._active_children.append(child)
        return child

    monkeypatch.setattr(delegate, "is_spawn_paused", lambda **_: False)
    monkeypatch.setattr(delegate, "_delegation_session_key", lambda _: "session")
    monkeypatch.setattr(delegate, "_load_config", lambda: {})
    monkeypatch.setattr(delegate, "_get_max_async_children", lambda: 1)
    monkeypatch.setattr(delegate, "_get_max_spawn_depth", lambda: 2)
    monkeypatch.setattr(delegate, "_get_max_concurrent_children", lambda: 3)
    monkeypatch.setattr(delegate, "_resolve_delegation_credentials", lambda *_: dict.fromkeys(
        ["model", "provider", "base_url", "api_key", "api_mode"]
    ))
    monkeypatch.setattr(delegate, "_build_child_agent", build)
    held = ad.CapacityReservation(1, 1) if failure == "capacity" else None
    if failure == "executor":
        def unavailable(*_):
            raise RuntimeError("executor unavailable")
        monkeypatch.setattr(ad, "_get_executor", unavailable)
    try:
        result = delegate.delegate_task(goal="bounded research", parent_agent=parent, background=True)
        assert "error" in result
        assert not parent._active_children
        if failure == "capacity":
            assert not built
        else:
            assert built == [child]
            child.close.assert_called_once()
            assert ad.active_count() == 0
            assert not ad._reservations
    finally:
        if held is not None:
            held.release()


def test_worker_observes_durable_admission_and_dropped_notice_keeps_result(tmp_path, monkeypatch):
    from superforecasting_agent import constants
    from superforecasting_agent.storage.background_research import BackgroundResearchJournal

    monkeypatch.setattr(constants, "get_agent_home", lambda: tmp_path)
    monkeypatch.setattr(ad, "_push_completion_event", lambda *_: None)
    seen = []
    done = threading.Event()
    def runner():
        seen.extend(BackgroundResearchJournal(tmp_path).tasks("session"))
        done.set()
        return {"status": "completed", "summary": "retained finding"}
    result = ad.dispatch_async_delegation(
        goal="inspect", context=None, toolsets=None, role="leaf", model=None,
        session_key="session", runner=runner,
    )
    assert result["status"] == "dispatched"
    assert done.wait(3)
    deadline = time.monotonic() + 3
    journal = BackgroundResearchJournal(tmp_path)
    while not journal.pending("session") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen[0]["status"] == "running"
    pending = journal.pending("session")
    assert pending[0]["tasks"][0]["result"]["summary"] == "retained finding"
    assert process_registry.completion_queue.empty()


def test_failed_completion_persistence_retries_without_rerunning_research(tmp_path, monkeypatch):
    from superforecasting_agent import constants
    from superforecasting_agent.storage.background_research import BackgroundResearchJournal

    monkeypatch.setattr(constants, "get_agent_home", lambda: tmp_path)
    original = BackgroundResearchJournal.finish
    unavailable = threading.Event()
    unavailable.set()
    attempts = []
    def finish(self, *args, **kwargs):
        if unavailable.is_set():
            raise OSError("journal temporarily unavailable")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(BackgroundResearchJournal, "finish", finish)
    def runner():
        attempts.append("executed")
        return {"status": "completed", "summary": "once"}
    handle = ad.dispatch_async_delegation(
        goal="inspect", context=None, toolsets=None, role="leaf", model=None,
        session_key="session", runner=runner,
    )
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with ad._records_lock:
            pending = ad._records[handle["delegation_id"]]["status"] == "completion_pending"
        if pending:
            break
        time.sleep(0.01)
    assert pending and process_registry.completion_queue.empty()
    unavailable.clear()
    ad.retry_pending_completions()
    ad.retry_pending_completions()
    assert attempts == ["executed"]
    assert len(BackgroundResearchJournal(tmp_path).pending("session")) == 1
    assert _drain_one()["summary"] == "once"
    assert process_registry.completion_queue.empty()


def test_failed_durable_start_retains_cleanup_until_retry(monkeypatch):
    from superforecasting_agent.storage.background_research import BackgroundResearchJournal

    def fail_start(*_):
        raise OSError("start admission unavailable")
    monkeypatch.setattr(BackgroundResearchJournal, "start", fail_start)
    unavailable = threading.Event()
    unavailable.set()
    closed = []
    def cleanup():
        if unavailable.is_set():
            raise OSError("cleanup transport unavailable")
        closed.append(True)
    result = ad.dispatch_async_delegation(
        goal="inspect", context=None, toolsets=None, role="leaf", model=None,
        session_key="session", runner=lambda: pytest.fail("unadmitted research ran"),
        abandon_fn=cleanup,
    )
    assert _drain_one()["status"] == "error"
    with ad._records_lock:
        assert ad._records[result["delegation_id"]]["status"] == "cleanup_pending"
    assert ad.active_count() == 1
    unavailable.clear()
    ad.retry_pending_completions()
    ad.retry_pending_completions()
    assert ad.active_count() == 0
    assert closed == [True]
    assert ad.list_async_delegations(session_key="session")[0]["status"] == "error"


def test_detached_workers_keep_profile_and_routing_but_not_parent_cancellation(tmp_path):
    import contextvars
    from superforecasting_agent.constants import (
        get_agent_home, set_agent_home_override, reset_agent_home_override,
    )
    from superforecasting_agent.tooling.interrupts import (
        cancellation_scope, is_interrupted, set_interrupt,
    )
    from tools.approval import get_current_session_key

    tenant = contextvars.ContextVar("background-test-tenant", default="missing")
    release = threading.Event()
    parent_cancel = threading.Event()
    observed = []
    finished = [threading.Event(), threading.Event()]
    def runner(index, expected):
        try:
            assert release.wait(3)
            observed.append((get_agent_home(), get_current_session_key(), tenant.get(), is_interrupted()))
            set_interrupt(True)
            assert is_interrupted(), "child thread cancellation was masked"
            set_interrupt(False)
            return {"status": "completed", "summary": expected}
        finally:
            set_interrupt(False)
            finished[index].set()
    try:
        for index, name in enumerate(("first", "second")):
            token = set_agent_home_override(tmp_path / name)
            tenant_token = tenant.set(name)
            try:
                with cancellation_scope(parent_cancel):
                    result = ad.dispatch_async_delegation(
                        goal=name, context=None, toolsets=None, role="leaf", model=None,
                        session_key=name, runner=lambda i=index, n=name: runner(i, n),
                    )
                    assert result["status"] == "dispatched"
            finally:
                tenant.reset(tenant_token)
                reset_agent_home_override(token)
        parent_cancel.set()
        release.set()
        assert all(done.wait(3) for done in finished)
        assert sorted(observed) == [
            (tmp_path / "first", "first", "first", False),
            (tmp_path / "second", "second", "second", False),
        ]
        assert _drain_one() is not None
        assert _drain_one() is not None
    finally:
        release.set()
        for done in finished:
            done.wait(3)


def test_status_recovers_completed_results_and_marks_unowned_live_work_unconfirmed(tmp_path, monkeypatch):
    from superforecasting_agent import constants
    from superforecasting_agent.storage.background_research import BackgroundResearchJournal

    monkeypatch.setattr(constants, "get_agent_home", lambda: tmp_path)
    journal = BackgroundResearchJournal(tmp_path)
    first, second = journal.admit([{"goal": "done"}, {"goal": "elsewhere"}], session="s", owner="other-worker")
    journal.start(first, "other-worker")
    journal.finish(first, "other-worker", "completed", {"summary": "saved finding"})
    journal.start(second, "other-worker")
    rows = {row["delegation_id"]: row for row in ad.list_async_delegations(session_key="s")}
    assert rows[first]["status"] == "completed"
    assert rows[first]["result"]["summary"] == "saved finding"
    assert rows[second]["status"] == "unconfirmed"
    assert rows[second]["durable_status"] == "running"
    assert ad.list_async_delegations(session_key="other-session") == []


@pytest.mark.parametrize('approval_owner,inherited_owner,expected', [
    ('gateway-root', None, 'gateway-root'),
    ('', None, 'cli-session'),
    ('', 'root-session', 'root-session'),
])
def test_background_dispatch_preserves_parent_session_without_approval_context(monkeypatch, approval_owner, inherited_owner, expected):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock
    from tools import approval, delegate_tool

    parent = SimpleNamespace(session_id='cli-session', _active_children=[])
    if inherited_owner is not None:
        parent._delegation_owner_key = inherited_owner
    child = SimpleNamespace(close=Mock())
    parent._active_children.append(child)
    monkeypatch.setattr(approval, 'get_current_session_key', lambda **kwargs: approval_owner)
    monkeypatch.setattr(delegate_tool, '_run_single_child', lambda *args: {'status': 'completed', 'summary': 'Evidence'})
    monkeypatch.setattr(delegate_tool, '_apply_summary_budget', lambda *args: None)
    reservation = ad.CapacityReservation(1, 2)
    result = json.loads(delegate_tool._dispatch_background_children(
        [(0, {'goal': 'Check evidence'}, child)], parent, [], None, {'model': 'fixture'}, reservation))
    assert result['status'] == 'dispatched'
    event = _drain_one()
    assert event['session_key'] == expected
    assert ad.pending_notifications(expected)[0]['session_key'] == expected
    assert parent._active_children == []
