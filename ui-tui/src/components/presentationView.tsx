import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text } from '@hermes/ink'
import type { ReactNode, RefObject } from 'react'

import { bandChart, type BandPoint, compactNumber, histogram, pct } from '../lib/forecastCharts.js'
import { asciiTable } from '../lib/marketCharts.js'
import type { Presentation, PresentationBlock } from '../lib/presentation.js'
import { blockChart } from '../lib/sparkline.js'
import { dirColor, semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'
import { Rule, SectionTitle, WrapText } from './textBlocks.js'
import { Chart as VizChart } from './viz/Chart.js'

const numbers = (arr: unknown): number[] =>
  Array.isArray(arr) ? arr.map(v => (typeof v === 'number' ? v : Number(v))).filter(n => Number.isFinite(n)) : []

const xyPoints = (arr: unknown): { x: number; y: number }[] =>
  Array.isArray(arr)
    ? arr
        .filter((p): p is Record<string, unknown> => Boolean(p) && typeof p === 'object')
        .map(p => ({ x: Number(p.x), y: Number(p.y) }))
        .filter(p => Number.isFinite(p.x) && Number.isFinite(p.y))
    : []

// An item in assumptions/sources may be a plain string or an object with
// text/title/url — coerce robustly so we never render empty bullets.
const itemText = (it: unknown): string => {
  if (typeof it === 'string') {
    return it.trim()
  }

  if (it && typeof it === 'object') {
    const o = it as Record<string, unknown>
    const body = String(o.text ?? o.title ?? o.claim ?? o.label ?? o.name ?? '').trim()
    const url = o.url ? String(o.url) : ''

    if (body && url) {
      return `${body} (${url})`
    }

    return body || url
  }

  return ''
}

const Chart = ({ color, lines }: { color: string; lines: string[] }) => (
  <Box flexDirection="column" flexShrink={0}>
    {lines.map((line, i) => (
      <Text color={color} key={i}>
        {line}
      </Text>
    ))}
  </Box>
)

function renderBlock(block: PresentationBlock, t: Theme, width: number): ReactNode {
  const sem = semantics(t)
  const chartW = Math.max(24, Math.min(width, 96))
  const title = typeof block.title === 'string' ? block.title : ''
  const note = typeof block.note === 'string' ? block.note : ''

  switch (block.type) {
    case 'narrative':
      return (
        <Box flexDirection="column">
          {title ? <SectionTitle t={t}>{title}</SectionTitle> : null}
          <WrapText t={t} width={width}>
            {String(block.body ?? '')}
          </WrapText>
        </Box>
      )
    case 'finding': {
      const conf = String(block.confidence ?? 'medium')
      const tone = block.direction === 'up' ? sem.up : block.direction === 'down' ? sem.down : sem.star
      // Provenance: the evidence ids backing this claim (was persisted but never shown).
      const refs = Array.isArray(block.evidence_refs) ? block.evidence_refs.map(r => String(r).trim()).filter(Boolean) : []

      return (
        <Box flexDirection="column">
          <Box flexDirection="row">
            <Text color={tone}>{'• '}</Text>
            <Box width={Math.max(8, width - 2)}>
              <Text wrap="wrap">
                <Text bold color={t.color.text}>
                  {String(block.claim ?? '')}
                </Text>
                <Text color={t.color.muted}>{`  (${conf})`}</Text>
              </Text>
            </Box>
          </Box>
          {note ? (
            <Box marginLeft={2} width={Math.max(8, width - 2)}>
              <Text color={t.color.muted} wrap="wrap">
                {note}
              </Text>
            </Box>
          ) : null}
          {refs.length ? (
            <Box marginLeft={2} width={Math.max(8, width - 2)}>
              <Text color={t.color.muted} wrap="truncate-end">
                {`↳ ${refs.length === 1 ? 'evidence' : `${refs.length} evidence`}: ${refs.slice(0, 4).join(', ')}`}
              </Text>
            </Box>
          ) : null}
        </Box>
      )
    }

    case 'metric': {
      const val = typeof block.value === 'number' ? compactNumber(block.value) : String(block.value ?? '—')
      const delta = typeof block.delta === 'number' ? block.delta : null

      return (
        <Box width={width}>
          <Text wrap="wrap">
            <Text color={t.color.label}>{String(block.label ?? '')}</Text>
            <Text bold color={t.color.text}>{`  ${val}`}</Text>
            {block.unit ? <Text color={t.color.muted}>{` ${block.unit}`}</Text> : null}
            {delta !== null ? <Text color={dirColor(sem, delta)}>{`  ${delta >= 0 ? '+' : ''}${compactNumber(delta)}`}</Text> : null}
          </Text>
        </Box>
      )
    }

    case 'timeseries': {
      const series = Array.isArray(block.series) ? block.series : []

      return (
        <Box flexDirection="column">
          {title ? <SectionTitle t={t}>{title}</SectionTitle> : null}
          {series.map((s: Record<string, unknown>, i: number) => {
            const pts = xyPoints(s.points)
            const ys = pts.length ? pts.map(p => p.y) : numbers(s.points)

            return (
              <Box flexDirection="column" key={i} marginTop={i ? 1 : 0}>
                {s.name ? <Text color={t.color.label}>{String(s.name)}</Text> : null}
                <Chart color={sem.up} lines={blockChart(ys, chartW, 7)} />
              </Box>
            )
          })}
        </Box>
      )
    }

    case 'scatter':
      return (
        <Box flexDirection="column">
          {title ? <SectionTitle t={t}>{title}</SectionTitle> : null}
          <VizChart data={{ markers: block.markers, points: block.points }} kind="scatter" t={t} width={chartW} />
        </Box>
      )
    case 'regression': {
      const r2 = typeof block.r2 === 'number' ? block.r2.toFixed(3) : '—'
      const coeffs = Array.isArray(block.coeffs) ? block.coeffs : []

      const stat = coeffs
        .map((c: Record<string, unknown>) => `${c.name}=${typeof c.value === 'number' ? c.value.toFixed(3) : c.value}`)
        .join(' · ')

      const yl = block.y_label ? String(block.y_label) : ''
      const xl = Array.isArray(block.x_labels) && block.x_labels.length ? String(block.x_labels[0]) : ''

      return (
        <Box flexDirection="column">
          <SectionTitle t={t}>{title || (yl && xl ? `${yl} vs ${xl}` : 'Regression')}</SectionTitle>
          <VizChart data={{ fitLine: block.fit_line, markers: block.markers, points: block.points }} kind="scatter" t={t} width={chartW} />
          <WrapText color={t.color.muted} t={t} width={width}>
            {`R² ${r2}${stat ? ` · ${stat}` : ''}${typeof block.n === 'number' ? ` · n=${block.n}` : ''}`}
          </WrapText>
        </Box>
      )
    }

    case 'bars': {
      const cats = Array.isArray(block.categories) ? block.categories : []
      const series = Array.isArray(block.series) ? block.series : []
      const vals = numbers((series[0] as Record<string, unknown>)?.values)
      const bars = cats.map((c: unknown, i: number) => ({ label: String(c), value: vals[i] ?? 0 }))

      return (
        <Box flexDirection="column">
          {title ? <SectionTitle t={t}>{title}</SectionTitle> : null}
          <Chart color={sem.up} lines={histogram(bars, { width: chartW })} />
        </Box>
      )
    }

    case 'table': {
      const cols = Array.isArray(block.columns) ? (block.columns as { align?: 'left' | 'right'; key: string; label: string }[]) : []
      const rows = Array.isArray(block.rows) ? (block.rows as Record<string, number | string>[]) : []
      const lines = asciiTable(cols, rows, { width: chartW })

      return (
        <Box flexDirection="column">
          {title ? <SectionTitle t={t}>{title}</SectionTitle> : null}
          {lines.map((line, i) => (
            <Text color={i === 0 ? t.color.label : i === 1 ? t.color.border : t.color.text} key={i} wrap="truncate-end">
              {line}
            </Text>
          ))}
        </Box>
      )
    }

    case 'fan': {
      const median = numbers(block.median)
      const bands = Array.isArray(block.bands) ? block.bands : []
      const band0 = bands[0] as Record<string, unknown> | undefined
      // Monte-Carlo upgrade: when the block carries simulated `paths`, render the
      // braille cone (median + spaghetti + band) via the viz engine. Otherwise the
      // existing bandChart path renders byte-identically (back-compat).
      const hasPaths = Array.isArray(block.paths) && (block.paths as unknown[]).some(p => Array.isArray(p) && p.length)

      if (hasPaths) {
        return (
          <Box flexDirection="column">
            <SectionTitle t={t}>{title || 'Simulation'}</SectionTitle>
            <VizChart data={block} height={9} kind="fan" t={t} width={chartW} />
            {band0 ? <Text color={t.color.muted}>{`P${band0.p_lo}–P${band0.p_hi}${typeof block.n_paths === 'number' && block.n_paths ? ` · ${block.n_paths} paths` : ''}`}</Text> : null}
          </Box>
        )
      }

      const lower = numbers(band0?.lower)
      const upper = numbers(band0?.upper)
      const points: BandPoint[] = median.map((y, i) => ({ hi: upper[i] ?? null, lo: lower[i] ?? null, y }))
      const yAll = [...median, ...lower, ...upper]
      const { rows } = bandChart(points, { height: 8, width: chartW, yMax: Math.max(...yAll, 1), yMin: Math.min(...yAll, 0) })

      return (
        <Box flexDirection="column">
          <SectionTitle t={t}>{title || 'Simulation'}</SectionTitle>
          <Chart color={sem.up} lines={rows} />
          {band0 ? <Text color={t.color.muted}>{`P${band0.p_lo}–P${band0.p_hi}${typeof block.n_paths === 'number' && block.n_paths ? ` · ${block.n_paths} paths` : ''}`}</Text> : null}
        </Box>
      )
    }

    case 'heatmap':

    case 'distribution':

    case 'candles':

    case 'depth':

    case 'sparkgrid':
      return (
        <Box flexDirection="column">
          {title ? <SectionTitle t={t}>{title}</SectionTitle> : null}
          <VizChart
            data={block}
            height={block.type === 'sparkgrid' ? undefined : 10}
            kind={block.type as 'candles' | 'depth' | 'distribution' | 'heatmap' | 'sparkgrid'}
            t={t}
            width={chartW}
          />
          {note ? (
            <WrapText color={t.color.muted} t={t} width={width}>
              {note}
            </WrapText>
          ) : null}
        </Box>
      )
    case 'scenario': {
      const scen = Array.isArray(block.scenarios) ? (block.scenarios as Record<string, unknown>[]) : []

      const rows = scen.map(s => ({
        outcome: typeof s.outcome === 'number' ? compactNumber(s.outcome) : String(s.outcome ?? ''),
        prob: typeof s.probability === 'number' ? pct(s.probability, 0) : '—',
        scenario: String(s.name ?? '')
      }))

      const lines = asciiTable(
        [
          { key: 'scenario', label: 'Scenario' },
          { align: 'right', key: 'prob', label: 'Prob' },
          { align: 'right', key: 'outcome', label: 'Outcome' }
        ],
        rows,
        { width: chartW }
      )

      return (
        <Box flexDirection="column">
          <SectionTitle t={t}>{title || 'Scenarios'}</SectionTitle>
          {lines.map((line, i) => (
            <Text color={i < 2 ? t.color.label : t.color.text} key={i} wrap="truncate-end">
              {line}
            </Text>
          ))}
        </Box>
      )
    }

    case 'assumptions':
    case 'sources': {
      const items = (Array.isArray(block.items) ? block.items : []).map(itemText).filter(Boolean)

      return (
        <Box flexDirection="column">
          <SectionTitle t={t}>{title || (block.type === 'sources' ? 'Sources' : 'Assumptions')}</SectionTitle>
          {items.length === 0 ? (
            <Text color={t.color.muted}>—</Text>
          ) : (
            items.map((text, i) => (
              <Box flexDirection="row" key={i}>
                <Text color={t.color.muted}>{'• '}</Text>
                <Box width={Math.max(8, width - 2)}>
                  <Text color={t.color.muted} wrap="wrap">
                    {text}
                  </Text>
                </Box>
              </Box>
            ))
          )}
        </Box>
      )
    }

    default:
      return (
        <Box flexDirection="column">
          {title ? <SectionTitle t={t}>{title}</SectionTitle> : null}
          <WrapText color={t.color.muted} t={t} width={width}>
            {note || `(${block.type})`}
          </WrapText>
        </Box>
      )
  }
}

export function PresentationView({
  height,
  now,
  presentation,
  scrollRef,
  t,
  versionLabel,
  width
}: {
  height: number
  now: number
  presentation: Presentation
  scrollRef: RefObject<null | ScrollBoxHandle>
  t: Theme
  versionLabel?: string
  width: number
}) {
  const innerW = Math.max(24, width - 2)
  const dataStamp = presentation.as_of_data ? `data ${presentation.as_of_data.slice(0, 10)}` : ''
  const analysisStamp = presentation.as_of_analysis ? `analysis ${presentation.as_of_analysis.slice(0, 10)}` : ''

  return (
    <Box flexDirection="row" height={height}>
      <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={scrollRef}>
        <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
          <WrapText bold t={t} width={innerW}>
            {presentation.title}
          </WrapText>
          <Text color={t.color.muted} wrap="truncate-end">
            {[versionLabel, analysisStamp, dataStamp, presentation.status].filter(Boolean).join(' · ')}
          </Text>
          {presentation.summary ? (
            <Box marginTop={1}>
              <WrapText t={t} width={innerW}>
                {presentation.summary}
              </WrapText>
            </Box>
          ) : null}
          <Box marginTop={1}>
            <Rule t={t} width={innerW} />
          </Box>
          {presentation.blocks.map((b, i) => (
            <Box flexDirection="column" key={b.id ?? `b-${i}`} marginTop={1}>
              {renderBlock(b, t, innerW)}
            </Box>
          ))}
        </Box>
      </ScrollBox>
      <NoSelect flexShrink={0} marginLeft={1}>
        <OverlayScrollbar scrollRef={scrollRef} t={t} tick={now} />
      </NoSelect>
    </Box>
  )
}
