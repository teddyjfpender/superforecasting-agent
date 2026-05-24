<p align="center">
  <img src="assets/banner.png" alt="Superforecasting Agent" width="100%">
</p>

# Superforecasting Agent

<p align="center">
  <a href="docs/plans/2026-05-20-superforecasting-agent-fork-prd.md"><img src="https://img.shields.io/badge/Docs-forecasting%20PRD-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="https://discord.gg/NousResearch"><img src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="README.md"><img src="https://img.shields.io/badge/Lang-English-lightgrey?style=for-the-badge" alt="English"></a>
</p>

**Superforecasting Agent 是一个 CLI 优先的预测研究终端。** 它的核心对象不是聊天记录，而是可评分的 forecast：问题、概率历史、时间戳证据、假设、参考类、模型运行、解析结果、分数、复盘和校准经验都会被持久化。

北极星：

> 一个会随时间复利判断力的命令行预测台。

这个 fork 继承了上游运行时中有用的部分：模型供应商适配、工具执行、本地状态、日志、profiles、插件、CLI/TUI 和可选 dashboard。通用聊天、消息网关和传统记忆被降级为预测工作流的辅助面。

## 核心能力

| 能力 | 说明 |
|------|------|
| Forecast ledger | 从 CLI 创建、研究、更新、解析、评分和复盘预测，保留 append-only 概率快照和可审计证据链。 |
| Calibration loop | 追踪 Brier/log score、校准桶、sharpness、horizon/domain 表现、错误画像和带 provenance 的校准经验。 |
| Backtesting | 在明确 evidence cutoff 下 replay resolved questions，并与 base-rate、crowd、market、naive baseline 比较。 |
| Self-checks | 使用 scheduled reviews、watched sources 和 alerts 发现 stale forecasts、新证据、失效假设和解析工作，不会静默改写概率。 |
| Adapters | 从 Metaculus、Manifold、Polymarket、Kalshi、RSS/Atom、GDELT、FRED、EIA、U.S. Treasury Fiscal Data、BLS、World Bank、SEC EDGAR、arXiv、OpenAlex、CSV/JSON 和 generic URL 导入上下文。 |

## 快速安装

```bash
git clone <this-fork-url> superforecasting-agent
cd superforecasting-agent
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
```

安装后：

```bash
forecast                  # 打开预测台
superforecasting-agent    # fork-native 命令，默认进入 forecast desk
python -m superforecasting_agent status
hermes                    # 兼容入口；fork 过渡期也会进入预测台
```

## 快速开始

```bash
forecast status
forecast new "Will X happen?" --resolution-criteria "Resolved by ..."
forecast list
forecast review --stale
forecast self-check --auto-score --auto-postmortem
forecast calibration --by-origin --all
forecast backtest --benchmarks
forecast backtest --all-benchmarks --probability-source forecast-engine
forecast performance --last 5 --json
superforecasting-agent dashboard
```

## Forecast 快速参考

| 操作 | 命令 |
|------|------|
| 打开预测台 | `forecast` 或裸 `superforecasting-agent` |
| 创建问题 | `forecast new "Will X happen?" --resolution-criteria "Resolved by ..."` |
| 添加证据 | `forecast evidence add <id> <url-or-note>` |
| 研究但不移动概率 | `forecast research <id> <source...>` |
| 导入数据行 | `forecast import data indicators.csv --question <id>` |
| 导入经济数据 | `forecast import fred UNRATE --question <id>`、`forecast import bls LNS14000000 --question <id>`、`forecast import worldbank USA/NY.GDP.MKTP.CD --question <id>` |
| 导入公司公告 | `forecast import sec 0000320193 --question <id>` |
| 导入研究论文 | `forecast import arxiv "cat:cs.AI AND forecasting" --question <id>` 或 `forecast import openalex "forecasting calibration" --question <id>` |
| 导入市场/群体 baseline | `forecast import manifold <slug> --question <id>`、`forecast import polymarket <slug> --question <id>`、`forecast import kalshi <ticker> --question <id>`、`forecast import metaculus <id-or-url> --question <id>` |
| 估计 base rate | `forecast base-rate <id> ...` |
| 运行模型 | `forecast model <id> --type bayesian_update ...` |
| 保存概率更新 | `forecast update <id> --probability 0.63 --rationale "..."` |
| Review stale beliefs | `forecast review --stale` |
| 解析并评分 | `forecast resolve <id> --outcome yes && forecast score <id>` |
| 复盘错误 | `forecast postmortem <id>`、`forecast errors`、`forecast calibration --by-origin --all` |
| Backtest | `forecast backtest builtin:heldout-120-binary` |
| 运行 benchmark suite | `forecast backtest --all-benchmarks --probability-source forecast-engine` |
| 观察 backtest 表现 | `forecast performance --last 5` 或 `forecast performance --last 5 --json` |
| 导入 tournament export | `forecast import tournament resolved_questions.json --name my-tournament` |
| 监听 sources | `forecast watch add --question <id> rss:<feed>`、`gdelt:<query>`、`fred:<series-id>`、`sec:<cik>`、`arxiv:<query>`、`openalex:<query>`、`manifold:<slug>`、`polymarket:<slug>`、`kalshi:<ticker>` |
| 调度 scoped learning | `forecast schedule add --domain macro --topic inflation --cadence 1d --next-run-at <time> --auto-score --auto-postmortem` |

## TUI

`superforecasting-agent --tui` 打开 Ink TUI。常用 forecast-native slash commands：

```text
/forecast
/new-forecast
/base-rate
/update-forecast
/resolve
/score
/postmortem
/review
/alerts
/calibration
/lessons
/backtest
/schedule
/performance
```

完整生命周期命令仍可通过 `/forecast <subcommand>` 进入。

## 状态目录和兼容性

新安装默认使用 `~/.superforecasting-agent`。已有 `~/.hermes` 可以在 fork 过渡期复用。也可以设置：

```bash
SUPERFORECASTING_AGENT_HOME=/path/to/home
FORECAST_HOME=/path/to/home
```

Dashboard 和 Docker 覆盖项也优先支持 `SUPERFORECASTING_AGENT_DASHBOARD`、`SUPERFORECASTING_AGENT_DASHBOARD_HOST`、`SUPERFORECASTING_AGENT_DASHBOARD_PORT`、`SUPERFORECASTING_AGENT_WEB_DIST`、`SUPERFORECASTING_AGENT_DASHBOARD_TUI`，以及较短的 `FORECAST_*` 别名。

## Fork 文档

- [PRD](docs/plans/2026-05-20-superforecasting-agent-fork-prd.md)
- [Context](docs/plans/2026-05-20-superforecasting-agent-fork-context.md)
- [Implementation audit](docs/plans/2026-05-20-superforecasting-agent-fork-implementation-audit.md)

## 贡献

预测领域工作请优先遵循 PRD、Context 和 implementation audit。继承运行时相关改动仍可参考上游架构，但默认产品面应保持 forecast-first。

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
scripts/run_tests.sh tests/forecasting -q
```

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

Built by [Nous Research](https://nousresearch.com).
