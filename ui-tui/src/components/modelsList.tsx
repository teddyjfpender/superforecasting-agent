import { Box, Text } from '@hermes/ink'

import { spinnerFrame, statusGlyph } from '../lib/icons.js'
import type { MarketModelListItem } from '../lib/presentation.js'
import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

const relTime = (iso?: string): string => {
  if (!iso) {
    return ''
  }

  const ms = Date.parse(iso)

  if (!Number.isFinite(ms)) {
    return ''
  }

  const m = Math.floor((Date.now() - ms) / 60_000)

  if (m < 1) {
    return 'now'
  }

  if (m < 60) {
    return `${m}m`
  }

  const h = Math.floor(m / 60)

  if (h < 24) {
    return `${h}h`
  }

  return `${Math.floor(h / 24)}d`
}

const trunc = (s: string, n: number): string => (s.length > n ? `${s.slice(0, Math.max(0, n - 1))}…` : s)

// Render-only list of saved Market Models. The parent (marketsView) owns
// selection + keys; building rows show a spinner + the latest progress label.
export function ModelsList({
  height,
  models,
  progressById,
  sel,
  t,
  tick,
  width
}: {
  height: number
  models: MarketModelListItem[]
  progressById: Record<string, string>
  sel: number
  t: Theme
  tick: number
  width: number
}) {
  const sem = semantics(t)
  const rows = Math.max(3, height - 1)
  const start = Math.max(0, Math.min(sel - Math.floor(rows / 2), Math.max(0, models.length - rows)))
  const windowed = models.slice(start, start + rows)
  const titleW = Math.max(16, Math.min(48, width - 28))

  if (models.length === 0) {
    return (
      <Box flexDirection="column" height={height} justifyContent="center" paddingX={2}>
        <Text bold color={t.color.text}>
          No market models yet.
        </Text>
        <Box marginTop={1}>
          <Text color={t.color.muted} wrap="wrap">
            Press n to define a quant question (e.g. "how has GPU compute-per-chip growth driven NVIDIA revenue; build a forward-looking regression"). The desk researches, computes, and presents it here.
          </Text>
        </Box>
      </Box>
    )
  }

  return (
    <Box flexDirection="column" height={height}>
      <Text bold color={t.color.label} wrap="truncate-end">
        {'  '}
        {'STATUS  '}
        {'MODEL'.padEnd(titleW)}
        {'  DEPTH    UPDATED'}
      </Text>
      {windowed.map((m, i) => {
        const idx = start + i
        const on = idx === sel
        // Server-truth: a model is still building until its first presentation
        // exists (current_version >= 1). This survives a missed "complete" event;
        // the live progress label (from events) is just a nicety on top.
        const hasPresentation = (m.current_version ?? 0) >= 1
        const building = !hasPresentation && m.status !== 'error'
        // An already-built model with a live progress label is being refined.
        const refining = !building && Boolean(progressById[m.id])
        const failed = hasPresentation && (m.last_status === 'failed' || m.status === 'error')
        const active = building || refining
        const glyph = active ? spinnerFrame(tick) : failed ? statusGlyph('error') : statusGlyph('live', tick)
        const glyphColor = active ? sem.star : failed ? sem.down : sem.up
        const label = active ? trunc(progressById[m.id] || (refining ? 'refining…' : 'building…'), titleW) : trunc(m.title, titleW)

        return (
          <Text key={m.id} wrap="truncate-end">
            <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
            <Text color={glyphColor}>{glyph.padEnd(7)}</Text>
            <Text bold={on} color={on ? sem.selectionFg : t.color.text}>
              {label.padEnd(titleW)}
            </Text>
            <Text color={t.color.muted}>{`  ${(m.depth ?? '').padEnd(8)} ${relTime(m.updated_at)}`}</Text>
          </Text>
        )
      })}
    </Box>
  )
}
