"""Load clinicaltrials research records as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, quote, urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .research_records import ClinicalTrialStudy
from .values import _collapse_ws, _collapse_optional, _first_present, _optional_str

def load_clinicaltrials_studies(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://clinicaltrials.gov/api/v2/studies",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[ClinicalTrialStudy]:
    """Load ClinicalTrials.gov studies as timestamped health/biotech evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("clinicaltrials:") else source.strip()
    if not normalized_source:
        raise ValidationError("clinicaltrials import query, NCT id, or API URL is required")
    if limit <= 0:
        raise ValidationError("clinicaltrials import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _clinicaltrials_endpoint(normalized_source, limit=limit, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "clinicaltrials studies")
    raw_studies = _clinicaltrials_study_rows(payload)

    studies: list[ClinicalTrialStudy] = []
    for row in raw_studies:
        if not isinstance(row, dict):
            continue
        protocol = row.get("protocolSection")
        if not isinstance(protocol, dict):
            protocol = {}
        identification = protocol.get("identificationModule")
        status = protocol.get("statusModule")
        design = protocol.get("designModule")
        conditions = protocol.get("conditionsModule")
        interventions = protocol.get("armsInterventionsModule")
        sponsors = protocol.get("sponsorCollaboratorsModule")
        identification = identification if isinstance(identification, dict) else {}
        status = status if isinstance(status, dict) else {}
        design = design if isinstance(design, dict) else {}
        conditions = conditions if isinstance(conditions, dict) else {}
        interventions = interventions if isinstance(interventions, dict) else {}
        sponsors = sponsors if isinstance(sponsors, dict) else {}

        nct_id = _optional_str(identification.get("nctId"))
        if not nct_id:
            continue
        last_update_posted_at = _clinicaltrials_date_to_iso(
            _first_present(status.get("lastUpdatePostDateStruct"), status.get("lastUpdatePostDate"))
        )
        last_update_submitted_at = _clinicaltrials_date_to_iso(
            _first_present(status.get("lastUpdateSubmitDate"), status.get("lastUpdateSubmittedDate"))
        )
        updated_at = last_update_posted_at or last_update_submitted_at
        updated_dt = timestamp_to_datetime(updated_at) if updated_at else None
        if since_dt is not None and updated_dt is not None and updated_dt < since_dt:
            continue

        brief_title = _collapse_ws(
            _optional_str(_first_present(identification.get("briefTitle"), identification.get("officialTitle")))
            or nct_id
        )
        study = ClinicalTrialStudy(
            nct_id=nct_id,
            brief_title=brief_title,
            official_title=_collapse_optional(identification.get("officialTitle")),
            url=f"https://clinicaltrials.gov/study/{quote(nct_id, safe='')}",
            status=_optional_str(status.get("overallStatus")),
            phases=_clinicaltrials_list(design.get("phases")),
            study_type=_optional_str(design.get("studyType")),
            conditions=_clinicaltrials_list(conditions.get("conditions")),
            interventions=_clinicaltrials_interventions(interventions.get("interventions")),
            sponsors=_clinicaltrials_sponsors(sponsors),
            start_date=_clinicaltrials_date_to_iso(_first_present(status.get("startDateStruct"), status.get("startDate"))),
            primary_completion_date=_clinicaltrials_date_to_iso(
                _first_present(status.get("primaryCompletionDateStruct"), status.get("primaryCompletionDate"))
            ),
            completion_date=_clinicaltrials_date_to_iso(
                _first_present(status.get("completionDateStruct"), status.get("completionDate"))
            ),
            last_update_submitted_at=last_update_submitted_at,
            last_update_posted_at=last_update_posted_at,
            has_results=bool(row.get("hasResults")),
            source_name="ClinicalTrials.gov",
            entry_id=nct_id,
            raw=dict(row),
        )
        studies.append(study)
        if len(studies) >= limit:
            break
    return studies


def _clinicaltrials_endpoint(source: str, *, limit: int, api_base_url: str) -> str:
    value = source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        endpoint_base = value.split("?", 1)[0].rstrip("?&")
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    else:
        endpoint_base = api_base_url.rstrip("?&")
        params = dict(parse_qsl(value.lstrip("?"), keep_blank_values=True)) if "=" in value else {}
        if not params:
            if value.upper().startswith("NCT"):
                params["query.id"] = value.upper()
            else:
                params["query.term"] = value
    params.setdefault("format", "json")
    params["pageSize"] = min(max(limit, 1), 1000)
    return f"{endpoint_base}?{urlencode(params)}"


def _clinicaltrials_study_rows(payload: object) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("studies"), list):
        return [row for row in payload["studies"] if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("protocolSection"), dict):
        return [payload]
    raise ValidationError("clinicaltrials studies response must contain a studies array")


def _clinicaltrials_date_to_iso(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("date")
    text = _optional_str(value)
    if not text:
        return None
    raw = text.strip()
    if len(raw) == 4 and raw.isdigit():
        raw = f"{raw}-01-01"
    elif len(raw) == 7 and raw[4] == "-" and raw[:4].isdigit() and raw[5:].isdigit():
        raw = f"{raw}-01"
    try:
        return parse_timestamp(raw, field_name="clinicaltrials date")
    except ValidationError:
        return None


def _clinicaltrials_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [_collapse_ws(value)] if value.strip() else []
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        text = _optional_str(item)
        if text:
            rows.append(_collapse_ws(text))
    return rows


def _clinicaltrials_interventions(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = _first_present(item.get("name"), item.get("type"))
        else:
            text = item
        label = _optional_str(text)
        if label:
            rows.append(_collapse_ws(label))
    return rows


def _clinicaltrials_sponsors(value: dict) -> list[str]:
    rows: list[str] = []
    lead = value.get("leadSponsor")
    if isinstance(lead, dict):
        label = _optional_str(lead.get("name"))
        if label:
            rows.append(_collapse_ws(label))
    collaborators = value.get("collaborators")
    if isinstance(collaborators, list):
        for item in collaborators:
            if not isinstance(item, dict):
                continue
            label = _optional_str(item.get("name"))
            if label:
                rows.append(_collapse_ws(label))
    return rows
