"""Outbound message transports for the forecast-native notification surfaces.

These are the thin, stdlib-only clients the ``forecast connect`` flows and the
notification router (:mod:`forecasting.notify`) ride to reach a chat surface.
They are deliberately separate from the gateway's inbound platform adapters
(``gateway/platforms/*``): the gateway owns bidirectional long-poll / socket
sessions inside the running gateway process, while these transports are simple
request/response clients any CLI invocation can call directly — no event loop,
no optional heavy deps (``python-telegram-bot`` / ``slack-bolt``), and a single
module-level HTTP seam that tests monkeypatch instead of hitting the wire.
"""
