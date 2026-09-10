"""Load reliefweb public records as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
import re
from urllib.parse import urlencode, urlparse
from forecasting import appconfig
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .public_records import ReliefWebReport
from .dates import _optional_iso_timestamp
from .values import _collapse_ws, _collapse_optional, _first_present, _optional_str

def load_reliefweb_reports(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    appname: str | None = None,
    api_base_url: str = "https://api.reliefweb.int/v1/reports",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[ReliefWebReport]:
    """Load ReliefWeb reports as humanitarian/disaster evidence."""

    normalized_query = query.split(":", 1)[1].strip() if query.startswith("reliefweb:") else query.strip()
    if not normalized_query:
        raise ValidationError("reliefweb import query or API URL is required")
    if limit <= 0:
        raise ValidationError("reliefweb import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _reliefweb_endpoint(
        normalized_query,
        limit=limit,
        since_ts=since_ts,
        appname=appname or appconfig.get_str("RELIEFWEB_APPNAME") or "superforecasting-agent",
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "reliefweb reports")
    rows = _reliefweb_rows(payload)

    reports: list[ReliefWebReport] = []
    for row in rows:
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else row
        if not isinstance(fields, dict):
            continue
        report_id = _optional_str(_first_present(row.get("id"), fields.get("id")))
        published_at = _reliefweb_timestamp(_first_present(_reliefweb_date(fields, "created"), fields.get("date.created")))
        changed_at = _reliefweb_timestamp(_first_present(_reliefweb_date(fields, "changed"), fields.get("date.changed")))
        published_dt = timestamp_to_datetime(published_at) if published_at else None
        if since_dt is not None and published_dt is not None and published_dt < since_dt:
            continue
        title = _collapse_ws(_optional_str(fields.get("title")) or "Untitled ReliefWeb report")
        sources = _reliefweb_names(fields.get("source"))
        countries = _reliefweb_names(fields.get("country"))
        disasters = _reliefweb_names(fields.get("disaster"))
        formats = _reliefweb_names(fields.get("format"))
        themes = _reliefweb_names(fields.get("theme"))
        url = _optional_str(_first_present(fields.get("url"), row.get("href")))
        summary = _reliefweb_summary(fields)
        reports.append(
            ReliefWebReport(
                report_id=report_id,
                title=title,
                summary=summary,
                url=url,
                published_at=published_at,
                changed_at=changed_at,
                sources=sources,
                countries=countries,
                disasters=disasters,
                formats=formats,
                themes=themes,
                source_name=", ".join(sources[:2]) if sources else "ReliefWeb",
                entry_id=report_id or url or title,
                raw={
                    "id": report_id,
                    "href": row.get("href"),
                    "title": fields.get("title"),
                    "date": fields.get("date"),
                    "sources": sources,
                    "countries": countries,
                    "disasters": disasters,
                    "formats": formats,
                    "themes": themes,
                    "query": normalized_query,
                },
            )
        )
        if len(reports) >= limit:
            break
    return reports


def _reliefweb_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='reliefweb timestamp')


def _reliefweb_endpoint(
    source: str,
    *,
    limit: int,
    since_ts: str | None,
    appname: str,
    api_base_url: str,
) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source
    endpoint_base = api_base_url.rstrip("?&")
    params: dict[str, object] = {
        "appname": appname,
        "query[value]": source,
        "limit": min(limit, 100),
        "sort[]": "date.created:desc",
        "fields[include][]": [
            "title",
            "body",
            "body-html",
            "date",
            "source",
            "country",
            "disaster",
            "format",
            "theme",
            "url",
        ],
    }
    if since_ts:
        since_dt = timestamp_to_datetime(since_ts)
        if since_dt is not None:
            params["filter[field]"] = "date.created"
            params["filter[value][from]"] = since_dt.date().isoformat()
    separator = "&" if "?" in endpoint_base else "?"
    return f"{endpoint_base}{separator}{urlencode(params, doseq=True)}"


def _reliefweb_rows(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        for key in ("data", "results", "reports"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    raise ValidationError("reliefweb reports response must include a data array")


def _reliefweb_date(fields: dict, key: str) -> object | None:
    date_value = fields.get("date")
    if isinstance(date_value, dict):
        return date_value.get(key)
    return None


def _reliefweb_names(value: object) -> list[str]:
    if isinstance(value, dict):
        label = _optional_str(_first_present(value.get("name"), value.get("shortname"), value.get("title")))
        return [_collapse_ws(label)] if label else []
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, dict):
                label = _optional_str(_first_present(item.get("name"), item.get("shortname"), item.get("title")))
            else:
                label = _optional_str(item)
            if label:
                names.append(_collapse_ws(label))
        return names
    label = _optional_str(value)
    return [_collapse_ws(label)] if label else []


def _reliefweb_summary(fields: dict) -> str:
    summary = _collapse_optional(fields.get("body")) or _collapse_optional(fields.get("summary"))
    if summary:
        return summary
    html_text = _optional_str(fields.get("body-html"))
    if not html_text:
        return ""
    return _collapse_ws(re.sub(r"<[^>]+>", " ", html_text))
