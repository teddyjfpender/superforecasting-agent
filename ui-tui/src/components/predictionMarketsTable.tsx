import { Box, Text } from '@hermes/ink'

import { fmtClose, fmtPMVol, fmtProb, venueLabel } from '../lib/pmData.js'
import { type PMDisplayRow } from '../lib/pmRows.js'
import { pmExpandable } from '../lib/pmRows.js'
import { sortIndicator, type TableSortState } from '../lib/tableSort.js'
import { pad, type Semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

interface PMTableProps {
  active: boolean
  avail: number
  clampedSel: number
  emptyText: string
  expanded: ReadonlySet<string>
  height: number
  labelCol: number
  listStart: number
  livePrices: Record<string, number>
  onSelect: (idx: number) => void
  onSortByKey: (key: string) => void
  rowsLength: number
  sem: Semantics
  sortState: TableSortState
  t: Theme
  tableWidth: number
  windowed: PMDisplayRow[]
}

const sortHead = (label: string, key: string, state: TableSortState, w: number): string =>
  pad(`${label}${state.key === key ? ` ${sortIndicator(state, key)}` : ''}`, w, key === 'title' ? 'left' : 'right')

// The dense tape: event HEADLINE rows (title + top outcome, de-vigged prob,
// volume, close, venue chip) with ▸ expand revealing INDENTED outcome sub-rows
// (label, prob, bid/ask, volume) — the discretised distribution.
export function PredictionMarketsTable({
  active,
  avail,
  clampedSel,
  emptyText,
  expanded,
  height,
  labelCol,
  listStart,
  livePrices,
  onSelect,
  onSortByKey,
  rowsLength,
  sem,
  sortState,
  t,
  tableWidth,
  windowed
}: PMTableProps) {
  const headColor = (key: string) => (sortState.key === key ? t.color.accent : sem.heading)

  return (
    <Box flexDirection="column" flexShrink={0} height={height} overflow="hidden" paddingRight={1} width={tableWidth}>
      <Box>
        <Text bold color={sem.heading}>{'  '}</Text>
        <Text bold color={headColor('title')} onClick={active ? () => onSortByKey('title') : undefined}>
          {sortHead('MARKET', 'title', sortState, labelCol)}
        </Text>
        <Text bold color={headColor('prob')} onClick={active ? () => onSortByKey('prob') : undefined}>
          {sortHead('PROB', 'prob', sortState, 7)}
        </Text>
        <Text bold color={headColor('vol')} onClick={active ? () => onSortByKey('vol') : undefined}>
          {sortHead('VOL', 'vol', sortState, 8)}
        </Text>
        <Text bold color={headColor('close')} onClick={active ? () => onSortByKey('close') : undefined}>
          {sortHead('CLOSE', 'close', sortState, 7)}
        </Text>
      </Box>
      <Text color={sem.rule}>{'─'.repeat(avail)}</Text>
      <Box flexDirection="column">
        {rowsLength === 0 ? (
          <Text color={sem.subtle} wrap="wrap">
            {emptyText}
          </Text>
        ) : (
          windowed.map((row, i) => {
            const idx = listStart + i
            const on = idx === clampedSel

            if (row.kind === 'headline') {
              const h = row.item.distribution.headline
              // The live tick is a RAW yes mid; only overlay it where the shown
              // prob is itself raw (binary, or a non-de-vigged event). For a
              // de-vigged categorical, overlaying the raw mid would break
              // sum-to-1 and mix scales — keep the de-vigged prob.
              const rawOk = row.item.distribution.binary || !row.item.distribution.normalized
              const live = rawOk ? livePrices[row.item.distribution.outcomes?.[0]?.market_id ?? ''] : undefined
              const prob = live ?? h.top_prob
              const canExpand = pmExpandable(row.item)
              const caret = canExpand ? (expanded.has(row.id) ? '▾ ' : '▸ ') : '  '

              const title = row.item.distribution.binary
                ? row.item.distribution.title
                : `${row.item.distribution.title}${h.top_label ? ` — ${h.top_label}` : ''}`

              return (
                <Box key={row.id} onClick={active ? () => onSelect(idx) : undefined} width="100%">
                  <Text wrap="truncate-end">
                    <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
                    <Text color={canExpand ? sem.subtle : sem.faint}>{caret}</Text>
                    <Text bold={on} color={on ? sem.selectionFg : t.color.label}>
                      {pad(title, labelCol - 2, 'left')}
                    </Text>
                    <Text color={t.color.text}>{pad(fmtProb(prob), 7, 'right')}</Text>
                    <Text color={sem.subtle}>{pad(fmtPMVol(h.total_volume), 8, 'right')}</Text>
                    <Text color={sem.subtle}>{pad(fmtClose(h.close_time), 6, 'right')}</Text>
                    <Text color={sem.faint}>{` ${venueLabel(row.item.event.venue).slice(0, 4)}`}</Text>
                  </Text>
                </Box>
              )
            }

            const o = row.outcome
            // Same raw-vs-devig guard as the headline: a de-vigged sub-row keeps
            // its de-vigged prob rather than jumping to the raw live mid.
            const rawOk = row.parent.distribution.binary || !row.parent.distribution.normalized
            const live = rawOk ? livePrices[o.market_id] : undefined
            const prob = live ?? o.prob
            const quote = o.yes_bid !== null || o.yes_ask !== null ? `${Math.round((o.yes_bid ?? 0) * 100)}/${Math.round((o.yes_ask ?? 0) * 100)}` : '—'

            return (
              <Box key={row.id} onClick={active ? () => onSelect(idx) : undefined} width="100%">
                <Text wrap="truncate-end">
                  <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
                  <Text color={sem.faint}>{'   └ '}</Text>
                  <Text color={on ? sem.selectionFg : sem.subtle}>{pad(o.label, labelCol - 5, 'left')}</Text>
                  <Text color={t.color.text}>{pad(fmtProb(prob), 7, 'right')}</Text>
                  <Text color={sem.faint}>{pad(quote, 8, 'right')}</Text>
                  <Text color={sem.subtle}>{pad(fmtPMVol(o.volume), 6, 'right')}</Text>
                </Text>
              </Box>
            )
          })
        )}
      </Box>
    </Box>
  )
}
