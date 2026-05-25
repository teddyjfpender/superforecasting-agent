---
sidebar_position: 12
title: "Working with Skills"
description: "Use skills for repeatable forecasting workflows."
---

# Working with Skills

Skills are on-demand knowledge documents for repeatable forecasting work: source adapters, research protocols, benchmark setup, model checks, and domain-specific evidence handling. They are useful when they improve forecast quality; durable beliefs, evidence, scores, postmortems, and calibration lessons still belong in the forecast ledger.

For the full technical reference, see [Skills System](/user-guide/features/skills).

---

## Finding Skills

Every Superforecasting Agent installation ships with bundled skills. See what's available:

```bash
# In any forecast session:
/skills

# Or from the CLI:
superforecasting-agent skills list
```

This shows a compact list with names and descriptions:

```
arxiv             Search and retrieve academic papers from arXiv...
finance-stocks    Pull market context for public-company forecasts...
forecast-review   Review active questions and stale assumptions...
research-paper    Structure paper evidence for model runs...
data-adapter      Attach CSV/JSON observations as timestamped evidence...
```

### Searching for a Skill

```bash
# Search by keyword
/skills search arxiv
/skills search polling
```

### The Skills Hub

Official optional skills (heavier or niche skills not active by default) are available via the Hub:

```bash
# Browse official optional skills
/skills browse

# Search the hub
/skills search macro
```

---

## Using a Skill

Every installed skill is automatically a slash command. Just type its name:

```bash
# Load a skill and give it a task
/arxiv Find recent papers relevant to this question
/forecast-review Review stale assumptions for question 142
/data-adapter Attach this CSV as evidence for the inflation forecast

# Just the skill name (no task) loads it and lets you describe what you need
/arxiv
```

You can also trigger skills through natural language inside a forecast session. Ask the desk to use a specific skill, and it will load it via the `skill_view` tool.

### Progressive Disclosure

Skills use a token-efficient loading pattern. The runtime does not load everything at once:

1. **`skills_list()`** — compact list of all skills (~3k tokens). Loaded at session start.
2. **`skill_view(name)`** — full SKILL.md content for one skill. Loaded when the runtime decides it needs that skill.
3. **`skill_view(name, file_path)`** — a specific reference file within the skill. Only loaded if needed.

This means skills don't cost tokens until they're actually used.

---

## Installing from the Hub

Official optional skills ship with Superforecasting Agent but aren't active by default. Install them explicitly:

```bash
# Install an official optional skill
superforecasting-agent skills install official/research/arxiv

# Install from the hub in a forecast session
/skills install official/research/arxiv

# Install a single-file SKILL.md directly from any HTTP(S) URL
superforecasting-agent skills install https://sharethis.chat/SKILL.md
/skills install https://example.com/SKILL.md --name my-skill
```

What happens:
1. The skill directory is copied to `~/.superforecasting-agent/skills/`
2. It appears in your `skills_list` output
3. It becomes available as a slash command

:::tip
Installed skills take effect in new sessions. If you want it available in the current session, use `/reset` to start fresh, or add `--now` to invalidate the prompt cache immediately (costs more tokens on the next turn).
:::

### Verifying Installation

```bash
# Check it's there
superforecasting-agent skills list | grep arxiv

# Or in chat
/skills search arxiv
```

---

## Plugin-Provided Skills

Plugins can bundle their own skills using namespaced names (`plugin:skill`). This prevents name collisions with built-in skills.

```bash
# Load a plugin skill by its qualified name
skill_view("superpowers:writing-plans")

# Built-in skill with the same base name is unaffected
skill_view("writing-plans")
```

Plugin skills are **not** listed in the system prompt and do not appear in `skills_list`. They are opt-in: load them explicitly when you know a plugin provides one. When loaded, the runtime sees a banner listing sibling skills from the same plugin.

For how to ship skills in your own plugin, see the plugin guide's bundle-skills section.

---

## Configuring Skill Settings

Some skills declare configuration they need in their frontmatter:

```yaml
metadata:
  forecasting:
    config:
      - key: fred.api_key
        description: "FRED API key for economic time series"
        prompt: "Enter your FRED API key"
        url: "https://fred.stlouisfed.org/docs/api/api_key.html"
```

When a skill with config is first loaded, Superforecasting Agent prompts you for the values. They're stored in `config.yaml` under `skills.config.*`.

Manage skill config from the CLI:

```bash
# Interactive config for a specific skill
superforecasting-agent skills config fred

# View all skill config
superforecasting-agent config get skills.config
```

---

## Creating Your Own Skill

Skills are just markdown files with YAML frontmatter. Creating one takes under five minutes.

### 1. Create the Directory

```bash
mkdir -p ~/.superforecasting-agent/skills/my-category/my-skill
```

### 2. Write SKILL.md

```markdown title="~/.superforecasting-agent/skills/my-category/my-skill/SKILL.md"
---
name: my-forecast-skill
description: Brief description of the forecasting workflow
version: 1.0.0
metadata:
  forecasting:
    tags: [evidence, automation]
    category: research
---

# My Forecast Skill

## When to Use
Use this skill when a forecast needs [specific source], [specific model], or [specific review protocol].

## Procedure
1. Check that the question has resolution criteria and an evidence cutoff
2. Run the data or source query with the relevant timestamp bounds
3. Attach findings as evidence, model inputs, or a review note

## Pitfalls
- Do not use post-cutoff evidence in backtests
- Separate facts, estimates, rumors, and assumptions

## Verification
Confirm every produced claim has source metadata and an `available_at` timestamp.
```

### 3. Add Reference Files (Optional)

Skills can include supporting files the runtime loads on demand:

```
my-skill/
├── SKILL.md                    # Main skill document
├── references/
│   ├── api-docs.md             # API reference the runtime can consult
│   └── examples.md             # Example inputs/outputs
├── templates/
│   └── config.yaml             # Template files the runtime can use
└── scripts/
    └── setup.sh                # Scripts the runtime can execute
```

Reference these in your SKILL.md:

```markdown
For API details, load the reference: `skill_view("my-forecast-skill", "references/api-docs.md")`
```

### 4. Test It

Start a new session and try your skill:

```bash
superforecasting-agent chat -q "/my-forecast-skill review question 142"
```

The skill appears automatically — no registration needed. Drop it in `~/.superforecasting-agent/skills/` and it's live.

:::info
The runtime can also create and update skills with `skill_manage`. After a repeatable research or modeling workflow, it may offer to save the approach as a skill for next time. Treat that as procedural knowledge; it should not replace ledger entries or calibration lessons.
:::

---

## Per-Platform Skill Management

Control which skills are available on which platforms:

```bash
superforecasting-agent skills
```

This opens an interactive TUI where you can enable or disable skills per platform (CLI, Telegram, Discord, etc.). For the fork, keep forecasting and evidence skills available in the CLI first; messaging gateways should usually get only the skills needed for alerts, approvals, and source capture.

---

## Skills vs Memory

Both are persistent across sessions, but they serve different purposes:

| | Skills | Memory |
|---|---|---|
| **What** | Procedural knowledge — how to do things | Calibration and evidence memory tied to scored forecasts |
| **When** | Loaded on demand, only when relevant | Used when reviewing similar domains, horizons, or error patterns |
| **Size** | Can be large (hundreds of lines) | Should be compact and provenance-aware |
| **Cost** | Zero tokens until loaded | Used selectively when relevant to a question |
| **Examples** | "How to import FRED evidence" | "Overweighted late polling swings in mayoral races" |
| **Who creates** | You, the runtime, or installed from Hub | Scoring and postmortem workflows |

**Rule of thumb:** If it is a repeatable procedure, make it a skill. If it is a scored lesson from a forecast, keep it in calibration memory.

---

## Tips

**Keep skills focused.** A skill that tries to cover "all macro forecasting" will be too long and too vague. A skill that covers "import and sanity-check FRED CPI observations" is specific enough to be useful.

**Let the runtime create skills carefully.** After a complex multi-step research task, it may offer to save the approach as a skill. Accept when the procedure is reusable, then keep outcome-specific learnings in the ledger.

**Use categories.** Organize skills into subdirectories (`~/.superforecasting-agent/skills/devops/`, `~/.superforecasting-agent/skills/research/`, etc.). This keeps the list manageable and helps the runtime find relevant skills faster.

**Update skills when they go stale.** If a source format, API, or review protocol changes, update the skill. Skills that are not maintained become liabilities.

---

*For the complete skills reference — frontmatter fields, conditional activation, external directories, and more — see [Skills System](/user-guide/features/skills).*
