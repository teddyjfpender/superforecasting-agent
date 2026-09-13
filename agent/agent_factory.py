"""The single resolve->construct path for an AIAgent.

Migrated surfaces spawn agents through ``build_agent()`` so the
resolve-runtime-provider -> map -> construct pattern has one owner. A per-tenant
credential context has a single seam to thread through (``credential_context``).

ADDITIVE by design: this wraps, and never replaces, ``AIAgent`` / ``init_agent``. The
constructor and its 30+ kwargs are unchanged; existing call sites keep working and are
migrated incrementally.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# The runtime-provider dict keys (resolve_runtime_provider) that map onto AIAgent
# constructor kwargs. CLI and TUI construction both use this mapping.
_RUNTIME_TO_KWARG: dict[str, str] = {
    "provider": "provider",
    "base_url": "base_url",
    "api_key": "api_key",
    "api_mode": "api_mode",
    "command": "acp_command",
    "args": "acp_args",
    "credential_pool": "credential_pool",
}


def _validate_provider_model(provider: str | None, model: str) -> None:
    """Reject combinations known to fail before any paid/network dispatch."""
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    if normalized_provider != "openai-codex" or not normalized_model:
        return
    if normalized_model.startswith(("gpt-", "o1", "o3", "o4", "codex-")):
        return
    raise ValueError(
        f"model {model!r} is not compatible with openai-codex; "
        "select that model's provider or use a Codex-supported GPT/o-series model"
    )


def _aiagent_cls():
    """Indirection so callers/tests can construct without importing the runtime eagerly
    (agent.runtime is heavy) and so the class is patchable in tests."""
    from agent.runtime import AIAgent

    return AIAgent


def resolve_and_map_runtime(
    runtime: dict[str, Any] | None = None,
    *,
    requested_provider: str | None = None,
    target_model: str | None = None,
    credential_context: dict[str, Any] | None = None,
    configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a runtime-provider dict (if not supplied) and map it to the AIAgent
    kwargs. A ``credential_context`` (the per-tenant seam) may supply an explicit
    provider / api_key / base_url that take precedence when resolving — so a future
    multi-tenant caller can resolve secrets per tenant without touching process globals.
    Keys whose runtime value is None are dropped (so the AIAgent default applies)."""
    if runtime is None:
        from superforecasting_agent.runtime.runtime_provider import (
            resolve_runtime_provider,
        )

        ctx = credential_context or {}
        config_options = {"config": configuration} if configuration is not None else {}
        runtime = resolve_runtime_provider(
            requested=ctx.get("provider") or requested_provider,
            explicit_api_key=ctx.get("api_key"),
            explicit_base_url=ctx.get("base_url"),
            target_model=target_model or None,
            **config_options,
        )
    return {
        kwarg: runtime.get(key)
        for key, kwarg in _RUNTIME_TO_KWARG.items()
        if runtime.get(key) is not None
    }


def build_agent(
    runtime: dict[str, Any] | None = None,
    *,
    model: str = "",
    requested_provider: str | None = None,
    credential_context: dict[str, Any] | None = None,
    configuration: dict[str, Any] | None = None,
    **agent_kwargs: Any,
):
    """Construct an AIAgent via the single resolve->construct path.

    ``runtime`` is a resolved ``resolve_runtime_provider()`` dict; when None it is
    resolved here from ``requested_provider`` + ``model`` (+ ``credential_context``).
    All other AIAgent kwargs pass straight through. Explicit ``agent_kwargs`` WIN over
    the mapped runtime defaults (a caller may override e.g. ``api_key``); the mapping
    only fills what the caller didn't specify — behaviour-identical to the hand-written
    sites it replaces.
    """
    if credential_context is None:
        # fall back to the per-tenant contextvar so a multi-tenant host's secrets
        # resolve per session without an explicit hand-off (zero effect when unset).
        from agent.tenant_runtime import get_credential_context

        credential_context = get_credential_context()
    mapped = resolve_and_map_runtime(
        runtime,
        requested_provider=requested_provider,
        target_model=model or None,
        credential_context=credential_context,
        configuration=configuration,
    )
    for kwarg, value in mapped.items():
        agent_kwargs.setdefault(kwarg, value)
    _validate_provider_model(agent_kwargs.get("provider"), model)
    return _aiagent_cls()(model=model, **agent_kwargs)


def build_forecast_agent(
    *,
    session_id: str,
    system_prompt: str | None = None,
    startup_skills: list[str] | None = None,
    **agent_kwargs: Any,
):
    """Construct a forecasting desk agent with the shared startup policy.

    Interfaces supply their session, callbacks and runtime options. Prompt/skill
    validation precedes provider resolution or agent allocation. Storage remains
    borrowed from the caller; construction and cleanup ownership are unchanged.
    """
    from agent.startup_prompt import prepare_startup_prompt
    from forecasting.protocol import build_forecast_chat_system_prompt

    if "ephemeral_system_prompt" in agent_kwargs:
        raise ValueError("Use system_prompt when constructing a forecasting agent")
    prompt, _loaded_skills = prepare_startup_prompt(
        system_prompt, startup_skills or [], session_id=session_id
    )
    return build_agent(
        session_id=session_id,
        ephemeral_system_prompt=build_forecast_chat_system_prompt(prompt),
        **agent_kwargs,
    )


@contextmanager
def managed_agent(**kwargs: Any) -> Iterator[Any]:
    """Own a newly constructed agent through a complete unit of conversation work.

    Cleanup happens in the calling thread after work exits, never while a timed-out
    worker is still using the agent. Close failures propagate with the original
    exception as context. Minimal injected agents without a close method remain
    supported; production AIAgent supplies explicit resource cleanup.
    """
    agent = build_agent(**kwargs)
    try:
        yield agent
    finally:
        close = getattr(agent, "close", None)
        if callable(close):
            close()
