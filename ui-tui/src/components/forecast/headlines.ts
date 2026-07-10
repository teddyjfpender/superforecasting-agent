import type { ForecastWorkspaceItem } from '../../gatewayTypes.js'
import { compactNumber, deltaGlyph, type HistogramBar, pct, pctDelta } from '../../lib/forecastCharts.js'
import { type FieldSpec, rankItems } from '../../lib/fuzzyRank.js'

// ── Forecast headline / format lib ───────────────────────────────────────────
// Pure formatters for the forecast desk: probability/distribution/vote-share
// headlines, deltas, candidate labels, and the `/` filter fields. Moved out of
// forecastsWorkspace.tsx verbatim (Wave-5 modularization); the workspace and the
// desk re-export these so callers/tests keep importing them from their modules.

export const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

// Distribution values (μ, σ, median, CI bounds, Δμ) are abbreviated with
// k/M/B/T so a Bitcoin mean reads "73k", not "73000", and the master-list and
// detail values stay short. Percentages and small values pass through unchanged.
export const trimNum = (value: number): string => compactNumber(value)

export const unitSuffix = (units: null | string | undefined): string => {
  const u = (units ?? '').toLowerCase()

  if (u.includes('percent') || u.includes('%')) {
    return '%'
  }

  return ''
}

/**
 * Headline label for a forecast.
 *   probability/binary → a percent ("59%")
 *   distribution       → a continuous summary ("μ 4.23% · σ 0.10")
 *   categorical PMF    → a value-sorted, leader-first list ("Farage 67.0 · …")
 * so a CPI mean never renders as a misleading "310%" and a vote-share never dumps
 * raw JSON that truncates the leader.
 */
export const headlineLabel = (item: ForecastWorkspaceItem): string => {
  const dist = item.distribution

  if (item.headline_kind === 'distribution' && dist && finite(dist.mean)) {
    const suffix = unitSuffix(item.units)
    const parts = [`μ ${trimNum(dist.mean)}${suffix}`]

    if (finite(dist.sd)) {
      parts.push(`σ ${trimNum(dist.sd)}`)
    }

    return parts.join(' · ')
  }

  // Categorical / vote-share PMF → value-sorted, leader-first (never raw JSON). The
  // detail modal also draws every candidate as a bar below, so the one-line headline
  // stays a compact leader-first summary here. Continuous distributions are handled
  // above (μ/σ), so only NON-distribution kinds reach here.
  if (item.headline_kind !== 'distribution') {
    // The sidebar/detail one-line surfaces the LEADER's 90% interval where published.
    const distHead = distributionHeadline(item.probability, { compact: true, max: 3, intervals: item.candidate_intervals })
    if (distHead) return distHead
  }

  const headline = item.headline_probability

  if (finite(headline) && headline >= 0 && headline <= 1) {
    return pct(headline)
  }

  if (finite(headline)) {
    return item.probability_display ?? String(headline)
  }

  return item.probability_display ?? '—'
}

/** Compact one-token headline for the master list (e.g. "59%", "μ4.23%", or a
 *  value-sorted vote-share "Farage 67.0 · Binface 16.5 · Fox 4.0 · +2 more"). */
export const headlineCompact = (item: ForecastWorkspaceItem, probDigits = 0): string => {
  if (item.headline_kind === 'distribution' && item.distribution && finite(item.distribution.mean)) {
    return `μ${trimNum(item.distribution.mean)}${unitSuffix(item.units)}`
  }

  if (item.headline_kind !== 'distribution') {
    const distHead = distributionHeadline(item.probability, { compact: true, max: 3 })
    if (distHead) return distHead
  }

  const headline = item.headline_probability

  if (finite(headline) && headline >= 0 && headline <= 1) {
    return pct(headline, probDigits)
  }

  return finite(headline) ? String(headline) : '—'
}

/** Delta in headline units: percent-points for probabilities, outcome units (Δμ) for distributions. */
export const deltaLabel = (item: ForecastWorkspaceItem): string => {
  const d = item.delta

  if (!finite(d) || Math.abs(d) < (item.headline_kind === 'distribution' ? 1e-6 : 0.005)) {
    return '· flat'
  }

  if (item.headline_kind === 'distribution') {
    return `${deltaGlyph(d)} Δμ ${d > 0 ? '+' : ''}${trimNum(d)}${unitSuffix(item.units)}`
  }

  return pctDelta(d)
}

export const truncate = (value: string, max: number): string =>
  value.length <= max ? value : `${value.slice(0, Math.max(0, max - 1))}…`

// Field weights for the desk `/` filter: title dominates, then domain/topics,
// then the id. Shared between the boolean test and the ranked list below so they
// always agree on what matches.
export const FORECAST_SEARCH_FIELDS: FieldSpec<ForecastWorkspaceItem>[] = [
  { get: i => i.title, weight: 1 },
  { get: i => i.domain, weight: 0.6 },
  { get: i => i.topics, weight: 0.5 },
  { get: i => i.id, weight: 0.3 }
]

export const matchesFilter = (item: ForecastWorkspaceItem, query: string): boolean =>
  !query.trim() || rankItems([item], query, FORECAST_SEARCH_FIELDS).length > 0

/** Categorical / bucket distribution → sorted bars; null for scalar or mean/sd shapes. */
/** Per-candidate interval lookup that tolerates case/whitespace divergence between the
 * share keys and the interval keys (the scorer + commit hook normalize candidate keys,
 * so the dashboard must too — else an interval silently drops). */
export const intervalForLabel = (
  intervals: ForecastWorkspaceItem['candidate_intervals'] | undefined,
  label: string
): { hi: number; lo: number } | null => {
  if (!intervals) return null
  if (intervals[label]) return intervals[label]
  const norm = label.trim().toLowerCase()
  for (const key of Object.keys(intervals)) {
    if (key.trim().toLowerCase() === norm) return intervals[key]
  }
  return null
}

export const distributionBars = (
  probability: ForecastWorkspaceItem['probability'],
  intervals?: ForecastWorkspaceItem['candidate_intervals']
): HistogramBar[] | null => {
  if (!probability || typeof probability !== 'object' || Array.isArray(probability)) {
    return null
  }

  const entries = Object.entries(probability).filter(([, value]) => finite(value)) as [string, number][]

  // Drop distribution-summary fields (mean / median / sd / quantiles / intervals) so a
  // HYBRID payload (candidate shares + a bolted-on leader distribution, e.g. from a
  // vote-share repair) renders ONLY the candidate bars — never q05 / q25 / interval_*
  // as spurious "candidates". Candidate labels are kept; stat keys are filtered.
  const distributionalKeys = new Set([
    'mean', 'mu', 'sd', 'sigma', 'std', 'stdev', 'variance', 'expected', 'value',
    'median', 'mode', 'lower', 'upper', 'low', 'high', 'min', 'max',
  ])
  const isStatKey = (key: string): boolean => {
    const k = key.toLowerCase()
    return distributionalKeys.has(k) || /^[qp]\d/.test(k) || k.startsWith('ci') || k.startsWith('interval')
  }

  const bars = entries.filter(([key]) => !isStatKey(key))

  if (bars.length < 2) {
    return null
  }

  return bars
    .map(([label, value]) => ({ label, value, interval: intervalForLabel(intervals, label) }))
    .sort((a, b) => b.value - a.value)
}

/** Short label for a candidate in a distribution headline: a long two-word person
 *  name collapses to its surname ("Nigel Farage" → "Farage", "Count Binface" →
 *  "Binface"), so the leader + top few fit one row. Longer/other multi-word labels
 *  ("Other official candidates") and single long tokens just tail-truncate. */
export const shortCandidateLabel = (name: string, max = 11): string => {
  const trimmed = (name ?? '').trim()
  if (trimmed.length <= max) return trimmed
  const words = trimmed.split(/\s+/)
  const last = words[words.length - 1] ?? ''
  if (words.length === 2 && last.length > 0 && last.length <= max) return last
  return truncate(trimmed, max)
}

/**
 * Value-sorted, leader-first headline for a categorical / vote-share PMF —
 * "Farage 67.0 · Binface 16.5 · Fox 4.0 · +2 more". NEVER a raw JSON dump: the old
 * headline rendered the probability dict in INSERTION order inside braces, which
 * truncated the very candidate that mattered (the leader, e.g. Farage 67). Sorted
 * DESC so the leader is always first, 1dp, no braces/quotes. `compact` caps to
 * `max` entries + "+N more" (row contexts, which then tail-ellipsize what remains);
 * full mode lists every candidate (detail contexts, which wrap — never truncating a
 * value). Fraction-scale dicts (every value in [0,1]) render as percentages (×100).
 * Returns null when the payload is not a ≥2-candidate categorical distribution.
 */
export const distributionHeadline = (
  probability: ForecastWorkspaceItem['probability'],
  opts: { compact?: boolean; max?: number; intervals?: ForecastWorkspaceItem['candidate_intervals'] } = {}
): null | string => {
  const bars = distributionBars(probability, opts.intervals)
  if (!bars) {
    return null
  }
  const scale = bars.every(bar => bar.value >= 0 && bar.value <= 1) ? 100 : 1
  const fmt1 = (n: number): string => (Number.isInteger(n) ? String(n) : n.toFixed(1))
  // The LEADER (index 0) shows its 90% interval where one is published — "67.0 [61-73]"
  // — so the row/sidebar surfaces the leading candidate's uncertainty, not just a point.
  // The tail stays point-only so the line does not blow its width budget.
  const fmt = (bar: HistogramBar, index: number): string => {
    const point = `${shortCandidateLabel(bar.label)} ${(bar.value * scale).toFixed(1)}`
    const iv = index === 0 ? bar.interval : null
    if (iv && finite(iv.lo) && finite(iv.hi)) {
      return `${point} [${fmt1(iv.lo * scale)}-${fmt1(iv.hi * scale)}]`
    }
    return point
  }
  const max = Math.max(1, opts.max ?? 3)

  if (opts.compact && bars.length > max) {
    return `${bars.slice(0, max).map(fmt).join(' · ')} · +${bars.length - max} more`
  }

  return bars.map(fmt).join(' · ')
}
