import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useEffect, useRef, useState } from 'react'

import { $globalModal, openHelpOverlay } from '../app/overlayStore.js'
import type { ChartKind } from '../lib/viz/index.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'
import { FooterChips } from './footerChips.js'
import { Rule, SectionTitle } from './textBlocks.js'
import { Chart as VizChart } from './viz/Chart.js'

// A scrollable gallery of every @hermes/viz chart type with sample data — a
// living showcase to eyeball fidelity across the engine in one place.

const series = (n: number, fn: (i: number) => number): number[] => Array.from({ length: n }, (_, i) => fn(i))

function gen<T>(n: number, fn: (i: number) => T): T[] {
  return Array.from({ length: n }, (_, i) => fn(i))
}

// Deterministic fixtures (no RNG — sin/cos by index so the gallery is stable).
const SAMPLES: { data: unknown; height?: number; kind: ChartKind; subtitle: string; title: string }[] = (() => {
  const n = 48
  const trend = series(n, i => 1 + i * 0.07 + Math.sin(i / 4) * 0.25)
  const scatterPts = gen(n, i => ({ x: i, y: i * 0.6 + Math.sin(i / 3) * 4 + (i % 5) - 2 }))

  const corr = ['NVDA', 'TSM', 'AVGO', 'AMD', 'MSFT', 'SMCI']
  const matrix = corr.map((_, r) => corr.map((_, c) => (r === c ? 1 : Math.cos((r - c) / 2) * 0.85)))

  const median = series(36, i => 100 + i * 2.2 + Math.sin(i / 5) * 6)
  const lower = median.map((m, i) => m - (4 + i * 0.5))
  const upper = median.map((m, i) => m + (4 + i * 0.5))
  const paths = gen(16, k => series(36, i => median[i]! + (k - 8) * (1 + i * 0.12) * 0.5))

  const support = series(60, i => -3 + (6 * i) / 59)
  const pdf = support.map(x => Math.exp(-(x * x) / 2))
  const total = pdf.reduce((a, b) => a + b, 0)
  let acc = 0
  const cdf = pdf.map(v => (acc += v) / total)

  const candles = gen(40, i => {
    const o = 100 + Math.sin(i / 4) * 8 + i * 0.4
    const c = o + Math.cos(i / 3) * 3

    return { c, h: Math.max(o, c) + 1.5, l: Math.min(o, c) - 1.5, o }
  })

  const volume = candles.map((_, i) => 1000 + Math.abs(Math.sin(i / 2)) * 2400)

  const bids = gen(14, i => ({ price: 100 - i * 0.4, size: 3 + i * 1.6 + Math.sin(i) }))
  const asks = gen(14, i => ({ price: 100.6 + i * 0.4, size: 3 + i * 1.4 + Math.cos(i) }))

  const watch = ['NVDA', 'TSM', 'AVGO', 'AMD', 'MSFT', 'SMCI'].map((label, i) => ({
    delta: Math.sin(i) * 0.05,
    label,
    value: 100 + i * 47,
    values: series(20, j => 100 + i * 10 + Math.sin(j / 2 + i) * 12)
  }))

  return [
    {
      data: { fitLine: [{ x: 0, y: 0 }, { x: n - 1, y: (n - 1) * 0.6 }], points: scatterPts },
      height: 14,
      kind: 'scatter',
      subtitle: 'braille points + interpolated fit line (regression / scatter blocks)',
      title: 'Scatter / Regression'
    },
    {
      data: { colLabels: corr, diverging: true, matrix, rowLabels: corr },
      kind: 'heatmap',
      subtitle: 'truecolor half-block correlation matrix (diverging blue↔red)',
      title: 'Heatmap'
    },
    {
      data: { bands: [{ lower, p_hi: 90, p_lo: 10, upper }], markers: [{ label: 'target', y: 160 }], median, paths },
      height: 12,
      kind: 'fan',
      subtitle: 'smooth confidence cone (dim fill + braille outline) + bright median + threshold marker',
      title: 'Fan / Monte-Carlo'
    },
    {
      data: { cdf, intervals: [{ hi: 1.28, lo: -1.28, p: 0.8 }, { hi: 1.96, lo: -1.96, p: 0.95 }], mean: 0, median: 0, pdf, support },
      height: 12,
      kind: 'distribution',
      subtitle: 'PDF + CDF overlay + 80/95% interval bands + mean/median markers',
      title: 'Distribution'
    },
    {
      data: { candles, ma: trend.map(v => v * 30), volume },
      height: 16,
      kind: 'candles',
      subtitle: 'OHLC block candles + volume sub-panel (gain green / loss red)',
      title: 'Candlesticks'
    },
    {
      data: { asks, bids, mid: 100.3 },
      height: 12,
      kind: 'depth',
      subtitle: 'cumulative bid/ask depth curve + mid marker',
      title: 'Order-book Depth'
    },
    {
      data: { cells: watch, columns: 2 },
      kind: 'sparkgrid',
      subtitle: 'dashboard grid of label + sparkline + value + colored delta',
      title: 'Sparkline Grid'
    }
  ]
})()

export function DemoVizView({ onClose, t }: { onClose: () => void; t: Theme }) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24
  const scrollRef = useRef<null | ScrollBoxHandle>(null)
  const [tick, setTick] = useState(0)
  // Go inert while the Ctrl+K palette / `?` cheat-sheet stacks above the view.
  const globalModal = useStore($globalModal)

  useEffect(() => {
    const id = setInterval(() => setTick(v => v + 1), 600)

    return () => clearInterval(id)
  }, [])

  const width = Math.min(cols - 4, 100)
  const innerW = Math.max(24, width - 2)
  const chartW = Math.max(24, Math.min(innerW, 96))
  const contentHeight = Math.max(8, termRows - 4)

  useInput((ch, key) => {
    if (key.escape || ch === 'q') {
      return onClose()
    }

    // `h` opens the unified Help modal — consistent on every view.
    if (ch === 'h') {
      return openHelpOverlay()
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return scrollRef.current?.scrollBy?.(-2)
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return scrollRef.current?.scrollBy?.(2)
    }

    if (key.pageUp) {
      return scrollRef.current?.scrollBy?.(-(contentHeight - 2))
    }

    if (key.pageDown) {
      return scrollRef.current?.scrollBy?.(contentHeight - 2)
    }

    if (ch === 'g') {
      return scrollRef.current?.scrollTo?.(0)
    }

    if (ch === 'G') {
      return scrollRef.current?.scrollToBottom?.()
    }
  }, { isActive: !globalModal })

  return (
    <Box flexDirection="column" flexGrow={1} paddingX={1}>
      <Text bold color={t.color.accent} wrap="truncate-end">
        DEMO VISUALISATIONS
      </Text>
      <Text color={t.color.muted} wrap="truncate-end">
        every @hermes/viz chart type with sample data
      </Text>
      <Box flexDirection="row" height={contentHeight} marginTop={1}>
        <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={scrollRef}>
          <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
            {SAMPLES.map((s, i) => (
              <Box flexDirection="column" key={s.kind} marginTop={i ? 2 : 0}>
                <SectionTitle t={t}>{s.title}</SectionTitle>
                <Text color={t.color.muted} wrap="truncate-end">
                  {s.subtitle}
                </Text>
                <Box marginTop={1}>
                  <VizChart data={s.data} height={s.height} kind={s.kind} t={t} width={chartW} />
                </Box>
                <Box marginTop={1}>
                  <Rule t={t} width={innerW} />
                </Box>
              </Box>
            ))}
          </Box>
        </ScrollBox>
        <NoSelect flexShrink={0} marginLeft={1}>
          <OverlayScrollbar scrollRef={scrollRef} t={t} tick={tick} />
        </NoSelect>
      </Box>
      <FooterChips
        chips={[
          { k: '↑↓', label: 'Scroll' },
          { k: 'PgUp/Dn', label: 'Page' },
          { k: 'g/G', label: 'Top/Bot' },
          { k: 'h', label: 'Help', run: openHelpOverlay },
          { k: '⎋', label: 'Back', run: onClose }
        ]}
        disabled={globalModal}
        t={t}
      />
    </Box>
  )
}
