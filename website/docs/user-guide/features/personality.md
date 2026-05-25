---
sidebar_position: 9
title: "Personality & SOUL.md"
description: "Customize Superforecasting Agent's SOUL.md identity."
---

# Personality & SOUL.md

Superforecasting Agent's personality is customizable. `SOUL.md` is the **primary identity**: the first cached system-prompt layer that defines the agent's voice and standing behavior.

- `SOUL.md` - a durable persona file that lives in the active runtime home and serves as the agent's identity (slot #1 in the system prompt)
- built-in or custom `/personality` presets - session-level system-prompt overlays

If you want to change the default voice or standing behavior of the forecasting desk, edit `SOUL.md`. Forecast probabilities, evidence, lessons, and error records still belong in the forecast ledger, not in personality text.

## How SOUL.md works now

New installs seed a default `SOUL.md` automatically in:

```text
~/.superforecasting-agent/SOUL.md
```

Existing `~/.hermes` homes remain readable as legacy compatibility paths. More precisely, the runtime uses the active home resolved from `SUPERFORECASTING_AGENT_HOME`, `FORECAST_HOME`, or legacy `HERMES_HOME`, so custom homes use:

```text
$SUPERFORECASTING_AGENT_HOME/SOUL.md
```

### Important behavior

- **SOUL.md is the agent's primary identity.** It occupies slot #1 in the system prompt, replacing the hardcoded default identity.
- Superforecasting Agent creates a starter `SOUL.md` automatically if one does not exist yet
- Existing user `SOUL.md` files are never overwritten
- Superforecasting Agent loads `SOUL.md` only from the active runtime home
- Superforecasting Agent does not look in the current working directory for `SOUL.md`
- If `SOUL.md` exists but is empty, or cannot be loaded, Superforecasting Agent falls back to a built-in forecast-desk identity
- If `SOUL.md` has content, that content is injected verbatim after security scanning and truncation
- SOUL.md is **not** duplicated in the context files section; it appears only once, as the identity

That makes `SOUL.md` a true per-user or per-instance identity, not just an additive layer.

## Why this design

This keeps personality predictable.

If Superforecasting Agent loaded `SOUL.md` from whatever directory you happened to launch it in, the agent's identity could change unexpectedly between projects. By loading only from the active runtime home, the personality belongs to the forecast-desk instance itself.

That also makes it easier to teach users:
- "Edit `~/.superforecasting-agent/SOUL.md` to change Superforecasting Agent's default personality."

## Where to edit it

For most users:

```bash
~/.superforecasting-agent/SOUL.md
```

If you use a custom home:

```bash
$SUPERFORECASTING_AGENT_HOME/SOUL.md
```

## What should go in SOUL.md?

Use it for durable voice and personality guidance, such as:
- tone
- communication style
- level of directness
- default interaction style
- what to avoid stylistically
- how Superforecasting Agent should handle uncertainty, disagreement, or ambiguity

Use it less for:
- one-off project instructions
- file paths
- repo conventions
- temporary workflow details

Those belong in `AGENTS.md`, not `SOUL.md`.

## Good SOUL.md content

A good SOUL file is:
- stable across contexts
- broad enough to apply in many conversations
- specific enough to materially shape the voice
- focused on communication and identity, not task-specific instructions

### Example

```markdown
# Personality

You are a pragmatic senior engineer with strong taste.
You optimize for truth, clarity, and usefulness over politeness theater.

## Style
- Be direct without being cold
- Prefer substance over filler
- Push back when something is a bad idea
- Admit uncertainty plainly
- Keep explanations compact unless depth is useful

## What to avoid
- Sycophancy
- Hype language
- Repeating the user's framing if it's wrong
- Overexplaining obvious things

## Technical posture
- Prefer simple systems over clever systems
- Care about operational reality, not idealized architecture
- Treat edge cases as part of the design, not cleanup
```

## What Superforecasting Agent injects into the prompt

`SOUL.md` content goes directly into slot #1 of the system prompt — the agent identity position. No wrapper language is added around it.

The content goes through:
- prompt-injection scanning
- truncation if it is too large

If the file is empty, whitespace-only, or cannot be read, Superforecasting Agent falls back to a built-in forecast-desk identity ("You are Superforecasting Agent, a command-line forecasting desk..."). This fallback also applies when `skip_context_files` is set (e.g., in subagent/delegation contexts).

## Security scanning

`SOUL.md` is scanned like other context-bearing files for prompt injection patterns before inclusion.

That means you should still keep it focused on persona/voice rather than trying to sneak in strange meta-instructions.

## SOUL.md vs AGENTS.md

This is the most important distinction.

### SOUL.md
Use for:
- identity
- tone
- style
- communication defaults
- personality-level behavior

### AGENTS.md
Use for:
- project architecture
- coding conventions
- tool preferences
- repo-specific workflows
- commands, ports, paths, deployment notes

A useful rule:
- if it should follow you everywhere, it belongs in `SOUL.md`
- if it belongs to a project, it belongs in `AGENTS.md`

## SOUL.md vs `/personality`

`SOUL.md` is your durable default personality.

`/personality` is a session-level overlay that changes or supplements the current system prompt.

So:
- `SOUL.md` = baseline voice
- `/personality` = temporary mode switch

Examples:
- keep a pragmatic default SOUL, then use `/personality teacher` for a tutoring conversation
- keep a concise SOUL, then use `/personality skeptical` for an assumption review

## Built-in Forecast Modes

Superforecasting Agent ships with forecast-desk overlays you can switch to with `/personality`.

| Name | Description |
|------|-------------|
| **forecaster** | Disciplined probability, assumptions, and update triggers |
| **concise** | Brief forecast-desk responses with quantified judgments |
| **technical** | Quantitative research, models, and sensitivity checks |
| **research** | Timestamped evidence, source quality, and evidence gaps |
| **skeptical** | Assumption review, ambiguity checks, and alternate explanations |
| **calibration** | Confidence checks against historical error patterns |
| **teacher** | Forecasting concepts explained with examples |
| **creative** | Non-obvious scenarios, mechanisms, and indicators |
| **executive** | Decision-oriented summary of probabilities, deltas, and caveats |

## Switching personalities with commands

### CLI

```text
/personality
/personality concise
/personality skeptical
```

### Messaging platforms

```text
/personality teacher
```

These are convenient overlays, but your global `SOUL.md` still gives Superforecasting Agent its persistent default personality unless the overlay meaningfully changes it.

## Custom personalities in config

You can also define named custom personalities in `~/.superforecasting-agent/config.yaml` under `agent.personalities`. Legacy `~/.hermes/config.yaml` remains readable during the fork transition.

```yaml
agent:
  personalities:
    energy-reviewer: >
      You are a meticulous energy-market forecaster. Identify base rates,
      supply constraints, demand shocks, policy changes, and indicators that
      would move the probability.
```

Then switch to it with:

```text
/personality energy-reviewer
```

## Recommended workflow

A strong default setup is:

1. Keep a thoughtful global `SOUL.md` in `~/.superforecasting-agent/SOUL.md`
2. Put project instructions in `AGENTS.md`
3. Use `/personality` only when you want a temporary mode shift

That gives you:
- a stable voice
- project-specific behavior where it belongs
- temporary control when needed

## How personality interacts with the full prompt

At a high level, the prompt stack includes:
1. **SOUL.md** (agent identity — or built-in fallback if SOUL.md is unavailable)
2. tool-aware behavior guidance
3. memory/user context
4. skills guidance
5. context files (`AGENTS.md`, `.cursorrules`)
6. timestamp
7. platform-specific formatting hints
8. optional system-prompt overlays such as `/personality`

`SOUL.md` is the foundation — everything else builds on top of it.

## Related docs

- [Context Files](/docs/user-guide/features/context-files)
- [Configuration](/docs/user-guide/configuration)
- [Tips & Best Practices](/docs/guides/tips)
- [SOUL.md Guide](/docs/guides/use-soul-with-superforecasting-agent)

## CLI appearance vs conversational personality

Conversational personality and CLI appearance are separate:

- `SOUL.md`, `agent.system_prompt`, and `/personality` affect how Superforecasting Agent speaks
- `display.skin` and `/skin` affect how Superforecasting Agent looks in the terminal

For terminal appearance, see [Skins & Themes](./skins.md).
