# Configuration & Environment Variables

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Source of truth: os.getenv / os.environ reads across forecasting/, tui_gateway/, tools/, superforecasting_agent/ -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

> This page is generated from code. Do not edit it by hand — your change would be overwritten on the next regeneration and the staleness gate would fail. Edit the source instead, then run `python -m scripts.docgen`.

> **Source of truth:** `os.getenv / os.environ reads across forecasting/, tui_gateway/, tools/, superforecasting_agent/`

Every environment variable the server, tools, and CLI actually **read** — harvested by walking the AST of every module under `forecasting/`, `tui_gateway/`, `tools/`, and `superforecasting_agent/` for `os.getenv` / `os.environ.get` / `os.environ[...]`. There are **217 variables** (50 flagged as secrets, 167 configuration/runtime). The **default** column shows the fallback passed at the call site — `None` means a bare `os.getenv` (unset → `None`), `(required)` means a subscript that raises `KeyError` when unset, `(computed)` means a non-literal default. A variable read in several modules lists each; differing defaults are all shown.


> **Secrets** are classified by name (any variable whose name contains `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `CREDENTIAL`). This is a conservative naming heuristic, not a data-flow analysis — treat the list as "never log or commit these", and audit the source before assuming a variable *not* listed here is safe to print.

## Secrets & credentials


**50 variables** carry a credential-shaped name. Provide them via the environment or the credential store; never commit them.

| variable | default | read in |
| --- | --- | --- |
| `AI_GATEWAY_API_KEY` | `''` | `superforecasting_agent.runtime.models` |
| `ANTHROPIC_API_KEY` | `''` | `superforecasting_agent.runtime.runtime_provider` |
| `ANTHROPIC_TOKEN` | `None` | `superforecasting_agent.runtime.web_server` |
| `AWS_ACCESS_KEY_ID` | `''` | `superforecasting_agent.runtime.model_switch` |
| `AWS_BEARER_TOKEN_BEDROCK` | `''` | `superforecasting_agent.runtime.model_switch` |
| `AWS_SECRET_ACCESS_KEY` | `''` | `superforecasting_agent.runtime.model_switch` |
| `AZURE_ANTHROPIC_KEY` | `''` | `superforecasting_agent.runtime.runtime_provider` |
| `AZURE_FOUNDRY_API_KEY` | `''` | `superforecasting_agent.runtime.auth`, `superforecasting_agent.runtime.runtime_provider` |
| `CAMOFOX_SESSION_KEY` | `''` | `tools.browser_camofox` |
| `CLAUDE_CODE_OAUTH_TOKEN` | `None` | `superforecasting_agent.runtime.web_server` |
| `CUSTOM_API_KEY` | `''` | `superforecasting_agent.runtime.models` |
| `DAYTONA_API_KEY` | `None` | `superforecasting_agent.runtime.doctor`, `tools.terminal_tool` |
| `DISCORD_BOT_TOKEN` | `''` | `tools.discord_tool` |
| `EMAIL_PASSWORD` | `''` | `tools.send_message_tool` |
| `FAL_KEY` | `None` | `tools.tool_backend_helpers` |
| `FIRECRAWL_API_KEY` | `''` | `tools.web_tools` |
| `FORECAST_REDACT_SECRETS` | `None` | `superforecasting_agent.runtime.codex_runtime_plugin_migration` |
| `FORECAST_TRACE_ENCRYPTION_KEY` | `''` | `forecasting.change_control.trace_archive` |
| `FRED_API_KEY` | `None` | `tools.forecasting_tool` |
| `GH_TOKEN` | `None` | `forecasting.cli.collaboration_admin`, `superforecasting_agent.tooling.github_auth` |
| `GITHUB_APP_CLIENT_SECRET` | `''` | `forecasting.cli.collaboration_admin` |
| `GITHUB_APP_PRIVATE_KEY_PATH` | `None` | `superforecasting_agent.tooling.github_auth` |
| `GITHUB_TOKEN` | `None` | `forecasting.cli.collaboration_admin`, `superforecasting_agent.tooling.github_auth`, `tools.tirith_security` |
| `GITHUB_TOKEN_ENCRYPTION_KEY` | `''` | `forecasting.cli.collaboration_admin` |
| `HASS_TOKEN` | `''`, `None` | `superforecasting_agent.runtime.tools_config`, `tools.homeassistant_tool`, `tools.send_message_tool` |
| `HERMES_API_KEY` | `''` | `tui_gateway.server` |
| `HERMES_KANBAN_SPECIFY_MAX_TOKENS` | `'6000'` | `superforecasting_agent.runtime.kanban_specify` |
| `HERMES_REDACT_SECRETS` | `None` | `superforecasting_agent.runtime.codex_runtime_plugin_migration` |
| `HERMES_SESSION_KEY` | `''` | `tools.terminal_tool` |
| `LM_API_KEY` | `''`, `None` | `superforecasting_agent.runtime.commands`, `superforecasting_agent.runtime.model_switch` |
| `MATRIX_ACCESS_TOKEN` | `''` | `tools.send_message_tool` |
| `MATTERMOST_TOKEN` | `''` | `tools.send_message_tool` |
| `MODAL_TOKEN_ID` | `None` | `tools.tool_backend_helpers` |
| `MODAL_TOKEN_SECRET` | `None` | `tools.tool_backend_helpers` |
| `NOVITA_API_KEY` | `''` | `superforecasting_agent.runtime.models` |
| `OLLAMA_API_KEY` | `''`, `None` | `superforecasting_agent.runtime.models`, `superforecasting_agent.runtime.runtime_provider` |
| `OPENAI_API_KEY` | `''`, `None` | `superforecasting_agent.runtime.auth`, `superforecasting_agent.runtime.models`, `superforecasting_agent.runtime.runtime_provider`, `tools.tool_backend_helpers` |
| `OPENROUTER_API_KEY` | `''`, `None` | `superforecasting_agent.runtime.auth`, `superforecasting_agent.runtime.doctor`, `superforecasting_agent.runtime.models`, `superforecasting_agent.runtime.runtime_provider`, `superforecasting_agent.runtime.status`, `tools.mixture_of_agents_tool`, `tools.openrouter_client` |
| `QQ_CLIENT_SECRET` | `''` | `tools.send_message_tool` |
| `SLACK_BOT_TOKEN` | `None` | `tools.slack_tool` |
| `SUDO_PASSWORD` | `''` | `superforecasting_agent.runtime.status`, `tools.terminal_tool` |
| `SUPERFORECASTING_AGENT_REDACT_SECRETS` | `None` | `superforecasting_agent.runtime.codex_runtime_plugin_migration` |
| `TELEGRAM_BOT_TOKEN` | `None` | `forecasting.transports.telegram` |
| `TERMINAL_SSH_KEY` | `''`, `None` | `superforecasting_agent.runtime.doctor`, `tools.terminal_tool` |
| `TOOL_GATEWAY_USER_TOKEN` | `None` | `tools.managed_tool_gateway` |
| `VERCEL_OIDC_TOKEN` | `None` | `tools.terminal_tool` |
| `VERCEL_TOKEN` | `None` | `tools.terminal_tool` |
| `VOICE_TOOLS_OPENAI_KEY` | `''` | `tools.tool_backend_helpers` |
| `WEIXIN_TOKEN` | `''` | `tools.send_message_tool` |
| `XAI_API_KEY` | `''`, `None` | `superforecasting_agent.runtime.tools_config`, `tools.xai_http` |

## Configuration & runtime


**167 variables** tune runtime behaviour, endpoints, paths, and feature flags, or are inherited from the surrounding shell/OS. Everything here is read directly from the environment at the call site shown.

| variable | default | read in |
| --- | --- | --- |
| `AGENT_BROWSER_ENGINE` | `''` | `tools.browser_tool` |
| `AGENT_BROWSER_EXECUTABLE_PATH` | `''` | `tools.browser_tool` |
| `AI_GATEWAY_BASE_URL` | `''` | `superforecasting_agent.runtime.models` |
| `APPDATA` | `''` | `superforecasting_agent.runtime.gateway_windows` |
| `APPTAINER_CACHEDIR` | `None` | `tools.environments.singularity` |
| `AUXILIARY_VIDEO_MODEL` | `''` | `tools.vision_tools` |
| `AUXILIARY_VISION_MODEL` | `''` | `tools.browser_tool`, `tools.vision_tools` |
| `AUXILIARY_WEB_EXTRACT_MODEL` | `''` | `tools.browser_tool` |
| `AWS_EC2_METADATA_DISABLED` | `None` | `superforecasting_agent.runtime.doctor` |
| `AZURE_FOUNDRY_BASE_URL` | `''` | `superforecasting_agent.runtime.runtime_provider` |
| `BROWSER_CDP_URL` | `''` | `superforecasting_agent.runtime.browser_commands`, `tools.browser_camofox`, `tools.browser_tool`, `tui_gateway.browser_rpc` |
| `BROWSER_INACTIVITY_TIMEOUT` | `'300'` | `tools.browser_tool` |
| `CAMOFOX_URL` | `''` | `tools.browser_camofox` |
| `CAMOFOX_USER_ID` | `''` | `tools.browser_camofox` |
| `CODEX_HOME` | `''` | `superforecasting_agent.runtime.auth`, `superforecasting_agent.runtime.codex_models` |
| `COPILOT_GH_HOST` | `''` | `superforecasting_agent.runtime.copilot_auth` |
| `CUSTOM_BASE_URL` | `''` | `superforecasting_agent.runtime.runtime_provider` |
| `DELEGATION_CHILD_TIMEOUT_SECONDS` | `None` | `tools.delegate_tool` |
| `DELEGATION_MAX_ASYNC_CHILDREN` | `None` | `tools.delegate_tool` |
| `DELEGATION_MAX_CONCURRENT_CHILDREN` | `None` | `tools.delegate_tool` |
| `DINGTALK_REGISTRATION_BASE_URL` | `'https://oapi.dingtalk.com'` | `superforecasting_agent.runtime.dingtalk_auth` |
| `DINGTALK_REGISTRATION_SOURCE` | `'openClaw'` | `superforecasting_agent.runtime.dingtalk_auth` |
| `DINGTALK_WEBHOOK_URL` | `''` | `tools.send_message_tool` |
| `DISPLAY` | `None` | `superforecasting_agent.runtime.web_server`, `tools.mcp_oauth` |
| `EDITOR` | `None` | `superforecasting_agent.runtime.config`, `superforecasting_agent.runtime.stdio` |
| `EMAIL_ADDRESS` | `''` | `tools.send_message_tool` |
| `EMAIL_SMTP_HOST` | `''` | `tools.send_message_tool` |
| `EMAIL_SMTP_PORT` | `'587'` | `tools.send_message_tool` |
| `FAL_IMAGE_MODEL` | `''` | `tools.image_generation_tool` |
| `FIRECRAWL_API_URL` | `''`, `None` | `tools.web_tools` |
| `FORECAST_BIN` | `''` | `superforecasting_agent.runtime.kanban_db` |
| `FORECAST_COMMIT_POLICY` | `''` | `forecasting.ledger.gate` |
| `FORECAST_HOME` | `''` | `superforecasting_agent.cli`, `superforecasting_agent.runtime.main` |
| `FORECAST_RESOLUTION_MODEL` | `None` | `tools.forecast_actions.resolution` |
| `FORECAST_TIMEZONE` | `''` | `superforecasting_agent.runtime.config` |
| `FORECAST_TRIAGE_MODEL` | `None` | `tools.forecast_actions.triage` |
| `FORECAST_TRIAGE_TRUST_MIN_SAMPLE` | `'20'` | `tools.forecast_actions.triage` |
| `FORECAST_TRIAGE_TRUST_THRESHOLD` | `'0.8'` | `tools.forecast_actions.triage` |
| `GATEWAY_HEALTH_TIMEOUT` | `'3'`, `None` | `superforecasting_agent.runtime.web_server` |
| `GATEWAY_HEALTH_URL` | `None` | `superforecasting_agent.runtime.web_server` |
| `GITHUB_APP_ID` | `None` | `superforecasting_agent.tooling.github_auth` |
| `GITHUB_APP_INSTALLATION_ID` | `None` | `superforecasting_agent.tooling.github_auth` |
| `GITHUB_SHA` | `None` | `forecasting.ledger.workflow` |
| `GROQ_BASE_URL` | `'https://api.groq.com/openai/v1'` | `tools.transcription_tools` |
| `HASS_URL` | `''`, `'http://homeassistant.local:8123'` | `tools.homeassistant_tool`, `tools.send_message_tool` |
| `HERMES_ALLOW_ROOT_GATEWAY` | `None` | `superforecasting_agent.runtime.gateway` |
| `HERMES_BASE_URL` | `''` | `tui_gateway.server` |
| `HERMES_BIN` | `''` | `superforecasting_agent.runtime.kanban_db` |
| `HERMES_CA_BUNDLE` | `None` | `superforecasting_agent.runtime.auth` |
| `HERMES_CODEX_BASE_URL` | `''` | `superforecasting_agent.runtime.auth`, `superforecasting_agent.runtime.codex_device_flow` |
| `HERMES_CODEX_REFRESH_TIMEOUT_SECONDS` | `'20'` | `superforecasting_agent.runtime.auth` |
| `HERMES_COMPUTER_USE_BACKEND` | `'cua'` | `tools.computer_use.tool` |
| `HERMES_CONTAINER` | `None` | `superforecasting_agent.runtime.config` |
| `HERMES_CUA_DRIVER_CMD` | `'cua-driver'` | `tools.computer_use.cua_backend` |
| `HERMES_CUA_DRIVER_VERSION` | `'0.5.0'` | `tools.computer_use.cua_backend` |
| `HERMES_DEV` | `None` | `superforecasting_agent.runtime.config` |
| `HERMES_DISABLE_LAZY_INSTALLS` | `None` | `tools.lazy_deps` |
| `HERMES_GATEWAY_DETACHED` | `''` | `superforecasting_agent.runtime.gateway` |
| `HERMES_GATEWAY_ELEVATED_HANDOFF` | `None` | `superforecasting_agent.runtime.gateway_windows` |
| `HERMES_GATEWAY_EXIT_DIAG` | `'1'` | `superforecasting_agent.runtime.gateway` |
| `HERMES_GATEWAY_INSTALL_START_NOW` | `None` | `superforecasting_agent.runtime.gateway_windows` |
| `HERMES_GATEWAY_INSTALL_START_ON_LOGIN` | `None` | `superforecasting_agent.runtime.gateway_windows` |
| `HERMES_HOME` | `''`, `(computed)`, `None` | `superforecasting_agent.cli`, `superforecasting_agent.runtime.codex_runtime_plugin_migration`, `superforecasting_agent.runtime.gateway`, `superforecasting_agent.runtime.main`, `superforecasting_agent.runtime.profiles`, `tools.mcp_oauth`, `tools.mcp_tool` |
| `HERMES_HOME_MODE` | `''` | `superforecasting_agent.runtime.config` |
| `HERMES_KANBAN_CLAIM_LOCK` | `None` | `tools.kanban_tools` |
| `HERMES_KANBAN_RUN_ID` | `None` | `superforecasting_agent.runtime.kanban`, `tools.kanban_tools` |
| `HERMES_KANBAN_TASK` | `None` | `superforecasting_agent.runtime.doctor`, `superforecasting_agent.runtime.kanban`, `superforecasting_agent.tooling.definitions`, `tools.kanban_tools`, `tools.send_message_tool` |
| `HERMES_MARKET_INTERACTIVE` | `''` | `tui_gateway.server` |
| `HERMES_PLATFORM` | `None` | `tools.skills_tool` |
| `HERMES_PROFILE` | `None` | `superforecasting_agent.runtime.kanban_decompose`, `superforecasting_agent.runtime.kanban_specify`, `tools.kanban_tools` |
| `HERMES_SESSION_ID` | `None` | `tools.kanban_tools` |
| `HERMES_SESSION_PLATFORM` | `''` | `tools.approval` |
| `HERMES_SHARED_AUTH_DIR` | `''` | `superforecasting_agent.runtime.auth` |
| `HERMES_SKIP_CHMOD` | `None` | `superforecasting_agent.runtime.config` |
| `HERMES_TENANT` | `None` | `tools.kanban_tools` |
| `HERMES_TIMEZONE` | `''` | `superforecasting_agent.runtime.config` |
| `HERMES_VOICE_DEBUG` | `''` | `superforecasting_agent.runtime.voice` |
| `HERMES_XAI_BASE_URL` | `''` | `superforecasting_agent.runtime.auth` |
| `HERMES_XAI_REFRESH_TIMEOUT_SECONDS` | `'20'` | `superforecasting_agent.runtime.auth` |
| `HOME` | `''`, `None` | `superforecasting_agent.runtime.auth`, `superforecasting_agent.runtime.gateway_windows`, `superforecasting_agent.runtime.main` |
| `LM_BASE_URL` | `None` | `superforecasting_agent.runtime.commands`, `superforecasting_agent.runtime.model_switch` |
| `LOCALAPPDATA` | `''`, `None` | `superforecasting_agent.runtime.browser_connect`, `superforecasting_agent.runtime.plugins_cmd`, `superforecasting_agent.runtime.stdio`, `tools.browser_tool`, `tools.environments.local` |
| `LOGNAME` | `None` | `superforecasting_agent.runtime.auth`, `superforecasting_agent.runtime.gateway`, `superforecasting_agent.runtime.gateway_windows` |
| `MATRIX_HOMESERVER` | `''` | `tools.send_message_tool` |
| `MATTERMOST_URL` | `''` | `tools.send_message_tool` |
| `MESSAGING_CWD` | `None` | `superforecasting_agent.runtime.config` |
| `MINIMAX_PORTAL_BASE_URL` | `None` | `superforecasting_agent.runtime.web_server` |
| `NOVITA_BASE_URL` | `''` | `superforecasting_agent.runtime.models` |
| `NO_COLOR` | `None` | `superforecasting_agent.runtime.colors`, `superforecasting_agent.runtime.security_advisories` |
| `OBSIDIAN_VAULT_PATH` | `''` | `tui_gateway.obsidian_rpc` |
| `OLLAMA_BASE_URL` | `''` | `superforecasting_agent.runtime.models` |
| `OPENAI_BASE_URL` | `''` | `superforecasting_agent.runtime.models`, `superforecasting_agent.runtime.runtime_provider` |
| `OPENROUTER_BASE_URL` | `''` | `superforecasting_agent.runtime.runtime_provider` |
| `OSV_ENDPOINT` | `'https://api.osv.dev/v1/query'` | `tools.osv_check` |
| `PATH` | `''` | `superforecasting_agent.runtime.doctor`, `superforecasting_agent.runtime.gateway`, `superforecasting_agent.runtime.kanban_db`, `superforecasting_agent.runtime.main`, `superforecasting_agent.runtime.profiles`, `superforecasting_agent.runtime.stdio` |
| `PATHEXT` | `None` | `superforecasting_agent.runtime.kanban_db` |
| `PLAYWRIGHT_BROWSERS_PATH` | `''` | `tools.browser_tool` |
| `PREFIX` | `''` | `superforecasting_agent.constants`, `superforecasting_agent.runtime.doctor`, `superforecasting_agent.runtime.uninstall` |
| `PULSE_SERVER` | `None` | `tools.voice_mode` |
| `PYTEST_CURRENT_TEST` | `None` | `superforecasting_agent.runtime.auth` |
| `PYTHON` | `''` | `superforecasting_agent.runtime.main` |
| `PYTHONPATH` | `''`, `None` | `superforecasting_agent.runtime.codex_runtime_plugin_migration`, `superforecasting_agent.runtime.gateway_windows` |
| `ProgramFiles` | `'C:\\Program Files'`, `None` | `superforecasting_agent.runtime.browser_connect`, `superforecasting_agent.runtime.plugins_cmd`, `tools.environments.local` |
| `ProgramFiles(x86)` | `'C:\\Program Files (x86)'`, `None` | `superforecasting_agent.runtime.browser_connect`, `superforecasting_agent.runtime.plugins_cmd`, `tools.environments.local` |
| `QQ_APP_ID` | `''` | `tools.send_message_tool` |
| `QQ_HOME_CHANNEL` | `''` | `superforecasting_agent.runtime.status` |
| `REQUESTS_CA_BUNDLE` | `None` | `superforecasting_agent.runtime.auth` |
| `SEARXNG_URL` | `''` | `tools.web_tools` |
| `SHELL` | `None` | `tools.environments.local` |
| `SSH_CLIENT` | `None` | `superforecasting_agent.runtime.auth`, `tools.mcp_oauth` |
| `SSH_TTY` | `None` | `superforecasting_agent.runtime.auth`, `tools.mcp_oauth` |
| `SSL_CERT_FILE` | `None` | `superforecasting_agent.runtime.auth` |
| `STT_GROQ_MODEL` | `'whisper-large-v3-turbo'` | `tools.transcription_tools` |
| `STT_MISTRAL_MODEL` | `'voxtral-mini-latest'` | `tools.transcription_tools` |
| `STT_OPENAI_BASE_URL` | `'https://api.openai.com/v1'` | `tools.transcription_tools` |
| `STT_OPENAI_MODEL` | `'whisper-1'` | `tools.transcription_tools` |
| `SUDO_USER` | `None` | `superforecasting_agent.runtime.gateway` |
| `SUPERFORECASTING_AGENT_BIN` | `''` | `superforecasting_agent.runtime.kanban_db` |
| `SUPERFORECASTING_AGENT_CODE_REVISION` | `None` | `forecasting.ledger.workflow` |
| `SUPERFORECASTING_AGENT_HOME` | `''` | `superforecasting_agent.cli`, `superforecasting_agent.runtime.main` |
| `SUPERFORECASTING_AGENT_TIMEZONE` | `''` | `superforecasting_agent.runtime.config` |
| `TERM` | `'dumb'`, `None` | `superforecasting_agent.runtime.colors`, `superforecasting_agent.runtime.main` |
| `TERMINAL_CONTAINER_DISK` | `'51200'` | `superforecasting_agent.runtime.doctor` |
| `TERMINAL_CONTAINER_PERSISTENT` | `'true'`, `None` | `superforecasting_agent.runtime.doctor`, `superforecasting_agent.runtime.status`, `tools.terminal_tool` |
| `TERMINAL_CWD` | `''`, `(computed)`, `None` | `superforecasting_agent.runtime.checkpoint_commands`, `superforecasting_agent.runtime.config`, `superforecasting_agent.runtime.file_drop`, `tools.code_execution_tool`, `tools.delegate_tool`, `tools.file_tools`, `tools.terminal_tool`, `tui_gateway.server` |
| `TERMINAL_DAYTONA_IMAGE` | `'nikolaik/python-nodejs:python3.11-nodejs20'`, `(computed)` | `superforecasting_agent.runtime.status`, `tools.terminal_tool` |
| `TERMINAL_DOCKER_IMAGE` | `'python:3.11-slim'`, `(computed)` | `superforecasting_agent.runtime.status`, `tools.terminal_tool` |
| `TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE` | `'false'` | `tools.terminal_tool` |
| `TERMINAL_DOCKER_RUN_AS_HOST_USER` | `'false'` | `tools.terminal_tool` |
| `TERMINAL_ENV` | `''`, `'local'` | `superforecasting_agent.runtime.doctor`, `superforecasting_agent.runtime.status`, `superforecasting_agent.trajectories.batch_worker`, `tools.credential_files`, `tools.file_tools`, `tools.skills_tool`, `tools.terminal_tool` |
| `TERMINAL_LIFETIME_SECONDS` | `'300'` | `tools.terminal_tool` |
| `TERMINAL_LOCAL_PERSISTENT` | `'false'` | `tools.terminal_tool` |
| `TERMINAL_MODAL_IMAGE` | `(computed)` | `tools.terminal_tool` |
| `TERMINAL_MODAL_MODE` | `'auto'` | `tools.terminal_tool` |
| `TERMINAL_PERSISTENT_SHELL` | `'true'` | `tools.terminal_tool` |
| `TERMINAL_SANDBOX_DIR` | `(computed)`, `None` | `tools.environments.base`, `tools.terminal_tool` |
| `TERMINAL_SCRATCH_DIR` | `None` | `tools.environments.singularity` |
| `TERMINAL_SINGULARITY_IMAGE` | `(computed)` | `tools.terminal_tool` |
| `TERMINAL_SSH_HOST` | `''`, `None` | `superforecasting_agent.runtime.doctor`, `superforecasting_agent.runtime.status`, `tools.terminal_tool` |
| `TERMINAL_SSH_PERSISTENT` | `(computed)` | `tools.terminal_tool` |
| `TERMINAL_SSH_PORT` | `None` | `superforecasting_agent.runtime.doctor` |
| `TERMINAL_SSH_USER` | `''`, `None` | `superforecasting_agent.runtime.doctor`, `superforecasting_agent.runtime.status`, `tools.terminal_tool` |
| `TERMINAL_TIMEOUT` | `'180'`, `'60'`, `None` | `superforecasting_agent.runtime.kanban_db`, `tools.process_registry`, `tools.terminal_tool` |
| `TERMINAL_VERCEL_RUNTIME` | `''`, `'node24'`, `None` | `superforecasting_agent.runtime.doctor`, `superforecasting_agent.runtime.status`, `tools.terminal_tool` |
| `TERMUX_VERSION` | `None` | `superforecasting_agent.constants`, `superforecasting_agent.runtime.doctor`, `superforecasting_agent.runtime.uninstall` |
| `TIRITH_BIN` | `(computed)` | `tools.tirith_security` |
| `TOOL_GATEWAY_DOMAIN` | `''` | `tools.managed_tool_gateway` |
| `TOOL_GATEWAY_SCHEME` | `''` | `tools.managed_tool_gateway` |
| `TWILIO_ACCOUNT_SID` | `''` | `tools.send_message_tool` |
| `TWILIO_PHONE_NUMBER` | `''` | `tools.send_message_tool` |
| `USER` | `''`, `'your-user'`, `(computed)`, `None` | `superforecasting_agent.runtime.auth`, `superforecasting_agent.runtime.gateway`, `superforecasting_agent.runtime.gateway_windows`, `superforecasting_agent.runtime.kanban_decompose`, `superforecasting_agent.runtime.kanban_specify`, `superforecasting_agent.runtime.main`, `superforecasting_agent.runtime.setup`, `tools.environments.singularity` |
| `USERDOMAIN` | `None` | `superforecasting_agent.runtime.gateway_windows` |
| `USERNAME` | `None` | `superforecasting_agent.runtime.gateway_windows` |
| `USERPROFILE` | `''` | `superforecasting_agent.runtime.gateway_windows` |
| `VERCEL_PROJECT_ID` | `None` | `tools.terminal_tool` |
| `VERCEL_TEAM_ID` | `None` | `tools.terminal_tool` |
| `VIRTUAL_ENV` | `None` | `superforecasting_agent.runtime.gateway` |
| `VISUAL` | `None` | `superforecasting_agent.runtime.config`, `superforecasting_agent.runtime.stdio` |
| `WAYLAND_DISPLAY` | `None` | `superforecasting_agent.runtime.clipboard`, `superforecasting_agent.runtime.web_server`, `tools.mcp_oauth` |
| `WEIXIN_ACCOUNT_ID` | `''` | `tools.send_message_tool` |
| `WEIXIN_BASE_URL` | `''` | `tools.send_message_tool` |
| `WEIXIN_CDN_BASE_URL` | `''` | `tools.send_message_tool` |
| `WEIXIN_HOME_CHANNEL` | `''` | `tools.send_message_tool` |
| `XAI_BASE_URL` | `''` | `superforecasting_agent.runtime.auth` |
| `XAI_STT_BASE_URL` | `'https://api.x.ai/v1'` | `tools.transcription_tools` |
| `XDG_RUNTIME_DIR` | `(computed)`, `None` | `superforecasting_agent.runtime.gateway` |
| `_HERMES_GATEWAY` | `None` | `superforecasting_agent.runtime.interactive_config` |
