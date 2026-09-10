"""Load OpenFEMA disaster declarations as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
import re
from urllib.parse import parse_qsl, urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .environment_records import FemaDisasterDeclaration
from .values import _collapse_optional, _first_present, _optional_bool, _optional_int

def load_fema_disaster_declarations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    state: str | None = None,
    incident_type: str | None = None,
    declaration_type: str | None = None,
    api_base_url: str = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[FemaDisasterDeclaration]:
    """Load OpenFEMA Disaster Declarations Summaries v2 rows as evidence."""

    if limit <= 0:
        raise ValidationError("fema import --limit must be positive")
    endpoint = _fema_disaster_declarations_endpoint(
        source,
        limit=limit,
        state=state,
        incident_type=incident_type,
        declaration_type=declaration_type,
        api_base_url=api_base_url,
    )
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    payload = _read_json_endpoint(endpoint, "FEMA disaster declarations")
    if isinstance(payload, dict):
        rows = next((payload[key] for key in ("DisasterDeclarationsSummaries", "value", "results", "data")
                     if isinstance(payload.get(key), list)), None)
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValidationError("FEMA disaster declarations response must include a declarations array")

    declarations: list[FemaDisasterDeclaration] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        declaration_date = _fema_timestamp(row.get("declarationDate"))
        if since_dt is not None:
            declaration_dt = timestamp_to_datetime(declaration_date)
            if declaration_dt is not None and declaration_dt < since_dt:
                continue
        incident_begin_date = _fema_timestamp(row.get("incidentBeginDate"))
        incident_end_date = _fema_timestamp(row.get("incidentEndDate"))
        last_refresh = _fema_timestamp(row.get("lastRefresh"))
        disaster_number = _optional_int(row.get("disasterNumber"))
        declaration_string = _collapse_optional(row.get("femaDeclarationString"))
        state_value = _collapse_optional(row.get("state"))
        declaration_type_value = _collapse_optional(row.get("declarationType"))
        incident_type_value = _collapse_optional(row.get("incidentType"))
        designated_area = _collapse_optional(row.get("designatedArea"))
        title = _collapse_optional(row.get("declarationTitle")) or _collapse_optional(
            _first_present(row.get("title"), incident_type_value, declaration_string)
        )
        entry_id = _collapse_optional(_first_present(row.get("id"), row.get("hash"), declaration_string))
        if not entry_id:
            entry_id = ":".join(
                part
                for part in (
                    str(disaster_number) if disaster_number is not None else None,
                    state_value,
                    designated_area,
                    declaration_date,
                )
                if part
            )
        if not title or not entry_id:
            continue
        declarations.append(
            FemaDisasterDeclaration(
                disaster_number=disaster_number,
                declaration_string=declaration_string,
                state=state_value,
                declaration_type=declaration_type_value,
                declaration_date=declaration_date,
                fiscal_year=_optional_int(row.get("fyDeclared")),
                incident_type=incident_type_value,
                title=title,
                designated_area=designated_area,
                incident_begin_date=incident_begin_date,
                incident_end_date=incident_end_date,
                individual_assistance=_optional_bool(row.get("iaProgramDeclared")),
                public_assistance=_optional_bool(row.get("paProgramDeclared")),
                hazard_mitigation=_optional_bool(row.get("hmProgramDeclared")),
                last_refresh=last_refresh,
                source_url=endpoint,
                source_name="FEMA Disaster Declarations Summaries",
                entry_id=entry_id,
                raw=dict(row),
            )
        )
        if len(declarations) >= limit:
            break
    return declarations


def _fema_disaster_declarations_endpoint(
    source: str,
    *,
    limit: int,
    state: str | None,
    incident_type: str | None,
    declaration_type: str | None,
    api_base_url: str,
) -> str:
    value = source.split(":", 1)[1].strip() if source.startswith("fema:") else source.strip()
    if not value:
        raise ValidationError("fema source must be an API URL, disaster number, state, incident type, or query params")

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        endpoint_base = value.split("?", 1)[0].rstrip("?&")
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=False))
    else:
        endpoint_base = api_base_url.rstrip("?&")
        query_params = {}
        if "=" in value:
            query_params.update(dict(parse_qsl(value.lstrip("?"), keep_blank_values=False)))
        elif value.isdigit():
            query_params["disasterNumber"] = value
        elif re.fullmatch(r"[A-Za-z]{2}", value):
            query_params["state"] = value.upper()
        else:
            query_params["incidentType"] = value

    if state:
        query_params["state"] = state.strip().upper()
    if incident_type:
        query_params["incidentType"] = incident_type.strip()
    if declaration_type:
        query_params["declarationType"] = declaration_type.strip().upper()

    filter_parts: list[str] = []
    existing_filter = query_params.pop("$filter", None)
    if existing_filter:
        filter_parts.append(existing_filter)

    for key in list(query_params):
        if key in {"limit", "top"}:
            query_params["$top"] = query_params.pop(key)
            continue
        if key.startswith("$"):
            continue
        raw_value = query_params.pop(key)
        filter_parts.append(_fema_filter_expression(key, raw_value))

    if filter_parts:
        query_params["$filter"] = " and ".join(filter_parts)
    query_params.setdefault("$top", str(min(max(limit, 1), 1000)))
    query_params.setdefault("$orderby", "declarationDate desc")

    separator = "&" if "?" in endpoint_base else "?"
    return f"{endpoint_base}{separator}{urlencode(query_params)}"


def _fema_filter_expression(field: str, value: str) -> str:
    field_name = field.strip()
    aliases = {
        "area": "designatedArea",
        "county": "designatedArea",
        "declaration": "declarationType",
        "declaration_title": "declarationTitle",
        "declaration_type": "declarationType",
        "designated_area": "designatedArea",
        "disaster": "disasterNumber",
        "disaster_number": "disasterNumber",
        "fy": "fyDeclared",
        "fy_declared": "fyDeclared",
        "fiscal_year": "fyDeclared",
        "hm": "hmProgramDeclared",
        "hm_program_declared": "hmProgramDeclared",
        "ia": "iaProgramDeclared",
        "ia_program_declared": "iaProgramDeclared",
        "ih": "ihProgramDeclared",
        "ih_program_declared": "ihProgramDeclared",
        "incident": "incidentType",
        "incident_type": "incidentType",
        "pa": "paProgramDeclared",
        "pa_program_declared": "paProgramDeclared",
        "place_code": "placeCode",
        "title": "declarationTitle",
    }
    field_name = aliases.get(field_name, field_name)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", field_name):
        raise ValidationError("fema filter field names must be alphanumeric identifiers")
    numeric_fields = {"disasterNumber", "fyDeclared", "region", "placeCode"}
    bool_fields = {"ihProgramDeclared", "iaProgramDeclared", "paProgramDeclared", "hmProgramDeclared"}
    if field_name in numeric_fields:
        number = _optional_int(value)
        if number is None:
            raise ValidationError(f"fema filter {field_name} must be numeric")
        return f"{field_name} eq {number}"
    if field_name in bool_fields:
        bool_value = _optional_bool(value)
        if bool_value is None:
            raise ValidationError(f"fema filter {field_name} must be boolean")
        return f"{field_name} eq {str(bool_value).lower()}"
    text_value = value.strip()
    if field_name == "state":
        text_value = text_value.upper()
    escaped_value = text_value.replace("'", "''")
    return f"{field_name} eq '{escaped_value}'"


def _fema_timestamp(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        timestamp_value = text
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?", text):
        timestamp_value = f"{text}Z"
    else:
        timestamp_value = text
    try:
        return parse_timestamp(timestamp_value, field_name="FEMA timestamp")
    except ValidationError:
        return None
