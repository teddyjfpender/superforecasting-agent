import { Box, Text, useInput } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useEffect, useRef, useState } from 'react'

import { $globalModal } from '../app/overlayStore.js'
import type { MarketSeries } from '../content/marketProviders.js'
import { ICON, spinnerFrame } from '../lib/icons.js'
import { searchCatalog, searchYahoo } from '../lib/marketSearch.js'
import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'

// Search the market catalog + Yahoo's symbol lookup to find any ticker / line
// item, then add it to the watchlist. Press `/` in Markets. Mirrors the News /
// add-provider modal key scheme: ↑↓ move · Enter add · Esc close.

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

const dedupe = (items: MarketSeries[]): MarketSeries[] => {
  const seen = new Set<string>()
  const out: MarketSeries[] = []

  for (const s of items) {
    const k = `${s.provider}:${s.symbol.toLowerCase()}`

    if (!seen.has(k)) {
      seen.add(k)
      out.push(s)
    }
  }

  return out
}

interface MarketSearchModalProps {
  cols: number
  isAdded: (s: MarketSeries) => boolean
  isWatched: (s: MarketSeries) => boolean
  onClose: () => void
  onToggleCategory: (s: MarketSeries) => void
  onToggleWatch: (s: MarketSeries) => void
  rows: number
  t: Theme
}

export function MarketSearchModal({
  cols,
  isAdded,
  isWatched,
  onClose,
  onToggleCategory,
  onToggleWatch,
  rows,
  t
}: MarketSearchModalProps) {
  const sem = semantics(t)
  // Go inert while the global palette / cheat-sheet stacks above this modal.
  const globalModal = useStore($globalModal)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<MarketSeries[]>([])
  const [sel, setSel] = useState(0)
  const [loading, setLoading] = useState(false)
  const [tick, setTick] = useState(0)
  const seqRef = useRef(0)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    const id = setInterval(() => setTick(v => v + 1), 220)

    return () => {
      aliveRef.current = false
      clearInterval(id)
    }
  }, [])

  // Debounced search: instant catalog results, then merge in Yahoo lookups.
  useEffect(() => {
    const q = query.trim()

    if (!q) {
      setResults([])
      setLoading(false)

      return
    }

    const seq = ++seqRef.current
    const local = searchCatalog(q)
    setResults(local)
    setSel(0)
    setLoading(true)

    const id = setTimeout(() => {
      void (async () => {
        const remote = await searchYahoo(q)

        if (!aliveRef.current || seq !== seqRef.current) {
          return
        }

        setResults(dedupe([...local, ...remote]))
        setLoading(false)
      })()
    }, 250)

    return () => clearTimeout(id)
  }, [query])

  // Mirror ModalOverlay's box sizing so inner widths + the explicit list height
  // line up with the overlay this renders through.
  const narrow = cols < 100
  const modalW = narrow ? Math.max(40, cols - 2) : Math.max(48, Math.min(cols - 6, 100))
  const modalH = Math.max(8, Math.min(rows - 6, 32))
  const inner = modalW - 6
  const listRows = Math.max(4, modalH - 10)

  useInput((ch, key) => {
    if (key.escape) {
      return onClose()
    }

    if (key.return) {
      const pick = results[sel]

      if (pick) {
        onToggleCategory(pick) // default: add to its own category
      }

      return
    }

    if (key.tab) {
      const pick = results[sel]

      if (pick) {
        onToggleWatch(pick) // opt-in: add to the watchlist instead
      }

      return
    }

    if (key.upArrow || key.wheelUp) {
      return setSel(i => Math.max(0, i - 1))
    }

    if (key.downArrow || key.wheelDown) {
      return setSel(i => Math.min(Math.max(0, results.length - 1), i + 1))
    }

    if (key.backspace || key.delete) {
      return setQuery(s => s.slice(0, -1))
    }

    if (ch && !key.ctrl && !key.meta) {
      const printable = [...ch].filter(c => c >= ' ').join('')

      if (printable) {
        setQuery(s => s + printable)
      }
    }
  }, { isActive: !globalModal })

  const start = Math.max(0, Math.min(sel - Math.floor(listRows / 2), results.length - listRows))
  const windowed = results.slice(Math.max(0, start), Math.max(0, start) + listRows)

  return (
    <ModalOverlay cols={cols} maxHeight={32} maxWidth={100} rows={rows} t={t}>
        <Box flexShrink={0} justifyContent="space-between">
          <Text bold color={t.color.primary}>
            Search markets
          </Text>
          <Text color={loading ? sem.star : t.color.muted}>
            {loading ? `${spinnerFrame(tick)} searching…` : `${results.length} ${results.length === 1 ? 'match' : 'matches'}`}
          </Text>
        </Box>

        <Box flexShrink={0} marginTop={1}>
          <Text bold color={sem.cursor}>{`${ICON.search} `}</Text>
          <Text color={t.color.text}>{query}</Text>
          <Text color={t.color.text} inverse>
            {' '}
          </Text>
          {!query ? <Text color={t.color.muted}> ticker, name or theme (e.g. NVDA, gold, 10y yield)…</Text> : null}
        </Box>

        <Box flexShrink={0} marginTop={1}>
          <Text color={sem.rule}>{'─'.repeat(inner)}</Text>
        </Box>

        <Box flexDirection="column" flexShrink={0} height={listRows} overflow="hidden">
          {results.length === 0 ? (
            <Text color={t.color.muted} wrap="truncate-end">
              {query ? (loading ? 'Searching…' : 'No matches — try a ticker or company name.') : 'Type to search the catalog and every Yahoo Finance ticker.'}
            </Text>
          ) : (
            windowed.map((s, i) => {
              const idx = start + i
              const on = idx === sel
              const added = isAdded(s)
              const watched = isWatched(s)

              return (
                <Box key={`${s.provider}:${s.symbol}:${idx}`} width="100%">
                  <Text wrap="truncate-end">
                    <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
                    <Text bold color={added ? sem.up : sem.subtle}>
                      {added ? '[✓]' : '[+]'}
                    </Text>
                    <Text color={watched ? sem.star : sem.faint}>{watched ? '★' : ' '}</Text>
                    <Text color={t.color.accent}> {s.symbol.padEnd(10)}</Text>
                    <Text color={on ? sem.selectionFg : t.color.label}> {truncate(s.name, inner - 32)}</Text>
                    <Text color={sem.badge}> {s.category}</Text>
                  </Text>
                </Box>
              )
            })
          )}
        </Box>

        <Box flexShrink={0} marginTop={1}>
          <Text color={t.color.muted} wrap="truncate-end">
            type to search · ↑↓ move · ⏎ add to category · Tab ★ watchlist · Esc close
          </Text>
        </Box>
    </ModalOverlay>
  )
}
