"""Load owid indicator observations as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
import csv
from pathlib import Path
from urllib.parse import quote, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .research_records import OwidObservation
from .values import _optional_float, _optional_str

def load_owid_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    entity: str | None = None,
    value_column: str | None = None,
    api_base_url: str = "https://ourworldindata.org/grapher",
    _read_text_endpoint: Callable[[str, str], str],
) -> list[OwidObservation]:
    """Load Our World in Data grapher CSV rows as data evidence."""

    slug, endpoint = _owid_endpoint(source, api_base_url=api_base_url)
    if limit <= 0:
        raise ValidationError("owid import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    text = _read_text_endpoint(endpoint, "owid grapher csv")
    return _owid_observations_from_text(text, slug=slug, endpoint=endpoint, entity=entity,
                                        value_column=value_column, since_dt=since_dt, limit=limit)


def _owid_observations_from_text(text, *, slug, endpoint, entity=None, value_column=None, since_dt=None, limit=10):
    """Parse an explicit measurement without inventing publication/vintage data."""
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames and len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValidationError("owid CSV has duplicate columns")
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValidationError("owid CSV row does not match its columns")
    if not rows:
        return []
    selected_value_column = value_column or _owid_value_column(rows[0])
    if selected_value_column not in rows[0] or selected_value_column in {"Entity", "Code", "Year", "Date"}:
        raise ValidationError("owid CSV is missing the requested measurement column")
    observations: list[OwidObservation] = []
    entity_filter = entity.casefold() if entity else None
    for row in rows:
        if entity_filter and (_optional_str(row.get("Entity")) or "").casefold() != entity_filter:
            continue
        observation_date = _optional_str(row.get("Year")) or _optional_str(row.get("Date"))
        if not observation_date:
            continue
        observation_time = _owid_date_to_iso(observation_date)
        if not observation_time:
            continue
        observation_dt = timestamp_to_datetime(observation_time)
        if since_dt is not None and observation_dt is not None and observation_dt < since_dt:
            continue
        raw_value = _optional_str(row.get(selected_value_column))
        value = _optional_float(raw_value)
        if raw_value is not None and value is None:
            raise ValidationError("owid measurement must be finite numeric data")
        observations.append(
            OwidObservation(
                slug=slug,
                entity=_optional_str(row.get("Entity")),
                code=_optional_str(row.get("Code")),
                observation_date=observation_date,
                value=value if value is not None else raw_value,
                value_column=selected_value_column,
                published_at=None,
                source_url=endpoint,
                source_name="Our World in Data",
                entry_id=f"{slug}:{row.get('Entity', '')}:{observation_date}",
                raw=dict(row),
            )
        )
        if len(observations) >= limit:
            break
    return observations


def _owid_endpoint(source: str, *, api_base_url: str) -> tuple[str, str]:
    value = source.split(":", 1)[1].strip() if source.startswith("owid:") else source.strip()
    if not value:
        raise ValidationError("owid source slug or URL is required")
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        slug = Path(parsed.path).name.removesuffix(".csv").removesuffix(".metadata.json")
        endpoint = value if value.endswith(".csv") else f"{value.rstrip('/')}.csv"
        return slug or "owid", endpoint
    slug = value.removesuffix(".csv").strip("/")
    if "/" in slug:
        raise ValidationError("owid source must be a grapher slug or CSV URL")
    endpoint = f"{api_base_url.rstrip('/')}/{quote(slug, safe='')}.csv"
    return slug, endpoint


def _owid_value_column(row: dict[str, str]) -> str:
    columns = [key for key in row if key not in {"Entity", "Code", "Year", "Date"}]
    if len(columns) != 1:
        raise ValidationError("owid CSV measurement is ambiguous; specify --value-column")
    return columns[0]


def _owid_date_to_iso(value: str) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    if text.isdigit() and len(text) == 4:
        text = f"{text}-01-01"
    try:
        return parse_timestamp(text, field_name="owid observation date")
    except ValidationError:
        return None
