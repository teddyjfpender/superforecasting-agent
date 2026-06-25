"""P0 #3 completion: resolve_runtime_provider() consults the per-tenant contextvar
(agent.tenant_runtime) so EVERY caller — not just build_agent — resolves secrets per
tenant. Explicit args always win; an unset contextvar is byte-identical to before."""

from __future__ import annotations

import agent.tenant_runtime as tr
from hermes_cli.runtime_provider import resolve_runtime_provider


def test_tenant_contextvar_supplies_credentials_when_args_absent():
    token = tr.set_tenant_runtime(credential={"provider": "custom", "api_key": "tenant-key", "base_url": "https://tenant.example"})
    try:
        out = resolve_runtime_provider()  # no explicit args -> tenant context fills them
    finally:
        tr.clear_tenant_runtime(token)
    assert out.get("api_key") == "tenant-key"
    assert out.get("base_url") == "https://tenant.example"


def test_explicit_args_win_over_contextvar():
    token = tr.set_tenant_runtime(credential={"provider": "custom", "api_key": "tenant-key", "base_url": "https://tenant.example"})
    try:
        out = resolve_runtime_provider(explicit_api_key="explicit-key", explicit_base_url="https://explicit.example")
    finally:
        tr.clear_tenant_runtime(token)
    assert out.get("api_key") == "explicit-key"
    assert out.get("base_url") == "https://explicit.example"


def test_unset_contextvar_is_unchanged():
    # No tenant context -> resolves normally (returns the always-present keys, no crash).
    assert tr.get_credential_context() is None
    out = resolve_runtime_provider(requested="custom", explicit_api_key="k", explicit_base_url="https://x.example")
    assert "provider" in out and "api_key" in out and "base_url" in out
