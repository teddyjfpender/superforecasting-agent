import { useStore } from '@nanostores/react'
import { Box, ScrollBox, type ScrollBoxHandle, Text, useInput } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import { $globalModal } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import { catalogSeries, deskConfig } from '../lib/dataDesk.js'
import { searchCatalog } from '../lib/marketSearch.js'
import type { MarketConfig } from '../lib/marketStore.js'
import type {
  DeskEdit,
  DeskPreview,
  MarketCatalogResponse,
  MarketDiscoveryHit,
  MarketProviderStatus,
  Quote
} from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'

interface AddProviderModalProps {
  cols: number
  gw?: GatewayClient
  initial: MarketConfig
  onCancel: () => void
  onSaved: (config: MarketConfig) => void
  onSearchSymbols?: () => void
  rows: number
  sessionId?: string
  t: Theme
}

const tabs = ['Starter sets', 'Browse data', 'Sources'] as const

export function AddProviderModal({ cols, gw, onCancel, onSaved, rows, sessionId = '', t }: AddProviderModalProps) {
  const globalModal = useStore($globalModal)
  const scrollRef = useRef<ScrollBoxHandle | null>(null)
  const generation = useRef(0)
  const [data, setData] = useState<MarketCatalogResponse | null>(null)
  const [tab, setTab] = useState(0)
  const [index, setIndex] = useState(0)
  const [region, setRegion] = useState(0)
  const [category, setCategory] = useState(0)
  const [kind, setKind] = useState(0)
  const [country, setCountry] = useState(0)
  const [source, setSource] = useState(0)
  const [filterFocus, setFilterFocus] = useState<number | null>(null)
  const [remote, setRemote] = useState<MarketDiscoveryHit[]>([])
  const [picked, setPicked] = useState<Record<string, MarketDiscoveryHit>>({})
  const [searchStatus, setSearchStatus] = useState<MarketProviderStatus[]>([])
  const [searching, setSearching] = useState(false)
  const [searchAttempt, setSearchAttempt] = useState(0)
  const [previewIndex, setPreviewIndex] = useState(0)
  const [latest, setLatest] = useState<Record<string, Quote>>({})
  const [latestStatus, setLatestStatus] = useState<Record<string, string>>({})
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [preview, setPreview] = useState<DeskPreview | null>(null)
  const [edit, setEdit] = useState<DeskEdit | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    generation.current += 1
    setData(null)
    setBusy(false)
    setError('')
    setEdit(null)
    setPreview(null)
    setSelected(new Set())
    setLatest({})
    setLatestStatus({})

    if (!gw) {
      setError('Connect to the gateway to configure this data desk.')

      return
    }

    gw.request('market.catalog', {})
      .then(result => {
        if (alive) {
          setData(result)
        }
      })
      .catch(() => {
        if (alive) {
          setError('Unable to load the data catalog. Close and reopen Add data to retry.')
        }
      })

    return () => {
      alive = false
      generation.current += 1
    }
  }, [gw])

  const catalog = data?.catalog

  const availableCategories =
    catalog?.categories.filter(item => catalog.series.some(series => series.category === item.id)) ?? []

  const regions = catalog?.regions ?? []
  const kinds = [...new Set(catalog?.series.map(series => series.kind) ?? [])]

  const countries =
    catalog?.countries.filter(country => catalog.series.some(series => series.country === country.id)) ?? []

  const regionFilter = regions[region - 1]
  const categoryFilter = availableCategories[category - 1]

  const sourceFilter = catalog?.providers[source - 1]
  const countryFilter = countries[country - 1]?.id ?? ''
  const kindFilter = kinds[kind - 1] ?? ''
  const regionId = regionFilter?.id ?? ''
  const categoryId = categoryFilter?.id ?? ''
  const sourceId = sourceFilter?.id ?? ''

  useEffect(() => {
    let alive = true
    setRemote([])
    setSearchStatus([])
    setSearching(false)

    if (tab !== 1 || !gw || query.trim().length < 2) {
      return
    }

    setSearching(true)

    const timer = setTimeout(() => {
      void gw
        .request('market.discover', {
          query: query.trim().slice(0, 200),
          provider: sourceId,
          country: countryFilter,
          region: regionId,
          category: categoryId,
          kind: kindFilter
        })
        .then(result => {
          if (!alive) {
            return
          }

          setRemote(result.results)
          setSearchStatus(result.statuses)
        })
        .catch(() => {
          if (alive) {
            setSearchStatus([
              {
                provider: 'discovery',
                status: 'unavailable',
                message: 'Live search unavailable; catalog matches remain available.',
                retry_after: null
              }
            ])
          }
        })
        .finally(() => {
          if (alive) {
            setSearching(false)
          }
        })
    }, 300)

    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [gw, tab, query, sourceId, countryFilter, regionId, categoryId, kindFilter, searchAttempt])

  const localIds =
    query.trim() && catalog
      ? new Map(searchCatalog(query, catalogSeries(catalog)).map((item, position) => [item.catalog_id, position]))
      : null

  const local = (catalog?.series ?? [])
    .filter(series => !localIds || localIds.has(series.id))
    .sort((a, b) => (localIds?.get(a.id) ?? 0) - (localIds?.get(b.id) ?? 0))
    .map(series => ({
      ...series,
      catalog_id: series.id,
      description: `Catalog binding · revisions: ${series.revision_policy}`
    }))

  const matches = [...new Map([...local, ...remote].map(hit => [hit.id, hit])).values()].filter(
    series =>
      (!regionFilter || series.region === regionFilter.id || regionFilter.members.includes(series.region)) &&
      (!categoryFilter || series.category === categoryFilter.id) &&
      (!kindFilter || series.kind === kindFilter) &&
      (!countryFilter || series.country === countryFilter) &&
      (!sourceId || series.provider === sourceId)
  )

  const filterFields = [
    { name: 'Region', value: regionFilter?.name ?? 'All', length: regions.length + 1, set: setRegion },
    { name: 'Country', value: countries[country - 1]?.name ?? 'All', length: countries.length + 1, set: setCountry },
    { name: 'Kind', value: kindFilter || 'All', length: kinds.length + 1, set: setKind },
    { name: 'Source', value: sourceFilter?.name ?? 'All', length: (catalog?.providers.length ?? 0) + 1, set: setSource }
  ]

  const cycleFilter = (position: number, direction: number) => {
    const field = filterFields[position]
    field?.set(value => (value + direction + field.length) % field.length)

    if (position === 0) {
      setCountry(0)
    }

    if (position === 1) {
      setRegion(0)
    }

    setIndex(0)
  }

  const choices =
    tab === 1
      ? matches
      : (tab === 0 ? (catalog?.presets ?? []) : (catalog?.providers ?? [])).filter(item =>
          `${item.name} ${item.description}`.toLowerCase().includes(query.toLowerCase())
        )

  const current = choices[Math.min(index, Math.max(0, choices.length - 1))]

  const existing = new Set([
    ...(data?.selection.series_ids ?? []),
    ...(data?.selection.custom ?? []).map(item => `custom:${item.provider}:${item.symbol}`)
  ])

  const modalWidth = cols < 100 ? Math.max(40, cols - 2) : Math.max(48, Math.min(cols - 6, 112))
  const innerWidth = modalWidth - 6
  const verticalMargin = rows < 30 ? 2 : 6
  const modalHeight = Math.max(8, Math.min(rows - verticalMargin, 38))
  const detailHeight = modalHeight >= 26 ? 5 : 2
  const pageSize = Math.max(1, modalHeight - 4 - 11 - detailHeight - (cols < 100 ? 1 : 0))
  const railWidth = Math.max(14, Math.min(24, Math.floor(innerWidth * 0.25)))

  const topicStart = Math.max(
    0,
    Math.min(category - Math.floor(pageSize / 2), availableCategories.length + 1 - pageSize)
  )

  const topicChoices = [{ id: '', name: 'All topics' }, ...availableCategories]

  const start = Math.max(0, Math.min(index - Math.floor(pageSize / 2), choices.length - pageSize))

  const prepare = async (request: DeskEdit) => {
    if (!gw || busy) {
      return
    }

    const owner = generation.current
    setBusy(true)
    setError('')

    try {
      const result = await gw.request('market.selection.preview', { edit: request })

      if (owner !== generation.current) {
        return
      }

      setEdit(request)
      setPreview(result.preview)
      setPreviewIndex(0)
    } catch (cause) {
      if (owner !== generation.current) {
        return
      }

      setError(cause instanceof Error ? cause.message : 'Unable to preview this selection.')
    } finally {
      if (owner === generation.current) {
        setBusy(false)
      }
    }
  }

  const apply = async () => {
    if (!gw || !preview || !edit || !catalog || busy) {
      return
    }

    const owner = generation.current
    setBusy(true)
    setError('')

    try {
      const result = await gw.request('market.selection.apply', { edit, expected_revision: preview.revision })

      if (owner === generation.current) {
        onSaved(deskConfig(catalog, result.selection))
      }
    } catch (cause) {
      if (owner !== generation.current) {
        return
      }

      setError(cause instanceof Error ? cause.message : 'Unable to save. Your existing selection is unchanged.')
      setPreview(null)
    } finally {
      if (owner === generation.current) {
        setBusy(false)
      }
    }
  }

  const connect = async (provider: string) => {
    if (!gw || !sessionId || busy) {
      return
    }

    const owner = generation.current
    setBusy(true)
    setError('')

    try {
      await gw.request('market.provider.connect', { provider, session_id: sessionId })
      const result = await gw.request('market.catalog', {})

      if (owner === generation.current) {
        setData(result)
      }
    } catch (cause) {
      if (owner !== generation.current) {
        return
      }

      setError(cause instanceof Error ? cause.message : 'Unable to connect provider.')
    } finally {
      if (owner === generation.current) {
        setBusy(false)
      }
    }
  }

  useInput((input, key) => {
    if (globalModal) {
      return
    }

    if (key.pageDown || (key.ctrl && input === 'd')) {
      scrollRef.current?.scrollBy(Math.max(3, rows - 16))

      return
    }

    if (key.pageUp || (key.ctrl && input === 'u')) {
      scrollRef.current?.scrollBy(-Math.max(3, rows - 16))

      return
    }

    if (key.escape) {
      if (filterFocus !== null) {
        setFilterFocus(null)

        return
      }

      if (preview) {
        setPreview(null)
        setEdit(null)
      } else if (!busy) {
        onCancel()
      }

      return
    }

    if (busy || !data) {
      return
    }

    if (preview) {
      if (key.return) {
        void apply()
      } else if (key.downArrow) {
        setPreviewIndex(value =>
          Math.min(Math.max(0, preview.added.length + preview.removed.length - pageSize), value + 1)
        )
      } else if (key.upArrow) {
        setPreviewIndex(value => Math.max(0, value - 1))
      }

      return
    }

    if (key.tab && key.shift && tab === 1) {
      setFilterFocus(value => (value === null ? 0 : null))

      return
    }

    if (filterFocus !== null) {
      if (key.leftArrow || key.rightArrow || key.tab) {
        setFilterFocus(value => ((value ?? 0) + (key.leftArrow ? 3 : 1)) % 4)
      } else if (key.upArrow || key.downArrow) {
        cycleFilter(filterFocus, key.upArrow ? -1 : 1)
      } else if (key.return) {
        setFilterFocus(null)
      } else if (key.backspace || key.delete) {
        setRegion(0)
        setCountry(0)
        setKind(0)
        setSource(0)
        setIndex(0)
      }

      return
    }

    if (key.tab) {
      setTab(value => (value + (key.shift ? 2 : 1)) % 3)
      setQuery('')
      setIndex(0)

      return
    }

    if (key.return && key.shift && tab === 1) {
      setSearchAttempt(value => value + 1)

      return
    }

    if (key.downArrow) {
      setIndex(value => Math.min(choices.length - 1, value + 1))
    } else if (key.upArrow) {
      setIndex(value => Math.max(0, value - 1))
    } else if ((key.leftArrow || key.rightArrow) && tab === 1) {
      setCategory(
        value => (value + (key.leftArrow ? availableCategories.length : 1)) % (availableCategories.length + 1)
      )
      setIndex(0)
    } else if (key.ctrl && input === 'l' && tab === 1) {
      void loadLatest()
    } else if (key.ctrl && input === 's' && tab === 1 && selected.size) {
      reviewSelection()
    } else if (key.ctrl && input === 'e' && tab === 0 && ['empty', 'unconfigured'].includes(data.selection.state)) {
      void prepare({ add: [], catalog_revision: data.catalog_revision, preset_id: null, remove: [], start_empty: true })
    } else if (key.return && current) {
      choose(current.id)
    } else if (key.backspace || key.delete) {
      setQuery(value => value.slice(0, -1))
      setIndex(0)
    } else if (input && !key.ctrl && !key.meta) {
      setQuery(value => (value + input).slice(0, 200))
      setIndex(0)
    }
  })

  const series = tab === 1 ? matches.find(item => item.id === current?.id) : undefined
  const provider = catalog?.providers.find(item => item.id === (series?.provider ?? (tab === 2 ? current?.id : '')))
  const preset = tab === 0 ? catalog?.presets.find(item => item.id === current?.id) : undefined

  const enablePredictionMarkets = async () => {
    if (!gw || !data || busy) {
      return
    }

    const owner = generation.current
    setBusy(true)

    try {
      const result = await gw.request('market.selection.update', {
        expected_revision: data.selection.revision,
        patch: { providers: [...new Set([...data.selection.providers, 'predictionmarkets'])] }
      })

      if (owner === generation.current) {
        onSaved(deskConfig(data.catalog, result.selection))
      }
    } catch {
      if (owner !== generation.current) {
        return
      }

      setError('Could not enable prediction-market discovery. Reopen Add data and retry.')
    } finally {
      if (owner === generation.current) {
        setBusy(false)
      }
    }
  }

  const loadLatest = async () => {
    if (!gw || !series || series.kind === 'event') {
      return
    }

    const id = series.id
    const owner = generation.current
    setLatestStatus(previous => ({ ...previous, [id]: 'Loading latest data…' }))

    try {
      const result = await gw.request('market.quotes', {
        series: [
          {
            ...(series.catalog_id ? { catalog_id: series.catalog_id } : {}),
            provider: series.provider,
            symbol: series.symbol,
            name: series.name,
            unit: series.unit
          }
        ]
      })

      if (owner !== generation.current) {
        return
      }

      const quote = result.quotes.find(item => item.provider === series.provider && item.symbol === series.symbol)

      if (quote) {
        setLatest(previous => ({ ...previous, [id]: quote }))
      }

      setLatestStatus(previous => ({
        ...previous,
        [id]:
          result.statuses.find(item => item.provider === series.provider)?.message ??
          (quote ? '' : 'No observations returned.')
      }))
    } catch {
      if (owner !== generation.current) {
        return
      }

      setLatestStatus(previous => ({ ...previous, [id]: 'Data unavailable. Ctrl+L to retry.' }))
    }
  }

  const reviewSelection = () => {
    if (!data || busy || !selected.size) {
      return
    }

    void prepare({
      add: [...selected].filter(id => !id.startsWith('custom:') && !existing.has(id)),
      remove: [...selected].filter(id => !id.startsWith('custom:') && existing.has(id)),
      custom_add: [...selected]
        .filter(id => id.startsWith('custom:') && !existing.has(id))
        .flatMap(id => {
          const hit = picked[id]

          return hit
            ? [
                {
                  provider: hit.provider,
                  symbol: hit.symbol,
                  name: hit.name,
                  category: catalog?.categories.find(c => c.id === hit.category)?.name ?? hit.category,
                  unit: hit.unit,
                  line: null
                }
              ]
            : []
        }),
      custom_remove: (data.selection.custom ?? []).filter(item =>
        selected.has(`custom:${item.provider}:${item.symbol}`)
      ),
      catalog_revision: data.catalog_revision,
      preset_id: null,
      start_empty: false
    })
  }

  const choose = (id: string) => {
    if (!data || busy || globalModal) {
      return
    }

    if (tab === 0) {
      void prepare({ add: [], remove: [], catalog_revision: data.catalog_revision, preset_id: id, start_empty: false })
    } else if (tab === 1) {
      const hit = matches.find(item => item.id === id)

      if (hit) {
        setPicked(previous => ({ ...previous, [id]: hit }))
      }

      setSelected(previous => {
        const next = new Set(previous)

        if (next.has(id)) {
          next.delete(id)
        } else {
          next.add(id)
        }

        return next
      })
    } else if (id === 'predictionmarkets') {
      void enablePredictionMarkets()
    } else if (catalog?.providers.find(item => item.id === id)?.key_env && sessionId) {
      void connect(id)
    } else {
      setSource((catalog?.providers.findIndex(item => item.id === id) ?? -1) + 1)
      setTab(1)
      setQuery('')
      setIndex(0)
      setCategory(0)
      setRegion(0)
      setCountry(0)
      setKind(0)
    }
  }

  const measurement = series ? latest[series.id] : undefined

  const previewRows = preview
    ? [...preview.added.map(id => ({ id, action: 'Add' })), ...preview.removed.map(id => ({ id, action: 'Remove' }))]
    : []

  return (
    <ModalOverlay cols={cols} maxHeight={38} maxWidth={112} rows={rows} t={t} verticalMargin={verticalMargin}>
      <Box flexDirection="column" flexGrow={1} minHeight={0}>
        <Box flexShrink={0} justifyContent="space-between">
          <Text bold color={t.color.primary}>
            Add data
          </Text>
          <Text color={t.color.muted}>
            {choices.length} matches · {selected.size} changes
          </Text>
        </Box>
        <Box flexShrink={0} gap={3}>
          {tabs.map((name, position) => (
            <Text
              bold={tab === position}
              color={tab === position ? t.color.accent : t.color.muted}
              key={name}
              onClick={() => {
                if (!globalModal && !busy && !preview) {
                  setTab(position)
                  setIndex(0)
                  setQuery('')
                }
              }}
            >
              {name}
            </Text>
          ))}
        </Box>
        <Box flexShrink={0} marginTop={1}>
          <Text color={t.color.accent}>Search </Text>
          <Text>{query}</Text>
          {!preview && filterFocus === null ? <Text inverse> </Text> : null}
          {!query ? <Text color={t.color.muted}> type a name, country or indicator…</Text> : null}
        </Box>
        <Text color={t.color.border}>{'─'.repeat(innerWidth)}</Text>
        {error ? <Text color={t.color.error}>{error}</Text> : null}
        {!data && !error ? <Text color={t.color.muted}>Loading catalog from your connected backend…</Text> : null}
        {busy ? <Text color={t.color.muted}>Working…</Text> : null}
        {preview ? (
          <Box flexDirection="column" flexGrow={1} minHeight={0}>
            <Text bold>
              {preview.added.length} additions · {preview.removed.length} removals · {preview.already_selected.length}{' '}
              already selected
            </Text>
            <Text color={t.color.muted}>
              Only the listed changes will be applied; watchlists and saved events are preserved.
            </Text>
            {previewRows.slice(previewIndex, previewIndex + pageSize).map(({ id, action }) => (
              <Text key={id} wrap="truncate-end">
                {action}: {catalog?.series.find(item => item.id === id)?.name ?? picked[id]?.name ?? id}
              </Text>
            ))}
            {previewRows.length > pageSize ? (
              <Text color={t.color.muted}>
                {previewIndex + 1}–{Math.min(previewRows.length, previewIndex + pageSize)} of {previewRows.length} · ↑↓
                review
              </Text>
            ) : null}
            {edit?.start_empty ? <Text>Start empty; the starter remains available here later.</Text> : null}
            {preview.credential_providers.length ? (
              <Text color={t.color.muted}>Requires connection: {preview.credential_providers.join(', ')}</Text>
            ) : null}
          </Box>
        ) : data ? (
          <>
            {tab === 1 ? (
              <Box flexDirection="column" flexShrink={0}>
                <Box flexWrap="wrap" gap={1}>
                  {filterFields.map((field, position) => (
                    <Text
                      color={filterFocus === position ? t.color.accent : t.color.muted}
                      inverse={filterFocus === position}
                      key={field.name}
                      onClick={() => {
                        if (!globalModal && !busy) {
                          setFilterFocus(position)
                        }
                      }}
                    >
                      {field.name}: {field.value}
                    </Text>
                  ))}
                </Box>
                <Text
                  color={t.color.muted}
                  onClick={() => {
                    if (!globalModal && !busy) {
                      setSearchAttempt(value => value + 1)
                    }
                  }}
                  wrap="truncate-end"
                >
                  {filterFocus !== null
                    ? '←→ Filter · ↑↓ Value · Backspace Reset · Enter Results'
                    : searching
                      ? 'Searching live directories… · Shift+Tab Filters'
                      : query.trim().length < 2
                        ? 'Catalog results · type 2+ characters for live search · Shift+Tab Filters'
                        : `${matches.length} results · Shift+Tab Filters · ${searchStatus.filter(s => !['ok', 'cached', 'catalog_only'].includes(s.status)).length || 'no'} source limits · Shift+Enter Retry`}
                </Text>
              </Box>
            ) : (
              <Text color={t.color.muted}>
                {tab === 0
                  ? 'Preview a collection before adding it to your desk.'
                  : 'Access requirements and coverage from your connected backend.'}
              </Text>
            )}
            <Box flexDirection="row" flexGrow={1} minHeight={0}>
              {tab === 1 ? (
                <Box
                  borderBottom={false}
                  borderColor={t.color.border}
                  borderLeft={false}
                  borderStyle="single"
                  borderTop={false}
                  flexDirection="column"
                  flexShrink={0}
                  overflow="hidden"
                  paddingRight={1}
                  width={railWidth}
                >
                  <Text bold color={t.color.label}>
                    TOPICS
                  </Text>
                  {topicChoices.slice(topicStart, topicStart + pageSize).map((topic, offset) => (
                    <Text
                      color={category === topicStart + offset ? t.color.accent : t.color.muted}
                      key={topic.id}
                      onClick={() => {
                        if (!globalModal && !busy) {
                          setCategory(topicStart + offset)
                          setIndex(0)
                        }
                      }}
                      wrap="truncate-end"
                    >
                      {category === topicStart + offset ? '▸ ' : '  '}
                      {topic.name}
                    </Text>
                  ))}
                </Box>
              ) : null}
              <Box flexDirection="column" flexGrow={1} marginLeft={tab === 1 ? 1 : 0} minWidth={0} overflow="hidden">
                <Text bold color={t.color.label}>
                  {tab === 0 ? 'COLLECTIONS' : tab === 1 ? 'INDICATORS' : 'SOURCES'}
                </Text>
                {choices.slice(start, start + pageSize).map((item, offset) => (
                  <Box
                    key={item.id}
                    onClick={() => {
                      if (!globalModal && !busy) {
                        setIndex(start + offset)
                        choose(item.id)
                      }
                    }}
                    width="100%"
                  >
                    <Text color={index === start + offset ? t.color.accent : t.color.muted}>
                      {index === start + offset ? '▸ ' : '  '}
                    </Text>
                    {tab === 1 ? (
                      <Text color={selected.has(item.id) ? t.color.accent : t.color.muted}>
                        {selected.has(item.id)
                          ? existing.has(item.id)
                            ? '[−] '
                            : '[+] '
                          : existing.has(item.id)
                            ? '[✓] '
                            : '[ ] '}
                      </Text>
                    ) : null}
                    <Box flexGrow={1} minWidth={0}>
                      <Text bold={index === start + offset} wrap="truncate-end">
                        {item.name}
                        {tab === 1 && 'provider' in item ? ` · ${item.provider}` : ''}
                      </Text>
                    </Box>
                  </Box>
                ))}
                {!choices.length ? <Text color={t.color.muted}>No matches. Change your search or filters.</Text> : null}
              </Box>
            </Box>
            <Text color={t.color.border}>{'─'.repeat(innerWidth)}</Text>
            <ScrollBox
              decstbm={false}
              flexDirection="column"
              flexShrink={0}
              followContent={false}
              height={detailHeight}
              key={current?.id ?? tab}
              ref={scrollRef}
            >
              {preset ? (
                <>
                  <Text bold>
                    {preset.name} · {preset.series_ids.length} series
                  </Text>
                  <Text>{preset.description}</Text>
                </>
              ) : null}
              {series ? (
                <>
                  <Text bold>{series.name}</Text>
                  <Text>
                    {catalog?.countries.find(country => country.id === series.country)?.name ?? series.region} ·{' '}
                    {series.unit} · {series.frequency} · {series.kind}
                  </Text>
                  <Text color={t.color.muted}>
                    Ctrl+L Latest · {series.symbol} · {series.description}. Display only; not settlement evidence.
                  </Text>
                </>
              ) : null}
              {searchStatus
                .filter(status => !['ok', 'cached', 'catalog_only'].includes(status.status))
                .map(status => (
                  <Text color={t.color.muted} key={status.provider}>
                    {status.provider}: {status.message}
                  </Text>
                ))}
              {sourceFilter &&
              searchStatus.some(status => status.provider === sourceFilter.id && status.status === 'catalog_only') ? (
                <Text color={t.color.muted}>
                  This source supports reviewed catalog entries; live directory search is unavailable.
                </Text>
              ) : null}
              {series && measurement ? (
                <Text wrap="truncate-end">
                  Latest: {measurement.value ?? '—'} {measurement.unit} ·{' '}
                  {measurement.asOf ? new Date(measurement.asOf).toISOString().slice(0, 10) : 'Date unknown'} ·{' '}
                  {measurement.dated_history.length} dated points
                </Text>
              ) : null}
              {series && latestStatus[series.id] ? (
                <Text color={t.color.muted} wrap="truncate-end">
                  {latestStatus[series.id]}
                </Text>
              ) : null}
              {series && measurement ? (
                <Text color={t.color.muted} wrap="truncate-end">
                  {series.kind === 'forecast'
                    ? `Issued: ${measurement.issue_time ?? 'not supplied'} · valid ${measurement.valid_from ?? 'unknown'} to ${measurement.valid_until ?? 'unknown'}`
                    : `Published: ${measurement.published_at ?? 'not supplied'} · fetched ${measurement.retrieved_at ?? 'unknown'}`}
                </Text>
              ) : null}
              {provider?.id === 'predictionmarkets' ? (
                <Text color={t.color.accent}>Enter Enable prediction-market discovery</Text>
              ) : null}
              {provider ? (
                <>
                  <Text bold>{provider.name}</Text>
                  <Text wrap="truncate-end">{provider.description}</Text>
                  <Text color={t.color.muted}>
                    {provider.auth === 'none'
                      ? 'Keyless access'
                      : data.configured_providers.includes(provider.id)
                        ? 'Credentials saved; access checked when fetching'
                        : `${provider.auth === 'required' ? 'Required' : 'Optional'} credentials not configured`}
                    {tab === 2
                      ? provider.key_env && sessionId
                        ? ' · Enter to connect securely'
                        : ' · Enter to browse this source'
                      : ''}
                  </Text>
                  {provider.access_note ? (
                    <Text color={t.color.muted} wrap="truncate-end">
                      {provider.access_note}
                    </Text>
                  ) : null}
                </>
              ) : null}
              {tab === 0 && ['empty', 'unconfigured'].includes(data.selection.state) ? (
                <Text color={t.color.muted}>Ctrl+E Start empty — load a starter set here whenever you are ready.</Text>
              ) : null}
            </ScrollBox>
          </>
        ) : (
          <Box flexGrow={1} />
        )}
        <Box flexShrink={0} justifyContent="space-between" marginTop={1}>
          <Box flexGrow={1} minWidth={0}>
            <Text color={t.color.muted} wrap="truncate-end">
              {preview
                ? '↑↓ Review · Enter Apply selection · Esc Back'
                : filterFocus !== null
                  ? 'Enter Results · Esc Results · ←→ Filter · ↑↓ Value'
                  : 'Enter Choose · Esc Cancel · Tab View · ←→ Topic · PgUp/Dn Details'}
            </Text>
          </Box>
          {!preview && tab === 1 && selected.size ? (
            <Box flexShrink={0}>
              <Text
                bold
                color={t.color.accent}
                onClick={() => {
                  if (!globalModal) {
                    reviewSelection()
                  }
                }}
              >
                {' '}
                Review {selected.size} [Ctrl+S]
              </Text>
            </Box>
          ) : null}
        </Box>
      </Box>
    </ModalOverlay>
  )
}
