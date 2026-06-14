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
from typing import Any, Callable, Mapping, Sequence

from forecasting.agent_protocol import parse_agent_protocol_response
from forecasting.models import ValidationError
from forecasting.panel import (
    PanelAggregation,
    aggregate_panel_estimates,
    disagreement_signal,
)


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
    """The judge model's structured synthesis over the panel."""

    probability: float | None
    rationale: str
    reasons_up: list[str] = field(default_factory=list)
    reasons_down: list[str] = field(default_factory=list)
    change_my_mind: list[str] = field(default_factory=list)
    blind_spots: list[str] = field(default_factory=list)
    consensus: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    judge_model: str | None = None

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
        }


@dataclass
class QuorumResult:
    """Everything a ``forecast update`` needs to commit a quorum-backed snapshot."""

    question_id: str | None
    forecasts: list[ModelForecast]
    aggregation: PanelAggregation
    disagreement: dict[str, Any]
    judge: JudgeSynthesis | None
    pool_method: str
    trim: int
    judge_model: str | None = None

    @property
    def aggregate_probability(self) -> float:
        return self.aggregation.aggregate_probability

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
            "disagreement": self.disagreement,
            "judge_model": self.judge_model,
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
    )


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
    self_fusion: bool = False,
    max_concurrency: int = 4,
    on_progress: Callable[[str, str], None] | None = None,
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
    """

    if not models:
        raise ValidationError("quorum requires at least one model")
    judge_runner = judge_runner or runner

    def _dispatch(index: int, model: str) -> ModelForecast:
        prompt = build_panelist_prompt(
            question_title=question_title,
            resolution_criteria=resolution_criteria,
            context_packet=context_packet,
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

    forecasts: list[ModelForecast | None] = [None] * len(models)
    if on_progress:
        on_progress("panelists_start", f"{len(models)} models")
    workers = max(1, min(int(max_concurrency), len(models)))
    if workers == 1:
        for index, model in enumerate(models):
            forecasts[index] = _dispatch(index, model)
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_dispatch, index, model): index
                for index, model in enumerate(models)
            }
            for future in futures:
                index = futures[future]
                forecasts[index] = future.result()
    forecasts = [f for f in forecasts if f is not None]

    ok = [f for f in forecasts if f.error is None]
    if not ok:
        raise ValidationError(
            "every quorum panelist failed; first error: "
            + (forecasts[0].error or "unknown")
        )

    aggregation = aggregate_panel_estimates(
        [f.to_estimate() for f in ok],
        method=pool_method,
        trim=trim,
    )
    disagreement = disagreement_signal(
        [f.probability for f in ok],
        [f.weight for f in ok],
    )

    judge: JudgeSynthesis | None = None
    if judge_model:
        if on_progress:
            on_progress("judge_start", judge_model)
        jp = build_judge_prompt(
            question_title=question_title,
            resolution_criteria=resolution_criteria,
            forecasts=forecasts,
            aggregation=aggregation,
            disagreement=disagreement,
        )
        try:
            jraw = judge_runner(judge_model, jp["system"], jp["user"])
            judge = parse_judge_response(jraw, judge_model)
        except Exception as exc:  # noqa: BLE001 — a judge failure must not lose the panel
            judge = JudgeSynthesis(
                probability=None,
                rationale=f"(judge synthesis failed: {type(exc).__name__}: {exc})",
                judge_model=judge_model,
            )
        if on_progress:
            on_progress("judge_done", judge_model)

    return QuorumResult(
        question_id=question_id,
        forecasts=forecasts,
        aggregation=aggregation,
        disagreement=disagreement,
        judge=judge,
        pool_method=aggregation.method,
        trim=aggregation.trim,
        judge_model=judge_model,
    )


def make_aiagent_runner(
    *,
    max_iterations: int = 30,
    toolsets: Sequence[str] = ("forecasting", "web"),
    quiet: bool = True,
    timeout: float | None = None,
) -> QuorumRunner:
    """Default production runner: one :class:`run_agent.AIAgent` per call.

    Routes every model through the OpenRouter provider (one key, many models)
    with web search enabled, so each panelist researches independently — the
    Fusion design. Built lazily so importing this module never pulls in the
    full agent runtime.

    ``timeout`` (seconds) bounds a single model call: a model that hangs past
    it raises ``RuntimeError`` so :func:`run_quorum` records that panelist as
    errored and the quorum still completes on the survivors. The call runs on a
    daemon thread, so a hung model cannot wedge the job — it is abandoned and
    reaped when the (per-run) process exits.
    """

    def _call(model: str, system: str, user: str) -> str:
        from run_agent import AIAgent

        agent = AIAgent(
            model=model,
            provider="openrouter",
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
    "run_quorum",
    "quorum_auto_indicated",
    "make_aiagent_runner",
]
