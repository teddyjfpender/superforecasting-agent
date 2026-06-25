"""speak_text single-flight: a reply is spoken once, start to finish. The gateway can
re-fire the TTS trigger (goal continuations / async notifications) and the voice.tts RPC
can race it; without a guard two calls overlapped and (with second-resolution temp names)
shared one file — call B rewrote + restarted call A's audio ("jumps back to the start")."""

from __future__ import annotations

import pytest

import hermes_cli.voice as v
import tools.tts_tool as tt
import tools.voice_mode as vm


@pytest.fixture(autouse=True)
def _reset_single_flight():
    v._tts_active_text = None
    yield
    v._tts_active_text = None


def _wire(monkeypatch):
    state = {"synth": [], "played": [], "stops": 0}

    def _synth(text, output_path):
        state["synth"].append(output_path)
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 64)

    monkeypatch.setattr(tt, "text_to_speech_tool", _synth)
    monkeypatch.setattr(v, "play_audio_file", lambda p: state["played"].append(p) or True)

    def _stop():
        state["stops"] += 1

    monkeypatch.setattr(vm, "stop_playback", _stop)
    return state


def test_identical_reply_already_speaking_is_deduped(monkeypatch):
    state = _wire(monkeypatch)
    v._tts_active_text = "the market moved"  # an utterance currently owns the speaker
    v.speak_text("the market moved")  # the re-fire of the SAME reply
    assert state["synth"] == []  # never synthesized
    assert state["played"] == []  # never played -> no restart-from-start


def test_new_reply_supersedes_in_flight_and_plays(monkeypatch):
    state = _wire(monkeypatch)
    v._tts_active_text = "an older reply"  # something is in flight
    v.speak_text("a genuinely new reply")
    assert state["stops"] == 1  # cancelled the in-flight player (latest wins)
    assert len(state["synth"]) == 1 and len(state["played"]) == 1
    assert v._tts_active_text is None  # ownership released after finishing


def test_filenames_are_unique_per_call(monkeypatch):
    state = _wire(monkeypatch)
    v.speak_text("first reply")
    v.speak_text("second reply")
    assert len(state["synth"]) == 2
    assert state["synth"][0] != state["synth"][1]  # no same-second collision


def test_empty_text_is_ignored(monkeypatch):
    state = _wire(monkeypatch)
    v.speak_text("   ")
    assert state["synth"] == [] and state["stops"] == 0
