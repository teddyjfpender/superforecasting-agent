<p align="center">
  <img src="assets/banner.png" alt="Superforecasting Agent" width="100%">
</p>

# Superforecasting Agent

<p align="center">
  <a href="docs/plans/2026-05-20-superforecasting-agent-fork-prd.md"><img src="https://img.shields.io/badge/Docs-forecasting%20PRD-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="https://discord.gg/NousResearch"><img src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://nousresearch.com"><img src="https://img.shields.io/badge/Forked%20from-Hermes%20Agent-blueviolet?style=for-the-badge" alt="Forked from Hermes Agent"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/Lang-中文-red?style=for-the-badge" alt="中文"></a>
</p>

**A CLI-first forecasting desk forked from Hermes Agent.** The core product primitive is the scoreable forecast: a durable question with an append-only probability history, timestamped evidence, assumptions, reference classes, model runs, resolutions, scores, postmortems, and calibration lessons. The north star is a command-line forecasting desk that compounds judgment over time.

This fork keeps the useful Hermes runtime pieces: model-provider adapters, local storage, tool execution, logging, profiles, plugins, and the CLI/TUI foundation. It demotes broad chat, gateway-first messaging, and generic assistant memory behind forecasting workflows.

Use any model you want — [Nous Portal](https://portal.nousresearch.com), [OpenRouter](https://openrouter.ai) (200+ models), [NovitaAI](https://novita.ai) (AI-native cloud for Model API, Agent Sandbox, and GPU Cloud), [NVIDIA NIM](https://build.nvidia.com) (Nemotron), [Xiaomi MiMo](https://platform.xiaomimimo.com), [z.ai/GLM](https://z.ai), [Kimi/Moonshot](https://platform.moonshot.ai), [MiniMax](https://www.minimax.io), [Hugging Face](https://huggingface.co), OpenAI, or your own endpoint. Switch with `superforecasting-agent model` — no code changes, no lock-in.

<table>
<tr><td><b>Forecast ledger</b></td><td>Create, research, update, resolve, score, and postmortem forecasts from the CLI with append-only snapshots and auditable source trails.</td></tr>
<tr><td><b>Calibration loop</b></td><td>Track Brier/log scores, calibration buckets, sharpness, horizon/domain performance, error profiles, and provenance-linked calibration lessons.</td></tr>
<tr><td><b>Backtesting</b></td><td>Replay resolved questions under explicit evidence cutoffs, compare against base-rate, crowd, and market baselines, and keep live/backtest/baseline scores separate.</td></tr>
<tr><td><b>Self-checks</b></td><td>Use scheduled reviews, watched sources, and alerts to surface stale forecasts, new evidence, invalidated assumptions, and resolution work without silently changing probabilities.</td></tr>
<tr><td><b>Adapters, not centerpieces</b></td><td>Import context from Metaculus, Manifold, Polymarket, Kalshi, GDELT, FRED, EIA, U.S. Treasury Fiscal Data, BLS, World Bank, Stooq, Yahoo Finance, CoinGecko, SEC EDGAR, arXiv, OpenAlex, PubMed, Wikipedia, Wikimedia pageviews, GitHub, PyPI, npm, Hacker News, Reddit, Federal Register, CourtListener, NVD, Open-Meteo, USGS earthquakes, NASA EONET natural events, National Weather Service alerts, OWID, market files, RSS/Atom feeds, and generic benchmark datasets while keeping the ledger platform-neutral.</td></tr>
<tr><td><b>Inherited runtime</b></td><td>Reuse provider routing, tools, plugins, profiles, logging, terminal execution, and optional chat/TUI infrastructure where they improve forecasting workflows.</td></tr>
</table>

---

## Quick Install

This fork is installed from the repo checkout while the packaging and installer names finish moving away from Hermes:

```bash
git clone <this-fork-url> superforecasting-agent
cd superforecasting-agent
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
```

On native Windows, use the PowerShell installer:

```powershell
iex (irm https://raw.githubusercontent.com/NousResearch/superforecasting-agent/main/scripts/install.ps1)
```

After installation or editable setup:

```bash
forecast            # open the forecast desk
superforecasting-agent  # fork-native command; forecast workflows are shorthand
python -m superforecasting_agent status
# or:
hermes              # also opens the forecast desk during the fork transition
```

---

## Getting Started

```bash
forecast status     # Show the forecasting desk state
python3 scripts/forecast_smoke_test.py  # Local tester-readiness smoke test
forecast new "Will X happen?" --resolution-criteria "Resolved by ..."
forecast list       # List standing forecasts
forecast review     # Find stale forecasts and upcoming work
forecast self-check --auto-score --auto-postmortem
forecast calibration
forecast calibration --by-origin --all
forecast sources
forecast backtest --benchmarks
forecast backtest --all-benchmarks --probability-source forecast-engine
forecast backtest builtin:manifold-public-120-binary --probability-source forecast-engine
forecast backtest path/to/cases.json --probability-source agent-protocol --agent-response-jsonl path/to/agent-responses.jsonl
forecast backtest path/to/cases.json --probability-source agent-protocol --agent-output-jsonl path/to/captured-responses.jsonl
forecast performance --last 5
forecast performance --last 5 --json
forecast readiness
forecast readiness --json
forecast readiness --require-evidence
forecast pilot-report
forecast pilot-report --json
forecast pilot-aggregate .pilot/*-export.json --json
# readiness shows evidence gaps and next actions before stronger performance claims
superforecasting-agent chat       # Forecast-scoped chat remains available explicitly
superforecasting-agent dashboard  # Open the forecast-first dashboard
superforecasting-agent model      # Choose your LLM provider and model
superforecasting-agent tools      # Configure which tools are enabled for agent workflows
superforecasting-agent setup      # Run the full setup wizard
superforecasting-agent gateway    # Legacy optional messaging gateway surface
superforecasting-agent-acp        # Direct fork-native ACP server script for editor clients
```

📖 **Fork plans:** [PRD](docs/plans/2026-05-20-superforecasting-agent-fork-prd.md) · [Context](docs/plans/2026-05-20-superforecasting-agent-fork-context.md)

## Forecasting Quick Reference

The forecast ledger is the product surface. Generic chat and messaging gateways remain available during the fork transition, but they are subordinate to the forecast lifecycle.

| Action | Command |
|---------|---------|
| Open the desk | `forecast` or bare `superforecasting-agent` |
| Create a question | `forecast new "Will X happen?" --resolution-criteria "Resolved by ..."` |
| Add evidence | `forecast evidence add <id> <url-or-note>` |
| Research without moving probability | `forecast research <id> <source...>` |
| Discover source adapters | `forecast sources` or `forecast sources --json` |
| Import data rows as evidence | `forecast import data indicators.csv --question <id>` |
| Import economic/fiscal/demographic/market data | `forecast import fred UNRATE --question <id>`, `forecast import treasury v2/accounting/od/avg_interest_rates --question <id>`, `forecast import bls LNS14000000 --question <id>`, `forecast import worldbank USA/NY.GDP.MKTP.CD --question <id>`, `forecast import census "2023/acs/acs5?get=NAME,B01003_001E&for=state:*" --question <id>`, `forecast import stooq AAPL.US --question <id>`, `forecast import yahoo AAPL --question <id>`, or `forecast import coingecko bitcoin --question <id>` |
| Import company filings | `forecast import sec 0000320193 --question <id>` |
| Import research papers | `forecast import arxiv "cat:cs.AI AND forecasting" --question <id>` or `forecast import openalex "forecasting calibration" --question <id>` |
| Import reference/software/policy/legal/security/weather/geophysical/health/public data | `forecast import wikipedia "topic" --question <id>`, `forecast import wikipediapageviews en.wikipedia.org/Topic --question <id>`, `forecast import github owner/repo --question <id>`, `forecast import githubissues owner/repo --question <id>`, `forecast import githubcommits owner/repo --question <id>`, `forecast import pypi package-name --question <id>`, `forecast import npm package-name --question <id>`, `forecast import hackernews "product query" --question <id>`, `forecast import reddit "topic query" --question <id>`, `forecast import federalregister "rule query" --question <id>`, `forecast import courtlistener "case or legal query" --question <id>`, `forecast import nvd CVE-2026-0001 --question <id>`, `forecast import cisakev CVE-2026-0001 --question <id>`, `forecast import clinicaltrials "NCT01234567" --question <id>`, `forecast import openfda "BLA125514" --question <id>`, `forecast import pubmed "forecasting calibration" --question <id>`, `forecast import openmeteo 38.7,-9.1 --question <id>`, `forecast import usgs "minmagnitude=5" --question <id>`, `forecast import eonet "category=wildfires&status=open" --question <id>`, `forecast import nws "area=CA&event=Flood Warning" --question <id>`, or `forecast import owid grapher-slug --question <id>` |
| Estimate a base rate | `forecast base-rate <id> ...` |
| Run a model | `forecast model <id> --type bayesian_update ...` |
| Save a forecast update | `forecast update <id> --probability 0.63 --rationale "..."` |
| Save a numeric forecast | `forecast update <id> --numeric-value 123.4 --rationale "..."` |
| Review stale beliefs | `forecast review --stale` |
| Resolve and score | `forecast resolve <id> --outcome yes && forecast score <id>` |
| Diagnose errors | `forecast postmortem <id>`, `forecast errors`, and `forecast calibration --by-origin --all` |
| Backtest | `forecast backtest builtin:heldout-120-binary` |
| Run benchmark suite | `forecast backtest --all-benchmarks --probability-source forecast-engine` |
| Replay forecast engine | `forecast backtest builtin:manifold-public-120-binary --probability-source forecast-engine` |
| Replay captured agent protocol | `forecast backtest cases.json --probability-source agent-protocol --agent-response-jsonl responses.jsonl` |
| Capture agent protocol outputs | `forecast backtest cases.json --probability-source agent-protocol --agent-output-jsonl captured.jsonl` |
| Review backtest performance | `forecast performance --last 5` or `forecast performance --last 5 --json` |
| Check claim readiness | `forecast readiness`, `forecast readiness --json`, or `forecast readiness --require-evidence` |
| Check tester pilot coverage | `forecast pilot-report` or `forecast pilot-report --json` |
| Aggregate tester exports | `forecast pilot-aggregate tester-a.json tester-b.json --json` |
| Import tournament exports | `forecast import tournament resolved_questions.json --name my-tournament` |
| Watch sources | `forecast watch add --question <id> rss:<feed-or-file>`, `gdelt:<query>`, `fred:<series-id>`, `eia:<series-id-or-api-url>`, `treasury:<dataset-path-or-api-url>`, `bls:<series-id>`, `worldbank:<country>/<indicator>`, `census:<dataset-path?get=...&for=...>`, `stooq:<symbol-or-csv-url>`, `yahoo:<symbol>`, `coingecko:<coin-id>`, `sec:<cik>`, `arxiv:<query>`, `openalex:<query>`, `wikipedia:<query>`, `wikipediapageviews:<project>/<article>`, `github:<owner/repo>`, `githubissues:<owner/repo>`, `githubcommits:<owner/repo>`, `pypi:<package>`, `npm:<package>`, `hackernews:<query>`, `reddit:<query>`, `federalregister:<query>`, `courtlistener:<query>`, `nvd:<keyword-or-CVE>`, `cisakev:<keyword-or-CVE-or-all>`, `clinicaltrials:<query-or-NCT-id>`, `openfda:<query-or-application-number>`, `pubmed:<query-or-PMID>`, `openmeteo:<lat,lon>`, `usgs:<query>`, `eonet:<query-or-category>`, `nws:<area-or-point-or-query>`, `owid:<slug>`, or market-prior watches such as `manifold:<slug>`, `metaculus:<id>`, `polymarket:<slug>`, and `kalshi:<ticker>` |
| Schedule scoped learning | `forecast schedule add --domain macro --topic inflation --cadence 1d --next-run-at <time> --stale-days 3 --auto-score --auto-postmortem` or `forecast schedule add --horizon 30 --cadence 1d --next-run-at <time>` |

In the TUI, `/forecast` opens the structured forecast desk panel; `/new-forecast`, `/base-rate`, `/update-forecast`, `/resolve`, `/score`, `/postmortem`, `/review`, `/alerts`, `/calibration`, `/lessons`, `/backtest`, `/schedule`, `/performance`, and `/readiness` jump to common desk workflows; and `/forecast <subcommand>` remains available for the full forecast CLI.

Runtime state defaults to `~/.superforecasting-agent` for new installs. Existing `~/.hermes` homes are reused during the fork transition, and deployments can set `SUPERFORECASTING_AGENT_HOME` or `FORECAST_HOME` instead of the legacy `HERMES_HOME` variable.
Dashboard overrides also accept `SUPERFORECASTING_AGENT_WEB_DIST`/`FORECAST_WEB_DIST` and `SUPERFORECASTING_AGENT_DASHBOARD_TUI`/`FORECAST_DASHBOARD_TUI` ahead of the legacy Hermes environment names.

---

## Documentation

The fork documentation leads with forecasting workflows. Inherited runtime features are documented with compatibility notes where legacy Hermes names still appear in APIs, env vars, or module paths:

| Section | What's Covered |
|---------|---------------|
| [Quickstart](https://superforecasting-agent.nousresearch.com/docs/getting-started/quickstart) | Install and setup |
| [Tester Smoke Test](https://superforecasting-agent.nousresearch.com/docs/getting-started/forecast-smoke-test) | Local lifecycle, self-check, and backtest acceptance check |
| [CLI Usage](https://superforecasting-agent.nousresearch.com/docs/user-guide/cli) | Forecast desk commands and inherited keybindings |
| [Configuration](https://superforecasting-agent.nousresearch.com/docs/user-guide/configuration) | Config file, providers, models, all options |
| [Messaging Gateway](https://superforecasting-agent.nousresearch.com/docs/user-guide/messaging) | Optional alert and evidence-capture surface |
| [Security](https://superforecasting-agent.nousresearch.com/docs/user-guide/security) | Command approval, DM pairing, container isolation |
| [Tools & Toolsets](https://superforecasting-agent.nousresearch.com/docs/user-guide/features/tools) | Forecast-support tools, toolsets, terminal backends |
| [Skills System](https://superforecasting-agent.nousresearch.com/docs/user-guide/features/skills) | Procedural forecasting playbooks |
| [Memory](https://superforecasting-agent.nousresearch.com/docs/user-guide/features/memory) | Legacy memory systems; forecast learning lives in the ledger |
| [MCP Integration](https://superforecasting-agent.nousresearch.com/docs/user-guide/features/mcp) | Connect MCP servers for extended source access |
| [Cron Scheduling](https://superforecasting-agent.nousresearch.com/docs/user-guide/features/cron) | Runtime scheduler used by forecast self-checks |
| [Architecture](https://superforecasting-agent.nousresearch.com/docs/developer-guide/architecture) | Forecast ledger, agent loop, key classes |
| [Contributing](https://superforecasting-agent.nousresearch.com/docs/developer-guide/contributing) | Development setup, PR process, code style |

---

## Migrating from OpenClaw

If you're coming from OpenClaw, Superforecasting Agent can automatically import your settings, memories, skills, and API keys.

**During first-time setup:** The setup wizard (`superforecasting-agent setup`) automatically detects `~/.openclaw` and offers to migrate before configuration begins.

**Anytime after install:**

```bash
superforecasting-agent claw migrate              # Interactive migration (full preset)
superforecasting-agent claw migrate --dry-run    # Preview what would be migrated
superforecasting-agent claw migrate --preset user-data   # Migrate without secrets
superforecasting-agent claw migrate --overwrite  # Overwrite existing conflicts
```

What gets imported:
- **SOUL.md** — persona file
- **Memories** — MEMORY.md and USER.md entries
- **Skills** — user-created skills → `~/.superforecasting-agent/skills/openclaw-imports/`
- **Command allowlist** — approval patterns
- **Messaging settings** — platform configs, allowed users, working directory
- **API keys** — allowlisted secrets (Telegram, OpenRouter, OpenAI, Anthropic, ElevenLabs)
- **TTS assets** — workspace audio files
- **Workspace instructions** — AGENTS.md (with `--workspace-target`)

See `superforecasting-agent claw migrate --help` for all options, or use the `openclaw-migration` skill for an interactive agent-guided migration with dry-run previews.

---

## Contributing

We welcome contributions. The upstream Hermes contributing guide is still useful for inherited runtime areas, but forecast-domain work should follow the PRD and context docs linked above.

Quick start for contributors:

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
scripts/run_tests.sh tests/forecasting -q
```

Manual path (equivalent to the above):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
scripts/run_tests.sh
```

---

## Community

- 💬 [Discord](https://discord.gg/NousResearch)
- 📚 [Skills Hub](https://agentskills.io)
- 🐛 Issues: use this fork repository's issue tracker.
- 🔌 [computer-use-linux](https://github.com/avifenesh/computer-use-linux) — Linux desktop-control MCP server for Hermes and other MCP hosts, with AT-SPI accessibility trees, Wayland/X11 input, screenshots, and compositor window targeting.
- 🔌 [HermesClaw](https://github.com/AaronWong1999/hermesclaw) — Legacy WeChat bridge from the upstream Hermes/OpenClaw ecosystem.

---

## License

MIT — see [LICENSE](LICENSE).

Built by [Nous Research](https://nousresearch.com).
