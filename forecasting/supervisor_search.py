"""GATE 2 (AIA P1.1, live) — a real fresh-search runner for the quorum supervisor.

:func:`forecasting.quorum.run_quorum` exposes a ``search_runner`` seam: when the
judge flags an UNRESOLVED CRUX (``information_gap`` + ``clarifying_queries``) the
loop hands those queries to ``search_runner``, folds the returned evidence into
the working context, and RE-SYNTHESISES once (bounded by ``max_research_rounds``).
P1.1 built that loop but the live caller (the QUORUM type's
:func:`forecasting.jobs.types.quorum.execute`) never passed a ``search_runner``, so
it could never fire. This module is the backend that wires it.

WHY this is the only path to a real edge: the market-hidden ForecastBench
experiment showed the closed-book LLM has NO intrinsic edge over the market
(Brier 0.279 vs 0.164, over-confident). The single lever that can beat the market
is FRESH INFORMATION the market has not yet priced — so the supervisor's job is to
go and FETCH that information when the judge says the panel could not settle a
crux from what it already had.

The runner is:

  * **Bounded.** It caps the number of distinct queries (default 3) and the
    results per query (default 5), and dedups by canonical URL / normalised title
    across the whole call, so a single research round can never search
    unboundedly or balloon the working context.
  * **Robust.** A failing backend (no provider configured, transport error, bad
    JSON) yields ``[]`` and NEVER throws — a research round that finds nothing
    simply re-synthesises on the original context, exactly as if no gap had been
    flagged.
  * **Live-legitimate.** ``available_at`` is stamped at NOW. This is the LIVE
    forecast path: the question resolves in the FUTURE, so fresh search as of now
    is legitimate evidence, NOT foreknowledge. (The leakage-sensitive backtest
    path does not use this runner — it pins sources to the evidence cutoff.)

The backend is the agent's existing web-search harness
(:func:`superforecasting_agent.tooling.web_search.search_web`), which returns the registry-routed
provider's ``{title, url, description}`` rows. We reshape each row into the
``{title, summary, source, url, available_at}`` evidence dict that
``forecasting.quorum._augment_context`` (and the panel/judge prompts) consume.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# A search backend takes (query, limit) and returns structured data or legacy
# JSON. Injectable so tests need neither network access nor provider setup.
SearchBackend = Callable[[str, int], str | dict[str, Any]]

# Conservative live caps. A supervisor research round is a fresh-information
# top-up, not an exhaustive crawl: a handful of the most-relevant fresh items is
# enough to move a crux, and the cap keeps the re-synthesis context (and the
# per-round cost) bounded.
DEFAULT_MAX_QUERIES = 3
DEFAULT_MAX_RESULTS_PER_QUERY = 5
DEFAULT_TOTAL_CAP = 12


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_backend(query: str, limit: int) -> dict[str, Any]:
    """The live web-search backend: the agent's registry-routed provider.

    Imported lazily so importing this module never initializes provider selection
    (and so tests that inject a stub backend never touch the real provider).
    """

    from superforecasting_agent.tooling.web_search import search_web

    return search_web(query, limit)


def _canonical_url(value: str) -> str:
    """Normalise a URL for dedup: lowercase scheme/host, drop utm_* params."""

    try:
        parsed = urlparse(value.strip())
    except (ValueError, AttributeError):
        return value.strip().lower()
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ),
        doseq=True,
    )
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", query, ""))


def _norm_title(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _dedupe_key(url: str, title: str) -> str | None:
    if url:
        return f"url:{_canonical_url(url)}"
    norm = _norm_title(title)
    if norm:
        return f"title:{norm}"
    return None


def _parse_web_rows(raw: Any) -> list[dict[str, Any]]:
    """Pull the ``data.web`` rows out of a web_search_tool response.

    Tolerant: a non-JSON string, a failed (``success: False``) payload, or a
    shape we don't recognise yields ``[]`` rather than raising — a robust runner
    never lets a backend quirk abort the research round.
    """

    if isinstance(raw, (dict, list)):
        payload: Any = raw
    else:
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(payload, dict):
        return []
    if payload.get("success") is False:
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        rows = data.get("web")
    elif isinstance(data, list):
        rows = data
    else:
        rows = None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def build_supervisor_search_runner(
    *,
    backend: SearchBackend | None = None,
    max_queries: int = DEFAULT_MAX_QUERIES,
    max_results_per_query: int = DEFAULT_MAX_RESULTS_PER_QUERY,
    total_cap: int = DEFAULT_TOTAL_CAP,
    available_at: str | None = None,
) -> Callable[[list[str]], list[dict[str, Any]]]:
    """Build the ``search_runner`` the quorum supervisor calls on a flagged gap.

    Returns a ``Callable[[list[str]], list[dict]]``: given the judge's
    ``clarifying_queries`` it runs a real web/news search per query (via
    ``backend``, defaulting to the live :func:`superforecasting_agent.tooling.web_search.search_web`)
    and returns evidence dicts shaped ``{title, summary, source, url,
    available_at}`` — exactly what :func:`forecasting.quorum._augment_context`
    and the panel/judge prompts expect.

    Bounds (so a run can never search unboundedly):
      * at most ``max_queries`` DISTINCT queries are issued;
      * at most ``max_results_per_query`` results are requested per query;
      * results are deduped by canonical URL / normalised title across the call;
      * the returned list is capped at ``total_cap`` items.

    Robustness: a backend that raises or returns garbage for one query
    contributes ``[]`` for that query (logged-by-omission, never re-raised), so
    the runner ALWAYS returns a list and never throws into the supervisor loop.

    ``available_at`` defaults to NOW at CALL time (the live path): the question
    resolves in the future, so fresh search now is legitimate evidence, not
    foreknowledge.
    """

    backend_fn: SearchBackend = backend or _default_backend
    max_queries = max(1, int(max_queries))
    max_results_per_query = max(1, int(max_results_per_query))
    total_cap = max(1, int(total_cap))

    def _runner(queries: list[str]) -> list[dict[str, Any]]:
        stamp = available_at or _now_iso()
        # Dedup the queries themselves first, then honour the query cap — so a
        # judge that repeats / over-asks can't blow past the bound.
        seen_queries: set[str] = set()
        clean_queries: list[str] = []
        for q in queries or []:
            text = str(q or "").strip()
            key = text.lower()
            if not text or key in seen_queries:
                continue
            seen_queries.add(key)
            clean_queries.append(text)
            if len(clean_queries) >= max_queries:
                break

        out: list[dict[str, Any]] = []
        seen_results: set[str] = set()
        for query in clean_queries:
            try:
                raw = backend_fn(query, max_results_per_query)
                rows = _parse_web_rows(raw)
            except Exception:  # noqa: BLE001 — a failed search must never throw
                rows = []
            for row in rows[:max_results_per_query]:
                title = str(row.get("title") or "").strip()
                url = str(row.get("url") or "").strip()
                summary = str(
                    row.get("description") or row.get("summary") or row.get("snippet") or ""
                ).strip()
                key = _dedupe_key(url, title)
                if key is None or key in seen_results:
                    continue
                # Drop live-widget / settlement / resolution-aggregator hosts (the
                # P2.4 denylist) so fresh search can't fold an answer-revealing URL
                # (a live odds/price/ratings widget) into the panel/judge context.
                if url and _is_leak_domain(url):
                    continue
                seen_results.add(key)
                # ``source`` is the human-facing origin label: the URL host,
                # else the raw URL, else the originating query.
                out.append(
                    {
                        "title": title,
                        "summary": summary,
                        "source": _host(url) or url or query,
                        "url": url,
                        "available_at": stamp,
                    }
                )
                if len(out) >= total_cap:
                    return out
        return out

    return _runner


def _host(url: str) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower()
    except (ValueError, AttributeError):
        return ""


def _is_leak_domain(url: str) -> bool:
    """True if ``url`` is a P2.4 denylisted live-widget / settlement host.

    Lazily imported so this module never hard-depends on leak_domains; any failure
    fails OPEN (does not drop the result) — the cutoff guard is the primary control.
    """

    try:
        from forecasting.leak_domains import is_leak_domain

        return bool(is_leak_domain(url))
    except Exception:  # noqa: BLE001
        return False


__all__ = [
    "SearchBackend",
    "DEFAULT_MAX_QUERIES",
    "DEFAULT_MAX_RESULTS_PER_QUERY",
    "DEFAULT_TOTAL_CAP",
    "build_supervisor_search_runner",
]
