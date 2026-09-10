"""Provider credential refresh and active-client credential rotation."""

import logging

from superforecasting_agent.runtime.timeouts import get_provider_request_timeout

logger = logging.getLogger("run_agent")


def _try_refresh_codex_client_credentials(self, *, force: bool = True) -> bool:
    if self.api_mode != "codex_responses" or self.provider not in {"openai-codex", "xai-oauth"}:
        return False

    # Guard against silent account swap.
    #
    # When an agent is using a non-singleton credential — e.g. a manual
    # pool entry (``superforecasting-agent auth add xai-oauth``) whose tokens belong to
    # a different account than the loopback_pkce singleton, or an agent
    # constructed with an explicit ``api_key=`` arg — force-refreshing
    # the singleton here and adopting its tokens silently re-routes the
    # rest of the conversation onto the singleton's account.  The
    # credential pool's reactive recovery (``_recover_with_credential_pool``)
    # is the right channel for that case; this path is the
    # singleton-only fallback used when the pool can't recover, and
    # MUST only fire when the agent really is on singleton tokens.
    try:
        if self.provider == "openai-codex":
            from superforecasting_agent.runtime.auth import resolve_codex_runtime_credentials

            singleton_now = resolve_codex_runtime_credentials(
                refresh_if_expiring=False,
            )
        else:
            from superforecasting_agent.runtime.auth import resolve_xai_oauth_runtime_credentials

            singleton_now = resolve_xai_oauth_runtime_credentials(
                refresh_if_expiring=False,
            )
    except Exception as exc:
        logger.debug("%s singleton read failed: %s", self.provider, exc)
        return False

    singleton_key = str(singleton_now.get("api_key") or "").strip()
    active_key = str(self.api_key or "").strip()
    if singleton_key and active_key and singleton_key != active_key:
        logger.debug(
            "%s singleton tokens differ from the active api_key; "
            "skipping singleton force-refresh to avoid silent account swap. "
            "Reactive credential rotation should go through the pool.",
            self.provider,
        )
        return False

    try:
        if self.provider == "openai-codex":
            from superforecasting_agent.runtime.auth import resolve_codex_runtime_credentials

            creds = resolve_codex_runtime_credentials(force_refresh=force)
        else:
            from superforecasting_agent.runtime.auth import resolve_xai_oauth_runtime_credentials

            creds = resolve_xai_oauth_runtime_credentials(force_refresh=force)
    except Exception as exc:
        logger.debug("%s credential refresh failed: %s", self.provider, exc)
        return False

    api_key = creds.get("api_key")
    base_url = creds.get("base_url")
    if not isinstance(api_key, str) or not api_key.strip():
        return False
    if not isinstance(base_url, str) or not base_url.strip():
        return False

    self.api_key = api_key.strip()
    self.base_url = base_url.strip().rstrip("/")
    self._client_kwargs["api_key"] = self.api_key
    self._client_kwargs["base_url"] = self.base_url

    if not self._replace_primary_openai_client(reason=f"{self.provider}_credential_refresh"):
        return False

    return True


def _try_refresh_nous_client_credentials(self, *, force: bool = True) -> bool:
    if self.api_mode != "chat_completions" or self.provider != "nous":
        return False

    try:
        from superforecasting_agent.runtime.auth import (
            NOUS_INFERENCE_AUTH_MODE_AUTO,
            NOUS_INFERENCE_AUTH_MODE_LEGACY,
            resolve_nous_runtime_credentials,
        )

        from superforecasting_agent.runtime.nous_env import (
            nous_min_key_ttl_seconds,
            nous_timeout_seconds,
        )

        creds = resolve_nous_runtime_credentials(
            min_key_ttl_seconds=nous_min_key_ttl_seconds(),
            timeout_seconds=nous_timeout_seconds(),
            inference_auth_mode=(
                NOUS_INFERENCE_AUTH_MODE_LEGACY
                if force
                else NOUS_INFERENCE_AUTH_MODE_AUTO
            ),
        )
    except Exception as exc:
        logger.debug("Nous credential refresh failed: %s", exc)
        return False

    api_key = creds.get("api_key")
    base_url = creds.get("base_url")
    if not isinstance(api_key, str) or not api_key.strip():
        return False
    if not isinstance(base_url, str) or not base_url.strip():
        return False

    self.api_key = api_key.strip()
    self.base_url = base_url.strip().rstrip("/")
    self._client_kwargs["api_key"] = self.api_key
    self._client_kwargs["base_url"] = self.base_url
    # Nous requests should not inherit OpenRouter-only attribution headers.
    self._client_kwargs.pop("default_headers", None)

    if not self._replace_primary_openai_client(reason="nous_credential_refresh"):
        return False

    return True


def _try_refresh_copilot_client_credentials(self) -> bool:
    """Refresh Copilot credentials and rebuild the shared OpenAI client.

        Copilot tokens may remain the same string across refreshes (`gh auth token`
        returns a stable OAuth token in many setups). We still rebuild the client
        on 401 so retries recover from stale auth/client state without requiring
        a session restart.
        """
    if self.provider != "copilot":
        return False

    try:
        from superforecasting_agent.runtime.copilot_auth import resolve_copilot_token

        new_token, token_source = resolve_copilot_token()
    except Exception as exc:
        logger.debug("Copilot credential refresh failed: %s", exc)
        return False

    if not isinstance(new_token, str) or not new_token.strip():
        return False

    new_token = new_token.strip()

    self.api_key = new_token
    self._client_kwargs["api_key"] = self.api_key
    self._client_kwargs["base_url"] = self.base_url
    self._apply_client_headers_for_base_url(str(self.base_url or ""))

    if not self._replace_primary_openai_client(reason="copilot_credential_refresh"):
        return False

    logger.info("Copilot credentials refreshed from %s", token_source)
    return True


def _try_refresh_anthropic_client_credentials(self) -> bool:
    if self.api_mode != "anthropic_messages" or not hasattr(self, "_anthropic_api_key"):
        return False
    # Only refresh credentials for the native Anthropic provider.
    # Other anthropic_messages providers (MiniMax, Alibaba, etc.) use their own keys.
    if self.provider != "anthropic":
        return False
    # Azure endpoints use static API keys — OAuth token rotation doesn't apply.
    # Refreshing would pick up ~/.claude/.credentials.json OAuth token and break auth.
    _base = getattr(self, "_anthropic_base_url", "") or ""
    if "azure.com" in _base:
        return False

    try:
        from agent.anthropic_adapter import resolve_anthropic_token, build_anthropic_client

        new_token = resolve_anthropic_token()
    except Exception as exc:
        logger.debug("Anthropic credential refresh failed: %s", exc)
        return False

    if not isinstance(new_token, str) or not new_token.strip():
        return False
    new_token = new_token.strip()
    if new_token == self._anthropic_api_key:
        return False

    try:
        self._anthropic_client.close()
    except Exception:
        pass

    try:
        self._anthropic_client = build_anthropic_client(
            new_token,
            getattr(self, "_anthropic_base_url", None),
            timeout=get_provider_request_timeout(self.provider, self.model),
        )
    except Exception as exc:
        logger.warning("Failed to rebuild Anthropic client after credential refresh: %s", exc)
        return False

    self._anthropic_api_key = new_token
    # Update OAuth flag — token type may have changed (API key ↔ OAuth).
    # Only treat as OAuth on native Anthropic; third-party endpoints using
    # the Anthropic protocol must not trip OAuth paths (#1739 & third-party
    # identity-injection guard).
    from agent.anthropic_adapter import _is_oauth_token
    self._is_anthropic_oauth = _is_oauth_token(new_token) if self.provider == "anthropic" else False
    return True


def _swap_credential(self, entry) -> None:
    runtime_key = getattr(entry, "runtime_api_key", None) or getattr(entry, "access_token", "")
    runtime_base = getattr(entry, "runtime_base_url", None) or getattr(entry, "base_url", None) or self.base_url

    if self.api_mode == "anthropic_messages":
        from agent.anthropic_adapter import build_anthropic_client, _is_oauth_token

        try:
            self._anthropic_client.close()
        except Exception:
            pass

        self._anthropic_api_key = runtime_key
        self._anthropic_base_url = runtime_base
        self._anthropic_client = build_anthropic_client(
            runtime_key, runtime_base,
            timeout=get_provider_request_timeout(self.provider, self.model),
        )
        self._is_anthropic_oauth = _is_oauth_token(runtime_key) if self.provider == "anthropic" else False
        self.api_key = runtime_key
        self.base_url = runtime_base
        return

    self.api_key = runtime_key
    self.base_url = runtime_base.rstrip("/") if isinstance(runtime_base, str) else runtime_base
    self._client_kwargs["api_key"] = self.api_key
    self._client_kwargs["base_url"] = self.base_url
    self._apply_client_headers_for_base_url(self.base_url)
    self._replace_primary_openai_client(reason="credential_rotation")
