"""Load gdelt source records as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timezone
from urllib.parse import urlencode
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .public_records import GdeltArticle
from .values import _first_present, _optional_str

def load_gdelt_articles(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    timespan: str | None = None,
    source_country: str | None = None,
    source_lang: str | None = None,
    api_base_url: str = "https://api.gdeltproject.org/api/v2/doc/doc",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[GdeltArticle]:
    """Load GDELT DOC 2.0 article-list results as timestamped evidence."""

    if not query.strip():
        raise ValidationError("gdelt import query is required")
    if limit <= 0:
        raise ValidationError("gdelt import --limit must be positive")
    since_iso = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_iso) if since_iso else None
    params: dict[str, object] = {
        "query": _gdelt_augmented_query(
            query,
            source_country=source_country,
            source_lang=source_lang,
        ),
        "mode": "ArtList",
        "format": "json",
        "maxrecords": min(limit, 250),
        "sort": "DateDesc",
    }
    if timespan:
        params["timespan"] = timespan
    if since_iso:
        params["startdatetime"] = _gdelt_datetime_parameter(since_iso)
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "gdelt article list")
    if isinstance(payload, dict):
        rows = payload.get("articles")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValidationError("gdelt article list response must contain an articles array")

    articles: list[GdeltArticle] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        published_at = _gdelt_timestamp(
            _first_present(row.get("seendate"), row.get("seenDate"), row.get("date"), row.get("publishedAt"))
        )
        if since_dt is not None:
            article_dt = timestamp_to_datetime(published_at)
            if article_dt is None or article_dt < since_dt:
                continue
        title = _optional_str(row.get("title")) or "Untitled GDELT article"
        url = _optional_str(row.get("url"))
        domain = _optional_str(row.get("domain"))
        source_country_value = _optional_str(_first_present(row.get("sourcecountry"), row.get("sourceCountry")))
        language = _optional_str(row.get("language"))
        source_name = domain or source_country_value or "GDELT"
        articles.append(
            GdeltArticle(
                title=title,
                summary=_optional_str(_first_present(row.get("summary"), row.get("snippet"), row.get("description")))
                or "",
                url=url,
                published_at=published_at,
                source_name=source_name,
                entry_id=_optional_str(_first_present(row.get("id"), url, title)),
                domain=domain,
                source_country=source_country_value,
                language=language,
                image_url=_optional_str(_first_present(row.get("socialimage"), row.get("image"))),
                raw=dict(row),
            )
        )
        if len(articles) >= limit:
            break
    return articles


def _gdelt_augmented_query(query: str, *, source_country: str | None, source_lang: str | None) -> str:
    parts = [query.strip()]
    if source_country:
        parts.append(f"sourcecountry:{_gdelt_query_operator_value(source_country)}")
    if source_lang:
        parts.append(f"sourcelang:{_gdelt_query_operator_value(source_lang)}")
    return " ".join(part for part in parts if part)


def _gdelt_query_operator_value(value: str) -> str:
    return "".join(str(value).strip().lower().split())


def _gdelt_datetime_parameter(value: str) -> str:
    parsed = timestamp_to_datetime(value)
    if parsed is None:
        raise ValidationError("gdelt timestamp cannot be empty")
    return parsed.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def _gdelt_timestamp(value: object) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    try:
        if len(raw) == 14 and raw.isdigit():
            from datetime import datetime

            parsed = datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if len(raw) == 16 and raw.endswith("Z") and raw[8] == "T":
            from datetime import datetime

            parsed = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return parse_timestamp(raw, field_name="gdelt timestamp")
    except (ValueError, ValidationError):
        return None
