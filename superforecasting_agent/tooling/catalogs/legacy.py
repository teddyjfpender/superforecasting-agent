"""Legacy toolset catalog."""

from .core import _CORE_TOOLS

TOOLSETS = {
    'hermes-acp': {
        "description": "Editor integration (VS Code, Zed, JetBrains) — coding-focused tools without messaging, audio, or clarify UI",
        "tools": [
            "web_search", "web_extract",
            "terminal", "process",
            "read_file", "write_file", "patch", "search_files",
            "vision_analyze",
            "skills_list", "skill_view", "skill_manage",
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_scroll", "browser_back",
            "browser_press", "browser_get_images",
            "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
            "todo", "memory",
            "session_search",
            "execute_code", "delegate_task",
        ],
        "includes": []
    },
    'hermes-api-server': {
        "description": "OpenAI-compatible API server — full agent tools accessible via HTTP (no interactive UI tools like clarify or send_message)",
        "tools": [
            # Web
            "web_search", "web_extract",
            # Terminal + process management
            "terminal", "process",
            # File manipulation
            "read_file", "write_file", "patch", "search_files",
            # Vision + image generation
            "vision_analyze", "image_generate",
            # Skills
            "skills_list", "skill_view", "skill_manage",
            # Browser automation
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_scroll", "browser_back",
            "browser_press", "browser_get_images",
            "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
            # Planning & memory
            "todo", "memory",
            # Session history search
            "session_search",
            # Code execution + delegation
            "execute_code", "delegate_task",
            # Cronjob management
            "cronjob",
            # Home Assistant smart home control (gated on HASS_TOKEN via check_fn)
            "ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service",

        ],
        "includes": []
    },
    'hermes-cli': {
        "description": "Full interactive CLI toolset - all default tools plus cronjob management",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-cron': {
        # Mirrors hermes-cli so cron's "default" toolset is the same set of
        # core tools users see interactively — then `hermes tools` filters
        # them down per the platform config. _DEFAULT_OFF_TOOLSETS (moa,
        # homeassistant) are excluded by _get_platform_tools() unless
        # the user explicitly enables them.
        "description": "Default cron toolset - same core tools as the CLI; gated by `superforecasting-agent tools`",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-telegram': {
        "description": "Telegram bot toolset - full access for personal use (terminal has safety checks)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-discord': {
        "description": "Discord bot toolset - full access (terminal has safety checks via dangerous command approval)",
        "tools": _CORE_TOOLS + [
            "discord",
            "discord_admin",
        ],
        "includes": []
    },
    'hermes-whatsapp': {
        "description": "WhatsApp bot toolset - similar to Telegram (personal messaging, more trusted)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-slack': {
        "description": "Slack bot toolset - full access for workspace use (terminal has safety checks)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-signal': {
        "description": "Signal bot toolset - encrypted messaging platform (full access)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-bluebubbles': {
        "description": "BlueBubbles iMessage bot toolset - Apple iMessage via local BlueBubbles server",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-homeassistant': {
        "description": "Home Assistant bot toolset - smart home event monitoring and control",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-email': {
        "description": "Email bot toolset - interact with Superforecasting Agent via email (IMAP/SMTP)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-mattermost': {
        "description": "Mattermost bot toolset - self-hosted team messaging (full access)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-matrix': {
        "description": "Matrix bot toolset - decentralized encrypted messaging (full access)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-dingtalk': {
        "description": "DingTalk bot toolset - enterprise messaging platform (full access)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-feishu': {
        "description": "Feishu/Lark bot toolset - enterprise messaging via Feishu/Lark (full access)",
        "tools": _CORE_TOOLS + [
            "feishu_doc_read",
            "feishu_drive_list_comments",
            "feishu_drive_list_comment_replies",
            "feishu_drive_reply_comment",
            "feishu_drive_add_comment",
        ],
        "includes": []
    },
    'hermes-weixin': {
        "description": "Weixin bot toolset - personal WeChat messaging via iLink (full access)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-qqbot': {
        "description": "QQBot toolset - QQ messaging via Official Bot API v2 (full access)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-wecom': {
        "description": "WeCom bot toolset - enterprise WeChat messaging (full access)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-wecom-callback': {
        "description": "WeCom callback toolset - enterprise self-built app messaging (full access)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-yuanbao': {
        "description": "Yuanbao Bot 元宝消息平台工具集 - 群信息、成员查询、私聊、贴纸表情",
        "tools": _CORE_TOOLS + [
            "yb_query_group_info",
            "yb_query_group_members",
            "yb_send_dm",
            "yb_search_sticker",
            "yb_send_sticker",
        ],
        "module": "tools.yuanbao_tools",
        "includes": []
    },
    'hermes-sms': {
        "description": "SMS bot toolset - interact with Superforecasting Agent via SMS (Twilio)",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-webhook': {
        "description": "Webhook toolset - receive and process external webhook events",
        "tools": _CORE_TOOLS,
        "includes": []
    },
    'hermes-gateway': {
        "description": "Gateway toolset - union of all messaging platform tools",
        "tools": [],
        "includes": ["hermes-telegram", "hermes-discord", "hermes-whatsapp", "hermes-slack", "hermes-signal", "hermes-bluebubbles", "hermes-homeassistant", "hermes-email", "hermes-sms", "hermes-mattermost", "hermes-matrix", "hermes-dingtalk", "hermes-feishu", "hermes-wecom", "hermes-wecom-callback", "hermes-weixin", "hermes-qqbot", "hermes-webhook", "hermes-yuanbao"]
    },
}
