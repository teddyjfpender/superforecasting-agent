"""SSRF protection tests for yuanbao_media.download_url().

download_url() fetches both model-supplied (outbound) and inbound image/file
URLs server-side via httpx (it is the live media path wired into the yuanbao
adapter's inbound/outbound handlers as ``media_download_url``). Without an
is_safe_url() pre-flight, a model response (or inbound message) containing
http://169.254.169.254/... would make the gateway fetch cloud-metadata
endpoints. These tests pin the guard.

Port of upstream d65468e7f, adapted to our fork: the unguarded download path
in our tree lives in gateway/platforms/yuanbao_media.py (tools/yuanbao_tools.py
is a sticker/DM toolset with no URL-fetch surface).
"""

import pytest

from gateway.platforms.yuanbao_media import download_url


class TestDownloadUrlSSRF:
    @pytest.mark.asyncio
    async def test_metadata_endpoint_blocked(self):
        with pytest.raises(ValueError, match="SSRF protection"):
            await download_url("http://169.254.169.254/latest/meta-data/")

    @pytest.mark.asyncio
    async def test_loopback_blocked(self):
        with pytest.raises(ValueError, match="SSRF protection"):
            await download_url("http://127.0.0.1:8080/secret")

    @pytest.mark.asyncio
    async def test_private_range_blocked(self):
        with pytest.raises(ValueError, match="SSRF protection"):
            await download_url("http://192.168.1.1/admin/logo.png")

    @pytest.mark.asyncio
    async def test_non_http_scheme_blocked(self):
        with pytest.raises(ValueError, match="SSRF protection"):
            await download_url("file:///etc/passwd")

    @pytest.mark.asyncio
    async def test_public_url_passes_guard_then_fetches(self, monkeypatch):
        """A public URL with no redirect clears the SSRF guard and fetches.

        Drives the real download path (httpx stubbed) and asserts a public,
        non-redirecting response is downloaded — the guard does not reject it.
        """
        import gateway.platforms.yuanbao_media as ym

        client = _StubClient(
            monkeypatch,
            routes={
                "https://example.com/image.png": _StubResp(
                    headers={"content-type": "image/png", "content-length": "3"},
                    body=b"png",
                ),
            },
        )

        # is_safe_url is the real implementation here; example.com is public.
        # Force the URL-safety oracle to allow the public host without DNS so
        # the test is hermetic, and block known-internal addresses behaviorally.
        from tools import url_safety
        monkeypatch.setattr(
            url_safety,
            "is_safe_url",
            lambda u: not _is_internal(u),
        )

        data, ct = await download_url("https://example.com/image.png")
        assert data == b"png"
        assert ct == "image/png"

    @pytest.mark.asyncio
    async def test_public_to_public_redirect_succeeds(self, monkeypatch):
        """A public → public 302 is followed and the final body is returned."""
        _StubClient(
            monkeypatch,
            routes={
                "https://example.com/start": _StubResp(
                    status_code=302,
                    headers={"location": "https://cdn.example.com/real.png"},
                ),
                "https://cdn.example.com/real.png": _StubResp(
                    headers={"content-type": "image/png", "content-length": "3"},
                    body=b"png",
                ),
            },
        )
        from tools import url_safety
        monkeypatch.setattr(
            url_safety, "is_safe_url", lambda u: not _is_internal(u)
        )

        data, ct = await download_url("https://example.com/start")
        assert data == b"png"
        assert ct == "image/png"

    @pytest.mark.asyncio
    async def test_public_redirect_to_metadata_blocked(self, monkeypatch):
        """A public URL that 302→cloud-metadata is blocked at the redirect hop.

        This is the real SSRF hole: the initial URL is public (passes the
        pre-flight guard) but the server redirects to the AWS/GCP metadata
        endpoint. The manual redirect loop must re-validate and RAISE.
        """
        _StubClient(
            monkeypatch,
            routes={
                "https://example.com/innocent.png": _StubResp(
                    status_code=302,
                    headers={"location": "http://169.254.169.254/latest/meta-data/"},
                ),
                # Should never be reached; present to prove we DON'T fetch it.
                "http://169.254.169.254/latest/meta-data/": _StubResp(
                    body=b"SECRET-CREDENTIALS",
                ),
            },
        )
        from tools import url_safety
        monkeypatch.setattr(
            url_safety, "is_safe_url", lambda u: not _is_internal(u)
        )

        with pytest.raises(ValueError, match="SSRF protection"):
            await download_url("https://example.com/innocent.png")

    @pytest.mark.asyncio
    async def test_public_redirect_to_private_blocked(self, monkeypatch):
        """A public URL that 302→a loopback/private address is blocked."""
        _StubClient(
            monkeypatch,
            routes={
                "https://example.com/innocent.png": _StubResp(
                    status_code=302,
                    headers={"location": "http://127.0.0.1:8080/secret"},
                ),
                "http://127.0.0.1:8080/secret": _StubResp(body=b"SECRET"),
            },
        )
        from tools import url_safety
        monkeypatch.setattr(
            url_safety, "is_safe_url", lambda u: not _is_internal(u)
        )

        with pytest.raises(ValueError, match="SSRF protection"):
            await download_url("https://example.com/innocent.png")


# ---------------------------------------------------------------------------
# Behavioral httpx stubs: a tiny routing client that returns canned responses
# and surfaces redirects via is_redirect / the Location header, exactly how
# the production redirect loop consumes them.
# ---------------------------------------------------------------------------

_INTERNAL_MARKERS = ("169.254.169.254", "127.0.0.1", "localhost", "192.168.", "10.", "::1")


def _is_internal(url: str) -> bool:
    return any(marker in url for marker in _INTERNAL_MARKERS)


class _StubResp:
    def __init__(self, *, status_code: int = 200, headers=None, body: bytes = b""):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308)

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=None, response=None
            )

    async def aiter_bytes(self, _n):
        yield self._body


class _StreamCtx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class _StubClient:
    """Installs itself as httpx.AsyncClient for the duration of the test."""

    def __init__(self, monkeypatch, routes: dict):
        import gateway.platforms.yuanbao_media as ym

        self.routes = routes
        self.requested: list[str] = []
        monkeypatch.setattr(ym.httpx, "AsyncClient", lambda *a, **kw: self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def _resolve(self, url: str) -> _StubResp:
        self.requested.append(url)
        if url not in self.routes:
            raise AssertionError(f"unexpected request to {url}")
        return self.routes[url]

    async def head(self, url):
        return self._resolve(str(url))

    def stream(self, method, url, **kw):
        return _StreamCtx(self._resolve(str(url)))
