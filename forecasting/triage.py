"""Information-triage labeler — replicate desk judgment on what to READ.

The Thinking Machines / Bridgewater AIA "Learning to Replicate Expert Judgment
in Financial Tasks" study found the result-carrying moves were not a bigger
model but (a) reframing binary relevance into a THREE-WAY label that separates
*interesting* from merely *relevant* (a small IPO is relevant but uninteresting
to a macro desk), and (b) routing only CONTESTED examples to expensive expert
adjudication.

This module is the harness analog of their cheap labeler. It runs a small model
over candidate readings, scoped by a desk-authored rubric, and emits a
keep/skim/skip verdict BEFORE anything becomes evidence — so the desk (and the
human) wade through the material set, not the firehose. The contested-routing
loop (the alert kind) and the held-out trust gate are built on top of the
``triage_labels`` rows these verdicts produce.

The model call is INJECTED — a ``TriageRunner`` with the same shape as the
quorum runner, ``(model, system, user) -> str`` — so the labeler is trivially
testable: the tool wires the real cheap-model caller, tests inject a fake.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Sequence

# ── Three-way label (L9) — the middle class is the load-bearing distinction ───
RELEVANT_INTERESTING = "relevant_interesting"
RELEVANT_UNINTERESTING = "relevant_uninteresting"
IRRELEVANT = "irrelevant"
THREE_WAY_LABELS = (RELEVANT_INTERESTING, RELEVANT_UNINTERESTING, IRRELEVANT)

KEEP, SKIM, SKIP = "keep", "skim", "skip"
TRIAGE_VERDICTS = (KEEP, SKIM, SKIP)

# Each label maps to the analyst's default reading action.
LABEL_TO_VERDICT = {
    RELEVANT_INTERESTING: KEEP,
    RELEVANT_UNINTERESTING: SKIM,
    IRRELEVANT: SKIP,
}

MATERIALITY = ("low", "medium", "high")

TriageRunner = Callable[[str, str, str], str]

# Tolerant aliasing so a model that phrases the label slightly differently is not
# silently mis-bucketed. Unknown / missing → relevant_uninteresting (skim): the
# conservative "don't drop it" default, so a labeling miss surfaces rather than
# vanishing as irrelevant.
_LABEL_ALIASES = {
    "relevant_interesting": RELEVANT_INTERESTING,
    "relevant_and_interesting": RELEVANT_INTERESTING,
    "interesting": RELEVANT_INTERESTING,
    "keep": RELEVANT_INTERESTING,
    "relevant_uninteresting": RELEVANT_UNINTERESTING,
    "relevant_but_uninteresting": RELEVANT_UNINTERESTING,
    "uninteresting": RELEVANT_UNINTERESTING,
    "relevant": RELEVANT_UNINTERESTING,
    "skim": RELEVANT_UNINTERESTING,
    "irrelevant": IRRELEVANT,
    "not_relevant": IRRELEVANT,
    "skip": IRRELEVANT,
}


# The seed macro-desk rubric — what counts as INTERESTING here. The operator
# edits/overrides it with `set_label_rubric` (stored scoped, like a calibration
# lesson); this default is used only when no scoped rubric exists.
DEFAULT_TRIAGE_RUBRIC: dict[str, Any] = {
    "scope_type": "global",
    "scope_ref": None,
    "rubric_id": None,
    "interesting_criteria": (
        "Broad macro/markets significance to a generalist desk: moves or re-rates "
        "a major asset class, policy regime, or the path of growth / inflation / "
        "rates; a genuine SURPRISE versus consensus; a development that changes the "
        "odds on an OPEN forecast the desk holds; or a second-order / cross-asset "
        "implication a fast reader would miss."
    ),
    "uninteresting_criteria": (
        "Financially real but narrow or already-priced: a small single-name event "
        "(e.g. a small IPO), routine scheduled data that landed in line with "
        "consensus, incremental company news with no macro read-through, or a "
        "restatement of widely-known facts."
    ),
    "irrelevant_criteria": (
        "No bearing on markets, macro, or any desk forecast: off-topic, "
        "promotional, duplicate, or pure boilerplate."
    ),
    "examples": [
        {
            "title": "Small regional IPO prices at the low end of its range",
            "label": RELEVANT_UNINTERESTING,
            "why": "financially real but lacks the broad significance that makes it interesting to a macro desk",
        },
        {
            "title": "Central bank unexpectedly signals a pause in hikes",
            "label": RELEVANT_INTERESTING,
            "why": "a surprise versus consensus that re-rates the rate path",
        },
        {
            "title": "Celebrity gossip column",
            "label": IRRELEVANT,
            "why": "no market or macro bearing",
        },
    ],
}


_SYSTEM_PROMPT = (
    "You are a triage labeler on a superforecasting / markets desk. For each "
    "candidate reading, decide how a busy analyst should triage it. Apply the "
    "desk's rubric EXACTLY: separate what is INTERESTING (worth the analyst's "
    "scarce attention) from what is merely RELEVANT (financially real but not "
    "worth the attention) from what is IRRELEVANT (no bearing). Be decisive and "
    "calibrated; do not inflate everything to interesting. Return STRICT JSON only."
)


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return round(number, 4)


def normalize_label(value: Any) -> str:
    if not value:
        return RELEVANT_UNINTERESTING
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return _LABEL_ALIASES.get(text, RELEVANT_UNINTERESTING)


def _normalize_materiality(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in MATERIALITY else "medium"


def verdict_for_label(label: str) -> str:
    return LABEL_TO_VERDICT.get(label, SKIM)


def rubric_to_block(rubric: dict[str, Any] | None) -> str:
    """Render a rubric (or the default) as the prompt's criteria block."""
    rubric = rubric or DEFAULT_TRIAGE_RUBRIC
    lines = [
        "DESK RUBRIC — what counts as INTERESTING here:",
        f"- {RELEVANT_INTERESTING}: {rubric.get('interesting_criteria', '')}",
        f"- {RELEVANT_UNINTERESTING}: {rubric.get('uninteresting_criteria', '')}",
        f"- {IRRELEVANT}: {rubric.get('irrelevant_criteria', '')}",
    ]
    examples = rubric.get("examples") or []
    if examples:
        lines.append("")
        lines.append("Worked examples:")
        for ex in examples:
            if not isinstance(ex, dict):
                continue
            lines.append(
                f'- "{ex.get("title", "")}" -> {ex.get("label", "")} ({ex.get("why", "")})'
            )
    return "\n".join(lines)


def _candidate_title(candidate: dict[str, Any]) -> str:
    return (
        candidate.get("title")
        or candidate.get("claim")
        or candidate.get("source_label")
        or candidate.get("source")
        or "(untitled)"
    )


def build_triage_prompt(
    candidates: Sequence[dict[str, Any]], rubric: dict[str, Any] | None = None
) -> tuple[str, str]:
    """Deterministic labeling scaffold: (system, user) prompts."""
    lines = [rubric_to_block(rubric), ""]
    lines.append("CANDIDATES (label every one, by index):")
    for index, candidate in enumerate(candidates):
        title = _candidate_title(candidate)
        source = candidate.get("source_type") or candidate.get("source") or ""
        block = f"[{index}] {title}"
        if source:
            block += f"  (source: {source})"
        summary = (candidate.get("summary") or "").strip()
        if summary:
            block += f"\n    {summary[:600]}"
        lines.append(block)
    lines.append("")
    lines.append(
        'Return JSON: {"labels": [{"index": int, "triage_label": one of '
        f"[{', '.join(THREE_WAY_LABELS)}], "
        '"relevance": number in 0..1 (how on-topic for the desk), '
        '"materiality": one of [low, medium, high] (how much it could move the '
        'desk view), "rationale": short string}]}. Label EVERY candidate index '
        "exactly once."
    )
    return _SYSTEM_PROMPT, "\n".join(lines)


def _extract_json(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`")
        newline = text.find("\n")
        if newline != -1 and text[:newline].strip().lower() in ("json", ""):
            text = text[newline + 1 :]
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except (ValueError, TypeError):
                continue
    return None


def _candidate_ref(candidate: dict[str, Any]) -> str | None:
    for key in ("candidate_ref", "id", "entry_id", "url", "watched_source_id"):
        value = candidate.get(key)
        if value:
            return str(value)
    return None


def parse_triage_response(
    raw: Any, candidates: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Parse a labeler response into one verdict dict per candidate (by index).

    Tolerant of fences, extra prose, and missing rows; a candidate with no row
    falls back to relevant_uninteresting (skim) so a labeling miss surfaces
    rather than silently dropping the reading.
    """
    data = _extract_json(raw)
    if isinstance(data, dict):
        rows = data.get("labels") or data.get("results") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    by_index: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("index"))
        except (TypeError, ValueError):
            continue
        by_index[index] = row

    verdicts: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        row = by_index.get(index, {})
        label = normalize_label(row.get("triage_label") or row.get("label"))
        verdicts.append(
            {
                "candidate_ref": _candidate_ref(candidate),
                "title": _candidate_title(candidate),
                "summary": candidate.get("summary") or "",
                "source_type": candidate.get("source_type"),
                "source": candidate.get("source"),
                "url": candidate.get("url"),
                "triage_label": label,
                "auto_label": label,
                "relevance": _safe_float(row.get("relevance")),
                "materiality": _normalize_materiality(row.get("materiality")),
                "verdict": verdict_for_label(label),
                "rationale": str(row.get("rationale") or ""),
                "label_source": "auto",
            }
        )
    return verdicts


def triage_candidates(
    candidates: Sequence[dict[str, Any]],
    *,
    runner: TriageRunner,
    model: str,
    rubric: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run the cheap auto-labeler over candidates and return one verdict each.

    Raises whatever ``runner`` raises (a hung/failed model) so the caller can
    decide how to degrade; a garbled-but-returned response is tolerated and
    degrades per-candidate to skim.
    """
    if not candidates:
        return []
    system, user = build_triage_prompt(candidates, rubric)
    raw = runner(model, system, user)
    verdicts = parse_triage_response(raw, candidates)
    # Stored rubrics carry their id under "id"; the implicit default has neither,
    # so this is None for the default (correct) and the real id for a stored rubric.
    rubric_id = (rubric or {}).get("id")
    for verdict in verdicts:
        verdict["rubric_id"] = rubric_id
        verdict["model"] = model
    return verdicts


def active_rubric_for_question(ledger: Any, question: Any) -> dict[str, Any] | None:
    """Most-specific active rubric for a question (None → caller uses default).

    Scope walk by subject specificity: domain_topic → domain → topic →
    question_type → global. Mirrors ``learning.active_lessons_for_question`` but
    returns the single most-specific match rather than the union.
    """
    domain = getattr(question, "domain", None)
    topics = list(getattr(question, "topics", []) or [])
    outcome = getattr(question, "outcome_space", None)
    qtype = getattr(outcome, "type", None) if outcome is not None else None

    scopes: list[tuple[str, str | None]] = []
    for topic in topics:
        if domain:
            scopes.append(("domain_topic", f"{domain}:{topic}"))
    if domain:
        scopes.append(("domain", domain))
    for topic in topics:
        scopes.append(("topic", topic))
    if qtype:
        scopes.append(("question_type", qtype))
    scopes.append(("global", None))

    for scope_type, scope_ref in scopes:
        rubrics = ledger.list_triage_rubrics(
            scope_type=scope_type, scope_ref=scope_ref, active_only=True
        )
        if rubrics:
            return rubrics[0]
    return None


def build_triage_trust_gate(
    ledger: Any, *, threshold: float = 0.8, min_sample: int = 20
) -> dict[str, Any]:
    """Held-out trust gate: is the cheap auto-labeler good enough to be trusted?

    Scores the auto-label against the operator's expert adjudication over every
    relabeled item (auto_label = prediction, expert_label = gold). Until accuracy
    clears ``threshold`` (the 80% analog the study's investors required) over at
    least ``min_sample`` adjudicated items, the labeler stays SUGGEST-ONLY — it
    surfaces verdicts but is not trusted to auto-filter. Mirrors the
    ``can_claim_live_superforecasting`` guardrail: a flag that only flips on real
    measured evidence, never by assertion.
    """
    from forecasting.label_scoring import headline_accuracy, score_labels

    rows = ledger.list_triage_labels(label_source="expert", adjudicated=True, limit=1000)
    pairs = [r for r in rows if r.get("auto_label") and r.get("expert_label")]
    score = score_labels(
        [{"id": r["id"], "label": r["auto_label"]} for r in pairs],
        [{"id": r["id"], "label": r["expert_label"]} for r in pairs],
        task_type="relevance",
    )
    accuracy = headline_accuracy(score)
    n = score.n
    has_sample = n >= min_sample
    cleared = bool(has_sample and accuracy is not None and accuracy >= threshold)

    if accuracy is None:
        action = (
            "No adjudicated triage labels yet — hand-label a contested sample "
            "(triage_contested then relabel_route) to start measuring auto-label "
            "accuracy against expert labels."
        )
    elif not has_sample:
        action = (
            f"Only {n}/{min_sample} adjudicated labels — the labeler stays "
            "SUGGEST-ONLY until the held-out sample is large enough to trust."
        )
    elif not cleared:
        action = (
            f"Auto-label accuracy {accuracy:.1%} is below the {threshold:.0%} trust "
            "bar — the labeler stays SUGGEST-ONLY; keep routing disagreements to "
            "operator review (relabel_route)."
        )
    else:
        action = (
            f"Auto-label accuracy {accuracy:.1%} clears the {threshold:.0%} bar over "
            f"n={n} adjudicated items — the labeler is trusted to auto-filter."
        )

    return {
        "id": "triage_labeler_trust",
        "observed_accuracy": accuracy,
        "n": n,
        "threshold": threshold,
        "min_sample": min_sample,
        "passed": cleared,
        "mode": "auto" if cleared else "suggest_only",
        "can_auto_filter": cleared,
        "label_score": score.to_dict(),
        "recommended_action": action,
    }

