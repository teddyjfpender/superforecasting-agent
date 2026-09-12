"""Forecast toolset catalog."""

TOOLSETS = {
    "forecast-desk": {
        "description": "Default forecasting desk tools for research, modeling, ledger writes, and scheduled review",
        "tools": [],
        "includes": [
            "forecasting",
            "web",
            "browser",
            "terminal",
            "file",
            "code_execution",
            "todo",
            "clarify",
            "cronjob",
            # Lets the desk fan research legwork out to subagents — synchronously,
            # or in the background (delegate_task(background=true)) so the user
            # keeps interacting while it runs and the result re-enters the chat
            # when ready. The structured ensemble still comes from the panel /
            # quorum (see forecasting/protocol.py), not raw delegations.
            "delegation",
        ],
    },
    "market-models": {
        "description": "Agentic quant-research for Market Models: research data, compute deterministic stats/models, and emit a structured presentation",
        # Deliberately excludes approval-gated tools (terminal/browser/code_execution):
        # the build runs as a HEADLESS background agent with no approval callback, so
        # those would stall or be denied. All math goes through the pure market_compute
        # tool; research uses read-only data (forecasting) + web. Keeps builds robust.
        "tools": ["market_compute", "emit_market_presentation", "read_desk_forecast"],
        "includes": [
            "forecasting",
            "web",
            "todo",
            "delegation",
        ],
    },
    "market-models-interactive": {
        "description": "Market Models with the sandboxed code_execution + browser tools added, for richer custom quant pipelines and multi-step web research",
        # Opt-in (HERMES_MARKET_INTERACTIVE=1) variant. Adds code_execution (a
        # custom-Python sandbox beyond the fixed market_compute menu) + browser
        # (multi-step research). It runs with a thread-local auto-approve for the
        # SANDBOXED tools only (no host terminal / file-write here), so it does not
        # stall headless. Default builds use the plain "market-models" preset.
        "tools": ["market_compute", "emit_market_presentation", "read_desk_forecast"],
        "includes": [
            "forecasting",
            "web",
            "browser",
            "code_execution",
            "todo",
            "delegation",
            "clarify",
        ],
    },
    "forecast-messaging": {
        "description": "Forecast-scoped messaging runtime tools for platform conversations and review alerts",
        "tools": [],
        "includes": [
            "forecasting",
            "web",
            "browser",
            "terminal",
            "file",
            "code_execution",
            "todo",
            "clarify",
            "messaging",
            "delegation",
        ],
    },
    "forecast-api-server": {
        "description": "Forecast-scoped OpenAI-compatible HTTP runtime preset",
        "tools": [],
        "includes": [
            "forecasting",
            "web",
            "browser",
            "terminal",
            "file",
            "code_execution",
            "todo",
            "delegation",
        ],
    },
    "forecast-cron": {
        "description": "Forecast-scoped cron runtime tools for scheduled research, evidence checks, and delivery",
        "tools": [],
        "includes": [
            "forecasting",
            "web",
            "terminal",
            "file",
            "code_execution",
            "todo",
            "messaging",
            "delegation",
        ],
    },
    "forecast-telegram": {
        "description": "Forecast-scoped Telegram runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-discord": {
        "description": "Forecast-scoped Discord runtime preset with read/participation tools",
        "tools": [],
        "includes": ["forecast-messaging", "discord"],
    },
    "forecast-whatsapp": {
        "description": "Forecast-scoped WhatsApp runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-slack": {
        "description": "Forecast-scoped Slack runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-signal": {
        "description": "Forecast-scoped Signal runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-bluebubbles": {
        "description": "Forecast-scoped BlueBubbles runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-homeassistant": {
        "description": "Forecast-scoped Home Assistant conversation preset without smart-home control tools by default",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-email": {
        "description": "Forecast-scoped email runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-mattermost": {
        "description": "Forecast-scoped Mattermost runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-matrix": {
        "description": "Forecast-scoped Matrix runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-dingtalk": {
        "description": "Forecast-scoped DingTalk runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-feishu": {
        "description": "Forecast-scoped Feishu/Lark runtime preset with document-read support",
        "tools": [],
        "includes": ["forecast-messaging", "feishu_doc"],
    },
    "forecast-weixin": {
        "description": "Forecast-scoped Weixin runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-qqbot": {
        "description": "Forecast-scoped QQBot runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-wecom": {
        "description": "Forecast-scoped WeCom runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-wecom-callback": {
        "description": "Forecast-scoped WeCom callback runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-yuanbao": {
        "description": "Forecast-scoped Yuanbao runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-sms": {
        "description": "Forecast-scoped SMS runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
    "forecast-webhook": {
        "description": "Forecast-scoped webhook runtime preset",
        "tools": [],
        "includes": ["forecast-messaging"],
    },
}
