"""The IMPORT PIPELINE — a peer's sfp/1 payload lands in this ledger as a GUEST.

M3 (the import pipeline) of the multiplayer-harness plan
(``docs/plans/2026-07-05-multiplayer-slack-harness.md``). Design pillar 4 —
"imports are guests, not citizens" — made concrete and, above all, HONEST:

* **forecast.card** → resolve the local question by resolution-criteria hash
  (never title fuzzy-match alone). A same-title question with DIFFERENT criteria
  raises a criteria-divergence WARNING (the classic group-forecasting failure,
  made visible not silenced). The peer number lands as a WORLD-VIEW forecast_link
  artifact (flag-don't-merge) hung off a peer-origin STUB question — NEVER as a
  local snapshot, so the receiver's scoring can never see it — and a >10pp gap
  against the local current fires an operator divergence alert.
* **evidence.share** → :meth:`ForecastLedger.add_evidence` with peer provenance,
  its sha256 verified against the payload, and — the no-fabricated-freshness law
  — the ORIGINAL ``captured_at`` preserved (never arrival time).
* **lesson.share** → stored INACTIVE (``status='tentative'``) with origin stats,
  surfaced in the lesson-review/triage queue, and NEVER auto-compiled to an
  enforced rule (no ``recommended_adjustment`` is passed, so the auto-compile hook
  cannot fire).

Everything — every import AND every refusal — appends a ``collab.*`` entry to the
collab event log (``{home}/collab/events.jsonl``) with the policy decision, so the
whole exchange is forensically replayable. Nothing here ever fabricates a peer's
number as the receiver's own: ``calibration_eligible`` is never set for peer data.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from protocol.collab import (
    KIND_EVIDENCE_SHARE,
    KIND_FORECAST_CARD,
    KIND_LESSON_SHARE,
    SfpSender,
    is_file_pointer,
    parse_body,
    sha256_hex,
)

logger = logging.getLogger("forecasting.collab.imports")

# The forecast_links.link_type used for a peer world-view edge (a valid existing
# type — ``related`` — carrying the peer number in its metadata; weight 0 so the
# cross-pollination auto-walk never gives it numeric pull: flag-don't-merge).
_PEER_LINK_TYPE = "related"

# The >10pp divergence bar that surfaces an operator alert (the plan's example
# "Ada @ 34% vs you @ 48%").
DIVERGENCE_THRESHOLD = 0.10

_DIVERGENCE_ALERT_PREFIX = "peer_forecast_divergence"
_CRITERIA_DIVERGENCE_ALERT_PREFIX = "criteria_divergence"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cfg(cfg: Any = None) -> Any:
    if cfg is not None:
        return cfg
    from forecasting.appconfig import get_config

    return get_config()


# ── the collab event log (forensic trail) ─────────────────────────────────────

def collab_events_path(home: Optional[Path | str] = None) -> Path:
    from forecasting.collab.directory import collab_dir

    return collab_dir(home) / "events.jsonl"


def append_collab_event(entry: dict[str, Any], home: Optional[Path | str] = None) -> None:
    """Append one ``collab.*`` event (import / refusal / decision) to the JSONL
    trail. Best-effort — a logging hiccup NEVER breaks an import (fail-open)."""

    record = {"ts": entry.get("ts") or _now_iso(), **entry}
    try:
        path = collab_events_path(home)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as exc:  # pragma: no cover — disk failure is non-fatal
        logger.warning("could not append collab event: %s", exc)


def list_collab_events(home: Optional[Path | str] = None) -> list[dict[str, Any]]:
    """Read back the collab event trail (oldest-first). ``[]`` when absent."""

    try:
        text = collab_events_path(home).read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ── result ────────────────────────────────────────────────────────────────────

@dataclass
class ImportResult:
    """The outcome of accepting a peer payload (data, never an exception — a
    refusal is a normal, logged outcome)."""

    kind: str
    outcome: str  # imported | refused | pending_approval | skipped | error
    provenance: Optional[str] = None
    sender: Optional[dict[str, Any]] = None
    decision: Optional[str] = None
    question_id: Optional[str] = None       # local anchor (forecast) / target (evidence)
    peer_question_id: Optional[str] = None  # the peer-origin stub
    link_id: Optional[str] = None
    evidence_id: Optional[str] = None
    lesson_id: Optional[str] = None
    alert_ids: list[str] = field(default_factory=list)
    reason: Optional[str] = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def imported(self) -> bool:
        return self.outcome == "imported"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "outcome": self.outcome,
            "provenance": self.provenance,
            "sender": self.sender,
            "decision": self.decision,
            "question_id": self.question_id,
            "peer_question_id": self.peer_question_id,
            "link_id": self.link_id,
            "evidence_id": self.evidence_id,
            "lesson_id": self.lesson_id,
            "alert_ids": list(self.alert_ids),
            "reason": self.reason,
            "detail": dict(self.detail),
        }


# ── provenance + small helpers ────────────────────────────────────────────────

def provenance_of(sender: SfpSender) -> str:
    """The immutable peer provenance string ``peer:<agent>@<team>`` (``peer:<agent>``
    when the team is unknown). Human-readable; the stable machine key is the
    instance_id, stored alongside it."""

    if sender.team:
        return f"peer:{sender.agent}@{sender.team}"
    return f"peer:{sender.agent}"


def _sender_dict(sender: SfpSender) -> dict[str, Any]:
    return {"agent": sender.agent, "instance_id": sender.instance_id, "team": sender.team}


def _scalar_prob(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _is_peer_stub(question: Any) -> bool:
    meta = getattr(question, "metadata", None) or {}
    return bool(meta.get("collab_peer_stub")) or str(meta.get("origin") or "").startswith("peer:")


def _criteria_hash(text: str) -> str:
    from forecasting.collab.cards import criteria_hash

    return criteria_hash(text or "")


# ── question resolution (criteria-hash first; title only to WARN) ─────────────

def find_local_question_by_criteria_hash(ledger: Any, target_hash: str) -> Optional[Any]:
    """The FIRST non-peer local question whose resolution-criteria hash matches
    *target_hash* — the honest identity key (never title fuzzy-match alone)."""

    if not target_hash:
        return None
    for question in ledger.list_questions():
        if _is_peer_stub(question):
            continue
        if _criteria_hash(question.resolution_criteria) == target_hash:
            return question
    return None


def find_local_question_by_title(ledger: Any, title: str) -> Optional[Any]:
    """The FIRST non-peer local question with the same (case-insensitive) title —
    used ONLY to raise the criteria-divergence warning, never to merge onto."""

    needle = (title or "").strip().lower()
    if not needle:
        return None
    for question in ledger.list_questions():
        if _is_peer_stub(question):
            continue
        if question.title.strip().lower() == needle:
            return question
    return None


# ── the peer-origin stub (the world-view link's peer endpoint) ────────────────

def _find_peer_stub(ledger: Any, instance_id: str, criteria_hash: str) -> Optional[Any]:
    for question in ledger.list_questions(status="archived"):
        meta = getattr(question, "metadata", None) or {}
        if meta.get("collab_peer_stub") and meta.get("peer_instance_id") == instance_id \
                and meta.get("peer_criteria_hash") == criteria_hash:
            return question
    return None


def _deactivate_peer_stub(ledger: Any, question_id: str) -> None:
    """Make a peer stub INERT: archived (off the operator's active desk lenses) and
    review-disabled (never auto-reforecast). Both are UPDATEs — NOT the gated
    INSERT path — so no commit context is needed."""

    with ledger._connect() as conn:
        conn.execute("UPDATE forecast_questions SET status = 'archived' WHERE id = ?", (question_id,))
        conn.execute(
            "UPDATE scheduled_reviews SET enabled = 0 WHERE scope_type = 'question' AND scope_ref = ?",
            (question_id,),
        )


def _write_stub_metadata(ledger: Any, question_id: str, metadata: dict[str, Any]) -> None:
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE forecast_questions SET metadata = ? WHERE id = ?",
            (json.dumps(metadata, sort_keys=True), question_id),
        )


def resolve_or_create_peer_stub(ledger: Any, body: Any, sender: SfpSender, provenance: str) -> Any:
    """Resolve (idempotent on instance_id + criteria_hash) or create the peer-origin
    stub that anchors this peer's world-view. Created archived + review-disabled and
    NEVER given a snapshot — it exists only to carry the peer's number in metadata
    and to be the peer endpoint of the world-view forecast_link."""

    existing = _find_peer_stub(ledger, sender.instance_id, body.criteria_hash)
    if existing is not None:
        return existing

    from forecasting.ledger import allow_ledger_writes
    from forecasting.models import ValidationError

    base_meta = {
        "collab_peer_stub": True,
        "origin": provenance,
        "peer_instance_id": sender.instance_id,
        "peer_criteria_hash": body.criteria_hash,
        "peer_agent": sender.agent,
        "peer_team": sender.team,
    }
    criteria = (
        f"Peer-origin shadow of {sender.agent}'s forecast; resolves exactly as the "
        f"originating desk resolves its own question by its held criteria "
        f"(identity hash {body.criteria_hash[:16]})."
    )
    titles = [body.question_title, f"[peer] {body.question_title}", f"[peer:{sender.agent}] shadow question"]
    with allow_ledger_writes(reason="collab_import_peer_stub"):
        stub = None
        for title in titles:
            try:
                stub = ledger.create_question(
                    title=title,
                    resolution_criteria=criteria,
                    domain="collab_peer",
                    tags=["peer", "collab"],
                    metadata=dict(base_meta),
                )
                break
            except ValidationError:
                continue
        if stub is None:  # pragma: no cover — the last title is always scoreable
            raise ValidationError("could not create a scoreable peer stub question")
    _deactivate_peer_stub(ledger, stub.id)
    return ledger.get_question(stub.id)


# ── forecast.card ─────────────────────────────────────────────────────────────

def import_forecast_card(ledger: Any, envelope: Any, body: Any, *, home=None, now=None) -> ImportResult:
    sender: SfpSender = envelope.sender
    provenance = provenance_of(sender)
    now = now or _now_iso()
    alert_ids: list[str] = []

    local = find_local_question_by_criteria_hash(ledger, body.criteria_hash)

    # A same-title question with DIFFERENT criteria is the classic group failure —
    # surface it, and DO NOT merge onto it (import as a peer stub instead).
    if local is None:
        title_match = find_local_question_by_title(ledger, body.question_title)
        if title_match is not None:
            reason = (
                f"{_CRITERIA_DIVERGENCE_ALERT_PREFIX}: {provenance} shares "
                f"{body.question_title!r} with DIFFERENT resolution criteria"
            )
            action = (
                "Two desks appear to be 'on the same question' with different "
                "resolution criteria — reconcile the criteria before treating the "
                "peer number as comparable. Imported as a peer-origin stub, NOT "
                f"merged onto your question {title_match.id}."
            )
            try:
                alert_ids.append(
                    ledger.create_alert(
                        severity="warning", scope_type="question", scope_ref=title_match.id,
                        reason=reason, recommended_action=action,
                    ).id
                )
            except Exception:  # noqa: BLE001 — a surfacing hiccup never blocks the import
                logger.warning("could not raise criteria-divergence alert", exc_info=True)

    stub = resolve_or_create_peer_stub(ledger, body, sender, provenance)

    peer_forecast = {
        "origin": provenance,
        "agent": sender.agent,
        "instance_id": sender.instance_id,
        "team": sender.team,
        "criteria_hash": body.criteria_hash,
        "outcome_type": body.outcome_type,
        "probability": body.probability,
        "distribution": body.distribution,
        "band": body.band.model_dump(mode="json") if getattr(body, "band", None) else None,
        "as_of": body.as_of,
        "horizon_days": body.horizon_days,
        "rationale_bullets": list(body.rationale_bullets or []),
        "evidence_refs": [r.model_dump(mode="json") for r in (body.evidence_refs or [])],
        # THE honesty law: a peer's number is never the receiver's scoreable forecast.
        "calibration_eligible": False,
        "linked_question_id": local.id if local is not None else None,
        "imported_at": now,
    }

    # Pin the latest peer number onto the stub metadata (the canonical store; NEVER
    # a snapshot, so scoring can never see it).
    stub_meta = dict(getattr(stub, "metadata", None) or {})
    stub_meta.update(
        {
            "collab_peer_stub": True,
            "origin": provenance,
            "peer_instance_id": sender.instance_id,
            "peer_criteria_hash": body.criteria_hash,
            "peer_agent": sender.agent,
            "peer_team": sender.team,
            "peer_forecast": peer_forecast,
        }
    )
    _write_stub_metadata(ledger, stub.id, stub_meta)

    link_id: Optional[str] = None
    if local is not None:
        # The WORLD-VIEW link (flag-don't-merge): the peer number rides the link's
        # metadata, weight 0 (no numeric pull), calibration_eligible false.
        try:
            link = ledger.add_forecast_link(
                stub.id, local.id, link_type=_PEER_LINK_TYPE, weight=0.0,
                rationale=f"peer world-view from {provenance}", created_by=provenance,
                metadata={"kind": "peer_world_view", "calibration_eligible": False, "peer_forecast": peer_forecast},
            )
            link_id = link["id"]
        except Exception:  # noqa: BLE001 — a link hiccup never loses the import
            logger.warning("could not add peer world-view link", exc_info=True)

        # >10pp divergence vs the local current → operator alert.
        try:
            local_snapshot = ledger.get_current_snapshot(local.id)
        except Exception:  # noqa: BLE001
            local_snapshot = None
        local_p = _scalar_prob(getattr(local_snapshot, "probability_or_distribution", None)) if local_snapshot else None
        peer_p = _scalar_prob(body.probability)
        if local_p is not None and peer_p is not None and abs(local_p - peer_p) > DIVERGENCE_THRESHOLD:
            gap = abs(peer_p - local_p) * 100
            reason = (
                f"{_DIVERGENCE_ALERT_PREFIX}: {sender.agent} @ {peer_p * 100:.0f}% "
                f"vs you @ {local_p * 100:.0f}%"
            )
            action = (
                f"Peer {provenance} diverges {gap:.0f}pp from your current forecast on "
                f"{local.title!r}. Review the peer world-view (link {link_id}); it is "
                "advisory (calibration_eligible=false) and is never averaged into yours."
            )
            try:
                alert_ids.append(
                    ledger.create_alert(
                        severity="warning", scope_type="question", scope_ref=local.id,
                        reason=reason, recommended_action=action,
                    ).id
                )
            except Exception:  # noqa: BLE001
                logger.warning("could not raise divergence alert", exc_info=True)

    return ImportResult(
        kind=KIND_FORECAST_CARD, outcome="imported", provenance=provenance,
        sender=_sender_dict(sender), question_id=local.id if local is not None else None,
        peer_question_id=stub.id, link_id=link_id, alert_ids=alert_ids,
        detail={"criteria_hash": body.criteria_hash, "linked": local is not None},
    )


# ── evidence.share ────────────────────────────────────────────────────────────

def import_evidence_share(
    ledger: Any, envelope: Any, body: Any, *, question_id: Optional[str], home=None, now=None,
) -> ImportResult:
    sender: SfpSender = envelope.sender
    provenance = provenance_of(sender)
    now = now or _now_iso()

    # sha256 verify against the payload (a mismatch is a provenance/leak concern ⚠️).
    computed = sha256_hex(body.excerpt or "")
    if computed != body.sha256:
        return ImportResult(
            kind=KIND_EVIDENCE_SHARE, outcome="error", provenance=provenance,
            sender=_sender_dict(sender),
            reason=f"sha256 mismatch (payload {body.sha256[:12]} vs computed {computed[:12]}) — provenance/leak concern",
        )

    if not question_id:
        return ImportResult(
            kind=KIND_EVIDENCE_SHARE, outcome="skipped", provenance=provenance,
            sender=_sender_dict(sender),
            reason="evidence.share needs a question context (share it in a question thread)",
        )

    from forecasting.models import ValidationError

    metadata = {
        "origin": provenance,
        "collab_peer_evidence": True,
        "peer": _sender_dict(sender),
        "shared_sha256": body.sha256,
        "shared_captured_at": body.captured_at,
        "triage_label": body.triage_label,
        "imported_at": now,
    }
    try:
        item = ledger.add_evidence(
            question_id=question_id,
            source_or_note=body.source_url or body.source_name or (body.excerpt or body.claim or "peer evidence"),
            claim=body.claim or "",
            summary=body.excerpt or "",
            source_url=body.source_url,
            source_name=body.source_name,
            source_type=body.source_type,
            published_at=body.published_at,
            # availability window keeps the PEER's timeline (never arrival time) so a
            # backtest can't be tricked into seeing it early.
            available_at=body.available_at or body.published_at or body.captured_at,
            stance=body.stance or "context",
            metadata=metadata,
            archive_url_snapshot=False,  # peer already vetted it; no network on import
        )
    except (ValidationError, Exception) as exc:  # noqa: BLE001 — a bad payload is data, not a crash
        return ImportResult(
            kind=KIND_EVIDENCE_SHARE, outcome="error", provenance=provenance,
            sender=_sender_dict(sender), reason=f"could not import evidence: {exc}",
        )

    # add_evidence stamps captured_at = arrival time; PIN it back to the peer's
    # original (the no-fabricated-freshness law). captured_at is not a gated column.
    _pin_captured_at(ledger, item.id, body.captured_at)

    return ImportResult(
        kind=KIND_EVIDENCE_SHARE, outcome="imported", provenance=provenance,
        sender=_sender_dict(sender), question_id=question_id, evidence_id=item.id,
        detail={"captured_at": body.captured_at, "sha256": body.sha256},
    )


def _pin_captured_at(ledger: Any, evidence_id: str, captured_at: str) -> None:
    from forecasting.models import parse_timestamp

    stamped = parse_timestamp(captured_at, field_name="captured_at") or captured_at
    with ledger._connect() as conn:
        conn.execute("UPDATE evidence_items SET captured_at = ? WHERE id = ?", (stamped, evidence_id))


# ── lesson.share ──────────────────────────────────────────────────────────────

_VALID_LESSON_SCOPES = {"domain", "topic", "domain_topic", "horizon", "question_type", "model_component", "global"}


def import_lesson_share(ledger: Any, envelope: Any, body: Any, *, home=None, now=None) -> ImportResult:
    sender: SfpSender = envelope.sender
    provenance = provenance_of(sender)
    now = now or _now_iso()

    scope_type = body.scope_type if body.scope_type in _VALID_LESSON_SCOPES else "global"
    scope_ref = body.scope_ref
    if scope_type == "global":
        scope_ref = None
    elif scope_type == "domain_topic" and (not scope_ref or ":" not in scope_ref):
        scope_type, scope_ref = "global", None  # can't satisfy the colon rule → global
    elif scope_type != "global" and not scope_ref:
        scope_type, scope_ref = "global", None  # a scoped lesson with no ref → global

    metadata = {
        "origin": provenance,
        "collab_peer_lesson": True,
        "peer": _sender_dict(sender),
        "origin_status": body.status,
        "origin_n": body.origin_n,
        "effect_size": body.effect_size,
        "compiled_rule_preview": body.compiled_rule_preview,
        "imported_at": now,
    }
    try:
        # recommended_adjustment is DELIBERATELY None: a peer lesson must NEVER
        # auto-compile to an enforced rule (the auto-compile hook only fires on a
        # dict adjustment). status='tentative' → surfaces in the lesson-review /
        # triage queue, excluded from the active (enforced) set.
        lesson = ledger.create_calibration_lesson(
            scope_type=scope_type, scope_ref=scope_ref, lesson=body.lesson,
            confidence=body.confidence, recommended_adjustment=None,
            status="tentative", metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001 — a bad payload is data, not a crash
        return ImportResult(
            kind=KIND_LESSON_SHARE, outcome="error", provenance=provenance,
            sender=_sender_dict(sender), reason=f"could not import lesson: {exc}",
        )

    return ImportResult(
        kind=KIND_LESSON_SHARE, outcome="imported", provenance=provenance,
        sender=_sender_dict(sender), lesson_id=lesson["id"],
        detail={"status": "tentative", "auto_compiled": False},
    )


# ── the policy-gated entry point ──────────────────────────────────────────────

def accept_envelope(
    ledger: Any,
    envelope: Any,
    *,
    home: Optional[Path | str] = None,
    cfg: Any = None,
    allowlist: Any = None,
    question_id: Optional[str] = None,
    now: Optional[str] = None,
) -> ImportResult:
    """Accept a peer envelope: authorise (allowlist) → resolve the accept decision
    → dispatch to the honest importer → log the whole thing to the collab trail.

    Never raises for a normal outcome (refusal / pending / bad payload are DATA).
    Any unexpected error is caught, logged to the trail, and returned as an
    ``error`` result — the platform adapter is never crashed."""

    from forecasting.collab import directory
    from forecasting.jobs.policy import (
        CollabPolicyRefused,
        Decision,
        ShareDirection,
        resolve_collab_action,
        share_class_for_kind,
    )

    now = now or _now_iso()
    sender: SfpSender = envelope.sender
    provenance = provenance_of(sender)
    kind = envelope.kind

    # Any received sfp message updates the directory (server-less discovery).
    try:
        directory.record_agent(sender, team=sender.team, home=home, now=now)
    except Exception:  # noqa: BLE001
        logger.warning("could not record peer in directory", exc_info=True)

    # Overflow bodies (>8 KB) rode a file upload; M3 imports the inline form only.
    if is_file_pointer(envelope.body):
        result = ImportResult(
            kind=kind, outcome="skipped", provenance=provenance, sender=_sender_dict(sender),
            reason="body overflowed to a file upload; inline-only import in M3",
        )
        append_collab_event({"event": "collab.skipped", **_event_fields(result)}, home)
        return result

    share_class = share_class_for_kind(kind)

    decision: Optional[Decision] = None
    if share_class is not None:
        allow = allowlist if allowlist is not None else directory.allowed_instances(cfg)
        try:
            decision = resolve_collab_action(
                ShareDirection.ACCEPT, share_class,
                counterparty_instance_id=sender.instance_id, allowlist=allow,
            )
        except CollabPolicyRefused as exc:
            result = ImportResult(
                kind=kind, outcome="refused", decision="refused", provenance=provenance,
                sender=_sender_dict(sender), reason=str(exc),
            )
            append_collab_event({"event": "collab.refused", **_event_fields(result)}, home)
            return result
        if decision == Decision.NEVER:
            result = ImportResult(
                kind=kind, outcome="refused", decision="never", provenance=provenance,
                sender=_sender_dict(sender),
                reason=f"accept.{share_class.value} = never; nothing imported",
            )
            append_collab_event({"event": "collab.refused", **_event_fields(result)}, home)
            return result
        if decision == Decision.ASK:
            result = ImportResult(
                kind=kind, outcome="pending_approval", decision="ask", provenance=provenance,
                sender=_sender_dict(sender),
                reason=f"accept.{share_class.value} = ask; import pending operator approval",
            )
            append_collab_event({"event": "collab.pending", **_event_fields(result)}, home)
            return result

    try:
        body = parse_body(envelope)
        if kind == KIND_FORECAST_CARD:
            result = import_forecast_card(ledger, envelope, body, home=home, now=now)
        elif kind == KIND_EVIDENCE_SHARE:
            result = import_evidence_share(ledger, envelope, body, question_id=question_id, home=home, now=now)
        elif kind == KIND_LESSON_SHARE:
            result = import_lesson_share(ledger, envelope, body, home=home, now=now)
        else:
            result = ImportResult(
                kind=kind, outcome="skipped", provenance=provenance, sender=_sender_dict(sender),
                reason=f"{kind} is not an import kind (handled by the router)",
            )
    except Exception as exc:  # noqa: BLE001 — fail-open: log + return, never crash the adapter
        logger.warning("collab import failed for kind %s", kind, exc_info=True)
        result = ImportResult(
            kind=kind, outcome="error", provenance=provenance, sender=_sender_dict(sender),
            reason=f"import error: {exc}",
        )

    if decision is not None and result.decision is None:
        result.decision = decision.value
    event_name = "collab.import" if result.outcome == "imported" else f"collab.{result.outcome}"
    append_collab_event({"event": event_name, **_event_fields(result)}, home)
    return result


def _event_fields(result: ImportResult) -> dict[str, Any]:
    return {
        "kind": result.kind,
        "outcome": result.outcome,
        "decision": result.decision,
        "provenance": result.provenance,
        "sender": result.sender,
        "question_id": result.question_id,
        "peer_question_id": result.peer_question_id,
        "link_id": result.link_id,
        "evidence_id": result.evidence_id,
        "lesson_id": result.lesson_id,
        "alert_ids": list(result.alert_ids),
        "reason": result.reason,
    }


__all__ = [
    "DIVERGENCE_THRESHOLD",
    "ImportResult",
    "provenance_of",
    "collab_events_path",
    "append_collab_event",
    "list_collab_events",
    "find_local_question_by_criteria_hash",
    "find_local_question_by_title",
    "resolve_or_create_peer_stub",
    "import_forecast_card",
    "import_evidence_share",
    "import_lesson_share",
    "accept_envelope",
]
