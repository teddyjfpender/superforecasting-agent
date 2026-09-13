"""Apply freshly authenticated credentials to an idle, host-owned agent.

The host reserves the session before calling this operation. Credential storage
and provider resolution are supplied by the runtime; transports only report the
result and refresh their presentation workers.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def refresh_credentials(
    agent: Any,
    provider: str,
    *,
    resolve: Callable[..., Mapping[str, Any]],
) -> bool:
    """Refresh the matching provider without changing the selected model.

    A sign-in for another provider must not replace the current credential pool.
    Resolution and client-switch failures propagate; the caller can distinguish
    stored credentials from credentials actually applied to the live session.
    """
    current = (getattr(agent, "provider", "") or "").strip()
    requested = provider.strip()
    allowed = (
        {"openai-codex", "openai", "codex"}
        if requested == "openai-codex"
        else {requested}
    )
    if not requested or (current and current not in allowed):
        return False
    model = getattr(agent, "model", "") or ""
    runtime = resolve(requested=current or requested, target_model=model or None)
    agent.switch_model(
        new_model=model,
        new_provider=runtime.get("provider", current) or current,
        api_key=runtime.get("api_key", ""),
        base_url=runtime.get("base_url", "") or "",
        api_mode=runtime.get("api_mode", "") or "",
    )
    # Recovery must use the same credential generation as the new client.
    agent._credential_pool = runtime.get("credential_pool")
    return True
