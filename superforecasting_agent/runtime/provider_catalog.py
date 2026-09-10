"""Provider definitions, overlays, aliases, labels, and transport metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

@dataclass(frozen=True)
class ProviderOverlay:
    """Runtime provider metadata layered on top of models.dev."""

    transport: str = "openai_chat"        # openai_chat | anthropic_messages | codex_responses
    is_aggregator: bool = False
    auth_type: str = "api_key"            # api_key | oauth_device_code | oauth_external | external_process
    extra_env_vars: Tuple[str, ...] = ()  # env vars models.dev doesn't list
    base_url_override: str = ""           # override if models.dev URL is wrong/missing
    base_url_env_var: str = ""            # env var for user-custom base URL


PROVIDER_OVERLAYS: Dict[str, ProviderOverlay] = {
    "openrouter": ProviderOverlay(
        transport="openai_chat",
        is_aggregator=True,
        extra_env_vars=("OPENAI_API_KEY",),
        base_url_env_var="OPENROUTER_BASE_URL",
    ),
    "nous": ProviderOverlay(
        transport="openai_chat",
        auth_type="oauth_device_code",
        base_url_override="https://inference-api.nousresearch.com/v1",
    ),
    "openai-codex": ProviderOverlay(
        transport="codex_responses",
        auth_type="oauth_external",
        base_url_override="https://chatgpt.com/backend-api/codex",
    ),
    "openai-api": ProviderOverlay(
        transport="codex_responses",
        base_url_override="https://api.openai.com/v1",
        base_url_env_var="OPENAI_BASE_URL",
    ),
    "xai-oauth": ProviderOverlay(
        transport="codex_responses",
        auth_type="oauth_external",
        base_url_override="https://api.x.ai/v1",
        base_url_env_var="XAI_BASE_URL",
    ),
    "qwen-oauth": ProviderOverlay(
        transport="openai_chat",
        auth_type="oauth_external",
        base_url_override="https://portal.qwen.ai/v1",
        base_url_env_var="SUPERFORECASTING_AGENT_QWEN_BASE_URL",
    ),
    "google-gemini-cli": ProviderOverlay(
        transport="openai_chat",
        auth_type="oauth_external",
        base_url_override="cloudcode-pa://google",
    ),
    "lmstudio": ProviderOverlay(
        transport="openai_chat",
        auth_type="api_key",
        extra_env_vars=("LM_API_KEY",),
        base_url_override="http://127.0.0.1:1234/v1",
        base_url_env_var="LM_BASE_URL",
    ),
    "copilot-acp": ProviderOverlay(
        transport="codex_responses",
        auth_type="external_process",
        base_url_override="acp://copilot",
        base_url_env_var="COPILOT_ACP_BASE_URL",
    ),
    "github-copilot": ProviderOverlay(
        transport="openai_chat",
        extra_env_vars=("COPILOT_GITHUB_TOKEN", "GH_TOKEN"),
    ),
    "anthropic": ProviderOverlay(
        transport="anthropic_messages",
        extra_env_vars=("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"),
    ),
    "zai": ProviderOverlay(
        transport="openai_chat",
        extra_env_vars=("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"),
        base_url_env_var="GLM_BASE_URL",
    ),
    "kimi-for-coding": ProviderOverlay(
        transport="openai_chat",
        base_url_env_var="KIMI_BASE_URL",
    ),
    "stepfun": ProviderOverlay(
        transport="openai_chat",
        extra_env_vars=("STEPFUN_API_KEY",),
        base_url_override="https://api.stepfun.ai/step_plan/v1",
        base_url_env_var="STEPFUN_BASE_URL",
    ),
    "minimax": ProviderOverlay(
        transport="anthropic_messages",
        base_url_env_var="MINIMAX_BASE_URL",
    ),
    "minimax-oauth": ProviderOverlay(
        transport="anthropic_messages",
        auth_type="oauth_external",
        base_url_override="https://api.minimax.io/anthropic",
    ),
    "minimax-cn": ProviderOverlay(
        transport="anthropic_messages",
        base_url_env_var="MINIMAX_CN_BASE_URL",
    ),
    "deepseek": ProviderOverlay(
        transport="openai_chat",
        base_url_env_var="DEEPSEEK_BASE_URL",
    ),
    "alibaba": ProviderOverlay(
        transport="openai_chat",
        base_url_env_var="DASHSCOPE_BASE_URL",
    ),
    "alibaba-coding-plan": ProviderOverlay(
        transport="openai_chat",
        base_url_env_var="ALIBABA_CODING_PLAN_BASE_URL",
    ),
    "vercel": ProviderOverlay(
        transport="openai_chat",
        is_aggregator=True,
    ),
    "opencode": ProviderOverlay(
        transport="openai_chat",
        is_aggregator=True,
        base_url_env_var="OPENCODE_ZEN_BASE_URL",
    ),
    "opencode-go": ProviderOverlay(
        transport="openai_chat",
        is_aggregator=True,
        base_url_env_var="OPENCODE_GO_BASE_URL",
    ),
    "kilo": ProviderOverlay(
        transport="openai_chat",
        is_aggregator=True,
        base_url_env_var="KILOCODE_BASE_URL",
    ),
    "huggingface": ProviderOverlay(
        transport="openai_chat",
        is_aggregator=True,
        base_url_env_var="HF_BASE_URL",
    ),
    "novita": ProviderOverlay(
        transport="openai_chat",
        is_aggregator=True,
        base_url_env_var="NOVITA_BASE_URL",
    ),
    "xai": ProviderOverlay(
        transport="codex_responses",
        base_url_override="https://api.x.ai/v1",
        base_url_env_var="XAI_BASE_URL",
    ),
    "nvidia": ProviderOverlay(
        transport="openai_chat",
        base_url_override="https://integrate.api.nvidia.com/v1",
        base_url_env_var="NVIDIA_BASE_URL",
    ),
    "xiaomi": ProviderOverlay(
        transport="openai_chat",
        base_url_env_var="XIAOMI_BASE_URL",
    ),
    "tencent-tokenhub": ProviderOverlay(
        transport="openai_chat",
        base_url_env_var="TOKENHUB_BASE_URL",
    ),
    "arcee": ProviderOverlay(
        transport="openai_chat",
        base_url_override="https://api.arcee.ai/api/v1",
        base_url_env_var="ARCEE_BASE_URL",
    ),
    "gmi": ProviderOverlay(
        transport="openai_chat",
        extra_env_vars=("GMI_API_KEY",),
        base_url_override="https://api.gmi-serving.com/v1",
        base_url_env_var="GMI_BASE_URL",
    ),
    "ollama-cloud": ProviderOverlay(
        transport="openai_chat",
        base_url_override="https://ollama.com/v1",
        base_url_env_var="OLLAMA_BASE_URL",
    ),
    # Azure Foundry: supports both OpenAI-style and Anthropic-style endpoints.
    # The transport is determined at runtime from config.yaml model.api_mode.
    "azure-foundry": ProviderOverlay(
        transport="openai_chat",  # default; overridden by api_mode in config
        base_url_env_var="AZURE_FOUNDRY_BASE_URL",
    ),
    "bedrock": ProviderOverlay(
        transport="bedrock_converse",
        auth_type="aws_sdk",
    ),
}


@dataclass
class ProviderDef:
    """Complete provider definition — merged from all sources."""

    id: str
    name: str
    transport: str                        # openai_chat | anthropic_messages | codex_responses
    api_key_env_vars: Tuple[str, ...]     # all env vars to check for API key
    base_url: str = ""
    base_url_env_var: str = ""
    is_aggregator: bool = False
    auth_type: str = "api_key"
    doc: str = ""
    source: str = ""                      # "models.dev", "hermes", "user-config"


ALIASES: Dict[str, str] = {
    # openrouter
    "openai": "openrouter",     # bare "openai" → route through aggregator

    # zai
    "glm": "zai",
    "z-ai": "zai",
    "z.ai": "zai",
    "zhipu": "zai",

    # xai
    "x-ai": "xai",
    "x.ai": "xai",
    "grok": "xai",
    "grok-oauth": "xai-oauth",
    "xai-oauth": "xai-oauth",
    "x-ai-oauth": "xai-oauth",
    "xai-grok-oauth": "xai-oauth",

    # nvidia
    "nim": "nvidia",
    "nvidia-nim": "nvidia",
    "build-nvidia": "nvidia",
    "nemotron": "nvidia",

    # kimi-for-coding (models.dev ID)
    "kimi": "kimi-for-coding",
    "kimi-coding": "kimi-for-coding",
    "kimi-coding-cn": "kimi-for-coding",
    "moonshot": "kimi-for-coding",

    # stepfun
    "step": "stepfun",
    "stepfun-coding-plan": "stepfun",

    # minimax-cn
    "minimax-china": "minimax-cn",
    "minimax_cn": "minimax-cn",

    # anthropic
    "claude": "anthropic",
    "claude-code": "anthropic",

    # github-copilot (models.dev ID)
    "copilot": "github-copilot",
    "github": "github-copilot",
    "github-copilot-acp": "copilot-acp",

    # vercel (models.dev ID for AI Gateway)
    "ai-gateway": "vercel",
    "aigateway": "vercel",
    "vercel-ai-gateway": "vercel",

    # opencode (models.dev ID for OpenCode Zen)
    "opencode-zen": "opencode",
    "zen": "opencode",

    # opencode-go
    "go": "opencode-go",
    "opencode-go-sub": "opencode-go",

    # kilo (models.dev ID for KiloCode)
    "kilocode": "kilo",
    "kilo-code": "kilo",
    "kilo-gateway": "kilo",

    # deepseek
    "deep-seek": "deepseek",

    # alibaba
    "dashscope": "alibaba",
    "aliyun": "alibaba",
    "qwen": "alibaba",
    "alibaba-cloud": "alibaba",
    "alibaba_coding": "alibaba-coding-plan",
    "alibaba-coding": "alibaba-coding-plan",
    "alibaba_coding_plan": "alibaba-coding-plan",

    # google-gemini-cli (OAuth + Code Assist)
    "gemini-cli": "google-gemini-cli",
    "gemini-oauth": "google-gemini-cli",


    # huggingface
    "hf": "huggingface",
    "hugging-face": "huggingface",
    "huggingface-hub": "huggingface",

    # novita
    "novita-ai": "novita",
    "novitaai": "novita",

    # xiaomi
    "mimo": "xiaomi",
    "xiaomi-mimo": "xiaomi",

    # tencent
    "tencent": "tencent-tokenhub",
    "tokenhub": "tencent-tokenhub",
    "tencent-cloud": "tencent-tokenhub",
    "tencentmaas": "tencent-tokenhub",

    # bedrock
    "aws": "bedrock",
    "aws-bedrock": "bedrock",
    "amazon-bedrock": "bedrock",
    "amazon": "bedrock",

    # arcee
    "arcee-ai": "arcee",
    "arceeai": "arcee",

    # gmi
    "gmi-cloud": "gmi",
    "gmicloud": "gmi",

    # Local server aliases → virtual "local" concept (resolved via user config)
    "lmstudio": "lmstudio",
    "lm-studio": "lmstudio",
    "lm_studio": "lmstudio",
    "ollama": "custom",  # bare "ollama" = local; use "ollama-cloud" for cloud
    "vllm": "local",
    "llamacpp": "local",
    "llama.cpp": "local",
    "llama-cpp": "local",
}


_LABEL_OVERRIDES: Dict[str, str] = {
    "nous": "Nous Portal",
    "openai-codex": "OpenAI Codex",
    "copilot-acp": "GitHub Copilot ACP",
    "stepfun": "StepFun Step Plan",
    "xiaomi": "Xiaomi MiMo",
    "gmi": "GMI Cloud",
    "tencent-tokenhub": "Tencent TokenHub",
    "lmstudio": "LM Studio",
    "local": "Local endpoint",
    "bedrock": "AWS Bedrock",
    "ollama-cloud": "Ollama Cloud",
}


TRANSPORT_TO_API_MODE: Dict[str, str] = {
    "openai_chat": "chat_completions",
    "anthropic_messages": "anthropic_messages",
    "codex_responses": "codex_responses",
    "bedrock_converse": "bedrock_converse",
}
