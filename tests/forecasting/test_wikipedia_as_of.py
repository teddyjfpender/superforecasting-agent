"""AIA P2.4 — Wikipedia as_of revision pinning (mocked MediaWiki API)."""

from __future__ import annotations

import pytest

from forecasting import source_adapters
from forecasting.source_adapters import load_wikipedia_pages


_SEARCH_PAYLOAD = {
    "query": {
        "pages": {
            "12345": {
                "pageid": 12345,
                "index": 1,
                "title": "Example Topic",
                "extract": "LIVE intro extract (today's text).",
                "fullurl": "https://en.wikipedia.org/wiki/Example_Topic",
                "revisions": [{"timestamp": "2026-06-20T10:00:00Z"}],
            }
        }
    }
}

# The historical revision the as_of revisions API should return.
_REVISION_PAYLOAD = {
    "query": {
        "pages": {
            "12345": {
                "pageid": 12345,
                "title": "Example Topic",
                "revisions": [
                    {
                        "revid": 9001,
                        "timestamp": "2023-09-15T08:30:00Z",
                        "slots": {"main": {"content": "HISTORICAL intro as of 2023."}},
                    }
                ],
            }
        }
    }
}


def _install_mock(monkeypatch, *, revision_payload=_REVISION_PAYLOAD):
    calls: list[str] = []

    def fake_read(url, label, **kwargs):
        calls.append(url)
        if "rvstart=" in url or label == "wikipedia revision as-of":
            return revision_payload
        return _SEARCH_PAYLOAD

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", fake_read)
    return calls


def test_as_of_none_serves_live_page_unchanged(monkeypatch):
    _install_mock(monkeypatch)
    pages = load_wikipedia_pages("Example Topic")
    assert len(pages) == 1
    page = pages[0]
    # Live path: latest-revision timestamp + live extract, no pinning metadata.
    assert page.updated_at == "2026-06-20T10:00:00Z"
    assert "LIVE intro" in page.extract
    assert "pinned_as_of" not in page.raw


def test_as_of_pins_to_historical_revision(monkeypatch):
    calls = _install_mock(monkeypatch)
    pages = load_wikipedia_pages("Example Topic", as_of="2024-01-01T00:00:00Z")
    assert len(pages) == 1
    page = pages[0]
    # available_at-driving timestamp is the historical revision, not now/live.
    assert page.updated_at == "2023-09-15T08:30:00Z"
    assert "HISTORICAL intro as of 2023" in page.extract
    assert page.raw["pinned_as_of"] == "2024-01-01T00:00:00Z"
    assert page.raw["pinned_revision_id"] == 9001
    # The revisions API was consulted with an rvstart cutoff.
    assert any("rvstart=" in c and "rvdir=older" in c for c in calls)


def test_as_of_drops_page_with_no_revision_before_cutoff(monkeypatch):
    empty = {"query": {"pages": {"12345": {"pageid": 12345, "title": "Example Topic"}}}}
    _install_mock(monkeypatch, revision_payload=empty)
    pages = load_wikipedia_pages("Example Topic", as_of="2010-01-01T00:00:00Z")
    assert pages == []


@pytest.mark.parametrize("content", ["", "   ", None])
def test_empty_historical_revision_never_reuses_live_extract(monkeypatch, content):
    revision = {"revid": 9002, "timestamp": "2023-09-15T08:30:00Z"}
    if content is not None:
        revision["slots"] = {"main": {"content": content}}
    payload = {"query": {"pages": {"12345": {"revisions": [revision]}}}}
    _install_mock(monkeypatch, revision_payload=payload)
    pages = load_wikipedia_pages("Example Topic", as_of="2024-01-01T00:00:00Z")
    assert len(pages) == 1
    assert pages[0].extract == ""
    assert pages[0].updated_at == "2023-09-15T08:30:00Z"
    assert pages[0].raw["pinned_revision_id"] == 9002
