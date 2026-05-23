"""Public package namespace for the Superforecasting Agent fork."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from forecasting import (
    ForecastLedger,
    ForecastQuestion,
    ForecastSnapshot,
    ForecastingError,
    LedgerNotFoundError,
    OutcomeSpace,
    PRODUCT_NAME,
    PRODUCT_SLUG,
    ValidationError,
)

try:
    __version__ = version("superforecasting-agent")
except PackageNotFoundError:  # pragma: no cover - editable source tree without metadata
    __version__ = "0.0.0"

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
    "__version__",
]
