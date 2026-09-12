"""Coordinate allocation of browser sessions independently of browser providers."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_creation = threading.Condition()
_creating: set[str] = set()


@contextmanager
def browser_session_creation(task_id: str) -> Iterator[None]:
    """Serialize allocation for one task while unrelated tasks remain independent.

    Callers recheck the session cache after admission. Failed allocations release
    admission, allowing a waiting caller to retry without retaining per-task locks.
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
