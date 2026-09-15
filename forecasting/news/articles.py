"""Extract visible article paragraphs, keeping source excerpts explicitly labeled."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from protocol.rpc.news import NewsArticleResponse

MAX_ARTICLE_CHARS = 48_000


class ArticleHTML(HTMLParser):
    """Read semantic article/main containers; discard navigation and hidden content."""

    def __init__(self, url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool, int]] = []
        self.parts: dict[int, list[str]] = {1: [], 2: [], 3: []}
        self.host = urlsplit(url).hostname
        self.excerpt = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta":
            if values.get("property", values.get("name")) in {
                "og:description",
                "description",
            }:
                self.excerpt = self.excerpt or (values.get("content") or "")
        parent_blocked = self.stack[-1][1] if self.stack else False
        parent_article = self.stack[-1][2] if self.stack else 0
        hidden = (
            "hidden" in values
            or values.get("aria-hidden") == "true"
            or bool(
                re.search(
                    r"display\s*:\s*none|visibility\s*:\s*hidden",
                    values.get("style") or "",
                    re.I,
                )
            )
        )
        blocked = (
            parent_blocked
            or hidden
            or tag
            in {
                "script",
                "style",
                "nav",
                "footer",
                "header",
                "aside",
                "form",
                "button",
                "noscript",
                "svg",
            }
        )
        classes = set((values.get("class") or "").split())
        # Prefer actual body containers over the surrounding article controls.
        specific = (
            bool(
                classes
                & {"post-content", "entry-content", "article-body", "story-body"}
            )
            or values.get("itemprop") == "articleBody"
        )
        specific |= self.host == "en.mercopress.com" and "cnt" in classes
        specific |= self.host == "www.eia.gov" and "tie-article" in classes
        specific |= (
            self.host == "www.federalreserve.gov" and values.get("id") == "article"
        )
        article = max(
            parent_article,
            3
            if specific
            else 2
            if tag == "article"
            else 1
            if tag == "main" or values.get("role") == "main"
            else 0,
        )
        if (
            tag in {"p", "br", "li", "h2", "h3", "blockquote"}
            and article
            and not blocked
        ):
            self.parts[article].append("\n\n")
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append((tag, blocked, article))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag in {"p", "li", "h2", "h3", "blockquote"}:
            for parts in self.parts.values():
                parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1][2] and not self.stack[-1][1]:
            self.parts[self.stack[-1][2]].append(
                re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", data)
            )


def extract_article(html: str, url: str) -> NewsArticleResponse:
    parser = ArticleHTML(url)
    parser.feed(html)
    # Do not mine hidden structured data to work around a publisher's access gate.
    restricted = bool(
        re.search(r'"isAccessibleForFree"\s*:\s*(?:false|"false")', html, re.I)
    )
    parts = next(
        (
            parser.parts[level]
            for level in (3, 2, 1)
            if len("".join(parser.parts[level]).strip()) >= 240
        ),
        [],
    )
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in "".join(parts).split("\n\n")]
    text = "\n\n".join(p for p in paragraphs if p)
    if not restricted and len(text) >= 240:
        clipped = len(text) > MAX_ARTICLE_CHARS
        return NewsArticleResponse(
            text=text[:MAX_ARTICLE_CHARS],
            url=url,
            status="article",
            message="Publisher article text"
            + (" · shortened at reader limit" if clipped else ""),
        )
    excerpt = re.sub(r"\s+", " ", parser.excerpt).strip()[:4000]
    return NewsArticleResponse(
        text=excerpt,
        url=url,
        status="excerpt" if excerpt else "unavailable",
        message="Publisher excerpt; open source for full access"
        if restricted
        else "Only a source excerpt is available; open in browser for more",
    )
