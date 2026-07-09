"""Deploy-artifact hardening gates (P3).

A grep-gate over the SHIPPED bootstrap/units/compose: no active ``--insecure``,
no active ``0.0.0.0`` bind (P3.1 AC), plus positive checks that the P3 hardening
is actually wired into the installer + the Caddy opt-in recipe. Comments are
allowed (a commented example never binds anything); only ACTIVE lines count.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# The artifacts a fresh box actually runs / installs (NOT the opt-in Caddy public
# surface, which binds 80/443 by design and is gated behind a compose profile).
SHIPPED = [
    REPO / "scripts" / "hetzner-install.sh",
    REPO / "scripts" / "upgrade.sh",
    REPO / "scripts" / "forecast-desk",
    REPO / "deploy" / "cloud-init.yaml",
    REPO / "docker-compose.yml",
]


def _active_lines(path: Path) -> list[str]:
    """Lines that are not blank and not a shell/YAML comment."""
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        out.append(raw)
    return out


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_no_insecure_flag_in_shipped_artifacts(path):
    for line in _active_lines(path):
        assert "--insecure" not in line, f"{path.name}: active --insecure line: {line!r}"


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_no_public_bind_in_shipped_artifacts(path):
    for line in _active_lines(path):
        assert "0.0.0.0" not in line, f"{path.name}: active 0.0.0.0 bind: {line!r}"


def test_installer_mints_gateway_token_0600():
    text = (REPO / "scripts" / "hetzner-install.sh").read_text(encoding="utf-8")
    assert "mint_gateway_token" in text
    assert "gateway.token" in text
    assert "chmod 600" in text  # the token is 0600
    assert "mint_gateway_token" in text.split("# ── run", 1)[-1]  # actually called


def test_installer_seeds_spend_guards():
    text = (REPO / "scripts" / "hetzner-install.sh").read_text(encoding="utf-8")
    assert "seed_spend_guidance" in text
    assert "FORECAST_BUDGET_DAILY_USD" in text
    assert "FORECAST_POLICY_CRON_LLM_SPEND" in text


def test_forecast_desk_is_stdio_tui_not_http():
    """The SSH landing must stay on the stdio TUI (unaffected by the HTTP token)."""
    text = (REPO / "scripts" / "forecast-desk").read_text(encoding="utf-8")
    assert "--tui" in text
    assert "gateway.token" not in text  # the landing never touches the HTTP token


def test_caddy_recipe_present_and_sse_safe():
    caddyfile = REPO / "deploy" / "caddy" / "Caddyfile"
    compose = REPO / "deploy" / "caddy" / "compose.caddy.yml"
    assert caddyfile.exists() and compose.exists()
    cf = caddyfile.read_text(encoding="utf-8")
    assert "reverse_proxy" in cf
    assert "flush_interval -1" in cf  # SSE buffering OFF
    assert "basicauth" in cf  # login in front of the dashboard
    comp = compose.read_text(encoding="utf-8")
    assert 'profiles: ["tls"]' in comp  # opt-in, never on by default
