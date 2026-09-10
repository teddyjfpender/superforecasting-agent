"""Load openfda research records as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .research_records import OpenFdaDrugApplication
from .values import _collapse_ws, _collapse_optional, _first_present, _optional_str

def load_openfda_drug_applications(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.fda.gov/drug/drugsfda.json",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[OpenFdaDrugApplication]:
    """Load openFDA Drugs@FDA application records as regulatory evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("openfda:") else source.strip()
    if not normalized_source:
        raise ValidationError("openfda import query, application number, or API URL is required")
    if limit <= 0:
        raise ValidationError("openfda import --limit must be positive")
    since_iso = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_iso) if since_iso else None
    endpoint = _openfda_endpoint(normalized_source, limit=limit, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "openFDA Drugs@FDA applications")
    rows = _openfda_application_rows(payload)

    applications: list[OpenFdaDrugApplication] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        application_number = _collapse_optional(row.get("application_number"))
        if not application_number:
            continue
        latest = _openfda_latest_submission(row.get("submissions"))
        latest_submission_status_date = _openfda_date_to_iso(
            _first_present(latest.get("submission_status_date"), latest.get("submission_date"))
        )
        if since_dt is not None:
            application_dt = timestamp_to_datetime(latest_submission_status_date)
            if application_dt is None or application_dt < since_dt:
                continue
        openfda = row.get("openfda") if isinstance(row.get("openfda"), dict) else {}
        products = row.get("products") if isinstance(row.get("products"), list) else []
        brand_names = _openfda_unique(
            _openfda_list(openfda.get("brand_name")) + _openfda_product_values(products, "brand_name")
        )
        generic_names = _openfda_unique(
            _openfda_list(openfda.get("generic_name")) + _openfda_product_values(products, "generic_name")
        )
        routes = _openfda_unique(_openfda_list(openfda.get("route")) + _openfda_product_values(products, "route"))
        substances = _openfda_unique(
            _openfda_list(openfda.get("substance_name")) + _openfda_active_ingredient_names(products)
        )
        dosage_forms = _openfda_unique(_openfda_product_values(products, "dosage_form"))
        marketing_statuses = _openfda_unique(_openfda_product_values(products, "marketing_status"))
        url = _openfda_application_url(application_number, latest)
        applications.append(
            OpenFdaDrugApplication(
                application_number=application_number,
                sponsor_name=_collapse_optional(row.get("sponsor_name")),
                brand_names=brand_names,
                generic_names=generic_names,
                routes=routes,
                substances=substances,
                dosage_forms=dosage_forms,
                marketing_statuses=marketing_statuses,
                latest_submission_status=_collapse_optional(latest.get("submission_status")),
                latest_submission_status_date=latest_submission_status_date,
                latest_submission_type=_collapse_optional(latest.get("submission_type")),
                latest_submission_class=_collapse_optional(
                    _first_present(latest.get("submission_class_code"), latest.get("submission_class_code_description"))
                ),
                url=url,
                source_name="openFDA Drugs@FDA",
                entry_id=application_number,
                raw=dict(row),
            )
        )
        if len(applications) >= limit:
            break
    return applications


def _openfda_endpoint(source: str, *, limit: int, api_base_url: str) -> str:
    value = source.strip()
    parsed = urlparse(value)
    params: dict[str, str | int] = {}
    if parsed.scheme in {"http", "https"}:
        endpoint_base = value.split("?", 1)[0].rstrip("?&")
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    else:
        endpoint_base = api_base_url.rstrip("?&")
        if "=" in value and not _looks_like_openfda_application_number(value):
            params = dict(parse_qsl(value.lstrip("?"), keep_blank_values=True))
        else:
            params["search"] = _openfda_search_query(value)
    params.setdefault("limit", min(limit, 100))
    separator = "&" if "?" in endpoint_base else "?"
    return f"{endpoint_base}{separator}{urlencode(params)}"


def _openfda_search_query(value: str) -> str:
    source = value.strip()
    if not source:
        raise ValidationError("openfda source is required")
    if _looks_like_openfda_application_number(source):
        return f'application_number:"{source.upper()}"'
    if ":" in source or " " in source and any(operator in source.upper() for operator in (" AND ", " OR ", " NOT ")):
        return source
    quoted = source.replace('"', r"\"")
    return (
        f'(openfda.brand_name:"{quoted}" OR '
        f'openfda.generic_name:"{quoted}" OR '
        f'sponsor_name:"{quoted}" OR '
        f'products.brand_name:"{quoted}")'
    )


def _looks_like_openfda_application_number(value: str) -> bool:
    raw = "".join(value.strip().upper().split())
    prefixes = ("NDA", "ANDA", "BLA")
    if any(raw.startswith(prefix) and raw[len(prefix) :].isdigit() for prefix in prefixes):
        return True
    return raw.isdigit() and 3 <= len(raw) <= 8


def _openfda_application_rows(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        rows = payload.get("results")
    else:
        rows = payload
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    raise ValidationError("openFDA Drugs@FDA response must contain a results array")


def _openfda_date_to_iso(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    raw = "".join(text.split())
    if len(raw) == 8 and raw.isdigit():
        raw = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    try:
        return parse_timestamp(raw, field_name="openFDA date")
    except ValidationError:
        return None


def _openfda_latest_submission(value: object) -> dict:
    if not isinstance(value, list):
        return {}
    latest: dict = {}
    latest_date = ""
    for row in value:
        if not isinstance(row, dict):
            continue
        date_text = _optional_str(_first_present(row.get("submission_status_date"), row.get("submission_date"))) or ""
        normalized_date = "".join(date_text.split())
        if normalized_date >= latest_date:
            latest = row
            latest_date = normalized_date
    return latest


def _openfda_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [_collapse_ws(str(item)) for item in value if _optional_str(item)]
    text = _optional_str(value)
    return [_collapse_ws(text)] if text else []


def _openfda_product_values(products: object, key: str) -> list[str]:
    if not isinstance(products, list):
        return []
    values: list[str] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        values.extend(_openfda_list(product.get(key)))
    return values


def _openfda_active_ingredient_names(products: object) -> list[str]:
    if not isinstance(products, list):
        return []
    names: list[str] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        ingredients = product.get("active_ingredients")
        if not isinstance(ingredients, list):
            continue
        for ingredient in ingredients:
            if not isinstance(ingredient, dict):
                continue
            label = _collapse_optional(ingredient.get("name"))
            if label:
                names.append(label)
    return names


def _openfda_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = _collapse_ws(value)
        key = normalized.lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def _openfda_application_url(application_number: str, latest_submission: dict) -> str:
    docs = latest_submission.get("application_docs")
    if isinstance(docs, list):
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            url = _optional_str(doc.get("url"))
            if url:
                return url
    digits = "".join(ch for ch in application_number if ch.isdigit())
    if digits:
        return f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={digits}"
    return "https://www.accessdata.fda.gov/scripts/cder/daf/"
