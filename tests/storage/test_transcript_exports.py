"""Shared export collision, interruption and validation regressions."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace

import pytest

from superforecasting_agent.storage import transcripts


def test_concurrent_saves_in_same_second_do_not_replace_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(
        transcripts, "datetime", SimpleNamespace(now=lambda: datetime(2026, 9, 12))
    )

    def save(index):
        return transcripts.save_transcript(
            tmp_path,
            messages=[{"role": "user", "content": f"Forecast Ω {index}"}],
            model="test-model",
            session_id=f"session-{index}",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        paths = list(executor.map(save, range(12)))
    assert len(set(paths)) == 12
    for index, path in enumerate(paths):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["session_id"] == f"session-{index}"
        assert data["messages"][0]["content"] == f"Forecast Ω {index}"
    assert set((tmp_path / "sessions" / "saved").iterdir()) == set(paths)


def test_failed_serialization_leaves_no_partial_export(tmp_path):
    saved = transcripts.save_transcript(
        tmp_path, messages=[{"role": "user", "content": "Keep this"}],
        model="test-model", session_id="saved",
    )
    before = saved.read_bytes()
    with pytest.raises(TypeError):
        transcripts.save_transcript(
            tmp_path, messages=[{"role": "user", "content": object()}],
            model="test-model", session_id="failed",
        )
    assert saved.read_bytes() == before
    assert list(saved.parent.iterdir()) == [saved]


def test_empty_transcript_is_rejected_before_creating_export_directory(tmp_path):
    with pytest.raises(ValueError, match="No forecast transcript"):
        transcripts.save_transcript(tmp_path, messages=[], model="", session_id="empty")
    assert not (tmp_path / "sessions").exists()
