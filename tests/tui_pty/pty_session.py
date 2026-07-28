"""Drive a child process behind a real pseudo-terminal.

Design notes that are load-bearing (each one was measured, not assumed):

* **The child MUST own the pty as its controlling terminal.**  Inheriting the
  slave fd as stdin/stdout/stderr is enough to satisfy ``isTTY``, but the
  kernel delivers ``SIGWINCH`` only to the *foreground process group of the
  controlling terminal*.  Without ``login_tty`` a ``TIOCSWINSZ`` on the master
  is silently ignored by the child — verified: the TUI sat at its 80-column
  layout for 20s after a resize to 120.  Since the resize branch is the whole
  point of this harness, ``login_tty`` is mandatory.

* **...but not via ``preexec_fn``.**  ``preexec_fn`` runs Python bytecode in a
  forked child of a process that, under ``pytest-xdist``, has live threads —
  the classic fork-with-threads deadlock exposure.  Instead we exec a
  four-line Python helper that calls :func:`os.login_tty` and immediately
  ``execvpe``s the real target.  The helper is a fresh single-threaded
  interpreter, so there is no fork-safety question at all; the cost is one
  extra interpreter start that then replaces itself.

* **Output must be drained continuously.**  A pty has a small kernel buffer;
  the TUI paints ~30KB during boot.  Stop reading and the child blocks in
  ``write()`` and never reaches the state you are waiting for.  Every wait
  helper here reads while it waits.
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from collections.abc import Callable, Mapping, Sequence

from .vt import VTScreen

__all__ = ["PtySession", "PtyTimeout"]

# Runs as a brand-new interpreter (see module docstring), so it may safely do
# whatever it likes before handing the process over to the real target.
_LOGIN_TTY_HELPER = (
    "import os,sys\n"
    "os.login_tty(int(sys.argv[1]))\n"
    "os.execvpe(sys.argv[2],sys.argv[2:],os.environ)\n"
)


class PtyTimeout(AssertionError):
    """A wait_for/wait_exit deadline elapsed.  Carries screen diagnostics."""


class PtySession:
    """A child process on a pty, plus a live reconstruction of its screen."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str],
        rows: int = 30,
        cols: int = 80,
    ) -> None:
        self.argv = list(argv)
        self.cwd = cwd
        self.env = dict(env)
        self.rows = rows
        self.cols = cols
        self.screen = VTScreen(rows=rows, cols=cols)
        self.raw = bytearray()
        self.started_at = 0.0
        self._master = -1
        self._proc: subprocess.Popen | None = None
        self._pgid = -1
        self._group_confirmed = False
        self._eof = False

    # ── lifecycle ─────────────────────────────────────────────────────────

    def __enter__(self) -> PtySession:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def start(self) -> PtySession:
        master, slave = pty.openpty()
        self._master = master
        _set_winsize(master, self.rows, self.cols)
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-c", _LOGIN_TTY_HELPER, str(slave), *self.argv],
                cwd=self.cwd,
                env=self.env,
                pass_fds=(slave,),
                close_fds=True,
            )
        finally:
            os.close(slave)
        # login_tty made the child a session leader, so its PGID equals its PID
        # and the group contains its whole descendant tree -- crucially the
        # Python gateway it spawns. Captured now because os.getpgid() stops
        # working the moment the child is reaped, and the orphans are exactly
        # what we still need to reach at that point.
        self._pgid = self._proc.pid
        self.started_at = time.monotonic()
        return self

    def _confirm_group(self) -> None:
        """Latch, once, that the child really is its own process-group leader.

        SAFETY GATE, not bookkeeping.  ``_pgid`` is recorded at spawn time, but
        the child only becomes a group leader a moment later, inside
        ``login_tty``.  In that window ``getpgid(child) ==`` *our own* group --
        so a ``killpg`` issued then would SIGKILL the pytest process itself.
        We therefore never sweep until we have observed ``getpgid(pid) == pid``,
        which is what makes the group unambiguously the child's and nobody
        else's.  Cheap: it short-circuits forever after the first success.
        """
        if self._group_confirmed or self._pgid <= 0:
            return
        try:
            self._group_confirmed = os.getpgid(self._pgid) == self._pgid
        except (OSError, ProcessLookupError):
            pass

    def _sweep_group(self) -> None:
        """SIGKILL the child's process group, orphans included.

        A clean TUI exit is NOT sufficient teardown: the TUI signals its
        gateway and calls ``process.exit(0)`` without waiting, so the gateway
        can be reparented to init and outlive the process that spawned it
        (observed: a ``python -m tui_gateway.entry`` still running with PPID 1
        long after node exited 0). Sweeping the group is what keeps a test run
        from leaving stray gateways behind.
        """
        self._confirm_group()
        if self._pgid <= 0 or not self._group_confirmed:
            return
        try:
            os.killpg(self._pgid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass  # already gone, or nothing left in the group

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            if proc.poll() is None:
                self._sweep_group()
                if not self._group_confirmed:
                    # Spawned but not yet a group leader (or already reparented
                    # oddly): kill just this PID -- never a group we cannot
                    # prove is the child's.
                    try:
                        proc.kill()
                    except OSError:
                        pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                proc.kill()
                proc.wait(timeout=5)
        # Second sweep: the leader may have exited cleanly on its own, leaving
        # descendants behind for the first branch to never look at.
        self._sweep_group()
        self._pgid = -1
        if self._master >= 0:
            try:
                os.close(self._master)
            finally:
                self._master = -1

    @property
    def returncode(self) -> int | None:
        return None if self._proc is None else self._proc.poll()

    @property
    def pgid(self) -> int:
        """The child's process group -- it and every process it spawned."""
        return self._pgid

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    # ── input ─────────────────────────────────────────────────────────────

    def send(self, data: bytes) -> None:
        """Write raw bytes to the terminal, as a keyboard would."""
        os.write(self._master, data)

    def resize(self, rows: int, cols: int) -> None:
        """Resize the terminal.  The kernel raises SIGWINCH in the child."""
        self.rows, self.cols = rows, cols
        self.screen.resize(rows, cols)
        _set_winsize(self._master, rows, cols)

    # ── output ────────────────────────────────────────────────────────────

    def _read_once(self, timeout: float = 0.05) -> bytes:
        """One non-blocking-ish drain of the master fd.  b"" when idle/EOF."""
        if self._eof or self._master < 0:
            return b""
        # Every wait path funnels through here, so this is where the teardown
        # safety gate gets latched -- long before anything can want to sweep.
        self._confirm_group()
        try:
            ready, _, _ = select.select([self._master], [], [], timeout)
        except OSError:  # pragma: no cover - fd yanked mid-select
            self._eof = True
            return b""
        if not ready:
            return b""
        try:
            chunk = os.read(self._master, 65536)
        except OSError as exc:
            # Linux signals "the slave side is gone" with EIO; macOS may also
            # return an empty read.  Both mean the child is done writing.
            if exc.errno not in (errno.EIO, errno.EBADF):
                raise
            self._eof = True
            return b""
        if not chunk:
            self._eof = True
            return b""
        self.raw.extend(chunk)
        self.screen.feed(chunk)
        return chunk

    def pump(self, seconds: float) -> None:
        """Drain output for a fixed span (only where polling is meaningless)."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._read_once()

    def wait_for(
        self,
        predicate: Callable[[VTScreen], bool],
        *,
        timeout: float,
        what: str,
    ) -> float:
        """Poll (never sleep) until ``predicate(screen)`` holds.

        Returns seconds elapsed since :meth:`start` at the moment it first
        became true, so callers can report a real latency instead of a bound.
        """
        deadline = time.monotonic() + timeout
        while True:
            if predicate(self.screen):
                return self.elapsed
            if time.monotonic() >= deadline:
                raise PtyTimeout(
                    f"timed out after {timeout:.1f}s waiting for {what}\n"
                    + self.diagnostics()
                )
            if self._read_once() == b"" and self._eof and self.returncode is not None:
                # Child gone and stream drained: one last check, then give up
                # rather than spin until the deadline.
                if predicate(self.screen):
                    return self.elapsed
                raise PtyTimeout(
                    f"child exited (rc={self.returncode}) before {what}\n"
                    + self.diagnostics()
                )

    def settle(self, *, quiet: float = 0.35, max_wait: float = 4.0) -> None:
        """Best-effort: drain until the child has been silent for *quiet*.

        Used before NEGATIVE assertions ("the rail is absent at 80 columns"),
        which are vacuous against a half-painted frame.  Deliberately
        best-effort — it returns after *max_wait* even if the app keeps
        repainting (a live ticker must not turn into a test failure).
        """
        deadline = time.monotonic() + max_wait
        last_output = time.monotonic()
        while time.monotonic() < deadline:
            if self._read_once():
                last_output = time.monotonic()
            elif time.monotonic() - last_output >= quiet:
                return

    def wait_exit(self, *, timeout: float, sweep: bool = True) -> int:
        """Wait for the child to exit, draining output throughout.

        ``sweep=False`` leaves the process group ALONE on the way out.  That is
        for the one test that asserts on the application's own teardown: if the
        harness kills the group before looking, it measures its own hygiene
        rather than whether the app reaped its gateway.  Callers that pass it
        are responsible for the group surviving until :meth:`close`, which
        sweeps unconditionally.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rc = self.returncode
            if rc is not None:
                self.pump(0.2)  # collect the final teardown escape sequences
                if sweep:
                    # Sweep immediately rather than at close(): `returncode`
                    # just reaped the leader, and killing the group while its
                    # PID is still fresh keeps the (already negligible)
                    # PID-reuse window down to microseconds.
                    self._sweep_group()
                return rc
            self._read_once()
        raise PtyTimeout(
            f"child still running after {timeout:.1f}s\n" + self.diagnostics()
        )

    # ── diagnostics ───────────────────────────────────────────────────────

    def diagnostics(self) -> str:
        """A failure report: the screen a human would have seen, plus tail bytes."""
        border = "─" * min(self.cols, 100)
        return (
            f"\n--- screen {self.cols}x{self.rows} at t+{self.elapsed:.2f}s "
            f"(rc={self.returncode}) ---\n{border}\n"
            f"{self.screen.text()}\n{border}\n"
            f"--- last 600 raw bytes ---\n{bytes(self.raw[-600:])!r}\n"
        )


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
