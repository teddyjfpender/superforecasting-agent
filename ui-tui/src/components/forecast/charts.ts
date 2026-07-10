import type {
  ForecastWorkspaceHistoryPoint,
  ForecastWorkspaceItem,
  ForecastWorkspacePanel
} from '../../gatewayTypes.js'
import {
  type BandPoint,
  type DownsampleResult,
  downsampleSeries,
  type HistogramBar,
  type SeriesCell
} from '../../lib/forecastCharts.js'

import { distributionBars, finite } from './headlines.js'

// ── Forecast chart / series builders ─────────────────────────────────────────
// Band-point derivation, auto-zoom y-scale, vote-share multi-series assembly, and
// run-length collapse for the terminal charts. Moved out of forecastsWorkspace.tsx
// verbatim (Wave-5 modularization); pure functions, unit-tested in isolation.

/** Confidence/spread band for one history point. Latest point prefers the panel spread. */
const bandForPoint = (
  isLatest: boolean,
  panel: ForecastWorkspacePanel | null | undefined
): { hi?: number; lo?: number } => {
  if (isLatest && panel?.spread && finite(panel.spread.min) && finite(panel.spread.max)) {
    return { hi: panel.spread.max, lo: panel.spread.min }
  }

  // Never SYNTHESIZE a band from `confidence`. The old `clamp01(1 - confidence) * K`
  // fallback assumed a 0-1 probability scale, so on a vote-share point (e.g. 44.7 on a
  // 0-100 axis) it clamped to ~[0,1] and rendered the band detached at the bottom of
  // the chart — disconnected from the point. A forecast's band must come from its OWN
  // interval (distribution ci90) or a real panel spread; otherwise show no band.
  return {}
}

export const historyToBandPoints = (item: ForecastWorkspaceItem): BandPoint[] => {
  const history = item.history ?? []
  const isDistribution = item.headline_kind === 'distribution'

  return history.map((point, index) => {
    const y = point.headline_probability

    if (!finite(y)) {
      return { y: null }
    }

    // Distribution snapshots carry their own 90% interval (in outcome units);
    // use it directly and never the panel's probability spread.
    if (finite(point.band_low) && finite(point.band_high)) {
      return { hi: point.band_high, lo: point.band_low, y }
    }

    const isLatest = index === history.length - 1

    const band = bandForPoint(!isDistribution && isLatest, isDistribution ? null : item.panel)

    return { hi: band.hi ?? null, lo: band.lo ?? null, y }
  })
}

const MIN_CHART_SPAN = 0.12

/**
 * Auto-zoom the y-axis to the data + band range so small probability moves and
 * the confidence band are actually visible (a fixed 0..1 axis squashes a
 * 0.49→0.58 series into one row). A minimum span stops a flat series from
 * exploding into noise; probability series stay clamped to [0,1]; the axis
 * labels report the real bounds so the zoom is honest.
 */
export const chartScale = (points: BandPoint[]): { yMax: number; yMin: number } => {
  const values: number[] = []

  for (const point of points) {
    if (finite(point.y)) {
      values.push(point.y)
    }

    if (finite(point.lo)) {
      values.push(point.lo)
    }

    if (finite(point.hi)) {
      values.push(point.hi)
    }
  }

  if (!values.length) {
    return { yMax: 1, yMin: 0 }
  }

  const probabilityLike = values.every(value => value >= 0 && value <= 1)
  let lo = Math.min(...values)
  let hi = Math.max(...values)

  if (hi - lo < MIN_CHART_SPAN) {
    const mid = (lo + hi) / 2
    lo = mid - MIN_CHART_SPAN / 2
    hi = mid + MIN_CHART_SPAN / 2
  }

  const pad = (hi - lo) * 0.15
  lo -= pad
  hi += pad

  if (probabilityLike) {
    lo = Math.max(0, lo)
    hi = Math.min(1, hi)
  }

  if (hi - lo < 1e-6) {
    hi = lo + 1
  }

  return { yMax: hi, yMin: lo }
}

// ── Vote-share / categorical PMF series (multi-candidate over time) ──────────

export interface VoteShareSeriesResult {
  /** one series per top-K candidate, then an aggregated `Other` when the tail is
   *  non-empty. The leader is index 0. Aligned to `keptIndices`. */
  series: { label: string; latestInterval?: { hi: number; lo: number } | null; values: (null | number)[] }[]
  /** indices INTO item.history the columns were drawn from (drives the x-axis) */
  keptIndices: number[]
  /** the leader's downsample preview (its `note` is the honest thinning caption) */
  preview: DownsampleResult
  /** the largest series value drawn (post-scale) — the chart's headroom anchor */
  yMax: number
  /** 100 when the payload is fraction-scale (shares in [0,1]), else 1 — so a 0.67
   *  share and a 67.0 share both render as 67 on a 0–100 axis */
  scale: number
}

// A candidate lookup tolerant of case/whitespace divergence between snapshots
// (the same tolerance intervalForLabel applies to interval keys).
const barForLabel = (bars: HistogramBar[] | null, label: string): HistogramBar | null => {
  if (!bars) {
    return null
  }
  const norm = label.trim().toLowerCase()
  return bars.find(bar => bar.label.trim().toLowerCase() === norm) ?? null
}

/**
 * Series-ify a vote-share / categorical PMF question's history into one line per
 * candidate — CLIENT-SIDE, because each snapshot already carries its full share
 * dict (`history[].probability`). The current snapshot's `probability` dict
 * (value-sorted) sets the candidate ranking + which labels are candidates (stat
 * keys already filtered by `distributionBars`); the top `topK` become their own
 * series (leader first), and the remaining tail folds into an aggregated `Other`.
 * Older points fill each series by the same candidate key (a missing candidate is
 * a `null` gap, never a fake 0). The leader series drives the change-aware
 * downsample so the x-axis thins on the material moves of the leading candidate.
 * Fraction-scale payloads are scaled ×100 so the axis is always 0–100, never the
 * negative axis the single-scalar chart produced.
 */
export const buildVoteShareSeries = (
  item: ForecastWorkspaceItem,
  currentBars: HistogramBar[],
  topK = 4
): VoteShareSeriesResult => {
  const scale = currentBars.every(bar => bar.value >= 0 && bar.value <= 1) ? 100 : 1
  const leaders = currentBars.slice(0, topK)
  const tailLabels = new Set(currentBars.slice(topK).map(bar => bar.label.trim().toLowerCase()))
  const history = (item.history ?? []) as ForecastWorkspaceHistoryPoint[]

  // Per-point candidate bars (stat keys filtered, value-sorted) — null for a
  // point whose payload is not a ≥2-candidate dict (older/degenerate snapshots).
  const pointBars = history.map(point => distributionBars(point.probability))

  // The leader's own series drives the downsample (its material moves anchor the
  // thinned x-axis), then every series is drawn from the SAME kept columns.
  const leaderValues = pointBars.map(bars => {
    const hit = barForLabel(bars, leaders[0]?.label ?? '')
    return hit ? hit.value * scale : null
  })
  const preview = downsampleSeries(leaderValues)
  const kept = preview.keptIndices

  const series = leaders.map(leader => ({
    label: leader.label,
    // The per-candidate 90% interval for the LATEST point (scaled to the axis) —
    // the chart draws it as a whisker on the final column.
    latestInterval:
      leader.interval && finite(leader.interval.lo) && finite(leader.interval.hi)
        ? { hi: leader.interval.hi * scale, lo: leader.interval.lo * scale }
        : null,
    values: kept.map(index => {
      const hit = barForLabel(pointBars[index] ?? null, leader.label)
      return hit ? hit.value * scale : null
    })
  }))

  // Aggregate the tail into a single `Other` line only when there IS a tail.
  if (currentBars.length > leaders.length) {
    series.push({
      label: 'Other',
      latestInterval: null, // the aggregated tail carries no single interval
      values: kept.map(index => {
        const bars = pointBars[index]
        if (!bars) {
          return null
        }
        const tail = bars.filter(bar => tailLabels.has(bar.label.trim().toLowerCase()))
        return tail.length ? tail.reduce((sum, bar) => sum + bar.value, 0) * scale : null
      })
    })
  }

  const drawn = series.flatMap(s => s.values).filter((value): value is number => finite(value))
  const yMax = drawn.length ? Math.max(...drawn) : 0

  return { keptIndices: kept, preview, scale, series, yMax }
}

/** Collapse a row of tagged plot cells into contiguous same-series runs, so the
 *  multi-series chart renders one coloured <Text> per run (leader distinct) rather
 *  than one node per cell. */
export const seriesRuns = (cells: SeriesCell[]): { series: number; text: string }[] => {
  const runs: { series: number; text: string }[] = []
  for (const cell of cells) {
    const last = runs[runs.length - 1]
    if (last && last.series === cell.series) {
      last.text += cell.ch
    } else {
      runs.push({ series: cell.series, text: cell.ch })
    }
  }
  return runs
}
