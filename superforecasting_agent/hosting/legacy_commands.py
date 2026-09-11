"""On-demand ownership of the compatibility command worker for a session."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any


def invalidate_worker(session: MutableMapping[str, Any]) -> None:
    """Retire an existing worker without constructing its replacement.

    Failed cleanup retains the handle and retirement flag. No later command may
    reuse that worker; cleanup must succeed before a new one can be admitted.
    """
    with session.setdefault("_slash_worker_lock", threading.RLock()):
        worker = session.get("slash_worker")
        if worker is None:
            return
        session["_slash_worker_retiring"] = True
        worker.close()
        session["slash_worker"] = None
        session["_slash_worker_retiring"] = False


@contextmanager
def use_worker(
    session: MutableMapping[str, Any], factory: Callable[[], Any]
) -> Iterator[Any]:
    """Serialize command execution, invalidation and lazy worker construction."""
    with session.setdefault("_slash_worker_lock", threading.RLock()):
        if session.get("_slash_worker_retiring"):
            invalidate_worker(session)
        worker = session.get("slash_worker")
        if worker is None:
            worker = factory()
            session["slash_worker"] = worker
        try:
            yield worker
        except BaseException as exc:
            try:
                invalidate_worker(session)
            except Exception as cleanup_error:
                if not isinstance(exc, Exception):
                    exc.add_note(f"Worker cleanup pending: {cleanup_error}")
                    raise exc from cleanup_error
                raise RuntimeError(
                    f"Legacy command failed: {exc}; worker cleanup pending: {cleanup_error}"
                ) from cleanup_error
            raise
