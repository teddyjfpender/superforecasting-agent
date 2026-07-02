"""Nightly FREE-TIER warning DRAIN (folded into `run_due_reviews`).

The operator ruling: "a lot of these 'free' warnings should be done by the system
itself automatically if they're just capturing data and inputting it in the
ledger." So the nightly self-check now ends with a zero-token-spend sweep that
RESOLVES the free-tier open-alert backlog through REAL gated work.

These pins guard the load-bearing properties:

* STRICT TIER GUARD — the drain touches ONLY alert kinds whose aggregate tier is
  'free'; never the paid (LLM reforecast/evidence) or manual (operator-judgment,
  incl. contested_label) kinds.
* REAL WORK, NEVER A BARE ACK — a free alert closes only when its dispatcher
  runner did genuine gated work (a persisted score record); an un-doable free
  alert stays OPEN and is reported as an error.
* VISIBILITY — the sweep report gains a "Free-tier automode" section and the
  drain state is persisted for `forecast doctor`; a cap hit is stated explicitly.
* CONFIG — `forecasting.warnings.auto_free_tier` / `free_tier_sweep_cap` gate and
  bound the drain, with the documented precedence + defaults (TRUE / 500).
"""

from __future__ import annotations

from forecasting.cron_runner import (
    read_free_tier_drain_state,
    resolve_auto_free_tier,
    resolve_free_tier_sweep_cap,
    run_due_reviews,
)
from forecasting.ledger import ForecastLedger


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "drain.db"))
    lg.initialize_schema()
    return lg


def _scorable_question(lg: ForecastLedger) -> str:
    """A resolved question WITH a snapshot but NOT yet scored — so the free-tier
    SCORE runner (score_question) has real gated work to do at drain time."""
    q = lg.create_question(
        title="Will the official index close above target in 2026?",
        resolution_criteria="Resolves yes if the official index closes above target; otherwise no.",
    )
    lg.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.7,
        rationale="prior estimate",
        require_panel=False,
    )
    lg.resolve_question(question_id=q.id, outcome="yes", auto_score=False)
    return q.id


# The phases we switch OFF so the test isolates the drain (no scheduled reviews are
# due here anyway, but silencing the neighbours keeps the report to just the drain).
_ISOLATE = dict(
    reconcile_alerts=False,
    propose_resolutions=False,
    score_market_nightly=False,
    refresh=False,
    check_triage_graduation=False,
    saturation_sweep=False,
)


def test_drain_resolves_only_the_free_tier_through_real_work(tmp_path):
    """Seed one alert of each aggregate tier; the nightly drain resolves ONLY the
    free one (through a real score record), leaving agent + manual OPEN."""
    lg = _ledger(tmp_path)
    qid = _scorable_question(lg)

    # FREE (score): closes only when score_question persists a real score record.
    free_id = lg.create_alert(
        severity="high", scope_type="question", scope_ref=qid,
        reason="score_due", recommended_action="Score the resolved question.").id
    # AGENT (reforecast): the free drain wires no LLM runner -> must stay OPEN.
    agent_id = lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_agent",
        reason="evidence_stale_7d_plus", recommended_action="Re-forecast.").id
    # MANUAL (contested triage label): operator judgment -> surfaced, never acked.
    manual_id = lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_manual",
        reason="contested_label:fq_manual:lbl_1", recommended_action="Hand-label.").id

    before_scores = len(lg.list_scores())
    report = run_due_reviews(db_path=str(lg.db_path), **_ISOLATE)

    open_now = {a.id for a in lg.list_alerts(unresolved_only=True)}
    # The free alert closed; the agent + manual alerts are untouched (never selected).
    assert free_id not in open_now
    assert agent_id in open_now
    assert manual_id in open_now
    # REAL WORK: the SCORE runner persisted a genuine score record (not a bare ack).
    assert len(lg.list_scores()) == before_scores + 1
    # VISIBILITY: the sweep report surfaces the drain.
    assert "Free-tier automode" in report
    assert "resolved 1" in report


def test_drain_never_bare_acks_an_undoable_free_alert(tmp_path):
    """A free-tier SCORE alert whose question CANNOT be scored (no snapshot, not
    resolved) stays OPEN and is reported as an error — never bare-acked to drop the
    count. This is the invariant the whole subsystem exists to protect."""
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Will the metric exceed target by the close date?",
        resolution_criteria="Resolves yes if it exceeds target; otherwise no.",
    )
    stuck_id = lg.create_alert(
        severity="high", scope_type="question", scope_ref=q.id,
        reason="score_due", recommended_action="Score it.").id

    report = run_due_reviews(db_path=str(lg.db_path), **_ISOLATE)

    open_now = {a.id for a in lg.list_alerts(unresolved_only=True)}
    assert stuck_id in open_now  # still open — the runner did no real work
    assert "errors 1" in report
    assert "resolved 0" in report
    # State persisted for the doctor: an error, nothing resolved.
    state = read_free_tier_drain_state()
    assert state.get("errors") == 1
    assert state.get("resolved") == 0


def test_cap_hit_is_reported_and_points_at_automode(tmp_path, monkeypatch):
    """When more free alerts exist than one sweep can drain, the report states the
    cap was hit, how many remain, and how to drain the rest now."""
    lg = _ledger(tmp_path)
    # Three drainable BOOKKEEPING (free) notices; a cap of 1 drains one per sweep.
    for i in range(3):
        lg.create_alert(
            severity="info", scope_type="question", scope_ref=f"fq_{i}",
            reason="autopilot_enabled", recommended_action="Informational.")

    report = run_due_reviews(db_path=str(lg.db_path), free_tier_sweep_cap=1, **_ISOLATE)

    assert "Free-tier automode" in report
    assert "resolved 1" in report
    assert "cap 1 hit" in report
    assert "2 free-tier alert(s) remain" in report
    assert "forecast warnings automode" in report
    # One acked this sweep; two remain for the next nights.
    assert len(lg.list_alerts(unresolved_only=True)) == 2
    state = read_free_tier_drain_state()
    assert state.get("cap_hit") is True
    assert state.get("remaining_free") == 2


def test_config_gate_off_disables_the_nightly_drain(tmp_path, monkeypatch):
    """`forecasting.warnings.auto_free_tier: false` skips the drain entirely — the
    free backlog is left for the on-demand `forecast warnings automode`."""
    lg = _ledger(tmp_path)
    bk_id = lg.create_alert(
        severity="info", scope_type="question", scope_ref="fq_a",
        reason="autopilot_enabled", recommended_action="Informational.").id

    monkeypatch.setattr(
        "forecasting.cron_runner.resolve_auto_free_tier", lambda explicit=None: False
    )
    report = run_due_reviews(db_path=str(lg.db_path), **_ISOLATE)

    assert "Free-tier automode" not in report
    assert bk_id in {a.id for a in lg.list_alerts(unresolved_only=True)}  # untouched


def test_free_tier_drain_flag_off_is_a_hard_skip(tmp_path):
    """The code-level `free_tier_drain=False` flag skips the phase even with the
    config gate ON (mirrors the saturation_sweep flag)."""
    lg = _ledger(tmp_path)
    lg.create_alert(
        severity="info", scope_type="question", scope_ref="fq_a",
        reason="autopilot_enabled", recommended_action="Informational.")

    report = run_due_reviews(db_path=str(lg.db_path), free_tier_drain=False, **_ISOLATE)
    assert "Free-tier automode" not in report
    assert len(lg.list_alerts(unresolved_only=True)) == 1


def test_resolve_helpers_default_and_precedence(monkeypatch):
    """The config resolvers honour explicit args, then config, then the defaults
    (auto_free_tier TRUE / free_tier_sweep_cap 500)."""
    # Defaults (no config file in the isolated HERMES_HOME).
    assert resolve_auto_free_tier() is True
    assert resolve_free_tier_sweep_cap() == 500

    # Explicit arg always wins.
    assert resolve_auto_free_tier(False) is False
    assert resolve_free_tier_sweep_cap(42) == 42
    # A negative / unparseable cap falls through to the default.
    assert resolve_free_tier_sweep_cap(-5) == 500

    # Config value is read when no explicit arg is given.
    monkeypatch.setattr(
        "forecasting.cron_runner._warnings_config",
        lambda: {"auto_free_tier": False, "free_tier_sweep_cap": 250},
    )
    assert resolve_auto_free_tier() is False
    assert resolve_free_tier_sweep_cap() == 250
    # Explicit still overrides config.
    assert resolve_free_tier_sweep_cap(10) == 10
