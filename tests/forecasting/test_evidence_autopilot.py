"""Evidence autopilot loop + trust-gate graduation (S6.1 / S6.2)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import forecasting.source_search as ss
from forecasting.cron_runner import build_warning_runners, run_evidence_autopilot
from forecasting.ledger import ForecastLedger
from forecasting.source_search import WatchedTextSourceCandidate, WatchedTextSourceSearchResult


@pytest.fixture
def ledger(tmp_path):
    return ForecastLedger(db_path=str(tmp_path / "auto.db"))


def _question(ledger):
    return ledger.create_question(
        title="Will the rate be cut in Q3?",
        resolution_criteria="Resolves yes if the official rate is cut before Q3 ends; otherwise no.",
    )


def _candidate(title, url):
    return WatchedTextSourceCandidate(
        watched_source_id="w1",
        source_type="rss",
        source=f"rss:{url}",
        source_label="Feed",
        title=title,
        summary="summary",
        url=url,
        published_at="2026-06-30T00:00:00Z",
        entry_id=url,
        relevance_score=10,
    )


def _fake_search(*candidates):
    def _search(led, question_id, *, query=None, limit=20, since=None):
        return WatchedTextSourceSearchResult(
            question_id=question_id,
            query="q",
            searched_sources=1,
            candidates=list(candidates),
            errors=[],
        )

    return _search


def _keep_all_runner(model, system, user):
    # label every candidate index keep (relevant_interesting)
    import re

    indices = sorted({int(n) for n in re.findall(r"\[(\d+)\]", user)})
    labels = [{"index": i, "triage_label": "relevant_interesting", "relevance": 0.9, "materiality": "high"} for i in indices]
    return json.dumps({"labels": labels})


def _adjudicate_perfect(ledger, n):
    for _ in range(n):
        [row] = ledger.record_triage_labels(verdicts=[{"triage_label": "irrelevant", "title": "x"}])
        ledger.update_triage_label(
            row["id"],
            expert_label="irrelevant",
            triage_label="irrelevant",
            label_source="expert",
            adjudicated_at="2026-06-30T00:00:00Z",
        )


# ── S6.1: suggest-only branch (trust gate NOT passed) ─────────────────────────


def test_evidence_autopilot_suggest_only_stages_no_import(ledger, monkeypatch):
    q = _question(ledger)
    monkeypatch.setattr(ss, "search_watched_text_sources", _fake_search(
        _candidate("Rate cut odds rise", "https://a.example/1"),
        _candidate("Soft CPI print", "https://a.example/2"),
    ))
    before = len(ledger.list_evidence(q.id))
    result = run_evidence_autopilot(
        ledger, q.id, triage_runner=_keep_all_runner, triage_model="cheap", trust_min_sample=3
    )
    assert result["mode"] == "suggest_only"
    assert result["staged"] == 2
    assert result["imported"] == 0
    # NO evidence imported in suggest-only mode
    assert len(ledger.list_evidence(q.id)) == before
    # a suggest-review alert was raised (never a bare ack) with the required content
    alerts = [a for a in ledger.list_alerts(unresolved_only=True) if a.reason.startswith("triage_suggest_review")]
    assert len(alerts) == 1
    assert "keeps await review" in alerts[0].recommended_action
    # staging rows exist for provenance
    assert len(ledger.list_triage_labels(question_id=q.id, label_source="auto")) == 2


# ── S6.1: auto-capture branch (trust gate PASSED) ─────────────────────────────


def test_evidence_autopilot_auto_imports_keeps(ledger, monkeypatch):
    q = _question(ledger)
    _adjudicate_perfect(ledger, 3)  # clears the trust bar at min_sample=3
    monkeypatch.setattr(ss, "search_watched_text_sources", _fake_search(
        _candidate("Rate cut odds rise", "https://a.example/1"),
        _candidate("Soft CPI print", "https://b.example/2"),
    ))
    before = len(ledger.list_evidence(q.id))
    result = run_evidence_autopilot(
        ledger, q.id, triage_runner=_keep_all_runner, triage_model="cheap", trust_min_sample=3
    )
    assert result["mode"] == "auto"
    assert result["imported"] == 2
    assert len(ledger.list_evidence(q.id)) == before + 2
    # no suggest-review alert in auto mode
    assert not [a for a in ledger.list_alerts(unresolved_only=True) if a.reason.startswith("triage_suggest_review")]


def test_evidence_autopilot_no_candidates_is_noop(ledger, monkeypatch):
    q = _question(ledger)
    monkeypatch.setattr(ss, "search_watched_text_sources", _fake_search())
    result = run_evidence_autopilot(ledger, q.id, triage_runner=_keep_all_runner, triage_model="cheap")
    assert result["candidates"] == 0
    assert result["imported"] == 0


# ── S6.1: autopilot_runner wiring (opt-in, fail-open) ─────────────────────────


def test_autopilot_runner_runs_evidence_autopilot_when_wired(ledger, monkeypatch):
    q = _question(ledger)
    monkeypatch.setattr(ledger, "run_autopilot", lambda *a, **k: {"status": "success"})
    monkeypatch.setattr(ss, "search_watched_text_sources", _fake_search(
        _candidate("Rate cut odds rise", "https://a.example/1"),
    ))
    runners = build_warning_runners(ledger, triage_runner=_keep_all_runner, triage_model="cheap")
    warning = SimpleNamespace(scope_type="question", scope_ref=q.id, reason="autopilot_material_change:p1")
    result = runners.autopilot_runner(ledger, warning)
    assert result is not None
    assert "evidence_autopilot" in result
    assert result["evidence_autopilot"]["mode"] == "suggest_only"


def test_autopilot_runner_no_triage_when_not_wired(ledger, monkeypatch):
    q = _question(ledger)
    monkeypatch.setattr(ledger, "run_autopilot", lambda *a, **k: {"status": "success"})
    runners = build_warning_runners(ledger)  # no triage_runner (free tier)
    warning = SimpleNamespace(scope_type="question", scope_ref=q.id, reason="autopilot_material_change:p1")
    result = runners.autopilot_runner(ledger, warning)
    assert result == {"status": "success"}
    assert "evidence_autopilot" not in result


def test_autopilot_runner_fail_open_on_labeler_error(ledger, monkeypatch):
    q = _question(ledger)
    monkeypatch.setattr(ledger, "run_autopilot", lambda *a, **k: {"status": "success"})
    monkeypatch.setattr(ss, "search_watched_text_sources", _fake_search(
        _candidate("Rate cut odds rise", "https://a.example/1"),
    ))

    def _boom(model, system, user):
        raise RuntimeError("labeler down")

    runners = build_warning_runners(ledger, triage_runner=_boom, triage_model="cheap")
    warning = SimpleNamespace(scope_type="question", scope_ref=q.id, reason="autopilot_material_change:p1")
    result = runners.autopilot_runner(ledger, warning)
    # deterministic autopilot result still returned (truthy → ack), error captured
    assert result["status"] == "success"
    assert "evidence_autopilot_error" in result


# ── S6.2: trust-gate graduation / demotion ────────────────────────────────────


def test_graduation_alert_fires_once_on_transition(ledger):
    # baseline: suggest_only, no alert
    first = ledger.check_triage_gate_graduation(threshold=0.8, min_sample=3)
    assert first["transition"] == "baseline"
    assert first["alert"] is None
    # steady state -> no transition
    assert ledger.check_triage_gate_graduation(threshold=0.8, min_sample=3) is None
    # now clear the bar
    _adjudicate_perfect(ledger, 3)
    grad = ledger.check_triage_gate_graduation(threshold=0.8, min_sample=3)
    assert grad["transition"] == "graduated"
    assert grad["mode"] == "auto"
    assert grad["alert"].reason == "triage_labeler_graduated"
    assert "auto-filter enabled" in grad["alert"].recommended_action
    # idempotent: no second graduation alert
    assert ledger.check_triage_gate_graduation(threshold=0.8, min_sample=3) is None
    grad_alerts = [a for a in ledger.list_alerts(unresolved_only=False) if a.reason == "triage_labeler_graduated"]
    assert len(grad_alerts) == 1


def test_demotion_alert_after_graduation(ledger):
    _adjudicate_perfect(ledger, 3)
    ledger.check_triage_gate_graduation(threshold=0.8, min_sample=3)  # graduate
    # add wrong adjudications to drop accuracy below the bar
    for _ in range(4):
        [row] = ledger.record_triage_labels(verdicts=[{"triage_label": "relevant_interesting", "title": "x"}])
        ledger.update_triage_label(
            row["id"], expert_label="irrelevant", triage_label="irrelevant",
            label_source="expert", adjudicated_at="2026-06-30T00:00:00Z",
        )
    demo = ledger.check_triage_gate_graduation(threshold=0.8, min_sample=3)
    assert demo["transition"] == "demoted"
    assert demo["mode"] == "suggest_only"
    assert demo["alert"].reason == "triage_labeler_demoted"


def test_cron_sweep_surfaces_graduation(tmp_path):
    from forecasting.cron_runner import run_due_reviews

    db = str(tmp_path / "cron.db")
    ledger = ForecastLedger(db_path=db)
    # default trust threshold/min_sample (0.8 / 20) — clear it with 20 perfect labels
    _adjudicate_perfect(ledger, 20)
    text = run_due_reviews(db_path=db, refresh=False, score_market_nightly=False)
    assert "Triage trust gate" in text
    assert "graduated" in text
    # idempotent across sweeps: a second sweep does not re-surface it
    text2 = run_due_reviews(db_path=db, refresh=False, score_market_nightly=False)
    assert "Triage trust gate" not in text2


def test_desk_state_roundtrip(ledger):
    assert ledger.get_desk_state("k") is None
    ledger.set_desk_state("k", "v1")
    assert ledger.get_desk_state("k") == "v1"
    ledger.set_desk_state("k", "v2")
    assert ledger.get_desk_state("k") == "v2"
