"""One detached-job runtime (Arc B).

Quorum, reforecast/task, and warning-automode become TYPES on this one runtime;
every future background capability arrives pre-integrated with progress,
coalescing, cancellation, persistence, and desk re-attach.

    from forecasting.jobs import JobStore, runtime
    from forecasting.jobs.types import resolve
"""

from __future__ import annotations

from forecasting.jobs import runtime
from forecasting.jobs.context import JobContext
from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore
from forecasting.jobs.types import (
    JobType,
    register,
    registered_types,
    resolve,
)

__all__ = [
    "JobRecord",
    "JobStore",
    "JobContext",
    "JobType",
    "runtime",
    "register",
    "resolve",
    "registered_types",
]
