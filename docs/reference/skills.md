# Skills

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Source of truth: skills/**/SKILL.md frontmatter (parsed with agent.skill_utils.parse_frontmatter) -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

> This page is generated from code. Do not edit it by hand — your change would be overwritten on the next regeneration and the staleness gate would fail. Edit the source instead, then run `python -m scripts.docgen`.

> **Source of truth:** `skills/**/SKILL.md frontmatter (parsed with agent.skill_utils.parse_frontmatter)`

The agent loads **skills** — self-contained capability bundles — on demand. There are **98 skills** in **19 categories**, indexed here straight from each `SKILL.md`'s frontmatter. *When to use* is the skill's declared `triggers` list when it has one, otherwise the `Use when…` guidance mined from its description. Skills directly under `skills/` (the forecasting desk's own) are listed first.


| category | count |
| --- | --- |
| `(top-level)` | 11 |
| `apple` | 5 |
| `autonomous-ai-agents` | 5 |
| `creative` | 20 |
| `data-science` | 1 |
| `devops` | 3 |
| `email` | 1 |
| `gaming` | 2 |
| `github` | 6 |
| `mcp` | 1 |
| `media` | 4 |
| `mlops` | 9 |
| `note-taking` | 1 |
| `productivity` | 9 |
| `red-teaming` | 1 |
| `research` | 6 |
| `smart-home` | 1 |
| `social-media` | 1 |
| `software-development` | 11 |

## (top-level)

| skill | when to use | what it does |
| --- | --- | --- |
| `apply-lesson`<br>`skills/apply-lesson` | use this to apply/strengthen one, pick its enforcement pattern, and verify it bites. Invoke after a postmortem produces a lesson, or when `forecast lessons audit` shows a lesson is ADVISORY or DORMANT, e.g. /apply-lesson cl_9ebae9c3280f | Turn a calibration LESSON into an enforced hook rule so it actually changes future forecasts instead of sitting as prose. The system auto-compiles a recognized lesson at creation; use this to apply/strengthen one, pick its enforcement pattern, and verify it bites. Invoke after a postmortem produces a lesson, or when `forecast lessons audit` shows a lesson is ADVISORY or DORMANT, e.g. /apply-lesson cl_9ebae9c3280f |
| `bayes-forecast-scratchpad`<br>`skills/bayes-forecast-scratchpad` | Use whenever you move or combine a forecast probability. | Auditable Bayesian forecasting scratchpad: likelihood-ratio updating, log-odds pooling, evidence weighting, reference-class blending, poll→probability, market de-vig, double-counting checks, sensitivity, forecast-diff, and conditional-chain decomposition with mandatory unconditional sanity-check. Use whenever you move or combine a forecast probability. |
| `dogfood`<br>`skills/dogfood` | — | Exploratory QA of web apps: find bugs, evidence, reports. |
| `forecast-onboard`<br>`skills/forecast-onboard` | Invoke when the user wants to start/track a new question, e.g. /forecast-onboard Will the Fed cut in September? | Curate a NEW forecast question with the user before committing it — propose a complete typed spec, ask only the gap-closing questions (with recommended defaults), then commit the whole setup (question + watched sources + reference classes + decision card) in one shot. Invoke when the user wants to start/track a new question, e.g. /forecast-onboard Will the Fed cut in September? |
| `forecast-rerun`<br>`skills/forecast-rerun` | — | Re-run an existing forecast the proper way: pull the latest watched-source readings, collect genuinely new evidence, re-pool with STRUCTURED components, and commit a fresh live snapshot — instead of redoing imports by hand. Invoke by NAME, e.g. /forecast-rerun May CPI — no UUID needed. |
| `forecasting-loop`<br>`skills/forecasting-loop` | Use when running a forecast end-to-end, or when unsure which stage comes next. | The guided superforecasting loop: parse -> research -> base_rate -> model -> update -> resolve -> postmortem, driven by `forecast pipeline`. Sequences a question through the stages, reports what is done from ledger artifacts, and refuses to advance to a committed forecast before an outside view (base rate) and source-backed evidence exist. Use when running a forecast end-to-end, or when unsure which stage comes next. |
| `information-triage`<br>`skills/information-triage` | Invoke when a candidate stream is large, when deciding what to read/import, or whenever you are about to import many sources as evidence at once, e.g. /information-triage | How to TRIAGE a stream of readings before it becomes evidence — decide what is relevant_interesting vs relevant_uninteresting vs irrelevant (keep/skim/skip) against the desk rubric, score the labeler, and route disputed auto-labels to operator hand-labeling. Invoke when a candidate stream is large, when deciding what to read/import, or whenever you are about to import many sources as evidence at once, e.g. /information-triage |
| `ledger-interaction`<br>`skills/ledger-interaction` | Invoke before any bulk or batch ledger work, or whenever you are tempted to write a Python script that touches the ledger, e.g. /ledger-interaction | How to read and write the forecast ledger correctly. WRITES (questions, forecasts, evidence, panels, lessons, resolutions) go through the forecast tool's gated, per-question flow — NOT through scripts that import ForecastLedger or hit its SQLite file. Scripting is for read-only audits and rare one-off migrations only. Invoke before any bulk or batch ledger work, or whenever you are tempted to write a Python script that touches the ledger, e.g. /ledger-interaction |
| `path-driven-forecast`<br>`skills/path-driven-forecast` | Use before committing any live forecast, especially binary and numeric questions: anchor on the status quo and horizon, trace and price the path to each outcome, reconcile against the market, stress the tails, then commit with conviction. Complements the forecasting-loop pipeline and the bayes-forecast-scratchpad. | The path-driven reasoning rubric that turns a junior forecast (a number from a vibe) into a senior one (a number that falls out of a priced causal path). Use before committing any live forecast, especially binary and numeric questions: anchor on the status quo and horizon, trace and price the path to each outcome, reconcile against the market, stress the tails, then commit with conviction. Complements the forecasting-loop pipeline and the bayes-forecast-scratchpad. |
| `quorum-forecast`<br>`skills/quorum-forecast` | Use for high-impact or first forecasts, when you want model-architecture diversity and an explicit disagreement reading — not just one model's view. | Run a model-diverse forecast quorum (the superforecaster's 'Fusion'): dispatch one forecasting brief to a panel of independent models via OpenRouter, then a judge synthesizes a senior-desk verdict. Records a sibling panel run with a first-class disagreement signal, and feeds the senior process (reasons_up/down, change_my_mind, ensemble_components). Use for high-impact or first forecasts, when you want model-architecture diversity and an explicit disagreement reading — not just one model's view. |
| `yuanbao`<br>`skills/yuanbao` | — | Yuanbao (元宝) groups: @mention users, query info/members. |

## apple

| skill | when to use | what it does |
| --- | --- | --- |
| `apple-notes`<br>`skills/apple/apple-notes` | — | Manage Apple Notes via memo CLI: create, search, edit. |
| `apple-reminders`<br>`skills/apple/apple-reminders` | — | Apple Reminders via remindctl: add, list, complete. |
| `findmy`<br>`skills/apple/findmy` | — | Track Apple devices/AirTags via FindMy.app on macOS. |
| `imessage`<br>`skills/apple/imessage` | — | Send and receive iMessages/SMS via the imsg CLI on macOS. |
| `macos-computer-use`<br>`skills/apple/macos-computer-use` | — | Drive the macOS desktop in the background — screenshots, mouse, keyboard, scroll, drag — without stealing the user's cursor, keyboard focus, or Space. Works with any tool-capable model. Load this skill whenever the `computer_use` tool is available. |

## autonomous-ai-agents

| skill | when to use | what it does |
| --- | --- | --- |
| `claude-code`<br>`skills/autonomous-ai-agents/claude-code` | — | Delegate coding to Claude Code CLI (features, PRs). |
| `codex`<br>`skills/autonomous-ai-agents/codex` | — | Delegate coding to OpenAI Codex CLI (features, PRs). |
| `kanban-codex-lane`<br>`skills/autonomous-ai-agents/kanban-codex-lane` | Use when a Superforecasting Agent Kanban worker wants to run Codex CLI as an isolated implementation lane while Superforecasting Agent keeps ownership of task lifecycle, reconciliation, testing, and handoff. | Use when a Superforecasting Agent Kanban worker wants to run Codex CLI as an isolated implementation lane while Superforecasting Agent keeps ownership of task lifecycle, reconciliation, testing, and handoff. |
| `opencode`<br>`skills/autonomous-ai-agents/opencode` | — | Delegate coding to OpenCode CLI (features, PR review). |
| `superforecasting-agent`<br>`skills/autonomous-ai-agents/hermes-agent` | — | Configure, extend, or contribute to Superforecasting Agent. |

## creative

| skill | when to use | what it does |
| --- | --- | --- |
| `architecture-diagram`<br>`skills/creative/architecture-diagram` | — | Dark-themed SVG architecture/cloud/infra diagrams as HTML. |
| `ascii-art`<br>`skills/creative/ascii-art` | — | ASCII art: pyfiglet, cowsay, boxes, image-to-ascii. |
| `ascii-video`<br>`skills/creative/ascii-video` | — | ASCII video: convert video/audio to colored ASCII MP4/GIF. |
| `baoyu-article-illustrator`<br>`skills/creative/baoyu-article-illustrator` | — | Article illustrations: type × style × palette consistency. |
| `baoyu-comic`<br>`skills/creative/baoyu-comic` | — | Knowledge comics (知识漫画): educational, biography, tutorial. |
| `baoyu-infographic`<br>`skills/creative/baoyu-infographic` | — | Infographics: 21 layouts x 21 styles (信息图, 可视化). |
| `claude-design`<br>`skills/creative/claude-design` | — | Design one-off HTML artifacts (landing, deck, prototype). |
| `comfyui`<br>`skills/creative/comfyui` | — | Generate images, video, and audio with ComfyUI — install, launch, manage nodes/models, run workflows with parameter injection. Uses the official comfy-cli for lifecycle and direct REST/WebSocket API for execution. |
| `design-md`<br>`skills/creative/design-md` | — | Author/validate/export Google's DESIGN.md token spec files. |
| `excalidraw`<br>`skills/creative/excalidraw` | — | Hand-drawn Excalidraw JSON diagrams (arch, flow, seq). |
| `humanizer`<br>`skills/creative/humanizer` | — | Humanize text: strip AI-isms and add real voice. |
| `ideation`<br>`skills/creative/creative-ideation` | — | Generate project ideas via creative constraints. |
| `manim-video`<br>`skills/creative/manim-video` | — | Manim CE animations: 3Blue1Brown math/algo videos. |
| `p5js`<br>`skills/creative/p5js` | — | p5.js sketches: gen art, shaders, interactive, 3D. |
| `pixel-art`<br>`skills/creative/pixel-art` | — | Pixel art w/ era palettes (NES, Game Boy, PICO-8). |
| `popular-web-designs`<br>`skills/creative/popular-web-designs` | build a page that looks like; make it look like stripe; design like linear; vercel style; create a UI; web design; landing page; dashboard design; website styled like | 54 real design systems (Stripe, Linear, Vercel) as HTML/CSS. |
| `pretext`<br>`skills/creative/pretext` | Use when building creative browser demos with @chenglou/pretext — DOM-free text layout for ASCII art, typographic flow around obstacles, text-as-geometry games, kinetic typography, and text-powered generative art. Produces single-file HTML demos by default. | Use when building creative browser demos with @chenglou/pretext — DOM-free text layout for ASCII art, typographic flow around obstacles, text-as-geometry games, kinetic typography, and text-powered generative art. Produces single-file HTML demos by default. |
| `sketch`<br>`skills/creative/sketch` | — | Throwaway HTML mockups: 2-3 design variants to compare. |
| `songwriting-and-ai-music`<br>`skills/creative/songwriting-and-ai-music` | writing a song; song lyrics; music prompt; suno prompt; parody song; adapting a song; AI music generation | Songwriting craft and Suno AI music prompts. |
| `touchdesigner-mcp`<br>`skills/creative/touchdesigner-mcp` | — | Control a running TouchDesigner instance via twozero MCP — create operators, set parameters, wire connections, execute Python, build real-time visuals. 36 native tools. |

## data-science

| skill | when to use | what it does |
| --- | --- | --- |
| `jupyter-live-kernel`<br>`skills/data-science/jupyter-live-kernel` | — | Iterative Python via live Jupyter kernel (hamelnb). |

## devops

| skill | when to use | what it does |
| --- | --- | --- |
| `kanban-orchestrator`<br>`skills/devops/kanban-orchestrator` | — | Decomposition playbook + anti-temptation rules for an orchestrator profile routing work through Kanban. The "don't do the work yourself" rule and the basic lifecycle are auto-injected into every kanban worker's system prompt; this skill is the deeper playbook when you're specifically playing the orchestrator role. |
| `kanban-worker`<br>`skills/devops/kanban-worker` | — | Pitfalls, examples, and edge cases for Superforecasting Agent Kanban workers. The lifecycle itself is auto-injected into every worker's system prompt as KANBAN_GUIDANCE (from agent/prompt_builder.py); this skill is what you load when you want deeper detail on specific scenarios. |
| `webhook-subscriptions`<br>`skills/devops/webhook-subscriptions` | — | Webhook subscriptions: event-driven agent runs. |

## email

| skill | when to use | what it does |
| --- | --- | --- |
| `himalaya`<br>`skills/email/himalaya` | — | Himalaya CLI: IMAP/SMTP email from terminal. |

## gaming

| skill | when to use | what it does |
| --- | --- | --- |
| `minecraft-modpack-server`<br>`skills/gaming/minecraft-modpack-server` | — | Host modded Minecraft servers (CurseForge, Modrinth). |
| `pokemon-player`<br>`skills/gaming/pokemon-player` | — | Play Pokemon via headless emulator + RAM reads. |

## github

| skill | when to use | what it does |
| --- | --- | --- |
| `codebase-inspection`<br>`skills/github/codebase-inspection` | — | Inspect codebases w/ pygount: LOC, languages, ratios. |
| `github-auth`<br>`skills/github/github-auth` | — | GitHub auth setup: HTTPS tokens, SSH keys, gh CLI login. |
| `github-code-review`<br>`skills/github/github-code-review` | — | Review PRs: diffs, inline comments via gh or REST. |
| `github-issues`<br>`skills/github/github-issues` | — | Create, triage, label, assign GitHub issues via gh or REST. |
| `github-pr-workflow`<br>`skills/github/github-pr-workflow` | — | GitHub PR lifecycle: branch, commit, open, CI, merge. |
| `github-repo-management`<br>`skills/github/github-repo-management` | — | Clone/create/fork repos; manage remotes, releases. |

## mcp

| skill | when to use | what it does |
| --- | --- | --- |
| `native-mcp`<br>`skills/mcp/native-mcp` | — | MCP client: connect servers, register tools (stdio/HTTP). |

## media

| skill | when to use | what it does |
| --- | --- | --- |
| `gif-search`<br>`skills/media/gif-search` | — | Search/download GIFs from Tenor via curl + jq. |
| `heartmula`<br>`skills/media/heartmula` | — | HeartMuLa: Suno-like song generation from lyrics + tags. |
| `songsee`<br>`skills/media/songsee` | — | Audio spectrograms/features (mel, chroma, MFCC) via CLI. |
| `youtube-content`<br>`skills/media/youtube-content` | — | YouTube transcripts to summaries, threads, blogs. |

## mlops

| skill | when to use | what it does |
| --- | --- | --- |
| `audiocraft-audio-generation`<br>`skills/mlops/models/audiocraft` | — | AudioCraft: MusicGen text-to-music, AudioGen text-to-sound. |
| `dspy`<br>`skills/mlops/research/dspy` | — | DSPy: declarative LM programs, auto-optimize prompts, RAG. |
| `evaluating-llms-harness`<br>`skills/mlops/evaluation/lm-evaluation-harness` | — | lm-eval-harness: benchmark LLMs (MMLU, GSM8K, etc.). |
| `huggingface-hub`<br>`skills/mlops/huggingface-hub` | — | HuggingFace hf CLI: search/download/upload models, datasets. |
| `llama-cpp`<br>`skills/mlops/inference/llama-cpp` | — | llama.cpp local GGUF inference + HF Hub model discovery. |
| `obliteratus`<br>`skills/mlops/inference/obliteratus` | — | OBLITERATUS: abliterate LLM refusals (diff-in-means). |
| `segment-anything-model`<br>`skills/mlops/models/segment-anything` | — | SAM: zero-shot image segmentation via points, boxes, masks. |
| `serving-llms-vllm`<br>`skills/mlops/inference/vllm` | — | vLLM: high-throughput LLM serving, OpenAI API, quantization. |
| `weights-and-biases`<br>`skills/mlops/evaluation/weights-and-biases` | — | W&B: log ML experiments, sweeps, model registry, dashboards. |

## note-taking

| skill | when to use | what it does |
| --- | --- | --- |
| `obsidian`<br>`skills/note-taking/obsidian` | — | Read, search, create, and edit notes in the Obsidian vault, and publish forecast learnings into it. |

## productivity

| skill | when to use | what it does |
| --- | --- | --- |
| `airtable`<br>`skills/productivity/airtable` | — | Airtable REST API via curl. Records CRUD, filters, upserts. |
| `google-workspace`<br>`skills/productivity/google-workspace` | — | Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python. |
| `linear`<br>`skills/productivity/linear` | — | Linear: manage issues, projects, teams via GraphQL + curl. |
| `maps`<br>`skills/productivity/maps` | — | Geocode, POIs, routes, timezones via OpenStreetMap/OSRM. |
| `nano-pdf`<br>`skills/productivity/nano-pdf` | — | Edit PDF text/typos/titles via nano-pdf CLI (NL prompts). |
| `notion`<br>`skills/productivity/notion` | — | Notion API + ntn CLI: pages, databases, markdown, Workers. |
| `ocr-and-documents`<br>`skills/productivity/ocr-and-documents` | — | Extract text from PDFs/scans (pymupdf, marker-pdf). |
| `powerpoint`<br>`skills/productivity/powerpoint` | — | Create, read, edit .pptx decks, slides, notes, templates. |
| `teams-meeting-pipeline`<br>`skills/productivity/teams-meeting-pipeline` | — | Operate the Teams meeting summary pipeline via Superforecasting Agent CLI — summarize meetings, inspect pipeline status, replay jobs, manage Microsoft Graph subscriptions. |

## red-teaming

| skill | when to use | what it does |
| --- | --- | --- |
| `godmode`<br>`skills/red-teaming/godmode` | — | Evaluate LLM safety behavior with red-team probes. |

## research

| skill | when to use | what it does |
| --- | --- | --- |
| `arxiv`<br>`skills/research/arxiv` | — | Search arXiv papers by keyword, author, category, or ID. |
| `blogwatcher`<br>`skills/research/blogwatcher` | — | Monitor blogs and RSS/Atom feeds via blogwatcher-cli tool. |
| `grounded-citations`<br>`skills/research/grounded-citations` | — | Ground answers and documents in cited, verifiable sources. |
| `llm-wiki`<br>`skills/research/llm-wiki` | — | Karpathy's LLM Wiki: build/query interlinked markdown KB. |
| `polymarket`<br>`skills/research/polymarket` | — | Query Polymarket: markets, prices, orderbooks, history. |
| `research-paper-writing`<br>`skills/research/research-paper-writing` | — | Write ML papers for NeurIPS/ICML/ICLR: design→submit. |

## smart-home

| skill | when to use | what it does |
| --- | --- | --- |
| `openhue`<br>`skills/smart-home/openhue` | — | Control Philips Hue lights, scenes, rooms via OpenHue CLI. |

## social-media

| skill | when to use | what it does |
| --- | --- | --- |
| `xurl`<br>`skills/social-media/xurl` | — | X/Twitter via xurl CLI: post, search, DM, media, v2 API. |

## software-development

| skill | when to use | what it does |
| --- | --- | --- |
| `debugging-superforecasting-tui-commands`<br>`skills/software-development/debugging-hermes-tui-commands` | — | Debug forecast TUI slash commands. |
| `node-inspect-debugger`<br>`skills/software-development/node-inspect-debugger` | — | Debug Node.js via --inspect + Chrome DevTools Protocol CLI. |
| `plan`<br>`skills/software-development/plan` | — | Plan mode: write markdown plan to .superforecasting-agent/plans/, no exec. |
| `python-debugpy`<br>`skills/software-development/python-debugpy` | — | Debug Python: pdb REPL + debugpy remote (DAP). |
| `requesting-code-review`<br>`skills/software-development/requesting-code-review` | — | Pre-commit review: security scan, quality gates, auto-fix. |
| `spike`<br>`skills/software-development/spike` | — | Throwaway experiments to validate an idea before build. |
| `subagent-driven-development`<br>`skills/software-development/subagent-driven-development` | — | Execute plans via delegate_task subagents (2-stage review). |
| `superforecasting-agent-skill-authoring`<br>`skills/software-development/hermes-agent-skill-authoring` | — | Author in-repo SKILL.md: frontmatter, validator, structure. |
| `systematic-debugging`<br>`skills/software-development/systematic-debugging` | — | 4-phase root cause debugging: understand bugs before fixing. |
| `test-driven-development`<br>`skills/software-development/test-driven-development` | — | TDD: enforce RED-GREEN-REFACTOR, tests before code. |
| `writing-plans`<br>`skills/software-development/writing-plans` | — | Write implementation plans: bite-sized tasks, paths, code. |
