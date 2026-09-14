"""The real SDK provider never emits a refresh grant to an unbound destination."""

import asyncio
import json

import httpx
import pytest
from mcp.client.auth.exceptions import OAuthTokenError
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)

from tools.mcp_oauth import AgentTokenStorage, build_oauth_auth
from tools.mcp_oauth_manager import _AGENT_PROVIDER_CLS


def metadata(issuer="https://issuer.example/", endpoint="https://issuer.example/token"):
    return OAuthMetadata(
        issuer=issuer,
        authorization_endpoint=issuer + "authorize",
        token_endpoint=endpoint,
        response_types_supported=["code"],
    )


async def unused(*args):
    raise AssertionError("No interactive authorization should run in this test")


def provider(storage, server_url="https://resource.example/mcp"):
    return _AGENT_PROVIDER_CLS(
        server_url=server_url,
        server_name="test",
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://localhost:8080/callback"]
        ),
        storage=storage,
        redirect_handler=unused,
        callback_handler=unused,
    )


async def seed(storage, bound=True):
    meta = metadata()
    if bound:
        storage.bind_authorization_server(str(meta.issuer), str(meta.token_endpoint))
    await storage.set_tokens(
        OAuthToken(
            access_token="access",
            refresh_token="refresh",
            token_type="Bearer",
            expires_in=3600,
        )
    )
    await storage.set_client_info(
        OAuthClientInformationFull(
            client_id="client", redirect_uris=["http://localhost:8080/callback"]
        )
    )
    storage.save_oauth_metadata(meta)


@pytest.mark.parametrize("change", ["issuer", "endpoint", "legacy", "missing_metadata"])
def test_changed_or_unproven_issuer_cannot_construct_refresh_request(
    tmp_path, monkeypatch, change
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    async def scenario():
        storage = AgentTokenStorage("test")
        await seed(storage, bound=change != "legacy")
        p = provider(AgentTokenStorage("test"))
        await p._initialize()
        if change == "issuer":
            p.context.oauth_metadata = metadata(issuer="https://other.example/")
        elif change == "endpoint":
            p.context.oauth_metadata = metadata(endpoint="https://other.example/token")
        elif change == "missing_metadata":
            p.context.oauth_metadata = None
        with pytest.raises(OAuthTokenError, match="reauthorization"):
            await p._refresh_token()
        assert p.context.current_tokens.access_token == "access"
        assert p.context.current_tokens.refresh_token is None
        saved = json.loads(storage._tokens_path().read_text())
        assert saved["access_token"] == "access" and "refresh_token" not in saved

    asyncio.run(scenario())


@pytest.mark.parametrize("rotate", [False, True])
def test_matching_grant_roundtrips_and_refreshes_on_pinned_endpoint(
    tmp_path, monkeypatch, rotate
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    async def scenario():
        storage = AgentTokenStorage("test")
        await seed(storage)
        p = provider(AgentTokenStorage("test"))
        await p._initialize()
        request = await p._refresh_token()
        assert str(request.url) == "https://issuer.example/token"
        assert b"refresh_token=refresh" in request.content
        assert b"authorization_issuer" not in request.content
        response = httpx.Response(
            200,
            json={
                "access_token": "new-access",
                **({"refresh_token": "rotated"} if rotate else {}),
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
        assert await p._handle_refresh_response(response)
        reopened = AgentTokenStorage("test")
        assert (await reopened.get_tokens()).refresh_token == (
            "rotated" if rotate else "refresh"
        )
        assert reopened.loaded_binding == (
            str(metadata().issuer),
            str(metadata().token_endpoint),
        )

    asyncio.run(scenario())


@pytest.mark.parametrize("reuse_refresh", [False, True])
def test_rejected_stale_grant_does_not_remove_replacement(
    tmp_path, monkeypatch, reuse_refresh
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    async def scenario():
        first = AgentTokenStorage("test")
        await seed(first)
        stale = AgentTokenStorage("test")
        await stale.get_tokens()
        replacement = AgentTokenStorage("test")
        replacement.bind_authorization_server(
            *(
                stale.loaded_binding
                if reuse_refresh
                else ("https://new.example/", "https://new.example/token")
            )
        )
        await replacement.set_tokens(
            OAuthToken(
                access_token="new",
                refresh_token="refresh" if reuse_refresh else "replacement",
                token_type="Bearer",
            )
        )
        stale.discard_loaded_refresh()
        assert (await replacement.get_tokens()).refresh_token == (
            "refresh" if reuse_refresh else "replacement"
        )

    asyncio.run(scenario())


def test_storage_keeps_its_original_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "one"))
    storage = AgentTokenStorage("test")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "two"))
    asyncio.run(seed(storage))
    assert storage._tokens_path().is_relative_to(tmp_path / "one")
    assert not (tmp_path / "two" / "mcp-tokens" / "test.json").exists()


@pytest.mark.parametrize("reuse_refresh", [False, True])
def test_late_refresh_response_cannot_overwrite_new_authorization(tmp_path, monkeypatch, reuse_refresh):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    async def scenario():
        initial = AgentTokenStorage("test")
        await seed(initial)
        stale_storage = AgentTokenStorage("test")
        stale = provider(stale_storage)
        await stale._initialize()
        await stale._refresh_token()
        replacement = AgentTokenStorage("test")
        replacement.bind_authorization_server(
            "https://new.example/", "https://new.example/token"
        )
        await replacement.set_tokens(OAuthToken(
            access_token="new-authorization", token_type="Bearer",
            refresh_token="refresh" if reuse_refresh else "replacement",
        ))
        expected = replacement._tokens_path().read_bytes()
        # Even a reload of the storage object must not change the request's
        # original compare-and-swap identity.
        await stale_storage.get_tokens()
        response = httpx.Response(200, json={
            "access_token": "late-access", "refresh_token": "late-refresh",
            "token_type": "Bearer", "expires_in": 3600,
        })
        with pytest.raises(OAuthTokenError, match="superseded"):
            await stale._handle_refresh_response(response)
        assert replacement._tokens_path().read_bytes() == expected
        assert stale.context.current_tokens is None

    asyncio.run(scenario())


def test_compatibility_builder_uses_issuer_enforcing_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    p = build_oauth_auth("compat", "https://resource.example/mcp")
    assert isinstance(p, _AGENT_PROVIDER_CLS)


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["matching", "issuer", "endpoint", "legacy"])
async def test_sdk_http_refresh_sends_only_bound_grant_and_reloads_saved_access(
    tmp_path, monkeypatch, binding
):
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    received = []

    async def endpoint(request):
        received.append((request.path, dict(await request.post()), request.headers.get("Authorization")))
        if request.path == "/token":
            return web.json_response({"access_token": "renewed-access", "token_type": "Bearer", "expires_in": 3600})
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", endpoint)
    async with TestServer(app) as server:
        base = str(server.make_url("/"))
        meta = metadata(issuer=base, endpoint=base + "token")
        storage = AgentTokenStorage("test")
        if binding != "legacy":
            storage.bind_authorization_server(
                base + "different-issuer" if binding == "issuer" else base,
                base + "different-token" if binding == "endpoint" else base + "token",
            )
        await storage.set_tokens(OAuthToken(
            access_token="expired-access", refresh_token="bound-refresh",
            token_type="Bearer", expires_in=0,
        ))
        await storage.set_client_info(OAuthClientInformationFull(
            client_id="client", redirect_uris=["http://localhost:8080/callback"]
        ))
        storage.save_oauth_metadata(meta)
        auth = provider(AgentTokenStorage("test"), base + "mcp")
        async with httpx.AsyncClient(auth=auth, timeout=3, trust_env=False) as client:
            if binding != "matching":
                with pytest.raises(OAuthTokenError, match="reauthorization"):
                    await client.get(base + "mcp")
                assert received == []
                saved = await AgentTokenStorage("test").get_tokens()
                assert saved.access_token == "expired-access"
                assert saved.refresh_token is None
                return
            assert (await client.get(base + "mcp")).json() == {"ok": True}
        reopened = AgentTokenStorage("test")
        assert (await reopened.get_tokens()).refresh_token == "bound-refresh"
        assert reopened.loaded_binding == (base, base + "token")
        # A fresh provider must use persisted access without refreshing again.
        async with httpx.AsyncClient(
            auth=provider(reopened, base + "mcp"), timeout=3, trust_env=False
        ) as client:
            assert (await client.get(base + "mcp")).status_code == 200
    assert [item[0] for item in received] == ["/token", "/mcp", "/mcp"]
    assert received[0][1]["grant_type"] == "refresh_token"
    assert received[0][1]["refresh_token"] == "bound-refresh"
    assert all(item[2] == "Bearer renewed-access" for item in received[1:])
