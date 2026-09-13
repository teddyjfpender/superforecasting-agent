"""Real terminal ownership checks; runs through ConPTY on native Windows."""

import os
import sys
import time

import pytest

from scripts.terminal_session import TerminalSession


def expect(terminal, marker):
    output = bytearray()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        output.extend(terminal.read())
        if marker in output:
            return
    pytest.fail(f"missing {marker!r}: {output!r}")


def test_terminal_input_resize_cancellation_and_restart(tmp_path):
    child = tmp_path / "child.py"
    child.write_text(r"""import os, sys
from pathlib import Path
if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.windll.kernel32
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    if not kernel.SetConsoleMode(kernel.GetStdHandle(-10), 0):
        raise ctypes.WinError()
    read = msvcrt.getwch
else:
    import tty
    tty.setraw(sys.stdin.fileno())
    read = lambda: sys.stdin.read(1)
p = Path("durable.txt")
print("RESUMED" if p.exists() else "READY", flush=True)
command = ""
while True:
    char = read()
    if char == "\x03":
        print("CANCELLED", flush=True)
        command = ""
        continue
    if char not in "\r\n":
        command += char
        continue
    if command == "size":
        print("SIZE=" + str(os.get_terminal_size().columns), flush=True)
    elif command == "save":
        p.write_text("saved")
        print("SAVED", flush=True)
    elif command == "quit":
        break
    command = ""
""")
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    with TerminalSession(
        [sys.executable, str(child)], cwd=tmp_path, env=env
    ) as terminal:
        expect(terminal, b"READY")
        terminal.resize(30, 100)
        terminal.write(b"size\r")
        expect(terminal, b"SIZE=100")
        terminal.write(b"\x03")
        expect(terminal, b"CANCELLED")
        terminal.write(b"save\r")
        expect(terminal, b"SAVED")
    terminal.close()  # Retry must not touch a replacement's resources.
    with TerminalSession(
        [sys.executable, str(child)], cwd=tmp_path, env=env
    ) as replacement:
        expect(replacement, b"RESUMED")
        terminal.close()
        replacement.write(b"quit\r")
        assert replacement.wait() == 0


def test_invalid_dimensions_do_not_allocate(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        TerminalSession([sys.executable], cwd=tmp_path, env=dict(os.environ), rows=0)
