---
sidebar_position: 2
title: "Forecast Skills System"
description: "Load procedural forecasting playbooks on demand."
---

# Forecast Skills System

Skills are on-demand instruction packs the forecast desk can load when a question needs a specialized workflow. They are useful for repeatable research procedures, source-specific adapters, modeling templates, backtest review checklists, domain postmortem routines, and team operating rules.

Skills are not the forecast ledger. A skill can teach the agent how to inspect sources or run a model, but probabilities, evidence records, model runs, resolutions, scores, postmortems, calibration lessons, and domain/topic error profiles stay in the ledger and learning systems.

The skill format remains compatible with the [agentskills.io](https://agentskills.io/specification) open standard.

By default, local skills live in **`~/.superforecasting-agent/skills/`**. During migration, the runtime can still read legacy **`~/.hermes/skills/`** homes when the compatibility environment is configured.

You can also point Superforecasting Agent at **external skill directories** scanned alongside the local skill home. See [External Skill Directories](#external-skill-directories).

See also:

- [Bundled Skills Catalog](/docs/reference/skills-catalog)
- [Official Optional Skills Catalog](/docs/reference/optional-skills-catalog)

## Using Skills

Every installed skill is available as a slash command:

```bash
# In the CLI, TUI, dashboard chat, or a messaging gateway:
/plan design the evidence plan for a credit-default forecast
/research-arxiv find recent papers relevant to this resolution criterion
/github-pr-workflow inspect release activity as evidence for a ship-date forecast

# Just the skill name loads it and lets the agent ask what it needs:
/excalidraw
```

The bundled `plan` skill is a good example. Running `/plan [request]` loads its instructions and tells the agent to inspect context if needed, write a markdown plan instead of executing the work, and save the result under `.superforecasting-agent/plans/` relative to the active workspace or backend working directory.

You can also inspect skills through the CLI:

```bash
superforecasting-agent chat --toolsets skills -q "What skills do you have?"
superforecasting-agent chat --toolsets skills -q "Show me the research-arxiv skill"
```

## Forecasting Boundaries

Use skills for procedure, not durable belief state.

Good skill uses:

- A domain checklist for election, credit, macro, policy, security, or product-launch forecasts.
- A source procedure for SEC filings, RSS feeds, arXiv, GitHub releases, court dockets, or market pages.
- A modeling recipe for reference classes, base rates, Bayesian updates, scenario trees, or time-series diagnostics.
- A postmortem checklist that turns resolved misses into ledger-backed learning notes.
- A backtest review routine that compares probability sources and flags leakage.

Do not use skills to store:

- Current probabilities or rationales for active questions.
- Evidence items that should be timestamped and source-attributed.
- Resolutions, scores, calibration adjustments, or domain error profiles.
- Private secrets or account credentials.

Those belong in the forecast ledger, configured providers, or local secret stores.

## Progressive Disclosure

Skills use a token-efficient loading pattern:

```text
Level 0: skills_list()           -> [{name, description, category}, ...]
Level 1: skill_view(name)        -> Full SKILL.md content + metadata
Level 2: skill_view(name, path)  -> Specific reference, template, or script file
```

The agent only loads full skill content when it actually needs it. This matters for a forecasting desk because active research already consumes a lot of context from evidence, model outputs, and prior forecast history.

## SKILL.md Format

```markdown
---
name: forecast-reference-class
description: Build comparable historical reference classes.
version: 1.0.0
platforms: [macos, linux]     # Optional OS gating
metadata:
  hermes:
    tags: [forecasting, base-rates]
    category: research
    fallback_for_toolsets: [web]    # Optional conditional activation
    requires_toolsets: [terminal]   # Optional conditional activation
    config:                         # Optional config.yaml settings
      - key: reference_class.default_window_years
        description: "Default lookback window for comparable events"
        default: 10
        prompt: "Reference-class lookback window"
---

# Forecast Reference Class Skill

## When to Use
Use when a question needs historical comparables before an inside-view estimate.

## Prerequisites
List required providers, toolsets, data files, or MCP servers.

## How to Run
Name the native tools or commands the agent should use.

## Quick Reference
Provide concise commands, schemas, or source patterns.

## Procedure
1. Parse the outcome and resolution criteria.
2. Define inclusion and exclusion rules.
3. Gather comparable cases before the evidence cutoff.
4. Estimate the base rate and uncertainty.
5. Write results into the forecast ledger as a model run or evidence note.

## Pitfalls
- Do not mix post-resolution evidence into backtests.
- Record ambiguous inclusion decisions as assumptions.

## Verification
Confirm the ledger has a timestamped model run and source links.
```

The metadata namespace is still `metadata.hermes` for compatibility with the inherited loader. Treat that key as a runtime compatibility name, not product branding.

### Platform-Specific Skills

Skills can restrict themselves to specific operating systems:

| Value | Matches |
|-------|---------|
| `macos` | macOS (Darwin) |
| `linux` | Linux |
| `windows` | Windows |

```yaml
platforms: [macos]
platforms: [macos, linux]
```

When set, the skill is hidden from the system prompt, `skills_list()`, and slash commands on incompatible platforms. If omitted, the skill loads on all platforms.

## Skill Output and Media Delivery

When a skill response, or any agent response, includes a bare absolute path to a media file, the gateway can deliver that file natively to the user's chat instead of leaving the raw path in the text.

This is useful for forecast-desk artifacts such as:

- Calibration charts.
- Backtest reports.
- Evidence screenshots.
- Scenario-tree diagrams.
- Source-extraction bundles.

For audio, the `[[audio_as_voice]]` directive promotes audio files to native voice-message bubbles on platforms that support them.

### Forcing Document Delivery: `[[as_document]]`

Use `[[as_document]]` when a chart, screenshot, or evidence pack should be sent as an intact file rather than a compressed image preview.

```text
Here is the calibration chart:

/home/user/.superforecasting-agent/cache/calibration-q4.png

[[as_document]]
```

The directive is stripped before delivery. It applies to every media path in the same response.

Media delivery does not write to the forecast ledger. If a screenshot, chart, or extracted file changes a forecast, follow it with an explicit evidence, model-run, update, resolution, score, or postmortem command.

## Conditional Activation

Skills can automatically show or hide themselves based on available toolsets or tools:

```yaml
metadata:
  hermes:
    fallback_for_toolsets: [web]
    requires_toolsets: [terminal]
    fallback_for_tools: [web_search]
    requires_tools: [terminal]
```

| Field | Behavior |
|-------|----------|
| `fallback_for_toolsets` | Hidden when the listed toolsets are available; shown when they are missing. |
| `fallback_for_tools` | Same, but checks individual tools. |
| `requires_toolsets` | Hidden when the listed toolsets are unavailable; shown when they are present. |
| `requires_tools` | Same, but checks individual tools. |

Example: a local search skill can use `fallback_for_toolsets: [web]`. When managed web search is available, the skill stays hidden. When web search is unavailable, the local fallback appears in the skill index.

## Secure Setup on Load

Skills can declare required environment variables without disappearing from discovery:

```yaml
required_environment_variables:
  - name: TENOR_API_KEY
    prompt: Tenor API key
    help: Get a key from https://developers.google.com/tenor
    required_for: full functionality
```

When a missing value is encountered, Superforecasting Agent asks for it securely only when the skill is actually loaded in the local CLI. Messaging surfaces never ask for secrets in chat; they tell you to use `superforecasting-agent setup` or `~/.superforecasting-agent/.env` locally.

Once set, declared env vars are automatically passed through to `execute_code` and `terminal` sandboxes. For non-skill env vars, use the `terminal.env_passthrough` config option. See [Environment Variable Passthrough](/docs/user-guide/security#environment-variable-passthrough).

Legacy `~/.hermes/.env` and `HERMES_*` runtime names may still appear in compatibility paths. New fork-native setup should prefer `~/.superforecasting-agent/.env` and the documented forecast-desk commands.

### Skill Config Settings

Skills can declare non-secret config settings stored in `config.yaml`:

```yaml
metadata:
  hermes:
    config:
      - key: reference_class.default_window_years
        description: Default lookback window for comparable cases
        default: 10
        prompt: Reference-class lookback window
```

Settings are stored under `skills.config` in `~/.superforecasting-agent/config.yaml`. `superforecasting-agent config migrate` prompts for unconfigured settings, and `superforecasting-agent config show` displays them. When a skill loads, resolved config values are injected into context so the agent knows the configured values.

See [Skill Settings](/docs/user-guide/configuration#skill-settings) and [Creating Skills: Config Settings](/docs/developer-guide/creating-skills#config-settings-configyaml).

## Skill Directory Structure

```text
~/.superforecasting-agent/skills/       # Primary local skill home
├── forecasting/
│   ├── reference-class/
│   │   ├── SKILL.md                    # Main instructions
│   │   ├── references/                 # Supporting docs
│   │   ├── templates/                  # Output formats
│   │   ├── scripts/                    # Helper scripts
│   │   └── assets/                     # Supplementary files
│   └── postmortem-review/
│       └── SKILL.md
├── research/
│   └── sec-filing-watch/
│       ├── SKILL.md
│       └── references/
├── .hub/                               # Skills Hub state
│   ├── lock.json
│   ├── quarantine/
│   └── audit.log
└── .bundled_manifest                   # Tracks seeded bundled skills
```

Legacy homes may still use `~/.hermes/skills/` during migration.

## External Skill Directories

If you maintain skills outside the local Superforecasting Agent home, such as a shared `~/.agents/skills/` directory used by several AI tools, add them under `skills.external_dirs`:

```yaml
skills:
  external_dirs:
    - ~/.agents/skills
    - /home/shared/forecasting-skills
    - ${SKILLS_REPO}/skills
```

Paths support `~` expansion and `${VAR}` environment variable substitution.

### How it works

- **Read-only**: External dirs are scanned for discovery. When the agent creates or edits a skill, it writes to `~/.superforecasting-agent/skills/`.
- **Local precedence**: If the same skill name exists locally and externally, the local version wins.
- **Full integration**: External skills appear in the system prompt index, `skills_list`, `skill_view`, and `/skill-name` slash commands.
- **Silent skips**: Non-existent configured directories are skipped without errors.

### Example

```text
~/.superforecasting-agent/skills/       # Local, read-write
├── forecasting/reference-class/
│   └── SKILL.md
└── research/sec-filing-watch/
    └── SKILL.md

~/.agents/skills/                       # External, read-only, shared
├── macro-policy-watch/
│   └── SKILL.md
└── team-source-rules/
    └── SKILL.md
```

All four skills appear in your skill index. If you create a local `macro-policy-watch` skill, it shadows the external version.

## Skill Bundles

Skill bundles are small YAML files that group several skills under one slash command. When you run `/<bundle-name>`, every listed skill loads at once.

Bundles are useful for recurring forecast workflows where the same procedures should travel together, such as macro policy monitoring, election forecasting, release-risk forecasting, market-pricing review, or weekly calibration review.

### Quick example

```bash
superforecasting-agent bundles create macro-policy-watch \
  --skill reference-class \
  --skill web-search-review \
  --skill postmortem-review \
  -d "Macro policy forecast review workflow"
```

Then in the CLI or any gateway platform:

```text
/macro-policy-watch review the current central-bank-rate forecast
```

The agent receives all listed skills in one user message, with any text after the slash command attached as the user instruction.

### YAML schema

Bundles live in **`~/.superforecasting-agent/skill-bundles/<slug>.yaml`**:

```yaml
name: macro-policy-watch
description: Macro policy forecast review workflow.
skills:
  - reference-class
  - web-search-review
  - postmortem-review
instruction: |
  Start from the active forecast ledger entry.
  Keep new claims as evidence candidates until explicitly ledgered.
```

Fields:

- `name` defaults to the filename stem and normalizes to a slash-command slug.
- `description` appears in `/bundles` and `superforecasting-agent bundles list`.
- `skills` is a required non-empty list of skill names or paths.
- `instruction` is optional extra guidance prepended to the loaded skill content.

### Managing bundles

```bash
superforecasting-agent bundles list
superforecasting-agent bundles show macro-policy-watch
superforecasting-agent bundles create research
superforecasting-agent bundles create macro-policy-watch --skill ... --force
superforecasting-agent bundles delete macro-policy-watch
superforecasting-agent bundles reload
```

Inside a session, `/bundles` lists every installed bundle and its skills.

### Behavior

- **Bundles take precedence over individual skills** when slugs collide.
- **Missing skills are skipped, not fatal**; the agent receives a note listing skipped names.
- **Bundles work in every surface** because dispatch is centralized with individual skill commands.
- **Bundles do not invalidate the prompt cache**; they generate a user message at invocation time.

## Agent-Managed Skills {#agent-managed-skills-skill_manage-tool}

The agent can create, update, and delete local skills via the `skill_manage` tool. This is procedural memory: when the agent discovers a durable method, it can save that method as a skill for future use.

### When the agent should create skills

- After a repeated source-inspection workflow becomes stable.
- After a postmortem identifies a reusable process fix.
- When the user corrects a recurring approach error.
- When a domain-specific procedure should be preserved for future forecasts.
- When a team wants to encode a standing operating rule.

### When the agent should not create skills

- To store a forecast's current probability.
- To remember evidence that belongs in the ledger.
- To encode a calibration adjustment that should live in learning memory.
- To preserve secrets, tokens, cookies, or personal data.

### Actions

| Action | Use for | Key params |
|--------|---------|------------|
| `create` | New skill from scratch | `name`, `content`, optional `category` |
| `patch` | Targeted fixes | `name`, `old_string`, `new_string` |
| `edit` | Major structural rewrites | `name`, `content` |
| `delete` | Remove a skill | `name` |
| `write_file` | Add or update supporting files | `name`, `file_path`, `file_content` |
| `remove_file` | Remove a supporting file | `name`, `file_path` |

Prefer `patch` for small updates because it is more token-efficient than replacing the full skill.

## Skills Hub

The Skills Hub lets you browse, search, install, update, audit, and publish skills from online registries, `skills.sh`, well-known skill endpoints, GitHub taps, direct URLs, and official optional skills.

### Common commands

```bash
superforecasting-agent skills browse
superforecasting-agent skills browse --source official
superforecasting-agent skills search forecasting
superforecasting-agent skills search react --source skills-sh
superforecasting-agent skills search https://mintlify.com/docs --source well-known
superforecasting-agent skills inspect openai/skills/k8s
superforecasting-agent skills install openai/skills/k8s
superforecasting-agent skills install official/research/arxiv
superforecasting-agent skills install skills-sh/vercel-labs/json-render/json-render-react --force
superforecasting-agent skills install well-known:https://mintlify.com/docs/.well-known/skills/mintlify
superforecasting-agent skills install https://example.com/SKILL.md --name my-skill
superforecasting-agent skills list --source hub
superforecasting-agent skills check
superforecasting-agent skills update
superforecasting-agent skills audit
superforecasting-agent skills uninstall k8s
superforecasting-agent skills reset research-arxiv
superforecasting-agent skills reset research-arxiv --restore
superforecasting-agent skills publish skills/my-skill --to github --repo owner/repo
superforecasting-agent skills snapshot export setup.json
superforecasting-agent skills tap add myorg/forecasting-skills
```

### Supported hub sources

| Source | Example | Notes |
|--------|---------|-------|
| `official` | `official/research/arxiv` | Optional skills shipped with the repo. |
| `skills-sh` | `skills-sh/vercel-labs/agent-skills/vercel-react-best-practices` | Searchable via `superforecasting-agent skills search <query> --source skills-sh`. |
| `well-known` | `well-known:https://mintlify.com/docs/.well-known/skills/mintlify` | Skills served directly from `/.well-known/skills/index.json`. |
| `url` | `https://example.com/SKILL.md` | Direct HTTP(S) URL to a single-file `SKILL.md`. |
| `github` | `openai/skills/k8s` | Direct GitHub repo/path installs and custom taps. |
| `clawhub`, `lobehub`, `browse-sh`, `claude-marketplace` | Source-specific identifiers | Community or marketplace integrations. |

### Integrated hubs and registries

Superforecasting Agent currently integrates with these skill ecosystems and discovery sources.

#### 1. Official optional skills (`official`)

These are maintained in the repository and install with builtin trust.

- Catalog: [Official Optional Skills Catalog](../../reference/optional-skills-catalog)
- Source in repo: `optional-skills/`

```bash
superforecasting-agent skills browse --source official
superforecasting-agent skills install official/research/arxiv
```

#### 2. skills.sh (`skills-sh`)

This is Vercel's public skills directory. Superforecasting Agent can search it directly, inspect skill detail pages, resolve alias-style slugs, and install from the underlying source repo.

- Directory: [skills.sh](https://skills.sh/)
- CLI/tooling repo: [vercel-labs/skills](https://github.com/vercel-labs/skills)
- Official Vercel skills repo: [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills)

```bash
superforecasting-agent skills search react --source skills-sh
superforecasting-agent skills inspect skills-sh/vercel-labs/json-render/json-render-react
superforecasting-agent skills install skills-sh/vercel-labs/json-render/json-render-react --force
```

#### 3. Well-known skill endpoints (`well-known`)

This is URL-based discovery from sites that publish `/.well-known/skills/index.json`. It is a discovery convention, not a single central registry.

- Example endpoint: [Mintlify docs skills index](https://mintlify.com/docs/.well-known/skills/index.json)
- Reference implementation: [vercel-labs/skills-handler](https://github.com/vercel-labs/skills-handler)

```bash
superforecasting-agent skills search https://mintlify.com/docs --source well-known
superforecasting-agent skills inspect well-known:https://mintlify.com/docs/.well-known/skills/mintlify
superforecasting-agent skills install well-known:https://mintlify.com/docs/.well-known/skills/mintlify
```

#### 4. Direct GitHub skills (`github`)

Superforecasting Agent can install directly from GitHub repositories and GitHub-based taps. This is useful when you already know the repo/path or want to add your own custom source repo.

Default taps that can be browsed without extra setup include:

- [openai/skills](https://github.com/openai/skills)
- [anthropics/skills](https://github.com/anthropics/skills)
- [huggingface/skills](https://github.com/huggingface/skills)
- [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)
- [garrytan/gstack](https://github.com/garrytan/gstack)

```bash
superforecasting-agent skills install openai/skills/k8s
superforecasting-agent skills tap add myorg/forecasting-skills
```

#### 5. ClawHub (`clawhub`)

ClawHub is a third-party skills marketplace integrated as a community source.

- Site: [clawhub.ai](https://clawhub.ai/)
- Source id: `clawhub`

#### 6. Claude marketplace-style repos (`claude-marketplace`)

Superforecasting Agent supports marketplace repos that publish Claude-compatible plugin or marketplace manifests.

Known integrated sources include:

- [anthropics/skills](https://github.com/anthropics/skills)
- [aiskillstore/marketplace](https://github.com/aiskillstore/marketplace)

Source id: `claude-marketplace`

#### 7. LobeHub (`lobehub`)

Superforecasting Agent can search and convert agent entries from LobeHub's public catalog into installable skills.

- Site: [LobeHub](https://lobehub.com/)
- Public agents index: [chat-agents.lobehub.com](https://chat-agents.lobehub.com/)
- Backing repo: [lobehub/lobe-chat-agents](https://github.com/lobehub/lobe-chat-agents)
- Source id: `lobehub`

#### 8. browse.sh (`browse-sh`)

Superforecasting Agent integrates with [browse.sh](https://browse.sh), Browserbase's catalog of site-specific browser-automation `SKILL.md` files. These can be useful for evidence discovery on websites that require structured browser interaction.

- Site: [browse.sh](https://browse.sh/)
- Catalog API: `https://browse.sh/api/skills`
- Source id: `browse-sh`
- Trust level: `community`

```bash
superforecasting-agent skills search airbnb --source browse-sh
superforecasting-agent skills inspect browse-sh/airbnb.com/search-listings-ddgioa
superforecasting-agent skills install browse-sh/airbnb.com/search-listings-ddgioa
```

Identifiers use `browse-sh/<hostname>/<task-id>`. Content is resolved through the per-skill detail endpoint, not through the catalog's GitHub `sourceUrl`.

#### 9. Direct URL (`url`)

Install a single-file `SKILL.md` directly from any HTTP(S) URL. This is useful when an author hosts a skill on their own site without a hub listing.

- Source id: `url`
- Identifier: the URL itself
- Scope: single-file `SKILL.md` only

```bash
superforecasting-agent skills install https://example.com/SKILL.md
superforecasting-agent skills install https://example.com/my-skill/SKILL.md --category productivity
```

Name resolution:

1. `name:` field in the SKILL.md YAML frontmatter.
2. Parent directory name from the URL path when valid.
3. Interactive prompt on a terminal with a TTY.
4. A clean error on non-interactive surfaces pointing at `--name`.

```bash
superforecasting-agent skills install https://example.com/SKILL.md --name source-watch
```

Trust level is always `community`. The same security scan runs as for every other source. The URL is stored as the install identifier, so `superforecasting-agent skills update` re-fetches from the same URL.

### Security Scanning and `--force`

All hub-installed skills go through a security scanner that checks for data exfiltration, prompt injection, destructive commands, supply-chain signals, and other threats.

`superforecasting-agent skills inspect ...` also surfaces upstream metadata when available:

- Repo URL.
- Skills.sh detail page URL.
- Install command.
- Weekly installs.
- Upstream security audit statuses.
- Well-known index and endpoint URLs.

Use `--force` only after reviewing a third-party skill and deciding a non-dangerous policy block is acceptable:

```bash
superforecasting-agent skills install skills-sh/anthropics/skills/pdf --force
```

Important behavior:

- `--force` can override caution or warning findings.
- `--force` does not override a `dangerous` scan verdict.
- Official optional skills are treated as builtin trust and do not show the third-party warning panel.

### Trust Levels

| Level | Source | Policy |
|-------|--------|--------|
| `builtin` | Bundled skills in the repo | Always trusted |
| `official` | `optional-skills/` in the repo | Builtin trust, no third-party warning |
| `trusted` | Trusted registries/repos such as `openai/skills`, `anthropics/skills`, `huggingface/skills` | More permissive policy than community sources |
| `community` | Everything else | Non-dangerous findings can be overridden with `--force`; `dangerous` verdicts stay blocked |

### Update Lifecycle

The hub tracks enough provenance to re-check upstream copies of installed skills:

```bash
superforecasting-agent skills check
superforecasting-agent skills update
superforecasting-agent skills update react
```

This uses the stored source identifier plus the current upstream bundle content hash to detect drift.

:::tip GitHub rate limits
Skills Hub operations use the GitHub API, which has a rate limit of 60 requests/hour for unauthenticated users. If you see rate-limit errors during install or search, set `GITHUB_TOKEN` in your `.env` file to increase the limit to 5,000 requests/hour. The error message includes an actionable hint when this happens.
:::

### Publishing a Custom Skill Tap

If you want to share a curated set of skills with a team, organization, or public audience, publish them as a tap: a GitHub repository other users add with `superforecasting-agent skills tap add <owner/repo>`.

#### Repo layout

```text
owner/repo
├── skills/                       # Default path; configurable per tap
│   ├── macro-policy-watch/
│   │   ├── SKILL.md              # Required
│   │   ├── references/
│   │   ├── templates/
│   │   └── scripts/
│   └── source-review/
│       └── SKILL.md
└── README.md
```

Rules:

- Each skill lives in its own directory under the tap root path.
- The directory name becomes the install slug.
- Each skill directory must contain `SKILL.md` with standard [SKILL.md frontmatter](#skillmd-format).
- Supporting `references/`, `templates/`, `scripts/`, and `assets/` are downloaded at install time.
- Directories starting with `.` or `_` are ignored.

The runtime discovers skills by listing every subdirectory of the tap path and probing each for `SKILL.md`.

#### Minimal tap example

```text
my-org/forecasting-skills
└── skills/
    └── source-review/
        └── SKILL.md
```

`skills/source-review/SKILL.md`:

```markdown
---
name: source-review
description: Review source quality before ledger import.
version: 1.0.0
author: My Org Forecasting Team
metadata:
  hermes:
    tags: [forecasting, evidence, review]
---

# Source Review

Step 1: ...
```

After pushing that to GitHub, any user can subscribe and install:

```bash
superforecasting-agent skills tap add my-org/forecasting-skills
superforecasting-agent skills search source-review
superforecasting-agent skills install my-org/forecasting-skills/source-review
```

#### Non-default paths

If your skills do not live under `skills/`, edit the tap entry in `~/.superforecasting-agent/.hub/taps.json`:

```json
{
  "taps": [
    {"repo": "my-org/platform-docs", "path": "internal/forecasting-skills/"}
  ]
}
```

`superforecasting-agent skills tap add` defaults new taps to `path: "skills/"`. Edit the file directly if you need a different path. `superforecasting-agent skills tap list` shows the effective path per tap.

#### Installing individual skills directly

Users can also install one skill from a public GitHub repo without adding the full repo as a tap:

```bash
superforecasting-agent skills install owner/repo/skills/my-workflow
```

#### Trust levels for taps

New taps are assigned `community` trust by default. Installed skills run through the security scan and show the third-party warning panel on first install. If your organization or a widely trusted source should get higher trust, add its repo to `TRUSTED_REPOS` in `tools/skills_hub.py`, which requires a core PR.

#### Tap management

```bash
superforecasting-agent skills tap list
superforecasting-agent skills tap add myorg/forecasting-skills
superforecasting-agent skills tap remove myorg/forecasting-skills
```

Inside a running session:

```text
/skills tap list
/skills tap add myorg/forecasting-skills
/skills tap remove myorg/forecasting-skills
```

Taps are stored in `~/.superforecasting-agent/.hub/taps.json`. Legacy homes may store the same state under `~/.hermes/.hub/taps.json` during migration.

## Bundled Skill Updates

Superforecasting Agent ships with bundled skills in `skills/` inside the repo. On install and on every managed update, a sync pass copies those into `~/.superforecasting-agent/skills/` and records a manifest at `~/.superforecasting-agent/skills/.bundled_manifest`.

On each sync, the runtime recomputes the hash of your local copy and compares it to the origin hash:

- **Unchanged**: safe to pull upstream changes, copy the new bundled version in, and record the new origin hash.
- **Changed**: treated as user-modified and skipped, so local edits are not overwritten.

If you edit a bundled skill and later want to restore the bundled version, use `superforecasting-agent skills reset`:

```bash
# Safe: clears the manifest entry for this skill. Your current copy is preserved,
# and the next sync re-baselines against it.
superforecasting-agent skills reset research-arxiv

# Full restore: also deletes your local copy and re-copies the current bundled version.
superforecasting-agent skills reset research-arxiv --restore

# Non-interactive: skip the restore confirmation.
superforecasting-agent skills reset research-arxiv --restore --yes
```

The same command works inside chat:

```text
/skills reset research-arxiv
/skills reset research-arxiv --restore
```

:::note Profiles
Each profile has its own `.bundled_manifest` under its own home, so `superforecasting-agent -p macro skills reset <name>` only affects that profile.
:::

### Slash Commands Inside Chat

The same Skills Hub commands work with `/skills`:

```text
/skills browse
/skills search forecasting --source official
/skills search https://mintlify.com/docs --source well-known
/skills inspect skills-sh/vercel-labs/json-render/json-render-react
/skills install openai/skills/skill-creator --force
/skills check
/skills update
/skills reset research-arxiv
/skills list
```

Official optional skills still use identifiers like `official/security/1password` and `official/migration/openclaw-migration`.
