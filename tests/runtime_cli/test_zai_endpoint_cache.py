"""Endpoint discovery persists metadata without changing credential ownership."""

from superforecasting_agent.runtime import auth
from superforecasting_agent.storage.auth import load_auth_store, save_auth_store


def test_detected_endpoint_survives_reload_without_switching_active_provider(
    tmp_path, monkeypatch
):
    path = tmp_path / "auth.json"
    monkeypatch.setattr(auth, "_auth_file_path", lambda: path)
    save_auth_store(path, {"providers": {}, "active_provider": "selected-provider"})
    calls = []

    def detect(key):
        calls.append(key)
        # A concurrent configuration/credential write during the network probe.
        current = load_auth_store(path)
        current["providers"]["zai"] = {"other_metadata": "keep"}
        current["unrelated"] = "concurrent value"
        save_auth_store(path, current)
        return {
            "base_url": "https://fixture.invalid/coding",
            "id": "fixture",
            "label": "Fixture",
        }

    monkeypatch.setattr(auth, "detect_zai_endpoint", detect)
    for _ in range(2):
        assert (
            auth._resolve_zai_base_url("fixture-key", "https://default.invalid", "")
            == "https://fixture.invalid/coding"
        )
    assert calls == ["fixture-key"]
    recovered = load_auth_store(path)
    assert recovered["active_provider"] == "selected-provider"
    assert recovered["unrelated"] == "concurrent value"
    assert recovered["providers"]["zai"]["other_metadata"] == "keep"
    assert "fixture-key" not in path.read_text(encoding="utf-8")


def test_probe_cannot_publish_into_a_replacement_profile(tmp_path, monkeypatch):
    paths = [tmp_path / "one.json", tmp_path / "two.json"]
    for index, path in enumerate(paths):
        save_auth_store(path, {"providers": {}, "active_provider": f"selected-{index}"})
    replacement_before = paths[1].read_bytes()
    active = [paths[0]]
    monkeypatch.setattr(auth, "_auth_file_path", lambda: active[0])

    def detect(key):
        active[0] = paths[1]
        return {"base_url": "https://fixture.invalid", "label": "Fixture"}

    monkeypatch.setattr(auth, "detect_zai_endpoint", detect)
    assert (
        auth._resolve_zai_base_url("fixture-key", "https://default.invalid", "")
        == "https://fixture.invalid"
    )
    assert "detected_endpoint" in load_auth_store(paths[0])["providers"]["zai"]
    assert paths[1].read_bytes() == replacement_before


def test_cache_failure_does_not_discard_successful_detection(
    tmp_path, monkeypatch, caplog
):
    from superforecasting_agent.storage import auth as store

    path = tmp_path / "auth.json"
    monkeypatch.setattr(auth, "_auth_file_path", lambda: path)
    monkeypatch.setattr(
        auth, "detect_zai_endpoint", lambda key: {"base_url": "https://fixture.invalid"}
    )

    def fail(*args, **kwargs):
        raise OSError("fixture write failure")

    monkeypatch.setattr(store, "save_auth_store", fail)
    assert (
        auth._resolve_zai_base_url("fixture-key", "https://default.invalid", "")
        == "https://fixture.invalid"
    )
    assert "could not persist endpoint cache" in caplog.text
    assert "fixture-key" not in caplog.text
    assert not path.exists()
