"""Forecast-native domain package for the Superforecasting Agent fork."""

from typing import TYPE_CHECKING

from forecasting.branding import PRODUCT_NAME, PRODUCT_SLUG

if TYPE_CHECKING:
    from forecasting.ledger import ForecastLedger
    from forecasting.models import (
        ForecastingError,
        ForecastQuestion,
        ForecastSnapshot,
        LedgerNotFoundError,
        OutcomeSpace,
        ValidationError,
    )

__all__ = [
    "ForecastLedger",
    "ForecastQuestion",
    "ForecastSnapshot",
    "ForecastingError",
    "LedgerNotFoundError",
    "OutcomeSpace",
    "PRODUCT_NAME",
    "PRODUCT_SLUG",
    "ValidationError",
]


def __getattr__(name: str):
    """Load public storage/model exports only when a caller requests them.

    Importing a pure forecasting submodule must not initialize the ledger graph.
    Existing ``from forecasting import ForecastLedger`` callers retain the same
    class objects and constructors.
    """
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module = "forecasting.ledger" if name == "ForecastLedger" else "forecasting.models"
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
