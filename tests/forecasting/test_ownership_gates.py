"""Tests for the forecasting-agent ownership/initiative enforcement:
- the decomposition-panel gate now binds a RE-COMMITTED live forecast (not just
  high-impact ones), so a lazy re-run can't skip the panel;
- the context packet warns when a sourceless question has related forecasts, so
  the agent can't borrow a sibling's evidence;
- a deterministic refresh of a sourceless question reports it owes evidence.
"""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.ledger import ValidationError
from forecasting.protocol import build_context_packet, FORECAST_CHAT_SYSTEM_PROMPT


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "own.db"))
    ledger.initialize_schema()
    return ledger


def _q(ledger, **kw):
    return ledger.create_question(
        title="Will the metric clear the threshold by EOY?",
        resolution_criteria="Resolves yes if the reported value exceeds the threshold.",
        **kw,
    )


def _components():
    return {"components": [
        {"name": "base_rate", "probability": 0.4, "weight": 2},
        {"name": "markets", "source": "manifold:x", "probability": 0.55, "weight": 3},
    ]}


def test_recommit_without_panel_is_refused(tmp_path):
    ledger = _ledger(tmp_path)
    q = _q(ledger)  # low impact
    # First live commit: no prior snapshot yet, so the panel is recommended, not
    # required — this must succeed even with require_panel=True.
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="baseline",
        method="log_odds_pool", ensemble_components=_components(), require_panel=True,
    )
    # Re-commit (a prior live snapshot now exists): the panel binds even though
    # the question is not high-impact. No panel_run_ref + no skip reason → refused.
    with pytest.raises(ValidationError, match="re-committed"):
        ledger.create_snapshot(
            question_id=q.id, probability_or_distribution=0.6, rationale="update",
            method="log_odds_pool", ensemble_components=_components(), require_panel=True,
        )


def test_recommit_with_skip_reason_is_allowed(tmp_path):
    ledger = _ledger(tmp_path)
    q = _q(ledger)
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="baseline",
        method="log_odds_pool", ensemble_components=_components(), require_panel=True,
    )
    # An explicit skip reason is the documented escape hatch (e.g. a deterministic
    # programmatic re-pool) — this must commit.
    snap = ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.6, rationale="update",
        method="log_odds_pool", ensemble_components=_components(), require_panel=True,
        panel_skipped_reason="deterministic re-pool, evidence unchanged",
    )
    assert snap is not None


def test_recommit_panel_gate_off_when_not_required(tmp_path):
    ledger = _ledger(tmp_path)
    q = _q(ledger)
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="baseline",
        method="log_odds_pool", ensemble_components=_components(), require_panel=False,
    )
    # require_panel=False (e.g. autopilot path that opts out) is unaffected.
    snap = ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.6, rationale="update",
        method="log_odds_pool", ensemble_components=_components(), require_panel=False,
    )
    assert snap is not None


def test_context_packet_warns_when_sourceless_with_related(tmp_path):
    ledger = _ledger(tmp_path)
    q = _q(ledger)  # no watched sources added
    related = [{"id": "q2", "title": "sibling", "relationship": "related",
                "probability_or_distribution": 0.5}]
    packet = build_context_packet(ledger, q, None, related=related, shared_sources=[])
    assert "evidence-ownership WARNING" in packet
    assert "never borrow a sibling" in packet


def test_context_packet_no_warning_when_sources_present(tmp_path):
    ledger = _ledger(tmp_path)
    q = _q(ledger)
    ledger.add_watched_source(scope_type="question", scope_ref=q.id, source="x", source_type="manifold")
    related = [{"id": "q2", "title": "sibling", "relationship": "related",
                "probability_or_distribution": 0.5}]
    packet = build_context_packet(ledger, q, None, related=related, shared_sources=[])
    assert "evidence-ownership WARNING" not in packet


def test_refresh_sourceless_reports_evidence_required(tmp_path):
    ledger = _ledger(tmp_path)
    q = _q(ledger)
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="baseline",
        method="log_odds_pool", ensemble_components=_components(), require_panel=False,
    )
    out = ledger.refresh_forecast(q.id, fetcher=lambda specs: [])
    assert out["status"] == "no_watched_sources"
    assert out["evidence_required"] is True  # not a silent success
    assert out["committed"] is None


def test_chat_prompt_has_ownership_directive():
    p = FORECAST_CHAT_SYSTEM_PROMPT
    assert "You own the book" in p
    assert "OWNERSHIP TRIGGER" in p
    assert "Bare-minimum completion is a scored failure" in p
    assert "RE-COMMITMENT" in p


def test_chat_prompt_does_not_recommend_invalid_tool_args():
    # Regression guard: the prompt once told the agent to call refresh_forecast
    # with re_estimate="agent" (the action only accepts deterministic/carry_forward
    # and RAISES otherwise) and to pass use_active_lessons to refresh (unsupported).
    p = FORECAST_CHAT_SYSTEM_PROMPT
    assert 're_estimate="agent"' not in p
    assert 're_estimate=“agent”' not in p
