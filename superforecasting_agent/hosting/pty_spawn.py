"""Spawn a controlling terminal without executing Python after a threaded fork."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import select
import signal
import struct
import sys
import termios
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

SPAWN_TIMEOUT = 10.0


def _above_stdio(fd: int) -> int:
    if fd >= 4:
        return fd
    moved = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 4)
    os.close(fd)
    return moved


def spawn_pty(
    argv: Sequence[str],
    *,
    cwd: str | None,
    env: Mapping[str, str],
    rows: int,
    cols: int,
) -> tuple[int, int]:
    """Return the unreaped child PID and owned master fd after confirmed exec.

    The caller becomes the sole waitpid/fd owner. On admission/setup failure this
    function reaps the child and releases every allocation before raising.
    """
    if not argv or not argv[0]:
        raise ValueError("PTY command must contain an executable")
    master, slave = os.openpty()
    read_error = write_error = None
    pid = None
    try:
        master = _above_stdio(master)
        slave = _above_stdio(slave)
        fcntl.ioctl(
            slave,
            termios.TIOCSWINSZ,
            struct.pack(
                "HHHH", min(65535, max(1, rows)), min(65535, max(1, cols)), 0, 0
            ),
        )
        read_error, write_error = os.pipe()
        read_error = _above_stdio(read_error)
        write_error = _above_stdio(write_error)
        actions: list[tuple[int, int] | tuple[int, int, int]] = [
            (os.POSIX_SPAWN_DUP2, slave, 0),
            (os.POSIX_SPAWN_DUP2, slave, 1),
            (os.POSIX_SPAWN_DUP2, slave, 2),
            (os.POSIX_SPAWN_DUP2, write_error, 3),
        ]
        actions.extend(
            (os.POSIX_SPAWN_CLOSE, fd)
            for fd in (master, slave, read_error, write_error)
            if fd > 3
        )
        helper = str(Path(__file__).with_name("pty_exec.py"))
        pid = os.posix_spawn(
            sys.executable,
            [sys.executable, "-I", helper, cwd or "", *argv],
            dict(env),
            file_actions=actions,
            setsigmask=(),
            # Ignored dispositions survive exec. A dashboard started by a daemon
            # must not disable Ctrl+C, hangup or job control in its terminal child.
            setsigdef=(
                signal.SIGHUP,
                signal.SIGINT,
                signal.SIGQUIT,
                signal.SIGTERM,
                signal.SIGTSTP,
                signal.SIGTTIN,
                signal.SIGTTOU,
                signal.SIGWINCH,
            ),
        )
        os.close(write_error)
        write_error = None
        deadline = time.monotonic() + SPAWN_TIMEOUT
        payload = bytearray()
        while True:
            readable, _, _ = select.select(
                [read_error], [], [], max(0, deadline - time.monotonic())
            )
            if not readable:
                raise TimeoutError("PTY child did not confirm executable startup")
            chunk = os.read(read_error, 4096)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > 4096:
                raise OSError(errno.EIO, "PTY child startup response exceeded limit")
        if payload != b"ready\n":
            error = payload.removeprefix(b"ready\n")
            if not error:
                raise OSError(errno.EIO, "PTY helper exited before executable startup")
            try:
                details = json.loads(error)
                code = int(details["errno"])
                filename = details["filename"]
            except (ValueError, TypeError, KeyError) as exc:
                raise OSError(errno.EIO, "Invalid PTY child startup response") from exc
            raise OSError(code, os.strerror(code), filename)
        result = pid, master
        pid = None
        master = -1
        return result
    except BaseException:
        if pid is not None:
            # This direct child has not been reaped, so its PID cannot be reused.
            try:
                os.kill(
                    pid, signal.SIGKILL
                )  # windows-footgun: ok — POSIX-only terminal owner
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
        raise
    finally:
        for fd in (master, slave, read_error, write_error):
            if fd is not None and fd >= 0:
                os.close(fd)
