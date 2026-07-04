"""Auto-resolution DETECTION — surface "this question is ready to resolve, and
here is the proposed outcome" so the learning loop stops starving on operator-
initiated resolutions.

WHY THIS EXISTS
---------------
The calibration learning loop's throughput is capped by *resolutions*: no
resolution → no score → no lesson. Today an outcome only gets recorded when the
operator hand-runs ``forecast resolve``. This module closes that gap WITHOUT ever
auto-committing an outcome: it DETECTS resolvable questions, writes a PROPOSAL
(an ``alert_events`` row with the canonical ``resolution proposed:`` reason), and
lets the operator confirm with one key — which routes through the EXISTING
``forecast resolve`` flow that auto-scores + synthesizes the lesson. Guide and
make visible; never auto-resolve.

TWO DETECTION TIERS
-------------------
1. DETERMINISTIC (always on, no LLM, no fabrication). Keyed on hard facts:
   * PRIMARY trigger — the question is PAST DUE (``resolution_time <= now``).
     This is what makes a question a *candidate*; being past due alone never
     yields an outcome (we never fabricate yes/no from a clock).
   * The outcome, when we propose one, comes from a real TERMINAL SIGNAL:
     - a STRUCTURED market ref (``metadata.market_id`` = ``"<venue>:<id>"`` +
       ``metadata.market_source``) read through an injected market-outcome
       reader (a closed/settled market reports its terminal YES/NO); OR
     - a terminal signal already ingested into a watched-source snapshot
       (an explicit ``resolved``/``outcome`` field, or a saturated price).
   * ``resolution_source`` is treated as a *bonus* confirmation signal when
     present — NEVER the key (in the live ledger only ~8% of past-due questions
     carry one, while ~91% carry a structured ``market_id``).
   A past-due question with no readable terminal signal is reported as an honest
   NON-proposal (``unclear``) — it is NOT proposed, and the existing
   ``resolution_check_due`` alert already nudges the operator on it.

2. LLM-ASSISTED (OPT-IN, paid). Given the resolution criteria + the freshest
   watched-source payloads, a small injected classifier returns one of
   {resolved_yes, resolved_no, resolved_value, not_yet, unclear} with a cited
   rationale. Mirrors the paid-tier convention elsewhere in the desk: the
   classifier is INJECTED (``None`` in the cron/deterministic path) and only runs
   when a caller explicitly opts in, so an unattended loop never spends on it.

HONEST LIMITS
-------------
* We never write a resolution. We write a PROPOSAL alert. The operator confirms.
* The deterministic tier can only propose an OUTCOME when a terminal signal is
  readable. Venues with no public reader (e.g. ``infer``) and pure numeric/
  distribution questions resolved off an external series (e.g. a FRED/BLS
  ``resolution_source``) are honestly reported as undetermined by tier 1 — they
  are the LLM tier's or the operator's job.
* The injected market reader does live I/O; it is best-effort. A failed/None read
  is treated as "not yet readable", never as an outcome.
* Proposals reuse the SAME ``resolution proposed:`` alert reason as the
  metric-threshold resolver so the two paths dedupe against each other (outcome-
  aware) and surface/reconcile identically — a question never gets two competing
  proposal alerts for the same outcome.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Mapping

from forecasting.models import (
    parse_timestamp,
    timestamp_to_datetime,
    utc_now_iso,
)

# ── labels the classifier / detector may emit ───────────────────────────────────
LABEL_YES = "resolved_yes"
LABEL_NO = "resolved_no"
LABEL_VALUE = "resolved_value"
LABEL_NOT_YET = "not_yet"
LABEL_UNCLEAR = "unclear"
DETECTION_LABELS = frozenset({LABEL_YES, LABEL_NO, LABEL_VALUE, LABEL_NOT_YET, LABEL_UNCLEAR})
# The labels that carry a determinable outcome (a proposal is only raised for these).
_DETERMINABLE_LABELS = frozenset({LABEL_YES, LABEL_NO, LABEL_VALUE})

# ── which fact fired the detection (carried in the proposal for auditability) ───
TRIGGER_PAST_DUE = "past_due"                        # resolution_time <= now (candidacy)
TRIGGER_MARKET_TERMINAL = "market_terminal_print"    # a settled market reported its outcome
TRIGGER_INGESTED_VALUE = "ingested_source_value"     # a watched-source snapshot carried a terminal field
TRIGGER_RESOLUTION_SOURCE = "resolution_source"      # bonus: a resolution_source was present
TRIGGER_LLM = "llm_classified"                       # tier-2 classifier

TIER_DETERMINISTIC = "deterministic"
TIER_LLM = "llm"

# A market price is a TERMINAL print (settled) only when it has saturated to a
# bound. Deliberately conservative: mid-book prices are NEVER read as an outcome.
TERMINAL_LOW = 0.05
TERMINAL_HIGH = 0.95

# Candidacy window: consider active questions whose resolution_time is at/behind
# now, or within this many days AHEAD of now (so the desk can pre-stage a proposal
# just before a known resolution instant). Past-due is unbounded on the past side
# — a question due months ago is still a live target until it is resolved.
DEFAULT_HORIZON_DAYS = 3


@dataclass(frozen=True)
class TerminalOutcome:
    """A market's TERMINAL (settled) reading as returned by an injected reader.

    ``resolved`` is True only when the venue reports the market as settled. A
    reader returns ``None`` (not this object) when the market is unreadable or
    still open — so a caller never mistakes "couldn't read" for an outcome.
    """

    resolved: bool
    outcome: str | None            # "yes" / "no" / a value string when known
    probability: float | None      # terminal YES probability when known
    venue: str | None
    market_ref: str | None
    detail: str


@dataclass(frozen=True)
class ResolutionDetection:
    """The result of running detection on ONE question. A PROPOSAL is raised only
    when :meth:`determinable` — every other case is an honest non-proposal that
    records WHY nothing was proposed."""

    question_id: str
    tier: str
    trigger: str
    label: str
    outcome: str | None
    confidence: float
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    source_ref: str | None = None
    market_id: str | None = None

    def determinable(self) -> bool:
        return self.label in _DETERMINABLE_LABELS and self.outcome is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "tier": self.tier,
            "trigger": self.trigger,
            "label": self.label,
            "outcome": self.outcome,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "evidence_refs": list(self.evidence_refs),
            "source_ref": self.source_ref,
            "market_id": self.market_id,
            "determinable": self.determinable(),
        }


# A reader: (market_id, market_source) -> a TerminalOutcome when the market has
# settled, else None. Injected so the pure logic is testable and cron/ledger never
# import the network adapters directly.
MarketOutcomeReader = Callable[[str, "str | None"], "TerminalOutcome | None"]
# A classifier: (question, payloads, runner, model) -> {label, outcome, confidence, rationale}.
ResolutionClassifier = Callable[..., dict]


# ── pure helpers (no ledger, exhaustively testable) ─────────────────────────────
def _finite(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _outcome_space_type(question: Any) -> str:
    space = getattr(question, "outcome_space", None)
    return str(getattr(space, "type", "") or "").lower()


def market_ref_of(question: Any) -> tuple[str | None, str | None]:
    """Structured market reference for a question, preferred over any criteria-text
    match: ``(metadata.market_id, metadata.market_source)``. Returns ``(None, None)``
    when the question carries no structured market ref."""
    meta = getattr(question, "metadata", None)
    if not isinstance(meta, dict):
        return None, None
    market_id = meta.get("market_id")
    source = meta.get("market_source")
    return (
        str(market_id) if isinstance(market_id, str) and market_id.strip() else None,
        str(source) if isinstance(source, str) and source.strip() else None,
    )


def _label_outcome_from_probability(prob: float, outcome_type: str) -> tuple[str, str] | None:
    """Map a saturated terminal probability to a (label, outcome). Only binary
    questions map from a probability; a mid-book value returns None (never
    fabricated)."""
    if outcome_type not in ("binary", ""):
        return None
    if prob >= TERMINAL_HIGH:
        return LABEL_YES, "yes"
    if prob <= TERMINAL_LOW:
        return LABEL_NO, "no"
    return None


def _normalize_binary_outcome(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in ("yes", "y", "true", "1", "1.0"):
        return "yes"
    if text in ("no", "n", "false", "0", "0.0"):
        return "no"
    return None


def extract_terminal_signal(
    parsed_values: Mapping[str, Any], *, outcome_type: str = ""
) -> tuple[str, str, float, str] | None:
    """Pull a TERMINAL signal out of an ingested watched-source snapshot's
    ``parsed_values`` — returns ``(label, outcome, confidence, detail)`` or None.

    Read order (most explicit first): an explicit ``resolved``/``settled`` flag
    paired with an ``outcome``/``result``; a bare ``outcome``/``result``/``winner``
    string; a saturated market ``probability``/``price``. Never fabricates: an
    ambiguous / mid-book / non-finite value yields None.
    """
    if not isinstance(parsed_values, Mapping):
        return None
    resolved_flag = parsed_values.get("resolved")
    if resolved_flag is None:
        resolved_flag = parsed_values.get("settled")
    if resolved_flag is None:
        resolved_flag = parsed_values.get("is_resolved")

    # explicit outcome/result/winner string
    for key in ("outcome", "result", "resolution", "winner"):
        raw = parsed_values.get(key)
        if raw is None:
            continue
        binary = _normalize_binary_outcome(raw)
        if binary is not None:
            label = LABEL_YES if binary == "yes" else LABEL_NO
            conf = 0.98 if resolved_flag else 0.85
            return label, binary, conf, f"{key}={raw!r} in ingested snapshot"
        # a non-binary explicit value → resolved_value (numeric/categorical)
        if bool(resolved_flag) and str(raw).strip():
            return LABEL_VALUE, str(raw).strip(), 0.9, f"{key}={raw!r} in ingested snapshot"

    # saturated probability / price (binary only)
    for key in ("probability", "prob_yes", "yes_probability", "price", "last", "implied_probability"):
        prob = _finite(parsed_values.get(key))
        if prob is None:
            continue
        mapped = _label_outcome_from_probability(prob, outcome_type)
        if mapped is not None:
            label, outcome = mapped
            conf = 0.95 if resolved_flag else 0.8
            return label, outcome, conf, f"{key}={prob:.4f} saturated to a terminal bound"
    return None


def detection_from_terminal(
    question_id: str,
    market_id: str | None,
    terminal: TerminalOutcome,
    *,
    outcome_type: str,
    trigger: str = TRIGGER_MARKET_TERMINAL,
) -> ResolutionDetection | None:
    """Build a DETERMINABLE detection from a settled market's terminal reading, or
    None when the reading is present but not cleanly determinable (e.g. the market
    is 'resolved' but the reader gave no clean outcome for a binary question)."""
    if not terminal.resolved:
        return None
    label: str | None = None
    outcome: str | None = None
    binary = _normalize_binary_outcome(terminal.outcome)
    if binary is not None:
        label = LABEL_YES if binary == "yes" else LABEL_NO
        outcome = binary
    elif terminal.outcome is not None and outcome_type not in ("binary", ""):
        label, outcome = LABEL_VALUE, str(terminal.outcome).strip()
    elif terminal.probability is not None:
        mapped = _label_outcome_from_probability(terminal.probability, outcome_type)
        if mapped is not None:
            label, outcome = mapped
    if label is None or not outcome:
        return None
    prob_txt = f" (terminal p={terminal.probability:.3f})" if terminal.probability is not None else ""
    venue = terminal.venue or "market"
    return ResolutionDetection(
        question_id=question_id,
        tier=TIER_DETERMINISTIC,
        trigger=trigger,
        label=label,
        outcome=outcome,
        confidence=0.97,
        rationale=(
            f"[{venue}] settled market {market_id or terminal.market_ref} reports "
            f"{outcome.upper()}{prob_txt} — {terminal.detail}"
        ),
        evidence_refs=(terminal.market_ref,) if terminal.market_ref else (),
        source_ref=terminal.market_ref,
        market_id=market_id,
    )


# ── ledger glue ─────────────────────────────────────────────────────────────────
def _now_dt(now: str | None):
    return timestamp_to_datetime(parse_timestamp(now, field_name="now") or utc_now_iso())


def resolution_time_passed(question: Any, now_dt) -> bool:
    raw = getattr(question, "resolution_time", None)
    if not raw:
        return False
    dt = timestamp_to_datetime(raw)
    return dt is not None and now_dt is not None and dt <= now_dt


def is_candidate(question: Any, now_dt, horizon_days: int) -> bool:
    """A question is a detection candidate when it is active and its resolution
    instant is at/behind now OR within ``horizon_days`` ahead (so the sweep is
    bounded on the future side while catching every past-due question)."""
    if getattr(question, "status", None) != "active":
        return False
    raw = getattr(question, "resolution_time", None)
    if not raw:
        return False
    dt = timestamp_to_datetime(raw)
    if dt is None or now_dt is None:
        return False
    return dt <= now_dt + timedelta(days=max(0, horizon_days))


def latest_parsed_values(ledger: Any, question_id: str) -> tuple[dict[str, Any], str | None]:
    """Freshest ingested source snapshot's parsed_values + its snapshot id, or
    ``({}, None)`` when nothing has been ingested."""
    try:
        snaps = ledger.list_source_snapshots(question_id=question_id, limit=1)
    except Exception:
        return {}, None
    if not snaps:
        return {}, None
    parsed = snaps[0].get("parsed_values")
    return (parsed if isinstance(parsed, dict) else {}), snaps[0].get("id")


def detect_deterministic(
    ledger: Any,
    question: Any,
    *,
    now_dt,
    market_reader: MarketOutcomeReader | None = None,
) -> ResolutionDetection:
    """Tier-1 detection over hard facts. Returns a DETERMINABLE detection when a
    terminal signal is readable, else an honest ``not_yet`` (not past due) /
    ``unclear`` (past due, no terminal signal)."""
    qid = question.id
    market_id, market_source = market_ref_of(question)
    past_due = resolution_time_passed(question, now_dt)

    if not past_due:
        return ResolutionDetection(
            question_id=qid, tier=TIER_DETERMINISTIC, trigger=TRIGGER_PAST_DUE,
            label=LABEL_NOT_YET, outcome=None, confidence=0.0,
            rationale="resolution_time has not passed yet — watching, not resolving",
            market_id=market_id,
        )

    outcome_type = _outcome_space_type(question)

    # (a) STRUCTURED market ref → injected reader → terminal outcome (primary path).
    if market_id and market_reader is not None:
        try:
            terminal = market_reader(market_id, market_source)
        except Exception:
            terminal = None
        if terminal is not None:
            detection = detection_from_terminal(qid, market_id, terminal, outcome_type=outcome_type)
            if detection is not None:
                return detection

    # (b) A terminal signal already ingested into the freshest watched snapshot.
    parsed, snap_ref = latest_parsed_values(ledger, qid)
    signal = extract_terminal_signal(parsed, outcome_type=outcome_type)
    if signal is not None:
        label, outcome, conf, detail = signal
        return ResolutionDetection(
            question_id=qid, tier=TIER_DETERMINISTIC, trigger=TRIGGER_INGESTED_VALUE,
            label=label, outcome=outcome, confidence=conf,
            rationale=f"ingested terminal signal: {detail}",
            evidence_refs=(snap_ref,) if snap_ref else (),
            source_ref=snap_ref, market_id=market_id,
        )

    # Past due but no readable terminal signal → honest non-proposal. Note the
    # bonus resolution_source signal in the reason when present (never a key).
    bonus = ""
    src = getattr(question, "resolution_source", None)
    if isinstance(src, str) and src.strip():
        bonus = f" resolution_source present ({src.strip()[:60]}) but not machine-readable here."
    reason = "past due but no readable terminal signal"
    if market_id and market_reader is None:
        reason += " (no market reader wired)"
    elif market_id:
        reason += f" (market {market_id} not settled/readable)"
    return ResolutionDetection(
        question_id=qid, tier=TIER_DETERMINISTIC, trigger=TRIGGER_PAST_DUE,
        label=LABEL_UNCLEAR, outcome=None, confidence=0.0,
        rationale=reason + bonus, market_id=market_id,
    )


def detect_llm(
    ledger: Any,
    question: Any,
    *,
    classifier: ResolutionClassifier,
    runner: Any,
    model: str,
) -> ResolutionDetection:
    """Tier-2 OPT-IN classification. The classifier is injected + only reached when
    a caller wired it (never in the deterministic/cron path). A garbled response
    degrades to an ``unclear`` non-proposal — it never fabricates a resolution."""
    qid = question.id
    parsed, snap_ref = latest_parsed_values(ledger, qid)
    payloads: list[dict[str, Any]] = []
    if parsed:
        payloads.append({"kind": "watched_snapshot", "ref": snap_ref, "parsed_values": parsed})
    try:
        for item in ledger.list_evidence(qid)[:8]:
            payloads.append({
                "kind": "evidence",
                "ref": getattr(item, "id", None),
                "summary": getattr(item, "summary", None) or getattr(item, "title", None),
            })
    except Exception:
        pass
    try:
        verdict = classifier(question, payloads, runner=runner, model=model)
    except Exception as exc:  # a hung/failed model must not fabricate an outcome
        return ResolutionDetection(
            question_id=qid, tier=TIER_LLM, trigger=TRIGGER_LLM,
            label=LABEL_UNCLEAR, outcome=None, confidence=0.0,
            rationale=f"llm classifier failed: {exc}",
        )
    label = str((verdict or {}).get("label") or LABEL_UNCLEAR).strip().lower()
    if label not in DETECTION_LABELS:
        label = LABEL_UNCLEAR
    outcome = verdict.get("outcome") if isinstance(verdict, dict) else None
    if label in (LABEL_YES, LABEL_NO):
        outcome = "yes" if label == LABEL_YES else "no"
    conf = _finite((verdict or {}).get("confidence")) or (0.7 if label in _DETERMINABLE_LABELS else 0.0)
    refs = tuple(str(r) for r in (verdict.get("evidence_refs") or []) if r) if isinstance(verdict, dict) else ()
    return ResolutionDetection(
        question_id=qid, tier=TIER_LLM, trigger=TRIGGER_LLM,
        label=label, outcome=(str(outcome) if outcome is not None else None),
        confidence=float(conf),
        rationale=str((verdict or {}).get("rationale") or "llm classification"),
        evidence_refs=refs or ((snap_ref,) if snap_ref else ()),
        source_ref=snap_ref,
    )


def detect_resolution(
    ledger: Any,
    question: Any,
    *,
    now_dt,
    market_reader: MarketOutcomeReader | None = None,
    classifier: ResolutionClassifier | None = None,
    runner: Any = None,
    model: str = "",
) -> ResolutionDetection:
    """Run tier-1; escalate to tier-2 ONLY when the deterministic tier could not
    determine an outcome AND a classifier is wired (opt-in)."""
    deterministic = detect_deterministic(ledger, question, now_dt=now_dt, market_reader=market_reader)
    if deterministic.determinable():
        return deterministic
    if classifier is not None and deterministic.label != LABEL_NOT_YET:
        # Only spend the model on past-due questions the deterministic tier left
        # unclear — never on not-yet-due ones.
        return detect_llm(ledger, question, classifier=classifier, runner=runner, model=model)
    return deterministic


def propose_detected_resolutions(
    ledger: Any,
    *,
    now: str | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    market_reader: MarketOutcomeReader | None = None,
    classifier: ResolutionClassifier | None = None,
    runner: Any = None,
    model: str = "",
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sweep candidate questions, run detection, and raise a deduped confirm-me
    PROPOSAL alert for each DETERMINABLE detection. Propose-only — never resolves.

    Reuses the canonical ``resolution proposed:`` alert reason (via
    :func:`ForecastLedger.enqueue_resolution_proposal`) so proposals dedupe
    outcome-aware against the metric-threshold resolver AND prior sweeps, and
    surface / reconcile identically. Returns a rich summary incl. per-trigger and
    coverage counts for the read-only dry-run.
    """
    now_iso = parse_timestamp(now, field_name="now") or utc_now_iso()
    now_dt = timestamp_to_datetime(now_iso)

    # Outcome-aware dedup set built from ALL open proposal alerts (mirrors
    # propose_due_resolutions: (question_id, outcome) is the key, so a flipped
    # outcome still re-alerts, but a repeat does not spam).
    from forecasting.ledger import alerts as _alerts

    already: set[tuple[str, str]] = set()
    try:
        for alert in ledger.list_alerts(unresolved_only=True):
            if getattr(alert, "scope_type", None) != "question":
                continue
            outcome = _alerts.resolution_proposal_outcome(getattr(alert, "reason", ""))
            if outcome:
                already.add((alert.scope_ref, outcome))
    except Exception:
        pass

    candidates = [q for q in ledger.list_questions(status="active") if is_candidate(q, now_dt, horizon_days)]
    if limit is not None:
        candidates = candidates[: max(0, int(limit))]

    proposals: list[dict[str, Any]] = []
    undetermined: list[dict[str, Any]] = []
    by_trigger: dict[str, int] = {}
    n_past_due = 0

    for question in candidates:
        detection = detect_resolution(
            ledger, question, now_dt=now_dt,
            market_reader=market_reader, classifier=classifier, runner=runner, model=model,
        )
        if resolution_time_passed(question, now_dt):
            n_past_due += 1
        if not detection.determinable():
            undetermined.append({
                "question_id": question.id, "label": detection.label,
                "reason": detection.rationale, "market_id": detection.market_id,
            })
            continue
        by_trigger[detection.trigger] = by_trigger.get(detection.trigger, 0) + 1
        key = (question.id, str(detection.outcome))
        if key in already:
            proposals.append({**detection.to_dict(), "alerted": False, "skipped": "open_alert"})
            continue
        alert_id = None
        if not dry_run:
            tag = f"[{detection.tier}:{detection.trigger}] "
            alert = ledger.enqueue_resolution_proposal(
                question_id=question.id,
                outcome=detection.outcome,
                rationale=tag + detection.rationale,
            )
            alert_id = alert.id
            already.add(key)
        proposals.append({**detection.to_dict(), "alerted": not dry_run, "alert_id": alert_id})

    n_alerted = sum(1 for p in proposals if p.get("alerted"))
    return {
        "now": now_iso,
        "candidates": len(candidates),
        "past_due": n_past_due,
        "proposed": len(proposals),
        "alerted": n_alerted,
        "by_trigger": by_trigger,
        "proposals": proposals,
        "undetermined": undetermined,
        "undetermined_count": len(undetermined),
        "dry_run": dry_run,
    }


# ── the real, injected market-outcome reader (network I/O; best-effort) ──────────
def build_market_outcome_reader(*, api_timeout: float | None = None) -> MarketOutcomeReader:
    """Venue-dispatch reader over the existing source adapters. Dispatches on the
    ``<venue>:<id>`` market_id; a ``forecastbench:<id>`` ref uses ``market_source``
    as the true venue (the frozen benchmark hides the live URL from the agent, but
    RESOLUTION of an already-past-due, locked forecast may legitimately re-read the
    settled market). Returns None on any failure — a proposal is never fabricated.

    Coverage of the venues seen in the live ledger: manifold (settled → clean
    YES/NO), metaculus (resolution field), polymarket (saturated terminal price).
    Venues with no public reader (e.g. ``infer``) return None honestly.
    """

    def _reader(market_id: str, market_source: str | None) -> TerminalOutcome | None:
        raw = str(market_id or "").strip()
        if not raw or ":" not in raw:
            return None
        venue, ident = raw.split(":", 1)
        venue = venue.strip().lower()
        ident = ident.strip()
        if venue == "forecastbench":
            venue = str(market_source or "").strip().lower() or venue
        if not ident:
            return None
        try:
            if venue == "manifold":
                from forecasting.source_adapters import load_manifold_market

                m = load_manifold_market(f"id:{ident}")
                if not m.is_resolved:
                    return None
                outcome = _normalize_binary_outcome(m.resolution)
                return TerminalOutcome(
                    resolved=True, outcome=outcome, probability=m.probability,
                    venue="manifold", market_ref=raw,
                    detail=f"manifold isResolved, resolution={m.resolution!r}",
                )
            if venue == "metaculus":
                from forecasting.source_adapters import load_metaculus_question

                q = load_metaculus_question(f"id:{ident}")
                outcome = _normalize_binary_outcome(q.resolution)
                resolved = bool(q.resolution) or str(getattr(q, "status", "") or "").lower() in ("resolved", "closed")
                if not resolved:
                    return None
                return TerminalOutcome(
                    resolved=True, outcome=outcome, probability=q.probability,
                    venue="metaculus", market_ref=raw,
                    detail=f"metaculus resolution={q.resolution!r} status={getattr(q, 'status', None)!r}",
                )
            if venue == "polymarket":
                from forecasting.source_adapters import load_polymarket_market

                p = load_polymarket_market(f"id:{ident}")
                prob = p.probability
                # Polymarket import carries no explicit resolved flag; a settled
                # market prints a terminal (saturated) YES price — read that only.
                if prob is None or (TERMINAL_LOW < prob < TERMINAL_HIGH):
                    return None
                return TerminalOutcome(
                    resolved=True, outcome=("yes" if prob >= TERMINAL_HIGH else "no"),
                    probability=prob, venue="polymarket", market_ref=raw,
                    detail=f"polymarket terminal price {prob:.4f}",
                )
        except Exception:
            return None
        return None

    return _reader


# ── the injected LLM classifier (opt-in, bounded) ───────────────────────────────
def build_resolution_prompt(question: Any, payloads: list[dict[str, Any]]) -> tuple[str, str]:
    """System + user prompt for the tier-2 classifier. Kept small + explicit: the
    model classifies the resolution status ONLY from the criteria + the supplied
    payloads and must cite which payload supports it (or say not_yet/unclear)."""
    system = (
        "You are a forecast resolution adjudicator. Given a question's resolution "
        "criteria and the freshest watched-source payloads, decide whether it has "
        "RESOLVED. Reply with strict JSON: {\"label\": one of "
        "[resolved_yes, resolved_no, resolved_value, not_yet, unclear], "
        "\"outcome\": the outcome (\"yes\"/\"no\"/a value) or null, "
        "\"confidence\": 0..1, \"rationale\": one sentence citing the payload, "
        "\"evidence_refs\": [payload refs]}. NEVER guess: if the payloads do not "
        "clearly establish the outcome, return not_yet or unclear."
    )
    lines = [
        f"QUESTION: {getattr(question, 'title', '')}",
        f"CRITERIA: {getattr(question, 'resolution_criteria', '')}",
        f"OUTCOME_SPACE: {_outcome_space_type(question)}",
        "PAYLOADS:",
    ]
    for p in payloads[:10]:
        lines.append(f"  - {p}")
    return system, "\n".join(lines)


def classify_resolution(question: Any, payloads: list[dict[str, Any]], *, runner: Any, model: str) -> dict[str, Any]:
    """Reference classifier: build the prompt, call the injected runner, parse JSON.
    Raises on a hung runner (the caller degrades to unclear). Tolerant of a JSON
    object embedded in prose."""
    import json
    import re

    system, user = build_resolution_prompt(question, payloads)
    raw = runner(model, system, user)
    text = str(raw or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    return {"label": LABEL_UNCLEAR, "outcome": None, "confidence": 0.0, "rationale": "unparseable classifier response"}
