"""Tests for fork-native auth command guidance."""

from types import SimpleNamespace

import pytest

from hermes_cli.auth import AuthError, format_auth_error, login_command
from hermes_cli.auth_commands import auth_add_command, auth_status_command


def test_auth_status_missing_provider_uses_forecast_native_example():
    with pytest.raises(SystemExit) as exc:
        auth_status_command(SimpleNamespace(provider=""))

    message = str(exc.value)
    assert "`superforecasting-agent auth status xai-oauth`" in message
    assert "`hermes auth status xai-oauth`" not in message


def test_auth_add_unsupported_type_uses_forecast_native_command(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))

    with pytest.raises(SystemExit) as exc:
        auth_add_command(
            SimpleNamespace(
                provider="openrouter",
                auth_type="oauth",
                api_key="",
                label="",
            )
        )

    message = str(exc.value)
    assert "`superforecasting-agent auth add openrouter`" in message
    assert "`hermes auth add openrouter`" not in message


def test_runtime_auth_relogin_guidance_uses_forecast_native_model_command():
    message = format_auth_error(AuthError("Token expired.", relogin_required=True))

    assert "`superforecasting-agent model`" in message
    assert "`hermes model`" not in message


def test_removed_login_command_points_to_fork_native_replacements(capsys):
    with pytest.raises(SystemExit):
        login_command(SimpleNamespace())

    out = capsys.readouterr().out
    assert "'superforecasting-agent auth'" in out
    assert "'superforecasting-agent model'" in out
    assert "'superforecasting-agent setup'" in out


def test_auth_docs_urls_are_repo_local():
    import hermes_cli.auth as auth

    assert auth.XAI_OAUTH_DOCS_URL == "website/docs/guides/xai-grok-oauth.md"
    assert auth.OAUTH_OVER_SSH_DOCS_URL == "website/docs/guides/oauth-over-ssh.md"
    assert "hermes-agent.nousresearch.com" not in auth.XAI_OAUTH_DOCS_URL
    assert "hermes-agent.nousresearch.com" not in auth.OAUTH_OVER_SSH_DOCS_URL


def test_xai_pkce_local_error_uses_fork_native_product_name():
    from hermes_cli.auth import _xai_oauth_exchange_code_for_tokens

    with pytest.raises(AuthError) as exc:
        _xai_oauth_exchange_code_for_tokens(
            token_endpoint="https://example.invalid/token",
            code="code",
            redirect_uri="http://127.0.0.1/callback",
            code_verifier="",
            code_challenge="challenge",
        )

    message = str(exc.value)
    assert "Superforecasting Agent" in message
    assert "bug in Hermes" not in message
    assert "NousResearch/hermes-agent/issues" not in message
