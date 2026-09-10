"""Load wikimedia reference evidence through explicit reader callbacks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from urllib.parse import quote, unquote, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .research_records import WikimediaPageviewObservation
from .dates import _fred_date, _fred_date_to_iso
from .values import _optional_str, _optional_float

def load_wikimedia_pageviews(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    access: str = "all-access",
    agent: str = "user",
    api_base_url: str = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article",
    _read_json_endpoint: Callable[[str, str], object],
    _wikimedia_today_utc: Callable[[], date],
) -> list[WikimediaPageviewObservation]:
    """Load Wikimedia pageview observations as public-attention evidence."""

    project, article = _wikimedia_pageview_source_parts(source)
    if limit <= 0:
        raise ValidationError("wikipediapageviews import --limit must be positive")
    normalized_access = access.strip() or "all-access"
    normalized_agent = agent.strip() or "user"
    since_date = _fred_date(since, field_name="since") if since else None
    end_date = _wikimedia_today_utc()
    if since_date is None:
        from datetime import timedelta

        start_date = end_date - timedelta(days=max(30, limit * 2))
    else:
        start_date = since_date
    if start_date > end_date:
        start_date = end_date
    endpoint = _wikimedia_pageviews_endpoint(
        project,
        article,
        normalized_access,
        normalized_agent,
        start_date,
        end_date,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "wikimedia pageviews")
    if isinstance(payload, dict):
        rows = payload.get("items")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValidationError("wikimedia pageviews response must contain an items array")

    observations: list[WikimediaPageviewObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = row.get("timestamp") or row.get("date")
        observation_date, published_at = _wikimedia_pageview_timestamp(timestamp)
        if observation_date is None or published_at is None:
            continue
        parsed_date = _fred_date(observation_date, field_name="wikimedia pageview date")
        if since_date is not None and parsed_date is not None and parsed_date < since_date:
            continue
        views = _wikimedia_pageview_count(row.get("views"))
        if views is None:
            continue
        row_project = _optional_str(row.get("project")) or project
        row_article = _optional_str(row.get("article")) or article
        row_access = _optional_str(row.get("access")) or normalized_access
        row_agent = _optional_str(row.get("agent")) or normalized_agent
        granularity = _optional_str(row.get("granularity")) or "daily"
        observations.append(
            WikimediaPageviewObservation(
                project=row_project,
                article=row_article,
                access=row_access,
                agent=row_agent,
                granularity=granularity,
                observation_date=observation_date,
                views=views,
                published_at=published_at,
                source_url=endpoint,
                source_name="Wikimedia Pageviews",
                entry_id=f"{row_project}:{row_article}:{observation_date}",
                raw={"endpoint": endpoint, **dict(row)},
            )
        )
    observations.sort(key=lambda item: item.observation_date)
    return observations[-limit:]


def _wikimedia_pageview_source_parts(source: str) -> tuple[str, str]:
    value = source.split(":", 1)[1].strip() if source.startswith("wikipediapageviews:") else source.strip()
    if not value:
        raise ValidationError("wikipediapageviews source is required")
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        project = parsed.netloc.lower()
        path = parsed.path.strip("/")
        article = parsed.path.split("/wiki/", 1)[1] if "/wiki/" in parsed.path else path
    elif "/" in value and "." in value.split("/", 1)[0]:
        project, article = value.split("/", 1)
    else:
        project = "en.wikipedia.org"
        article = value
    project = project.strip().lower()
    article = unquote(article).strip().lstrip("/")
    if article.startswith("wiki/"):
        article = article[5:]
    article = article.replace(" ", "_")
    if not project or not article:
        raise ValidationError("wikipediapageviews source must include a project and article")
    return project, article


def _wikimedia_pageviews_endpoint(
    project: str,
    article: str,
    access: str,
    agent: str,
    start_date,
    end_date,
    *,
    api_base_url: str,
) -> str:
    start = _wikimedia_pageview_date_param(start_date)
    end = _wikimedia_pageview_date_param(end_date)
    parts = [project, access, agent, article, "daily", start, end]
    path = "/".join(quote(part, safe="") for part in parts)
    return f"{api_base_url.rstrip('/')}/{path}"


def _wikimedia_pageview_date_param(value) -> str:
    return f"{value.year:04d}{value.month:02d}{value.day:02d}00"


def _wikimedia_pageview_timestamp(value: object) -> tuple[str | None, str | None]:
    text = _optional_str(value)
    if text is None:
        return None, None
    if len(text) >= 8 and text[:8].isdigit():
        raw_date = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        try:
            parsed_date = _fred_date(raw_date, field_name="wikimedia pageview timestamp")
        except ValidationError:
            return None, None
        if parsed_date is None:
            return None, None
        return parsed_date.isoformat(), _fred_date_to_iso(parsed_date)
    try:
        parsed = parse_timestamp(text, field_name="wikimedia pageview timestamp")
    except ValidationError:
        return None, None
    parsed_dt = timestamp_to_datetime(parsed)
    if parsed_dt is None:
        return None, None
    parsed_date = parsed_dt.date()
    return parsed_date.isoformat(), _fred_date_to_iso(parsed_date)


def _wikimedia_pageview_count(value: object) -> int | None:
    number = _optional_float(value)
    if number is None or number < 0:
        return None
    return int(number)
