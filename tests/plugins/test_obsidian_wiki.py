"""Second-brain wiki tests: enriched sync, manifest deltas, triage-gated
operator-note ingestion, wiki query, prune proposals + tombstone semantics,
and vault health.

Every test runs on a SCRATCH vault (tmp_path pinned via OBSIDIAN_VAULT_PATH)
and a SCRATCH ledger (tmp_path pinned via FORECAST_LEDGER_DB) — never the
operator's real vault or ledger.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from plugins.obsidian.ingest import collect_operator_deltas, ingest_operator_notes
from plugins.obsidian.manifest import (
    compute_deltas,
    load_manifest,
    manifest_path,
    page_signature,
    split_note,
)
from plugins.obsidian.prune import (
    apply_prune,
    build_prune_report,
    build_vault_health,
    tombstone_page,
)
from plugins.obsidian.tools import handle_obsidian_wiki_query, handle_obsidian_wiki_sync
from plugins.obsidian.vault import MANAGED_BEGIN
from plugins.obsidian.wiki import (
    CRUXES_DIR,
    ENTITIES_DIR,
    LESSONS_DIR,
    POSTMORTEMS_DIR,
    QUESTIONS_DIR,
    THESES_DIR,
    is_tombstone_text,
    sync_wiki,
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


def _seed(ledger):
    """One of everything: question (+note/crux/snapshot), linked question,
    lesson, thesis (+member+entity)."""
    q = ledger.create_question(
        title="Will the FOMC cut the federal funds target range at the 2026-12-09 meeting?",
        resolution_criteria=(
            "Resolves YES if the FOMC statement published on 2026-12-09 lowers "
            "the federal funds target range relative to the prior meeting."
        ),
        description="Rate-cut watch for the December 2026 meeting.",
        domain="macro",
        tags=["fomc", "rates"],
    )
    q2 = ledger.create_question(
        title="Will core CPI YoY print below 3.0 percent for November 2026?",
        resolution_criteria=(
            "Resolves YES if the BLS-published core CPI YoY for November 2026 "
            "is strictly below 3.0 percent."
        ),
        domain="macro",
    )
    ledger.add_forecast_link(q.id, q2.id, link_type="related")
    ledger.add_analyst_note(
        question_id=q.id,
        kind="brief",
        headline="Cuts priced but not promised",
        body="Futures imply ~60%; statement language still hedged.",
    )
    lesson = ledger.create_calibration_lesson(
        scope_type="domain",
        scope_ref="macro",
        lesson="In macro questions we under-shoot well-priced market moves.",
        confidence=0.7,
        status="active",
    )
    crux = ledger.add_crux(
        question_id=q.id, crux_variable="November CPI print", materiality="high"
    )
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.6,
        rationale="Market-implied probability with a small haircut.",
        as_of="2026-07-01T00:00:00Z",
    )
    from forecasting.models import OutcomeSpace

    thesis = ledger.create_question(
        title="AI capex supercycle thesis",
        resolution_criteria="Aggregate health of tagged members; reviewed as they update.",
        outcome_space=OutcomeSpace(type="thesis"),
    )
    ledger.add_thesis_member(thesis.id, q.id)
    ledger.add_thesis_entity(thesis.id, "NVIDIA", kind="org", label="pure-play accelerator")
    return {"q": q, "q2": q2, "lesson": lesson, "crux": crux, "thesis": thesis}


def _question_page(vault) -> Path:
    return next((vault / QUESTIONS_DIR).glob("will-the-fomc*.md"))


def _fake_runner(label: str = "relevant_interesting"):
    """A deterministic triage runner: labels every candidate `label`."""

    def runner(model, system, user):  # noqa: ARG001 — TriageRunner shape
        count = user.count("\n[")  # one "[i] title" line per candidate
        rows = [
            {"index": i, "triage_label": label, "relevance": 0.9,
             "materiality": "high", "rationale": "operator note"}
            for i in range(max(count, 1))
        ]
        return json.dumps({"labels": rows})

    return runner


# ---------------------------------------------------------------------------
# Enriched sync
# ---------------------------------------------------------------------------

class TestSyncWiki:
    def test_publishes_every_section_wikilinked(self, vault, ledger):
        _seed(ledger)
        summary = sync_wiki(vault)
        assert summary["questions"] == 2
        assert summary["lessons"] == 1
        assert summary["theses"] == 1
        assert summary["cruxes"] == 1
        assert summary["entities"] == 1

        qpage = _question_page(vault).read_text()
        assert f"[[{CRUXES_DIR}/november-cpi-print" in qpage
        assert f"[[{LESSONS_DIR}/lesson-macro" in qpage
        assert f"[[{THESES_DIR}/ai-capex-supercycle-thesis" in qpage
        assert "## Related forecasts" in qpage

        thesis_page = next((vault / THESES_DIR).glob("*.md")).read_text()
        assert f"[[{ENTITIES_DIR}/nvidia|NVIDIA]]" in thesis_page
        assert f"[[{QUESTIONS_DIR}/will-the-fomc" in thesis_page

    def test_frontmatter_contract(self, vault, ledger):
        seeded = _seed(ledger)
        sync_wiki(vault)
        text = _question_page(vault).read_text()
        front = split_note(text)["frontmatter"]
        for key in ("summary:", "provenance:", "as_of:", "ledger_refs:", "status:"):
            assert key in front, f"missing {key} in {front}"
        assert f"question_id: {seeded['q'].id}" in front
        assert f"ledger:question:{seeded['q'].id}" in front

    def test_operator_edits_survive_resync(self, vault, ledger):
        seeded = _seed(ledger)
        sync_wiki(vault)
        page = _question_page(vault)
        page.write_text(page.read_text() + "\nOPERATOR: my own read on the dot plot.\n")

        ledger.create_snapshot(
            question_id=seeded["q"].id,
            probability_or_distribution=0.7,
            rationale="Upgraded after the November CPI print.",
            as_of="2026-07-05T00:00:00Z",
        )
        sync_wiki(vault)
        text = page.read_text()
        assert "OPERATOR: my own read on the dot plot." in text
        assert "70.0%" in text  # managed content regenerated
        assert text.count(MANAGED_BEGIN) == 1

    def test_frontmatter_as_of_refreshes_to_ledger_truth(self, vault, ledger):
        seeded = _seed(ledger)
        sync_wiki(vault)
        ledger.create_snapshot(
            question_id=seeded["q"].id,
            probability_or_distribution=0.7,
            rationale="Fresh update.",
            as_of="2026-07-05T00:00:00Z",
        )
        sync_wiki(vault)
        front = split_note(_question_page(vault).read_text())["frontmatter"]
        assert "2026-07-05T00:00:00Z" in front

    def test_postmortem_page_synced_for_resolved_question(self, vault, ledger):
        seeded = _seed(ledger)
        ledger.resolve_question(question_id=seeded["q"].id, outcome="yes")
        ledger.create_postmortem(
            question_id=seeded["q"].id,
            summary="Cut delivered; market had it right.",
            lesson="Trust the priced path in macro unless evidence is strong.",
        )
        summary = sync_wiki(vault)
        assert summary["postmortems"] == 1
        pm_page = next((vault / POSTMORTEMS_DIR).glob("pm-*.md")).read_text()
        assert "Cut delivered" in pm_page
        assert f"[[{QUESTIONS_DIR}/will-the-fomc" in pm_page

    def test_sync_never_resurrects_a_tombstone(self, vault, ledger):
        _seed(ledger)
        sync_wiki(vault)
        page = _question_page(vault)
        rel = str(page.relative_to(vault))
        tombstone_page(vault, rel, reason="resolution_condensation")
        sync_wiki(vault)
        assert is_tombstone_text(page.read_text())

    def test_wiki_sync_tool_handler(self, vault, ledger):
        _seed(ledger)
        res = json.loads(handle_obsidian_wiki_sync({}))
        assert res["success"], res
        assert res["questions"] == 2
        assert res["theses"] == 1


# ---------------------------------------------------------------------------
# Delta manifest
# ---------------------------------------------------------------------------

class TestManifest:
    def test_sync_tracks_pages(self, vault, ledger):
        _seed(ledger)
        sync_wiki(vault)
        assert manifest_path(vault).is_file()
        manifest = load_manifest(vault)
        assert len(manifest["pages"]) >= 6  # 2 questions + lesson + thesis + crux + entity
        entry = next(
            v for k, v in manifest["pages"].items() if k.startswith(QUESTIONS_DIR)
        )
        assert entry["provenance"].startswith("ledger:question:")
        assert entry["content_sha"] and entry["operator_sha"]

    def test_delta_classification(self, vault, ledger):
        _seed(ledger)
        sync_wiki(vault)
        page = _question_page(vault)
        rel = str(page.relative_to(vault))

        deltas = compute_deltas(vault)
        assert deltas["operator_edited"] == []
        assert deltas["missing"] == []
        assert deltas["operator_created"] == []
        assert any(d["path"] == rel for d in deltas["unchanged"])

        # operator edit outside the managed block
        page.write_text(page.read_text() + "\nOPERATOR: watch the dots.\n")
        # operator-created note in a tracked section
        created = vault / QUESTIONS_DIR / "my-scratch-note.md"
        created.write_text("Just my thinking about the December meeting odds.\n")
        # a tracked page vanishes
        lesson_page = next((vault / LESSONS_DIR).glob("*.md"))
        lesson_rel = str(lesson_page.relative_to(vault))
        lesson_page.unlink()

        deltas = compute_deltas(vault)
        assert any(d["path"] == rel for d in deltas["operator_edited"])
        assert any(d["path"].endswith("my-scratch-note.md") for d in deltas["operator_created"])
        assert any(d["path"] == lesson_rel for d in deltas["missing"])

    def test_managed_resync_is_not_an_operator_edit(self, vault, ledger):
        seeded = _seed(ledger)
        sync_wiki(vault)
        ledger.create_snapshot(
            question_id=seeded["q"].id,
            probability_or_distribution=0.7,
            rationale="Managed-layer change only.",
            as_of="2026-07-05T00:00:00Z",
        )
        sync_wiki(vault)
        deltas = compute_deltas(vault)
        assert deltas["operator_edited"] == []


# ---------------------------------------------------------------------------
# Vault → agent: triage-gated ingestion
# ---------------------------------------------------------------------------

class TestIngest:
    def _edit_question_page(self, vault, text="OPERATOR: my contact says the vote is closer than priced."):
        page = _question_page(vault)
        page.write_text(page.read_text() + f"\n{text}\n")
        # Pin a known, real modified time (the epistemic timestamp under test).
        mtime = int(
            dt.datetime(2026, 7, 3, tzinfo=dt.timezone.utc).timestamp()
        )
        os.utime(page, (mtime, mtime))
        return page, mtime

    def test_keep_note_lands_as_evidence_with_provenance_and_mtime(self, vault, ledger):
        seeded = _seed(ledger)
        sync_wiki(vault)
        page, mtime = self._edit_question_page(vault)
        rel = str(page.relative_to(vault))

        report = ingest_operator_notes(vault, runner=_fake_runner(), model="fake-model")
        assert len(report["ingested"]) == 1
        assert report["ingested"][0]["path"] == rel

        items = ledger.list_evidence(seeded["q"].id)
        assert len(items) == 1
        ev = items[0]
        assert ev.source_type == "operator_note"
        assert ev.source_name == f"operator-note:{rel}"
        assert ev.metadata["provenance"] == f"operator-note:{rel}"
        expected = dt.datetime.fromtimestamp(mtime, tz=dt.timezone.utc)
        got = dt.datetime.fromisoformat(ev.available_at.replace("Z", "+00:00"))
        assert got == expected
        assert ev.metadata["page_modified_at"] == "2026-07-03T00:00:00Z"
        assert "my contact says" in (ev.summary or "")

        # staged through the triage machinery, not around it
        staged = ledger.list_triage_labels(question_id=seeded["q"].id)
        assert len(staged) == 1
        assert staged[0]["auto_label"] == "relevant_interesting"
        assert staged[0]["label_source"] == "auto"

    def test_suggest_only_skip_is_surfaced_not_imported(self, vault, ledger):
        seeded = _seed(ledger)
        sync_wiki(vault)
        self._edit_question_page(vault)

        report = ingest_operator_notes(vault, runner=_fake_runner("irrelevant"), model="fake")
        # no adjudicated labels yet -> the trust gate is suggest_only: the
        # labeler may not silently drop a reading.
        assert report["triage_gate_mode"] == "suggest_only"
        assert len(report["needs_review"]) == 1
        assert report["ingested"] == []
        assert ledger.list_evidence(seeded["q"].id) == []
        # ...but the verdict IS staged for adjudication.
        assert len(ledger.list_triage_labels(question_id=seeded["q"].id)) == 1

    def test_ingest_high_water_mark(self, vault, ledger):
        _seed(ledger)
        sync_wiki(vault)
        self._edit_question_page(vault)
        first = ingest_operator_notes(vault, runner=_fake_runner(), model="fake")
        assert len(first["ingested"]) == 1
        second = ingest_operator_notes(vault, runner=_fake_runner(), model="fake")
        assert second["pending"] == 0
        assert second["ingested"] == []

    def test_dry_run_is_inert(self, vault, ledger):
        seeded = _seed(ledger)
        sync_wiki(vault)
        page, _ = self._edit_question_page(vault)
        rel = str(page.relative_to(vault))
        before = manifest_path(vault).read_text()

        report = ingest_operator_notes(vault, dry_run=True)
        assert report["dry_run"] is True
        assert report["pending"] == 1
        assert report["deltas"][0]["path"] == rel
        assert ledger.list_evidence(seeded["q"].id) == []
        assert manifest_path(vault).read_text() == before

    def test_unmapped_operator_page_is_reported_never_guessed(self, vault, ledger):
        _seed(ledger)
        sync_wiki(vault)
        note = vault / QUESTIONS_DIR / "loose-thought.md"
        note.write_text("A loose thought with no question mapping whatsoever.\n")
        report = ingest_operator_notes(vault, runner=_fake_runner(), model="fake")
        assert any(u["path"].endswith("loose-thought.md") for u in report["unmapped"])
        assert report["ingested"] == []

    def test_ingest_tool_handler_dry_run(self, vault, ledger):
        from plugins.obsidian.tools import handle_obsidian_ingest_notes

        _seed(ledger)
        sync_wiki(vault)
        self._edit_question_page(vault)
        res = json.loads(handle_obsidian_ingest_notes({"dry_run": True}))
        assert res["success"], res
        assert res["dry_run"] is True
        assert res["pending"] == 1

    def test_tombstones_are_never_ingested(self, vault, ledger):
        _seed(ledger)
        sync_wiki(vault)
        page = _question_page(vault)
        rel = str(page.relative_to(vault))
        tombstone_page(vault, rel, reason="resolution_condensation")
        deltas = collect_operator_deltas(vault)
        assert all(d["path"] != rel for d in deltas)


# ---------------------------------------------------------------------------
# Retrieval-before-forecast: wiki query
# ---------------------------------------------------------------------------

class TestWikiQuery:
    def test_query_by_question_id_pulls_the_neighbourhood(self, vault, ledger):
        seeded = _seed(ledger)
        sync_wiki(vault)
        res = json.loads(handle_obsidian_wiki_query({"question_id": seeded["q"].id}))
        assert res["success"], res
        sections = {p["section"] for p in res["pages"]}
        assert "questions" in sections
        assert "cruxes" in sections  # one hop over the wikilinks
        assert "lessons" in sections
        assert res["count"] <= 8

    def test_query_includes_operator_annotations(self, vault, ledger):
        seeded = _seed(ledger)
        sync_wiki(vault)
        page = _question_page(vault)
        page.write_text(page.read_text() + "\nOPERATOR: base rate feels low here.\n")
        res = json.loads(handle_obsidian_wiki_query({"question_id": seeded["q"].id}))
        qpage = next(p for p in res["pages"] if p["section"] == "questions")
        assert "OPERATOR: base rate feels low here." in qpage["content"]

    def test_query_requires_a_handle(self, vault, ledger):
        res = json.loads(handle_obsidian_wiki_query({}))
        assert not res["success"]


# ---------------------------------------------------------------------------
# Prune: rot-class proposals + tombstone semantics + vault health
# ---------------------------------------------------------------------------

_DUPE_BODY = (
    "the polling average has moved by about {n} points since the primary and "
    "the fundamentals model still shows a lean toward {name} while early vote "
    "returns keep tracking the registration mix in the suburbs and turnout in "
    "the college towns keeps running ahead of the midterm baseline overall"
)


class TestPrune:
    def test_each_rot_class_is_proposed(self, vault, ledger):
        seeded = _seed(ledger)
        sync_wiki(vault)

        # orphan — an operator straggler nothing links to
        (vault / QUESTIONS_DIR / "scratchpad.md").write_text(
            "loose unlinked scratch content, long enough to be a real page\n"
        )
        # broken link
        (vault / QUESTIONS_DIR / "pointer.md").write_text(
            f"see [[{QUESTIONS_DIR}/ghost-page]] for the missing dossier\n"
        )
        # stale — as_of far in the past on a non-resolved page
        (vault / LESSONS_DIR / "old-take.md").write_text(
            "---\nstatus: active\nas_of: 2020-01-01T00:00:00Z\n---\nan old take\n"
        )
        # near-duplicates — same skeleton, different names/numbers
        (vault / LESSONS_DIR / "dupe-a.md").write_text(_DUPE_BODY.format(n=3, name="Alice"))
        (vault / LESSONS_DIR / "dupe-b.md").write_text(_DUPE_BODY.format(n=7, name="Bob"))
        # resolution condensation + contradiction — ledger truth moved on
        ledger.resolve_question(question_id=seeded["q"].id, outcome="yes")

        report = build_prune_report(
            vault,
            ledger=ledger,
            page_byte_budget=400,  # makes the big dossier 'oversized' too
            section_budgets={"questions": 1},
        )
        proposals = report["proposals"]
        assert any(p["path"].endswith("scratchpad.md") for p in proposals["orphans"])
        assert any(b["target"].endswith("ghost-page") for b in proposals["broken_links"])
        assert any(s["path"].endswith("old-take.md") for s in proposals["stale"])
        assert len(proposals["near_duplicates"]) == 1
        cluster = proposals["near_duplicates"][0]
        assert cluster["keep"].endswith("dupe-a.md")
        assert cluster["tombstone"] == [f"{LESSONS_DIR}/dupe-b.md"]
        rc = proposals["resolution_condensation"]
        assert any(p["question_id"] == seeded["q"].id for p in rc)
        assert any(
            c["field"] == "status" and c["ledger_value"] == "resolved"
            for c in proposals["contradictions"]
        )
        assert proposals["oversized"], "big dossier should breach the tiny budget"
        assert report["budget"]["questions"]["over_by"] >= 1
        assert report["proposal_count"] == sum(report["counts"].values())

    def test_tombstone_semantics(self, vault, ledger):
        seeded = _seed(ledger)
        sync_wiki(vault)
        ledger.resolve_question(question_id=seeded["q"].id, outcome="yes")
        report = build_prune_report(vault, ledger=ledger)

        files_before = {p for p in vault.rglob("*.md")}
        original_text = _question_page(vault).read_text()

        applied = apply_prune(vault, report)  # default: resolution_condensation
        assert len(applied["tombstoned"]) >= 1
        entry = next(
            t for t in applied["tombstoned"] if t["path"].startswith(QUESTIONS_DIR)
        )

        page = vault / entry["path"]
        assert page.is_file(), "tombstoned page is never deleted"
        text = page.read_text()
        assert is_tombstone_text(text)
        assert "status: tombstone" in text
        assert entry["archive"] in text

        archive = vault / entry["archive"]
        assert archive.is_file()
        assert archive.read_text() == original_text  # full content preserved

        files_after = {p for p in vault.rglob("*.md")}
        assert files_before <= files_after, "apply never removes a file"

        # idempotent — a second apply skips
        applied_again = apply_prune(vault, build_prune_report(vault, ledger=ledger))
        assert all(s.get("skipped") for s in applied_again["skipped"])
        assert not any(
            t["path"] == entry["path"] for t in applied_again["tombstoned"]
        )

        # ...and the tombstone rewrite is not mistaken for an operator edit
        deltas = compute_deltas(vault)
        assert all(d["path"] != entry["path"] for d in deltas["operator_edited"])

    def test_near_duplicate_apply_is_opt_in(self, vault, ledger):
        _seed(ledger)
        sync_wiki(vault)
        (vault / LESSONS_DIR / "dupe-a.md").write_text(_DUPE_BODY.format(n=3, name="Alice"))
        (vault / LESSONS_DIR / "dupe-b.md").write_text(_DUPE_BODY.format(n=7, name="Bob"))
        report = build_prune_report(vault, ledger=ledger)

        default_applied = apply_prune(vault, report)
        assert default_applied["tombstoned"] == []  # near-dupes need the explicit class

        applied = apply_prune(vault, report, classes=("near_duplicates",))
        assert [t["path"] for t in applied["tombstoned"]] == [f"{LESSONS_DIR}/dupe-b.md"]
        assert is_tombstone_text((vault / LESSONS_DIR / "dupe-b.md").read_text())
        assert not is_tombstone_text((vault / LESSONS_DIR / "dupe-a.md").read_text())

    def test_apply_refuses_unknown_classes(self, vault, ledger):
        _seed(ledger)
        sync_wiki(vault)
        report = build_prune_report(vault, ledger=ledger)
        with pytest.raises(ValueError):
            apply_prune(vault, report, classes=("stale",))

    def test_vault_health(self, vault, ledger):
        _seed(ledger)
        sync_wiki(vault)
        page = _question_page(vault)
        page.write_text(page.read_text() + "\nOPERATOR: pending annotation.\n")

        health = build_vault_health(vault, ledger=ledger)
        assert health["pages"] >= 6
        assert health["operator_edits_pending"] == 1
        for key in ("orphans", "broken_links", "stale", "tombstones", "budget_overflows"):
            assert key in health
