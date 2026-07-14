import pytest

from gateway.credential_broker import CredentialBroker
from tools.registry import CredentialRequirement, ToolRegistry


def _broker():
    registry = ToolRegistry()
    registry.register(
        name="search", toolset="test", schema={"description": ""}, handler=lambda _: "{}",
        credentials=[CredentialRequirement(
            name="search-api", env_var="SEARCH_TOKEN", hosts=("api.example.com",),
            path_prefixes=("/v1/search",),
        )],
    )
    return CredentialBroker(registry, {"SEARCH_TOKEN": "top-secret"})


def test_broker_injects_secret_only_for_declared_scope():
    request = _broker().prepare("search", "search-api", "https://api.example.com/v1/search?q=x")
    assert request.headers["Authorization"] == "Bearer top-secret"


@pytest.mark.parametrize("url", [
    "http://api.example.com/v1/search",
    "https://evil.example/v1/search",
    "https://api.example.com/admin",
    "https://api.example.com:444/v1/search",
    "https://api.example.com/v1/search/%2e%2e/admin",
    "https://api.example.com/v1/search/../../admin",
    "https://api.example.com/v1/search#@evil.example",
    "https://api.example.com/v1/search-admin",
])
def test_broker_rejects_out_of_scope_destinations(url):
    with pytest.raises(PermissionError):
        _broker().prepare("search", "search-api", url)


def test_worker_cannot_override_brokered_header():
    with pytest.raises(PermissionError):
        _broker().prepare(
            "search", "search-api", "https://api.example.com/v1/search",
            {"authorization": "Bearer attacker"},
        )


def test_broker_rejects_secret_with_header_injection():
    broker = _broker()
    broker.environ["SEARCH_TOKEN"] = "token\r\nX-Evil: yes"
    with pytest.raises(RuntimeError, match="invalid header"):
        broker.prepare("search", "search-api", "https://api.example.com/v1/search")
