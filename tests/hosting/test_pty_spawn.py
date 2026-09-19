"""POSIX spawn admission, controlling-terminal ownership and failure cleanup."""

from __future__ import annotations

import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor

import pytest

if sys.platform == "win32":
    pytest.skip("POSIX terminal hosting", allow_module_level=True)

from superforecasting_agent.hosting import pty_spawn
from superforecasting_agent.runtime.pty_bridge import PtyBridge


def read_until(bridge, needle):
    import time

    output = bytearray()
    deadline = time.monotonic() + 5
    while needle not in output and time.monotonic() < deadline:
        chunk = bridge.read(0.1)
        if chunk is None:
            break
        output.extend(chunk)
    assert needle in output, output


def test_threaded_spawn_has_controlling_terminal_without_python_fork(monkeypatch):
    import ptyprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("Python fork-based PTY path must not run")

    monkeypatch.setattr(ptyprocess.PtyProcess, "spawn", forbidden)
    monkeypatch.setattr(os, "forkpty", forbidden)
    script = "import os; print('OWNED', os.tcgetpgrp(0) == os.getpgrp(), flush=True)"

    def run_one(_):
        bridge = PtyBridge.spawn([sys.executable, "-c", script])
        try:
            read_until(bridge, b"OWNED True")
        finally:
            bridge.close()

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run_one, range(8)))



def test_spawn_without_optional_native_setsid_extension(monkeypatch):
    original = os.posix_spawn

    def without_setsid(path, argv, env, **kwargs):
        if kwargs.get("setsid"):
            raise NotImplementedError("setsid is not supported on this platform")
        return original(path, argv, env, **kwargs)

    monkeypatch.setattr(os, "posix_spawn", without_setsid)
    script = (
        "import os; print('SESSION', "
        "os.getsid(0) == os.getpid() == os.getpgrp() == os.tcgetpgrp(0), flush=True)"
    )
    bridge = PtyBridge.spawn([sys.executable, "-c", script])
    try:
        read_until(bridge, b"SESSION True")
    finally:
        bridge.close()


def test_unrelated_inheritable_descriptor_does_not_reach_target(tmp_path):
    path = tmp_path / "private-owner"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.set_inheritable(fd, True)
    script = (
        "import os,sys\n"
        "try: os.fstat(int(sys.argv[1]))\n"
        "except OSError: print('CLOSED', flush=True)\n"
        "else: print('LEAKED', flush=True)\n"
    )
    try:
        bridge = PtyBridge.spawn([sys.executable, "-c", script, str(fd)])
        try:
            read_until(bridge, b"CLOSED")
            os.fstat(fd)  # The parent component still owns its descriptor.
        finally:
            bridge.close()
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "failure", ["missing-executable", "bad-cwd", "spawn", "timeout", "helper-exit"]
)
def test_failed_spawn_closes_allocations_and_reaps_child(
    monkeypatch, tmp_path, failure
):
    descriptors = []
    children = []
    original_openpty, original_pipe, original_spawn = (
        os.openpty,
        os.pipe,
        os.posix_spawn,
    )

    def openpty():
        pair = original_openpty()
        descriptors.extend(pair)
        return pair

    def pipe():
        pair = original_pipe()
        descriptors.extend(pair)
        return pair

    def spawn(path, argv, env, **kwargs):
        if failure == "spawn":
            raise OSError("injected native spawn failure")
        if failure in {"timeout", "helper-exit"}:
            argv = [
                sys.executable,
                "-c",
                "import time; time.sleep(30)" if failure == "timeout" else "pass",
            ]
        pid = original_spawn(path, argv, env, **kwargs)
        children.append(pid)
        return pid

    monkeypatch.setattr(os, "openpty", openpty)
    monkeypatch.setattr(os, "pipe", pipe)
    monkeypatch.setattr(os, "posix_spawn", spawn)
    monkeypatch.setattr(pty_spawn, "SPAWN_TIMEOUT", 0.1 if failure == "timeout" else 5)
    command = (
        [str(tmp_path / "missing")]
        if failure == "missing-executable"
        else [sys.executable, "-c", "pass"]
    )
    cwd = str(tmp_path / "bad-cwd") if failure == "bad-cwd" else None
    with pytest.raises(OSError):
        pty_spawn.spawn_pty(command, cwd=cwd, env=os.environ, rows=24, cols=80)
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    for pid in children:
        with pytest.raises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)


def test_spawn_handles_closed_standard_descriptors():
    import subprocess
    from pathlib import Path

    script = """
import os, sys
from superforecasting_agent.runtime.pty_bridge import PtyBridge
for fd in (0, 1, 2):
    os.close(fd)
bridge = PtyBridge.spawn([sys.executable, '-c', "print('READY', flush=True)"])
try:
    output = bytearray()
    for _ in range(50):
        chunk = bridge.read(0.1)
        if chunk is None:
            break
        output.extend(chunk)
        if b'READY' in output:
            break
    assert b'READY' in output
finally:
    bridge.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        timeout=10,
    )
    assert result.returncode == 0


def test_unsupported_native_spawn_fails_closed_with_platform_diagnostic(monkeypatch):
    from superforecasting_agent.runtime import pty_bridge

    def unsupported(*args, **kwargs):
        raise NotImplementedError("setsid unsupported")

    monkeypatch.setattr(pty_bridge, "spawn_pty", unsupported)
    with pytest.raises(pty_bridge.PtyUnavailableError, match="Safe POSIX"):
        PtyBridge.spawn([sys.executable, "-c", "pass"])


def test_ignored_parent_signals_do_not_disable_terminal_interrupts():
    import signal

    original = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    script = (
        "try:\n"
        "    print('READY', flush=True)\n"
        "    input()\n"
        "except KeyboardInterrupt: print('INTERRUPTED', flush=True)\n"
    )
    bridge = None
    try:
        bridge = PtyBridge.spawn([sys.executable, "-c", script])
        read_until(bridge, b"READY")
        bridge.write(b"\x03")
        read_until(bridge, b"INTERRUPTED")
        assert signal.getsignal(signal.SIGINT) == signal.SIG_IGN
    finally:
        if bridge is not None:
            bridge.close()
        signal.signal(signal.SIGINT, original)
