# Runtime modules and import migration

The forecast ledger lives in `forecasting/`. Shared application infrastructure
lives in `superforecasting_agent/`, with explicit modules for storage, runtime
commands, environment values, URLs, and trajectory processing.

Internal Python imports have changed during the repository cleanup. Update
extensions that import these implementation modules using this mapping:

| Previous import | Current import |
| --- | --- |
| `hermes_bootstrap` | `superforecasting_agent.bootstrap` |
| `hermes_constants` | `superforecasting_agent.constants` |
| `hermes_time` | `superforecasting_agent.clock` |
| `hermes_logging` | `superforecasting_agent.logging` |
| `hermes_state` | `superforecasting_agent.storage.session` |
| `hermes_cli.<module>` | `superforecasting_agent.runtime.<module>` |
| `batch_runner` | `superforecasting_agent.trajectories.batch` |
| `toolset_distributions` | `superforecasting_agent.trajectories.distributions` |
| `trajectory_compressor` | `superforecasting_agent.trajectories.compression` |
| `model_tools` | `superforecasting_agent.tooling.runtime` |
| `toolsets` | `superforecasting_agent.tooling.toolsets` |
| `mcp_serve` | `superforecasting_agent.mcp.server` |
| `utils` environment helpers | `superforecasting_agent.environment` |
| `utils` hostname and proxy helpers | `superforecasting_agent.urls` |
| `utils` JSON/YAML and atomic file helpers | `superforecasting_agent.storage.files` |

The old root modules and `hermes_cli` package are removed. Home helpers also use
native names: `get_agent_home()`, `display_agent_home()`, and
`get_agent_home_override()`. Use `superforecasting_agent.paths.get_install_root()`
when resolving installation assets; a runtime module's parent directory is no
longer the installation root.

For example:

```python
from superforecasting_agent.constants import get_agent_home
from superforecasting_agent.storage.files import atomic_json_write
from superforecasting_agent.storage.session import SessionDB
from superforecasting_agent.urls import base_url_hostname
```

`SessionDB` remains the storage facade. Its implementation is divided by
responsibility under `storage/`; callers should keep using the facade rather
than depending on its method-binding modules. Environment and URL helpers are
lightweight imports and do not initialize the forecast application.

Trajectory utilities run as modules:

```bash
python -m superforecasting_agent.trajectories.batch --help
python -m superforecasting_agent.trajectories.compression --help
```

The checkout-only SWE data generator is
`python -m scripts.data_generation.swe_runner`; see its
[guide](../../scripts/data_generation/README.md).

The TUI renderer package is `@superforecasting/ink`, maintained in
`ui-tui/packages/forecast-ink`. The Python gateway remains in `tui_gateway/`,
and the dashboard embeds that TUI through a PTY.

The messaging MCP bridge lives in `superforecasting_agent/mcp/`: `server.py`
creates and runs the server, `data.py` reads session data, `events.py` owns the
poller, and the two tool-registration modules define the conversation and event
surfaces. The public command remains `superforecasting-agent mcp serve`.

The Codex tool callback implementation is
`agent.transports.forecast_tools_mcp_server`. Existing configurations can still
launch `agent.transports.hermes_tools_mcp_server`, which delegates to the native
entrypoint. Its persisted `hermes-tools` server ID remains compatible.

Tool argument coercion and error sanitization live in
`superforecasting_agent/tooling/arguments.py` and `errors.py`. The orchestration
API in `superforecasting_agent/tooling/runtime.py` continues to dispatch through those helpers.
`tooling/async_bridge.py` owns persistent event loops and coroutine bridging;
tool handlers import it directly. Their tests are grouped in `tests/tooling/`.

These source changes do not rename existing user data. Legacy home paths,
supported `HERMES_*` environment aliases, launcher aliases, and persisted names
such as `hermes_state.db` retain their compatibility handling. Prefer
`superforecasting-agent` and `~/.superforecasting-agent` for new installations.

`tooling/definitions.py` owns schema discovery, cache invalidation, and the
last-resolved tool selection. `tooling/dispatch.py` reads that state for sandbox
fallback and runs approvals and plugin hooks. Mutable state is accessed through
the definitions module; the public runtime API does not copy those bindings.

Toolset resolution lives in `tooling/toolsets.py`. Catalogs under
`tooling/catalogs/` separate capabilities, forecast presets, compatibility
presets, and aliases. Add membership to the category or forecast preset that
should expose the tool. The shared `_CORE_TOOLS` list supports legacy platform
presets; it does not automatically add tools to every forecast workflow.

CLI worktree creation lives in `runtime/worktree_setup.py`; cleanup and active
worktree state live in `runtime/worktrees.py`. Automatic cleanup preserves local
files and unpushed commits regardless of age. Worktree removal must succeed
before branch cleanup, and unmerged branches are retained by Git's safe delete.

`ForecastCLI` is the concrete interactive CLI class. The legacy `HermesCLI`
import is an alias to that same class for existing extensions.

CLI display-text normalization lives in `runtime/assistant_text.py`; session
and checkpoint startup maintenance live in `runtime/session_maintenance.py`.
These helpers can be imported without initializing the interactive CLI.

The interactive loader delegates from `cli.load_cli_config()` to
`runtime/interactive_config.py`. Its wrapper supplies the active home and
installation-relative project file explicitly. `interactive_defaults.py`
creates a fresh defaults dictionary for each load; environment bridging remains
part of the load operation.

Agent transcript cleanup, JSON log writes, SQLite flushes, and content redaction
live in `agent/session_persistence.py`. `AIAgent` binds these functions as methods
and retains staticmethod descriptors for the content helpers.

Provider-error classification helpers and display formatting live in
`agent/api_errors.py`, bound by `AIAgent` through the same method interface.

Image capability checks, image-to-text fallback, temporary-file cleanup and
multimodal tool-result formatting live in `agent/image_preprocessing.py`.
Anthropic and other non-vision model paths share the same preprocessing loop.

Output-sink safety, lifecycle notifications and buffered retry messages live in
`agent/status_output.py`, with the existing AIAgent methods bound to those
functions. Rendering remains owned by each CLI, gateway or TUI caller.

Memory flush/shutdown, client eviction and full task cleanup live in
`agent/session_lifecycle.py`. Cache eviction releases clients while preserving
terminal, browser and process state; actual session boundaries use full cleanup.

Shared/per-request OpenAI client locks, recreation, keepalive configuration and
request-specific headers live in `agent/openai_clients.py`. Client construction
and transport recovery still use the existing runtime helpers.

Provider credential refresh and rotation live in `agent/credential_recovery.py`.
Nous refresh reuses the same native/compatibility environment helpers as normal
credential resolution.

Setup and the OpenClaw CLI share `runtime/openclaw_loader.py` for loading the
standalone `openclaw_to_forecast.py` command. Its sibling
`_forecast_migration_runner.py` coordinates focused modules for file operations,
workspace memory, skills, channels, providers, preferences, external integrations,
options, text processing, and reports. These modules remain inside the optional
skill so it can run without installing the main package. The former
`openclaw_to_hermes.py` filename is a compatibility launcher; discovery also
supports older installed copies that only contain that filename.

Forecast search ranking, result formatting and reference splitting live in
`runtime/forecast_search.py`. The interactive CLI retains command dispatch and
its terminal output renderer; class/static method bindings remain unchanged.

Interactive credential refresh, model normalization and per-turn provider
configuration live in `runtime/interactive_routing.py`. The CLI coordinates
agent initialization through the same bound method interface.

Prompt-toolkit printing, the Rich ChatConsole adapter and redraw history live
in `runtime/console_output.py`. Saved conversation recap rendering and resize replay live in
`runtime/resume_display.py`, using the same output-history owner.
That module owns the mutable history buffer and replay/suppression flags; callers
use its functions rather than copying state bindings. The root CLI re-exports
the print/history functions for existing command handlers.

Forecast slash-command handlers and question-reference resolution live in
`runtime/forecast_commands.py`, using the shared console output functions.
Their search/formatting helpers remain in `forecast_search.py`; ForecastCLI
binds both through its existing command interface.

Interactive browser connection commands live in `runtime/browser_commands.py`,
using `runtime/browser_connect.py` for platform discovery and CDP readiness.
The root CLI retains the command and static launch method bindings.

Interactive goal/subgoal commands and post-turn continuation coordination live
in `runtime/goal_commands.py`; persistent goal state and judging stay in
`runtime/goals.py`. Slash-command detection belongs to the central command
module, and console escape constants share the console-output owner.
