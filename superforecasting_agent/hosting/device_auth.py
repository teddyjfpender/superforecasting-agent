"""Host-owned device sign-in attempts with cancellation and stale-result fencing."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(eq=False)
class SignInAttempt:
    state: dict[str, Any]
    cancelled: threading.Event = field(default_factory=threading.Event)
    consumed: bool = False


class DeviceSignIn:
    """Own one current attempt; superseded work cannot save or publish results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: SignInAttempt | None = None

    def begin(
        self, *, provider: str, session_id: str, user_code: str, url: str
    ) -> SignInAttempt:
        attempt = SignInAttempt(
            dict(
                provider=provider,
                session_id=session_id,
                user_code=user_code,
                url=url,
                status="pending",
            )
        )
        with self._lock:
            if self._current is not None:
                self._current.cancelled.set()
            self._current = attempt
        return attempt

    def cancel(self) -> None:
        with self._lock:
            attempt = self._current
            if attempt is not None and attempt.state["status"] == "pending":
                attempt.cancelled.set()
                attempt.state.update(status="cancelled", message="sign-in cancelled")

    def poll(self, *, cancel: bool = False) -> dict[str, Any]:
        with self._lock:
            attempt = self._current
            if attempt is None or attempt.consumed:
                return {}
            if cancel and attempt.state["status"] == "pending":
                attempt.cancelled.set()
                attempt.state.update(status="cancelled", message="sign-in cancelled")
            snapshot = dict(attempt.state)
            if snapshot["status"] != "pending":
                attempt.consumed = True
            return snapshot

    def _active(self, attempt: SignInAttempt) -> bool:
        return (
            self._current is attempt
            and not attempt.cancelled.is_set()
            and attempt.state["status"] == "pending"
        )

    def fail(self, attempt: SignInAttempt, message: str) -> None:
        with self._lock:
            if self._active(attempt):
                attempt.state.update(status="failed", message=message)

    def run(
        self,
        attempt: SignInAttempt,
        *,
        interval: float,
        max_wait: float,
        poll: Callable[[], Mapping[str, Any] | None],
        exchange: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        persist: Callable[[Mapping[str, Any]], None],
        success_message: str,
        timeout_message: str,
    ) -> None:
        deadline = time.monotonic() + max_wait
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.fail(attempt, timeout_message)
                    return
                if attempt.cancelled.wait(min(max(0.0, interval), remaining)):
                    return
                with self._lock:
                    if not self._active(attempt):
                        return
                if time.monotonic() >= deadline:
                    self.fail(attempt, timeout_message)
                    return
                result = poll()
                if result is None:
                    continue
                with self._lock:
                    if not self._active(attempt):
                        return
                    if time.monotonic() >= deadline:
                        attempt.state.update(status="failed", message=timeout_message)
                        return
                credentials = exchange(result)
                # Save under the same lock as replacement/cancel. If either won
                # while network I/O was in flight, these credentials are stale.
                with self._lock:
                    if not self._active(attempt):
                        return
                    if time.monotonic() >= deadline:
                        attempt.state.update(status="failed", message=timeout_message)
                        return
                    persist(credentials)
                    attempt.state.update(status="success", message=success_message)
                return
        except Exception as exc:
            self.fail(attempt, str(exc))
