"""JobContext: the COALESCING CONTRACT + cancellation + annotate (Arc B1).

The coalescing is the structural guard against the 1,300-event storm: a burst of
progress calls collapses to a bounded number of emissions, but the FINAL value
always lands and phase changes always pass.
"""

from __future__ import annotations

from forecasting.jobs.context import JobContext
from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore


class _FrozenClock:
    """A clock the test drives explicitly."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


def _ctx(tmp_path, *, sink=None, clock=None, extra_should_cancel=None, min_interval_s=0.125):
    store = JobStore(home=tmp_path)
    rec = JobRecord(job_id="job_ctx", type="warnings", status="running")
    store.write(rec)
    ctx = JobContext(
        rec,
        store,
        sink=sink,
        clock=clock or _FrozenClock(),
        extra_should_cancel=extra_should_cancel,
        min_interval_s=min_interval_s,
    )
    return ctx, store, rec


def test_burst_of_200_is_bounded_and_final_value_lands(tmp_path):
    """A 200-call same-phase burst at a frozen clock collapses to just the first
    and the final (done == total) events — the storm is impossible."""
    emitted: list[dict] = []
    ctx, _store, rec = _ctx(tmp_path, sink=emitted.append, clock=_FrozenClock(0.0))

    for i in range(1, 201):
        ctx.progress({"phase": "alert", "done": i, "total": 200})

    # Bounded: nowhere near 200 emissions.
    assert len(emitted) <= 5, [e.get("done") for e in emitted]
    # The FINAL value ALWAYS lands.
    assert emitted[-1]["done"] == 200
    assert emitted[0]["done"] == 1  # first always passes
    # In-memory accounting reflects the last call regardless of coalescing.
    assert rec.done_count == 200
    assert rec.total == 200


def test_phase_changes_always_pass(tmp_path):
    """Every change of phase emits, even at a frozen clock (throttle bypassed)."""
    emitted: list[dict] = []
    ctx, _store, _rec = _ctx(tmp_path, sink=emitted.append, clock=_FrozenClock(0.0))

    ctx.progress({"phase": "start", "done": 0, "total": 3})
    ctx.progress({"phase": "alert", "done": 1, "total": 3})
    ctx.progress({"phase": "alert", "done": 2, "total": 3})  # throttled (same phase)
    ctx.progress({"phase": "reconcile", "done": 3, "total": 3})
    ctx.progress({"phase": "done", "done": 3, "total": 3})

    phases = [e["phase"] for e in emitted]
    # start / first-alert / reconcile / done all pass; the middle alert is coalesced.
    assert phases == ["start", "alert", "reconcile", "done"]


def test_time_gate_allows_when_interval_elapses(tmp_path):
    """When the clock advances past min_interval, same-phase events pass again."""
    emitted: list[dict] = []
    clock = _FrozenClock(0.0)
    ctx, _store, _rec = _ctx(tmp_path, sink=emitted.append, clock=clock, min_interval_s=0.125)

    ctx.progress({"phase": "alert", "done": 1})  # first
    clock.t = 0.05
    ctx.progress({"phase": "alert", "done": 2})  # within interval -> coalesced
    clock.t = 0.20
    ctx.progress({"phase": "alert", "done": 3})  # interval elapsed -> passes

    dones = [e["done"] for e in emitted]
    assert dones == [1, 3]


def test_flush_lands_a_trailing_throttled_event(tmp_path):
    """If the LAST event is neither terminal nor a phase change, flush() still
    lands it — the final value is never swallowed."""
    emitted: list[dict] = []
    ctx, _store, _rec = _ctx(tmp_path, sink=emitted.append, clock=_FrozenClock(0.0))

    ctx.progress({"phase": "alert", "done": 1})  # first, passes
    ctx.progress({"phase": "alert", "done": 2})  # throttled, held
    ctx.progress({"phase": "alert", "done": 3})  # throttled, held (replaces pending)
    assert [e["done"] for e in emitted] == [1]

    ctx.flush()
    assert [e["done"] for e in emitted] == [1, 3]
    # flush is idempotent (nothing pending now).
    ctx.flush()
    assert [e["done"] for e in emitted] == [1, 3]


def test_coalesced_progress_persisted_to_record(tmp_path):
    """Only the emitted (coalesced) events append to the record.progress list —
    so the persisted array is bounded too."""
    ctx, store, rec = _ctx(tmp_path, clock=_FrozenClock(0.0))
    for i in range(1, 51):
        ctx.progress({"phase": "alert", "done": i, "total": 50})
    reloaded = store.read("job_ctx")
    assert len(reloaded.progress) <= 5
    assert reloaded.progress[-1]["done"] == 50


def test_should_cancel_stop_file_path(tmp_path):
    ctx, store, _rec = _ctx(tmp_path)
    assert ctx.should_cancel() is False
    store.stop_path("job_ctx").write_text("1")
    assert ctx.should_cancel() is True
    # Latches: stays cancelled even if the file is removed.
    store.clear_stop("job_ctx")
    assert ctx.should_cancel() is True


def test_should_cancel_record_flag_path(tmp_path):
    """The record cancel_requested flag (no stop file) is the second path."""
    store = JobStore(home=tmp_path)
    rec = JobRecord(job_id="job_flag", type="warnings", status="running")
    store.write(rec)
    ctx = JobContext(rec, store, clock=_FrozenClock())
    assert ctx.should_cancel() is False
    # Set the flag durably WITHOUT touching the stop file.
    stored = store.read("job_flag")
    stored.cancel_requested = True
    store.write(stored)
    assert store.stop_path("job_flag").exists() is False
    assert ctx.should_cancel() is True


def test_should_cancel_in_process_event_path(tmp_path):
    flag = {"stop": False}
    ctx, _store, _rec = _ctx(tmp_path, extra_should_cancel=lambda: flag["stop"])
    assert ctx.should_cancel() is False
    flag["stop"] = True
    assert ctx.should_cancel() is True


def test_annotate_persists(tmp_path):
    ctx, store, _rec = _ctx(tmp_path)
    ctx.annotate("spend_class", "free")
    ctx.annotate("est_calls", 12)
    reloaded = store.read("job_ctx")
    assert reloaded.annotations == {"spend_class": "free", "est_calls": 12}
