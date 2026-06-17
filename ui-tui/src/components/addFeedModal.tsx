import { Box, Text } from '@hermes/ink'

import type { CatalogFeed } from '../content/newsFeedCatalog.js'
import { ensureFeedUrlScheme, feedHost } from '../lib/newsFeedStore.js'
import type { Theme } from '../theme.js'

// Presentational "Add a feed" modal. State + key handling live in NewsView
// (single useInput); this just paints the current view-model: a search line, a
// scrollable CATEGORIES rail to filter, a windowed RESULTS list with
// subscription checkboxes, and — when the query is a URL — an affordance to add
// it as a custom feed.

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

const window = <T,>(items: T[], sel: number, size: number): { items: T[]; start: number } => {
  const start = Math.max(0, Math.min(sel - Math.floor(size / 2), items.length - size))

  return { items: items.slice(Math.max(0, start), Math.max(0, start) + size), start: Math.max(0, start) }
}

const RIGHT_RULE = {
  borderBottom: false,
  borderLeft: false,
  borderStyle: 'single',
  borderTop: false
} as const

interface ClickEvent {
  cellIsBlank?: boolean
  stopPropagation?: () => void
}

export interface AddFeedModalProps {
  categories: string[]
  category: string
  cols: number
  isSubscribed: (url: string) => boolean
  isUrlQuery: boolean
  onAddUrl: () => void
  onPickCategory: (category: string) => void
  onToggle: (feed: CatalogFeed) => void
  query: string
  resultSel: number
  results: CatalogFeed[]
  rows: number
  subscribedCount: number
  t: Theme
}

export function AddFeedModal({
  categories,
  category,
  cols,
  isSubscribed,
  isUrlQuery,
  onAddUrl,
  onPickCategory,
  onToggle,
  query,
  resultSel,
  results,
  rows,
  subscribedCount,
  t
}: AddFeedModalProps) {
  const modalW = Math.max(54, Math.min(cols - 4, 112))
  const modalH = Math.max(14, Math.min(rows - 4, 38))
  const inner = modalW - 6 // border (2) + paddingX (4)

  // Reserve rows for chrome (title, search, rule, url/rule, footer + paddings).
  const bodyRows = Math.max(4, modalH - 9)

  const railWidth = 18
  const resultWidth = Math.max(20, inner - railWidth - 1)

  const catIdx = Math.max(0, categories.indexOf(category))
  const cats = window(categories, catIdx, bodyRows)
  const res = window(results, resultSel, bodyRows)

  const click = (run: () => void) => (event: ClickEvent) => {
    if (event.cellIsBlank) {
      return
    }

    event.stopPropagation?.()
    run()
  }

  return (
    <Box alignItems="center" flexGrow={1} justifyContent="center" minHeight={0}>
      <Box
        borderColor={t.color.accent}
        borderStyle="round"
        flexDirection="column"
        height={modalH}
        paddingX={2}
        paddingY={1}
        width={modalW}
      >
        {/* Title + counters */}
        <Box flexShrink={0} justifyContent="space-between">
          <Text bold color={t.color.primary}>
            Add a feed
          </Text>
          <Text color={t.color.muted}>
            <Text color={t.color.accent}>{subscribedCount}</Text> subscribed ·{' '}
            <Text color={t.color.text}>{results.length}</Text> {results.length === 1 ? 'match' : 'matches'}
          </Text>
        </Box>

        {/* Search line */}
        <Box flexShrink={0} marginTop={1}>
          <Text color={t.color.muted}>{'🔎 '}</Text>
          <Text color={t.color.text}>{query}</Text>
          <Text color={t.color.text} inverse>
            {' '}
          </Text>
          {!query ? (
            <Text color={t.color.muted}> search feeds, paste an RSS URL, or pick a category…</Text>
          ) : null}
        </Box>

        <Box flexShrink={0} marginTop={1}>
          <Text color={t.color.border}>{'─'.repeat(inner)}</Text>
        </Box>

        {/* Body: CATEGORIES rail | RESULTS list */}
        <Box flexDirection="row" flexGrow={1} minHeight={0}>
          <Box {...RIGHT_RULE} borderColor={t.color.border} flexDirection="column" flexShrink={0} overflow="hidden" paddingRight={1} width={railWidth}>
            <Text bold color={t.color.label}>
              CATEGORIES
            </Text>
            {cats.items.map((cat, i) => {
              const active = cats.start + i === catIdx

              return (
                <Box key={cat} onClick={click(() => onPickCategory(cat))} width="100%">
                  <Text color={active ? t.color.accent : t.color.muted} wrap="truncate-end">
                    {active ? '▸ ' : '  '}
                    {cat}
                  </Text>
                </Box>
              )
            })}
          </Box>

          <Box flexDirection="column" flexGrow={1} marginLeft={1} minWidth={0} overflow="hidden">
            {results.length === 0 ? (
              <Text color={t.color.muted} wrap="truncate-end">
                {isUrlQuery
                  ? 'Press ⏎ to add this URL as a custom feed.'
                  : 'No feeds match — try another word or paste an RSS URL.'}
              </Text>
            ) : (
              res.items.map((feed, i) => {
                const idx = res.start + i
                const on = idx === resultSel
                const subscribed = isSubscribed(feed.url)
                const tag = truncate(feed.category, 11).padEnd(11)
                // marker(2) + checkbox(3) + space + title + space + tag(11) +
                // space + host(≤14) must stay < resultWidth or the row wraps.
                const titleRoom = Math.max(10, resultWidth - 11 - 14 - 8)

                return (
                  <Box key={`${feed.url}:${idx}`} onClick={click(() => onToggle(feed))} width="100%">
                    <Text color={on ? t.color.primary : t.color.border}>{on ? '▸ ' : '  '}</Text>
                    <Text bold color={subscribed ? t.color.ok : t.color.muted}>
                      {subscribed ? '[✓]' : '[ ]'}
                    </Text>
                    <Text color={on ? t.color.text : t.color.label}>
                      {' '}
                      {truncate(feed.title, titleRoom).padEnd(titleRoom)}
                    </Text>
                    <Text color={t.color.muted}> {tag}</Text>
                    <Text color={t.color.border} wrap="truncate-end">
                      {' '}
                      {truncate(feedHost(feed.url), 14)}
                    </Text>
                  </Box>
                )
              })
            )}
          </Box>
        </Box>

        {/* Custom-URL affordance / rule */}
        {isUrlQuery ? (
          <Box flexShrink={0} onClick={click(onAddUrl)}>
            <Text color={t.color.ok}>{'⏎ '}</Text>
            <Text color={t.color.text} wrap="truncate-end">
              add <Text color={t.color.accent}>{truncate(ensureFeedUrlScheme(query), inner - 8)}</Text>
            </Text>
          </Box>
        ) : (
          <Box flexShrink={0}>
            <Text color={t.color.border}>{'─'.repeat(inner)}</Text>
          </Box>
        )}

        {/* Footer keys */}
        <Box flexShrink={0} marginTop={1}>
          <Text color={t.color.muted} wrap="truncate-end">
            type to search · ↑↓ move · ⏎ {isUrlQuery ? 'add URL' : 'subscribe/unsubscribe'} · Tab/←→ category · Esc done
          </Text>
        </Box>
      </Box>
    </Box>
  )
}
