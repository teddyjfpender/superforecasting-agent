"""Endpoint identity and invalid inputs agree across browser consumers."""

import pytest

from superforecasting_agent.configuration.browser import (
    DEFAULT_BROWSER_CDP_URL,
    normalize_cdp_url,
    parse_cdp_url,
)


@pytest.mark.parametrize("url", [None, "", "localhost:9222", "ws://localhost:9222/json/version", "http://127.0.0.1:9222/"])
def test_local_discovery_aliases(url):
    assert normalize_cdp_url(parse_cdp_url(url)) == DEFAULT_BROWSER_CDP_URL


@pytest.mark.parametrize("url", ["wss://host:443/devtools/browser/id?token=abc", "ws://127.0.0.1:9222/devtools/browser/id?token=abc"])
def test_concrete_endpoint_identity(url):
    assert normalize_cdp_url(parse_cdp_url(url)) == url


@pytest.mark.parametrize("url", [False, 3, [], "ftp://host", "http://", "http://[invalid", "http://host:abc", "http://host:65536", "http://host:0"])
def test_invalid_endpoint_is_rejected(url):
    with pytest.raises(ValueError):
        parse_cdp_url(url)
