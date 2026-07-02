"""END-TO-END FLOW HARNESS — the lazy prompter's whole journey as ONE tested story.

onboard (accept-defaults) → gated tool commit → recurrence installed →
deterministic scheduled refresh (no LLM) → deadline-aware escalation →
resolution (auto-score + lesson synthesis) → the desk still commits cleanly.

Every wave's features are unit-tested elsewhere; THIS file pins that they
COMPOSE. A change that greens its own unit tests but breaks the journey — a
gate that starts refusing the auto path, a refresh that stops firing, a
resolution hook that throws — fails here first.
"""

from __future__ import annotations

import json

import pytest

from forecasting.ledger import ForecastLedger
from tools.forecasting_tool import forecast_ledger_tool


@pytest.fixture
def desk(tmp_path, monkeypatch):
    """Isolated desk: scratch HERMES_HOME (cron store) + a scratch ledger db."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return str(tmp_path / "desk.db")


SPEC = {
    "title": "Will the Fed cut rates by September 2026?",
    "resolution_criteria": (
        "Resolves YES if the FOMC lowers the federal funds target range per the "
        "Federal Reserve's official statement on or before 2026-09-30; otherwise NO."
    ),
    "domain": "macro",
}


def _commit_first_forecast(db: str, question_id: str) -> dict:
    """The gated agent commit a real session would make (live, evidence-backed,
    market-sourced components so the deterministic refresh has fuel)."""
    seeded = forecast_ledger_tool({
        "action": "add_evidence",
        "db": db,
        "question_id": question_id,
        "source_or_note": "FOMC statement 2026-06",
        "claim": "two officials signaled openness to a cut",
    })
    assert json.loads(seeded).get("success", True)
    out = forecast_ledger_tool({
        "action": "update_forecast",
        "db": db,
        "question_id": question_id,
        "probability_or_distribution": 0.55,
        "rationale": "Officials signaling openness; market pricing agrees at ~55%.",
        "components": {
            "markets": {"probability": 0.55, "weight": 3, "source": "manifold:fed-cut"},
            "base_rate": {"probability": 0.40, "weight": 2},
        },
        "reference_class": {
            "name": "FOMC easing cycles since 1990",
            "inclusion_criteria": "FOMC decisions in the 12 months after a hiking pause",
            "base_rate": 0.40,
        },
        "reasons_up": ["dovish speeches", "cooling CPI prints"],
        "reasons_down": ["sticky services inflation"],
        "change_my_mind": "A hot CPI print above 3.5% YoY.",
        "reasoning_methods": ["outside_view", "base_rate", "disconfirmation"],
        "require_panel": False,
        "require_fresh_evidence": False,
        "require_decision_readiness": False,
    })
    payload = json.loads(out)
    assert payload["success"] is True, payload.get("error")
    return payload


def _market_fetcher(probability: float):
    def fetch(specs):
        return [
            {
                "source_type": spec["source_type"],
                "source": spec["source"],
                "success": True,
                "payloads": [{
                    "source_or_note": f"{spec['source_type']} {spec['source']}",
                    "source_type": f"adapter:{spec['source_type']}",
                    "claim": "market reading",
                    "summary": "",
                    "metadata": {
                        "adapter": spec["source_type"],
                        "source": spec["source"],
                        "adapter_item": {"probability": probability},
                    },
                }],
                "error": None,
            }
            for spec in specs
        ]

    return fetch


def test_the_whole_journey(desk, monkeypatch):
    db = desk

    # ── 1. ONBOARD: one accept-defaults commit_spec — the CLI --auto / chat path ──
    out = json.loads(forecast_ledger_tool({
        "action": "commit_spec",
        "db": db,
        "accept_defaults": True,
        "spec": SPEC,
    }))
    assert out["success"] is True, out.get("error")
    qid = out["question_id"]
    # deadline inferred from the criteria text, not fabricated
    applied = {a["field"]: a for a in out["applied_defaults"]}
    assert "close_time" in applied and str(applied["close_time"]["value"]).startswith("2026-09")
    # the question is ON the review cycle from birth
    assert out.get("scheduled_review"), "commit_spec must schedule the review cadence"
    # recurrence-by-default attempted (fail-open field always present)
    assert "default_routines" in out

    ledger = ForecastLedger(db_path=db)
    question = ledger.get_question(qid)
    assert (question.close_time or "").startswith("2026-09")

    # ── 2. FIRST COMMIT through the gated tool path ──────────────────────────────
    committed = _commit_first_forecast(db, qid)
    snap_id = committed["forecast_snapshot"]["forecast_id"]
    assert committed["forecast_snapshot"]["probability_or_distribution"] == pytest.approx(0.55, abs=0.15)
    # Wave-3 visibility: the agent SEES the saturation read on success
    assert "saturation" in committed and 0 <= committed["saturation"]["score"] <= 100

    # ── 3. DETERMINISTIC REFRESH: the desk keeps itself current with no LLM ─────
    ledger.add_watched_source(scope_type="question", scope_ref=qid, source="fed-cut", source_type="manifold")
    # five days before the close deadline: refresh must fire AND cadence must escalate
    now = "2026-09-25T08:00:00Z"
    results = ledger.run_due_scheduled_reviews(now=now, refresh_fetcher=_market_fetcher(0.80))
    ours = [r for r in results if (r["review"] or {}).get("scope_ref") == qid]
    assert ours, "the scheduled review row must be due and swept"
    row = ours[0]
    assert row.get("refresh_error") is None
    assert row.get("refresh"), "a watched+componentized question must deterministically refresh"
    fresh = ledger.get_current_snapshot(qid)
    assert fresh.forecast_id != snap_id, "the refresh must commit a NEW snapshot"
    # the market moved to 0.80 — the re-pooled number must move toward it
    assert float(fresh.probability_or_distribution) > 0.55
    # deadline-aware escalation: within 7 days of close → next run at most daily
    next_run = row["review"]["next_run_at"]
    assert next_run <= "2026-09-26T08:00:01Z", f"cadence must escalate near the deadline, got {next_run}"

    # ── 4. RESOLUTION closes the loop: auto-score + lesson synthesis fire ───────
    synth_calls: list = []
    real_synth = ForecastLedger.synthesize_bias_lessons

    def _spy(self, *a, **k):
        synth_calls.append(k)
        return real_synth(self, *a, **k)

    monkeypatch.setattr(ForecastLedger, "synthesize_bias_lessons", _spy)
    resolved = json.loads(forecast_ledger_tool({
        "action": "resolve",
        "db": db,
        "question_id": qid,
        "outcome": "yes",
        "resolver_notes": "FOMC cut 25bp at the September meeting.",
        "criteria_satisfied": True,
    }))
    assert resolved["success"] is True, resolved.get("error")
    scores = [s for s in ledger.list_scores() if getattr(s, "question_id", None) == qid or (isinstance(s, dict) and s.get("question_id") == qid)]
    assert scores, "resolution must auto-score the live snapshots"
    # The S7 spend-bound is part of the contract: on a THIN desk (2 scores, far
    # below the 12-per-domain ESS floor) the COUNT pre-gate must skip the O(n)
    # synthesis scan entirely — resolution stays O(1). The synthesis-fires case
    # is covered at the floor in test_s7_calibration_autoclose.
    assert not synth_calls, "thin-data resolution must NOT pay the bias-lesson synthesis scan"

    # ── 5. THE DESK STILL WORKS after the full cycle ─────────────────────────────
    out2 = json.loads(forecast_ledger_tool({
        "action": "commit_spec",
        "db": db,
        "accept_defaults": True,
        "spec": {
            "title": "Will US CPI YoY fall below 3% by December 2026?",
            "resolution_criteria": (
                "Resolves YES if BLS CPI-U YoY is below 3.0% in any monthly release "
                "on or before 2026-12-31; otherwise NO."
            ),
            "domain": "macro",
        },
    }))
    assert out2["success"] is True
    committed2 = _commit_first_forecast(db, out2["question_id"])
    # the lesson machinery ran on a live commit without breaking it (audit trail keys exist)
    assert committed2["forecast_snapshot"]["forecast_id"]


def test_journey_duplicate_sentence_routes_not_forks(desk):
    db = desk
    first = json.loads(forecast_ledger_tool({
        "action": "commit_spec", "db": db, "accept_defaults": True, "spec": SPEC,
    }))
    assert first["success"] is True
    # the same sentence again — commit_spec surfaces the rival warning
    second = json.loads(forecast_ledger_tool({
        "action": "commit_spec", "db": db, "accept_defaults": True, "spec": SPEC,
    }))
    assert second.get("duplicate_warning"), "an identical sentence must surface the rival warning"


def test_journey_cron_health_is_readable(desk):
    db = desk
    out = json.loads(forecast_ledger_tool({
        "action": "commit_spec", "db": db, "accept_defaults": True, "spec": SPEC,
    }))
    assert out["success"] is True
    from forecasting.scheduler import forecast_cron_health

    health = forecast_cron_health()
    assert isinstance(health, dict)
    # shape contract: the doctor folds this in fail-safe; jobs/errored/missed keys exist
    for key in ("jobs", "errored", "missed"):
        assert key in health
