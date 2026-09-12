"""Callbacks operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _xai_validate_loopback_redirect_uri(redirect_uri: str) -> tuple[str, int, str]:
    parsed = _core.urlparse(redirect_uri)
    if parsed.scheme != "http":
        raise _core.AuthError(
            "xAI OAuth redirect_uri must use http://127.0.0.1.",
            provider="xai-oauth",
            code="xai_redirect_invalid",
        )
    host = parsed.hostname or ""
    if host != _core.XAI_OAUTH_REDIRECT_HOST:
        raise _core.AuthError(
            "xAI OAuth redirect_uri must point to 127.0.0.1.",
            provider="xai-oauth",
            code="xai_redirect_invalid",
        )
    if not parsed.port:
        raise _core.AuthError(
            "xAI OAuth redirect_uri must include an explicit localhost port.",
            provider="xai-oauth",
            code="xai_redirect_invalid",
        )
    return host, parsed.port, parsed.path or "/"


def _xai_callback_cors_origin(origin: _core.Optional[str]) -> str:
    # CORS allowlist for the loopback callback.  Only xAI's own auth origins
    # are accepted; the redirect_uri itself is bound to 127.0.0.1 and gated by
    # PKCE+state, so additional dev/3p origins are not needed here.
    allowed = {
        "https://accounts.x.ai",
        "https://auth.x.ai",
    }
    return origin if origin in allowed else ""


def _make_xai_callback_handler(
    expected_path: str,
) -> tuple[type[_core.BaseHTTPRequestHandler], dict[str, _core.Any]]:
    result: dict[str, _core.Any] = {
        "code": None,
        "state": None,
        "error": None,
        "error_description": None,
    }
    result_lock = _core.threading.Lock()

    class _XAICallbackHandler(_core.BaseHTTPRequestHandler):
        def _maybe_write_cors_headers(self) -> None:
            origin = self.headers.get("Origin")
            allow_origin = _core._xai_callback_cors_origin(origin)
            if allow_origin:
                self.send_header("Access-Control-Allow-Origin", allow_origin)
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Vary", "Origin")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._maybe_write_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = _core.urlparse(self.path)
            if parsed.path != expected_path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found.")
                return

            params = _core.parse_qs(parsed.query)
            incoming = {
                "code": params.get("code", [None])[0],
                "state": params.get("state", [None])[0],
                "error": params.get("error", [None])[0],
                "error_description": params.get("error_description", [None])[0],
            }

            # Treat a hit on the callback path with neither `code` nor `error`
            # as a missing OAuth callback (e.g. xAI's auth backend failed to
            # redirect and the user navigated to the bare loopback URL by hand).
            # Show an explicit "not received" page rather than the success page —
            # otherwise the browser claims authorization succeeded while the CLI
            # is still waiting for a real callback and eventually times out.
            if incoming["code"] is None and incoming["error"] is None:
                self.send_response(400)
                self._maybe_write_cors_headers()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                body = (
                    "<html><body>"
                    "<h1>xAI authorization not received.</h1>"
                    "<p>No authorization code was present in this callback URL. "
                    "Return to the terminal and re-run "
                    f"<code>{_core._PRIMARY_CLI} auth add xai-oauth</code> to retry.</p>"
                    "</body></html>"
                )
                self.wfile.write(body.encode("utf-8"))
                return

            # ThreadingHTTPServer allows a fallback/manual callback to complete
            # while a browser connection is stuck.  Once we have a terminal
            # OAuth result (code or error), keep the first one so a later
            # concurrent/invalid callback cannot overwrite state before
            # validation in _xai_oauth_loopback_login().
            with result_lock:
                if not (result["code"] or result["error"]):
                    result.update(incoming)

            self.send_response(200)
            self._maybe_write_cors_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if incoming["error"]:
                body = "<html><body><h1>xAI authorization failed.</h1>You can close this tab.</body></html>"
            else:
                body = "<html><body><h1>xAI authorization received.</h1>You can close this tab.</body></html>"
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, format: str, *args: _core.Any) -> None:  # noqa: A003
            return

    return _XAICallbackHandler, result


def _xai_start_callback_server(
    preferred_port: int = _core.XAI_OAUTH_REDIRECT_PORT,
) -> tuple[_core.HTTPServer, _core.threading.Thread, dict[str, _core.Any], str]:
    host = _core.XAI_OAUTH_REDIRECT_HOST
    expected_path = _core.XAI_OAUTH_REDIRECT_PATH
    handler_cls, result = _core._make_xai_callback_handler(expected_path)

    class _ReuseHTTPServer(_core.ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    ports_to_try = [preferred_port]
    if preferred_port != 0:
        ports_to_try.append(0)
    server = None
    last_error: _core.Optional[OSError] = None
    for port in ports_to_try:
        try:
            server = _ReuseHTTPServer((host, port), handler_cls)
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        raise _core.AuthError(
            f"Could not bind xAI callback server on {host}:{preferred_port}: {last_error}",
            provider="xai-oauth",
            code="xai_callback_bind_failed",
        ) from last_error

    actual_port = int(server.server_address[1])
    redirect_uri = f"http://{host}:{actual_port}{expected_path}"
    thread = _core.threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.1},
        daemon=True,
    )
    thread.start()
    return server, thread, result, redirect_uri


def _xai_wait_for_callback(
    server: _core.HTTPServer,
    thread: _core.threading.Thread,
    result: dict[str, _core.Any],
    *,
    timeout_seconds: float = 180.0,
) -> dict[str, _core.Any]:
    deadline = _core.time.monotonic() + max(5.0, timeout_seconds)
    try:
        while _core.time.monotonic() < deadline:
            if result["code"] or result["error"]:
                return result
            _core.time.sleep(0.1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)
    raise _core.AuthError(
        "xAI authorization timed out waiting for the local callback.",
        provider="xai-oauth",
        code="xai_callback_timeout",
    )


def _is_remote_session() -> bool:
    """Detect environments where loopback OAuth can't reach the local browser.

    Historically only SSH was checked, but #26923 surfaced that
    **browser-only remote consoles** (GCP Cloud Shell, GitHub
    Codespaces, AWS EC2 Instance Connect, Gitpod, Replit, etc.) hit
    the exact same problem — the user has a browser on their laptop
    but the loopback listener is bound on the remote VM that the
    laptop's browser can't reach.  These environments typically don't
    set ``SSH_CLIENT`` / ``SSH_TTY``, so the SSH-only check left
    them with no guidance and no fallback.
    """
    if _core.os.getenv("SSH_CLIENT") or _core.os.getenv("SSH_TTY"):
        return True
    # Browser-only remote IDEs / cloud shells.  Keep this list narrow
    # (well-known, documented env vars set by the host platform) so
    # we don't falsely trip on a developer's local shell.
    for var in (
        "CLOUD_SHELL",  # GCP Cloud Shell
        "CODESPACES",  # GitHub Codespaces
        "CODESPACE_NAME",  # GitHub Codespaces (alt)
        "GITPOD_WORKSPACE_ID",  # Gitpod
        "REPL_ID",  # Replit
        "STACKBLITZ",  # StackBlitz
    ):
        if _core.os.getenv(var):
            return True
    return False


def _parse_pasted_callback(raw: str) -> dict:
    """Parse a pasted callback URL / query string into the loopback shape.

    Accepts any of:

    * full URL:  ``http://127.0.0.1:56121/callback?code=abc&state=xyz``
    * bare query string:  ``?code=abc&state=xyz``  or  ``code=abc&state=xyz``
    * bare code (no state, only used when the upstream omits state):
      ``abc-the-code-value``

    Returns ``{"code", "state", "error", "error_description"}`` with
    missing keys set to ``None`` so the loopback callsites can keep
    using the same validation path (state check, error check, etc.)
    they already use for the HTTP server output.  Regression for
    #26923 — formalises the curl-the-callback-URL workaround the
    reporter used while waiting for upstream support.
    """
    stripped = raw.strip()
    result: dict = {
        "code": None,
        "state": None,
        "error": None,
        "error_description": None,
    }
    if not stripped:
        return result
    query = ""
    if stripped.startswith(("http://", "https://")):
        try:
            parsed = _core.urlparse(stripped)
        except Exception:
            return result
        query = parsed.query or ""
    elif stripped.startswith("?"):
        query = stripped[1:]
    elif "=" in stripped:
        # Looks like a bare query fragment (``code=...&state=...``).
        query = stripped
    else:
        # Treat as a bare opaque code value with no state.
        result["code"] = stripped
        return result
    params = _core.parse_qs(query, keep_blank_values=False)
    for key in ("code", "state", "error", "error_description"):
        values = params.get(key)
        if values:
            result[key] = values[0]
    return result


def _ssh_user_at_host() -> str:
    """Return best-effort 'user@hostname' for the SSH tunnel hint command.

    Falls back to placeholder tokens when the values cannot be determined so
    the hint is always syntactically valid even if not copy-pasteable.
    """
    try:
        import socket as _socket

        hostname = _socket.gethostname() or "<this-host>"
    except OSError:
        hostname = "<this-host>"
    user = _core.os.getenv("USER") or _core.os.getenv("LOGNAME") or "<user>"
    return f"{user}@{hostname}"
