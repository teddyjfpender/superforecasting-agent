import { Box, Text } from '@hermes/ink'

import { levelSparkline } from '../lib/forecastCharts.js'
import {
  fmtCents,
  fmtClose,
  fmtPMVol,
  fmtProb,
  fmtProb1,
  type PMHistoryPointDTO,
  type PMHistoryRange,
  type PMListItem,
  type PMOrderBookDTO,
  venueLabel
} from '../lib/pmData.js'
import { hbar } from '../lib/sparkline.js'
import { pad, semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

interface PMDetailProps {
  book: null | PMOrderBookDTO
  bookLabel: string
  history: PMHistoryPointDTO[]
  historyRange: PMHistoryRange
  item: null | PMListItem
  keyHint: null | string
  selectedMarketId: null | string
  streaming: boolean
  t: Theme
  width: number
}

const RANGES: { key: PMHistoryRange; label: string }[] = [
  { key: '1d', label: '1D' },
  { key: '1w', label: '1W' },
  { key: 'all', label: 'ALL' }
]

// Greedy word-wrap to at most `max` lines; a title that overflows gets a
// trailing ellipsis on the last line rather than the whole thing truncating to
// a single '…'-clipped row.
const wrapLines = (text: string, width: number, max: number): string[] => {
  const words = (text || '').split(/\s+/).filter(Boolean)
  const lines: string[] = []
  let cur = ''

  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w

    if (next.length > width && cur) {
      lines.push(cur)
      cur = w

      if (lines.length === max) {
        break
      }
    } else {
      cur = next
    }
  }

  if (lines.length < max && cur) {
    lines.push(cur)
  }

  const consumed = lines.join(' ').length

  if (consumed < (text || '').trim().length && lines.length) {
    const last = lines[lines.length - 1]
    lines[lines.length - 1] = last.length >= width ? `${last.slice(0, Math.max(0, width - 1))}…` : `${last}…`
  }

  return lines
}

// Middle-ellipsize a URL so the host AND the tail (event slug) both stay legible:
// "https://polymarket.com/…/nba-champion-2026".
const midEllipsis = (s: string, width: number): string => {
  if (s.length <= width) {
    return s
  }

  if (width <= 1) {
    return '…'
  }

  const keep = width - 1
  const head = Math.ceil(keep / 2)
  const tail = Math.floor(keep / 2)

  return `${s.slice(0, head)}…${s.slice(s.length - tail)}`
}

// The selection detail (a right side pane, matching the quote-instrument detail
// surface): de-vigged distribution as horizontal bars, the order book as compact
// bid/ask ladders (top 5), a history sparkline with a range toggle, and the
// market URL. Raw-vs-devig is labelled honestly and no liquidity is fabricated —
// a zero-liquidity outcome reads "no quote", never a percentage.
export function PredictionMarketDetail({
  book,
  bookLabel,
  history,
  historyRange,
  item,
  keyHint,
  selectedMarketId,
  streaming,
  t,
  width
}: PMDetailProps) {
  const sem = semantics(t)
  const inner = Math.max(14, width - 2)

  if (!item) {
    return (
      <Box flexDirection="column" flexShrink={0} marginLeft={1} width={width}>
        <Text color={sem.subtle}>Select a market to see its distribution, book, and history.</Text>
      </Box>
    )
  }

  const dist = item.distribution
  const outcomes = dist.outcomes ?? []
  // Fixed label + value columns; the bar absorbs the slack. The value column is
  // wide enough for "no quote" (8) so a percentage NEVER truncates to "5…".
  const valueW = 8
  const labelW = Math.max(8, Math.min(18, Math.floor(inner * 0.4)))
  const barW = Math.max(6, inner - 2 - labelW - 1 - 1 - valueW)
  // The raw YES mids sum to (1 + overround); state it honestly next to the bars.
  const rawSum = outcomes.reduce((acc, o) => acc + (o.raw_prob ?? 0), 0)

  const bids = (book?.bids ?? []).slice(0, 5)
  const asks = (book?.asks ?? []).slice(0, 5)
  const ladderColW = Math.max(6, Math.floor((inner - 3) / 2))

  // Probabilities render on a FIXED 0..1 scale (matching forecastCharts), so a
  // market that barely moved reads as barely moved — never a full-height swing
  // from min–max auto-scaling.
  const spark =
    history.length >= 2 ? levelSparkline(history.slice(-inner).map(p => p.p), { yMax: 1, yMin: 0 }) : ''

  const lastP = history.length ? history[history.length - 1].p : null
  const url = dist.url || item.event.url
  const titleLines = wrapLines(dist.title, inner, 2)

  // The honest raw-vs-devig note, as ONE muted line.
  const note =
    outcomes.length > 1
      ? dist.normalized
        ? `raw YES mids sum ${fmtProb(rawSum)} · overround ${(dist.overround * 100).toFixed(1)}pp`
        : dist.notes?.[0] ?? `raw prices — book sums to ${fmtProb(rawSum)} (not de-vigged)`
      : ''

  return (
    <Box flexDirection="column" flexShrink={0} marginLeft={1} overflow="hidden" width={width}>
      {titleLines.map((line, i) => (
        <Text bold color={t.color.text} key={i} wrap="truncate-end">
          {line}
        </Text>
      ))}
      <Text color={sem.subtle} wrap="truncate-end">
        {venueLabel(dist.venue)}
        {item.event.category ? ` · ${item.event.category}` : ''} · closes {fmtClose(dist.close_time)}
        {' · '}
        {fmtPMVol(dist.total_volume)}
      </Text>

      {/* Colour-coded direction reading. A binary market states its YES / NO pair
          (YES success, NO danger); a categorical event states once that the bars
          are YES-side prices (each outcome label IS its own direction). yes_mid is
          honest — a one-sided book yields a null YES, so NO is left blank too. */}
      {dist.binary ? (
        (() => {
          const yesP = dist.headline.top_prob ?? outcomes[0]?.prob ?? null
          const noP = yesP === null || yesP === undefined ? null : 1 - yesP

          return (
            <Text wrap="truncate-end">
              <Text bold color={sem.up}>
                {'YES '}
              </Text>
              <Text color={t.color.text}>{fmtProb(yesP)}</Text>
              <Text color={sem.subtle}>{'    '}</Text>
              <Text bold color={sem.down}>
                {'NO '}
              </Text>
              <Text color={t.color.text}>{fmtProb(noP)}</Text>
            </Text>
          )
        })()
      ) : outcomes.length > 1 ? (
        <Text color={sem.subtle}>prices are YES-side</Text>
      ) : null}

      {/* ── distribution bars (de-vigged) ── */}
      <Box marginTop={1}>
        <Text color={sem.heading}>Distribution</Text>
        <Text color={sem.subtle}>{dist.normalized ? '  de-vigged' : '  raw prices'}</Text>
      </Box>
      <Box flexDirection="column">
        {outcomes.length === 0 ? (
          <Text color={sem.subtle}>no priced outcomes</Text>
        ) : (
          outcomes.slice(0, 10).map(o => {
            const on = o.market_id === selectedMarketId
            const noQuote = o.raw_prob === 0 && o.yes_bid === null && o.yes_ask === null

            return (
              <Text key={o.market_id} wrap="truncate-end">
                <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
                <Text bold={on} color={on ? sem.selectionFg : t.color.label}>
                  {pad(o.label, labelW, 'left')}
                </Text>
                <Text color={noQuote ? sem.faint : sem.up}>{` ${pad(hbar(o.prob, barW), barW, 'left')} `}</Text>
                <Text color={noQuote ? sem.subtle : t.color.text}>{pad(noQuote ? 'no quote' : fmtProb(o.prob), valueW, 'right')}</Text>
              </Text>
            )
          })
        )}
      </Box>
      {note ? (
        <Text color={dist.normalized ? sem.subtle : sem.star} wrap="truncate-end">
          {note}
        </Text>
      ) : null}

      {/* ── order book ── */}
      <Box marginTop={1}>
        <Text color={sem.rule}>{'─'.repeat(inner)}</Text>
      </Box>
      <Text color={sem.heading} wrap="truncate-end">
        {'Order book · '}
        <Text color={t.color.text}>{bookLabel}</Text>
      </Text>
      {bids.length === 0 && asks.length === 0 ? (
        <Text color={sem.subtle}>{selectedMarketId ? 'no resting orders' : 'select an outcome'}</Text>
      ) : (
        <Box flexDirection="column">
          <Text wrap="truncate-end">
            <Text color={sem.up}>{pad('BID  size', ladderColW, 'left')}</Text>
            <Text color={sem.subtle}>{'   '}</Text>
            <Text color={sem.down}>{pad('ASK  size', ladderColW, 'left')}</Text>
          </Text>
          {Array.from({ length: Math.max(bids.length, asks.length) }).map((_, i) => {
            const b = bids[i]
            const a = asks[i]
            const bidCell = b ? `${pad(fmtCents(b.price), 4, 'left')} ${pad(fmtPMVol(b.size), ladderColW - 5, 'right')}` : ''
            const askCell = a ? `${pad(fmtCents(a.price), 4, 'left')} ${pad(fmtPMVol(a.size), ladderColW - 5, 'right')}` : ''

            return (
              <Text key={i} wrap="truncate-end">
                <Text color={b ? t.color.text : sem.faint}>{pad(bidCell, ladderColW, 'left')}</Text>
                <Text color={sem.subtle}>{'   '}</Text>
                <Text color={a ? t.color.text : sem.faint}>{pad(askCell, ladderColW, 'left')}</Text>
              </Text>
            )
          })}
          <Text color={sem.subtle} wrap="truncate-end">
            {`mid ${fmtProb1(book?.mid ?? null)}${streaming ? ' · live' : ''}`}
          </Text>
        </Box>
      )}

      {/* ── history sparkline · range chips rendered like the app's other toggles ── */}
      <Box marginTop={1}>
        <Text color={sem.rule}>{'─'.repeat(inner)}</Text>
      </Box>
      <Text wrap="truncate-end">
        <Text color={sem.heading}>{'History  '}</Text>
        {RANGES.map((r, i) => (
          <Text color={r.key === historyRange ? t.color.accent : sem.subtle} key={r.key}>
            {i > 0 ? ' ' : ''}
            {r.key === historyRange ? `[${r.label}]` : ` ${r.label} `}
          </Text>
        ))}
      </Text>
      {spark ? (
        <Text color={sem.up} wrap="truncate-end">
          {spark}
          <Text color={sem.subtle}>{`  ${fmtProb1(lastP)}`}</Text>
        </Text>
      ) : (
        <Text color={sem.subtle}>not enough history</Text>
      )}

      {url ? (
        <Box marginTop={1}>
          <Text color={sem.subtle} wrap="truncate-end">
            {'⏎ open · '}
            <Text color={t.color.accent}>{midEllipsis(url, Math.max(12, inner - 9))}</Text>
          </Text>
        </Box>
      ) : null}

      {keyHint ? (
        <Box marginTop={1}>
          <Text color={sem.star} wrap="wrap">
            {keyHint}
          </Text>
        </Box>
      ) : null}
    </Box>
  )
}
