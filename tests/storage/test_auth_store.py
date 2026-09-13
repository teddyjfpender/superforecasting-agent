"""Credential-store compatibility through the presentation-independent owner."""

import json

import pytest

from superforecasting_agent.storage.auth import load_auth_store, save_auth_store


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            {"credential_pool": {"nous": [{"label": "fixture"}]}},
            {"credential_pool": {"nous": [{"label": "fixture"}]}, "providers": {}},
        ),
        (
            {"systems": {"nous_portal": {"account": "fixture"}}},
            {
                "version": 1,
                "providers": {"nous": {"account": "fixture"}},
                "active_provider": "nous",
            },
        ),
    ],
)
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
    path.write_text("{broken", encoding="utf-8")
    assert load_auth_store(path) == {"version": 1, "providers": {}}
    assert path.read_text(encoding="utf-8") == "{broken"
    assert path.with_suffix(".json.corrupt").read_text(encoding="utf-8") == "{broken"


@pytest.mark.parametrize("local", [[], None, "malformed"])
def test_empty_or_malformed_local_pool_uses_global_candidates(local):
    from superforecasting_agent.storage.auth import select_credential_pool

    profile = {"credential_pool": {"fixture": local}}
    fallback = {"credential_pool": {"fixture": [{"source": "global"}]}}
    assert select_credential_pool(profile, fallback, "fixture") == [
        {"source": "global"}
    ]
    assert select_credential_pool(profile, fallback)["fixture"] == [
        {"source": "global"}
    ]


def test_nonempty_local_pool_shadows_global_and_returns_independent_records():
    from superforecasting_agent.storage.auth import select_credential_pool

    profile = {"credential_pool": {"fixture": [{"metadata": {"source": "local"}}]}}
    fallback = {
        "credential_pool": {
            "fixture": [{"metadata": {"source": "global"}}],
            "other": [{"metadata": {"source": "global-other"}}],
        }
    }
    selected = select_credential_pool(profile, fallback, "fixture")
    assert selected == [{"metadata": {"source": "local"}}]
    selected[0]["metadata"]["source"] = "caller mutation"
    merged = select_credential_pool(profile, fallback)
    assert merged["fixture"] == [{"metadata": {"source": "local"}}]
    merged["other"][0]["metadata"]["source"] = "another mutation"
    assert (
        fallback["credential_pool"]["other"][0]["metadata"]["source"] == "global-other"
    )
    assert profile["credential_pool"]["fixture"][0]["metadata"]["source"] == "local"


@pytest.mark.parametrize("invalid", [None, [], "malformed"])
def test_malformed_pool_roots_do_not_invent_candidates(invalid):
    from superforecasting_agent.storage.auth import select_credential_pool

    assert (
        select_credential_pool(
            {"credential_pool": invalid}, {"credential_pool": invalid}
        )
        == {}
    )
    assert (
        select_credential_pool({}, {"credential_pool": {"fixture": invalid}}, "fixture")
        == []
    )


def test_provider_state_presence_and_explicit_activation():
    from superforecasting_agent.storage.auth import provider_state, set_provider_state

    store = {
        "active_provider": "previous",
        "providers": {"previous": {"source": "retained"}},
    }
    assert provider_state(store, "fixture") is None
    set_provider_state(store, "fixture", {}, set_active=False)
    assert provider_state(store, "fixture") == {}  # present, not absent
    assert store["active_provider"] == "previous"
    set_provider_state(store, "fixture", {"source": "new"})
    assert store["active_provider"] == "fixture"
    assert store["providers"]["previous"] == {"source": "retained"}


def test_every_store_write_strips_borrowed_pool_secrets_without_changing_runtime_values(
    tmp_path,
):
    store = {
        "providers": {},
        "credential_pool": {
            "fixture": [
                {
                    "source": "env:FIXTURE_TOKEN",
                    "access_token": "fixture-borrowed-secret",
                    "label": "borrowed",
                },
                {
                    "source": "manual",
                    "access_token": "fixture-owned-secret",
                    "label": "owned",
                },
            ]
        },
    }
    path = tmp_path / "auth.json"
    save_auth_store(path, store)
    written = json.loads(path.read_text(encoding="utf-8"))
    borrowed, owned = written["credential_pool"]["fixture"]
    assert "fixture-borrowed-secret" not in path.read_text(encoding="utf-8")
    assert borrowed["source"] == "env:FIXTURE_TOKEN"
    assert borrowed["secret_fingerprint"].startswith("sha256:")
    assert owned["access_token"] == "fixture-owned-secret"
    assert (
        store["credential_pool"]["fixture"][0]["access_token"]
        == "fixture-borrowed-secret"
    )


@pytest.mark.parametrize("secret_key", ["accessToken", "refresh-token", "api.key"])
def test_borrowed_nested_secrets_are_removed_but_metadata_and_inputs_survive(
    tmp_path, secret_key
):
    from copy import deepcopy

    entry = {
        "source": "external:fixture",
        "metadata": {
            "region": "fixture-region",
            "nested": [{secret_key: "nested-fixture-secret", "label": "retained"}],
        },
    }
    original = deepcopy(entry)
    path = tmp_path / "auth.json"
    save_auth_store(path, {"providers": {}, "credential_pool": {"fixture": [entry]}})
    persisted = json.loads(path.read_text(encoding="utf-8"))["credential_pool"][
        "fixture"
    ][0]
    assert persisted == {
        "source": "external:fixture",
        "metadata": {"region": "fixture-region", "nested": [{"label": "retained"}]},
    }
    assert entry == original


def test_legacy_policy_exports_share_the_storage_owner():
    from agent import credential_persistence as legacy
    from superforecasting_agent.storage import credential_policy as shared

    assert (
        legacy.sanitize_borrowed_credential_payload
        is shared.sanitize_borrowed_credential_payload
    )
    assert legacy.is_borrowed_credential_source is shared.is_borrowed_credential_source
