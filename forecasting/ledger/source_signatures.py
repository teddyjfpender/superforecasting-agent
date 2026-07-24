"""Watched-source change-signature domain (carved from core).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns the per-adapter CHANGE-SIGNATURE
family used by refresh/change-detection: the generic dispatcher
(``_source_signature``) and the ~55 provider-specific signature builders
(``_url_source_signature`` / ``_rss_source_signature`` / ``_github_*`` / ``_fred_`` /
``_manifold_`` / ``_kalshi_`` / ... one per watched-source adapter), plus the RSS
relevance-filter helpers (``_rss_relevance_filters`` / ``_rss_filter_terms`` /
``_rss_filter_cli_args``) and the CLI/shell arg quoters (``_cli_arg`` / ``_shell_arg``).

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed (refresh/snapshot code reaches
``ledger._source_signature`` unchanged). The URL fetch reaches the module-level
``urlopen`` (monkeypatched on ``forecasting.ledger`` by tests) via the ``_core.``
call-time hop; the watched-source enum constants come from the ``watches`` leaf."""

from __future__ import annotations

from contextvars import ContextVar
from forecasting.ledger import core as _core
from typing import Any
from forecasting.branding import PRODUCT_SLUG
from urllib.request import Request
from urllib.error import URLError
from forecasting.ledger import watches as _watches
import hashlib
import json
from forecasting.models import json_dumps as _model_json_dumps
import re
from urllib.parse import urlparse


_CAPTURED_OBSERVATION: ContextVar[Any | None] = ContextVar(
    "forecast_source_observation", default=None
)


def begin_source_observation_capture() -> None:
    _CAPTURED_OBSERVATION.set(None)


def capture_source_observation(value: Any) -> None:
    """Keep the exact bounded payload that produced a source signature."""
    try:
        encoded = _model_json_dumps(value)
        if len(encoded) > 256_000:
            candidates = value.get("items") if isinstance(value, dict) else value
            if not isinstance(candidates, list):
                candidates = [value]
            encoded = _model_json_dumps(
                {"truncated": True, "items": candidates[:50]}
            )
        _CAPTURED_OBSERVATION.set(json.loads(encoded))
    except (TypeError, ValueError, AttributeError):
        _CAPTURED_OBSERVATION.set(None)


def take_source_observation() -> Any | None:
    value = _CAPTURED_OBSERVATION.get()
    _CAPTURED_OBSERVATION.set(None)
    return value


def json_dumps(value: Any) -> str:
    capture_source_observation(value)
    return _model_json_dumps(value)


def _rss_relevance_filters(ledger, metadata: dict[str, Any]) -> dict[str, list[str]]:
    raw_filters = metadata.get("relevance_filters") if isinstance(metadata, dict) else {}
    if not isinstance(raw_filters, dict):
        raw_filters = {}
    return {
        "keywords": ledger._rss_filter_terms(raw_filters.get("keywords")),
        "exclude_keywords": ledger._rss_filter_terms(raw_filters.get("exclude_keywords")),
    }


def _rss_filter_terms(ledger, value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    terms: list[str] = []
    for item in values:
        for chunk in str(item).split(","):
            term = chunk.strip()
            if term and term not in terms:
                terms.append(term)
    return terms


def _rss_filter_cli_args(ledger, filters: dict[str, list[str]]) -> str:
    parts: list[str] = []
    for term in filters.get("keywords") or []:
        parts.append(f" --keyword {ledger._shell_arg(term)}")
    for term in filters.get("exclude_keywords") or []:
        parts.append(f" --exclude-keyword {ledger._shell_arg(term)}")
    return "".join(parts)


def _shell_arg(ledger, value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:+=,@%-]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _source_signature(
    ledger,
    source: str,
    source_type: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    return _watches._source_signature(ledger, source=source, source_type=source_type, metadata=metadata)


def _url_source_signature(ledger, source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return f"missing:url:{source}:invalid"
    request = Request(source, headers={"User-Agent": f"{PRODUCT_SLUG}/forecast-watch"})
    digest = hashlib.sha256()
    total = 0
    excerpt = bytearray()
    try:
        with _core.urlopen(request, timeout=10) as response:
            while total < 2 * 1024 * 1024:
                chunk = response.read(min(1024 * 1024, 2 * 1024 * 1024 - total))
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
                if len(excerpt) < 32_768:
                    excerpt.extend(chunk[: 32_768 - len(excerpt)])
            headers = response.headers
            decoded = bytes(excerpt).decode(
                response.headers.get_content_charset() or "utf-8", errors="replace"
            )
            text_excerpt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", decoded)).strip()
            capture_source_observation(
                {
                    "entry_id": source,
                    "canonical_url": source,
                    "title": "",
                    "published_at": None,
                    "summary": text_excerpt[:8_000],
                    "content_type": str(headers.get("Content-Type") or ""),
                    "etag": str(headers.get("ETag") or ""),
                    "last_modified": str(headers.get("Last-Modified") or ""),
                    "content_hash": digest.hexdigest(),
                }
            )
            return ":".join(
                [
                    "url",
                    str(response.getcode()),
                    str(headers.get("ETag") or ""),
                    str(headers.get("Last-Modified") or ""),
                    str(headers.get("Content-Length") or ""),
                    str(total),
                    digest.hexdigest(),
                ]
            )
    except (OSError, URLError, ValueError) as exc:
        return f"missing:url:{source}:{exc.__class__.__name__}"


def _rss_source_signature(ledger, source: str, *, metadata: dict[str, Any] | None = None) -> str:
    feed_source = source.split(":", 1)[1] if source.startswith(("rss:", "atom:")) else source
    filters = ledger._rss_relevance_filters(metadata or {})
    try:
        from forecasting.source_adapters import load_news_feed_items
        items = load_news_feed_items(
            feed_source,
            limit=50,
            keywords=filters["keywords"],
            exclude_keywords=filters["exclude_keywords"],
        )
    except Exception as exc:
        return f"missing:rss:{feed_source}:{exc.__class__.__name__}"
    payload = {
        "filters": filters,
        "items": [
            {
                "entry_id": item.entry_id,
                "published_at": item.published_at,
                "title": item.title,
                "url": item.url,
            }
            for item in items
        ],
    }
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"rss:{len(items)}:{digest}"


def _gdelt_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("gdelt:") else source.strip()
    if not query:
        return "missing:gdelt:empty-query"
    try:
        from forecasting.source_adapters import load_gdelt_articles
        articles = load_gdelt_articles(query, limit=50)
    except Exception as exc:
        return f"missing:gdelt:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "entry_id": article.entry_id,
            "published_at": article.published_at,
            "title": article.title,
            "url": article.url,
            "domain": article.domain,
        }
        for article in articles
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"gdelt:{len(payload)}:{digest}"


def _fivethirtyeight_source_signature(ledger, source: str) -> str:
    source_value = (
        source.split(":", 1)[1].strip()
        if source.startswith(("fivethirtyeight:", "538:"))
        else source.strip()
    )
    if not source_value:
        return "missing:fivethirtyeight:empty-source"
    try:
        from forecasting.source_adapters import load_fivethirtyeight_polls
        observations = load_fivethirtyeight_polls(source_value, limit=50)
    except Exception as exc:
        return f"missing:fivethirtyeight:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "dataset": observation.dataset,
            "poll_id": observation.poll_id,
            "question_id": observation.question_id,
            "pollster": observation.pollster,
            "state": observation.state,
            "cycle": observation.cycle,
            "candidate_name": observation.candidate_name,
            "answer": observation.answer,
            "pct": observation.pct,
            "sample_size": observation.sample_size,
            "end_date": observation.end_date,
            "published_at": observation.published_at,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"fivethirtyeight:{len(payload)}:{digest}"


def _github_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("github:") else source.strip()
    if not source_value:
        return "missing:github:empty-repo"
    try:
        from forecasting.source_adapters import load_github_releases
        releases = load_github_releases(source_value, limit=50)
    except Exception as exc:
        return f"missing:github:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "created_at": release.created_at,
            "draft": release.draft,
            "entry_id": release.entry_id,
            "prerelease": release.prerelease,
            "published_at": release.published_at,
            "release_id": release.release_id,
            "repo": release.repo,
            "tag_name": release.tag_name,
        }
        for release in releases
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"github:{len(payload)}:{digest}"


def _github_repo_metadata_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("githubrepo:") else source.strip()
    if not source_value:
        return "missing:githubrepo:empty-repo"
    try:
        from forecasting.source_adapters import load_github_repository_snapshots
        snapshots = load_github_repository_snapshots(source_value, limit=1)
    except Exception as exc:
        return f"missing:githubrepo:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "repo": item.repo,
            "default_branch": item.default_branch,
            "stargazers_count": item.stargazers_count,
            "watchers_count": item.watchers_count,
            "forks_count": item.forks_count,
            "open_issues_count": item.open_issues_count,
            "subscribers_count": item.subscribers_count,
            "network_count": item.network_count,
            "updated_at": item.updated_at,
            "pushed_at": item.pushed_at,
            "archived": item.archived,
            "disabled": item.disabled,
        }
        for item in snapshots
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"githubrepo:{len(payload)}:{digest}"


def _github_issues_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("githubissues:") else source.strip()
    if not source_value:
        return "missing:githubissues:empty-repo"
    try:
        from forecasting.source_adapters import load_github_issues
        issues = load_github_issues(source_value, limit=50)
    except Exception as exc:
        return f"missing:githubissues:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "closed_at": issue.closed_at,
            "comments": issue.comments,
            "entry_id": issue.entry_id,
            "is_pull_request": issue.is_pull_request,
            "issue_number": issue.issue_number,
            "labels": issue.labels,
            "state": issue.state,
            "title": issue.title,
            "updated_at": issue.updated_at,
        }
        for issue in issues
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"githubissues:{len(payload)}:{digest}"


def _github_commits_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("githubcommits:") else source.strip()
    if not source_value:
        return "missing:githubcommits:empty-repo"
    try:
        from forecasting.source_adapters import load_github_commits
        commits = load_github_commits(source_value, limit=50)
    except Exception as exc:
        return f"missing:githubcommits:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "author_login": commit.author_login,
            "committed_at": commit.committed_at,
            "entry_id": commit.entry_id,
            "message": commit.message,
            "repo": commit.repo,
            "sha": commit.sha,
        }
        for commit in commits
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"githubcommits:{len(payload)}:{digest}"


def _github_actions_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("githubactions:") else source.strip()
    if not source_value:
        return "missing:githubactions:empty-repo"
    try:
        from forecasting.source_adapters import load_github_workflow_runs
        runs = load_github_workflow_runs(source_value, limit=50)
    except Exception as exc:
        return f"missing:githubactions:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "conclusion": run.conclusion,
            "display_title": run.display_title,
            "entry_id": run.entry_id,
            "event": run.event,
            "head_branch": run.head_branch,
            "head_sha": run.head_sha,
            "name": run.name,
            "repo": run.repo,
            "run_id": run.run_id,
            "status": run.status,
            "updated_at": run.updated_at,
        }
        for run in runs
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"githubactions:{len(payload)}:{digest}"


def _coingecko_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("coingecko:") else source.strip()
    if not source_value:
        return "missing:coingecko:empty-source"
    try:
        from forecasting.source_adapters import load_coingecko_market_snapshots
        snapshots = load_coingecko_market_snapshots(source_value, limit=50)
    except Exception as exc:
        return f"missing:coingecko:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "coin_id": snapshot.coin_id,
            "symbol": snapshot.symbol,
            "vs_currency": snapshot.vs_currency,
            "current_price": snapshot.current_price,
            "market_cap": snapshot.market_cap,
            "market_cap_rank": snapshot.market_cap_rank,
            "total_volume": snapshot.total_volume,
            "price_change_percentage_24h": snapshot.price_change_percentage_24h,
            "last_updated": snapshot.last_updated,
        }
        for snapshot in snapshots
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"coingecko:{len(payload)}:{digest}"


def _pypi_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("pypi:") else source.strip()
    if not source_value:
        return "missing:pypi:empty-package"
    try:
        from forecasting.source_adapters import load_pypi_releases
        releases = load_pypi_releases(source_value, limit=50)
    except Exception as exc:
        return f"missing:pypi:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "entry_id": release.entry_id,
            "file_count": release.file_count,
            "latest_upload_at": release.latest_upload_at,
            "package": release.package,
            "package_types": release.package_types,
            "python_versions": release.python_versions,
            "uploaded_at": release.uploaded_at,
            "version": release.version,
            "yanked": release.yanked,
            "yanked_reason": release.yanked_reason,
        }
        for release in releases
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"pypi:{len(payload)}:{digest}"


def _npm_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("npm:") else source.strip()
    if not source_value:
        return "missing:npm:empty-package"
    try:
        from forecasting.source_adapters import load_npm_package_versions
        versions = load_npm_package_versions(source_value, limit=50)
    except Exception as exc:
        return f"missing:npm:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "dependency_count": version.dependency_count,
            "deprecated": version.deprecated,
            "entry_id": version.entry_id,
            "license": version.license,
            "package": version.package,
            "published_at": version.published_at,
            "version": version.version,
        }
        for version in versions
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"npm:{len(payload)}:{digest}"


def _hackernews_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("hackernews:") else source.strip()
    if not query:
        return "missing:hackernews:empty-query"
    try:
        from forecasting.source_adapters import load_hackernews_items
        items = load_hackernews_items(query, limit=50)
    except Exception as exc:
        return f"missing:hackernews:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "comments": item.comments,
            "created_at": item.created_at,
            "entry_id": item.entry_id,
            "object_id": item.object_id,
            "points": item.points,
            "title": item.title,
            "url": item.url,
        }
        for item in items
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"hackernews:{len(payload)}:{digest}"


def _reddit_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("reddit:") else source.strip()
    if not query:
        return "missing:reddit:empty-query"
    try:
        from forecasting.source_adapters import load_reddit_posts
        posts = load_reddit_posts(query, limit=50)
    except Exception as exc:
        return f"missing:reddit:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "comments": post.comments,
            "created_at": post.created_at,
            "entry_id": post.entry_id,
            "post_id": post.post_id,
            "score": post.score,
            "subreddit": post.subreddit,
            "title": post.title,
            "url": post.url,
            "upvote_ratio": post.upvote_ratio,
        }
        for post in posts
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"reddit:{len(payload)}:{digest}"


def _bluesky_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("bluesky:") else source.strip()
    if not query:
        return "missing:bluesky:empty-query"
    try:
        from forecasting.source_adapters import load_bluesky_posts
        posts = load_bluesky_posts(query, limit=50)
    except Exception as exc:
        return f"missing:bluesky:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "created_at": post.created_at,
            "entry_id": post.entry_id,
            "indexed_at": post.indexed_at,
            "like_count": post.like_count,
            "post_uri": post.post_uri,
            "reply_count": post.reply_count,
            "repost_count": post.repost_count,
            "text": post.text,
            "url": post.url,
        }
        for post in posts
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"bluesky:{len(payload)}:{digest}"


def _mastodon_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("mastodon:") else source.strip()
    if not source_value:
        return "missing:mastodon:empty-source"
    try:
        from forecasting.source_adapters import load_mastodon_statuses
        statuses = load_mastodon_statuses(source_value, limit=40)
    except Exception as exc:
        return f"missing:mastodon:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "account_acct": status.account_acct,
            "content_text": status.content_text,
            "created_at": status.created_at,
            "entry_id": status.entry_id,
            "favourites_count": status.favourites_count,
            "reblogs_count": status.reblogs_count,
            "replies_count": status.replies_count,
            "status_id": status.status_id,
            "url": status.url,
        }
        for status in statuses
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"mastodon:{len(payload)}:{digest}"


def _federalregister_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("federalregister:") else source.strip()
    if not query:
        return "missing:federalregister:empty-query"
    try:
        from forecasting.source_adapters import load_federal_register_documents
        documents = load_federal_register_documents(query, limit=50)
    except Exception as exc:
        return f"missing:federalregister:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "agencies": document.agencies,
            "document_number": document.document_number,
            "document_type": document.document_type,
            "entry_id": document.entry_id,
            "published_at": document.published_at,
            "title": document.title,
            "url": document.url,
        }
        for document in documents
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"federalregister:{len(payload)}:{digest}"


def _courtlistener_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("courtlistener:") else source.strip()
    if not query:
        return "missing:courtlistener:empty-query"
    try:
        from forecasting.source_adapters import load_courtlistener_search_results
        results = load_courtlistener_search_results(query, limit=50)
    except Exception as exc:
        return f"missing:courtlistener:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "citation": result.citation,
            "court_id": result.court_id,
            "date_filed": result.date_filed,
            "docket_number": result.docket_number,
            "entry_id": result.entry_id,
            "result_id": result.result_id,
            "status": result.status,
            "title": result.title,
            "url": result.url,
        }
        for result in results
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"courtlistener:{len(payload)}:{digest}"


def _nvd_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("nvd:") else source.strip()
    if not query:
        return "missing:nvd:empty-query"
    try:
        from forecasting.source_adapters import load_nvd_cves
        cves = load_nvd_cves(query, limit=50)
    except Exception as exc:
        return f"missing:nvd:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "base_score": cve.base_score,
            "cve_id": cve.cve_id,
            "entry_id": cve.entry_id,
            "last_modified_at": cve.last_modified_at,
            "published_at": cve.published_at,
            "severity": cve.severity,
            "vuln_status": cve.vuln_status,
        }
        for cve in cves
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"nvd:{len(payload)}:{digest}"


def _cisa_kev_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("cisakev:") else source.strip()
    if not query:
        return "missing:cisakev:empty-query"
    try:
        from forecasting.source_adapters import load_cisa_kev_vulnerabilities
        vulnerabilities = load_cisa_kev_vulnerabilities(query, limit=50)
    except Exception as exc:
        return f"missing:cisakev:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "cve_id": vulnerability.cve_id,
            "date_added": vulnerability.date_added,
            "due_date": vulnerability.due_date,
            "entry_id": vulnerability.entry_id,
            "product": vulnerability.product,
            "ransomware_use": vulnerability.ransomware_use,
            "vendor_project": vulnerability.vendor_project,
            "vulnerability_name": vulnerability.vulnerability_name,
        }
        for vulnerability in vulnerabilities
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"cisakev:{len(payload)}:{digest}"


def _openmeteo_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("openmeteo:") else source.strip()
    if not source_value:
        return "missing:openmeteo:empty-coordinates"
    try:
        from forecasting.source_adapters import load_openmeteo_daily_forecasts
        forecasts = load_openmeteo_daily_forecasts(source_value, limit=16, forecast_days=16)
    except Exception as exc:
        return f"missing:openmeteo:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "entry_id": forecast.entry_id,
            "forecast_date": forecast.forecast_date,
            "precipitation_sum": forecast.precipitation_sum,
            "temperature_2m_max": forecast.temperature_2m_max,
            "temperature_2m_min": forecast.temperature_2m_min,
            "wind_speed_10m_max": forecast.wind_speed_10m_max,
        }
        for forecast in forecasts
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"openmeteo:{len(payload)}:{digest}"


def _airquality_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("airquality:") else source.strip()
    if not source_value:
        return "missing:airquality:empty-coordinates"
    try:
        from forecasting.source_adapters import load_openmeteo_air_quality_forecasts
        forecasts = load_openmeteo_air_quality_forecasts(source_value, limit=48, forecast_days=5)
    except Exception as exc:
        return f"missing:airquality:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "entry_id": forecast.entry_id,
            "forecast_time": forecast.forecast_time,
            "carbon_monoxide": forecast.carbon_monoxide,
            "european_aqi": forecast.european_aqi,
            "nitrogen_dioxide": forecast.nitrogen_dioxide,
            "ozone": forecast.ozone,
            "pm10": forecast.pm10,
            "pm2_5": forecast.pm2_5,
            "us_aqi": forecast.us_aqi,
        }
        for forecast in forecasts
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"airquality:{len(payload)}:{digest}"


def _weatherhistory_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("weatherhistory:") else source.strip()
    if not source_value:
        return "missing:weatherhistory:empty-source"
    try:
        from forecasting.source_adapters import load_openmeteo_historical_weather
        observations = load_openmeteo_historical_weather(source_value, limit=366)
    except Exception as exc:
        return f"missing:weatherhistory:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "entry_id": observation.entry_id,
            "observation_date": observation.observation_date,
            "precipitation_sum": observation.precipitation_sum,
            "temperature_2m_mean": observation.temperature_2m_mean,
            "temperature_2m_max": observation.temperature_2m_max,
            "temperature_2m_min": observation.temperature_2m_min,
            "wind_speed_10m_max": observation.wind_speed_10m_max,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"weatherhistory:{len(payload)}:{digest}"


def _usgs_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("usgs:") else source.strip()
    if not source_value:
        return "missing:usgs:empty-query"
    try:
        from forecasting.source_adapters import load_usgs_earthquakes
        events = load_usgs_earthquakes(source_value, limit=50)
    except Exception as exc:
        return f"missing:usgs:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "depth_km": event.depth_km,
            "entry_id": event.entry_id,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "latitude": event.latitude,
            "longitude": event.longitude,
            "magnitude": event.magnitude,
            "place": event.place,
            "significance": event.significance,
            "status": event.status,
            "time": event.time,
            "updated_at": event.updated_at,
        }
        for event in events
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"usgs:{len(payload)}:{digest}"


def _eonet_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("eonet:") else source.strip()
    if not source_value:
        return "missing:eonet:empty-query"
    try:
        from forecasting.source_adapters import load_nasa_eonet_events
        events = load_nasa_eonet_events(source_value, limit=50)
    except Exception as exc:
        return f"missing:eonet:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "categories": event.categories,
            "closed_at": event.closed_at,
            "entry_id": event.entry_id,
            "event_id": event.event_id,
            "latest_geometry_at": event.latest_geometry_at,
            "latitude": event.latitude,
            "longitude": event.longitude,
            "source_names": event.source_names,
            "status": event.status,
            "title": event.title,
        }
        for event in events
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"eonet:{len(payload)}:{digest}"


def _nws_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("nws:") else source.strip()
    if not source_value:
        return "missing:nws:empty-query"
    try:
        from forecasting.source_adapters import load_nws_alerts
        alerts = load_nws_alerts(source_value, limit=50)
    except Exception as exc:
        return f"missing:nws:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "alert_id": alert.alert_id,
            "area_desc": alert.area_desc,
            "certainty": alert.certainty,
            "effective_at": alert.effective_at,
            "ends_at": alert.ends_at,
            "event": alert.event,
            "expires_at": alert.expires_at,
            "headline": alert.headline,
            "severity": alert.severity,
            "status": alert.status,
            "urgency": alert.urgency,
        }
        for alert in alerts
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"nws:{len(payload)}:{digest}"


def _clinicaltrials_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("clinicaltrials:") else source.strip()
    if not source_value:
        return "missing:clinicaltrials:empty-query"
    try:
        from forecasting.source_adapters import load_clinicaltrials_studies
        studies = load_clinicaltrials_studies(source_value, limit=50)
    except Exception as exc:
        return f"missing:clinicaltrials:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "completion_date": study.completion_date,
            "conditions": study.conditions,
            "entry_id": study.entry_id,
            "has_results": study.has_results,
            "last_update_posted_at": study.last_update_posted_at,
            "nct_id": study.nct_id,
            "phases": study.phases,
            "primary_completion_date": study.primary_completion_date,
            "status": study.status,
            "title": study.brief_title,
        }
        for study in studies
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"clinicaltrials:{len(payload)}:{digest}"


def _openfda_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("openfda:") else source.strip()
    if not source_value:
        return "missing:openfda:empty-query"
    try:
        from forecasting.source_adapters import load_openfda_drug_applications
        applications = load_openfda_drug_applications(source_value, limit=50)
    except Exception as exc:
        return f"missing:openfda:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "application_number": application.application_number,
            "brand_names": application.brand_names,
            "entry_id": application.entry_id,
            "generic_names": application.generic_names,
            "latest_submission_status": application.latest_submission_status,
            "latest_submission_status_date": application.latest_submission_status_date,
            "latest_submission_type": application.latest_submission_type,
            "marketing_statuses": application.marketing_statuses,
            "sponsor_name": application.sponsor_name,
        }
        for application in applications
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"openfda:{len(payload)}:{digest}"


def _pubmed_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("pubmed:") else source.strip()
    if not source_value:
        return "missing:pubmed:empty-query"
    try:
        from forecasting.source_adapters import load_pubmed_articles
        articles = load_pubmed_articles(source_value, limit=50)
    except Exception as exc:
        return f"missing:pubmed:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "doi": article.doi,
            "entry_id": article.entry_id,
            "journal": article.journal,
            "pmid": article.pmid,
            "publication_types": article.publication_types,
            "published_at": article.published_at,
            "revised_at": article.revised_at,
            "title": article.title,
        }
        for article in articles
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"pubmed:{len(payload)}:{digest}"


def _owid_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("owid:") else source.strip()
    if not source_value:
        return "missing:owid:empty-source"
    try:
        from forecasting.source_adapters import load_owid_observations
        observations = load_owid_observations(source_value, limit=50)
    except Exception as exc:
        return f"missing:owid:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "code": observation.code,
            "entity": observation.entity,
            "entry_id": observation.entry_id,
            "observation_date": observation.observation_date,
            "slug": observation.slug,
            "value": observation.value,
            "value_column": observation.value_column,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"owid:{len(payload)}:{digest}"


def _who_gho_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("whogho:") else source.strip()
    if not source_value:
        return "missing:whogho:empty-source"
    try:
        from forecasting.source_adapters import load_who_gho_observations
        observations = load_who_gho_observations(source_value, limit=50)
    except Exception as exc:
        return f"missing:whogho:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "dim1": observation.dim1,
            "dim2": observation.dim2,
            "dim3": observation.dim3,
            "entry_id": observation.entry_id,
            "high": observation.high,
            "indicator": observation.indicator,
            "low": observation.low,
            "numeric_value": observation.numeric_value,
            "published_at": observation.published_at,
            "spatial_dim": observation.spatial_dim,
            "time_dim": observation.time_dim,
            "value": observation.value,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"whogho:{len(payload)}:{digest}"


def _fema_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("fema:") else source.strip()
    if not source_value:
        return "missing:fema:empty-source"
    try:
        from forecasting.source_adapters import load_fema_disaster_declarations
        declarations = load_fema_disaster_declarations(source_value, limit=50)
    except Exception as exc:
        return f"missing:fema:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "declaration_date": declaration.declaration_date,
            "declaration_string": declaration.declaration_string,
            "declaration_type": declaration.declaration_type,
            "designated_area": declaration.designated_area,
            "disaster_number": declaration.disaster_number,
            "entry_id": declaration.entry_id,
            "fiscal_year": declaration.fiscal_year,
            "incident_begin_date": declaration.incident_begin_date,
            "incident_end_date": declaration.incident_end_date,
            "incident_type": declaration.incident_type,
            "last_refresh": declaration.last_refresh,
            "state": declaration.state,
            "title": declaration.title,
        }
        for declaration in declarations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"fema:{len(payload)}:{digest}"


def _fred_source_signature(ledger, source: str) -> str:
    series_id = source.split(":", 1)[1].strip() if source.startswith("fred:") else source.strip()
    if not series_id:
        return "missing:fred:empty-series"
    try:
        from forecasting.source_adapters import load_fred_observations
        observations = load_fred_observations(series_id, limit=50)
    except Exception as exc:
        return f"missing:fred:{series_id}:{exc.__class__.__name__}"
    payload = [
        {
            "entry_id": observation.entry_id,
            "observation_date": observation.observation_date,
            "published_at": observation.published_at,
            "series_id": observation.series_id,
            "value": observation.value,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"fred:{len(payload)}:{digest}"


def _eia_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("eia:") else source.strip()
    if not source_value:
        return "missing:eia:empty-source"
    try:
        from forecasting.source_adapters import load_eia_observations
        observations = load_eia_observations(source_value, limit=50)
    except Exception as exc:
        return f"missing:eia:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "entry_id": observation.entry_id,
            "observation_period": observation.observation_period,
            "published_at": observation.published_at,
            "series_id": observation.series_id,
            "unit": observation.unit,
            "value": observation.value,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"eia:{len(payload)}:{digest}"


def _treasury_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("treasury:") else source.strip()
    if not source_value:
        return "missing:treasury:empty-source"
    try:
        from forecasting.source_adapters import load_treasury_records
        records = load_treasury_records(source_value, limit=50)
    except Exception as exc:
        return f"missing:treasury:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "dataset": record.dataset,
            "entry_id": record.entry_id,
            "published_at": record.published_at,
            "record_date": record.record_date,
            "value": record.value,
            "value_field": record.value_field,
        }
        for record in records
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"treasury:{len(payload)}:{digest}"


def _bls_source_signature(ledger, source: str) -> str:
    series_id = source.split(":", 1)[1].strip() if source.startswith("bls:") else source.strip()
    if not series_id:
        return "missing:bls:empty-series"
    try:
        from forecasting.source_adapters import load_bls_observations
        observations = load_bls_observations(series_id, limit=50)
    except Exception as exc:
        return f"missing:bls:{series_id}:{exc.__class__.__name__}"
    payload = [
        {
            "entry_id": observation.entry_id,
            "observation_date": observation.observation_date,
            "period": observation.period,
            "published_at": observation.published_at,
            "series_id": observation.series_id,
            "value": observation.value,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"bls:{len(payload)}:{digest}"


def _worldbank_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("worldbank:") else source.strip()
    if not source_value:
        return "missing:worldbank:empty-source"
    try:
        from forecasting.source_adapters import load_worldbank_observations
        observations = load_worldbank_observations(source_value, limit=50)
    except Exception as exc:
        return f"missing:worldbank:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "country": observation.country,
            "entry_id": observation.entry_id,
            "indicator": observation.indicator,
            "observation_date": observation.observation_date,
            "published_at": observation.published_at,
            "value": observation.value,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"worldbank:{len(payload)}:{digest}"


def _imf_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("imf:") else source.strip()
    if not source_value:
        return "missing:imf:empty-source"
    try:
        from forecasting.source_adapters import load_imf_datamapper_observations
        observations = load_imf_datamapper_observations(source_value, limit=50)
    except Exception as exc:
        return f"missing:imf:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "country": observation.country,
            "entry_id": observation.entry_id,
            "indicator": observation.indicator,
            "observation_date": observation.observation_date,
            "published_at": observation.published_at,
            "value": observation.value,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"imf:{len(payload)}:{digest}"


def _census_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("census:") else source.strip()
    if not source_value:
        return "missing:census:empty-source"
    try:
        from forecasting.source_adapters import load_census_records
        records = load_census_records(source_value, limit=50)
    except Exception as exc:
        return f"missing:census:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "dataset": record.dataset,
            "entry_id": record.entry_id,
            "geography": record.geography,
            "observation_date": record.observation_date,
            "published_at": record.published_at,
            "values": record.values,
        }
        for record in records
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"census:{len(payload)}:{digest}"


def _socrata_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("socrata:") else source.strip()
    if not source_value:
        return "missing:socrata:empty-source"
    try:
        from forecasting.source_adapters import load_socrata_records
        records = load_socrata_records(source_value, limit=50)
    except Exception as exc:
        return f"missing:socrata:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "dataset_id": record.dataset_id,
            "domain": record.domain,
            "entry_id": record.entry_id,
            "observation_time": record.observation_time,
            "row_id": record.row_id,
            "updated_at": record.updated_at,
            "values": record.values,
        }
        for record in records
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"socrata:{len(payload)}:{digest}"


def _ckan_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("ckan:") else source.strip()
    if not source_value:
        return "missing:ckan:empty-source"
    try:
        from forecasting.source_adapters import load_ckan_datasets
        datasets = load_ckan_datasets(source_value, limit=50)
    except Exception as exc:
        return f"missing:ckan:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "entry_id": dataset.entry_id,
            "metadata_created": dataset.metadata_created,
            "metadata_modified": dataset.metadata_modified,
            "name": dataset.name,
            "package_id": dataset.package_id,
            "portal": dataset.portal,
            "resource_count": len(dataset.resources),
            "tags": dataset.tags,
            "title": dataset.title,
        }
        for dataset in datasets
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"ckan:{len(payload)}:{digest}"


def _stooq_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("stooq:") else source.strip()
    if not source_value:
        return "missing:stooq:empty-source"
    try:
        from forecasting.source_adapters import load_stooq_prices
        observations = load_stooq_prices(source_value, limit=50)
    except Exception as exc:
        return f"missing:stooq:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "close_price": observation.close_price,
            "entry_id": observation.entry_id,
            "interval": observation.interval,
            "observation_date": observation.observation_date,
            "published_at": observation.published_at,
            "symbol": observation.symbol,
            "volume": observation.volume,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"stooq:{len(payload)}:{digest}"


def _yahoo_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("yahoo:") else source.strip()
    if not source_value:
        return "missing:yahoo:empty-symbol"
    try:
        from forecasting.source_adapters import load_yahoo_finance_prices
        observations = load_yahoo_finance_prices(source_value, limit=50)
    except Exception as exc:
        return f"missing:yahoo:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "close_price": observation.close_price,
            "currency": observation.currency,
            "entry_id": observation.entry_id,
            "interval": observation.interval,
            "observation_time": observation.observation_time,
            "symbol": observation.symbol,
            "volume": observation.volume,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"yahoo:{len(payload)}:{digest}"


def _sec_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("sec:") else source.strip()
    if not source_value:
        return "missing:sec:empty-cik"
    try:
        from forecasting.source_adapters import load_sec_filings
        filings = load_sec_filings(source_value, limit=50)
    except Exception as exc:
        return f"missing:sec:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "accession_number": filing.accession_number,
            "cik": filing.cik,
            "filing_date": filing.filing_date,
            "form": filing.form,
            "published_at": filing.published_at,
            "report_date": filing.report_date,
        }
        for filing in filings
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"sec:{len(payload)}:{digest}"


def _sec_company_facts_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("secfacts:") else source.strip()
    if not source_value:
        return "missing:secfacts:empty-source"
    try:
        from forecasting.source_adapters import load_sec_company_facts
        facts = load_sec_company_facts(source_value, limit=50)
    except Exception as exc:
        return f"missing:secfacts:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "accession_number": fact.accession_number,
            "cik": fact.cik,
            "concept": fact.concept,
            "entry_id": fact.entry_id,
            "filed_at": fact.filed_at,
            "frame": fact.frame,
            "observation_date": fact.observation_date,
            "published_at": fact.published_at,
            "taxonomy": fact.taxonomy,
            "unit": fact.unit,
            "value": fact.value,
        }
        for fact in facts
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"secfacts:{len(payload)}:{digest}"


def _arxiv_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("arxiv:") else source.strip()
    if not query:
        return "missing:arxiv:empty-query"
    try:
        from forecasting.source_adapters import load_arxiv_papers
        papers = load_arxiv_papers(query, limit=50)
    except Exception as exc:
        return f"missing:arxiv:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "arxiv_id": paper.arxiv_id,
            "categories": paper.categories,
            "entry_id": paper.entry_id,
            "published_at": paper.published_at,
            "title": paper.title,
            "updated_at": paper.updated_at,
        }
        for paper in papers
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"arxiv:{len(payload)}:{digest}"


def _openalex_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("openalex:") else source.strip()
    if not query:
        return "missing:openalex:empty-query"
    try:
        from forecasting.source_adapters import load_openalex_works
        works = load_openalex_works(query, limit=50)
    except Exception as exc:
        return f"missing:openalex:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "concepts": work.concepts,
            "doi": work.doi,
            "entry_id": work.entry_id,
            "published_at": work.published_at,
            "title": work.title,
            "updated_at": work.updated_at,
            "work_id": work.work_id,
        }
        for work in works
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"openalex:{len(payload)}:{digest}"


def _crossref_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("crossref:") else source.strip()
    if not query:
        return "missing:crossref:empty-query"
    try:
        from forecasting.source_adapters import load_crossref_works
        works = load_crossref_works(query, limit=50)
    except Exception as exc:
        return f"missing:crossref:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "cited_by_count": work.cited_by_count,
            "container_title": work.container_title,
            "doi": work.doi,
            "entry_id": work.entry_id,
            "published_at": work.published_at,
            "publisher": work.publisher,
            "reference_count": work.reference_count,
            "title": work.title,
            "updated_at": work.updated_at,
            "work_type": work.work_type,
        }
        for work in works
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"crossref:{len(payload)}:{digest}"


def _reliefweb_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("reliefweb:") else source.strip()
    if not query:
        return "missing:reliefweb:empty-query"
    try:
        from forecasting.source_adapters import load_reliefweb_reports
        reports = load_reliefweb_reports(query, limit=50)
    except Exception as exc:
        return f"missing:reliefweb:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "changed_at": report.changed_at,
            "countries": report.countries,
            "disasters": report.disasters,
            "entry_id": report.entry_id,
            "published_at": report.published_at,
            "report_id": report.report_id,
            "sources": report.sources,
            "title": report.title,
            "url": report.url,
        }
        for report in reports
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"reliefweb:{len(payload)}:{digest}"


def _wikipedia_source_signature(ledger, source: str) -> str:
    query = source.split(":", 1)[1].strip() if source.startswith("wikipedia:") else source.strip()
    if not query:
        return "missing:wikipedia:empty-query"
    try:
        from forecasting.source_adapters import load_wikipedia_pages
        pages = load_wikipedia_pages(query, limit=50)
    except Exception as exc:
        return f"missing:wikipedia:{query}:{exc.__class__.__name__}"
    payload = [
        {
            "entry_id": page.entry_id,
            "page_id": page.page_id,
            "title": page.title,
            "updated_at": page.updated_at,
            "url": page.url,
        }
        for page in pages
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"wikipedia:{len(payload)}:{digest}"


def _wikipediapageviews_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("wikipediapageviews:") else source.strip()
    if not source_value:
        return "missing:wikipediapageviews:empty-source"
    try:
        from forecasting.source_adapters import load_wikimedia_pageviews
        observations = load_wikimedia_pageviews(source_value, limit=50)
    except Exception as exc:
        return f"missing:wikipediapageviews:{source_value}:{exc.__class__.__name__}"
    payload = [
        {
            "access": observation.access,
            "agent": observation.agent,
            "article": observation.article,
            "entry_id": observation.entry_id,
            "granularity": observation.granularity,
            "observation_date": observation.observation_date,
            "project": observation.project,
            "views": observation.views,
        }
        for observation in observations
    ]
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"wikipediapageviews:{len(payload)}:{digest}"


def _manifold_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("manifold:") else source.strip()
    if not source_value:
        return "missing:manifold:empty-source"
    try:
        from forecasting.source_adapters import load_manifold_market
        market = load_manifold_market(source_value)
    except Exception as exc:
        return f"missing:manifold:{source_value}:{exc.__class__.__name__}"
    payload = {
        "close_time": market.close_time,
        "distribution": market.distribution,
        "is_resolved": market.is_resolved,
        "market_id": market.market_id,
        "probability": market.probability,
        "question": market.question,
        "resolution": market.resolution,
        "resolution_time": market.resolution_time,
        "slug": market.slug,
        "url": market.url,
    }
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"manifold:1:{digest}"


def _metaculus_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("metaculus:") else source.strip()
    if not source_value:
        return "missing:metaculus:empty-source"
    try:
        from forecasting.source_adapters import load_metaculus_question
        question = load_metaculus_question(source_value)
    except Exception as exc:
        return f"missing:metaculus:{source_value}:{exc.__class__.__name__}"
    payload = {
        "close_time": question.close_time,
        "distribution": question.distribution,
        "probability": question.probability,
        "question_id": question.question_id,
        "resolution": question.resolution,
        "resolution_time": question.resolution_time,
        "status": question.status,
        "title": question.title,
        "url": question.url,
    }
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"metaculus:1:{digest}"


def _polymarket_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("polymarket:") else source.strip()
    if not source_value:
        return "missing:polymarket:empty-source"
    try:
        from forecasting.source_adapters import load_polymarket_market
        market = load_polymarket_market(source_value)
    except Exception as exc:
        return f"missing:polymarket:{source_value}:{exc.__class__.__name__}"
    payload = {
        "close_time": market.close_time,
        "distribution": market.distribution,
        "market_id": market.market_id,
        "probability": market.probability,
        "question": market.question,
        "resolution_time": market.resolution_time,
        "slug": market.slug,
        "url": market.url,
    }
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"polymarket:1:{digest}"


def _kalshi_source_signature(ledger, source: str) -> str:
    source_value = source.split(":", 1)[1].strip() if source.startswith("kalshi:") else source.strip()
    if not source_value:
        return "missing:kalshi:empty-source"
    try:
        from forecasting.source_adapters import load_kalshi_market
        market = load_kalshi_market(source_value)
    except Exception as exc:
        return f"missing:kalshi:{source_value}:{exc.__class__.__name__}"
    payload = {
        "close_time": market.close_time,
        "event_ticker": market.event_ticker,
        "probability": market.probability,
        "question": market.question,
        "resolution_time": market.resolution_time,
        "result": market.result,
        "status": market.status,
        "ticker": market.ticker,
        "url": market.url,
    }
    digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
    return f"kalshi:1:{digest}"


def _cli_arg(ledger, value: str) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_./:@%+=,-]+", text):
        return text
    return json.dumps(text)
