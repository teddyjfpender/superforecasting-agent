"""Process ID parsing and liveness shared by hosts and resource owners."""

import os
import sys
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"


def read_pid_file(path: Path) -> int:
    """Read one process ID; never accept POSIX process-group selectors.

    A valid number alone does not prove resource ownership or prevent PID reuse.
    """
    pid = int(path.read_text(encoding="utf-8").strip())
    if pid <= 0:
        raise ValueError(f"PID file must contain a positive process ID: {path}")
    return pid


def pid_exists(pid: int) -> bool:
    """Cross-platform "is this PID alive" check that does NOT kill the target.

    CRITICAL on Windows: Python's ``os.kill(pid, 0)`` is NOT a no-op like it
    is on POSIX. CPython's Windows implementation
    (``Modules/posixmodule.c::os_kill_impl``) treats ``sig=0`` as
    ``CTRL_C_EVENT`` because the two values collide at the C level, and
    routes it through ``GenerateConsoleCtrlEvent(0, pid)`` — which sends
    a Ctrl+C to the entire console process group containing the target
    PID, not just the PID itself. Any caller that wanted to "check if
    this PID is alive" via ``os.kill(pid, 0)`` on Windows was silently
    killing that process (and often unrelated processes in the same
    console group). Long-standing Python quirk; see bpo-14484.

    Implementation: prefer :mod:`psutil` (hard dependency — the canonical
    cross-platform answer, maintained by Giampaolo Rodolà, uses
    ``OpenProcess + GetExitCodeProcess`` on Windows internally). Fall back
    to a hand-rolled ctypes ``OpenProcess`` / ``WaitForSingleObject`` pair
    on Windows + ``os.kill(pid, 0)`` on POSIX if psutil is somehow
    unavailable — e.g. stripped-down install or import error during the
    scaffold phase before ``psutil`` is pip-installed.
    """
    if pid <= 0:
        return False
    try:
        import psutil

        return bool(psutil.pid_exists(int(pid)))
    except ImportError:
        pass  # Fall through to stdlib fallback.

    if _IS_WINDOWS:
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            # Pin return types — default ctypes restype is c_int (signed),
            # which mangles WAIT_* DWORD return codes into negative numbers.
            kernel32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
            kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            kernel32.GetLastError.argtypes = []
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.WaitForSingleObject.restype = ctypes.c_uint
            kernel32.GetLastError.restype = ctypes.c_uint
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            SYNCHRONIZE = 0x100000  # required for WaitForSingleObject
            WAIT_TIMEOUT = 0x00000102
            ERROR_INVALID_PARAMETER = 87
            ERROR_ACCESS_DENIED = 5
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, int(pid)
            )
            if not handle:
                err = kernel32.GetLastError()
                if err == ERROR_INVALID_PARAMETER:
                    return False  # PID definitely gone
                if err == ERROR_ACCESS_DENIED:
                    return True  # Exists but owned by another user/session
                return False  # Conservative default for unknown errors
            try:
                wait_result = kernel32.WaitForSingleObject(handle, 0)
                # WAIT_TIMEOUT = still running; anything else (WAIT_OBJECT_0
                # via exit, WAIT_FAILED via handle issue) = treat as gone.
                return wait_result == WAIT_TIMEOUT
            finally:
                kernel32.CloseHandle(handle)
        except (OSError, AttributeError):
            return False
    else:
        try:
            os.kill(
                int(pid), 0
            )  # windows-footgun: ok — POSIX-only branch (the whole point of _pid_exists)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but we can't signal it — still alive.
            return True
        except OSError:
            return False
