"""Starter knowledge base seeded into a fresh forecasting vault.

The vault is the desk's research surface and, over time, an LLM-curated wiki:
the forecaster (and the agent) read, write, link and aggregate knowledge here,
while the ledger stays the source of truth for the numbers. Seeding gives a
new vault an opinionated, wikilinked starting point — the art of forecasting,
how to get started, the core methods, and the conventions that keep the wiki
coherent as it grows.

All seed notes live under ``Forecasting/Knowledge`` and ``Forecasting/Templates``
so they never collide with synced lessons/dossiers (``Forecasting/Lessons``,
``Forecasting/Questions``). Seeding never overwrites an existing file.
"""

from __future__ import annotations

from pathlib import Path

from plugins.obsidian.vault import write_note

_INDEX = """---
tags: [forecasting, moc]
type: index
---

# Forecasting Desk

The home of this vault. The ledger holds the numbers; this wiki holds the
reasoning, the methods, and the accumulated knowledge behind them.

## Start here
- [[Getting Started]] — how the desk and this vault fit together
- [[Superforecasting]] — the art of forecasting, distilled
- [[Knowledge Base Conventions]] — how to keep this wiki coherent as it grows

## Methods
- [[Reference Classes and Base Rates]]
- [[Bayesian Updating]]
- [[Calibration and Scoring]]

## Templates
- [[Question Dossier]] — copy when opening a new forecast

## Published by the desk
- `Forecasting/Questions/` — per-question dossiers (description, current
  probability, analyst-note timeline), synced from the ledger
- `Forecasting/Lessons/` — calibration lessons extracted from postmortems

> The desk publishes into the folders above inside managed markers; your own
> notes and links around them survive every re-sync.
"""

_SUPERFORECASTING = """---
tags: [forecasting, method, core]
type: note
---

# Superforecasting

Forecasting is a skill, not a gift — it improves with the right habits and
honest scoring. The desk's house style, distilled:

## Be a fox, not a hedgehog
Many small models and reference classes beat one grand theory. Hold several
angles at once and let them argue.

## Outside view first
Anchor on a base rate before the case-specific story: *how often do things of
this sort happen in situations of this sort?* See
[[Reference Classes and Base Rates]]. Only then adjust with the inside view.

## Anchor on the status quo and the horizon
The world changes slowly; weight the persistence outcome, and weight it more
the shorter the time to resolution. Move off it only as far as a concrete
mechanism and the evidence justify — change needs a cause, and the cause
usually does not arrive in time.

## Reason along paths, not vibes
Before pricing an outcome, trace the causal path to it and price the links.
For a binary, name the path to YES and the path to NO; the probability is the
weight of the path that must actually occur. A path with one weak link cannot
carry heavy mass. "The economy is weak" is a vibe; "rates hold → demand
softens → the print clears X by date D" is a path.

## Update like a Bayesian
Move in log-odds on likelihood ratios — often, but not wildly.
See [[Bayesian Updating]].

## Calibrate in both directions
Under-confidence is a scored failure, not humility. If a tail holds 10%, name
the path by which it happens — if you cannot, that mass is miscalibration.
Form your own view, then compare to crowd/market/model and state where you
diverge: a forecast that only echoes the market adds no value. See
[[Calibration and Scoring]].

## Forecast from the information frontier
Reason only from what was knowable at your as-of cutoff. Guard against
hindsight and recency — the most salient recent headline is rarely the most
diagnostic evidence.

## Tetlock's working habits
Triage (skip the unknowable and the trivial); decompose; balance inside and
outside views; update incrementally; look for the error in your own reasoning
before defending it; keep score and learn from it.
"""

_GETTING_STARTED = """---
tags: [forecasting, guide]
type: note
---

# Getting Started

## The desk in one loop
`parse → research → base_rate → [model] → update → resolve → postmortem`

1. **Parse** — make the question scoreable and decision-relevant (clear
   resolution criteria, an as-of cutoff, a decision it informs).
2. **Research** — gather timestamped, source-backed evidence.
3. **Base rate** — establish the outside view with a
   [[Reference Classes and Base Rates|reference class]].
4. **Model / update** — decompose into components, pool them, and commit a
   snapshot with structured reasoning (reasons up, reasons down, what would
   change your mind).
5. **Resolve & postmortem** — score it, then extract a lesson.

## How this vault fits in
The ledger DB is the source of truth; the vault is a published, linkable
**view** of it, plus your own research and synthesis. The desk syncs
calibration lessons and question dossiers under `Forecasting/`; everything you
write by hand (like these notes) is yours to edit freely.

## Working in the wiki
- Link generously with `[[wikilinks]]` — the value is in the connections.
- Keep one idea per note; let notes get small and link out.
- Use this Obsidian view to browse what the desk has published, then ask the
  desk to research, draft, or revise a write-up.

See [[Knowledge Base Conventions]] for how to keep it all coherent.
"""

_REFERENCE_CLASSES = """---
tags: [forecasting, method]
type: note
---

# Reference Classes and Base Rates

The outside view asks: *of the cases like this one, how often did the thing
happen?* That frequency is your base rate — the prior you start from before
any case-specific adjustment.

## Building a reference class
1. Define membership: what counts as "a case like this"? State inclusion and
   exclusion criteria explicitly.
2. Estimate the frequency within the class, with its uncertainty.
3. Note the class size — a base rate from 6 cases is a weak anchor.

## When classes compete
Real questions sit in several reference classes at once (e.g. an election is
both "incumbent-party races" and "races with a scandal"). Blend them
deliberately rather than eyeballing — weight by relevance and sample size.

## Adjusting to the inside view
Move off the base rate only as far as a concrete, case-specific mechanism
justifies — and price that mechanism as a [[Superforecasting|path]], not a
vibe. The base rate is a prior to update, never the final answer and never an
excuse to hedge.

Related: [[Bayesian Updating]], [[Calibration and Scoring]].
"""

_BAYES = """---
tags: [forecasting, method]
type: note
---

# Bayesian Updating

Update beliefs by combining a prior with evidence, in proportion to how
diagnostic the evidence is.

## Work in log-odds
Odds = p / (1 - p); log-odds = ln(odds). Updating is *addition* in log-odds:

```
posterior_logodds = prior_logodds + ln(likelihood_ratio)
```

The **likelihood ratio** (LR) is P(evidence | YES) / P(evidence | NO). LR > 1
pushes toward YES, LR < 1 toward NO. Working in log-odds keeps updates from
piling past 0 or 1 and makes them composable.

## Discipline
- Update often, but not wildly — each piece of evidence moves you by its LR,
  no more.
- Avoid double-counting correlated evidence (two outlets reporting the same
  leak is one update, not two).
- Pool independent estimates in log-odds (geometric mean of odds), and
  consider trimming extremes (Samotsvety style).

Related: [[Reference Classes and Base Rates]], [[Calibration and Scoring]].
"""

_CALIBRATION = """---
tags: [forecasting, method, scoring]
type: note
---

# Calibration and Scoring

A forecaster is **calibrated** when things they call 70% happen about 70% of
the time. Calibration is measured only on resolved, scored forecasts.

## Proper scores
- **Brier score** = mean squared error of the probability (lower is better;
  0 is perfect, 0.25 is a coin flip on a binary).
- **Log score** = −ln(probability assigned to the outcome that happened);
  punishes confident misses hard.

Both are *proper*: they are minimised by reporting your true belief, so they
cannot be gamed by hedging or by over-claiming.

## Both directions matter
Over-confidence (too sharp) and under-confidence (too timid) are both scored
failures. Chronic hedging — mirroring the market, flattening the distribution
to feel safe — loses to a committed, well-calibrated forecaster over many
questions. The fix for thin conviction is to *go get evidence*, not to flatten.

## The loop closes here
Score every resolution, run a postmortem, and fold the lesson back into the
next forecast. The desk does this automatically and stores lessons under
`Forecasting/Lessons/`.

Related: [[Superforecasting]], [[Bayesian Updating]].
"""

_CONVENTIONS = """---
tags: [forecasting, meta]
type: note
---

# Knowledge Base Conventions

This vault is meant to grow into an LLM-curated wiki — a place where research,
write-ups and insights are aggregated and densely linked, so the next forecast
starts from accumulated knowledge instead of a blank page.

## Conventions
- **One idea per note.** Small notes link better than long ones.
- **Link, don't copy.** Reference other notes with `[[wikilinks]]` instead of repeating them;
  the graph is the value.
- **Frontmatter tags.** Tag by topic and `type` (note / index / template /
  dossier) so notes can be gathered programmatically.
- **Maps of Content.** Index notes (like [[Forecasting Desk]]) curate links
  into a topic; let them grow as the area does.
- **Atomic, durable claims.** Prefer claims that stay true and cite their
  evidence, with timestamps where it matters.

## Working with the desk
Ask the desk to draft a note, summarise a cluster of evidence into a new note,
or refine an existing one — it reads and writes here through its Obsidian
tools. Agent-generated sections live inside managed markers, so your edits
around them survive re-syncs.

> Inspiration: a personal LLM wiki that aggregates knowledge over time
> (karpathy's note-taking gist → the llm_wiki progression). The aim is the
> same here, pointed at forecasting and research.
"""

_TEMPLATE_DOSSIER = """---
tags: [forecasting, template]
type: template
---

# Question Dossier — <title>

> Copy this note when opening a new forecast. The ledger holds the committed
> numbers; this is the human-readable workspace around them.

## Question
- **Resolves:** <criteria — unambiguous, scoreable>
- **As-of cutoff:** <date>
- **Decision it informs:** <owner / action / threshold>

## Outside view
- Reference class: <class + inclusion/exclusion>
- Base rate: <p, with sample size and uncertainty>
  — see [[Reference Classes and Base Rates]]

## Paths
- Path to YES: <link → link → outcome>
- Path to NO: <link → link → outcome>
- Weakest load-bearing link: <what would break it>

## Components
| component | p | weight | source |
|-----------|---|--------|--------|
| base_rate |   |        |        |
| market    |   |        |        |
| inside    |   |        |        |

## Current call
- **Probability:** <p>  ·  **Confidence:** <80% CI>
- Reasons up / down / change-my-mind: <…>

## Evidence log
- <timestamp> — <claim> — <source>
"""

# relative path → content. Knowledge under Forecasting/Knowledge, the template
# under Forecasting/Templates; the index is the vault's home note.
STARTER_DOCS: dict[str, str] = {
    "Forecasting/Index.md": _INDEX,
    "Forecasting/Knowledge/Superforecasting.md": _SUPERFORECASTING,
    "Forecasting/Knowledge/Getting Started.md": _GETTING_STARTED,
    "Forecasting/Knowledge/Reference Classes and Base Rates.md": _REFERENCE_CLASSES,
    "Forecasting/Knowledge/Bayesian Updating.md": _BAYES,
    "Forecasting/Knowledge/Calibration and Scoring.md": _CALIBRATION,
    "Forecasting/Knowledge/Knowledge Base Conventions.md": _CONVENTIONS,
    "Forecasting/Templates/Question Dossier.md": _TEMPLATE_DOSSIER,
}


def seed_starter_vault(vault: Path, *, overwrite: bool = False) -> dict[str, list[str]]:
    """Write the starter knowledge base into ``vault``.

    Existing files are left untouched unless ``overwrite`` is set — seeding is
    safe to run against a vault that already has content. Returns the relative
    paths created vs skipped.
    """

    vault = Path(vault)
    created: list[str] = []
    skipped: list[str] = []
    for relative, content in STARTER_DOCS.items():
        path = vault / relative
        if path.exists() and not overwrite:
            skipped.append(relative)
            continue
        write_note(path, content)
        created.append(relative)
    return {"created": created, "skipped": skipped}


__all__ = ["STARTER_DOCS", "seed_starter_vault"]
