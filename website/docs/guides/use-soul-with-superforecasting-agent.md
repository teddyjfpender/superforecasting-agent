---
sidebar_position: 7
title: "Use SOUL.md with Superforecasting Agent"
description: "Shape durable forecast-desk style and distinguish it from AGENTS.md and /style."
---

# Use SOUL.md with Superforecasting Agent

`SOUL.md` is the **primary style identity** for your Superforecasting Agent instance. It defines how the agent speaks, handles uncertainty, and pushes back. It does not replace the forecast protocol or the ledger.

If you want the agent to feel consistent every time you use the forecast desk, this is the file to edit.

## What SOUL.md is for

Use `SOUL.md` for:
- tone
- personality
- communication style
- how direct or warm Superforecasting Agent should be
- what the agent should avoid stylistically
- how the agent should relate to uncertainty, disagreement, and ambiguity

In short:
- `SOUL.md` is about how Superforecasting Agent speaks and reasons in conversation

## What SOUL.md is not for

Do not use it for:
- repo-specific coding conventions
- file paths
- commands
- service ports
- architecture notes
- project workflow instructions
- forecast probabilities, evidence, postmortems, scores, or calibration lessons

Project instructions belong in `AGENTS.md`. Scoreable forecast state belongs in the forecast ledger.

A good rule:
- if it should apply everywhere, put it in `SOUL.md`
- if it only belongs to one project, put it in `AGENTS.md`

## Where it lives

Superforecasting Agent now uses only the global SOUL file for the current instance:

```text
~/.superforecasting-agent/SOUL.md
```

If you run the inherited runtime with a custom home directory, the legacy compatibility path is:

```text
$HERMES_HOME/SOUL.md
```

## First-run behavior

Superforecasting Agent automatically seeds a starter `SOUL.md` for you if one does not already exist.

That means most users now begin with a real file they can read and edit immediately.

Important:
- if you already have a `SOUL.md`, the fork does not overwrite it
- if the file exists but is empty, the fork adds nothing from it to the prompt

## How Superforecasting Agent uses it

When Superforecasting Agent starts a session, it reads `SOUL.md` from the active home, scans it for prompt-injection patterns, truncates it if needed, and uses it as the durable style identity. Forecast-specific system instructions still enforce the forecasting protocol, tool boundaries, and ledger discipline.

If SOUL.md is missing, empty, or cannot be loaded, Superforecasting Agent falls back to a built-in default identity.

No wrapper language is added around the file. The content itself matters — write the way you want your agent to think and speak.

## A good first edit

If you do nothing else, open the file and change just a few lines so it feels like you.

For example:

```markdown
You are direct, calm, and technically precise.
Prefer substance over politeness theater.
Push back clearly when an idea is weak.
Keep answers compact unless deeper detail is useful.
```

That alone can noticeably change how Superforecasting Agent feels.

## Example styles

### 1. Pragmatic engineer

```markdown
You are a pragmatic senior engineer.
You care more about correctness and operational reality than sounding impressive.

## Style
- Be direct
- Be concise unless complexity requires depth
- Say when something is a bad idea
- Prefer practical tradeoffs over idealized abstractions

## Avoid
- Sycophancy
- Hype language
- Overexplaining obvious things
```

### 2. Research partner

```markdown
You are a thoughtful forecasting research collaborator.
You are curious, honest about uncertainty, and skeptical of unsupported claims.

## Style
- Explore possibilities without pretending certainty
- Distinguish speculation from evidence
- Ask clarifying questions when the idea space is underspecified
- Prefer calibrated uncertainty over false confidence
```

### 3. Teacher / explainer

```markdown
You are a patient technical teacher.
You care about understanding, not performance.

## Style
- Explain clearly
- Use examples when they help
- Do not assume prior knowledge unless the user signals it
- Build from intuition to details
```

### 4. Tough reviewer

```markdown
You are a rigorous reviewer.
You are fair, but you do not soften important criticism.

## Style
- Point out weak assumptions directly
- Prioritize correctness over harmony
- Be explicit about risks and tradeoffs
- Prefer blunt clarity to vague diplomacy
```

## What makes a strong SOUL.md?

A strong `SOUL.md` is:
- stable
- broadly applicable
- specific in voice
- not overloaded with temporary instructions

A weak `SOUL.md` is:
- full of project details
- contradictory
- trying to micro-manage every response shape
- mostly generic filler like "be helpful" and "be clear"

Superforecasting Agent already tries to be useful, clear, and forecast-disciplined. `SOUL.md` should add real personality and style, not restate obvious defaults or alter forecast rules.

## Suggested structure

You do not need headings, but they help.

A simple structure that works well:

```markdown
# Identity
How Superforecasting Agent should present itself.

# Style
How Superforecasting Agent should sound.

# Avoid
What Superforecasting Agent should not do.

# Defaults
How Superforecasting Agent should behave when ambiguity appears.
```

## SOUL.md vs `/style`

These are complementary.

Use `SOUL.md` for your durable baseline.
Use `/style` for temporary forecast-mode switches.

Examples:
- your default SOUL is pragmatic and direct
- then for one session you use `/style teacher`
- later you switch back without changing your base voice file

## SOUL.md vs AGENTS.md

This is the most common mistake.

### Put this in SOUL.md
- “Be direct.”
- “Avoid hype language.”
- “Prefer short answers unless depth helps.”
- “Push back when the user is wrong.”
- “When uncertain, separate evidence from speculation.”

### Put this in AGENTS.md
- “Use pytest, not unittest.”
- “Frontend lives in `frontend/`.”
- “Never edit migrations directly.”
- “The API runs on port 8000.”

## How to edit it

```bash
nano ~/.superforecasting-agent/SOUL.md
```

or

```bash
vim ~/.superforecasting-agent/SOUL.md
```

Then restart Superforecasting Agent or start a new session.

## A practical workflow

1. Start with the seeded default file
2. Trim anything that does not feel like the voice you want
3. Add 4–8 lines that clearly define tone and defaults
4. Use Superforecasting Agent for a few forecast research sessions
5. Adjust based on what still feels off

That iterative approach works better than trying to design the perfect personality in one shot.

## Troubleshooting

### I edited SOUL.md but Superforecasting Agent still sounds the same

Check:
- you edited `~/.superforecasting-agent/SOUL.md` or the legacy `$HERMES_HOME/SOUL.md`
- not some repo-local `SOUL.md`
- the file is not empty
- your session was restarted after the edit
- a `/style` overlay is not dominating the result

### Superforecasting Agent is ignoring parts of my SOUL.md

Possible causes:
- higher-priority instructions are overriding it
- the file includes conflicting guidance
- the file is too long and got truncated
- some of the text resembles prompt-injection content and may be blocked or altered by the scanner

### My SOUL.md became too project-specific

Move project instructions into `AGENTS.md` and keep `SOUL.md` focused on identity and style.

## Related docs

- [Forecast Style & SOUL.md](/user-guide/features/personality)
- [Context Files](/user-guide/features/context-files)
- [Configuration](/user-guide/configuration)
- [Tips & Best Practices](/guides/tips)
