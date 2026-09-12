"""Coordinate browser session lifecycle changes independently of browser providers."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_creation = threading.Condition()
_creating: set[str] = set()


@contextmanager
def browser_session_lifecycle(task_id: str) -> Iterator[None]:
    """Serialize lifecycle changes for one task while unrelated tasks remain independent.

    Creation callers recheck the cache after admission. Cleanup callers capture
    owned resources only after earlier allocations settle. Failures release
    admission, allowing retry without retaining per-task locks.
    """
    with _creation:
        _creation.wait_for(lambda: task_id not in _creating)
        _creating.add(task_id)
    try:
        yield
    finally:
        with _creation:
            _creating.remove(task_id)
            _creation.notify_all()
