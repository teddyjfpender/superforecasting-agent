"""The gateway must stop TTS playback on shutdown — otherwise the afplay/ffplay child is
orphaned and keeps speaking after the TUI is gone. _stop_audio_playback() is wired into
both the termination signal handler (synchronously, before the grace timer can os._exit)
and atexit (the clean stdin-EOF path)."""

from __future__ import annotations

import superforecasting_agent.runtime.voice as hv
import tools.voice_mode as vm
import tui_gateway.entry as entry


def test_stop_audio_playback_terminates_player_and_recorder(monkeypatch):
    calls = []
    monkeypatch.setattr(vm, "stop_playback", lambda: calls.append("player"))
    monkeypatch.setattr(hv, "stop_continuous", lambda: calls.append("recorder"))
    entry._stop_audio_playback()
    assert calls == ["player", "recorder"]


def test_stop_audio_playback_swallows_player_error(monkeypatch):
    def _boom():
        raise RuntimeError("device busy")

    monkeypatch.setattr(vm, "stop_playback", _boom)
    monkeypatch.setattr(hv, "stop_continuous", lambda: None)
    entry._stop_audio_playback()  # must not raise — shutdown can't be blocked


def test_stop_audio_playback_idle_is_noop():
    # No playback active: stop_playback finds _active_playback is None -> harmless.
    entry._stop_audio_playback()


def test_stop_playback_terminates_the_tracked_process(monkeypatch):
    # The mechanism stop_playback relies on: terminate the retained player handle.
    class _FakeProc:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return None  # still running

        def terminate(self):
            self.terminated = True

    proc = _FakeProc()
    monkeypatch.setattr(vm, "_active_playback", proc)
    vm.stop_playback()
    assert proc.terminated is True
    assert vm._active_playback is None  # cleared so a later call is a no-op
