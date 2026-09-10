"""Preserve NVD evidence links across current and legacy reference formats.

NVD API schema: https://csrc.nist.gov/schema/nvd/api/2.0/cve_api_json_2.0.schema
The CVE references property is an array of reference objects, each with a URL.
"""
import pytest

from forecasting import source_adapters


@pytest.mark.parametrize("references,expected", [
    ([{"url": "https://example.com/advisory", "source": "fixture"},
      {"url": "https://example.com/patch", "tags": ["Patch"]}],
     ["https://example.com/advisory", "https://example.com/patch"]),
    ({"referenceData": [{"url": "https://example.com/legacy"}]}, ["https://example.com/legacy"]),
    ([None, "malformed", {}, {"url": ""}, {"url": "https://example.com/valid"}],
     ["https://example.com/valid"]),
    (None, []),
    ({"referenceData": "malformed"}, []),
    ([], []),
])
def test_nvd_loader_preserves_reference_links(monkeypatch, references, expected):
    payload = {"vulnerabilities": [{"cve": {
        "id": "CVE-2024-12345", "published": "2024-01-01T00:00:00Z",
        "lastModified": "2024-01-01T00:00:00Z",
        "descriptions": [{"lang": "en", "value": "Fixture record"}],
        "references": references,
    }}]}
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: payload)
    records = source_adapters.load_nvd_cves("CVE-2024-12345")
    assert len(records) == 1
    assert records[0].references == expected
    assert records[0].description == "Fixture record"
