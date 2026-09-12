"""Coordinate task browser lifetimes and exclusive endpoint transitions."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_condition = threading.Condition()
_owners: dict[str, tuple[int, int]] = {}
_transition_owner: int | None = None
_transition_depth = 0
_waiting_transitions = 0


@contextmanager
def browser_session_lifecycle(task_id: str) -> Iterator[None]:
    """Admit a task operation, reentrantly within the same task.

    Cross-task nesting has no lock order and can deadlock with another task or
    a draining endpoint transition. Only the exclusive transition owner may
    acquire multiple task lifetimes for global cleanup.
    """
    owner = threading.get_ident()
    with _condition:
        owned_tasks = {key for key, entry in _owners.items() if entry[0] == owner}
        if owned_tasks and task_id not in owned_tasks and _transition_owner != owner:
            raise RuntimeError("Cannot nest browser operations across tasks")

        def admitted() -> bool:
            current = _owners.get(task_id)
            if current is not None:
                return current[0] == owner
            return _transition_owner == owner or (
                _transition_owner is None and not _waiting_transitions
            )

        _condition.wait_for(admitted)
        _, depth = _owners.get(task_id, (owner, 0))
        _owners[task_id] = (owner, depth + 1)
    try:
        yield
    finally:
        with _condition:
            _, depth = _owners[task_id]
            if depth == 1:
                del _owners[task_id]
            else:
                _owners[task_id] = (owner, depth - 1)
            _condition.notify_all()


@contextmanager
def browser_endpoint_transition() -> Iterator[None]:
    """Drain admitted tasks and prevent new ones throughout a global transition.

    The transition owner may call nested cleanup helpers. Upgrading from a task
    operation is rejected instead of deadlocking with another admitted task.
    """
    global _transition_owner, _transition_depth, _waiting_transitions
    owner = threading.get_ident()
    with _condition:
        if _transition_owner == owner:
            _transition_depth += 1
        else:
            if any(entry[0] == owner for entry in _owners.values()):
                raise RuntimeError(
                    "Cannot change browser endpoint during a task operation"
                )
            _waiting_transitions += 1
            try:
                _condition.wait_for(lambda: _transition_owner is None and not _owners)
                _transition_owner = owner
                _transition_depth = 1
            finally:
                _waiting_transitions -= 1
                _condition.notify_all()
    try:
        yield
    finally:
        with _condition:
            _transition_depth -= 1
            if not _transition_depth:
                _transition_owner = None
            _condition.notify_all()
