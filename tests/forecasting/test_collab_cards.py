"""Card-renderer tests (multiplayer M2): render real seeded ledger objects into
sfp/1 cards, prove the honesty laws (2dp headline, band only when real, immutable
provenance) and that a forecast.card rendered from a seeded snapshot round-trips
byte-equal — the M2 gate.
"""

from __future__ import annotations

import json

import pytest

from forecasting import ForecastLedger
from forecasting.identity import AgentIdentity
from forecasting.ledger import allow_ledger_writes
from forecasting.models import ForecastSnapshot, ForecastQuestion, OutcomeSpace
from protocol.collab import (
    ForecastCardBody,
    SfpEnvelope,
    canonical_json,
    parse_body,
    parse_envelope,
    sha256_hex,
)
from forecasting.collab import (
    build_forecast_card_body,
    criteria_hash,
    render_evidence_share,
    render_forecast_card,
    render_lesson_share,
)
from forecasting.collab.cards import _extract_band
from tools.forecasting_tool import forecast_ledger_tool

CRITERIA = "BLS CPI-U YoY for July 2026 release exceeds 3.0%."


def _identity() -> AgentIdentity:
    return AgentIdentity(name="Ada", instance_id="inst-abc", team="T012ABC")


def _blocks_text(blocks) -> str:
    """Flatten a Block Kit list to searchable text."""
    return json.dumps(blocks)


@pytest.fixture()
def seeded(tmp_path):
    """A real ledger with a binary question, one evidence item, and a committed
    snapshot referencing it (four reasons_up so the top-3 clamp is exercised)."""
    db = str(tmp_path / "collab.db")

    def tool(**a):
        return json.loads(forecast_ledger_tool({"db": db, **a}))

    created = tool(
        action="create_question",
        title="Will CPI YoY exceed 3.0% in July 2026?",
        resolution_criteria=CRITERIA,
        close_time="2026-12-31T00:00:00Z",
    )
    qid = created["question"]["id"]
    ev = tool(
        action="add_evidence", question_id=qid, source_or_note="BLS release",
        claim="June CPI printed 3.1% YoY", source_name="BLS June CPI",
        summary="June CPI YoY came in at 3.1 percent, above consensus.",
        source_type="statistical_release",
    )
    eid = ev["evidence"]["id"]
    tool(
        action="update_forecast", question_id=qid, probability=0.62,
        rationale="Base effects favor a hot print.",
        reasons_up=["shelter inflation sticky", "energy rebound", "wage growth firm", "services momentum"],
        evidence_refs=[eid],
        require_components=False, require_structured_reasoning=False, require_panel=False,
    )
    return ForecastLedger(db), qid, eid


# ── forecast.card ─────────────────────────────────────────────────────────────

def test_forecast_card_headline_two_decimals_and_no_fabricated_band(seeded):
    ledger, qid, eid = seeded
    snapshot = ledger.get_current_snapshot(qid)
    question = ledger.get_question(qid)

    card = render_forecast_card(snapshot, question, _identity(), ledger=ledger)

    assert card.event_type == "sfp.forecast.card"
    # Headline % to 2dp on the Block Kit surface.
    assert "62.00%" in _blocks_text(card.blocks)
    # A binary point forecast has no band — never fabricated.
    body = ForecastCardBody.model_validate(card.event_payload["body"])
    assert body.band is None
    assert body.probability == 0.62


def test_forecast_card_top_three_bullets_and_evidence_refs(seeded):
    ledger, qid, eid = seeded
    card = render_forecast_card(
        ledger.get_current_snapshot(qid), ledger.get_question(qid), _identity(), ledger=ledger,
    )
    body = ForecastCardBody.model_validate(card.event_payload["body"])

    assert body.rationale_bullets == [
        "shelter inflation sticky", "energy rebound", "wage growth firm",
    ]  # clamped to top 3
    assert [r.id for r in body.evidence_refs] == [eid]
    assert body.evidence_refs[0].title == "BLS June CPI"


def test_forecast_card_carries_criteria_hash_and_provenance(seeded):
    ledger, qid, eid = seeded
    question = ledger.get_question(qid)
    card = render_forecast_card(ledger.get_current_snapshot(qid), question, _identity(), ledger=ledger)
    body = ForecastCardBody.model_validate(card.event_payload["body"])

    assert body.criteria_hash == criteria_hash(CRITERIA)
    text = _blocks_text(card.blocks)
    assert body.criteria_hash[:12] in text  # short hash on the surface
    assert "Ada" in text and "T012ABC" in text  # immutable provenance footer
    assert body.as_of == ledger.get_current_snapshot(qid).as_of


def test_forecast_card_round_trips_byte_equal_from_seeded_snapshot(seeded):
    """THE M2 GATE: rendered from a real seeded snapshot, serialized to metadata,
    re-parsed through the pydantic model, body byte-equal in canonical JSON."""
    ledger, qid, eid = seeded
    snapshot, question = ledger.get_current_snapshot(qid), ledger.get_question(qid)

    card = render_forecast_card(snapshot, question, _identity(), ledger=ledger)
    # Simulate the Slack post -> metadata -> re-read round-trip.
    on_the_wire = json.loads(json.dumps(card.event_payload))
    reparsed = parse_envelope(on_the_wire)

    original_body = build_forecast_card_body(snapshot, question, ledger=ledger)
    assert canonical_json(reparsed.body) == canonical_json(original_body)
    assert canonical_json(parse_body(reparsed)) == canonical_json(original_body)


# ── band honesty (positive + negative) ────────────────────────────────────────

def _distribution_snapshot(payload) -> ForecastSnapshot:
    return ForecastSnapshot(
        forecast_id="f1", question_id="q1", created_at="2026-07-05T00:00:00Z",
        as_of="2026-07-05T00:00:00Z", probability_or_distribution=payload,
        confidence=None, forecast_horizon_days=30.0, method=None, ensemble_components={},
        rationale="dist", key_assumptions=[], assumption_refs=[], reference_class_refs=[],
        evidence_refs=[], model_run_refs=[], parent_forecast_id=None, forecast_origin="live",
        agent_model=None, prompt_version=None, forecasting_protocol_version=None,
        toolset_version=None, source_snapshot_refs=[], evidence_cutoff=None, backtest_run_id=None,
        calibration_eligible=True, calibration_weight=1.0, calibration_lesson_refs=[],
        calibration_adjustment={}, metadata={}, reasons_up=["a"], reasons_down=[], change_my_mind=[],
    )


def _numeric_question() -> ForecastQuestion:
    return ForecastQuestion(
        id="q1", title="CPI YoY level?", description="", resolution_criteria=CRITERIA,
        resolution_source=None, created_at="t", close_time=None, resolution_time=None,
        outcome_space=OutcomeSpace(type="numeric", choices=[], units="pct"), status="open",
        tags=[], domain=None, topics=[], owner=None, impact=None, review_cadence=None,
        next_review_at=None, current_forecast_id="f1",
    )


def test_band_extracted_when_the_distribution_really_has_one():
    snap = _distribution_snapshot({"median": 3.0, "interval_90_low": 2.5, "interval_90_high": 3.6})
    body = build_forecast_card_body(snap, _numeric_question())
    assert body.band is not None
    assert (body.band.low, body.band.high, body.band.label) == (2.5, 3.6, "90%")
    # A distribution has no single winner probability.
    assert body.probability is None
    assert body.distribution is not None


def test_band_never_fabricated_for_malformed_or_absent_intervals():
    assert _extract_band(0.62) is None  # binary scalar
    assert _extract_band({"median": 3.0}) is None  # no interval
    assert _extract_band({"interval_90_low": 3.6, "interval_90_high": 2.5}) is None  # inverted
    assert _extract_band({"q05": 2.0, "q95": 4.0}).low == 2.0  # quantile fallback


# ── evidence.share ────────────────────────────────────────────────────────────

def test_evidence_share_hashes_the_excerpt_and_keeps_capture_time(seeded):
    ledger, qid, eid = seeded
    evidence = ledger.get_evidence(eid)

    card = render_evidence_share(evidence, _identity())
    assert card.event_type == "sfp.evidence.share"
    from protocol.collab import EvidenceShareBody

    body = EvidenceShareBody.model_validate(card.event_payload["body"])
    excerpt = evidence.summary or evidence.claim
    assert body.excerpt == excerpt
    assert body.sha256 == sha256_hex(excerpt)  # hash the shared excerpt
    assert body.claim == evidence.claim
    assert body.captured_at == evidence.captured_at  # capture time, not arrival
    assert excerpt in _blocks_text(card.blocks)  # excerpt rides the quote block


# ── lesson.share ──────────────────────────────────────────────────────────────

def test_lesson_share_marked_pending_triage_with_origin_stats(tmp_path):
    ledger = ForecastLedger(str(tmp_path / "lesson.db"))
    ledger.initialize_schema()
    with allow_ledger_writes("test seed"):
        lesson = ledger.create_calibration_lesson(
            scope_type="domain", scope_ref="politics",
            lesson="Discount single-poll swings in primaries.",
            confidence=0.6, status="active",
            metadata={"n": 12, "effect_size": 0.08},
        )

    card = render_lesson_share(lesson, _identity())
    assert card.event_type == "sfp.lesson.share"
    from protocol.collab import LessonShareBody

    body = LessonShareBody.model_validate(card.event_payload["body"])
    assert body.scope_type == "domain" and body.scope_ref == "politics"
    assert body.origin_n == 12 and body.effect_size == 0.08
    assert body.status == "active"
    text = _blocks_text(card.blocks)
    assert "pending your triage" in text
    assert "n=12" in text
    assert "Ada" in text  # provenance
