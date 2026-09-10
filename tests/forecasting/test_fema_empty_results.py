"""Empty declaration arrays are valid responses, including legacy wrappers."""
import pytest
from forecasting import source_adapters


@pytest.mark.parametrize("key", ["DisasterDeclarationsSummaries", "value", "results", "data"])
def test_fema_empty_results(monkeypatch, key):
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: {key: []})
    assert source_adapters.load_fema_disaster_declarations("TX") == []


def test_fema_primary_empty_array_does_not_use_other_records(monkeypatch):
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: {
        "DisasterDeclarationsSummaries": [],
        "results": [{"id": "stale", "declarationTitle": "Stale record"}],
    })
    assert source_adapters.load_fema_disaster_declarations("TX") == []


def test_fema_legacy_records_remain_supported(monkeypatch):
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: {
        "results": [{"id": "fixture", "declarationTitle": "Fixture record"}]
    })
    rows = source_adapters.load_fema_disaster_declarations("TX")
    assert len(rows) == 1
    assert rows[0].title == "Fixture record"
