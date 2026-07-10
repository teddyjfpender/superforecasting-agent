"""Quorum panelist / judge / Delphi prompt builders (carved from ``quorum.py``).

The Wave-4 §W3.a ``prompts`` leaf: the panelist / reconcile / judge / Delphi
prompt-string builders and their private formatting helpers. Pure string
assembly — no I/O, no dispatch. Imported back into
:mod:`forecasting.quorum.core` (for ``run_quorum`` and the ``__all__`` surface)
and re-exported by the package façade, so ``from forecasting.quorum import
build_panelist_prompt`` is byte-for-byte unchanged.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from forecasting.panel import PanelAggregation
from forecasting.quorum.core import JudgeSynthesis, ModelForecast

# ── Prompt builders ──────────────────────────────────────────────────────────


_PANELIST_SYSTEM = (
    "You are a panelist on a superforecasting desk. Anchor on the status quo "
    "and the horizon, reason along causal PATHS (named links, not vibes), and "
    "forecast strictly from the information frontier — do not use any "
    "information you could not have known as of the evidence cutoff. Treat any "
    "single number (a market, a poll, a model) as a PRIOR to check, not the "
    "answer. Form your OWN independent view; you will not see other panelists' "
    "answers. Use web search to gather current evidence where it helps. "
    "Maintain a running BELIEF STATE: hold a probability from your very first "
    "prior and REVISE it after each piece of evidence you gather — naming, each "
    "time, the specific evidence that moved the number and by how much. Do not "
    "save all your judgement for the end; the number should walk the path of the "
    "evidence, and your FINAL belief is your committed forecast."
)

_PANELIST_USER_TEMPLATE = (
    "## Forecast Question\n{title}\n\n"
    "## Resolution Criteria\n{resolution}\n\n"
    "## Evidence Cutoff\n{cutoff}\n\n"
    "## Shared Ledger Context\n{context}\n\n"
    "## Submission\n"
    "Research independently, then return ONLY a JSON object with keys:\n"
    "- probability: number in [0, 1] for YES\n"
    "- confidence_low: number in [0, 1] (10th percentile)\n"
    "- confidence_high: number in [0, 1] (90th percentile)\n"
    "- rationale: one paragraph audit trail citing the evidence you used\n"
    "- reasons_up: array of 1-3 concrete links that push the probability higher\n"
    "- reasons_down: array of 1-3 concrete links that push it lower\n"
    "- change_my_mind: array of 1-3 observations that would force a material update\n"
    "- crux: one sentence naming the single biggest uncertainty\n"
    "- belief_trajectory: array of your belief REVISIONS in order, one entry per "
    "evidence step you took. Each entry is an object with: step (1-based integer), "
    "probability (your YES probability AFTER that step), confidence "
    '("low"/"medium"/"high"), evidence_for (array of strings), evidence_against '
    "(array of strings), open_questions (array of strings), and moved_by (one short "
    'line naming the specific evidence that moved the number, or "prior" for your '
    "starting point). Start with your prior and add a step whenever the evidence "
    "shifts your view. The LAST step's probability MUST equal your committed "
    "probability above — the final belief is the commit."
)


def build_panelist_prompt(
    *,
    question_title: str,
    resolution_criteria: str,
    context_packet: str,
    evidence_cutoff: str | None = None,
    sample_hint: int | None = None,
    market_anchor: float | None = None,
) -> dict[str, str]:
    """System + user prompts for one panelist model.

    ``market_anchor`` (FIX B — market-anchor discipline) is the current de-vigged
    market price for a market-linked question. When supplied it is SHOWN to the
    panelist as the outside-view prior (the market-as-prior doctrine): deviate only
    for a NAMED reason, never vibes.
    """

    user = _PANELIST_USER_TEMPLATE.format(
        title=question_title,
        resolution=resolution_criteria,
        cutoff=evidence_cutoff or "now (live forecast)",
        context=context_packet or "(no shared context supplied)",
    )
    if market_anchor is not None:
        user += (
            "\n\n## Outside-View Anchor (current market)\n"
            f"The market currently prices YES at {market_anchor:.3f}. Treat this as the "
            "OUTSIDE-VIEW PRIOR to interrogate, not an answer to copy. You may deviate, "
            "but only for a NAMED reason — specific private information or an edge the "
            "market has not yet priced — never on unsupported intuition."
        )
    if sample_hint is not None:
        # For self-fusion: nudge independent reasoning paths across samples
        # without leaking that it is the same model.
        user += (
            f"\n\n(Independent draft #{sample_hint}: reason from first "
            "principles; do not assume any particular prior answer.)"
        )
    return {"system": _PANELIST_SYSTEM, "user": user}


def build_reconcile_block(
    *,
    blind_probability: float,
    market_anchor: float,
    threshold_pp: float = 10.0,
) -> str:
    """The RECONCILE turn (UPGRADE 1 — blind-then-reconcile, phase 2).

    Appended as a second-turn message AFTER a panelist has committed its BLIND
    estimate (formed without ever seeing the market). It reveals the market anchor
    and the panelist's OWN blind number and asks it to reconcile — keep, converge,
    or hold against the market — naming the specific edge for any deviation past
    ``threshold_pp``. Deliberately does NOT re-state the question (the reconcile
    runs on the same session, so the model still has the full blind-turn context);
    the two-session fallback re-supplies it. The panelist returns the same JSON
    schema plus ``reconcile_reason``.
    """

    return (
        "\n\n## Market Reconciliation\n"
        f"Your BLIND estimate — formed WITHOUT seeing any market — was "
        f"{float(blind_probability):.4f}.\n"
        f"The market now prices YES at {float(market_anchor):.4f}. Treat the market as "
        "the OUTSIDE-VIEW PRIOR: a strong aggregator of already-priced information, not "
        "a number to reflexively copy. Reconcile your blind estimate with it — hold your "
        "number, converge toward it, or move further away — but if your reconciled "
        f"probability deviates more than {threshold_pp:.0f}pp from the market you MUST "
        "name the SPECIFIC edge (private information, or a signal the market has not yet "
        "priced) that justifies the deviation.\n"
        "Return ONLY the same JSON object as before (probability, confidence_low, "
        "confidence_high, rationale, reasons_up, reasons_down, change_my_mind, crux, "
        "belief_trajectory), plus:\n"
        "- reconcile_reason: the named edge justifying any material deviation from the "
        "market, or one sentence on why you converged to / held against it\n"
        "APPEND one final step to belief_trajectory recording this reconciliation "
        "(moved_by naming the outside-view anchor) and re-emit the full trajectory so "
        "its last step is your reconciled commit."
    )


_JUDGE_SYSTEM = (
    "You are the JUDGE of a superforecasting quorum. You receive a panel of "
    "independent model forecasts and a pooled aggregate. Your job is the "
    "synthesis step: identify CONSENSUS points, CONTRADICTIONS between "
    "panelists, partial coverage, unique insights, and BLIND SPOTS the panel "
    "shares. Then write a final senior-desk synthesis that respects the "
    "forecasting protocol: paths not vibes, information frontier inviolable, "
    "the pooled number is a prior to interrogate. Do not simply average — "
    "explain where the panel is right, where it is fragile, and what single "
    "observation would move the answer."
)


def build_judge_prompt(
    *,
    question_title: str,
    resolution_criteria: str,
    forecasts: Sequence[ModelForecast],
    aggregation: PanelAggregation,
    disagreement: Mapping[str, Any],
    market_anchor: float | None = None,
    market_anchor_threshold_pp: float = 10.0,
) -> dict[str, str]:
    """System + user prompts for the judge synthesis pass.

    ``market_anchor`` (FIX B — market-anchor discipline) makes the judge accountable
    to the outside view: when a de-vigged market price is supplied, the judge is told
    that deviating more than ``market_anchor_threshold_pp`` from it REQUIRES an explicit
    named edge (private information the market has not priced), returned in the
    ``market_deviation_justification`` field — otherwise the committed verdict is pulled
    back toward the market. This inverts the failure mode where the judge discounted the
    market with no justification (the Alaska run) — the doctrine is market-as-prior."""

    lines: list[str] = []
    for f in forecasts:
        if f.error is not None:
            continue
        lines.append(
            f"### {f.model}\n"
            f"- probability: {f.probability:.4f}"
            + (
                f" (80% CI {f.confidence_low:.3f}–{f.confidence_high:.3f})"
                if f.confidence_low is not None and f.confidence_high is not None
                else ""
            )
            + "\n"
            f"- rationale: {f.rationale or '(none)'}\n"
            f"- reasons_up: {'; '.join(f.reasons_up) or '(none)'}\n"
            f"- reasons_down: {'; '.join(f.reasons_down) or '(none)'}\n"
            f"- change_my_mind: {'; '.join(f.change_my_mind) or '(none)'}\n"
            f"- crux: {f.crux or '(none)'}"
        )
    panel_block = "\n\n".join(lines) or "(no successful panelist forecasts)"
    spread = aggregation.spread
    anchor_block = ""
    anchor_key = ""
    if market_anchor is not None:
        anchor_block = (
            f"## Outside-View Anchor (current market)\n"
            f"- de-vigged market price (YES): {market_anchor:.4f}\n"
            f"- deviation discipline: the committed verdict may deviate more than "
            f"{market_anchor_threshold_pp:.0f}pp from this price ONLY with a specific, "
            f"named edge the market has not priced. Absent that, your number will be "
            f"pulled back toward the market. Treat the price as the prior to beat, "
            f"not a number to discount.\n\n"
        )
        anchor_key = (
            "- market_deviation_justification: if your probability deviates more than "
            f"{market_anchor_threshold_pp:.0f}pp from the market price "
            f"({market_anchor:.4f}), you MUST name the specific private information or "
            "market-unpriced edge that justifies the deviation; otherwise return an empty "
            'string "" and your number will be pulled toward the market\n'
        )
    user = (
        f"## Forecast Question\n{question_title}\n\n"
        f"## Resolution Criteria\n{resolution_criteria}\n\n"
        f"{anchor_block}"
        f"## Pooled Aggregate\n"
        f"- method: {aggregation.method} (trim={aggregation.trim})\n"
        f"- aggregate_probability: {aggregation.aggregate_probability:.4f}\n"
        f"- spread: min={spread.get('min')}, median={spread.get('median')}, "
        f"max={spread.get('max')}, IQR={spread.get('iqr')}\n"
        f"- disagreement: index={disagreement.get('disagreement_index')} "
        f"({disagreement.get('disagreement_band')}), "
        f"sd_logit={disagreement.get('sd_logit')}\n\n"
        f"## Panel Forecasts\n{panel_block}\n\n"
        "## Synthesis\n"
        "Return ONLY a JSON object with keys:\n"
        "- probability: your final number in [0, 1] (may differ from the pool "
        "if the panel shares a blind spot — justify any divergence)\n"
        f"{anchor_key}"
        "- directional_confidence: one of \"high\", \"medium\", \"low\" — how "
        "confident you are in YOUR REVISED probability above. Answer \"high\" "
        "ONLY when you have a specific, well-supported reason your number beats "
        "the pool (a named blind spot the panel shares, a decisive piece of "
        "evidence). A \"high\" reading lets your number OVERRIDE the pool as the "
        "committed forecast; \"medium\"/\"low\" defers to the pool. When in "
        "doubt, answer \"medium\".\n"
        "- rationale: one paragraph senior-desk synthesis\n"
        "- consensus: array of points the panel agrees on\n"
        "- contradictions: array of genuine disagreements and which side is "
        "better supported\n"
        "- reasons_up: array of the strongest links pushing the probability higher\n"
        "- reasons_down: array of the strongest links pushing it lower\n"
        "- change_my_mind: array of the load-bearing observations whose failure "
        "forces a material update\n"
        "- blind_spots: array of risks/angles no panelist covered (these become "
        "evidence gaps to research next)"
    )
    return {"system": _JUDGE_SYSTEM, "user": user}


# ── Delphi revision (anonymous reveal → private second round) ─────────────────
#
# The Delphi intervention is a PROCESS change, not a scoring change: after the
# sealed round the panel sees an ANONYMOUS summary of the group's spread and the
# judge's contradictions/blind-spots, then privately revises. The summary must
# NEVER leak model identities ("Claude said", "GPT said") or the judge's preferred
# number as an authority — only the distribution, the disagreement band, and the
# anonymous strongest arguments. The prompt explicitly forbids deferring to the
# median so a panelist moves only when an argument or fresh evidence changed its view.


_DELPHI_REVISION_INSTRUCTIONS = (
    "Revise privately. Do not defer to the median. Move your probability only if "
    "the anonymous arguments or fresh evidence changed your view. If you keep the "
    "same probability, say why.\n\n"
    "Return ONLY the same JSON object as round 1 (probability, confidence_low, "
    "confidence_high, rationale, reasons_up, reasons_down, change_my_mind, crux), "
    "plus optional:\n"
    "- revision_reason: one sentence explaining what changed or why you held steady"
)


def _fmt_prob(value: Any) -> str:
    """Format a spread scalar to 3dp, tolerating missing/garbage values."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "n/a"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "n/a"


def _dedup_capped(lists: Sequence[Sequence[str]], *, cap: int = 6) -> list[str]:
    """Union of the given string lists, order-preserving, case-insensitively
    de-duplicated, capped at ``cap`` — for the anonymous reasons roll-up."""

    seen: set[str] = set()
    out: list[str] = []
    for lst in lists:
        for item in lst or []:
            s = str(item).strip()
            key = s.lower()
            if not s or key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= cap:
                return out
    return out


def _join_or_none(items: Sequence[str]) -> str:
    return "; ".join(items) if items else "(none)"


def _render_fresh_evidence(evidence: Sequence[Mapping[str, Any]]) -> str:
    """One-line-per-item rendering of supervisor-search evidence (tolerant of the
    ``{title, summary, source}`` / ``{claim, text, url}`` shapes)."""

    pieces: list[str] = []
    for item in evidence or []:
        title = str(item.get("title") or item.get("claim") or "").strip()
        summary = str(item.get("summary") or item.get("text") or "").strip()
        if title and summary:
            piece = f"{title}: {summary}"
        else:
            piece = title or summary
        if piece:
            pieces.append(piece)
    return "; ".join(pieces) if pieces else "(none)"


def build_delphi_summary(
    *,
    forecasts: Sequence[ModelForecast],
    aggregation: PanelAggregation,
    disagreement: Mapping[str, Any],
    judge: JudgeSynthesis | None,
    supervisor_evidence: Sequence[Mapping[str, Any]],
) -> str:
    """The ANONYMOUS first-round reveal handed to every revision-round panelist.

    Emits the distribution summary (min/p25/median/p75/max), the disagreement band,
    the anonymous strongest reasons up/down, the judge's contradictions and shared
    blind-spots, and any fresh supervisor evidence. It deliberately contains NO
    model identity and NO named ordering — the whole point of Delphi is that the
    panelist revises against arguments, not against who said them.
    """

    ok = [f for f in forecasts if f.error is None]
    spread = aggregation.spread
    reasons_up = _dedup_capped(
        [judge.reasons_up if judge else [], *[f.reasons_up for f in ok]]
    )
    reasons_down = _dedup_capped(
        [judge.reasons_down if judge else [], *[f.reasons_down for f in ok]]
    )
    contradictions = list(judge.contradictions) if judge else []
    blind_spots = list(judge.blind_spots) if judge else []
    lines = [
        "Anonymous first-round panel summary:",
        (
            "- probability distribution: "
            f"min={_fmt_prob(spread.get('min'))}, "
            f"p25={_fmt_prob(spread.get('p25'))}, "
            f"median={_fmt_prob(spread.get('median'))}, "
            f"p75={_fmt_prob(spread.get('p75'))}, "
            f"max={_fmt_prob(spread.get('max'))}"
        ),
        (
            "- disagreement: "
            f"{disagreement.get('disagreement_band', 'n/a')} "
            f"(index={disagreement.get('disagreement_index', 'n/a')})"
        ),
        f"- strongest reasons for YES: {_join_or_none(reasons_up)}",
        f"- strongest reasons for NO: {_join_or_none(reasons_down)}",
        f"- contradictions: {_join_or_none(contradictions)}",
        f"- shared blind spots: {_join_or_none(blind_spots)}",
        f"- fresh evidence added after round 1: {_render_fresh_evidence(supervisor_evidence)}",
    ]
    return "\n".join(lines)


def build_revision_context_block(
    *, prior: ModelForecast | None, delphi_summary: str
) -> str:
    """The ``## Delphi Revision Context`` block appended to a panelist's round-1
    prompt for the private revision round: its OWN prior (probability/crux/
    rationale) followed by the shared ANONYMOUS ``delphi_summary`` and the
    do-not-defer-to-the-median instructions."""

    if prior is not None:
        own_prob = f"{prior.probability:.4f}"
        own_crux = prior.crux or "(none)"
        own_rationale = prior.rationale or "(none)"
    else:
        own_prob = "(unavailable)"
        own_crux = "(none)"
        own_rationale = "(none)"
    return (
        "\n\n## Delphi Revision Context\n"
        "You previously forecast:\n"
        f"- probability: {own_prob}\n"
        f"- crux: {own_crux}\n"
        f"- rationale: {own_rationale}\n\n"
        f"{delphi_summary}\n\n"
        f"{_DELPHI_REVISION_INSTRUCTIONS}"
    )


def _delphi_audit_round(
    *,
    round_index: int,
    forecasts: Sequence[ModelForecast],
    aggregation: PanelAggregation,
    disagreement: Mapping[str, Any],
    judge: JudgeSynthesis | None,
) -> dict[str, Any]:
    """Compact, JSON-serializable snapshot of one Delphi round for ``delphi_audit``.

    Stores the round's aggregate, its disagreement signal, the judge's
    consensus/contradictions/blind-spots, and the per-seat (participant) forecasts
    that fed the aggregate — enough to reconstruct the round-1 → round-2 movement
    without re-running anything, and without bloating ``panel_estimates`` (which
    stays scoped to the FINAL round's aggregate)."""

    ok = [f for f in forecasts if f.error is None]
    return {
        "round_index": round_index,
        "aggregate_probability": round(aggregation.aggregate_probability, 6),
        "disagreement": dict(disagreement),
        "judge": (
            {
                "consensus": list(judge.consensus),
                "contradictions": list(judge.contradictions),
                "blind_spots": list(judge.blind_spots),
            }
            if judge is not None
            else None
        ),
        "forecasts": [
            {
                "participant_id": f.participant_id,
                "model": f.model,
                "probability": f.probability,
                "confidence_low": f.confidence_low,
                "confidence_high": f.confidence_high,
                "crux": f.crux,
                "reasons_up": list(f.reasons_up),
                "reasons_down": list(f.reasons_down),
                "change_my_mind": list(f.change_my_mind),
            }
            for f in ok
        ],
    }
