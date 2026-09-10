"""Aliases toolset catalog."""

TOOLSETS = {
    'forecast-cli': {
        "description": "Fork-native alias for the inherited full interactive runtime preset; prefer forecast-desk for normal forecasting work",
        "tools": [],
        "includes": ["hermes-cli"],
    },
    'forecast-acp': {
        "description": "Fork-native alias for the inherited ACP editor-integration preset",
        "tools": [],
        "includes": ["hermes-acp"],
    },
    'forecast-gateway': {
        "description": "Fork-native aggregate of forecast-scoped messaging platform presets",
        "tools": [],
        "includes": [
            "forecast-telegram", "forecast-discord", "forecast-whatsapp",
            "forecast-slack", "forecast-signal", "forecast-bluebubbles",
            "forecast-homeassistant", "forecast-email", "forecast-sms",
            "forecast-mattermost", "forecast-matrix", "forecast-dingtalk",
            "forecast-feishu", "forecast-wecom", "forecast-wecom-callback",
            "forecast-weixin", "forecast-qqbot", "forecast-webhook",
            "forecast-yuanbao",
        ],
    },
}
