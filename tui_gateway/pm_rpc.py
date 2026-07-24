"""Gateway RPCs for prediction markets (Polymarket + Kalshi).

``server.py`` only imports :func:`register` and calls it — every handler here
routes through :class:`forecasting.pm.PMService` (the one source of truth) and
the shared :class:`forecasting.pm.stream.PMStreamHub`. No direct venue-client
calls live in the RPC layer.

Methods
-------
* ``pm.list`` ``{venue?, query?, tag?, limit?}`` → ``{events: [{event, distribution}]}``
* ``pm.detail`` ``{venue, event_id}`` → ``{event, distribution}``
* ``pm.book`` ``{venue, market_id}`` → normalised order book
* ``pm.history`` ``{venue, market_id, range?, series_ticker?, period_interval?}`` → ``{points}``
* ``pm.stream.start`` ``{venue, market_ids}`` / ``pm.stream.stop`` ``{venue, market_ids?}``
  — one ws connection per venue; ticks are re-emitted as sessionless
  ``pm.tick`` events, mirroring the ``cron.fired`` / ``review.sweep`` seam.

Streaming degrades politely: no websocket lib or no Kalshi key → ``start``
returns ``{streaming: false, reason}`` and the TUI keeps its 30s list re-poll.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import ValidationError

from protocol import RPC_BY_METHOD

logger = logging.getLogger(__name__)

# Result keys that ride the wire additively even though the generated response
# model doesn't declare them (see ``_rpc_model``). Kept tiny + explicit.
_PASSTHROUGH_RESULT_KEYS = ("stale", "catalog")


def _field_error(exc: ValidationError) -> ValueError:
    """Turn a pydantic request-validation failure into a ValueError that NAMES
    the offending field (so it routes to the -32602 ``_err`` path with the field
    called out, matching the handlers' explicit ``ValueError("… required")``)."""

    first = exc.errors()[0]
    loc = ".".join(str(part) for part in first.get("loc", ())) or "params"
    return ValueError(f"invalid params: field '{loc}' {first.get('msg', 'is invalid')}")

# Lazily-built singletons (injectable in tests via set_service / set_hub).
_service_holder: dict[str, Any] = {"svc": None}
_hub_holder: dict[str, Any] = {"hub": None}


def get_service():
    if _service_holder["svc"] is None:
        from forecasting.pm.service import PMService

        _service_holder["svc"] = PMService()
    return _service_holder["svc"]


def set_service(service) -> None:
    _service_holder["svc"] = service


def get_hub():
    if _hub_holder["hub"] is None:
        from forecasting.api_keys import load_kalshi_credentials
        from forecasting.pm.stream import PMStreamHub

        _hub_holder["hub"] = PMStreamHub(kalshi_credentials=load_kalshi_credentials)
    return _hub_holder["hub"]


def set_hub(hub) -> None:
    _hub_holder["hub"] = hub


def shutdown() -> None:
    """Close every venue websocket — wired into the gateway's atexit."""
    hub = _hub_holder["hub"]
    if hub is not None:
        try:
            hub.shutdown()
        except Exception:  # pragma: no cover - best-effort shutdown
            logger.debug("pm stream hub shutdown failed")


def _err_code(exc: Exception) -> int:
    return -32602 if isinstance(exc, (ValueError, KeyError)) else -32000


def register(server) -> None:
    """Register every ``pm.*`` handler into the gateway dispatch table."""

    def _ok(rid, result):
        return server._ok(rid, result)

    def _err(rid, exc):
        return server._err(rid, _err_code(exc), f"pm error: {exc}")

    def _emit_tick(
        venue: str, market_id: str, kind: str, payload: dict, estimate: float | None = None
    ) -> None:
        server.write_json(
            {
                "jsonrpc": "2.0",
                "method": "event",
                "params": {
                    "type": "pm.tick",
                    "payload": {
                        "venue": venue,
                        "market_id": market_id,
                        "kind": kind,
                        # The ONLY probability a consumer may fold: the honest
                        # server-side estimate (canonical honest_yes_mid rule),
                        # null when this tick carries no estimate-grade info.
                        "estimate": estimate,
                        "payload": payload,
                    },
                },
            }
        )

    # ── list / search ────────────────────────────────────────────────────────

    def pm_list(rid, params):
        started = time.monotonic()
        venue = params.get("venue") or None
        query = params.get("query") or None
        tag = params.get("tag") or None
        try:
            limit = int(params.get("limit") or 40)
        except (TypeError, ValueError):
            limit = 40
        limit = max(1, min(limit, 200))
        try:
            svc = get_service()
            # Prefer the payload API (serialises server-side + reports whether
            # the rows were served stale from the disk-persisted tape cache on a
            # cold start). Fall back to the typed API for stubs/older services.
            payload = getattr(svc, "list_events_payload", None)
            if callable(payload):
                events, stale = payload(venue=venue, query=query, tag=tag, limit=limit)
            else:
                pairs = svc.list_events(venue=venue, query=query, tag=tag, limit=limit)
                events = [
                    {"event": event.to_dict(), "distribution": dist.to_dict()}
                    for event, dist in pairs
                ]
                stale = False
        except Exception as exc:
            logger.warning("pm.list failed: %s", exc)
            return _err(rid, exc)
        result = {"events": events, "count": len(events)}
        catalog_status = getattr(svc, "catalog_status", None)
        if callable(catalog_status):
            result["catalog"] = catalog_status()
        # Only present when actually stale — a warm/fresh tape stays byte-identical
        # to the pre-cache wire (and the UI shows the marker only when it's set).
        if stale:
            result["stale"] = True
        logger.info(
            "pm.list complete venue=%s query=%r events=%d stale=%s elapsed=%.3fs",
            venue or "all",
            query or "",
            len(events),
            stale,
            time.monotonic() - started,
        )
        return _ok(rid, result)

    # ── detail ───────────────────────────────────────────────────────────────

    def pm_detail(rid, params):
        venue = params.get("venue")
        event_id = params.get("event_id")
        if not venue or not event_id:
            return _err(rid, ValueError("venue and event_id are required"))
        try:
            event, dist = get_service().event_detail(str(venue), str(event_id))
        except Exception as exc:
            return _err(rid, exc)
        return _ok(rid, {"event": event.to_dict(), "distribution": dist.to_dict()})

    # ── book (always fresh) ──────────────────────────────────────────────────

    def pm_book(rid, params):
        venue = params.get("venue")
        market_id = params.get("market_id")
        if not venue or not market_id:
            return _err(rid, ValueError("venue and market_id are required"))
        try:
            book = get_service().orderbook(str(venue), str(market_id))
        except Exception as exc:
            return _err(rid, exc)
        return _ok(rid, {"book": book.to_dict()})

    # ── history ──────────────────────────────────────────────────────────────

    def pm_history(rid, params):
        venue = params.get("venue")
        market_id = params.get("market_id")
        if not venue or not market_id:
            return _err(rid, ValueError("venue and market_id are required"))
        interval = str(params.get("range") or params.get("interval") or "1w")
        series_ticker = params.get("series_ticker") or None
        # Pass period_interval through only when the caller set it explicitly;
        # otherwise let the service derive a sane candle granularity from the
        # range (daily for long windows) so the fetch stays under Kalshi's cap.
        raw_pi = params.get("period_interval")
        if raw_pi is None:
            period_interval: int | None = None
        else:
            try:
                period_interval = int(raw_pi)
            except (TypeError, ValueError):
                period_interval = None
        try:
            max_points = int(params.get("max_points") or 200)
        except (TypeError, ValueError):
            max_points = 200
        try:
            points = get_service().history(
                str(venue),
                str(market_id),
                series_ticker=str(series_ticker) if series_ticker else None,
                interval=interval,
                period_interval=period_interval,
                max_points=max(10, min(max_points, 1000)),
            )
        except Exception as exc:
            return _err(rid, exc)
        return _ok(rid, {"points": [p.to_dict() for p in points], "count": len(points)})

    # ── streaming ────────────────────────────────────────────────────────────

    def pm_stream_start(rid, params):
        venue = params.get("venue")
        market_ids = params.get("market_ids") or []
        if not venue:
            return _err(rid, ValueError("venue is required"))
        if not isinstance(market_ids, list):
            return _err(rid, ValueError("market_ids must be a list"))
        try:
            result = get_hub().start(str(venue), market_ids, _emit_tick)
        except Exception as exc:
            return _err(rid, exc)
        return _ok(rid, result.to_dict())

    def pm_stream_stop(rid, params):
        venue = params.get("venue")
        if not venue:
            return _err(rid, ValueError("venue is required"))
        market_ids = params.get("market_ids")
        if market_ids is not None and not isinstance(market_ids, list):
            return _err(rid, ValueError("market_ids must be a list or omitted"))
        try:
            result = get_hub().stop(str(venue), market_ids)
        except Exception as exc:
            return _err(rid, exc)
        return _ok(rid, result)

    def _rpc_model(method: str, handler):
        """Wrap a handler with protocol-model validation WITHOUT changing the
        wire.

        * requests are validated against the registered request model — an
          invalid payload short-circuits to the existing ``_err`` path with the
          field named (pydantic ``ValidationError`` subclasses ``ValueError`` so
          the code stays -32602);
        * a SUCCESS result is round-tripped through the response model and
          re-serialised via ``model_dump`` — for a well-formed venue payload this
          is byte-identical to the handler's ``to_dict`` output. A payload that
          does NOT validate (e.g. a test stub, or genuine latent drift) passes
          through UNCHANGED and is logged, so the wire can never regress.
        """

        spec = RPC_BY_METHOD.get(method)
        if spec is None:  # pragma: no cover - every pm.* method is registered
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
                        "pm response for %s did not validate; passing through unchanged",
                        method,
                    )
                    return resp
                dumped = model.model_dump(mode="json", exclude_none=spec.exclude_none)
                # Re-attach whitelisted out-of-model markers the wire is allowed
                # to carry but the generated response model doesn't declare (it
                # is extra='ignore', so model_dump silently drops them). pm.list's
                # cold-start `stale` flag is one such honest, additive signal.
                for extra in _PASSTHROUGH_RESULT_KEYS:
                    if extra in resp["result"] and extra not in dumped:
                        dumped[extra] = resp["result"][extra]
                return {**resp, "result": dumped}
            return resp

        wrapped.__name__ = getattr(handler, "__name__", method)
        return wrapped

    server.register_method("pm.list", _rpc_model("pm.list", pm_list))
    server.register_method("pm.detail", _rpc_model("pm.detail", pm_detail))
    server.register_method("pm.book", _rpc_model("pm.book", pm_book))
    server.register_method("pm.history", _rpc_model("pm.history", pm_history))
    server.register_method("pm.stream.start", _rpc_model("pm.stream.start", pm_stream_start))
    server.register_method("pm.stream.stop", _rpc_model("pm.stream.stop", pm_stream_stop))

    _prewarm_service()


def _prewarm_service() -> None:
    """At gateway boot, warm the PM service in a background thread so the first
    ``pm.list`` (and first '/' search) don't pay the cold fetch/scan on the
    request path. Skipped under pytest and when a service was injected (a stub),
    and fully best-effort — a warm failure never blocks boot."""
    import sys

    if "pytest" in sys.modules or _service_holder["svc"] is not None:
        return

    def _run() -> None:
        try:
            prewarm = getattr(get_service(), "prewarm", None)
            if callable(prewarm):
                prewarm()
        except Exception:  # pragma: no cover - warm is best-effort
            logger.debug("pm prewarm failed", exc_info=True)

    import threading

    threading.Thread(target=_run, name="pm-prewarm", daemon=True).start()


__all__ = ["register", "get_service", "set_service", "get_hub", "set_hub", "shutdown"]
