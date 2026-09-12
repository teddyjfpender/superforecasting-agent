"""Entra configuration and SDK presence without client construction."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Dict, Optional

SCOPE_AI_AZURE_DEFAULT = "https://ai.azure.com/.default"


def has_azure_identity_installed() -> bool:
    """Return True if `azure-identity` can be imported right now.

    Cheap check — does not walk the credential chain.
    """
    try:
        import_module("azure.identity")
        return True
    except Exception:
        return False


@dataclass(frozen=True)
class EntraIdentityConfig:
    """Serializable Entra ID config.

    Captures the agent-managed Entra knobs we need outside Azure SDK
    environment configuration. Everything else
    (tenant ID, service principal secret, federated token file, sovereign
    cloud authority, etc.) flows through azure-identity's standard
    ``AZURE_*`` env vars — see the Bedrock pattern in
    ``superforecasting_agent/runtime/runtime_provider.py:1310-1377`` for the analogous
    "let the SDK read env" approach.

    ``scope`` is Microsoft's documented Foundry inference audience. Almost
    everyone uses the default; sovereign-cloud / non-standard tenants can
    override via ``model.entra.scope``. Identity selection (user-assigned
    managed identity, workload identity, service principal, tenant, authority)
    stays in the standard Azure SDK env vars such as ``AZURE_CLIENT_ID``.

    ``exclude_interactive_browser`` is kept as an internal constructor knob
    so probes stay non-interactive by default. It is not written by the setup
    wizard.

    The dataclass is frozen so it's hashable for ``functools.lru_cache``
    keying, and serializable across multiprocessing boundaries (workers
    rebuild the credential inside their own process).
    """

    scope: str = SCOPE_AI_AZURE_DEFAULT
    exclude_interactive_browser: bool = True

    def __post_init__(self) -> None:
        scope = str(self.scope or "").strip() or SCOPE_AI_AZURE_DEFAULT
        object.__setattr__(self, "scope", scope)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": self.scope,
            "exclude_interactive_browser": self.exclude_interactive_browser,
        }

    @classmethod
    def from_dict(
        cls, data: Optional[Dict[str, Any]], *, default_scope: Optional[str] = None
    ) -> "EntraIdentityConfig":
        data = data or {}
        scope = (
            str(data.get("scope") or "").strip()
            or default_scope
            or SCOPE_AI_AZURE_DEFAULT
        )
        exclude_browser = bool(data.get("exclude_interactive_browser", True))
        return cls(
            scope=scope,
            exclude_interactive_browser=exclude_browser,
        )
