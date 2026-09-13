"""Shared shell policy and owned cancellation, without external providers."""
import asyncio
import os
import shlex
import sys

import pytest

from superforecasting_agent.runtime import quick_commands as commands


@pytest.mark.skipif(os.name == "nt", reason="POSIX fixture shell")
@pytest.mark.asyncio
async def test_output_exit_status_and_environment_are_shared(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-private-value")
    result = await commands.execute(
        "printf stdout; printf stderr >&2; printf '%s' \"$OPENROUTER_API_KEY\"; exit 7"
    )
    assert result.output == "stdout\nstderr"
    assert result.error == "Quick command failed with exit code 7.\nstdout\nstderr"
    assert (await commands.execute("true")).message == "Command returned no output."


@pytest.mark.skipif(os.name == "nt", reason="POSIX fixture shell")
@pytest.mark.asyncio
async def test_invalid_utf8_and_redaction(monkeypatch):
    monkeypatch.setattr("agent.redact._REDACT_ENABLED", True)
    code = "import os; os.write(1, b'\\xff sk-ant-api03-supersecretkey1234567890')"
    result = await commands.execute(f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}")
    assert not result.error
    assert "\ufffd" in result.output
    assert "supersecretkey1234567890" not in result.output


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group fixture")
@pytest.mark.asyncio
async def test_timeout_reaps_real_shell(monkeypatch):
    original = asyncio.create_subprocess_shell
    children = []

    async def spawn(*args, **kwargs):
        proc = await original(*args, **kwargs)
        children.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_shell", spawn)
    result = await commands.execute("sleep 100", timeout=0.05)
    assert "timed out" in result.error
    assert len(children) == 1
    assert children[0].returncode is not None
    assert children[0].stdout.at_eof()
    assert children[0].stderr.at_eof()


@pytest.mark.asyncio
async def test_repeated_cancellation_during_startup_waits_for_owned_cleanup(monkeypatch):
    started, release, reading, drained = (asyncio.Event() for _ in range(4))

    class Process:
        pid = 123
        returncode = None

        async def communicate(self):
            reading.set()
            await drained.wait()
            self.returncode = -9
            return b"", b""

    proc = Process()
    killed = []

    async def spawn(*args, **kwargs):
        started.set()
        await release.wait()
        return proc

    def kill(owned):
        assert owned is proc
        killed.append(owned)

    monkeypatch.setattr(asyncio, "create_subprocess_shell", spawn)
    monkeypatch.setattr("superforecasting_agent.hosting.commands._kill_tree", kill)
    task = asyncio.create_task(commands.execute("fixture"))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    assert not task.done()
    release.set()
    await reading.wait()
    # Allow cancellation to reach communicate, then cancel the outer waiter again.
    for _ in range(10):
        if killed:
            break
        await asyncio.sleep(0)
    assert killed == [proc]
    task.cancel()
    drained.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert proc.returncode == -9


@pytest.mark.asyncio
async def test_invalid_timeout_and_spawn_failure(monkeypatch):
    for timeout in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="positive"):
            await commands.execute("fixture", timeout=timeout)

    async def fail(*args, **kwargs):
        raise OSError("fixture unavailable")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", fail)
    result = await commands.execute("fixture")
    assert result.error == "Quick command error: fixture unavailable"
