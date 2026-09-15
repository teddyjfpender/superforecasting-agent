"""News RPC adapters; subscriptions live on the connected backend profile."""
from pathlib import Path

import httpx

from forecasting.news.articles import extract_article
from forecasting.news.transport import fetch_public_text as acquire_text
from protocol.rpc.news import NewsConfigureRequest
from superforecasting_agent.application.news_desk import NewsDesk
from superforecasting_agent.constants import get_agent_home
from tools.url_safety import is_safe_url


def fetch_public_text(url: str) -> tuple[str, str]:
    return acquire_text(url, is_safe_url=is_safe_url)


def register(server) -> None:
    def desk():
        return NewsDesk(Path(get_agent_home()))

    def selection(rid, params):
        try:
            return server._ok(rid, desk().selection().model_dump())
        except (ValueError, OSError):
            return server._err(rid, -32000, "Cannot read news subscriptions; inspect news_feeds.json")

    def configure(rid, params):
        try:
            return server._ok(rid, desk().configure(NewsConfigureRequest.model_validate(params)).model_dump())
        except (ValueError, OSError):
            return server._err(rid, -32602, "Cannot update news subscriptions; check the feed URL and existing selection")

    def feed(rid, params):
        try:
            xml, url = fetch_public_text(params["url"])
            return server._ok(rid, {"xml": xml, "url": url})
        except (ValueError, OSError, httpx.HTTPError):
            return server._err(rid, -32000, "News source unavailable or response rejected; retry later")

    def article(rid, params):
        try:
            html, url = fetch_public_text(params["url"])
            return server._ok(rid, extract_article(html, url).model_dump())
        except (ValueError, OSError, httpx.HTTPError):
            return server._ok(rid, {"text": "", "url": params["url"], "status": "unavailable", "message": "Article unavailable; retaining feed content. Open source in browser."})

    server.register_method("news.desk", selection)
    server.register_method("news.configure", configure)
    server.register_method("news.feed", feed)
    server.register_method("news.article", article)
