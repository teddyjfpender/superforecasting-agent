---
sidebar_position: 5
title: "Programmatic Forecast Workflows"
description: "Use the forecast ledger and inherited AIAgent runtime from Python without replacing the CLI desk."
---

# Programmatic Forecast Workflows

The CLI is the main product surface, but you can also call the forecast ledger and inherited agent runtime from Python. Use this for internal tools, benchmark runners, source adapters, resolver scripts, or narrow automation around active forecast questions.

The important boundary is:

- Use `ForecastLedger` for durable, scoreable state: questions, evidence, snapshots, model runs, resolutions, scores, postmortems, calibration lessons, and domain error profiles.
- Use `AIAgent` for ephemeral research or text synthesis when a model helps inspect sources or draft rationale.
- Do not store probabilities, evidence, or learning artifacts only in chat history.

---

## Installation

From this fork:

```bash
pip install git+https://github.com/NousResearch/superforecasting-agent.git
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv pip install git+https://github.com/NousResearch/superforecasting-agent.git
```

For local development, install the checkout in editable mode:

```bash
uv pip install -e ".[dev]"
```

The inherited `hermes-agent` package and repository names remain compatibility surfaces during migration, but new programmatic examples should use the fork-native package name and commands.

:::tip
The same provider credentials used by the CLI are required for model calls. At minimum, configure a provider with `superforecasting-agent model` or set an API key such as `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY`.
:::

---

## Ledger-First Usage

The forecast ledger is the programmatic source of truth:

```python
from forecasting import ForecastLedger, OutcomeSpace

ledger = ForecastLedger()

question = ledger.create_question(
    title="Will the next CPI release exceed consensus expectations?",
    resolution_criteria=(
        "Resolve yes if the first official BLS CPI release is above "
        "the published consensus estimate."
    ),
    outcome_space=OutcomeSpace(type="binary", choices=["yes", "no"]),
    close_time="2026-06-10T12:00:00Z",
    resolution_source="BLS CPI release and named consensus source",
    domain="macro",
    topics=["inflation"],
)

evidence = ledger.add_evidence(
    question_id=question.id,
    source_or_note="Consensus estimate not yet available from configured source.",
    claim="No configured consensus estimate was available at review time.",
    summary="Hold update until resolver-adjacent consensus source is available.",
    claim_type="fact",
    stance="context",
    reliability_rating=0.7,
    relevance_rating=0.8,
)

snapshot = ledger.create_snapshot(
    question_id=question.id,
    probability_or_distribution={"yes": 0.41, "no": 0.59},
    rationale="Base-rate prior retained; no admissible consensus evidence yet.",
    evidence_refs=[evidence.id],
    require_citations=True,
    confidence=0.55,
    method="base-rate-plus-evidence-review",
)

print(question.id, snapshot.forecast_id)
```

This mirrors the CLI lifecycle: `forecast new`, `forecast research`, and `forecast update`.

---

## Calling the Forecast CLI from Python

For scripts that do not need direct ledger objects, invoke the CLI. This keeps behavior aligned with the main product:

```python
import json
import subprocess

result = subprocess.run(
    ["forecast", "review", "--domain", "macro", "--json"],
    check=True,
    capture_output=True,
    text=True,
)

review = json.loads(result.stdout)
print(review)
```

Use this approach for scheduled jobs, CI checks, and internal dashboards when the CLI already exposes the workflow you need.

---

## Using AIAgent for Forecast Research

`AIAgent` is inherited runtime infrastructure. Use it to gather or synthesize research, but write any durable forecast state back to the ledger.

```python
from run_agent import AIAgent

agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    enabled_toolsets=["forecast-desk"],
    quiet_mode=True,
    skip_memory=True,
)

response = agent.chat(
    "Research recent evidence for forecast fq_123. "
    "Summarize candidate evidence with source URLs, claim type, "
    "publication time, and relevance. Do not update probability."
)

print(response)
```

`chat()` handles tool calls and returns the final text. Treat the result as a research artifact until evidence and forecast snapshots are written to the ledger.

:::warning
Always set `quiet_mode=True` when embedding the runtime. Without it, CLI spinners and progress output can clutter your application's stdout.
:::

---

## Full Conversation Control

Use `run_conversation()` when you need the message list or custom one-turn system prompt:

```python
from run_agent import AIAgent

agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    enabled_toolsets=["forecast-desk"],
    quiet_mode=True,
    skip_memory=True,
)

result = agent.run_conversation(
    user_message=(
        "For forecast fq_123, identify reference classes and list "
        "what evidence would change the probability."
    ),
    task_id="forecast-research-fq-123",
)

print(result["final_response"])
print(f"Messages exchanged: {len(result['messages'])}")
```

The returned dictionary includes:

- `final_response` - final text reply.
- `messages` - OpenAI-format message history, including tool calls.

The `task_id` is stored on the agent instance for runtime isolation but is not echoed back in the return dict.

---

## Toolset Scope

Prefer narrow tool access:

```python
agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    enabled_toolsets=["forecast-desk"],
    quiet_mode=True,
    skip_memory=True,
)
```

Use broader toolsets only for a specific reason, such as terminal-backed model execution or browser source inspection. The default fork CLI narrows routine work through the forecast desk; programmatic callers should follow that pattern.

---

## Sessions vs. Ledger State

Conversation history is useful for multi-turn research:

```python
first = agent.run_conversation("Inspect forecast fq_123 and list missing evidence.")
history = first["messages"]

second = agent.run_conversation(
    "Now draft a source-acquisition plan.",
    conversation_history=history,
)
```

Do not confuse this with durable learning. If the result matters, write it to the ledger as evidence, an assumption, a reference class, a model run, a forecast snapshot, a postmortem, or a calibration lesson.

---

## Batch Processing

For many independent research prompts, create one agent per task:

```python
import concurrent.futures
from run_agent import AIAgent

prompts = [
    "For fq_101, find missing resolver-source evidence. Do not update probability.",
    "For fq_102, identify reference classes. Do not update probability.",
    "For fq_103, summarize active calibration lessons. Do not update probability.",
]

def process_prompt(prompt: str) -> str:
    agent = AIAgent(
        model="anthropic/claude-sonnet-4",
        enabled_toolsets=["forecast-desk"],
        quiet_mode=True,
        skip_memory=True,
    )
    return agent.chat(prompt)

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    results = list(executor.map(process_prompt, prompts))

for result in results:
    print(result)
```

Always create a new `AIAgent` instance per thread or task. The runtime maintains internal state and is not safe to share across concurrent calls.

---

## Integration Examples

### FastAPI Forecast Research Endpoint

```python
from fastapi import FastAPI
from pydantic import BaseModel
from run_agent import AIAgent

app = FastAPI()

class ResearchRequest(BaseModel):
    question_id: str
    model: str = "anthropic/claude-sonnet-4"

@app.post("/forecast/research")
async def research(request: ResearchRequest):
    agent = AIAgent(
        model=request.model,
        enabled_toolsets=["forecast-desk"],
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    response = agent.chat(
        f"Research forecast {request.question_id}. Return candidate evidence "
        "with source URLs, timestamps, claim type, reliability, and relevance. "
        "Do not update probability."
    )
    return {"research_note": response}
```

### CI Benchmark Step

```python
#!/usr/bin/env python3
"""CI step: run a small benchmark replay."""
import subprocess

subprocess.run(
    [
        "forecast",
        "backtest",
        "builtin:mini-binary",
        "--probability-source",
        "forecast-engine",
    ],
    check=True,
)
```

### Evidence Ingestion Script

```python
from forecasting import ForecastLedger

ledger = ForecastLedger()
question = ledger.get_question("fq_123")

evidence = ledger.add_evidence(
    question_id=question.id,
    source_or_note="https://example.com/resolver-update",
    claim="Resolver source published a new update relevant to the question.",
    summary="New resolver-source update captured by internal watcher.",
    source_type="url",
    claim_type="fact",
    stance="supports_yes",
    reliability_rating=0.8,
    relevance_rating=0.9,
)

print(evidence.id)
```

---

## Key Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | `str` | configured default | Provider/model identifier |
| `quiet_mode` | `bool` | `False` | Suppress CLI output |
| `enabled_toolsets` | `list[str]` | `None` | Whitelist specific toolsets |
| `disabled_toolsets` | `list[str]` | `None` | Blacklist specific toolsets |
| `skip_context_files` | `bool` | `False` | Skip loading project context files |
| `skip_memory` | `bool` | `False` | Disable runtime memory read/write |
| `save_trajectories` | `bool` | `False` | Save conversations to JSONL |
| `max_iterations` | `int` | `90` | Max tool-calling iterations per conversation |
| `api_key` | `str` | `None` | API key, otherwise resolved from config/env |
| `base_url` | `str` | `None` | Custom API endpoint URL |
| `platform` | `str` | `None` | Platform hint such as `discord` or `telegram` |

---

## Important Notes

:::tip
- Prefer `ForecastLedger` or the `forecast` CLI for anything that changes durable forecast state.
- Set `skip_context_files=True` if a service should not load local `AGENTS.md` files.
- Set `skip_memory=True` for stateless endpoints unless runtime recall is explicitly desired.
- Keep probability updates cited and ledgered; raw model text is not a scoreable forecast.
:::

:::warning
- **Thread safety:** create one `AIAgent` per thread or task.
- **Resource cleanup:** ensure conversations finish normally in long-lived processes.
- **Iteration limits:** lower `max_iterations` for narrow endpoints to limit runaway tool loops and cost.
:::
