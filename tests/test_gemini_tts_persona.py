"""Gemini TTS persona-prompt (harvested from upstream hermes-agent): an optional
performance-direction file that shapes how the agent's Gemini voice speaks. Default
(no file configured) is byte-identical to before — the transcript passes through."""

from __future__ import annotations

import tools.tts_tool as tts


def test_compose_without_persona_returns_transcript_unchanged():
    assert tts._compose_gemini_tts_prompt("hello world", {}) == "hello world"
    assert tts._compose_gemini_tts_prompt("hi", {"persona_prompt_file": ""}) == "hi"
    assert tts._compose_gemini_tts_prompt("hi", {"persona_prompt_file": "   "}) == "hi"


def test_resolve_path_blank_or_missing_is_none():
    assert tts._resolve_gemini_persona_prompt_path({}) is None
    assert tts._resolve_gemini_persona_prompt_path({"persona_prompt_file": ""}) is None


def test_resolve_path_absolute_passthrough(tmp_path):
    f = tmp_path / "persona.md"
    f.write_text("x")
    assert tts._resolve_gemini_persona_prompt_path({"persona_prompt_file": str(f)}) == f


def test_read_missing_file_fails_soft(tmp_path):
    cfg = {"persona_prompt_file": str(tmp_path / "nope.md")}
    assert tts._read_gemini_persona_prompt(cfg) == ""


def test_compose_substitutes_transcript_placeholder(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("DIRECTOR'S NOTES: whisper conspiratorially.\n#### LINE\n{transcript}")
    out = tts._compose_gemini_tts_prompt("the secret code is 1234", {"persona_prompt_file": str(f)})
    assert "the secret code is 1234" in out
    assert "whisper conspiratorially" in out
    assert "{transcript}" not in out  # placeholder substituted, not spoken literally


def test_compose_appends_transcript_when_no_placeholder(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("SCENE: a quiet study at midnight.")
    out = tts._compose_gemini_tts_prompt("good evening", {"persona_prompt_file": str(f)})
    assert "quiet study at midnight" in out
    assert "good evening" in out
    assert "TRANSCRIPT" in out  # appended under the heading
