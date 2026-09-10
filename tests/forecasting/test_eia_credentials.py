"""EIA authenticates requests without publishing credentials as evidence URLs."""

import json
from dataclasses import asdict
from urllib.parse import parse_qsl, urlparse

import pytest

from forecasting import source_adapters


@pytest.mark.parametrize("source, api_key", [
    ("PET.RWTC.M", "fixture-eia-secret"),
    ("https://eia.test/series/?series_id=PET.RWTC.M&api_key=fixture-eia-secret", None),
    ("https://eia.test/series/?series_id=PET.RWTC.M&%61pi_key=fixture-eia-secret&api_key=second-secret&keep=", None),
])
def test_eia_evidence_excludes_request_credentials(monkeypatch, source, api_key):
    requested = []

    def read(endpoint, label):
        requested.append(endpoint)
        return {"response": {"data": [{"period": "2026-03", "value": "72.5"}]}}

    monkeypatch.setattr(source_adapters, "_read_json_endpoint", read)
    rows = source_adapters.load_eia_observations(source, api_key=api_key)
    request_pairs = parse_qsl(urlparse(requested[0]).query, keep_blank_values=True)
    assert ("api_key", "fixture-eia-secret") in request_pairs
    assert len(rows) == 1 and rows[0].value == 72.5
    public_pairs = parse_qsl(urlparse(rows[0].source_url).query, keep_blank_values=True)
    assert public_pairs == [(k, v) for k, v in request_pairs if k.lower() != "api_key"]
    payload = json.dumps(asdict(rows[0]))
    assert "fixture-eia-secret" not in payload
    assert "second-secret" not in payload
