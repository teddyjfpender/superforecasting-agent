"""The gateway brackets TTS playback with voice.status speaking/idle so the TUI can show
a 'speaking' audiogram for the real duration, and exposes voice.stop to cut it off."""

from __future__ import annotations

import superforecasting_agent.runtime.voice as hv
import tui_gateway.server as srv


def test_speak_with_status_brackets_speaking_then_idle(monkeypatch):
    events = []
    monkeypatch.setattr(srv, "_emit", lambda ev, sid, payload: events.append((ev, sid, payload.get("state"))))
    monkeypatch.setattr(hv, "speak_text", lambda t: None)
    srv._speak_with_status("hello", "sid-1")
    assert events == [("voice.status", "sid-1", "speaking"), ("voice.status", "sid-1", "idle")]


def test_speak_with_status_emits_idle_even_when_tts_raises(monkeypatch):
    states = []
    monkeypatch.setattr(srv, "_emit", lambda ev, sid, payload: states.append(payload.get("state")))

    def _boom(_t):
        raise RuntimeError("tts failed")

    monkeypatch.setattr(hv, "speak_text", _boom)
    srv._speak_with_status("hi", "sid-2")
    assert states == ["speaking", "idle"]  # idle still fires in finally -> audiogram clears


def test_speak_with_status_no_sid_emits_nothing(monkeypatch):
    seen = []
    monkeypatch.setattr(srv, "_emit", lambda *a, **k: seen.append(1))
    monkeypatch.setattr(hv, "speak_text", lambda t: None)
    srv._speak_with_status("hi", "")
    assert seen == []
