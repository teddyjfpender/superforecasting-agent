import { useStore } from '@nanostores/react'
import { Box, Text, useInput, useStdout } from '@superforecasting/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import { $globalModal, openHelpOverlay, patchOverlayState } from '../app/overlayStore.js'
import type { CatalogFeed } from '../content/newsFeedCatalog.js'
import { FEED_CATEGORIES } from '../content/newsFeedCatalog.js'
import type { GatewayClient } from '../gatewayClient.js'
import { type FieldSpec, rankItems } from '../lib/fuzzyRank.js'
import { statusGlyph } from '../lib/icons.js'
import { type ArticleCache, loadArticleCache, pruneArticleCache, saveArticleCache } from '../lib/newsFeedCache.js'
import { type Article, fetchFeeds } from '../lib/newsFeedFetch.js'
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
import { nextProviderColor, providerColor } from '../lib/newsProviderColor.js'
import { loadProviderColors, type ProviderColors, saveProviderColors } from '../lib/newsProviderColorStore.js'
import { openExternalUrl } from '../lib/openExternalUrl.js'
import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { AddFeedModal } from './addFeedModal.js'
import { type FooterChip, FooterChips } from './footerChips.js'

export const openNewsView = () => patchOverlayState({ news: true })
export const closeNewsView = () => patchOverlayState({ news: false })

// News — live RSS feeds with quick reading. Press `a` to manage subscriptions
// (catalog + search + paste URL); feeds are fetched and parsed in the TUI's
// Node runtime, so the article list + reader fill in automatically. Panes are
// separated by thin vertical rules with an explicit height so nothing reflows.

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

// Short, recognizable provider/brand from a feed title: the part before the
// first " - / | — : " separator (so "CNBC - Top News" → "CNBC", "MarketWatch -
// Top Stories" → "MarketWatch"), trimmed to a fixed column width.
const PROVIDER_WIDTH = 12

const providerName = (feedTitle: string): string => {
  const brand = feedTitle.split(/\s+[-|—:·]\s+/)[0]?.trim() || feedTitle

  return truncate(brand, PROVIDER_WIDTH).padEnd(PROVIDER_WIDTH)
}

const ALL_FEEDS = 'All feeds'
const STALE_MS = 10 * 60 * 1000

const relTime = (ms: number): string => {
  if (!ms) {
    return ''
  }

  const diff = Date.now() - ms

  if (diff < 0) {
    return 'soon'
  }

  const m = Math.floor(diff / 60_000)

  if (m < 1) {
    return 'just now'
  }

  if (m < 60) {
    return `${m}m`
  }

  const h = Math.floor(m / 60)

  if (h < 24) {
    return `${h}h`
  }

  const d = Math.floor(h / 24)

  if (d < 7) {
    return `${d}d`
  }

  return new Date(ms).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
}

interface NewsViewProps {
  // Gateway client for the semantic-search RPC. Optional so the view renders
  // standalone (e.g. in tests) — search is simply disabled when absent.
  gw?: GatewayClient
  // A `/news <query>` argument: run this semantic search once articles load.
  initialQuery?: null | string
  onClose: () => void
  t: Theme
}

// Field weights for the article fuzzy filter: a title hit dominates a source or
// summary hit, but all three contribute so intent words still surface articles.
const NEWS_SEARCH_FIELDS: FieldSpec<Article>[] = [
  { get: a => a.title, weight: 1 },
  { get: a => a.feedTitle, weight: 0.5 },
  { get: a => a.summary, weight: 0.3 }
]

export function NewsView({ gw, initialQuery, onClose, t }: NewsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24
  // Go inert while the Ctrl+K palette / `?` cheat-sheet stacks above the view.
  const globalModal = useStore($globalModal)

  const [subscribed, setSubscribed] = useState<SubscribedFeed[]>(() => loadSubscribedFeeds())
  const [source, setSource] = useState(0)
  const [sel, setSel] = useState(0)
  const [tick, setTick] = useState(0)
  const [articles, setArticles] = useState<Article[]>([])
  const [fetching, setFetching] = useState(false)

  // Add-feed modal state.
  const [adding, setAdding] = useState(false)
  const [providerColors, setProviderColors] = useState<ProviderColors>(() => loadProviderColors())
  const [query, setQuery] = useState('')
  const [modalCat, setModalCat] = useState(ALL_CATEGORY)
  const [modalSel, setModalSel] = useState(0)
  const [flash, setFlash] = useState('')

  // INSTANT client-side fuzzy search over the loaded articles. `/` (or
  // `/news <query>`) opens a top-row search bar that live-filters + ranks by
  // relevance with NO RPC / NO LLM — so it's immediate (the old gateway rerank
  // awaited a 25s-timeout LLM call on submit, which made search feel broken).
  // `searchMode` just routes keystrokes to the bar; the filtered list is derived.
  const [searchMode, setSearchMode] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const initialRanRef = useRef(false)

  const cacheRef = useRef<ArticleCache>(loadArticleCache())
  const inflightRef = useRef(false)
  const aliveRef = useRef(true)

  useEffect(() => {
    // Reset on (re)mount — not just initial — so a remount re-enables the
    // async-safe setState guard that the cleanup turns off.
    aliveRef.current = true
    const id = setInterval(() => setTick(value => value + 1), 600)

    return () => {
      clearInterval(id)
      aliveRef.current = false
    }
  }, [])

  const subscribedUrls = useMemo(() => new Set(subscribed.map(f => normalizeFeedUrl(f.url))), [subscribed])
  const isSubscribed = (url: string) => subscribedUrls.has(normalizeFeedUrl(url))

  const categoryByUrl = useMemo(() => {
    const m = new Map<string, string>()

    for (const f of subscribed) {
      m.set(normalizeFeedUrl(f.url), f.category)
    }

    return m
  }, [subscribed])

  const sources = useMemo(() => {
    const cats = [...new Set(subscribed.map(f => f.category))].sort((a, b) => a.localeCompare(b))

    return [ALL_FEEDS, ...cats]
  }, [subscribed])

  const activeSource = sources[Math.min(source, sources.length - 1)] ?? ALL_FEEDS

  // Aggregate the cached articles for the currently-subscribed feeds.
  const rebuild = () => {
    if (!aliveRef.current) {
      return
    }

    const out: Article[] = []

    for (const f of subscribed) {
      const entry = cacheRef.current[normalizeFeedUrl(f.url)]

      if (entry?.articles?.length) {
        out.push(...entry.articles)
      }
    }

    out.sort((a, b) => b.publishedAt - a.publishedAt)
    setArticles(out)
  }

  // Fetch feeds that are missing or stale (or everything, when forced).
  const refresh = async (force: boolean) => {
    if (inflightRef.current) {
      return
    }

    const targets = subscribed.filter(f => {
      const entry = cacheRef.current[normalizeFeedUrl(f.url)]

      return force || !entry || Date.now() - entry.fetchedAt > STALE_MS
    })

    if (targets.length === 0) {
      rebuild()

      return
    }

    inflightRef.current = true

    if (aliveRef.current) {
      setFetching(true)
    }

    await fetchFeeds(
      targets.map(f => ({ title: f.title, url: f.url })),
      (url, result) => {
        cacheRef.current[normalizeFeedUrl(url)] = {
          articles: result.articles,
          error: result.error ?? undefined,
          fetchedAt: Date.now()
        }
        rebuild()
      }
    )

    saveArticleCache(cacheRef.current)
    inflightRef.current = false

    if (aliveRef.current) {
      setFetching(false)
    }
  }

  // Whenever the subscription set changes (and on first mount): prune cached
  // articles for feeds you no longer follow so the cache can't grow without
  // bound, then rebuild + refresh.
  useEffect(() => {
    const keep = new Set(subscribed.map(f => normalizeFeedUrl(f.url)))
    cacheRef.current = pruneArticleCache(cacheRef.current, { keep, maxAgeMs: 30 * 24 * 60 * 60 * 1000 })
    saveArticleCache(cacheRef.current)
    rebuild()
    void refresh(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subscribed])

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
      persist([{ addedAt: Date.now(), category: feed.category, title: feed.title, url: feed.url }, ...subscribed])
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

  // Per-source colour: resolve, and cycle the highlighted feed's provider hue.
  const colorFor = (feedTitle: string) => providerColor(providerName(feedTitle), t, providerColors)

  const cycleColorFor = (feedTitle: string) => {
    const name = providerName(feedTitle)
    const next = { ...providerColors, [providerName(feedTitle).trim().toLowerCase()]: nextProviderColor(name, t, colorFor(feedTitle)) }
    setProviderColors(next)
    saveProviderColors(next)
    setFlash(`colour set · ${name.trim()}`)
  }

  const cycleSelectedColor = () => {
    const feed = results[modalSel]

    if (feed) {
      cycleColorFor(feed.title)
    }
  }

  const feedArticles = useMemo(() => {
    if (activeSource === ALL_FEEDS) {
      return articles
    }

    return articles.filter(a => categoryByUrl.get(normalizeFeedUrl(a.feedUrl)) === activeSource)
  }, [articles, activeSource, categoryByUrl])

  // The live query (trimmed). The filter is active whenever this is non-empty,
  // whether or not the input bar still has focus (Enter commits + keeps it).
  const searchActive = searchInput.trim()

  // Ranked client-side filter over ALL loaded articles (not just the active
  // source) so search finds anything; recomputed instantly per keystroke.
  const searchResults = useMemo(
    () => (searchActive ? rankItems(articles, searchActive, NEWS_SEARCH_FIELDS).map(r => r.item) : null),
    [searchActive, articles]
  )

  // When a search is active, the ranked results replace the feed list.
  const visibleArticles = searchResults ?? feedArticles

  const clearSearch = () => {
    setSearchMode(false)
    setSearchInput('')
    setSel(0)
  }

  // `/news <query>` (or a query carried into the view) auto-runs once articles
  // are available — run it a single time per provided query.
  useEffect(() => {
    const q = (initialQuery ?? '').trim()

    if (q && !initialRanRef.current && articles.length > 0) {
      initialRanRef.current = true
      setSearchInput(q)
    }
     
  }, [initialQuery, articles.length])

  const openModal = () => {
    setAdding(true)
    setQuery('')
    setModalCat(ALL_CATEGORY)
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

      // Shift+Tab recolours the highlighted feed's provider (before plain Tab,
      // which switches category).
      if (key.tab && key.shift) {
        return cycleSelectedColor()
      }

      if (key.tab || key.rightArrow) {
        return cycleModalCat(1)
      }

      if (key.leftArrow) {
        return cycleModalCat(-1)
      }

      if (key.upArrow || key.wheelUp) {
        return setModalSel(i => Math.max(0, i - 1))
      }

      if (key.downArrow || key.wheelDown) {
        return setModalSel(i => Math.min(Math.max(0, results.length - 1), i + 1))
      }

      if (key.backspace || key.delete) {
        setModalSel(0)

        return setQuery(q => q.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          setModalSel(0)
          setQuery(q => q + printable)
        }
      }

      return
    }

    // Typing a semantic search query.
    if (searchMode) {
      if (key.escape) {
        setSearchMode(false)
        setSearchInput('')

        return
      }

      if (key.return) {
        // Filtering is already live; Enter just drops focus so ↑↓ navigate the
        // ranked results while the filter stays applied.
        return setSearchMode(false)
      }

      if (key.backspace || key.delete) {
        setSel(0)

        return setSearchInput(s => s.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          // Reset the cursor to the top match as the ranking shifts under typing.
          setSel(0)
          setSearchInput(s => s + printable)
        }
      }

      return
    }

    if (ch === 'q') {
      return onClose()
    }

    // `h` opens the unified Help modal — consistent on every view. Nav mode only
    // (the `adding` + `searchMode` text guards above already returned).
    if (ch === 'h') {
      return openHelpOverlay()
    }

    if (key.escape) {
      // Esc backs out of an active search first, then leaves the view.
      if (searchActive) {
        return clearSearch()
      }

      return onClose()
    }

    // `/` opens the instant fuzzy filter (keeps any current query to refine).
    if (ch === '/') {
      return setSearchMode(true)
    }

    if (ch === 'a') {
      return openModal()
    }

    if (ch === 'r') {
      setFlash('refreshing…')

      return void refresh(true)
    }

    if (key.return) {
      const article = visibleArticles[sel]
      const target = article?.link || article?.feedUrl

      if (target && openExternalUrl(ensureFeedUrlScheme(target))) {
        setFlash('opened in browser')
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

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setSel(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setSel(i => Math.min(Math.max(0, visibleArticles.length - 1), i + 1))
    }
  }, { isActive: !globalModal })

  const width = Math.max(48, cols - 4)
  const contentHeight = Math.max(8, termRows - 7)
  const sem = semantics(t)
  const hasFeeds = subscribed.length > 0
  const railWidth = Math.min(26, Math.max(20, Math.floor(width * 0.2)))
  // One screen row per article (single-line rows) below the pane label + gap.
  const listRows = Math.max(3, contentHeight - 2)
  const clampedSel = Math.min(sel, Math.max(0, visibleArticles.length - 1))
  const selectedArticle = visibleArticles[clampedSel]

  // Window the article list around the selection so scrolling stays visible.
  const listStart = Math.max(0, Math.min(clampedSel - Math.floor(listRows / 2), visibleArticles.length - listRows))
  const windowedArticles = visibleArticles.slice(Math.max(0, listStart), Math.max(0, listStart) + listRows)

  const statusWord = fetching ? 'fetching…' : hasFeeds ? 'idle' : 'no feeds'

  // Header is a single row. While typing a search the row becomes the input;
  // with an active search it appends a compact result indicator — neither adds a
  // line, so the footer/shortcuts never get pushed off-screen.
  const header = (
    <Box flexShrink={0} marginBottom={1}>
      {searchMode ? (
        <Text wrap="truncate-end">
          <Text bold color={t.color.primary}>
            NEWS
          </Text>
          <Text color={t.color.muted}>{'   '}</Text>
          <Text color={t.color.primary}>{'⌕ '}</Text>
          <Text color={t.color.text}>{searchInput}</Text>
          <Text color={t.color.primary} inverse>
            {' '}
          </Text>
          <Text color={t.color.muted}>{`   ${searchActive ? `${visibleArticles.length} matches · ` : ''}⏎ done · Esc clear`}</Text>
        </Text>
      ) : (
        <Text wrap="truncate-end">
          <Text bold color={t.color.primary}>
            NEWS
          </Text>
          <Text color={t.color.muted}>{'   '}</Text>
          <Text color={fetching ? sem.star : hasFeeds ? sem.up : sem.subtle}>
            {statusGlyph(fetching ? 'busy' : hasFeeds ? 'live' : 'idle', tick)}
          </Text>
          <Text color={t.color.muted}> {statusWord} · </Text>
          <Text color={t.color.text}>live RSS feeds</Text>
          <Text color={t.color.muted}>
            {' · '}
            {hasFeeds ? `${subscribed.length} feeds · ${articles.length} articles` : 'press a to add feeds'}
          </Text>
          {searchActive ? (
            <Text>
              <Text color={t.color.muted}>{'  ·  '}</Text>
              <Text color={t.color.primary}>{'⌕ '}</Text>
              <Text bold color={t.color.text}>
                {truncate(searchActive, 28)}
              </Text>
              <Text color={t.color.muted}>
                {` · ${visibleArticles.length}/${articles.length} · Esc clear`}
              </Text>
            </Text>
          ) : null}
        </Text>
      )}
    </Box>
  )

  // SOURCES rail — subscribed categories with article counts (filter).
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

          const count =
            src === ALL_FEEDS
              ? articles.length
              : articles.filter(a => categoryByUrl.get(normalizeFeedUrl(a.feedUrl)) === src).length

          return (
            <Box
              justifyContent="space-between"
              key={src}
              onClick={() => {
                if (adding || globalModal) {return}
                setSource(i)
                setSel(0)
              }}
              width="100%"
            >
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

  // ARTICLES list — headlines (browse), or a scaffold when empty.
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
        {visibleArticles.length ? <Text color={t.color.muted}>{`  (${visibleArticles.length})`}</Text> : null}
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {visibleArticles.length > 0 ? (
          // One contiguous line per article — title (bright/bold when selected)
          // then a dim "source · time" tail. Single-line rows avoid the diff
          // ghosting that two-line rows hit when the window scrolls.
          windowedArticles.map((article, i) => {
            const idx = listStart + i
            const on = idx === clampedSel
            // Fixed-width recency + provider prefixes so both stay visible (and
            // aligned) even when the headline is truncated.
            const when = (article.publishedAt ? relTime(article.publishedAt) : '·').padEnd(5)
            const provider = providerName(article.feedTitle)

            return (
              <Box key={`${article.feedUrl}:${idx}`} onClick={() => { if (!adding && !globalModal) {setSel(idx)} }} width="100%">
                <Text wrap="truncate-end">
                  <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
                  <Text color={sem.subtle}>{when} </Text>
                  <Text color={providerColor(provider, t, providerColors)}>{provider} </Text>
                  <Text bold={on} color={on ? sem.selectionFg : t.color.label}>
                    {article.title}
                  </Text>
                </Text>
              </Box>
            )
          })
        ) : searchActive && searchResults ? (
          <Text color={t.color.muted} wrap="wrap">
            {`No articles match “${truncate(searchActive, 40)}” — press Esc to clear or / to refine.`}
          </Text>
        ) : hasFeeds ? (
          <Text color={t.color.muted} wrap="wrap">
            {fetching
              ? 'Fetching articles…'
              : `No articles${activeSource === ALL_FEEDS ? '' : ` in ${activeSource}`} yet — feeds may be slow or unreachable. Press r to retry.`}
          </Text>
        ) : (
          <Box flexDirection="column">
            {Array.from({ length: Math.min(6, listRows) }, (_, r) => (
              <Text color={t.color.border} key={r} wrap="truncate-end">
                {'  '}
                {bar(22 + (r % 3) * 6)}
                <Text color={t.color.muted}>{`  ${bar(8)} · ${bar(3)}`}</Text>
              </Text>
            ))}
          </Box>
        )}
      </Box>
    </Box>
  )

  // READER pane — the selected article, or paragraph skeleton when empty.
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
      {selectedArticle ? (
        <Box flexDirection="column" marginTop={1}>
          <Text bold color={t.color.text} wrap="wrap">
            {selectedArticle.title}
          </Text>
          <Text color={t.color.muted} wrap="truncate-end">
            {selectedArticle.feedTitle}
            {selectedArticle.publishedAt ? ` · ${relTime(selectedArticle.publishedAt)}` : ''}
          </Text>
          {selectedArticle.summary ? (
            <Box marginTop={1}>
              <Text color={t.color.text} wrap="wrap">
                {truncate(selectedArticle.summary, 600)}
              </Text>
            </Box>
          ) : null}
          {selectedArticle.link ? (
            <Box marginTop={1}>
              <Text color={t.color.accent} wrap="truncate-end">
                {selectedArticle.link}
              </Text>
            </Box>
          ) : null}
          <Box marginTop={1}>
            <Text color={t.color.muted} wrap="wrap">
              Press Enter to open this article in your browser.
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
              {hasFeeds
                ? fetching
                  ? 'Fetching the latest articles…'
                  : 'Select an article on the left to read it here.'
                : 'No feeds yet. Press a to browse a catalog of quality RSS feeds, search them, or paste your own URL.'}
            </Text>
          </Box>
        </Box>
      )}
    </Box>
  )

  const chips: FooterChip[] = [
    { k: '↑↓', label: 'Browse' },
    { k: '/', label: 'Search', run: () => { setSearchMode(true); setSearchInput(searchActive) } },
    { k: '⇥', label: 'Source', run: () => { setSel(0); setSource(i => (i + 1) % sources.length) } },
    { k: '⏎', label: 'Open' },
    { k: 'a', label: 'Add feed', run: openModal },
    { k: 'r', label: 'Refresh', run: () => { setFlash('refreshing…'); void refresh(true) } },
    { k: 'h', label: 'Help', run: openHelpOverlay },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {/* The FooterChips are the ONE canonical shortcuts row (the always-on prose
          duplicate below them was removed). Only a transient flash survives, and
          only when there is something to say — never a second shortcuts row. */}
      <FooterChips chips={chips} disabled={adding || globalModal} t={t} />
      {flash ? (
        <Text color={t.color.accent} wrap="truncate-end">
          {flash}
        </Text>
      ) : null}
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      <Box flexDirection="row" flexShrink={0} height={contentHeight}>
        {rail}
        {list}
        {reader}
      </Box>
      {footer}
      {/* Body stays mounted; the overlay paints over it (its own absolute box).
          Body mouse handlers are gated while `adding` (rail/list onClick → no-op),
          and the keyboard is trapped by the `if (adding)` branch in useInput. */}
      {adding ? (
        <AddFeedModal
          categories={modalCategories}
          category={modalCat}
          cols={cols}
          isSubscribed={isSubscribed}
          isUrlQuery={isUrlQuery}
          onAddUrl={addUrlFeed}
          onCycleColor={feed => cycleColorFor(feed.title)}
          onPickCategory={cat => {
            setModalCat(cat)
            setModalSel(0)
          }}
          onToggle={toggleFeed}
          providerColorFor={feed => colorFor(feed.title)}
          query={query}
          results={results}
          resultSel={modalSel}
          rows={termRows}
          subscribedCount={subscribed.length}
          t={t}
        />
      ) : null}
    </Box>
  )
}
