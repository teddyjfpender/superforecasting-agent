# Feedback: RSS And Textual Data For Forecast Source Breadth

Date: 2026-05-26

This note records beta feedback from a CPI forecasting example, generalized to
the broader Superforecasting Agent workflow.

## User Need

Testers want the agent to consume a wider and more diverse set of textual
information sources, especially RSS/Atom feeds and news-like streams. They do
not want to manually bootstrap every feed or data source for a new question.
From question inception, the system should propose a large enough source plan
covering official data, quantitative leading indicators, market priors, RSS/news
feeds, and broad textual search.

For example, a CPI question should automatically suggest sources such as BLS
CPI releases, CPI time series, gasoline and oil price series, energy-related
news, inflation and shelter/rent news, and market-implied priors where
available.

## Product Principle

RSS/news items should not directly mutate a forecast probability. They should
become filtered evidence candidates, accepted evidence, or review alerts. The
forecast protocol decides whether the probability should move.

Useful loop:

```text
official data / FRED / BLS / EIA / markets
        -> quantitative evidence
RSS / GDELT / official release feeds / domain news
        -> qualitative evidence candidates
both streams
        -> evidence ledger
        -> materiality detection
        -> forecast review proposal
        -> explicit forecast snapshot only when warranted
```

## Why It Matters

Quantitative sources answer what the latest measured value or model estimate
says. RSS/news sources answer what may cause the next data update or market
belief to move before the data lands.

For CPI, textual sources can surface:

- Energy price shocks.
- Port, shipping, or supply-chain disruption.
- Tariff announcements.
- Food supply shocks.
- Shelter, rent, or methodology changes.
- Fed or BLS methodology updates.
- Strike disruption.
- Healthcare or insurance price effects.
- Geopolitical shocks affecting oil.
- Analyst consensus revisions.

## Desired Capabilities

- `forecast sources --question <id>` proposes question-specific source plans.
- `forecast new ... --source-plan` prints the plan immediately after question
  creation.
- `forecast sources --question <id> --apply-watch` adds concrete watchable
  sources while skipping placeholders that require a user-supplied feed, market,
  repository, or company identifier.
- `forecast watch add --question <id> --source-type rss <feed-url>` supports
  RSS/Atom watched sources.
- RSS watches store feed URL, question scope, cadence metadata, source label,
  relevance filters, impact hints, and last checked timestamp.
- RSS checks use relevance filters so irrelevant feed changes do not trigger
  alerts.
- RSS alerts recommend a filtered `forecast import news ...` command and remind
  operators that probability updates are explicit.
- `forecast import news <rss-or-atom-url> --question <id>` supports keyword
  filters, exclusion filters, dedupe, materiality, direction, and affected
  component metadata.
- `forecast sources --question <id> --search-watched` searches configured
  watched RSS/Atom streams for question-relevant candidate evidence.
- `forecast sources --question <id> --search-watched --capture-candidates`
  promotes matched feed items into evidence without mutating probability.

## Triage Fields

Each relevant RSS/news item should be able to carry:

- `relevance_rating`
- `reliability_rating`
- `stance`: `supports`, `opposes`, `mixed`, or `context`
- `claim_type`: `fact`, `estimate`, `rumor`, `opinion`, or `assumption`
- `direction`: `upward`, `downward`, or `ambiguous`
- `affected_components`
- `materiality`: `low`, `medium`, or `high`

## CPI Source Plan Example

Expected high-value recommendations for a CPI question:

- BLS CPI-U official series.
- FRED CPI series for trend and revision checks.
- EIA gasoline price series.
- EIA crude oil series.
- BLS CPI release RSS.
- GDELT CPI/energy/shelter/tariff news search.
- Prediction market, CPI fixing, or other market-implied prior when available.

Example commands:

```bash
forecast sources --question fq_145c7af5b87b

forecast watch add \
  --question fq_145c7af5b87b \
  --source-type rss \
  rss:https://www.bls.gov/feed/news_release/cpi.rss \
  --keyword CPI \
  --keyword inflation \
  --keyword gasoline \
  --keyword shelter \
  --materiality high

forecast import news https://www.bls.gov/feed/news_release/cpi.rss \
  --question fq_145c7af5b87b \
  --since 2026-05-20T00:00:00Z \
  --keyword CPI \
  --keyword gasoline \
  --materiality high \
  --direction upward \
  --affected-component energy
```

## Expected Value Ranking

For a CPI harness, RSS/news is valuable but should be weighted below official
measurement and quantitative leading indicators unless the news is clearly
material.

Very high:

- BLS source adapter.
- Cleveland Fed or equivalent nowcast adapter when available.
- Direct prediction-market or CPI fixing adapter.
- Scheduled review plus resolution and scoring loop.

High:

- Gasoline, oil, and energy price data.
- FRED and EIA quantitative series.
- Automated model refresh.

Moderate:

- RSS/news qualitative context.
- GDELT global news search.
- Analyst commentary.

Low unless filtered well:

- Generic financial-news firehoses.

## Implementation Response

This feedback maps to the source-planning and RSS triage slice:

- Add a deterministic source planner for question-specific source
  recommendations.
- Make source planning available from `forecast sources --question <id>` and
  `forecast new --source-plan`.
- Add RSS/Atom keyword and exclusion filters to watched sources and imports.
- Deduplicate RSS/Atom items before evidence capture.
- Store RSS triage and forecast-impact metadata on evidence.
- Make watched-source alerts point to filtered import commands.
- Add a watched-text-source search path so agents can inspect current RSS/Atom
  streams from the local ledger before deciding what evidence to capture.
- Preserve the rule that RSS/news never silently mutates active probabilities.
