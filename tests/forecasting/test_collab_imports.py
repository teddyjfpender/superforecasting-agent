"""The IMPORT PIPELINE honesty core (M3): peer forecasts land as world-view links
off archived stubs (never snapshots, never scoreable), evidence keeps its original
captured_at + provenance, lessons land inactive + never auto-compiled, and the
criteria-hash / divergence gates fire."""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.collab import imports as I
from forecasting.collab.cards import criteria_hash
from protocol.collab import (
    KIND_EVIDENCE_SHARE,
    KIND_FORECAST_CARD,
    KIND_LESSON_SHARE,
    EvidenceShareBody,
    ForecastCardBody,
    LessonShareBody,
    SfpEnvelope,
    SfpSender,
    sha256_hex,
)

CRIT = "BLS CPI-U YoY for the July 2026 release exceeds 3.0 percent per the official BLS table."
ADA = SfpSender(agent="Ada", instance_id="inst-ada", team="T012ABC")


def _ledger(tmp_path, name="recv.db") -> ForecastLedger:
    return ForecastLedger(str(tmp_path / name))


def _local_question(ledger, *, probability=None, title="Will CPI YoY exceed 3.0%?", criteria=CRIT):
    q = ledger.create_question(title=title, resolution_criteria=criteria,
                               close_time="2026-12-31T00:00:00Z", domain="macro")
    if probability is not None:
        ledger.create_snapshot(
            question_id=q.id, probability_or_distribution=probability,
            rationale="my own committed read of the incoming inflation data for this month",
            reasons_up=["shelter"], require_components=False, require_structured_reasoning=False,
        )
    return ledger.get_question(q.id)


def _card_env(*, probability=0.34, criteria=CRIT, title="Will CPI YoY exceed 3.0%?", sender=ADA) -> SfpEnvelope:
    body = ForecastCardBody(
        question_title=title, criteria_hash=criteria_hash(criteria), outcome_type="binary",
        as_of="2026-07-05T09:00:00Z", probability=probability,
        rationale_bullets=["cooling but sticky shelter"],
    )
    return SfpEnvelope.of(KIND_FORECAST_CARD, sender, body)


# ── forecast.card ──────────────────────────────────────────────────────────────

def test_forecast_import_creates_peer_stub_and_world_view_link_never_a_snapshot(tmp_path):
    ledger = _ledger(tmp_path)
    local = _local_question(ledger, probability=0.48)

    res = I.accept_envelope(ledger, _card_env(probability=0.34), home=tmp_path, allowlist={"inst-ada"})
    assert res.outcome == "imported"
    assert res.question_id == local.id           # resolved onto the local question by hash
    assert res.peer_question_id and res.link_id   # a peer stub + a world-view link

    stub = ledger.get_question(res.peer_question_id)
    # The stub is inert: archived (off the desk lenses) + origin=peer.
    assert stub.status == "archived"
    assert stub.metadata["origin"] == "peer:Ada@T012ABC"
    assert stub.metadata["collab_peer_stub"] is True
    # The peer number rides METADATA, never a snapshot; calibration_eligible false.
    pf = stub.metadata["peer_forecast"]
    assert pf["probability"] == 0.34
    assert pf["calibration_eligible"] is False
    assert ledger.get_current_snapshot(stub.id) is None  # NEVER a snapshot

    # The world-view link carries the peer number + flag-don't-merge marker.
    link = ledger.get_forecast_link(res.link_id)
    assert link["metadata"]["kind"] == "peer_world_view"
    assert link["metadata"]["calibration_eligible"] is False
    assert link["weight"] == 0.0


def test_forecast_import_is_idempotent_on_reimport(tmp_path):
    ledger = _ledger(tmp_path)
    _local_question(ledger, probability=0.48)
    r1 = I.accept_envelope(ledger, _card_env(probability=0.34), home=tmp_path, allowlist={"inst-ada"})
    r2 = I.accept_envelope(ledger, _card_env(probability=0.30), home=tmp_path, allowlist={"inst-ada"})
    # Same peer stub reused; the latest number replaces the old one.
    assert r1.peer_question_id == r2.peer_question_id
    stub = ledger.get_question(r2.peer_question_id)
    assert stub.metadata["peer_forecast"]["probability"] == 0.30
    peer_stubs = [q for q in ledger.list_questions(status="archived")
                  if (q.metadata or {}).get("collab_peer_stub")]
    assert len(peer_stubs) == 1


def test_no_local_question_creates_stub_without_link_or_divergence(tmp_path):
    ledger = _ledger(tmp_path)
    res = I.accept_envelope(ledger, _card_env(probability=0.34), home=tmp_path, allowlist={"inst-ada"})
    assert res.outcome == "imported"
    assert res.question_id is None      # no local anchor
    assert res.link_id is None          # nothing to link to
    assert res.alert_ids == []          # no divergence without a local current
    assert ledger.get_question(res.peer_question_id).metadata["collab_peer_stub"] is True


def test_same_title_different_criteria_raises_criteria_divergence(tmp_path):
    ledger = _ledger(tmp_path)
    # Local question with the SAME title but DIFFERENT resolution criteria.
    other_crit = "Resolves YES if the print is above three percent on the alternative index reading."
    local = _local_question(ledger, probability=0.48, criteria=other_crit)

    res = I.accept_envelope(ledger, _card_env(probability=0.34), home=tmp_path, allowlist={"inst-ada"})
    assert res.outcome == "imported"
    assert res.question_id is None        # NOT merged onto the title-colliding question
    reasons = [a.reason for a in ledger.list_alerts(unresolved_only=True)]
    assert any(r.startswith("criteria_divergence") for r in reasons)
    # the divergence alert is scoped to the colliding local question
    div = next(a for a in ledger.list_alerts(unresolved_only=True) if a.reason.startswith("criteria_divergence"))
    assert div.scope_ref == local.id


def test_divergence_alert_fires_above_10pp_only(tmp_path):
    # 48% vs 34% = 14pp → alert.
    ledger = _ledger(tmp_path)
    _local_question(ledger, probability=0.48)
    res = I.accept_envelope(ledger, _card_env(probability=0.34), home=tmp_path, allowlist={"inst-ada"})
    div = [a for a in ledger.list_alerts(unresolved_only=True) if a.reason.startswith("peer_forecast_divergence")]
    assert div and "Ada @ 34% vs you @ 48%" in div[0].reason

    # 48% vs 42% = 6pp → NO alert.
    ledger2 = _ledger(tmp_path, "recv2.db")
    _local_question(ledger2, probability=0.48)
    I.accept_envelope(ledger2, _card_env(probability=0.42), home=tmp_path / "h2", allowlist={"inst-ada"})
    assert not [a for a in ledger2.list_alerts(unresolved_only=True) if a.reason.startswith("peer_forecast_divergence")]


def test_scoring_provably_excludes_the_peer_forecast(tmp_path):
    ledger = _ledger(tmp_path)
    local = _local_question(ledger, probability=0.48)
    my_snapshot = ledger.get_current_snapshot(local.id)

    res = I.accept_envelope(ledger, _card_env(probability=0.34), home=tmp_path, allowlist={"inst-ada"})

    ledger.resolve_question(question_id=local.id, outcome="yes", auto_score=False)
    score = ledger.score_question(local.id)

    all_scores = ledger.list_scores()
    assert len(all_scores) == 1                       # exactly one — the receiver's own
    assert all_scores[0].forecast_id == my_snapshot.forecast_id
    # The brier reflects MY 0.48 (=(1-.48)^2), NOT the peer's 0.34 (=(1-.34)^2).
    assert score.brier_score == pytest.approx((1 - 0.48) ** 2, abs=1e-9)
    # The peer stub is snapshotless, so it can never be scored at all.
    assert ledger.get_current_snapshot(res.peer_question_id) is None
    with pytest.raises(Exception):
        ledger.score_question(res.peer_question_id)


# ── evidence.share ─────────────────────────────────────────────────────────────

def _evidence_env(*, captured_at="2026-06-30T12:00:00Z", excerpt="June CPI printed 3.1% YoY", sha=None):
    body = EvidenceShareBody(
        source_type="url", captured_at=captured_at, claim="June CPI printed 3.1% YoY",
        sha256=sha if sha is not None else sha256_hex(excerpt),
        source_url="https://bls.gov/cpi", source_name="BLS", available_at="2026-06-30T08:30:00Z",
        triage_label="relevant", stance="support", excerpt=excerpt,
    )
    return SfpEnvelope.of(KIND_EVIDENCE_SHARE, ADA, body)


def test_evidence_import_preserves_original_captured_at_and_provenance(tmp_path):
    ledger = _ledger(tmp_path)
    q = _local_question(ledger)
    res = I.accept_envelope(ledger, _evidence_env(), home=tmp_path, allowlist={"inst-ada"}, question_id=q.id)
    assert res.outcome == "imported"
    item = ledger.get_evidence(res.evidence_id)
    # THE no-fabricated-freshness law: captured_at is the peer's original, not arrival.
    assert item.captured_at.startswith("2026-06-30T12:00:00")
    assert item.metadata["origin"] == "peer:Ada@T012ABC"
    assert item.metadata["collab_peer_evidence"] is True
    assert item.metadata["shared_captured_at"] == "2026-06-30T12:00:00Z"


def test_evidence_sha256_mismatch_is_refused(tmp_path):
    ledger = _ledger(tmp_path)
    q = _local_question(ledger)
    bad = _evidence_env(sha="deadbeef" * 8)
    res = I.accept_envelope(ledger, bad, home=tmp_path, allowlist={"inst-ada"}, question_id=q.id)
    assert res.outcome == "error"
    assert "sha256 mismatch" in res.reason
    assert ledger.list_evidence(q.id) == []  # nothing imported


def test_evidence_without_question_context_is_skipped(tmp_path):
    ledger = _ledger(tmp_path)
    res = I.accept_envelope(ledger, _evidence_env(), home=tmp_path, allowlist={"inst-ada"}, question_id=None)
    assert res.outcome == "skipped"
    assert "question context" in res.reason


# ── lesson.share ───────────────────────────────────────────────────────────────

def _lesson_env():
    body = LessonShareBody(
        lesson="Base-effect narratives overshoot CPI by one to two points in reversals.",
        scope_type="domain", scope_ref="macro", confidence=0.6, origin_n=12, effect_size=0.15,
        compiled_rule_preview='{"when": "domain=macro", "warn": "check base effects"}', status="active",
    )
    return SfpEnvelope.of(KIND_LESSON_SHARE, ADA, body)


def test_lesson_lands_inactive_and_is_never_auto_compiled(tmp_path, monkeypatch):
    # Operator authorised lesson imports from this counterparty (accept.lesson=auto);
    # even so it lands inactive (tentative) for triage, never enforced.
    monkeypatch.setenv("FORECAST_POLICY_ACCEPT_LESSON", "auto")
    ledger = _ledger(tmp_path)
    res = I.accept_envelope(ledger, _lesson_env(), home=tmp_path, allowlist={"inst-ada"})
    assert res.outcome == "imported"
    lesson = next(x for x in ledger.list_calibration_lessons() if x["id"] == res.lesson_id)
    assert lesson["status"] == "tentative"                     # INACTIVE pending triage
    assert lesson["metadata"]["collab_peer_lesson"] is True
    assert lesson["metadata"]["origin"] == "peer:Ada@T012ABC"
    # NEVER auto-compiled to an enforced rule (no recommended_adjustment carried).
    assert not (lesson.get("recommended_adjustment") or {}).get("rule")
    # Excluded from the active (enforced) set.
    assert res.lesson_id not in {x["id"] for x in ledger.list_calibration_lessons(active_only=True)}


def test_lesson_default_ask_parks_without_importing(tmp_path, monkeypatch):
    monkeypatch.delenv("FORECAST_POLICY_ACCEPT_LESSON", raising=False)
    ledger = _ledger(tmp_path)
    res = I.accept_envelope(ledger, _lesson_env(), home=tmp_path, allowlist={"inst-ada"})
    assert res.outcome == "pending_approval" and res.decision == "ask"
    assert ledger.list_calibration_lessons() == []  # nothing imported under the default


# ── policy + event log at the accept boundary ──────────────────────────────────

def test_non_allowlisted_sender_is_refused_and_logged(tmp_path):
    ledger = _ledger(tmp_path)
    _local_question(ledger, probability=0.48)
    res = I.accept_envelope(ledger, _card_env(probability=0.34), home=tmp_path, allowlist=set())
    assert res.outcome == "refused" and res.decision == "refused"
    # No import happened.
    assert not [q for q in ledger.list_questions(status="archived") if (q.metadata or {}).get("collab_peer_stub")]
    # ...and it is on the forensic trail.
    events = I.list_collab_events(tmp_path)
    assert any(e["event"] == "collab.refused" and e["provenance"] == "peer:Ada@T012ABC" for e in events)


def test_every_import_appends_to_the_event_log(tmp_path):
    ledger = _ledger(tmp_path)
    _local_question(ledger, probability=0.48)
    I.accept_envelope(ledger, _card_env(probability=0.34), home=tmp_path, allowlist={"inst-ada"})
    events = I.list_collab_events(tmp_path)
    imp = [e for e in events if e["event"] == "collab.import" and e["kind"] == "forecast.card"]
    assert imp and imp[0]["decision"] == "auto" and imp[0]["provenance"] == "peer:Ada@T012ABC"
