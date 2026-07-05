"""THE M3 GATE — a two-instance exchange, end-to-end, through the router.

Ada (sender) renders REAL M2 cards from her ledger; Bernard (receiver) imports them
through the collab router carrying stubbed Slack events. The gate:

* a forecast + evidence + lesson each LAND in Bernard's ledger with peer provenance;
* Bernard's scoring PROVABLY excludes the peer forecast (his Brier is his own);
* the divergence alert fires at >10pp ("Ada @ 34% vs you @ 48%");
* a non-allowlisted sender is REFUSED and logged;
* the peer evidence keeps ITS captured_at (never arrival time).
"""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.collab.cards import (
    render_evidence_share,
    render_forecast_card,
    render_lesson_share,
)
from forecasting.collab.router import CollabRouter
from forecasting.collab.imports import list_collab_events
from forecasting.identity import AgentIdentity
from protocol.collab import build_metadata

CRIT = "BLS CPI-U YoY for the July 2026 release exceeds 3.0 percent per the official BLS table."


def _event(rendered, *, channel="C_THESIS", ts="1700.1", user="U_ADA", team="T012ABC"):
    """A stubbed Slack message event carrying a real rendered card's sfp metadata."""

    meta = build_metadata(rendered.envelope)
    return {
        "channel": channel, "ts": ts, "user": user, "team": team,
        "metadata": {"event_type": meta.event_type, "event_payload": meta.event_payload},
    }


@pytest.fixture()
def ada(tmp_path):
    """Ada's instance: a ledger with a 34% forecast, one evidence item, one lesson."""

    identity = AgentIdentity(name="Ada", instance_id="inst-ada", team="T012ABC")
    ledger = ForecastLedger(str(tmp_path / "ada.db"))
    q = ledger.create_question(title="Will CPI YoY exceed 3.0%?", resolution_criteria=CRIT,
                               close_time="2026-12-31T00:00:00Z", domain="macro")
    ev = ledger.add_evidence(question_id=q.id, source_or_note="https://bls.gov/cpi",
                             claim="June CPI printed 3.1% YoY", summary="hot June print",
                             source_name="BLS")
    # Give the evidence a distinctly-PAST capture time so preservation is meaningful.
    with ledger._connect() as conn:
        conn.execute("UPDATE evidence_items SET captured_at = ? WHERE id = ?",
                     ("2026-06-30T12:00:00Z", ev.id))
    ledger.create_snapshot(question_id=q.id, probability_or_distribution=0.34,
                           rationale="cooling but sticky shelter keeps it near the line for now",
                           reasons_up=["shelter sticky"], require_components=False,
                           require_structured_reasoning=False)
    lesson = ledger.create_calibration_lesson(
        scope_type="domain", scope_ref="macro",
        lesson="Base-effect narratives overshoot CPI by one to two points in reversals.",
        confidence=0.6)
    return {
        "identity": identity, "ledger": ledger, "question": ledger.get_question(q.id),
        "evidence": ledger.get_evidence(ev.id), "lesson": lesson,
    }


@pytest.fixture()
def bernard(tmp_path):
    """Bernard's instance: a ledger with his OWN 48% forecast on the same question."""

    home = tmp_path / "bernard_home"
    ledger = ForecastLedger(str(tmp_path / "bernard.db"))
    q = ledger.create_question(title="Will CPI YoY exceed 3.0%?", resolution_criteria=CRIT,
                               close_time="2026-12-31T00:00:00Z", domain="macro")
    ledger.create_snapshot(question_id=q.id, probability_or_distribution=0.48,
                           rationale="base effects favor a hot print in my own read of the data",
                           reasons_up=["energy rebound"], require_components=False,
                           require_structured_reasoning=False)
    return {"home": home, "ledger": ledger, "question": ledger.get_question(q.id)}


def test_two_instance_exchange_end_to_end(ada, bernard, monkeypatch):
    monkeypatch.setenv("COLLAB_ALLOWED_INSTANCES", "inst-ada")
    # Operator authorised lesson imports from this trusted counterparty.
    monkeypatch.setenv("FORECAST_POLICY_ACCEPT_LESSON", "auto")

    lb = bernard["ledger"]
    qb = bernard["question"]
    reactions = []
    router = CollabRouter(
        ledger=lb, home=bernard["home"],
        question_resolver=lambda ev: qb.id,           # the thread is about qb
        poster=lambda a: reactions.append(a) or {"ok": True},
    )

    # ── forecast.card ─────────────────────────────────────────────────────────
    fc = render_forecast_card(ada["ledger"].get_current_snapshot(ada["question"].id),
                              ada["question"], ada["identity"], ledger=ada["ledger"])
    r_fc = router.handle_slack_event(_event(fc))
    assert r_fc.outcome == "imported"
    stub_id = r_fc.import_result.peer_question_id
    stub = lb.get_question(stub_id)
    assert stub.metadata["origin"] == "peer:Ada@T012ABC"
    assert stub.metadata["peer_forecast"]["calibration_eligible"] is False
    assert lb.get_current_snapshot(stub_id) is None                  # never a snapshot
    # divergence alert fires at 14pp.
    div = [a for a in lb.list_alerts(unresolved_only=True) if a.reason.startswith("peer_forecast_divergence")]
    assert div and "Ada @ 34% vs you @ 48%" in div[0].reason

    # ── evidence.share ────────────────────────────────────────────────────────
    es = render_evidence_share(ada["evidence"], ada["identity"])
    r_es = router.handle_slack_event(_event(es))
    assert r_es.outcome == "imported"
    imported_ev = lb.get_evidence(r_es.import_result.evidence_id)
    assert imported_ev.metadata["origin"] == "peer:Ada@T012ABC"
    # captured_at survives — the peer's original, not Bernard's arrival time.
    assert imported_ev.captured_at.startswith("2026-06-30T12:00:00")

    # ── lesson.share ──────────────────────────────────────────────────────────
    ls = render_lesson_share(ada["lesson"], ada["identity"])
    r_ls = router.handle_slack_event(_event(ls))
    assert r_ls.outcome == "imported"
    imported_lesson = next(x for x in lb.list_calibration_lessons() if x["id"] == r_ls.import_result.lesson_id)
    assert imported_lesson["status"] == "tentative"                  # inactive pending triage
    assert imported_lesson["metadata"]["origin"] == "peer:Ada@T012ABC"
    assert not (imported_lesson.get("recommended_adjustment") or {}).get("rule")  # never compiled
    assert r_ls.import_result.lesson_id not in {x["id"] for x in lb.list_calibration_lessons(active_only=True)}

    # ── scoring PROVABLY excludes the peer forecast ───────────────────────────
    my_snapshot = lb.get_current_snapshot(qb.id)
    lb.resolve_question(question_id=qb.id, outcome="yes", auto_score=False)
    score = lb.score_question(qb.id)
    all_scores = lb.list_scores()
    assert len(all_scores) == 1 and all_scores[0].forecast_id == my_snapshot.forecast_id
    assert score.brier_score == pytest.approx((1 - 0.48) ** 2, abs=1e-9)  # MY 0.48, not Ada's 0.34

    # ── a non-allowlisted sender is refused + logged ──────────────────────────
    mallory = AgentIdentity(name="Mallory", instance_id="inst-mallory", team="T999XYZ")
    mfc = render_forecast_card(ada["ledger"].get_current_snapshot(ada["question"].id),
                               ada["question"], mallory, ledger=ada["ledger"])
    r_m = router.handle_slack_event(_event(mfc, user="U_MAL"))
    assert r_m.outcome == "refused"
    events = list_collab_events(bernard["home"])
    assert any(e["event"] == "collab.refused" and e.get("provenance") == "peer:Mallory@T999XYZ" for e in events)
    # the refusal imported NOTHING new (only Ada's stub exists).
    peer_stubs = [q for q in lb.list_questions(status="archived") if (q.metadata or {}).get("collab_peer_stub")]
    assert len(peer_stubs) == 1

    # ── the whole exchange is on the forensic trail ───────────────────────────
    kinds = {(e["event"], e.get("kind")) for e in events}
    assert ("collab.import", "forecast.card") in kinds
    assert ("collab.import", "evidence.share") in kinds
    assert ("collab.import", "lesson.share") in kinds
    # 📥 reactions posted for each successful import.
    assert sum(1 for a in reactions if a.get("name") == "inbox_tray") >= 3
