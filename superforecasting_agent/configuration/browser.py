"""Browser endpoint validation shared by command and transport adapters."""

from urllib.parse import ParseResult, urlparse

DEFAULT_BROWSER_CDP_PORT = 9222
DEFAULT_BROWSER_CDP_URL = f"http://127.0.0.1:{DEFAULT_BROWSER_CDP_PORT}"


def is_default_local_cdp(parsed: ParseResult) -> bool:
    """Recognize discovery aliases without collapsing concrete WS endpoints."""
    return (
        parsed.scheme in {"http", "ws"}
        and parsed.hostname in {"127.0.0.1", "localhost"}
        and (parsed.port or 80) == DEFAULT_BROWSER_CDP_PORT
        and parsed.path in {"", "/", "/json", "/json/version"}
        and not parsed.username
        and not parsed.password
        and not parsed.query
    )


def parse_cdp_url(value: object = None) -> ParseResult:
    if value is not None and not isinstance(value, str):
        raise ValueError("browser url must be a string")
    url = (value or "").strip() or DEFAULT_BROWSER_CDP_URL
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
        if parsed.scheme not in {"http", "https", "ws", "wss"}:
            raise ValueError(
                "unsupported browser url scheme (expected http, https, ws or wss)"
            )
        if not parsed.hostname:
            raise ValueError("missing host in browser url")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("invalid port in browser url") from exc
        if port == 0:
            raise ValueError("invalid port in browser url")
    except ValueError as exc:
        raise ValueError(f"Invalid browser endpoint: {exc}") from exc
    return urlparse(DEFAULT_BROWSER_CDP_URL) if is_default_local_cdp(parsed) else parsed


def normalize_cdp_url(parsed: ParseResult) -> str:
    """Retain concrete endpoint identity; remove discovery resource paths."""
    if parsed.path.startswith("/devtools/browser/"):
        return parsed.geturl()
    return parsed._replace(path="", params="", query="", fragment="").geturl()
