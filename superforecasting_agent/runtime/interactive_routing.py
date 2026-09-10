"""Resolve interactive credentials, model identifiers, and per-turn routing."""

import logging

from .console_output import ChatConsole, _cprint

logger = logging.getLogger("cli")


def _normalize_model_for_provider(self, resolved_provider: str) -> bool:
    """Normalize provider-specific model IDs and routing."""
    current_model = (self.model or "").strip()
    changed = False

    try:
        from superforecasting_agent.runtime.model_normalize import (
            _AGGREGATOR_PROVIDERS,
            normalize_model_for_provider,
        )

        if resolved_provider not in _AGGREGATOR_PROVIDERS:
            normalized_model = normalize_model_for_provider(current_model, resolved_provider)
            if normalized_model and normalized_model != current_model:
                if not self._model_is_default:
                    self._console_print(
                        f"[yellow]⚠️  Normalized model '{current_model}' to '{normalized_model}' for {resolved_provider}.[/]"
                    )
                self.model = normalized_model
                current_model = normalized_model
                changed = True
    except Exception:
        pass

    if resolved_provider == "copilot":
        try:
            from superforecasting_agent.runtime.models import copilot_model_api_mode, normalize_copilot_model_id

            canonical = normalize_copilot_model_id(current_model, api_key=self.api_key)
            if canonical and canonical != current_model:
                if not self._model_is_default:
                    self._console_print(
                        f"[yellow]⚠️  Normalized Copilot model '{current_model}' to '{canonical}'.[/]"
                    )
                self.model = canonical
                current_model = canonical
                changed = True

            resolved_mode = copilot_model_api_mode(current_model, api_key=self.api_key)
            if resolved_mode != self.api_mode:
                self.api_mode = resolved_mode
                changed = True
        except Exception:
            pass
        return changed

    if resolved_provider in {"opencode-zen", "opencode-go"}:
        try:
            from superforecasting_agent.runtime.models import normalize_opencode_model_id, opencode_model_api_mode

            canonical = normalize_opencode_model_id(resolved_provider, current_model)
            if canonical and canonical != current_model:
                if not self._model_is_default:
                    self._console_print(
                        f"[yellow]⚠️  Stripped provider prefix from '{current_model}'; using '{canonical}' for {resolved_provider}.[/]"
                    )
                self.model = canonical
                current_model = canonical
                changed = True

            resolved_mode = opencode_model_api_mode(resolved_provider, current_model)
            if resolved_mode != self.api_mode:
                self.api_mode = resolved_mode
                changed = True
        except Exception:
            pass
        return changed

    if resolved_provider != "openai-codex":
        return changed

    # 1. Strip provider prefix ("openai/gpt-5.4" → "gpt-5.4")
    if "/" in current_model:
        slug = current_model.split("/", 1)[1]
        if not self._model_is_default:
            self._console_print(
                f"[yellow]⚠️  Stripped provider prefix from '{current_model}'; "
                f"using '{slug}' for OpenAI Codex.[/]"
            )
        self.model = slug
        current_model = slug
        changed = True

    # 2. Replace untouched default with a Codex model
    if self._model_is_default:
        fallback_model = "gpt-5.3-codex"
        try:
            from superforecasting_agent.runtime.codex_models import get_codex_model_ids

            available = get_codex_model_ids(
                access_token=self.api_key if self.api_key else None,
            )
            if available:
                fallback_model = available[0]
        except Exception:
            pass

        if current_model != fallback_model:
            self.model = fallback_model
            changed = True

    return changed


def _resolve_turn_agent_config(self, user_message: str) -> dict:
    """Build the effective model/runtime config for a single user turn.

        Always uses the session's primary model/provider.  If the user has
        toggled `/fast` on and the current model supports Priority
        Processing / Anthropic fast mode, attach `request_overrides` so the
        API call is marked accordingly.
        """
    from superforecasting_agent.runtime.models import resolve_fast_mode_overrides

    runtime = {
        "api_key": self.api_key,
        "base_url": self.base_url,
        "provider": self.provider,
        "api_mode": self.api_mode,
        "command": self.acp_command,
        "args": list(self.acp_args or []),
        "credential_pool": getattr(self, "_credential_pool", None),
    }
    route = {
        "model": self.model,
        "runtime": runtime,
        "signature": (
            self.model,
            runtime["provider"],
            runtime["base_url"],
            runtime["api_mode"],
            runtime["command"],
            tuple(runtime["args"]),
        ),
    }

    service_tier = getattr(self, "service_tier", None)
    if not service_tier:
        route["request_overrides"] = None
        return route

    try:
        overrides = resolve_fast_mode_overrides(route["model"])
    except Exception:
        overrides = None
    route["request_overrides"] = overrides
    return route


def _ensure_runtime_credentials(self) -> bool:
    """
        Ensure runtime credentials are resolved before agent use.
        Re-resolves provider credentials so key rotation and token refresh
        are picked up without restarting the CLI.
        Returns True if credentials are ready, False on auth failure.
        """
    from superforecasting_agent.runtime.runtime_provider import (
        resolve_runtime_provider,
        format_runtime_provider_error,
    )

    _primary_exc = None
    runtime = None
    try:
        runtime = resolve_runtime_provider(
            requested=self.requested_provider,
            explicit_api_key=self._explicit_api_key,
            explicit_base_url=self._explicit_base_url,
        )
    except Exception as exc:
        _primary_exc = exc

    # Primary provider auth failed — try fallback providers before giving up.
    if runtime is None and _primary_exc is not None:
        from superforecasting_agent.runtime.auth import AuthError
        if isinstance(_primary_exc, AuthError):
            _fb_chain = self._fallback_model if isinstance(self._fallback_model, list) else []
            for _fb in _fb_chain:
                _fb_provider = (_fb.get("provider") or "").strip().lower()
                _fb_model = (_fb.get("model") or "").strip()
                if not _fb_provider or not _fb_model:
                    continue
                try:
                    runtime = resolve_runtime_provider(requested=_fb_provider)
                    logger.warning(
                        "Primary provider auth failed (%s). Falling through to fallback: %s/%s",
                        _primary_exc, _fb_provider, _fb_model,
                    )
                    _cprint(f"⚠️  Primary auth failed — switching to fallback: {_fb_provider} / {_fb_model}")
                    self.requested_provider = _fb_provider
                    self.model = _fb_model
                    _primary_exc = None
                    break
                except Exception:
                    continue

    if runtime is None:
        message = format_runtime_provider_error(_primary_exc) if _primary_exc else "Provider resolution failed."
        ChatConsole().print(f"[bold red]{message}[/]")
        return False

    api_key = runtime.get("api_key")
    base_url = runtime.get("base_url")
    resolved_provider = runtime.get("provider", "openrouter")
    resolved_api_mode = runtime.get("api_mode", self.api_mode)
    resolved_acp_command = runtime.get("command")
    resolved_acp_args = list(runtime.get("args") or [])
    resolved_credential_pool = runtime.get("credential_pool")
    # A callable api_key is a bearer-token provider (Azure Foundry
    # Entra ID — ``azure_identity_adapter.build_token_provider``).
    # The OpenAI SDK accepts ``Callable[[], str]`` for ``api_key`` and
    # invokes it before every request. Skip the string-only validation
    # and placeholder substitution for callables.
    _is_callable_provider = callable(api_key) and not isinstance(api_key, str)
    if not _is_callable_provider and (not isinstance(api_key, str) or not api_key):
        # Custom / local endpoints (llama.cpp, ollama, vLLM, etc.) often
        # don't require authentication.  When a base_url IS configured but
        # no API key was found, use a placeholder so the OpenAI SDK
        # doesn't reject the request and local servers just ignore it.
        _source = runtime.get("source", "")
        _has_custom_base = isinstance(base_url, str) and base_url and "openrouter.ai" not in base_url
        if _has_custom_base:
            api_key = "no-key-required"
            logger.debug(
                "No API key for custom endpoint %s (source=%s), "
                "using placeholder — local servers typically ignore auth",
                base_url, _source,
            )
        else:
            print("\n⚠️  Provider resolver returned an empty API key. "
                  "Set OPENROUTER_API_KEY or run: superforecasting-agent setup")
            return False
    if not isinstance(base_url, str) or not base_url:
        print("\n⚠️  Provider resolver returned an empty base URL. "
              "Check your provider config or run: superforecasting-agent setup")
        return False

    credentials_changed = api_key != self.api_key or base_url != self.base_url
    routing_changed = (
        resolved_provider != self.provider
        or resolved_api_mode != self.api_mode
        or resolved_acp_command != self.acp_command
        or resolved_acp_args != self.acp_args
    )
    self.provider = resolved_provider
    self.api_mode = resolved_api_mode
    self.acp_command = resolved_acp_command
    self.acp_args = resolved_acp_args
    self._credential_pool = resolved_credential_pool
    self._provider_source = runtime.get("source")
    self.api_key = api_key
    self.base_url = base_url

    # When a custom_provider entry carries an explicit `model` field,
    # use it as the effective model name. Without this, running
    # `superforecasting-agent chat --model <provider-name>` sends the provider name
    # (e.g. "my-provider") as the model string to the API instead of
    # the configured model (e.g. "qwen3.6-plus"), causing 400 errors.
    runtime_model = runtime.get("model")
    if runtime_model and isinstance(runtime_model, str):
        # Only use runtime model if: model is unset, or model equals provider name
        should_use_runtime_model = (
            not self.model or  # No model configured yet
            self.model == self.provider or  # Model is the provider slug
            self.model == runtime.get("name")  # Model matches provider display name
        )
        if should_use_runtime_model:
            self.model = runtime_model

    # If model is still empty (e.g. user ran `superforecasting-agent auth add openai-codex`
    # without `superforecasting-agent model`), fall back to the provider's first catalog
    # model so the API call doesn't fail with "model must be non-empty".
    if not self.model and resolved_provider:
        try:
            from superforecasting_agent.runtime.models import get_default_model_for_provider
            _default = get_default_model_for_provider(resolved_provider)
            if _default:
                self.model = _default
                logger.info(
                    "No model configured — defaulting to %s for provider %s",
                    _default, resolved_provider,
                )
        except Exception:
            pass

    # Normalize model for the resolved provider (e.g. swap non-Codex
    # models when provider is openai-codex).  Fixes #651.
    model_changed = self._normalize_model_for_provider(resolved_provider)

    # AIAgent/OpenAI client holds auth at init time, so rebuild if key,
    # routing, or the effective model changed.
    if (credentials_changed or routing_changed or model_changed) and self.agent is not None:
        self.agent = None
        self._active_agent_route_signature = None

    return True
