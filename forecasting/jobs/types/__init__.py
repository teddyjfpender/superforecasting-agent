"""The registry of job TYPES. Each type declares how to run one class of
background work on the shared runtime: an ``execute(spec, ctx)`` callable, a
progress-rate policy (``min_interval_s``), an optional back-compat
``alias_namespace`` (the legacy event prefix its aliased RPCs still emit), and a
``spend_class`` (the Arc-9 approval seam, wired now as a pass-through).

Adding a capability = registering a :class:`JobType`. It then arrives
pre-integrated with progress coalescing, cancellation, persistence, and re-attach.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class JobType:
    name: str
    execute: Callable[[dict[str, Any], Any], Any]
    min_interval_s: float = 0.125
    alias_namespace: str | None = None
    spend_class: str = "free"
    validate_spec: Callable[[dict[str, Any]], None] | None = None


_REGISTRY: dict[str, JobType] = {}


def register(job_type: JobType) -> JobType:
    _REGISTRY[job_type.name] = job_type
    return job_type


def resolve(name: str) -> JobType:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown job type: {name!r}") from None


def registered_types() -> list[str]:
    return sorted(_REGISTRY)


# Register the built-in types on package import. ``JobType``/``register`` are
# defined above, so these bottom-of-module imports resolve cleanly despite the
# submodules importing back from here.
from forecasting.jobs.types import warnings as _warnings  # noqa: E402,F401
from forecasting.jobs.types import reforecast as _reforecast  # noqa: E402,F401
from forecasting.jobs.types import task as _task  # noqa: E402,F401
from forecasting.jobs.types import refresh as _refresh  # noqa: E402,F401

__all__ = ["JobType", "register", "resolve", "registered_types"]
