"""Routing operations; shared state belongs to credentials.auth."""

from __future__ import annotations

from superforecasting_agent.credentials import auth as _core


def _get_config_hint_for_unknown_provider(
    provider_name: str, config: _core.Optional[dict] = None
) -> str:
    """Return a helpful hint string when provider resolution fails.

    Checks for common config.yaml mistakes (malformed custom_providers, etc.)
    and returns a human-readable diagnostic, or empty string if nothing found.
    """
    try:
        from superforecasting_agent.configuration.provider_validation import (
            validate_config_structure,
        )
        from superforecasting_agent.credentials.environment import load_config

        issues = validate_config_structure(load_config() if config is None else config)
        if not issues:
            return ""

        lines = [
            f"Config issue detected — run '{_core._PRIMARY_CLI} doctor' for full diagnostics:"
        ]
        for ci in issues:
            prefix = "ERROR" if ci.severity == "error" else "WARNING"
            lines.append(f"  [{prefix}] {ci.message}")
            # Show first line of hint
            first_hint = ci.hint.splitlines()[0] if ci.hint else ""
            if first_hint:
                lines.append(f"    → {first_hint}")
        return "\n".join(lines)
    except Exception:
        return ""


def resolve_provider(
    requested: _core.Optional[str] = None,
    *,
    explicit_api_key: _core.Optional[str] = None,
    explicit_base_url: _core.Optional[str] = None,
    config: _core.Optional[dict] = None,
) -> str:
    """
    Determine which inference provider to use.

    Priority (when requested="auto" or None):
    1. active_provider in auth.json with valid credentials
    2. Explicit CLI api_key/base_url -> "openrouter"
    3. OPENAI_API_KEY or OPENROUTER_API_KEY env vars -> "openrouter"
    4. Provider-specific API keys (GLM, Kimi, MiniMax) -> that provider
    5. Fallback: "openrouter"
    """
    normalized = (requested or "auto").strip().lower()

    # Normalize provider aliases
    _PROVIDER_ALIASES = {
        "glm": "zai",
        "z-ai": "zai",
        "z.ai": "zai",
        "zhipu": "zai",
        "google": "gemini",
        "google-gemini": "gemini",
        "google-ai-studio": "gemini",
        "x-ai": "xai",
        "x.ai": "xai",
        "grok": "xai",
        "xai-oauth": "xai-oauth",
        "x-ai-oauth": "xai-oauth",
        "grok-oauth": "xai-oauth",
        "xai-grok-oauth": "xai-oauth",
        "kimi": "kimi-coding",
        "kimi-for-coding": "kimi-coding",
        "moonshot": "kimi-coding",
        "kimi-cn": "kimi-coding-cn",
        "moonshot-cn": "kimi-coding-cn",
        "step": "stepfun",
        "stepfun-coding-plan": "stepfun",
        "arcee-ai": "arcee",
        "arceeai": "arcee",
        "gmi-cloud": "gmi",
        "gmicloud": "gmi",
        "minimax-china": "minimax-cn",
        "minimax_cn": "minimax-cn",
        "minimax-portal": "minimax-oauth",
        "minimax-global": "minimax-oauth",
        "minimax_oauth": "minimax-oauth",
        "alibaba_coding": "alibaba-coding-plan",
        "alibaba-coding": "alibaba-coding-plan",
        "alibaba_coding_plan": "alibaba-coding-plan",
        "claude": "anthropic",
        "claude-code": "anthropic",
        "github": "copilot",
        "github-copilot": "copilot",
        "github-models": "copilot",
        "github-model": "copilot",
        "github-copilot-acp": "copilot-acp",
        "copilot-acp-agent": "copilot-acp",
        "aigateway": "ai-gateway",
        "vercel": "ai-gateway",
        "vercel-ai-gateway": "ai-gateway",
        "opencode": "opencode-zen",
        "zen": "opencode-zen",
        "qwen-portal": "qwen-oauth",
        "qwen-cli": "qwen-oauth",
        "qwen-oauth": "qwen-oauth",
        "google-gemini-cli": "google-gemini-cli",
        "gemini-cli": "google-gemini-cli",
        "gemini-oauth": "google-gemini-cli",
        "hf": "huggingface",
        "hugging-face": "huggingface",
        "huggingface-hub": "huggingface",
        "mimo": "xiaomi",
        "xiaomi-mimo": "xiaomi",
        "tencent": "tencent-tokenhub",
        "tokenhub": "tencent-tokenhub",
        "tencent-cloud": "tencent-tokenhub",
        "tencentmaas": "tencent-tokenhub",
        "aws": "bedrock",
        "aws-bedrock": "bedrock",
        "amazon-bedrock": "bedrock",
        "amazon": "bedrock",
        "go": "opencode-go",
        "opencode-go-sub": "opencode-go",
        "kilo": "kilocode",
        "kilo-code": "kilocode",
        "kilo-gateway": "kilocode",
        "lmstudio": "lmstudio",
        "lm-studio": "lmstudio",
        "lm_studio": "lmstudio",
        # Local server aliases — route through the generic custom provider
        "ollama": "custom",
        "ollama_cloud": "ollama-cloud",
        "vllm": "custom",
        "llamacpp": "custom",
        "llama.cpp": "custom",
        "llama-cpp": "custom",
    }
    # Extend with aliases declared in plugins/model-providers/<name>/ that aren't already mapped.
    # This keeps providers/ as the single source for new aliases while the
    # hardcoded dict above remains authoritative for existing ones.
    try:
        from providers import list_providers as _lp

        for _pp in _lp():
            for _alias in _pp.aliases:
                if _alias not in _PROVIDER_ALIASES:
                    _PROVIDER_ALIASES[_alias] = _pp.name
    except Exception:
        pass
    normalized = _PROVIDER_ALIASES.get(normalized, normalized)

    if normalized == "openrouter":
        return "openrouter"
    if normalized == "custom":
        return "custom"
    if normalized in _core.PROVIDER_REGISTRY:
        return normalized
    if normalized != "auto":
        # Check for common config.yaml issues that cause this error
        _config_hint = _core._get_config_hint_for_unknown_provider(normalized, config)
        msg = f"Unknown provider '{normalized}'."
        if _config_hint:
            msg += f"\n\n{_config_hint}"
        else:
            msg += (
                f" Check '{_core._PRIMARY_CLI} model' for available providers, or "
                f"run '{_core._PRIMARY_CLI} doctor' to diagnose config issues."
            )
        raise _core.AuthError(msg, code="invalid_provider")

    # Explicit one-off CLI creds always mean openrouter/custom
    if explicit_api_key or explicit_base_url:
        return "openrouter"

    # Check auth store for an active OAuth provider
    try:
        auth_store = _core._load_auth_store()
        active = auth_store.get("active_provider")
        if active and active in _core.PROVIDER_REGISTRY:
            status = _core.get_auth_status(active)
            if status.get("logged_in"):
                return active
    except Exception as e:
        _core.logger.debug("Could not detect active auth provider: %s", e)

    if _core.has_usable_secret(
        _core.os.getenv("OPENAI_API_KEY")
    ) or _core.has_usable_secret(_core.os.getenv("OPENROUTER_API_KEY")):
        return "openrouter"

    # Auto-detect an OpenRouter credential added via `auth add openrouter`
    # (manual pool entry, no env var). Without this, a key that only lives in
    # the credential pool is invisible to auto-detection — the user sees
    # `auth list` showing the credential while requests go out with no
    # Authorization header ("HTTP 401: Missing Authentication header"). The
    # env-var check above only covers keys exported as OPENROUTER_API_KEY /
    # OPENAI_API_KEY. See upstream issue #42130.
    try:
        from agent.credential_pool import load_pool as _load_pool

        if _load_pool("openrouter").has_credentials():
            return "openrouter"
    except Exception as e:
        _core.logger.debug("Could not check OpenRouter credential pool: %s", e)

    # Auto-detect API-key providers by checking their env vars
    for pid, pconfig in _core.PROVIDER_REGISTRY.items():
        if pconfig.auth_type != "api_key":
            continue
        # GitHub tokens are commonly present for repo/tool access but should not
        # hijack inference auto-selection unless the user explicitly chooses
        # Copilot/GitHub Models as the provider. LM Studio is a local server
        # whose availability isn't implied by LM_API_KEY presence (it may be
        # offline, and the no-auth setup uses a placeholder value), so it
        # also requires explicit selection.
        if pid in {"copilot", "lmstudio"}:
            continue
        for env_var in pconfig.api_key_env_vars:
            if _core.has_usable_secret(_core.os.getenv(env_var, "")):
                return pid

    # AWS Bedrock — detect via boto3 credential chain (IAM roles, SSO, env vars).
    # This runs after API-key providers so explicit keys always win.
    try:
        from superforecasting_agent.hosting.aws_credentials import has_aws_credentials

        if has_aws_credentials():
            return "bedrock"
    except ImportError:
        pass  # boto3 not installed — skip Bedrock auto-detection

    raise _core.AuthError(
        f"No inference provider configured. Run '{_core._PRIMARY_CLI} model' to choose a "
        "provider and model, or set an API key (OPENROUTER_API_KEY, "
        "OPENAI_API_KEY, etc.) in the runtime .env.",
        code="no_provider_configured",
    )
