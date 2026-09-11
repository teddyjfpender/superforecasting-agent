"""Reentrant cross-process file locking shared by credential and config stores."""
from contextlib import contextmanager
from pathlib import Path
import threading
import time
try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

@contextmanager
def file_lock(
    lock_path: Path,
    holder: threading.local,
    timeout_seconds: float,
    timeout_message: str,
    *, posix=fcntl, windows=msvcrt,
):
    """Cross-process advisory flock helper.

    Reentrant per-thread via ``holder.depth``. Falls back to a depth-only
    guard when neither ``fcntl`` nor ``msvcrt`` is available (rare).
    Callers supply their own ``threading.local`` so independent locks
    (e.g. profile auth.json vs shared Nous store) don't share reentrancy
    state — that would let one lock's reentrant acquisition silently skip
    the other's kernel-level flock.
    """
    if getattr(holder, "depth", 0) > 0:
        holder.depth += 1
        try:
            yield
        finally:
            holder.depth -= 1
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if posix is None and windows is None:
        holder.depth = 1
        try:
            yield
        finally:
            holder.depth = 0
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
                    lock_file.seek(0)
                    windows.locking(lock_file.fileno(), windows.LK_NBLCK, 1)
                break
            except (BlockingIOError, OSError, PermissionError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(timeout_message)
                time.sleep(0.05)

        holder.depth = 1
        try:
            yield
        finally:
            holder.depth = 0
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


