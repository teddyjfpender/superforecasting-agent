"""Durable cancellation admission shared by CLI and RPC adapters."""

from __future__ import annotations

from dataclasses import dataclass

from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore


@dataclass(frozen=True)
class CancellationReceipt:
    job_id: str
    accepted: bool
    record: JobRecord | None


def request_job_cancellation(store: JobStore, job_id: str) -> CancellationReceipt:
    """Acknowledge durable admission, never infer worker exit from a request.

    Storage failures propagate. Product adapters may signal their local worker only
    after this succeeds; a transient in-memory signal cannot replace persistence.
    The returned record is an observation, not a promise that a live worker stopped.
    """
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id must be a non-empty string")
    job_id = job_id.strip()
    accepted = store.request_cancel(job_id)
    if not accepted:
        return CancellationReceipt(job_id, False, None)
    # A concurrent deletion after admission must not turn a persisted request
    # into a fabricated terminal status. Admission remains acknowledged.
    try:
        record = store.read(job_id)
    except FileNotFoundError:
        record = None
    return CancellationReceipt(job_id, True, record)
