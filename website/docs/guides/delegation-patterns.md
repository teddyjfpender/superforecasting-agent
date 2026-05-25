---
sidebar_position: 13
title: "Delegation & Parallel Work"
description: "When and how to use subagent delegation for forecast research, evidence review, and model checks"
---

# Delegation & Parallel Work

Superforecasting Agent can spawn isolated child agents to work on forecast-support tasks in parallel. Each subagent gets its own conversation, terminal session, and toolset. Only the final summary comes back — intermediate tool calls never enter your context window or the forecast ledger unless the parent explicitly records them.

For the full feature reference, see [Subagent Delegation](/user-guide/features/delegation).

---

## When to Delegate

**Good candidates for delegation:**
- Reasoning-heavy forecast subtasks such as reference-class research, evidence review, and model critique
- Tasks that would flood your context with intermediate data
- Parallel independent workstreams such as market evidence, regulatory evidence, and historical analogs
- Fresh-context tasks where you want the agent to approach without bias

**Use something else:**
- Single tool call → just use the tool directly
- Mechanical multi-step work with logic between steps → `execute_code`
- Tasks needing user interaction → subagents can't use `clarify`
- Quick file edits → do them directly
- Durable long-running work that must outlive the current turn → `cronjob` or `terminal(background=True, notify_on_complete=True)`. `delegate_task` is **synchronous**: if the parent turn is interrupted, active children are cancelled and their work is discarded.

---

## Pattern: Parallel Research

Research three independent forecast angles simultaneously and get structured summaries back:

```
Research these three angles in parallel for forecast Q-142:
1. Historical base rates for similar policy rollbacks
2. Current market-implied probability from prediction markets and public odds
3. Recent official statements and implementation constraints

Return timestamped evidence, uncertainty, and which claims should enter the evidence log.
```

Behind the scenes, the inherited runtime uses:

```python
delegate_task(tasks=[
    {
        "goal": "Research historical base rates for similar policy rollbacks",
        "context": "Forecast Q-142. Focus on comparable policies, time-to-reversal, and selection effects.",
        "toolsets": ["web"]
    },
    {
        "goal": "Research market-implied probability",
        "context": "Forecast Q-142. Find public market or odds sources, timestamp all probabilities, and flag liquidity issues.",
        "toolsets": ["web"]
    },
    {
        "goal": "Research official statements and implementation constraints",
        "context": "Forecast Q-142. Focus on primary sources and concrete blockers, not commentary alone.",
        "toolsets": ["web"]
    }
])
```

All three run concurrently. Each subagent searches independently and returns a summary. The parent agent then decides which claims are admissible evidence, what should update the forecast, and what should remain an assumption.

---

## Pattern: Code Review

Delegate a security review to a fresh-context subagent that approaches a forecast data connector without preconceptions:

```
Review the SEC filing source adapter for security and data-integrity issues.
Check URL handling, file writes, timestamp cutoffs, credential handling,
and test coverage. Fix anything you find and run the tests.
```

The key is the `context` field — it must include everything the subagent needs:

```python
delegate_task(
    goal="Review the SEC filing source adapter for security and data-integrity issues",
    context="""Project at /home/user/superforecasting-agent. Python 3.11.
    Files: forecasting/source_adapters.py, tools/forecasting_tool.py
    Test command: pytest tests/forecasting/ -v
    Focus on: URL validation, source availability timestamps, credential handling, and durable evidence writes.
    Fix issues found and verify tests pass.""",
    toolsets=["terminal", "file"]
)
```

:::warning The Context Problem
Subagents know **absolutely nothing** about your conversation. They start completely fresh. If you delegate "fix the bug we were discussing," the subagent has no idea what bug you mean. Always pass file paths, error messages, project structure, and constraints explicitly.
:::

---

## Pattern: Compare Alternatives

Evaluate multiple probability-modeling approaches in parallel, then pick the best:

```
I need to model whether a bill will pass committee by June 30. Evaluate three approaches
in parallel:
1. Historical committee base-rate model
2. Sponsor/cosponsor and party-control model
3. Market/crowd-implied prior plus Bayesian evidence updates

For each: assumptions, data requirements, likely failure modes, and how to score it after resolution.
Compare them and recommend an ensemble weighting.
```

Each subagent researches one option independently. Because they're isolated, there's no cross-contamination — each evaluation stands on its own merits. The parent agent gets all three summaries and makes the comparison.

---

## Pattern: Multi-File Refactoring

Split a large forecast-system refactoring task across parallel subagents, each handling a different part of the codebase:

```python
delegate_task(tasks=[
    {
        "goal": "Refactor forecast evidence adapters to emit availability timestamps",
        "context": """Project at /home/user/superforecasting-agent.
        Files: forecasting/source_adapters.py, tests/forecasting/test_source_adapters.py
        Every EvidenceItem must include source timestamp and available_at.
        Run tests after: pytest tests/forecasting/test_source_adapters.py -v""",
        "toolsets": ["terminal", "file"]
    },
    {
        "goal": "Update forecast CLI output for timestamped evidence",
        "context": """Project at /home/user/superforecasting-agent.
        Files: forecasting/cli.py, tests/forecasting/test_cli.py
        Show source timestamp and available_at in evidence listings without widening compact tables.""",
        "toolsets": ["terminal", "file"]
    },
    {
        "goal": "Update docs for timestamped evidence handling",
        "context": """Project at /home/user/superforecasting-agent.
        Docs at: docs/plans/ and website/docs/. Format: Markdown.
        Explain why evidence timestamps and availability cutoffs are required for backtesting.""",
        "toolsets": ["terminal", "file"]
    }
])
```

:::tip
Each subagent gets its own terminal session. They can work on the same project directory without stepping on each other — as long as they're editing different files. If two subagents might touch the same file, handle that file yourself after the parallel work completes.
:::

---

## Pattern: Gather Then Analyze

Use `execute_code` for mechanical data gathering, then delegate the reasoning-heavy forecast analysis:

```python
# Step 1: Mechanical gathering (execute_code is better here — no reasoning needed)
execute_code("""
# Inherited execute_code helper module.
from hermes_tools import web_search, web_extract

results = []
for query in ["export controls semiconductor equipment 2026",
              "semiconductor equipment shipment restrictions 2026",
              "chip equipment export license approvals 2026"]:
    r = web_search(query, limit=5)
    for item in r["data"]["web"]:
        results.append({"title": item["title"], "url": item["url"], "desc": item["description"]})

# Extract full content from top 5 most relevant
urls = [r["url"] for r in results[:5]]
content = web_extract(urls)

# Save for the analysis step
import json
with open("/tmp/export-control-evidence.json", "w") as f:
    json.dump({"search_results": results, "extracted": content["results"]}, f)
print(f"Collected {len(results)} results, extracted {len(content['results'])} pages")
""")

# Step 2: Reasoning-heavy analysis (delegation is better here)
delegate_task(
    goal="Analyze semiconductor export-control evidence for a forecast update",
    context="""Raw data at /tmp/export-control-evidence.json contains search results and
    extracted web pages about semiconductor export controls.
    Write a forecast evidence memo for whether new restrictions will be announced by Q3 2026.
    Separate facts, estimates, rumors, and assumptions; include what should enter the evidence log.""",
    toolsets=["terminal", "file"]
)
```

This is often the most efficient pattern: `execute_code` handles the 10+ sequential tool calls cheaply, then a subagent does the single expensive reasoning task with a clean context. The parent still owns the final probability update and ledger write.

---

## Toolset Selection

Choose toolsets based on what the subagent needs:

| Task type | Toolsets | Why |
|-----------|----------|-----|
| Forecast research | `["web"]` | web_search + web_extract only |
| Code or adapter work | `["terminal", "file"]` | Shell access + file operations |
| Full-stack | `["terminal", "file", "web"]` | Everything except messaging |
| Read-only analysis | `["file"]` | Can only read files, no shell |

Restricting toolsets keeps the subagent focused and prevents accidental side effects (like a research subagent running shell commands).

---

## Constraints

- **Default 3 parallel tasks**: batches default to 3 concurrent subagents (configurable via `delegation.max_concurrent_children` in config.yaml, no hard ceiling, only a floor of 1)
- **Nested delegation is opt-in**: leaf subagents (default) cannot call `delegate_task`, `clarify`, `memory`, `send_message`, or `execute_code`. Orchestrator subagents (`role="orchestrator"`) retain `delegate_task` for further delegation, but only when `delegation.max_spawn_depth` is raised above the default of 1 (1-3 supported); the other four remain blocked. Disable globally via `delegation.orchestrator_enabled: false`.

### Tuning Concurrency and Depth

| Config | Default | Range | Effect |
|--------|---------|-------|--------|
| `max_concurrent_children` | 3 | >=1 | Parallel batch size per `delegate_task` call |
| `max_spawn_depth` | 1 | 1-3 | How many delegation levels can spawn further |

Example: running 30 parallel workers with nested subagents:

```yaml
delegation:
  max_concurrent_children: 30
  max_spawn_depth: 2
```

- **Separate terminals** — each subagent gets its own terminal session with separate working directory and state
- **No conversation history** — subagents see only the `goal` and `context` the parent agent passes when calling `delegate_task`
- **Default 50 iterations** — set `max_iterations` lower for simple tasks to save cost
- **Not durable** — `delegate_task` is synchronous and runs inside the parent turn. If the parent is interrupted (new user message, `/stop`, `/new`), all active children are cancelled (`status="interrupted"`) and their work is discarded. For work that must outlive the current turn, use `cronjob` or `terminal(background=True, notify_on_complete=True)`.

---

## Tips

**Be specific in goals.** "Fix the bug" is too vague. "Fix the TypeError in api/handlers.py line 47 where process_request() receives None from parse_body()" gives the subagent enough to work with.

**Include file paths.** Subagents don't know your project structure. Always include absolute paths to relevant files, the project root, and the test command.

**Use delegation for context isolation.** Sometimes you want a fresh perspective. Delegating forces you to articulate the problem clearly, and the subagent approaches it without the assumptions that built up in your conversation.

**Check results.** Subagent summaries are just that — summaries. If a subagent says "fixed the bug and tests pass," verify by running the tests yourself or reading the diff.

---

*For the complete delegation reference — all parameters, ACP integration, and advanced configuration — see [Subagent Delegation](/user-guide/features/delegation).*
