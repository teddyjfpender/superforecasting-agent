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
DEPTH_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "max_iterations": 18,
        "goal": "a fast, focused read: one primary model + a couple of charts + the key findings.",
        "structure": "summary, 1 primary chart, 2-4 findings.",
    },
    "standard": {
        "max_iterations": 32,
        "goal": "a solid analysis: the requested model, supporting data, diagnostics, and clear findings.",
        "structure": "summary, the model (regression/timeseries), supporting charts, findings, assumptions, sources.",
    },
    "deep": {
        "max_iterations": 55,
        "goal": "a deep analysis: broad data + web/supply-chain research, the model plus diagnostics and a sensitivity or scenario view.",
        "structure": "summary, primary model + diagnostics, sensitivity/scenario, supporting charts/tables, findings, assumptions, sources.",
    },
    "ultra": {
        "max_iterations": 90,
        "goal": "an exhaustive, highly structured study: competing models, robustness/sensitivity, scenario fan, extensive sourcing.",
        "structure": "executive summary, multiple models, robustness/sensitivity, scenario/simulation fan, detailed tables, findings, assumptions, full sources.",
    },
}
DEFAULT_DEPTH = "standard"

MARKET_MODEL_SYSTEM_PROMPT = """You are a quantitative markets researcher building a saved, reproducible "Market Model" for a forecasting desk. Think like a sharp quant: decompose the question into measurable drivers, gather REAL data, compute every number deterministically, and present formal findings.

Rules:
1. Gather data from adapters with `import_source_evidence` / `import_source_evidence_batch` (fred, bls, yahoo, stooq, sec/secsearch, coingecko, worldbank, markets, rss, ...) and the web (`web_search`/`web_extract`) for context/supply-chain. NEVER invent numbers or sources.
2. Compute EVERY statistic (regression, correlation, trend/extrapolation, Monte-Carlo, cointegration, event-study, ARIMA, backtest) by calling the `market_compute` tool. Do NOT hand-derive coefficients, R^2, percentiles, or projections.
3. Build the answer from the standardized presentation block library and call `emit_market_presentation` EXACTLY ONCE with the assembled Presentation. Cite imported evidence in findings (`evidence_refs`) and a `sources` block.
4. Also pass a `spec` to `emit_market_presentation` describing the re-runnable recipe: the data series you used (name + source_type + source) and the compute steps (model_type + which series map to inputs + params), so the model can re-pull fresh data and recompute later.
5. House style: plain, probability-literate, decisive but hedged; NO em-dashes.

Block types: narrative, finding, metric, timeseries, scatter, regression, bars, table, fan (simulation), scenario, assumptions, sources. The presentation header needs a title + summary; status defaults to complete."""


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


def _run_market_agent(
    *,
    system: str,
    user: str,
    max_iterations: int,
    model: str | None,
    provider: str | None,
    main_runtime: dict | None = None,
    runtime: dict | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the bounded market-models agent. Returns run_conversation's result dict.

    ``runtime`` carries the SESSION's resolved credentials (provider / base_url /
    api_key / api_mode / model) so the background agent authenticates exactly like
    the live session — a fresh AIAgent that re-resolves from config can land on a
    different/unconfigured provider and get an HTML auth/error page. ``main_runtime``
    is unused here (it belongs to the auxiliary call_llm).
    """
    from run_agent import AIAgent

    rt = runtime or {}
    kwargs: dict[str, Any] = {
        "model": rt.get("model") or model or "",
        "provider": rt.get("provider") or provider,
        "max_iterations": max_iterations,
        "enabled_toolsets": ["market-models"],
        "platform": "cli",
    }
    # Forward the session's resolved credentials (only when present, so we never
    # override the agent's own resolution with None). Mirrors _make_agent.
    for src, dst in (
        ("base_url", "base_url"), ("api_key", "api_key"), ("api_mode", "api_mode"),
        ("credential_pool", "credential_pool"), ("command", "acp_command"), ("args", "acp_args"),
    ):
        if rt.get(src) is not None:
            kwargs[dst] = rt[src]

    # Stream a live label per tool call so the UI shows what the agent is doing
    # (system visibility), not a static spinner. Best-effort, never throws.
    if progress is not None:
        def _on_tool_start(_id: Any, name: str, _args: Any) -> None:
            try:
                progress(_TOOL_LABELS.get(name, str(name)))
            except Exception:
                pass

        kwargs["tool_start_callback"] = _on_tool_start

    agent = AIAgent(**kwargs)
    return agent.run_conversation(user, system_message=system)


def _aux_llm(messages: list[dict], *, max_tokens: int = 900, temperature: float = 0.5, main_runtime: dict | None = None) -> str:
    """Auxiliary LLM call for prose re-narration. Returns content text ('' on failure)."""
    try:
        from agent.auxiliary_client import call_llm

        resp = call_llm(task="market_model", messages=messages, temperature=temperature,
                        max_tokens=max_tokens, timeout=60, main_runtime=main_runtime)
        return resp.choices[0].message.content or ""
    except Exception:
        return ""


def _repull_series(spec: dict) -> list[dict] | None:
    """Best-effort re-pull of a spec's data series via import_source_evidence.

    Returns refreshed series dicts ([{name,source_type,source,unit,points,as_of}]),
    or None if the spec has no re-runnable series / re-pull is unavailable.
    """
    series_defs = [s for s in (spec or {}).get("series", []) if isinstance(s, dict)]
    runnable = [s for s in series_defs if s.get("source_type") and s.get("source")]
    if not runnable:
        return None
    try:
        from tools.forecasting_tool import _load_source_adapter_items  # type: ignore
    except Exception:
        return None

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
        try:
            items = _load_source_adapter_items(s["source_type"], s["source"], {"limit": int(s.get("limit") or 60)})
        except Exception:
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
    return refreshed or None


# ── presentation extraction from an agent run ─────────────────────────────────


def _collect_emit(result: dict) -> tuple[dict | None, dict | None]:
    """Most reliable → least: the tool's thread-local stash, then the run's tool
    calls, then a fenced JSON object in the final response."""
    try:
        from tools.market_presentation_tool import take_emitted

        emitted = take_emitted()
        if isinstance(emitted, dict) and isinstance(emitted.get("presentation"), dict):
            spec = emitted.get("spec") if isinstance(emitted.get("spec"), dict) else None
            return emitted["presentation"], spec
    except Exception:
        pass
    return _extract_emit(result)


def _reset_emit() -> None:
    try:
        from tools.market_presentation_tool import reset_emitted

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
    if params.get("horizon"):
        extras.append(f"Horizon: {params['horizon']}.")
    if params.get("target_year"):
        extras.append(f"Extrapolate toward: {params['target_year']}.")
    if params.get("assumptions"):
        extras.append(f"User assumptions: {params['assumptions']}.")
    return (
        f"Quant question:\n{question}\n\n"
        f"Depth: {params.get('depth') or DEFAULT_DEPTH} — aim for {preset['goal']}\n"
        f"Suggested structure: {preset['structure']}\n"
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
    return {
        "api_calls": result.get("api_calls"),
        "completed": result.get("completed"),
        # Clean: the error may be a raw HTML auth/error page — never store the dump.
        "agent_error": _clean_text(str(err), limit=300) if err else None,
        "messages": len(msgs),
        "tool_calls": tool_names,
        "emitted": "emit_market_presentation" in tool_names,
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

    refreshed_series = _repull_series(spec)
    if not refreshed_series:
        return {"model_id": model_id, "presentation": pres, "refreshed": False}

    try:
        ledger.replace_market_data_series(model_id, refreshed_series)
    except Exception:
        pass
    by_name = {s["name"]: s["points"] for s in refreshed_series}
    recomputed = _recompute_blocks(pres.get("blocks", []), spec, by_name)
    pres["blocks"] = recomputed
    pres["as_of_data"] = utc_now_iso()
    return {"model_id": model_id, "presentation": pres, "refreshed": True}


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

    Best-effort: returns {question_id?, seed} so the caller can route to the normal
    forecast-create flow if the ledger can't create a full question directly.
    """
    model = ledger.get_market_model(model_id)
    try:
        pres = ledger.get_market_presentation(model_id)["presentation"]
    except Exception:
        pres = {}
    proj = _extrapolation_summary(pres)
    seed = {
        "title": f"{model.get('title')} — will the projection hold?",
        "description": (model.get("question") or "")
        + (f"\n\nModel projection: {proj}" if proj else ""),
        "source_market_model": model_id,
    }
    return {"model_id": model_id, "seed": seed}


def _extrapolation_summary(pres: dict) -> str:
    for b in pres.get("blocks", []):
        if isinstance(b, dict) and b.get("type") == "regression" and b.get("extrapolation"):
            last = b["extrapolation"][-1]
            return f"{b.get('y_label','value')} ≈ {last.get('y'):.4g} at x={last.get('x')}"
    for b in pres.get("blocks", []):
        if isinstance(b, dict) and b.get("type") == "fan" and b.get("median"):
            return f"median path ends near {b['median'][-1]:.4g}"
    return ""
