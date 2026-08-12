"""Boot the shipped TUI bundle in a real terminal and assert what a user sees.

WHY THIS FILE EXISTS
--------------------
``ui-tui`` has ~1900 vitest cases and every one of them renders headless.
Three consequences, all of them holes this file fills:

1. ``ui-tui/src/entry.tsx`` starts with ``if (!process.stdin.isTTY) { print
   'no TTY'; exit(0) }``.  Nothing that runs headless can get past that line,
   so the *process entry point* -- ``resetTerminalModes()`` on startup, the
   ``setupGracefulExit`` cleanups, the memory monitor, the gateway spawn --
   has no test at all.
2. A headless Ink render sizes the root box to CONTENT height, so overlays and
   lower rows are clipped and cannot be asserted on.
3. Headless tests default to 80 columns, so they cannot prove the full-width
   Home layout survives a real terminal resize.  The resize test below covers
   that PTY-only path.

WHAT ONE BOOT ACTUALLY PROVES
-----------------------------
More than it looks.  The Setup Required panel this test waits for is rendered
from the result of a ``setup.status`` RPC, so seeing it on screen proves the
whole stack came up: node parsed the bundle, Ink took the terminal, the client
spawned ``python -m tui_gateway.entry`` over stdio, the protocol handshake
completed, an RPC round-tripped, and React painted the answer.

ASSERTION STYLE
---------------
Assertions run against a reconstructed cell grid (``vt.VTScreen``), never
against ANSI-stripped bytes -- Ink pads with ``ESC[nC`` cursor moves, so
stripping silently eats characters ("Setup Required" strips to "Stup Requid").
Content anchors are named constants in the TUI source, cited at each use, so a
rename is greppable from both ends.  The terminal-protocol assertions (alt
screen, mouse tracking, DECSET restoration) are the redesign-proof half: they
are the contract with the terminal itself and no visual refresh can move them.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from .conftest import FIRST_PAINT_BUDGET_S, NO_TTY_SENTINEL, REPO_ROOT
from .pty_session import PtySession
from .vt import VTScreen

# ── Layout constants mirrored from the TUI source ───────────────────────────
NARROW_COLS, NARROW_ROWS = 80, 30
WIDE_COLS, WIDE_ROWS = 120, 44

# ui-tui/src/content/setup.ts: SETUP_REQUIRED_TITLE.  Shown when the gateway's
# `setup.status` RPC reports no provider configured -- always true for the
# pristine `tui_home` fixture.
SETUP_REQUIRED_TITLE = "Setup Required"

# ui-tui/src/lib/terminalModes.ts: TERMINAL_MODE_RESET.  The subset that leaves
# a terminal unusable if it is not restored -- a tab stuck in mouse-tracking
# spews escape codes on every mouse move; a tab stuck in the alternate screen
# has lost the user's scrollback.  This is the regression `resetTerminalModes`
# exists to prevent, and it has never had a test.
MODE_RESTORE_SEQUENCES = {
    "alternate screen off": b"\x1b[?1049l",
    "X10 mouse off": b"\x1b[?1000l",
    "button-motion mouse off": b"\x1b[?1002l",
    "any-motion mouse off": b"\x1b[?1003l",
    "SGR mouse off": b"\x1b[?1006l",
    "bracketed paste off": b"\x1b[?2004l",
}

# Startup counterparts, asserted so "modes were restored" cannot pass vacuously
# by never having been set in the first place.
MODE_ENABLE_SEQUENCES = {
    "alternate screen on": b"\x1b[?1049h",
    "any-motion mouse on": b"\x1b[?1003h",
    "bracketed paste on": b"\x1b[?2004h",
}

CTRL_C = b"\x03"


def make_session(bundle: Path, env: dict[str, str]) -> PtySession:
    """An unstarted TUI session at the narrow (headless-equivalent) size."""
    return PtySession(
        ["node", str(bundle)],
        cwd=str(REPO_ROOT),
        env=env,
        rows=NARROW_ROWS,
        cols=NARROW_COLS,
    )


@pytest.fixture()
def tui(tui_bundle: Path, tui_env: dict[str, str]):
    """A booted TUI on an 80x30 pty, torn down (process group killed) after."""
    with make_session(tui_bundle, tui_env) as session:
        yield session


# ═══════════════════════════════════════════════════════════════════════════
# The control: prove the pty is doing something
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(60)
def test_without_a_tty_the_bundle_refuses_to_start(tui_bundle: Path, tui_env: dict):
    """The negative control for the whole file.

    Every other test asserts the ``no TTY`` bail-out did NOT happen.  That
    assertion is unfalsifiable unless we also show the bail-out is real and
    reachable -- otherwise a harness that silently stopped launching anything
    would still pass.  This is also the only coverage of the guard itself.
    """
    proc = subprocess.run(
        ["node", str(tui_bundle)],
        cwd=str(REPO_ROOT),
        env=tui_env,
        stdin=subprocess.DEVNULL,  # a pipe, not a tty: the guard must fire
        capture_output=True,
        timeout=45,
    )
    assert proc.returncode == 0, f"expected a clean bail-out, got {proc.returncode}\n{proc.stderr!r}"
    assert NO_TTY_SENTINEL in proc.stdout, (
        f"expected the no-TTY guard in ui-tui/src/entry.tsx to fire; got {proc.stdout!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# First paint
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(120)
def test_first_paint_under_a_real_pty(tui: PtySession, record_property):
    """Boots past the TTY gate, takes the terminal, and paints within budget."""
    first_paint = tui.wait_for(
        lambda s: SETUP_REQUIRED_TITLE in s.text(),
        timeout=FIRST_PAINT_BUDGET_S,
        what=f"first paint (screen containing {SETUP_REQUIRED_TITLE!r})",
    )
    record_property("first_paint_seconds", round(first_paint, 3))
    print(f"\n[tui-pty] first paint at t+{first_paint:.2f}s (budget {FIRST_PAINT_BUDGET_S}s)")

    raw = bytes(tui.raw)
    assert NO_TTY_SENTINEL not in raw, (
        "the bundle took the no-TTY path even though it was launched on a pty"
        + tui.diagnostics()
    )

    # The terminal-protocol contract: it claimed the alternate screen, turned
    # on mouse reporting and bracketed paste.  Structural, so a visual redesign
    # cannot move it.
    for name, seq in MODE_ENABLE_SEQUENCES.items():
        assert seq in raw, f"expected {name} ({seq!r}) during startup" + tui.diagnostics()

    # A real, dense paint -- not a blank alternate screen with one status line.
    tui.settle()
    filled = [row for row in tui.screen.rows_text() if row.strip()]
    assert len(filled) >= 8, f"only {len(filled)} non-blank rows" + tui.diagnostics()
    assert sum(len(r.strip()) for r in filled) >= 200, "screen is nearly empty" + tui.diagnostics()

    # Reaching this panel means the gateway subprocess answered `setup.status`
    # (see the module docstring) -- so it doubles as the gateway smoke test.
    assert SETUP_REQUIRED_TITLE in tui.screen.text()


# ═══════════════════════════════════════════════════════════════════════════
# Resize -- the branch headless tests cannot reach
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(120)
def test_wide_terminal_keeps_home_full_width(tui: PtySession, record_property):
    """Resize 80 -> 120 columns without reviving the removed chat rail."""
    tui.wait_for(
        lambda s: SETUP_REQUIRED_TITLE in s.text(),
        timeout=FIRST_PAINT_BUDGET_S,
        what="first paint before resizing",
    )

    tui.settle()

    before = tui.elapsed
    tui.resize(WIDE_ROWS, WIDE_COLS)
    latency = tui.wait_for(
        lambda s: s.cols == WIDE_COLS and SETUP_REQUIRED_TITLE in s.text(),
        timeout=30,
        what=f"the full-width Home layout after resizing to {WIDE_COLS} columns",
    ) - before
    record_property("resize_home_seconds", round(latency, 3))
    print(f"[tui-pty] Home resized {latency:.2f}s after SIGWINCH")

    assert tui.returncode is None, "the TUI exited during the resize" + tui.diagnostics()
    tui.settle()
    assert SETUP_REQUIRED_TITLE in tui.screen.text(), (
        "the app lost its panel across the resize" + tui.diagnostics()
    )
    assert "New chat" not in tui.screen.text()
    assert "Recent" not in tui.screen.text()


# ═══════════════════════════════════════════════════════════════════════════
# Clean exit + terminal restoration
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(120)
def test_ctrl_c_exits_zero_and_restores_terminal_modes(tui: PtySession, record_property):
    """The documented quit path leaves the terminal usable.

    Ctrl+C on an empty composer routes to ``actions.die()``
    (ui-tui/src/app/useInputHandlers.ts) -> ``gw.kill(); exit();
    process.exit(0)`` (useMainApp.ts).  Because Ink has the tty in raw mode the
    0x03 arrives as a keystroke, not SIGINT -- which is exactly why the exit
    code is 0 and not 130, and why we must wait for first paint before sending
    it (before raw mode is on, the same byte WOULD be SIGINT).

    The restoration half is the regression `resetTerminalModes` exists for: a
    TUI that dies without clearing mouse tracking leaves the user's tab
    spewing escape codes on every mouse move.
    """
    tui.wait_for(
        lambda s: SETUP_REQUIRED_TITLE in s.text(),
        timeout=FIRST_PAINT_BUDGET_S,
        what="first paint before quitting",
    )
    tui.settle()

    quit_mark = len(tui.raw)
    tui.send(CTRL_C)
    rc = tui.wait_exit(timeout=30)
    record_property("quit_seconds", round(tui.elapsed, 3))
    print(f"[tui-pty] exited rc={rc} at t+{tui.elapsed:.2f}s")

    assert rc == 0, f"the documented quit path must exit 0, got {rc}" + tui.diagnostics()

    teardown = bytes(tui.raw[quit_mark:])
    missing = [name for name, seq in MODE_RESTORE_SEQUENCES.items() if seq not in teardown]
    assert not missing, (
        "the TUI exited without restoring: "
        + ", ".join(missing)
        + " -- see TERMINAL_MODE_RESET in ui-tui/src/lib/terminalModes.ts"
        + f"\n--- teardown bytes ---\n{teardown[-400:]!r}\n"
    )


# How long the TUI gets, after node exits, to have already reaped its gateway.
# Sized against the mechanism rather than a guess: `gw.kill()` closes stdin,
# sends SIGTERM, escalates to SIGKILL at 1.5s and resolves by 2s regardless;
# the gateway's own SIGTERM handler dumps thread stacks and os._exit()s after a
# 1s grace, measured at 0.6-1.1s. So a correct implementation is done well
# inside 2s and this is ~7x that. It is not a timing assertion -- before the
# fix the orphan survived indefinitely (observed alive with PPID 1 at 13s), so
# any bound at all separates reaped from orphaned.
GATEWAY_REAP_GRACE_S = 15.0


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(120)
def test_quitting_reaps_the_gateway_without_help_from_the_harness(
    tui_bundle: Path, tui_env: dict, record_property
):
    """The TUI must reap its own gateway -- measured BEFORE the harness sweeps.

    An earlier version of this test asserted after ``with session:`` had
    already exited, which meant ``_sweep_group()`` had SIGKILLed the process
    group before anything was measured.  It could only ever prove the harness
    cleans up after itself; the application could have leaked every single run
    and it would still have passed.  That is the exact shape of a test that
    looks like coverage and is not, so it is worth being explicit about.

    The real assertion needs the harness to keep its hands off: ``wait_exit(
    sweep=False)`` leaves the process group alive so the question "did the app
    reap its own child?" is actually asked.  ``close()`` still sweeps
    afterwards, but only after the measurement -- it is a backstop, not the
    thing under test.

    This regressed once already: ``gw.kill()`` used to fire a bare SIGTERM and
    never await it while ``die()`` called ``process.exit(0)`` immediately, so
    the gateway outlived node and was reparented to init.
    """
    psutil = pytest.importorskip("psutil")

    session = make_session(tui_bundle, tui_env)
    with session:
        session.wait_for(
            lambda s: SETUP_REQUIRED_TITLE in s.text(),
            timeout=FIRST_PAINT_BUDGET_S,
            what="first paint before inventorying children",
        )
        # Bound Process objects: if one of these PIDs is later reused, psutil
        # reports NoSuchProcess rather than a false "still alive".
        leader = psutil.Process(session.pgid)
        descendants = leader.children(recursive=True)
        gateways = [p for p in descendants if _is_gateway(p)]
        assert gateways, (
            "expected a `python -m tui_gateway.entry` child before quitting; "
            "without one this test proves nothing. Saw: "
            + repr([_safe_cmdline(p) for p in descendants])
            + session.diagnostics()
        )

        session.settle()
        # Instrument check: these handles see a LIVE gateway right up to the
        # quit, so "gone" below is a real transition and not a lookup that was
        # always going to come back empty.
        assert all(p.is_running() for p in gateways), (
            "the gateway died before the quit was even sent" + session.diagnostics()
        )

        session.send(CTRL_C)
        # sweep=False is the whole point -- see the docstring.
        rc = session.wait_exit(timeout=30, sweep=False)
        assert rc == 0, f"expected a clean quit, got {rc}" + session.diagnostics()

        exited_at = time.monotonic()
        _, alive = psutil.wait_procs(gateways, timeout=GATEWAY_REAP_GRACE_S)
        reap_delay = time.monotonic() - exited_at
        record_property("gateway_reap_seconds", round(reap_delay, 3))
        print(f"\n[tui-pty] gateway gone {reap_delay:.2f}s after node exited")

        assert not alive, (
            "the TUI exited 0 but left its gateway running -- it is now an "
            "orphan reparented to init:\n  "
            + "\n  ".join(f"pid {p.pid} ppid {_safe_ppid(p)}: {' '.join(_safe_cmdline(p))}" for p in alive)
            + "\nSee gw.kill() in ui-tui/src/gatewayClient.ts and die() in "
            "useMainApp.ts: kill() must be awaited before process.exit()."
        )

        # Nothing else from the group may survive either -- a respawned gateway
        # would carry a PID the captured list above cannot know about.
        strays = _survivors_in_group(psutil, session.pgid)
        assert not strays, (
            "processes from the TUI's process group outlived it: " + repr(strays)
        )


def _is_gateway(proc) -> bool:
    return "tui_gateway.entry" in " ".join(_safe_cmdline(proc))


def _safe_cmdline(proc) -> list[str]:
    try:
        return proc.cmdline()
    except Exception:  # pragma: no cover - process vanished mid-report
        return ["<gone>"]


def _safe_ppid(proc) -> object:
    try:
        return proc.ppid()
    except Exception:  # pragma: no cover - process vanished mid-report
        return "?"


def _survivors_in_group(psutil, pgid: int) -> list[str]:
    """Any live process still in *pgid*, found by scan rather than by pid list."""
    found = []
    for proc in psutil.process_iter(["pid"]):
        try:
            if os.getpgid(proc.pid) == pgid and proc.pid != os.getpid():
                found.append(f"pid {proc.pid}: {' '.join(_safe_cmdline(proc))}")
        except Exception:
            continue  # exited mid-scan, or not ours to inspect
    return found
