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
import sys
import threading
import traceback
from typing import Any

MAX_REQUEST_BYTES = 1_048_576
MAX_OUTPUT_CHARS = 250_000


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
                os._exit(0)
            if len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
                os._exit(65)
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
                os._exit(65)
            rpc = request.get("rpc")
            if rpc is not None and (
                not isinstance(rpc, dict)
                or set(rpc) != {"endpoint", "token"}
                or not all(isinstance(value, str) and value for value in rpc.values())
            ):
                os._exit(65)
            inbox.put_nowait(request)
    except (ValueError, OSError, queue.Full):
        os._exit(65)


def main() -> None:
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
                os._exit(73)


if __name__ == "__main__":
    main()
