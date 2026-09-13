"""Stale sign-in workers cannot replace current credentials or consume results twice."""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.device_auth import DeviceSignIn


def begin(owner, code="current"):
    return owner.begin(
        provider="fixture",
        session_id="session",
        user_code=code,
        url="https://example.test",
    )


def operations():
    return dict(
        interval=0,
        max_wait=5,
        poll=Mock(return_value={"code": "grant"}),
        exchange=Mock(return_value={"token": "secret"}),
        persist=Mock(),
        success_message="signed in",
        timeout_message="timed out",
    )


@pytest.mark.parametrize("action", ["replace", "cancel"])
def test_inflight_exchange_cannot_persist_after_attempt_loses_ownership(action):
    owner = DeviceSignIn()
    attempt = begin(owner, "old")
    entered, release = threading.Event(), threading.Event()
    ops = operations()

    def exchange(result):
        entered.set()
        assert release.wait(3)
        return {"token": "obsolete"}

    ops["exchange"] = exchange
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(owner.run, attempt, **ops)
        try:
            assert entered.wait(2)
            if action == "replace":
                begin(owner, "new")
            else:
                owner.cancel()
        finally:
            release.set()
        worker.result(timeout=3)
    ops["persist"].assert_not_called()
    snapshot = owner.poll()
    assert snapshot["status"] == ("pending" if action == "replace" else "cancelled")
    assert snapshot["user_code"] == ("new" if action == "replace" else "old")


def test_terminal_result_is_consumed_atomically_by_one_poller():
    owner = DeviceSignIn()
    attempt = begin(owner)
    ops = operations()
    owner.run(attempt, **ops)
    barrier = threading.Barrier(2)

    def poll():
        barrier.wait(timeout=2)
        return owner.poll()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(poll) for _ in range(2)]
        results = [future.result(timeout=3) for future in futures]
    assert sum(result.get("status") == "success" for result in results) == 1
    assert results.count({}) == 1
    ops["persist"].assert_called_once_with({"token": "secret"})
    assert all("token" not in result for result in results)


def test_cancel_wakes_long_interval_without_another_network_call():
    owner = DeviceSignIn()
    attempt = begin(owner)
    ops = operations()
    ops.update(interval=60, max_wait=120)
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(owner.run, attempt, **ops)
        owner.cancel()
        worker.result(timeout=2)
    ops["poll"].assert_not_called()
    assert owner.poll()["status"] == "cancelled"


def test_late_failure_does_not_overwrite_new_attempt():
    owner = DeviceSignIn()
    stale = begin(owner, "old")
    begin(owner, "new")
    owner.fail(stale, "obsolete network error")
    assert owner.poll()["status"] == "pending"
    assert owner.poll()["user_code"] == "new"


def test_persistence_failure_is_reported_and_success_is_not_published():
    owner = DeviceSignIn()
    attempt = begin(owner)
    ops = operations()
    ops["persist"].side_effect = OSError("storage unavailable")
    owner.run(attempt, **ops)
    assert owner.poll()["status"] == "failed"
    assert not owner.poll()


def test_expired_attempt_does_not_poll_or_save():
    owner = DeviceSignIn()
    attempt = begin(owner)
    ops = operations()
    ops["max_wait"] = 0
    owner.run(attempt, **ops)
    assert owner.poll()["message"] == "timed out"
    ops["poll"].assert_not_called()
    ops["persist"].assert_not_called()


@pytest.mark.parametrize("slow_step", ["poll", "exchange"])
def test_network_result_after_deadline_is_not_saved(monkeypatch, slow_step):
    from types import SimpleNamespace
    from superforecasting_agent.hosting import device_auth

    now = [0.0]
    monkeypatch.setattr(device_auth, "time", SimpleNamespace(monotonic=lambda: now[0]))
    owner = DeviceSignIn()
    attempt = begin(owner)
    ops = operations()
    ops["max_wait"] = 1

    def slow(*args):
        now[0] = 2.0
        return {"code": "late", "token": "late"}

    ops[slow_step] = slow
    owner.run(attempt, **ops)
    ops["persist"].assert_not_called()
    assert owner.poll()["message"] == "timed out"


def test_host_shutdown_cancels_device_waiter_before_worker_drain():
    from superforecasting_agent.hosting.runtime import RuntimeHost

    host = RuntimeHost()
    attempt = begin(host.sign_in)
    ops = operations()
    ops.update(interval=60, max_wait=120)
    owner = host.sign_in
    thread = host.workers.start(
        lambda: owner.run(attempt, **ops), name="device-auth-fixture"
    )
    shutdown = dict(
        stop_services=lambda: None,
        release_prompts=lambda *_: None,
        interrupt_delegations=lambda: None,
        close_session=lambda *_: None,
    )
    assert host.shutdown(2, **shutdown)
    thread.join(1)
    assert not thread.is_alive()
    assert owner.poll()["status"] == "cancelled"
    ops["poll"].assert_not_called()
    host.start(reset_services=lambda: None)
    assert host.sign_in is not owner
    assert not host.sign_in.poll()
    assert host.shutdown(0, **shutdown)
