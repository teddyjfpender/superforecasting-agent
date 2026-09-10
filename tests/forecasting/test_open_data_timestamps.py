"""Invalid numeric metadata timestamps must not abort open-data imports."""

import pytest
from forecasting import source_adapters


@pytest.mark.parametrize("source", ["socrata", "ckan"])
@pytest.mark.parametrize("raw, expected", [
    pytest.param(float("inf"), None, id="infinite"),
    pytest.param(1e100, None, id="out-of-range"),
    pytest.param(10**400, None, id="integer-overflow"),
    pytest.param(1700000000, "2023-11-14T22:13:20Z", id="seconds"),
    pytest.param(1700000000000, "2023-11-14T22:13:20Z", id="milliseconds"),
])
def test_numeric_timestamps_preserve_valid_records(monkeypatch, source, raw, expected):
    valid = "2026-05-22T11:30:00Z"
    if source == "socrata":
        payload = [{"id": "first", "updated_at": raw}, {"id": "second", "updated_at": valid}]
        loader = source_adapters.load_socrata_records
        query = "data.example.test/abcd-1234"
        field = "updated_at"
    else:
        payload = {"success": True, "result": {"results": [
            {"id": "first", "metadata_modified": raw},
            {"id": "second", "metadata_modified": valid},
        ]}}
        loader = source_adapters.load_ckan_datasets
        query = "data.example.test/fixture"
        field = "metadata_modified"
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *_: payload)

    records = loader(query)

    assert len(records) == 2
    assert getattr(records[0], field) == expected
    assert getattr(records[1], field) == valid
