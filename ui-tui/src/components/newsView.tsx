import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useMemo, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { CatalogFeed } from '../content/newsFeedCatalog.js'
import { FEED_CATEGORIES } from '../content/newsFeedCatalog.js'
import { ALL_CATEGORY, searchFeeds } from '../lib/newsFeedSearch.js'
import {
  ensureFeedUrlScheme,
  feedHost,
  isFeedUrl,
  loadSubscribedFeeds,
  normalizeFeedUrl,
  saveSubscribedFeeds,
  type SubscribedFeed
} from '../lib/newsFeedStore.js'
import { openExternalUrl } from '../lib/openExternalUrl.js'
import type { Theme } from '../theme.js'

import { AddFeedModal } from './addFeedModal.js'
import { type FooterChip, FooterChips } from './footerChips.js'

export const openNewsView = () => patchOverlayState({ news: true })
export const closeNewsView = () => patchOverlayState({ news: false })

// News — live RSS feeds with quick reading. The catalog + Add-feed modal are
// wired (press `a`); article fetching is the next step. Panes are separated by
// thin vertical rules and given an explicit height so the layout never reflows.

const bar = (n: number): string => '░'.repeat(Math.max(3, n))

const PARA_WIDTHS = [40, 44, 38, 42, 30, 44, 36]

const RIGHT_RULE = {
  borderBottom: false,
  borderLeft: false,
  borderStyle: 'single',
  borderTop: false
} as const

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

const ALL_FEEDS = 'All feeds'

interface NewsViewProps {
  onClose: () => void
  t: Theme
}

export function NewsView({ onClose, t }: NewsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  const [subscribed, setSubscribed] = useState<SubscribedFeed[]>(() => loadSubscribedFeeds())
  const [source, setSource] = useState(0)
  const [sel, setSel] = useState(0)
  const [tick, setTick] = useState(0)

  // Add-feed modal state.
  const [adding, setAdding] = useState(false)
  const [query, setQuery] = useState('')
  const [modalCat, setModalCat] = useState(ALL_CATEGORY)
  const [modalSel, setModalSel] = useState(0)
  const [flash, setFlash] = useState('')

  useEffect(() => {
    const id = setInterval(() => setTick(value => value + 1), 600)

    return () => clearInterval(id)
  }, [])

  // No real text cursor in this view — park it so it doesn't sit in the corner.
  useEffect(() => {
    stdout?.write('\x1b[?25l')

    return () => {
      stdout?.write('\x1b[?25h')
    }
  }, [stdout])

  const subscribedUrls = useMemo(
    () => new Set(subscribed.map(f => normalizeFeedUrl(f.url))),
    [subscribed]
  )

  const isSubscribed = (url: string) => subscribedUrls.has(normalizeFeedUrl(url))

  // Sources rail: "All feeds" + the categories present in the subscriptions.
  const sources = useMemo(() => {
    const cats = [...new Set(subscribed.map(f => f.category))].sort((a, b) => a.localeCompare(b))

    return [ALL_FEEDS, ...cats]
  }, [subscribed])

  const activeSource = sources[Math.min(source, sources.length - 1)] ?? ALL_FEEDS

  const visibleFeeds = useMemo(() => {
    const pool = activeSource === ALL_FEEDS ? subscribed : subscribed.filter(f => f.category === activeSource)

    return [...pool].sort((a, b) => b.addedAt - a.addedAt || a.title.localeCompare(b.title))
  }, [subscribed, activeSource])

  const modalCategories = useMemo(() => [ALL_CATEGORY, ...FEED_CATEGORIES], [])
  const results = useMemo(() => searchFeeds(query, modalCat), [query, modalCat])
  const isUrlQuery = isFeedUrl(query)

  const persist = (next: SubscribedFeed[]) => {
    setSubscribed(next)
    saveSubscribedFeeds(next)
  }

  const toggleFeed = (feed: CatalogFeed) => {
    const key = normalizeFeedUrl(feed.url)

    if (subscribedUrls.has(key)) {
      persist(subscribed.filter(f => normalizeFeedUrl(f.url) !== key))
      setFlash(`unsubscribed ${feed.title}`)
    } else {
      const entry: SubscribedFeed = {
        addedAt: Date.now(),
        category: feed.category,
        title: feed.title,
        url: feed.url
      }

      persist([entry, ...subscribed])
      setFlash(`subscribed ${feed.title}`)
    }
  }

  const addUrlFeed = () => {
    if (!isFeedUrl(query)) {
      return
    }

    const url = ensureFeedUrlScheme(query)
    const key = normalizeFeedUrl(url)

    if (subscribedUrls.has(key)) {
      setFlash('already subscribed')
      setQuery('')

      return
    }

    persist([{ addedAt: Date.now(), category: 'Custom', custom: true, title: feedHost(url), url }, ...subscribed])
    setFlash(`added ${feedHost(url)}`)
    setQuery('')
    setModalSel(0)
  }

  const closeModal = () => {
    setAdding(false)
    setQuery('')
    setModalSel(0)
  }

  const cycleModalCat = (dir: number) => {
    const i = modalCategories.indexOf(modalCat)
    const next = (i + dir + modalCategories.length) % modalCategories.length
    setModalCat(modalCategories[next])
    setModalSel(0)
  }

  useInput((ch, key) => {
    if (adding) {
      if (key.escape) {
        return closeModal()
      }

      if (key.return) {
        if (isUrlQuery) {
          return addUrlFeed()
        }

        const feed = results[modalSel]

        if (feed) {
          toggleFeed(feed)
        }

        return
      }

      if (key.tab || key.rightArrow) {
        return cycleModalCat(1)
      }

      if (key.leftArrow) {
        return cycleModalCat(-1)
      }

      if (key.upArrow) {
        return setModalSel(i => Math.max(0, i - 1))
      }

      if (key.downArrow) {
        return setModalSel(i => Math.min(Math.max(0, results.length - 1), i + 1))
      }

      if (key.backspace || key.delete) {
        setModalSel(0)

        return setQuery(q => q.slice(0, -1))
      }

      // Printable input (including pasted URLs) feeds the search box.
      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          setModalSel(0)
          setQuery(q => q + printable)
        }
      }

      return
    }

    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (ch === 'a') {
      setAdding(true)
      setQuery('')
      setModalCat(ALL_CATEGORY)
      setModalSel(0)

      return
    }

    if (ch === 'r') {
      setSubscribed(loadSubscribedFeeds())
      setFlash('reloaded')

      return
    }

    if (key.return) {
      const feed = visibleFeeds[sel]

      if (feed && openExternalUrl(ensureFeedUrlScheme(feed.url))) {
        setFlash(`opened ${feedHost(feed.url)}`)
      }

      return
    }

    if (key.tab || key.rightArrow) {
      setSel(0)

      return setSource(i => (i + 1) % sources.length)
    }

    if (key.leftArrow) {
      setSel(0)

      return setSource(i => (i - 1 + sources.length) % sources.length)
    }

    if (key.upArrow || ch === 'k') {
      return setSel(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j') {
      return setSel(i => Math.min(Math.max(0, visibleFeeds.length - 1), i + 1))
    }
  })

  const width = Math.max(48, cols - 4)
  const contentHeight = Math.max(8, termRows - 7)
  const live = tick % 2 === 0
  const hasFeeds = subscribed.length > 0
  const railWidth = Math.min(26, Math.max(20, Math.floor(width * 0.2)))
  const listRows = Math.max(3, Math.floor((contentHeight - 2) / 2))
  const selectedFeed = visibleFeeds[Math.min(sel, Math.max(0, visibleFeeds.length - 1))]

  const header = (
    <Box flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          NEWS
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={live ? t.color.ok : t.color.muted}>●</Text>
        <Text color={t.color.muted}> {hasFeeds ? 'idle' : 'no feeds'} · </Text>
        <Text color={t.color.text}>live RSS feeds</Text>
        <Text color={t.color.muted}>
          {' · '}
          {hasFeeds ? `${subscribed.length} subscribed` : 'press a to add feeds'}
        </Text>
      </Text>
    </Box>
  )

  // SOURCES rail — categories of the subscribed feeds (filter).
  const rail = (
    <Box
      {...RIGHT_RULE}
      borderColor={t.color.border}
      flexDirection="column"
      flexShrink={0}
      height={contentHeight}
      overflow="hidden"
      paddingRight={1}
      width={railWidth}
    >
      <Text bold color={t.color.label}>
        SOURCES
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {sources.map((src, i) => {
          const isActive = i === source
          const count = src === ALL_FEEDS ? subscribed.length : subscribed.filter(f => f.category === src).length

          return (
            <Box justifyContent="space-between" key={src} onClick={() => { setSource(i); setSel(0) }} width="100%">
              <Text color={isActive ? t.color.accent : t.color.muted} wrap="truncate-end">
                {isActive ? '▸ ' : '  '}
                {src}
              </Text>
              <Text color={t.color.border}>{count || '—'}</Text>
            </Box>
          )
        })}
      </Box>
    </Box>
  )

  // ALL FEEDS / list — the subscribed feeds (browse), or a scaffold when empty.
  const list = (
    <Box
      {...RIGHT_RULE}
      borderColor={t.color.border}
      flexBasis={0}
      flexDirection="column"
      flexGrow={1}
      flexShrink={1}
      height={contentHeight}
      marginLeft={1}
      minWidth={0}
      overflow="hidden"
      paddingRight={1}
    >
      <Text bold color={t.color.label} wrap="truncate-end">
        {activeSource.toUpperCase()}
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {hasFeeds ? (
          visibleFeeds.slice(0, listRows).map((feed, i) => {
            const on = i === sel

            return (
              <Box flexDirection="column" key={`${feed.url}:${i}`} marginBottom={1} onClick={() => setSel(i)}>
                <Box width="100%">
                  <Text color={on ? t.color.accent : t.color.border}>{on ? '▸ ' : '  '}</Text>
                  <Text bold={on} color={on ? t.color.text : t.color.label} wrap="truncate-end">
                    {feed.title}
                  </Text>
                </Box>
                <Text color={t.color.muted} wrap="truncate-end">
                  {'   '}
                  {feed.category} · {feedHost(feed.url)}
                </Text>
              </Box>
            )
          })
        ) : (
          <Box flexDirection="column">
            {Array.from({ length: Math.min(6, listRows) }, (_, r) => (
              <Box flexDirection="column" key={r} marginBottom={1}>
                <Text color={t.color.border} wrap="truncate-end">
                  {'  '}
                  {bar(22 + (r % 3) * 6)}
                </Text>
                <Text color={t.color.muted} wrap="truncate-end">
                  {'   '}
                  {bar(8)} · {bar(3)}
                </Text>
              </Box>
            ))}
          </Box>
        )}
      </Box>
    </Box>
  )

  // READER pane — the selected feed's detail, or paragraph skeleton when empty.
  const reader = (
    <Box
      flexBasis={0}
      flexDirection="column"
      flexGrow={1}
      flexShrink={1}
      height={contentHeight}
      marginLeft={1}
      minWidth={0}
      overflow="hidden"
    >
      <Text bold color={t.color.label} wrap="truncate-end">
        READER
      </Text>
      {hasFeeds && selectedFeed ? (
        <Box flexDirection="column" marginTop={1}>
          <Text bold color={t.color.text} wrap="truncate-end">
            {selectedFeed.title}
          </Text>
          <Text color={t.color.muted} wrap="truncate-end">
            {selectedFeed.category} · {feedHost(selectedFeed.url)}
          </Text>
          <Box marginTop={1}>
            <Text color={t.color.accent} wrap="truncate-end">
              {selectedFeed.url}
            </Text>
          </Box>
          <Box marginTop={1}>
            <Text color={t.color.muted} wrap="wrap">
              Articles will appear here once feeds are fetched. Press Enter to open this source in your browser.
            </Text>
          </Box>
        </Box>
      ) : (
        <Box flexDirection="column" marginTop={1}>
          <Box flexDirection="column">
            {PARA_WIDTHS.map((w, i) => (
              <Text color={t.color.border} key={i} wrap="truncate-end">
                {bar(w)}
              </Text>
            ))}
          </Box>
          <Box marginTop={1}>
            <Text color={t.color.muted} wrap="wrap">
              No feeds yet. Press a to browse a catalog of quality RSS feeds, search them, or paste your own URL.
            </Text>
          </Box>
        </Box>
      )}
    </Box>
  )

  const chips: FooterChip[] = [
    { k: '↑↓', label: 'Browse' },
    { k: '⇥', label: 'Source', run: () => { setSel(0); setSource(i => (i + 1) % sources.length) } },
    { k: '⏎', label: 'Open' },
    { k: 'a', label: 'Add feed', run: () => { setAdding(true); setQuery(''); setModalCat(ALL_CATEGORY); setModalSel(0) } },
    { k: 'r', label: 'Refresh', run: () => { setSubscribed(loadSubscribedFeeds()); setFlash('reloaded') } },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} t={t} />
      <Text color={t.color.muted} wrap="truncate-end">
        {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
        ↑↓/jk browse · Tab/←→ source · Enter open · a add feed · r refresh · Esc/q close
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {adding ? (
        <AddFeedModal
          categories={modalCategories}
          category={modalCat}
          cols={cols}
          isSubscribed={isSubscribed}
          isUrlQuery={isUrlQuery}
          onAddUrl={addUrlFeed}
          onPickCategory={cat => { setModalCat(cat); setModalSel(0) }}
          onToggle={toggleFeed}
          query={query}
          results={results}
          resultSel={modalSel}
          rows={termRows}
          subscribedCount={subscribed.length}
          t={t}
        />
      ) : (
        <Box flexDirection="row" flexShrink={0} height={contentHeight}>
          {rail}
          {list}
          {reader}
        </Box>
      )}
      {footer}
    </Box>
  )
}
