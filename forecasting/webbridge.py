"""Read-only HTTP bridge exposing Superforecasting Agent forecast data.

A tiny stdlib-only HTTP server that serves the forecasting ledger's read
surface (workspace, dashboard, per-question packet) to the web terminal. It
mirrors the JSON-RPC ``forecast.*`` handlers in ``tui_gateway/server.py`` but
speaks plain HTTP/GET so a browser-based terminal can fetch the same data
without a websocket round trip.

Design notes
------------
* **stdlib only** — ``http.server.ThreadingHTTPServer`` +
  ``BaseHTTPRequestHandler``. No third-party deps.
* **Read-only** — only ``GET`` (and CORS-preflight ``OPTIONS``) are served.
  Every other method or unknown path returns ``404`` JSON.
* **Thread affinity** — ``ForecastLedger`` wraps a ``sqlite3`` connection,
  which is bound to the thread that created it. Under ``ThreadingHTTPServer``
  each request runs on its own thread, so we construct a *fresh*
  ``ForecastLedger`` per request rather than sharing one. ``build_*`` helpers
  create their own ledger when ``ledger=None``, so we just pass ``limit``.
* **Lazy imports** — ``forecasting.*`` is imported inside each handler (matching
  the gateway) so importing this module is cheap and a partially-broken
  forecasting install surfaces as a clean HTTP 500 rather than an import crash.

Run with::

    python3 -m forecasting.webbridge

Bind host is always ``127.0.0.1``; the port comes from ``FORECAST_BRIDGE_PORT``
(default ``8787``).
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HOST = "127.0.0.1"
DEFAULT_PORT = 8787

logger = logging.getLogger("forecasting.webbridge")


def _resolve_port() -> int:
    """Return the bridge port from ``FORECAST_BRIDGE_PORT`` or the default."""
    from forecasting import appconfig

    raw = (appconfig.get_str("FORECAST_BRIDGE_PORT", "") or "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid FORECAST_BRIDGE_PORT=%r; using %d", raw, DEFAULT_PORT)
        return DEFAULT_PORT


class ForecastBridgeHandler(BaseHTTPRequestHandler):
    """Serve the forecasting read surface over HTTP/GET."""

    server_version = "ForecastBridge/1.0"

    # ------------------------------------------------------------------ #
    # Response helpers
    # ------------------------------------------------------------------ #
    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _not_found(self) -> None:
        self._send_json(404, {"error": "not found"})

    def _server_error(self, exc: BaseException) -> None:
        self._send_json(500, {"error": str(exc)})

    # ------------------------------------------------------------------ #
    # HTTP verbs
    # ------------------------------------------------------------------ #
    def do_OPTIONS(self) -> None:  # noqa: N802 (http.server naming)
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        try:
            if path == "/forecast/health":
                self._handle_health()
            elif path == "/forecast/workspace":
                self._handle_workspace(query)
            elif path == "/forecast/dashboard":
                self._handle_dashboard(query)
            elif path.startswith("/forecast/question/"):
                question_id = unquote(path[len("/forecast/question/") :])
                self._handle_question(question_id)
            else:
                self._not_found()
        except Exception as exc:  # noqa: BLE001 — surface any handler error as 500
            self._server_error(exc)

    # ------------------------------------------------------------------ #
    # Route handlers (lazy-import forecasting.* inside each, like the gateway)
    # ------------------------------------------------------------------ #
    def _handle_health(self) -> None:
        self._send_json(200, {"ok": True})

    def _handle_workspace(self, query: dict[str, list[str]]) -> None:
        from forecasting.dashboard import build_workspace_payload

        # Default high so the desk loads the full active book (the client filters
        # locally; a small cap silently hides the oldest forecasts).
        limit = _query_int(query, "limit", 1000)
        # build_workspace_payload builds its own ledger when ledger=None,
        # so per-request thread affinity is handled for us.
        payload = build_workspace_payload(limit=limit)
        self._send_json(200, payload)

    def _handle_dashboard(self, query: dict[str, list[str]]) -> None:
        from forecasting.dashboard import build_dashboard_summary, render_dashboard_text

        limit = _query_int(query, "limit", 20)
        summary = build_dashboard_summary(limit=limit)
        self._send_json(
            200,
            {"summary": summary, "output": render_dashboard_text(summary)},
        )

    def _handle_question(self, question_id: str) -> None:
        question_id = question_id.strip()
        if not question_id:
            self._not_found()
            return

        from forecasting.ledger import ForecastLedger

        # Fresh ledger per request: sqlite3 connections have thread affinity
        # and ThreadingHTTPServer dispatches each request on its own thread.
        ledger = ForecastLedger()
        # export_question(fmt="json") returns a JSON *string*; json.loads it so
        # the packet is embedded as a real object (not double-encoded).
        packet = json.loads(ledger.export_question(question_id, fmt="json"))
        self._send_json(200, {"packet": packet})

    # ------------------------------------------------------------------ #
    # Logging — silence the default stderr access log; route to logging.
    # ------------------------------------------------------------------ #
    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
        logger.debug("%s - %s", self.address_string(), fmt % args)


def _query_int(query: dict[str, list[str]], key: str, default: int) -> int:
    """Parse an int query param, falling back to ``default`` on absence/garbage."""
    values = query.get(key)
    if not values:
        return default
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return default


def serve(port: int | None = None) -> None:
    """Start the bridge and block, serving requests until interrupted."""
    resolved = port if port is not None else _resolve_port()
    httpd = ThreadingHTTPServer((HOST, resolved), ForecastBridgeHandler)
    print(f"forecast bridge on http://{HOST}:{resolved}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
