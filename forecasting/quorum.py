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
            "metadata": {"source": f"quorum:{self.model}"},
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
    max_concurrency: int = 4,
    on_progress: Callable[[str, str], None] | None = None,
    search_runner: Callable[[list[str]], list[dict[str, Any]]] | None = None,
    max_research_rounds: int = 1,
) -> QuorumResult:
    """Run the full quorum: dispatch panelists, aggregate, judge-synthesise.

    ``runner`` and ``judge_runner`` are injectable for testing; in production
    they wrap :func:`make_aiagent_runner`. Panelists are dispatched **in
    parallel** (up to ``max_concurrency``) — the Fusion design — so the
    wall-clock is the slowest single model, not the sum. ``on_progress(stage,
    detail)`` fires as each panelist completes so the caller can stream desk
    progress; it may be called from worker threads.

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
    """

    if not models:
        raise ValidationError("quorum requires at least one model")
    judge_runner = judge_runner or runner

    def _run_pass(working_context: str) -> tuple[
        list[ModelForecast], PanelAggregation, dict[str, Any], JudgeSynthesis | None
    ]:
        """One full panel-dispatch → aggregate → judge-synthesise pass over the
        given (possibly fresh-evidence-augmented) context. Pure of the override
        gate / terminal Platt, which are applied once on the final pass below."""

        def _dispatch(index: int, model: str) -> ModelForecast:
            prompt = build_panelist_prompt(
                question_title=question_title,
                resolution_criteria=resolution_criteria,
                context_packet=working_context,
                evidence_cutoff=evidence_cutoff,
                sample_hint=index + 1 if self_fusion else None,
            )
            try:
                raw = runner(model, prompt["system"], prompt["user"])
                forecast = parse_panelist_response(raw, model)
            except Exception as exc:  # noqa: BLE001 — isolate one panelist's failure
                # Any single model failing (bad JSON, timeout, provider/SDK error)
                # is recorded as an errored panelist; the quorum completes on the
                # survivors rather than aborting the whole run.
                forecast = ModelForecast(
                    model=model, probability=0.5, error=f"{type(exc).__name__}: {exc}"
                )
            if on_progress:
                on_progress(
                    "panelist_done",
                    f"{model}: {'error' if forecast.error else f'{forecast.probability:.3f}'}",
                )
            return forecast

        slots: list[ModelForecast | None] = [None] * len(models)
        if on_progress:
            on_progress("panelists_start", f"{len(models)} models")
        workers = max(1, min(int(max_concurrency), len(models)))
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

    # ── agentic-supervisor fresh-search loop (AIA P1.1) ────────────────────────
    # First pass over the original context is ALWAYS run. When a search_runner is
    # wired AND the judge flags an unresolved crux, we run fresh search, append
    # the returned evidence to the working context, and re-synthesise — bounded
    # by max_research_rounds. With NO search_runner the while-guard is never even
    # evaluated for cost (search_runner is None), so the default path is exactly
    # one pass and byte-identical to before.
    working_context = context_packet
    research_rounds = 0
    supervisor_evidence: list[dict[str, Any]] = []
    forecasts, aggregation, disagreement, judge = _run_pass(working_context)
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
        forecasts, aggregation, disagreement, judge = _run_pass(working_context)

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
    using the SAME :func:`forecasting.quorum_jobs._cutoff_is_live` predicate that
    guards the supervisor search:

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

    from forecasting.quorum_jobs import _cutoff_is_live

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
    "parse_panelist_response",
    "parse_judge_response",
    "resolve_models",
    "resolve_final_probability",
    "should_research",
    "run_quorum",
    "quorum_auto_indicated",
    "make_aiagent_runner",
]
