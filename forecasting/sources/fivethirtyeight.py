"""Load fivethirtyeight source records as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
import csv
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .economic_records import FiveThirtyEightPollObservation
from .values import _collapse_optional, _first_present, _optional_float, _optional_int, _optional_str

def load_fivethirtyeight_polls(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    state: str | None = None,
    candidate: str | None = None,
    pollster: str | None = None,
    cycle: int | None = None,
    office_type: str | None = None,
    api_base_url: str = "https://projects.fivethirtyeight.com/polls-page/data",
    _read_text_endpoint: Callable[[str, str], str],
) -> list[FiveThirtyEightPollObservation]:
    """Load FiveThirtyEight polling CSV rows as timestamped public-opinion evidence."""

    dataset, endpoint = _fivethirtyeight_poll_endpoint(source, api_base_url=api_base_url)
    if not dataset:
        raise ValidationError("fivethirtyeight import dataset or CSV URL is required")
    if limit <= 0:
        raise ValidationError("fivethirtyeight import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    state_filter = state.strip().casefold() if state else None
    candidate_filter = candidate.strip().casefold() if candidate else None
    pollster_filter = pollster.strip().casefold() if pollster else None
    office_filter = office_type.strip().casefold() if office_type else None

    text = _read_text_endpoint(endpoint, "fivethirtyeight polls")
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ValidationError("fivethirtyeight polls CSV has no header row")

    observations: list[FiveThirtyEightPollObservation] = []
    for index, row in enumerate(reader):
        if not isinstance(row, dict):
            continue
        row_state = _collapse_optional(_first_present(row.get("state"), row.get("seat_name")))
        row_candidate = _collapse_optional(_first_present(row.get("candidate_name"), row.get("candidate"), row.get("answer")))
        row_pollster = _collapse_optional(
            _first_present(row.get("pollster"), row.get("display_name"), row.get("pollster_name"))
        )
        row_office = _collapse_optional(_first_present(row.get("office_type"), row.get("office")))
        row_cycle = _optional_int(row.get("cycle"))

        if state_filter and (row_state or "").casefold() != state_filter:
            continue
        if candidate_filter and candidate_filter not in (row_candidate or "").casefold():
            continue
        if pollster_filter and pollster_filter not in (row_pollster or "").casefold():
            continue
        if office_filter and (row_office or "").casefold() != office_filter:
            continue
        if cycle is not None and row_cycle != cycle:
            continue

        start_date = _fivethirtyeight_date(_first_present(row.get("start_date"), row.get("startDate")))
        end_date = _fivethirtyeight_date(_first_present(row.get("end_date"), row.get("endDate")))
        published_at = _fivethirtyeight_timestamp(
            _first_present(
                row.get("created_at"),
                row.get("createdAt"),
                row.get("published_at"),
                row.get("updated_at"),
                row.get("last_updated"),
                end_date,
            )
        )
        if since_dt is not None:
            published_dt = timestamp_to_datetime(published_at)
            if published_dt is None or published_dt < since_dt:
                continue

        pct = _optional_float(_first_present(row.get("pct"), row.get("percent"), row.get("value")))
        sample_size = _fivethirtyeight_sample_size(
            _first_present(row.get("sample_size"), row.get("samplesize"), row.get("sampleSize"))
        )
        poll_id = _optional_str(row.get("poll_id"))
        question_id = _optional_str(row.get("question_id"))
        answer = _collapse_optional(row.get("answer"))
        entry_id = ":".join(
            part
            for part in (
                dataset,
                poll_id,
                question_id,
                row_candidate or answer,
                str(index),
            )
            if part
        )
        observations.append(
            FiveThirtyEightPollObservation(
                dataset=dataset,
                poll_id=poll_id,
                question_id=question_id,
                pollster=row_pollster,
                pollster_grade=_collapse_optional(
                    _first_present(row.get("fte_grade"), row.get("pollster_rating_name"), row.get("grade"))
                ),
                race_id=_optional_str(row.get("race_id")),
                office_type=row_office,
                state=row_state,
                cycle=row_cycle,
                stage=_collapse_optional(row.get("stage")),
                candidate_name=row_candidate,
                answer=answer,
                party=_collapse_optional(row.get("party")),
                pct=pct,
                sample_size=sample_size,
                population=_collapse_optional(row.get("population")),
                start_date=start_date,
                end_date=end_date,
                published_at=published_at,
                source_url=_optional_str(row.get("url")) or endpoint,
                source_name=row_pollster or "FiveThirtyEight Polls",
                entry_id=entry_id,
                raw={"row_index": index, "endpoint": endpoint, **dict(row)},
            )
        )
    observations.sort(
        key=lambda item: (
            timestamp_to_datetime(item.published_at)
            or datetime.min.replace(tzinfo=timezone.utc),
            item.poll_id or "",
            item.question_id or "",
            item.candidate_name or item.answer or "",
        )
    )
    return observations[-limit:]


def _fivethirtyeight_poll_endpoint(source: str, *, api_base_url: str) -> tuple[str, str]:
    raw = source.strip()
    if raw.startswith(("fivethirtyeight:", "538:")):
        raw = raw.split(":", 1)[1].strip()
    if not raw:
        return "", ""
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        dataset = Path(unquote(parsed.path)).name.removesuffix(".csv") or "polls"
        return dataset, raw

    aliases = {
        "president": "president_polls",
        "presidential": "president_polls",
        "president-polls": "president_polls",
        "senate": "senate_polls",
        "senate-polls": "senate_polls",
        "house": "house_polls",
        "house-polls": "house_polls",
        "governor": "governor_polls",
        "governor-polls": "governor_polls",
        "approval": "president_approval_polls",
        "president-approval": "president_approval_polls",
        "president-approval-polls": "president_approval_polls",
        "generic": "generic_ballot_polls",
        "generic-ballot": "generic_ballot_polls",
        "generic-ballot-polls": "generic_ballot_polls",
    }
    dataset = aliases.get(raw.strip().lower().removesuffix(".csv"), raw.strip().removesuffix(".csv"))
    if not dataset or any(character.isspace() for character in dataset) or "/" in dataset:
        raise ValidationError("fivethirtyeight source must be a dataset alias, dataset name, or CSV URL")
    base = api_base_url.strip()
    if not base:
        raise ValidationError("fivethirtyeight import --api-base-url cannot be empty")
    if "{dataset}" in base:
        return dataset, base.replace("{dataset}", quote(dataset, safe="_-."))
    if base.endswith(".csv"):
        return dataset, base
    return dataset, f"{base.rstrip('/')}/{quote(dataset, safe='_-')}.csv"


def _fivethirtyeight_date(value: object) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            from datetime import datetime

            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        parsed = parse_timestamp(raw, field_name="fivethirtyeight date")
    except ValidationError:
        return None
    parsed_dt = timestamp_to_datetime(parsed)
    return parsed_dt.date().isoformat() if parsed_dt is not None else None


def _fivethirtyeight_timestamp(value: object) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parsed_date = _fivethirtyeight_date(raw)
    if parsed_date and len(raw) <= 10:
        return f"{parsed_date}T00:00:00Z"
    try:
        return parse_timestamp(raw, field_name="fivethirtyeight timestamp")
    except ValidationError:
        return f"{parsed_date}T00:00:00Z" if parsed_date else None


def _fivethirtyeight_sample_size(value: object) -> float | int | None:
    number = _optional_float(value)
    if number is None:
        return None
    return int(number) if number.is_integer() else number
