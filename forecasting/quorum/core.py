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

# ── Variance-adaptive cross-model pool shrinkage (BLF A3) ─────────────────────
# The CROSS-MODEL pool (the aggregate AFTER A2's per-panelist trial pooling) is
# shrunk toward the outside-view anchor by the SAME James–Stein family as A2 — one
# shrinkage philosophy at both layers, differing only in the variance it reads.
# A2 shrinks a seat's K trials by the INTER-TRIAL logit variance (within-seat
# noise); A3 shrinks the panel's pool by the CROSS-PANELIST logit variance the
# ``disagreement_signal`` already computes (between-panelist noise, ``sd_logit²``).
# BLF's rule: the noisier the panel, the harder the pool leans on the anchor.
#
#     α_pool = max(f, 1 − c·max(0, s² − s²_calm))
#     ℓ_pool = α_pool·logit(pool) + (1 − α_pool)·logit(anchor)
#
# The CALM DEAD-ZONE (the hinge at ``s²_calm``) is what makes default-ON safe: at
# or below the calm/moderate disagreement-band edge the pool is UNMOVED (α≡1, a
# STRICT no-op — bit-identical to the pre-A3 pool), and because the hinge is
# CONTINUOUS the shrinkage grows smoothly from zero just past it — there is no
# cliff at the band edge. ``f`` floors the pool's own weight at ½ (it never
# collapses onto the anchor); ``c`` sets how fast excess disagreement pulls toward
# it. Documented, LOO-CV-able defaults, deliberately EQUAL to A2's f/c for
# coherence — two layers of the same rule at two scopes.
_POOL_SHRINK_FLOOR = 0.5
_POOL_SHRINK_C = 0.5
# The calm/moderate disagreement-band edge expressed in logit-variance space: the
# disagreement index is ``tanh(sd_logit / scale)`` and the calm band is index<0.15
# under ``scale=2.0`` (forecasting.panel), so the edge sits at
# ``s²_calm = (2·atanh(0.15))² ≈ 0.0914``. Below it ``disagreement_signal`` labels
# the panel "calm" and A3 leaves it untouched; a change to panel's scale/band would
# want this kept in sync (a boundary test pins the correspondence).
_POOL_SHRINK_CALM_VAR = (2.0 * math.atanh(0.15)) ** 2

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
    # Variance-adaptive cross-model pool shrinkage (BLF A3). Provenance for the
    # shrink of the DEFAULT pool toward the outside-view anchor: ``{alpha, var_logit,
    # anchor, anchor_source, floor, c, calm_var, pre_shrink_pool, shrunk}`` — so every
    # pooled number records its α + inputs and the formula is reconstructable. None on
    # an anchorless question (no market link, no recorded prior); a dict with
    # ``shrunk=False`` / ``alpha=1.0`` on a calm anchored panel (the strict no-op).
    pool_shrinkage: dict[str, Any] | None = None

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
            # Variance-adaptive pool shrinkage provenance (BLF A3). None on an
            # anchorless question so the payload stays byte-compatible there.
            "pool_shrinkage": self.pool_shrinkage,
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
                    # BLF A1/A2 process visibility (the durable per-step trajectory +
                    # per-trial provenance live on the estimate metadata; here the
                    # run-status carries only the compact indicators). ``belief_steps``
                    # is 0 and ``trial_shrinkage`` None on the legacy/K=1 path, so a
                    # baseline payload stays byte-compatible.
                    "belief_steps": len(f.belief_trajectory),
                    "trial_shrinkage": f.trial_shrinkage,
                }
                for f in self.forecasts
            ],
        }


# ── Orchestration ────────────────────────────────────────────────────────────


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
    outside_view_prior: float | None = None,
    trials: int = 1,
    trial_shrink_floor: float = _TRIAL_SHRINK_FLOOR,
    trial_shrink_c: float = _TRIAL_SHRINK_C,
    pool_shrink_floor: float = _POOL_SHRINK_FLOOR,
    pool_shrink_c: float = _POOL_SHRINK_C,
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

    ``outside_view_prior`` (BLF A3) is the recorded outside-view prior used as the
    shrink anchor when the question carries NO live market. The A3 anchor is the
    ``market_anchor`` where linked, ELSE ``outside_view_prior``, else nothing (no-op).

    ``pool_shrink_floor`` / ``pool_shrink_c`` (BLF A3) parameterise the
    VARIANCE-ADAPTIVE shrink of the DEFAULT cross-model pool toward that anchor
    (:func:`shrink_pool_toward_anchor`), the aggregation-layer sibling of A2's
    per-panelist trial shrink. The pool is pulled toward the anchor by
    ``α = max(f, 1 − c·max(0, s² − s²_calm))`` with ``s²`` the CROSS-PANELIST logit
    variance (``disagreement.sd_logit²``) — the noisier the panel, the harder it
    leans on the anchor — while a CALM panel (``s² ≤ s²_calm``) or an anchorless
    question is a STRICT no-op, so the committed number is bit-identical to the
    pre-A3 pool there (the default-ON safety case). The shrink governs only the
    DEFAULT pool: a high-confidence judge override (the named edge) replaces the
    shrunk pool wholesale, and the market-anchor discipline still keeps a justified
    deviation. Every pooled number's α + inputs land on ``QuorumResult.pool_shrinkage``.
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

    # ── variance-adaptive cross-model pool shrinkage (BLF A3) ──────────────────
    # The DEFAULT cross-model pool (post per-panelist trial pooling) is shrunk toward
    # the outside-view anchor — the market price where linked, else the recorded
    # outside-view prior — as a CONTINUOUS function of cross-panelist disagreement:
    # the noisier the panel, the harder it leans on the anchor (calm ⇒ strict no-op).
    # This governs only the DEFAULT pool: a named edge is NOT shrunk — the judge_high
    # override below replaces the (shrunk) pool wholesale, and the deviation discipline
    # still keeps a justified deviation — so the shrink lands on the number the desk
    # would otherwise commit by default. Every pooled number records its α + inputs.
    pool_anchor = market_anchor if market_anchor is not None else outside_view_prior
    _shrink = shrink_pool_toward_anchor(
        aggregation.aggregate_probability,
        anchor=pool_anchor,
        var_logit=float(disagreement.get("sd_logit", 0.0)) ** 2,
        floor=pool_shrink_floor,
        c=pool_shrink_c,
    )
    shrunk_pool = _shrink["probability"]
    pool_shrinkage: dict[str, Any] | None = (
        {
            "alpha": round(_shrink["alpha"], 6),
            "var_logit": round(_shrink["var_logit"], 6),
            "anchor": round(float(_shrink["anchor"]), 6),
            "anchor_source": (
                "market" if market_anchor is not None else "outside_view_prior"
            ),
            "floor": _shrink["floor"],
            "c": _shrink["c"],
            "calm_var": round(_shrink["calm_var"], 6),
            "pre_shrink_pool": round(float(aggregation.aggregate_probability), 6),
            "shrunk": _shrink["shrunk"],
        }
        if pool_anchor is not None
        else None
    )
    if _shrink["shrunk"] and on_progress:
        on_progress(
            "pool_shrink",
            f"panel noisy (s²={_shrink['var_logit']:.3f}) → α={_shrink['alpha']:.3f}; "
            f"pool {aggregation.aggregate_probability:.3f}→{shrunk_pool:.3f} toward "
            f"anchor {float(pool_anchor):.3f}",
        )

    # ── confidence-gated supervisor override (AIA P0.3) ────────────────────────
    # The pool is already terminally-Platt'd inside aggregate_panel_estimates.
    # resolve_final_probability picks the winning branch on the RAW numbers; we
    # then Platt the judge's raw override here so terminal calibration lands on
    # whichever number wins EXACTLY ONCE (pool: Platt'd in aggregation; judge:
    # Platt'd just below). Never both, never zero times. The pool branch commits the
    # A3-SHRUNK pool; the judge_high branch (the named edge) escapes the shrink.
    final_probability, final_source = resolve_final_probability(
        shrunk_pool, judge
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
        pool_shrinkage=pool_shrinkage,
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


# ── Carved-leaf re-exports (surface parity + run_quorum runtime) ──────────────
# ``prompts`` (W3.a) — re-import the public builders (kept in ``__all__``) and the
# private ``_delphi_audit_round`` that ``run_quorum`` calls, so both the façade's
# ``import *`` surface and the orchestrator's call sites resolve unchanged.
from forecasting.quorum.prompts import build_panelist_prompt, build_reconcile_block, build_judge_prompt
from forecasting.quorum.prompts import build_delphi_summary, build_revision_context_block, _delphi_audit_round
# ``parsing`` (W3.a) — the two public parsers (``__all__``) plus the private
# ``_reparse_full`` / ``_assemble_response_text`` that ``run_quorum`` calls.
from forecasting.quorum.parsing import parse_panelist_response, parse_judge_response
from forecasting.quorum.parsing import _reparse_full, _assemble_response_text
# ``panels`` (W3.a) — the public model/provider/panel resolvers + config-key
# constants (``__all__`` surface; ``resolve_quorum_defaults`` reads the keys).
from forecasting.quorum.panels import resolve_models, models_reachable, quorum_auto_indicated
from forecasting.quorum.panels import available_provider_slugs, available_providers_detail, resolve_connected_panel
from forecasting.quorum.panels import parse_panel_models_config, validate_panel_models, resolve_configured_panel
from forecasting.quorum.panels import QUORUM_PANEL_MODELS_KEY, QUORUM_JUDGE_MODEL_KEY
# ``_split_provider_model`` (private) — ``make_aiagent_runner`` splits provider:model.
from forecasting.quorum.panels import _split_provider_model
# ``estimation`` (W3.a) — call-count / preset-cap / trial-count machinery
# (``__all__`` surface; ``run_quorum`` calls the trial/estimate resolvers).
from forecasting.quorum.estimation import estimate_quorum_calls, cap_preset_by_calls, resolve_quorum_defaults
from forecasting.quorum.estimation import resolve_trial_count, cap_trials_by_calls
# ``shrinkage`` (W3.a) — the James–Stein pool/trial family + final-probability +
# market-anchor (``__all__`` surface + the private poolers ``run_quorum`` calls).
from forecasting.quorum.shrinkage import shrink_pool_toward_anchor, resolve_final_probability, apply_market_anchor_discipline
from forecasting.quorum.shrinkage import _pool_seat_trials


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
    "shrink_pool_toward_anchor",
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
