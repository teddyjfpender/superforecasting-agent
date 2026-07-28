"""A load budget for the Desk's ``forecast.workspace`` fetch.

THE GAP THIS FILLS
------------------
``tui_gateway/forecast_rpc.py`` serves ``forecast.workspace`` by calling
``build_workspace_payload(limit=1000, include_related=False,
include_lessons=False, history_limit=40)``.  That is the single most
size-sensitive read in the product: the operator's desk has passed 1,100 open
alerts and 1,140 review schedules, and the last regression of this class was a
**4.28s load doing 10,706 SQLite connections**.  It was found because a human
measured by hand.  There has never been a gate.

WHY THIS FILE DOES NOT DRIVE A PTY
----------------------------------
The seam in ``__init__.py`` proposed driving ``d`` to open the Desk and timing
it.  Having built it, the pty is the wrong instrument for the *budget*: the
number worth asserting on lives inside the gateway subprocess, where nothing
can be patched from here, and the only thing observable through a terminal is
wall-clock -- the one measurement this environment is provably bad at.  Same
harness, same day: first paint measured 1.26s on a quiet box and 3.43s on a
saturated one, a 2.7x spread.  Any wall-clock budget tight enough to catch a
2x regression fires on a busy runner; any budget loose enough to survive a busy
runner sleeps through a 2x regression.  So the budget runs in-process, and the
pty covers what only it can (see ``test_desk_opens_against_a_large_ledger``).

WHAT IS ASSERTED, AND WHY IT IS LOAD-PROOF
------------------------------------------
The primary gate is not a number at all -- it is an INVARIANT:

    the workspace fetch costs the same number of SQLite connections and
    statements for a 240-question book as for a 30-question one.

That is what "no N+1" means, stated directly.  It is identical on an idle
laptop and a thrashing container because it counts work done rather than time
taken, and an 8x book-size difference makes any per-question query obvious.
The 10,706-connection regression would have failed it by three orders of
magnitude.  An absolute ceiling backs it up so a constant-but-enormous cost
cannot pass, and a deliberately loose wall-clock check sits behind both as a
catastrophe detector only, clearly labelled as such.
"""

from __future__ import annotations

import os
import re
import time

import pytest

from .conftest import REPO_ROOT
from .ledger_probe import count_sqlite_usage

# Mirrors tui_gateway/forecast_rpc.py's `forecast.workspace` handler exactly
# (limit=1000, include_related=False, include_lessons=False, history_limit=40).
# If that handler's arguments change, change these too -- the budget is only
# meaningful while it measures what the RPC actually calls.
WORKSPACE_LIMIT = 1000
WORKSPACE_HISTORY_LIMIT = 40

# Ceilings, not targets. Measured today: 18 connections / 35 statements at every
# book size from 30 to 450 questions. These sit ~2-3x above that, which leaves
# room for a handful of new batched queries without churn while still being
# ~250x below the historical regression. Raising them should be a conscious act
# with a reason; the equality assertion is the gate that actually bites.
MAX_CONNECTIONS = 40
MAX_STATEMENTS = 120

# Catastrophe detector ONLY. Measured ~0.3s for a 450-question book on a quiet
# box; this is ~30x that, so it fires for a 4.28s-class regression and stays
# quiet through any plausible CI contention. Do not tighten it -- if you want a
# sharper signal, assert on counts, which do not lie under load.
WALL_CLOCK_BACKSTOP_S = float(
    os.environ.get("HERMES_TUI_PTY_WORKSPACE_BUDGET_S", "10")
)


def _fetch_workspace(db_path: str):
    """Construct a ledger and build the payload, counting only the payload.

    Schema initialisation is deliberately OUTSIDE the counted region: it is one
    connection and a fixed pile of DDL that grows every time a table is added,
    so folding it in would make the statement ceiling drift for reasons that
    have nothing to do with the thing being measured.
    """
    from forecasting.dashboard import build_workspace_payload
    from forecasting.ledger import ForecastLedger

    ledger = ForecastLedger(db_path=db_path)
    started = time.perf_counter()
    with count_sqlite_usage() as usage:
        payload = build_workspace_payload(
            ledger=ledger,
            limit=WORKSPACE_LIMIT,
            include_related=False,
            include_lessons=False,
            history_limit=WORKSPACE_HISTORY_LIMIT,
        )
    return payload, usage, time.perf_counter() - started


# ═══════════════════════════════════════════════════════════════════════════
# The gate
# ═══════════════════════════════════════════════════════════════════════════


def test_budget_still_measures_what_the_rpc_actually_calls():
    """Fail loudly if the RPC's arguments drift away from the ones measured here.

    Everything below measures ``build_workspace_payload`` with hand-copied
    arguments. If someone re-tunes the real handler -- drops the limit, turns
    ``include_related`` back on -- this module would keep passing while
    measuring a call the product no longer makes. That is the quiet way a
    perf gate stops being a perf gate, so it gets its own check.
    """
    source = (REPO_ROOT / "tui_gateway" / "forecast_rpc.py").read_text(encoding="utf-8")
    match = re.search(
        r'@rpc_validated\("forecast\.workspace"\)(.{0,1600}?)@rpc_validated',
        source,
        re.DOTALL,
    )
    assert match, (
        "could not find the forecast.workspace handler in "
        "tui_gateway/forecast_rpc.py -- if it moved, re-point this check and "
        "re-verify the constants at the top of this module"
    )
    handler = match.group(1)

    expected = {
        f"default limit of {WORKSPACE_LIMIT}": f"or {WORKSPACE_LIMIT}",
        f"history_limit={WORKSPACE_HISTORY_LIMIT}": f"history_limit={WORKSPACE_HISTORY_LIMIT}",
        "include_related disabled": "include_related=False",
        "include_lessons disabled": "include_lessons=False",
    }
    missing = [name for name, needle in expected.items() if needle not in handler]
    assert not missing, (
        "the forecast.workspace handler no longer matches what this budget "
        "measures: " + ", ".join(missing) + ".\nUpdate WORKSPACE_LIMIT / "
        "WORKSPACE_HISTORY_LIMIT / the _fetch_workspace call in this module, "
        "then re-measure the ceilings -- do not just silence this."
    )


@pytest.mark.timeout(300)
def test_workspace_fetch_cost_does_not_grow_with_the_book(
    small_book, large_book, record_property
):
    """An 8x bigger book must cost the SAME number of SQLite round trips.

    This is the N+1 gate, and it is the reason this module exists.  It needs no
    magic constant and does not care how loaded the machine is: if any query in
    ``build_workspace_payload`` runs once per question, the large book's count
    exceeds the small book's by roughly the ratio of their sizes.
    """
    small_payload, small_usage, _ = _fetch_workspace(small_book["db_path"])
    large_payload, large_usage, elapsed = _fetch_workspace(large_book["db_path"])

    # The fixtures must actually differ in size, or the comparison is vacuous.
    assert len(small_payload["forecasts"]) == small_book["questions"]
    assert len(large_payload["forecasts"]) == large_book["questions"]
    assert large_book["questions"] >= small_book["questions"] * 4, (
        "the two books are too close in size for a per-question regression to "
        f"show up: {small_book['questions']} vs {large_book['questions']}"
    )

    record_property("workspace_connections", large_usage.connections)
    record_property("workspace_statements", large_usage.statements)
    print(
        f"\n[desk-budget] {small_book['questions']:>4} questions -> {small_usage}"
        f"\n[desk-budget] {large_book['questions']:>4} questions -> {large_usage}"
        f"  ({elapsed:.2f}s, {large_book['db_bytes'] / 1e6:.1f}MB db)"
    )

    assert large_usage.connections == small_usage.connections, (
        "the workspace fetch opens more SQLite connections for a bigger book -- "
        "that is an N+1.\n"
        f"  {small_book['questions']} questions: {small_usage}\n"
        f"  {large_book['questions']} questions: {large_usage}\n"
        "The historical regression of this shape was 10,706 connections / 4.28s. "
        "Look for a per-question call that should be one batched query (the "
        "existing *_by_question helpers in forecasting/dashboard/core.py are the "
        "pattern to follow)."
    )
    assert large_usage.statements == small_usage.statements, (
        "the workspace fetch runs more SQL statements for a bigger book -- an "
        "N+1 that happens to reuse a connection.\n"
        f"  {small_book['questions']} questions: {small_usage}\n"
        f"  {large_book['questions']} questions: {large_usage}\n"
        f"  per-connection statements: {large_usage.statements_per_connection}"
    )


@pytest.mark.timeout(300)
def test_workspace_fetch_stays_under_absolute_ceilings(large_book, record_property):
    """Constant cost is necessary but not sufficient -- it must also be small.

    Guards the case the equality test cannot see: a fetch that is O(1) in book
    size but does a constant thousand connections anyway.
    """
    _, usage, elapsed = _fetch_workspace(large_book["db_path"])
    record_property("workspace_seconds", round(elapsed, 3))
    print(
        f"\n[desk-budget] {large_book['spec'].label} -> {usage} in {elapsed:.2f}s"
        f" (fixture built in {large_book['build_seconds']}s)"
    )

    assert usage.connections <= MAX_CONNECTIONS, (
        f"workspace fetch opened {usage.connections} SQLite connections "
        f"(ceiling {MAX_CONNECTIONS}). Each one re-runs two PRAGMAs and installs "
        "the write authorizer, which is why the 10,706-connection regression cost "
        "4.28s."
    )
    assert usage.statements <= MAX_STATEMENTS, (
        f"workspace fetch ran {usage.statements} SQL statements "
        f"(ceiling {MAX_STATEMENTS}); per connection: "
        f"{usage.statements_per_connection}"
    )


@pytest.mark.timeout(300)
def test_workspace_fetch_wall_clock_backstop(large_book):
    """A loose catastrophe detector, and nothing more.

    Deliberately ~30x the measured cost.  It exists so that a regression which
    somehow keeps the query count flat while becoming pathologically slow (a
    missing index, an accidental full-table scan) still trips something.  It is
    NOT a performance target: read the counts above for that.
    """
    _, _, elapsed = _fetch_workspace(large_book["db_path"])
    assert elapsed < WALL_CLOCK_BACKSTOP_S, (
        f"workspace fetch took {elapsed:.2f}s for {large_book['questions']} "
        f"questions, over the {WALL_CLOCK_BACKSTOP_S}s backstop. This bound is "
        "loose on purpose -- exceeding it means something is badly wrong, not "
        "that the box is busy. Override with "
        "HERMES_TUI_PTY_WORKSPACE_BUDGET_S if you are on genuinely slow hardware."
    )
