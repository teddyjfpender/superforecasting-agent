"""Auto-resolution DETECTION (forecasting/resolution_detector.py).

The learning loop's throughput is capped by resolutions (no resolution → no score
→ no lesson). The detector DETECTS resolvable past-due questions and raises a
propose-only confirm-me alert — it NEVER resolves. These tests pin: the pure
terminal-signal logic (never fabricated), the deterministic tier (market terminal
print + ingested signal), the propose sweep (dedupe/flip/coverage), that a
proposal never mutates the question, that the alert rides the existing
NO_AUTO/reconcile machinery, that the LLM tier is OFF by default, and that the
one-key confirm reuses the resolve flow and triggers scoring (the payoff).
"""

from __future__ import annotations

import json

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.models import json_dumps, utc_now_iso
from forecasting.warnings import ResolutionKind, classify_warning
from tools.forecasting_tool import forecast_ledger_tool
import forecasting.resolution_detector as rd

PAST = "2020-01-01T00:00:00Z"
FUTURE = "2999-01-01T00:00:00Z"
CRIT = "Resolves yes if the linked market settles YES."


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "rd.db"))
    lg.initialize_schema()
    return lg


def _fake_reader(*, resolved=True, outcome="no", prob=0.02, venue="manifold"):
    def reader(market_id, market_source):
        if not resolved:
            return None
        return rd.TerminalOutcome(
            resolved=True, outcome=outcome, probability=prob,
            venue=venue, market_ref=market_id, detail="test settled",
        )
    return reader


def _market_question(lg, *, resolution_time=PAST, market_id="manifold:abc"):
    return lg.create_question(
        title="Will the linked market settle YES?",
        resolution_criteria=CRIT,
        resolution_time=resolution_time,
        metadata={"market_id": market_id, "market_source": market_id.split(":", 1)[0], "market_nightly": True},
    )


# ── pure terminal-signal logic (never fabricated) ───────────────────────────────
def test_extract_terminal_signal_resolved_flag_and_outcome():
    label, outcome, conf, _ = rd.extract_terminal_signal({"resolved": True, "outcome": "YES"})
    assert label == rd.LABEL_YES and outcome == "yes" and conf >= 0.9


def test_extract_terminal_signal_saturated_probability_binary():
    hi = rd.extract_terminal_signal({"probability": 0.99}, outcome_type="binary")
    lo = rd.extract_terminal_signal({"probability": 0.01}, outcome_type="binary")
    assert hi[0] == rd.LABEL_YES and hi[1] == "yes"
    assert lo[0] == rd.LABEL_NO and lo[1] == "no"


def test_extract_terminal_signal_midbook_and_nan_are_none():
    assert rd.extract_terminal_signal({"probability": 0.5}, outcome_type="binary") is None
    assert rd.extract_terminal_signal({"probability": float("nan")}, outcome_type="binary") is None
    assert rd.extract_terminal_signal({}) is None


def test_extract_terminal_signal_non_binary_value():
    label, outcome, _, _ = rd.extract_terminal_signal({"resolved": True, "result": "42.5"})
    assert label == rd.LABEL_VALUE and outcome == "42.5"


def test_detection_from_terminal_requires_resolved():
    unresolved = rd.TerminalOutcome(resolved=False, outcome="yes", probability=1.0, venue="m", market_ref="m:1", detail="")
    assert rd.detection_from_terminal("q", "m:1", unresolved, outcome_type="binary") is None
    resolved = rd.TerminalOutcome(resolved=True, outcome="no", probability=0.0, venue="m", market_ref="m:1", detail="")
    det = rd.detection_from_terminal("q", "m:1", resolved, outcome_type="binary")
    assert det is not None and det.label == rd.LABEL_NO and det.determinable()


def test_market_ref_of_reads_structured_metadata():
    class Q:
        metadata = {"market_id": "manifold:xyz", "market_source": "manifold"}
    assert rd.market_ref_of(Q()) == ("manifold:xyz", "manifold")


# ── deterministic tier (ledger + injected reader) ───────────────────────────────
def test_deterministic_past_due_market_terminal_is_determinable(tmp_path):
    lg = _ledger(tmp_path)
    q = _market_question(lg)
    det = rd.detect_deterministic(lg, q, now_dt=rd._now_dt(None), market_reader=_fake_reader(outcome="no"))
    assert det.determinable()
    assert det.outcome == "no" and det.trigger == rd.TRIGGER_MARKET_TERMINAL
    assert det.market_id == "manifold:abc" and det.evidence_refs == ("manifold:abc",)


def test_deterministic_not_yet_when_not_past_due(tmp_path):
    lg = _ledger(tmp_path)
    q = _market_question(lg, resolution_time=FUTURE)
    det = rd.detect_deterministic(lg, q, now_dt=rd._now_dt(None), market_reader=_fake_reader())
    assert det.label == rd.LABEL_NOT_YET and not det.determinable()


def test_deterministic_unclear_when_market_unsettled(tmp_path):
    lg = _ledger(tmp_path)
    q = _market_question(lg)
    det = rd.detect_deterministic(lg, q, now_dt=rd._now_dt(None), market_reader=_fake_reader(resolved=False))
    assert det.label == rd.LABEL_UNCLEAR and not det.determinable()


def test_deterministic_ingested_terminal_signal(tmp_path):
    lg = _ledger(tmp_path)
    q = _market_question(lg, market_id="manifold:def")
    ws = lg.add_watched_source(scope_type="question", scope_ref=q.id, source="https://x/mkt", source_type="rss", role="resolver")
    with lg._connect() as conn:
        conn.execute(
            "INSERT INTO source_snapshots (id, question_id, watched_source_id, source_type, retrieved_at, parsed_values) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("ss_rd1", q.id, ws["id"], "rss", utc_now_iso(), json_dumps({"resolved": True, "outcome": "yes"})),
        )
    # No market reader wired → falls back to the ingested terminal signal.
    det = rd.detect_deterministic(lg, q, now_dt=rd._now_dt(None), market_reader=None)
    assert det.determinable() and det.outcome == "yes" and det.trigger == rd.TRIGGER_INGESTED_VALUE
    assert det.source_ref == "ss_rd1"


# ── propose sweep: dedupe / flip / propose-only / coverage ──────────────────────
def test_propose_alerts_once_and_never_resolves(tmp_path):
    lg = _ledger(tmp_path)
    q = _market_question(lg)
    out = rd.propose_detected_resolutions(lg, market_reader=_fake_reader(outcome="no"))
    assert out["alerted"] == 1 and out["by_trigger"].get(rd.TRIGGER_MARKET_TERMINAL) == 1
    open_props = [a for a in lg.list_alerts(unresolved_only=True) if "resolution proposed" in a.reason.lower()]
    assert len(open_props) == 1
    # PROPOSE-ONLY: the question is not resolved and carries no resolution.
    assert lg.get_question(q.id).status == "active"
    assert lg.get_latest_resolution(q.id, confirmed_only=True) is None

    # Second sweep dedups against the open alert (no re-alert spam).
    second = rd.propose_detected_resolutions(lg, market_reader=_fake_reader(outcome="no"))
    assert second["alerted"] == 0
    assert len([a for a in lg.list_alerts(unresolved_only=True) if "resolution proposed" in a.reason.lower()]) == 1


def test_flipped_outcome_re_alerts(tmp_path):
    lg = _ledger(tmp_path)
    _market_question(lg)
    assert rd.propose_detected_resolutions(lg, market_reader=_fake_reader(outcome="no"))["alerted"] == 1
    flipped = rd.propose_detected_resolutions(lg, market_reader=_fake_reader(outcome="yes", prob=0.98))
    assert flipped["alerted"] == 1 and flipped["by_trigger"].get(rd.TRIGGER_MARKET_TERMINAL) == 1


def test_dry_run_previews_without_alerting(tmp_path):
    lg = _ledger(tmp_path)
    _market_question(lg)
    out = rd.propose_detected_resolutions(lg, market_reader=_fake_reader(), dry_run=True)
    assert out["proposed"] == 1 and out["alerted"] == 0 and out["past_due"] == 1
    assert lg.list_alerts(unresolved_only=True) == []


def test_undetermined_past_due_is_reported_not_proposed(tmp_path):
    lg = _ledger(tmp_path)
    _market_question(lg)
    out = rd.propose_detected_resolutions(lg, market_reader=_fake_reader(resolved=False))
    assert out["alerted"] == 0 and out["undetermined_count"] == 1
    assert out["undetermined"][0]["label"] == rd.LABEL_UNCLEAR


def test_not_due_question_is_not_a_candidate(tmp_path):
    lg = _ledger(tmp_path)
    _market_question(lg, resolution_time=FUTURE)
    out = rd.propose_detected_resolutions(lg, market_reader=_fake_reader(), horizon_days=3)
    assert out["candidates"] == 0 and out["alerted"] == 0


# ── the proposal rides the existing NO_AUTO / reconcile machinery ───────────────
def test_proposal_alert_is_no_auto_and_survives_reconcile(tmp_path):
    lg = _ledger(tmp_path)
    q = _market_question(lg)
    rd.propose_detected_resolutions(lg, market_reader=_fake_reader(outcome="no"))
    alert = next(a for a in lg.list_alerts(unresolved_only=True) if "resolution proposed" in a.reason.lower())
    # Classifies NO_AUTO → surfaced for the human, never auto-reconciled.
    assert classify_warning(alert.reason) is ResolutionKind.NO_AUTO
    assert "forecast resolve" in alert.recommended_action
    lg.reconcile_alerts()
    assert any(a.id == alert.id for a in lg.list_alerts(unresolved_only=True))


def test_dedups_against_metric_resolver_proposal(tmp_path):
    # The metric-threshold resolver and the detector share the SAME reason format,
    # so a proposal from one suppresses a duplicate from the other (outcome-aware).
    lg = _ledger(tmp_path)
    q = _market_question(lg)
    lg.enqueue_resolution_proposal(question_id=q.id, outcome="no", rationale="metric resolver said NO")
    out = rd.propose_detected_resolutions(lg, market_reader=_fake_reader(outcome="no"))
    assert out["alerted"] == 0  # deduped against the pre-existing proposal
    assert len([a for a in lg.list_alerts(unresolved_only=True) if "resolution proposed" in a.reason.lower()]) == 1


# ── LLM tier: OFF by default; opt-in only; never fabricates ─────────────────────
def test_llm_tier_off_by_default_never_called(tmp_path):
    lg = _ledger(tmp_path)
    _market_question(lg)

    def boom(*a, **k):
        raise AssertionError("classifier must NOT be called when unwired")

    out = rd.propose_detected_resolutions(lg, market_reader=_fake_reader(resolved=False), classifier=None)
    assert out["alerted"] == 0  # unclear, and no LLM escalation
    # Even reaching detect_resolution with classifier=None must not call any model.
    q = lg.list_questions(status="active")[0]
    det = rd.detect_resolution(lg, q, now_dt=rd._now_dt(None), market_reader=_fake_reader(resolved=False), classifier=None)
    assert det.label == rd.LABEL_UNCLEAR


def test_llm_tier_opt_in_classifies_and_proposes(tmp_path):
    lg = _ledger(tmp_path)
    _market_question(lg)
    calls = []

    def stub_classifier(question, payloads, *, runner, model):
        calls.append(question.id)
        return {"label": "resolved_yes", "outcome": "yes", "confidence": 0.9, "rationale": "cited payload"}

    out = rd.propose_detected_resolutions(
        lg, market_reader=_fake_reader(resolved=False),  # deterministic can't settle it
        classifier=stub_classifier, runner=lambda *a: "", model="stub",
    )
    assert calls, "opt-in classifier should run on a past-due unclear question"
    assert out["alerted"] == 1 and out["by_trigger"].get(rd.TRIGGER_LLM) == 1


def test_llm_garbled_response_never_fabricates(tmp_path):
    lg = _ledger(tmp_path)
    q = _market_question(lg)

    def garbled(question, payloads, *, runner, model):
        return {"label": "banana", "outcome": None}

    det = rd.detect_llm(lg, q, classifier=garbled, runner=lambda *a: "", model="stub")
    assert det.label == rd.LABEL_UNCLEAR and not det.determinable()


def test_llm_not_escalated_for_not_yet_due(tmp_path):
    lg = _ledger(tmp_path)
    q = _market_question(lg, resolution_time=FUTURE)

    def boom(*a, **k):
        raise AssertionError("must not classify a not-yet-due question")

    det = rd.detect_resolution(lg, q, now_dt=rd._now_dt(None), market_reader=None, classifier=boom)
    assert det.label == rd.LABEL_NOT_YET


# ── nightly cron pass wires the detector (deterministic tier always on) ─────────
def test_cron_pass_raises_proposal_with_injected_reader(tmp_path):
    from forecasting import cron_runner

    db = str(tmp_path / "cron_rd.db")
    lg = ForecastLedger(db_path=db)
    lg.initialize_schema()
    _market_question(lg)

    report = cron_runner.run_due_reviews(
        db_path=db,
        resolution_market_reader=_fake_reader(outcome="no", prob=0.02),
        # Keep the sweep focused on the detection pass.
        refresh=False, reconcile_alerts=False, propose_resolutions=False,
        score_market_nightly=False, check_triage_graduation=False,
        saturation_sweep=False, free_tier_drain=False, thesis_aggregate=False,
    )
    assert "Resolution detection" in report
    props = [a for a in lg.list_alerts(unresolved_only=True) if "resolution proposed" in a.reason.lower()]
    assert len(props) == 1
    # Deterministic tier only — the LLM classifier stayed OFF (never injected here).
    assert lg.get_question(lg.list_questions(status="active")[0].id).status == "active"


# ── tool actions (additive: propose_resolutions / list_resolution_proposals) ────
def test_tool_list_resolution_proposals(tmp_path):
    db = str(tmp_path / "tool_list.db")
    lg = ForecastLedger(db_path=db)
    lg.initialize_schema()
    q = _market_question(lg)
    lg.enqueue_resolution_proposal(question_id=q.id, outcome="no", rationale="[deterministic] settled NO")

    out = json.loads(forecast_ledger_tool({"action": "list_resolution_proposals", "db": db}))
    assert out["success"] is True and out["count"] == 1
    prop = out["proposals"][0]
    assert prop["question_id"] == q.id and prop["outcome"] == "no"
    assert "forecast resolve" in prop["confirm_command"]


def test_tool_propose_resolutions_ingested_path_no_network(tmp_path):
    # venue "other" has no reader → no network; the ingested terminal signal path
    # drives the proposal, so the tool action is exercised hermetically.
    db = str(tmp_path / "tool_prop.db")
    lg = ForecastLedger(db_path=db)
    lg.initialize_schema()
    q = lg.create_question(
        title="Past-due ingested-signal question", resolution_criteria=CRIT,
        resolution_time=PAST, metadata={"market_id": "other:x", "market_source": "other"},
    )
    ws = lg.add_watched_source(scope_type="question", scope_ref=q.id, source="https://x/m", source_type="rss", role="resolver")
    with lg._connect() as conn:
        conn.execute(
            "INSERT INTO source_snapshots (id, question_id, watched_source_id, source_type, retrieved_at, parsed_values) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("ss_tool1", q.id, ws["id"], "rss", utc_now_iso(), json_dumps({"resolved": True, "outcome": "yes"})),
        )

    dry = json.loads(forecast_ledger_tool({"action": "propose_resolutions", "db": db, "dry_run": True}))
    assert dry["success"] is True and dry["proposed"] == 1 and dry["alerted"] == 0

    live = json.loads(forecast_ledger_tool({"action": "propose_resolutions", "db": db}))
    assert live["alerted"] == 1 and live["by_trigger"].get(rd.TRIGGER_INGESTED_VALUE) == 1
    assert lg.get_question(q.id).status == "active"  # propose-only


# ── the payoff: one-key confirm reuses resolve + triggers scoring ───────────────
def test_confirm_path_reuses_resolve_and_scores(tmp_path):
    lg = _ledger(tmp_path)
    q = _market_question(lg)
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.2, rationale="base", require_panel=False)

    # Detect → one confirm-me proposal; question still unresolved.
    rd.propose_detected_resolutions(lg, market_reader=_fake_reader(outcome="no", prob=0.02))
    alert = next(a for a in lg.list_alerts(unresolved_only=True) if "resolution proposed" in a.reason.lower())
    from forecasting.ledger import alerts as _alerts
    outcome = _alerts.resolution_proposal_outcome(alert.reason)
    assert outcome == "no" and lg.get_question(q.id).status == "active"

    # Confirm THROUGH THE EXISTING RESOLVE FLOW (what the one-key confirm runs).
    lg.resolve_question(question_id=q.id, outcome=outcome, resolver_type="scheduled_check")

    # The payoff: resolved + auto-scored (a score now exists to feed learning).
    assert lg.get_question(q.id).status == "resolved"
    scores = [s for s in lg.list_scores() if s.question_id == q.id]
    assert scores and scores[0].brier_score is not None
