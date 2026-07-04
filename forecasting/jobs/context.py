"""JobContext — the execution-time handle a job type gets: progress (with
BUILT-IN coalescing), cooperative cancellation, and annotation.

The coalescing is the structural fix for the 1,300-event storm: a job may call
``ctx.progress(...)`` as often as it likes, but the sink (the gateway's event
emit) is time-gated to ``min_interval_s`` per type — with THREE invariants that
always pass regardless of the gate:

* FIRST — the opening event of a run always emits;
* PHASE-CHANGE — any change of ``phase`` always emits;
* FINAL — a terminal phase, or ``done >= total``, always emits.

so the final value can never be swallowed by the throttle. A trailing throttled
event is additionally held and flushed at close (``flush()``), guaranteeing the
last value lands even when it is neither terminal nor a phase change.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore

# Phases that are terminal by name (a job's last progress event) — these always
# pass the coalescer.
_TERMINAL_PHASES = frozenset(
    {"done", "complete", "completed", "error", "cancelled", "finished"}
)

_NO_PHASE = object()  # sentinel: no phase seen yet


class JobContext:
    def __init__(
        self,
        record: JobRecord,
        store: JobStore,
        *,
        sink: Callable[[dict[str, Any]], None] | None = None,
        extra_should_cancel: Callable[[], bool] | None = None,
        min_interval_s: float = 0.125,
        clock: Callable[[], float] = time.monotonic,
        persist: bool = True,
    ) -> None:
        self._record = record
        self._store = store
        self._sink = sink
        self._extra_should_cancel = extra_should_cancel
        self._min_interval_s = max(0.0, float(min_interval_s))
        self._clock = clock
        self._persist = persist
        self._last_emit_at: float | None = None
        self._last_phase: Any = _NO_PHASE
        self._emit_count = 0
        self._pending: dict[str, Any] | None = None
        self._cancelled = False

    @property
    def record(self) -> JobRecord:
        return self._record

    @property
    def emit_count(self) -> int:
        """How many progress events actually passed the coalescer (test hook)."""
        return self._emit_count

    # ── progress ─────────────────────────────────────────────────────────────
    def progress(self, payload: Any = None, /, **extra: Any) -> None:
        """Report progress. Accepts a raw payload dict (the shape
        ``run_warning_resolution`` emits) or ``phase=..., done=..., total=...``
        keyword form. Coalesced before it reaches the sink."""

        if isinstance(payload, dict):
            event = dict(payload)
            event.update(extra)
        elif payload is None:
            event = dict(extra)
        else:
            event = {"phase": payload, **extra}
        self._handle(event)

    def _handle(self, event: dict[str, Any]) -> None:
        phase = event.get("phase")
        done = event.get("done")
        total = event.get("total")
        current = event.get("current") or event.get("alert_id") or event.get("reason")

        # In-memory accounting is updated on EVERY call (cheap) — only the sink
        # + persistence are coalesced.
        if isinstance(done, (int, float)) and not isinstance(done, bool):
            self._record.done_count = int(done)
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            self._record.total = int(total)
        if current is not None:
            self._record.current = str(current)

        now = self._clock()
        is_first = self._last_emit_at is None
        is_phase_change = phase != self._last_phase
        is_final = self._is_final(phase, done, total)
        throttled = (not is_first) and (now - self._last_emit_at) < self._min_interval_s

        if is_first or is_phase_change or is_final or not throttled:
            self._flush_event(event, now, phase)
        else:
            # Hold the most recent suppressed event so flush() can land it.
            self._pending = event

    @staticmethod
    def _is_final(phase: Any, done: Any, total: Any) -> bool:
        if phase in _TERMINAL_PHASES:
            return True
        if (
            isinstance(done, (int, float))
            and not isinstance(done, bool)
            and isinstance(total, (int, float))
            and not isinstance(total, bool)
            and total > 0
        ):
            return done >= total
        return False

    def _flush_event(self, event: dict[str, Any], now: float, phase: Any) -> None:
        self._last_emit_at = now
        self._last_phase = phase
        self._pending = None
        self._emit_count += 1
        self._record.progress.append(event)
        if self._persist:
            self._store.write(self._record)
        if self._sink is not None:
            self._sink(event)

    def flush(self) -> None:
        """Land the last suppressed progress event, if any — the belt-and-braces
        guarantee that the FINAL value is never swallowed by the throttle."""

        if self._pending is not None:
            event = self._pending
            self._flush_event(event, self._clock(), event.get("phase"))

    # ── cancellation ─────────────────────────────────────────────────────────
    def should_cancel(self) -> bool:
        """Polled by the job body before each unit of work. Checks (in order) the
        in-process signal (the gateway's Event), then the durable stop-file /
        record ``cancel_requested`` flag. Latches once set."""

        if self._cancelled:
            return True
        cancelled = False
        if self._extra_should_cancel is not None:
            try:
                cancelled = bool(self._extra_should_cancel())
            except Exception:  # a cancel probe must never break the run
                cancelled = False
        if not cancelled:
            try:
                cancelled = self._store.is_cancel_requested(self._record.job_id)
            except Exception:
                cancelled = False
        if cancelled:
            self._cancelled = True
            self._record.cancel_requested = True
        return cancelled

    # ── annotation ───────────────────────────────────────────────────────────
    def annotate(self, key: str, value: Any) -> None:
        """Attach durable metadata to the record (spend class, resolved model,
        cost notes …). Persisted immediately so ``jobs.status`` reflects it."""

        self._record.annotations[str(key)] = value
        if self._persist:
            self._store.write(self._record)


__all__ = ["JobContext"]
