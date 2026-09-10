"""Pure parsing helpers for SEC filings and company facts."""

from __future__ import annotations

import re
from urllib.parse import quote
from forecasting.models import ValidationError, parse_timestamp
from .dates import _fred_date, _fred_date_to_iso
from .values import _optional_float, _optional_str, _list_get

def _sec_search_cik(src: dict) -> str | None:
    ciks = src.get("ciks")
    if isinstance(ciks, list) and ciks:
        digits = "".join(ch for ch in str(ciks[0]) if ch.isdigit())
        if digits:
            return digits.zfill(10)
    names = src.get("display_names")
    if isinstance(names, list) and names:
        m = re.search(r"CIK\s*(\d{4,10})", str(names[0]))
        if m:
            return m.group(1).zfill(10)
    return None


def _sec_search_company(src: dict) -> str | None:
    names = src.get("display_names")
    if isinstance(names, list) and names:
        # "BLOOM ENERGY CORP  (BE)  (CIK 0001664703)" → strip the trailing tags.
        return re.sub(r"\s*\((?:CIK\s*\d+|[A-Z.\-]+)\)\s*", "", str(names[0])).strip() or None
    return None


def _sec_search_ticker(src: dict) -> str | None:
    names = src.get("display_names")
    if isinstance(names, list) and names:
        m = re.search(r"\(([A-Z][A-Z.\-]{0,6})\)", str(names[0]))
        if m:
            return m.group(1)
    return None


def _sec_submissions_endpoint(cik: str, *, api_base_url: str) -> str:
    return f"{api_base_url.rstrip('/')}/CIK{cik}.json"


def _sec_company_fact_unit_rows(units: dict, *, unit: str | None) -> tuple[str, list]:
    requested_unit = unit.strip() if unit and unit.strip() else None
    if requested_unit:
        rows = units.get(requested_unit)
        if not isinstance(rows, list):
            raise ValidationError(f"sec company facts concept has no {requested_unit} unit rows")
        return requested_unit, rows

    for candidate in ("USD", "shares", "pure"):
        rows = units.get(candidate)
        if isinstance(rows, list):
            return candidate, rows
    for candidate in sorted(str(key) for key in units):
        rows = units.get(candidate)
        if isinstance(rows, list):
            return candidate, rows
    raise ValidationError("sec company facts concept has no list-valued unit rows")


def _sec_company_fact_filed_at(value: str | None) -> str | None:
    filed = _fred_date(value, field_name="sec company fact filed")
    return _fred_date_to_iso(filed) if filed is not None else None


def _sec_company_fact_fiscal_year(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _sec_company_fact_value(value: object) -> float | int | str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int | float):
        return value
    parsed = _optional_float(value)
    if parsed is None:
        text = _optional_str(value)
        return text if text is not None else ""
    if parsed.is_integer():
        return int(parsed)
    return parsed


def _sec_filing_timestamp(acceptance_time: str | None, filing_date: str) -> str:
    if acceptance_time:
        try:
            return parse_timestamp(acceptance_time, field_name="sec acceptanceDateTime") or _fred_date_to_iso(
                _fred_date(filing_date, field_name="sec filingDate")
            )
        except ValidationError:
            pass
    filing = _fred_date(filing_date, field_name="sec filingDate")
    if filing is None:
        raise ValidationError("sec filingDate must be an ISO-8601 date")
    return _fred_date_to_iso(filing)


def _sec_filing_url(cik: str, accession_number: str, primary_document: str | None) -> str | None:
    if not primary_document:
        return None
    accession_path = accession_number.replace("-", "")
    cik_path = str(int(cik))
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_path}/{quote(primary_document)}"


def _sec_recent_row(recent: dict, index: int) -> dict:
    row: dict[str, object] = {}
    for key, value in recent.items():
        if isinstance(value, list):
            row[key] = _list_get(value, index)
    return row
