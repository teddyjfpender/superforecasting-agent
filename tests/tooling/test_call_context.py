"""Call authority follows the submitting session, never a reused worker."""

import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from superforecasting_agent.tooling import prompt_callbacks
from superforecasting_agent.tooling.call_context import CallContext
from superforecasting_agent.tooling.interrupts import is_interrupted


def test_worker_context_and_callbacks_restore_after_failure():
    tenant = contextvars.ContextVar("test_tenant", default="worker")
    token = tenant.set("caller")
    original = prompt_callbacks.get_approval_callback()
    callback = lambda *_: "approved-by-caller"
    prompt_callbacks.set_approval_callback(callback)
    context = CallContext()
    prompt_callbacks.set_approval_callback(original)
    tenant.reset(token)

    def operation():
        assert tenant.get() == "caller"
        assert prompt_callbacks.get_approval_callback() is callback
        tenant.set("mutated-only-this-invocation")
        raise ValueError("controlled failure")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(ValueError, match="controlled failure"):
            pool.submit(context.run, operation).result(timeout=2)
        assert pool.submit(tenant.get).result(timeout=2) == "worker"
        assert pool.submit(prompt_callbacks.get_approval_callback).result(timeout=2) is None
        assert pool.submit(context.run, tenant.get).result(timeout=2) == "caller"


def test_retirement_cancels_inflight_and_rejects_late_calls_without_poisoning_worker():
    context = CallContext()
    entered = threading.Event()
    proceed = threading.Event()

    def operation():
        entered.set()
        assert proceed.wait(2)
        return is_interrupted()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(context.run, operation)
        assert entered.wait(2)
        context.retire()
        proceed.set()
        assert future.result(timeout=2)
        with pytest.raises(InterruptedError, match="retired"):
            pool.submit(context.run, lambda: pytest.fail("late effect")).result(timeout=2)
        assert not pool.submit(is_interrupted).result(timeout=2)
        assert not pool.submit(CallContext().run, is_interrupted).result(timeout=2)


def test_nested_call_keeps_parent_cancellation():
    parent = CallContext()
    child = parent.run(CallContext)
    parent.retire()
    with pytest.raises(InterruptedError, match="retired"):
        child.run(lambda: pytest.fail("effect after parent cancellation"))
    assert not is_interrupted()


def test_already_interrupted_caller_cannot_create_fresh_authority():
    from superforecasting_agent.tooling.interrupts import set_interrupt

    set_interrupt(True)
    try:
        context = CallContext()
    finally:
        set_interrupt(False)
    with pytest.raises(InterruptedError, match="retired"):
        context.run(lambda: pytest.fail("effect from interrupted caller"))


def test_maintenance_scope_restores_thread_cancellation_and_keeps_nested_stops():
    import threading

    from superforecasting_agent.tooling.interrupts import (
        cancellation_scope,
        is_interrupted,
        set_interrupt,
    )

    set_interrupt(True)
    try:
        with cancellation_scope(threading.Event(), inherit=False):
            assert not is_interrupted()
            nested = threading.Event()
            with cancellation_scope(nested):
                assert not is_interrupted()
                nested.set()
                assert is_interrupted()
            assert not is_interrupted()
        assert is_interrupted()
    finally:
        set_interrupt(False)
