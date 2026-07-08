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

# Sentinel: "caller passed no value → read the layered appconfig loader" (distinct
# from an explicit None/"" injected by a test or an operator clearing the key).
_UNSET_CONFIG: Any = object()

# When ``run_quorum`` is called without an explicit ``max_concurrency`` the whole
# panel is dispatched in one wave, bounded by this cap so a very wide panel does
# not spawn an unreasonable number of concurrent LLM calls.
_AUTO_CONCURRENCY_CAP = 8

# ── Multi-trial per-panelist pooling (BLF A2) ────────────────────────────────
# A single run per panelist is a noisy POINT-SAMPLE of the model's own belief
# distribution (BLF measures inter-trial σ≈0.20 in probability space — enormous),
# so a high-impact question runs K trials per seat and pools them, per BLF, as a
# James–Stein shrunken logit mean toward the outside-view anchor: the noisier the
# trials, the harder the pool shrinks to the anchor. K is question-impact-driven
# (config below); the extra spend rides the SAME cost caps + policy-matrix
# LLM_SPEND authorize the panel width already does.
_DEFAULT_TRIALS = 1  # routine question — one draw per seat (byte-identical baseline)
_HIGH_IMPACT_TRIALS = 3  # high-impact question — three draws per seat, pooled
# James–Stein form α = max(f, 1 − c·s²) with s² the inter-trial LOGIT variance:
# α is the weight kept on the trials' own mean, (1−α) the weight shrunk onto the
# anchor. ``_TRIAL_SHRINK_FLOOR`` (f) never lets the pool collapse entirely onto
# the anchor; ``_TRIAL_SHRINK_C`` (c) sets how fast disagreement pulls toward it
# (at s²≈1 — trials split ~0.27 vs ~0.73 — α hits the floor). Documented, LOO-CV-
# able defaults; at s²=0 (K=1 or unanimous trials) α=1 so the pool is the mean.
_TRIAL_SHRINK_FLOOR = 0.5
_TRIAL_SHRINK_C = 0.5

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
    # Blind-then-reconcile provenance (UPGRADE 1). On a market-linked question each
    # panelist first produces a BLIND estimate WITHOUT seeing the market anchor
    # (``blind_probability``), then — in a second turn on the SAME session — sees the
    # anchor + its own blind number and RECONCILES (``reconciled_probability`` == the
    # committed ``probability``), giving a named-edge ``reconcile_reason`` for any
    # deviation. Both default to None so a non-market single-phase panelist (the
    # anchor is None → no reconcile turn) is byte-identical to before: the blind and
    # reconciled numbers are simply the one committed number.
    blind_probability: float | None = None
    reconciled_probability: float | None = None
    reconcile_reason: str | None = None
    # Linguistic belief state (BLF A1). The ordered trajectory of belief REVISIONS
    # the panelist emitted as it accumulated evidence — each step a dict
    # ``{step, probability, confidence, evidence_for, evidence_against,
    # open_questions, moved_by}`` where ``moved_by`` names the single piece of
    # evidence that moved the number. The LAST step's probability is the committed
    # forecast (the final belief IS the commit). Empty when the panelist returned no
    # trajectory (a stub/legacy response) — the committed number then stands alone.
    belief_trajectory: list[dict[str, Any]] = field(default_factory=list)
    # Multi-trial provenance (BLF A2). On a K>1 seat this ModelForecast is the
    # POOLED belief over K trials; ``trials`` records each surviving trial
    # (``{trial, probability, blind_probability, crux, moved_by}``) so a divergent
    # lone-skeptic trial's distinct read stays discoverable, and ``trial_shrinkage``
    # records the James–Stein pool (``{n_trials, survivors, alpha, var_logit,
    # target, degraded}``). Both empty/None on the default K=1 path so a single-trial
    # seat is byte-identical to a pre-A2 panelist.
    trials: list[dict[str, Any]] = field(default_factory=list)
    trial_shrinkage: dict[str, Any] | None = None

    @property
    def trial_probabilities(self) -> list[float]:
        """The per-trial committed probabilities that feed the disagreement index.

        A single-trial seat reports its one committed number; a multi-trial seat
        reports EVERY surviving trial so trial divergence widens the measured spread
        (BLF: the lone skeptic is a divergent trial). Byte-identical to
        ``[self.probability]`` on the default K=1 path (``trials`` is empty)."""

        if self.trials:
            probs = [
                t.get("probability")
                for t in self.trials
                if t.get("error") is None and t.get("probability") is not None
            ]
            return [float(p) for p in probs] or [self.probability]
        return [self.probability]

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
                # Blind-then-reconcile provenance (None on the non-market path).
                "blind_probability": self.blind_probability,
                "reconciled_probability": self.reconciled_probability,
                "reconcile_reason": self.reconcile_reason,
                # Linguistic belief state (A1) + multi-trial provenance (A2). Ride
                # the existing panel_estimates.metadata JSON column — no schema
                # migration; empty/None on the legacy/K=1 path so a durable estimate
                # is byte-compatible with a pre-BLF reader.
                "belief_trajectory": self.belief_trajectory,
                "trials": self.trials,
                "trial_shrinkage": self.trial_shrinkage,
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
    # FIX B — market-anchor discipline. The judge's stated NAMED edge (private
    # information / market-unpriced signal) that justifies deviating more than the
    # threshold from the outside-view market prior. Empty/None ⇒ no justification, so
    # a large deviation is pulled back toward the market. Defaults to None so every
    # non-market-linked and pre-FIX-B construction is unchanged.
    market_deviation_justification: str | None = None

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
            "market_deviation_justification": self.market_deviation_justification,
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
    # FIX B — market-anchor discipline. On a market-linked question the current
    # de-vigged market price is injected as the outside-view anchor; these record the
    # verdict's relationship to it. ``market_price`` is the anchor (None on a
    # non-market question — every field then stays in its no-anchor default so the
    # committed number is byte-identical to before). ``market_deviation_pp`` is the
    # final |verdict − market| in percentage points; ``market_justification`` is the
    # judge's named edge (or the 'insufficient justification — verdict pulled toward
    # market' note when the pull fired); ``market_pull_applied`` flags that the
    # committed number was pulled back toward the market via the log-odds pool.
    market_price: float | None = None
    market_deviation_pp: float | None = None
    market_justification: str | None = None
    market_pull_applied: bool = False
    # Blind-then-reconcile pools (UPGRADE 1 — the continuous orthogonality signal).
    # ``blind_pool`` is the panel aggregate over the panelists' BLIND (pre-anchor)
    # numbers — the market-INDEPENDENT signal, de-correlated from the price by
    # construction; ``reconciled_pool`` is the aggregate over their RECONCILED
    # (post-anchor) numbers (== the pooled ``aggregate_probability`` the judge/commit
    # path operates on). Stamped alongside ``market_price`` so blind-vs-market
    # divergence (the orthogonality measurement) travels with every market panel.
    # Both None on a non-market question (no anchor → no blind/reconcile split).
    blind_pool: float | None = None
    reconciled_pool: float | None = None
    # Self-fusion pseudo-diversity caveat (FIX B). A prominent, honest label set when
    # the panel is N samples of ONE model (not independent multi-model fusion), so a
    # reader never mistakes resample spread for genuine model diversity. None on a
    # real multi-model panel.
    pseudo_diversity_caveat: str | None = None

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
            # FIX B — market-anchor discipline (all in their no-anchor default on a
            # non-market question, so the payload stays byte-compatible there).
            "market_price": (
                round(self.market_price, 6) if self.market_price is not None else None
            ),
            "market_deviation_pp": (
                round(self.market_deviation_pp, 3)
                if self.market_deviation_pp is not None
                else None
            ),
            "market_justification": self.market_justification,
            "market_pull_applied": self.market_pull_applied,
            # Blind-then-reconcile pools (None on a non-market question).
            "blind_pool": (
                round(self.blind_pool, 6) if self.blind_pool is not None else None
            ),
            "reconciled_pool": (
                round(self.reconciled_pool, 6)
                if self.reconciled_pool is not None
                else None
            ),
            "pseudo_diversity_caveat": self.pseudo_diversity_caveat,
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
    "starting anchor). Start with your prior and add a step whenever the evidence "
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
    trajectory = _parse_belief_trajectory(payload.get("belief_trajectory"))
    # BLF A1: the final belief IS the commit. When the panelist emitted a belief
    # trajectory, its last step's probability is the committed number (the belief the
    # evidence walked to); absent a trajectory, the top-level ``probability`` stands.
    committed = float(parsed["probability"])
    if trajectory and trajectory[-1].get("probability") is not None:
        committed = float(trajectory[-1]["probability"])
    return ModelForecast(
        model=model,
        probability=committed,
        confidence_low=_opt_prob(payload.get("confidence_low")),
        confidence_high=_opt_prob(payload.get("confidence_high")),
        rationale=str(parsed.get("rationale") or ""),
        reasons_up=_str_list(payload.get("reasons_up")),
        reasons_down=_str_list(payload.get("reasons_down")),
        change_my_mind=_str_list(payload.get("change_my_mind")),
        crux=(str(payload["crux"]).strip() if payload.get("crux") else None),
        belief_trajectory=trajectory,
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
        market_deviation_justification=_opt_justification(
            payload.get("market_deviation_justification")
        ),
    )


def _opt_justification(value: Any) -> str | None:
    """Coerce the judge's market-deviation justification to a clean string or None.

    An empty/whitespace/garbage value collapses to ``None`` (the no-justification
    state) so a blank field can never be read as a real named edge — a large
    deviation with an empty justification is pulled toward the market.
    """

    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


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


def _text_has_json_object(text: str) -> bool:
    """True when ``text`` carries a parseable JSON object (fenced/prose-embedded)."""

    if not text:
        return False
    from forecasting.agent_protocol import _coerce_json_response

    try:
        _coerce_json_response(text)
        return True
    except ValueError:
        return False


def _assemble_response_text(result: Mapping[str, Any]) -> str:
    """Best text to parse from a successful agent result.

    A reasoning model sometimes emits the structured answer INSIDE its thinking
    trace and leaves the visible final message empty (or as prose), so when the
    visible ``final_response`` carries no parseable JSON object we fall back to the
    ``last_reasoning`` trace. This NEVER fabricates: if neither the visible message
    nor the reasoning carries a JSON object, the visible text is returned verbatim
    so the downstream parser still errors honestly (empty vs prose).
    """

    final = str(result.get("final_response") or "").strip()
    if _text_has_json_object(final):
        return final
    reasoning = str(result.get("last_reasoning") or "").strip()
    if reasoning and _text_has_json_object(reasoning):
        return reasoning
    return final or reasoning


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


def _belief_step(raw: Any, index: int) -> dict[str, Any] | None:
    """Normalize one linguistic-belief-state step (BLF A1) into the recorded schema.

    Returns ``{step, probability, confidence, evidence_for, evidence_against,
    open_questions, moved_by}`` — the belief slot plus the one-line ``moved_by``
    naming the evidence that moved the number. A step with no parseable probability
    is dropped (a belief revision without a number is not a revision); ``step``
    falls back to the 1-based position when the model omitted it. Tolerant by
    design so a malformed step can never abort the whole panelist parse."""

    if not isinstance(raw, Mapping):
        return None
    probability = _opt_prob(raw.get("probability"))
    if probability is None:
        probability = _opt_prob(raw.get("p"))
    if probability is None:
        return None
    try:
        step = int(raw.get("step"))
    except (TypeError, ValueError):
        step = index + 1
    confidence = raw.get("confidence")
    return {
        "step": step,
        "probability": probability,
        "confidence": str(confidence).strip().lower() if confidence else None,
        "evidence_for": _str_list(raw.get("evidence_for")),
        "evidence_against": _str_list(raw.get("evidence_against")),
        "open_questions": _str_list(raw.get("open_questions")),
        "moved_by": (str(raw.get("moved_by")).strip() if raw.get("moved_by") else None),
    }


def _parse_belief_trajectory(raw: Any) -> list[dict[str, Any]]:
    """The ordered belief trajectory (BLF A1) from a panelist payload.

    Returns a list of normalized belief steps; ``[]`` when the field is absent or
    carries nothing parseable — so a legacy/stub response with no trajectory yields
    an empty trajectory and the committed number stands alone (byte-compatible)."""

    if not isinstance(raw, (list, tuple)):
        return []
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        step = _belief_step(item, index)
        if step is not None:
            out.append(step)
    return out


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


# ── FIX A: resolve presets to ACTUALLY-connected providers ───────────────────
#
# The built-in budget/frontier/wide presets name OpenRouter-format model ids
# (``anthropic/claude-opus-4-8`` …). On a host with no OpenRouter key those ids
# route to nothing and EVERY panelist fails ("agent protocol response is empty").
# resolve_connected_panel rebuilds a preset's panel from the user's ACTUALLY-authed
# providers — each provider's own default model, dispatched natively via the
# ``provider:model`` runner split — and falls back to an HONESTLY-labeled
# single-provider self-fusion when only one provider is reachable. It NEVER names a
# model the user cannot call.

# Aggregator providers serve many vendors' models under one key, so the hardcoded
# preset ids ARE callable when one is authed — no rebuild needed (OpenRouter/Nous/
# Vercel become "just another provider IF a key exists").
_AGGREGATOR_PROVIDER_SLUGS = frozenset({"openrouter", "nous", "ai-gateway"})
# Provider slugs that are not a distinct model source for panel diversity.
_NON_PANEL_PROVIDER_SLUGS = frozenset({"custom"})


def available_providers_detail() -> list[dict[str, Any]] | None:
    """Authenticated-provider detail rows, or ``None`` when detection is unavailable.

    Reuses the same :func:`hermes_cli.models.list_available_providers` seam as
    :func:`available_provider_slugs` but keeps the ORDER + labels (so the panel is
    built deterministically from the canonical provider order). ``None`` on any
    failure is the FAIL-OPEN signal — an unknown provider picture must never
    rebuild a panel; the caller keeps the preset verbatim.
    """

    try:
        from hermes_cli.models import list_available_providers

        rows = [
            dict(p) for p in list_available_providers() if p.get("authenticated")
        ]
    except Exception:  # noqa: BLE001 — detection is best-effort; unknown ⇒ fail-open
        return None
    return rows or None


def _provider_default_model(slug: str) -> str | None:
    """The provider's own default/best model id (native form), or ``None``."""

    try:
        from hermes_cli.models import get_default_model_for_provider

        model = (get_default_model_for_provider(slug) or "").strip()
    except Exception:  # noqa: BLE001 — best-effort; a provider with no default is skipped
        return None
    return model or None


def _split_provider_model(model_id: str) -> tuple[str | None, str]:
    """Split a ``provider:model`` panel id into ``(provider, model)``.

    Only splits when the token before the FIRST colon is a KNOWN provider name —
    so a native/OpenRouter id that merely contains a colon (e.g.
    ``anthropic/claude-3.5-sonnet:beta``) is left intact and routed by
    auto-resolution. Returns ``(None, model_id)`` when there is no provider prefix.
    """

    if ":" not in model_id:
        return None, model_id
    head, rest = model_id.split(":", 1)
    head_n = head.strip().lower()
    rest = rest.strip()
    if not rest:
        return None, model_id
    try:
        from hermes_cli.models import _KNOWN_PROVIDER_NAMES

        known = head_n in _KNOWN_PROVIDER_NAMES
    except Exception:  # noqa: BLE001 — without the catalog, never split
        known = False
    return (head_n, rest) if known else (None, model_id)


def resolve_connected_panel(
    preset: str,
    *,
    active_model: str | None,
    active_provider: str | None = None,
    providers: Sequence[Mapping[str, Any]] | None = None,
    samples: int = 3,
) -> dict[str, Any]:
    """Rebuild a multi-provider preset panel from the user's ACTUALLY-authed providers.

    Returns ``{"rebuilt", "self_fusion", "models", "judge", "label", "providers_used"}``.

      * ``rebuilt=False`` — keep the preset's own model ids verbatim. Happens when
        detection is unavailable (fail-open), an AGGREGATOR key is present (the
        preset ids are callable), or nothing usable was found.
      * multi-provider (``rebuilt=True``, ``self_fusion=False``) — >=2 distinct
        native providers, each contributing its own default model as a
        ``provider:model`` id; ``label`` names them.
      * self-fusion (``rebuilt=True``, ``self_fusion=True``) — exactly one provider
        reachable: ``active_model`` sampled ``samples`` times, with the HONEST label
        "1 provider connected -> self-fusion; multi-model needs a second provider".

    Never names a model the user cannot call: a rebuilt multi-provider panel uses
    each provider's OWN default model, and the self-fusion fallback uses the active
    model routed through its active provider.
    """

    detail = (
        [dict(p) for p in providers]
        if providers is not None
        else available_providers_detail()
    )
    base = {
        "rebuilt": False,
        "self_fusion": False,
        "models": None,
        "judge": None,
        "label": None,
        "providers_used": [],
    }
    if detail is None:
        # Unknown provider picture — fail open, keep the preset verbatim.
        return base

    authed = {str(p.get("id")) for p in detail}
    base["providers_used"] = sorted(authed)
    # An aggregator key serves the hardcoded preset ids as-is — no rebuild.
    if authed & _AGGREGATOR_PROVIDER_SLUGS:
        return base

    # Distinct native providers, canonical order, each with its own default model.
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in detail:
        slug = str(row.get("id"))
        if slug in _NON_PANEL_PROVIDER_SLUGS or slug in _AGGREGATOR_PROVIDER_SLUGS:
            continue
        if slug in seen:
            continue
        model = _provider_default_model(slug)
        if not model:
            continue
        seen.add(slug)
        pairs.append((slug, f"{slug}:{model}"))

    if len(pairs) >= 2:
        want = max(2, min(preset_model_count(preset, samples=samples), len(pairs)))
        chosen = pairs[:want]
        models = [qm for _, qm in chosen]
        active_norm = (active_provider or "").strip().lower()
        judge = next(
            (qm for slug, qm in chosen if slug == active_norm), models[0]
        )
        label = (
            f"{len(chosen)} providers connected -> multi-model panel: "
            + ", ".join(slug for slug, _ in chosen)
        )
        return {
            "rebuilt": True,
            "self_fusion": False,
            "models": models,
            "judge": judge,
            "label": label,
            "providers_used": [slug for slug, _ in chosen],
        }

    # ZERO usable providers: the docstring's contract — nothing usable was
    # found -> rebuilt=False (fail-open, preset verbatim). Claiming
    # "1 provider connected" here would be a lie, and self-fusing an active
    # model with no live provider behind it reproduces the empty-response
    # failure this function exists to prevent.
    if not pairs and not authed:
        return base

    # Exactly 1 native provider reachable — honest single-provider self-fusion.
    if active_model:
        n = max(1, int(samples))
        label = (
            "1 provider connected -> self-fusion; multi-model needs a second provider"
        )
        return {
            "rebuilt": True,
            "self_fusion": True,
            "models": [active_model] * n,
            "judge": active_model,
            "label": label,
            "providers_used": [pairs[0][0]] if pairs else sorted(authed),
        }

    # Nothing usable to rebuild with (no aggregator, <2 providers, no active model).
    return base


# ── Operator-pinned panel (QUORUM_PANEL_MODELS) ──────────────────────────────
#
# The connected-provider rebuild picks each provider's OWN default model, which is
# right for a hands-off desk but wrong when an operator KNOWS a provider's default
# is unreachable (a dead token, a zero-quota preview model) or simply wants a
# specific line-up. QUORUM_PANEL_MODELS / QUORUM_JUDGE_MODEL let the operator pin
# exactly which ``provider:model`` seats sit in the panel; it takes PRECEDENCE over
# both the preset expansion and the connected-provider rebuild. Every pinned entry
# is validated against the actually-callable providers so a non-callable entry
# ERRORS NAMING ITSELF rather than silently dropping out at dispatch time.

# Config keys (mirrored in forecasting.appconfig's registry so the doctor knows them).
QUORUM_PANEL_MODELS_KEY = "QUORUM_PANEL_MODELS"
QUORUM_JUDGE_MODEL_KEY = "QUORUM_JUDGE_MODEL"


def parse_panel_models_config(raw: str | None) -> list[str]:
    """Parse a ``QUORUM_PANEL_MODELS`` comma list into clean ``provider:model`` entries."""

    if not raw:
        return []
    return [entry.strip() for entry in str(raw).split(",") if entry.strip()]


def validate_panel_models(
    models: Sequence[str],
    *,
    providers: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Validate pinned panel entries against the ACTUALLY-callable providers.

    Raises :class:`ValidationError` naming EVERY entry whose ``provider:`` prefix is
    not a connected/callable provider — never silently drops one. A bare id (no
    known provider prefix) routes through the active provider, so it is accepted
    (its reachability cannot be judged here). When the provider picture is UNKNOWN
    (detection unavailable) validation fails OPEN — the same fail-open contract the
    rest of the module keeps — so a sandboxed/headless host is never blocked. An
    aggregator key (OpenRouter/Nous/AI-Gateway) serves any id, so all entries pass.
    """

    detail = (
        [dict(p) for p in providers]
        if providers is not None
        else available_providers_detail()
    )
    if detail is None:
        return  # unknown provider picture — cannot prove non-callability, fail open
    authed = {str(p.get("id")) for p in detail}
    if authed & _AGGREGATOR_PROVIDER_SLUGS:
        return  # a universal aggregator serves every pinned id
    bad: list[str] = []
    for entry in models:
        prefix, _bare = _split_provider_model(entry)
        if prefix is None:
            continue  # bare id → active provider; reachability not decidable here
        if prefix not in authed:
            bad.append(entry)
    if bad:
        raise ValidationError(
            f"{QUORUM_PANEL_MODELS_KEY} names entr"
            + ("ies" if len(bad) > 1 else "y")
            + " whose provider is not connected/callable: "
            + ", ".join(bad)
            + ". Connected providers: "
            + (", ".join(sorted(authed)) or "(none)")
            + f". Fix {QUORUM_PANEL_MODELS_KEY} or connect the provider."
        )


def resolve_configured_panel(
    *,
    providers: Sequence[Mapping[str, Any]] | None = None,
    panel_models: str | None = _UNSET_CONFIG,
    judge_model: str | None = _UNSET_CONFIG,
) -> dict[str, Any] | None:
    """The operator-pinned panel from ``QUORUM_PANEL_MODELS`` / ``QUORUM_JUDGE_MODEL``.

    Returns ``{"models": [...], "judge": str | None}`` when ``QUORUM_PANEL_MODELS``
    is set (validated — a non-callable entry raises :class:`ValidationError`), or
    ``None`` when it is unset so the caller falls through to the preset / connected
    resolution. ``panel_models`` / ``judge_model`` are injectable for tests; unset
    (the default) reads them from the layered appconfig loader (registry default <
    config-file ``env:`` section < ``os.environ`` < override).
    """

    if panel_models is _UNSET_CONFIG:
        from forecasting import appconfig

        panel_models = appconfig.get_str(QUORUM_PANEL_MODELS_KEY, None)
    models = parse_panel_models_config(panel_models)
    if not models:
        return None
    validate_panel_models(models, providers=providers)
    if judge_model is _UNSET_CONFIG:
        from forecasting import appconfig

        judge_model = appconfig.get_str(QUORUM_JUDGE_MODEL_KEY, None)
    judge = (str(judge_model).strip() if judge_model else "") or None
    if judge:
        validate_panel_models([judge], providers=providers)
    return {"models": models, "judge": judge}


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
    *, model_count: int, delphi_rounds: int, has_judge: bool = True, trials: int = 1
) -> int:
    """Pre-run model-call estimate for a quorum.

    Each round dispatches ``model_count`` panelists — each run ``trials`` times per
    seat (BLF A2 multi-trial; ``trials=1`` is the default and byte-identical) — plus
    (if wired) one judge. A Delphi run adds a second full round (``delphi_rounds`` in
    {0, 1}). Supervisor fresh-search, when enabled, adds further full rounds — it is
    OPT-IN/OFF by default and reported separately, so it is deliberately excluded
    here (the estimate is the guaranteed floor, not the search-enabled ceiling)."""

    rounds = max(1, int(delphi_rounds) + 1)
    per_round = max(1, int(model_count)) * max(1, int(trials)) + (1 if has_judge else 0)
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
      * ``medium`` impact → ``budget`` panel, one Delphi revision round, trim.
      * routine / low / unset → ``self`` fusion, no revision, no trim — cheap.

    DELPHI TRIGGER (the audit's finding #1: Delphi had fired 0/223 while gated to
    high/contested only): the anonymous revision round is defaulted ON for every
    LIVE **multi-model** panel (``frontier`` + ``budget``), because a genuine second
    read of independent panelists is where an anonymous revision earns its extra
    round. It stays OFF for single-model ``self`` fusion (N samples of ONE model —
    a revision among clones of the same model buys little and doubles cost) and is
    still cost-capped: ``cap_preset_by_calls`` drops the Delphi round FIRST when a
    run would overrun ``max_calls``.

    Then the SINGLE-KEY REALITY GUARD (item 3): when the resolved multi-provider
    preset spans a provider that is not reachable (only one provider key present,
    no OpenRouter), it falls back to ``self`` (the active model sampled) with a
    note — a panel that would silently error every non-local panelist is worse
    than an honest self-fusion. Because that fallback makes the run single-model,
    the Delphi round is dropped with it (Delphi is a multi-model default).

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
        # Multi-model budget panel → Delphi ON (a real second read of independent
        # panelists earns the anonymous revision round; the cap drops it if over budget).
        preset, delphi_rounds, trim = "budget", 1, 1
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
                # A self-fusion run is single-model, so drop the Delphi revision that
                # only makes sense across independent panelists.
                delphi_rounds = 0
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


def resolve_trial_count(
    question: Any,
    *,
    high_impact_trials: int = _HIGH_IMPACT_TRIALS,
    default_trials: int = _DEFAULT_TRIALS,
    override: int | None = None,
) -> tuple[int, str]:
    """Map a question's IMPACT onto K trials-per-panelist (BLF A2).

    ``high`` impact runs ``high_impact_trials`` draws per seat (default 3 — a
    contested, expensive-to-be-wrong question deserves the variance-reduced pool);
    every other question stays ``default_trials`` (1 — a single draw, byte-identical
    to a pre-A2 panelist). An explicit ``override`` (a per-run spec value) always
    wins. Returns ``(K, reason)`` so the printable defaults line can name why. The
    resolved K is bounded downstream by :func:`cap_trials_by_calls` + the policy
    matrix's LLM_SPEND cap — the same brakes that bound panel width."""

    if override is not None:
        return max(1, int(override)), f"trials override={int(override)}"
    impact = (getattr(question, "impact", None) or "").strip().lower()
    if impact == "high":
        return max(1, int(high_impact_trials)), (
            f"impact=high → K={max(1, int(high_impact_trials))} trials/panelist"
        )
    return max(1, int(default_trials)), (
        f"impact={impact or 'unset'} → K={max(1, int(default_trials))} trial/panelist"
    )


def cap_trials_by_calls(
    *,
    preset: str | None,
    delphi_rounds: int,
    samples: int,
    trials: int,
    max_calls: int,
    has_judge: bool = True,
) -> tuple[int, str | None]:
    """Bound K trials-per-panelist to fit ``max_calls`` given the (already-capped)
    panel shape.

    Extra trials of the SAME seats are the cheapest lever to cut, so this runs AFTER
    :func:`cap_preset_by_calls` has fixed the panel width/Delphi/samples: it steps K
    down to the largest value whose total call estimate still fits ``max_calls``,
    never below 1. Returns ``(trials, note)`` — ``note`` is ``None`` when the
    requested K already fit (nothing changed), so a default K=1 run is untouched."""

    model_count = preset_model_count(preset, samples=samples)
    requested = max(1, int(trials))
    k = requested
    while k > 1 and estimate_quorum_calls(
        model_count=model_count, delphi_rounds=delphi_rounds, has_judge=has_judge, trials=k
    ) > int(max_calls):
        k -= 1
    if k == requested:
        return requested, None
    return k, f"trials {requested}→{k} to fit max_calls={int(max_calls)}"


def _shrunk_logit_mean(
    probabilities: Sequence[float],
    *,
    target: float | None,
    floor: float = _TRIAL_SHRINK_FLOOR,
    c: float = _TRIAL_SHRINK_C,
) -> tuple[float, float, float]:
    """Pool trial probabilities as a James–Stein shrunken logit mean (BLF A2).

    Computes ``ℓ̂ = α·ℓ̄ + (1−α)·logit(target)`` with ``α = max(floor, 1 − c·s²)``
    clamped to [0, 1], where ``ℓ̄`` is the mean of the trial logits and ``s²`` their
    (population) variance: the noisier the trials, the smaller α, the harder the pool
    shrinks toward the anchor. ``target=None`` shrinks toward the trials' OWN logit
    mean — a strict no-op (pooled == mean), used for the market-INDEPENDENT blind
    pool so the orthogonality signal is never contaminated by the anchor. Returns
    ``(pooled_probability, alpha, var_logit)``; a single trial has ``s²=0 → α=1`` so
    the pool is exactly that trial (K=1 identity)."""

    from forecasting.bayes_toolkit import inv_logit, logit

    logits = [logit(float(p)) for p in probabilities]
    n = len(logits)
    if n == 0:
        raise ValidationError("_shrunk_logit_mean requires at least one probability")
    mean = sum(logits) / n
    var = sum((x - mean) ** 2 for x in logits) / n if n > 1 else 0.0
    target_logit = logit(float(target)) if target is not None else mean
    alpha = max(float(floor), 1.0 - float(c) * var)
    alpha = min(1.0, max(0.0, alpha))
    pooled = inv_logit(alpha * mean + (1.0 - alpha) * target_logit)
    return float(pooled), float(alpha), float(var)


def _pool_seat_trials(
    model: str,
    trials: Sequence[ModelForecast],
    *,
    market_anchor: float | None,
    floor: float = _TRIAL_SHRINK_FLOOR,
    c: float = _TRIAL_SHRINK_C,
) -> ModelForecast:
    """Pool a seat's K trials (BLF A2) into ONE representative ModelForecast.

    The COMMITTED (reconciled) numbers shrink toward the outside-view anchor — the
    market price when present, else the trials' own mean (a no-op) — via
    :func:`_shrunk_logit_mean`; the BLIND numbers pool market-INDEPENDENTLY (target
    ``None``) so ``blind_pool`` orthogonality is never contaminated by the anchor.
    The trial NEAREST the pooled number carries the seat's qualitative headline
    (rationale / reasons / crux / belief_trajectory — the pool itself is not a new
    argument), every trial (survivor and error) is recorded in ``.trials`` so a
    divergent lone-skeptic trial stays discoverable, and the pool summary lands in
    ``.trial_shrinkage``. A seat where ALL trials errored returns the first errored
    trial, labeled — excluded from the cross-model pool exactly as a single failed
    panelist is."""

    survivors = [f for f in trials if f.error is None]
    n = len(trials)
    if not survivors:
        rep = trials[0]
        rep.trial_shrinkage = {
            "n_trials": n,
            "survivors": 0,
            "alpha": None,
            "var_logit": None,
            "target": None,
            "degraded": True,
        }
        return rep

    pooled_p, alpha, var = _shrunk_logit_mean(
        [f.probability for f in survivors], target=market_anchor, floor=floor, c=c
    )
    blind = [f.blind_probability for f in survivors if f.blind_probability is not None]
    blind_pooled = (
        _shrunk_logit_mean(blind, target=None, floor=floor, c=c)[0] if blind else None
    )
    rep = min(survivors, key=lambda f: abs(f.probability - pooled_p))
    seat = ModelForecast(
        model=model,
        probability=pooled_p,
        confidence_low=rep.confidence_low,
        confidence_high=rep.confidence_high,
        rationale=rep.rationale,
        reasons_up=list(rep.reasons_up),
        reasons_down=list(rep.reasons_down),
        change_my_mind=list(rep.change_my_mind),
        crux=rep.crux,
        weight=rep.weight,
        reconcile_reason=rep.reconcile_reason,
        revision_reason=rep.revision_reason,
        belief_trajectory=list(rep.belief_trajectory),
    )
    # Mirror _run_trial's contract: blind == committed on the single-phase
    # (non-market) path, distinct on a market question.
    seat.blind_probability = blind_pooled if market_anchor is not None else pooled_p
    seat.reconciled_probability = pooled_p
    seat.trials = [
        {
            "trial": i + 1,
            "probability": round(f.probability, 6) if f.error is None else None,
            "blind_probability": (
                round(f.blind_probability, 6)
                if f.blind_probability is not None
                else None
            ),
            "crux": f.crux,
            "moved_by": (
                f.belief_trajectory[-1].get("moved_by") if f.belief_trajectory else None
            ),
            "error": f.error,
        }
        for i, f in enumerate(trials)
    ]
    seat.trial_shrinkage = {
        "n_trials": n,
        "survivors": len(survivors),
        "alpha": round(alpha, 6),
        "var_logit": round(var, 6),
        "target": (
            round(float(market_anchor), 6)
            if market_anchor is not None
            else "trial_mean"
        ),
        "degraded": len(survivors) < n,
    }
    return seat


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


def apply_market_anchor_discipline(
    committed: float,
    *,
    market_anchor: float | None,
    justification: str | None,
    threshold_pp: float = 10.0,
) -> dict[str, Any]:
    """FIX B — enforce the market-as-prior doctrine on the committed verdict.

    The market price is the OUTSIDE-VIEW anchor. When the verdict deviates more than
    ``threshold_pp`` (default 10pp) from it WITHOUT a named edge (``justification``),
    the deviation is unjustified and the verdict is PULLED back toward the market —
    via the same honest weighted machinery :mod:`forecasting.market_ensemble` uses to
    pool a forecast with a de-vigged market: the equal-weight LOG-ODDS pool
    (:func:`forecasting.bayes_toolkit.log_odds_pool`), the KL-optimal, externally-
    Bayesian pooling operator. A justified deviation (a non-empty named edge) is
    LEFT ALONE — the discipline requires a reason, it does not forbid an edge.

    Returns ``{"probability", "deviation_pp", "justification", "pull_applied"}``.
    With no anchor the committed number passes through untouched.
    """

    if market_anchor is None:
        return {
            "probability": float(committed),
            "deviation_pp": None,
            "justification": None,
            "pull_applied": False,
        }
    anchor = float(market_anchor)
    deviation_pp = abs(float(committed) - anchor) * 100.0
    named_edge = bool((justification or "").strip())
    if deviation_pp <= float(threshold_pp) or named_edge:
        # Within discipline, or a genuine named edge justifies the deviation.
        return {
            "probability": float(committed),
            "deviation_pp": deviation_pp,
            "justification": (justification or "").strip() or None,
            "pull_applied": False,
        }
    # Unjustified over-deviation: pull toward the market in log-odds space.
    from forecasting.bayes_toolkit import log_odds_pool

    pulled = float(log_odds_pool([anchor, float(committed)]))
    return {
        "probability": pulled,
        "deviation_pp": abs(pulled - anchor) * 100.0,
        "justification": "insufficient justification — verdict pulled toward market",
        "pull_applied": True,
    }


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
    market_anchor: float | None = None,
    market_anchor_threshold_pp: float = 10.0,
    trials: int = 1,
    trial_shrink_floor: float = _TRIAL_SHRINK_FLOOR,
    trial_shrink_c: float = _TRIAL_SHRINK_C,
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

    ``trials`` (BLF A2 multi-trial) runs K independent draws PER PANELIST seat and
    pools them, before the cross-model pool, as a James–Stein shrunken logit mean
    toward the outside-view anchor (:func:`_shrunk_logit_mean`, floor
    ``trial_shrink_floor`` = f, sensitivity ``trial_shrink_c`` = c): the noisier a
    seat's trials, the harder its pool shrinks to the anchor (the market price when
    present, else the trials' own mean — a no-op). ``trials=1`` (the default) is a
    strict identity — one draw per seat, no pooling wrapper — so an un-configured
    quorum is byte-identical. On a K>1 seat the pooled ModelForecast carries every
    surviving trial in ``.trials`` (a divergent lone-skeptic trial stays
    discoverable) and the pool summary in ``.trial_shrinkage``; the FULL trial sample
    (not just the pooled seats) feeds :func:`disagreement_signal`, so trial
    divergence widens the measured spread, and each seat's BLIND trials pool
    market-INDEPENDENTLY into ``blind_pool`` so the orthogonality signal is intact.
    A seat where some trials error is labeled (``trial_shrinkage['degraded']``); a
    seat where ALL trials error is an errored panelist, excluded from the pool
    exactly as a single failed panelist is today.
    """

    if not models:
        raise ValidationError("quorum requires at least one model")
    if delphi_rounds not in (0, 1):
        raise ValidationError("delphi_rounds must be 0 or 1")
    trials = max(1, int(trials))
    judge_runner = judge_runner or runner

    def _blind_reconcile(
        model: str,
        system: str,
        blind_user: str,
        build_reconcile: "Callable[[str], str]",
    ) -> tuple[str, str]:
        """One BLIND turn then one RECONCILE turn (UPGRADE 1), returning both raw
        responses. ``blind_user`` NEVER carries the market anchor — the anchor is
        introduced only by the ``build_reconcile(blind_text)`` follow-up, AFTER the
        blind turn's output exists (so a test can prove phase-1 anchor-absence).

        Cost-optimal single-session path when the production runner exposes a
        ``.two_turn`` capability (:func:`make_aiagent_runner`): it builds ONE agent,
        runs both turns on the SAME conversation, so the blind turn's expensive
        research is not repeated (~half the cost of two independent sessions). Any
        runner WITHOUT ``.two_turn`` (e.g. an injected test stub) falls back to two
        plain calls — the fresh second call re-supplies the blind context + the
        reconcile block. Both paths keep the anchor out of the blind turn.
        """

        two_turn = getattr(runner, "two_turn", None)
        if callable(two_turn):
            return two_turn(model, system, blind_user, build_reconcile)
        blind_text = runner(model, system, blind_user)
        reconcile_block = build_reconcile(blind_text)
        reconciled_text = runner(model, system, blind_user + reconcile_block)
        return blind_text, reconciled_text

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

        def _run_trial(index: int, model: str) -> ModelForecast:
            """One independent DRAW for a seat (BLF A2). Builds the (blind, anchor-
            free) prompt, runs the single-phase or blind-then-reconcile turns, and
            returns a ModelForecast with its INTRINSIC fields set — committed
            probability, the blind/reconciled numbers + reason, the delphi
            revision_reason, the belief trajectory (A1), and the track-record weight.
            Seat-level provenance (participant_id/round_index/prior) is stamped by
            ``_dispatch`` so a K>1 pooled seat and a K=1 passthrough share one path."""

            # BLIND prompt (UPGRADE 1): the market anchor is ALWAYS withheld from
            # phase 1 — we pass ``market_anchor=None`` so no anchor block is built.
            # On a non-market question market_anchor is None anyway, so this is the
            # unchanged single-phase prompt; on a market question the anchor is
            # introduced only in the RECONCILE turn below.
            prompt = build_panelist_prompt(
                question_title=question_title,
                resolution_criteria=resolution_criteria,
                context_packet=working_context,
                evidence_cutoff=evidence_cutoff,
                sample_hint=index + 1 if self_fusion else None,
                market_anchor=None,
            )
            blind_user = prompt["user"]
            if delphi_summary is not None:
                prior = (
                    prior_by_participant.get(f"p{index + 1:02d}")
                    if prior_by_participant is not None
                    else None
                )
                blind_user = blind_user + build_revision_context_block(
                    prior=prior, delphi_summary=delphi_summary
                )
            system = prompt["system"]
            revision_reason: str | None = None
            reconcile_reason: str | None = None
            blind_probability: float | None = None
            try:
                if market_anchor is not None:
                    # BLIND-THEN-RECONCILE (market-linked): commit a blind number,
                    # THEN reveal the anchor + own blind number and reconcile.
                    def _reconcile_from_blind(blind_text: str) -> str:
                        bfc = parse_panelist_response(blind_text, model)
                        return build_reconcile_block(
                            blind_probability=bfc.probability,
                            market_anchor=market_anchor,
                            threshold_pp=market_anchor_threshold_pp,
                        )

                    blind_raw, reconciled_raw = _blind_reconcile(
                        model, system, blind_user, _reconcile_from_blind
                    )
                    blind_probability = parse_panelist_response(
                        blind_raw, model
                    ).probability
                    forecast = parse_panelist_response(reconciled_raw, model)
                    payload = _reparse_full(reconciled_raw)
                    rr = payload.get("reconcile_reason")
                    reconcile_reason = str(rr).strip() if rr else None
                    if delphi_summary is not None:
                        dv = payload.get("revision_reason")
                        revision_reason = str(dv).strip() if dv else None
                else:
                    # SINGLE-PHASE (non-market) — byte-identical to before.
                    raw = runner(model, system, blind_user)
                    forecast = parse_panelist_response(raw, model)
                    blind_probability = forecast.probability
                    if delphi_summary is not None:
                        rr = _reparse_full(raw).get("revision_reason")
                        revision_reason = str(rr).strip() if rr else None
            except Exception as exc:  # noqa: BLE001 — isolate one trial's failure
                # Any single draw failing (bad JSON, timeout, provider/SDK error, or a
                # broken reconcile turn) is recorded as an errored trial; the seat
                # pools on its survivors and the quorum completes on the survivors.
                forecast = ModelForecast(
                    model=model, probability=0.5, error=f"{type(exc).__name__}: {exc}"
                )
            forecast.revision_reason = revision_reason
            # Blind-then-reconcile provenance: record BOTH numbers on a surviving
            # trial (blind == committed on the single-phase path; distinct on a
            # market question). Errored trials carry neither (excluded from pooling).
            forecast.reconcile_reason = reconcile_reason
            forecast.blind_probability = (
                blind_probability if forecast.error is None else None
            )
            forecast.reconciled_probability = (
                forecast.probability if forecast.error is None else None
            )
            # Track-record weighting (S7): a surviving trial carries its measured
            # weight (default 1.0 when unmeasured/cold-start), consumed by the pool +
            # disagreement. Errored trials keep 1.0 but are excluded from pooling.
            if model_weights and forecast.error is None:
                try:
                    forecast.weight = float(model_weights.get(model, 1.0))
                except (TypeError, ValueError):
                    forecast.weight = 1.0
            return forecast

        def _dispatch(index: int, model: str) -> ModelForecast:
            """Produce ONE seat forecast: run K trials (BLF A2) and pool them, then
            stamp the seat-level provenance. K=1 is a strict passthrough — the single
            trial, unchanged — so a default quorum is byte-identical to pre-A2."""

            participant_id = f"p{index + 1:02d}"
            prior = (
                prior_by_participant.get(participant_id)
                if prior_by_participant is not None
                else None
            )
            trial_forecasts = [_run_trial(index, model) for _ in range(trials)]
            seat = (
                trial_forecasts[0]
                if trials == 1
                else _pool_seat_trials(
                    model,
                    trial_forecasts,
                    market_anchor=market_anchor,
                    floor=trial_shrink_floor,
                    c=trial_shrink_c,
                )
            )
            # Delphi provenance (harmless on the round-1 / non-delphi path: seat id
            # set, round_index=1, no prior, no revision_reason).
            seat.participant_id = participant_id
            seat.round_index = round_index
            seat.prior_probability = prior.probability if prior is not None else None
            if on_progress:
                pooled_note = "" if trials == 1 else f" (pooled over {trials} trials)"
                on_progress(
                    "panelist_done",
                    f"{model}: "
                    + ("error" if seat.error else f"{seat.probability:.3f}")
                    + pooled_note,
                )
            return seat

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
        # Disagreement is measured over the FULL trial sample (BLF A2): the cross-
        # model pool commits on the variance-reduced per-seat numbers, but a divergent
        # lone-skeptic TRIAL must still widen the measured spread. A K=1 seat reports
        # its one committed number, so this is byte-identical to the pre-A2 signal.
        trial_probs: list[float] = []
        trial_weights: list[float] = []
        for f in ok:
            for p in f.trial_probabilities:
                trial_probs.append(p)
                trial_weights.append(f.weight)
        pass_disagreement = disagreement_signal(trial_probs, trial_weights)

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
                market_anchor=market_anchor,
                market_anchor_threshold_pp=market_anchor_threshold_pp,
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

    # ── market-anchor discipline (FIX B) ───────────────────────────────────────
    # On a market-linked question the current de-vigged market price is the outside-
    # view anchor. A verdict that deviates more than the threshold from it WITHOUT a
    # named edge is pulled back toward the market via the log-odds pool — applied to
    # the ALREADY-committed (override-resolved, Platt'd) number exactly once.
    anchor_result = apply_market_anchor_discipline(
        final_probability,
        market_anchor=market_anchor,
        justification=(
            judge.market_deviation_justification if judge is not None else None
        ),
        threshold_pp=market_anchor_threshold_pp,
    )
    final_probability = anchor_result["probability"]
    if anchor_result["pull_applied"] and on_progress:
        on_progress(
            "market_anchor_pull",
            f"deviation {anchor_result['deviation_pp']:.1f}pp unjustified — "
            f"pulled toward market {float(market_anchor):.3f}",
        )

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

    # Self-fusion pseudo-diversity caveat (FIX B): N samples of ONE model is not
    # independent multi-model fusion, so label the spread honestly.
    pseudo_diversity_caveat: str | None = None
    if self_fusion:
        pseudo_diversity_caveat = (
            f"self-fusion: {ok_count} sample(s) of ONE model — pseudo-diversity, "
            "not independent multi-model fusion; the spread reflects resampling, "
            "not model disagreement"
        )

    # Blind-then-reconcile pools (UPGRADE 1 — the continuous orthogonality signal).
    # ``reconciled_pool`` IS the pool the commit path used (the reconciled numbers);
    # ``blind_pool`` re-pools the panelists' BLIND (pre-anchor) numbers with the SAME
    # method/trim/alpha so blind, reconciled, and market sit in one comparable space.
    # Only on a market question (no anchor → no blind/reconcile split → both None).
    blind_pool: float | None = None
    reconciled_pool: float | None = None
    if market_anchor is not None:
        ok_final = [f for f in forecasts if f.error is None]
        reconciled_pool = aggregation.aggregate_probability
        blind_rows = [
            {**f.to_estimate(), "probability": float(f.blind_probability)}
            for f in ok_final
            if f.blind_probability is not None
        ]
        if blind_rows:
            blind_pool = aggregate_panel_estimates(
                blind_rows,
                method=pool_method,
                trim=trim,
                alpha_extremize=alpha_extremize,
            ).aggregate_probability

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
        market_price=float(market_anchor) if market_anchor is not None else None,
        market_deviation_pp=anchor_result["deviation_pp"],
        market_justification=anchor_result["justification"],
        market_pull_applied=anchor_result["pull_applied"],
        blind_pool=blind_pool,
        reconciled_pool=reconciled_pool,
        pseudo_diversity_caveat=pseudo_diversity_caveat,
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

        # FIX A: a rebuilt connected panel dispatches ``provider:model`` ids so each
        # panelist runs on ITS provider's native model. Split the leading known-
        # provider token and route it explicitly; a bare/OpenRouter id (no known
        # prefix) keeps ``requested_provider`` and auto-resolves as before.
        provider_prefix, bare_model = _split_provider_model(model)
        agent = build_agent(
            model=bare_model,
            requested_provider=provider_prefix or requested_provider,
            enabled_toolsets=list(toolsets),
            max_iterations=max_iterations,
            quiet_mode=quiet,
            skip_memory=True,
            skip_context_files=True,
            load_soul_identity=False,
            platform="cli",
        )
        result = agent.run_conversation(user, system_message=system)
        if not isinstance(result, dict):
            return str(result or "")
        # HONEST ERROR SURFACING. When the agent run FAILED (a non-retryable 400
        # model-not-supported, a 429 quota-exhaustion, etc.) the loop sets
        # ``failed``/``error`` and leaves ``final_response`` either None or an error
        # BANNER carrying no JSON. Passing that straight to the JSON parser masks the
        # real cause behind a misleading "response is empty" / "did not contain a JSON
        # object" — the exact two symptoms the live quorum surfaced. Raise the REAL
        # error so run_quorum records the panelist's honest, actionable failure reason.
        if result.get("failed") or result.get("error"):
            detail = str(result.get("error") or "").strip()
            raise RuntimeError(detail or "model call failed with no response")
        return _assemble_response_text(result)

    def _call_two_turn(
        model: str,
        system: str,
        blind_user: str,
        build_reconcile: "Callable[[str], str]",
    ) -> tuple[str, str]:
        """BLIND then RECONCILE on ONE agent session (UPGRADE 1). Builds the agent
        ONCE, runs the (expensive, research-heavy) blind turn, then continues the
        SAME conversation with the reconcile follow-up — so the anchor reaches the
        model only in turn 2 and the blind research is not paid for twice."""

        from agent.agent_factory import build_agent

        provider_prefix, bare_model = _split_provider_model(model)
        agent = build_agent(
            model=bare_model,
            requested_provider=provider_prefix or requested_provider,
            enabled_toolsets=list(toolsets),
            max_iterations=max_iterations,
            quiet_mode=quiet,
            skip_memory=True,
            skip_context_files=True,
            load_soul_identity=False,
            platform="cli",
        )
        r1 = agent.run_conversation(blind_user, system_message=system)
        if not isinstance(r1, dict):
            blind_text = str(r1 or "")
            history: Any = None
        else:
            if r1.get("failed") or r1.get("error"):
                detail = str(r1.get("error") or "").strip()
                raise RuntimeError(detail or "blind turn failed with no response")
            blind_text = _assemble_response_text(r1)
            history = r1.get("messages")
        # Only NOW does the anchor enter (build_reconcile parses the blind text, may raise).
        reconcile_user = build_reconcile(blind_text)
        r2 = agent.run_conversation(reconcile_user, conversation_history=history)
        if not isinstance(r2, dict):
            return blind_text, str(r2 or "")
        if r2.get("failed") or r2.get("error"):
            detail = str(r2.get("error") or "").strip()
            raise RuntimeError(detail or "reconcile turn failed with no response")
        return blind_text, _assemble_response_text(r2)

    def _run_with_timeout(model: str, fn: "Callable[[], Any]") -> Any:
        if not timeout or timeout <= 0:
            return fn()
        import threading

        box: dict[str, Any] = {}

        def _target() -> None:
            try:
                box["result"] = fn()
            except Exception as exc:  # noqa: BLE001 — surfaced to the caller below
                box["error"] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            raise RuntimeError(f"model {model} timed out after {timeout:g}s")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def _runner(model: str, system: str, user: str) -> str:
        return _run_with_timeout(model, lambda: _call(model, system, user)) or ""

    def _two_turn(
        model: str,
        system: str,
        blind_user: str,
        build_reconcile: "Callable[[str], str]",
    ) -> tuple[str, str]:
        result = _run_with_timeout(
            model, lambda: _call_two_turn(model, system, blind_user, build_reconcile)
        )
        return result if result is not None else ("", "")

    # The blind-then-reconcile single-session seam (UPGRADE 1). run_quorum detects it
    # via ``getattr(runner, "two_turn", None)``; an injected test stub without it
    # falls back to two plain calls, so this is purely additive.
    _runner.two_turn = _two_turn  # type: ignore[attr-defined]
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
    "build_reconcile_block",
    "build_judge_prompt",
    "build_delphi_summary",
    "build_revision_context_block",
    "parse_panelist_response",
    "parse_judge_response",
    "resolve_models",
    "resolve_final_probability",
    "resolve_quorum_defaults",
    "apply_market_anchor_discipline",
    "available_provider_slugs",
    "available_providers_detail",
    "resolve_connected_panel",
    "parse_panel_models_config",
    "validate_panel_models",
    "resolve_configured_panel",
    "QUORUM_PANEL_MODELS_KEY",
    "QUORUM_JUDGE_MODEL_KEY",
    "models_reachable",
    "preset_model_count",
    "estimate_quorum_calls",
    "cap_preset_by_calls",
    "resolve_trial_count",
    "cap_trials_by_calls",
    "should_research",
    "run_quorum",
    "quorum_auto_indicated",
    "make_aiagent_runner",
]
