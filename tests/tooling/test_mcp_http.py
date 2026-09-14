"""The SDK must never receive an oversized body or SSE event to buffer."""

from functools import partial

import httpx
import pytest

from superforecasting_agent.tooling.mcp_http import bound_response, identity_encoding


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers,chunks,accepted",
    [
        ({}, [b"1234", b"5678"], True),
        ({}, [b"1234", b"56789"], False),
        ({"content-length": "9"}, [], False),
        ({"content-encoding": "gzip"}, [b"x"], False),
        ({"content-type": "text/event-stream"}, [b"data:x\n\n"] * 100, True),
        (
            {"content-type": "text/event-stream"},
            [b"data:x\r", b"\n\r", b"\n"] * 100,
            True,
        ),
        ({"content-type": "text/event-stream"}, [b"data:x\r", b"\n", b"x:x"], False),
        ({"content-type": "text/event-stream"}, [b"data:x\r\r"] * 100, True),
        ({"content-type": "text/event-stream"}, [b"data:", b"xxxx"], False),
    ],
)
async def test_cap_before_sdk_consumption_and_close(headers, chunks, accepted):
    stream = Chunks(chunks)

    def serve(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers=headers, stream=stream)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(serve),
        event_hooks={
            "request": [identity_encoding],
            "response": [partial(bound_response, limit=8)],
        },
    ) as client:
        if accepted:
            response = await client.get("https://fixture.invalid/mcp")
            assert response.content == b"".join(chunks)
        else:
            with pytest.raises(httpx.ReadError, match="MCP"):
                await client.get("https://fixture.invalid/mcp")
    assert stream.closed


@pytest.mark.asyncio
async def test_factory_preserves_auth_hooks_and_caps_before_consuming_hooks(
    monkeypatch,
):
    from superforecasting_agent.tooling import mcp_http

    stream = Chunks([b"123456789"])
    observed = []

    async def consume(response):
        observed.append("hook entered")
        await response.aread()
        observed.append("parsed")

    monkeypatch.setattr(mcp_http, "bound_response", partial(bound_response, limit=8))

    def serve(request):
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(200, stream=stream)

    async with mcp_http.client(
        transport=httpx.MockTransport(serve),
        auth=("user", "key"),
        event_hooks={"response": [consume]},
    ) as client:
        with pytest.raises(httpx.ReadError, match="MCP"):
            await client.get("https://fixture.invalid/mcp")
    assert observed == ["hook entered"] and stream.closed
