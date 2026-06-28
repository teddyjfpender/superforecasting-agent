# Upstream / competitor watch

A **running** intelligence report. We track three repos and periodically harvest the
genuinely-portable value into our headless superforecasting fork. This doc is the
human-readable companion to `scripts/upstream_watch.py` + `upstream-watch-state.json`.

- **Upstream** — `NousResearch/hermes-agent`. Our actual base. Same stack (Python agent
  + tui_gateway + Ink TUI), so its features are *ports* (low friction, copy-and-adapt).
- **Competitors** — `superagent-ai/grok-cli`, `anomalyco/opencode`. Different stack
  (TypeScript / Bun / OpenTUI / Solid). We harvest **design ideas, not code** — these
  inform architecture, never drop in.

Our north star is narrow: a headless, autonomous, calibration-disciplined forecasting
agent. We deliberately ignore most of what these repos ship (desktop apps, gamification,
multi-tenant relay infra, media generation, remote-control bridges). The filter for
everything below is: *does it make the forecasting loop more correct, cheaper, or more
auditable?*

---

## How to refresh this report

```bash
# 1. See what's new since the last marks (no clone; uses gh API compare)
python scripts/upstream_watch.py            # prints new commit subjects per repo
python scripts/upstream_watch.py --limit 80 # widen the per-repo commit list

# 2. Triage: read the new subjects, pull the interesting commits/files with gh,
#    and run the per-repo deep audit (the agent task that produced the tables below).

# 3. Once triaged, advance the high-water marks and update this doc:
python scripts/upstream_watch.py --update   # writes new SHAs to upstream-watch-state.json
```

Then update: (a) the **Watch state** table below, (b) the per-repo finding tables, and
(c) the **cross-repo adoption backlog** (strike through anything we ported, add new finds).
Keep the marks in this doc in sync with `upstream-watch-state.json`.

> Note: `upstream_watch.py` is the refresh tool (an earlier task description called it
> `upstream_watch.sh` — it's Python). It tracks the repos' *default* branches via the
> `gh` API and stores `{repo: {sha, branch}}` state.

---

## Watch state

| Repo | Role | Baseline mark (high-water) | Branch | Last audited |
|------|------|----------------------------|--------|--------------|
| `NousResearch/hermes-agent` | Upstream — port features | `b31b0b9d95d1` (was `d62979a6f` @ 2026-06-12) | main | 2026-06-28 |
| `superagent-ai/grok-cli` | Competitor — design ideas | `fb97af83f06d` | main | 2026-06-28 |
| `anomalyco/opencode` | Competitor — design ideas | `bda0ddc207db` | dev | 2026-06-28 |

> ⚠️ Mark drift to reconcile: `upstream-watch-state.json` currently records hermes upstream
> at `9a0010fd4` (the watcher's own first baseline). The **audit** above was run against
> `b31b0b9d95d1` as the high-water mark — that is the authoritative mark for the next harvest.
> Bump the JSON to `b31b0b9d95d1` on the next `--update` so the two agree.

Audit deltas this cycle: ~1705 non-merge commits on hermes upstream since `d62979a6f`.

---

## 1. `NousResearch/hermes-agent` (upstream — same stack, real ports)

**Summary.** Of ~1705 commits since our last mark, the bulk is *not for us*: an Electron
desktop app, a "pets" gamification surface, and a large gateway/relay/multiplex/scale-to-zero
infra build-out (multi-platform-per-agent, dormant-quiesce, Chronos NAS cron, profile
multiplexing) — all orthogonal to a headless forecasting fork. The portable value clusters
in four areas: **(1) agent capabilities** (verification-before-finish, a stateless one-shot
LLM helper, always-background delegation), **(2) skills** (`/learn`, risk-tiered simplify),
**(3) security/correctness** (a startup posture audit + redaction fixes — one of which
reproduces *verbatim* in our `agent/redact.py`), and **(4) retrieval/context quality**
(office/notebook extraction in `read_file`, lossless `search_files` densification, dynamic
context-file caps). **All top candidate files are absent from our fork** — confirmed real
ports, not already-applied.

### Agent features

| Feature | Effort | What / why adopt | Where (commits / files) |
|---------|--------|------------------|-------------------------|
| **Redaction correctness fixes** | low | Two bugs: (1) replayed-history redaction made the model read back `PGPASSWORD='***'` and copy the placeholder, breaking credentialed commands on turn 2; (2) the greedy `_AUTH_HEADER_RE` `\S+` token class eats a closing quote when a token abuts it → shell/EOF errors. **The identical regex `(Authorization:\s*Bearer\s+)(\S+)` is live in our `agent/redact.py:139` right now.** | `bbe1bf404` (`agent/redact.py` regex + `build_assistant_message`); `c1c179a23` (env-dump/bg); `674e16e7c` (DB-connstr over-redaction); `3b56d3a29`/`5b45fb269` (kanban) |
| **One-shot stateless LLM helper + `llm.oneshot` RPC** | medium | `run_oneshot()`: a single stateless model call *outside* any conversation — never touches session history, never breaks prompt caching, returns plain text. We hand-roll aux calls for titles/thesis summaries/desk-notes/lesson-compile; this is the sanctioned path to consolidate them onto, riding our existing tui_gateway long-handler plumbing. | `211ba9c7d` — `agent/oneshot.py`, `tui_gateway/server.py` (`llm.oneshot`) |
| **Verification-before-finish (closure system)** | high | Forces the agent to run a verification command + record evidence before it can stop after file edits; bounded retries; ad-hoc scripts count when no canonical suite exists; evidence goes stale on workspace change; default-OFF switch. Maps directly onto our `cycle run --agent` autonomous reforecast loop (the agent already runs scoring/benchmark scripts) — evidence-gated stop kills premature "looks done." Pairs with our forecast-hooks saturation gates. | `fcbdf3c35`, `2f1a47b90`, `a5a2edd45`, `7ef0f360d`; default-OFF in `60f58a2b9` — `agent/verification_evidence.py`, `verification_stop.py`, `conversation_loop.py`, `turn_context.py`, `hermes_cli/config.py` |
| **Background-review aux selector + curator prune-only default** | medium | `auxiliary.background_review.{provider,model}` routes post-turn self-improvement review to a cheaper model (~3-5× cost cut) with cache-aware digest replay; curator defaults to prune-only (LLM consolidation opt-in). Cost-control knobs on aux machinery we already run for lessons/curation. | `87c4a5ebb`, `7bbffceb9` |
| **MoA reference-model loop (advisory cross-checking)** | high | Mixture-of-Agents: reference models see full tool state, re-run on every user message + tool result, surface as labelled blocks before the aggregator. *On-thesis but speculative* — our whole edge is ensemble/aggregation discipline; an advisory panel judging the in-progress forecast at each tool step is conceptually our "superforecaster panel" as a live loop. `agent/moa_loop.py` is **absent** from our fork → from-scratch port. | `7c38249c7`, `3b44a3c8b`, `163cb24d4`, `c6575df92`, `50f685521` — `agent/moa_loop.py` |

### Skills

| Feature | Effort | What / why adopt | Where |
|---------|--------|------------------|-------|
| **`/learn` — distill a skill from any source** | medium | Takes a dir/URL/the workflow just walked/pasted notes; the live agent gathers it with existing tools and authors a `SKILL.md` via `skill_manage`. Engine-free (a standards-guided prompt as a normal turn); works on any backend. Feeds the lesson-enforcement/skill flywheel our fork already invests in — the SF agent could capture a forecasting workflow it just executed into a durable skill. | `e32ebc6aa` — `agent/learn_prompt.py`, `cli.py`, `gateway/run.py`, `hermes_cli/cli_commands_mixin.py`, `hermes_cli/commands.py` |
| **Risk-tiered simplify-code skill** | low | SAFE/CAREFUL/RISKY tiering (safe auto, careful per-file verified, risky human-flagged), Chesterton's Fence (`git blame` before removal), AI-slop + silent-failure (`except: pass`) detection, structured reviewer output. We already run `/simplify` + `/code-review` on ledger/forecast code; tiering materially reduces the chance an auto-simplification breaks a calibration path. Skill-only, no engine change. | `db744e7d1` — `optional-skills/simplify-code` |

### Retrieval / context quality

| Feature | Effort | What / why adopt | Where |
|---------|--------|------------------|-------|
| **`read_file` office/notebook extraction** | low | Stdlib-only `.ipynb` / `.docx` / `.xlsx` extraction inside `read_file`, lazy + malformed-doc fallback, **no new hard deps**. Forecasting evidence routinely arrives as spreadsheets (polls, econ series, tallies) and `.docx` memos the agent currently can't read. Immediately widens evidence ingestion. | `817f39231` — `tools/read_extract.py`, `tools/file_tools.py` |
| **`search_files` lossless densification** | low | Path-grouped lossless densification of content-mode results: consecutive same-path matches under one path header with indented `<line>: <content>`. ~57.8% mean token cut on a 422-output corpus, fires on 97%, gated ≥5 matches, default-off per-caller. Behavior-safe (preserves every byte + ripgrep ordering). Pure token win on a tool the agent calls constantly during research. | `22b6942fc` — `search_files` `to_dict(densify=...)` |

### Security / operability

| Feature | Effort | What / why adopt | Where |
|---------|--------|------------------|-------|
| **Startup security-posture audit (warn-on-load)** | low | One-shot from `start_gateway()`: warns (never blocks) on running as root, SSH `PasswordAuthentication` on, containerized with no persistent volume over `HERMES_HOME`, and network-accessible API server with no `API_SERVER_KEY`. Cross-platform, each check fail-safe. We expose a web/forecast bridge + gateway → cheap operator-safety signal, no behavioral risk, drops in standalone. | `f45ace931` — `hermes_cli/security_audit_startup.py`, `gateway/run.py` |

### QoL CLI/TUI commands (one commit cluster)

`2ba1cfeb2` `/goal` completion contracts (outcome/verification/constraints/boundaries/`stop_when`
— evidence-based done-judging; shares the philosophy we want for autonomous forecast goals) ·
`9e96e7099` `/prompt` opens `$EDITOR` · `95d53c3bc` `/reasoning full` (complete thinking vs
10-line clamp — helps audit calibration reasoning) · `5ff11a689` `/timestamps` in `/history`.
All ride existing slash-command plumbing.

### Upstream TUI work in range

Mostly status-bar plumbing for the always-background delegation model: `72bfc48e6`/`70d28b62f`
track background subagents in the CLI/TUI status bar; `7f02f30b7` adds a width-budgeted
"resumes when subagent finishes" segment. **Per memory we already ported the async-subagent
backbone (`c66ecf0bc`) and route completions by `session_key`** — so these status-bar segments
(bg count + "will resume" notice) are the natural TUI follow-on to surface work we already have.
`74f0dd62e` Ctrl+G submit-on-save in `$EDITOR`; `95d53c3bc` `/reasoning full` renders as an
expand/collapse section. **Ignore** the desktop/Electron + "pets" surface (floating pet, Pokedex,
inline embeds, Shiki diffs, timeline rail) — irrelevant to a terminal-first forecasting TUI.

---

## 2. `superagent-ai/grok-cli` (competitor — TS, ideas only)

**Summary.** Open-source TypeScript coding agent for the Grok API (~3k★). Bun runtime,
`@opentui/react` TUI, Vercel AI SDK (`streamText` / `ToolSet`). Strengths: a clean agent loop
with streaming observers, a delegation system for parallel background tasks, MCP integration,
SQLite session/context persistence, a broad tool ecosystem, provider-agnostic model handling,
sandbox isolation (Shuru microVM), reasoning-effort control, batch API, Telegram remote control.
**Caveat:** the agent core is a monolithic `agent.ts` (2830 lines) and `app.tsx` is 5862 lines —
architectural debt; modularize earlier if borrowing patterns. *Everything here is an idea to
adapt into Python, not code to port.*

| Idea | Effort | What / why borrow | Where (paths under `/tmp/upstream-watch/grok-cli/`) |
|------|--------|-------------------|------|
| **Streaming observer pattern + semantic chunks** | medium | `ProcessMessageObserver` (`onStepStart/Finish`, `onToolStart/Finish`, `onError`) decouples agent state from rendering; UI yields a discriminated `StreamChunk` union (content/tool_calls/tool_result/step_finish/error/plan/delegation/subagent_status); a headless emitter turns the same chunks into JSONL. The decoupling is the lesson — Python can use `@dataclass`/pydantic discriminated unions + async generators. Enables custom output formatters (text/JSON) and hookable tool boundaries without coupling. | `src/agent/agent.ts` (151-157, 1824-2050), `src/types/index.ts` (`StreamChunk`), `src/headless/output.ts` |
| **Agent turn orchestration via `streamText`** | high | Single async-generator loop (`processMessage`) handles tool execution, error recovery, persistence, and usage in one place, with lifecycle observers. Reference for a clean interactive+batch turn loop. | `src/agent/agent.ts` (1324, 1942, 1824-2050) |
| **Tool registry + pre/post hook integration** | medium | `createTools()` centralizes definitions; each tool wraps a Zod schema for input validation and runs `executePreToolHooks`/`executePostToolHooks` (user shell commands on hook events) → operators can intercept/block/log tool calls. Structured `ToolResult` (success/output/media/error) enables semantic logging. | `src/grok/tools.ts`, `src/hooks/`, `src/tools/{bash,file,grep,computer}.ts` |
| **Session persistence + context recovery** | medium | SQLite `SessionStore` persists messages/metadata/usage/recaps per session; `loadTranscript` rebuilds history, `--session latest` resumes, auto-titles + `generateRecap` summaries. Python+SQLite parity is trivial; per-session token budgets feed compaction. | `src/storage/{sessions,transcript,usage}.ts` |
| **Context compaction + sliding window** | high | `shouldCompactContext()` estimates tokens → `generateCompactionSummary` (LLM recap) + `prepareCompaction` (synthetic message tree); tunable keep/reserve thresholds. LLM summaries > truncation for long forecast sessions. | `src/agent/compaction.ts` |
| **Delegations: background task spawning + polling** | high | `DelegationManager` spawns detached child processes for read-only tasks (explore agent); per-delegation ID + JSON job file + output markdown + status; `consumeNotifications()` injects results as system messages. Non-blocking `delegation_list/read`. (We already have an async-subagent backbone — this is a richer reference for persistent job state surviving crashes.) | `src/agent/delegations.ts`, `src/agent/agent.ts` (931-954) |
| **Reasoning-effort control + multi-model dispatch** | medium | `ReasoningEffort` (low/med/high) per model; explore uses a fast non-reasoning variant, verify/general use reasoning; `stepCountIs` budgets the loop. Fast-explore-then-reason maps onto cheap-scan-then-deep-forecast. | `src/grok/{models,client}.ts`, `src/agent/agent.ts` (1329-1332) |
| **Model/provider abstraction + alias resolution** | low | `normalizeModelId` maps aliases→canonical; feature flags (`supportsClientTools`, `supportsMaxOutputTokens`) decouple tool availability from model. Future-proofs model renames. | `src/grok/{models,client}.ts` |
| **Slash-command routing + custom sub-agents** | low | `SLASH_MENU_ITEMS` + `parseKeypress` route to handlers; custom sub-agents loaded from user settings wrap a prompt in a task instruction. Extensible command-palette pattern. | `src/ui/slash-menu.ts`, `src/ui/app.tsx` (2259-2330) |
| **Workspace trust + sandbox gating** | medium | First-run `promptWorkspaceTrust()` (Shuru sandbox vs host), choice persisted; `--sandbox/--no-sandbox` override. UX pattern for untrusted-repo detection. | `src/index.ts` (192-249), `src/utils/settings.ts`, `src/tools/bash.ts` |

**Explicitly skip:** Telegram bridge (`src/telegram/*` — remote-control, off-thesis), media
generation / vision (`src/grok/media.ts`, `src/agent/vision-input.ts` — image/video gen,
computer automation), batch API path (`src/grok/batch.ts` — adds latency for our interactive
loop), OpenTUI React UI itself (different stack — borrow the *streaming-loop* and *modal* shapes,
not the components), LSP (`src/lsp/` — code-nav, not forecasting). The monolithic `app.tsx`
(5862 lines) is an anti-pattern to *learn from*, not copy.

---

## 3. `anomalyco/opencode` (competitor — TS, ideas only; the architecturally strongest)

**Summary.** A 180k★ TypeScript agent with a professionally-tiered architecture: (1) an LLM
abstraction over 13+ providers; (2) a **session-centric core** with durable history,
**context-epoch** management, mid-conversation system-message injection, a permission-gated tool
registry, and resumable provider turns *without replay re-execution*; (3) an elegant OpenTUI/Solid
TUI (command palette, modal stack, plugin system, 35+ themes, keymap layering, thinking toggle);
(4) a zero-coupling plugin ecosystem. **The session/context architecture is the standout** — it
solves compaction + recovery without stale-context reinjection, which is exactly the class of
problem our long autonomous forecast turns hit. *Ideas to adapt, not code to port.*

| Idea | Effort | What / why borrow | Where (paths under `/tmp/upstream-watch/opencode/`) |
|------|--------|-------------------|------|
| **Durable session + context-epoch architecture** | high | Sessions persist history durably while assembling runtime context. **Context Epochs** partition provider-cache baselines from mid-conversation system messages; lazy reconciliation samples context sources only at provider-turn boundaries; changed state injects chronologically *without re-execution*; tool output bounded with managed-file fallback; exact-retry reconciles by session/prompt/delivery match, not replay. Solves compaction/recovery without stale reinjection — directly on-point for our long forecast sessions. | `packages/core/src/session/*.ts`, `CONTEXT.md` (200-line spec) |
| **System-context reconciliation pattern** | high | Context sources (project instructions, skills list, date) register with stable keys; `reconcile()` lazily samples all at once → `{unchanged\|updated\|replacement_ready\|replacement_blocked}`; stale-while-revalidate for unavailable sources. Eliminates stale-context re-injection; our skills/date/lesson context could register the same way. | `CONTEXT.md` (106-122), `packages/core/src/system-context/` |
| **Tool registry with permission gating** | medium | Dynamic `ToolRegistry.register({name})` scoped to a `Scope`; `materialize({permissions})` filters; `settle` binds agent/session/permission to each call; **tool output bounded** (truncated preview in history, complete text in a managed `/tmp` file with stable path); stale-call detection via identity object. Tool-output bounding + managed-file fallback is the reusable trick for stdout explosions in research. | `packages/core/src/tool/registry.ts`, `CONTEXT.md` |
| **Keymap layering + mode stack** | low | `createOpencodeModeStack(keymap)` — nested mode symbols, `push(mode)` returns a cleanup fn, `current()` snapshots active mode; leader key w/ timeout; binding aliases (`enter→return`). Symbol-scoped stack eliminates modal-collision bugs; each layer owns its cleanup. Low-effort, high-reliability TUI pattern. | `packages/tui/src/keymap.tsx` (53-110) |
| **Streaming + event batching** | medium | SDK context subscribes to durable session events via SSE; events batch on a **16ms** debounce to sync renders (`batch(() => …)`); live-only stream distinct from durable `sessions.events({sessionID, after})` with cursor-based continuation. 16ms batching prevents render thrashing on high-frequency events. | `packages/tui/src/context/sdk.tsx` (54-80), `routes/session/index.tsx` |
| **Thinking/reasoning visibility toggle** | low | `ReasoningPart` extraction; thinking mode cycles hidden/collapsed/expanded; summary shows step count + first 50 chars; opacity theme config; toggle persisted to KV. Makes LLM reasoning a first-class UI primitive — useful for auditing calibration reasoning in our desk views. | `packages/tui/src/context/thinking.ts`, `routes/session/index.tsx` (76, 127-130) |
| **Agent abstraction + subagent system** | medium | Keyed agents (build/plan/general) with layered permission rulesets; **plan agent read-only by default** (denies edits, asks before bash); `@general` subagent for complex searches; schema stores mode/permission/model/temp/topP/steps. A read-only "explore/forecast-research" agent maps onto our pipeline. | `packages/opencode/src/agent/agent.ts` (35-150) |
| **Skill discovery + permission-gated exposure** | medium | Skills discovered from config, listed in agent system context (name+description, permission-checked); **bodies exposed only via the `skill` tool** (permission-checked) at safe provider-turn boundaries; skill changes produce a mid-conversation system message. Reduces token waste on hidden skills; agent-specific skill filtering. | `packages/opencode/src/agent/agent.ts` (102-107), `CONTEXT.md` (122-124) |
| **Multi-provider LLM abstraction** | high | Unified streaming over 13+ providers with provider-semantic options namespaced while generation controls stay neutral; single `llm.stream(request)` per turn; history re-projection before durable continuation. Eliminates lock-in; native mid-session model switching with graceful reasoning downgrade. | `packages/llm/src/{provider,llm}.ts`, `providers/*`, `route/*.ts` |
| **Model switching + continuity** | medium | `sessions.switchModel()` preserves Context Epoch + history; reasoning metadata dropped on incompatible model; native continuation metadata kept only for exact provider/model match (a "provider fence" against cross-model hallucination). | `CONTEXT.md` (134-135, 167), `packages/core/src/model.ts` |
| **TUI plugin system (Solid + OpenTUI)** | medium | Plugins declare routes/keybindings/commands/tools/themes via `@opencode-ai/plugin/tui`; **plugins never import core/server — the SDK is the boundary**; theme-only packages via an `oc-themes` array; KV-persisted enable state; framework-agnostic export shape. The zero-coupling boundary is the lesson. | `packages/plugin/src/tui.ts`, `packages/opencode/specs/tui-plugins.md` |
| **Command palette + dialog system** | low | Modal-stack dialogs (alert/confirm/select/prompt/help); `CommandPaletteDialog` fuzzy-searches registered commands; `useDialog` lifecycle; slash → command invocation. Reduces interactive-UX boilerplate. | `packages/tui/src/ui/dialog*.tsx`, `component/command-palette.tsx` |
| **Theme system (35+ presets)** | low | JSON theme assets (catppuccin/dracula/gruvbox/nord/tokyonight…) with RGBA; semantic tokens incl. diff/markdown/syntax/thinking-opacity; `selectedForeground()` contrast calc. Portable color *taxonomy* even though we're on Ink, not Solid. | `packages/tui/src/theme/index.ts`, `theme/assets/*.json` |

**Explicitly skip:** the OpenTUI/Solid rendering stack itself (we're Python+Ink — borrow the
*patterns* above, not the framework), the workspace/location-scoping machinery
(`packages/core/src/location*.ts` — multi-workspace PTY overlays, beyond our single-repo loop),
and the full 13-provider matrix (we have a fixed small provider set — take the *abstraction shape*,
not the breadth).

---

## Cross-repo ranked adoption backlog

Ranked by value-to-effort. **Tier A = port from upstream hermes** (same stack, low friction,
copy-and-adapt). **Tier B = adapt a design idea** from grok-cli/opencode (different TS stack —
idea, not code).

### Tier A — port from upstream `hermes-agent` (do these first)

| # | Item | Effort | Why now (value) | From |
|---|------|--------|-----------------|------|
| 1 | **Redaction correctness fixes** (`bbe1bf404` + `c1c179a23` + `674e16e7c`) | low | **Live bug in our tree:** the greedy `(Authorization:\s*Bearer\s+)(\S+)` regex is verbatim at `agent/redact.py:139`; it corrupts any tool call where a bearer token abuts a quote. The history-redaction fix is correctness for multi-turn credentialed commands. Small, real, immediate. | hermes |
| 2 | **`read_file` office/notebook extraction** (`817f39231`) | low | Stdlib-only `.ipynb`/`.docx`/`.xlsx` — directly widens evidence ingestion (polls/econ-series spreadsheets, analyst `.docx` memos the agent can't read today). No new hard deps, no behavioral risk. | hermes |
| 3 | **One-shot stateless LLM helper** (`211ba9c7d`) | medium | A sanctioned stateless path to consolidate our aux-model calls (titles/thesis-summaries/desk-notes/lesson-compile) that won't pollute the forecast thread or invalidate the cache. Rides our existing tui_gateway long-handler plumbing. | hermes |
| 4 | **`search_files` lossless densification** (`22b6942fc`) | low | ~58% token cut on a tool the agent calls constantly during research; behavior-safe (every byte + ripgrep ordering preserved). Cuts context pressure in long forecast research turns. | hermes |
| 5 | **`/learn` skill distillation** (`e32ebc6aa`) | medium | Feeds the lesson-enforcement/skill flywheel we already invest in: the SF agent captures a forecasting workflow it just ran into a durable `SKILL.md`. Engine-free, any backend. | hermes |
| 6 | **Startup security-posture audit** (`f45ace931`) | low | We expose a web/forecast bridge + gateway; cheap operator-safety warnings (root, SSH password-auth, no-volume container, keyless network API) with zero behavioral risk. Drops in standalone. | hermes |
| 7 | **Risk-tiered simplify-code skill** (`db744e7d1`) | low | We already run `/simplify` on ledger/forecast code; SAFE/CAREFUL/RISKY tiering + silent-failure (`except: pass`) detection cuts the chance an auto-simplification breaks a calibration path. Skill-only. | hermes |
| 8 | **Verification-before-finish** (`fcbdf3c35` + `2f1a47b90` + `a5a2edd45`) | high | Evidence-gated stop maps onto our `cycle run --agent` autonomous reforecast loop (the agent already runs scoring/benchmark scripts) → kills premature "looks done" on forecast updates. Pairs with our forecast-hooks saturation gates. Higher effort, high leverage. | hermes |
| 9 | **Background-review aux selector + curator prune-only** (`87c4a5ebb` + `7bbffceb9`) | medium | Cost-control on aux machinery we already run for lessons/curation — cheaper model for post-turn review, no aux cost when curation off. Config-shaped, low-risk. | hermes |
| 10 | **Background-subagent status-bar segments** (`72bfc48e6`/`70d28b62f`/`7f02f30b7`) | low | We already ported the async backbone (`c66ecf0bc`); these surface the bg-count + "will resume" notice we lack. Natural TUI follow-on to existing work. | hermes |
| 11 | **`/goal` contracts + `/reasoning full`** (`2ba1cfeb2` + `95d53c3bc`) | medium | `/goal` contracts share the evidence-based-completion philosophy we want for autonomous forecast goals; `/reasoning full` helps audit calibration reasoning in desk views. Ride existing slash-command plumbing. | hermes |
| 12 | **MoA reference-model loop** (`7c38249c7` + chain) | high | *Speculative, on-thesis:* an advisory panel of reference models judging the in-progress forecast at each tool step is conceptually our superforecaster panel as a live loop. `agent/moa_loop.py` absent → from-scratch. Evaluate before committing. | hermes |

### Tier B — adapt a design idea (TS competitors → our Python/Ink stack)

| # | Item | Effort | Why (value) | From |
|---|------|--------|-------------|------|
| 13 | **Keymap mode-stack** (symbol-scoped push/cleanup) | low | Eliminates modal-collision bugs as our TUI grows lens-tabs/modals (Markets/Desk redesign). Low-effort, high-reliability; translate the symbol-stack to Ink. | opencode |
| 14 | **Thinking/reasoning visibility toggle** | low | Makes LLM reasoning a first-class, collapsible UI primitive — directly useful for auditing calibration reasoning in desk views (complements hermes `/reasoning full`). | opencode |
| 15 | **Streaming observer pattern + semantic chunks** | medium | Decouple TUI rendering from agent logic via an async-generator + discriminated `StreamChunk` union (Python `@dataclass`/pydantic). Enables headless JSON + rich TUI from one event stream. | grok-cli |
| 16 | **Tool-output bounding + managed-file fallback** | medium | The reusable trick from opencode's tool registry: truncated preview in history, full text in a stable `/tmp` file — prevents stdout explosions blowing our research-turn context. Adopt even without the full registry. | opencode |
| 17 | **Streaming event batching (16ms debounce)** | medium | Batch high-frequency stream events on a frame budget to stop render thrashing during long streamed forecasts. Framework-agnostic timing pattern. | opencode |
| 18 | **System-context reconciliation** (lazy sample + stale-while-revalidate) | high | Register our skills/date/lesson context as keyed sources reconciled at turn boundaries → no stale-context reinjection in long autonomous loops. The single highest-architectural-value idea, but a real build. | opencode |
| 19 | **Durable session + context-epoch architecture** | high | The gold-standard answer to compaction/recovery without stale reinjection — on-point for our long forecast sessions, but a large core change. Study `CONTEXT.md` before any compaction rework. | opencode |
| 20 | **Permission-gated agent abstraction** (read-only "plan" agent) | medium | A read-only explore/forecast-research agent (denies edits, asks before bash) reduces accidental destructive actions in the autonomous loop. | opencode |
| 21 | **Reasoning-effort control + multi-model dispatch** | medium | Cheap non-reasoning scan → reasoning deep-forecast, mirroring grok-cli's explore/verify split. Maps onto cheap-scan-then-deep-forecast cost discipline. | grok-cli |
| 22 | **Zero-coupling TUI plugin boundary** (SDK-as-boundary) | medium | If we ever open the TUI to plugins, the "plugins never import core, SDK is the boundary, themes decouple from code" shape is the right contract. Lower priority for a single-purpose fork. | opencode |

---

## What we should NOT adopt (and why)

- **Electron desktop app + "pets" gamification** (hermes upstream) — entire surface is for a
  consumer desktop product; we are headless/terminal-first. Pure noise for a forecasting fork.
- **Gateway/relay/multiplex/scale-to-zero infra** (hermes upstream) — multi-platform-per-agent,
  dormant-quiesce, Chronos NAS cron, profile multiplexing. Solves multi-tenant hosting we don't do.
- **Media generation + vision + computer automation** (grok-cli) — image/video gen, screenshots,
  accessibility-tree automation. No place in evidence-driven forecasting.
- **Telegram / remote-control bridges** (grok-cli) — off-thesis remote UX; we drive the agent
  locally + via our own web/forecast bridge.
- **Batch API path** (grok-cli) — adds latency that hurts our interactive reforecast loop; the
  cost angle is better served by hermes's background-review aux selector (#9).
- **LSP code-intelligence** (grok-cli) — symbol nav for code editing, not forecasting research.
- **The OpenTUI/Solid + `@opentui/react` rendering stacks themselves** (grok-cli, opencode) — we
  are Python+Ink. Borrow the *patterns* (mode-stack, streaming batching, modal stack, theme
  taxonomy), never the framework code. Note grok-cli's monolithic `agent.ts` (2830 lines) and
  `app.tsx` (5862 lines) are explicit anti-patterns — modularize if borrowing.
- **Workspace/location-scoping + 13-provider matrix** (opencode) — multi-workspace PTY overlays and
  provider breadth beyond our fixed small set; take the *abstraction shapes*, not the scale.

---

## Top 5 adoption candidates (this cycle)

1. **Redaction correctness fixes** (hermes `bbe1bf404`+`c1c179a23`+`674e16e7c`, low) — the
   quote-eating auth regex is **live in our `agent/redact.py:139` right now**; fixes real
   credential-command corruption. Highest value-to-effort; do first.
2. **`read_file` office/notebook extraction** (hermes `817f39231`, low) — stdlib-only
   `.ipynb`/`.docx`/`.xlsx`; immediately widens forecasting evidence ingestion, no new deps.
3. **One-shot stateless LLM helper** (hermes `211ba9c7d`, medium) — clean sanctioned path to
   consolidate our aux title/thesis/desk-note/lesson calls without polluting the forecast thread
   or breaking the cache; rides existing tui_gateway plumbing.
4. **`search_files` lossless densification** (hermes `22b6942fc`, low) — ~58% token cut on a
   constantly-used research tool, behavior-safe.
5. **`/learn` skill distillation** (hermes `e32ebc6aa`, medium) — feeds the lesson/skill flywheel
   we already invest in; lets the SF agent capture a forecasting workflow it just ran into a
   durable skill.
