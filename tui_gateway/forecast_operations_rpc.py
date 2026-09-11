"""Structured forecasting operations: no classic CLI or stdout redirection."""
from __future__ import annotations

from dataclasses import asdict

from forecasting.application.resolution import resolve_forecast
from forecasting.application.reviews import review_forecasts
from forecasting.ledger import ForecastLedger
from forecasting.models import ForecastingError


def register(server) -> None:
    @server.rpc_validated("forecast.review")
    def review(rid, params):
        try:
            rows = review_forecasts(ForecastLedger(), **params)
            return server._ok(rid, {"rows": [
                {**row, "question": asdict(row["question"]),
                 "current_snapshot": asdict(row["current_snapshot"]) if row["current_snapshot"] else None}
                for row in rows
            ]})
        except ForecastingError as exc:
            return server._err(rid, 4003, str(exc))

    @server.rpc_validated("forecast.resolve")
    def resolve(rid, params):
        try:
            result = resolve_forecast(ForecastLedger(), params)
            return server._ok(rid, asdict(result))
        except ForecastingError as exc:
            return server._err(rid, 4003, str(exc))
