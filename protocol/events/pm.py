"""Wire model for the sessionless ``pm.tick`` streaming event.

Mirrors ``_emit_tick`` in ``tui_gateway/pm_rpc.py``: the inner payload always
carries ``venue``, ``market_id``, ``kind``, ``estimate`` (the canonical
honest-yes-mid, ``null`` when the tick carries no estimate-grade info), and the
raw venue ``payload`` delta.
"""

from __future__ import annotations

from typing import Any

from protocol.types import MarketId, Venue, WireModel


class PmTick(WireModel):
    TS_NAME = "PMTickPayload"

    venue: Venue
    market_id: MarketId
    kind: str
    # SERVER WINS: the server ALWAYS emits both keys (estimate as float|null,
    # payload as a dict). pmData.ts marked them optional (`estimate?`/`payload?`);
    # the wire always includes them.
    estimate: float | None
    payload: dict[str, Any]


__all__ = ["PmTick"]
