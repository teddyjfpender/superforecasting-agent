"""Load cisa_kev vulnerability records as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .technology_records import CisaKevVulnerability
from .dates import _optional_iso_timestamp
from .values import _collapse_ws, _first_present, _optional_str

def load_cisa_kev_vulnerabilities(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[CisaKevVulnerability]:
    """Load CISA Known Exploited Vulnerabilities records as security evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("cisakev:") else source.strip()
    if not normalized_source:
        raise ValidationError("cisakev import query, CVE id, all, or catalog URL is required")
    if limit <= 0:
        raise ValidationError("cisakev import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None

    parsed = urlparse(normalized_source)
    is_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    endpoint = normalized_source if is_url else api_base_url
    filter_query = "" if is_url else normalized_source
    payload = _read_json_endpoint(endpoint, "cisa kev catalog")
    if isinstance(payload, dict):
        rows = payload.get("vulnerabilities")
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValidationError("cisa kev catalog response must include a vulnerabilities array")

    vulnerabilities: list[CisaKevVulnerability] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cve_id = _optional_str(_first_present(row.get("cveID"), row.get("cveId"), row.get("cve_id")))
        if not cve_id:
            continue
        if filter_query and not _cisa_kev_matches_query(row, filter_query):
            continue
        date_added = _cisa_kev_timestamp(row.get("dateAdded"))
        added_dt = timestamp_to_datetime(date_added) if date_added else None
        if since_dt is not None and added_dt is not None and added_dt < since_dt:
            continue
        vulnerability_name = _collapse_ws(
            _optional_str(row.get("vulnerabilityName")) or f"CISA KEV record for {cve_id}"
        )
        vulnerabilities.append(
            CisaKevVulnerability(
                cve_id=cve_id,
                vendor_project=_optional_str(row.get("vendorProject")),
                product=_optional_str(row.get("product")),
                vulnerability_name=vulnerability_name,
                short_description=_collapse_ws(_optional_str(row.get("shortDescription")) or ""),
                date_added=date_added,
                due_date=_cisa_kev_timestamp(row.get("dueDate")),
                required_action=_collapse_ws(_optional_str(row.get("requiredAction")) or ""),
                ransomware_use=_optional_str(row.get("knownRansomwareCampaignUse")),
                notes=_collapse_ws(_optional_str(row.get("notes")) or ""),
                cwes=_cisa_kev_cwes(row.get("cwes")),
                source_url=endpoint,
                source_name="CISA Known Exploited Vulnerabilities",
                entry_id=cve_id,
                raw={
                    "cveID": row.get("cveID"),
                    "vendorProject": row.get("vendorProject"),
                    "product": row.get("product"),
                    "vulnerabilityName": row.get("vulnerabilityName"),
                    "dateAdded": row.get("dateAdded"),
                    "dueDate": row.get("dueDate"),
                    "knownRansomwareCampaignUse": row.get("knownRansomwareCampaignUse"),
                    "query": filter_query or normalized_source,
                },
            )
        )
        if len(vulnerabilities) >= limit:
            break
    return vulnerabilities


def _cisa_kev_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='cisa kev timestamp')


def _cisa_kev_matches_query(row: dict, query: str) -> bool:
    normalized = query.strip().lower()
    if normalized in {"*", "all", "latest"}:
        return True
    cve_id = _optional_str(_first_present(row.get("cveID"), row.get("cveId"), row.get("cve_id")))
    if cve_id and normalized == cve_id.lower():
        return True
    haystack = " ".join(
        str(value)
        for value in (
            row.get("cveID"),
            row.get("vendorProject"),
            row.get("product"),
            row.get("vulnerabilityName"),
            row.get("shortDescription"),
            row.get("requiredAction"),
            row.get("knownRansomwareCampaignUse"),
            row.get("notes"),
            row.get("cwes"),
        )
        if value not in (None, "")
    ).lower()
    return normalized in haystack


def _cisa_kev_cwes(value: object) -> list[str]:
    if isinstance(value, list):
        return [text for item in value for text in [_optional_str(item)] if text]
    text = _optional_str(value)
    if not text:
        return []
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
