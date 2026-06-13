"""Analyst write-ups ("desk notes") for the forecasting ledger.

Each forecast carries a time-series of short prose notes written in the voice of
a FiveThirtyEight desk analyst: how the model feels about the number, how it
thinks about the question, what it is looking for next, and what the reader
should be aware of. A `brief` is written on every probability-bearing update (and
on evidence-only thinking updates); a `retrospective` is written once the
question resolves.

This module is intentionally import-light: the LLM client and the protocol
context builder are imported lazily inside :func:`generate_writeup`, so the pure
prompt/parse/sanitize helpers can be unit-tested without any provider configured.
Generation is always best-effort: any failure returns ``None`` and the caller
commits the forecast anyway. A note must never be able to roll back a snapshot.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Dash characters the house style forbids, mapped to a clean replacement. Models
# leak these despite the prompt, so the sanitizer below is mandatory, not
# advisory. (em, en, horizontal bar, figure dash, hyphen-minus variants.)
BANNED_DASHES = {
    "—": ", ",  # em dash
    "–": "-",   # en dash
    "―": ", ",  # horizontal bar
    "‒": "-",   # figure dash
    "‐": "-",   # hyphen
    "‑": "-",   # non-breaking hyphen
}

PROMPT_VERSION = "writeup-v1"

WRITEUP_SYSTEM_PROMPT = """You are the desk analyst for a Superforecasting agent. \
You write a short, sharp opinion note in the voice of Nate Silver at FiveThirtyEight: \
plain-spoken, probability-literate, evidence-pointing, hedged but decisive. You are a \
fox, not a hedgehog. You think in probabilities and odds, not verdicts. You take the \
outside view first, decompose the question into its drivers, and update like a Bayesian \
on the strength of new evidence. You point AT the evidence in the context, you do not \
just assert.

STYLE RULES (hard constraints):
- Write in clean American English with good flow. Short paragraphs.
- Do NOT use em-dashes or en-dashes. Use periods, commas, or rephrase the sentence. \
Do not stack clauses with semicolons. No bullet lists inside the prose.
- Do not repeat the structured reasons verbatim. Synthesize them and point to them.
- Never invent evidence, sources, or numbers that are not in the context. If you are \
genuinely unsure, say so plainly.
- About 3 to 5 sentences per angle. Keep the whole thing under 280 words.

Cover exactly four angles:
1. HOW IT FEELS: the model's confidence and comfort with this number right now, and why.
2. HOW IT THINKS: the core mechanism and the drivers behind the probability, the inside \
view checked against the outside view.
3. LOOKING FOR NEXT: the specific signals or data that would move the number up or down.
4. BE AWARE: the live caveat or risk, and what the reader should not over-read.

Return ONLY a JSON object, with no prose around it, using these keys:
{"headline": "<=90 chars, one-line takeaway, no em-dash>",
 "how_it_feels": "...", "how_it_thinks": "...", "looking_for": "...", "be_aware": "...",
 "stance": "lean_yes|lean_no|toss_up"}"""

RETRO_SYSTEM_PROMPT = """You are the desk analyst for a Superforecasting agent, writing \
the closing retrospective now that the question has resolved. Keep the same FiveThirtyEight \
voice: plain-spoken, honest, probability-literate. Be realistic about whether the call was \
right, wrong, close, or far. No spin. A good forecaster grades themselves honestly and \
says what they would do differently.

STYLE RULES (hard constraints):
- Clean American English, good flow, short paragraphs.
- Do NOT use em-dashes or en-dashes. Do not stack clauses with semicolons. No bullet \
lists inside the prose.
- Ground the verdict in the score and in the probability the model put on the outcome \
that actually happened. Do not overclaim question-specific causation from domain-level \
patterns.
- Keep the whole thing under 300 words.

Cover:
1. HOW IT FEELS (the honest grade): right, wrong, close, or far, and how it feels in \
hindsight.
2. HOW IT THINKS: what actually drove the outcome versus what the model weighted.
3. LOOKING FOR NEXT (the lesson): what it learned and what it would do differently next \
time, drawing on the postmortem and any domain-level patterns, flagged as domain-level \
rather than specific to this question.
4. BE AWARE: what the reader should carry forward to similar questions.

Return ONLY a JSON object, with no prose around it, using these keys:
{"headline": "<=90 chars, no em-dash>",
 "how_it_feels": "...", "how_it_thinks": "...", "looking_for": "...", "be_aware": "...",
 "verdict": "right|wrong|close|far"}"""

_FIELD_KEYS = ("how_it_feels", "how_it_thinks", "looking_for", "be_aware")


def sanitize_writeup_text(text: str) -> str:
    """Deterministically strip banned dashes and tidy whitespace.

    Mandatory post-process: the prompt forbids em-dashes but models still emit
    them, so we enforce the house style here rather than trusting the model.
    """

    if not text:
        return ""
    for bad, repl in BANNED_DASHES.items():
        text = text.replace(bad, repl)
    # A spaced " -- " reads as an em-dash substitute; turn it into a comma break.
    text = re.sub(r"\s+--\s+", ", ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)  # trim around hard newlines
    text = re.sub(r"[ \t]{2,}", " ", text)        # collapse runs of spaces
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)   # tighten space-before-punct
    text = re.sub(r",\s*,", ", ", text)            # collapse doubled commas
    text = re.sub(r"\.\s*\.(?!\.)", ". ", text)     # collapse doubled periods
    return text.strip()


def tail_audit_summary(snapshot: Any) -> str:
    """One-line summary of a snapshot's probability-mass audit, or '' when the
    snapshot has none (non-categorical / older) or the audit passed. Injected
    into the write-up so the analyst commentary FLAGS unearned tail mass instead
    of contradicting the audit the desk shows."""
    metadata = getattr(snapshot, "metadata", None)
    if not isinstance(metadata, dict):
        return ""
    audit = metadata.get("tail_audit")
    if not isinstance(audit, dict) or audit.get("passes"):
        return ""
    unearned = audit.get("unearned_mass") or 0.0
    offenders = [
        o.get("name")
        for o in (audit.get("outcomes") or [])
        if isinstance(o, dict) and o.get("unearned")
    ]
    null = audit.get("null_model") or {}
    bits = [f"tail audit FAIL: {unearned:.1%} unearned tail mass"]
    if offenders:
        bits.append("on " + ", ".join(str(o) for o in offenders if o))
    if null and not null.get("within_tolerance", True):
        ratio = null.get("ratio")
        if isinstance(ratio, (int, float)) and ratio != float("inf"):
            bits.append(f"(no-path tail {ratio:.1f}x the simple null)")
    return " ".join(bits)


def build_writeup_messages(
    question: Any,
    snapshot: Any,
    context_packet: str,
    *,
    prior_probability: Any | None = None,
    delta: Any | None = None,
    evidence_only: bool = False,
) -> list[dict[str, str]]:
    framing = (
        "New evidence just landed and the probability was reaffirmed rather than moved. "
        "Write the note as a thinking update on what the new evidence does and does not change.\n\n"
        if evidence_only
        else ""
    )
    audit_summary = tail_audit_summary(snapshot)
    audit_block = (
        f"\n## Probability-Mass Audit\n{audit_summary}. In `be_aware`, name this "
        "unearned tail mass explicitly and say it should be priced through a mechanism "
        "or compressed — do not let the note imply those outcomes are live when the "
        "audit says they have no path.\n"
        if audit_summary
        else ""
    )
    user = (
        f"## Shared Ledger Context\n{context_packet}\n\n"
        f"## This Forecast\n"
        f"{framing}"
        f"Title: {getattr(question, 'title', '')}\n"
        f"Current probability or distribution: {getattr(snapshot, 'probability_or_distribution', None)}\n"
        f"Prior probability: {prior_probability}\n"
        f"Delta since last: {delta}\n"
        f"Confidence: {getattr(snapshot, 'confidence', None)}\n"
        f"Method: {getattr(snapshot, 'method', None)}\n"
        f"{audit_block}\n"
        f"## Task\nWrite the desk note covering the four angles. Return ONLY the JSON object."
    )
    return [
        {"role": "system", "content": WRITEUP_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def build_retrospective_messages(
    question: Any,
    snapshot: Any,
    resolution: Any,
    score: Any,
    postmortem: Any,
    context_packet: str,
    *,
    scope_adjustments: Any | None = None,
) -> list[dict[str, str]]:
    user = (
        f"## Shared Ledger Context\n{context_packet}\n\n"
        f"## Resolution\n"
        f"Outcome: {getattr(resolution, 'outcome', None)}\n"
        f"Final probability or forecast at close: {getattr(snapshot, 'probability_or_distribution', None)}\n"
        f"Score: brier={getattr(score, 'brier_score', None)} "
        f"log={getattr(score, 'log_score', None)} "
        f"proper={getattr(score, 'proper_score', None)} "
        f"rule={getattr(score, 'score_rule', None)} "
        f"bucket={getattr(score, 'calibration_bucket', None)}\n"
        f"Postmortem: {postmortem}\n"
        f"Domain-level recommended adjustments (not specific to this question): {scope_adjustments}\n\n"
        f"## Task\nWrite the closing retrospective. Return ONLY the JSON object."
    )
    return [
        {"role": "system", "content": RETRO_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_writeup_response(text: str) -> dict[str, Any] | None:
    """Parse the model JSON, tolerate fences/surrounding prose, sanitize fields.

    Returns a dict with the four angle fields, a synthesized multi-paragraph
    ``body``, a ``headline``, and ``stance``/``verdict`` when present, or
    ``None`` if nothing parseable came back.
    """

    if not text:
        return None
    raw = text.strip()
    if raw.startswith("```"):
        # ```json ... ``` or ``` ... ```
        parts = raw.split("```")
        raw = parts[1] if len(parts) >= 2 else raw
        raw = raw.lstrip("json").strip()
    obj: Any
    try:
        obj = json.loads(raw)
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            obj = json.loads(raw[start : end + 1])
        except Exception:
            return None
    if not isinstance(obj, dict):
        return None

    result: dict[str, Any] = {}
    result["headline"] = sanitize_writeup_text(str(obj.get("headline", "")))
    for key in _FIELD_KEYS:
        result[key] = sanitize_writeup_text(str(obj.get(key, "")))
    stance = obj.get("stance")
    if isinstance(stance, str) and stance.strip():
        result["stance"] = stance.strip()
    verdict = obj.get("verdict")
    if isinstance(verdict, str) and verdict.strip():
        result["verdict"] = verdict.strip()
    result["body"] = "\n\n".join(result[key] for key in _FIELD_KEYS if result[key])
    if not result["body"] and not result["headline"]:
        return None
    return result


def _numeric_delta(previous: Any, current: Any) -> float | None:
    """Scalar probability delta when both sides are plain numbers, else None."""

    if isinstance(previous, bool) or isinstance(current, bool):
        return None
    if isinstance(previous, (int, float)) and isinstance(current, (int, float)):
        return float(current) - float(previous)
    return None


def write_brief(
    ledger: Any,
    question_id: str,
    snapshot: Any,
    *,
    previous: Any | None = None,
    evidence_only: bool = False,
    main_runtime: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Generate and persist an analyst brief for a committed snapshot.

    Best-effort and never raises: a write-up failure must not roll back or block
    a forecast that was already committed. Returns the persisted note dict, or
    ``None`` when nothing was written (no snapshot, exploratory origin, or a
    generation/persist failure).
    """

    try:
        if snapshot is None:
            return None
        if getattr(snapshot, "forecast_origin", "live") in {"exploratory", "backtest"}:
            return None
        prior = getattr(previous, "probability_or_distribution", None) if previous is not None else None
        delta = _numeric_delta(prior, getattr(snapshot, "probability_or_distribution", None))
        note = generate_writeup(
            ledger,
            ledger.get_question(question_id),
            snapshot,
            kind="brief",
            prior_probability=prior,
            delta=delta,
            evidence_only=evidence_only,
            main_runtime=main_runtime,
        )
        if not note:
            return None
        return ledger.add_analyst_note(
            question_id=question_id,
            kind="brief",
            body=note["body"],
            headline=note.get("headline", ""),
            how_it_feels=note.get("how_it_feels", ""),
            how_it_thinks=note.get("how_it_thinks", ""),
            looking_for=note.get("looking_for", ""),
            be_aware=note.get("be_aware", ""),
            stance=note.get("stance"),
            forecast_id=getattr(snapshot, "forecast_id", None),
            as_of=getattr(snapshot, "as_of", None),
            probability_at_write=getattr(snapshot, "probability_or_distribution", None),
            confidence_at_write=getattr(snapshot, "confidence", None),
            agent_model=note.get("agent_model"),
            prompt_version=note.get("prompt_version"),
            generator="llm",
        )
    except Exception:
        return None


def write_retrospective(
    ledger: Any,
    question_id: str,
    *,
    score: Any | None = None,
    main_runtime: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Generate and persist the closing retrospective. Best-effort; never raises."""

    try:
        question = ledger.get_question(question_id)
        final = ledger.get_current_snapshot(question_id)
        if final is None:
            return None
        resolution = ledger.get_latest_resolution(question_id)
        postmortems = ledger.list_postmortems(question_id)
        profiles = ledger.list_domain_error_profiles(domain=question.domain) if getattr(question, "domain", None) else []
        adjustments = [adj for profile in profiles for adj in (profile.get("recommended_adjustments") or [])]
        note = generate_writeup(
            ledger,
            question,
            final,
            kind="retrospective",
            resolution=resolution,
            score=score,
            postmortem=postmortems[-1] if postmortems else None,
            scope_adjustments=adjustments or None,
            main_runtime=main_runtime,
        )
        if not note:
            return None
        return ledger.add_analyst_note(
            question_id=question_id,
            kind="retrospective",
            body=note["body"],
            headline=note.get("headline", ""),
            how_it_feels=note.get("how_it_feels", ""),
            how_it_thinks=note.get("how_it_thinks", ""),
            looking_for=note.get("looking_for", ""),
            be_aware=note.get("be_aware", ""),
            verdict=note.get("verdict"),
            forecast_id=getattr(final, "forecast_id", None),
            resolution_id=getattr(resolution, "id", None),
            probability_at_write=getattr(final, "probability_or_distribution", None),
            confidence_at_write=getattr(final, "confidence", None),
            agent_model=note.get("agent_model"),
            prompt_version=note.get("prompt_version"),
            generator="llm",
        )
    except Exception:
        return None


def generate_writeup(
    ledger: Any,
    question: Any,
    snapshot: Any,
    *,
    kind: str = "brief",
    resolution: Any | None = None,
    score: Any | None = None,
    postmortem: Any | None = None,
    prior_probability: Any | None = None,
    delta: Any | None = None,
    scope_adjustments: Any | None = None,
    evidence_only: bool = False,
    main_runtime: dict[str, Any] | None = None,
    temperature: float = 0.6,
    max_tokens: int = 800,
    timeout: float = 60.0,
) -> dict[str, Any] | None:
    """Generate an analyst write-up. Best-effort: returns ``None`` on any failure.

    Uses the centralized ``call_llm`` with ``task="forecast_writeup"`` so it
    inherits the configured forecasting provider/model (auto-resolving when no
    dedicated aux key is set). ``main_runtime`` lets the agent tool reuse the
    running model. Never raises.
    """

    try:
        from forecasting.protocol import build_context_packet

        context = build_context_packet(ledger, question, snapshot)
        from agent.auxiliary_client import call_llm

        if kind == "retrospective":
            messages = build_retrospective_messages(
                question,
                snapshot,
                resolution,
                score,
                postmortem,
                context,
                scope_adjustments=scope_adjustments,
            )
        else:
            messages = build_writeup_messages(
                question,
                snapshot,
                context,
                prior_probability=prior_probability,
                delta=delta,
                evidence_only=evidence_only,
            )
        response = call_llm(
            task="forecast_writeup",
            messages=messages,
            main_runtime=main_runtime,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        content = response.choices[0].message.content
        parsed = parse_writeup_response(content)
        if parsed is not None:
            model = getattr(response, "model", None)
            if model:
                parsed.setdefault("agent_model", str(model))
            parsed.setdefault("prompt_version", PROMPT_VERSION)
        return parsed
    except Exception:
        return None
