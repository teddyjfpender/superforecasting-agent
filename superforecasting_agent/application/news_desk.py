"""Backend-owned news subscriptions; additive starter and atomic individual edits."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from forecasting.news.catalog import starter_feeds
from protocol.rpc.news import NewsConfigureRequest, NewsDeskResponse, NewsSubscription
from superforecasting_agent.storage.files import atomic_json_write, yaml_update_lock
from superforecasting_agent.storage.profile_lease import ProfileLease


def feed_key(url: str) -> str:
    p = urlsplit(url.strip())
    return urlunsplit(("https", p.netloc.lower(), p.path.rstrip("/"), p.query, ""))


class NewsDesk:
    def __init__(self, home: Path):
        self.home = home
        self.path = home / "news_feeds.json"

    def _read(self) -> tuple[dict, list[NewsSubscription], bool]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}, [], False
        # Accept both legacy representations. Corruption must never trigger seeding.
        data = {"feeds": raw} if isinstance(raw, list) else raw
        if not isinstance(data, dict) or not isinstance(data.get("feeds"), list):
            raise ValueError("news_feeds.json must contain a feeds list")
        feeds = []
        for item in data["feeds"]:
            if not isinstance(item, dict):
                raise ValueError("Invalid news subscription")
            url = str(item.get("url", ""))
            if url and "://" not in url:
                url = "https://" + url
            feeds.append(
                NewsSubscription.model_validate({
                    **item,
                    "url": url,
                    "title": item.get("title") or urlsplit(url).hostname or url,
                    "category": item.get("category") or "Custom",
                })
            )
        return data, feeds, True

    def selection(self) -> NewsDeskResponse:
        _, feeds, configured = self._read()
        return NewsDeskResponse(
            feeds=feeds,
            starter=starter_feeds(),
            state="configured" if configured else "unconfigured",
        )

    def configure(self, edit: NewsConfigureRequest) -> NewsDeskResponse:
        if (edit.action in {"add", "remove"}) != (edit.feed is not None):
            raise ValueError("Add/remove requires one feed; starter/empty takes none")
        with ProfileLease(self.home), yaml_update_lock(self.path):
            data, feeds, _ = self._read()
            if edit.action == "empty" and feeds:
                raise ValueError("Start empty cannot erase existing subscriptions")
            if edit.action in {"starter", "add"}:
                additions = starter_feeds() if edit.action == "starter" else [edit.feed]
                keys = {feed_key(feed.url) for feed in feeds}
                for feed in additions:
                    assert feed is not None
                    if feed_key(feed.url) not in keys:
                        feeds.append(
                            feed.model_copy(update={"addedAt": int(time.time() * 1000)})
                        )
                        keys.add(feed_key(feed.url))
            elif edit.action == "remove":
                assert edit.feed is not None
                feeds = [f for f in feeds if feed_key(f.url) != feed_key(edit.feed.url)]
            original = {
                feed_key(str(item.get("url", ""))): item
                for item in data.get("feeds", [])
                if isinstance(item, dict)
            }
            data.update(
                version=1,
                feeds=[
                    {**original.get(feed_key(f.url), {}), **f.model_dump()}
                    for f in feeds
                ],
            )
            atomic_json_write(self.path, data)
            return NewsDeskResponse(
                feeds=feeds, starter=starter_feeds(), state="configured"
            )
