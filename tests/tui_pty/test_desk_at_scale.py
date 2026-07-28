"""Open the real Desk, in a real terminal, against a large ledger.

WHAT THIS COVERS THAT THE BUDGET DOES NOT
-----------------------------------------
``test_desk_load_budget.py`` measures the workspace fetch in-process, which is
the only place the numbers worth asserting on are observable.  But it stops at
the payload: it never checks that a 240-question, 1,200-alert payload actually
survives the trip out of the gateway subprocess, across the stdio protocol,
through the client, and onto a screen.  Frame-size limits, protocol truncation,
a render that throws on a long list -- none of that is visible in-process.

So this test asserts CORRECTNESS AT SCALE rather than speed.  It presses the
real key chord, waits for the Desk, and checks the header reports the exact
counts the fixture wrote.  Those numbers are load-invariant: a busy machine
makes this test slower, never wrong.  The only time bound is the wait deadline,
which is a liveness bound (did it ever arrive?) and deliberately not a budget --
timing lives in the module above, on measurements that do not lie under load.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import FIRST_PAINT_BUDGET_S, REPO_ROOT
from .pty_session import PtySession
from .vt import VTScreen

# The Desk is reached by a CHORD, not a bare key: ui-tui/src/content/keymaps.ts
# documents `Ctrl+G then <letter>` in GLOBAL_KEYS, and VIEW_CHORDS maps 'd' to
# the desk route. (A bare `d` types into the composer -- verified by watching it
# land in the prompt.)
CTRL_G = b"\x07"
DESK_CHORD_LETTER = b"d"

# Rendered by the desk header (ui-tui/src/components/deskView.tsx) from the
# forecast.workspace payload's counts. Structural: it is the desk telling us
# what it received.
DESK_HEADER = "FORECASTS"

# Wide enough for the desk's list + skinny summary panel (WIDE_COLS = 100 in
# deskView.tsx) and tall enough that the header is not scrolled away.
DESK_COLS, DESK_ROWS = 120, 44

# Liveness bound, NOT a performance budget. Generous on purpose: this test is
# about whether the payload arrives intact, and the budget module owns speed.
DESK_ARRIVAL_TIMEOUT_S = 60.0


def desk_is_open(screen: VTScreen) -> bool:
    text = screen.text()
    return DESK_HEADER in text and "QUESTION" in text


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(300)
def test_desk_opens_against_a_large_ledger(
    tui_bundle: Path, tui_env: dict, tui_home_with_large_book: dict, record_property
):
    """Ctrl+G d opens the Desk and it reports the whole book, intact."""
    book = tui_home_with_large_book
    session = PtySession(
        ["node", str(tui_bundle)],
        cwd=str(REPO_ROOT),
        env=tui_env,
        rows=DESK_ROWS,
        cols=DESK_COLS,
    )
    with session:
        session.wait_for(
            lambda s: "Setup Required" in s.text(),
            timeout=FIRST_PAINT_BUDGET_S,
            what="first paint before opening the desk",
        )
        session.settle()

        pressed_at = session.elapsed
        session.send(CTRL_G)
        # The chord's two keys are separate reads for the client; give the first
        # a moment to register as a pending chord rather than racing it.
        session.settle(quiet=0.15, max_wait=2.0)
        session.send(DESK_CHORD_LETTER)

        arrival = (
            session.wait_for(
                desk_is_open,
                timeout=DESK_ARRIVAL_TIMEOUT_S,
                what=f"the Desk view (header {DESK_HEADER!r}) after Ctrl+G d",
            )
            - pressed_at
        )
        record_property("desk_arrival_seconds", round(arrival, 3))
        print(
            f"\n[desk-scale] Desk rendered {arrival:.2f}s after the chord "
            f"({book['questions']} questions, {book['alerts']} alerts, "
            f"{book['db_bytes'] / 1e6:.1f}MB ledger)"
        )

        session.settle(quiet=0.4, max_wait=10.0)
        text = session.screen.text()

        # The header is the desk restating the payload it received. Asserting on
        # the exact fixture counts turns "the Desk opened" into "the Desk got
        # every row" -- a truncated or capped payload fails here, and neither
        # number moves because the machine is busy.
        assert f"{book['questions']} active" in text, (
            f"desk header should report all {book['questions']} synthetic "
            "questions as active; a smaller number means the payload was "
            "truncated between the ledger and the screen" + session.diagnostics()
        )
        assert f"{book['alerts']} open alerts" in text, (
            f"desk header should report all {book['alerts']} open alerts"
            + session.diagnostics()
        )
        # And it actually drew rows, not just a header over an empty list.
        assert "Synthetic forecast" in text, (
            "desk rendered its header but no forecast rows" + session.diagnostics()
        )
        assert session.returncode is None, (
            "the TUI exited while rendering the desk" + session.diagnostics()
        )
