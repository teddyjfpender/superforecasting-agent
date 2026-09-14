"""Cost notice for deliberate model selection; automatic routing never calls this."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def context_switch_notice(
    *,
    current_model: str,
    current_provider: str,
    target_model: str,
    target_provider: str,
    tokens: int,
    threshold: int = 100_000,
) -> str:
    if threshold <= 0 or tokens < threshold:
        return ""
    if (current_model, current_provider) == (target_model, target_provider):
        return ""
    return (
        f"This conversation contains about {tokens:,} context tokens. "
        "Changing model or provider may forfeit its prompt cache; the next reply "
        "may process the full conversation at uncached input rates. "
        "Start a new session if you do not need this history."
    )


def attach_context_warning(result: Any, agent: Any) -> None:
    """Use the same recovered accounting and configuration on every user surface."""
    if agent is None or not result.success:
        return
    from agent.context_usage import context_tokens
    from superforecasting_agent.runtime.config import load_config

    display = load_config().get("display", {})
    threshold = (
        display.get("model_switch_warning_tokens", 100_000)
        if isinstance(display, dict)
        else 100_000
    )
    if type(threshold) is not int or threshold < 0:
        threshold = 100_000
    if threshold == 0:
        return
    messages = getattr(agent, "_session_messages", [])
    try:
        tokens = context_tokens(agent, messages if isinstance(messages, list) else [])
    except (AttributeError, TypeError, ValueError):
        logger.warning(
            "Context accounting unavailable; proceeding without a model-switch cache estimate"
        )
        return
    warning = context_switch_notice(
        current_model=agent.model,
        current_provider=agent.provider,
        target_model=result.new_model,
        target_provider=result.target_provider,
        tokens=tokens,
        threshold=threshold,
    )
    if warning and warning not in result.warning_message:
        result.warning_message = "\n".join(
            filter(None, [result.warning_message, warning])
        )
