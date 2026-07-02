"""Smoke tests for the `forecast triage` CLI group + `forecast new --apply-watch`."""

from __future__ import annotations

import json

import pytest

from forecasting import cli
from forecasting.ledger import ForecastLedger


def _run(capsys, db, subargv):
    # --db is a global option on the forecast parser, so it precedes the subcommand.
    cli.main(["--db", db, *subargv])
    return capsys.readouterr().out


def _fake_make_runner(label="relevant_interesting"):
    def factory(**kwargs):
        def runner(model, system, user):
            import re

            indices = sorted({int(n) for n in re.findall(r"\[(\d+)\]", user)})
            return json.dumps(
                {"labels": [{"index": i, "triage_label": label, "relevance": 0.9, "materiality": "high"} for i in indices]}
            )

        return runner

    return factory


def test_triage_set_and_list_rubrics(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    out = _run(capsys, db, ["triage", "set-rubric", "--scope-type", "global", "--interesting", "macro surprises"])
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["rubric"]["interesting_criteria"] == "macro surprises"

    out2 = _run(capsys, db, ["triage", "list-rubrics"])
    assert json.loads(out2)["count"] == 1


def test_triage_label_with_fake_runner(tmp_path, capsys, monkeypatch):
    import forecasting.quorum as quorum_mod

    monkeypatch.setattr(quorum_mod, "make_aiagent_runner", _fake_make_runner("relevant_interesting"))
    db = str(tmp_path / "t.db")
    out = _run(
        capsys, db,
        ["triage", "label", "--candidates-json", json.dumps([{"title": "Fed surprise pause", "summary": "off consensus"}])],
    )
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["summary"] == {"keep": 1, "skim": 0, "skip": 0, "n": 1}
    # persisted as a staging row
    assert len(ForecastLedger(db_path=db).list_triage_labels()) == 1


def test_triage_trust_smoke(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    ledger = ForecastLedger(db_path=db)
    for _ in range(3):
        [row] = ledger.record_triage_labels(verdicts=[{"triage_label": "irrelevant", "title": "x"}])
        ledger.update_triage_label(
            row["id"], expert_label="irrelevant", triage_label="irrelevant",
            label_source="expert", adjudicated_at="2026-06-30T00:00:00Z",
        )
    out = _run(capsys, db, ["triage", "trust", "--threshold", "0.8", "--min-sample", "3"])
    payload = json.loads(out)
    assert payload["triage_gate"]["mode"] == "auto"


def test_triage_contested_then_relabel(tmp_path, capsys, monkeypatch):
    import forecasting.quorum as quorum_mod

    monkeypatch.setattr(quorum_mod, "make_aiagent_runner", _fake_make_runner("irrelevant"))
    db = str(tmp_path / "t.db")
    ledger = ForecastLedger(db_path=db)
    q = ledger.create_question(
        title="Will the rate be cut?",
        resolution_criteria="Resolves yes if the official rate is cut before quarter end; otherwise no.",
    )
    # label a high-materiality item as irrelevant -> contested
    _run(
        capsys, db,
        ["triage", "label", "--question", q.id, "--candidates-json", json.dumps([{"title": "Major surprise cut", "id": "c1"}])],
    )
    out = _run(capsys, db, ["triage", "contested", "--question", q.id])
    contested = json.loads(out)
    assert contested["contested_count"] == 1
    label_id = contested["contested"][0]["id"]
    # adjudicate it
    out2 = _run(capsys, db, ["triage", "relabel", label_id, "relevant_interesting"])
    relabeled = json.loads(out2)
    assert relabeled["count"] == 1
    assert relabeled["relabeled"][0]["label_source"] == "expert"


def test_new_apply_watch_flag(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    out = _run(
        capsys, db,
        [
            "new", "Will US CPI exceed 3% in December 2026?",
            "--resolution-criteria", "Resolves yes if the BLS CPI release shows YoY above 3%; otherwise no.",
            "--domain", "macro",
            "--topic", "inflation",
            "--apply-watch",
        ],
    )
    # --apply-watch routes through the same apply seam as --apply-source-plan
    assert "applied_watches:" in out
