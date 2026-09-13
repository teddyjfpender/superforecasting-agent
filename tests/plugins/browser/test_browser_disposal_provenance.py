"""Provider cleanup uses allocation configuration and never exports credentials."""

import importlib
import json
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("name, class_name, header, suffix", [
    ("browserbase", "BrowserbaseBrowserProvider", "X-BB-API-Key", "/v1/sessions/remote"),
    ("browser_use", "BrowserUseBrowserProvider", "X-Browser-Use-API-Key", "/browsers/remote"),
    ("firecrawl", "FirecrawlBrowserProvider", "Authorization", "/v2/browser/remote"),
])
def test_disposal_is_bound_to_allocation_configuration(monkeypatch, name, class_name, header, suffix):
    module = importlib.import_module(f"plugins.browser.{name}.provider")
    provider = getattr(module, class_name)()
    config = {"base_url": "https://original.invalid", "api_key": "original-secret", "project_id": "original-project"}
    headers = {"Authorization": "Bearer original-secret"}
    if name == "firecrawl":
        monkeypatch.setattr(provider, "_api_url", lambda: config["base_url"])
        monkeypatch.setattr(provider, "_headers", lambda: headers)
    else:
        monkeypatch.setattr(provider, "_get_config", lambda: config)
    response = Mock(status_code=200, ok=True, headers={})
    response.json.return_value = {"id": "remote", "connectUrl": "wss://cdp.invalid/devtools/browser/id", "cdpUrl": "wss://cdp.invalid/devtools/browser/id"}
    calls = []
    def request(url, **kwargs):
        calls.append((url, kwargs))
        return response
    for method in ("post", "patch", "delete"):
        monkeypatch.setattr(module.requests, method, request)
    session = provider.create_session("task")
    # Mutate the actual source mappings, not only the accessor functions.
    config.update(base_url="https://replacement.invalid", api_key="replacement-secret", project_id="replacement-project")
    headers["Authorization"] = "Bearer replacement-secret"
    assert session.close() is True
    url, options = calls[-1]
    assert url == "https://original.invalid" + suffix
    assert "original-secret" in options["headers"][header]
    if name == "browserbase":
        assert options["json"]["projectId"] == "original-project"
    serialized = json.dumps(session)
    assert "secret" not in serialized
    assert "_close" not in serialized
