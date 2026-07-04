"""Wire models for the ``market.*`` server-side data-plane RPCs (Arc C on Arc A).

Mirrors ``tui_gateway/market_rpc.py`` and ``forecasting.marketdata``:
* ``market.quotes`` ``{series: [{provider, symbol, name?, category?, unit?, line?}]}``
  → ``{quotes: [Quote]}``.

``Quote`` is transcribed field-for-field from ``forecasting/marketdata/model.py``
``Quote.to_dict`` — which itself mirrors the TUI's ``MarketQuote`` so a server
quote is a drop-in for the client-parsed one. THE LAW holds on the wire: every
measurement (``value`` / ``change`` / ``changePct`` / ``prevClose``) is
``float | None`` and stays ``null`` when absent — NEVER a fabricated ``0``.
"""

from __future__ import annotations

from protocol.types import WireModel, wire_optional


class MarketSeriesRef(WireModel):
    TS_NAME = "MarketSeriesRef"

    provider: str
    symbol: str
    # Display metadata echoed onto the Quote; ``line`` is a BEA NIPA headline
    # override. All optional (dropped when absent, never sent as null).
    name: str | None = wire_optional()
    category: str | None = wire_optional()
    unit: str | None = wire_optional()
    line: str | None = wire_optional()


class Quote(WireModel):
    TS_NAME = "Quote"

    symbol: str
    provider: str
    name: str
    category: str
    # THE LAW — None NEVER 0: absence stays null on the wire.
    value: float | None
    change: float | None
    changePct: float | None
    prevClose: float | None
    asOf: int  # epoch ms, 0 when unknown
    unit: str
    history: list[float]


class MarketQuotesRequest(WireModel):
    TS_NAME = "MarketQuotesRequest"

    series: list[MarketSeriesRef]


class MarketQuotesResponse(WireModel):
    TS_NAME = "MarketQuotesResponse"

    quotes: list[Quote]


__all__ = [
    "MarketSeriesRef",
    "Quote",
    "MarketQuotesRequest",
    "MarketQuotesResponse",
]
