---
sidebar_position: 9
title: "Forecast Style & SOUL.md"
description: "Customize SOUL.md identity and forecast style overlays."
---

# Forecast Style & SOUL.md

Superforecasting Agent has two separate style layers. `SOUL.md` is the
**primary identity**: the first cached system-prompt layer that defines the
desk's default voice and standing behavior. `/style` is a temporary forecast
mode overlay for the current session.

- `SOUL.md` - a durable identity file that lives in the active runtime home and serves as the agent's identity (slot #1 in the system prompt)
- built-in or custom `/style` presets - session-level system-prompt overlays
- `/personality` remains available as a legacy compatibility alias for `/style`

If you want to change the default voice or standing behavior of the forecasting desk, edit `SOUL.md`. Forecast probabilities, evidence, lessons, and error records still belong in the forecast ledger, not in style text.

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

This keeps the desk's standing identity predictable.

If Superforecasting Agent loaded `SOUL.md` from whatever directory you happened to launch it in, the desk identity could change unexpectedly between projects. By loading only from the active runtime home, the standing style belongs to the forecast-desk instance itself.

That also makes it easier to teach users:
- "Edit `~/.superforecasting-agent/SOUL.md` to change Superforecasting Agent's default desk style."

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

Use it for durable voice and style guidance, such as:
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
# Forecast Desk Style

You are a precise forecasting analyst.
You optimize for calibrated probability estimates, source quality, and explicit uncertainty.

## Style
- Be concise, skeptical, and evidence-led
- State probabilities with the "as of" date
- Separate facts, estimates, assumptions, and speculation
- Call out what would change the forecast
- Keep rationales compact unless a decomposition is useful

## What to avoid
- Sycophancy
- Hype language
- Repeating the user's framing if it's wrong
- Treating fluency as evidence

## Forecasting posture
- Start with base rates when possible
- Track unresolved assumptions
- Prefer auditable evidence over untraceable intuition
- Learn from misses through postmortems and calibration lessons
```

## What Superforecasting Agent injects into the prompt

`SOUL.md` content goes directly into slot #1 of the system prompt — the agent identity position. No wrapper language is added around it.

The content goes through:
- prompt-injection scanning
- truncation if it is too large

If the file is empty, whitespace-only, or cannot be read, Superforecasting Agent falls back to a built-in forecast-desk identity ("You are Superforecasting Agent, a command-line forecasting desk..."). This fallback also applies when `skip_context_files` is set (e.g., in subagent/delegation contexts).

## Security scanning

`SOUL.md` is scanned like other context-bearing files for prompt injection patterns before inclusion.

That means you should still keep it focused on voice and standing style rather than trying to sneak in strange meta-instructions.

## SOUL.md vs AGENTS.md

This is the most important distinction.

### SOUL.md
Use for:
- identity
- tone
- style
- communication defaults
- voice-level behavior

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

## SOUL.md vs `/style`

`SOUL.md` is your durable default desk identity.

`/style` is a session-level overlay that changes or supplements the current system prompt. The inherited `/personality` command is still accepted as a compatibility alias, but `/style` is the primary forecast-desk command.

So:
- `SOUL.md` = baseline voice
- `/style` = temporary forecast mode switch

Examples:
- keep a concise default SOUL, then use `/style skeptical` for an assumption review
- keep an evidence-led SOUL, then use `/style calibration` when reviewing recent misses

## Built-in Forecast Modes

Superforecasting Agent ships with forecast-desk overlays you can switch to with `/style`.

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

## Switching forecast styles with commands

### CLI

```text
/style
/style concise
/style skeptical
```

### Messaging platforms

```text
/style teacher
```

These are convenient overlays, but your global `SOUL.md` still gives Superforecasting Agent its persistent default voice unless the overlay meaningfully changes it.

The inherited `/personality` spelling remains accepted for older habits and integrations.

## Custom style overlays in config

You can also define named custom style overlays in `~/.superforecasting-agent/config.yaml` under the inherited `agent.personalities` key. Legacy `~/.hermes/config.yaml` remains readable during the fork transition.

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
/style energy-reviewer
```

## Recommended workflow

A strong default setup is:

1. Keep a thoughtful global `SOUL.md` in `~/.superforecasting-agent/SOUL.md`
2. Put project instructions in `AGENTS.md`
3. Use `/style` only when you want a temporary forecast-mode shift

That gives you:
- a stable voice
- project-specific behavior where it belongs
- temporary control when needed

## How style overlays interact with the full prompt

At a high level, the prompt stack includes:
1. **SOUL.md** (agent identity — or built-in fallback if SOUL.md is unavailable)
2. tool-aware behavior guidance
3. memory/user context
4. skills guidance
5. context files (`AGENTS.md`, `.cursorrules`)
6. timestamp
7. platform-specific formatting hints
8. optional system-prompt overlays such as `/style`

`SOUL.md` is the foundation — everything else builds on top of it.

## Related docs

- [Context Files](/docs/user-guide/features/context-files)
- [Configuration](/docs/user-guide/configuration)
- [Tips & Best Practices](/docs/guides/tips)
- [SOUL.md Guide](/docs/guides/use-soul-with-superforecasting-agent)

## CLI appearance vs conversational style

Conversational style and CLI appearance are separate:

- `SOUL.md`, `agent.system_prompt`, and `/style` affect how Superforecasting Agent speaks
- `display.skin` and `/skin` affect how Superforecasting Agent looks in the terminal

For terminal appearance, see [Skins & Themes](./skins.md).
