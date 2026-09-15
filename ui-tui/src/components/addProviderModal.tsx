import { useStore } from '@nanostores/react'
import { Box, ScrollBox, type ScrollBoxHandle, Text, useInput } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import { $globalModal } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import { deskConfig } from '../lib/dataDesk.js'
import type { MarketConfig } from '../lib/marketStore.js'
import type { DeskEdit, DeskPreview, MarketCatalogResponse, Quote } from '../protocol/generated.js'
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

  const matches =
    catalog?.series.filter(series => {
      const haystack =
        `${series.name} ${series.symbol} ${series.country ?? ''} ${catalog?.countries.find(country => country.id === series.country)?.name ?? ''} ${series.location?.name ?? ''} ${series.tags.join(' ')}`.toLowerCase()

      return (
        (!regionFilter || series.region === regionFilter.id || regionFilter.members.includes(series.region)) &&
        (!categoryFilter || series.category === categoryFilter.id) &&
        (!kind || series.kind === kinds[kind - 1]) &&
        (!country || series.country === countries[country - 1]?.id) &&
        query
          .toLowerCase()
          .split(/\s+/)
          .every(term => haystack.includes(term))
      )
    }) ?? []

  const choices =
    tab === 1
      ? matches
      : (tab === 0 ? (catalog?.presets ?? []) : (catalog?.providers ?? [])).filter(item =>
          `${item.name} ${item.description}`.toLowerCase().includes(query.toLowerCase())
        )

  const current = choices[Math.min(index, Math.max(0, choices.length - 1))]
  const existing = new Set(data?.selection.series_ids ?? [])
  const modalWidth = cols < 100 ? Math.max(40, cols - 2) : Math.max(48, Math.min(cols - 6, 112))
  const innerWidth = modalWidth - 6
  const modalHeight = Math.max(8, Math.min(rows - 6, 38))
  const detailHeight = modalHeight >= 26 ? 5 : 2
  const pageSize = Math.max(2, modalHeight - 4 - 12 - detailHeight)
  const railWidth = Math.max(14, Math.min(24, Math.floor(innerWidth * 0.25)))

  const topicStart = Math.max(
    0,
    Math.min(category - Math.floor(pageSize / 2), availableCategories.length + 1 - (pageSize + 1))
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

    if (key.tab) {
      setTab(value => (value + (key.shift ? 2 : 1)) % 3)
      setQuery('')
      setIndex(0)

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
    } else if (key.ctrl && input === 'r' && tab === 1) {
      setRegion(value => (value + 1) % (regions.length + 1))
      setIndex(0)
    } else if (key.ctrl && input === 'k' && tab === 1) {
      setKind(value => (value + 1) % (kinds.length + 1))
      setIndex(0)
    } else if (key.ctrl && input === 'g' && tab === 1) {
      setCountry(value => (value + 1) % (countries.length + 1))
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
      setQuery(value => value + input)
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
        series: [{ catalog_id: id, provider: series.provider, symbol: series.symbol }]
      })

      if (owner !== generation.current) {
        return
      }

      const quote = result.quotes.find(item => item.catalog_id === id)

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
      add: [...selected].filter(id => !existing.has(id)),
      remove: [...selected].filter(id => existing.has(id)),
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
    } else if (catalog?.providers.find(item => item.id === id)?.key_env) {
      void connect(id)
    }
  }

  const measurement = series ? latest[series.id] : undefined

  const previewRows = preview
    ? [...preview.added.map(id => ({ id, action: 'Add' })), ...preview.removed.map(id => ({ id, action: 'Remove' }))]
    : []

  return (
    <ModalOverlay cols={cols} maxHeight={38} maxWidth={112} rows={rows} t={t}>
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
          {!preview ? <Text inverse> </Text> : null}
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
            <Text color={t.color.muted}>Watchlists, custom data and saved prediction markets are preserved.</Text>
            {previewRows.slice(previewIndex, previewIndex + pageSize).map(({ id, action }) => (
              <Text key={id} wrap="truncate-end">
                {action}: {catalog?.series.find(item => item.id === id)?.name ?? id}
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
              <Text color={t.color.muted} wrap="truncate-end">
                Ctrl+R Region: {regionFilter?.name ?? 'All'} · Ctrl+G Country: {countries[country - 1]?.name ?? 'All'} ·
                Ctrl+K Kind: {kinds[kind - 1] ?? 'All'}
              </Text>
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
                  {topicChoices.slice(topicStart, topicStart + pageSize + 1).map((topic, offset) => (
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
                      </Text>
                    </Box>
                  </Box>
                ))}
                {!choices.length ? <Text color={t.color.muted}>No matches. Change your search or filters.</Text> : null}
              </Box>
            </Box>
            <Text color={t.color.border}>{'─'.repeat(innerWidth)}</Text>
            <ScrollBox decstbm={false} flexDirection="column" flexShrink={0} height={detailHeight} ref={scrollRef}>
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
                    Ctrl+L Latest · Revision: {series.revision_policy}. Display data does not authorize settlement.
                  </Text>
                </>
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
                    {provider.key_env && sessionId && tab === 2 ? ' · Enter to connect securely' : ''}
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
