"""Optional fiscal-year metadata must not abort company-fact imports."""
import pytest
from forecasting import source_adapters


@pytest.mark.parametrize("year,expected", [(float("inf"), None), (float("-inf"), None),
                                           (2024, 2024), ("2024", 2024)])
def test_company_fact_fiscal_year_is_optional(monkeypatch, year, expected):
    payload = {"cik": 320193, "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"end": "2024-09-28", "val": 100, "fy": year, "filed": "2024-11-01"},
        {"end": "2025-09-27", "val": 200, "fy": 2025, "filed": "2025-11-01"},
    ]}}}}}
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args, **kwargs: payload)
    rows = source_adapters.load_sec_company_facts("secfacts:320193/Revenues")
    assert len(rows) == 2
    assert rows[0].fiscal_year == expected
    assert rows[0].value == 100
    assert rows[1].fiscal_year == 2025
