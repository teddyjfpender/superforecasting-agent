"""Gateway job lifetime tests with controlled work and independent stores."""

import threading
from types import SimpleNamespace

import pytest


from forecasting.jobs import runtime
from forecasting.jobs.store import JobStore
from superforecasting_agent.hosting.job_workers import JobWorkers
from superforecasting_agent.hosting.runtime import RuntimeHost
from superforecasting_agent.hosting.workers import HostStopping
from tui_gateway.jobs_rpc import register


def gateway(home):
    methods, events = {}, []
    server = SimpleNamespace(
        _host=RuntimeHost(home=home),
        register_method=lambda name, fn: methods.__setitem__(name, fn),
        _ok=lambda rid, result: {"id": rid, "result": result},
        _err=lambda rid, code, message: {"id": rid, "error": {"code": code, "message": message}},
        _emit=lambda *event: events.append(event),
    )
    store = JobStore(home=home)
    owner = register(server, store_factory=lambda: store)
    return server, store, owner, methods, events


def test_stale_worker_cannot_remove_or_signal_replacement():
    owner = JobWorkers()
    old, current = threading.Event(), threading.Event()
    owner.install("same", old)
    owner.install("same", current)
    owner.retire("same", old)
    assert owner.get("same") is current
    assert not owner.signal("same", old)
    assert not current.is_set()
    assert owner.signal("same", current)
    owner.retire("same", current)
    assert owner.get("same") is None


def test_two_hosts_cancel_and_drain_independently(tmp_path, monkeypatch):
    a, sa, wa, ma, ea = gateway(tmp_path / "a")
    b, sb, wb, mb, eb = gateway(tmp_path / "b")
    entered = {id(sa): threading.Event(), id(sb): threading.Event()}
    release = threading.Event()
    predicates = {}
    def run(job_id, *, store, extra_should_cancel, **callbacks):
        predicates[id(store)] = extra_should_cancel
        entered[id(store)].set()
        assert release.wait(5)
        callbacks["on_complete"]({"ok": True})
    monkeypatch.setattr(runtime, "run", run)
    monkeypatch.setattr(JobStore, "new_id", lambda self: "job_same")
    try:
        for methods in (ma, mb):
            assert "result" in methods["jobs.start"]("start", {"type": "warnings", "spec": {}})
        assert all(event.wait(2) for event in entered.values())
        assert wa.get("job_same") is not wb.get("job_same")
        assert ma["jobs.cancel"]("cancel", {"job_id": "job_same"})["result"]["cancel_requested"]
        assert predicates[id(sa)]()
        assert not predicates[id(sb)]()
        a._host.workers.stop()
        assert not a._host.workers.drain(0)
        assert ma["jobs.active"]("late", {})["error"]["code"] == 5030
        assert "result" in mb["jobs.active"]("live", {})
        b._host.workers.stop()
        assert predicates[id(sb)]()  # shutdown is cooperative cancellation
        release.set()
        assert a._host.workers.drain(2)
        assert a._host.workers.drain(0)
        b._host.workers.stop()
        assert b._host.workers.drain(2)
        assert not ea  # stopped host cannot publish a late completion
        assert wa.get("job_same") is None
        assert wb.get("job_same") is None
    finally:
        release.set()
        for host in (a._host, b._host):
            host.workers.stop()
            host.workers.drain(2)


@pytest.mark.parametrize("error,code", [(RuntimeError("cannot start thread"), 5008), (HostStopping("draining"), 5030)])
def test_thread_start_failure_retires_handle_but_preserves_recoverable_record(tmp_path, monkeypatch, error, code):
    server, store, owner, methods, _ = gateway(tmp_path)
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(server._host.workers, "start", fail)
    response = methods["jobs.start"]("start", {"type": "warnings"})
    assert response["error"]["code"] == code
    record, = store.list()
    assert record.status == "queued"
    assert owner.get(record.job_id) is None


def test_host_replacement_suppresses_old_worker_events(tmp_path, monkeypatch):
    server, store, owner, methods, events = gateway(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = server._host
    threads = []
    start = original.workers.start
    def capture_thread(*args, **kwargs):
        thread = start(*args, **kwargs)
        threads.append(thread)
        return thread
    monkeypatch.setattr(original.workers, "start", capture_thread)
    def run(job_id, **callbacks):
        entered.set()
        assert release.wait(5)
        callbacks["sink"]({"late": True})
        callbacks["on_complete"]({"late": True})
    monkeypatch.setattr(runtime, "run", run)
    try:
        methods["jobs.start"]("start", {"type": "warnings"})
        assert entered.wait(2)
        server._host = RuntimeHost()
        release.set()
        threads[0].join(2)
        assert not threads[0].is_alive()
        assert not original.workers.stopping
        assert events == []  # replacement identity alone rejects late events
    finally:
        release.set()
        original.workers.stop()
        original.workers.drain(2)
