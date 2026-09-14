"""An execution call's copied context, prompt callbacks and cancellation scope.

Interpreter state may persist, but each call receives a fresh instance. Retiring
an instance cancels only its own work and prevents subsequent dispatch through
it, including on a worker thread later reused by another component.
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from superforecasting_agent.tooling import prompt_callbacks
from superforecasting_agent.tooling.interrupts import cancellation_scope, is_interrupted

P = ParamSpec("P")
T = TypeVar("T")


class CallContext:
    def __init__(self) -> None:
        self.cancelled = threading.Event()
        if is_interrupted():
            self.cancelled.set()
        self._context = contextvars.copy_context()
        self._approval = prompt_callbacks.get_approval_callback()
        self._sudo = prompt_callbacks.get_sudo_password_callback()

    def retire(self) -> None:
        self.cancelled.set()

    def run(self, operation: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        """Copy context per invocation; restore the worker's exact callbacks."""
        if self.cancelled.is_set():
            raise InterruptedError("Execution call authority has retired")

        def invoke() -> T:
            previous_approval = prompt_callbacks.get_approval_callback()
            previous_sudo = prompt_callbacks.get_sudo_password_callback()
            try:
                prompt_callbacks.set_approval_callback(self._approval)
                prompt_callbacks.set_sudo_password_callback(self._sudo)
                with cancellation_scope(self.cancelled):
                    # Recheck after entering the worker scope. An operation
                    # already executing must cooperate with its cancellation.
                    if is_interrupted():
                        raise InterruptedError("Execution call authority has retired")
                    return operation(*args, **kwargs)
            finally:
                prompt_callbacks.set_approval_callback(previous_approval)
                prompt_callbacks.set_sudo_password_callback(previous_sudo)

        return self._context.copy().run(invoke)
