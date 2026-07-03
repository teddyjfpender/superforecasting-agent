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
  // Row ids (venue:event_id) surfaced via '/' discovery — each gets a subtle
  // "+" marker before its venue chip so curated finds read apart from the browse
  // feed. Optional (defaults empty) so the pure column tests need not pass it.
  discoveredKeys?: ReadonlySet<string>
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

// The FIXED-WIDTH direction gutter at the head of EVERY prob cell: exactly 4
// cells — "YES " on a binary YES-side reading, 4 spaces otherwise — then the %
// value right-aligned in the remaining (w - 4) cells. Pinning the gutter keeps
// the values right-aligned in ONE column whether or not the row carries a tag
// (the operator's screenshot showed YES floats at ragged offsets). A degenerate
// value too wide to sit beside the gutter (only a 7-char "100.00%") right-aligns
// across the FULL cell instead: its right edge stays in the same column, so the
// alignment holds; the tag is simply dropped for that one pathological row.
// Prices are YES-side; a NO complement belongs in the detail, never a table row.
const DIR_GUT = 4

const probCell = (num: string, w: number, tag: boolean, on: boolean, t: Theme, sem: Semantics) => {
  const fits = num.length <= w - DIR_GUT

  return (
    <Text key="prob">
      {GUT}
      {!fits ? null : tag ? (
        <Text bold={on} color={sem.up}>
          {'YES '}
        </Text>
      ) : (
        <Text>{' '.repeat(DIR_GUT)}</Text>
      )}
      <Text color={t.color.text}>{pad(num, fits ? w - DIR_GUT : w, 'right')}</Text>
    </Text>
  )
}

// The dense Prediction Markets section: event HEADLINE rows (title + top
// outcome, de-vigged prob, volume, close, venue chip) with ▸ expand revealing
// INDENTED outcome sub-rows (label, prob, bid·ask, volume). Two aligned column
// schemas — every value sits under a header that NAMES it.
export function PredictionMarketsTable({
  active,
  avail,
  clampedSel,
  discoveredKeys,
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
          column (except the non-sortable venue chip) is a click target. The
          click MUST live on a <Box> — <Text onClick> is silently dropped by the
          ink fork (Text has no onClick prop), which is why header-click sort was
          dead. This mirrors the quote table's Box-wrapped, working header. */}
      <Box>
        <Text bold color={sem.heading}>{'  '}</Text>
        <Box onClick={active ? () => onSortByKey('title') : undefined}>
          <Text bold color={headColor('title')}>
            {headText('MARKET', 'title', head.marketW, 'left')}
          </Text>
        </Box>
        {head.cols.map(c => (
          <Box key={c.key} onClick={active && c.key !== 'venue' ? () => onSortByKey(c.key) : undefined}>
            <Text bold color={headColor(c.key)}>
              {`${GUT}${headText(c.label, c.key, c.w, c.align)}`}
            </Text>
          </Box>
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

              // A binary market's headline prob IS a YES reading — contextualise
              // it with a colour-coded "YES" (success token) prefix. Categorical
              // headlines already carry their top outcome's label in the title, so
              // they stay a bare number (no double-labelling).
              const binary = row.item.distribution.binary

              // Rows that ride the tape ONLY because the operator discovered them
              // via '/' search carry a subtle "+" in the second cell of the cursor
              // gutter — a cell that is otherwise blank, so an absent marker
              // reflows nothing and it survives every column drop (venue is the
              // first column shed on a narrow tape).
              const discovered = discoveredKeys?.has(row.id) ?? false

              return (
                // The selected row highlights across its FULL width (desk-view
                // parity): the background IS the cursor.
                <Box key={row.id} onClick={active ? () => onSelect(idx) : undefined} width="100%">
                  <Text backgroundColor={on ? t.color.selectionBg : undefined} wrap="truncate-end">
                    {/* The 2-cell cursor gutter: [cursor ▸ / space][discovered + /
                        space]. The marker rides the trailing cell that used to be
                        a plain space, so browse rows look exactly as before. */}
                    <Text color={on ? sem.cursor : sem.faint}>{on ? '▸' : ' '}</Text>
                    <Text color={sem.subtle}>{discovered ? '+' : ' '}</Text>
                    <Text color={canExpand ? sem.subtle : sem.faint}>{caret}</Text>
                    <Text bold={on} color={on ? sem.selectionFg : t.color.label}>
                      {pad(title, head.marketW - 2, 'left')}
                    </Text>
                    {head.cols.map(c =>
                      // PROB leads with the fixed 4-cell direction gutter (binary
                      // headline → colour-coded "YES ", categorical → 4 spaces,
                      // since its label already lives in the title) so every % in
                      // the column right-aligns under one edge.
                      c.key === 'prob' ? (
                        probCell(fmtProb(prob), c.w, binary, on, t, sem)
                      ) : (
                        <Text color={c.key === 'venue' ? sem.faint : sem.subtle} key={c.key}>
                          {`${GUT}${pad(cell(c.key), c.w, c.align)}`}
                        </Text>
                      )
                    )}
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
                  {/* Full-row highlight on the selected sub-row too (the cursor
                      must never disappear on an outcome). The 3-cell '└─ ' tree
                      run matches the pack's indent so the row fills the width. */}
                  <Text backgroundColor={on ? t.color.selectionBg : undefined} wrap="truncate-end">
                    <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
                    <Text color={sem.faint}>{'└─ '}</Text>
                    <Text bold={on} color={on ? sem.selectionFg : sem.subtle}>{pad(o.label, outcome.labelW, 'left')}</Text>
                    {outcome.cols.map(c =>
                      // Same fixed 4-cell prob gutter as the headline (sub-rows
                      // never tag → 4 spaces) so sub-row %s right-align in-column.
                      c.key === 'prob' ? (
                        probCell(fmtProb(prob), c.w, false, on, t, sem)
                      ) : (
                        <Text color={c.key === 'ba' ? sem.faint : sem.subtle} key={c.key}>
                          {`${GUT}${pad(outCell(c.key), c.w, c.align)}`}
                        </Text>
                      )
                    )}
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
