import { Box, Text, useInput } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useState } from 'react'

import { $globalModal } from '../app/overlayStore.js'
import { MARKET_CATEGORIES, MARKET_PROVIDERS, providerByKey } from '../content/marketProviders.js'
import { getProviderKey, saveProviderKey } from '../lib/marketKeys.js'
import { type MarketConfig, saveMarketConfig } from '../lib/marketStore.js'
import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'

// Markets onboarding (press `a`): enable data providers (entering + securely
// saving an API key where the provider needs one) and pick which categories to
// watch — the full breadth, not just Indices/FX/Crypto/Commodities.

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

const RIGHT_RULE = {
  borderBottom: false,
  borderLeft: false,
  borderStyle: 'single',
  borderTop: false
} as const

interface AddProviderModalProps {
  cols: number
  initial: MarketConfig
  onCancel: () => void
  onSaved: (config: MarketConfig) => void
  // Jump to the symbol search (find + add a specific series) — the other half of
  // "Add data", reached with `/` from here.
  onSearchSymbols?: () => void
  rows: number
  t: Theme
}

export function AddProviderModal({ cols, initial, onCancel, onSaved, onSearchSymbols, rows, t }: AddProviderModalProps) {
  const sem = semantics(t)
  // Go inert while the global palette / cheat-sheet stacks above this modal.
  const globalModal = useStore($globalModal)
  const [providers, setProviders] = useState<Set<string>>(() => new Set(initial.providers))

  const [categories, setCategories] = useState<Set<string>>(
    () => new Set(initial.categories.length ? initial.categories : MARKET_CATEGORIES.slice(0, 4))
  )

  const [focus, setFocus] = useState<'categories' | 'key' | 'providers'>('providers')
  const [provIdx, setProvIdx] = useState(0)
  const [catIdx, setCatIdx] = useState(0)
  const [keyProvider, setKeyProvider] = useState('')
  const [keyInput, setKeyInput] = useState('')
  const [flash, setFlash] = useState('')

  // Mirror ModalOverlay's box sizing so the inner widths/heights line up with the
  // overlay it renders through.
  const narrow = cols < 100
  const modalW = narrow ? Math.max(40, cols - 2) : Math.max(48, Math.min(cols - 6, 104))
  const modalH = Math.max(8, Math.min(rows - 6, 34))

  const hasKey = (key: string): boolean => {
    const env = providerByKey(key)?.keyEnv

    return env ? Boolean(getProviderKey(env)) : true
  }

  const commit = () => {
    const config: MarketConfig = {
      categories: [...categories],
      custom: initial.custom,
      providers: [...providers],
      watchlist: initial.watchlist
    }

    saveMarketConfig(config)
    onSaved(config)
  }

  const toggleProvider = () => {
    const provider = MARKET_PROVIDERS[provIdx]

    if (!provider) {
      return
    }

    const next = new Set(providers)

    if (next.has(provider.key)) {
      next.delete(provider.key)
      setProviders(next)

      return
    }

    // Enabling: if it needs a key we don't have, collect it first.
    if (provider.needsKey && !hasKey(provider.key)) {
      setKeyProvider(provider.key)
      setKeyInput('')
      setFocus('key')

      return
    }

    next.add(provider.key)
    setProviders(next)
  }

  const submitKey = () => {
    const provider = providerByKey(keyProvider)

    if (!provider?.keyEnv) {
      return
    }

    if (keyInput.trim()) {
      saveProviderKey(provider.keyEnv, keyInput.trim())
      setProviders(prev => new Set(prev).add(provider.key))
      setFlash(`saved ${provider.name} key`)
    }

    setFocus('providers')
    setKeyInput('')
  }

  useInput((ch, key) => {
    if (focus === 'key') {
      if (key.escape) {
        setFocus('providers')
        setKeyInput('')

        return
      }

      if (key.return) {
        return submitKey()
      }

      if (key.backspace || key.delete) {
        return setKeyInput(s => s.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          setKeyInput(s => s + printable)
        }
      }

      return
    }

    // `/` jumps to the symbol search — the find-and-add-a-specific-series half
    // of Add data.
    if (ch === '/' && onSearchSymbols) {
      return onSearchSymbols()
    }

    // Esc saves what's selected and closes (toggles applied incrementally) —
    // matches the News modal: ↑↓ move, Tab/←→ switch, Enter toggle, Esc done.
    if (key.escape) {
      return commit()
    }

    if (key.tab || key.leftArrow || key.rightArrow) {
      return setFocus(f => (f === 'providers' ? 'categories' : 'providers'))
    }

    if (key.upArrow) {
      return focus === 'providers'
        ? setProvIdx(i => Math.max(0, i - 1))
        : setCatIdx(i => Math.max(0, i - 1))
    }

    if (key.downArrow) {
      return focus === 'providers'
        ? setProvIdx(i => Math.min(MARKET_PROVIDERS.length - 1, i + 1))
        : setCatIdx(i => Math.min(MARKET_CATEGORIES.length - 1, i + 1))
    }

    // `k` adds or replaces the highlighted provider's API key — for ANY provider
    // that supports one (FRED/BLS/BEA), whether or not a key already exists.
    if (ch === 'k' && focus === 'providers') {
      const provider = MARKET_PROVIDERS[provIdx]

      if (!provider?.keyEnv) {
        return setFlash(`${provider?.name ?? 'this provider'} needs no API key`)
      }

      setKeyProvider(provider.key)
      setKeyInput('')

      return setFocus('key')
    }

    // Enter toggles the highlighted item in the focused pane.
    if (key.return) {
      if (focus === 'providers') {
        return toggleProvider()
      }

      const cat = MARKET_CATEGORIES[catIdx]
      const next = new Set(categories)

      if (next.has(cat)) {
        next.delete(cat)
      } else {
        next.add(cat)
      }

      return setCategories(next)
    }
  }, { isActive: !globalModal })

  const railWidth = 26
  const inner = modalW - 6
  // Explicit body height (modalH − border/padding − title/rule/desc/footer) so
  // the lists never clip the way an unbounded flexGrow row does.
  const bodyRows = Math.max(6, modalH - 12)

  const selectedProvider = MARKET_PROVIDERS[provIdx]
  const keyHintProvider = providerByKey(keyProvider)
  const keyHintExists = keyHintProvider?.keyEnv ? Boolean(getProviderKey(keyHintProvider.keyEnv)) : false

  let bodyBottom: React.ReactNode

  if (focus === 'key' && keyHintProvider) {
    bodyBottom = (
      <Box flexDirection="column">
        <Text color={t.color.label} wrap="wrap">
          {keyHintExists ? `Replace the ${keyHintProvider.name} API key (one is already saved).` : `Add a free ${keyHintProvider.name} API key.`}
        </Text>
        {keyHintProvider.keyUrl ? (
          <Text color={t.color.accent} wrap="truncate-end">
            Get one: {keyHintProvider.keyUrl}
          </Text>
        ) : null}
        <Box marginTop={1}>
          <Text color={t.color.muted}>{'› '}</Text>
          <Text color={t.color.text}>{keyInput}</Text>
          <Text color={t.color.text} inverse>
            {' '}
          </Text>
          {!keyInput ? <Text color={t.color.muted}> {keyHintExists ? 'paste a new key to replace it' : 'paste your key'}</Text> : null}
        </Box>
      </Box>
    )
  } else {
    bodyBottom = (
      <Text color={t.color.muted} wrap="wrap">
        {selectedProvider ? selectedProvider.description : ''}
      </Text>
    )
  }

  const keyAction = focus === 'providers' && selectedProvider?.keyEnv ? ` · k ${hasKey(selectedProvider.key) ? 'change' : 'add'} key` : ''

  const footer =
    focus === 'key'
      ? '⏎ save key · Esc back'
      : `Tab/←→ switch · ↑↓ move · ⏎ toggle${keyAction}${onSearchSymbols ? ' · / search symbols' : ''} · Esc save & close`

  return (
    <ModalOverlay cols={cols} maxHeight={34} maxWidth={104} rows={rows} t={t}>
        <Box flexShrink={0} justifyContent="space-between">
          <Text bold color={t.color.primary}>
            Add market data
          </Text>
          <Text color={t.color.muted}>
            <Text color={t.color.accent}>{providers.size}</Text> providers ·{' '}
            <Text color={t.color.accent}>{categories.size}</Text> categories
          </Text>
        </Box>

        <Box flexDirection="row" flexShrink={0} height={bodyRows} marginTop={1}>
          {/* Providers */}
          <Box {...RIGHT_RULE} borderColor={t.color.border} flexDirection="column" flexShrink={0} height={bodyRows} overflow="hidden" paddingRight={1} width={railWidth}>
            <Text bold color={focus === 'providers' ? sem.cursor : sem.heading}>
              PROVIDERS
            </Text>
            {MARKET_PROVIDERS.map((p, i) => {
              const on = focus === 'providers' && i === provIdx
              const enabled = providers.has(p.key)
              // Key status for providers that support one: ✓ set, ! missing-and-
              // wanted (required or recommended), · supported-but-optional.
              const keySet = p.keyEnv ? hasKey(p.key) : false
              const keyWanted = p.needsKey || p.keyRecommended

              return (
                <Box key={p.key} onClick={() => { if (globalModal) {return;} setFocus('providers'); setProvIdx(i) }} width="100%">
                  <Text wrap="truncate-end">
                    <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
                    <Text bold color={enabled ? sem.up : sem.subtle}>
                      {enabled ? '[✓]' : '[ ]'}
                    </Text>
                    <Text color={on ? sem.selectionFg : t.color.label}> {truncate(p.name, railWidth - 11)}</Text>
                    {p.keyEnv ? (
                      <Text color={keySet ? sem.up : keyWanted ? sem.star : sem.faint}>{keySet ? ' key✓' : keyWanted ? ' key!' : ' key'}</Text>
                    ) : null}
                  </Text>
                </Box>
              )
            })}
          </Box>

          {/* Categories */}
          <Box flexDirection="column" flexGrow={1} height={bodyRows} marginLeft={1} minWidth={0} overflow="hidden">
            <Text bold color={focus === 'categories' ? sem.cursor : sem.heading}>
              CATEGORIES
            </Text>
            {MARKET_CATEGORIES.map((c, i) => {
              const on = focus === 'categories' && i === catIdx
              const sel = categories.has(c)

              return (
                <Box key={c} onClick={() => { if (globalModal) {return;} setFocus('categories'); setCatIdx(i) }} width="100%">
                  <Text wrap="truncate-end">
                    <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
                    <Text bold color={sel ? sem.up : sem.subtle}>
                      {sel ? '[✓]' : '[ ]'}
                    </Text>
                    <Text color={on ? sem.selectionFg : t.color.label}> {c}</Text>
                  </Text>
                </Box>
              )
            })}
          </Box>
        </Box>

        <Box flexShrink={0}>
          <Text color={sem.rule}>{'─'.repeat(inner)}</Text>
        </Box>
        <Box flexShrink={0} minHeight={3}>
          {bodyBottom}
        </Box>

        <Box flexShrink={0} marginTop={1}>
          <Text color={t.color.muted} wrap="truncate-end">
            {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
            {footer}
          </Text>
        </Box>
    </ModalOverlay>
  )
}
