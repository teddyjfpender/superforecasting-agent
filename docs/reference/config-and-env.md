# Configuration & Environment Variables

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Source of truth: os.getenv / os.environ reads across forecasting/, tui_gateway/, tools/, hermes_cli/ -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

> This page is generated from code. Do not edit it by hand — your change would be overwritten on the next regeneration and the staleness gate would fail. Edit the source instead, then run `python -m scripts.docgen`.

> **Source of truth:** `os.getenv / os.environ reads across forecasting/, tui_gateway/, tools/, hermes_cli/`

Every environment variable the server, tools, and CLI actually **read** — harvested by walking the AST of every module under `forecasting/`, `tui_gateway/`, `tools/`, and `hermes_cli/` for `os.getenv` / `os.environ.get` / `os.environ[...]`. There are **210 variables** (47 flagged as secrets, 163 configuration/runtime). The **default** column shows the fallback passed at the call site — `None` means a bare `os.getenv` (unset → `None`), `(required)` means a subscript that raises `KeyError` when unset, `(computed)` means a non-literal default. A variable read in several modules lists each; differing defaults are all shown.


> **Secrets** are classified by name (any variable whose name contains `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `CREDENTIAL`). This is a conservative naming heuristic, not a data-flow analysis — treat the list as "never log or commit these", and audit the source before assuming a variable *not* listed here is safe to print.

## Secrets & credentials


**47 variables** carry a credential-shaped name. Provide them via the environment or the credential store; never commit them.

| variable | default | read in |
| --- | --- | --- |
| `AI_GATEWAY_API_KEY` | `''` | `hermes_cli.models` |
| `ANTHROPIC_API_KEY` | `''` | `hermes_cli.runtime_provider` |
| `ANTHROPIC_TOKEN` | `None` | `hermes_cli.web_server` |
| `AWS_ACCESS_KEY_ID` | `''` | `hermes_cli.model_switch` |
| `AWS_BEARER_TOKEN_BEDROCK` | `''` | `hermes_cli.model_switch` |
| `AWS_SECRET_ACCESS_KEY` | `''` | `hermes_cli.model_switch` |
| `AZURE_ANTHROPIC_KEY` | `''` | `hermes_cli.runtime_provider` |
| `AZURE_FOUNDRY_API_KEY` | `''` | `hermes_cli.auth`, `hermes_cli.runtime_provider` |
| `CAMOFOX_SESSION_KEY` | `''` | `tools.browser_camofox` |
| `CLAUDE_CODE_OAUTH_TOKEN` | `None` | `hermes_cli.web_server` |
| `CUSTOM_API_KEY` | `''` | `hermes_cli.models` |
| `DAYTONA_API_KEY` | `None` | `hermes_cli.doctor`, `tools.terminal_tool` |
| `DISCORD_BOT_TOKEN` | `''` | `tools.discord_tool` |
| `EMAIL_PASSWORD` | `''` | `tools.send_message_tool` |
| `FAL_KEY` | `None` | `tools.tool_backend_helpers` |
| `FIRECRAWL_API_KEY` | `''` | `tools.web_tools` |
| `FORECAST_REDACT_SECRETS` | `None` | `hermes_cli.codex_runtime_plugin_migration` |
| `FRED_API_KEY` | `None` | `tools.forecasting_tool` |
| `GH_TOKEN` | `None` | `tools.skills_hub` |
| `GITHUB_APP_PRIVATE_KEY_PATH` | `None` | `tools.skills_hub` |
| `GITHUB_TOKEN` | `None` | `tools.skills_hub`, `tools.tirith_security` |
| `HASS_TOKEN` | `''`, `None` | `hermes_cli.tools_config`, `tools.homeassistant_tool`, `tools.send_message_tool` |
| `HERMES_API_KEY` | `''` | `tui_gateway.server` |
| `HERMES_KANBAN_SPECIFY_MAX_TOKENS` | `'6000'` | `hermes_cli.kanban_specify` |
| `HERMES_REDACT_SECRETS` | `None` | `hermes_cli.codex_runtime_plugin_migration` |
| `HERMES_SESSION_KEY` | `''` | `tools.terminal_tool` |
| `LM_API_KEY` | `''`, `None` | `hermes_cli.commands`, `hermes_cli.model_switch` |
| `MATRIX_ACCESS_TOKEN` | `''` | `tools.send_message_tool` |
| `MATTERMOST_TOKEN` | `''` | `tools.send_message_tool` |
| `MODAL_TOKEN_ID` | `None` | `tools.tool_backend_helpers` |
| `MODAL_TOKEN_SECRET` | `None` | `tools.tool_backend_helpers` |
| `NOVITA_API_KEY` | `''` | `hermes_cli.models` |
| `OLLAMA_API_KEY` | `''`, `None` | `hermes_cli.models`, `hermes_cli.runtime_provider` |
| `OPENAI_API_KEY` | `''`, `None` | `hermes_cli.auth`, `hermes_cli.models`, `hermes_cli.runtime_provider`, `tools.tool_backend_helpers` |
| `OPENROUTER_API_KEY` | `''`, `None` | `hermes_cli.auth`, `hermes_cli.doctor`, `hermes_cli.models`, `hermes_cli.runtime_provider`, `hermes_cli.status`, `tools.mixture_of_agents_tool`, `tools.openrouter_client` |
| `QQ_CLIENT_SECRET` | `''` | `tools.send_message_tool` |
| `SLACK_BOT_TOKEN` | `None` | `tools.slack_tool` |
| `SUDO_PASSWORD` | `''` | `hermes_cli.status`, `tools.terminal_tool` |
| `SUPERFORECASTING_AGENT_REDACT_SECRETS` | `None` | `hermes_cli.codex_runtime_plugin_migration` |
| `TELEGRAM_BOT_TOKEN` | `None` | `forecasting.transports.telegram` |
| `TERMINAL_SSH_KEY` | `''`, `None` | `hermes_cli.doctor`, `tools.terminal_tool` |
| `TOOL_GATEWAY_USER_TOKEN` | `None` | `tools.managed_tool_gateway` |
| `VERCEL_OIDC_TOKEN` | `None` | `tools.terminal_tool` |
| `VERCEL_TOKEN` | `None` | `tools.terminal_tool` |
| `VOICE_TOOLS_OPENAI_KEY` | `''` | `tools.tool_backend_helpers` |
| `WEIXIN_TOKEN` | `''` | `tools.send_message_tool` |
| `XAI_API_KEY` | `''`, `None` | `hermes_cli.tools_config`, `tools.xai_http` |

## Configuration & runtime


**163 variables** tune runtime behaviour, endpoints, paths, and feature flags, or are inherited from the surrounding shell/OS. Everything here is read directly from the environment at the call site shown.

| variable | default | read in |
| --- | --- | --- |
| `AGENT_BROWSER_ENGINE` | `''` | `tools.browser_tool` |
| `AGENT_BROWSER_EXECUTABLE_PATH` | `''` | `tools.browser_tool` |
| `AI_GATEWAY_BASE_URL` | `''` | `hermes_cli.models` |
| `APPDATA` | `''` | `hermes_cli.gateway_windows` |
| `APPTAINER_CACHEDIR` | `None` | `tools.environments.singularity` |
| `AUXILIARY_VIDEO_MODEL` | `''` | `tools.vision_tools` |
| `AUXILIARY_VISION_MODEL` | `''` | `tools.browser_tool`, `tools.vision_tools` |
| `AUXILIARY_WEB_EXTRACT_MODEL` | `''` | `tools.browser_tool` |
| `AWS_EC2_METADATA_DISABLED` | `None` | `hermes_cli.doctor` |
| `AZURE_FOUNDRY_BASE_URL` | `''` | `hermes_cli.runtime_provider` |
| `BROWSER_CDP_URL` | `''` | `tools.browser_camofox`, `tools.browser_tool`, `tui_gateway.server` |
| `BROWSER_INACTIVITY_TIMEOUT` | `'300'` | `tools.browser_tool` |
| `CAMOFOX_URL` | `''` | `tools.browser_camofox` |
| `CAMOFOX_USER_ID` | `''` | `tools.browser_camofox` |
| `CODEX_HOME` | `''` | `hermes_cli.auth`, `hermes_cli.codex_models` |
| `COPILOT_GH_HOST` | `''` | `hermes_cli.copilot_auth` |
| `CUSTOM_BASE_URL` | `''` | `hermes_cli.runtime_provider` |
| `DELEGATION_CHILD_TIMEOUT_SECONDS` | `None` | `tools.delegate_tool` |
| `DELEGATION_MAX_ASYNC_CHILDREN` | `None` | `tools.delegate_tool` |
| `DELEGATION_MAX_CONCURRENT_CHILDREN` | `None` | `tools.delegate_tool` |
| `DINGTALK_REGISTRATION_BASE_URL` | `'https://oapi.dingtalk.com'` | `hermes_cli.dingtalk_auth` |
| `DINGTALK_REGISTRATION_SOURCE` | `'openClaw'` | `hermes_cli.dingtalk_auth` |
| `DINGTALK_WEBHOOK_URL` | `''` | `tools.send_message_tool` |
| `DISPLAY` | `None` | `hermes_cli.web_server`, `tools.mcp_oauth` |
| `EDITOR` | `None` | `hermes_cli.config`, `hermes_cli.stdio` |
| `EMAIL_ADDRESS` | `''` | `tools.send_message_tool` |
| `EMAIL_SMTP_HOST` | `''` | `tools.send_message_tool` |
| `EMAIL_SMTP_PORT` | `'587'` | `tools.send_message_tool` |
| `FAL_IMAGE_MODEL` | `''` | `tools.image_generation_tool` |
| `FIRECRAWL_API_URL` | `''`, `None` | `tools.web_tools` |
| `FORECAST_BIN` | `''` | `hermes_cli.kanban_db` |
| `FORECAST_HOME` | `''` | `hermes_cli.main` |
| `FORECAST_RESOLUTION_MODEL` | `None` | `tools.forecast_actions.resolution` |
| `FORECAST_TIMEZONE` | `''` | `hermes_cli.config` |
| `FORECAST_TRIAGE_MODEL` | `None` | `tools.forecast_actions.triage` |
| `FORECAST_TRIAGE_TRUST_MIN_SAMPLE` | `'20'` | `tools.forecast_actions.triage` |
| `FORECAST_TRIAGE_TRUST_THRESHOLD` | `'0.8'` | `tools.forecast_actions.triage` |
| `GATEWAY_HEALTH_TIMEOUT` | `'3'`, `None` | `hermes_cli.web_server` |
| `GATEWAY_HEALTH_URL` | `None` | `hermes_cli.web_server` |
| `GITHUB_APP_ID` | `None` | `tools.skills_hub` |
| `GITHUB_APP_INSTALLATION_ID` | `None` | `tools.skills_hub` |
| `GROQ_BASE_URL` | `'https://api.groq.com/openai/v1'` | `tools.transcription_tools` |
| `HASS_URL` | `''`, `'http://homeassistant.local:8123'` | `tools.homeassistant_tool`, `tools.send_message_tool` |
| `HERMES_ALLOW_ROOT_GATEWAY` | `None` | `hermes_cli.gateway` |
| `HERMES_BASE_URL` | `''` | `tui_gateway.server` |
| `HERMES_BIN` | `''` | `hermes_cli.kanban_db` |
| `HERMES_CA_BUNDLE` | `None` | `hermes_cli.auth` |
| `HERMES_CODEX_BASE_URL` | `''` | `hermes_cli.auth`, `hermes_cli.codex_device_flow` |
| `HERMES_CODEX_REFRESH_TIMEOUT_SECONDS` | `'20'` | `hermes_cli.auth` |
| `HERMES_COMPUTER_USE_BACKEND` | `'cua'` | `tools.computer_use.tool` |
| `HERMES_CONTAINER` | `None` | `hermes_cli.config` |
| `HERMES_CUA_DRIVER_CMD` | `'cua-driver'` | `tools.computer_use.cua_backend` |
| `HERMES_CUA_DRIVER_VERSION` | `'0.5.0'` | `tools.computer_use.cua_backend` |
| `HERMES_DEV` | `None` | `hermes_cli.config` |
| `HERMES_DISABLE_LAZY_INSTALLS` | `None` | `tools.lazy_deps` |
| `HERMES_GATEWAY_DETACHED` | `''` | `hermes_cli.gateway` |
| `HERMES_GATEWAY_ELEVATED_HANDOFF` | `None` | `hermes_cli.gateway_windows` |
| `HERMES_GATEWAY_EXIT_DIAG` | `'1'` | `hermes_cli.gateway` |
| `HERMES_GATEWAY_INSTALL_START_NOW` | `None` | `hermes_cli.gateway_windows` |
| `HERMES_GATEWAY_INSTALL_START_ON_LOGIN` | `None` | `hermes_cli.gateway_windows` |
| `HERMES_HOME` | `''`, `(computed)`, `None` | `hermes_cli.codex_runtime_plugin_migration`, `hermes_cli.gateway`, `hermes_cli.main`, `hermes_cli.profiles`, `tools.mcp_oauth`, `tools.mcp_tool` |
| `HERMES_HOME_MODE` | `''` | `hermes_cli.config` |
| `HERMES_KANBAN_CLAIM_LOCK` | `None` | `tools.kanban_tools` |
| `HERMES_KANBAN_RUN_ID` | `None` | `hermes_cli.kanban`, `tools.kanban_tools` |
| `HERMES_KANBAN_TASK` | `None` | `hermes_cli.doctor`, `hermes_cli.kanban`, `tools.kanban_tools`, `tools.send_message_tool` |
| `HERMES_MARKET_INTERACTIVE` | `''` | `tui_gateway.server` |
| `HERMES_PLATFORM` | `None` | `tools.skills_tool` |
| `HERMES_PROFILE` | `None` | `hermes_cli.kanban_decompose`, `hermes_cli.kanban_specify`, `tools.kanban_tools` |
| `HERMES_SESSION_ID` | `None` | `tools.kanban_tools` |
| `HERMES_SESSION_PLATFORM` | `''` | `tools.approval` |
| `HERMES_SHARED_AUTH_DIR` | `''` | `hermes_cli.auth` |
| `HERMES_SKIP_CHMOD` | `None` | `hermes_cli.config` |
| `HERMES_TENANT` | `None` | `tools.kanban_tools` |
| `HERMES_TIMEZONE` | `''` | `hermes_cli.config` |
| `HERMES_VOICE_DEBUG` | `''` | `hermes_cli.voice` |
| `HERMES_XAI_BASE_URL` | `''` | `hermes_cli.auth` |
| `HERMES_XAI_REFRESH_TIMEOUT_SECONDS` | `'20'` | `hermes_cli.auth` |
| `HOME` | `''`, `None` | `hermes_cli.auth`, `hermes_cli.gateway_windows`, `hermes_cli.main` |
| `LM_BASE_URL` | `None` | `hermes_cli.commands`, `hermes_cli.model_switch` |
| `LOCALAPPDATA` | `''`, `None` | `hermes_cli.browser_connect`, `hermes_cli.plugins_cmd`, `hermes_cli.stdio`, `tools.browser_tool`, `tools.environments.local` |
| `LOGNAME` | `None` | `hermes_cli.auth`, `hermes_cli.gateway`, `hermes_cli.gateway_windows` |
| `MATRIX_HOMESERVER` | `''` | `tools.send_message_tool` |
| `MATTERMOST_URL` | `''` | `tools.send_message_tool` |
| `MESSAGING_CWD` | `None` | `hermes_cli.config` |
| `MINIMAX_PORTAL_BASE_URL` | `None` | `hermes_cli.web_server` |
| `NOVITA_BASE_URL` | `''` | `hermes_cli.models` |
| `NO_COLOR` | `None` | `hermes_cli.colors`, `hermes_cli.security_advisories` |
| `OBSIDIAN_VAULT_PATH` | `''` | `tui_gateway.server` |
| `OLLAMA_BASE_URL` | `''` | `hermes_cli.models` |
| `OPENAI_BASE_URL` | `''` | `hermes_cli.models`, `hermes_cli.runtime_provider` |
| `OPENROUTER_BASE_URL` | `''` | `hermes_cli.runtime_provider` |
| `OSV_ENDPOINT` | `'https://api.osv.dev/v1/query'` | `tools.osv_check` |
| `PATH` | `''` | `hermes_cli.doctor`, `hermes_cli.gateway`, `hermes_cli.kanban_db`, `hermes_cli.main`, `hermes_cli.profiles`, `hermes_cli.stdio` |
| `PATHEXT` | `None` | `hermes_cli.kanban_db` |
| `PLAYWRIGHT_BROWSERS_PATH` | `''` | `tools.browser_tool` |
| `PREFIX` | `''` | `hermes_cli.doctor`, `hermes_cli.uninstall` |
| `PULSE_SERVER` | `None` | `tools.voice_mode` |
| `PYTEST_CURRENT_TEST` | `None` | `hermes_cli.auth` |
| `PYTHON` | `''` | `hermes_cli.main` |
| `PYTHONPATH` | `''`, `None` | `hermes_cli.codex_runtime_plugin_migration`, `hermes_cli.gateway_windows` |
| `ProgramFiles` | `'C:\\Program Files'`, `None` | `hermes_cli.browser_connect`, `hermes_cli.plugins_cmd`, `tools.environments.local` |
| `ProgramFiles(x86)` | `'C:\\Program Files (x86)'`, `None` | `hermes_cli.browser_connect`, `hermes_cli.plugins_cmd`, `tools.environments.local` |
| `QQ_APP_ID` | `''` | `tools.send_message_tool` |
| `QQ_HOME_CHANNEL` | `''` | `hermes_cli.status` |
| `REQUESTS_CA_BUNDLE` | `None` | `hermes_cli.auth` |
| `SEARXNG_URL` | `''` | `tools.web_tools` |
| `SHELL` | `None` | `tools.environments.local` |
| `SSH_CLIENT` | `None` | `hermes_cli.auth`, `tools.mcp_oauth` |
| `SSH_TTY` | `None` | `hermes_cli.auth`, `tools.mcp_oauth` |
| `SSL_CERT_FILE` | `None` | `hermes_cli.auth` |
| `STT_GROQ_MODEL` | `'whisper-large-v3-turbo'` | `tools.transcription_tools` |
| `STT_MISTRAL_MODEL` | `'voxtral-mini-latest'` | `tools.transcription_tools` |
| `STT_OPENAI_BASE_URL` | `'https://api.openai.com/v1'` | `tools.transcription_tools` |
| `STT_OPENAI_MODEL` | `'whisper-1'` | `tools.transcription_tools` |
| `SUDO_USER` | `None` | `hermes_cli.gateway` |
| `SUPERFORECASTING_AGENT_BIN` | `''` | `hermes_cli.kanban_db` |
| `SUPERFORECASTING_AGENT_HOME` | `''` | `hermes_cli.main` |
| `SUPERFORECASTING_AGENT_TIMEZONE` | `''` | `hermes_cli.config` |
| `TERM` | `'dumb'`, `None` | `hermes_cli.colors`, `hermes_cli.main` |
| `TERMINAL_CONTAINER_DISK` | `'51200'` | `hermes_cli.doctor` |
| `TERMINAL_CONTAINER_PERSISTENT` | `'true'`, `None` | `hermes_cli.doctor`, `hermes_cli.status`, `tools.terminal_tool` |
| `TERMINAL_CWD` | `''`, `(computed)`, `None` | `hermes_cli.config`, `hermes_cli.file_drop`, `tools.code_execution_tool`, `tools.delegate_tool`, `tools.file_tools`, `tools.terminal_tool`, `tui_gateway.server` |
| `TERMINAL_DAYTONA_IMAGE` | `'nikolaik/python-nodejs:python3.11-nodejs20'`, `(computed)` | `hermes_cli.status`, `tools.terminal_tool` |
| `TERMINAL_DOCKER_IMAGE` | `'python:3.11-slim'`, `(computed)` | `hermes_cli.status`, `tools.terminal_tool` |
| `TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE` | `'false'` | `tools.terminal_tool` |
| `TERMINAL_DOCKER_RUN_AS_HOST_USER` | `'false'` | `tools.terminal_tool` |
| `TERMINAL_ENV` | `''`, `'local'` | `hermes_cli.doctor`, `hermes_cli.status`, `tools.credential_files`, `tools.file_tools`, `tools.skills_tool`, `tools.terminal_tool` |
| `TERMINAL_LIFETIME_SECONDS` | `'300'` | `tools.terminal_tool` |
| `TERMINAL_LOCAL_PERSISTENT` | `'false'` | `tools.terminal_tool` |
| `TERMINAL_MODAL_IMAGE` | `(computed)` | `tools.terminal_tool` |
| `TERMINAL_MODAL_MODE` | `'auto'` | `tools.terminal_tool` |
| `TERMINAL_PERSISTENT_SHELL` | `'true'` | `tools.terminal_tool` |
| `TERMINAL_SANDBOX_DIR` | `(computed)`, `None` | `tools.environments.base`, `tools.terminal_tool` |
| `TERMINAL_SCRATCH_DIR` | `None` | `tools.environments.singularity` |
| `TERMINAL_SINGULARITY_IMAGE` | `(computed)` | `tools.terminal_tool` |
| `TERMINAL_SSH_HOST` | `''`, `None` | `hermes_cli.doctor`, `hermes_cli.status`, `tools.terminal_tool` |
| `TERMINAL_SSH_PERSISTENT` | `(computed)` | `tools.terminal_tool` |
| `TERMINAL_SSH_PORT` | `None` | `hermes_cli.doctor` |
| `TERMINAL_SSH_USER` | `''`, `None` | `hermes_cli.doctor`, `hermes_cli.status`, `tools.terminal_tool` |
| `TERMINAL_TIMEOUT` | `'180'`, `'60'`, `None` | `hermes_cli.kanban_db`, `tools.process_registry`, `tools.terminal_tool` |
| `TERMINAL_VERCEL_RUNTIME` | `''`, `'node24'`, `None` | `hermes_cli.doctor`, `hermes_cli.status`, `tools.terminal_tool` |
| `TERMUX_VERSION` | `None` | `hermes_cli.doctor`, `hermes_cli.uninstall` |
| `TIRITH_BIN` | `(computed)` | `tools.tirith_security` |
| `TOOL_GATEWAY_DOMAIN` | `''` | `tools.managed_tool_gateway` |
| `TOOL_GATEWAY_SCHEME` | `''` | `tools.managed_tool_gateway` |
| `TWILIO_ACCOUNT_SID` | `''` | `tools.send_message_tool` |
| `TWILIO_PHONE_NUMBER` | `''` | `tools.send_message_tool` |
| `USER` | `''`, `'your-user'`, `(computed)`, `None` | `hermes_cli.auth`, `hermes_cli.gateway`, `hermes_cli.gateway_windows`, `hermes_cli.kanban_decompose`, `hermes_cli.kanban_specify`, `hermes_cli.main`, `hermes_cli.setup`, `tools.environments.singularity` |
| `USERDOMAIN` | `None` | `hermes_cli.gateway_windows` |
| `USERNAME` | `None` | `hermes_cli.gateway_windows` |
| `USERPROFILE` | `''` | `hermes_cli.gateway_windows` |
| `VERCEL_PROJECT_ID` | `None` | `tools.terminal_tool` |
| `VERCEL_TEAM_ID` | `None` | `tools.terminal_tool` |
| `VIRTUAL_ENV` | `None` | `hermes_cli.gateway` |
| `VISUAL` | `None` | `hermes_cli.config`, `hermes_cli.stdio` |
| `WAYLAND_DISPLAY` | `None` | `hermes_cli.clipboard`, `hermes_cli.web_server`, `tools.mcp_oauth` |
| `WEIXIN_ACCOUNT_ID` | `''` | `tools.send_message_tool` |
| `WEIXIN_BASE_URL` | `''` | `tools.send_message_tool` |
| `WEIXIN_CDN_BASE_URL` | `''` | `tools.send_message_tool` |
| `WEIXIN_HOME_CHANNEL` | `''` | `tools.send_message_tool` |
| `XAI_BASE_URL` | `''` | `hermes_cli.auth` |
| `XAI_STT_BASE_URL` | `'https://api.x.ai/v1'` | `tools.transcription_tools` |
| `XDG_RUNTIME_DIR` | `(computed)`, `None` | `hermes_cli.gateway` |
