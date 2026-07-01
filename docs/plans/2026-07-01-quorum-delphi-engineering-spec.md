# Engineering Spec: Delphi-Style Revision Rounds For Forecast Quorum

**Date:** 2026-07-01
**Status:** implementation spec
**Primary files:** `forecasting/quorum.py`, `forecasting/quorum_jobs.py`,
`forecasting/ledger.py`, `forecasting/cli.py`, `tools/forecasting_tool.py`

## Goal

Add an optional Delphi-style revision round to the existing model-diverse forecast
quorum so multi-agent forecast sessions get the anti-herding benefits of:

```text
sealed independent forecasts
-> anonymous disagreement reveal
-> targeted evidence / blind-spot summary
-> private revision forecasts
-> final pool + judge synthesis
```

This should improve serious forecast sessions without adding Bayesian Truth Serum
or another scoring mechanism. Proper scoring after resolution remains Brier/log
score. Delphi is a process intervention, not the accuracy metric.

## Non-Goals

- Do not add BTS or peer-prediction payouts.
- Do not silently mutate committed forecast probabilities from a background job.
- Do not build Slack multiplayer UX in this change.
- Do not change existing quorum behavior when `delphi_rounds == 0`.
- Do not add a new dependency.
- Do not replace the existing panel/quorum gate; this extends quorum.

## Current System

The repo already has most of the structure:

- `forecasting/quorum.py` runs independent model panelists, pools them, and runs a
  judge synthesis.
- Panelists are explicitly told they do not see other panelists' answers.
- `run_quorum()` dispatches panelists in parallel, tolerates failed panelists, and
  preserves input order.
- Optional supervisor search can add fresh evidence when the judge flags an
  unresolved information gap.
- `forecasting/quorum_jobs.py` runs quorum as a detached background job and records
  the result as a `panel_run`.
- `forecasting/ledger.py` stores final panel estimates in `panel_estimates` and the
  run-level artifact in `panel_runs`.
- `forecasting/cli.py` exposes `forecast quorum <question-id>`.
- `tools/forecasting_tool.py` exposes manual panel record/aggregate/show/list
  actions, but not a first-class quorum job action.

The missing piece is a second private revision pass where each panelist sees an
anonymous summary of the first pass, not named model answers.

## Product Behavior

### CLI

Add:

```bash
forecast quorum <question-id> --delphi
forecast quorum <question-id> --delphi-rounds 1
forecast quorum <question-id> --preset wide --supervisor-search --delphi --wait
```

`--delphi` is shorthand for `--delphi-rounds 1`.

For v1, support only:

```text
delphi_rounds = 0 or 1
```

Reject values above `1` with a clear message. More rounds are easy later, but one
revision round captures most of the process value and bounds cost.

Add config:

```yaml
quorum:
  delphi_rounds: 0
```

CLI precedence:

```text
--delphi / --delphi-rounds
> quorum.delphi_rounds
> 0
```

### Status Output

`forecast quorum status <run-id>` should show:

```text
delphi: 1 revision round
round 1 pool: 0.42 disagreement: high
round 2 pool: 0.37 disagreement: moderate
```

Keep the detailed per-model display focused on final-round estimates. Prior-round
details live in the JSON output and the persisted audit artifact.

### Agent Tool Surface

Add `forecast_ledger` actions:

```text
start_quorum
show_quorum_status
```

`start_quorum` arguments:

```json
{
  "action": "start_quorum",
  "question_id": "fq_...",
  "preset": "frontier|budget|self|wide",
  "models": ["provider/model-a", "provider/model-b"],
  "judge": "provider/model",
  "pool_method": "trimmed_geomean_odds|log_odds_pool|median|mean",
  "trim": 1,
  "delphi_rounds": 1,
  "supervisor_search": true,
  "wait": false
}
```

`show_quorum_status` arguments:

```json
{
  "action": "show_quorum_status",
  "run_id": "qr_..."
}
```

Do not add a default auto-commit action in v1. The agent can commit explicitly with
the existing snapshot/update action and `panel_run_ref`, or the CLI can use
`forecast update ... --panel-run-ref <panel_run_id>`.

Reason: background jobs and watched-source workflows must not silently mutate active
probabilities. A quorum run creates an auditable recommendation artifact; committing
it is a separate forecast event.

## Forecast Flow

When `delphi_rounds == 0`, behavior must remain byte-identical except for additive
fields that default to empty/zero.

When `delphi_rounds == 1`:

```text
1. Build shared context from the ledger.
2. Run independent sealed panelist round.
3. Pool round-1 estimates.
4. Run judge on round-1 estimates.
5. If supervisor_search is enabled and the judge flags an information gap:
   a. run bounded fresh search;
   b. append fresh evidence to the working context.
6. Build an anonymous Delphi summary from round 1:
   - distribution summary;
   - disagreement band;
   - strongest yes/no reasons;
   - contradictions;
   - blind spots;
   - fresh supervisor evidence, if any.
7. Run a private revision round for the same participants.
8. Pool final-round estimates.
9. Run final judge synthesis.
10. Apply the existing confidence-gated judge override.
11. Persist a `panel_run` whose final estimates are the revision estimates and
    whose `delphi_audit` preserves the prior round.
```

## Prompt Design

### Round 1

Use the existing panelist prompt unchanged.

### Delphi Revision Prompt

Add a revision context block to the panelist prompt. The panelist should see:

- its own prior probability and rationale;
- anonymous group distribution summary;
- anonymous strongest reasons up/down;
- contradictions and blind spots from the judge;
- supervisor search evidence, if present.

It must not see:

- model identities for other panelists;
- named ordering like "Claude said" or "GPT said";
- the judge's final preferred probability as an authority.

It may see the round-1 median/range/IQR. That is the normal Delphi reveal. The
prompt must explicitly say not to copy the median and to revise only when evidence
or arguments changed the panelist's view.

Suggested text:

```text
## Delphi Revision Context

You previously forecast:
- probability: {own_probability}
- crux: {own_crux}
- rationale: {own_rationale}

Anonymous first-round panel summary:
- probability distribution: min={min}, p25={p25}, median={median}, p75={p75}, max={max}
- disagreement: {band} (index={index})
- strongest reasons for YES: ...
- strongest reasons for NO: ...
- contradictions: ...
- shared blind spots: ...
- fresh evidence added after round 1: ...

Revise privately. Do not defer to the median. Move your probability only if
the anonymous arguments or fresh evidence changed your view. If you keep the
same probability, say why.

Return ONLY the same JSON object as round 1, plus optional:
- revision_reason: one sentence explaining what changed or why you held steady
```

## Code Changes

### `forecasting/quorum.py`

Add fields to `ModelForecast`:

```python
participant_id: str | None = None
round_index: int = 1
prior_probability: float | None = None
revision_reason: str | None = None
```

Thread these into `to_estimate()["metadata"]`:

```python
"metadata": {
    "source": f"quorum:{self.model}",
    "participant_id": self.participant_id,
    "round_index": self.round_index,
    "prior_probability": self.prior_probability,
    "revision_reason": self.revision_reason,
}
```

Add fields to `QuorumResult`:

```python
delphi_rounds: int = 0
delphi_audit: dict[str, Any] = field(default_factory=dict)
```

Add args to `run_quorum()`:

```python
delphi_rounds: int = 0
```

Validation:

```python
if delphi_rounds not in (0, 1):
    raise ValidationError("delphi_rounds must be 0 or 1")
```

Refactor the inner pass helper from:

```python
_run_pass(working_context: str)
```

to:

```python
_run_pass(
    working_context: str,
    *,
    round_index: int,
    prior_by_participant: dict[str, ModelForecast] | None = None,
    delphi_summary: str | None = None,
)
```

Participant identity:

```text
participant_id = f"p{index + 1:02d}"
```

Do not use model id as identity because the `self` preset repeats the same model.

Add helpers:

```python
def build_delphi_summary(
    *,
    forecasts: Sequence[ModelForecast],
    aggregation: PanelAggregation,
    disagreement: Mapping[str, Any],
    judge: JudgeSynthesis | None,
    supervisor_evidence: Sequence[Mapping[str, Any]],
) -> str:
    ...

def _delphi_audit_round(
    *,
    round_index: int,
    forecasts: Sequence[ModelForecast],
    aggregation: PanelAggregation,
    disagreement: Mapping[str, Any],
    judge: JudgeSynthesis | None,
) -> dict[str, Any]:
    ...
```

The audit round should store compact, serializable data:

```json
{
  "round_index": 1,
  "aggregate_probability": 0.42,
  "disagreement": {"disagreement_band": "high", "...": "..."},
  "judge": {"consensus": [], "contradictions": [], "blind_spots": []},
  "forecasts": [
    {
      "participant_id": "p01",
      "model": "provider/model",
      "probability": 0.31,
      "confidence_low": 0.20,
      "confidence_high": 0.45,
      "crux": "...",
      "reasons_up": ["..."],
      "reasons_down": ["..."],
      "change_my_mind": ["..."]
    }
  ]
}
```

The final returned `QuorumResult.forecasts` should be the final-round forecasts.
The prior round lives in `delphi_audit`.

### Supervisor Search Interaction

Preserve current behavior when `delphi_rounds == 0`.

For `delphi_rounds == 1`:

```text
round 1 -> judge -> optional supervisor search -> revision round -> final judge
```

Do not run an additional post-revision supervisor search in v1. That doubles the
loop and makes cost harder to predict. If final judge still reports an information
gap, persist it as a blind spot and let the operator run another quorum or update.

### `forecasting/quorum_jobs.py`

Add accepted spec keys:

```python
"delphi_rounds"
```

Resolve:

```python
delphi_rounds = int(spec.get("delphi_rounds") or 0)
```

Pass to `run_quorum()`.

Pass result fields into `ledger.record_panel_run()`:

```python
delphi_rounds=result.delphi_rounds,
delphi_audit=result.delphi_audit,
```

Add progress events:

```text
delphi_start: revision round 1
delphi_done: revision round 1
```

### `forecasting/ledger.py`

Add columns:

```sql
ALTER TABLE panel_runs ADD COLUMN delphi_rounds INTEGER NOT NULL DEFAULT 0;
ALTER TABLE panel_runs ADD COLUMN delphi_audit TEXT NOT NULL DEFAULT '{}';
```

Use the existing `_ensure_column()` migration pattern.

Extend `record_panel_run()`:

```python
delphi_rounds: int = 0,
delphi_audit: dict[str, Any] | None = None,
```

Persist:

```python
max(0, int(delphi_rounds or 0))
json_dumps(delphi_audit or {})
```

Extend `_panel_run_dict()`:

```python
data["delphi_audit"] = json_loads(data.get("delphi_audit"), {})
```

Do not store all prior-round estimates in `panel_estimates`; that table should
continue to mean "estimates used by this panel run's final aggregate." Prior rounds
are audit material.

### `forecasting/cli.py`

Parser additions:

```python
quorum_parser.add_argument("--delphi", action="store_true")
quorum_parser.add_argument("--delphi-rounds", type=int, choices=(0, 1))
```

In `_quorum_run()`:

```python
if args.delphi and args.delphi_rounds is not None and args.delphi_rounds == 0:
    raise SystemExit("forecast quorum: --delphi conflicts with --delphi-rounds 0")
delphi_rounds = (
    1 if args.delphi
    else args.delphi_rounds
    if args.delphi_rounds is not None
    else int(cfg.get("delphi_rounds", 0) or 0)
)
```

Add to job spec:

```python
"delphi_rounds": delphi_rounds,
```

Add `delphi_rounds` to `forecast quorum config` output.

In `_print_quorum_job()`, display `result["delphi_rounds"]` and summaries from
`result["delphi_audit"]["rounds"]` when present.

### `tools/forecasting_tool.py`

Extend action enum with:

```text
start_quorum
show_quorum_status
```

Implementation:

```python
if action == "start_quorum":
    from forecasting.quorum_jobs import start_job, read_job
    spec = {...}
    run_id = start_job(spec, wait=bool(args.get("wait")))
    job = read_job(run_id) if args.get("wait") else None
    return tool_result(success=True, run_id=run_id, job=job)

if action == "show_quorum_status":
    from forecasting.quorum_jobs import read_job
    return tool_result(success=True, job=read_job(_required(args, "run_id")))
```

Do not add commit behavior here in v1. The existing snapshot/update action should
commit with `panel_run_ref`.

## Data Contract

Job result JSON should include:

```json
{
  "aggregate_probability": 0.37,
  "final_probability": 0.37,
  "final_source": "pool",
  "delphi_rounds": 1,
  "delphi_audit": {
    "rounds": [
      {"round_index": 1, "aggregate_probability": 0.42, "disagreement": {}},
      {"round_index": 2, "aggregate_probability": 0.37, "disagreement": {}}
    ],
    "revision_context": {
      "included_probability_distribution": true,
      "included_model_names": false,
      "included_supervisor_evidence": true
    }
  }
}
```

Panel run JSON should include the same `delphi_rounds` and `delphi_audit`.

Final-round `panel_estimates.metadata` should include:

```json
{
  "participant_id": "p01",
  "round_index": 2,
  "prior_probability": 0.42,
  "revision_reason": "Moved down after the panel surfaced stale-source risk."
}
```

## Tests

### Core Unit Tests

Add to `tests/test_quorum.py`:

- `test_run_quorum_delphi_zero_matches_existing_path`
  - Run the same stubbed quorum with `delphi_rounds=0`.
  - Assert no `delphi_audit["rounds"]`.
  - Assert final probability equals the existing path.

- `test_run_quorum_delphi_runs_second_private_round`
  - Stub runner returns different probabilities when prompt contains
    `Delphi Revision Context`.
  - Assert final forecasts come from round 2.
  - Assert `delphi_audit.rounds[0]` contains round-1 probabilities.

- `test_delphi_summary_is_anonymous`
  - Build a summary from forecasts with model names.
  - Assert summary does not contain model ids.
  - Assert it contains distribution summary, contradictions, and blind spots.

- `test_self_fusion_delphi_uses_participant_ids_not_model_ids`
  - Use the same model id repeated.
  - Assert participants are `p01`, `p02`, `p03`.
  - Assert prior forecasts map correctly into revision prompts.

- `test_delphi_rounds_rejects_more_than_one_for_v1`
  - `run_quorum(..., delphi_rounds=2)` raises `ValidationError`.

### Supervisor Search Interaction

Add to `tests/forecasting/test_supervisor_search_wiring.py`:

- `test_delphi_supervisor_search_feeds_revision_round`
  - Gate on.
  - Round-1 judge flags `information_gap`.
  - Mock search returns one evidence item.
  - Revision prompt contains the evidence.
  - Persisted result has `research_rounds=1` and `delphi_rounds=1`.

- `test_delphi_historical_cutoff_disables_fresh_search`
  - Historical cutoff.
  - Gate on.
  - Assert no supervisor evidence is added.
  - Delphi may still run using supplied historical context.

### Job/Persistence Tests

Add to `tests/test_quorum_jobs.py`:

- `test_execute_job_records_delphi_audit`
  - Start job with `delphi_rounds=1`.
  - Assert `job["result"]["delphi_rounds"] == 1`.
  - Assert ledger panel run has `delphi_rounds == 1`.
  - Assert `delphi_audit.rounds` exists.

Add to `tests/forecasting/test_forecast_panel.py` or new ledger test:

- `test_record_panel_run_persists_delphi_fields`
  - Call `record_panel_run(..., delphi_rounds=1, delphi_audit={...})`.
  - Assert `get_panel_run()` round-trips both fields.

### CLI Tests

Add parser/command tests:

- `forecast quorum <qid> --delphi --wait --json` passes `delphi_rounds=1`.
- `forecast quorum <qid> --delphi-rounds 0` passes `0`.
- `forecast quorum <qid> --delphi --delphi-rounds 0` exits with clear conflict.
- `forecast quorum config` prints `delphi_rounds`.

### Tool Tests

Add to `tests/tools/test_forecasting_tool.py` or existing forecast tool tests:

- `start_quorum` returns a run id.
- `start_quorum` with `wait=true` returns a completed job under a monkeypatched
  runner.
- `show_quorum_status` returns a persisted job.
- Tool schema advertises `start_quorum`, `show_quorum_status`, and
  `delphi_rounds`.

## Acceptance Criteria

- `forecast quorum <qid>` remains unchanged by default.
- `forecast quorum <qid> --delphi --wait` runs a sealed panelist round, a
  round-1 judge summary, one private revision round, and a final judge synthesis.
- Round-2 panelists see anonymous first-round disagreement, not named peer model
  outputs.
- Final aggregate uses only final-round estimates.
- First-round forecasts are preserved in `delphi_audit`.
- A completed Delphi quorum records a normal `panel_run_id` and can satisfy the
  existing `--panel-run-ref` commit gate.
- `supervisor_search` still fails closed for historical cutoffs.
- Agent sessions can start and inspect quorum jobs through `forecast_ledger`
  without shelling out.
- No path silently commits a new probability from the background quorum job.

## Example Operator Flow

```bash
forecast quorum fq_123 --preset wide --supervisor-search --delphi --wait
```

Output:

```text
quorum run: qr_abcd1234  [done]
  question: fq_123
  panel_run: pr_789
  delphi: 1 revision round
  round 1 pool: 0.420 disagreement: high
  round 2 pool: 0.370 disagreement: moderate
  committed (pool): 0.370
```

Then the operator commits explicitly:

```bash
forecast update fq_123 \
  --probability 0.37 \
  --rationale "Delphi quorum revision moved down after stale-source risk and base-rate disagreement were surfaced." \
  --panel-run-ref pr_789 \
  --reason-up "..." \
  --reason-down "..." \
  --change-my-mind "..."
```

## Example Agent Flow

1. Agent creates or selects a forecast question.
2. Agent calls `forecast_ledger.start_quorum` with `delphi_rounds=1`.
3. Agent polls `forecast_ledger.show_quorum_status`.
4. Agent summarizes:
   - final probability;
   - round-1 to round-2 movement;
   - disagreement change;
   - judge blind spots;
   - supervisor evidence.
5. User decides whether to commit.
6. Agent commits only after explicit user instruction or an explicit workflow step
   that already authorizes forecast updates.

## Future Extensions

Keep these out of v1:

- Human Slack sealed rounds using the same `panel_run` shape.
- More than one Delphi revision round.
- Leave-one-out contribution scoring for panelists.
- Calibration-weighted participant aggregation.
- `forecast quorum commit <run-id>` helper.

The v1 shape should make those easy without forcing them now.
