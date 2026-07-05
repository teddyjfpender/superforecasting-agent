"""Card renderers — turn a ledger object into an ``sfp/1`` payload + Block Kit.

M2 (the protocol + cards) of the multiplayer-harness plan. Each renderer takes a
real ledger object (a snapshot, an evidence item, a lesson) plus the sharing
desk's :class:`forecasting.identity.AgentIdentity` and returns a
:class:`RenderedCard`: the human-readable Block Kit for the Slack surface, the
``event_type`` label, and the machine-truth ``event_payload`` (the ``sfp/1``
envelope) that a peer parses.

The forecast card obeys the honesty laws: the headline % is the committed
probability formatted to 2dp, the uncertainty band is carried ONLY when the
forecast genuinely has one (never fabricated for a binary point estimate), and the
sender provenance footer is immutable. The resolution-criteria sha256 hash is the
question-identity key M3 resolves peers onto local questions by.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from protocol.collab import (
    KIND_EVIDENCE_SHARE,
    KIND_FORECAST_CARD,
    KIND_LESSON_SHARE,
    EvidenceShareBody,
    ForecastCardBody,
    LessonShareBody,
    SfpBand,
    SfpEnvelope,
    SfpEvidenceRef,
    SfpMetadata,
    SfpSender,
    build_metadata,
    canonical_json,
    sha256_hex,
)

# The Slack ``header`` block's ``plain_text`` is capped at 150 chars.
_HEADER_MAX = 150


# ── criteria identity hash ────────────────────────────────────────────────────

def criteria_hash(resolution_criteria: str) -> str:
    """The question-identity hash: sha256 of the whitespace-normalised criteria.

    Whitespace-insensitive (runs collapse to single spaces, ends stripped) so two
    desks that wrote the same criteria with different wrapping resolve onto the
    SAME question (design: never title fuzzy-match alone). Case and wording are
    preserved — a genuine criteria difference is a different question, which M3
    surfaces as a divergence warning rather than silently merging."""

    normalised = " ".join((resolution_criteria or "").split())
    return sha256_hex(normalised)


# ── the rendered result ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class RenderedCard:
    """A rendered card: the Block Kit surface + the ``sfp/1`` metadata.

    Behaves as the ``{blocks, event_type, event_payload}`` mapping the tool /
    router contract expects (``["blocks"]`` etc.), while also exposing the typed
    :attr:`envelope` and the overflow :attr:`file_content` for the post path."""

    blocks: list[dict[str, Any]]
    event_type: str
    event_payload: dict[str, Any]
    envelope: SfpEnvelope
    file_content: Optional[str] = None
    file_sha256: Optional[str] = None
    filename: Optional[str] = None
    fallback_text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return {
            "blocks": self.blocks,
            "event_type": self.event_type,
            "event_payload": self.event_payload,
        }[key]

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks": self.blocks,
            "event_type": self.event_type,
            "event_payload": self.event_payload,
        }


def _rendered(
    envelope: SfpEnvelope,
    blocks: list[dict[str, Any]],
    fallback_text: str,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> RenderedCard:
    meta: SfpMetadata = build_metadata(envelope)
    return RenderedCard(
        blocks=blocks,
        event_type=meta.event_type,
        event_payload=meta.event_payload,
        envelope=envelope,
        file_content=meta.file_content,
        file_sha256=meta.file_sha256,
        filename=meta.filename,
        fallback_text=fallback_text,
        extra=dict(extra or {}),
    )


# ── small pure helpers ────────────────────────────────────────────────────────

def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_sender(identity: Any) -> SfpSender:
    """Coerce an AgentIdentity / sender-dict / SfpSender into an SfpSender."""

    if isinstance(identity, SfpSender):
        return identity
    if isinstance(identity, dict):
        return SfpSender.model_validate(identity)
    return SfpSender.model_validate(identity.sfp_sender())


def _provenance_footer(sender: SfpSender) -> str:
    team = f" · {sender.team}" if sender.team else ""
    return f"shared by *{sender.agent}*{team} · sfp/1"


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _headline_probability(payload: Any, outcome_type: str) -> Optional[float]:
    """The committed winner probability for a card headline: the binary ``p`` or a
    categorical leading-outcome mass. A distribution has no single winner
    probability, so this returns ``None`` (its central tendency renders instead)."""

    if outcome_type == "binary":
        return _num(payload)
    if outcome_type == "categorical" and isinstance(payload, dict):
        vals = [v for v in (_num(x) for x in payload.values()) if v is not None]
        return max(vals) if vals else None
    return None


def _extract_band(payload: Any) -> Optional[SfpBand]:
    """The honest uncertainty band: a distribution's 90% interval, or ``None``.

    NEVER fabricates one — a binary scalar (no dict payload) or a malformed /
    inverted interval yields ``None`` so the card carries no band rather than a
    made-up one (the central-in-band honesty law)."""

    if not isinstance(payload, dict):
        return None
    lo = _num(payload.get("interval_90_low"))
    hi = _num(payload.get("interval_90_high"))
    if lo is None or hi is None:
        lo, hi = _num(payload.get("q05")), _num(payload.get("q95"))
    if lo is None or hi is None or hi < lo:
        return None
    return SfpBand(low=lo, high=hi, label="90%")


def _top_bullets(snapshot: Any, limit: int = 3) -> list[str]:
    """Up to *limit* rationale bullets — the drivers (``reasons_up``), else the key
    assumptions, else the leading sentences of the rationale prose."""

    def _clean(items: Any) -> list[str]:
        return [str(x).strip() for x in (items or []) if str(x).strip()]

    bullets = _clean(getattr(snapshot, "reasons_up", None))
    if not bullets:
        bullets = _clean(getattr(snapshot, "key_assumptions", None))
    if not bullets:
        rationale = (getattr(snapshot, "rationale", None) or "").strip()
        if rationale:
            bullets = [s.strip() for s in re.split(r"(?<=[.!?])\s+", rationale) if s.strip()]
    return bullets[:limit]


def _headline_text(body: ForecastCardBody) -> str:
    """The 2dp headline for the Block Kit surface."""

    if body.probability is not None:
        return f"{body.probability * 100:.2f}%"
    if isinstance(body.distribution, dict):
        for key in ("median", "mean", "p50"):
            val = _num(body.distribution.get(key))
            if val is not None:
                return f"{key} {val:g}"
    return "(no point estimate)"


def _band_text(band: Optional[SfpBand]) -> str:
    if band is None:
        return ""
    label = f"{band.label} " if band.label else ""
    return f"  ·  {label}band {band.low:g}–{band.high:g}"


# ── forecast.card ─────────────────────────────────────────────────────────────

def build_forecast_card_body(
    snapshot: Any,
    question: Any,
    *,
    ledger: Any = None,
    max_bullets: int = 3,
) -> ForecastCardBody:
    """Build the :class:`ForecastCardBody` machine payload from a real snapshot +
    question (pure; no Slack, no network)."""

    outcome_type = getattr(question.outcome_space, "type", "binary")
    payload = snapshot.probability_or_distribution
    probability = _headline_probability(payload, outcome_type)
    distribution = payload if isinstance(payload, dict) and probability is None else None
    band = _extract_band(payload)

    evidence_refs = _resolve_evidence_refs(getattr(snapshot, "evidence_refs", None), ledger)

    return ForecastCardBody(
        question_title=question.title,
        criteria_hash=criteria_hash(question.resolution_criteria),
        outcome_type=outcome_type,
        as_of=snapshot.as_of,
        probability=probability,
        distribution=distribution,
        band=band,
        horizon_days=getattr(snapshot, "forecast_horizon_days", None),
        rationale_bullets=_top_bullets(snapshot, max_bullets),
        evidence_refs=evidence_refs,
        question_id=getattr(question, "id", None),
    )


def _resolve_evidence_refs(refs: Any, ledger: Any) -> list[SfpEvidenceRef]:
    out: list[SfpEvidenceRef] = []
    for ref in refs or []:
        eid = str(ref)
        title: Optional[str] = None
        if ledger is not None:
            try:
                item = ledger.get_evidence(eid)
                title = _truncate(item.source_name or item.claim or "", 80) or None
            except Exception:  # noqa: BLE001 — a missing/unreadable ref still shares its id
                title = None
        out.append(SfpEvidenceRef(id=eid, title=title))
    return out


def _forecast_card_blocks(body: ForecastCardBody, sender: SfpSender) -> list[dict[str, Any]]:
    headline = _headline_text(body)
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": _truncate(body.question_title, _HEADER_MAX)}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{headline}*{_band_text(body.band)}"}},
    ]
    if body.rationale_bullets:
        bullets = "\n".join(f"• {b}" for b in body.rationale_bullets)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": bullets}})
    ev = ""
    if body.evidence_refs:
        ev = "  ·  " + f"{len(body.evidence_refs)} evidence ref(s)"
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"as of {body.as_of}  ·  criteria `{body.criteria_hash[:12]}`{ev}"}],
    })
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": _provenance_footer(sender)}]})
    return blocks


def render_forecast_card(
    snapshot: Any,
    question: Any,
    identity: Any,
    *,
    ledger: Any = None,
    ts: Optional[str] = None,
) -> RenderedCard:
    """Render a snapshot as a ``forecast.card`` — Block Kit + ``sfp/1`` payload."""

    sender = _as_sender(identity)
    body = build_forecast_card_body(snapshot, question, ledger=ledger)
    envelope = SfpEnvelope.of(KIND_FORECAST_CARD, sender, body, ts=ts)
    blocks = _forecast_card_blocks(body, sender)
    fallback = f"{question.title} — {_headline_text(body)} (shared by {sender.agent})"
    return _rendered(envelope, blocks, fallback, extra={"criteria_hash": body.criteria_hash})


# ── evidence.share ────────────────────────────────────────────────────────────

def build_evidence_share_body(evidence: Any) -> EvidenceShareBody:
    """Build the :class:`EvidenceShareBody` from a real evidence item."""

    excerpt = (getattr(evidence, "summary", None) or getattr(evidence, "claim", None) or "").strip()
    return EvidenceShareBody(
        source_type=getattr(evidence, "source_type", None) or "note",
        captured_at=evidence.captured_at,
        claim=getattr(evidence, "claim", None) or "",
        sha256=sha256_hex(excerpt),
        evidence_id=getattr(evidence, "id", None),
        source_url=getattr(evidence, "source_url", None),
        source_name=getattr(evidence, "source_name", None),
        available_at=getattr(evidence, "available_at", None),
        published_at=getattr(evidence, "published_at", None),
        triage_label=(getattr(evidence, "metadata", None) or {}).get("triage_label"),
        stance=getattr(evidence, "stance", None),
        excerpt=excerpt or None,
    )


def _evidence_blocks(body: EvidenceShareBody, sender: SfpSender) -> list[dict[str, Any]]:
    src = body.source_name or body.source_url or body.source_type
    label = body.triage_label or "unlabeled"
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Evidence*  ·  {body.source_type}  ·  {_truncate(src, 120)}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"> {_truncate(body.excerpt or body.claim, 2800)}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"captured {body.captured_at}  ·  {label}  ·  sha `{body.sha256[:12]}`"}]},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": _provenance_footer(sender)}]},
    ]
    return blocks


def render_evidence_share(evidence: Any, identity: Any, *, ts: Optional[str] = None) -> RenderedCard:
    """Render an evidence item as an ``evidence.share`` — quote block + ``sfp/1``."""

    sender = _as_sender(identity)
    body = build_evidence_share_body(evidence)
    envelope = SfpEnvelope.of(KIND_EVIDENCE_SHARE, sender, body, ts=ts)
    blocks = _evidence_blocks(body, sender)
    fallback = f"Evidence: {_truncate(body.claim, 120)} (shared by {sender.agent})"
    return _rendered(envelope, blocks, fallback)


# ── lesson.share ──────────────────────────────────────────────────────────────

def build_lesson_share_body(lesson: dict[str, Any]) -> LessonShareBody:
    """Build the :class:`LessonShareBody` from a calibration-lesson dict (the shape
    ``list_calibration_lessons`` returns)."""

    recommended = lesson.get("recommended_adjustment") or {}
    metadata = lesson.get("metadata") or {}
    rule = recommended.get("rule") if isinstance(recommended, dict) else None
    rule_preview: Optional[str] = None
    if isinstance(rule, dict):
        rule_preview = _truncate(canonical_json(rule), 400)

    def _int(value: Any) -> Optional[int]:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return LessonShareBody(
        lesson=lesson.get("lesson") or "",
        scope_type=lesson.get("scope_type") or "global",
        scope_ref=lesson.get("scope_ref"),
        lesson_id=lesson.get("id"),
        confidence=_num(lesson.get("confidence")),
        origin_n=_int(metadata.get("n") or metadata.get("sample_size") or len(lesson.get("source_score_record_refs") or []) or None),
        effect_size=_num(metadata.get("effect_size")),
        compiled_rule_preview=rule_preview,
        status=lesson.get("status"),
    )


def _lesson_blocks(body: LessonShareBody, sender: SfpSender) -> list[dict[str, Any]]:
    scope = body.scope_type + (f":{body.scope_ref}" if body.scope_ref else "")
    stats: list[str] = []
    if body.origin_n is not None:
        stats.append(f"n={body.origin_n}")
    if body.effect_size is not None:
        stats.append(f"effect={body.effect_size:g}")
    if body.confidence is not None:
        stats.append(f"conf={body.confidence:g}")
    stats_text = ("  ·  ".join(stats)) if stats else "no origin stats"
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Lesson* (scope: `{scope}`)  —  _pending your triage_"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _truncate(body.lesson, 2800)}},
    ]
    if body.compiled_rule_preview:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"compiled rule preview:\n```{_truncate(body.compiled_rule_preview, 800)}```"}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"{stats_text}  ·  origin status: {body.status or 'unknown'}"}]})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": _provenance_footer(sender)}]})
    return blocks


def render_lesson_share(lesson: dict[str, Any], identity: Any, *, ts: Optional[str] = None) -> RenderedCard:
    """Render a calibration lesson as a ``lesson.share`` — callout marked
    "pending your triage" + ``sfp/1``."""

    sender = _as_sender(identity)
    body = build_lesson_share_body(lesson)
    envelope = SfpEnvelope.of(KIND_LESSON_SHARE, sender, body, ts=ts)
    blocks = _lesson_blocks(body, sender)
    fallback = f"Lesson (pending triage): {_truncate(body.lesson, 120)} (shared by {sender.agent})"
    return _rendered(envelope, blocks, fallback)


__all__ = [
    "criteria_hash",
    "RenderedCard",
    "build_forecast_card_body",
    "render_forecast_card",
    "build_evidence_share_body",
    "render_evidence_share",
    "build_lesson_share_body",
    "render_lesson_share",
]
