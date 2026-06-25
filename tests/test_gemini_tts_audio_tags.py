"""Gemini expressive audio-tags TTS rewrite (harvested from upstream commit 2c1920822).
Default OFF + only fires on gemini-3.1*-tts models, so it's inert until opted into; the
auxiliary-model call fails soft to untagged text. The aux call is mocked — no network."""

from __future__ import annotations

import agent.auxiliary_client as aux
import tools.tts_tool as tts


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


# ── _config_bool ──────────────────────────────────────────────────────────────

def test_config_bool_spellings():
    assert tts._config_bool(True) is True and tts._config_bool(False) is False
    for truthy in ("1", "true", "yes", "on", "enabled", "  ON  "):
        assert tts._config_bool(truthy) is True
    for falsy in ("0", "false", "no", "off", "disabled"):
        assert tts._config_bool(falsy) is False
    assert tts._config_bool(None, default=True) is True  # unset -> default
    assert tts._config_bool("garbage", default=False) is False  # random string != true


# ── model gate + enabled gate ─────────────────────────────────────────────────

def test_model_supports_audio_tags():
    assert tts._gemini_model_supports_audio_tags("gemini-3.1-flash-tts") is True
    assert tts._gemini_model_supports_audio_tags("models/gemini-3.1-flash-tts") is True
    assert tts._gemini_model_supports_audio_tags("gemini-2.5-flash-preview-tts") is False
    assert tts._gemini_model_supports_audio_tags("gemini-3.1-pro") is False  # no tts


def test_audio_tags_enabled_gating():
    # default OFF (the inert default for our gemini-2.5 voice)
    assert tts._gemini_audio_tags_enabled({}, "gemini-2.5-flash-preview-tts") is False
    assert tts._gemini_audio_tags_enabled({}, "gemini-3.1-flash-tts") is False
    # enabled + supported model -> True
    assert tts._gemini_audio_tags_enabled({"audio_tags": True}, "gemini-3.1-flash-tts") is True
    # enabled but UNsupported model -> False (model gate wins)
    assert tts._gemini_audio_tags_enabled({"audio_tags": True}, "gemini-2.5-flash-preview-tts") is False
    # dict form {"enabled": ...}
    assert tts._gemini_audio_tags_enabled({"audio_tags": {"enabled": True}}, "gemini-3.1-flash-tts") is True
    assert tts._gemini_audio_tags_enabled({"audio_tags": {"enabled": False}}, "gemini-3.1-flash-tts") is False


# ── response cleaning / extraction ────────────────────────────────────────────

def test_clean_strips_code_fence():
    assert tts._clean_gemini_audio_tag_rewrite("```\n[whispers] hi\n```") == "[whispers] hi"
    assert tts._clean_gemini_audio_tag_rewrite("```text\nhi there\n```") == "hi there"
    assert tts._clean_gemini_audio_tag_rewrite("[laughs] plain") == "[laughs] plain"
    assert tts._clean_gemini_audio_tag_rewrite("") == ""


def test_extract_auxiliary_message_content_object_dict_and_garbage():
    assert tts._extract_auxiliary_message_content(_Resp("tagged text")) == "tagged text"

    class _DictChoice:
        message = {"content": "from dict"}

    class _DictResp:
        choices = [_DictChoice()]

    assert tts._extract_auxiliary_message_content(_DictResp()) == "from dict"
    assert tts._extract_auxiliary_message_content(None) == ""  # malformed -> ""
    assert tts._extract_auxiliary_message_content(object()) == ""


# ── the rewrite (aux call mocked) ─────────────────────────────────────────────

def test_rewrite_returns_tagged_script(monkeypatch):
    captured = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return _Resp("[excitedly] the market moved!")

    monkeypatch.setattr(aux, "call_llm", _fake)
    out = tts._rewrite_gemini_tts_audio_tags("the market moved!", persona_prompt="warm analyst")
    assert out == "[excitedly] the market moved!"
    assert captured["task"] == "tts_audio_tags"
    assert captured["temperature"] == 0.7
    assert "warm analyst" in captured["messages"][1]["content"]  # persona threaded into the user prompt


def test_rewrite_empty_text_returns_original():
    assert tts._rewrite_gemini_tts_audio_tags("   ") == "   "


def test_rewrite_fails_soft_on_aux_error(monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("No LLM provider configured")

    monkeypatch.setattr(aux, "call_llm", _boom)
    assert tts._rewrite_gemini_tts_audio_tags("hello world") == "hello world"  # untagged fallback


def test_rewrite_empty_model_response_falls_back(monkeypatch):
    monkeypatch.setattr(aux, "call_llm", lambda **kw: _Resp(""))
    assert tts._rewrite_gemini_tts_audio_tags("hello") == "hello"  # tagged or text -> text
