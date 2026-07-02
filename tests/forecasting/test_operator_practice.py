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


# ── Corpus (ForecastBench) drills ───────────────────────────────────────────
# The flaw the corpus drill fixes: `drill --corpus desk` samples the operator's
# OWN resolved questions, which they watched resolve (recall, not calibration).
# The ForecastBench corpus feeds obscure, never-seen resolved questions, scored
# instantly — and MUST leak neither the outcome nor the freeze market price.

FB_DATE = "2099-01-01"


def _fb_question_set() -> dict:
    return {
        "forecast_due_date": FB_DATE,
        "questions": [
            # clean binary manifold, resolves YES -> produced
            {
                "id": "mf-1",
                "source": "manifold",
                "question": "Will alpha resolve yes by close?",
                "resolution_criteria": "Resolves YES if alpha occurs.",
                "background": "Background about alpha.",
                "url": "https://manifold.markets/q/alpha",
                "freeze_datetime": f"{FB_DATE}T00:00:00Z",
                "freeze_datetime_value": "0.83",
                "market_info_close_datetime": "2099-03-01T00:00:00Z",
                "resolution_dates": ["2099-02-15T00:00:00Z"],
            },
            # clean binary metaculus, resolves NO -> produced
            {
                "id": "mc-2",
                "source": "metaculus",
                "question": "Will beta happen?",
                "resolution_criteria": "Resolves YES if beta occurs.",
                "background": "",
                "url": "https://metaculus.com/q/beta",
                "freeze_datetime": f"{FB_DATE}T00:00:00Z",
                "freeze_datetime_value": "0.24",
                "market_info_close_datetime": "2099-03-01T00:00:00Z",
            },
            # dataset source (fred level, not a probability) -> dropped non-binary
            {
                "id": "fred-3",
                "source": "fred",
                "question": "What will CPI be?",
                "freeze_datetime": f"{FB_DATE}T00:00:00Z",
                "freeze_datetime_value": "317.5",
            },
            # unresolved manifold -> dropped
            {
                "id": "mf-4",
                "source": "manifold",
                "question": "Will delta happen?",
                "freeze_datetime": f"{FB_DATE}T00:00:00Z",
                "freeze_datetime_value": "0.40",
            },
            # fractional metaculus resolution -> dropped (never coerced to yes/no)
            {
                "id": "mc-5",
                "source": "metaculus",
                "question": "How much gamma by close?",
                "freeze_datetime": f"{FB_DATE}T00:00:00Z",
                "freeze_datetime_value": "0.49",
                "market_info_close_datetime": "2099-03-01T00:00:00Z",
            },
        ],
    }


def _fb_resolution_set() -> dict:
    return {
        "forecast_due_date": FB_DATE,
        "resolutions": [
            {"id": "mf-1", "source": "manifold", "direction": None,
             "resolution_date": "2099-02-15T00:00:00Z", "resolved_to": 1.0, "resolved": True},
            {"id": "mc-2", "source": "metaculus", "direction": None,
             "resolution_date": "2099-02-20T00:00:00Z", "resolved_to": 0.0, "resolved": True},
            {"id": "fred-3", "source": "fred", "direction": None,
             "resolution_date": "2099-02-20T00:00:00Z", "resolved_to": 1.0, "resolved": True},
            {"id": "mf-4", "source": "manifold", "direction": None,
             "resolution_date": "2099-02-20T00:00:00Z", "resolved_to": 0.0, "resolved": False},
            {"id": "mc-5", "source": "metaculus", "direction": None,
             "resolution_date": "2099-02-20T00:00:00Z", "resolved_to": 0.49, "resolved": True},
        ],
    }


@pytest.fixture
def patched_fb(monkeypatch):
    """Monkeypatch the ForecastBench network boundary with a canned payload pair."""

    from forecasting import forecastbench

    q, r = _fb_question_set(), _fb_resolution_set()

    def fake_fetch(url: str):
        if "question_sets" in url:
            return q
        if "resolution_sets" in url:
            return r
        raise AssertionError(f"unexpected fetch url: {url}")

    monkeypatch.setattr(forecastbench, "_fetch_json", fake_fetch)
    return fake_fetch


class _FakeTTY(io.StringIO):
    def isatty(self):
        return True


def _mf1_id() -> str:
    return f"forecastbench-{FB_DATE}-manifold-mf-1"


def _mc2_id() -> str:
    return f"forecastbench-{FB_DATE}-metaculus-mc-2"


def test_forecastbench_drill_cases_excludes_non_binary_and_unresolved(patched_fb, tmp_path):
    import forecasting.cli as cli

    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    cases = cli._forecastbench_drill_cases(ledger, date=FB_DATE, limit=10)
    assert cases is not None
    ids = {c["id"] for c in cases}
    # only the two clean binary resolved MARKET singles survive (fred/unresolved/
    # fractional are all excluded).
    assert ids == {_mf1_id(), _mc2_id()}
    for case in cases:
        assert case["outcome"] in ("yes", "no")


def test_forecastbench_drill_cases_excludes_already_drilled(patched_fb, tmp_path):
    import forecasting.cli as cli

    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    # Drill mf-1 once; it must not be re-served (no repeats, like desk drills).
    ledger.record_and_score_corpus_drill(f"fb:{_mf1_id()}", 0.5, "yes")
    cases = cli._forecastbench_drill_cases(ledger, date=FB_DATE, limit=10)
    assert {c["id"] for c in cases} == {_mc2_id()}


def test_forecastbench_drill_prompt_never_leaks_outcome_or_market(patched_fb, tmp_path):
    import forecasting.cli as cli

    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    cases = {c["id"]: c for c in cli._forecastbench_drill_cases(ledger, date=FB_DATE, limit=10)}
    case = cases[_mf1_id()]
    shown = cli._forecastbench_drill_prompt_text(case)

    # The freeze market probability (0.83) is NEVER in the shown text.
    assert "0.83" not in shown
    # And the outcome-side + market-side fields are never consulted: flip BOTH and
    # the rendered text is byte-identical -> neither could possibly have leaked.
    flipped = dict(
        case,
        outcome="no",
        baselines=[{"baseline_type": "market", "probability": 0.17}],
    )
    assert cli._forecastbench_drill_prompt_text(flipped) == shown
    # It DOES show the genuine pre-freeze context (question + background + criteria).
    assert "Will alpha resolve yes by close?" in shown
    assert "Background about alpha." in shown
    assert "Resolves YES if alpha occurs." in shown


def test_cmd_drill_forecastbench_scores_instantly(patched_fb, tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli

    db = str(tmp_path / "op.db")
    ledger = ForecastLedger(db_path=db)

    monkeypatch.setattr("sys.stdin", _FakeTTY())
    # mf-1 (yes) -> 0.7; mc-2 (no) -> 0.4; then nothing more to drill.
    answers = iter(["0.7", "0.4", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    args = argparse.Namespace(db=db, n=5, domain=None, corpus="forecastbench", date=FB_DATE)
    cli._cmd_drill(args)

    recorded = {r["question_id"]: r for r in ledger.list_operator_estimates()}
    assert set(recorded) == {f"fb:{_mf1_id()}", f"fb:{_mc2_id()}"}
    for row in recorded.values():
        assert row["context"] == "drill"
        assert row["scored_at"] is not None
    # instant Brier: 0.7 vs yes, 0.4 vs no.
    assert recorded[f"fb:{_mf1_id()}"]["brier"] == pytest.approx((0.7 - 1.0) ** 2)
    assert recorded[f"fb:{_mc2_id()}"]["brier"] == pytest.approx((0.4 - 0.0) ** 2)
    out = capsys.readouterr().out
    assert "drill Brier" in out
    # the outcome/market are only revealed AFTER the estimate (scoring), never 0.83.
    assert "0.83" not in out


def test_cmd_drill_forecastbench_degrades_without_dataset(tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli
    from forecasting import forecastbench

    db = str(tmp_path / "op.db")
    ForecastLedger(db_path=db)

    monkeypatch.setattr("sys.stdin", _FakeTTY())

    def _no_network(url: str):
        raise forecastbench.ForecastBenchError("no network and nothing cached")

    monkeypatch.setattr(forecastbench, "_fetch_json", _no_network)

    args = argparse.Namespace(db=db, n=5, domain=None, corpus="forecastbench", date=FB_DATE)
    cli._cmd_drill(args)  # must NOT raise — polite degradation
    out = capsys.readouterr().out
    assert "no benchmark dataset available" in out


def test_cmd_drill_auto_prefers_forecastbench_when_cached_and_desk_thin(
    patched_fb, tmp_path, monkeypatch, capsys
):
    import forecasting.cli as cli
    from forecasting import forecastbench

    db = str(tmp_path / "op.db")
    ledger = ForecastLedger(db_path=db)
    # Warm the on-disk cache so available_forecastbench_dates() sees the set
    # OFFLINE (this is what makes AUTO reach for the corpus).
    forecastbench.load_forecastbench_cases(FB_DATE)
    assert forecastbench.available_forecastbench_dates() == [FB_DATE]

    monkeypatch.setattr("sys.stdin", _FakeTTY())
    answers = iter(["0.6", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    # Desk has ZERO never-drilled resolved questions -> AUTO uses the corpus.
    args = argparse.Namespace(db=db, n=5, domain=None, corpus=None, date=None)
    cli._cmd_drill(args)

    recorded = ledger.list_operator_estimates()
    assert recorded and all(r["question_id"].startswith("fb:") for r in recorded)


# ── Ledger: corpus-drill storage + calibration ──────────────────────────────


def test_record_corpus_drill_stores_fb_ref_with_brier(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    est = ledger.record_and_score_corpus_drill(f"fb:{_mf1_id()}", 0.7, "yes", note="lean yes")

    assert est["question_id"] == f"fb:{_mf1_id()}"
    assert est["context"] == "drill"
    assert est["note"] == "lean yes"
    assert est["brier"] == pytest.approx((0.7 - 1.0) ** 2)
    assert est["scored_at"] is not None
    assert est["resolved_outcome"] == "yes"


def test_record_corpus_drill_validates(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    with pytest.raises(ValidationError):
        ledger.record_and_score_corpus_drill("no-colon-ref", 0.5, "yes")
    with pytest.raises(ValidationError):
        ledger.record_and_score_corpus_drill(f"fb:{_mf1_id()}", 1.5, "yes")
    with pytest.raises(ValidationError):
        ledger.record_and_score_corpus_drill(f"fb:{_mf1_id()}", True, "yes")  # noqa: FBT003
    with pytest.raises(ValidationError):
        ledger.record_and_score_corpus_drill(f"fb:{_mf1_id()}", 0.5, "maybe")


def test_operator_calibration_summary_includes_corpus_drills(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    # Two corpus drills whose question_ids are 'fb:' refs with NO forecast_questions
    # row — the summary must count them without trying to join them against the desk.
    ledger.record_and_score_corpus_drill(f"fb:{_mf1_id()}", 0.7, "yes")
    ledger.record_and_score_corpus_drill(f"fb:{_mc2_id()}", 0.4, "no")

    summary = ledger.operator_calibration_summary()
    assert summary["n"] == 2
    assert summary["brier"] == pytest.approx(((0.7 - 1.0) ** 2 + (0.4 - 0.0) ** 2) / 2)
    # curve populates for corpus refs (flow in like desk drills), no crash on join.
    populated = {row["bucket"] for row in summary["calibration_curve"] if row["count"]}
    assert "0.7-0.8" in populated


# ── Desk-drill memory-leak guard (prefer resolutions > 30 days old) ──────────


def _backdate_resolution(ledger: ForecastLedger, question_id: str, resolved_at: str) -> None:
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE resolutions SET resolved_at = ? WHERE question_id = ?",
            (resolved_at, question_id),
        )


def test_drill_candidates_prefer_older_than_30_days(tmp_path):
    import forecasting.cli as cli

    ledger = ForecastLedger(db_path=str(tmp_path / "op.db"))
    old_q = _binary_question(ledger, "Will the OLD (uncontaminated) question be preferred?")
    ledger.resolve_question(question_id=old_q.id, outcome="yes")
    _backdate_resolution(ledger, old_q.id, "2000-01-01T00:00:00Z")

    recent_q = _binary_question(ledger, "Will the RECENT (recall-risk) question be second?")
    ledger.resolve_question(question_id=recent_q.id, outcome="no")

    # limit 1 -> the old resolution is preferred even though the recent one is newer.
    only_one = cli._drill_candidates(ledger, domain=None, limit=1)
    assert [q.id for q, _ in only_one] == [old_q.id]

    # limit 5 -> both, old first (recent only fills the remaining slots).
    both = cli._drill_candidates(ledger, domain=None, limit=5)
    assert [q.id for q, _ in both][0] == old_q.id
    assert {q.id for q, _ in both} == {old_q.id, recent_q.id}


def test_desk_drill_warns_when_only_recent_available(tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli

    db = str(tmp_path / "op.db")
    ledger = ForecastLedger(db_path=db)
    # Only a RECENTLY-resolved question is available (recall risk).
    q = _binary_question(ledger, "Will the recent-only desk drill warn about recall?")
    ledger.resolve_question(question_id=q.id, outcome="yes")

    monkeypatch.setattr("sys.stdin", _FakeTTY())
    answers = iter(["0.9", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    args = argparse.Namespace(db=db, n=5, domain=None, corpus="desk", date=None)
    cli._cmd_drill(args)
    out = capsys.readouterr().out
    assert "you may remember" in out
