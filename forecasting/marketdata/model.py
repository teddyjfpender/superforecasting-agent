"""Domain model for the server-side market-data plane.

THE LAW — ``None`` NEVER ``0``.
================================
A missing measurement is ``None`` (renders "—"), never ``0`` / ``0.0``. The BEA
``0.0000`` wall that shipped to operators was born the moment an API-error
payload's empty string parsed to ``num('') === 0`` in the client. Every value
that crosses this boundary — ``value``, ``change``, ``changePct``,
``prevClose`` — is ``float | None``; absence is null, and null is the honest
answer. This is the single invariant the estimator-honesty tests exist to
defend, and it lives here (server-side) so the taxonomy tests can finally see
ALL of the quote math (they could not, when it lived in client TypeScript).

``Quote`` mirrors the TUI's ``MarketQuote`` (``ui-tui/src/lib/marketFetch.ts``)
field-for-field so a server quote is a drop-in for the client-parsed one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone


def num(value: object) -> float | None:
    """Coerce to a finite float, else ``None`` — the honest ``num`` helper.

    Mirrors the client's ``num``: strings are parsed, numbers pass through,
    everything else (and any non-finite / unparseable value) becomes ``None``.
    Crucially ``num('')`` is ``None`` here (Python ``float('')`` raises), closing
    the exact hole the client guarded against by hand — absence is never ``0``.
    """

    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            n = float(value.strip())
        elif isinstance(value, (int, float)):
            n = float(value)
        else:
            return None
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def epoch_ms(iso_date: str | None) -> int:
    """Parse a ``YYYY-MM-DD`` (UTC midnight) into epoch milliseconds, else ``0``.

    Matches the client's ``Date.parse('YYYY-MM-DD')`` (interpreted as UTC). An
    unparseable / empty date is ``0`` (the "unknown asOf" sentinel the tape reads
    as "—"), never a fabricated time.
    """

    if not iso_date:
        return 0
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 0
    return int(dt.timestamp() * 1000)


@dataclass(frozen=True)
class SeriesRef:
    """A request for one series from one provider.

    ``line`` is a BEA-specific NIPA line override (the headline line filter);
    absent for every other provider. ``name`` / ``category`` / ``unit`` are
    echoed straight back onto the resulting :class:`Quote` (display metadata the
    provider itself does not know).
    """

    provider: str
    symbol: str
    name: str = ""
    category: str = ""
    unit: str = ""
    line: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "SeriesRef":
        provider = str(data.get("provider") or "").strip()
        symbol = str(data.get("symbol") or "").strip()
        if not provider or not symbol:
            raise ValueError("series ref requires provider and symbol")
        line = data.get("line")
        return cls(
            provider=provider,
            symbol=symbol,
            name=str(data.get("name") or "") or symbol,
            category=str(data.get("category") or ""),
            unit=str(data.get("unit") or ""),
            line=str(line) if line not in (None, "") else None,
        )


@dataclass(frozen=True)
class Quote:
    """A normalized market reading. ``None`` NEVER ``0`` (see the module law)."""

    symbol: str
    provider: str
    name: str
    category: str
    value: float | None
    change: float | None
    changePct: float | None
    prevClose: float | None
    asOf: int  # epoch ms, 0 when unknown
    unit: str
    history: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "provider": self.provider,
            "name": self.name,
            "category": self.category,
            "value": self.value,
            "change": self.change,
            "changePct": self.changePct,
            "prevClose": self.prevClose,
            "asOf": self.asOf,
            "unit": self.unit,
            "history": list(self.history),
        }


def change_columns(
    value: float | None, prev: float | None
) -> tuple[float | None, float | None]:
    """``(change, changePct)`` from a value + prior close, honest about nulls.

    Both are ``None`` unless BOTH inputs are present; ``changePct`` is ``None``
    when ``prev`` is ``0`` (no division-by-zero fabrication).
    """

    if value is None or prev is None:
        return None, None
    change = value - prev
    return change, (change / prev * 100.0) if prev else None


__all__ = ["Quote", "SeriesRef", "num", "epoch_ms", "change_columns"]
