"""VOI-directed research planning + a research-adequacy judge.

The ledger already captures exactly what evidence would move a forecast — the
question's ``update_triggers``, the current snapshot's ``change_my_mind`` clauses
and ``reasons_down``, and (for categorical questions) the stored ``outcome_paths``.
The research stage historically hunted for none of it: it gathered evidence about
the topic in general, not about the specific levers that would change the number.

This module closes that loop with two pure, deterministic entry points plus one
optional, fail-open LLM check:

* :func:`build_research_plan` — a DETERMINISTIC scaffold of research angles. The
  standard angles (primary source, base rate / reference class, recent
  developments, contrarian / disconfirming) are always present; the VOI angles
  are derived from the question's OWN levers (one per update_trigger, one per
  change_my_mind clause, one per outcome_path). Suggested queries are template-
  built from the title + lever text — pure string work, no LLM.

* :func:`audit_research` — a research-adequacy judge. The deterministic checks
  (reference class present, evidence floor, source independence, disconfirming
  evidence present, recency, update-trigger coverage) ALWAYS run and are pure.
  The optional change_my_mind-coverage check runs only when a ``runner`` is
  supplied, is bounded and tool-less, and NEVER blocks: any error or unparseable
  reply simply drops that check.

Stdlib-only (mirroring forecasting/tail_audit.py + forecasting/hooks/spec.py): no
LLM, no network, no ledger writes. The ledger is read for the audit; planning
needs only the question (+ optional snapshot).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

# ── scoring weights ───────────────────────────────────────────────────────────
# Score = sum of the weights of the PASSING deterministic checks (0..100). The two
# ERROR-weight checks (reference_class_present, evidence_floor) are the hard floor:
# a gap in EITHER makes the research inadequate regardless of the numeric score.
ERROR_WEIGHT_CHECKS: frozenset[str] = frozenset({"reference_class_present", "evidence_floor"})

# The checks the RESEARCH stage itself controls (evidence gathering / watched
# sources). reference_class_present is a base_rate-stage artifact, so the chain's
# post-research audit loop must NOT re-run research to fix it — only these. The
# commit-time hook + the tool action still evaluate the FULL check set.
RESEARCH_STAGE_CHECKS: frozenset[str] = frozenset({
    "evidence_floor", "source_independence", "disconfirming_present", "recency", "triggers_covered",
})

CHECK_WEIGHTS: dict[str, float] = {
    "reference_class_present": 20.0,   # ERROR-weight
    "evidence_floor": 25.0,            # ERROR-weight
    "source_independence": 15.0,
    "disconfirming_present": 15.0,
    "recency": 15.0,
    "triggers_covered": 10.0,
}

# Default recency window (days) — mirrors the CLI's `--stale-evidence-days` default.
DEFAULT_STALE_EVIDENCE_DAYS = 30

# Evidence-count floor for a live-serious question.
EVIDENCE_FLOOR = 3

# Distinct-source floor for the independence check.
INDEPENDENCE_FLOOR = 2

DEFAULT_ADEQUACY_THRESHOLD = 70.0


# ── small pure helpers ────────────────────────────────────────────────────────
def _text(value: Any) -> str:
    return (str(value) if value is not None else "").strip()


def _days_since(iso: str | None, *, now: datetime | None = None) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ref = now or datetime.now(timezone.utc)
        return (ref - dt).days if dt <= ref else None
    except Exception:
        return None


_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "will", "by",
    "at", "is", "be", "as", "with", "that", "this", "than", "from", "into",
    "over", "under", "if", "it", "its", "are", "was", "were", "who", "what",
    "when", "which", "how", "does", "do", "did", "not",
}


def _keywords(text: str, *, limit: int = 6) -> list[str]:
    """Content tokens from a lever/title string (lowercased, stop-words dropped)."""
    out: list[str] = []
    seen: set[str] = set()
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]+", text or ""):
        low = tok.lower()
        if low in _STOPWORDS or len(low) <= 2:
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(tok)
        if len(out) >= limit:
            break
    return out


def _trigger_mechanism(trigger: dict[str, Any]) -> str:
    if not isinstance(trigger, dict):
        return _text(trigger)
    return _text(trigger.get("mechanism") or trigger.get("source_ref") or trigger.get("source"))


def _is_executable_trigger(trigger: dict[str, Any]) -> bool:
    """A trigger is EXECUTABLE when it keys off a series/market: it carries a
    ``source_ref`` plus an operator + numeric threshold (see models.py
    normalize_update_triggers)."""
    if not isinstance(trigger, dict):
        return False
    if not _text(trigger.get("source_ref")):
        return False
    op = _text(trigger.get("operator"))
    if op not in {">", ">=", "<", "<=", "==", "!="}:
        return False
    return isinstance(trigger.get("threshold"), (int, float)) and not isinstance(
        trigger.get("threshold"), bool
    )


def _outcome_paths_from_snapshot(snapshot: Any) -> dict[str, str]:
    """Recover the named outcome->path map a categorical snapshot stored. It lives
    in ``metadata['tail_audit']['verdicts']`` (each verdict has ``name`` + ``path``);
    returns only outcomes that carry a non-empty path. Empty for non-categorical or
    un-pathed snapshots."""
    if snapshot is None:
        return {}
    meta = getattr(snapshot, "metadata", None) or {}
    td = meta.get("tail_audit") if isinstance(meta, dict) else None
    if not isinstance(td, dict):
        return {}
    out: dict[str, str] = {}
    for v in td.get("verdicts") or []:
        if not isinstance(v, dict):
            continue
        name = _text(v.get("name"))
        path = _text(v.get("path"))
        if name and path:
            out[name] = path
    return out


# ── (1a) DETERMINISTIC research plan ──────────────────────────────────────────
def build_research_plan(question: Any, *, snapshot: Any = None) -> dict[str, Any]:
    """A deterministic scaffold of research angles for a question.

    Standard angles are always present; VOI angles are derived from the question's
    own levers — ``update_triggers``, the snapshot's ``change_my_mind`` clauses, and
    (categorical) stored ``outcome_paths``. Suggested queries are template-built
    from the title + lever text; NO LLM.

    Returns ``{question_id, title, angles:[{kind, rationale, suggested_queries}]}``.
    """
    title = _text(getattr(question, "title", ""))
    title_kw = " ".join(_keywords(title, limit=6)) or title
    angles: list[dict[str, Any]] = []

    # ── standard angles ──
    angles.append({
        "kind": "primary_source",
        "rationale": "Find the authoritative primary source that adjudicates the resolution criteria.",
        "suggested_queries": [
            f"{title} official announcement",
            f"{title_kw} primary source data",
        ],
    })
    angles.append({
        "kind": "base_rate",
        "rationale": "Establish the outside view: how often outcomes like this happen in the closest reference class.",
        "suggested_queries": [
            f"{title_kw} historical base rate",
            f"how often {title_kw} past occurrences frequency",
        ],
    })
    angles.append({
        "kind": "recent_developments",
        "rationale": "Pull the freshest developments that move the estimate off the base rate.",
        "suggested_queries": [
            f"{title} latest news",
            f"{title_kw} recent developments update",
        ],
    })
    angles.append({
        "kind": "contrarian",
        "rationale": "Hunt for disconfirming evidence and the strongest case AGAINST the leading outcome.",
        "suggested_queries": [
            f"{title_kw} why unlikely case against",
            f"{title_kw} skeptic analysis risks",
        ],
    })

    # ── VOI angles: one per update_trigger ──
    for trigger in getattr(question, "update_triggers", None) or []:
        mech = _trigger_mechanism(trigger)
        if not mech:
            continue
        src = _text(trigger.get("source_ref") if isinstance(trigger, dict) else "")
        queries = [f"{' '.join(_keywords(mech, limit=6)) or mech} latest value"]
        if src:
            queries.append(f"{src} current reading")
        else:
            queries.append(f"{title_kw} {' '.join(_keywords(mech, limit=3))}".strip())
        angles.append({
            "kind": "update_trigger",
            "rationale": f"Watch the update trigger's mechanism/source directly: {mech}",
            "suggested_queries": queries,
        })

    # ── VOI angles: one per change_my_mind clause ──
    for clause in (getattr(snapshot, "change_my_mind", None) or []):
        clause_t = _text(clause)
        if not clause_t:
            continue
        kw = " ".join(_keywords(clause_t, limit=6)) or clause_t
        angles.append({
            "kind": "change_my_mind",
            "rationale": f"Directly hunt for exactly what would change the forecast: {clause_t}",
            "suggested_queries": [
                kw,
                f"{title_kw} {' '.join(_keywords(clause_t, limit=3))}".strip(),
            ],
        })

    # ── VOI angles: one per outcome_path (categorical) ──
    for outcome, path in _outcome_paths_from_snapshot(snapshot).items():
        kw = " ".join(_keywords(f"{outcome} {path}", limit=6)) or outcome
        angles.append({
            "kind": "outcome_path",
            "rationale": f"Test the named path for outcome '{outcome}': {path}",
            "suggested_queries": [
                f"{title_kw} {' '.join(_keywords(outcome, limit=3))}".strip(),
                kw,
            ],
        })

    return {
        "question_id": _text(getattr(question, "id", "")),
        "title": title,
        "angles": angles,
    }


# ── (1b) DETERMINISTIC adequacy checks ────────────────────────────────────────
from forecasting.evidence_quality import observation_identity, source_identity


def _source_identity(item: Any) -> str:
    return source_identity(item) or "unknown"


def deterministic_research_checks(
    *,
    question: Any,
    evidence: list[Any],
    reference_classes: list[Any],
    watched_sources: list[Any],
    reasons_down: Iterable[str] | None,
    evidence_refs: Iterable[str] | None,
    stale_evidence_days: int = DEFAULT_STALE_EVIDENCE_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure deterministic adequacy checks over already-fetched ledger data. Returns
    ``{score, checks:{name:bool}, gaps:[...], adequate_deterministic}`` where
    ``adequate_deterministic`` is True only when NO ERROR-weight check failed.

    Shared by :func:`audit_research` (which fetches from the ledger) and the
    commit-time hook context builder (which passes the candidate commit's
    reasons_down / evidence_refs so the audit reflects the number being written)."""

    evidence = list(evidence or [])
    reasons_down = [r for r in (reasons_down or []) if _text(r)]
    evidence_refs = [r for r in (evidence_refs or []) if _text(r)]
    checks: dict[str, bool] = {}
    gaps: list[dict[str, Any]] = []
    title = _text(getattr(question, "title", ""))
    title_kw = " ".join(_keywords(title, limit=4)) or title

    # reference_class_present (ERROR-weight)
    active_refs = [
        rc for rc in (reference_classes or [])
        if _text((rc.get("status") if isinstance(rc, dict) else getattr(rc, "status", None)) or "active") != "superseded"
        and _text((rc.get("status") if isinstance(rc, dict) else getattr(rc, "status", None)) or "active") != "rejected"
    ]
    ref_ok = len(active_refs) >= 1
    checks["reference_class_present"] = ref_ok
    if not ref_ok:
        gaps.append({
            "kind": "reference_class_present",
            "detail": "no active reference class — the forecast has no outside-view anchor.",
            "suggested_queries": [f"{title_kw} historical base rate reference class"],
        })

    # evidence_floor (ERROR-weight)
    observation_count = len({observation_identity(item) for item in evidence})
    floor_ok = observation_count >= EVIDENCE_FLOOR
    checks["evidence_floor"] = floor_ok
    if not floor_ok:
        gaps.append({
            "kind": "evidence_floor",
            "detail": f"only {observation_count} distinct observation(s); a serious live forecast wants >= {EVIDENCE_FLOOR}.",
            "suggested_queries": [f"{title} analysis", f"{title_kw} expert forecast"],
        })

    # source_independence (>= 2 distinct sources)
    distinct_sources = {source_identity(item) for item in evidence} - {None}
    indep_ok = len(distinct_sources) >= INDEPENDENCE_FLOOR
    checks["source_independence"] = indep_ok
    if not indep_ok:
        gaps.append({
            "kind": "source_independence",
            "detail": (
                f"evidence traces to {len(distinct_sources)} distinct source(s); need >= "
                f"{INDEPENDENCE_FLOOR} source groups. Verify original provenance; host diversity alone does not prove independence."
            ),
            "suggested_queries": [f"{title_kw} independent second source", f"{title_kw} alternative data"],
        })

    # disconfirming_present. Primary signal: a stored evidence `stance` marks the
    # DOWN side (opposes / mixed). Structural fallback (documented proxy): the
    # candidate commit has non-empty reasons_down AND cites >= 1 evidence ref —
    # i.e. the DOWN path is at least evidence-backed, even when no stance is set.
    stance_down = any(
        _text(getattr(item, "stance", None)).lower() in {"opposes", "mixed"}
        for item in evidence
    )
    structural_down = bool(reasons_down) and bool(evidence_refs)
    disc_ok = stance_down or structural_down
    checks["disconfirming_present"] = disc_ok
    if not disc_ok:
        gaps.append({
            "kind": "disconfirming_present",
            "detail": (
                "no disconfirming evidence: no evidence row takes the DOWN side (stance "
                "opposes/mixed) and the commit does not back reasons_down with a cited ref. "
                "Research the strongest case against, not just the confirming view."
            ),
            "suggested_queries": [f"{title_kw} case against why unlikely", f"{title_kw} risks counterargument"],
        })

    # recency (>= 1 evidence row within stale_evidence_days)
    fresh = any(
        (lambda d: d is not None and d <= stale_evidence_days)(_days_since(getattr(item, "available_at", None), now=now))
        for item in evidence
    )
    checks["recency"] = fresh
    if not fresh:
        gaps.append({
            "kind": "recency",
            "detail": f"no evidence within {stale_evidence_days} days — the readings are stale; re-collect fresh data.",
            "suggested_queries": [f"{title} latest {datetime.now(timezone.utc).year}", f"{title_kw} recent news"],
        })

    # triggers_covered: each EXECUTABLE update_trigger has a watched source or an
    # evidence row matching its mechanism/source (string-match proxy — documented).
    executable = [t for t in (getattr(question, "update_triggers", None) or []) if _is_executable_trigger(t)]
    watched_ids = " ".join(
        _text((ws.get("source") if isinstance(ws, dict) else getattr(ws, "source", None)))
        + " " + _text((ws.get("source_type") if isinstance(ws, dict) else getattr(ws, "source_type", None)))
        for ws in (watched_sources or [])
    ).lower()
    evidence_blob = " ".join(
        _source_identity(item) + " " + _text(getattr(item, "source_type", None))
        for item in evidence
    ).lower()
    uncovered: list[str] = []
    for trig in executable:
        src = _text(trig.get("source_ref")).lower()
        # match on the source_ref token or its adapter prefix (e.g. fred:CPIAUCSL)
        needle = src.split(":", 1)[-1] if ":" in src else src
        prefix = src.split(":", 1)[0] if ":" in src else src
        covered = bool(needle) and (needle in watched_ids or needle in evidence_blob
                                    or (prefix and (prefix in watched_ids or prefix in evidence_blob)))
        if not covered:
            uncovered.append(_text(trig.get("source_ref")) or _trigger_mechanism(trig))
    triggers_ok = not uncovered
    checks["triggers_covered"] = triggers_ok
    if not triggers_ok:
        gaps.append({
            "kind": "triggers_covered",
            "detail": (
                "executable update trigger(s) with no watched source or matching evidence: "
                + ", ".join(uncovered)
                + " — add a watched source or import the series so the trigger can fire."
            ),
            "suggested_queries": [f"{u} current value" for u in uncovered[:3]],
        })

    score = round(sum(CHECK_WEIGHTS[name] for name, ok in checks.items() if ok), 1)
    adequate_deterministic = all(checks.get(name, False) for name in ERROR_WEIGHT_CHECKS)
    return {
        "score": score,
        "checks": checks,
        "gaps": gaps,
        "adequate_deterministic": adequate_deterministic,
    }


# ── (1b) the judge ────────────────────────────────────────────────────────────
def _resolve_adequacy_threshold() -> float:
    try:
        from superforecasting_agent.configuration import cfg_get
        from superforecasting_agent.storage.configuration import read_configuration

        val = cfg_get(read_configuration(), "forecasting", "research", "adequacy_threshold", default=None)
        if val is not None:
            return float(val)
    except Exception:
        pass
    return DEFAULT_ADEQUACY_THRESHOLD


def audit_research(
    ledger: Any,
    question: Any,
    *,
    snapshot: Any = None,
    runner: Callable[[str, str, str], str] | None = None,
    model: str | None = None,
    stale_evidence_days: int | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Judge whether the research backing ``question`` is adequate.

    Deterministic checks always run (pure). The optional change_my_mind-coverage
    check runs ONLY when ``runner`` is supplied and is fully fail-open: any error or
    unparseable reply drops it (never blocks, never changes the score).

    Returns ``{adequate, score, threshold, gaps, checks, llm_check?}``.
    """
    if snapshot is None:
        try:
            snapshot = ledger.get_current_snapshot(question.id)
        except Exception:
            snapshot = None

    try:
        evidence = ledger.list_evidence(question.id)
    except Exception:
        evidence = []
    try:
        reference_classes = ledger.list_reference_classes(question.id)
    except Exception:
        reference_classes = []
    try:
        watched_sources = ledger.list_watched_sources(
            scope_type="question", scope_ref=question.id, status="active"
        )
    except Exception:
        watched_sources = []

    window = stale_evidence_days if stale_evidence_days is not None else DEFAULT_STALE_EVIDENCE_DAYS
    result = deterministic_research_checks(
        question=question,
        evidence=evidence,
        reference_classes=reference_classes,
        watched_sources=watched_sources,
        reasons_down=getattr(snapshot, "reasons_down", None),
        evidence_refs=getattr(snapshot, "evidence_refs", None),
        stale_evidence_days=window,
    )

    thr = threshold if threshold is not None else _resolve_adequacy_threshold()
    gaps = list(result["gaps"])

    # ── optional, fail-open LLM check: change_my_mind coverage ──
    llm_check: dict[str, Any] | None = None
    cmm = [c for c in (getattr(snapshot, "change_my_mind", None) or []) if _text(c)]
    if runner is not None and cmm and evidence:
        try:
            llm_check = _change_my_mind_coverage(runner, model, question, cmm, evidence)
        except Exception:
            llm_check = None
        if llm_check and llm_check.get("uncovered"):
            gaps.append({
                "kind": "change_my_mind_coverage",
                "detail": (
                    "the evidence set does not address these change_my_mind clause(s): "
                    + "; ".join(str(u) for u in llm_check["uncovered"])
                    + " — a serious forecast researches its own change-my-mind conditions."
                ),
                "suggested_queries": [
                    " ".join(_keywords(str(u), limit=6)) for u in llm_check["uncovered"][:3]
                ],
            })

    adequate = result["adequate_deterministic"] and result["score"] >= thr
    out: dict[str, Any] = {
        "adequate": bool(adequate),
        "score": result["score"],
        "threshold": thr,
        "checks": result["checks"],
        "gaps": gaps,
    }
    if llm_check is not None:
        out["llm_check"] = llm_check
    return out


def research_stage_incomplete(audit: dict[str, Any] | None) -> bool:
    """True when a RESEARCH-stage-controllable check failed (evidence floor, source
    independence, disconfirming evidence, recency, trigger coverage) — the signal the
    chain's post-research audit loop uses to decide whether re-running RESEARCH would
    help. reference_class_present is deliberately excluded (it is the base_rate
    stage's job, run later)."""
    if not audit:
        return False
    checks = audit.get("checks") or {}
    return any(not checks.get(name, True) for name in RESEARCH_STAGE_CHECKS)


def audit_research_for_commit(
    ledger: Any,
    question: Any,
    *,
    reasons_down: Iterable[str] | None,
    evidence_refs: Iterable[str] | None,
    stale_evidence_days: int | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Deterministic-only research adequacy for the COMMIT path (NO LLM). Uses the
    CANDIDATE commit's ``reasons_down`` + ``evidence_refs`` (not a prior snapshot) so
    the audit reflects the number being written. Fully fail-open: any read error
    yields an adequate=True verdict so a commit is never falsely blocked.

    Returns ``{adequate, score, threshold, checks, gaps}``."""
    try:
        evidence = ledger.list_evidence(question.id)
    except Exception:
        evidence = []
    try:
        reference_classes = ledger.list_reference_classes(question.id)
    except Exception:
        reference_classes = []
    try:
        watched_sources = ledger.list_watched_sources(
            scope_type="question", scope_ref=question.id, status="active"
        )
    except Exception:
        watched_sources = []

    window = stale_evidence_days if stale_evidence_days is not None else DEFAULT_STALE_EVIDENCE_DAYS
    result = deterministic_research_checks(
        question=question,
        evidence=evidence,
        reference_classes=reference_classes,
        watched_sources=watched_sources,
        reasons_down=reasons_down,
        evidence_refs=evidence_refs,
        stale_evidence_days=window,
    )
    thr = threshold if threshold is not None else _resolve_adequacy_threshold()
    return {
        "adequate": bool(result["adequate_deterministic"] and result["score"] >= thr),
        "score": result["score"],
        "threshold": thr,
        "checks": result["checks"],
        "gaps": result["gaps"],
    }


def _change_my_mind_coverage(
    runner: Callable[[str, str, str], str],
    model: str | None,
    question: Any,
    change_my_mind: list[str],
    evidence: list[Any],
) -> dict[str, Any] | None:
    """One bounded, tool-less LLM call: which change_my_mind clauses does the
    current evidence set actually address? Returns {covered, uncovered} or None if
    the reply is unparseable. Never raises to the caller for anything but a truly
    unexpected error (the caller wraps it too)."""

    active_model = model
    if not active_model:
        try:
            from superforecasting_agent.storage.configuration import read_configuration
            from forecasting.quorum_autorun import resolve_active_model_id

            active_model = resolve_active_model_id(read_configuration().get("model"))
        except Exception:
            active_model = None
    if not active_model:
        return None

    clause_lines = "\n".join(f"{i}. {_text(c)}" for i, c in enumerate(change_my_mind))
    ev_lines = "\n".join(
        f"- {_text(getattr(item, 'claim', None)) or _text(getattr(item, 'summary', None))}"
        for item in evidence[:20]
    )
    system = (
        "You audit whether a forecast's evidence set addresses its stated "
        "'change my mind' conditions. Reply with ONLY a JSON object of the form "
        '{"covered": [<clause numbers the evidence speaks to>], '
        '"uncovered": [<clause numbers the evidence does NOT address>]}. '
        "No prose, no code fences."
    )
    user = (
        f'Question: "{_text(getattr(question, "title", ""))}"\n\n'
        f"Change-my-mind clauses:\n{clause_lines}\n\n"
        f"Evidence claims:\n{ev_lines or '- (none)'}\n\n"
        "Which clauses does the evidence address?"
    )
    text = (runner(active_model, system, user) or "").strip()
    if not text:
        return None
    # tolerate a fenced or padded reply
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None

    def _map(nums: Any) -> list[str]:
        out: list[str] = []
        for n in nums or []:
            try:
                idx = int(n)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(change_my_mind):
                out.append(_text(change_my_mind[idx]))
        return out

    covered = _map(parsed.get("covered"))
    uncovered = _map(parsed.get("uncovered"))
    # de-dup uncovered against covered (a clause the model listed twice)
    uncovered = [u for u in uncovered if u not in covered]
    return {"covered": covered, "uncovered": uncovered}
