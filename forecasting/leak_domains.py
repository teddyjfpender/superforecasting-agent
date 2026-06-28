"""Leak-domain denylist for backtest foreknowledge mitigation (AIA P2.4).

PURE module: no I/O, no ledger, no network. It answers a single question about a
source URL: "is this a *live widget / live quote / live ranking* surface whose
content silently time-travels?" Such a surface serves TODAY's number no matter
what `as_of` date a backtest pins, so any evidence cited from it leaks the
future into a historical simulation.

This module DOES NOT decide policy. ``ledger.add_evidence`` consults it only to
*tag* matching items and mark them inadmissible for backtest scoring; the normal
live ledger keeps the evidence untouched. For non-matching URLs every helper
here returns the unflagged default, so the default add path is byte-identical.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


# Host substrings that identify live-widget / live-quote / live-ranking sources.
# These pages render the *current* value regardless of any historical query, so
# evidence cited from them cannot be trusted to predate a backtest cutoff. Each
# entry is matched as a case-insensitive substring of the URL host.
LEAK_DENYLIST: frozenset[str] = frozenset(
    {
        "macrotrends.net",
        "stockanalysis.com",
        "ycharts.com",
        "tradingeconomics.com",
        "nasdaq.com/market-activity",
        "tipranks.com",
        "weatherspark.com",
        "historique-meteo.net",
        "fide.com",  # live FIDE rating / ranking widgets
        "marketwatch.com/investing",
        "finance.yahoo.com/quote",
        "google.com/finance",
        "investing.com",
        "wsj.com/market-data",
        "barchart.com",
        "stockcharts.com",
        "ycharts.com",
        "coinmarketcap.com",
        "coingecko.com",
    }
)


# URL *path/query shapes* that betray a live quote / score / ranking / market
# widget even on hosts we do not enumerate above. Kept DELIBERATELY high-precision:
# the broad tokens "/live/", "/real-time", and the "/charts/" PATH were removed
# because they false-positive on timestamped news live-blogs (apnews.com/live/…),
# encyclopedic articles (/wiki/Real-time_computing), and official stats
# (bls.gov/charts/…). "/live/" is narrowed to the "/live-scores" widget shape.
# Matched case-insensitively against the full URL.
LIVE_WIDGET_PATTERNS: re.Pattern[str] = re.compile(
    r"(?:"
    r"/quote[s]?/"
    r"|/live[-_]?scores?"                # live-SCORES widget, not bare /live/ blogs
    r"|/ranking[s]?/"
    r"|/leaderboard"
    r"|/market[-_]?activity"
    r"|/stocks?/[A-Za-z0-9.\-]+/?(?:$|\?|#)"
    r"|[?&](?:symbol|ticker)="
    r")",
    re.IGNORECASE,
)

# A "charts." LABEL in the HOST (stockcharts.com, ycharts.com, somecharts.example.com)
# is a chart-data widget host. Anchored to the host so the "/charts/" PATH on a
# reputable stats site (bls.gov/charts/…) is NOT matched.
_CHART_HOST_PATTERN: re.Pattern[str] = re.compile(r"(?:^|\.)[a-z0-9\-]*charts?\.", re.IGNORECASE)


def _host_and_path(url: str) -> tuple[str, str]:
    """Return ``(host, host+path)`` lowercased. Tolerant of scheme-less URLs."""
    text = (url or "").strip()
    if not text:
        return "", ""
    candidate = text if "//" in text else f"//{text}"
    parsed = urlparse(candidate)
    host = (parsed.netloc or "").lower()
    # Strip credentials / port for substring matching.
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if ":" in host:
        host = host.split(":", 1)[0]
    path = (parsed.path or "").lower()
    return host, f"{host}{path}"


def _denylist_hit(
    host: str, host_path: str, extra_denylist: frozenset[str] | None
) -> str | None:
    def matches(needle: str) -> bool:
        n = (needle or "").strip().lower()
        if not n:
            return False
        if "/" in n:
            # host+path entry ("nasdaq.com/market-activity"): anchor the host part on
            # a registrable boundary, then require the path fragment to be present.
            nh, _, npath = n.partition("/")
            host_ok = host == nh or host.endswith("." + nh)
            return host_ok and ("/" + npath) in host_path
        # bare-host entry: suffix-boundary match so 'fide.com' does NOT match
        # 'confide.com' / 'profide.com' (a plain substring would).
        return host == n or host.endswith("." + n)

    for needle in LEAK_DENYLIST:
        if matches(needle):
            return needle
    if extra_denylist:
        for needle in extra_denylist:
            if matches(needle):
                return (needle or "").strip().lower()
    return None


def _normalize_extra(extra_denylist: object) -> frozenset[str] | None:
    """Coerce a question_config-supplied deny list into a frozenset of hosts."""
    if not extra_denylist:
        return None
    if isinstance(extra_denylist, bytes):
        extra_denylist = extra_denylist.decode("utf-8", "ignore")
    if isinstance(extra_denylist, str):
        items = [extra_denylist]
    else:
        try:
            items = list(extra_denylist)
        except TypeError:
            return None
    cleaned = {str(item).strip().lower() for item in items if str(item).strip()}
    return frozenset(cleaned) or None


def leak_reason(url: str, *, extra_denylist: object = None) -> str | None:
    """Return a human-readable reason if ``url`` is a leak domain, else ``None``.

    ``extra_denylist`` may be supplied from ``question_config`` (a string or
    iterable of host substrings) to extend the static denylist per-question.
    """
    host, host_path = _host_and_path(url)
    if not host:
        return None
    extra = _normalize_extra(extra_denylist)
    hit = _denylist_hit(host, host_path, extra)
    if hit is not None:
        return f"denylisted live-widget host: {hit}"
    if _CHART_HOST_PATTERN.search(host):
        return f"chart-data widget host: {host}"
    full = (url or "").strip().lower()
    if LIVE_WIDGET_PATTERNS.search(full):
        return "live-quote/ranking/chart URL shape (time-travels to current value)"
    return None


def is_leak_domain(url: str, *, extra_denylist: object = None) -> bool:
    """``True`` if ``url`` is a live-widget / live-quote / live-ranking source."""
    return leak_reason(url, extra_denylist=extra_denylist) is not None
