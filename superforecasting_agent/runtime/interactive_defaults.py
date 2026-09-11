"""Fresh default values for the interactive CLI configuration loader."""


def default_cli_config():
    from copy import deepcopy

    from superforecasting_agent.runtime.config import DEFAULT_CONFIG

    return {
        "model": {
            "default": "",
            "base_url": "",
            "provider": "auto",
        },
        "terminal": {
            "env_type": "local",
            "cwd": ".",  # "." is resolved to os.getcwd() at runtime
            "timeout": 60,
            "lifetime_seconds": 300,
            "docker_image": "nikolaik/python-nodejs:python3.11-nodejs20",
            "docker_forward_env": [],
            "singularity_image": "docker://nikolaik/python-nodejs:python3.11-nodejs20",
            "modal_image": "nikolaik/python-nodejs:python3.11-nodejs20",
            "daytona_image": "nikolaik/python-nodejs:python3.11-nodejs20",
            "docker_volumes": [],  # host:container volume mounts for Docker backend
            "docker_mount_cwd_to_workspace": False,  # explicit opt-in only; default off for sandbox isolation
        },
        "browser": {
            "inactivity_timeout": 120,  # Auto-cleanup inactive browser sessions after 2 min
            "record_sessions": False,  # Auto-record browser sessions as WebM videos
            "engine": "auto",  # Browser engine: auto (Chrome), lightpanda, chrome
        },
        "compression": {
            "enabled": True,      # Auto-compress when approaching context limit
            "threshold": 0.50,    # Compress at 50% of model's context limit
        },
        "agent": {
            "max_turns": 200,  # Soft cap per turn; a breach checkpoints + continues, not a hard stop
            "verbose": False,
            "system_prompt": "",
            "prefill_messages_file": "",
            "reasoning_effort": "",
            "service_tier": "",
            "personalities": {
                "forecaster": "You are a disciplined probabilistic forecaster. State probabilities, uncertainty, key evidence, base rates, assumptions, and what would change your mind.",
                "concise": "You are a concise forecasting desk operator. Keep responses brief, quantify when possible, and separate facts from judgments.",
                "technical": "You are a quantitative forecasting researcher. Use careful decomposition, reference classes, simple models, sensitivity checks, and calibration-aware reasoning.",
                "research": "You are an evidence-focused research analyst. Prioritize timestamped sources, source reliability, claim type, and gaps in the evidence record.",
                "skeptical": "You are a skeptical forecast reviewer. Stress-test assumptions, ambiguity, incentives, data quality, and alternative explanations before updating probabilities.",
                "calibration": "You are a calibration coach. Compare confidence to historical error patterns, call out overconfidence, and recommend explicit update rules.",
                "teacher": "You are a forecasting teacher. Explain concepts clearly with examples while preserving the forecast desk's probability discipline.",
                "creative": "You are a hypothesis generator for forecast work. Suggest non-obvious scenarios, mechanisms, reference classes, and indicators without overstating confidence.",
                "executive": "You are a decision-support forecaster. Summarize probabilities, deltas, drivers, deadlines, and action-relevant caveats for a busy operator.",
            },
        },

        "display": {
            "compact": False,
            "resume_display": "full",
            "show_reasoning": False,
            "streaming": True,
            "busy_input_mode": "interrupt",
            "persistent_output": True,
            "persistent_output_max_lines": 200,

            "skin": "forecast",
        },
        "clarify": {
            "timeout": 120,  # Seconds to wait for a clarify answer before auto-proceeding
        },
        "code_execution": {
            "timeout": 300,    # Max seconds a sandbox script can run before being killed (5 min)
            "max_tool_calls": 50,  # Max RPC tool calls per execution
        },
        "auxiliary": {
            "vision": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
            },
            "web_extract": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
            },
        },
        "delegation": deepcopy(DEFAULT_CONFIG["delegation"]),
        "onboarding": {
            # First-touch hint flags (see agent/onboarding.py).  Each hint is
            # shown once per install then latched here.
            "seen": {},
        },
        # Keep the classic CLI's local defaults aligned with DEFAULT_CONFIG;
        # user config still deep-merges below.
        "collaboration": {
            "enabled": False,
            "github": {
                "enabled": False,
                "api_url": "https://api.github.com",
                "upload_url": "https://uploads.github.com",
                "app_id": "",
                "app_slug": "",
                "client_id": "",
                "public_base_url": "",
                "installation_begin_path": "/api/install/github/begin",
                "installation_callback_path": "/api/install/github/callback",
                "installation_state_ttl_seconds": 600,
                "oauth_callback_path": "/api/oauth/github/callback",
                "oauth_state_ttl_seconds": 600,
                "api_version": "2026-03-10",
                "webhook_path": "/api/webhooks/github",
            },
            "repository": {
                "slug": "",
                "workspace_id": "",
                "default_branch": "main",
            },
            "review": {
                "materiality_threshold": 0.10,
                "medium_required_humans": 1,
                "high_required_humans": 2,
                "high_requires_owner_or_steward": True,
                "risk_overrides": {},
            },
            "discussion": {
                "max_comments": 12,
                "max_rounds": 6,
                "max_tokens": 16000,
                "max_elapsed_seconds": 1800,
                "max_concurrent_tasks": 2,
                "agent_loop_threshold": 4,
                "max_comment_bytes": 32768,
            },
            "transcripts": {
                "raw_retention_days": 90,
                "require_publish_consent": True,
                "max_publish_bytes": 262144,
            },
        },
    }
