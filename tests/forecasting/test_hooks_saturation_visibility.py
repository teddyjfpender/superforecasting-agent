"""Slice H4 — saturation VISIBILITY.

The observe-mode saturation score is recorded on every snapshot but changed no
behaviour. These tests pin the four places it is now SEEN:
  1. the successful update_forecast tool result carries {score, advisories};
  2. the desk workspace payload carries per-forecast saturation_score + a
     below-threshold flag, read from the current snapshot ALREADY in memory (no
     added per-question query);
  3. the scheduled sweep opens exactly ONE deduped WARN alert for an
     under-saturated live forecast and NONE for a saturated one;
  4. a programmatic (autofix) commit below the bar escalates the SAME deduped
     alert, and the config threshold is respected.
"""

from __future__ import annotations

import json

from forecasting.dashboard import build_workspace_payload
from forecasting.ledger import ForecastLedger
from tools.forecasting_tool import forecast_ledger_tool


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "sat.db"))
    lg.initialize_schema()
    return lg


def _under_saturated_live(lg, *, title="Will the indicator exceed target by close?") -> str:
    """A bare live commit — no evidence / components / panel — scores well under
    the 60 bar (~39/100)."""
    q = lg.create_question(
        title=title,
        resolution_criteria="Resolves yes if the indicator exceeds target by close; otherwise no.",
    )
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
        method="m", require_panel=False,
    )
    return q.id


def _saturated_live(lg, *, title="Will the second indicator exceed target by close?") -> str:
    """A rich live commit — evidence, a reference class, a multi-source pool,
    structured reasoning, tagged methods — scores well ABOVE the 60 bar (~90/100)."""
    q = lg.create_question(
        title=title,
        resolution_criteria="Resolves yes if it exceeds target; otherwise no.",
    )
    lg.add_evidence(question_id=q.id, source_or_note="quarterly report", claim="rates rose")
    rc = lg.add_reference_class(
        question_id=q.id, name="past cycles", inclusion_criteria="similar cycles", base_rate=0.5,
    )
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.62,
        rationale="clean prose with a real path and mechanism", method="log_odds_pool",
        ensemble_components={
            "base_rate": {"probability": 0.5, "weight": 1},
            "inside_view": {"probability": 0.7, "weight": 1},
            "markets": {"probability": 0.6, "weight": 1},
        },
        reference_class_refs=[rc["id"]],
        reasons_up=["link a must happen", "link b"], reasons_down=["down link"],
        change_my_mind=["weakest link fails"],
        reasoning_methods=["reference_class", "inside_view", "market"],
        require_panel=False,
    )
    return q.id


# ── 1. tool result carries score + advisories ────────────────────────────────
def test_tool_result_carries_saturation_score_and_advisories(tmp_path):
    db = str(tmp_path / "tool.db")
    qid = json.loads(forecast_ledger_tool({
        "action": "create_question", "db": db,
        "title": "Will the indicator exceed target by close?",
        "resolution_criteria": "Resolves yes if the indicator exceeds target by close; otherwise no.",
    }))["question"]["id"]
    # Clear the require_evidence ERROR floor so the commit SUCCEEDS; it is still
    # under-saturated (no components / panel), so WARN advisories remain.
    ForecastLedger(db_path=db).add_evidence(
        question_id=qid, source_or_note="report", claim="rates rose",
    )
    out = json.loads(forecast_ledger_tool({
        "action": "update_forecast", "db": db, "question_id": qid,
        "probability": 0.5, "rationale": "clean prose", "method": "m",
        "require_panel": False,
        "reasons_up": ["link a"], "reasons_down": ["link b"], "change_my_mind": ["link c"],
        # G3: link an anchor so the first-commit anchor ERROR does not block.
        "reference_class": {"name": "base", "inclusion_criteria": "prior comparable cases", "base_rate": 0.5},
        "components": {"base_rate": {"probability": 0.4, "weight": 1},
                       "inside_view": {"probability": 0.6, "weight": 1}},
    }))
    assert out["success"] is True
    sat = out["saturation"]
    assert isinstance(sat["score"], (int, float))
    assert 0 <= sat["score"] <= 100
    # advisories are the failed WARN checks that PASSED the gate but flag a gap —
    # each a one-line rule_id + message the agent can act on without re-prompting.
    assert sat["advisories"], "an incomplete commit should still surface WARN advisories"
    for advisory in sat["advisories"]:
        assert advisory["rule_id"]
        assert "message" in advisory


def test_tool_result_omits_saturation_when_not_recorded(tmp_path, monkeypatch):
    # If observe-mode recorded nothing (defensive), the tool must not fabricate a block.
    db = str(tmp_path / "tool2.db")
    qid = json.loads(forecast_ledger_tool({
        "action": "create_question", "db": db,
        "title": "Will the metric clear the line?",
        "resolution_criteria": "Resolves yes if the metric clears the line; otherwise no.",
    }))["question"]["id"]
    ForecastLedger(db_path=db).add_evidence(question_id=qid, source_or_note="r", claim="c")
    # Force saturation_summary to return None (no report) for this call.
    import tools.forecasting_tool as tool_mod

    monkeypatch.setattr(tool_mod, "saturation_summary", lambda *_a, **_k: None)
    out = json.loads(forecast_ledger_tool({
        "action": "update_forecast", "db": db, "question_id": qid,
        "probability": 0.5, "rationale": "clean prose", "method": "m", "require_panel": False,
        "reasons_up": ["link a"], "reasons_down": ["link b"], "change_my_mind": ["link c"],
        # G3: link an anchor so the first-commit anchor ERROR does not block.
        "reference_class": {"name": "base", "inclusion_criteria": "prior comparable cases", "base_rate": 0.5},
        "components": {"base_rate": {"probability": 0.4, "weight": 1},
                       "inside_view": {"probability": 0.6, "weight": 1}},
    }))
    assert out["success"] is True
    assert "saturation" not in out


# ── 2. desk payload carries scores with NO added query ────────────────────────
def test_workspace_payload_carries_saturation_score_and_flag(tmp_path):
    lg = _ledger(tmp_path)
    _under_saturated_live(lg)
    forecast = build_workspace_payload(ledger=lg)["forecasts"][0]
    assert isinstance(forecast["saturation_score"], (int, float))
    assert forecast["saturation_score"] < 60
    assert forecast["saturation_below_threshold"] is True


def test_workspace_payload_saturation_uses_no_extra_query(tmp_path):
    lg = _ledger(tmp_path)
    _saturated_live(lg)

    # If the payload builder tried a per-question get_current_snapshot for the
    # saturation read, this would fire — the desk N+1 was a hard-won perf fix, so
    # the score MUST come from the batched snapshots already in memory.
    def _boom(*_a, **_k):  # pragma: no cover - only hit on regression
        raise AssertionError("build_workspace_payload must not call get_current_snapshot per row")

    lg.get_current_snapshot = _boom  # type: ignore[assignment]
    forecast = build_workspace_payload(
        ledger=lg, include_related=False, include_lessons=False,
    )["forecasts"][0]
    assert forecast["saturation_score"] >= 60
    assert forecast["saturation_below_threshold"] is False


# ── 3. scheduled sweep: one deduped alert for under, none for saturated ───────
def test_sweep_alerts_under_saturated_only_and_dedupes(tmp_path):
    lg = _ledger(tmp_path)
    under_id = _under_saturated_live(lg)
    _saturated_live(lg)

    first = lg.sweep_saturation_alerts()
    assert first["checked"] == 2
    assert first["under_saturated"] == 1
    assert first["alerted"] == [under_id]

    open_alerts = [a for a in lg.list_alerts(unresolved_only=True) if a.reason == "under_saturated"]
    assert len(open_alerts) == 1
    assert open_alerts[0].scope_ref == under_id
    assert open_alerts[0].severity == "warning"

    # A second sweep folds/dedupes — no duplicate row for the same open condition.
    second = lg.sweep_saturation_alerts()
    assert second["alerted"] == []
    assert len([a for a in lg.list_alerts(unresolved_only=True) if a.reason == "under_saturated"]) == 1


def test_sweep_ignores_non_live_origins(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Backtest replay question?",
        resolution_criteria="Resolves yes if the replayed outcome is yes; otherwise no.",
    )
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="replay",
        method="m", require_panel=False, forecast_origin="backtest",
    )
    result = lg.sweep_saturation_alerts()
    assert result["checked"] == 0
    assert not [a for a in lg.list_alerts(unresolved_only=True) if a.reason == "under_saturated"]


# ── 4. programmatic escalation + config threshold ─────────────────────────────
def test_programmatic_commit_below_bar_escalates_alert(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Will the programmatic series clear the line?",
        resolution_criteria="Resolves yes if the series clears the line; otherwise no.",
    )
    # A programmatic path (refresh/aggregate/autopilot) passes the autofix flags.
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="auto prose",
        method="m", require_panel=False, style_autofix=True, distribution_autofix=True,
    )
    open_alerts = [a for a in lg.list_alerts(unresolved_only=True) if a.reason == "under_saturated"]
    assert len(open_alerts) == 1
    assert open_alerts[0].scope_ref == q.id

    # A second programmatic commit below the bar dedupes (fold, never a re-alert).
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.51, rationale="auto prose",
        method="m", require_panel=False, style_autofix=True, distribution_autofix=True,
    )
    assert len([a for a in lg.list_alerts(unresolved_only=True) if a.reason == "under_saturated"]) == 1


def test_agent_path_commit_does_not_escalate_alert(tmp_path):
    # The AGENT path (no autofix) sees the tool-result advisory instead; it must
    # NOT open a background alert on its own under-saturated commit.
    lg = _ledger(tmp_path)
    _under_saturated_live(lg)  # raw live commit, no autofix flags
    assert not [a for a in lg.list_alerts(unresolved_only=True) if a.reason == "under_saturated"]


def test_escalation_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_DISABLE_SATURATION_ESCALATION", "1")
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Will the switched-off series clear the line?",
        resolution_criteria="Resolves yes if it clears the line; otherwise no.",
    )
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="auto prose",
        method="m", require_panel=False, style_autofix=True, distribution_autofix=True,
    )
    assert not [a for a in lg.list_alerts(unresolved_only=True) if a.reason == "under_saturated"]


def test_config_threshold_respected(tmp_path, monkeypatch):
    lg = _ledger(tmp_path)
    sat_id = _saturated_live(lg)  # ~90/100 — above the default 60 bar

    # Default bar (60): the rich forecast is saturated -> no alert.
    assert lg.sweep_saturation_alerts()["alerted"] == []

    # Raise the configured bar above the rich score -> now it is under-saturated.
    import forecasting.hooks.engine as engine_mod

    monkeypatch.setattr(engine_mod, "load_hook_config", lambda: {"sweep_alert_threshold": 95})
    result = lg.sweep_saturation_alerts()
    assert result["alerted"] == [sat_id]


def test_under_saturated_alert_routes_to_reforecast_not_a_dead_end(tmp_path):
    # The alert routes to REFORECAST (the agent re-saturates it) rather than the
    # NO_AUTO / CONTESTED manual classes — so reconcile_alerts will auto-clear it
    # once a fresh snapshot + evidence lands, instead of stranding it forever.
    from forecasting.warnings import ResolutionKind, classify_warning

    kind = classify_warning("under_saturated")
    assert kind is ResolutionKind.REFORECAST
    assert kind not in (ResolutionKind.NO_AUTO, ResolutionKind.CONTESTED_LABEL)
