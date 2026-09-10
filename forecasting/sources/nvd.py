"""Load nvd vulnerability records as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote, urlencode
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .technology_records import NvdCve
from .dates import _optional_iso_timestamp
from .values import _collapse_ws, _optional_float, _optional_str

def load_nvd_cves(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://services.nvd.nist.gov/rest/json/cves/2.0",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[NvdCve]:
    """Load NVD CVE records as timestamped security evidence."""

    normalized_query = query.split(":", 1)[1].strip() if query.startswith("nvd:") else query.strip()
    if not normalized_query:
        raise ValidationError("nvd import query is required")
    if limit <= 0:
        raise ValidationError("nvd import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    params: dict[str, object] = {"resultsPerPage": min(limit, 2000)}
    if normalized_query.upper().startswith("CVE-"):
        params["cveIds"] = normalized_query.upper()
    else:
        params["keywordSearch"] = normalized_query
    endpoint = f"{api_base_url.rstrip('/')}?{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "nvd cves")
    if not isinstance(payload, dict) or not isinstance(payload.get("vulnerabilities"), list):
        raise ValidationError("nvd cves response must include a vulnerabilities array")

    cves: list[NvdCve] = []
    for row in payload["vulnerabilities"]:
        if not isinstance(row, dict):
            continue
        cve = row.get("cve")
        if not isinstance(cve, dict):
            continue
        cve_id = _optional_str(cve.get("id"))
        if not cve_id:
            continue
        published_at = _nvd_timestamp(cve.get("published"))
        published_dt = timestamp_to_datetime(published_at) if published_at else None
        if since_dt is not None and published_dt is not None and published_dt < since_dt:
            continue
        severity, base_score, cvss_version = _nvd_cvss_summary(cve.get("metrics"))
        references = _nvd_references(cve.get("references"))
        cves.append(
            NvdCve(
                cve_id=cve_id,
                description=_nvd_description(cve.get("descriptions")),
                url=f"https://nvd.nist.gov/vuln/detail/{quote(cve_id, safe='')}",
                published_at=published_at,
                last_modified_at=_nvd_timestamp(cve.get("lastModified")),
                vuln_status=_optional_str(cve.get("vulnStatus")),
                severity=severity,
                base_score=base_score,
                cvss_version=cvss_version,
                references=references,
                source_identifier=_optional_str(cve.get("sourceIdentifier")),
                source_name="NVD",
                entry_id=cve_id,
                raw={
                    "id": cve.get("id"),
                    "published": cve.get("published"),
                    "lastModified": cve.get("lastModified"),
                    "vulnStatus": cve.get("vulnStatus"),
                    "severity": severity,
                    "base_score": base_score,
                    "cvss_version": cvss_version,
                    "query": normalized_query,
                },
            )
        )
        if len(cves) >= limit:
            break
    return cves


def _nvd_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='nvd timestamp')


def _nvd_description(value: object) -> str:
    if not isinstance(value, list):
        return ""
    fallback = ""
    for row in value:
        if not isinstance(row, dict):
            continue
        description = _optional_str(row.get("value"))
        if not description:
            continue
        if not fallback:
            fallback = description
        if _optional_str(row.get("lang")) == "en":
            return _collapse_ws(description)
    return _collapse_ws(fallback)


def _nvd_references(value: object) -> list[str]:
    rows = value.get("referenceData") if isinstance(value, dict) else value
    if not isinstance(rows, list):
        return []
    urls: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = _optional_str(row.get("url"))
        if url:
            urls.append(url)
    return urls


def _nvd_cvss_summary(value: object) -> tuple[str | None, float | None, str | None]:
    if not isinstance(value, dict):
        return None, None, None
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        rows = value.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        metric = rows[0] if isinstance(rows[0], dict) else {}
        data = metric.get("cvssData") if isinstance(metric.get("cvssData"), dict) else {}
        severity = (
            _optional_str(data.get("baseSeverity"))
            or _optional_str(metric.get("baseSeverity"))
            or _optional_str(metric.get("severity"))
        )
        base_score = _optional_float(data.get("baseScore"))
        cvss_version = _optional_str(data.get("version"))
        return severity, base_score, cvss_version
    return None, None, None
