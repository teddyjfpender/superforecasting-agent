"""Server-side market-data plane (Arc C).

Every market provider lives behind ONE interface (:class:`Provider`) and ONE
service (:class:`MarketDataService`): agent parity (the agent reads the same tape
the operator sees), one key store, and the estimator-honesty test discipline
covering ALL quote math — because it is server-side, the taxonomy tests can
finally see it (the BEA ``0.0000`` lived in client TypeScript precisely because
they could not).

THE LAW lives in :mod:`forecasting.marketdata.model`: ``None`` NEVER ``0``.
"""

from forecasting.marketdata.keys import resolve_key
from forecasting.marketdata.model import Quote, SeriesRef, change_columns, epoch_ms, num
from forecasting.marketdata.provider import Provider
from forecasting.marketdata.service import MarketDataService, QUOTES_TTL, TTLCache

__all__ = [
    "Quote",
    "SeriesRef",
    "num",
    "epoch_ms",
    "change_columns",
    "Provider",
    "MarketDataService",
    "TTLCache",
    "QUOTES_TTL",
    "resolve_key",
]
