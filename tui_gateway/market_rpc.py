"""Gateway RPC for the server-side market-data plane (Arc C).

``server.py`` only imports :func:`register` and calls it — the single handler
routes through :class:`forecasting.marketdata.MarketDataService` (the one source
of truth, with the TTL + stale-while-revalidate cache and per-provider failure
isolation). No provider HTTP lives in the RPC layer.

Methods
-------
* ``market.quotes`` ``{series: [{provider, symbol, name?, category?, unit?, line?}]}``
  → ``{quotes: [Quote]}`` — every measurement honest-null (THE LAW: None ≠ 0).

Follows the ``pm_rpc`` pattern exactly: a lazily-built, injectable service
singleton and a protocol-model validation wrapper that NEVER changes the wire.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from protocol import RPC_BY_METHOD

logger = logging.getLogger(__name__)


def _field_error(exc: ValidationError) -> ValueError:
    first = exc.errors()[0]
    loc = ".".join(str(part) for part in first.get("loc", ())) or "params"
    return ValueError(f"invalid params: field '{loc}' {first.get('msg', 'is invalid')}")


_service_holder: dict[str, Any] = {"svc": None}


def get_service():
    if _service_holder["svc"] is None:
        from forecasting.marketdata import MarketDataService

        _service_holder["svc"] = MarketDataService()
    return _service_holder["svc"]


def set_service(service) -> None:
    """Test seam: inject a stub MarketDataService (no network)."""
    _service_holder["svc"] = service


def _err_code(exc: Exception) -> int:
    return -32602 if isinstance(exc, (ValueError, KeyError)) else -32000


def register(server) -> None:
    """Register the ``market.*`` handlers into the gateway dispatch table."""

    def _ok(rid, result):
        return server._ok(rid, result)

    def _err(rid, exc):
        return server._err(rid, _err_code(exc), f"market error: {exc}")

    def market_quotes(rid, params):
        from forecasting.marketdata.model import SeriesRef

        raw = params.get("series")
        if not isinstance(raw, list):
            return _err(rid, ValueError("series must be a list"))
        try:
            refs = [SeriesRef.from_dict(item) for item in raw if isinstance(item, dict)]
        except ValueError as exc:
            return _err(rid, exc)
        try:
            quotes = get_service().quotes(refs)
        except Exception as exc:
            return _err(rid, exc)
        return _ok(rid, {"quotes": [q.to_dict() for q in quotes]})

    def _rpc_model(method: str, handler):
        spec = RPC_BY_METHOD.get(method)
        if spec is None:  # pragma: no cover - market.quotes is registered
            return handler

        def wrapped(rid, params):
            try:
                spec.request.model_validate(params if isinstance(params, dict) else {})
            except ValidationError as exc:
                return _err(rid, _field_error(exc))
            resp = handler(rid, params)
            if isinstance(resp, dict) and isinstance(resp.get("result"), dict):
                try:
                    model = spec.response.model_validate(resp["result"])
                except ValidationError:
                    logger.debug(
                        "market response for %s did not validate; passing through unchanged",
                        method,
                    )
                    return resp
                dumped = model.model_dump(mode="json", exclude_none=spec.exclude_none)
                return {**resp, "result": dumped}
            return resp

        wrapped.__name__ = getattr(handler, "__name__", method)
        return wrapped

    server.register_method("market.quotes", _rpc_model("market.quotes", market_quotes))


__all__ = ["register", "get_service", "set_service"]
