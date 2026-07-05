"""``sfp/1`` — the SuperForecast Protocol carried over Slack message metadata.

M2 (the protocol + cards) of the multiplayer-harness plan
(``docs/plans/2026-07-05-multiplayer-slack-harness.md``). Where the gateway wire
(``protocol/rpc`` + ``protocol/events``) is how the TUI talks to the desk, ``sfp/1``
is how one named desk talks to ANOTHER across the org boundary: a versioned JSON
payload rides Slack's ``chat.postMessage`` message-metadata (``event_type`` +
``event_payload``) under a human-readable Block Kit surface, so agents parse each
other's machine truth instead of regexing prose.

The envelope is ``{v, kind, sender, ts, body}`` (design pillar 3). Every payload:

* ``v`` — the protocol version (``1``); a peer speaking a version we don't know is
  rejected with a naming error rather than silently mis-parsed.
* ``kind`` — one of the six message kinds in the plan's table (``forecast.card``,
  ``evidence.share``, ``lesson.share``, ``thesis.round``, ``thesis.aggregate``, and
  ``ack`` / ``request`` — the last row shares :class:`AckRequestBody`).
* ``sender`` — the sfp/1 sender dict :meth:`forecasting.identity.AgentIdentity.sfp_sender`
  stamps (``{agent, instance_id, team}``); provenance is immutable (design pillar
  "the honesty doctrine, extended" — never repost another agent's numbers as your
  own).
* ``ts`` — an ISO-8601 instant.
* ``body`` — the kind's typed payload, stored as its canonical dict. It is carried
  as an opaque ``dict`` on the envelope and parsed back to its typed model by
  :func:`parse_body` keyed on ``kind`` — a discriminator no union-guessing can get
  wrong, so a re-parsed body is byte-identical to the rendered one (the M2 gate).

**Size cap + overflow.** Slack metadata is capped at 8 KB and only apps can read
it. A payload that fits rides inline; a larger one uploads its body as a file and
the metadata carries a :class:`SfpFilePointer` (``sha256`` + byte count) in place
of the body. :func:`build_metadata` picks the form; :func:`validate_metadata_size`
is the raw cap check (it names the byte count it refused).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import Field, field_validator

from protocol.types import WireModel

# ── constants ─────────────────────────────────────────────────────────────────

SFP_VERSION = 1

# Slack message metadata is capped at 8 KB (design pillar 3 / the honest limits).
# A body that would push the metadata past this rides a file upload instead.
SFP_MAX_METADATA_BYTES = 8 * 1024

# The six message kinds of the plan's table. ``ack`` and ``request`` are the two
# spellings of the last row and share :class:`AckRequestBody`.
KIND_FORECAST_CARD = "forecast.card"
KIND_EVIDENCE_SHARE = "evidence.share"
KIND_LESSON_SHARE = "lesson.share"
KIND_THESIS_ROUND = "thesis.round"
KIND_THESIS_AGGREGATE = "thesis.aggregate"
KIND_ACK = "ack"
KIND_REQUEST = "request"


# ── canonical serialisation (byte-stable so a round-trip can be compared) ─────

def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, unicode preserved.

    Accepts a :class:`WireModel` (dumped to its JSON-mode dict first) or a plain
    dict/list. This is THE canonical form the round-trip byte-equality (the M2
    gate) and the overflow ``sha256`` are computed over."""

    if isinstance(obj, WireModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    """The hex sha256 of *text*'s UTF-8 bytes (the content-identity hash)."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── shared value objects ──────────────────────────────────────────────────────

class SfpSender(WireModel):
    """The immutable provenance of a payload — mirrors
    :meth:`forecasting.identity.AgentIdentity.sfp_sender`."""

    agent: str
    instance_id: str
    team: Optional[str] = None


class SfpBand(WireModel):
    """An uncertainty band — carried ONLY when the forecast genuinely has one (a
    distribution's interval). A binary point forecast has no band and MUST NOT
    fabricate one (the honesty laws), so :attr:`ForecastCardBody.band` stays null."""

    low: float
    high: float
    label: Optional[str] = None


class SfpEvidenceRef(WireModel):
    """A pointer to a piece of evidence backing a card: its id and a short title."""

    id: str
    title: Optional[str] = None


class SfpQuestionRef(WireModel):
    """A cross-instance question identity: the title plus the resolution-criteria
    sha256 (:func:`criteria_hash`) — the key M3 resolves peers onto local
    questions by (never title fuzzy-match alone)."""

    title: str
    criteria_hash: str
    question_id: Optional[str] = None


class SfpMemberEstimate(WireModel):
    """One panelist's number in a :class:`ThesisAggregateBody` digest."""

    agent: str
    instance_id: Optional[str] = None
    probability: Optional[float] = None


class SfpFilePointer(WireModel):
    """The overflow form: a payload too big for 8 KB metadata rides a file upload
    and the metadata carries this pointer (content ``sha256`` + byte count) in the
    envelope's ``body`` slot."""

    sha256: str
    bytes: int
    kind: str
    encoding: str = "application/json"
    filename: Optional[str] = None


# ── the six body kinds ────────────────────────────────────────────────────────

class ForecastCardBody(WireModel):
    """``forecast.card`` — a scoreable forecast shared as a card.

    Machine truth: the raw ``probability`` (binary) or ``distribution``, the
    ``criteria_hash`` question identity, ``as_of``, ``horizon_days``, the top-3
    ``rationale_bullets``, ``evidence_refs``, and the honest ``band`` (null unless
    the forecast really carries one). The Block Kit surface renders the 2dp
    headline % from ``probability``."""

    question_title: str
    criteria_hash: str
    outcome_type: str
    as_of: str
    probability: Optional[float] = None
    distribution: Optional[dict[str, Any]] = None
    band: Optional[SfpBand] = None
    horizon_days: Optional[float] = None
    rationale_bullets: list[str] = Field(default_factory=list)
    evidence_refs: list[SfpEvidenceRef] = Field(default_factory=list)
    question_id: Optional[str] = None


class EvidenceShareBody(WireModel):
    """``evidence.share`` — one evidence item shared with peer provenance.

    Carries the source, ``captured_at`` (imported evidence keeps ITS capture time,
    never arrival time — the no-fabricated-freshness law), the triage label, a key
    excerpt, and the content ``sha256`` (the receiver verifies the file against it)."""

    source_type: str
    captured_at: str
    claim: str
    sha256: str
    evidence_id: Optional[str] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    available_at: Optional[str] = None
    published_at: Optional[str] = None
    triage_label: Optional[str] = None
    stance: Optional[str] = None
    excerpt: Optional[str] = None


class LessonShareBody(WireModel):
    """``lesson.share`` — a calibration lesson shared for the receiver's triage.

    A peer lesson lands INACTIVE pending triage (never auto-compiled to an enforced
    rule), so the body carries the origin stats (``origin_n``, ``effect_size``,
    ``confidence``) and a ``compiled_rule_preview`` for the operator to judge."""

    lesson: str
    scope_type: str
    scope_ref: Optional[str] = None
    lesson_id: Optional[str] = None
    confidence: Optional[float] = None
    origin_n: Optional[int] = None
    effect_size: Optional[float] = None
    compiled_rule_preview: Optional[str] = None
    status: Optional[str] = None


class ThesisRoundBody(WireModel):
    """``thesis.round`` — a facilitator opens a Delphi round on a question set."""

    round: int
    question_refs: list[SfpQuestionRef] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    deadline: Optional[str] = None
    facilitator: Optional[str] = None
    note: Optional[str] = None


class ThesisAggregateBody(WireModel):
    """``thesis.aggregate`` — the facilitator closes a round: the per-member digest,
    the spread/disagreement map, and the Delphi aggregate + its method."""

    round: int
    question_ref: SfpQuestionRef
    method: str
    member_estimates: list[SfpMemberEstimate] = Field(default_factory=list)
    aggregate: Optional[float] = None
    aggregate_distribution: Optional[dict[str, Any]] = None
    spread: Optional[float] = None
    disagreement: Optional[dict[str, Any]] = None


class AckRequestBody(WireModel):
    """``ack`` / ``request`` — a correlated signal. An ``ack`` reports a fixed-meaning
    protocol signal (``imported`` / ``read`` / ``revised``); a ``request`` asks a peer
    to act (e.g. ``share_evidence`` for a question)."""

    correlation_id: str
    intent: str  # "ack" | "request"
    signal: Optional[str] = None
    request_kind: Optional[str] = None
    question_ref: Optional[SfpQuestionRef] = None
    note: Optional[str] = None


# The kind -> body-model registry. ``ack`` and ``request`` share one body model
# (the plan's table lists them as one row).
BODY_MODEL_BY_KIND: dict[str, type[WireModel]] = {
    KIND_FORECAST_CARD: ForecastCardBody,
    KIND_EVIDENCE_SHARE: EvidenceShareBody,
    KIND_LESSON_SHARE: LessonShareBody,
    KIND_THESIS_ROUND: ThesisRoundBody,
    KIND_THESIS_AGGREGATE: ThesisAggregateBody,
    KIND_ACK: AckRequestBody,
    KIND_REQUEST: AckRequestBody,
}
VALID_KINDS = frozenset(BODY_MODEL_BY_KIND)


# ── the envelope ──────────────────────────────────────────────────────────────

class SfpEnvelope(WireModel):
    """The ``sfp/1`` envelope: ``{v, kind, sender, ts, body}``.

    ``body`` is carried as an opaque canonical dict — :func:`parse_body` turns it
    back into the typed model keyed on ``kind``. Build one with :meth:`of` so the
    body is always stored in its canonical form."""

    v: int = SFP_VERSION
    kind: str
    sender: SfpSender
    ts: str
    body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("v")
    @classmethod
    def _check_version(cls, value: int) -> int:
        if value != SFP_VERSION:
            raise ValueError(
                f"v (sfp protocol version) must be {SFP_VERSION}; got {value!r} — "
                "this desk speaks only sfp/1"
            )
        return value

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, value: str) -> str:
        if value not in VALID_KINDS:
            raise ValueError(
                f"kind must be one of {sorted(VALID_KINDS)}; got {value!r}"
            )
        return value

    @classmethod
    def of(
        cls,
        kind: str,
        sender: SfpSender | dict[str, Any],
        body: WireModel | dict[str, Any],
        *,
        ts: Optional[str] = None,
    ) -> "SfpEnvelope":
        """Build an envelope, storing *body* in its canonical dict form."""

        if isinstance(sender, dict):
            sender = SfpSender.model_validate(sender)
        body_dict = body.model_dump(mode="json") if isinstance(body, WireModel) else dict(body)
        return cls(v=SFP_VERSION, kind=kind, sender=sender, ts=ts or _now_iso(), body=body_dict)

    def canonical_body_json(self) -> str:
        return canonical_json(self.body)


def is_file_pointer(body: dict[str, Any]) -> bool:
    """Whether an envelope's ``body`` is the overflow :class:`SfpFilePointer` form.

    Detected by the pointer's ``sha256`` + ``bytes`` + ``kind`` triple, which no
    body kind carries together (``evidence.share`` has ``sha256`` but neither
    ``bytes`` nor a body-level ``kind``)."""

    return (
        isinstance(body, dict)
        and "sha256" in body
        and "bytes" in body
        and "kind" in body
    )


def parse_envelope(payload: dict[str, Any]) -> SfpEnvelope:
    """Parse a metadata ``event_payload`` into an :class:`SfpEnvelope` (validates
    ``v`` and ``kind``)."""

    return SfpEnvelope.model_validate(payload)


def parse_body(envelope: SfpEnvelope) -> WireModel:
    """Parse the envelope's ``body`` into its typed model — the overflow
    :class:`SfpFilePointer` when it's the file form, else the kind's body model."""

    if is_file_pointer(envelope.body):
        return SfpFilePointer.model_validate(envelope.body)
    model = BODY_MODEL_BY_KIND.get(envelope.kind)
    if model is None:  # pragma: no cover — kind is validated on the envelope
        raise ValueError(f"no body model for kind {envelope.kind!r}")
    return model.model_validate(envelope.body)


# ── size cap + overflow ───────────────────────────────────────────────────────

class SfpSizeError(ValueError):
    """Raised when a metadata payload exceeds the Slack 8 KB cap and cannot be
    carried inline (names the byte count it refused)."""

    def __init__(self, size_bytes: int, limit: int = SFP_MAX_METADATA_BYTES) -> None:
        self.size_bytes = size_bytes
        self.limit = limit
        super().__init__(
            f"sfp metadata payload is {size_bytes} bytes, over the {limit}-byte "
            "Slack metadata cap — share the body as a file upload with a pointer"
        )


def metadata_byte_size(payload: dict[str, Any]) -> int:
    """The UTF-8 byte size of a metadata ``event_payload`` in canonical form."""

    return len(canonical_json(payload).encode("utf-8"))


def validate_metadata_size(payload: dict[str, Any], *, limit: int = SFP_MAX_METADATA_BYTES) -> int:
    """Assert *payload* fits the metadata cap; return its byte size or raise
    :class:`SfpSizeError` naming the overflow."""

    size = metadata_byte_size(payload)
    if size > limit:
        raise SfpSizeError(size, limit)
    return size


@dataclass(frozen=True)
class SfpMetadata:
    """The resolved Slack-metadata form of an envelope: the ``event_type`` +
    ``event_payload`` to stamp on ``chat.postMessage``, plus (when it overflowed)
    the file body to upload alongside and its ``sha256``."""

    event_type: str
    event_payload: dict[str, Any]
    overflow: bool
    file_content: Optional[str] = None
    file_sha256: Optional[str] = None
    filename: Optional[str] = None


def event_type_for(kind: str) -> str:
    """The Slack ``event_type`` label for a kind: ``sfp.<kind>``."""

    return f"sfp.{kind}"


def build_metadata(
    envelope: SfpEnvelope,
    *,
    limit: int = SFP_MAX_METADATA_BYTES,
) -> SfpMetadata:
    """Resolve an envelope to its Slack-metadata form.

    Inline when it fits the cap; otherwise the body is replaced by a
    :class:`SfpFilePointer` (``sha256`` + byte count) and the canonical body JSON is
    returned as :attr:`SfpMetadata.file_content` for a file upload."""

    inline_payload = envelope.model_dump(mode="json")
    event_type = event_type_for(envelope.kind)
    if metadata_byte_size(inline_payload) <= limit:
        return SfpMetadata(event_type=event_type, event_payload=inline_payload, overflow=False)

    body_json = envelope.canonical_body_json()
    digest = sha256_hex(body_json)
    filename = f"sfp-{envelope.kind.replace('.', '_')}-{digest[:12]}.json"
    pointer = SfpFilePointer(
        sha256=digest,
        bytes=len(body_json.encode("utf-8")),
        kind=envelope.kind,
        filename=filename,
    )
    overflow_env = envelope.model_copy(update={"body": pointer.model_dump(mode="json")})
    overflow_payload = overflow_env.model_dump(mode="json")
    # The pointer is tiny, but assert the overflow form itself fits (names the
    # byte count if some pathological sender/kind ever didn't).
    validate_metadata_size(overflow_payload, limit=limit)
    return SfpMetadata(
        event_type=event_type,
        event_payload=overflow_payload,
        overflow=True,
        file_content=body_json,
        file_sha256=digest,
        filename=filename,
    )


# Every collab model the protocol registry emits to TS / docs (see
# ``protocol/__init__.py`` EXTRA_MODELS). Listed here so the registry imports one
# name and the codegen collector reaches them all.
COLLAB_MODELS: list[type[WireModel]] = [
    SfpEnvelope,
    SfpSender,
    SfpBand,
    SfpEvidenceRef,
    SfpQuestionRef,
    SfpMemberEstimate,
    SfpFilePointer,
    ForecastCardBody,
    EvidenceShareBody,
    LessonShareBody,
    ThesisRoundBody,
    ThesisAggregateBody,
    AckRequestBody,
]


__all__ = [
    "SFP_VERSION",
    "SFP_MAX_METADATA_BYTES",
    "KIND_FORECAST_CARD",
    "KIND_EVIDENCE_SHARE",
    "KIND_LESSON_SHARE",
    "KIND_THESIS_ROUND",
    "KIND_THESIS_AGGREGATE",
    "KIND_ACK",
    "KIND_REQUEST",
    "BODY_MODEL_BY_KIND",
    "VALID_KINDS",
    "SfpSender",
    "SfpBand",
    "SfpEvidenceRef",
    "SfpQuestionRef",
    "SfpMemberEstimate",
    "SfpFilePointer",
    "ForecastCardBody",
    "EvidenceShareBody",
    "LessonShareBody",
    "ThesisRoundBody",
    "ThesisAggregateBody",
    "AckRequestBody",
    "SfpEnvelope",
    "SfpMetadata",
    "SfpSizeError",
    "COLLAB_MODELS",
    "canonical_json",
    "sha256_hex",
    "event_type_for",
    "build_metadata",
    "validate_metadata_size",
    "metadata_byte_size",
    "is_file_pointer",
    "parse_envelope",
    "parse_body",
]
