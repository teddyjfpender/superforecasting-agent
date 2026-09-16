"""The shipped catalog is deterministic and rejects broken contributor metadata."""

import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CATALOG = runpy.run_path(str(ROOT / "scripts/gen-news-catalog.py"))


def test_shipped_catalog_is_current():
    source = json.loads(CATALOG["SOURCE"].read_text(encoding="utf-8"))
    assert CATALOG["render"](source) == CATALOG["OUTPUT"].read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/rss",
        "https://user:pass@example.org/feed",
        "https://example.org/feed#fragment",
        "https://example.org/bad feed",
    ],
)
def test_rejects_invalid_urls(url):
    with pytest.raises(ValueError, match="Invalid public feed URL"):
        CATALOG["render"]([
            dict(category="News", title="Example", url=url, description="")
        ])


def test_duplicate_host_case_is_rejected_but_path_case_is_preserved():
    feed = dict(
        category="News", title="Example", url="https://example.org/Feed", description=""
    )
    with pytest.raises(ValueError, match="Duplicate"):
        CATALOG["render"]([feed, dict(feed, url="https://EXAMPLE.org/Feed/")])
    assert CATALOG["render"]([feed, dict(feed, url="https://example.org/feed")])
