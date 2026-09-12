"""Reentrant cross-process file locking shared by credential and config stores."""

import os
import threading
import time
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast


class WindowsLocking(Protocol):
    LK_NBLCK: int
    LK_UNLCK: int

    def locking(self, fd: int, mode: int, nbytes: int, /) -> None: ...


fcntl: ModuleType | None
msvcrt: WindowsLocking | None
try:
    fcntl = import_module("fcntl")
except ImportError:
    fcntl = None
try:
    msvcrt = cast(WindowsLocking, import_module("msvcrt"))
except ImportError:
    msvcrt = None


@contextmanager
def file_lock(
    lock_path: Path,
    holder: threading.local,
    timeout_seconds: float,
    timeout_message: str,
    *,
    posix=fcntl,
    windows=msvcrt,
):
    """Cross-process advisory flock helper.

    Reentrant per thread, process, and resolved lock path. Independent paths
    always acquire their own OS lock, even when callers reuse the holder.
    Without an OS backend this only tracks nesting, not cross-process exclusion.
    """
    lock_path = lock_path.resolve()
    depths = getattr(holder, "depths", None)
    if depths is None:
        depths = holder.depths = {}
    key = (os.getpid(), str(lock_path))
    if depths.get(key, 0) > 0:
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if posix is None and windows is None:
        depths[key] = 1
        try:
            yield
        finally:
            depths.pop(key, None)
        return

    # On Windows, windows.locking needs the file to have content and the
    # file pointer at position 0. Ensure the lock file has at least 1 byte.
    if windows and (not lock_path.exists() or lock_path.stat().st_size == 0):
        lock_path.write_text(" ", encoding="utf-8")

    with lock_path.open("r+" if windows else "a+", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        while True:
            try:
                if posix:
                    posix.flock(lock_file.fileno(), posix.LOCK_EX | posix.LOCK_NB)
                else:
                    assert windows is not None  # no-backend fallback returned above
                    lock_file.seek(0)
                    windows.locking(lock_file.fileno(), windows.LK_NBLCK, 1)
                break
            except (BlockingIOError, OSError, PermissionError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(timeout_message)
                time.sleep(0.05)

        depths[key] = 1
        try:
            yield
        finally:
            depths.pop(key, None)
            if posix:
                try:
                    posix.flock(lock_file.fileno(), posix.LOCK_UN)
                except (OSError, IOError):
                    pass
            elif windows:
                try:
                    lock_file.seek(0)
                    windows.locking(lock_file.fileno(), windows.LK_UNLCK, 1)
                except (OSError, IOError):
                    pass
