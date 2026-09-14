"""Standalone persistent Python cell runner, also copyable to remote backends.

The host owns deadlines and tool authority. stdin/stdout carry bounded JSON
control frames. Native stdout writes go to stderr, never into the protocol.
Closing the owning input pipe terminates even a cell that never returns.
This is an execution mechanism, not a sandbox for hostile Python code.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import queue
import signal
import sys
import threading
import traceback
from typing import Any

MAX_REQUEST_BYTES = 1_048_576
MAX_OUTPUT_CHARS = 250_000


def own_windows_process_tree() -> int | None:
    """Own an unnamed, non-inherited kill-on-close job before accepting cells.

    The runner holds the sole handle. Windows closes it on normal exit or
    forced termination, killing descendants without PID-based cleanup races.
    https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_working_set", ctypes.c_size_t),
            ("max_working_set", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io_counters", ctypes.c_uint64 * 6),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    api.SetInformationJobObject.restype = wintypes.BOOL
    api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    api.AssignProcessToJobObject.restype = wintypes.BOOL
    api.GetCurrentProcess.argtypes = []
    api.GetCurrentProcess.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    handle = api.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
    if not api.SetInformationJobObject(
        handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
    ):
        error = ctypes.WinError(ctypes.get_last_error())
        api.CloseHandle(handle)
        raise error
    if not api.AssignProcessToJobObject(handle, api.GetCurrentProcess()):
        error = ctypes.WinError(ctypes.get_last_error())
        api.CloseHandle(handle)
        raise error
    # Do not close a successfully assigned job: that would terminate this
    # interpreter. Its sole handle lives until the OS disposes the process.
    return handle


def owner_exit(code: int) -> None:
    """Only a verified, dedicated POSIX session may terminate its own group."""
    if (
        os.name == "posix"
        and os.environ.get("SUPERFORECASTING_AGENT_KERNEL_OWN_GROUP") == "1"
        and os.getpid() == os.getpgrp() == os.getsid(0)
    ):
        os.killpg(os.getpgrp(), signal.SIGKILL)  # windows-footgun: ok
    os._exit(code)


class Capture(io.TextIOBase):
    """Bound Python text output in memory while reporting omitted characters."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.kept = 0
        self.omitted = 0
        self._lock = threading.Lock()

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("write() requires a string")
        with self._lock:
            prefix = text[: max(0, MAX_OUTPUT_CHARS - self.kept)]
            if prefix:
                self.parts.append(prefix)
            self.kept += len(prefix)
            self.omitted += len(text) - len(prefix)
        return len(text)

    def value(self) -> str:
        with self._lock:
            return "".join(self.parts)


def _read_requests(inbox: queue.Queue[dict[str, Any]]) -> None:
    """Watch owner EOF concurrently with execution; never queue unbounded work."""
    try:
        while True:
            raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            if not raw:
                owner_exit(0)
            if len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
                owner_exit(65)
            request = json.loads(raw)
            if (
                not isinstance(request, dict)
                or set(request)
                not in ({"id", "code", "reset"}, {"id", "code", "reset", "rpc"})
                or not isinstance(request["id"], str)
                or not 1 <= len(request["id"]) <= 128
                or not isinstance(request["code"], str)
                or type(request["reset"]) is not bool
            ):
                owner_exit(65)
            rpc = request.get("rpc")
            if rpc is not None and (
                not isinstance(rpc, dict)
                or set(rpc)
                not in ({"endpoint", "token"}, {"endpoint", "token", "transport"})
                or not all(isinstance(value, str) and value for value in rpc.values())
            ):
                owner_exit(65)
            if rpc is not None and rpc.get("transport", "socket") not in {
                "socket",
                "file",
            }:
                owner_exit(65)
            inbox.put_nowait(request)
    except (ValueError, OSError, queue.Full):
        owner_exit(65)


def main() -> None:
    _windows_job = own_windows_process_tree()
    # Own a duplicate, never close the host's borrowed stream object. fd 1
    # becomes raw diagnostic output; Python print is captured per cell below.
    protocol_fd = os.dup(sys.stdout.fileno())
    os.set_inheritable(protocol_fd, False)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    inbox: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
    namespace: dict[str, Any] = {"__name__": "__main__"}
    sequence = 0
    previous = ""
    reader = threading.Thread(target=_read_requests, args=(inbox,), daemon=True)
    reader.start()
    with os.fdopen(protocol_fd, "w", encoding="utf-8") as protocol:
        runtime = {
            "python": sys.version,
            "implementation": sys.implementation.name,
            "platform": sys.platform,
            "machine": platform.machine(),
            "packages": sorted(
                (distribution.metadata.get("Name", ""), distribution.version)
                for distribution in importlib.metadata.distributions()
            ),
        }
        protocol.write(
            json.dumps({"ready": True, "version": 1, "runtime": runtime}) + "\n"
        )
        protocol.flush()
        while True:
            request = inbox.get()
            if "rpc" in request:
                for name in ("forecast_tools",):
                    module = sys.modules.get(name)
                    connection = getattr(module, "_sock", None)
                    if connection is not None and module is not None:
                        connection.close()
                        setattr(module, "_sock", None)
                if request["rpc"].get("transport") == "file":
                    os.environ["SUPERFORECASTING_AGENT_RPC_DIR"] = request["rpc"][
                        "endpoint"
                    ]
                    module = sys.modules.get("forecast_tools")
                    if module is not None:
                        setattr(module, "_RPC_DIR", request["rpc"]["endpoint"])
                        setattr(module, "_seq", 0)
                os.environ["SUPERFORECASTING_AGENT_RPC_SOCKET"] = request["rpc"][
                    "endpoint"
                ]
                os.environ["SUPERFORECASTING_AGENT_RPC_TOKEN"] = request["rpc"]["token"]
            if request["reset"]:
                namespace = {"__name__": "__main__"}
            stdout, stderr = Capture(), Capture()
            error = False
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    exec(compile(request["code"], "<forecast-cell>", "exec"), namespace)
                except BaseException as exc:
                    # Python errors (including SystemExit) can leave assignments
                    # behind. Report that honestly; the host decides on reset.
                    error = True
                    # The private staging path is not part of the user's
                    # calculation. Start at its first frame so a replay in a
                    # new kernel preserves useful, comparable diagnostics.
                    trace = exc.__traceback__
                    traceback.print_exception(
                        type(exc), exc, trace.tb_next if trace else None
                    )
            sequence += 1
            # A Python thread left behind by a cell must never inherit the
            # next cell's tool authority or capture target. Retire this entire
            # interpreter instead of trying to kill an arbitrary Python thread.
            leaked_threads = [
                thread
                for thread in threading.enumerate()
                if thread is not threading.current_thread() and thread is not reader
            ]
            result = {
                "version": 1,
                "id": request["id"],
                "sequence": sequence,
                "reset": request["reset"],
                "code_sha256": hashlib.sha256(request["code"].encode()).hexdigest(),
                "previous_sha256": previous,
                "stdout": stdout.value(),
                "stderr": stderr.value(),
                "stdout_omitted_chars": stdout.omitted,
                "stderr_omitted_chars": stderr.omitted,
                "error": error,
                "state_preserved": not leaked_threads,
                "retirement_reason": "cell_left_running_threads"
                if leaked_threads
                else None,
            }
            encoded = json.dumps(result, ensure_ascii=True, sort_keys=True)
            previous = hashlib.sha256(encoded.encode()).hexdigest()
            protocol.write(encoded + "\n")
            protocol.flush()
            if leaked_threads:
                owner_exit(73)


if __name__ == "__main__":
    main()
