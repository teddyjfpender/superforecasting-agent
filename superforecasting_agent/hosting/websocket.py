"""Authenticated WebSocket access to the shared forecast runtime protocol."""

from __future__ import annotations

import hmac
from collections.abc import Collection

from fastapi import FastAPI, WebSocket


def create_app(*, token: str, allowed_origins: Collection[str] = ()) -> FastAPI:
    """Build a headless protocol host without importing the dashboard application.

    One process hosts one active profile. Native clients normally omit Origin;
    browser clients must use an explicitly permitted origin. Credentials may be
    supplied by Authorization or the existing terminal client's token query field.
    """
    if not isinstance(token, str) or not token.strip():
        raise ValueError("A nonempty host authentication token is required")
    if isinstance(allowed_origins, str):
        raise ValueError("allowed_origins must be a collection of exact origins")
    origins = frozenset(allowed_origins)
    if any(not origin or origin == "*" for origin in origins):
        raise ValueError(
            "Allowed origins must be explicit; wildcard origins are unsupported"
        )
    expected = token.encode()
    app = FastAPI(
        title="Superforecasting Agent Host",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.websocket("/api/ws")
    async def websocket(ws: WebSocket) -> None:
        origin = ws.headers.get("origin")
        if origin is not None and origin not in origins:
            await ws.close(code=4403)
            return
        authorization = ws.headers.get("authorization")
        if authorization is not None:
            scheme, _, credential = authorization.partition(" ")
            supplied = credential if scheme.lower() == "bearer" else ""
        else:
            supplied = ws.query_params.get("token", "")
        if not hmac.compare_digest(supplied.encode(), expected):
            await ws.close(code=4401)
            return
        from tui_gateway.ws import handle_ws

        await handle_ws(ws)

    return app
