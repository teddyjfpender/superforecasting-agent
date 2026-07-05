"""sfp/1 protocol tests (multiplayer M2): every kind round-trips, the 8 KB size
cap holds with a file-pointer overflow form, and the criteria-identity hash is
stable + whitespace-insensitive.
"""

from __future__ import annotations

import json

import pytest

from protocol.collab import (
    KIND_ACK,
    KIND_EVIDENCE_SHARE,
    KIND_FORECAST_CARD,
    KIND_LESSON_SHARE,
    KIND_REQUEST,
    KIND_THESIS_AGGREGATE,
    KIND_THESIS_ROUND,
    SFP_MAX_METADATA_BYTES,
    AckRequestBody,
    EvidenceShareBody,
    ForecastCardBody,
    LessonShareBody,
    SfpBand,
    SfpEnvelope,
    SfpEvidenceRef,
    SfpFilePointer,
    SfpMemberEstimate,
    SfpQuestionRef,
    SfpSender,
    SfpSizeError,
    ThesisAggregateBody,
    ThesisRoundBody,
    build_metadata,
    canonical_json,
    is_file_pointer,
    parse_body,
    parse_envelope,
    sha256_hex,
    validate_metadata_size,
)
from forecasting.collab.cards import criteria_hash


def _sender() -> SfpSender:
    return SfpSender(agent="Ada", instance_id="inst-abc", team="T012ABC")


# ── the six kinds each round-trip through the envelope ────────────────────────

def _bodies() -> dict[str, object]:
    return {
        KIND_FORECAST_CARD: ForecastCardBody(
            question_title="Will CPI YoY exceed 3.0%?",
            criteria_hash=criteria_hash("BLS CPI-U YoY exceeds 3.0%."),
            outcome_type="binary",
            as_of="2026-07-05T00:00:00Z",
            probability=0.62,
            band=None,
            rationale_bullets=["shelter sticky", "energy rebound", "wages firm"],
            evidence_refs=[SfpEvidenceRef(id="ev_1", title="BLS release")],
        ),
        KIND_EVIDENCE_SHARE: EvidenceShareBody(
            source_type="statistical_release",
            captured_at="2026-07-04T12:00:00Z",
            claim="June CPI printed 3.1% YoY",
            sha256=sha256_hex("June CPI printed 3.1% YoY"),
            triage_label="interesting",
            excerpt="June CPI printed 3.1% YoY",
        ),
        KIND_LESSON_SHARE: LessonShareBody(
            lesson="Discount single-poll swings in primaries.",
            scope_type="domain",
            scope_ref="politics",
            origin_n=12,
            effect_size=0.08,
            status="active",
        ),
        KIND_THESIS_ROUND: ThesisRoundBody(
            round=1,
            question_refs=[SfpQuestionRef(title="Q1", criteria_hash=criteria_hash("Q1 crit"))],
            participants=["Ada", "Bernard"],
            deadline="2026-07-10T00:00:00Z",
            facilitator="Ada",
        ),
        KIND_THESIS_AGGREGATE: ThesisAggregateBody(
            round=1,
            question_ref=SfpQuestionRef(title="Q1", criteria_hash=criteria_hash("Q1 crit")),
            method="trimmed_geomean_odds",
            member_estimates=[SfpMemberEstimate(agent="Ada", probability=0.4),
                              SfpMemberEstimate(agent="Bernard", probability=0.5)],
            aggregate=0.45,
            spread=0.1,
        ),
        KIND_ACK: AckRequestBody(correlation_id="c-1", intent="ack", signal="imported"),
        KIND_REQUEST: AckRequestBody(
            correlation_id="c-2", intent="request", request_kind="share_evidence",
            question_ref=SfpQuestionRef(title="Q", criteria_hash=criteria_hash("Q crit")),
        ),
    }


@pytest.mark.parametrize("kind", list(_bodies()))
def test_every_kind_round_trips_byte_equal(kind):
    body = _bodies()[kind]
    envelope = SfpEnvelope.of(kind, _sender(), body, ts="2026-07-05T00:00:00Z")

    # Serialize to the metadata event_payload, then re-parse it back.
    meta = build_metadata(envelope)
    assert meta.event_type == f"sfp.{kind}"
    assert meta.overflow is False

    reparsed = parse_envelope(json.loads(json.dumps(meta.event_payload)))
    # BODY byte-equal in canonical JSON (the M2 gate).
    assert canonical_json(reparsed.body) == canonical_json(envelope.body)
    # And the TYPED body survives the wire identically.
    typed = parse_body(reparsed)
    assert canonical_json(typed) == canonical_json(body)
    # Sender provenance is carried immutably.
    assert reparsed.sender.model_dump() == _sender().model_dump()


def test_envelope_rejects_unknown_version():
    with pytest.raises(ValueError, match="v .*version"):
        SfpEnvelope(v=2, kind=KIND_FORECAST_CARD, sender=_sender(), ts="t", body={})


def test_envelope_rejects_unknown_kind():
    with pytest.raises(ValueError, match="kind must be one of"):
        SfpEnvelope(v=1, kind="forecast.gossip", sender=_sender(), ts="t", body={})


# ── size cap + overflow form ──────────────────────────────────────────────────

def test_small_payload_fits_the_cap_inline():
    env = SfpEnvelope.of(KIND_ACK, _sender(), AckRequestBody(correlation_id="c", intent="ack"))
    size = validate_metadata_size(env.model_dump(mode="json"))
    assert size <= SFP_MAX_METADATA_BYTES
    assert build_metadata(env).overflow is False


def test_oversize_payload_raises_naming_the_byte_count():
    huge = {"blob": "x" * (SFP_MAX_METADATA_BYTES + 100)}
    with pytest.raises(SfpSizeError) as exc:
        validate_metadata_size(huge)
    assert exc.value.size_bytes > SFP_MAX_METADATA_BYTES
    assert str(exc.value.size_bytes) in str(exc.value)


def test_overflow_produces_a_file_pointer_metadata():
    # A rationale far over 8 KB forces the overflow form.
    big_body = ForecastCardBody(
        question_title="Q",
        criteria_hash=criteria_hash("crit"),
        outcome_type="binary",
        as_of="2026-07-05T00:00:00Z",
        probability=0.5,
        rationale_bullets=["y" * 9000],
    )
    env = SfpEnvelope.of(KIND_FORECAST_CARD, _sender(), big_body)
    meta = build_metadata(env)

    assert meta.overflow is True
    assert meta.event_type == "sfp.forecast.card"
    # The metadata body is now a file pointer, not the card.
    assert is_file_pointer(meta.event_payload["body"])
    pointer = SfpFilePointer.model_validate(meta.event_payload["body"])
    assert pointer.kind == KIND_FORECAST_CARD
    # The pointer's sha256 + byte count describe the uploaded file exactly.
    assert meta.file_content is not None
    assert pointer.sha256 == sha256_hex(meta.file_content) == meta.file_sha256
    assert pointer.bytes == len(meta.file_content.encode("utf-8"))
    # The overflow metadata itself is within the cap.
    assert validate_metadata_size(meta.event_payload) <= SFP_MAX_METADATA_BYTES
    # The file content is the canonical body, so it reconstructs the typed card.
    rebuilt = ForecastCardBody.model_validate(json.loads(meta.file_content))
    assert canonical_json(rebuilt) == canonical_json(big_body)


def test_parse_body_of_overflow_envelope_returns_the_pointer():
    env = SfpEnvelope.of(
        KIND_FORECAST_CARD, _sender(),
        ForecastCardBody(question_title="Q", criteria_hash="h", outcome_type="binary",
                         as_of="t", probability=0.5, rationale_bullets=["y" * 9000]),
    )
    meta = build_metadata(env)
    reparsed = parse_envelope(meta.event_payload)
    assert isinstance(parse_body(reparsed), SfpFilePointer)


# ── criteria-identity hash ────────────────────────────────────────────────────

def test_criteria_hash_is_stable_and_whitespace_insensitive():
    a = criteria_hash("BLS CPI-U YoY for July 2026 exceeds 3.0%.")
    b = criteria_hash("  BLS   CPI-U\tYoY for  July 2026\n exceeds 3.0%.  ")
    assert a == b  # whitespace-insensitive
    assert criteria_hash("BLS CPI-U YoY for July 2026 exceeds 3.0%.") == a  # deterministic
    assert len(a) == 64  # sha256 hex


def test_criteria_hash_distinguishes_different_criteria():
    assert criteria_hash("exceeds 3.0%") != criteria_hash("exceeds 3.5%")
