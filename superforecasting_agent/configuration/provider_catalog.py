"""Provider identities shared by configuration, model pickers and forecasting."""

from __future__ import annotations

from typing import NamedTuple

from superforecasting_agent.configuration.providers import PROVIDER_ALIASES


class ProviderEntry(NamedTuple):
    slug: str
    label: str
    tui_desc: str  # detailed description for the model-picker TUI


CANONICAL_PROVIDERS: list[ProviderEntry] = [
    ProviderEntry("nous", "Nous Portal", "Nous Portal (Nous Research subscription)"),
    ProviderEntry("openrouter", "OpenRouter", "OpenRouter (100+ models, pay-per-use)"),
    ProviderEntry(
        "novita",
        "NovitaAI",
        "NovitaAI (AI-native cloud: Model API, Agent Sandbox, GPU Cloud)",
    ),
    ProviderEntry(
        "lmstudio",
        "LM Studio",
        "LM Studio (local desktop app with built-in model server)",
    ),
    ProviderEntry(
        "anthropic", "Anthropic", "Anthropic (Claude models — API key or Claude Code)"
    ),
    ProviderEntry(
        "openai-codex", "OpenAI OAuth (ChatGPT)", "OpenAI OAuth (ChatGPT subscription)"
    ),
    ProviderEntry("openai-api", "OpenAI API", "OpenAI API (api.openai.com, API key)"),
    ProviderEntry(
        "alibaba", "Qwen Cloud", "Qwen Cloud / DashScope Coding (Qwen + multi-provider)"
    ),
    ProviderEntry(
        "xai-oauth",
        "xAI Grok OAuth (SuperGrok Subscription)",
        "xAI Grok OAuth (SuperGrok Subscription)",
    ),
    ProviderEntry(
        "xiaomi",
        "Xiaomi MiMo",
        "Xiaomi MiMo (MiMo-V2.5 and V2 models — pro, omni, flash)",
    ),
    ProviderEntry(
        "tencent-tokenhub",
        "Tencent TokenHub",
        "Tencent TokenHub (Hy3 Preview — direct API via tokenhub.tencentmaas.com)",
    ),
    ProviderEntry(
        "nvidia",
        "NVIDIA NIM",
        "NVIDIA NIM (Nemotron models — build.nvidia.com or local NIM)",
    ),
    ProviderEntry(
        "copilot",
        "GitHub Copilot",
        "GitHub Copilot (uses GITHUB_TOKEN or gh auth token)",
    ),
    ProviderEntry(
        "copilot-acp",
        "GitHub Copilot ACP",
        "GitHub Copilot ACP (spawns `copilot --acp --stdio`)",
    ),
    ProviderEntry(
        "huggingface",
        "Hugging Face",
        "Hugging Face Inference Providers (20+ open models)",
    ),
    ProviderEntry(
        "gemini",
        "Google AI Studio",
        "Google AI Studio (Gemini models — native Gemini API)",
    ),
    ProviderEntry(
        "google-gemini-cli",
        "Google Gemini (OAuth)",
        "Google Gemini via OAuth + Code Assist (free tier supported; no API key needed)",
    ),
    ProviderEntry(
        "deepseek", "DeepSeek", "DeepSeek (DeepSeek-V3, R1, coder — direct API)"
    ),
    ProviderEntry("xai", "xAI", "xAI (Grok models — direct API)"),
    ProviderEntry("zai", "Z.AI / GLM", "Z.AI / GLM (Zhipu AI direct API)"),
    ProviderEntry(
        "kimi-coding",
        "Kimi / Kimi Coding Plan",
        "Kimi Coding Plan (api.kimi.com) & Moonshot API",
    ),
    ProviderEntry(
        "kimi-coding-cn",
        "Kimi / Moonshot (China)",
        "Kimi / Moonshot China (Moonshot CN direct API)",
    ),
    ProviderEntry(
        "stepfun",
        "StepFun Step Plan",
        "StepFun Step Plan (agent/coding models via Step Plan API)",
    ),
    ProviderEntry("minimax", "MiniMax", "MiniMax (global direct API)"),
    ProviderEntry(
        "minimax-oauth",
        "MiniMax (OAuth)",
        "MiniMax via OAuth browser login (Coding Plan, minimax.io)",
    ),
    ProviderEntry(
        "minimax-cn", "MiniMax (China)", "MiniMax China (domestic direct API)"
    ),
    ProviderEntry(
        "ollama-cloud",
        "Ollama Cloud",
        "Ollama Cloud (cloud-hosted open models — ollama.com)",
    ),
    ProviderEntry("arcee", "Arcee AI", "Arcee AI (Trinity models — direct API)"),
    ProviderEntry("gmi", "GMI Cloud", "GMI Cloud (multi-model direct API)"),
    ProviderEntry("kilocode", "Kilo Code", "Kilo Code (Kilo Gateway API)"),
    ProviderEntry(
        "opencode-zen",
        "OpenCode Zen",
        "OpenCode Zen (35+ curated models, pay-as-you-go)",
    ),
    ProviderEntry(
        "opencode-go",
        "OpenCode Go",
        "OpenCode Go (open models, $10/month subscription)",
    ),
    ProviderEntry(
        "bedrock",
        "AWS Bedrock",
        "AWS Bedrock (Claude, Nova, Llama, DeepSeek — IAM or API key)",
    ),
    ProviderEntry(
        "azure-foundry",
        "Azure Foundry",
        "Azure Foundry (OpenAI-style or Anthropic-style endpoint — your Azure AI deployment)",
    ),
    ProviderEntry("ai-gateway", "Vercel AI Gateway", "Vercel AI Gateway"),
    ProviderEntry(
        "qwen-oauth", "Qwen OAuth (Portal)", "Qwen OAuth (reuses local Qwen CLI login)"
    ),
]

# Auto-extend CANONICAL_PROVIDERS with any provider registered in providers/
# that is not already in the list above.  Adding plugins/model-providers/<name>/
# is sufficient to expose a new provider in the model picker, /model, and all
# downstream consumers — no edits to this file needed.
_canonical_slugs = {p.slug for p in CANONICAL_PROVIDERS}
try:
    from providers import list_providers as _list_providers_for_canonical

    for _pp in _list_providers_for_canonical():
        if _pp.name in _canonical_slugs:
            continue
        if _pp.auth_type in {
            "oauth_device_code",
            "oauth_external",
            "external_process",
            "aws_sdk",
            "copilot",
        }:
            continue  # non-api-key flows need bespoke picker UX; skip auto-inject
        _label = _pp.display_name or _pp.name
        _desc = _pp.description or f"{_label} (direct API)"
        CANONICAL_PROVIDERS.append(ProviderEntry(_pp.name, _label, _desc))
        _canonical_slugs.add(_pp.name)
except Exception:
    pass

# Derived dicts — used throughout the codebase
PROVIDER_LABELS = {p.slug: p.label for p in CANONICAL_PROVIDERS}
PROVIDER_LABELS["custom"] = "Custom endpoint"  # special case: not a named provider


KNOWN_PROVIDER_NAMES: set[str] = (
    set(PROVIDER_LABELS) | set(PROVIDER_ALIASES) | {"openrouter", "custom"}
)
