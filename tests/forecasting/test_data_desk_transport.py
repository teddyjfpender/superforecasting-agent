"""Bounded body loading, quota feedback, and credential-safe diagnostics."""

from contextlib import contextmanager

import httpx
import pytest

from forecasting.marketdata import provider


@pytest.fixture(autouse=True)
def clear_pacing():
    provider._next_request.clear()
    provider._cooldown.clear()
    yield
    provider._next_request.clear()
    provider._cooldown.clear()


def transport(monkeypatch, status, chunks, headers=None):
    closed = []

    class Response:
        status_code = status

        def __init__(self):
            self.headers = headers or {}

        def iter_raw(self, **kwargs):
            yield from chunks

    @contextmanager
    def stream(*args, **kwargs):
        try:
            yield Response()
        finally:
            closed.append(True)

    monkeypatch.setattr(provider.httpx, "stream", stream)
    return closed


def test_body_cap_is_checked_before_json_parsing_and_stream_is_closed(monkeypatch):
    monkeypatch.setattr(provider, "MAX_RESPONSE_BYTES", 8)
    closed = transport(monkeypatch, 200, [b'{"first":', b'"oversized"}'])
    with pytest.raises(provider.ProviderFailure, match="exceeds"):
        provider.default_get_json("https://example.test/data")
    assert closed == [True]


def test_rate_limit_blocks_followup_requests_without_retrying_credentials(monkeypatch):
    closed = transport(monkeypatch, 429, [], {"Retry-After": "120"})
    with pytest.raises(provider.ProviderFailure) as failure:
        provider.default_get_json("https://example.test/token/SECRET")
    assert failure.value.status == "rate_limited" and failure.value.retry_after == 120
    with pytest.raises(provider.ProviderFailure, match="cooling down"):
        provider.default_get_json("https://example.test/token/SECRET")
    assert closed == [True]
    assert "SECRET" not in str(failure.value)


def test_network_exception_does_not_expose_the_request_url(monkeypatch):
    def stream(*args, **kwargs):
        raise httpx.ConnectError("token=SECRET")

    monkeypatch.setattr(provider.httpx, "stream", stream)
    with pytest.raises(provider.ProviderFailure) as failure:
        provider.default_get_json("https://example.test/?token=SECRET")
    assert failure.value.status == "unavailable"
    assert "SECRET" not in str(failure.value)


def test_compressed_body_is_rejected_before_decompression(monkeypatch):
    closed = transport(monkeypatch, 200, [], {"Content-Encoding": "gzip"})
    with pytest.raises(provider.ProviderFailure, match="uncompressed"):
        provider.default_get_json("https://example.test/data")
    assert closed == [True]
