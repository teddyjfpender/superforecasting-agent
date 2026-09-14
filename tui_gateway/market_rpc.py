"""Gateway RPC for the server-side market-data plane (Arc C).

``server.py`` only imports :func:`register` and calls it — the single handler
routes through :class:`forecasting.marketdata.MarketDataService` (the one source
of truth, with the TTL + stale-while-revalidate cache and per-provider failure
isolation). No provider HTTP lives in the RPC layer.

Methods
-------
* ``market.quotes`` ``{series: [{provider, symbol, name?, category?, unit?, line?}]}``
  → ``{quotes: [Quote]}`` — every measurement honest-null (THE LAW: None ≠ 0).
* ``market.search`` ``{query}`` → ``{results: [MarketSearchResult]}`` — the Yahoo
  symbol lookup moved server-side (the TUI's search box stops hitting Yahoo).

Follows the ``pm_rpc`` pattern exactly: a lazily-built, injectable service
singleton and a protocol-model validation wrapper that NEVER changes the wire.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from protocol import RPC_BY_METHOD


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

    def desk():
        from pathlib import Path

        from superforecasting_agent.application.data_desk import DataDesk
        from superforecasting_agent.constants import get_agent_home

        return DataDesk(Path(get_agent_home()))

    def market_catalog(rid, params):
        from forecasting.marketdata.keys import resolve_key

        try:
            owner = desk()
            return _ok(rid, {
                "catalog": owner.catalog.model_dump(mode="json"),
                "catalog_revision": owner.catalog.revision,
                "selection": owner.selection().model_dump(mode="json"),
                "configured_providers": [p.id for p in owner.catalog.providers
                                        if p.auth == "none" or resolve_key(p.id)],
            })
        except (ValueError, OSError) as exc:
            return _err(rid, exc)

    def market_selection_preview(rid, params):
        from superforecasting_agent.application.data_desk import DeskEdit

        try:
            preview = desk().preview(DeskEdit.model_validate(params["edit"]))
            return _ok(rid, {"preview": preview.model_dump(mode="json")})
        except (ValueError, OSError) as exc:
            return _err(rid, exc)

    def market_provider_connect(rid, params):
        try:
            connected = desk().connect(params["provider"], lambda slot, prompt: server._block(
                "secret.request", params["session_id"], {"env_var": slot, "prompt": prompt}))
            return _ok(rid, {"stored": connected})
        except (ValueError, OSError) as exc:
            return _err(rid, exc)

    def market_selection_apply(rid, params):
        from superforecasting_agent.application.data_desk import DeskEdit

        try:
            selection = desk().apply(DeskEdit.model_validate(params["edit"]),
                                     expected_revision=params["expected_revision"])
            return _ok(rid, {"selection": selection.model_dump(mode="json")})
        except (ValueError, OSError) as exc:
            return _err(rid, exc)

    def market_selection_update(rid, params):
        from superforecasting_agent.application.data_desk import DeskPatch

        try:
            selection = desk().update(DeskPatch.model_validate(params["patch"]),
                                      expected_revision=params["expected_revision"])
            return _ok(rid, {"selection": selection.model_dump(mode="json")})
        except (ValueError, OSError) as exc:
            return _err(rid, exc)

    def market_events_edit(rid, params):
        from superforecasting_agent.application.data_desk import DeskSavedEvent

        try:
            selection = desk().remember_events(
                [DeskSavedEvent.model_validate(item) for item in params["add"]],
                [DeskSavedEvent.model_validate(item) for item in params["remove"]])
            return _ok(rid, {"selection": selection.model_dump(mode="json")})
        except (ValueError, OSError) as exc:
            return _err(rid, exc)

    def market_events_list(rid, params):
        try:
            data, status = get_service().event_result(params["series_id"])
            return _ok(rid, {"data": data.model_dump(mode="json") if data else None, "status": status})
        except (ValueError, OSError) as exc:
            return _err(rid, exc)

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
            service = get_service()
            if hasattr(service, "quote_result"):
                quotes, statuses = service.quote_result(refs)
            else:
                quotes, statuses = service.quotes(refs), []
        except Exception as exc:
            return _err(rid, exc)
        return _ok(rid, {"quotes": [q.to_dict() for q in quotes], "statuses": statuses})

    def market_search(rid, params):
        query = params.get("query")
        if not isinstance(query, str):
            return _err(rid, ValueError("query must be a string"))
        try:
            results = get_service().search(query)
        except Exception as exc:
            return _err(rid, exc)
        return _ok(rid, {"results": [r.to_dict() for r in results]})

    def _validate_params(method: str, handler):
        spec = RPC_BY_METHOD.get(method)
        if spec is None:  # pragma: no cover - market.quotes is registered
            return handler

        def wrapped(rid, params):
            try:
                spec.request.model_validate(params if isinstance(params, dict) else {})
            except ValidationError as exc:
                return _err(rid, _field_error(exc))
            # Response enforcement belongs to the shared protocol wrapper
            # installed by server.register_method, not a second market-specific
            # serializer with different defaults or error behavior.
            return handler(rid, params)

        wrapped.__name__ = getattr(handler, "__name__", method)
        return wrapped

    server.register_method("market.quotes", _validate_params("market.quotes", market_quotes))
    server.register_method("market.search", _validate_params("market.search", market_search))
    server.register_method("market.catalog", _validate_params("market.catalog", market_catalog))
    server.register_method("market.provider.connect", _validate_params("market.provider.connect", market_provider_connect))
    server.register_method("market.selection.preview", _validate_params("market.selection.preview", market_selection_preview))
    server.register_method("market.selection.apply", _validate_params("market.selection.apply", market_selection_apply))
    server.register_method("market.selection.update", _validate_params("market.selection.update", market_selection_update))
    server.register_method("market.selection.events.update", _validate_params("market.selection.events.update", market_events_edit))
    server.register_method("market.events.list", _validate_params("market.events.list", market_events_list))


__all__ = ["register", "get_service", "set_service"]
