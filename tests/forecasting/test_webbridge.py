"""Smoke tests for the read-only forecast HTTP bridge (forecasting/webbridge.py).

Runs the real ``ForecastBridgeHandler`` on a ThreadingHTTPServer bound to a
free loopback port, against a throwaway ledger DB, and exercises every route.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from forecasting import ForecastLedger
from forecasting.webbridge import HOST, ForecastBridgeHandler

CRITERIA = "Resolves to the official value reported by the named source on the close date."


def _free_port() -> int:
    sock = socket.socket()
    sock.bind((HOST, 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _get(port: int, path: str) -> tuple[int, object]:
    url = f"http://{HOST}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 (loopback)
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    """A running bridge over a seeded throwaway ledger; yields (port, question_id)."""
    db = tmp_path / "forecasting.db"
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(db))

    ledger = ForecastLedger(db)
    question = ledger.create_question(
        title="Bridge smoke?",
        resolution_criteria=CRITERIA,
        domain="macro",
        topics=["smoke"],
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="seed",
    )

    port = _free_port()
    server = ThreadingHTTPServer((HOST, port), ForecastBridgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, question.id
    finally:
        server.shutdown()
        server.server_close()


def test_health_ok(bridge):
    port, _ = bridge
    status, body = _get(port, "/forecast/health")
    assert status == 200
    assert body == {"ok": True}


def test_workspace_returns_seeded_question(bridge):
    port, question_id = bridge
    status, body = _get(port, "/forecast/workspace?limit=75")
    assert status == 200
    assert isinstance(body, dict)
    assert "forecasts" in body
    ids = {f.get("id") for f in body["forecasts"]}
    assert question_id in ids


def test_dashboard_has_summary_and_output(bridge):
    port, _ = bridge
    status, body = _get(port, "/forecast/dashboard?limit=20")
    assert status == 200
    assert isinstance(body, dict)
    assert "summary" in body and "output" in body
    assert isinstance(body["output"], str)


def test_question_packet_is_a_real_object_not_double_encoded(bridge):
    port, question_id = bridge
    status, body = _get(port, f"/forecast/question/{question_id}")
    assert status == 200
    # The packet must be a JSON object, not a JSON *string* (the handler
    # json.loads the export to un-double-encode it).
    assert isinstance(body, dict)
    assert isinstance(body["packet"], dict)


def test_unknown_route_is_404(bridge):
    port, _ = bridge
    status, body = _get(port, "/forecast/nope")
    assert status == 404
    assert body == {"error": "not found"}


def test_missing_question_is_500(bridge):
    port, _ = bridge
    status, body = _get(port, "/forecast/question/does_not_exist")
    assert status == 500
    assert "error" in body
