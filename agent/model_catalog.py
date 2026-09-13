"""Offline model catalogs shared by forecast selection and product adapters."""

from __future__ import annotations

# Fallback OpenRouter snapshot used when the live catalog is unavailable.
# (model_id, display description shown in menus)
OPENROUTER_MODELS: list[tuple[str, str]] = [
    ("anthropic/claude-opus-4.7", ""),
    ("anthropic/claude-opus-4.6", ""),
    ("anthropic/claude-sonnet-4.6", ""),
    ("moonshotai/kimi-k2.6", "recommended"),
    (
        "openrouter/pareto-code",
        "auto-routes to cheapest coder meeting openrouter.min_coding_score",
    ),
    ("qwen/qwen3.6-plus", ""),
    ("anthropic/claude-haiku-4.5", ""),
    ("openai/gpt-5.5", ""),
    ("openai/gpt-5.5-pro", ""),
    ("openai/gpt-5.4-mini", ""),
    ("openai/gpt-5.4-nano", ""),
    ("openai/gpt-5.3-codex", ""),
    ("xiaomi/mimo-v2.5-pro", ""),
    ("tencent/hy3-preview", ""),
    ("google/gemini-3-pro-image-preview", ""),
    ("google/gemini-3-flash-preview", ""),
    ("google/gemini-3.1-pro-preview", ""),
    ("google/gemini-3.1-flash-lite-preview", ""),
    ("qwen/qwen3.6-35b-a3b", ""),
    ("stepfun/step-3.5-flash", ""),
    ("minimax/minimax-m2.7", ""),
    ("z-ai/glm-5.1", ""),
    ("x-ai/grok-4.20", ""),
    ("x-ai/grok-4.3", ""),
    ("nvidia/nemotron-3-super-120b-a12b", ""),
    ("deepseek/deepseek-v4-pro", ""),
    # Free tier
    ("openrouter/elephant-alpha", "free"),
    ("openrouter/owl-alpha", "free"),
    ("tencent/hy3-preview:free", "free"),
    ("nvidia/nemotron-3-super-120b-a12b:free", "free"),
    ("inclusionai/ring-2.6-1t:free", "free"),
]


# Fallback Vercel AI Gateway snapshot used when the live catalog is unavailable.
# OSS / open-weight models prioritized first, then closed-source by family.
# Slugs match Vercel's actual /v1/models catalog (e.g. alibaba/ for Qwen,
# zai/ and xai/ without hyphens).
VERCEL_AI_GATEWAY_MODELS: list[tuple[str, str]] = [
    ("moonshotai/kimi-k2.6", "recommended"),
    ("alibaba/qwen3.6-plus", ""),
    ("zai/glm-5.1", ""),
    ("minimax/minimax-m2.7", ""),
    ("anthropic/claude-sonnet-4.6", ""),
    ("anthropic/claude-opus-4.7", ""),
    ("anthropic/claude-opus-4.6", ""),
    ("anthropic/claude-haiku-4.5", ""),
    ("openai/gpt-5.4", ""),
    ("openai/gpt-5.4-mini", ""),
    ("openai/gpt-5.3-codex", ""),
    ("google/gemini-3.1-pro-preview", ""),
    ("google/gemini-3-flash", ""),
    ("google/gemini-3.1-flash-lite-preview", ""),
    ("xai/grok-4.20-reasoning", ""),
]


def _codex_curated_models() -> list[str]:
    """Derive the openai-codex curated list from codex_models.py.

    Single source of truth: DEFAULT_CODEX_MODELS + forward-compat synthesis.
    This keeps the gateway /model picker in sync with the CLI
    `superforecasting-agent model` flow without maintaining a separate static
    list.
    """
    from superforecasting_agent.configuration.codex_catalog import (
        DEFAULT_CODEX_MODELS,
        _add_forward_compat_models,
    )

    return _add_forward_compat_models(list(DEFAULT_CODEX_MODELS))


# Static fallback for xAI when the models.dev disk cache is empty (fresh
# install, offline first run, etc.). Mirrors the xAI-direct model IDs from
# $HERMES_HOME/models_dev_cache.json as of 2026-04-28. Whenever xAI renames
# or retires a model, the disk cache picks it up on the next refresh and the
# fallback here only matters until that refresh lands.
#
# Models retired by xAI on May 15, 2026 are excluded — see
# https://docs.x.ai/developers/migration/may-15-retirement
# (grok-4, grok-4-0709, grok-4-fast{,-reasoning,-non-reasoning},
#  grok-4-1-fast{,-reasoning,-non-reasoning}, grok-code-fast-1 → grok-4.3).
_XAI_STATIC_FALLBACK: list[str] = [
    "grok-4.3",
    "grok-4.20-0309-reasoning",
    "grok-4.20-0309-non-reasoning",
    "grok-4.20-multi-agent-0309",
]


_XAI_TOP_MODEL = "grok-4.3"


def _xai_promote_top(ids: list[str]) -> list[str]:
    """Pin the headline xAI model to the top of the curated list."""
    if _XAI_TOP_MODEL in ids:
        return [_XAI_TOP_MODEL] + [m for m in ids if m != _XAI_TOP_MODEL]
    return ids


def _xai_curated_models() -> list[str]:
    """Derive the xAI-direct curated list from models.dev disk cache.

    Reads $HERMES_HOME/models_dev_cache.json directly (no network) so this
    runs at import time without blocking. Falls back to ``_XAI_STATIC_FALLBACK``
    when the cache is empty or unreadable. The CLI refreshes the cache from
    https://models.dev/api.json on normal use, so this list self-heals as
    xAI renames models.

    Mirrors ``_codex_curated_models()``'s role for openai-codex.
    """
    try:
        from agent.models_dev import _load_disk_cache

        data = _load_disk_cache()
        xai = data.get("xai") if isinstance(data, dict) else None
        models = xai.get("models") if isinstance(xai, dict) else None
        if isinstance(models, dict) and models:
            ids = [mid for mid in models.keys() if isinstance(mid, str)]
            if ids:
                return _xai_promote_top(sorted(ids))
    except Exception:
        # Any failure (missing file, malformed JSON, import error)
        # falls through to the static list.
        pass
    return list(_XAI_STATIC_FALLBACK)


_PROVIDER_MODELS: dict[str, list[str]] = {
    "nous": [
        "anthropic/claude-opus-4.7",
        "anthropic/claude-opus-4.6",
        "anthropic/claude-sonnet-4.6",
        "moonshotai/kimi-k2.6",
        "qwen/qwen3.6-plus",
        "anthropic/claude-haiku-4.5",
        "openai/gpt-5.5",
        "openai/gpt-5.5-pro",
        "openai/gpt-5.4-mini",
        "openai/gpt-5.4-nano",
        "openai/gpt-5.3-codex",
        "xiaomi/mimo-v2.5-pro",
        "tencent/hy3-preview",
        "google/gemini-3-pro-preview",
        "google/gemini-3-flash-preview",
        "google/gemini-3.1-pro-preview",
        "google/gemini-3.1-flash-lite-preview",
        "qwen/qwen3.6-35b-a3b",
        "stepfun/step-3.5-flash",
        "minimax/minimax-m2.7",
        "z-ai/glm-5.1",
        "x-ai/grok-4.3",
        "nvidia/nemotron-3-super-120b-a12b",
        "deepseek/deepseek-v4-pro",
    ],
    # Native OpenAI Chat Completions (api.openai.com). Used by /model counts and
    # provider_model_ids fallback when /v1/models is unavailable.
    "openai": [
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5-mini",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
    ],
    "openai-api": [
        # Fallback only — provider_model_ids() prefers a live /v1/models fetch
        # when OPENAI_API_KEY is set. Mirrors the curated "openai" table.
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5-mini",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
    ],
    "openai-codex": _codex_curated_models(),
    "xai-oauth": _xai_curated_models(),
    "copilot-acp": [
        "copilot-acp",
    ],
    "copilot": [
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5-mini",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
        "claude-sonnet-4.6",
        "claude-sonnet-4",
        "claude-sonnet-4.5",
        "claude-haiku-4.5",
        "gemini-3.1-pro-preview",
        "gemini-3-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
    ],
    "gemini": [
        "gemini-3.1-pro-preview",
        "gemini-3-pro-preview",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview",
    ],
    "google-gemini-cli": [
        "gemini-3.1-pro-preview",
        "gemini-3-pro-preview",
        "gemini-3-flash-preview",
    ],
    "zai": [
        "glm-5.1",
        "glm-5",
        "glm-5v-turbo",
        "glm-5-turbo",
        "glm-4.7",
        "glm-4.5",
        "glm-4.5-flash",
    ],
    "xai": _xai_curated_models(),
    "nvidia": [
        # NVIDIA flagship reasoning models
        "nvidia/nemotron-3-super-120b-a12b",
        "nvidia/nemotron-3-nano-30b-a3b",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        # Third-party agentic models hosted on build.nvidia.com
        # (map to OpenRouter defaults — users get familiar picks on NIM)
        "qwen/qwen3.5-397b-a17b",
        "deepseek-ai/deepseek-v3.2",
        "moonshotai/kimi-k2.6",
        "minimaxai/minimax-m2.5",
        "z-ai/glm5",
        "openai/gpt-oss-120b",
    ],
    "kimi-coding": [
        "kimi-k2.6",
        "kimi-k2.5",
        "kimi-for-coding",
        "kimi-k2-thinking",
        "kimi-k2-thinking-turbo",
        "kimi-k2-turbo-preview",
        "kimi-k2-0905-preview",
    ],
    "kimi-coding-cn": [
        "kimi-k2.6",
        "kimi-k2.5",
        "kimi-k2-thinking",
        "kimi-k2-turbo-preview",
        "kimi-k2-0905-preview",
    ],
    "stepfun": [
        "step-3.5-flash",
        "step-3.5-flash-2603",
    ],
    "moonshot": [
        "kimi-k2.6",
        "kimi-k2.5",
        "kimi-k2-thinking",
        "kimi-k2-turbo-preview",
        "kimi-k2-0905-preview",
    ],
    "minimax": [
        "MiniMax-M2.7",
        "MiniMax-M2.5",
        "MiniMax-M2.1",
        "MiniMax-M2",
    ],
    "minimax-oauth": [
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
    ],
    "minimax-cn": [
        "MiniMax-M2.7",
        "MiniMax-M2.5",
        "MiniMax-M2.1",
        "MiniMax-M2",
    ],
    "anthropic": [
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-opus-4-5-20251101",
        "claude-sonnet-4-5-20250929",
        "claude-opus-4-20250514",
        "claude-sonnet-4-20250514",
        "claude-haiku-4-5-20251001",
    ],
    "deepseek": [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "xiaomi": [
        "mimo-v2.5-pro",
        "mimo-v2.5",
        "mimo-v2-pro",
        "mimo-v2-omni",
        "mimo-v2-flash",
    ],
    "tencent-tokenhub": [
        "hy3-preview",
    ],
    "arcee": [
        "trinity-large-thinking",
        "trinity-large-preview",
        "trinity-mini",
    ],
    "gmi": [
        "zai-org/GLM-5.1-FP8",
        "deepseek-ai/DeepSeek-V3.2",
        "moonshotai/Kimi-K2.5",
        "google/gemini-3.1-flash-lite-preview",
        "anthropic/claude-sonnet-4.6",
        "openai/gpt-5.4",
    ],
    "opencode-zen": [
        "kimi-k2.5",
        "gpt-5.4-pro",
        "gpt-5.4",
        "gpt-5.3-codex",
        "gpt-5.2",
        "gpt-5.2-codex",
        "gpt-5.1",
        "gpt-5.1-codex",
        "gpt-5.1-codex-max",
        "gpt-5.1-codex-mini",
        "gpt-5",
        "gpt-5-codex",
        "gpt-5-nano",
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-opus-4-1",
        "claude-sonnet-4-6",
        "claude-sonnet-4-5",
        "claude-sonnet-4",
        "claude-haiku-4-5",
        "claude-3-5-haiku",
        "gemini-3.1-pro",
        "gemini-3-pro",
        "gemini-3-flash",
        "minimax-m2.7",
        "minimax-m2.5",
        "minimax-m2.5-free",
        "minimax-m2.1",
        "glm-5",
        "glm-4.7",
        "glm-4.6",
        "kimi-k2-thinking",
        "kimi-k2",
        "qwen3-coder",
        "big-pickle",
    ],
    "opencode-go": [
        "kimi-k2.6",
        "kimi-k2.5",
        "glm-5.1",
        "glm-5",
        "mimo-v2.5-pro",
        "mimo-v2.5",
        "mimo-v2-pro",
        "mimo-v2-omni",
        "minimax-m2.7",
        "minimax-m2.5",
        "qwen3.6-plus",
        "qwen3.5-plus",
    ],
    "kilocode": [
        "anthropic/claude-opus-4.6",
        "anthropic/claude-sonnet-4.6",
        "openai/gpt-5.4",
        "google/gemini-3-pro-preview",
        "google/gemini-3-flash-preview",
    ],
    # Alibaba DashScope Coding platform (coding-intl) — default endpoint.
    # Supports Qwen models + third-party providers (GLM, Kimi, MiniMax).
    # Users with classic DashScope keys should override DASHSCOPE_BASE_URL
    # to https://dashscope-intl.aliyuncs.com/compatible-mode/v1 (OpenAI-compat)
    # or https://dashscope-intl.aliyuncs.com/apps/anthropic (Anthropic-compat).
    "alibaba": [
        "qwen3.6-plus",
        "kimi-k2.5",
        "qwen3.5-plus",
        "qwen3-coder-plus",
        "qwen3-coder-next",
        # Third-party models available on coding-intl
        "glm-5",
        "glm-4.7",
        "MiniMax-M2.5",
    ],
    # Alibaba Coding Plan — same platform as alibaba (DashScope coding-intl),
    # separate provider ID with its own base_url_env_var.
    "alibaba-coding-plan": [
        "qwen3.6-plus",
        "qwen3.5-plus",
        "qwen3-coder-plus",
        "qwen3-coder-next",
        "kimi-k2.5",
        "glm-5",
        "glm-4.7",
        "MiniMax-M2.5",
    ],
    # Curated HF model list — only agentic models that map to OpenRouter defaults.
    "huggingface": [
        "moonshotai/Kimi-K2.5",
        "Qwen/Qwen3.5-397B-A17B",
        "Qwen/Qwen3.5-35B-A3B",
        "deepseek-ai/DeepSeek-V3.2",
        "MiniMaxAI/MiniMax-M2.5",
        "zai-org/GLM-5",
        "XiaomiMiMo/MiMo-V2-Flash",
        "moonshotai/Kimi-K2-Thinking",
        "moonshotai/Kimi-K2.6",
    ],
    # AWS Bedrock — static fallback list used when dynamic discovery is
    # unavailable (no boto3, no credentials, or API error).  The agent
    # prefers live discovery via ListFoundationModels + ListInferenceProfiles.
    # Use inference profile IDs (us.*) since most models require them.
    "bedrock": [
        "us.anthropic.claude-sonnet-4-6",
        "us.anthropic.claude-opus-4-6-v1",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "us.amazon.nova-pro-v1:0",
        "us.amazon.nova-lite-v1:0",
        "us.amazon.nova-micro-v1:0",
        "deepseek.v3.2",
        "us.meta.llama4-maverick-17b-instruct-v1:0",
        "us.meta.llama4-scout-17b-instruct-v1:0",
    ],
    # Azure Foundry: user-provided endpoint and model.
    # Empty list because models depend on the endpoint configuration.
    "azure-foundry": [],
    "novita": [
        "moonshotai/kimi-k2.5",
        "minimax/minimax-m2.7",
        "zai-org/glm-5",
        "deepseek/deepseek-v3-0324",
        "deepseek/deepseek-r1-0528",
        "qwen/qwen3-235b-a22b-fp8",
    ],
}

# Vercel AI Gateway: derive the bare-model-id catalog from the curated
# ``VERCEL_AI_GATEWAY_MODELS`` snapshot so both the picker (tuples with descriptions)
# and the static fallback catalog (bare ids) stay in sync from a single
# source of truth.
_PROVIDER_MODELS["ai-gateway"] = [mid for mid, _ in VERCEL_AI_GATEWAY_MODELS]


def get_default_model_for_provider(provider: str) -> str:
    """Return the default model for a provider, or empty string if unknown.

    Uses the first entry in _PROVIDER_MODELS as the default.  This is the
    model a user would be offered first in the ``superforecasting-agent model``
    picker.

    Used as a fallback when the user has configured a provider but never
    selected a model (e.g. ``superforecasting-agent auth add openai-codex``
    without ``superforecasting-agent model``).
    """
    models = _PROVIDER_MODELS.get(provider, [])
    return models[0] if models else ""
