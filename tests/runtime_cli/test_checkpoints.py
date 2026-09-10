"""Tests for checkpoint CLI guidance."""

from __future__ import annotations

from argparse import Namespace


def test_status_legacy_hint_uses_fork_native_command(monkeypatch, capsys):
    import superforecasting_agent.runtime.checkpoints as checkpoints
    import tools.checkpoint_manager as checkpoint_manager

    monkeypatch.setattr(
        checkpoint_manager,
        "store_status",
        lambda: {
            "base": "/tmp/checkpoints",
            "total_size_bytes": 512,
            "store_size_bytes": 0,
            "legacy_size_bytes": 512,
            "project_count": 0,
            "projects": [],
            "legacy_archives": [
                {"name": "legacy-20260521", "size_bytes": 512, "mtime": 1},
            ],
        },
    )

    assert checkpoints.cmd_status(Namespace(limit=20)) == 0

    out = capsys.readouterr().out
    assert "Clear with: superforecasting-agent checkpoints clear-legacy" in out
