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


    @server.rpc_validated("forecast.operation")
    def operation(rid, params):
        from forecasting.interfaces.commands import execute_operation

        name = params.get("operation")
        if set(params) - {"operation", "arg", "argv"}:
            return server._err(rid, 4003, "unknown operation parameters")
        arg = params.get("argv") if params.get("argv") is not None else params.get("arg", "")
        if arg is None:
            arg = ""
        if not isinstance(name, str) or name not in {"review", "resolve", "score"}:
            return server._err(rid, 4003, "operation must be review, resolve or score")
        if not isinstance(arg, str) and not (isinstance(arg, list) and all(isinstance(v, str) for v in arg)):
            return server._err(rid, 4003, "arg must be text or argv must be a list of strings")
        if params.get("argv") is not None and params.get("arg"):
            return server._err(rid, 4003, "provide arg or argv, not both")
        return server._ok(rid, execute_operation(ForecastLedger(), name, arg))
