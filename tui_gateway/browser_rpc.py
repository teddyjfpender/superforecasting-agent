"""Gateway RPC for the browser-connect plane — carved from server.py.

Moves-only slice of the Wave-2 server family-split (docs/plans/2026-07-10-
modularization-program.md §W2.a). The ``browser.manage`` handler AND its entire
self-contained CDP helper cluster (``_resolve_browser_cdp_url`` /
``_is_default_local_cdp`` / ``_http_ok`` / ``_probe_urls`` / ``_normalize_cdp_url``
/ ``_failure_messages`` / ``_browser_connect`` / ``_browser_disconnect`` — 0
external references) moved here VERBATIM. The local ``rpc_validated`` decorator
captures the handler into ``_REGISTRARS``; ``server.py`` calls :func:`register`
(at load AND on ``importlib.reload`` — the pm_rpc/jobs_rpc sibling contract),
replaying it through the REAL ``server.rpc_validated`` so registration lands in
the same ``tui_gateway.server._methods`` dispatch dict — wire byte-identical.

``_emit`` is monkeypatched by the test suite → reached via the ``_core._emit``
call-time hop; ``_ok`` / ``_err`` are not patched — imported bare from core.
"""
from __future__ import annotations

import os
import time

from superforecasting_agent.configuration.browser import (
    parse_cdp_url, is_default_local_cdp as _is_default_local_cdp,
    normalize_cdp_url as _normalize_cdp_url,
)

import tui_gateway.server as _core
from tui_gateway.server import _err, _ok

_REGISTRARS: list[tuple[str, str, object]] = []


def rpc_validated(name: str):
    def _dec(fn):
        _REGISTRARS.append(("rpc_validated", name, fn))
        return fn

    return _dec


def register(server) -> None:
    """(Re-)register the carved browser.manage handler into ``server._methods``."""
    global _core, _err, _ok
    _core = server
    _err = server._err
    _ok = server._ok
    for kind, name, fn in _REGISTRARS:
        getattr(server, kind)(name)(fn)


__all__ = ["register"]
def _resolve_browser_cdp_url() -> str:
    """Return the configured browser CDP override without network I/O.

    ``/browser status`` must be fast — calling
    ``tools.browser_tool._get_cdp_override`` would invoke
    ``_resolve_cdp_override``, which performs an HTTP probe to
    ``.../json/version`` for discovery-style URLs.  That probe has
    a multi-second timeout and would block the TUI on a slow or
    unreachable host even though status only needs to report whether
    an override is set.

    Mirrors the env/config precedence of ``_get_cdp_override`` (env
    var first, then ``browser.cdp_url`` from config.yaml) without the
    websocket-resolution step, so the answer reflects user intent
    even when the configured host is not currently reachable.  The
    actual WS normalization happens in ``browser_navigate`` on the
    next tool call.
    """
    env_url = os.environ.get("BROWSER_CDP_URL", "").strip()
    if env_url:
        return env_url
    try:
        from superforecasting_agent.runtime.config import read_raw_config

        cfg = read_raw_config()
        browser_cfg = cfg.get("browser", {}) if isinstance(cfg, dict) else {}
        if isinstance(browser_cfg, dict):
            return str(browser_cfg.get("cdp_url", "") or "").strip()
    except Exception:
        pass
    return ""


def _http_ok(url: str, timeout: float) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def _probe_urls(parsed) -> list[str]:
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme)
    root = f"{scheme}://{parsed.netloc}".rstrip("/")
    return [f"{root}/json/version", f"{root}/json"]


def _failure_messages(url: str, port: int, system: str) -> list[str]:
    from superforecasting_agent.runtime.browser_connect import manual_chrome_debug_command

    command = manual_chrome_debug_command(port, system)
    hint = (
        ["Start a Chromium-family browser with remote debugging, then retry /browser connect:", command]
        if command
        else [
            "No supported Chromium-family browser executable was found in this environment.",
            f"Install one or start a Chromium-family browser with --remote-debugging-port={port}, then retry /browser connect.",
        ]
    )
    return [
        f"Browser CDP is not reachable at {url}.",
        *hint,
        "Browser not connected — start a Chromium-family browser with remote debugging and retry /browser connect",
    ]


@rpc_validated("browser.manage")
def _(rid, params: dict) -> dict:
    action = params.get("action", "status")

    if action == "status":
        url = _resolve_browser_cdp_url()
        return _ok(rid, {"connected": bool(url), "url": url})

    if action == "disconnect":
        return _browser_disconnect(rid)

    if action != "connect":
        return _err(rid, 4015, f"unknown action: {action}")

    return _browser_connect(rid, params)


def _browser_connect(rid, params: dict) -> dict:
    import platform

    from tools.browser_tool import cleanup_all_browsers

    url = params.get("url")

    sid = params.get("session_id") or ""
    system = platform.system()
    messages: list[str] = []

    def announce(message: str, *, level: str = "info") -> None:
        messages.append(message)
        # Without a session id the TUI prints `messages` from the
        # response; emitting an event would double-render. Only stream
        # progress when there's a real session to scope it to.
        if sid:
            _core._emit("browser.progress", sid, {"message": message, "level": level})

    try:
        parsed = parse_cdp_url(url)
    except ValueError as exc:
        return _err(rid, 4015, str(exc))
    url = parsed.geturl()
    port = parsed.port or (443 if parsed.scheme in {"https", "wss"} else 80)

    try:
        # ws[s]://.../devtools/browser/<id> endpoints (hosted CDP
        # providers) don't serve the HTTP discovery path; just check
        # TCP-level reachability and let browser_navigate handshake.
        if parsed.scheme in {"ws", "wss"} and parsed.path.startswith(
            "/devtools/browser/"
        ):
            import socket

            try:
                with socket.create_connection((parsed.hostname, port), timeout=2.0):
                    pass
            except OSError as e:
                return _err(rid, 5031, f"could not reach browser CDP at {url}: {e}")
        else:
            probes = _probe_urls(parsed)
            ok = any(_http_ok(p, timeout=2.0) for p in probes)

            if not ok and _is_default_local_cdp(parsed):
                from superforecasting_agent.runtime.browser_connect import try_launch_chrome_debug

                announce(
                    "Chromium-family browser isn't running with remote debugging — attempting to launch..."
                )

                if try_launch_chrome_debug(port, system):
                    for _ in range(20):
                        time.sleep(0.5)
                        if any(_http_ok(p, timeout=1.0) for p in probes):
                            ok = True
                            break

                if ok:
                    announce(f"Chromium-family browser launched and listening on port {port}")
                else:
                    for line in _failure_messages(url, port, system)[1:]:
                        announce(line, level="error")
                    return _ok(
                        rid, {"connected": False, "url": url, "messages": messages}
                    )
            elif not ok:
                return _err(rid, 5031, f"could not reach browser CDP at {url}")
            elif _is_default_local_cdp(parsed):
                announce(f"Chromium-family browser is already listening on port {port}")

        normalized = _normalize_cdp_url(parsed)

        # Order matters: reap sessions BEFORE publishing the new env
        # so an in-flight tool call sees the old supervisor closed,
        # then again AFTER so the default task's cached supervisor
        # is drained against the new URL.
        cleanup_all_browsers()
        os.environ["BROWSER_CDP_URL"] = normalized
        cleanup_all_browsers()
    except Exception as e:
        return _err(rid, 5031, str(e))

    payload: dict[str, object] = {"connected": True, "url": normalized}
    if messages:
        payload["messages"] = messages
    return _ok(rid, payload)


def _browser_disconnect(rid) -> dict:
    # Reap, drop the env override, reap again — closes the same swap
    # window covered by ``_browser_connect``.
    def reap() -> None:
        try:
            from tools.browser_tool import cleanup_all_browsers

            cleanup_all_browsers()
        except Exception:
            pass

    reap()
    os.environ.pop("BROWSER_CDP_URL", None)
    reap()
    return _ok(rid, {"connected": False})
