"""Agent-protocol probability source for historical forecast replay."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from forecasting.leak_domains import is_leak_domain
from forecasting.models import parse_timestamp, timestamp_to_datetime


AGENT_PROTOCOL_METHOD = "agent_protocol_v0"
AGENT_PROTOCOL_PROMPT_VERSION = "backtest-agent-protocol-v0"

AgentProtocolRunner = Callable[[list[dict[str, str]], dict[str, Any], int], Any]

_ANSWER_SIDE_FIELDS = {
    "probability",
    "forecast_probability",
    "distribution",
    "outcome",
    "resolution",
    "resolved_outcome",
    "resolved_at",
    "result",
    "resolution_status",
    "resolution_time",
    # The live resolution-source URL is an answer leak for historical replay: a
    # market/question slug (manifold.markets/q/<slug>, metaculus.com/questions/…)
    # often reveals the now-known outcome and is_leak_domain() does not flag those
    # hosts. Withhold it from the agent. The ledger still records it on the
    # backing question for scoring/audit; only the agent-visible blob drops it.
    "resolution_source",
    "score",
    "metadata",
    "notes",
}


def agent_protocol_binary_probability(
    case: dict[str, Any],
    *,
    runner: AgentProtocolRunner,
    case_index: int,
) -> dict[str, Any]:
    """Generate a binary probability by running the forecast protocol.

    The prompt intentionally excludes answer-side replay fields such as the
    dataset forecast probability and resolved outcome. External pre-cutoff
    baselines and evidence remain visible because they are admissible inputs.
    """

    messages = build_backtest_agent_protocol_messages(case)
    response = runner(messages, case, case_index)
    parsed = parse_agent_protocol_response(response)
    return {
        "probability": parsed["probability"],
        "confidence": parsed.get("confidence"),
        "rationale": parsed.get("rationale") or "Agent protocol generated backtest forecast.",
        "components": parsed.get("components") or {},
        "agent_model": parsed.get("agent_model"),
        "metadata": {
            "prompt_version": AGENT_PROTOCOL_PROMPT_VERSION,
            "response_fields": sorted(parsed.keys()),
        },
    }


def build_backtest_agent_protocol_messages(case: dict[str, Any]) -> list[dict[str, str]]:
    """Build strict JSON-output messages for a backtest forecast case."""

    public_case = sanitize_backtest_case_for_agent(case)
    return [
        {
            "role": "system",
            "content": (
                "You are Superforecasting Agent operating in a historical "
                "backtest. Produce an auditable binary forecast using only "
                "the case data supplied by the user. Do not infer from later "
                "resolution information, and do not use hidden answer-side "
                "fields."
            ),
        },
        {
            "role": "user",
            "content": (
                "## Historical Forecast Case\n"
                f"{json.dumps(public_case, indent=2, sort_keys=True)}\n\n"
                "Return only a JSON object with these fields:\n"
                "- probability: number between 0 and 1 for YES\n"
                "- confidence: optional number between 0 and 1\n"
                "- rationale: concise audit trail citing visible evidence, "
                "base rates, baselines, assumptions, and uncertainty\n"
                "- components: optional object or list of component probabilities"
            ),
        },
    ]


def build_agent_protocol_prompt_packet(
    case: dict[str, Any],
    *,
    case_index: int,
    dataset: str | None = None,
) -> dict[str, Any]:
    """Build a JSONL-safe prompt packet for offline agent-protocol runs."""

    public_case = sanitize_backtest_case_for_agent(case)
    packet = {
        "case_id": case.get("id"),
        "index": case_index,
        "prompt_version": AGENT_PROTOCOL_PROMPT_VERSION,
        "method": AGENT_PROTOCOL_METHOD,
        "messages": build_backtest_agent_protocol_messages(case),
        "public_case": public_case,
        "response_schema": {
            "probability": "number between 0 and 1 for YES",
            "confidence": "optional number between 0 and 1",
            "rationale": "concise audit trail citing visible evidence, base rates, baselines, assumptions, and uncertainty",
            "components": "optional object or list of component probabilities",
        },
    }
    if dataset:
        packet["dataset"] = dataset
    return packet


def sanitize_backtest_case_for_agent(case: dict[str, Any]) -> dict[str, Any]:
    """Return the case context visible to the agent during replay."""

    sanitized = {
        key: deepcopy(value)
        for key, value in case.items()
        if key not in _ANSWER_SIDE_FIELDS and not str(key).startswith("score")
    }
    cutoff = _case_cutoff(case)
    sanitized["evidence"] = _pre_cutoff_evidence(case, cutoff)
    sanitized["baselines"] = _pre_cutoff_baselines(case, cutoff)
    sanitized["evidence_cutoff"] = case.get("evidence_cutoff") or case.get("simulated_forecast_time") or case.get("as_of")
    sanitized["forecast_task"] = (
        "Estimate the probability that the binary question resolves YES as of "
        "the evidence cutoff. Keep the estimate independent from the resolved outcome."
    )
    return sanitized


def parse_agent_protocol_response(response: Any) -> dict[str, Any]:
    """Parse and validate a JSON probability response from an agent run."""

    payload = _coerce_json_response(response)
    probability = _optional_probability(payload.get("probability"))
    if probability is None:
        raise ValueError("agent protocol response must contain probability between 0 and 1")
    confidence = _optional_probability(payload.get("confidence"))
    components = payload.get("components", payload.get("component_forecasts", {}))
    if components is None:
        components = {}
    if not isinstance(components, (dict, list)):
        raise ValueError("agent protocol response components must be an object or list")
    rationale = payload.get("rationale") or payload.get("reasoning") or payload.get("summary")
    return {
        "probability": probability,
        "confidence": confidence,
        "rationale": str(rationale or ""),
        "components": components,
        "agent_model": payload.get("agent_model") or payload.get("model"),
    }


def _coerce_json_response(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        if isinstance(response.get("response"), (dict, str)):
            return _coerce_json_response(response["response"])
        if isinstance(response.get("final_response"), (dict, str)):
            return _coerce_json_response(response["final_response"])
        return response
    if not isinstance(response, str):
        raise ValueError("agent protocol response must be JSON text or an object")

    text = response.strip()
    if not text:
        raise ValueError("agent protocol response is empty")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return _coerce_json_response(fenced.group(1))

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("agent protocol response did not contain a JSON object")


def _case_cutoff(case: dict[str, Any]):
    cutoff_raw = case.get("evidence_cutoff") or case.get("simulated_forecast_time") or case.get("as_of")
    cutoff = parse_timestamp(cutoff_raw, field_name="evidence_cutoff") if cutoff_raw else None
    return timestamp_to_datetime(cutoff) if cutoff else None


def _evidence_url(item: dict[str, Any]) -> str | None:
    for key in ("source_url", "url", "source", "link", "source_or_note"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _pre_cutoff_evidence(case: dict[str, Any], cutoff) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    question_config = case.get("question_config")
    extra_deny = (
        question_config.get("leak_denylist") if isinstance(question_config, dict) else None
    )
    for item in case.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        # AIA P2.4 — never show backtest-inadmissible / leak-domain evidence to the
        # agent: a live-widget source re-introduces exactly the foreknowledge the
        # denylist exists to block. Honour an explicit flag, else compute from the URL.
        if item.get("admissible_for_backtests") is False or item.get("leak_domain"):
            continue
        url = _evidence_url(item)
        if url and is_leak_domain(url, extra_denylist=extra_deny):
            continue
        available_raw = item.get("available_at") or item.get("published_at")
        if not available_raw:
            continue
        available = parse_timestamp(available_raw, field_name="available_at")
        available_dt = timestamp_to_datetime(available)
        if cutoff and available_dt and available_dt > cutoff:
            continue
        rows.append(deepcopy(item))
    return rows


def _pre_cutoff_baselines(case: dict[str, Any], cutoff) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for baseline in case.get("baselines") or []:
        if not isinstance(baseline, dict):
            continue
        as_of_raw = baseline.get("as_of")
        if as_of_raw and cutoff:
            as_of = parse_timestamp(as_of_raw, field_name="baseline_as_of")
            as_of_dt = timestamp_to_datetime(as_of)
            if as_of_dt and as_of_dt > cutoff:
                continue
        rows.append(deepcopy(baseline))
    return rows


def _optional_probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        probability = float(value)
    elif isinstance(value, str):
        try:
            probability = float(value)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        return None
    return probability
