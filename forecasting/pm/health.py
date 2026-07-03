"""Prediction-market health snapshot for the ``forecast doctor`` fold-in.

Read-only and fail-safe by construction: it inspects *configuration and cache
state*, and only probes the network when the caller explicitly asks (default
off, so the doctor audit and the test suite never touch the wire).
"""

from __future__ import annotations

from typing import Any


def _kalshi_key_present() -> bool:
    try:
        from forecasting.api_keys import load_kalshi_credentials

        return load_kalshi_credentials() is not None
    except Exception:
        return False


def _cryptography_available() -> bool:
    try:  # pragma: no cover - trivial probe
        import cryptography  # noqa: F401

        return True
    except Exception:
        return False


def _cache_counts(service) -> dict[str, int]:
    """How many entries each PMService TTL cache currently holds, by prefix."""
    counts = {"list": 0, "detail": 0, "history": 0}
    try:
        cache = getattr(service, "_cache", None)
        entries = getattr(cache, "_entries", {}) if cache is not None else {}
        for key in entries:
            prefix = str(key).split(":", 1)[0]
            if prefix in counts:
                counts[prefix] += 1
    except Exception:
        pass
    return counts


def build_pm_doctor(
    *,
    service: Any | None = None,
    hub: Any | None = None,
    check_network: bool = False,
) -> dict[str, Any]:
    """A pm sibling for the doctor report: streaming readiness + cache state.

    ``stream state`` is only meaningful when a live hub is passed (the gateway
    process holds it); the CLI doctor reports readiness instead. Every field is
    computed defensively so a probe failure never fails the audit.
    """

    from forecasting.pm.stream import websocket_available

    ws_ok = False
    try:
        ws_ok = websocket_available()
    except Exception:
        ws_ok = False

    kalshi_key = _kalshi_key_present()
    crypto_ok = _cryptography_available()

    venues: dict[str, dict[str, Any]] = {
        "polymarket": {
            "market_data": "public",
            "stream_ready": ws_ok,
            "stream_reason": None if ws_ok else "websocket library not installed",
        },
        "kalshi": {
            "market_data": "public",
            "stream_ready": ws_ok and kalshi_key and crypto_ok,
            "stream_reason": _kalshi_stream_reason(ws_ok, kalshi_key, crypto_ok),
        },
    }

    report: dict[str, Any] = {
        "websocket_lib": ws_ok,
        "cryptography": crypto_ok,
        "kalshi_key_present": kalshi_key,
        "venues": venues,
    }

    if service is not None:
        report["cache_counts"] = _cache_counts(service)

    if hub is not None:
        try:
            report["stream_state"] = hub.active()
        except Exception:
            report["stream_state"] = {}

    if check_network:  # pragma: no cover - opt-in live probe
        report["reachable"] = _probe_reachability()

    return report


def _kalshi_stream_reason(ws_ok: bool, key: bool, crypto: bool) -> str | None:
    if not ws_ok:
        return "websocket library not installed"
    if not key:
        return "no key — run `forecast api-key set kalshi`"
    if not crypto:
        return "install 'cryptography' to sign the handshake"
    return None


def _probe_reachability() -> dict[str, bool]:  # pragma: no cover - live network
    from forecasting.pm._http import PMHTTPError, http_get_json
    from forecasting.pm.kalshi import KALSHI_BASE
    from forecasting.pm.polymarket import GAMMA_BASE

    out: dict[str, bool] = {}
    for venue, url in (
        ("polymarket", f"{GAMMA_BASE}/events?limit=1"),
        ("kalshi", f"{KALSHI_BASE}/events?limit=1"),
    ):
        try:
            http_get_json(url, label=venue, timeout=5.0)
            out[venue] = True
        except (PMHTTPError, Exception):
            out[venue] = False
    return out


__all__ = ["build_pm_doctor"]
