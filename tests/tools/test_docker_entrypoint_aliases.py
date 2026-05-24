"""Static contracts for forecast-native Docker runtime aliases."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
ENTRYPOINT = REPO_ROOT / "docker" / "entrypoint.sh"


def test_dockerfile_exports_forecast_native_web_dist_aliases() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert "ENV SUPERFORECASTING_AGENT_WEB_DIST=/opt/hermes/hermes_cli/web_dist" in text
    assert "ENV FORECAST_WEB_DIST=/opt/hermes/hermes_cli/web_dist" in text
    assert "ENV HERMES_WEB_DIST=/opt/hermes/hermes_cli/web_dist" in text


def test_docker_entrypoint_prefers_forecast_native_runtime_aliases() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    auth_alias = (
        'AUTH_JSON_BOOTSTRAP="${SUPERFORECASTING_AGENT_AUTH_JSON_BOOTSTRAP:-'
        '${FORECAST_AUTH_JSON_BOOTSTRAP:-${HERMES_AUTH_JSON_BOOTSTRAP:-}}}"'
    )
    uid_alias = 'RUNTIME_UID="${SUPERFORECASTING_AGENT_UID:-${FORECAST_UID:-${HERMES_UID:-}}}"'
    gid_alias = 'RUNTIME_GID="${SUPERFORECASTING_AGENT_GID:-${FORECAST_GID:-${HERMES_GID:-}}}"'

    assert uid_alias in text
    assert gid_alias in text
    assert auth_alias in text
    assert 'printf \'%s\' "$AUTH_JSON_BOOTSTRAP"' in text
    assert 'printf \'%s\' "$HERMES_AUTH_JSON_BOOTSTRAP"' not in text
    assert 'Changing forecast runtime UID to $RUNTIME_UID' in text
    assert 'Changing hermes UID to $HERMES_UID' not in text
