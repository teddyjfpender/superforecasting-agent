---
sidebar_position: 12
sidebar_label: "Built-in Plugins"
title: "Built-in Plugins"
description: "Use bundled plugins as optional forecast-desk support surfaces."
---

# Built-in Plugins

Superforecasting Agent ships a small set of bundled plugins under `<repo>/plugins/<name>/`. They are inherited runtime extensions for cleanup, observability, dashboards, media backends, meeting capture, and workflow support. They are useful around the forecasting desk, but they are not the forecast ledger.

The ledger remains the source of truth for forecast questions, evidence, assumptions, model runs, snapshots, resolutions, scores, postmortems, calibration lessons, domain error profiles, schedules, and alerts. A plugin output only affects a forecast after it is explicitly imported or recorded through `forecast` workflows.

See [Plugins](./plugins) for the general plugin system and [Build a plugin](../../guides/build-a-hermes-plugin) for authoring guidance. The tutorial keeps its inherited slug for compatibility, but the supported product target is Superforecasting Agent.

## How Discovery Works

The `PluginManager` scans four sources, in order:

1. **Bundled** - `<repo>/plugins/<name>/`
2. **User** - `~/.superforecasting-agent/plugins/<name>/`
3. **Project** - `./.hermes/plugins/<name>/` when `SUPERFORECASTING_AGENT_ENABLE_PROJECT_PLUGINS=1` or an accepted alias is set
4. **Pip entry points** - `hermes_agent.plugins`

Later sources win on name collision. A user plugin named `disk-cleanup` can override the bundled plugin with the same name.

Legacy `~/.hermes/plugins/<name>/`, `$HERMES_HOME`, `HERMES_*` environment variables, and the `hermes_agent.plugins` entry-point group remain real inherited runtime identifiers. New forecast profiles should use `~/.superforecasting-agent/` unless a specific integration still requires the inherited name.

`plugins/memory/` and `plugins/context_engine/` are deliberately excluded from this bundled-plugin scan. Memory providers and context engines use provider-specific discovery paths because they are configured separately through `superforecasting-agent memory setup`, `superforecasting-agent plugins`, and `context.engine`.

## Bundled Plugins Are Opt-In

Bundled lifecycle and tool plugins ship disabled. Discovery finds them, and they appear in `superforecasting-agent plugins list` plus the interactive `superforecasting-agent plugins` UI, but none load until you enable them:

```bash
superforecasting-agent plugins enable disk-cleanup
```

Or via `~/.superforecasting-agent/config.yaml`:

```yaml
plugins:
  enabled:
    - disk-cleanup
```

They are never auto-enabled on a fresh install or upgrade. Opting in matters because lifecycle hooks can observe tool calls, runtime state, or workspace files.

To turn a bundled plugin off again:

```bash
superforecasting-agent plugins disable disk-cleanup
```

Or remove it from `plugins.enabled` in config.

## Currently Shipped

The repo ships these bundled plugins under `plugins/`.

| Plugin | Kind | Forecast-desk role |
|---|---|---|
| `disk-cleanup` | hooks + slash command | Keeps temporary forecast research artifacts, cron outputs, and test files from accumulating |
| `observability/langfuse` | hooks | Traces model calls, tool calls, and usage so forecast-impacting runs can be audited outside the ledger |
| `google_meet` | standalone | Captures meeting transcripts that can become evidence candidates after review |
| `kanban/dashboard` | dashboard tab | Coordinates multi-worker forecast research and implementation tasks |
| `image_gen/openai` | image backend | Inherited media backend; not part of default forecast probability work |
| `image_gen/openai-codex` | image backend | Inherited media backend using Codex OAuth |
| `image_gen/xai` | image backend | Inherited media backend using xAI |
| `spotify` | backend tools | Inherited personal/media tooling; secondary unless a forecast workflow explicitly needs it |
| `hermes-achievements` | dashboard tab | Inherited session-achievement dashboard; not calibration, scoring, or forecast performance |

Memory providers (`plugins/memory/*`) and context engines (`plugins/context_engine/*`) are listed separately on [Memory Providers](./memory-providers). They are supporting recall/context systems, not durable forecast state.

## Forecasting Boundaries

When enabling any bundled plugin, keep these boundaries:

- Do not treat plugin transcripts, summaries, traces, or dashboard panels as evidence until they are added to the forecast ledger.
- Do not let a plugin mutate probability, resolution, score, calibration, or postmortem state directly unless it goes through a forecast-native command or tool action.
- Record model/provider/tool provenance for any plugin output used in a model run or forecast update.
- Prefer scheduled self-checks, watched sources, and `forecast alerts` for forecast maintenance. Use plugins for delivery, capture, tracing, and cleanup around that loop.

## Plugin Details

### disk-cleanup

`disk-cleanup` auto-tracks and removes ephemeral files created during sessions, including test scripts, temporary outputs, cron logs, and stale browser profiles. For the forecast desk, this is mainly workspace hygiene: it should never delete ledger state.

**How it works:**

| Hook | Behaviour |
|---|---|
| `post_tool_call` | When `write_file`, `terminal`, or `patch` creates a file matching temporary/test patterns inside `$HERMES_HOME` or `/tmp/hermes-*`, the plugin tracks it as `test`, `temp`, or `cron-output`. |
| `on_session_end` | If any test files were auto-tracked during the turn, it runs safe `quick` cleanup and logs a one-line summary. |

**Deletion rules:**

| Category | Threshold | Confirmation |
|---|---|---|
| `test` | every session end | Never |
| `temp` | more than 7 days since tracked | Never |
| `cron-output` | more than 14 days since tracked | Never |
| empty dirs under `$HERMES_HOME` | always | Never |
| `research` | more than 30 days, beyond 10 newest | Always for deep cleanup |
| `chrome-profile` | more than 14 days since tracked | Always for deep cleanup |
| files more than 500 MB | never auto | Always for deep cleanup |

**Slash command** - `/disk-cleanup` is available in CLI and gateway sessions after the plugin is enabled:

```text
/disk-cleanup status
/disk-cleanup dry-run
/disk-cleanup quick
/disk-cleanup deep
/disk-cleanup track <path> <category>
/disk-cleanup forget <path>
```

**State** - plugin state lives at `$HERMES_HOME/disk-cleanup/`:

| File | Contents |
|---|---|
| `tracked.json` | Tracked paths with category, size, and timestamp |
| `tracked.json.bak` | Atomic-write backup |
| `cleanup.log` | Append-only audit trail of track, skip, reject, and delete decisions |

**Safety** - cleanup only touches paths under `$HERMES_HOME` or `/tmp/hermes-*`. Windows mounts such as `/mnt/c/...` are rejected. Well-known state directories such as `logs/`, `memories/`, `sessions/`, `cron/`, `cache/`, `skills/`, `plugins/`, `forecasting/`, and `disk-cleanup/` are never removed when empty.

**Enable:**

```bash
superforecasting-agent plugins enable disk-cleanup
```

**Disable:**

```bash
superforecasting-agent plugins disable disk-cleanup
```

### observability/langfuse

`observability/langfuse` traces Superforecasting Agent turns, model calls, and tool invocations to [Langfuse](https://langfuse.com). For forecasting, use it to audit model/tool provenance, runtime cost, and failure patterns around research, source checks, model runs, updates, and scheduled reviews.

Langfuse traces are observability records. They are not a substitute for forecast snapshots, evidence records, model-run provenance, scores, or postmortems.

The plugin is fail-open: no SDK, no credentials, or a transient Langfuse error turns into a no-op. The forecast workflow keeps running.

**Setup:**

```bash
pip install langfuse
superforecasting-agent plugins enable observability/langfuse
```

Put credentials in `~/.superforecasting-agent/.env`:

```bash
HERMES_LANGFUSE_PUBLIC_KEY=pk-lf-...
HERMES_LANGFUSE_SECRET_KEY=sk-lf-...
HERMES_LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

The `HERMES_LANGFUSE_*` names are inherited runtime identifiers. Standard SDK variables (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`) are also accepted.

**How it works:**

| Hook | Behaviour |
|---|---|
| `pre_api_request` / `pre_llm_call` | Opens or reuses a per-turn root span and starts a generation observation with serialized recent context. |
| `post_api_request` / `post_llm_call` | Closes the generation, attaches usage, cost, finish reason, model output, and tool calls. |
| `pre_tool_call` | Starts a child tool observation with sanitized args. |
| `post_tool_call` | Closes the tool observation with sanitized result. Large `read_file` payloads are summarized under `HERMES_LANGFUSE_MAX_CHARS`. |

Session grouping keys off the inherited session ID via `langfuse.propagate_attributes`, so related CLI/gateway/sub-agent work can be inspected together.

**Verify:**

```bash
superforecasting-agent plugins list
forecast status --json
```

Then check the Langfuse UI for a trace from the run.

**Optional tuning** in `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `HERMES_LANGFUSE_ENV` | unset | Environment tag such as `production` or `staging` |
| `HERMES_LANGFUSE_RELEASE` | unset | Release/version tag |
| `HERMES_LANGFUSE_SAMPLE_RATE` | `1.0` | Sampling rate passed to the SDK |
| `HERMES_LANGFUSE_MAX_CHARS` | `12000` | Per-field truncation for message content, tool args, and tool results |
| `HERMES_LANGFUSE_DEBUG` | `false` | Verbose plugin logging to `agent.log` |

**Disable:**

```bash
superforecasting-agent plugins disable observability/langfuse
```

### google_meet

`google_meet` lets the runtime join a Google Meet call, transcribe audio, and optionally speak through the configured TTS provider. In a forecasting workflow, use it for interviews, expert calls, committee meetings, earnings-call style discussions, or postmortem reviews where the transcript may become forecast evidence.

**What it adds:**

- headless browser participation in a Meet URL
- live transcription through the configured STT provider
- `meet_summarize`, `meet_speak`, and `meet_followup` tools
- post-meeting artifacts under `~/.superforecasting-agent/cache/google_meet/<meeting_id>/`

Legacy `~/.hermes/cache/google_meet/<meeting_id>/` remains a migration-compatible cache path.

**Setup:**

```bash
superforecasting-agent plugins enable google_meet
```

The first use prompts for the plugin OAuth flow. Host approval may be required if the meeting restricts participants.

Use meeting output as candidate evidence:

```bash
forecast evidence add <id> --source "google-meet:<meeting-id>" --summary "..."
forecast update <id>
```

Do not let a meeting summary update probability automatically. A reviewer should decide which transcript claims, timestamps, and speaker attributions belong in the ledger.

**Disable:**

```bash
superforecasting-agent plugins disable google_meet
```

Cached transcripts and recordings stay in the cache directory until removed.

### hermes-achievements

`hermes-achievements` is an inherited dashboard-only plugin that generates collectible badges from session history. The plugin name remains unchanged for compatibility.

This plugin is not forecast performance infrastructure. It does not measure calibration, sharpness, Brier score, log score, backtest results, baseline wins, domain error profiles, or postmortem quality. Use `forecast calibration`, `forecast performance`, `forecast backtest`, and `forecast lessons` for those.

**How it works:**

- scans `~/.superforecasting-agent/state.db` session history on the dashboard backend
- caches per-session stats by `(started_at, last_active)` fingerprint
- runs the first scan in a background thread
- stores unlock state under `$HERMES_HOME/plugins/hermes-achievements/state.json`

Legacy `~/.hermes/state.db` remains readable when the active runtime home points there.

**API** - routes mount under `/api/plugins/hermes-achievements/`:

| Endpoint | Purpose |
|---|---|
| `GET /achievements` | Full catalog with per-badge unlock state |
| `GET /scan-status` | Background scanner state |
| `GET /recent-unlocks` | Twenty most recently unlocked badges |
| `GET /sessions/{id}/badges` | Badges earned primarily in one session |
| `POST /rescan` | Manual synchronous rescan |
| `POST /reset-state` | Clear unlock history and cached snapshot |

**Enable:** nothing to enable. It is dashboard-only and registers from `plugins/hermes-achievements/dashboard/manifest.json` when the dashboard loads.

**Opt out:** delete or rename `plugins/hermes-achievements/dashboard/manifest.json`, or override it with a user plugin of the same name under `~/.superforecasting-agent/plugins/hermes-achievements/`.

## Adding a Bundled Plugin

Bundled plugins are written like other plugins. Use [Build a plugin](../../guides/build-a-hermes-plugin) for the API details, then keep the bundled scope tight.

A plugin is a good candidate for bundling when:

- it supports core forecast-desk operation, auditability, source capture, or workspace hygiene
- it has no large optional dependency tree, or dependencies are already part of the supported install set
- it complements forecast workflows without expanding the default model-visible tool surface
- it keeps ledger writes explicit and scoreable
- it can be disabled without changing forecast outcomes already recorded in the ledger

Counter-examples that should stay user-installable:

- third-party integrations with niche API keys
- media or lifestyle tooling unrelated to forecast quality
- large dependency trees
- plugins that mutate probability, score, calibration, or postmortem state outside forecast-native commands
- anything that makes the default product feel like a general-purpose runtime instead of a command-line forecasting desk
