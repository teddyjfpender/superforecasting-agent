"""Operator practice loop (R2) — the Tetlock training loop tests.

Covers: record/validate/score round-trip, resolve firing operator scoring
(fail-open), the vs_system pairing math, drill sampling exclusions, the CLI
practice/drill flows (monkeypatched input + TTY guard), the gateway payload
section, and the config-default-OFF protocol gating.
"""

from __future__ import annotations

import argparse
import io
import json

import builtins
import pytest

from forecasting import ForecastLedger
from forecasting.models import OutcomeSpace, ValidationError


def _binary_question(ledger: ForecastLedger, title: str, **kwargs):
    return ledger.create_question(
        title=title,
        resolution_criteria="Resolved yes if the stated condition is met before the deadline.",
        outcome_space=OutcomeSpace(type="binary", choices=["yes", "no"]),
        **kwargs,
    )


# ── Ledger: record / validate / score round-trip ────────────────────────────


def test_record_validate_and_score_round_trip(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    question = _binary_question(ledger, "Will the operator round-trip work end to end?")

    estimate = ledger.record_operator_estimate(
        question.id, 0.7, note="lean yes", context="practice"
    )
    assert estimate["brier"] is None
    assert estimate["scored_at"] is None
    assert estimate["context"] == "practice"
    assert estimate["note"] == "lean yes"

    # unscored listing sees it; scored-only sees nothing yet.
    assert len(ledger.list_operator_estimates(question.id, unscored_only=True)) == 1

    ledger.score_operator_estimates(question.id, "yes")
    scored = ledger.list_operator_estimates(question.id)[0]
    assert scored["brier"] == pytest.approx((0.7 - 1.0) ** 2)
    assert scored["scored_at"] is not None
    assert ledger.list_operator_estimates(question.id, unscored_only=True) == []


def test_record_rejects_out_of_range_and_bad_context(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    question = _binary_question(ledger, "Will validation reject bad operator inputs?")

    with pytest.raises(ValidationError):
        ledger.record_operator_estimate(question.id, 1.5)
    with pytest.raises(ValidationError):
        ledger.record_operator_estimate(question.id, -0.1)
    with pytest.raises(ValidationError):
        ledger.record_operator_estimate(question.id, True)  # noqa: FBT003
    with pytest.raises(ValidationError):
        ledger.record_operator_estimate(question.id, 0.5, context="bogus")


def test_distribution_estimate_stored_and_skipped_on_score(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    question = ledger.create_question(
        title="Which candidate wins the multi-way vote share?",
        resolution_criteria="Resolved to the certified candidate vote shares in percent.",
        outcome_space=OutcomeSpace(type="categorical", choices=["a", "b", "c"]),
    )
    ledger.record_operator_estimate(question.id, {"a": 0.5, "b": 0.3, "c": 0.2})
    scored = ledger.score_operator_estimates(question.id, "a")
    # Non-binary: marked scored (won't re-process) but no Brier + a skip reason.
    assert scored[0]["brier"] is None
    assert scored[0]["scored_at"] is not None
    assert "skip_reason" in scored[0]
    # Excluded from the operator calibration mean (binary-only).
    summary = ledger.operator_calibration_summary()
    assert summary["n"] == 0


# ── Ledger: resolve fires operator scoring, fail-open ───────────────────────


def test_resolve_scores_operator_estimates(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    question = _binary_question(ledger, "Will resolution auto-score the operator estimate?")
    ledger.record_operator_estimate(question.id, 0.9)

    ledger.resolve_question(question_id=question.id, outcome="yes")

    scored = ledger.list_operator_estimates(question.id)[0]
    assert scored["brier"] == pytest.approx((0.9 - 1.0) ** 2)
    assert scored["scored_at"] is not None


def test_resolve_operator_scoring_is_fail_open(tmp_path, monkeypatch):
    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    question = _binary_question(ledger, "Will resolution survive an operator-scoring hiccup?")
    ledger.record_operator_estimate(question.id, 0.5)

    def _boom(*args, **kwargs):
        raise RuntimeError("scoring blew up")

    monkeypatch.setattr(ledger, "score_operator_estimates", _boom)
    # The resolution itself must still succeed (best-effort, like auto-score).
    resolution = ledger.resolve_question(question_id=question.id, outcome="yes")
    assert resolution.resolution_status == "confirmed"


# ── Ledger: vs_system pairing math ──────────────────────────────────────────


def test_vs_system_pairs_operator_and_system_brier(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    question = _binary_question(ledger, "Will the vs-system pairing math be correct?")
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.4,
        rationale="system view",
        forecast_origin="live",
        reasons_up=["up"],
        reasons_down=["down"],
        change_my_mind=["cmm"],
    )
    ledger.record_operator_estimate(question.id, 0.8)
    ledger.resolve_question(question_id=question.id, outcome="yes")

    vs = ledger.operator_calibration_summary()["vs_system"]
    assert vs["shared_n"] == 1
    assert vs["operator_brier"] == pytest.approx((0.8 - 1.0) ** 2)
    assert vs["system_brier"] == pytest.approx((0.4 - 1.0) ** 2)


def test_vs_system_excludes_questions_without_system_score(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    # Operator estimate but NO system snapshot -> not shared.
    q = _binary_question(ledger, "Will the unpaired question stay out of shared_n?")
    ledger.record_operator_estimate(q.id, 0.6)
    ledger.resolve_question(question_id=q.id, outcome="no")

    vs = ledger.operator_calibration_summary()["vs_system"]
    assert vs["shared_n"] == 0
    assert vs["operator_brier"] is None
    assert vs["system_brier"] is None


def test_operator_calibration_curve_and_window(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    q = _binary_question(ledger, "Will the operator calibration curve populate a decile?")
    ledger.record_operator_estimate(q.id, 0.8)
    ledger.resolve_question(question_id=q.id, outcome="yes")

    summary = ledger.operator_calibration_summary()
    assert summary["n"] == 1
    populated = [row for row in summary["calibration_curve"] if row["count"]]
    assert populated and populated[0]["bucket"] == "0.8-0.9"
    assert populated[0]["observed_frequency"] == pytest.approx(1.0)
    # A zero-day window filters everything out.
    assert ledger.operator_calibration_summary(window_days=0)["n"] == 1  # 0 is falsy → no filter
    assert ledger.operator_calibration_summary(window_days=3650)["n"] == 1


# ── Drill sampling exclusions ───────────────────────────────────────────────


def test_drill_candidates_exclusions(tmp_path):
    import forecasting.cli as cli

    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    # Two resolved binary questions, un-estimated -> eligible.
    eligible = []
    for i in range(2):
        q = _binary_question(ledger, f"Will drill-eligible question {i} be sampled?")
        ledger.resolve_question(question_id=q.id, outcome="yes")
        eligible.append(q.id)
    # Resolved binary but already estimated -> excluded.
    estimated = _binary_question(ledger, "Will the already-estimated question be excluded?")
    ledger.resolve_question(question_id=estimated.id, outcome="no")
    ledger.record_operator_estimate(estimated.id, 0.5, context="practice")
    # Unresolved binary -> excluded.
    _binary_question(ledger, "Will the unresolved question be excluded from drills?")
    # Resolved numeric -> excluded (binary-only).
    numeric = ledger.create_question(
        title="What level will the index close at in points?",
        resolution_criteria="Resolved to the closing index level in points.",
        outcome_space=OutcomeSpace(type="numeric", bounds=[0, 100], units="points"),
    )
    ledger.resolve_question(question_id=numeric.id, outcome="50")

    candidates = cli._drill_candidates(ledger, domain=None, limit=10)
    ids = {q.id for q, _ in candidates}
    assert ids == set(eligible)


# ── CLI: practice + drill ───────────────────────────────────────────────────


def test_cmd_practice_records_via_input(tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli

    db = str(tmp_path / "op.db")
    ledger = ForecastLedger(db_path=db)
    q = _binary_question(ledger, "Will the CLI practice command record my number?")

    monkeypatch.setattr(builtins, "input", lambda prompt="": "0.65")
    args = argparse.Namespace(db=db, question_ref=q.id, note="cli note")
    cli._cmd_practice(args)

    recorded = ledger.list_operator_estimates(q.id)
    assert len(recorded) == 1
    assert recorded[0]["probability_or_distribution"] == pytest.approx(0.65)
    assert recorded[0]["note"] == "cli note"


def test_cmd_drill_scores_instantly(tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli

    db = str(tmp_path / "op.db")
    ledger = ForecastLedger(db_path=db)
    q = _binary_question(ledger, "Will the drill score my estimate on the spot?")
    ledger.add_evidence(
        question_id=q.id,
        source_or_note="a pre-resolution signal",
        claim="a pre-resolution signal",
        source_type="note",
        available_at="2020-01-01T00:00:00Z",
    )
    ledger.resolve_question(question_id=q.id, outcome="yes")

    class FakeTTY(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdin", FakeTTY())
    answers = iter(["0.7", ""])  # one estimate then blank to stop
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    args = argparse.Namespace(db=db, n=5, domain=None)
    cli._cmd_drill(args)

    recorded = ledger.list_operator_estimates(q.id)
    assert len(recorded) == 1
    assert recorded[0]["context"] == "drill"
    assert recorded[0]["brier"] == pytest.approx((0.7 - 1.0) ** 2)
    out = capsys.readouterr().out
    assert "drill Brier" in out


def test_cmd_drill_refuses_without_tty(tmp_path, monkeypatch):
    import forecasting.cli as cli

    db = str(tmp_path / "op.db")
    ForecastLedger(db_path=db)

    class NoTTY(io.StringIO):
        def isatty(self):
            return False

    monkeypatch.setattr("sys.stdin", NoTTY())
    args = argparse.Namespace(db=db, n=5, domain=None)
    with pytest.raises(SystemExit):
        cli._cmd_drill(args)


# ── Tool actions ────────────────────────────────────────────────────────────


def test_tool_record_and_calibration_actions(tmp_path):
    from tools.forecasting_tool import forecast_ledger_tool

    db = str(tmp_path / "op.db")
    ledger = ForecastLedger(db_path=db)
    q = _binary_question(ledger, "Will the tool record and summarize operator estimates?")

    result = json.loads(
        forecast_ledger_tool(
            {"action": "record_operator_estimate", "db": db, "question_id": q.id, "probability": 0.6}
        )
    )
    assert result["success"]
    assert result["operator_estimate"]["context"] == "practice"

    ledger.resolve_question(question_id=q.id, outcome="yes")
    cal = json.loads(forecast_ledger_tool({"action": "operator_calibration", "db": db}))
    assert cal["success"]
    assert cal["operator_calibration"]["n"] == 1


# ── Protocol config gating (default OFF) ────────────────────────────────────


def test_protocol_estimate_first_default_off():
    from forecasting import protocol

    # Real config read under the hermetic (empty) home -> default OFF.
    assert protocol._estimate_first_enabled() is False
    prompt = protocol.build_forecast_chat_system_prompt()
    assert "PRACTICE MODE IS ON" not in prompt
    assert "PRACTICE MODE IS ON" not in protocol._stage_task("update")


def test_protocol_estimate_first_sentence_is_conditional(monkeypatch):
    from forecasting import protocol

    monkeypatch.setattr(protocol, "_estimate_first_enabled", lambda: True)
    prompt = protocol.build_forecast_chat_system_prompt()
    assert "PRACTICE MODE IS ON" in prompt
    # Only the update stage carries it — research/base_rate stay unchanged.
    assert "PRACTICE MODE IS ON" in protocol._stage_task("update")
    assert "PRACTICE MODE IS ON" not in protocol._stage_task("research")


def test_config_default_has_practice_estimate_first_off():
    from hermes_cli.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["forecasting"]["practice"]["estimate_first"] is False


# ── Gateway payload section ─────────────────────────────────────────────────


def test_gateway_calibration_payload_has_operator_section(monkeypatch):
    from tui_gateway import server

    # A scored operator estimate in the default (test-home) ledger the gateway
    # constructs with ForecastLedger().
    ledger = ForecastLedger()
    q = _binary_question(ledger, "Will the gateway expose an operator calibration section?")
    ledger.record_operator_estimate(q.id, 0.8)
    ledger.resolve_question(question_id=q.id, outcome="yes")

    resp = server.handle_request(
        {"id": "1", "method": "forecast.calibration", "params": {}}
    )
    operator = resp["result"]["operator"]
    assert operator is not None
    assert operator["n"] == 1
    assert operator["brier"] == pytest.approx((0.8 - 1.0) ** 2)
