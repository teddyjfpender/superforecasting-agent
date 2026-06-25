"""Kokoro-82M local TTS provider (kokoro-onnx). The model + onnxruntime aren't installed
here, so the synth engine + the download are mocked — these cover the integration logic:
text chunking, the synth->WAV path, and the model-file resolution/fallback."""

from __future__ import annotations

import json
import wave

import numpy as np

import tools.tts_tool as tts


def test_split_empty_and_single_sentence():
    assert tts._kokoro_split_text("") == []
    assert tts._kokoro_split_text("Just one sentence.") == ["Just one sentence."]


def test_split_breaks_on_sentences_and_merges():
    out = tts._kokoro_split_text("Alpha. Beta. Gamma.", max_chars=8)
    assert len(out) >= 2
    assert "".join(out).replace(" ", "") == "Alpha.Beta.Gamma.".replace(" ", "")


def test_split_oversized_unpunctuated_run_is_not_truncated():
    big = " ".join(["word"] * 60)  # one long run, no sentence enders
    chunks = tts._kokoro_split_text(big, max_chars=40)
    assert len(chunks) > 1
    assert all(len(c) <= 40 for c in chunks)
    # no content loss: every word survives
    assert sum(c.count("word") for c in chunks) == 60


def test_kokoro_not_available_in_this_env():
    # kokoro-onnx isn't installed here -> availability check is False (drives the dispatch error)
    assert tts._check_kokoro_available() is False


def test_resolve_files_unknown_model_falls_back_and_downloads(monkeypatch, tmp_path):
    downloaded = []

    def _fake_dl(url, dest):
        downloaded.append(dest.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\x00")

    monkeypatch.setattr(tts, "_download_kokoro_file", _fake_dl)
    model, voices = tts._resolve_kokoro_files({"model": "bogus.onnx", "model_dir": str(tmp_path)})
    assert model.endswith("kokoro-v1.0.int8.onnx")  # unknown name -> default asset
    assert voices.endswith("voices-v1.0.bin")
    assert "kokoro-v1.0.int8.onnx" in downloaded and "voices-v1.0.bin" in downloaded


def test_generate_writes_24k_mono_wav(monkeypatch, tmp_path):
    class _FakeKokoro:
        def __init__(self, model, voices):
            pass

        def create(self, text, voice, speed, lang):
            assert voice == "af_heart"  # config voice threaded through
            return np.linspace(-0.5, 0.5, 4800, dtype=np.float32), 24000

    monkeypatch.setattr(tts, "_import_kokoro", lambda: _FakeKokoro)
    monkeypatch.setattr(tts, "_resolve_kokoro_files", lambda cfg: ("m.onnx", "v.bin"))
    tts._kokoro_model_cache.clear()

    out = str(tmp_path / "out.wav")
    tts._generate_kokoro_tts("Hello there. How are you today?", out, {"kokoro": {"voice": "af_heart"}})

    with wave.open(out, "rb") as wf:
        assert wf.getframerate() == 24000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        # the two short sentences merge into one chunk (< max_chars) -> one synth call
        assert wf.getnframes() == 4800


def test_kokoro_unavailable_falls_back_to_edge_not_error(monkeypatch, tmp_path):
    # Default is now 'kokoro'; without kokoro-onnx it must transparently use Edge, not error.
    monkeypatch.setattr(tts, "_get_provider", lambda cfg: "kokoro")
    monkeypatch.setattr(tts, "_check_kokoro_available", lambda: False)
    monkeypatch.setattr(tts, "_import_edge_tts", lambda: None)  # Edge "available"

    async def _fake_edge(text, output_path, cfg):
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 256)

    monkeypatch.setattr(tts, "_generate_edge_tts", _fake_edge)
    tts._KOKORO_FALLBACK_WARNED = False

    out = json.loads(tts.text_to_speech_tool("hello there", str(tmp_path / "out.mp3")))
    assert out.get("success") is True
    assert "kokoro-onnx is not installed" not in json.dumps(out)  # did NOT hit the error path
