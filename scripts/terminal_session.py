"""Owned POSIX PTY / Windows ConPTY driver for installed-product verification.

ConPTY uses pywinpty's native PTY API directly: no reader thread or intermediate
socket is needed. Cleanup retains creation-time-bound process objects, including
observed descendants, and releases the terminal only after confirmed exit.
"""

from __future__ import annotations

import importlib
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil


class TerminalSession:
    def __init__(
        self,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        rows: int = 45,
        cols: int = 160,
    ):
        if rows <= 0 or cols <= 0:
            raise ValueError("terminal dimensions must be positive")
        self._pty: Any = None
        self._process: subprocess.Popen[bytes] | None = None
        self._master = -1
        self._owners: dict[tuple[int, float], psutil.Process] = {}
        self._root: psutil.Process | None = None
        self._closed = False
        try:
            if os.name == "nt":
                winpty = importlib.import_module("winpty")
                self._pty = winpty.PTY(cols, rows, backend=winpty.Backend.ConPTY)
                spawned = self._pty.spawn(
                    argv[0],
                    cmdline=" " + subprocess.list2cmdline(argv[1:]),
                    cwd=str(cwd),
                    env="\0".join(f"{k}={v}" for k, v in env.items()) + "\0",
                )
                if not spawned:
                    raise RuntimeError("ConPTY failed to spawn the terminal")
                pid = self._pty.pid
            else:
                import pty

                self._master, slave = pty.openpty()
                try:
                    self.resize(rows, cols)
                    helper = "import os,sys; os.login_tty(int(sys.argv[1])); os.execvpe(sys.argv[2],sys.argv[2:],os.environ)"
                    self._process = subprocess.Popen(
                        [sys.executable, "-c", helper, str(slave), *argv],
                        cwd=cwd,
                        env=env,
                        pass_fds=(slave,),
                    )
                finally:
                    os.close(slave)
                pid = self._process.pid
            try:
                self._root = psutil.Process(pid)
                self._owners[(pid, self._root.create_time())] = self._root
            except psutil.NoSuchProcess:
                pass  # A failed executable may already have exited.
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> TerminalSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _observe_children(self) -> None:
        if self._root is None:
            return
        try:
            for child in self._root.children(recursive=True):
                self._owners[(child.pid, child.create_time())] = child
        except (ProcessLookupError, psutil.NoSuchProcess):
            pass

    def poll(self) -> int | None:
        if self._pty is not None:
            return None if self._pty.isalive() else self._pty.get_exitstatus()
        return self._process.poll() if self._process else None

    def write(self, data: bytes) -> None:
        if self._closed:
            raise RuntimeError("terminal is closed")
        if self._pty is not None:
            self._pty.write(data.decode("utf-8"))
        else:
            os.write(self._master, data)

    def resize(self, rows: int, cols: int) -> None:
        if rows <= 0 or cols <= 0:
            raise ValueError("terminal dimensions must be positive")
        if self._pty is not None:
            self._pty.set_size(cols, rows)
        else:
            import fcntl
            import struct
            import termios

            fcntl.ioctl(
                self._master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0)
            )

    def read(self, timeout: float = 0.05) -> bytes:
        self._observe_children()
        if self._pty is not None:
            try:
                text = self._pty.read(65536, blocking=False)
            except Exception:
                if self.poll() is not None:
                    return b""
                raise
            if not text:
                time.sleep(timeout)
            return text.encode("utf-8")
        if self._master < 0 or not select.select([self._master], [], [], timeout)[0]:
            return b""
        try:
            return os.read(self._master, 65536)
        except OSError as exc:
            import errno

            if exc.errno != errno.EIO:
                raise
            return b""  # POSIX slave closed.

    def wait(self, timeout: float = 15) -> int:
        deadline = time.monotonic() + timeout
        while self.poll() is None:
            if time.monotonic() >= deadline:
                raise TimeoutError("terminal did not exit before deadline")
            self.read()
        return int(self.poll() or 0)

    def close(self) -> None:
        if self._closed:
            return
        self._observe_children()
        # psutil.Process.kill verifies creation time before signalling, including
        # descendants that survived their parent. No global process-name sweep.
        for process in reversed(list(self._owners.values())):
            try:
                if process.is_running():
                    process.kill()
            except psutil.NoSuchProcess:
                pass
        if self._process is not None and self._process.poll() is None:
            # Covers failure before psutil captured the child; Popen owns its handle.
            self._process.kill()
        deadline = time.monotonic() + 5

        def alive(process: psutil.Process) -> bool:
            try:
                return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                return False

        while any(alive(p) for p in self._owners.values()):
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "terminal cleanup pending; process ownership retained"
                )
            self.read()
        if self._process is not None:
            self._process.wait(timeout=5)
        if self._master >= 0:
            os.close(self._master)
            self._master = -1
        self._pty = None  # Native owner releases ConPTY handles after process exit.
        self._owners.clear()
        self._closed = True
