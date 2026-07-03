import { Box, Text } from '@hermes/ink'

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
import { levelSparkline } from '../lib/forecastCharts.js'
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

const RANGE_LABEL: Record<PMHistoryRange, string> = { '1d': '1D', '1w': '1W', all: 'ALL' }

// The selection detail: de-vigged distribution as horizontal bars, the order
// book as compact bid/ask ladders (top 5), a history sparkline with a range
// toggle, and the market URL. Raw-vs-devig is labelled honestly and no
// liquidity is fabricated — a zero-liquidity outcome reads "no quote".
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
  const labelW = Math.max(8, Math.min(18, Math.floor(inner * 0.4)))
  const barW = Math.max(6, inner - labelW - 6)
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

  return (
    <Box flexDirection="column" flexShrink={0} marginLeft={1} overflow="hidden" width={width}>
      <Text bold color={t.color.text} wrap="truncate-end">
        {dist.title}
      </Text>
      <Text color={sem.subtle} wrap="truncate-end">
        {venueLabel(dist.venue)}
        {item.event.category ? ` · ${item.event.category}` : ''} · closes {fmtClose(dist.close_time)}
        {' · '}
        {fmtPMVol(dist.total_volume)}
      </Text>

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
                <Text color={noQuote ? sem.faint : sem.up}>{` ${pad(hbar(o.prob, barW), barW, 'left')}`}</Text>
                <Text color={noQuote ? sem.subtle : t.color.text}>{` ${pad(noQuote ? 'no quote' : fmtProb(o.prob), 5, 'right')}`}</Text>
              </Text>
            )
          })
        )}
      </Box>
      {outcomes.length > 1 ? (
        dist.normalized ? (
          <Text color={sem.subtle} wrap="truncate-end">
            {`raw YES mids sum ${fmtProb(rawSum)} · overround ${(dist.overround * 100).toFixed(1)}pp`}
          </Text>
        ) : (
          <Text color={sem.star} wrap="truncate-end">
            {dist.notes?.[0] ?? `raw prices — book sums to ${fmtProb(rawSum)} (not de-vigged)`}
          </Text>
        )
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

      {/* ── history sparkline ── */}
      <Box marginTop={1}>
        <Text color={sem.rule}>{'─'.repeat(inner)}</Text>
      </Box>
      <Text color={sem.heading} wrap="truncate-end">
        {'History '}
        <Text color={t.color.accent}>{RANGE_LABEL[historyRange]}</Text>
        <Text color={sem.subtle}>{'  (1/2/3 · 1D 1W ALL)'}</Text>
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
            <Text color={t.color.accent}>{url}</Text>
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
