"""Wire models for the Markets "Models" tab streaming events.

Emitted by the ``markets.model.*`` RPC handlers in ``tui_gateway/server.py`` as a
quant-model build/refine/refresh runs: ``markets.model.progress`` (0+) →
``markets.model.complete``, ``markets.model.refreshed`` (background refresh of an
open model), and ``markets.model.error``.
"""

from __future__ import annotations

from typing import Any

from protocol.types import WireModel, wire_optional


class MarketModelProgress(WireModel):
    """``markets.model.progress`` — a build/refine progress line for model ``id``."""

    TS_NAME = "MarketModelProgressPayload"

    id: str
    phase: str | None = wire_optional()
    message: str | None = wire_optional()


class MarketModelComplete(WireModel):
    """``markets.model.complete`` — a build/refine/retry finished for model ``id``."""

    TS_NAME = "MarketModelCompletePayload"

    id: str
    version: int | None = wire_optional()
    status: str | None = wire_optional()


class MarketModelRefreshed(WireModel):
    """``markets.model.refreshed`` — a background refresh produced a fresh version."""

    TS_NAME = "MarketModelRefreshedPayload"

    id: str
    presentation: dict[str, Any] | None = wire_optional()


class MarketModelError(WireModel):
    """``markets.model.error`` — a model op failed for ``id``."""

    TS_NAME = "MarketModelErrorPayload"

    id: str
    message: str | None = wire_optional()


__all__ = [
    "MarketModelProgress",
    "MarketModelComplete",
    "MarketModelRefreshed",
    "MarketModelError",
]
