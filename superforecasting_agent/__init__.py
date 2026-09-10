"""Public Superforecasting Agent API, loaded only when requested.

Keep package initialization free of application imports so startup helpers can
run before configuration, logging, or the forecast ledger are initialized.
"""

from __future__ import annotations


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


def __getattr__(name: str):
    if name == "__version__":
        from importlib.metadata import PackageNotFoundError, version

        try:
            value = version("superforecasting-agent")
        except PackageNotFoundError:
            value = "0.0.0"
    elif name in __all__:
        import forecasting

        value = getattr(forecasting, name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
