"""Background review routing and budgets, independent of forecast calibration."""

from typing import Any

from superforecasting_agent.constants import parse_reasoning_effort
from superforecasting_agent.runtime.runtime_provider import resolve_runtime_provider


def review_options(parent: Any, config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    auxiliary = config.get("auxiliary", {})
    task = auxiliary.get("background_review", {}) if isinstance(auxiliary, dict) else {}
    if not isinstance(task, dict):
        raise ValueError("auxiliary.background_review must be a mapping")
    iterations = task.get("max_iterations", 16)
    if type(iterations) is not int or not 1 <= iterations <= 90:
        raise ValueError(
            "background_review.max_iterations must be an integer from 1 to 90"
        )
    max_tokens = task.get("max_tokens")
    if max_tokens is not None and (
        type(max_tokens) is not int or not 1 <= max_tokens <= 131072
    ):
        raise ValueError(
            "background_review.max_tokens must be an integer from 1 to 131072"
        )
    runtime = parent._current_main_runtime()
    for key in ("provider", "model", "base_url"):
        if key in task and not isinstance(task[key], str):
            raise ValueError(f"background_review.{key} must be a string")
    provider = (task.get("provider") or "auto").strip() or "auto"
    model = (task.get("model") or "").strip() or parent.model
    base_url = (task.get("base_url") or "").strip()
    requested = parent.provider if provider == "auto" else provider
    destination_changed = requested != parent.provider or bool(base_url)
    routed = destination_changed or model != parent.model
    if destination_changed:
        if not (task.get("model") or "").strip():
            raise ValueError(
                "background_review.model is required for a separate provider or endpoint"
            )
        # Resolve only the chosen destination; never borrow the parent's key for
        # another provider or endpoint. A model-only change keeps live OAuth and
        # credential-pool ownership, which environment resolution cannot rebuild.
        runtime = resolve_runtime_provider(
            requested=requested,
            target_model=model,
            explicit_api_key="",
            explicit_base_url=base_url,
            config=config,
        )
    mode = runtime.get("api_mode")
    if mode == "codex_app_server":
        mode = "codex_responses"
    options = {
        "model": model,
        "provider": runtime.get("provider") or requested,
        "api_mode": mode,
        "base_url": runtime.get("base_url") or None,
        "api_key": runtime.get("api_key") or None,
        "credential_pool": runtime.get("credential_pool")
        if destination_changed
        else getattr(parent, "_credential_pool", None),
        "max_iterations": iterations,
        "max_tokens": max_tokens
        if max_tokens is not None
        else (None if routed else getattr(parent, "max_tokens", None)),
        "reasoning_config": None
        if routed
        else getattr(parent, "reasoning_config", None),
    }
    for key in ("enabled_toolsets", "disabled_toolsets"):
        if hasattr(parent, key):
            options[key] = getattr(parent, key)
    effort = task.get("reasoning_effort")
    if effort not in (None, ""):
        if (
            not isinstance(effort, str)
            or (parsed := parse_reasoning_effort(effort)) is None
        ):
            raise ValueError("background_review.reasoning_effort is invalid")
        options["reasoning_config"] = parsed
    return options, routed
