"""Market Models orchestration — build / open / re-narrate / chat / to-forecast.

A Market Model is an agentic quant-research artifact. ``build_market_model`` runs
a bounded agent (the ``market-models`` toolset) that researches + computes (via
the deterministic ``market_compute`` tool) and emits a typed Presentation; we
persist the model, its presentation version, the data series, and a re-runnable
spec. ``open_market_model`` re-pulls the series + recomputes the math on live
data (keeping the timestamped writeup); ``renarrate`` rewrites only the prose
against fresh numbers; ``chat`` is an ongoing refine conversation that versions
the presentation; ``model_to_forecast`` spins a projection into a Desk forecast.

The agent run and the auxiliary LLM call are module-level seams so the
persistence / extraction / degradation logic is unit-testable without a live
model. Reuses forecasting.presentation (schema), forecasting.market_compute
(math), forecasting.writeup (house style), and the AIAgent run loop.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from forecasting import presentation as P
from forecasting.models import utc_now_iso

# Depth presets: escalating research effort + presentation structure, each with
# a hard iteration cap. Hints are injected into the prompt; max_iterations bounds
# the agent loop.
# Each preset also sizes the agent's runtime: max_tokens (so big multi-block
# presentations don't truncate), reasoning effort (quality vs latency/cost),
# `required` block types the build must include (enforced via the user prompt's
# self-check), and whether to persist a trajectory + checkpoints for resumability.
DEPTH_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "max_iterations": 18,
        "max_tokens": 4000,
        "reasoning": None,
        "goal": "a fast, focused read: one primary model + a couple of charts + the key findings.",
        "structure": "summary, 1 primary chart, 2-4 findings.",
        "required": ("summary", "1 primary model/chart", "2+ findings"),
    },
    "standard": {
        "max_iterations": 32,
        "max_tokens": 6000,
        "reasoning": "medium",
        "goal": "a solid analysis: the requested model, supporting data, diagnostics, and clear findings.",
        "structure": "summary, the model (regression/timeseries), supporting charts, findings, assumptions, sources.",
        "required": ("summary", "primary model", "supporting chart", "3+ findings", "assumptions", "sources"),
    },
    "deep": {
        "max_iterations": 55,
        "max_tokens": 9000,
        "reasoning": "medium",
        "goal": "a deep analysis: broad data + web/supply-chain research, the model plus diagnostics and a sensitivity or scenario view.",
        "structure": "summary, primary model + diagnostics, sensitivity/scenario, supporting charts/tables, findings, assumptions, sources.",
        "required": ("summary", "primary model + diagnostics", "sensitivity or scenario", "4+ findings", "assumptions", "sources"),
    },
    "ultra": {
        "max_iterations": 90,
        "max_tokens": 16000,
        "reasoning": "high",
        "goal": "an exhaustive, highly structured study: competing models, robustness/sensitivity, scenario fan, extensive sourcing.",
        "structure": "executive summary, multiple models, robustness/sensitivity, scenario/simulation fan, detailed tables, findings, assumptions, full sources.",
        "required": ("executive summary", "2+ competing models", "robustness/sensitivity", "scenario or simulation fan", "5+ findings", "assumptions", "full sources"),
    },
}
DEFAULT_DEPTH = "standard"


# ── model-type recommender (M4) ───────────────────────────────────────────────
# A tiny DETERMINISTIC map from a question's outcome shape (and a couple of cheap
# keyword signals in the prompt) to the model family a quant would reach for
# first. Injected as a strong DEFAULT into the build prompt (only when the caller
# did not pin an ``analysis_type``) and returned from the build_model action so
# the agent/TUI can show "recommended: timeseries_trend (numeric level question)".
# It never overrides an explicit choice and never gates anything.

# Keyword signals that refine the numeric default (checked lowercased on the
# question text). Order matters: the first family whose cues hit wins.
_RECOMMENDER_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("montecarlo", ("path", "trajectory", "tail", "worst case", "drawdown", "simulate", "scenario fan", "distribution of")),
    ("correlation", ("correlat", "cointegrat", "relationship between", "co-move", "spread between", "versus ", " vs ", "two series")),
    ("loglinear", ("growth", "compound", "exponential", "doubling", "cagr", "% per year", "percent per year")),
)


def recommend_model_family(outcome_type: str | None, question: str | None = None) -> dict[str, str]:
    """Suggest a model family from the question's outcome shape + cheap cues.

    Returns ``{"model_type", "family", "rationale"}``. ``model_type`` is a
    market_compute step name (or 'reference_class' for the binary outside view);
    ``family`` is the human label; ``rationale`` explains the pick. Pure + total:
    an unknown outcome type falls back to the numeric-level default.
    """
    ot = (outcome_type or "").strip().lower()
    text = (question or "").lower()

    if ot == "binary":
        return {
            "model_type": "ols",
            "family": "reference-class base rate + driver OLS",
            "rationale": "binary question: anchor on a reference-class base rate, then a driver regression (ols) for the inside-view adjustment.",
        }
    if ot in ("vote_share", "multiple_choice", "categorical"):
        return {
            "model_type": "montecarlo",
            "family": "reference class + Monte-Carlo share fan",
            "rationale": "share/multi-outcome question: base rates per option plus a Monte-Carlo fan for the correlated share uncertainty.",
        }
    if ot == "thesis":
        return {
            "model_type": "correlation",
            "family": "driver correlation / cointegration",
            "rationale": "thesis question: relate the member drivers (correlation / cointegration) rather than a single point projection.",
        }

    # Numeric (or unknown) — refine with keyword cues, else a timeseries trend.
    for family, cues in _RECOMMENDER_CUES:
        if any(cue in text for cue in cues):
            if family == "montecarlo":
                return {"model_type": "montecarlo", "family": "Monte-Carlo simulation fan",
                        "rationale": "path/tail question: simulate trajectories (montecarlo) for the fan of outcomes and tail percentiles."}
            if family == "correlation":
                return {"model_type": "correlation", "family": "correlation / cointegration",
                        "rationale": "two-series relationship: measure correlation (and cointegration for a stable long-run link)."}
            if family == "loglinear":
                return {"model_type": "loglinear", "family": "log-linear (exponential) trend",
                        "rationale": "growth question: fit a log-linear trend so a constant growth rate is a straight line."}
    return {
        "model_type": "timeseries_trend",
        "family": "time-series trend (with ARIMA as a robustness check)",
        "rationale": "numeric level question: project the level with a time-series trend (prediction interval), cross-check with arima.",
    }

MARKET_MODEL_SYSTEM_PROMPT = """You are a quantitative markets researcher building a saved, reproducible "Market Model" for a forecasting desk. Think like a sharp quant AND a calibrated superforecaster: anchor on an outside view before the case-specific story, decompose into measurable drivers, gather REAL data, compute every number deterministically, stress-test your own estimates, and present formal findings.

Forecasting discipline (this is a scoreable forecasting artifact, not just a chart):
- Outside view first: anchor on a base rate / reference class ("how often do things of this sort happen in situations of this sort?") before the inside-view narrative. Anchor on the status quo and the horizon — weight the persistence (no-change) outcome more the shorter the horizon, and move off it only as far as a concrete mechanism + the evidence justify.
- Reason along PATHS, not vibes: trace the causal path to each outcome and price the links; a path with one weak link cannot carry heavy probability mass.
- Forecast from the information frontier: reason only from what was knowable at the as-of cutoff; guard against hindsight and recency salience.
- Calibrate in BOTH directions: under-confidence is a scored failure too. Every chunk of probability mass needs a credible path; concentrate the distribution when the evidence earns it. Markets/crowds are evidence to weigh, not a verdict to copy.

Rules:
1. Gather REAL data — never invent numbers or sources. Use `import_source_evidence` / `import_source_evidence_batch` with the right adapter: equities/FX/commodities → yahoo or stooq; US macro → fred / bls / eia / treasury; crypto → coingecko; prediction markets → polymarket / kalshi / manifold; company filings → sec / secsearch; global/development → worldbank / imf / owid; news/feeds → rss / gdelt; plus `web_search` / `web_extract` for context + supply-chain. Call `read_desk_forecast` to reuse an existing desk forecast as an input or comparison when one is relevant.
2. Compute EVERY statistic (regression, correlation, trend/extrapolation, Monte-Carlo, cointegration, event-study, ARIMA, backtest) via the `market_compute` tool — never hand-derive coefficients, R^2, percentiles, or projections. Then SELF-VERIFY before emitting: re-read your key numbers (fit/R^2, extrapolation endpoints, tail percentiles) against the raw series and fix anything that does not reconcile.
3. Delegation: do the data imports + `market_compute` YOURSELF (they are fast and must stay auditable). Delegate ONLY open-ended research legwork — a driver deep-dive, a reference class, supply-chain digging — with `delegate_task(background=true)` so your loop keeps computing while it runs; cap at ~2 parallel subagents and fold their results into evidence / findings / sources, NEVER into the computed numbers.
4. Build the answer from the standardized presentation block library and call `emit_market_presentation` EXACTLY ONCE with the assembled Presentation. Cite the imported evidence that backs each finding via `evidence_refs` (the evidence ids you imported) and include a `sources` block.
5. Also pass a `spec` to `emit_market_presentation` describing the re-runnable recipe: each data series (name + source_type + source) and the compute steps (model_type + which series map to inputs + params). This is REQUIRED — a series without `source_type` + `source` cannot be refreshed on reopen.
6. House style: plain, probability-literate, decisive but hedged; NO em-dashes.

Block types: narrative, finding, metric, timeseries, scatter, regression, bars, table, fan (simulation), scenario, assumptions, sources. High-fidelity charts (rendered by the terminal viz engine):
- `heatmap` {matrix:[[..]], rowLabels?, colLabels?, diverging?:true for correlation} — truecolor cell heatmap; use for correlation / covariance / liquidity matrices.
- `fan` with optional `paths:[[..]]` (sample simulated trajectories) — Monte-Carlo cone (median + spaghetti + band); include paths when you ran a simulation.
- `distribution` {support:[..], pdf:[..], cdf?:[..], mean?, median?, intervals?:[{lo,hi,p}]} — a probability density with optional CDF + credible-interval bands; use for posteriors / forecast distributions.
- `candles` {candles:[{o,h,l,c,t?}], volume?:[..], ma?:[..]} — OHLC candlesticks with optional volume + moving average.
- `depth` {bids:[{price,size}], asks:[{price,size}], mid?} — order-book cumulative depth curve.
- `sparkgrid` {cells:[{label, values?:[..], value?, delta?, unit?}], columns?} — a dashboard grid of mini-sparklines for a watchlist/portfolio.
The presentation header needs a title + summary; status defaults to complete."""


# ── injectable seams (monkeypatched in tests) ─────────────────────────────────


# Friendly live-status labels for the agent's tool calls (system visibility in
# the chat composer while a build/refine runs).
_TOOL_LABELS = {
    "import_source_evidence": "importing data",
    "import_source_evidence_batch": "importing data",
    "forecast_ledger": "importing data",
    "web_search": "searching the web",
    "web_extract": "reading a page",
    "market_compute": "computing the model",
    "emit_market_presentation": "composing the presentation",
    "read_desk_forecast": "reading desk forecasts",
    "delegate_task": "delegating research",
}


def _market_toolset(rt: dict) -> str:
    """Pick the toolset preset. Interactive runtimes (an approval callback exists,
    e.g. a foreground CLI/ACP session) get the richer code_execution + browser
    variant; headless background builds keep the safe, non-approval-gated set."""
    return "market-models-interactive" if rt.get("interactive") else "market-models"


def _run_market_agent(
    *,
    system: str,
    user: str,
    max_iterations: int,
    model: str | None,
    provider: str | None,
    depth: str = DEFAULT_DEPTH,
    preset: dict | None = None,
    main_runtime: dict | None = None,
    runtime: dict | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the bounded market-models agent. Returns run_conversation's result dict.

    ``runtime`` carries the SESSION's resolved credentials (provider / base_url /
    api_key / api_mode / model) so the background agent authenticates exactly like
    the live session — a fresh AIAgent that re-resolves from config can land on a
    different/unconfigured provider and get an HTML auth/error page. It may also
    carry ``fallback_model`` (provider failover) + ``parent_session_id`` (lineage).
    ``main_runtime`` is unused here (it belongs to the auxiliary call_llm).
    """
    from agent.runtime import AIAgent

    rt = runtime or {}
    preset = preset or DEPTH_PRESETS.get(depth, DEPTH_PRESETS[DEFAULT_DEPTH])
    deep = max_iterations >= 55

    kwargs: dict[str, Any] = {
        "model": rt.get("model") or model or "",
        "provider": rt.get("provider") or provider,
        "max_iterations": max_iterations,
        "enabled_toolsets": [_market_toolset(rt)],
        "platform": "cli",
    }
    # Forward the session's resolved credentials (only when present, so we never
    # override the agent's own resolution with None). Mirrors _make_agent.
    for src, dst in (
        ("base_url", "base_url"), ("api_key", "api_key"), ("api_mode", "api_mode"),
        ("credential_pool", "credential_pool"), ("command", "acp_command"), ("args", "acp_args"),
        ("fallback_model", "fallback_model"), ("parent_session_id", "parent_session_id"),
    ):
        if rt.get(src) is not None:
            kwargs[dst] = rt[src]

    # Depth-scaled output budget + reasoning effort. Big ultra presentations
    # (heatmap + fan + distribution + tables) truncate at the default token cap;
    # quick runs disable thinking for latency.
    if preset.get("max_tokens"):
        kwargs["max_tokens"] = preset["max_tokens"]
    effort = preset.get("reasoning")
    kwargs["reasoning_config"] = {"enabled": True, "effort": effort} if effort else {"enabled": False}

    # Deep/ultra runs are long + valuable: persist a trajectory (debuggable on
    # failure) + checkpoints (resumable if interrupted).
    if deep:
        kwargs["save_trajectories"] = True
        kwargs["checkpoints_enabled"] = True

    # One iteration budget shared across the whole agent tree, so a delegating
    # deep run can't blow past its cap via subagents.
    try:
        from agent.iteration_budget import IterationBudget

        kwargs["iteration_budget"] = IterationBudget(max_iterations)
    except Exception:
        pass

    # Stream a live label per tool call so the UI shows what the agent is doing
    # (system visibility), not a static spinner. Best-effort, never throws.
    if progress is not None:
        def _on_tool_start(_id: Any, name: str, _args: Any) -> None:
            try:
                progress(_TOOL_LABELS.get(name, str(name)))
            except Exception:
                pass

        kwargs["tool_start_callback"] = _on_tool_start

    from contextlib import nullcontext
    from superforecasting_agent.tooling.prompt_callbacks import temporary_approval_callback

    # The interactive sandbox approval exists only during this build, including
    # construction. Restore the caller's policy before its worker thread is reused.
    approval_scope = (
        temporary_approval_callback(lambda _cmd, _desc, allow_permanent=True: "session")
        if rt.get("interactive") else nullcontext()
    )
    with approval_scope:
        agent = AIAgent(**kwargs)
        # Background research runs (no user waiting on first byte) can legitimately
        # take minutes for a deep synthesis call after multi-step research, so a 90s
        # non-stream time-to-first-byte ceiling kills them prematurely. Give a
        # generous, depth-scaled stale timeout (instance-scoped; see
        # AIAgent._resolved_api_call_stale_timeout_base). fallback_model is the real
        # resilience fix — this just stops a single slow byte from aborting.
        timeout_override = 600.0 if deep else 360.0
        agent._api_call_stale_timeout_override = timeout_override
        result = agent.run_conversation(user, system_message=system)
        # Stash runtime facts so diagnostics can surface them (no agent handle there).
        if isinstance(result, dict):
            result["_market_runtime"] = {
                "fallback": bool(kwargs.get("fallback_model")),
                "max_tokens": preset.get("max_tokens"),
                "reasoning": effort or "off",
                "timeout_override": timeout_override,
                "toolset": kwargs["enabled_toolsets"][0],
                "trajectory_session_id": getattr(agent, "session_id", None) if deep else None,
            }
        return result


def _aux_llm(messages: list[dict], *, max_tokens: int = 900, temperature: float = 0.5, main_runtime: dict | None = None) -> str:
    """Auxiliary LLM call for prose re-narration. Returns content text ('' on failure)."""
    try:
        from agent.auxiliary_client import call_llm

        resp = call_llm(task="market_model", messages=messages, temperature=temperature,
                        max_tokens=max_tokens, timeout=60, main_runtime=main_runtime)
        return resp.choices[0].message.content or ""
    except Exception:
        return ""


def _repull_series(spec: dict) -> tuple[list[dict], list[str]]:
    """Best-effort re-pull of a spec's data series via import_source_evidence.

    Returns ``(refreshed_series, reasons)`` — the refreshed series dicts
    ([{name,source_type,source,unit,points,as_of}]) plus human-readable reasons
    any series could NOT be refreshed, so ``open`` can surface "FRED id 404'd"
    instead of a silent false.
    """
    reasons: list[str] = []
    series_defs = [s for s in (spec or {}).get("series", []) if isinstance(s, dict)]
    missing = [str(s.get("name") or "?") for s in series_defs if not (s.get("source_type") and s.get("source"))]
    if missing:
        reasons.append(f"{len(missing)} series lack source_type/source (not refreshable): {', '.join(missing[:5])}")
    runnable = [s for s in series_defs if s.get("source_type") and s.get("source")]
    if not runnable:
        if not series_defs:
            reasons.append("spec has no data series")
        return [], reasons
    try:
        from forecasting.sources.dispatch import load_source_items
    except Exception:
        return [], reasons + ["data-adapter layer unavailable in this build"]

    def _attr(item: Any, *names: str) -> Any:
        for n in names:
            if isinstance(item, dict):
                if item.get(n) is not None:
                    return item.get(n)
            else:
                v = getattr(item, n, None)
                if v is not None:
                    return v
        return None

    refreshed: list[dict] = []
    for s in runnable:
        tag = f"{s['source_type']}:{s['source']}"
        try:
            items = load_source_items(s["source_type"], s["source"], {"limit": int(s.get("limit") or 60)})
        except Exception as e:
            reasons.append(f"{tag} fetch error: {_clean_text(str(e), limit=80)}")
            continue
        points = []
        for it in items or []:
            x = _attr(it, "observation_date", "published_at", "x", "date")
            y = _attr(it, "value", "y")
            if x is not None and y is not None:
                points.append({"x": x, "y": y})
        if points:
            refreshed.append({
                "name": s.get("name") or s["source"], "source_type": s["source_type"],
                "source": s["source"], "unit": s.get("unit"), "points": points, "as_of": utc_now_iso(),
            })
        else:
            reasons.append(f"{tag} returned no usable points")
    return refreshed, reasons


# ── presentation extraction from an agent run ─────────────────────────────────


def _collect_emit(result: dict) -> tuple[dict | None, dict | None]:
    """Most reliable → least: the tool's thread-local stash, then the run's tool
    calls, then a fenced JSON object in the final response."""
    try:
        from forecasting.application.market_output import take_emitted

        emitted = take_emitted()
        if isinstance(emitted, dict) and isinstance(emitted.get("presentation"), dict):
            spec = emitted.get("spec") if isinstance(emitted.get("spec"), dict) else None
            return emitted["presentation"], spec
    except Exception:
        pass
    return _extract_emit(result)


def _reset_emit() -> None:
    try:
        from forecasting.application.market_output import reset_emitted

        reset_emitted()
    except Exception:
        pass


def _extract_emit(result: dict) -> tuple[dict | None, dict | None]:
    """Pull (presentation, spec) from the agent run's emit_market_presentation call.

    run_conversation has NO top-level ``tool_calls`` key — tool calls live inside
    ``result["messages"]`` as assistant messages with ``tool_calls:[{function:{name,
    arguments}}]`` (arguments a JSON string). Scan those (taking the LAST emit, so
    a self-repair re-emit wins); fall back to a fenced JSON object in the final
    response. Returns (None, None) if nothing usable.
    """
    last: dict | None = None
    for message in result.get("messages", []) or []:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = fn.get("name") or call.get("name")
            if name != "emit_market_presentation":
                continue
            raw = fn.get("arguments") if fn.get("arguments") is not None else call.get("arguments")
            args = _loads(raw)
            if isinstance(args, dict):
                last = args
    if isinstance(last, dict):
        pres = last.get("presentation") if isinstance(last.get("presentation"), dict) else last
        spec = last.get("spec") if isinstance(last.get("spec"), dict) else None
        return pres, spec
    # Fallback: fenced/embedded JSON in the final response.
    obj = _extract_json_object(result.get("final_response") or "")
    if isinstance(obj, dict):
        pres = obj.get("presentation") if isinstance(obj.get("presentation"), dict) else obj
        spec = obj.get("spec") if isinstance(obj.get("spec"), dict) else None
        return pres, spec
    return None, None


def _loads(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except Exception:
        return _extract_json_object(raw)


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        d = json.loads(s)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    # outermost {...}
    start, depth = -1, 0
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    d = json.loads(s[start : i + 1])
                    if isinstance(d, dict):
                        return d
                except Exception:
                    start = -1
    return None


# ── series captured from the presentation (for storage + re-pull) ─────────────


def _series_from_presentation(pres: dict) -> list[dict]:
    """Extract chartable series from timeseries/regression blocks for storage."""
    out: list[dict] = []
    for b in pres.get("blocks", []):
        if not isinstance(b, dict):
            continue
        if b.get("type") == "timeseries":
            for s in b.get("series", []):
                if isinstance(s, dict) and s.get("points"):
                    out.append({"name": s.get("name") or "series", "points": s.get("points")})
        elif b.get("type") == "regression" and b.get("points"):
            out.append({"name": b.get("y_label") or "regression", "points": b.get("points")})
    return out


# ── build ─────────────────────────────────────────────────────────────────────


def build_market_model(
    question: str,
    params: dict | None = None,
    *,
    ledger,
    model_id: str | None = None,
    progress: Callable[[str], None] | None = None,
    main_runtime: dict | None = None,
    runtime: dict | None = None,
) -> dict[str, Any]:
    """Run the agentic build; persist the model + first presentation. Never raises.

    If ``model_id`` is given the row already exists (the gateway creates it up
    front to return an id immediately); otherwise a new model is created.
    ``runtime`` carries the session's resolved credentials for the agent.
    """
    params = dict(params or {})
    depth = params.get("depth") if params.get("depth") in DEPTH_PRESETS else DEFAULT_DEPTH
    preset = DEPTH_PRESETS[depth]
    title = (params.get("title") or question or "Untitled model").strip()[:120]

    def _note(msg: str) -> None:
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    if model_id:
        model = ledger.get_market_model(model_id)
        title = model.get("title") or title
        depth = model.get("depth") or depth
    else:
        model = ledger.create_market_model(title=title, question=question, depth=depth, spec={}, tags=params.get("tags") or [])
        model_id = model["id"]
    _note("researching")

    user = _build_user_prompt(question, params, preset)
    _reset_emit()
    try:
        result = _run_market_agent(
            system=MARKET_MODEL_SYSTEM_PROMPT, user=user,
            max_iterations=int(params.get("max_iterations") or preset["max_iterations"]),
            model=params.get("model"), provider=params.get("provider"),
            depth=depth, preset=preset,
            main_runtime=main_runtime, runtime=runtime, progress=progress,
        )
    except Exception as e:  # hard failure → persist a failed presentation, never raise
        return _persist_failed(ledger, model_id, title, question, f"build failed: {e}")

    _note("composing presentation")
    pres, spec = _collect_emit(result or {})
    return _finalize(ledger, model_id, title, question, pres, spec, depth=depth,
                     agent_model=(result or {}).get("model"), result=result)


def _build_user_prompt(question: str, params: dict, preset: dict) -> str:
    extras = []
    if params.get("tickers"):
        extras.append(f"Primary assets/tickers: {', '.join(params['tickers'])}.")
    if params.get("analysis_type"):
        extras.append(f"Preferred analysis type: {params['analysis_type']}.")
    else:
        # No explicit analysis type — inject the deterministic recommender's pick
        # as a STRONG DEFAULT (the agent may override it if the data argues otherwise).
        rec = recommend_model_family(params.get("outcome_type"), question)
        extras.append(
            f"Recommended primary model: {rec['model_type']} ({rec['family']}) — {rec['rationale']} "
            "Use it as your default primary model unless the data clearly argues for another."
        )
    if params.get("horizon"):
        extras.append(f"Horizon: {params['horizon']}.")
    if params.get("target_year"):
        extras.append(f"Extrapolate toward: {params['target_year']}.")
    if params.get("assumptions"):
        extras.append(f"User assumptions: {params['assumptions']}.")
    required = preset.get("required") or ()
    scaffold = (
        f"Required for this depth — the presentation MUST include: {', '.join(required)}.\n"
        "Before you call emit_market_presentation, self-check that every required element is present "
        "and that your computed numbers reconcile with the raw data; if not, keep working.\n"
        if required
        else ""
    )
    return (
        f"Quant question:\n{question}\n\n"
        f"Depth: {params.get('depth') or DEFAULT_DEPTH} — aim for {preset['goal']}\n"
        f"Suggested structure: {preset['structure']}\n"
        + scaffold
        + ("\n".join(extras) + "\n" if extras else "")
        + "\nResearch, compute via market_compute, then call emit_market_presentation once with the presentation + a re-runnable spec."
    )


def _run_diagnostics(result: dict | None) -> dict[str, Any]:
    """Surface what the agent run actually did, so failures aren't opaque."""
    result = result or {}
    msgs = result.get("messages") or []
    tool_names: list[str] = []
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") if isinstance(tc, dict) else None
                if isinstance(fn, dict) and fn.get("name"):
                    tool_names.append(fn["name"])
    err = result.get("error")
    rt = result.get("_market_runtime") or {}
    return {
        "api_calls": result.get("api_calls"),
        "completed": result.get("completed"),
        # Clean: the error may be a raw HTML auth/error page — never store the dump.
        "agent_error": _clean_text(str(err), limit=300) if err else None,
        "messages": len(msgs),
        "tool_calls": tool_names,
        "emitted": "emit_market_presentation" in tool_names,
        # Runtime facts so a failure isn't opaque (was research allowed enough
        # time? was failover available? is there a trajectory to replay?).
        "timeout_override": rt.get("timeout_override"),
        "fallback_available": rt.get("fallback"),
        "max_tokens": rt.get("max_tokens"),
        "reasoning": rt.get("reasoning"),
        "toolset": rt.get("toolset"),
        "trajectory_session_id": rt.get("trajectory_session_id"),
    }


def _looks_like_html(text: str) -> bool:
    head = text.lstrip()[:300].lower()
    if head.startswith(("<!doctype", "<html", "<?xml")) or "<head" in head or "<body" in head:
        return True
    return text.count("<") > 8 and "</" in text


def _clean_text(text: str, limit: int = 2000) -> str:
    """Strip HTML tags + collapse whitespace + clamp — never dump a raw page."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _finalize(ledger, model_id, title, question, pres, spec, *, depth, agent_model=None, result=None) -> dict[str, Any]:
    diag = _run_diagnostics(result)

    if not isinstance(pres, dict):
        # The agent ran but didn't emit structured blocks. Only surface a prose
        # fallback when the run actually COMPLETED with substantive, non-HTML prose
        # (an error/auth page must not be rendered as a "narrative analysis").
        final = str((result or {}).get("final_response") or "").strip()
        errored = bool((result or {}).get("error")) or (result or {}).get("completed") is False
        if final and not errored and not _looks_like_html(final):
            final = _clean_text(final)
            fallback = P.build_presentation(
                model_id=model_id, version=0, title=title, question=question, status="partial",
                summary=final[:300], as_of_analysis=utc_now_iso(),
                blocks=[
                    {"type": "narrative", "body": final},
                    {"type": "finding",
                     "claim": "The desk produced a prose analysis but did not emit structured charts/blocks. Refine (chat) to get a structured model.",
                     "confidence": "low"},
                ],
                diagnostics={**diag, "warnings": ["agent did not call emit_market_presentation"]},
            )
            P.sanitize_presentation_prose(fallback)
            saved = ledger.add_market_presentation(
                model_id=model_id, presentation=fallback, status="partial",
                summary=str(fallback.get("summary") or ""), diagnostics=diag, agent_model=agent_model,
            )
            return {"model_id": model_id, "version": saved["version"], "status": "partial", "presentation": saved["presentation"]}
        raw_reason = diag.get("agent_error") or "the build did not produce a presentation"
        # The error itself may be an HTML/auth page — clean + clamp so the row
        # shows a readable reason, not a page dump.
        reason = _clean_text(str(raw_reason), limit=400) or "the build did not produce a presentation"
        return _persist_failed(ledger, model_id, title, question, reason, diagnostics=diag)

    ok, errors = P.validate_presentation(pres)
    status = "complete" if ok else "partial"
    pres.setdefault("title", title)
    pres.setdefault("question", question)
    pres["model_id"] = model_id
    pres["diagnostics"] = {**diag, **(pres.get("diagnostics") or {})}
    P.sanitize_presentation_prose(pres)
    if not ok:
        pres.setdefault("blocks", []).append(
            {"type": "finding", "id": "validation-note", "claim": "Presentation was auto-repaired.",
             "confidence": "low", "note": "; ".join(errors[:4])}
        )
    if isinstance(spec, dict):
        try:
            ledger.update_market_model_spec(model_id, spec)
        except Exception:
            pass
    for s in _series_from_presentation(pres):
        try:
            ledger.add_market_data_series(model_id=model_id, name=s["name"], points=s["points"])
        except Exception:
            pass
    saved = ledger.add_market_presentation(
        model_id=model_id, presentation=pres, status=status, summary=str(pres.get("summary") or ""),
        diagnostics=pres.get("diagnostics") or {}, agent_model=agent_model,
    )
    return {"model_id": model_id, "version": saved["version"], "status": status, "presentation": saved["presentation"]}


def _persist_failed(ledger, model_id, title, question, reason, *, diagnostics: dict | None = None) -> dict[str, Any]:
    diag = dict(diagnostics or {})
    warnings = diag.get("warnings") if isinstance(diag.get("warnings"), list) else []
    diag["warnings"] = [*warnings, reason]
    note = f"api_calls={diag.get('api_calls')} · completed={diag.get('completed')} · tools={diag.get('tool_calls')}"
    pres = P.build_presentation(
        model_id=model_id, version=0, title=title, question=question, status="failed",
        summary=reason, blocks=[{"type": "finding", "claim": reason, "confidence": "low", "note": note}],
        diagnostics=diag,
    )
    saved = ledger.add_market_presentation(model_id=model_id, presentation=pres, status="failed", summary=reason, diagnostics=diag)
    return {"model_id": model_id, "version": saved["version"], "status": "failed", "presentation": saved["presentation"]}


# ── open (re-pull + recompute) ────────────────────────────────────────────────


def open_market_model(model_id: str, *, ledger) -> dict[str, Any]:
    """Return the current presentation, refreshed against live data when possible.

    Re-pulls the spec's series and re-runs the deterministic compute so charts /
    regression / projections reflect the latest data; the agentic writeup blocks
    are kept with their original ``as_of_analysis`` timestamp. Best-effort: if the
    spec is not re-runnable, returns the stored presentation unchanged.
    """
    model = ledger.get_market_model(model_id)
    try:
        current = ledger.get_market_presentation(model_id)
    except Exception:
        return {"model_id": model_id, "presentation": None, "refreshed": False}
    pres = dict(current["presentation"])
    spec = model.get("spec") or {}

    refreshed_series, reasons = _repull_series(spec)
    note = "; ".join(reasons) or None
    if not refreshed_series:
        return {"model_id": model_id, "presentation": pres, "refreshed": False, "refresh_note": note}

    try:
        ledger.replace_market_data_series(model_id, refreshed_series)
    except Exception:
        pass
    by_name = {s["name"]: s["points"] for s in refreshed_series}
    recomputed = _recompute_blocks(pres.get("blocks", []), spec, by_name)
    pres["blocks"] = recomputed
    pres["as_of_data"] = utc_now_iso()
    return {"model_id": model_id, "presentation": pres, "refreshed": True, "refresh_note": note}


def _recompute_blocks(blocks: list, spec: dict, by_name: dict) -> list:
    """Refresh data-driven blocks from fresh series + the compute spec.

    Re-runs each compute step in ``spec['compute']`` and swaps the matching block
    by id. Narrative/finding/sources blocks pass through untouched.
    """
    from forecasting import market_compute as MC

    out = list(blocks)
    for step in (spec or {}).get("compute", []):
        if not isinstance(step, dict):
            continue
        block_id = step.get("block_id")
        model_type = step.get("model_type")
        payload = _resolve_payload(step.get("payload") or {}, by_name)
        if not (block_id and model_type and payload):
            continue
        res = MC.compute(model_type, payload)
        if not res.get("ok"):
            continue
        new_block = res["block"]
        for i, b in enumerate(out):
            if isinstance(b, dict) and b.get("id") == block_id:
                new_block["id"] = block_id
                if b.get("title"):
                    new_block.setdefault("title", b["title"])
                out[i] = new_block
                break
    return out


def _resolve_payload(payload: dict, by_name: dict) -> dict:
    """Replace ``{"series": "<name>"}`` references in a compute payload with points."""
    resolved = dict(payload)
    for key in ("x", "y", "a", "b", "values"):
        ref = payload.get(key)
        if isinstance(ref, dict) and "series" in ref:
            pts = by_name.get(ref["series"]) or []
            field = ref.get("field", "y")
            resolved[key] = [p.get(field, p.get("y")) for p in pts if isinstance(p, dict)]
    return resolved


# ── re-narrate (prose only) ───────────────────────────────────────────────────


def renarrate_market_model(model_id: str, *, ledger, main_runtime: dict | None = None) -> dict[str, Any]:
    """Regenerate narrative/finding prose against the freshly recomputed numbers."""
    opened = open_market_model(model_id, ledger=ledger)
    pres = opened.get("presentation")
    if not isinstance(pres, dict):
        return {"model_id": model_id, "version": None, "status": "failed"}

    numeric = [b for b in pres.get("blocks", []) if isinstance(b, dict) and b.get("type") in ("regression", "metric", "fan", "table", "timeseries")]
    prompt = (
        "Rewrite the narrative + findings for this market model so they match the CURRENT numbers. "
        "Return ONLY a JSON object {\"summary\": str, \"narrative\": str, \"findings\": [{\"claim\": str, \"confidence\": \"low|medium|high\"}]}. "
        "Plain quant prose, no em-dashes.\n\n"
        f"Title: {pres.get('title')}\nQuestion: {pres.get('question')}\n"
        f"Current computed blocks:\n{json.dumps(numeric, default=str)[:6000]}"
    )
    content = _aux_llm([{"role": "system", "content": MARKET_MODEL_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}], main_runtime=main_runtime)
    obj = _extract_json_object(content) or {}
    # Guard: if the aux call produced no usable prose, keep the prior presentation
    # unchanged rather than persisting a version that dropped its narrative/findings.
    if not obj.get("narrative") and not (obj.get("findings")):
        return {"model_id": model_id, "version": pres.get("version"), "status": "complete", "presentation": pres, "renarrated": False}
    # Rebuild prose blocks from the response; keep all non-prose blocks.
    kept = [b for b in pres.get("blocks", []) if isinstance(b, dict) and b.get("type") not in ("narrative", "finding")]
    prose_blocks: list[dict] = []
    if obj.get("narrative"):
        prose_blocks.append({"type": "narrative", "body": str(obj["narrative"])})
    for f in obj.get("findings", []) or []:
        if isinstance(f, dict) and f.get("claim"):
            prose_blocks.append({"type": "finding", "claim": f["claim"], "confidence": f.get("confidence", "medium")})
    new_pres = P.build_presentation(
        model_id=model_id, version=0, title=pres.get("title", ""), question=pres.get("question", ""),
        summary=str(obj.get("summary") or pres.get("summary") or ""), status="complete",
        as_of_analysis=utc_now_iso(), as_of_data=pres.get("as_of_data"),
        blocks=prose_blocks + kept, diagnostics=pres.get("diagnostics") or {},
    )
    P.sanitize_presentation_prose(new_pres)
    saved = ledger.add_market_presentation(model_id=model_id, presentation=new_pres, status="complete",
                                           summary=str(new_pres.get("summary") or ""))
    return {"model_id": model_id, "version": saved["version"], "status": "complete", "presentation": saved["presentation"]}


# ── chat (ongoing refine) ─────────────────────────────────────────────────────


def chat_market_model(
    model_id: str, message: str, *, ledger, params: dict | None = None,
    progress: Callable[[str], None] | None = None, main_runtime: dict | None = None,
    runtime: dict | None = None,
) -> dict[str, Any]:
    """A refine turn: agentic run seeded with the prior model + the user message."""
    params = dict(params or {})
    model = ledger.get_market_model(model_id)
    ledger.add_market_message(model_id=model_id, role="user", content=message)
    try:
        prior = ledger.get_market_presentation(model_id)["presentation"]
    except Exception:
        prior = {}
    depth = model.get("depth") if model.get("depth") in DEPTH_PRESETS else DEFAULT_DEPTH
    preset = DEPTH_PRESETS[depth]
    user = (
        f"You are refining an existing market model.\nOriginal question: {model.get('question')}\n\n"
        f"Prior presentation (JSON):\n{json.dumps(prior, default=str)[:8000]}\n\n"
        f"User's refinement request:\n{message}\n\n"
        "Reuse the prior data/series where possible; fetch/compute only the delta the request needs. "
        "Re-emit a FULL updated presentation + spec via emit_market_presentation."
    )
    if progress:
        try:
            progress("refining")
        except Exception:
            pass
    _reset_emit()
    try:
        result = _run_market_agent(
            system=MARKET_MODEL_SYSTEM_PROMPT, user=user,
            max_iterations=int(params.get("max_iterations") or preset["max_iterations"]),
            model=params.get("model"), provider=params.get("provider"),
            depth=depth, preset=preset,
            main_runtime=main_runtime, runtime=runtime, progress=progress,
        )
    except Exception as e:
        out = _persist_failed(ledger, model_id, model.get("title", ""), model.get("question", ""), f"refine failed: {e}")
        ledger.add_market_message(model_id=model_id, role="assistant", content=f"Refine failed: {e}", version_ref=out["version"])
        return out
    pres, spec = _collect_emit(result or {})
    out = _finalize(ledger, model_id, model.get("title", ""), model.get("question", ""), pres, spec,
                    depth=depth, agent_model=(result or {}).get("model"), result=result)
    reply = str((pres or {}).get("summary") or "Updated the model.")
    ledger.add_market_message(model_id=model_id, role="assistant", content=reply, version_ref=out["version"])
    return out


# ── spin off a Desk forecast ──────────────────────────────────────────────────


def model_to_forecast(model_id: str, *, ledger) -> dict[str, Any]:
    """Create a Desk forecast question seeded by the model's projection; link them.

    Best-effort: returns {question_id?, seed, model_run_id?, reference_class_id?} so
    the caller can route to the normal forecast-create flow if the ledger can't
    create a full question directly.

    The COMPUTED numbers are preserved as scoreable ledger inputs, not just pasted
    into prose: after creating the linked question we ``record_model_run`` (with the
    ``market_model_id`` FK back to this model) carrying the primary compute step's
    output {projected_value, lo, hi, r2, ...}, and when the model produced a
    base-rate-like probability we also ``add_reference_class`` from it — so the
    panel / ensemble can consume the model as an input component.
    """
    model = ledger.get_market_model(model_id)
    try:
        pres = ledger.get_market_presentation(model_id)["presentation"]
    except Exception:
        pres = {}
    proj = _extrapolation_summary(pres)
    primary = _primary_projection(pres)
    seed = {
        "title": f"{model.get('title')} — will the projection hold?",
        "description": (model.get("question") or "")
        + (f"\n\nModel projection: {proj}" if proj else ""),
        "source_market_model": model_id,
    }
    # Actually create the linked Desk forecast (previously the seed went nowhere)
    # and record the edge BOTH ways: source_market_model on the question + the
    # spawned question id back on the model's spec. Best-effort, never raises.
    question_id = None
    model_run_id = None
    reference_class_id = None
    try:
        from forecasting.ledger import allow_ledger_writes

        with allow_ledger_writes(reason="market_model.model_to_forecast"):
            q = ledger.create_question(
                title=seed["title"][:200],
                resolution_criteria=(
                    f"Resolves by comparing the realized outcome against this market model's projection"
                    + (f" ({proj})" if proj else "") + ". Re-run the model on fresh data to score."
                ),
                description=seed["description"],
                tags=["market-model"],
                metadata={"source_market_model": model_id},
            )
            question_id = getattr(q, "id", None) or (q.get("id") if isinstance(q, dict) else None)
            if question_id:
                spec = dict(model.get("spec") or {})
                spec["forecast_question_id"] = question_id
                try:
                    ledger.update_market_model_spec(model_id, spec)
                except Exception:
                    pass
                model_run_id, reference_class_id = _record_model_leg(
                    ledger, question_id, model_id, primary
                )
    except Exception:
        question_id = None
    return {
        "model_id": model_id,
        "question_id": question_id,
        "model_run_id": model_run_id,
        "reference_class_id": reference_class_id,
        "seed": seed,
    }


def _record_model_leg(ledger, question_id: str, model_id: str, primary: dict | None) -> tuple[str | None, str | None]:
    """Persist the model's computed numbers as scoreable ledger inputs.

    Records a model_run (with the ``market_model_id`` FK) carrying the primary
    compute step's output, and — when the model produced a base-rate-like
    probability — a reference class from it. Best-effort; returns
    ``(model_run_id, reference_class_id)`` (either may be None). Callers hold the
    write context.
    """
    if not primary:
        return None, None
    model_run_id = None
    reference_class_id = None
    try:
        run = ledger.record_model_run(
            question_id=question_id,
            model_type=primary.get("model_type") or "market_model",
            inputs={"market_model_id": model_id},
            output=primary.get("output") or {},
            diagnostics={"source": "market_model", "block_type": primary.get("block_type")},
            market_model_id=model_id,
        )
        model_run_id = run.get("id")
    except Exception:
        model_run_id = None
    base_rate = primary.get("base_rate")
    if isinstance(base_rate, (int, float)) and 0.0 <= float(base_rate) <= 1.0:
        try:
            rc = ledger.add_reference_class(
                question_id=question_id,
                name=(primary.get("base_rate_label") or "market-model base rate")[:120],
                inclusion_criteria=(
                    "Derived from the linked Market Model's computed base-rate-like quantity "
                    f"({primary.get('model_type')})."
                ),
                base_rate=float(base_rate),
                source_refs=[model_id],
                notes="Auto-recorded from a Market Model projection (model_to_forecast).",
            )
            reference_class_id = rc.get("id")
        except Exception:
            reference_class_id = None
    return model_run_id, reference_class_id


def _primary_projection(pres: dict) -> dict | None:
    """Extract the PRIMARY computed number(s) from a presentation for a model_run.

    Returns ``{model_type, block_type, output:{...}, base_rate?, base_rate_label?}``
    or None. Prefers a regression/trend block's endpoint (with prediction interval
    + r2), then a Monte-Carlo/ARIMA fan's terminal median+band, then a correlation
    /probability metric. ``base_rate`` is set only when we can confidently read a
    probability in [0,1] (so we never fabricate a reference class from an arbitrary
    numeric projection)."""
    blocks = [b for b in (pres or {}).get("blocks", []) if isinstance(b, dict)]

    # 1) regression / trend endpoint
    for b in blocks:
        if b.get("type") == "regression" and b.get("extrapolation"):
            last = b["extrapolation"][-1]
            if not isinstance(last, dict):
                continue
            output = {
                "projected_value": last.get("y"),
                "lo": last.get("lo"),
                "hi": last.get("hi"),
                "x": last.get("x"),
                "r2": b.get("r2"),
                "method": b.get("method"),
            }
            out = {"model_type": b.get("method") or "ols", "block_type": "regression", "output": output}
            _maybe_base_rate(out, last.get("y"), b.get("y_label"))
            return out

    # 2) Monte-Carlo / ARIMA fan terminal point
    for b in blocks:
        if b.get("type") == "fan" and b.get("median"):
            median = b["median"]
            bands = b.get("bands") or []
            lo = hi = None
            if bands and isinstance(bands[0], dict):
                lower = bands[0].get("lower") or []
                upper = bands[0].get("upper") or []
                lo = lower[-1] if lower else None
                hi = upper[-1] if upper else None
            mt = "arima" if str(b.get("title", "")).lower().startswith("arima") else "montecarlo"
            output = {"projected_value": median[-1], "lo": lo, "hi": hi, "n_paths": b.get("n_paths")}
            return {"model_type": mt, "block_type": "fan", "output": output}

    # 3) correlation / probability metric
    for b in blocks:
        if b.get("type") == "metric" and isinstance(b.get("value"), (int, float)):
            label = str(b.get("label") or "")
            unit = str(b.get("unit") or "")
            mt = "correlation" if unit == "r" or "corr" in label.lower() else "metric"
            output = {"value": b.get("value"), "label": label, "unit": unit}
            out = {"model_type": mt, "block_type": "metric", "output": output}
            if mt != "correlation":
                _maybe_base_rate(out, b.get("value"), label, unit=unit)
            return out
    return None


def _maybe_base_rate(out: dict, value: Any, label: str | None, *, unit: str | None = None) -> None:
    """Tag ``out`` with a base_rate ONLY when value reads as a probability in [0,1]
    and the label/unit signals a rate/probability (never an arbitrary level)."""
    if not isinstance(value, (int, float)) or not (0.0 <= float(value) <= 1.0):
        return
    hay = f"{label or ''} {unit or ''}".lower()
    # NB: no ``share`` cue — a market/vote SHARE in [0,1] is a level, not the
    # probability of the question resolving, and promoting it to a reference-class
    # base rate silently pollutes the outside view (the very "arbitrary level"
    # this guard exists to reject).
    if any(cue in hay for cue in ("rate", "probability", "prob", "likelihood", "p(")):
        out["base_rate"] = float(value)
        out["base_rate_label"] = (label or "market-model base rate").strip()[:120]


def _extrapolation_summary(pres: dict) -> str:
    for b in pres.get("blocks", []):
        if isinstance(b, dict) and b.get("type") == "regression" and b.get("extrapolation"):
            last = b["extrapolation"][-1]
            return f"{b.get('y_label','value')} ≈ {last.get('y'):.4g} at x={last.get('x')}"
    for b in pres.get("blocks", []):
        if isinstance(b, dict) and b.get("type") == "fan" and b.get("median"):
            return f"median path ends near {b['median'][-1]:.4g}"
    return ""
