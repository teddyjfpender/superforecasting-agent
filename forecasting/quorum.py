"""Quorum — a model-diverse forecast panel with a judge synthesis step.

Where :mod:`forecasting.panel` runs one model under five constrained
*role* framings (outside / inside / market / red-team / sanity), the quorum
runs the *same* forecasting brief across a panel of independent **models**
(e.g. ``openai/gpt-5.5`` + ``google/gemini-3-flash`` + ``deepseek/deepseek-v4``
via the OpenRouter gateway), then a designated *judge* model reads every
response and synthesises a final, senior-process answer.

This is the superforecaster analogue of OpenRouter's "Fusion": parallel
dispatch → independent analysis → judge synthesis → grounded final answer.
Two findings shape the design:

  * **Model diversity** lifts accuracy over any single frontier model, and
  * **the synthesis step itself** carries a meaningful chunk of the lift —
    a model paired with *itself* still gains, because the judge pass forces
    consensus/contradiction/blind-spot reasoning. So a quorum is worth
    running even with a single provider key (``self`` preset, N samples).

The quorum is a *sibling* of the perspective panel, not a replacement: both
flow through :func:`forecasting.panel.aggregate_panel_estimates` and are
persisted via ``ledger.record_panel_run`` with ``triggered_by="quorum"`` so
model-disagreement stays attributable separately from role-disagreement. The
judge's structured output maps onto the senior process's required snapshot
fields (``reasons_up`` / ``reasons_down`` / ``change_my_mind``), and the
``blind_spots`` it surfaces become evidence gaps.

This module is deliberately runtime-agnostic: the model dispatch is an
injectable ``runner`` callable (mirroring ``agent_protocol.AgentProtocolRunner``)
so the orchestration is unit-testable without real API calls. The default
runner builds an :class:`run_agent.AIAgent` per model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Sequence

from forecasting.agent_protocol import parse_agent_protocol_response
from forecasting.models import ValidationError
from forecasting.panel import (
    PanelAggregation,
    aggregate_panel_estimates,
    disagreement_signal,
)


# The judge's self-reported confidence in its REVISED probability. Only a
# ``'high'`` reading lets the judge override the pool (AIA P0.3); anything else
# (and the back-compat default) keeps the committed number on the sound pool.
DirectionalConfidence = Literal["high", "medium", "low"]
_VALID_DIRECTIONAL_CONFIDENCE = frozenset({"high", "medium", "low"})


# ── Runner seam ──────────────────────────────────────────────────────────────

# A runner takes (model_id, system_prompt, user_prompt) and returns the model's
# raw text response. Injectable so tests can stub it; the default builds an
# AIAgent routed through OpenRouter with web search enabled (each panelist
# researches independently, matching the Fusion design).
QuorumRunner = Callable[[str, str, str], str]


DEFAULT_JUDGE_MODEL = "anthropic/claude-opus-4-8"

# When ``run_quorum`` is called without an explicit ``max_concurrency`` the whole
# panel is dispatched in one wave, bounded by this cap so a very wide panel does
# not spawn an unreasonable number of concurrent LLM calls.
_AUTO_CONCURRENCY_CAP = 8

# Built-in presets mirror the Fusion blog's panels. ``self`` is the
# single-provider self-fusion config — the model list is filled in at runtime
# from the active model, repeated ``samples`` times.
QUORUM_PRESETS: dict[str, dict[str, Any]] = {
    "frontier": {
        "models": ("anthropic/claude-opus-4-8", "openai/gpt-5.5"),
        "judge": "anthropic/claude-opus-4-8",
        "description": "Frontier panel — highest quality, highest cost.",
    },
    "budget": {
        "models": (
            "google/gemini-3-flash",
            "moonshotai/kimi-k2.6",
            "deepseek/deepseek-v4-pro",
        ),
        "judge": "google/gemini-3-flash",
        "description": "Budget panel — beats frontier solo at ~half the cost.",
    },
    "self": {
        # Filled from the active model at runtime; samples controls repeats.
        "models": (),
        "samples": 3,
        "judge": None,  # default to the sampled model
        "description": "Self-fusion — one model sampled N times; the lift "
        "comes from the judge synthesis, so it needs only one provider key.",
    },
    "wide": {
        # AIA P1.4 OPT-IN variance-reduction preset: ~10 mixed-model draws.
        # The ensemble-size curve (quorum_analysis.bootstrap_ensemble_curve)
        # shows Brier variance falls sharply to roughly k~=5 then plateaus, so
        # ~10 draws sits comfortably past the knee. NOT a default — the live
        # default preset stays 'frontier' and the 'self' default sample count
        # stays 3. Choose this explicitly (--preset wide) when you want the
        # variance floor and can pay for ~10 calls.
        "models": (
            "anthropic/claude-opus-4-8",
            "openai/gpt-5.5",
            "google/gemini-3-flash",
            "moonshotai/kimi-k2.6",
            "deepseek/deepseek-v4-pro",
            "anthropic/claude-opus-4-8",
            "openai/gpt-5.5",
            "google/gemini-3-flash",
            "moonshotai/kimi-k2.6",
            "deepseek/deepseek-v4-pro",
        ),
        "judge": "anthropic/claude-opus-4-8",
        "description": "Wide panel (AIA P1.4) — ~10 mixed-model draws past the "
        "variance-reduction knee. Opt-in only; highest cost.",
    },
}


# ── Result types ─────────────────────────────────────────────────────────────


@dataclass
class ModelForecast:
    """A single panelist model's parsed forecast."""

    model: str
    probability: float
    confidence_low: float | None = None
    confidence_high: float | None = None
    rationale: str = ""
    reasons_up: list[str] = field(default_factory=list)
    reasons_down: list[str] = field(default_factory=list)
    change_my_mind: list[str] = field(default_factory=list)
    crux: str | None = None
    weight: float = 1.0
    error: str | None = None  # set when the model failed; excluded from pooling
    # Delphi identity/provenance (default to the non-delphi single-round state so
    # a delphi_rounds==0 quorum is unchanged): ``participant_id`` is the panel SEAT
    # (``p01``…), stable across rounds and distinct from ``model`` because the
    # ``self`` preset repeats one model; ``round_index`` is 1 for the sealed round
    # and 2 for the private revision round; ``prior_probability`` is this seat's
    # round-1 number (set only on the revision round); ``revision_reason`` is the
    # panelist's optional one-liner on what moved (or held) its view.
    participant_id: str | None = None
    round_index: int = 1
    prior_probability: float | None = None
    revision_reason: str | None = None

    def to_estimate(self) -> dict[str, Any]:
        """Shape this forecast as a panel estimate for ``aggregate_panel_estimates``."""

        return {
            "perspective": self.model,
            "agent_model": self.model,
            "probability": self.probability,
            "weight": self.weight,
            "confidence_low": self.confidence_low,
            "confidence_high": self.confidence_high,
            "rationale": self.rationale,
            "reasons_up": self.reasons_up,
            "reasons_down": self.reasons_down,
            "change_my_mind": self.change_my_mind,
            "crux": self.crux,
            "metadata": {
                "source": f"quorum:{self.model}",
                "participant_id": self.participant_id,
                "round_index": self.round_index,
                "prior_probability": self.prior_probability,
                "revision_reason": self.revision_reason,
            },
        }


@dataclass
class JudgeSynthesis:
    """The judge model's structured synthesis over the panel.

    ``directional_confidence`` (AIA P0.3) is the judge's self-report of how
    confident it is in its REVISED probability. It defaults to ``'medium'`` so
    every historical/back-compat construction is non-overriding: only a
    self-declared ``'high'`` reading lets the judge's number replace the pool as
    the committed value (see :func:`resolve_final_probability`). This bounds the
    downside — a hedging judge can never drag a sound pool off-target.

    ``information_gap`` + ``clarifying_queries`` (AIA P1.1) are the
    agentic-supervisor signal: the judge can flag an UNRESOLVED CRUX it could not
    settle from the panel's evidence and request fresh searches. They drive
    :func:`should_research` / the optional :func:`run_quorum` research loop. Both
    default to the non-triggering values (``False`` / ``[]``) so every historical
    construction and the default (no ``search_runner``) path is unaffected.
    """

    probability: float | None
    rationale: str
    reasons_up: list[str] = field(default_factory=list)
    reasons_down: list[str] = field(default_factory=list)
    change_my_mind: list[str] = field(default_factory=list)
    blind_spots: list[str] = field(default_factory=list)
    consensus: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    judge_model: str | None = None
    directional_confidence: DirectionalConfidence = "medium"
    information_gap: bool = False
    clarifying_queries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "probability": self.probability,
            "rationale": self.rationale,
            "reasons_up": self.reasons_up,
            "reasons_down": self.reasons_down,
            "change_my_mind": self.change_my_mind,
            "blind_spots": self.blind_spots,
            "consensus": self.consensus,
            "contradictions": self.contradictions,
            "judge_model": self.judge_model,
            "directional_confidence": self.directional_confidence,
            "information_gap": self.information_gap,
            "clarifying_queries": self.clarifying_queries,
        }


@dataclass
class QuorumResult:
    """Everything a ``forecast update`` needs to commit a quorum-backed snapshot.

    ``final_probability`` is the number that gets COMMITTED (post terminal-Platt,
    post confidence-gated judge override) — the single source of truth for the
    whole pipeline. ``final_source`` records which branch won (``'pool'`` or
    ``'judge_high'``). ``aggregate_probability`` remains the (calibrated) pool
    scalar; before P0.3 the desk silently committed the pool, so when
    ``final_source == 'pool'`` the two agree exactly.
    """

    question_id: str | None
    forecasts: list[ModelForecast]
    aggregation: PanelAggregation
    disagreement: dict[str, Any]
    judge: JudgeSynthesis | None
    pool_method: str
    trim: int
    judge_model: str | None = None
    final_probability: float | None = None
    final_source: str = "pool"
    # AIA P1.1 — agentic supervisor fresh-search loop. ``research_rounds`` counts
    # how many fresh-search re-syntheses ran (0 on the default / no-search_runner
    # path); ``supervisor_evidence`` holds the fresh evidence items the search
    # runner returned across those rounds. Both default to the no-loop state so
    # the in-memory result and the persisted panel_run match a baseline run.
    research_rounds: int = 0
    supervisor_evidence: list[dict[str, Any]] = field(default_factory=list)
    # Delphi-revision provenance. ``delphi_rounds`` is 0 on the default (un-delphi)
    # path and 1 when a single private revision round ran; ``delphi_audit`` holds the
    # compact, serializable per-round record (``{"rounds": [...], "revision_context":
    # {...}}``) preserving the sealed round-1 estimates the final aggregate replaced.
    # Both default to the no-delphi state so a delphi_rounds==0 result is byte-identical.
    delphi_rounds: int = 0
    delphi_audit: dict[str, Any] = field(default_factory=dict)
    # Panel-integrity labeling (item 3). A quorum needs >=2 surviving panelist
    # forecasts to be a genuine PANEL; when only one survives (the rest errored),
    # the aggregate is a lone survivor dressed as a panel. We do NOT change the
    # aggregation math — a single estimate still aggregates to itself — but we label
    # the result HONESTLY so the desk (and the persisted job) can flag it rather
    # than treat one model's number as multi-model fusion. Defaults to the healthy
    # (non-degraded) state so an ordinary >=2-survivor run is unchanged.
    degraded: bool = False
    degraded_reason: str | None = None
    # Track-record weighting (S7): the {model: weight} map actually applied to the
    # panelists (empty on the default/cold-start path so an equal-weighted run is
    # byte-compatible with pre-S7 readers). Echoed so the operator SEES why a
    # weighted pool moved off the bare mean.
    model_weights_used: dict[str, float] = field(default_factory=dict)

    @property
    def aggregate_probability(self) -> float:
        return self.aggregation.aggregate_probability

    @property
    def committed_probability(self) -> float:
        """The number to persist/commit: the resolved final, or the pool if
        a pre-P0.3 result never resolved one (back-compat)."""

        return (
            self.final_probability
            if self.final_probability is not None
            else self.aggregation.aggregate_probability
        )

    @property
    def ok_forecasts(self) -> list[ModelForecast]:
        return [f for f in self.forecasts if f.error is None]

    def panel_estimates(self) -> list[dict[str, Any]]:
        """Estimates payload for ``ledger.record_panel_run`` / ``aggregate_panel_estimates``."""

        return [f.to_estimate() for f in self.ok_forecasts]

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "pool_method": self.pool_method,
            "trim": self.trim,
            "aggregate_probability": round(self.aggregate_probability, 6),
            "final_probability": round(self.committed_probability, 6),
            "final_source": self.final_source,
            "disagreement": self.disagreement,
            "judge_model": self.judge_model,
            "research_rounds": self.research_rounds,
            "supervisor_evidence": self.supervisor_evidence,
            # Delphi provenance (additive; 0 / {} on the default un-delphi path so a
            # delphi_rounds==0 result stays byte-compatible with pre-Delphi readers).
            "delphi_rounds": self.delphi_rounds,
            "delphi_audit": self.delphi_audit,
            # Panel-integrity labeling (item 3): honest flag when <2 panelists
            # survived, so a lone-survivor aggregate is never read as a panel.
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            # Track-record weighting (S7): the applied {model: weight} map (empty on
            # the default equal-weight path so the payload stays byte-compatible).
            "model_weights_used": self.model_weights_used,
            "judge": self.judge.to_dict() if self.judge else None,
            "forecasts": [
                {
                    "model": f.model,
                    "probability": f.probability,
                    "confidence_low": f.confidence_low,
                    "confidence_high": f.confidence_high,
                    "weight": f.weight,
                    "crux": f.crux,
                    "error": f.error,
                }
                for f in self.forecasts
            ],
        }


# ── Prompt builders ──────────────────────────────────────────────────────────


_PANELIST_SYSTEM = (
    "You are a panelist on a superforecasting desk. Anchor on the status quo "
    "and the horizon, reason along causal PATHS (named links, not vibes), and "
    "forecast strictly from the information frontier — do not use any "
    "information you could not have known as of the evidence cutoff. Treat any "
    "single number (a market, a poll, a model) as a PRIOR to check, not the "
    "answer. Form your OWN independent view; you will not see other panelists' "
    "answers. Use web search to gather current evidence where it helps."
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
    "- crux: one sentence naming the single biggest uncertainty"
)


def build_panelist_prompt(
    *,
    question_title: str,
    resolution_criteria: str,
    context_packet: str,
    evidence_cutoff: str | None = None,
    sample_hint: int | None = None,
) -> dict[str, str]:
    """System + user prompts for one panelist model."""

    user = _PANELIST_USER_TEMPLATE.format(
        title=question_title,
        resolution=resolution_criteria,
        cutoff=evidence_cutoff or "now (live forecast)",
        context=context_packet or "(no shared context supplied)",
    )
    if sample_hint is not None:
        # For self-fusion: nudge independent reasoning paths across samples
        # without leaking that it is the same model.
        user += (
            f"\n\n(Independent draft #{sample_hint}: reason from first "
            "principles; do not assume any particular prior answer.)"
        )
    return {"system": _PANELIST_SYSTEM, "user": user}


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
) -> dict[str, str]:
    """System + user prompts for the judge synthesis pass."""

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
    user = (
        f"## Forecast Question\n{question_title}\n\n"
        f"## Resolution Criteria\n{resolution_criteria}\n\n"
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


# ── Parsing ──────────────────────────────────────────────────────────────────


def parse_panelist_response(response: Any, model: str) -> ModelForecast:
    """Parse one panelist's JSON response into a :class:`ModelForecast`.

    Reuses the robust JSON extraction from :mod:`agent_protocol` (handles
    fenced blocks and surrounding prose). Raises :class:`ValidationError` with
    the model name on a bad response so the caller can record it as an errored
    panelist rather than aborting the whole quorum.
    """

    try:
        parsed = parse_agent_protocol_response(response)
    except ValueError as exc:
        raise ValidationError(f"{model}: {exc}") from exc
    payload = _reparse_full(response)
    return ModelForecast(
        model=model,
        probability=float(parsed["probability"]),
        confidence_low=_opt_prob(payload.get("confidence_low")),
        confidence_high=_opt_prob(payload.get("confidence_high")),
        rationale=str(parsed.get("rationale") or ""),
        reasons_up=_str_list(payload.get("reasons_up")),
        reasons_down=_str_list(payload.get("reasons_down")),
        change_my_mind=_str_list(payload.get("change_my_mind")),
        crux=(str(payload["crux"]).strip() if payload.get("crux") else None),
    )


def parse_judge_response(response: Any, judge_model: str | None) -> JudgeSynthesis:
    payload = _reparse_full(response)
    prob = _opt_prob(payload.get("probability"))
    return JudgeSynthesis(
        probability=prob,
        rationale=str(payload.get("rationale") or "").strip(),
        reasons_up=_str_list(payload.get("reasons_up")),
        reasons_down=_str_list(payload.get("reasons_down")),
        change_my_mind=_str_list(payload.get("change_my_mind")),
        blind_spots=_str_list(payload.get("blind_spots")),
        consensus=_str_list(payload.get("consensus")),
        contradictions=_str_list(payload.get("contradictions")),
        judge_model=judge_model,
        directional_confidence=_normalize_confidence(
            payload.get("directional_confidence")
        ),
        information_gap=_coerce_bool(payload.get("information_gap")),
        clarifying_queries=_str_list(payload.get("clarifying_queries")),
    )


def _coerce_bool(value: Any) -> bool:
    """Tolerant truthy parse for the judge's information_gap flag.

    Accepts a real bool, common string tokens (``true``/``yes``/``1``), or a
    number; anything missing/garbage collapses to ``False`` (the non-triggering
    default) so a malformed judge response can never spuriously start a research
    round.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # NaN != 0 is True; guard it so garbage collapses to False as intended.
        return value == value and value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1"}
    return False


def _normalize_confidence(value: Any) -> DirectionalConfidence:
    """Coerce a judge's self-reported confidence to a valid label.

    Tolerant by design: any missing/unknown/garbage value collapses to
    ``'medium'`` — the non-overriding default — so a malformed judge response
    can never accidentally trip the override gate.
    """

    if isinstance(value, str):
        token = value.strip().lower()
        if token in _VALID_DIRECTIONAL_CONFIDENCE:
            return token  # type: ignore[return-value]
    return "medium"


def _reparse_full(response: Any) -> dict[str, Any]:
    """Get the full JSON object (agent_protocol's parser keeps only some keys)."""

    from forecasting.agent_protocol import _coerce_json_response

    try:
        return _coerce_json_response(response)
    except ValueError:
        return {}


def _opt_prob(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        p = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        return None
    return p


def _str_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = raw.splitlines() if "\n" in raw else [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return []
    return [str(item).strip() for item in items if str(item).strip()]


# ── Orchestration ────────────────────────────────────────────────────────────


def resolve_models(
    preset: str | None,
    models: Sequence[str] | None,
    *,
    active_model: str | None = None,
) -> tuple[list[str], str | None]:
    """Resolve the panelist model list + judge from a preset and/or overrides.

    Explicit ``models`` always win. Otherwise a named preset is expanded; the
    ``self`` preset fills its model list from ``active_model`` repeated
    ``samples`` times. Returns ``(models, judge_model_or_None)``.
    """

    if models:
        return list(models), None
    if not preset:
        preset = "frontier"
    spec = QUORUM_PRESETS.get(preset)
    if spec is None:
        raise ValidationError(
            f"unknown quorum preset '{preset}'. Known: "
            + ", ".join(sorted(QUORUM_PRESETS))
        )
    judge = spec.get("judge")
    if preset == "self":
        if not active_model:
            raise ValidationError(
                "the 'self' preset needs an active model to sample; pass --models "
                "or set a default model"
            )
        samples = int(spec.get("samples", 3))
        return [active_model] * samples, judge or active_model
    return list(spec["models"]), judge


def quorum_auto_indicated(
    config: Mapping[str, Any] | None,
    *,
    panel_indicated: bool,
    has_prior_snapshot: bool,
) -> bool:
    """Decide whether a quorum should auto-run at the update stage.

    Honours the user's ``quorum.default_enabled`` / ``quorum.default_scope``
    config. The quorum rides the *existing* deliberative-panel trigger
    (``panel_indicated`` is :func:`forecasting.panel.should_run_panel`) so a
    quorum never fires where a panel wouldn't, keeping the multi-model spend
    bounded — unless the user widens the scope to ``always``.

      * ``high_impact`` (default) — only when a panel is already indicated
        (high-impact or first forecast).
      * ``first_only`` — only the first forecast for a question.
      * ``always`` — every probability-bearing update.
    """

    cfg = dict(config or {})
    if not cfg.get("default_enabled"):
        return False
    scope = str(cfg.get("default_scope", "high_impact"))
    if scope == "always":
        return True
    if scope == "first_only":
        return not has_prior_snapshot
    return bool(panel_indicated)  # high_impact


# ── Autonomy: default resolution, provider reality, cost bounding ─────────────
#
# One-size-fits-all quorum defaults are wrong: a high-impact contested question
# deserves a wide/frontier panel with a Delphi revision round; a routine update
# should stay cheap (self-fusion, no revision). resolve_quorum_defaults maps the
# question's IMPACT (and its question_type) onto a preset/delphi/trim triple, then
# two guards keep the choice honest and bounded: the single-key reality guard
# (item 3 — never resolve a multi-provider preset when only one provider key is
# reachable) and the max_calls cost cap (item 4 — downgrade a preset whose
# pre-run call estimate blows the budget).


def available_provider_slugs() -> set[str] | None:
    """Authenticated LLM-provider slugs, or ``None`` when detection is unavailable.

    Reuses the same :func:`hermes_cli.models.list_available_providers` seam the
    ``/model`` picker uses (which itself checks ``get_auth_status`` / the
    ``OPENROUTER_API_KEY``). Returning ``None`` on any failure is the FAIL-OPEN
    signal: an unknown provider picture must never spuriously downgrade a panel to
    self-fusion — the guards below treat ``None`` as "assume reachable".
    """

    try:
        from hermes_cli.models import list_available_providers

        slugs = {
            str(p.get("id"))
            for p in list_available_providers()
            if p.get("authenticated")
        }
    except Exception:  # noqa: BLE001 — detection is best-effort; unknown ⇒ fail-open
        return None
    # An EMPTY set is indistinguishable from "detection is unreliable here" (no
    # host creds, a sandboxed test, etc.), so treat it as UNKNOWN (fail-open) rather
    # than "single/zero key" — otherwise we would spuriously downgrade every panel
    # to self-fusion. Only a POSITIVELY detected provider picture guards the panel.
    return slugs or None


def _model_reachable(model: str, available: set[str]) -> bool:
    """Whether one ``vendor/model`` id can be served given the available providers.

    A bare id (no ``vendor/`` prefix) routes through the active provider, so it is
    assumed reachable. A prefixed id (``anthropic/…``) is reachable when that
    vendor's provider is authenticated — matched LENIENTLY, since a provider slug
    may carry a suffix (``openai`` ⇄ ``openai-codex``). (OpenRouter — a universal
    server — is handled by the caller as a short-circuit.)
    """

    if "/" not in model:
        return True
    prefix = model.split("/", 1)[0].strip().lower()
    return any(
        prefix == a or a.startswith(prefix) or prefix.startswith(a) for a in available
    )


def models_reachable(models: Sequence[str], available: set[str] | None) -> bool:
    """True when the panel can plausibly be served by the available providers.

    This is deliberately the CONSERVATIVE *single-key* guard the task calls for —
    it only rejects a multi-provider panel when we POSITIVELY know the host has a
    lone (non-OpenRouter) provider that cannot serve every model. Anything less
    certain fails OPEN (keeps the panel), because the vendor-prefix→slug mapping is
    too coarse to reject on:

      * ``available is None`` (detection unavailable / empty) ⇒ ``True``.
      * an OpenRouter key (universal server) ⇒ ``True``.
      * two-or-more distinct providers authenticated ⇒ ``True`` (not a single-key
        host; individual unreachable panelists simply error and the run is labeled
        degraded rather than mis-downgraded here).
      * exactly ONE provider ⇒ reachable only if every model maps to it.
    """

    if available is None:
        return True
    if "openrouter" in available:
        return True
    if len(available) >= 2:
        return True
    return all(_model_reachable(m, available) for m in models)


def preset_model_count(preset: str | None, *, samples: int = 3) -> int:
    """Number of panelist calls a preset issues per round (excludes the judge).

    ``self`` samples the active model ``samples`` times; every other preset uses
    its fixed model list. Unknown presets fall back to 1 (a single model)."""

    if preset == "self":
        return max(1, int(samples))
    spec = QUORUM_PRESETS.get(preset or "")
    if not spec:
        return 1
    if preset == "self":  # defensive; handled above
        return max(1, int(spec.get("samples", samples)))
    return max(1, len(spec.get("models", ())))


def estimate_quorum_calls(
    *, model_count: int, delphi_rounds: int, has_judge: bool = True
) -> int:
    """Pre-run model-call estimate for a quorum.

    Each round dispatches ``model_count`` panelists plus (if wired) one judge; a
    Delphi run adds a second full round (``delphi_rounds`` in {0, 1}). Supervisor
    fresh-search, when enabled, adds further full rounds — it is OPT-IN/OFF by
    default and reported separately, so it is deliberately excluded here (the
    estimate is the guaranteed floor, not the search-enabled ceiling)."""

    rounds = max(1, int(delphi_rounds) + 1)
    per_round = max(1, int(model_count)) + (1 if has_judge else 0)
    return per_round * rounds


# Cost/size tiers for the downgrade ladder. A cap must never route a request to a
# MORE EXPENSIVE tier than the one asked for — that would invert the cost cap
# (e.g. "downgrading" a cheap self-fusion onto the 10-model premium `wide` panel).
# The tiers rank by call count AND per-call model cost: `self` (one active model,
# cheapest) < `budget` (3 cheap models) < `frontier` (2 premium models) < `wide`
# (~10 mixed premium draws, most expensive).
_DOWNGRADE_PRESETS = ("wide", "budget", "self", "frontier")
_PRESET_TIER: dict[str, int] = {"self": 0, "budget": 1, "frontier": 2, "wide": 3}


def cap_preset_by_calls(
    preset: str,
    delphi_rounds: int,
    *,
    max_calls: int,
    samples: int = 3,
) -> tuple[str, int, int, int, str | None]:
    """Bound a (preset, delphi, samples) choice by ``max_calls``; downgrade if it overruns.

    Returns ``(preset, delphi_rounds, samples, estimated_calls, note)``. When the
    requested choice fits, ``note`` is ``None`` and nothing changes. Otherwise the
    LARGEST still-fitting choice is picked WITHOUT ever escalating to a costlier
    preset tier than the one requested (``self`` < ``budget`` < ``frontier`` <
    ``wide``) — so lowering the cap or raising ``--samples`` can only ever make a
    run CHEAPER, never route a routine ``self`` request onto a premium panel. Order
    of attack: (1) drop the Delphi round; (2) step DOWN the preset ladder / reduce
    ``self``'s sample count to the largest affordable panel AT OR BELOW the
    requested tier. A pathologically small ``max_calls`` falls open to the cheapest
    real panel (``self`` sampled once, no delphi) rather than blocking the run.
    """

    max_calls = int(max_calls)
    samples = max(1, int(samples))

    def _calls(cand: str, d: int, s: int) -> int:
        return estimate_quorum_calls(
            model_count=preset_model_count(cand, samples=s), delphi_rounds=d
        )

    est = _calls(preset, delphi_rounds, samples)
    if est <= max_calls:
        return preset, delphi_rounds, samples, est, None

    requested_tier = _PRESET_TIER.get(preset, 0)

    # (1) Drop the Delphi round first — it doubles cost for the same panel width.
    if delphi_rounds:
        est0 = _calls(preset, 0, samples)
        if est0 <= max_calls:
            return (
                preset,
                0,
                samples,
                est0,
                f"downgraded: dropped Delphi revision to fit max_calls={max_calls} "
                f"(would have been {est})",
            )

    # (2) Enumerate downgrade candidates — NEVER above the requested tier. For
    #     ``self`` (the cheapest tier) the only lever is fewer samples, so we keep
    #     it self-fusion of the active model rather than switching to a premium
    #     model list. Pick the LARGEST call-count that still fits within that
    #     bounded set (best affordable panel); ties break toward the cheaper tier.
    candidates: list[tuple[int, int, str, int, int]] = []
    for cand in _DOWNGRADE_PRESETS:
        cand_tier = _PRESET_TIER.get(cand, 0)
        if cand_tier > requested_tier:
            continue
        sample_options = range(samples, 0, -1) if cand == "self" else (samples,)
        for s in sample_options:
            for d in {delphi_rounds, 0}:
                calls = _calls(cand, d, s)
                if calls <= max_calls and calls < est:
                    candidates.append((calls, -cand_tier, cand, d, s))
    if candidates:
        calls, _neg_tier, cand, d, s = max(candidates)
        if cand != preset:
            note = (
                f"downgraded {preset}→{cand} (delphi={d}, samples={s}) to fit "
                f"max_calls={max_calls} (would have been {est})"
            )
        else:
            note = (
                f"downgraded {preset}: samples→{s} (delphi={d}) to fit "
                f"max_calls={max_calls} (would have been {est})"
            )
        return cand, d, s, calls, note

    # Nothing fits — fail OPEN to the cheapest real panel (self sampled once)
    # rather than blocking the run or escalating to a premium preset.
    floor = _calls("self", 0, 1)
    return (
        "self",
        0,
        1,
        floor,
        f"max_calls={max_calls} below any panel's floor; using self/1-sample/no-delphi ({floor} calls)",
    )


def resolve_quorum_defaults(
    question: Any,
    *,
    available_providers: set[str] | None = None,
    active_model: str | None = None,
    samples: int = 3,
) -> dict[str, Any]:
    """Map a question's impact + type onto a quorum preset/delphi/trim triple.

    The single place default quorum shape is decided, shared by BOTH the manual
    ``forecast quorum`` default resolution and the autonomous auto-run path, so a
    picked default is identical and printable ("using preset X: N models + judge,
    delphi=1 — why").

      * ``high`` impact (or a contested type) → ``frontier`` panel, one Delphi
        revision round, trim the extreme — the widest independent read.
      * ``medium`` impact → ``budget`` panel, no revision, trim.
      * routine / low / unset → ``self`` fusion, no revision, no trim — cheap.

    Then the SINGLE-KEY REALITY GUARD (item 3): when the resolved multi-provider
    preset spans a provider that is not reachable (only one provider key present,
    no OpenRouter), it falls back to ``self`` (the active model sampled) with a
    note — a panel that would silently error every non-local panelist is worse
    than an honest self-fusion.

    Returns ``{"preset", "delphi_rounds", "trim", "reason"}``. Does NOT apply the
    max_calls cap — the caller composes :func:`cap_preset_by_calls` after (so the
    cap note and the resolution note stay separately attributable).
    """

    impact = (getattr(question, "impact", None) or "").strip().lower()
    try:
        qtype = (getattr(getattr(question, "outcome_space", None), "type", None) or "").strip().lower()
    except Exception:  # noqa: BLE001 — a malformed question must never crash resolution
        qtype = ""

    contested = qtype in {"vote_share", "multiple_choice", "thesis"}
    if impact == "high" or contested:
        preset, delphi_rounds, trim = "frontier", 1, 1
        tier = "high-impact" if impact == "high" else f"contested ({qtype})"
    elif impact == "medium":
        preset, delphi_rounds, trim = "budget", 0, 1
        tier = "medium-impact"
    else:
        preset, delphi_rounds, trim = "self", 0, 0
        tier = "routine"

    reason_parts = [f"impact={impact or 'unset'}→{tier}"]

    if preset != "self":
        preset_models = list(QUORUM_PRESETS[preset]["models"])
        if not models_reachable(preset_models, available_providers):
            if active_model:
                preset = "self"
                reason_parts.append(
                    "single provider key reachable → self-fusion fallback"
                )
            else:
                # Single-key host with no active model to self-fuse: keep the
                # preset so the job still runs (unreachable panelists error and the
                # run is labeled degraded) rather than dead-ending.
                reason_parts.append(
                    "single provider key but no active model — keeping preset "
                    "(panelists may degrade)"
                )

    return {
        "preset": preset,
        "delphi_rounds": delphi_rounds,
        "trim": trim,
        "reason": "; ".join(reason_parts),
    }


def resolve_final_probability(
    pool_probability: float,
    judge: JudgeSynthesis | None,
) -> tuple[float, str]:
    """The whole AIA P0.3 decision rule — confidence-gated supervisor override.

    Returns ``(judge.probability, 'judge_high')`` IFF the judge exists, reported
    a usable probability, AND self-declared ``directional_confidence == 'high'``;
    otherwise ``(pool_probability, 'pool')``.

    This is a PURE function (no I/O, no calibration) and is the entire override
    logic: a low/medium-confidence judge can NEVER drag the committed number off
    a sound pool. Bounded downside, gated upside.

    Composition note (terminal Platt, AIA P0.1): the caller is responsible for
    feeding the ALREADY-CALIBRATED pool here (so the ``'pool'`` branch is Platt'd
    exactly once, inside aggregation) and for Platt-scaling the RAW judge number
    on the ``'judge_high'`` branch (so the winning override is also calibrated
    exactly once). This function neither knows nor applies alpha.
    """

    if (
        judge is not None
        and judge.probability is not None
        and judge.directional_confidence == "high"
    ):
        return float(judge.probability), "judge_high"
    return float(pool_probability), "pool"


def should_research(
    judge: JudgeSynthesis | None,
    *,
    rounds_done: int,
    max_rounds: int = 1,
) -> bool:
    """The whole AIA P1.1 supervisor research-gate — PURE, no I/O.

    Returns ``True`` IFF the judge exists, flagged an unresolved crux
    (``information_gap``), supplied at least one ``clarifying_queries`` entry, AND
    the loop is still under its budget (``rounds_done < max_rounds``). Any other
    state (no judge, no gap, empty queries, at/over cap) is ``False`` — so the
    research loop is opt-in, evidence-driven, and strictly bounded.
    """

    if judge is None:
        return False
    return (
        judge.information_gap
        and bool(judge.clarifying_queries)
        and rounds_done < max_rounds
    )


def run_quorum(
    *,
    question_title: str,
    resolution_criteria: str,
    context_packet: str = "",
    models: Sequence[str],
    runner: QuorumRunner,
    question_id: str | None = None,
    evidence_cutoff: str | None = None,
    judge_model: str | None = DEFAULT_JUDGE_MODEL,
    judge_runner: QuorumRunner | None = None,
    pool_method: str = "trimmed_geomean_odds",
    trim: int = 1,
    alpha_extremize: float = 1.0,
    self_fusion: bool = False,
    max_concurrency: int | None = None,
    on_progress: Callable[[str, str], None] | None = None,
    search_runner: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    max_research_rounds: int = 1,
    delphi_rounds: int = 0,
    model_weights: Mapping[str, float] | None = None,
) -> QuorumResult:
    """Run the full quorum: dispatch panelists, aggregate, judge-synthesise.

    ``runner`` and ``judge_runner`` are injectable for testing; in production
    they wrap :func:`make_aiagent_runner`. Panelists are dispatched **in
    parallel** (up to ``max_concurrency``) — the Fusion design — so the
    wall-clock is the slowest single model, not the sum. ``on_progress(stage,
    detail)`` fires as each panelist completes so the caller can stream desk
    progress; it may be called from worker threads.

    ``max_concurrency`` defaults to ``None`` → dispatch the whole panel at once,
    capped at ``_AUTO_CONCURRENCY_CAP`` (8) threads, so a wide preset runs in a
    single LLM wave. Pass an explicit int to bound it (``1`` forces the
    deterministic sequential branch).

    A panelist that errors (bad JSON, runtime failure, timeout) is recorded
    with its ``error`` set and excluded from pooling; the quorum still completes
    as long as at least one panelist succeeds. Results keep input order.

    ``alpha_extremize`` (AIA P0.1) is the per-question terminal Platt slope. It
    is applied EXACTLY ONCE to whichever number wins the P0.3 override gate:
    the pool is calibrated inside :func:`aggregate_panel_estimates`, and if a
    high-confidence judge overrides, its raw number is Platt'd here with the
    same alpha. Defaulting to ``1.0`` (identity) keeps an un-configured quorum's
    committed number byte-identical to the historical bare pool.

    ``search_runner`` (AIA P1.1 — the agentic-supervisor fresh-search loop) is
    the OPTIONAL seam that turns "matches the mean" into "beats the mean". When
    supplied AND the judge flags an unresolved crux (:func:`should_research`),
    its ``clarifying_queries`` are handed to ``search_runner`` which runs FRESH
    search and returns evidence dicts; those are appended to the working context
    and the panel+judge are RE-RUN once (bounded by ``max_research_rounds``,
    default 1). The committed number STILL flows through the P0.3 override gate +
    the terminal Platt EXACTLY ONCE, on the final pass only. When
    ``search_runner`` is ``None`` (the default) NOTHING changes: no gap check, no
    extra calls, and the committed probability / ``final_source`` are
    byte-identical to before — ``research_rounds`` stays 0 and
    ``supervisor_evidence`` empty.

    ``delphi_rounds`` (v1 supports only ``0`` or ``1``) adds an optional Delphi
    revision round. At ``0`` (the default) NOTHING changes — the sealed round →
    optional supervisor search → override gate runs exactly as before and
    ``delphi_rounds``/``delphi_audit`` return ``0``/``{}``. At ``1`` the sealed
    round-1 panel is pooled and judged, an ANONYMOUS reveal of the round-1 spread +
    the judge's contradictions/blind-spots (plus any round-1 supervisor evidence) is
    built, each panel SEAT privately revises against that reveal, and the FINAL
    aggregate/override runs on the revision round only. The sealed round is preserved
    in ``delphi_audit['rounds'][0]``. The supervisor search runs at most once, on
    round 1 only (no post-revision search), so cost stays bounded and predictable.

    ``model_weights`` (S7 track-record weighting) is an OPTIONAL ``{model: weight}``
    map derived from each panelist model's measured Brier edge over past resolved
    binaries (see :meth:`ForecastLedger.recommended_model_weights`). A surviving
    panelist's :attr:`ModelForecast.weight` is set from it (default 1.0 for any
    model NOT in the map), so a model with no measured track record — or a cold-
    start desk with an empty map — keeps EQUAL weights and the committed number is
    byte-identical to before. The weights are consumed by
    :func:`aggregate_panel_estimates` (weighted log-odds pool) and
    :func:`disagreement_signal`; the map actually used is echoed on
    ``QuorumResult.model_weights_used`` so the operator can see why.
    """

    if not models:
        raise ValidationError("quorum requires at least one model")
    if delphi_rounds not in (0, 1):
        raise ValidationError("delphi_rounds must be 0 or 1")
    judge_runner = judge_runner or runner

    def _run_pass(
        working_context: str,
        *,
        round_index: int,
        prior_by_participant: dict[str, ModelForecast] | None = None,
        delphi_summary: str | None = None,
    ) -> tuple[
        list[ModelForecast], PanelAggregation, dict[str, Any], JudgeSynthesis | None
    ]:
        """One full panel-dispatch → aggregate → judge-synthesise pass over the
        given (possibly fresh-evidence-augmented) context. Pure of the override
        gate / terminal Platt, which are applied once on the final pass below.

        ``round_index`` tags every seat's forecast (1 = sealed round, 2 = revision).
        On the revision round ``delphi_summary`` (the anonymous reveal) is appended
        to each panelist's prompt as a ``## Delphi Revision Context`` block seeded
        with that seat's own prior from ``prior_by_participant`` (keyed by the stable
        ``p01``… seat id, NOT the model id — the ``self`` preset repeats a model)."""

        def _dispatch(index: int, model: str) -> ModelForecast:
            participant_id = f"p{index + 1:02d}"
            prior = (
                prior_by_participant.get(participant_id)
                if prior_by_participant is not None
                else None
            )
            prompt = build_panelist_prompt(
                question_title=question_title,
                resolution_criteria=resolution_criteria,
                context_packet=working_context,
                evidence_cutoff=evidence_cutoff,
                sample_hint=index + 1 if self_fusion else None,
            )
            user = prompt["user"]
            if delphi_summary is not None:
                user = user + build_revision_context_block(
                    prior=prior, delphi_summary=delphi_summary
                )
            revision_reason: str | None = None
            try:
                raw = runner(model, prompt["system"], user)
                forecast = parse_panelist_response(raw, model)
                if delphi_summary is not None:
                    rr = _reparse_full(raw).get("revision_reason")
                    revision_reason = str(rr).strip() if rr else None
            except Exception as exc:  # noqa: BLE001 — isolate one panelist's failure
                # Any single model failing (bad JSON, timeout, provider/SDK error)
                # is recorded as an errored panelist; the quorum completes on the
                # survivors rather than aborting the whole run.
                forecast = ModelForecast(
                    model=model, probability=0.5, error=f"{type(exc).__name__}: {exc}"
                )
            # Delphi provenance (harmless on the round-1 / non-delphi path: seat id
            # set, round_index=1, no prior, no revision_reason).
            forecast.participant_id = participant_id
            forecast.round_index = round_index
            forecast.prior_probability = prior.probability if prior is not None else None
            forecast.revision_reason = revision_reason
            # Track-record weighting (S7): a surviving panelist carries its measured
            # weight (default 1.0 when unmeasured/cold-start), consumed by the pool +
            # disagreement. Errored panelists keep 1.0 but are excluded from pooling.
            if model_weights and forecast.error is None:
                try:
                    forecast.weight = float(model_weights.get(model, 1.0))
                except (TypeError, ValueError):
                    forecast.weight = 1.0
            if on_progress:
                on_progress(
                    "panelist_done",
                    f"{model}: {'error' if forecast.error else f'{forecast.probability:.3f}'}",
                )
            return forecast

        slots: list[ModelForecast | None] = [None] * len(models)
        if on_progress:
            on_progress("panelists_start", f"{len(models)} models")
        # Default to dispatching the whole panel at once (capped at 8 threads) so
        # a wide preset fires in a single LLM wave instead of serialising into
        # ``ceil(len(models)/4)`` sequential waves. An explicit ``max_concurrency``
        # (including ``1`` for the deterministic sequential branch) is honoured.
        if max_concurrency is None:
            requested = min(len(models), _AUTO_CONCURRENCY_CAP)
        else:
            requested = int(max_concurrency)
        workers = max(1, min(requested, len(models)))
        if workers == 1:
            for index, model in enumerate(models):
                slots[index] = _dispatch(index, model)
        else:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_dispatch, index, model): index
                    for index, model in enumerate(models)
                }
                for future in futures:
                    index = futures[future]
                    slots[index] = future.result()
        pass_forecasts = [f for f in slots if f is not None]

        ok = [f for f in pass_forecasts if f.error is None]
        if not ok:
            raise ValidationError(
                "every quorum panelist failed; first error: "
                + (pass_forecasts[0].error or "unknown")
            )

        pass_aggregation = aggregate_panel_estimates(
            [f.to_estimate() for f in ok],
            method=pool_method,
            trim=trim,
            alpha_extremize=alpha_extremize,
        )
        pass_disagreement = disagreement_signal(
            [f.probability for f in ok],
            [f.weight for f in ok],
        )

        pass_judge: JudgeSynthesis | None = None
        if judge_model:
            if on_progress:
                on_progress("judge_start", judge_model)
            jp = build_judge_prompt(
                question_title=question_title,
                resolution_criteria=resolution_criteria,
                forecasts=pass_forecasts,
                aggregation=pass_aggregation,
                disagreement=pass_disagreement,
            )
            try:
                jraw = judge_runner(judge_model, jp["system"], jp["user"])
                pass_judge = parse_judge_response(jraw, judge_model)
            except Exception as exc:  # noqa: BLE001 — a judge failure must not lose the panel
                pass_judge = JudgeSynthesis(
                    probability=None,
                    rationale=f"(judge synthesis failed: {type(exc).__name__}: {exc})",
                    judge_model=judge_model,
                )
            if on_progress:
                on_progress("judge_done", judge_model)
        return pass_forecasts, pass_aggregation, pass_disagreement, pass_judge

    working_context = context_packet
    research_rounds = 0
    supervisor_evidence: list[dict[str, Any]] = []
    delphi_audit: dict[str, Any] = {}

    if delphi_rounds == 1:
        # ── Delphi flow (Forecast Flow steps 1-11) ─────────────────────────────
        # Sealed round 1 → pool → judge → optional supervisor search (round 1 ONLY,
        # NO post-revision search) → anonymous reveal → private revision round →
        # final pool/judge. The override gate + terminal Platt below run on the
        # revision round only; the sealed round is preserved in delphi_audit.
        r1_forecasts, r1_aggregation, r1_disagreement, r1_judge = _run_pass(
            working_context, round_index=1
        )
        # Supervisor search is bounded to a single round-1 pass here (the revision
        # round is the re-synthesis, so we do NOT re-run the panel/judge as the
        # AIA loop does). search_runner is None for historical cutoffs (the caller
        # fails closed), so this branch also preserves the foreknowledge guard.
        if search_runner is not None and should_research(
            r1_judge, rounds_done=research_rounds, max_rounds=max_research_rounds
        ):
            assert r1_judge is not None  # should_research guarantees this
            if on_progress:
                on_progress("research_start", "round 1")
            fresh = list(search_runner(list(r1_judge.clarifying_queries)) or [])
            supervisor_evidence.extend(fresh)
            research_rounds += 1
            working_context = _augment_context(working_context, fresh)
            if on_progress:
                on_progress("research_done", f"{len(fresh)} item(s)")

        delphi_summary = build_delphi_summary(
            forecasts=r1_forecasts,
            aggregation=r1_aggregation,
            disagreement=r1_disagreement,
            judge=r1_judge,
            supervisor_evidence=supervisor_evidence,
        )
        prior_by_participant = {
            f.participant_id: f for f in r1_forecasts if f.participant_id
        }
        if on_progress:
            on_progress("delphi_start", "revision round 1")
        forecasts, aggregation, disagreement, judge = _run_pass(
            working_context,
            round_index=2,
            prior_by_participant=prior_by_participant,
            delphi_summary=delphi_summary,
        )
        if on_progress:
            on_progress("delphi_done", "revision round 1")

        delphi_audit = {
            "rounds": [
                _delphi_audit_round(
                    round_index=1,
                    forecasts=r1_forecasts,
                    aggregation=r1_aggregation,
                    disagreement=r1_disagreement,
                    judge=r1_judge,
                ),
                _delphi_audit_round(
                    round_index=2,
                    forecasts=forecasts,
                    aggregation=aggregation,
                    disagreement=disagreement,
                    judge=judge,
                ),
            ],
            "revision_context": {
                "included_probability_distribution": True,
                "included_model_names": False,
                "included_supervisor_evidence": bool(supervisor_evidence),
            },
        }
    else:
        # ── agentic-supervisor fresh-search loop (AIA P1.1) ────────────────────
        # First pass over the original context is ALWAYS run. When a search_runner
        # is wired AND the judge flags an unresolved crux, we run fresh search,
        # append the returned evidence to the working context, and re-synthesise —
        # bounded by max_research_rounds. With NO search_runner the while-guard is
        # never even evaluated for cost (search_runner is None), so the default
        # path is exactly one pass and byte-identical to before.
        forecasts, aggregation, disagreement, judge = _run_pass(
            working_context, round_index=1
        )
        while (
            search_runner is not None
            and should_research(
                judge, rounds_done=research_rounds, max_rounds=max_research_rounds
            )
        ):
            assert judge is not None  # should_research guarantees this
            if on_progress:
                on_progress("research_start", f"round {research_rounds + 1}")
            fresh = list(search_runner(list(judge.clarifying_queries)) or [])
            supervisor_evidence.extend(fresh)
            research_rounds += 1
            working_context = _augment_context(working_context, fresh)
            if on_progress:
                on_progress("research_done", f"{len(fresh)} item(s)")
            forecasts, aggregation, disagreement, judge = _run_pass(
                working_context, round_index=1
            )

    # ── confidence-gated supervisor override (AIA P0.3) ────────────────────────
    # The pool is already terminally-Platt'd inside aggregate_panel_estimates.
    # resolve_final_probability picks the winning branch on the RAW numbers; we
    # then Platt the judge's raw override here so terminal calibration lands on
    # whichever number wins EXACTLY ONCE (pool: Platt'd in aggregation; judge:
    # Platt'd just below). Never both, never zero times.
    final_probability, final_source = resolve_final_probability(
        aggregation.aggregate_probability, judge
    )
    if final_source == "judge_high":
        alpha = float(alpha_extremize)
        if alpha != 1.0:
            from forecasting.bayes_toolkit import platt_scale

            final_probability = float(platt_scale(final_probability, alpha=alpha, d=1.0))

    # Panel-integrity labeling (item 3): a genuine quorum needs >=2 surviving
    # panelist forecasts. When fewer survive, the aggregate is a lone survivor —
    # we keep the (unchanged) number but flag it degraded so no downstream reader
    # mistakes one model's answer for multi-model fusion.
    ok_count = len([f for f in forecasts if f.error is None])
    degraded = ok_count < 2
    degraded_reason = (
        f"only {ok_count} panelist forecast survived (need >=2 for a panel); "
        "the committed number is a lone survivor, not a fused quorum"
        if degraded
        else None
    )
    if degraded and on_progress:
        on_progress("degraded", degraded_reason or "")

    return QuorumResult(
        question_id=question_id,
        forecasts=forecasts,
        aggregation=aggregation,
        disagreement=disagreement,
        judge=judge,
        pool_method=aggregation.method,
        trim=aggregation.trim,
        judge_model=judge_model,
        final_probability=final_probability,
        final_source=final_source,
        research_rounds=research_rounds,
        supervisor_evidence=supervisor_evidence,
        delphi_rounds=delphi_rounds,
        delphi_audit=delphi_audit,
        degraded=degraded,
        degraded_reason=degraded_reason,
        # Only the weights that actually landed on a SURVIVING panelist (final pass).
        model_weights_used={
            f.model: float(f.weight)
            for f in forecasts
            if f.error is None and model_weights and f.model in model_weights
        },
    )


def _augment_context(base: str, fresh_evidence: Sequence[Mapping[str, Any]]) -> str:
    """Fold fresh supervisor-search evidence into the working context packet.

    The panelist/judge prompts consume a single context string, so the fresh
    evidence dicts are rendered into a clearly-fenced block appended to the
    existing context. Mirrors the tolerant ``{title, summary, source}`` shape
    used by :mod:`forecasting.news_search`; any of those keys may be absent.
    """

    if not fresh_evidence:
        return base
    lines = ["", "## Fresh Supervisor Search (AIA P1.1)"]
    for i, item in enumerate(fresh_evidence, start=1):
        title = str(item.get("title") or item.get("claim") or "").strip()
        summary = str(item.get("summary") or item.get("text") or "").strip()
        src = str(item.get("source") or item.get("url") or "").strip()
        head = f"[{i}] {title}" if title else f"[{i}]"
        if src:
            head += f" ({src})"
        lines.append(head)
        if summary:
            lines.append(f"    {summary}")
    block = "\n".join(lines)
    return f"{base}\n{block}" if base else block.lstrip("\n")


_UNSET_CUTOFF = object()


def resolve_panelist_toolsets(evidence_cutoff: Any) -> tuple[str, ...]:
    """Cutoff-gate the toolset every quorum PANELIST is built with (foreknowledge guard).

    A panelist's job is to emit an INDEPENDENT forecast that the quorum job then
    aggregates + records; the panelist itself must NEVER write the ledger. So the
    ledger-WRITE "forecasting" toolset (which also exposes
    ``forecast_ledger.import_source_evidence`` — a fetch of the LIVE current
    manifold/metaculus/polymarket value, i.e. the potentially now-known answer) is
    DROPPED in every case. What remains is gated on whether the forecast is LIVE,
    using the SAME :func:`forecasting.jobs.types.quorum._cutoff_is_live` predicate
    that guards the supervisor search:

      * HISTORICAL cutoff (a backtest / replay snapshot): EMPTY toolset ``()`` —
        closed-book, NO web, NO import_source_evidence. The panelist reasons only
        from the supplied case, mirroring the closed-book backtest runner
        (``forecasting.cli`` uses ``[]`` under ``--closed-book``). This closes the
        leak: post-cutoff / now-known information can never be pulled into a
        past-pinned forecast.
      * LIVE cutoff (no cutoff, or within tolerance of now): RESEARCH-ONLY
        ``("web",)`` — the panelist researches the open question via web search and
        emits a parsed forecast (the parse path reads the final response text; no
        forecasting tool is needed to emit a forecast). This mirrors the live market
        forecaster's ``LIVE_ENABLED_TOOLSETS = ["web"]`` fix — web research only, NO
        ledger-write surface.
    """

    from forecasting.jobs.types.quorum import _cutoff_is_live

    return ("web",) if _cutoff_is_live(evidence_cutoff) else ()


def make_aiagent_runner(
    *,
    max_iterations: int = 30,
    toolsets: Sequence[str] = ("forecasting", "web"),
    quiet: bool = True,
    timeout: float | None = None,
    requested_provider: str | None = None,
    evidence_cutoff: Any = _UNSET_CUTOFF,
) -> QuorumRunner:
    """Default production runner: one :class:`run_agent.AIAgent` per call.

    Each panelist is constructed via the single :func:`agent.agent_factory.build_agent`
    resolve->construct path, with web search enabled so it researches independently
    (the Fusion design). ``requested_provider=None`` (the default) AUTO-RESOLVES the
    provider from the model + active credentials — so a codex-only host runs gpt-5.5
    via codex, an OpenRouter host runs OpenRouter model ids via OpenRouter, etc. (The
    old hardcoded ``provider="openrouter"`` broke every non-OpenRouter deployment.)
    Built lazily so importing this module never pulls in the full agent runtime.

    ``evidence_cutoff`` is the FOREKNOWLEDGE GUARD (default ``_UNSET_CUTOFF`` keeps the
    explicit ``toolsets`` for backward safety). When the quorum call path passes it,
    :func:`resolve_panelist_toolsets` OVERRIDES ``toolsets`` with the cutoff-gated set:
    an EMPTY toolset for a HISTORICAL cutoff (closed-book — no web, no
    import_source_evidence, so no post-cutoff leak) and RESEARCH-ONLY ``("web",)`` for
    a LIVE cutoff (web research, NO ledger-write surface). This mirrors the
    supervisor-search leakage guard so a panelist can never pull now-known information
    into a past-pinned forecast.

    ``timeout`` (seconds) bounds a single model call: a model that hangs past
    it raises ``RuntimeError`` so :func:`run_quorum` records that panelist as
    errored and the quorum still completes on the survivors. The call runs on a
    daemon thread, so a hung model cannot wedge the job — it is abandoned and
    reaped when the (per-run) process exits.
    """

    if evidence_cutoff is not _UNSET_CUTOFF:
        toolsets = resolve_panelist_toolsets(evidence_cutoff)

    def _call(model: str, system: str, user: str) -> str:
        from agent.agent_factory import build_agent

        agent = build_agent(
            model=model,
            requested_provider=requested_provider,
            enabled_toolsets=list(toolsets),
            max_iterations=max_iterations,
            quiet_mode=quiet,
            skip_memory=True,
            skip_context_files=True,
            load_soul_identity=False,
            platform="cli",
        )
        result = agent.run_conversation(user, system_message=system)
        if isinstance(result, dict):
            return str(result.get("final_response") or "")
        return str(result or "")

    def _runner(model: str, system: str, user: str) -> str:
        if not timeout or timeout <= 0:
            return _call(model, system, user)
        import threading

        box: dict[str, Any] = {}

        def _target() -> None:
            try:
                box["result"] = _call(model, system, user)
            except Exception as exc:  # noqa: BLE001 — surfaced to the caller below
                box["error"] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            raise RuntimeError(f"model {model} timed out after {timeout:g}s")
        if "error" in box:
            raise box["error"]
        return box.get("result", "")

    return _runner


__all__ = [
    "QuorumRunner",
    "QUORUM_PRESETS",
    "DEFAULT_JUDGE_MODEL",
    "ModelForecast",
    "JudgeSynthesis",
    "QuorumResult",
    "disagreement_signal",
    "build_panelist_prompt",
    "build_judge_prompt",
    "build_delphi_summary",
    "build_revision_context_block",
    "parse_panelist_response",
    "parse_judge_response",
    "resolve_models",
    "resolve_final_probability",
    "resolve_quorum_defaults",
    "available_provider_slugs",
    "models_reachable",
    "preset_model_count",
    "estimate_quorum_calls",
    "cap_preset_by_calls",
    "should_research",
    "run_quorum",
    "quorum_auto_indicated",
    "make_aiagent_runner",
]
