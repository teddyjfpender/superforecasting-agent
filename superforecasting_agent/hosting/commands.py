"""Configured operator shell commands shared by CLI, Ink and messaging.

Only trusted configuration supplies shell source. Invocation arguments are not
interpolated into it. The adapters own rendering; this module owns execution.
"""

from __future__ import annotations

import asyncio
import math
import os
import signal
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass

TIMEOUT_SECONDS = 30
OUTPUT_LIMIT = 4000


@dataclass(frozen=True)
class CommandResult:
    output: str = ""
    error: str | None = None

    @property
    def message(self) -> str:
        return self.error or self.output or "Command returned no output."


def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode and proc.returncode is None:
            raise OSError((result.stderr or result.stdout).strip())
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # windows-footgun: ok — POSIX branch
        except ProcessLookupError:
            pass


async def _finish_cleanup(task: asyncio.Task) -> None:
    # Repeated cancellation must not abandon the pipe readers or child waiter.
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    task.result()


async def execute(
    command: str,
    *,
    environment: Mapping[str, str],
    redact: Callable[[str], str],
    timeout: float = TIMEOUT_SECONDS,
) -> CommandResult:

    if not isinstance(command, str) or not command.strip():
        return CommandResult(error="Quick command has no command defined.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Quick command timeout must be positive.")

    admitted = asyncio.Event()

    async def run() -> CommandResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                start_new_session=os.name != "nt",
            )
        finally:
            admitted.set()
        communicate = asyncio.create_task(proc.communicate())
        try:
            stdout, stderr = await asyncio.wait_for(
                asyncio.shield(communicate), timeout=timeout
            )
        except BaseException:
            _kill_tree(proc)
            await _finish_cleanup(communicate)
            raise
        output = "\n".join(
            part.decode("utf-8", errors="replace").strip()
            for part in (stdout, stderr)
            if part
        ).strip()
        output = redact(output)[:OUTPUT_LIMIT]
        if proc.returncode:
            error = f"Quick command failed with exit code {proc.returncode}."
            return CommandResult(
                output=output, error=error + ("\n" + output if output else "")
            )
        return CommandResult(output=output)

    # Shield startup too: cancellation during process creation otherwise loses
    # the handle before the caller can arrange cleanup.
    task = asyncio.create_task(run())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Do not cancel process creation before run() receives its handle.
        await _finish_cleanup(asyncio.create_task(admitted.wait()))
        task.cancel()
        await _finish_cleanup(task)
        raise
    except asyncio.TimeoutError:
        return CommandResult(error=f"Quick command timed out ({timeout:g}s).")
    except Exception as exc:
        return CommandResult(error=f"Quick command error: {redact(str(exc))}")
