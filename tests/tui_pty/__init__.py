"""Real-terminal (pty) tests for the Ink TUI.

Everything else that tests the TUI renders it headless through ink-testing
-- 1900+ vitest cases that never open a terminal.  ``ui-tui/src/entry.tsx``
refuses to start without ``process.stdin.isTTY``, so headless tests cannot
reach the process entry point at all: the terminal-mode reset, the graceful
exit wiring, the gateway spawn and every wide-layout branch are unexercised.

These tests boot the shipped ``entry.js`` bundle behind a real pseudo-terminal
and assert on a reconstructed screen.  See ``test_tui_boot_smoke.py`` for the
contract and ``vt.py`` for why assertions run against a cell grid instead of
ANSI-stripped text.


The Desk load budget (built -- and it is not a timer)
----------------------------------------------------
``test_desk_load_budget.py`` gates the read that actually scales with the
operator's book: ``forecast.workspace``.  Two things were learned building it
that are worth keeping written down, because both contradict the obvious
approach:

**First paint is the wrong thing to budget.**  The TUI paints its first frame
while ``import tui_gateway.server`` (~0.6s) is still running, because the
landing screen needs no ledger data.  Growing the ledger does not move
``test_first_paint_under_a_real_pty`` at all.

**Wall-clock is the wrong thing to assert.**  Measured in this harness: first
paint takes 1.26s on a quiet box and 3.43s on a saturated one.  A budget tight
enough to catch a 2x regression fires on a busy runner; one loose enough to
survive a busy runner sleeps through the regression.  Demonstrated, not
assumed: re-introducing the historical N+1 into ``snapshots_by_question`` takes
the fetch from 18 to 497 SQLite connections -- a 27x increase in work -- while
wall-clock stays at 0.66s.  A time-based budget misses it completely; the
count-based gate catches it by two orders of magnitude.

So the gate is an invariant, not a number: *the workspace fetch costs the same
number of SQLite connections and statements for a 240-question book as for a
30-question one.*  Counts are identical on an idle laptop and a thrashing
container, because they measure work done rather than time taken.

Supporting pieces:

* ``synthetic_ledger.py`` -- book generation through the ``forecasting.ledger``
  package API (never raw SQL, so schema drift fails loudly), writing only to an
  explicit ``db_path``.  It opens ``allow_ledger_writes()`` for the gated
  writes rather than switching ``forecasting/ledger/gate.py`` off, and batches
  each phase into one ``ledger.transaction()`` (without which generation takes
  minutes instead of ~2s).
* ``ledger_probe.py`` -- counts connections at ``ForecastLedger._new_connection``
  (the ledger's single connection chokepoint) and statements via
  ``sqlite3.Connection.set_trace_callback``.
* ``test_desk_at_scale.py`` -- the end-to-end half, covering what in-process
  measurement cannot: that a 240-question / 1,200-alert payload survives the
  gateway, the stdio protocol and the renderer.  It asserts the Desk header
  reports the exact fixture counts, which is load-invariant.  Note the Desk is
  opened by the **``Ctrl+G`` then ``d`` chord**, not a bare ``d`` -- an earlier
  draft of this note claimed otherwise, and a bare ``d`` simply types into the
  composer.  ``GLOBAL_KEYS`` in ``ui-tui/src/content/keymaps.ts`` is the source
  of truth.

Reference volumes on the operator's real desk when this was written: ~1,100
open alerts, ~1,140 review schedules, ~763 source events.
"""
