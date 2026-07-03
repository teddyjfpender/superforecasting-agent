import { Box, Text } from '@hermes/ink'

import { fmtBidAsk, fmtClose, fmtPMVol, fmtProb, venueChip } from '../lib/pmData.js'
import { packPmHead, packPmOutcome, type PMDisplayRow, pmExpandable } from '../lib/pmRows.js'
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

// The gutter every non-first column leads with — kept in sync with the pack
// machinery (lib/pmRows) so header + rows line up cell-for-cell.
const GUT = '  '

// The dense Prediction Markets section: event HEADLINE rows (title + top
// outcome, de-vigged prob, volume, close, venue chip) with ▸ expand revealing
// INDENTED outcome sub-rows (label, prob, bid·ask, volume). Two aligned column
// schemas — every value sits under a header that NAMES it.
export function PredictionMarketsTable({
  active,
  avail,
  clampedSel,
  emptyText,
  expanded,
  height,
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
  const head = packPmHead(avail)
  const outcome = packPmOutcome(avail)
  const headColor = (key: string) => (sortState.key === key ? t.color.accent : sem.heading)

  const headText = (label: string, key: string, w: number, align: 'left' | 'right') =>
    pad(`${label}${sortState.key === key ? ` ${sortIndicator(sortState, key)}` : ''}`, w, align)

  return (
    <Box flexDirection="column" flexShrink={0} height={height} overflow="hidden" paddingRight={1} width={tableWidth}>
      {/* Headline header row — MARKET | PROB | VOL | CLOSE | VENUE. Each named
          column (except the non-sortable venue chip) is a click target. */}
      <Box>
        <Text bold color={sem.heading}>{'  '}</Text>
        <Text bold color={headColor('title')} onClick={active ? () => onSortByKey('title') : undefined}>
          {headText('MARKET', 'title', head.marketW, 'left')}
        </Text>
        {head.cols.map(c => (
          <Text
            bold
            color={headColor(c.key)}
            key={c.key}
            onClick={active && c.key !== 'venue' ? () => onSortByKey(c.key) : undefined}
          >
            {`${GUT}${headText(c.label, c.key, c.w, c.align)}`}
          </Text>
        ))}
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
              // A degenerate/empty book yields a null top prob — render '—',
              // NEVER a fabricated 50%.
              const prob = live ?? h.top_prob
              const canExpand = pmExpandable(row.item)
              const caret = canExpand ? (expanded.has(row.id) ? '▾ ' : '▸ ') : '  '

              const title = row.item.distribution.binary
                ? row.item.distribution.title
                : `${row.item.distribution.title}${h.top_label ? ` — ${h.top_label}` : ''}`

              const cell = (key: string): string => {
                switch (key) {
                  case 'close':
                    return fmtClose(h.close_time)

                  case 'prob':
                    return fmtProb(prob)

                  case 'venue':
                    return venueChip(row.item.event.venue)

                  case 'vol':
                    return fmtPMVol(h.total_volume)

                  default:
                    return ''
                }
              }

              return (
                <Box key={row.id} onClick={active ? () => onSelect(idx) : undefined} width="100%">
                  <Text wrap="truncate-end">
                    <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
                    <Text color={canExpand ? sem.subtle : sem.faint}>{caret}</Text>
                    <Text bold={on} color={on ? sem.selectionFg : t.color.label}>
                      {pad(title, head.marketW - 2, 'left')}
                    </Text>
                    {head.cols.map(c => (
                      <Text color={c.key === 'venue' ? sem.faint : c.key === 'prob' ? t.color.text : sem.subtle} key={c.key}>
                        {`${GUT}${pad(cell(c.key), c.w, c.align)}`}
                      </Text>
                    ))}
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
            // First outcome of an expanded group gets a dim OUTCOME | PROB |
            // BID·ASK | VOL header line above it, so every sub-cell is named.
            const prev = windowed[i - 1]
            const firstOfGroup = !prev || prev.kind !== 'outcome' || prev.parentId !== row.parentId

            const outCell = (key: string): string => {
              switch (key) {
                case 'ba':
                  return fmtBidAsk(o.yes_bid, o.yes_ask)

                case 'prob':
                  return fmtProb(prob)

                case 'vol':
                  return fmtPMVol(o.volume)

                default:
                  return ''
              }
            }

            return (
              <Box flexDirection="column" key={row.id} width="100%">
                {firstOfGroup ? (
                  <Text wrap="truncate-end">
                    <Text color={sem.faint}>{'     '}</Text>
                    <Text color={sem.subtle}>{pad('OUTCOME', outcome.labelW, 'left')}</Text>
                    {outcome.cols.map(c => (
                      <Text color={sem.subtle} key={c.key}>
                        {`${GUT}${pad(c.label, c.w, c.align)}`}
                      </Text>
                    ))}
                  </Text>
                ) : null}
                <Box onClick={active ? () => onSelect(idx) : undefined} width="100%">
                  <Text wrap="truncate-end">
                    <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
                    <Text color={sem.faint}>{'└ '}</Text>
                    <Text color={on ? sem.selectionFg : sem.subtle}>{pad(o.label, outcome.labelW, 'left')}</Text>
                    {outcome.cols.map(c => (
                      <Text color={c.key === 'prob' ? t.color.text : c.key === 'ba' ? sem.faint : sem.subtle} key={c.key}>
                        {`${GUT}${pad(outCell(c.key), c.w, c.align)}`}
                      </Text>
                    ))}
                  </Text>
                </Box>
              </Box>
            )
          })
        )}
      </Box>
    </Box>
  )
}
