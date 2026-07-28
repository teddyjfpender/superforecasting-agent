"""Count the SQLite work a ledger operation does.

Why counting beats timing here
------------------------------
The regression this guards against had a precise signature: a desk load doing
**10,706 SQLite connections** and taking 4.28s.  Only one of those two numbers
is worth asserting on.

Wall-clock on a shared CI runner is worth roughly a factor of three -- measured
in this very harness, first paint ranged 1.26s on a quiet box to 3.43s on a
saturated one.  A budget tight enough to catch a 2x slowdown will fire on a
busy runner; a budget loose enough to survive a busy runner will not notice a
2x slowdown.  Connection and statement counts have no such problem: they are
identical on an idle laptop and a thrashing container, because they count work
*done*, not time *taken*.

Instrumentation points, both chosen because they are chokepoints rather than
conveniences:

* ``ForecastLedger._new_connection`` is the single place the ledger opens a
  SQLite connection (``_connect`` either borrows the active transaction's
  connection or calls it).  Each call also runs two PRAGMAs and installs the
  write authorizer, which is exactly why 10,706 of them cost seconds.
* ``sqlite3.Connection.set_trace_callback`` is the stdlib's own per-statement
  hook.  (Wrapping ``conn.execute`` is not an option -- the attribute is
  read-only on a Connection.)
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

__all__ = ["SqliteUsage", "count_sqlite_usage"]


@dataclass
class SqliteUsage:
    """How much SQLite work happened inside a ``count_sqlite_usage`` block."""

    connections: int = 0
    statements: int = 0
    #: One entry per connection opened, for diagnostics on failure.
    statements_per_connection: list[int] = field(default_factory=list)

    def __str__(self) -> str:
        return f"{self.connections} connections / {self.statements} statements"


@contextlib.contextmanager
def count_sqlite_usage():
    """Count ledger SQLite connections and statements inside the block.

    Patches the class attribute for the duration and restores it afterwards, so
    it is safe under xdist (each worker is its own process) but NOT safe to
    nest or use across threads -- neither of which the tests here do.
    """
    from forecasting.ledger import ForecastLedger

    original = getattr(ForecastLedger, "_new_connection", None)
    if original is None:  # pragma: no cover - fails loudly rather than silently passing
        raise AssertionError(
            "ForecastLedger._new_connection is gone -- this probe counts the "
            "ledger's connection chokepoint and can no longer see it. Find the "
            "new chokepoint in forecasting/ledger/core.py and update this file "
            "(do NOT delete the assertion: the count is the whole gate)."
        )

    usage = SqliteUsage()

    def counting_new_connection(self):
        usage.connections += 1
        connection = original(self)
        index = len(usage.statements_per_connection)
        usage.statements_per_connection.append(0)

        def on_statement(_sql: str) -> None:
            usage.statements += 1
            usage.statements_per_connection[index] += 1

        connection.set_trace_callback(on_statement)
        return connection

    # setattr rather than plain assignment: a direct assignment reads as an
    # implicit redefinition of the method to a type checker, and silencing that
    # with an ignore comment would hide any future real mismatch here.
    setattr(ForecastLedger, "_new_connection", counting_new_connection)
    try:
        yield usage
    finally:
        setattr(ForecastLedger, "_new_connection", original)
