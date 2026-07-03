"""Prediction-markets package: one Python implementation of Polymarket + Kalshi
read-only market data, consumed by both the agent tool and the TUI gateway.

Public facade — import from here rather than the submodules.
"""

from __future__ import annotations

from forecasting.pm.aggregate import build_distribution, devig_yes_mids
from forecasting.pm.history import downsample as downsample_history
from forecasting.pm.kalshi import (
    KalshiClient,
    KalshiSignerUnavailable,
    kalshi_auth_headers,
    sign_kalshi_message,
)
from forecasting.pm.model import (
    PMDistribution,
    PMEvent,
    PMHistoryPoint,
    PMMarket,
    PMOrderBook,
    PMOrderLevel,
    PMOutcome,
)
from forecasting.pm.polymarket import PolymarketClient
from forecasting.pm.service import PMService
from forecasting.pm.stream import PMStreamHub, StreamStart, websocket_available

__all__ = [
    "PMService",
    "PMStreamHub",
    "StreamStart",
    "websocket_available",
    "PolymarketClient",
    "KalshiClient",
    "PMEvent",
    "PMMarket",
    "PMOrderBook",
    "PMOrderLevel",
    "PMOutcome",
    "PMHistoryPoint",
    "PMDistribution",
    "build_distribution",
    "devig_yes_mids",
    "downsample_history",
    "sign_kalshi_message",
    "kalshi_auth_headers",
    "KalshiSignerUnavailable",
]
