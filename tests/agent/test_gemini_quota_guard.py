from __future__ import annotations

from agent import gemini_quota_guard as guard


def test_gemini_quota_guard_is_shared_and_clearable(tmp_path, monkeypatch):
    state = tmp_path / "rate_limits" / "gemini.json"
    monkeypatch.setattr(guard, "_state_path", lambda: str(state))
    monkeypatch.setattr(guard.time, "time", lambda: 1_000.0)

    guard.record_gemini_quota(cooldown_seconds=120)

    assert guard.gemini_quota_remaining() == 120
    guard.clear_gemini_quota()
    assert guard.gemini_quota_remaining() is None


def test_expired_gemini_quota_guard_removes_itself(tmp_path, monkeypatch):
    state = tmp_path / "rate_limits" / "gemini.json"
    monkeypatch.setattr(guard, "_state_path", lambda: str(state))
    monkeypatch.setattr(guard.time, "time", lambda: 1_000.0)
    guard.record_gemini_quota(cooldown_seconds=10)
    monkeypatch.setattr(guard.time, "time", lambda: 1_011.0)

    assert guard.gemini_quota_remaining() is None
    assert not state.exists()


def test_gemini_endpoint_detection_covers_provider_and_public_api():
    assert guard.is_gemini_endpoint("gemini", None)
    assert guard.is_gemini_endpoint(
        "openai-compatible", "https://generativelanguage.googleapis.com/v1beta"
    )
    assert not guard.is_gemini_endpoint("openai-codex", "https://api.openai.com/v1")
