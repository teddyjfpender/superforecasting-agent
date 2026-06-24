"""Per-tenant / per-session runtime overlay carried in a contextvar.

Today the desk resolves credentials and session toggles from process-global
``os.environ`` — fine for one session per process, but a multi-tenant host (multiple
Slack workspaces / TUI sessions in ONE process) would have sessions clobber each
other's provider keys and model/voice toggles. This contextvar is the per-tenant
truth: a host sets it around each session's execution, and ``build_agent`` reads the
credential half so secrets resolve per tenant WITHOUT touching process globals.

This is the FOUNDATION (the contextvar + the build_agent seam). Migrating the scattered
direct ``os.environ`` readers in tools/agent to consult it is the staged follow-on; an
unset contextvar means today's exact process-global behaviour (zero behaviour change).
"""

from __future__ import annotations

import contextvars
from typing import Any

_TENANT_RUNTIME: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "tenant_runtime", default=None
)


def set_tenant_runtime(
    *, credential: dict[str, Any] | None = None, toggles: dict[str, str] | None = None
):
    """Set the current tenant's credential context (``{provider, api_key, base_url}``)
    and/or runtime toggles (``{MODEL, VOICE, ...}``); returns a token for
    ``clear_tenant_runtime`` (call it in a ``finally``). Merges over any current value
    so a caller can set credentials and toggles independently."""
    current = _TENANT_RUNTIME.get() or {}
    nxt = {
        "credential": credential if credential is not None else current.get("credential"),
        "toggles": {**(current.get("toggles") or {}), **(toggles or {})},
    }
    return _TENANT_RUNTIME.set(nxt)


def clear_tenant_runtime(token) -> None:
    try:
        _TENANT_RUNTIME.reset(token)
    except Exception:
        pass


def get_credential_context() -> dict[str, Any] | None:
    """The current tenant's ``{provider, api_key, base_url}`` (None = use the
    process-global default). ``build_agent`` reads this when no explicit
    ``credential_context`` is passed."""
    runtime = _TENANT_RUNTIME.get()
    cred = (runtime or {}).get("credential")
    return cred or None


def get_toggle(name: str, default: str | None = None) -> str | None:
    """A per-tenant runtime toggle (e.g. MODEL, VOICE), or ``default`` when unset — the
    contextvar-scoped replacement for a process-global ``os.environ`` read."""
    runtime = _TENANT_RUNTIME.get()
    if not runtime:
        return default
    value = (runtime.get("toggles") or {}).get(name)
    return value if value is not None else default
