# Forecasting Methodology — and how to let it learn

This is the desk process: how a belief becomes a scoreable forecast, what the
commit gate demands, and — most importantly — how the system **compounds
judgment** by scoring itself and feeding the lessons back into future commits.
Every step here is backed by a CLI command ([cli.md](cli.md),
[reference/cli-reference.md](reference/cli-reference.md)) and a tool action
([reference/tool-actions.md](reference/tool-actions.md)); the agent runs the same
pipeline you can run by hand.

## The pipeline

```
 question ─▶ evidence ─▶ triage ─▶ base rate ─▶ components ─▶ panel ─▶ quorum/Delphi
     │          │          │           │            │           │           │
     └──────────┴──────────┴───────────┴────────────┴───────────┴───────────┘
                                   │
                            COMMIT GATE (hooks)
                                   │
                                snapshot ─▶ resolve ─▶ score ─▶ lesson ─▶ (applied to next commit)
```

### 1. Question

A forecast starts as a **scoreable question**: a resolution criterion, an outcome
space (binary, numeric, multiple-choice, distribution, thesis, factor), a close
time, and a resolution source. `forecast new` (hand-driven) or `forecast onboard`
(one sentence, infers the rest) create one. An unscoreable ask is refused, not
guessed. Near-duplicates refresh the existing question instead of forking a rival.

### 2. Evidence and triage

Evidence is timestamped and attached to the question, never silently folded into a
number. Watched sources (`forecast watch add`) re-pull on a cadence. The key
discipline is **triage, not hoarding**: candidate readings are auto-labeled
three-way — **keep / skim / skip** — by a cheap model. Auto-import only unlocks
once the labeler has earned **≥80% agreement** with your own hand adjudications
(`forecast triage trust`); until then contested items route to you to label. This
replicates desk judgment about what is worth reading before it spends attention.

### 3. Base rate, components, and models

Good forecasts anchor on an **outside view** first (a reference-class base rate,
`forecast base-rate`) and then decompose into **components** and **cruxes** — the
decisive inputs — before adjusting. `forecast model` records probabilistic model
runs; the `bayes` action is an auditable Bayesian scratchpad (likelihood-ratio
updates, log-odds pooling of disagreeing sources, de-vigging a market, blending
base rates). A market component comes from real de-vigged numbers via `pm_query`,
not a scraped page.

### 4. Panels, quorum, and Delphi

For calls that warrant it, a **panel** of perspectives is run and recorded
(`forecast panel`). High-impact commits escalate to a **quorum**: a multi-model
panel that forecasts independently, runs a **Delphi revision round** (members see
the spread and revise), and attaches a **judged synthesis** (consensus +
contradictions) to the snapshot. A high-impact commit with no panel auto-starts a
detached quorum job (impact-aware preset, cost-capped by `quorum.max_calls`).

### 5. The commit gate

A snapshot only commits when it passes the **hook gate** — git-hook-style checks
run on every forecast snapshot. A rule resolves to a severity: `error` **blocks**
the commit, `warn` surfaces without blocking, `off` is disabled. The 25 built-in
rules ([reference/hooks-rules.md](reference/hooks-rules.md)) enforce, among
others: structured reasoning (`reasons_up` / `reasons_down` / `change_my_mind`),
fresh evidence, decomposition into components, a panel where required, renderable
and well-formed uncertainty, justified tails, and applied calibration lessons.
Autonomy never buys a weaker forecast — it buys fewer keystrokes; every gate still
applies to the agent's `full_forecast`. Inspect and tune with `forecast hooks
list` (resolved severities), `forecast hooks set-severity`, and author your own
with `forecast hooks add`.

---

## The learning loop — how to let it learn

This is the part that makes the desk more than a logger. **The loop only turns if
questions get resolved and scored.** Here is how to keep it turning.

### Resolve and score

When a question's outcome is known, resolve it: `forecast resolve <id> --outcome
yes` (or a numeric value / chosen option). Resolution **auto-scores** the forecast
— Brier and log scores, calibration bucket, sharpness, probability movement before
close, and per-component contribution — and separates live / backtest / baseline
scores so a replay never contaminates your real track record. `forecast score
--baselines` compares against base-rate, crowd, and market baselines.

Trusted resolvers can close questions for you: `forecast resolver` attaches
metric-threshold rules that propose (and, with confirmation, raise) resolutions
from ingested source values — autonomy without silent probability changes.

### Postmortem and lessons

`forecast postmortem <id>` records a structured post-resolution diagnosis. Across
resolutions, the desk **synthesizes calibration lessons** — provenance-linked
findings like a measured over/under-confidence in a scope (global / domain / topic
/ question-type). `forecast lessons` lists them; `forecast lesson synth` compiles
them.

The lessons are not passive prose. Two mechanisms make them **bite**:

1. **Applied to the next commit.** A live commit applies the measured bias
   correction automatically (raw numbers stay on the audit trail;
   `--no-use-active-lessons` opts out). The `lessons_applied`,
   `calibration_bias_applied`, and `terminal_calibration_applied` hook rules warn
   when a commit ignores an active lesson.
2. **Compiled into an enforced rule.** `forecast lessons apply` turns a lesson
   into an enforceable hook rule (it auto-detects the enforcement pattern), so a
   repeated mistake becomes a gate the next forecast must clear.
   `forecast lessons audit` shows, per lesson, whether each learning is actually
   being used (in-scope / applied / dormant).

### Track-record weighting

Not every model or perspective earns an equal vote. `forecast track-record` and
the `component_track_record` action score how each ensemble component / panel
member has actually performed, and panel aggregation **weights by track record**
so consistently-good sources count for more over time.

### The practice loop — the desk scores you too

The desk does not only grade itself. Turn on practice mode
(`forecasting.practice.estimate_first: true`) and the agent asks for **your**
probability before it reveals its own, recording it to be scored when the question
resolves. `forecast drill --n 5` replays already-resolved binary questions and
gives you your Brier on the spot. `forecast calibration --operator` then shows
your reliability curve, your trend, and how your Brier stacks up against the
system's on the same questions.

### Keep it turning by itself

`forecast schedule` and the nightly self-check cron re-pull watched sources,
surface stale beliefs and invalidated assumptions as review alerts (without
changing probabilities), escalate cadence as deadlines near, and auto-score +
auto-postmortem where configured. `forecast cycle` runs the closed loop end to
end. The single measure of whether the loop is healthy is `forecast calibration`
and `forecast doctor` — resolved volume, calibration, and readiness gaps.
