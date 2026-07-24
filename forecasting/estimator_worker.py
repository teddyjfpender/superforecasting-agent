"""Hosted source-change estimator adapter for the operational queue."""

from __future__ import annotations

import json
from typing import Any, Callable

from forecasting.models import ValidationError, json_dumps


SYSTEM_PROMPT = """You are the source-change estimator for a forecasting ledger.
Research only as needed, then return one JSON object and no prose. The object must
contain proposed_probability_or_distribution, rationale, model_version, optional
usage, and estimation_artifact. estimation_artifact must contain:
prior_probability, evidence_updates (one row for every supplied event_id, with
likelihood_ratio, correlation_cluster, reliability_weight), raw_posterior,
ensemble_components, panel_result, proposed_probability, materiality,
evidence_cutoff, change_my_mind, and guardrail_results. Do not commit or edit the
ledger. Do not substitute the prior forecast when evidence is insufficient; report
that uncertainty in the estimate and rationale."""


class EstimatorExecutionError(RuntimeError):
    def __init__(self, message: str, *, usage: dict[str, Any]):
        super().__init__(message)
        self.usage = usage


class EstimatorOutputError(EstimatorExecutionError):
    """A deterministic estimator response error that retries cannot repair."""


def build_agent_estimator(
    *,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int = 12,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build the production callback while preserving the configured model."""
    if not model:
        from forecasting.quorum_autorun import resolve_active_model_id
        from hermes_cli.config import load_config

        model = resolve_active_model_id(load_config().get("model"))
    if not model:
        raise ValidationError("no active model configured for the estimator worker")

    def estimate(payload: dict[str, Any]) -> dict[str, Any]:
        from agent.agent_factory import build_agent

        events = payload.get("source_change_events") or [payload["source_change_event"]]
        event_ids = [str(event["id"]) for event in events]
        user = (
            "Estimate this immutable batch of source-change events for one forecast. "
            "The sources must not be "
            "polled again by the queue worker.\n\n"
            + json_dumps(payload)
            + "\n\nThe evidence_updates array must cite every event_id exactly once: "
            + ", ".join(event_ids)
            + "."
        )
        if ((payload.get("question") or {}).get("outcome_space") or {}).get("type") == "binary":
            user += (
                " proposed_probability_or_distribution must be one JSON number "
                "between 0 and 1, never an object or interval."
            )
        agent = build_agent(
            model=model,
            requested_provider=provider,
            enabled_toolsets=["web"],
            max_iterations=max_iterations,
            quiet_mode=True,
            skip_memory=True,
            skip_context_files=True,
            load_soul_identity=False,
            platform="cron",
        )
        result = agent.run_conversation(user, system_message=SYSTEM_PROMPT)
        result_dict = result if isinstance(result, dict) else {}
        usage = {
            "model_calls": int(result_dict.get("api_calls") or 0),
            "source_calls": sum(
                message.get("role") == "tool"
                for message in result_dict.get("messages") or []
            ),
            "input_tokens": int(
                result_dict.get("input_tokens") or result_dict.get("prompt_tokens") or 0
            ),
            "output_tokens": int(
                result_dict.get("output_tokens")
                or result_dict.get("completion_tokens")
                or 0
            ),
            "cost_usd": float(result_dict.get("estimated_cost_usd") or 0),
            "cost_status": str(result_dict.get("cost_status") or "estimated"),
            "cost_source": str(result_dict.get("cost_source") or "agent-runtime"),
        }
        if not isinstance(result, dict) or result.get("failed") or result.get("error"):
            detail = result_dict.get("error") or result
            raise EstimatorExecutionError(
                str(detail or "estimator model call failed"), usage=usage
            )
        try:
            parsed = _parse_json_object(str(result.get("final_response") or ""))
        except ValidationError as exc:
            raise EstimatorExecutionError(str(exc), usage=usage) from exc
        parsed["model_version"] = str(result.get("model") or model)
        parsed["usage"] = usage
        outcome_space = (payload.get("question") or {}).get("outcome_space") or {}
        try:
            parsed["proposed_probability_or_distribution"] = normalize_estimator_forecast(
                parsed.get("proposed_probability_or_distribution"),
                outcome_type=str(outcome_space.get("type") or "binary"),
            )
        except ValidationError as exc:
            raise EstimatorOutputError(str(exc), usage=usage) from exc
        return parsed

    return estimate


def _normalize_distribution_intervals(value: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    for key, low_key, high_key in (
        ("epistemic_interval_80", "q10", "q90"),
        ("credible_interval_80", "q10", "q90"),
        ("confidence_interval_80", "q10", "q90"),
        ("epistemic_interval_90", "q05", "q95"),
        ("credible_interval_90", "q05", "q95"),
        ("confidence_interval_90", "q05", "q95"),
    ):
        interval = normalized.pop(key, None)
        if (
            isinstance(interval, list)
            and len(interval) == 2
            and all(isinstance(item, (int, float)) for item in interval)
        ):
            normalized.setdefault(low_key, float(interval[0]))
            normalized.setdefault(high_key, float(interval[1]))
    return normalized


_STRUCTURAL_DISTRIBUTION_KEYS = {
    "type",
    "units",
    "unit",
    "bounds",
    "range",
    "support",
    "estimate_status",
    "status",
}
_POINT_KEYS = (
    "probability",
    "point_estimate",
    "mean",
    "median",
    "q50",
    "p50",
    "estimate",
    "value",
)


def normalize_estimator_forecast(value: Any, *, outcome_type: str) -> Any:
    """Remove model-facing envelopes and validate the ledger-facing value."""
    if isinstance(value, dict) and "distribution" in value:
        nested = value.get("distribution")
        if not isinstance(nested, (dict, int, float)) or isinstance(nested, bool):
            raise ValidationError("estimator distribution envelope must contain numeric data")
        value = nested

    if outcome_type == "binary" and isinstance(value, dict):
        point = next(
            (
                value[key]
                for key in _POINT_KEYS
                if isinstance(value.get(key), (int, float))
                and not isinstance(value.get(key), bool)
            ),
            None,
        )
        if point is None:
            raise ValidationError("binary estimator output must contain one numeric probability")
        value = float(point)
    elif isinstance(value, dict):
        value = _normalize_distribution_intervals(
            {
                str(key): raw
                for key, raw in value.items()
                if str(key).strip().lower() not in _STRUCTURAL_DISTRIBUTION_KEYS
            }
        )

    if isinstance(value, bool) or not isinstance(value, (int, float, dict)):
        raise ValidationError("estimator forecast must be a number or numeric distribution")
    if isinstance(value, dict):
        if not value:
            raise ValidationError("estimator forecast distribution cannot be empty")
        invalid = {
            key: raw
            for key, raw in value.items()
            if raw is not None
            and (isinstance(raw, bool) or not isinstance(raw, (int, float)))
        }
        if invalid:
            key, raw = next(iter(invalid.items()))
            raise ValidationError(
                f"estimator distribution value for {key!r} must be numeric "
                f"(got {type(raw).__name__})"
            )
    return value


def _parse_json_object(text: str) -> dict[str, Any]:
    value = (text or "").strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise ValidationError("estimator response did not contain a JSON object")
        try:
            parsed = json.loads(value[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValidationError(f"estimator response was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("estimator response must be a JSON object")
    return parsed


def run_hosted_estimator_worker(
    ledger,
    *,
    owner: str,
    model: str | None = None,
    provider: str | None = None,
    limit: int = 5,
    max_iterations: int = 12,
    now: str | None = None,
    question_id: str | None = None,
) -> list[dict[str, Any]]:
    estimator = build_agent_estimator(
        model=model, provider=provider, max_iterations=max_iterations
    )
    return ledger.run_estimator_tasks(
        owner=owner,
        estimator=estimator,
        now=now,
        limit=limit,
        question_id=question_id,
    )
