#!/usr/bin/env python3
"""Generate the bundled News feed catalog for the TUI.

Pulls the curated, category-tagged OPML exports from
github.com/plenaryapp/awesome-rss-feeds (CC0 / public-domain feed list),
parses each feed (title, url, description) and emits a typed TS module at
ui-tui/src/content/newsFeedCatalog.ts. A small hand-picked supplement adds
high-signal Markets / Tech / World feeds that matter for a forecasting desk.

Run:  python3 scripts/gen-news-catalog.py
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

RAW = "https://raw.githubusercontent.com/plenaryapp/awesome-rss-feeds/master/recommended/with_category"

# awesome-rss-feeds category file -> the (normalised) category we expose.
CATEGORIES = {
    "News": "News",
    "Business & Economy": "Business",
    "Personal finance": "Finance",
    "Startups": "Startups",
    "Tech": "Technology",
    "Programming": "Programming",
    "Web Development": "Web Dev",
    "Android Development": "Android Dev",
    "iOS Development": "iOS Dev",
    "Apple": "Apple",
    "Android": "Android",
    "UI - UX": "Design",
    "Science": "Science",
    "Space": "Space",
    "Gaming": "Gaming",
    "Movies": "Movies",
    "Television": "Television",
    "Music": "Music",
    "Books": "Books",
    "Sports": "Sports",
    "Football": "Football",
    "Cricket": "Cricket",
    "Tennis": "Tennis",
    "Food": "Food",
    "Travel": "Travel",
    "Cars": "Cars",
    "Photography": "Photography",
    "History": "History",
    "Architecture": "Architecture",
    "Fashion": "Fashion",
    "Funny": "Humor",
}

# Hand-picked, verified, high-signal feeds a forecasting desk wants. These
# supplement (and in a few cases reinforce) the awesome-rss-feeds set.
SUPPLEMENT = [
    # category, title, url, description
    ("News", "Reuters - Top News", "https://www.reutersagency.com/feed/?best-topics=top-news&post_type=best", "Reuters wire: world, business and markets."),
    ("News", "AP Top News", "https://rsshub.app/apnews/topics/apf-topnews", "Associated Press top headlines."),
    ("Markets", "CNBC - Top News", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "CNBC business and markets headlines."),
    ("Markets", "MarketWatch - Top Stories", "http://feeds.marketwatch.com/marketwatch/topstories/", "MarketWatch top market-moving stories."),
    ("Markets", "Financial Times - Home", "https://www.ft.com/rss/home", "Financial Times front page (may require subscription)."),
    ("Markets", "Bloomberg - Markets", "https://feeds.bloomberg.com/markets/news.rss", "Bloomberg markets coverage."),
    ("Markets", "The Economist - Finance", "https://www.economist.com/finance-and-economics/rss.xml", "The Economist finance & economics."),
    ("Finance", "Calculated Risk", "https://feeds.feedburner.com/CalculatedRisk", "Macro/housing/jobs analysis."),
    ("Technology", "Hacker News - Front Page", "https://hnrss.org/frontpage", "Top stories on Hacker News."),
    ("Technology", "Ars Technica", "http://feeds.arstechnica.com/arstechnica/index", "In-depth tech, science and policy."),
    ("Technology", "The Verge", "https://www.theverge.com/rss/index.xml", "Tech, science and culture."),
    ("Technology", "MIT Technology Review", "https://www.technologyreview.com/feed/", "Emerging technology analysis."),
    ("Technology", "Stratechery (free)", "https://stratechery.com/feed/", "Ben Thompson on tech strategy."),
    ("Science", "Nature - Latest", "https://www.nature.com/nature.rss", "Nature latest research and news."),
    ("Science", "Quanta Magazine", "https://www.quantamagazine.org/feed/", "Math and fundamental science journalism."),
    ("Science", "Science | The Guardian", "https://www.theguardian.com/science/rss", "Guardian science desk."),
    ("Politics", "Politico", "https://rss.politico.com/politics-news.xml", "US politics and policy."),
    ("Politics", "The Guardian - Politics", "https://www.theguardian.com/politics/rss", "UK & world politics."),
    ("World", "BBC News - World", "http://feeds.bbci.co.uk/news/world/rss.xml", "BBC world headlines."),
    ("World", "Al Jazeera - All", "https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera global coverage."),
    # Long-form / ideas / essays — "interesting reads".
    ("Long Reads", "The Atlantic", "https://www.theatlantic.com/feed/all/", "Politics, culture, science and ideas."),
    ("Long Reads", "The New Yorker - Everything", "https://www.newyorker.com/feed/everything", "Reporting, essays, culture and fiction."),
    ("Long Reads", "Aeon", "https://aeon.co/feed.rss", "Essays on philosophy, science and culture."),
    ("Long Reads", "Nautilus", "https://nautil.us/feed/", "Science connected to philosophy and culture."),
    ("Long Reads", "Longreads", "https://longreads.com/feed/", "The best long-form storytelling on the web."),
    ("Long Reads", "The Marginalian", "https://www.themarginalian.org/feed/", "Maria Popova on art, science and meaning."),
    ("Long Reads", "Astral Codex Ten", "https://www.astralcodexten.com/feed", "Scott Alexander on science, reasoning and society."),
    ("Long Reads", "Marginal Revolution", "https://feeds.feedburner.com/marginalrevolution/feed", "Tyler Cowen & Alex Tabarrok on economics and ideas."),
    # Art.
    ("Art", "Hyperallergic", "https://hyperallergic.com/feed/", "Perspectives on art and culture."),
    ("Art", "Colossal", "https://www.thisiscolossal.com/feed/", "Art, design and visual culture."),
    ("Art", "ARTnews", "https://www.artnews.com/feed/", "Art world news and market coverage."),
    ("Art", "The Art Newspaper", "https://www.theartnewspaper.com/rss.xml", "International art news and analysis."),
    ("Art", "Artsy - News", "https://www.artsy.net/rss/news", "Art market and culture news."),
    ("Art", "Smithsonian Magazine", "https://www.smithsonianmag.com/rss/latest_articles/", "History, science, art and culture."),
    # Academic / research journalism.
    ("Academic", "Science | AAAS - News", "https://www.science.org/rss/news_current.xml", "Latest news from Science / AAAS."),
    ("Academic", "ScienceDaily - All", "https://www.sciencedaily.com/rss/all.xml", "Research news across all sciences."),
    ("Academic", "Phys.org", "https://phys.org/rss-feed/", "Physics, tech and science research news."),
    ("Academic", "The Conversation - Articles", "https://theconversation.com/articles.atom", "Research-based analysis written by academics."),
    ("Academic", "JSTOR Daily", "https://daily.jstor.org/feed/", "Scholarship made accessible."),
    ("Academic", "Nature - News", "https://www.nature.com/nature/articles?type=news.rss", "News from the journal Nature."),
    # arXiv preprints (research frontier).
    ("arXiv", "arXiv cs.AI — Artificial Intelligence", "https://rss.arxiv.org/rss/cs.AI", "New AI preprints on arXiv."),
    ("arXiv", "arXiv cs.LG — Machine Learning", "https://rss.arxiv.org/rss/cs.LG", "New machine-learning preprints on arXiv."),
    ("arXiv", "arXiv cs.CL — Computation & Language", "https://rss.arxiv.org/rss/cs.CL", "New NLP / language preprints on arXiv."),
    ("arXiv", "arXiv stat.ML — Statistics / ML", "https://rss.arxiv.org/rss/stat.ML", "New statistical machine-learning preprints."),
    ("arXiv", "arXiv econ.EM — Econometrics", "https://rss.arxiv.org/rss/econ.EM", "New econometrics preprints on arXiv."),
    ("arXiv", "arXiv q-fin — Quantitative Finance", "https://rss.arxiv.org/rss/q-fin", "New quantitative-finance preprints on arXiv."),
    # Economics.
    ("Economics", "NBER - New Working Papers", "https://back.nber.org/rss/new.xml", "Latest NBER working papers."),
    ("Economics", "Noahpinion", "https://www.noahpinion.blog/feed", "Noah Smith on economics and policy."),
    ("Economics", "The Economist - Finance & Economics", "https://www.economist.com/finance-and-economics/rss.xml", "Economics coverage from The Economist."),
]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "outrider-news-catalog/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def clean(text: str | None, limit: int = 160) -> str:
    if not text:
        return ""
    t = html.unescape(text).strip()
    t = re.sub(r"\s+", " ", t)
    if len(t) > limit:
        t = t[: limit - 1].rstrip() + "…"
    return t


# Attribute scan, not an XML parse: these OPML files routinely carry raw,
# unescaped `&` in descriptions which makes strict parsers (ElementTree)
# reject the whole document. Each feed is a self-closing <outline …/> tag.
OUTLINE_RE = re.compile(r"<outline\b[^>]*\bxmlUrl=", re.IGNORECASE)
TAG_RE = re.compile(r"<outline\b[^>]*?/?>", re.IGNORECASE | re.DOTALL)
ATTR_RE = re.compile(r"(\w+)\s*=\s*\"([^\"]*)\"")


def parse_opml(xml_text: str, category: str) -> list[dict]:
    out: list[dict] = []
    for tag in TAG_RE.findall(xml_text):
        if not OUTLINE_RE.match(tag):
            continue
        attrs = {k.lower(): v for k, v in ATTR_RE.findall(tag)}
        url = (attrs.get("xmlurl") or "").strip()
        if not url:
            continue
        title = clean(attrs.get("title") or attrs.get("text"), 80)
        if not title:
            continue
        out.append(
            {"category": category, "title": title, "url": url, "description": clean(attrs.get("description"), 160)}
        )
    return out


def main() -> int:
    feeds: list[dict] = []
    seen: set[str] = set()

    def add(entry: dict) -> None:
        key = entry["url"].strip().lower().rstrip("/")
        if not key or key in seen:
            return
        seen.add(key)
        feeds.append(entry)

    for src_name, category in CATEGORIES.items():
        fname = urllib.parse.quote(f"{src_name}.opml")
        try:
            xml_text = fetch(f"{RAW}/{fname}")
        except Exception as e:  # noqa: BLE001
            print(f"  ! skip {src_name}: {e}", file=sys.stderr)
            continue
        parsed = parse_opml(xml_text, category)
        for entry in parsed:
            add(entry)
        print(f"  {category:<14} {len(parsed):>3} feeds", file=sys.stderr)

    for category, title, url, desc in SUPPLEMENT:
        add({"category": category, "title": title, "url": url, "description": desc})

    feeds.sort(key=lambda f: (f["category"].lower(), f["title"].lower()))

    categories = sorted({f["category"] for f in feeds}, key=str.lower)

    header = (
        "// AUTO-GENERATED by scripts/gen-news-catalog.py — do not edit by hand.\n"
        "// Source: github.com/plenaryapp/awesome-rss-feeds (curated, category-tagged\n"
        "// OPML exports) plus a hand-picked Markets/Tech/World supplement.\n"
        f"// {len(feeds)} feeds across {len(categories)} categories.\n\n"
        "export interface CatalogFeed {\n"
        "  category: string\n"
        "  title: string\n"
        "  url: string\n"
        "  description: string\n"
        "}\n\n"
        f"export const FEED_CATEGORIES: string[] = {json.dumps(categories, ensure_ascii=False)}\n\n"
        "export const FEED_CATALOG: CatalogFeed[] = "
    )

    body = json.dumps(feeds, ensure_ascii=False, indent=0)
    # Compact each object onto one line for readability + smaller diff churn.
    body = re.sub(r"\{\n", "{ ", body)
    body = re.sub(r",\n", ", ", body)
    body = re.sub(r"\n\}", " }", body)

    out_path = Path(__file__).resolve().parent.parent / "ui-tui" / "src" / "content" / "newsFeedCatalog.ts"
    out_path.write_text(header + body + "\n", encoding="utf-8")
    print(f"\nWrote {out_path} — {len(feeds)} feeds, {len(categories)} categories.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
