---
sidebar_position: 5
title: "Prompt Assembly"
description: "How Superforecasting Agent builds prompt layers."
---

# Prompt Assembly

Superforecasting Agent deliberately separates:

- **cached system prompt state**
- **ephemeral API-call-time additions**
- **forecast protocol overlays**

This is one of the most important design choices in the project because it affects:

- token usage
- prompt caching effectiveness
- session continuity
- memory correctness
- forecast-desk behavior and auditability

Primary files:

- `run_agent.py`
- `agent/prompt_builder.py`
- `forecasting/protocol.py`
- `tools/memory_tool.py`

## Cached system prompt layers

The cached system prompt is assembled in roughly this order:

1. agent identity - `SOUL.md` from the active runtime home when available, otherwise falls back to `DEFAULT_AGENT_IDENTITY` in `prompt_builder.py`
2. tool-aware behavior guidance
3. Honcho static block (when active)
4. optional system message
5. frozen MEMORY snapshot
6. frozen USER profile snapshot
7. skills index
8. context files (`AGENTS.md`, `.cursorrules`, `.cursor/rules/*.mdc`) - SOUL.md is **not** included here when it was already loaded as the identity in step 1
9. timestamp / optional session ID
10. platform hint

When `skip_context_files` is set (e.g., subagent delegation), SOUL.md is not loaded unless `load_soul_identity=True`, and the hardcoded `DEFAULT_AGENT_IDENTITY` is used instead. That fallback is forecast-desk oriented; CLI, TUI, and one-shot chat also add the forecast-scoped overlay from `forecasting.protocol.build_forecast_chat_system_prompt()`.

### Concrete example: assembled system prompt

Here is a simplified view of what the final system prompt looks like when all layers are present (comments show the source of each section):

```
# Layer 1: Agent Identity (from ~/.superforecasting-agent/SOUL.md)
You are Superforecasting Agent, a command-line forecasting desk.
You turn uncertain questions into scoreable forecasts with clear
resolution criteria, timestamped evidence, base rates, explicit
assumptions, auditable probability updates, and post-resolution learning.
...

# Layer 2: Tool-aware behavior guidance
You have persistent memory across sessions. Save durable facts using
the memory tool: user preferences, environment details, tool quirks,
and stable conventions. Memory is injected into every turn, so keep
it compact and focused on facts that will still matter later.
Forecast probabilities, evidence, postmortems, calibration lessons,
and domain error records belong in the forecast ledger rather than
general chat memory.
...
When the user references something from a past conversation or you
suspect relevant cross-session context exists, use session_search
to recall it before asking them to repeat themselves.

# Tool-use enforcement (for GPT/Codex models only)
You MUST use your tools to take action — do not describe what you
would do or plan to do without actually doing it.
...

# Layer 3: Honcho static block (when active)
[Honcho personality/context data]

# Layer 4: Optional system message (from config or API)
[User-configured system message override]

# Layer 5: Frozen MEMORY snapshot
## Persistent Memory
- User prefers Python 3.12, uses pyproject.toml
- Default editor is nvim
- Working on project "atlas" in ~/code/atlas
- Timezone: US/Pacific

# Layer 6: Frozen USER profile snapshot
## User Profile
- Name: Alice
- GitHub: alice-dev

# Layer 7: Skills index
## Skills (mandatory)
Before replying, scan the skills below. If one clearly matches
your task, load it with skill_view(name) and follow its instructions.
...
<available_skills>
  software-development:
    - code-review: Structured code review workflow
    - test-driven-development: TDD methodology
  research:
    - arxiv: Search and summarize arXiv papers
</available_skills>

# Layer 8: Context files (from project directory)
# Project Context
The following project context files have been loaded and should be followed:

## AGENTS.md
This is the atlas project. Use pytest for testing. The main
entry point is src/atlas/main.py. Always run `make lint` before
committing.

# Layer 9: Timestamp + session
Current time: 2026-03-30T14:30:00-07:00
Session: abc123

# Layer 10: Platform hint
You are a CLI AI Agent. Try not to use markdown but simple text
renderable inside a terminal.

# Ephemeral forecast overlay (not cached)
You are Superforecasting Agent, a command-line forecasting desk.
Treat free-form chat as forecast-scoped work...
```

## How SOUL.md appears in the prompt

`SOUL.md` lives at `~/.superforecasting-agent/SOUL.md` for new installs, with legacy `~/.hermes/SOUL.md` homes still readable during the fork transition. It serves as the agent's identity: the very first section of the cached system prompt. The loading logic in `prompt_builder.py` works as follows:

```python
# From agent/prompt_builder.py (simplified)
def load_soul_md() -> Optional[str]:
    soul_path = get_hermes_home() / "SOUL.md"  # fork-native home with legacy fallback
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    content = _scan_context_content(content, "SOUL.md")  # Security scan
    content = _truncate_content(content, "SOUL.md")       # Cap at 20k chars
    return content
```

When `load_soul_md()` returns content, it replaces the hardcoded `DEFAULT_AGENT_IDENTITY`. The `build_context_files_prompt()` function is then called with `skip_soul=True` to prevent SOUL.md from appearing twice (once as identity, once as a context file).

If `SOUL.md` doesn't exist, the system falls back to:

```
You are Superforecasting Agent, a command-line forecasting desk.
You help users turn uncertain questions into scoreable forecasts with clear
resolution criteria, timestamped evidence, base rates, explicit assumptions,
auditable probability updates, and post-resolution learning.
```

## How context files are injected

`build_context_files_prompt()` uses a **priority system** — only one project context type is loaded (first match wins):

```python
# From agent/prompt_builder.py (simplified)
def build_context_files_prompt(cwd=None, skip_soul=False):
    cwd_path = Path(cwd).resolve()

    # Priority: first match wins — only ONE project context loaded
    project_context = (
        _load_hermes_md(cwd_path)       # 1. .hermes.md / HERMES.md (walks to git root)
        or _load_agents_md(cwd_path)    # 2. AGENTS.md (cwd only)
        or _load_claude_md(cwd_path)    # 3. CLAUDE.md (cwd only)
        or _load_cursorrules(cwd_path)  # 4. .cursorrules / .cursor/rules/*.mdc
    )

    sections = []
    if project_context:
        sections.append(project_context)

    # SOUL.md from the active runtime home (independent of project context)
    if not skip_soul:
        soul_content = load_soul_md()
        if soul_content:
            sections.append(soul_content)

    if not sections:
        return ""

    return (
        "# Project Context\n\n"
        "The following project context files have been loaded "
        "and should be followed:\n\n"
        + "\n".join(sections)
    )
```

### Context file discovery details

| Priority | Files | Search scope | Notes |
|----------|-------|-------------|-------|
| 1 | `.hermes.md`, `HERMES.md` | CWD up to git root | Inherited project config filenames |
| 2 | `AGENTS.md` | CWD only | Common agent instruction file |
| 3 | `CLAUDE.md` | CWD only | Claude Code compatibility |
| 4 | `.cursorrules`, `.cursor/rules/*.mdc` | CWD only | Cursor compatibility |

All context files are:
- **Security scanned** — checked for prompt injection patterns (invisible unicode, "ignore previous instructions", credential exfiltration attempts)
- **Truncated** — capped at 20,000 characters using 70/20 head/tail ratio with a truncation marker
- **YAML frontmatter stripped** — `.hermes.md` frontmatter is removed (reserved for future config overrides)

## API-call-time-only layers

These are intentionally *not* persisted as part of the cached system prompt:

- `ephemeral_system_prompt`
- forecast-session overlays from `forecasting.protocol.build_forecast_chat_system_prompt()`
- prefill messages
- gateway-derived session context overlays
- later-turn Honcho recall injected into the current-turn user message

This separation keeps the stable prefix stable for caching.

## Memory snapshots

Local memory and user profile data are injected as frozen snapshots at session start. Mid-session writes update disk state but do not mutate the already-built system prompt until a new session or forced rebuild occurs. Forecast learning artifacts are different: probabilities, evidence, model runs, scores, postmortems, calibration lessons, and domain error profiles live in the forecast ledger and are loaded into forecast commands through structured context packets, not as generic memory prose.

## Context files

`agent/prompt_builder.py` scans and sanitizes project context files using a **priority system** — only one type is loaded (first match wins):

1. `.hermes.md` / `HERMES.md` (walks to git root)
2. `AGENTS.md` (CWD at startup; subdirectories discovered progressively during the session via `agent/subdirectory_hints.py`)
3. `CLAUDE.md` (CWD only)
4. `.cursorrules` / `.cursor/rules/*.mdc` (CWD only)

`SOUL.md` is loaded separately via `load_soul_md()` for the identity slot. When it loads successfully, `build_context_files_prompt(skip_soul=True)` prevents it from appearing twice.

Long files are truncated before injection.

## Skills index

The skills system contributes a compact skills index to the prompt when skills tooling is available.

## Supported prompt customization surfaces

Most users should treat `agent/prompt_builder.py` and `forecasting/protocol.py` as implementation code, not configuration surfaces. The supported customization path is to change the prompt inputs Superforecasting Agent already loads, rather than editing Python templates in place.

### Use these surfaces first

- `~/.superforecasting-agent/SOUL.md` - replace the built-in default identity block with your own forecast-desk style and standing behavior. Legacy `~/.hermes/SOUL.md` remains a compatibility path.
- `~/.superforecasting-agent/MEMORY.md` and `~/.superforecasting-agent/USER.md` - provide durable cross-session facts and user profile data that should be snapshotted into new sessions, not forecast probabilities or calibration records.
- Project context files such as `.hermes.md`, `HERMES.md`, `AGENTS.md`, `CLAUDE.md`, or `.cursorrules` - inject repo-specific working rules.
- Forecast ledger records - store scoreable forecasts, evidence, assumptions, reference classes, model runs, resolutions, scores, postmortems, and calibration lessons.
- Skills - package reusable workflows and references without editing core prompt code.
- Optional system prompt config / API overrides - add deployment-specific instruction text without forking the runtime.
- Ephemeral overlays such as `SUPERFORECASTING_AGENT_EPHEMERAL_SYSTEM_PROMPT` / `FORECAST_EPHEMERAL_SYSTEM_PROMPT` / legacy `HERMES_EPHEMERAL_SYSTEM_PROMPT` or prefill messages - add turn-scoped guidance that should not become part of the cached prompt prefix.

### When to edit code instead

Edit `agent/prompt_builder.py` or `forecasting/protocol.py` only if you are intentionally changing fork behavior. Those files assemble prompt plumbing, cache boundaries, forecast-stage instructions, and injection order for every session. Direct edits there are global product changes, not per-user prompt customization.

In other words:

- if you want a different assistant identity, edit `SOUL.md`
- if you want different repo rules, edit project context files
- if you want reusable operating procedures, add or modify skills
- if you want to change how Superforecasting Agent assembles forecast prompts for everyone, change Python and treat it as a code contribution

## Why prompt assembly is split this way

The architecture is intentionally optimized to:

- preserve provider-side prompt caching
- avoid mutating history unnecessarily
- keep memory semantics understandable
- keep scoreable forecast state in the ledger rather than in chat memory
- let gateway/ACP/CLI add context without poisoning persistent prompt state

## Related docs

- [Context Compression & Prompt Caching](./context-compression-and-caching.md)
- [Session Storage](./session-storage.md)
- [Gateway Internals](./gateway-internals.md)
