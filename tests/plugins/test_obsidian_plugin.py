"""Tests for the obsidian plugin: vault primitives, tool handlers, learnings sync."""

from __future__ import annotations

import json

import pytest

from plugins.obsidian import _TOOLS, register
from plugins.obsidian.sync import sync_learnings
from plugins.obsidian.tools import (
    check_obsidian_available,
    handle_obsidian_append_note,
    handle_obsidian_read_note,
    handle_obsidian_search,
    handle_obsidian_sync_learnings,
    handle_obsidian_write_note,
)
from plugins.obsidian.vault import (
    MANAGED_BEGIN,
    MANAGED_END,
    render_frontmatter,
    resolve_vault_path,
    safe_note_path,
    slugify,
    splice_managed_block,
)


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault_dir))
    return vault_dir


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    from forecasting.ledger import ForecastLedger

    db = tmp_path / "ledger.db"
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(db))
    return ForecastLedger(db)


# ---------------------------------------------------------------------------
# Vault primitives
# ---------------------------------------------------------------------------

class TestVaultPrimitives:
    def test_resolve_vault_path_env(self, vault):
        assert resolve_vault_path() == vault

    def test_resolve_vault_path_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "nope"))
        assert resolve_vault_path() is None

    def test_safe_note_path_adds_md(self, vault):
        assert safe_note_path(vault, "Notes/idea").suffix == ".md"

    def test_safe_note_path_rejects_traversal(self, vault):
        with pytest.raises(ValueError):
            safe_note_path(vault, "../outside")
        with pytest.raises(ValueError):
            safe_note_path(vault, "/etc/passwd")

    def test_slugify(self):
        assert slugify("Will the FOMC cut rates?") == "will-the-fomc-cut-rates"

    def test_render_frontmatter_quotes_special(self):
        fm = render_frontmatter({"title": "a: b", "tags": ["x", "y"], "n": 3})
        assert fm.startswith("---\n")
        assert '"a: b"' in fm
        assert "tags: [x, y]" in fm

    def test_splice_fresh(self):
        out = splice_managed_block(None, "body")
        assert out.startswith(MANAGED_BEGIN)
        assert MANAGED_END in out

    def test_splice_preserves_human_edits(self):
        first = splice_managed_block(None, "generated v1")
        edited = first + "\nmy own annotation\n"
        second = splice_managed_block(edited, "generated v2")
        assert "generated v2" in second
        assert "generated v1" not in second
        assert "my own annotation" in second


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

class TestHandlers:
    def test_check_available(self, vault):
        assert check_obsidian_available() is True

    def test_write_then_read(self, vault):
        res = json.loads(
            handle_obsidian_write_note(
                {
                    "path": "Inbox/test",
                    "content": "hello [[World]]",
                    "frontmatter": {"tags": ["t"]},
                }
            )
        )
        assert res["success"], res
        read = json.loads(handle_obsidian_read_note({"path": "Inbox/test"}))
        assert read["success"]
        assert "hello [[World]]" in read["content"]
        assert read["content"].startswith("---")

    def test_write_refuses_overwrite(self, vault):
        handle_obsidian_write_note({"path": "n", "content": "one"})
        res = json.loads(handle_obsidian_write_note({"path": "n", "content": "two"}))
        assert not res["success"]
        res = json.loads(
            handle_obsidian_write_note({"path": "n", "content": "two", "overwrite": True})
        )
        assert res["success"]

    def test_append_creates_and_appends(self, vault):
        handle_obsidian_append_note({"path": "log", "content": "first"})
        handle_obsidian_append_note({"path": "log", "content": "second"})
        read = json.loads(handle_obsidian_read_note({"path": "log"}))
        assert read["content"].index("first") < read["content"].index("second")

    def test_append_under_heading(self, vault):
        handle_obsidian_write_note(
            {"path": "n", "content": "## Alpha\n\na-body\n\n## Beta\n\nb-body"}
        )
        res = json.loads(
            handle_obsidian_append_note({"path": "n", "content": "alpha-extra", "heading": "Alpha"})
        )
        assert res["success"], res
        content = json.loads(handle_obsidian_read_note({"path": "n"}))["content"]
        assert content.index("alpha-extra") < content.index("## Beta")

    def test_search_content_and_files(self, vault):
        handle_obsidian_write_note({"path": "Projects/rates", "content": "FOMC watch"})
        res = json.loads(handle_obsidian_search({"query": "fomc", "kind": "content"}))
        assert res["count"] == 1
        assert res["matches"][0]["path"] == "Projects/rates.md"
        res = json.loads(handle_obsidian_search({"query": "rates", "kind": "files"}))
        assert res["count"] == 1

    def test_handlers_without_vault(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "missing"))
        res = json.loads(handle_obsidian_read_note({"path": "x"}))
        assert not res["success"]
        assert "OBSIDIAN_VAULT_PATH" in res["error"]


# ---------------------------------------------------------------------------
# Learnings sync
# ---------------------------------------------------------------------------

def _seed_ledger(ledger):
    question = ledger.create_question(
        title="Will the FOMC cut the federal funds target range at the 2026-12-09 meeting?",
        resolution_criteria=(
            "Resolves YES if the FOMC statement published on 2026-12-09 lowers "
            "the federal funds target range relative to the prior meeting."
        ),
        description="Rate-cut watch for the December 2026 meeting.",
        domain="macro",
        tags=["fomc", "rates"],
    )
    ledger.add_analyst_note(
        question_id=question.id,
        kind="brief",
        headline="Cuts priced but not promised",
        body="Futures imply ~60%; statement language still hedged.",
        looking_for="CPI print on 2026-11-12",
        be_aware="Dot plot revisions can swamp the statement.",
    )
    lesson = ledger.create_calibration_lesson(
        scope_type="domain",
        scope_ref="macro",
        lesson="In macro questions we under-shoot well-priced market moves; lean into the market when evidence is thin.",
        confidence=0.7,
        status="active",
    )
    return question, lesson


class TestSyncLearnings:
    def test_sync_writes_linked_notes(self, vault, ledger):
        question, lesson = _seed_ledger(ledger)
        summary = sync_learnings(vault)
        assert summary["questions"] == 1
        assert summary["lessons"] == 1

        index = (vault / "Forecasting" / "Forecast Desk Index.md").read_text()
        assert "[[Forecasting/Questions/" in index
        assert "[[Forecasting/Lessons/" in index

        lesson_notes = list((vault / "Forecasting" / "Lessons").glob("*.md"))
        assert len(lesson_notes) == 1
        assert "lean into the market" in lesson_notes[0].read_text()

        question_notes = list((vault / "Forecasting" / "Questions").glob("*.md"))
        assert len(question_notes) == 1
        text = question_notes[0].read_text()
        assert text.startswith("---")
        assert "Cuts priced but not promised" in text
        # domain-matched lesson is wikilinked from the dossier
        assert "[[Forecasting/Lessons/" in text

    def test_sync_is_idempotent_and_preserves_human_edits(self, vault, ledger):
        _seed_ledger(ledger)
        sync_learnings(vault)
        note = next((vault / "Forecasting" / "Questions").glob("*.md"))
        note.write_text(note.read_text() + "\nHUMAN: my own take\n")
        sync_learnings(vault)
        text = note.read_text()
        assert "HUMAN: my own take" in text
        assert text.count(MANAGED_BEGIN) == 1

    def test_sync_tool_handler(self, vault, ledger):
        _seed_ledger(ledger)
        res = json.loads(handle_obsidian_sync_learnings({"scope": "all"}))
        assert res["success"], res
        assert res["questions"] == 1
        assert res["lessons"] == 1

    def test_sync_active_only_filters(self, vault, ledger):
        _seed_ledger(ledger)
        ledger.create_calibration_lesson(
            scope_type="global",
            scope_ref=None,
            lesson="Tentative idea, not yet validated.",
            status="tentative",
        )
        summary = sync_learnings(vault, active_only=True)
        assert summary["lessons"] == 1


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_register_wires_tools_cli_and_hook(self):
        registered = {"tools": [], "cli": [], "hooks": []}

        class Ctx:
            def register_tool(self, **kwargs):
                registered["tools"].append(kwargs)

            def register_cli_command(self, **kwargs):
                registered["cli"].append(kwargs)

            def register_hook(self, hook_name, callback):
                registered["hooks"].append((hook_name, callback))

        register(Ctx())
        names = {t["name"] for t in registered["tools"]}
        assert names == {name for name, *_ in _TOOLS}
        assert all(t["toolset"] == "obsidian" for t in registered["tools"])
        assert registered["cli"][0]["name"] == "obsidian"
        assert [name for name, _ in registered["hooks"]] == ["on_session_end"]

    def test_session_end_autosync_is_opt_in(self, vault, ledger, monkeypatch):
        from plugins.obsidian import _on_session_end

        _seed_ledger(ledger)
        monkeypatch.delenv("OBSIDIAN_AUTOSYNC", raising=False)
        _on_session_end()
        assert not (vault / "Forecasting").exists()

        monkeypatch.setenv("OBSIDIAN_AUTOSYNC", "1")
        _on_session_end()
        assert (vault / "Forecasting" / "Forecast Desk Index.md").is_file()

    def test_schema_names_match_plugin_yaml(self):
        import yaml
        from pathlib import Path

        manifest = yaml.safe_load(
            (Path(__file__).resolve().parents[2] / "plugins" / "obsidian" / "plugin.yaml").read_text()
        )
        assert set(manifest["provides_tools"]) == {name for name, *_ in _TOOLS}
