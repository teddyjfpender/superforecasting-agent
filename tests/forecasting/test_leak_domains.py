"""AIA P2.4 — leak-domain denylist unit tests (pure module)."""

from __future__ import annotations

import pytest

from forecasting.leak_domains import is_leak_domain, leak_reason


POSITIVE_URLS = [
    "https://www.macrotrends.net/stocks/charts/AAPL/apple/revenue",
    "https://stockanalysis.com/stocks/aapl/",
    "https://ycharts.com/companies/AAPL/price",
    "https://tradingeconomics.com/united-states/gdp",
    "https://www.nasdaq.com/market-activity/stocks/aapl",
    "https://www.tipranks.com/stocks/aapl/forecast",
    "https://weatherspark.com/y/12345/Average-Weather",
    "https://www.historique-meteo.net/europe/france/",
    "https://ratings.fide.com/profile/1503014",
    "https://finance.yahoo.com/quote/AAPL",
    "https://www.investing.com/equities/apple-computer-inc",
    "https://www.barchart.com/stocks/quotes/AAPL",
    "https://coinmarketcap.com/currencies/bitcoin/",
    # Shape-based (host not enumerated):
    "https://example.com/quote/TSLA",
    "https://example.com/live-scores/today",
    "https://example.com/rankings/world",
    "https://example.com/data?symbol=BTC",
    "https://somecharts.example.com/foo",
]

NEGATIVE_URLS = [
    "https://en.wikipedia.org/wiki/Apple_Inc.",
    "https://www.reuters.com/business/apple-q3-2023-results",
    "https://apnews.com/article/election-2024-abcdef",
    "https://fred.stlouisfed.org/series/GDP",
    "https://www.sec.gov/cgi-bin/browse-edgar",
    "https://example.com/news/2023/story",
    "https://www.bls.gov/news.release/cpi.htm",
    "https://nytimes.com/2023/10/01/us/politics/story.html",
    # Review-identified false positives that must stay NEGATIVE: timestamped news
    # live-blogs (not live widgets), encyclopedic articles, the /charts/ PATH on a
    # reputable stats host, and registrable-boundary collisions with short tokens.
    "https://www.nytimes.com/live/2024/11/05/us/election-results",
    "https://apnews.com/live/election-results",
    "https://www.bbc.com/news/live/world",
    "https://www.reuters.com/world/us/live-coverage-2024",
    "https://en.wikipedia.org/wiki/Real-time_computing",
    "https://en.wikipedia.org/wiki/Live_(band)",
    "https://www.bls.gov/charts/consumer-price-index/cpi.htm",
    "https://confide.com/news/story",
    "https://www.profide.com/x",
    "",
    "not a url at all",
]


@pytest.mark.parametrize("url", POSITIVE_URLS)
def test_is_leak_domain_positive(url):
    assert is_leak_domain(url) is True
    assert leak_reason(url)


@pytest.mark.parametrize("url", NEGATIVE_URLS)
def test_is_leak_domain_negative(url):
    assert is_leak_domain(url) is False
    assert leak_reason(url) is None


def test_extra_denylist_from_config_extends_match():
    url = "https://customwidget.example.org/board"
    assert is_leak_domain(url) is False
    assert is_leak_domain(url, extra_denylist=["customwidget.example.org"]) is True
    reason = leak_reason(url, extra_denylist=["customwidget.example.org"])
    assert "customwidget.example.org" in reason


def test_extra_denylist_accepts_string():
    url = "https://onehost.test/page"
    assert is_leak_domain(url, extra_denylist="onehost.test") is True


def test_scheme_less_url_is_tolerated():
    assert is_leak_domain("macrotrends.net/stocks/charts/AAPL") is True
