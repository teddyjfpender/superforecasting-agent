"""Kill the gateway out from under the TUI and watch it recover.

WHY THIS NEEDS A REAL TERMINAL
------------------------------
The respawn ladder is a recovery path, and recovery paths rot silently: nothing
exercises them in normal use, so a regression surfaces months later on the one
day it was needed.  It also cannot be proved in-process.  The gateway is a
child process of the *node* client, so "did the client notice its child die,
tell the user, and start a new one?" is only observable by owning the terminal
and the process tree at the same time -- which is exactly what this harness is.

WHAT IS ASSERTED
----------------
Three things, in the order they become observable after a SIGKILL:

1. the UI *tells the operator* -- a reconnect notice with an attempt counter,
   rather than a silently dead desk;
2. a NEW gateway process appears (a different PID -- the structural proof, and
   the one that cannot be faked by a leftover status string);
3. the client is still alive and painting afterwards.

Measured on the way in: notice on screen +0.05s after the kill, replacement
process +0.53s.  The polling below samples every ~50ms and the notice persisted
across the whole interval, so the margin is ~10x -- but note the notice IS
transient (it is gone once reconnection completes), which is why it is waited
for BEFORE the new process rather than after.

A note on why the assertion reads the reconstructed screen and not the raw
bytes: in the capture that motivated this test, the raw stream contained
``reconnecting`` but NOT ``gateway lost`` -- Ink split the phrase across cursor
moves.  On the emulated screen both are present.  Same lesson as ``vt.py``.
"""

from __future__ import annotations

import os
import re
import signal
import time
from pathlib import Path

import pytest

from .conftest import FIRST_PAINT_BUDGET_S, REPO_ROOT
from .pty_session import PtySession
from .vt import VTScreen

GATEWAY_CMDLINE_MARKER = "tui_gateway.entry"

# Generous: the ladder's first rung is ~1s and the client re-spawns a Python
# process that takes ~0.6s to import. These are liveness bounds, not budgets.
NOTICE_TIMEOUT_S = 30.0
RESPAWN_TIMEOUT_S = 60.0

# "reconnecting 1/5 in 1s" -- assert the WORD plus the presence of an attempt
# counter, not the exact ladder depth. Whether the client retries 5 times or 8
# is a tuning decision; that it tells the operator which attempt it is on is
# the contract.
RECONNECT_WORD = "reconnect"
ATTEMPT_COUNTER = re.compile(r"\b\d+\s*/\s*\d+\b")


def gateway_processes(psutil, pgid: int) -> list:
    """Live ``python -m tui_gateway.entry`` processes under the TUI's group."""
    found = []
    try:
        children = psutil.Process(pgid).children(recursive=True)
    except Exception:  # pragma: no cover - leader gone
        return found
    for proc in children:
        try:
            if GATEWAY_CMDLINE_MARKER in " ".join(proc.cmdline()):
                found.append(proc)
        except Exception:
            continue  # exited mid-scan
    return found


def shows_reconnect_notice(screen: VTScreen) -> bool:
    text = screen.text().lower()
    return RECONNECT_WORD in text and bool(ATTEMPT_COUNTER.search(screen.text()))


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(300)
def test_gateway_is_respawned_after_being_killed(
    tui_bundle: Path, tui_env: dict, record_property
):
    """SIGKILL the gateway; the client must notice, say so, and start a new one."""
    psutil = pytest.importorskip("psutil")

    session = PtySession(
        ["node", str(tui_bundle)],
        cwd=str(REPO_ROOT),
        env=tui_env,
        # Wide enough that the status line is not truncated before the notice
        # reaches it.
        rows=44,
        cols=120,
    )
    with session:
        session.wait_for(
            lambda s: "Setup Required" in s.text(),
            timeout=FIRST_PAINT_BUDGET_S,
            what="first paint before killing the gateway",
        )
        session.settle()

        original = gateway_processes(psutil, session.pgid)
        assert original, (
            "no gateway process to kill -- this test would prove nothing. "
            "Expected a child matching " + GATEWAY_CMDLINE_MARKER + session.diagnostics()
        )
        original_pids = {p.pid for p in original}

        killed_at = time.monotonic()
        for proc in original:
            os.kill(proc.pid, signal.SIGKILL)

        # 1. The operator is told. Waited for FIRST because the notice clears
        #    once reconnection succeeds.
        session.wait_for(
            shows_reconnect_notice,
            timeout=NOTICE_TIMEOUT_S,
            what="a reconnect notice with an attempt counter (e.g. "
            "'gateway lost · reconnecting 1/5 in 1s')",
        )
        notice_delay = time.monotonic() - killed_at

        # 2. A genuinely new process exists -- not the corpse of the old one.
        def replacement_exists(_screen: VTScreen) -> bool:
            live = gateway_processes(psutil, session.pgid)
            return any(p.pid not in original_pids for p in live)

        session.wait_for(
            replacement_exists,
            timeout=RESPAWN_TIMEOUT_S,
            what=f"a replacement gateway process (original pids {sorted(original_pids)})",
        )
        respawn_delay = time.monotonic() - killed_at

        record_property("reconnect_notice_seconds", round(notice_delay, 3))
        record_property("gateway_respawn_seconds", round(respawn_delay, 3))
        print(
            f"\n[tui-pty] gateway killed -> notice at +{notice_delay:.2f}s, "
            f"replacement process at +{respawn_delay:.2f}s"
        )

        # 3. Every original process really is dead, and the client survived.
        _, still_alive = psutil.wait_procs(original, timeout=10)
        assert not still_alive, (
            "the 'replacement' check passed while an original gateway is still "
            f"running: {[p.pid for p in still_alive]}"
        )
        assert session.returncode is None, (
            "the TUI exited instead of recovering from a dead gateway"
            + session.diagnostics()
        )
        session.settle()
        assert "Superforecasting Agent" in session.screen.text(), (
            "the TUI is alive but no longer painting after the respawn"
            + session.diagnostics()
        )


# Pre-fix, an orphaned gateway survived indefinitely (observed alive with PPID 1
# at 13s). Any bound at all therefore separates "cleaned up" from "orphaned";
# this one is generous so a slow box cannot manufacture a failure.
ORPHAN_GRACE_S = 20.0


def live_orphans(psutil, processes):
    """A zombie has exited; only its new parent can reap the process entry."""
    live = []
    for process in processes:
        try:
            if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                live.append(process)
        except psutil.NoSuchProcess:
            pass
    return live


def test_orphan_check_distinguishes_exited_zombies_from_running_workers():
    from types import SimpleNamespace

    psutil = pytest.importorskip("psutil")
    zombie = SimpleNamespace(is_running=lambda: True, status=lambda: psutil.STATUS_ZOMBIE)
    worker = SimpleNamespace(is_running=lambda: True, status=lambda: psutil.STATUS_SLEEPING)
    assert live_orphans(psutil, [zombie, worker]) == [worker]


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(300)
def test_hard_killing_the_tui_does_not_orphan_the_gateway(
    tui_bundle: Path, tui_env: dict, record_property
):
    """SIGKILL the client itself -- no graceful path runs at all.

    The clean-quit case is covered by
    ``test_quitting_reaps_the_gateway_without_help_from_the_harness``, but that
    one exercises ``gw.kill()``, which by definition cannot run here: SIGKILL is
    not catchable, so node executes no teardown whatsoever.  This is the case
    operators actually hit -- force-quitting a terminal, a crash, an OOM kill --
    and it is the scenario that produced the original orphan report.

    Surviving it depends on a *second*, independent mechanism: the gateway
    noticing its stdin has reached EOF and exiting on its own.  Worth its own
    test precisely because it is the fallback -- if it ever regresses, the
    clean-quit test would still pass and nothing else would notice.

    (This is also why there is no fault-injected negative control for the
    clean-quit test: with both mechanisms in place, there is no failure this
    harness can induce from outside that reproduces the old orphan.)
    """
    psutil = pytest.importorskip("psutil")

    session = PtySession(
        ["node", str(tui_bundle)],
        cwd=str(REPO_ROOT),
        env=tui_env,
        rows=30,
        cols=80,
    )
    with session:
        session.wait_for(
            lambda s: "Setup Required" in s.text(),
            timeout=FIRST_PAINT_BUDGET_S,
            what="first paint before hard-killing the client",
        )
        gateways = gateway_processes(psutil, session.pgid)
        assert gateways, "no gateway to orphan" + session.diagnostics()

        # A POSITIVE pid signals that ONE process, not the group -- killing the
        # group here would take the gateway with it and prove nothing.
        killed_at = time.monotonic()
        os.kill(session.pgid, signal.SIGKILL)

        _, alive = psutil.wait_procs(gateways, timeout=ORPHAN_GRACE_S)
        # wait_procs cannot reap a grandchild reparented after node's death.
        # Some container PID 1 implementations leave its exited entry around.
        alive = live_orphans(psutil, alive)
        cleanup_delay = time.monotonic() - killed_at
        record_property("orphan_cleanup_seconds", round(cleanup_delay, 3))
        print(
            f"\n[tui-pty] gateway exited {cleanup_delay:.2f}s after the client "
            "was SIGKILLed (no teardown ran)"
        )

        assert not alive, (
            "the gateway outlived a hard-killed client and is now an orphan: "
            + ", ".join(f"pid {p.pid} ({p.status()})" for p in alive)
            + ". The gateway must exit when its stdin reaches EOF -- that is "
            "the only defence left when node cannot run any teardown."
        )
