---
sidebar_position: 1
title: "Tips & Best Practices"
description: "Practical advice for using the forecast desk, ledger, CLI shortcuts, memory, and security controls."
---

# Tips & Best Practices

A quick-wins collection of practical tips that make you more effective with Superforecasting Agent. Each section targets a different part of the forecast desk: question setup, evidence handling, ledger discipline, CLI flow, memory, cost, and security.

---

## Getting the Best Results

### Be Specific About the Forecast

Vague prompts produce vague forecasts. Instead of "research inflation," say "create a binary forecast for whether the next CPI print will exceed consensus, using BLS as the resolution source, and separate base-rate evidence from inside-view arguments." The more precise the question and resolution criteria, the fewer cleanup passes you need.

### Provide Context Up Front

Front-load your request with the relevant details: source URLs, close time, resolution source, prior forecasts, evidence cutoffs, and known ambiguities. One well-crafted message beats three rounds of clarification.

### Use Context Files for Recurring Instructions

If you find yourself repeating the same instructions ("always cite BLS releases," "separate market priors from model estimates," "use this local data directory"), put them in an `AGENTS.md` file. The agent reads it automatically every session — zero effort after setup.

### Let the Agent Use Its Tools

Don't try to hand-hold every step. Say "build a base-rate estimate and update the forecast with cited evidence" rather than manually sequencing every tool. The agent has file search, terminal access, browser access, and ledger tooling — let it explore, then verify the final probability and rationale.

### Use Skills for Complex Workflows

Before writing a long prompt explaining a workflow, check if there's already a skill for it. Type `/skills` to browse available skills. Use skills for repeatable research procedures, but keep scoreable forecast state in the ledger.

## CLI Power User Tips

### Multi-Line Input

Press **Alt+Enter**, **Ctrl+J**, or **Shift+Enter** to insert a newline without sending. `Shift+Enter` only works when the terminal sends it as a distinct keystroke (Kitty / foot / WezTerm / Ghostty by default; iTerm2 / Alacritty / VS Code terminal once the Kitty keyboard protocol is enabled). The other two work in every terminal.

### Paste Detection

The CLI auto-detects multi-line pastes. Just paste a code block or error traceback directly — it won't send each line as a separate message. The paste is buffered and sent as one message.

### Interrupt and Redirect

Press **Ctrl+C** once to interrupt the agent mid-response. You can then type a new message to redirect it. Double-press Ctrl+C within 2 seconds to force exit. This is invaluable when the agent starts going down the wrong path.

### Resume Sessions with `-c`

Forgot something from your last session? Run `superforecasting-agent -c` to resume exactly where you left off, with full conversation history restored. You can also resume by title: `superforecasting-agent -r "inflation forecast research"`.

### Clipboard Image Paste

Press **Ctrl+V** to paste an image from your clipboard directly into the chat. The agent uses vision to analyze screenshots, diagrams, error popups, or UI mockups — no need to save to a file first.

### Slash Command Autocomplete

Type `/` and press **Tab** to see all available commands. This includes built-in commands (`/compress`, `/model`, `/title`) and every installed skill. You don't need to memorize anything — Tab completion has you covered.

:::tip
Use `/verbose` to cycle through tool output display modes: **off → new → all → verbose**. The "all" mode is great for watching what the agent does; "off" is cleanest for simple Q&A.
:::

## Context Files

### AGENTS.md: Your Project's Brain

Create an `AGENTS.md` in your project root with architecture decisions, coding conventions, and project-specific instructions. This is automatically injected into every session, so the agent always knows your project's rules.

```markdown
# Project Context
- This is a FastAPI backend with SQLAlchemy ORM
- Always use async/await for database operations
- Tests go in tests/ and use pytest-asyncio
- Never commit .env files
```

### SOUL.md: Customize Personality

Want Superforecasting Agent to have a stable default voice? Edit `~/.superforecasting-agent/SOUL.md` (or the inherited `$HERMES_HOME/SOUL.md` compatibility path if you use a legacy home). The fork seeds a starter SOUL automatically and uses that global file as the instance-wide style source.

For a full walkthrough, see [Use SOUL.md with Superforecasting Agent](/docs/guides/use-soul-with-hermes).

```markdown
# Soul
You are a senior backend engineer. Be terse and direct.
Skip explanations unless asked. Prefer one-liners over verbose solutions.
Always consider error handling and edge cases.
```

Use `SOUL.md` for durable personality. Use `AGENTS.md` for project-specific instructions.

### .cursorrules Compatibility

Already have a `.cursorrules` or `.cursor/rules/*.mdc` file? The inherited runtime reads those too. No need to duplicate your project conventions — they're loaded automatically from the working directory.

### Discovery

Superforecasting Agent loads the top-level `AGENTS.md` from the current working directory at session start. Subdirectory `AGENTS.md` files are discovered lazily during tool calls (via `subdirectory_hints.py`) and injected into tool results — they are not loaded upfront into the system prompt.

:::tip
Keep context files focused and concise. Every character counts against your token budget since they're injected into every single message.
:::

## Memory & Skills

### Memory vs. Skills: What Goes Where

**Memory** is for preferences and recurring context: your environment, source habits, project locations, and communication defaults. **Skills** are for procedures: multi-step workflows, tool-specific instructions, and reusable recipes. **The forecast ledger** is for scoreable beliefs: questions, evidence, probabilities, model runs, resolutions, scores, postmortems, and calibration lessons.

### When to Create Skills

If you find a research task that takes 5+ steps and you'll do it again, ask the agent to create a skill for it. Say "save this evidence-triage workflow as a skill called `macro-source-review`." Next time, type `/macro-source-review` and the agent loads the procedure.

### Managing Memory Capacity

Memory is intentionally bounded (~2,200 chars for MEMORY.md, ~1,375 chars for USER.md). When it fills up, the agent consolidates entries. You can help by saying "clean up your memory" or "replace the old Python 3.9 note — we're on 3.12 now."

### Let the Agent Remember

After a productive session, say "remember this preference for next time" and the agent will save durable non-scoreable context. For forecast updates, use `forecast update`, `forecast postmortem`, and calibration lessons instead of chat memory.

:::warning
Memory is a frozen snapshot — changes made during a session don't appear in the system prompt until the next session starts. The agent writes to disk immediately, but the prompt cache isn't invalidated mid-session.
:::

## Performance & Cost

### Don't Break the Prompt Cache

Most LLM providers cache the system prompt prefix. If you keep your system prompt stable (same context files, same memory), subsequent messages in a session get **cache hits** that are significantly cheaper. Avoid changing the model or system prompt mid-session.

### Use /compress Before Hitting Limits

Long sessions accumulate tokens. When you notice responses slowing down or getting truncated, run `/compress`. This summarizes the conversation history, preserving key context while dramatically reducing token count. Use `/usage` to check where you stand.

### Delegate for Parallel Work

Need to research three source clusters at once? Ask the agent to use `delegate_task` with parallel subtasks. Each subagent runs independently with its own context, and only the final summaries come back — keep any final probability write in the ledger.

### Use execute_code for Batch Operations

Instead of running terminal commands one at a time, ask the agent to write a script that does everything at once. "Write a Python script to rename all `.jpeg` files to `.jpg` and run it" is cheaper and faster than renaming files individually.

### Choose the Right Model

Use `/model` to switch models mid-session. Use a frontier model for ambiguous resolution criteria, causal decomposition, and adversarial evidence review. Switch to a faster model for formatting, source summaries, and low-risk drafting.

:::tip
Run `/usage` periodically to see your token consumption. Run `/insights` for a broader view of usage patterns over the last 30 days.
:::

## Messaging Tips

### Set a Home Channel

Use `/sethome` in your preferred Telegram or Discord chat to designate it as the home channel. Forecast review prompts, watched-source alerts, cron job results, and scheduled self-check outputs are delivered here. Without it, the agent has nowhere to send proactive messages.

### Use /title to Organize Sessions

Name your sessions with `/title inflation-cpi-research` or `/title election-baselines`. Named sessions are easy to find with `superforecasting-agent sessions list` and resume with `superforecasting-agent -r "inflation-cpi-research"`. Unnamed sessions pile up and become impossible to distinguish.

### DM Pairing for Team Access

Instead of manually collecting user IDs for allowlists, enable DM pairing. When a teammate DMs the bot, they get a one-time pairing code. You approve it with `superforecasting-agent pairing approve telegram XKGH5N7P` — simple and secure.

### Tool Progress Display Modes

Use `/verbose` to control how much tool activity you see. In messaging platforms, less is usually more — keep it on "new" to see just new tool calls. In the CLI, "all" gives you a satisfying live view of everything the agent does.

:::tip
On messaging platforms, sessions auto-reset after idle time (default: 24 hours) or daily at 4 AM. Adjust per-platform in `~/.superforecasting-agent/config.yaml` if you need longer sessions.
:::

## Security

### Use Docker for Untrusted Code

When working with untrusted repositories or running unfamiliar code, use Docker or Daytona as your terminal backend. Set `TERMINAL_BACKEND=docker` in your `.env`. Destructive commands inside a container can't harm your host system.

```bash
# In your .env:
TERMINAL_BACKEND=docker
TERMINAL_DOCKER_IMAGE=nikolaik/python-nodejs:python3.11-nodejs20
```

### Avoid Windows Encoding Pitfalls

On Windows, some default encodings (such as `cp125x`) cannot represent all Unicode characters, which can cause `UnicodeEncodeError` when writing files in tests or scripts.

- Prefer opening files with an explicit UTF-8 encoding:

```python
with open("results.txt", "w", encoding="utf-8") as f:
    f.write("✓ All good\n")
```

- In PowerShell, you can also switch the current session to UTF-8 for console and native command output:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
```

This keeps PowerShell and child processes on UTF-8 and helps avoid Windows-only failures.

### Review Before Choosing "Always"

When the agent triggers a dangerous command approval (`rm -rf`, `DROP TABLE`, etc.), you get four options: **once**, **session**, **always**, **deny**. Think carefully before choosing "always" — it permanently allowlists that pattern. Start with "session" until you're comfortable.

### Command Approval Is Your Safety Net

Superforecasting Agent checks every command against a curated list of dangerous patterns before execution. This includes recursive deletes, SQL drops, piping curl to shell, and more. Don't disable this in production — it exists for good reasons.

:::warning
When running in a container backend (Docker, Singularity, Modal, Daytona), dangerous command checks are **skipped** because the container is the security boundary. Make sure your container images are properly locked down.
:::

### Use Allowlists for Messaging Bots

Never set `GATEWAY_ALLOW_ALL_USERS=true` on a bot with terminal access. Always use platform-specific allowlists (`TELEGRAM_ALLOWED_USERS`, `DISCORD_ALLOWED_USERS`) or DM pairing to control who can interact with your agent.

```bash
# Recommended: explicit allowlists per platform
TELEGRAM_ALLOWED_USERS=123456789,987654321
DISCORD_ALLOWED_USERS=123456789012345678

# Or use cross-platform allowlist
GATEWAY_ALLOWED_USERS=123456789,987654321
```

---

*Have a tip that should be on this page? Open an issue or PR — community contributions are welcome.*
