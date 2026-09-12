"""Credential-store compatibility through the presentation-independent owner."""

import json

import pytest

from superforecasting_agent.storage.auth import load_auth_store, save_auth_store


@pytest.mark.parametrize("raw,expected", [
    ({"credential_pool": {"nous": [{"label": "fixture"}]}}, {"credential_pool": {"nous": [{"label": "fixture"}]}, "providers": {}}),
    ({"systems": {"nous_portal": {"account": "fixture"}}}, {"version": 1, "providers": {"nous": {"account": "fixture"}}, "active_provider": "nous"}),
])
def test_legacy_credentials_survive_load_save_roundtrip(tmp_path, raw, expected):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = load_auth_store(path)
    assert loaded == expected
    save_auth_store(path, loaded)
    recovered = load_auth_store(path)
    for key, value in expected.items():
        assert recovered[key] == value
    assert recovered["version"] == 1
    assert recovered["updated_at"]


def test_unparseable_store_is_preserved_for_recovery(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text('{broken', encoding="utf-8")
    assert load_auth_store(path) == {"version": 1, "providers": {}}
    assert path.read_text(encoding="utf-8") == '{broken'
    assert path.with_suffix('.json.corrupt').read_text(encoding="utf-8") == '{broken'
