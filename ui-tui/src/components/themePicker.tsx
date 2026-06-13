import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import { getUiState, patchUiState } from '../app/uiStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type { ConfigSetResponse, ThemeListResponse, ThemeOption } from '../gatewayTypes.js'
import { asRpcResult, rpcErrorMessage } from '../lib/rpc.js'
import { fromSkin, type Theme } from '../theme.js'

import { OverlayHint, windowItems } from './overlayControls.js'

const VISIBLE = 12
const MIN_WIDTH = 52
const MAX_WIDTH = 96

interface ThemePickerProps {
  gw: GatewayClient
  onClose: () => void
  t: Theme
}

// Build a live Theme from a skin's color/branding maps — same path the gateway
// `skin.changed` event uses, so the preview is exactly what commit will apply.
export const themeFromOption = (option: ThemeOption): Theme =>
  fromSkin(option.colors ?? {}, option.branding ?? {})

// The swatch row: a labelled chip per load-bearing color so a glance shows
// whether a theme is gold, blue, mono, etc. and how severity reads in it.
const SWATCH_KEYS: { key: keyof Theme['color']; label: string }[] = [
  { key: 'primary', label: 'primary' },
  { key: 'accent', label: 'accent' },
  { key: 'info', label: 'info' },
  { key: 'ok', label: 'ok' },
  { key: 'warn', label: 'warn' },
  { key: 'error', label: 'error' },
  { key: 'muted', label: 'muted' }
]

export function ThemePicker({ gw, onClose, t }: ThemePickerProps) {
  const [themes, setThemes] = useState<ThemeOption[]>([])
  const [idx, setIdx] = useState(0)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)

  // The theme that was active when the picker opened — restored on cancel so
  // browsing never leaves the user stuck on a theme they didn't choose.
  const originalTheme = useRef<Theme>(getUiState().theme)
  const { stdout } = useStdout()
  const width = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, (stdout?.columns ?? 80) - 6))

  useEffect(() => {
    gw.request<ThemeListResponse>('theme.list', {})
      .then(raw => {
        const r = asRpcResult<ThemeListResponse>(raw)

        if (!r) {
          setErr('invalid response: theme.list')
          setLoading(false)

          return
        }

        const next = r.themes ?? []
        setThemes(next)

        const activeIdx = Math.max(
          0,
          next.findIndex(theme => theme.name === r.active)
        )

        setIdx(activeIdx)
        setLoading(false)
      })
      .catch((e: unknown) => {
        setErr(rpcErrorMessage(e))
        setLoading(false)
      })
  }, [gw])

  // Apply the highlighted theme live as the cursor moves — the whole point of
  // a picker is seeing the change, not reading a name.
  useEffect(() => {
    const option = themes[idx]

    if (option) {
      patchUiState({ theme: themeFromOption(option) })
    }
  }, [themes, idx])

  const cancel = () => {
    patchUiState({ theme: originalTheme.current })
    onClose()
  }

  const commit = () => {
    const option = themes[idx]

    if (!option || saving) {
      return
    }

    setSaving(true)
    // Persist via the existing skin config key (fires skin.changed); the live
    // preview already applied the theme, so we just keep it on success.
    gw.request<ConfigSetResponse>('config.set', { key: 'skin', value: option.name })
      .then(() => onClose())
      .catch((e: unknown) => {
        setErr(rpcErrorMessage(e))
        setSaving(false)
      })
  }

  useInput((ch, key) => {
    if (loading) {
      if (key.escape || ch === 'q') {
        cancel()
      }

      return
    }

    if (key.escape || ch === 'q') {
      return cancel()
    }

    if (key.return) {
      return commit()
    }

    if (key.upArrow || ch === 'k') {
      return setIdx(i => (i <= 0 ? themes.length - 1 : i - 1))
    }

    if (key.downArrow || ch === 'j') {
      return setIdx(i => (i >= themes.length - 1 ? 0 : i + 1))
    }
  })

  const current = themes[idx]
  // The preview must use the PREVIEWED theme's colors, not the picker's prop
  // `t` (which is the original) — otherwise the swatches wouldn't change.
  const preview = useMemo(() => (current ? themeFromOption(current) : t), [current, t])

  if (loading) {
    return (
      <Box flexDirection="column" width={width}>
        <Text color={t.color.primary}>Theme</Text>
        <Text color={t.color.muted}>loading themes…</Text>
      </Box>
    )
  }

  if (err && !themes.length) {
    return (
      <Box flexDirection="column" width={width}>
        <Text color={t.color.primary}>Theme</Text>
        <Text color={t.color.error}>{err}</Text>
        <OverlayHint t={t}>esc close</OverlayHint>
      </Box>
    )
  }

  const { items, offset } = windowItems(themes, idx, VISIBLE)

  return (
    <Box flexDirection="column" width={width}>
      <Text color={preview.color.primary}>Theme — live preview</Text>

      <Box flexDirection="row" marginTop={1}>
        {/* Left: theme list */}
        <Box flexDirection="column" width={Math.floor(width * 0.42)}>
          {items.map((option, i) => {
            const realIdx = offset + i
            const selected = realIdx === idx
            const optionTheme = themeFromOption(option)

            return (
              <Text
                color={selected ? optionTheme.color.accent : t.color.text}
                key={option.name}
                wrap="truncate-end"
              >
                {selected ? '❯ ' : '  '}
                {option.name}
                {option.source === 'user' ? ' *' : ''}
              </Text>
            )
          })}
        </Box>

        {/* Right: live swatch + description */}
        <Box flexDirection="column" marginLeft={2} width={Math.floor(width * 0.54)}>
          <Text color={preview.color.muted} wrap="truncate-end">
            {current?.description || ''}
          </Text>
          <Box flexDirection="column" marginTop={1}>
            {SWATCH_KEYS.map(({ key, label }) => (
              <Text color={preview.color[key]} key={key} wrap="truncate-end">
                {'██ '}
                <Text color={preview.color.text}>{label}</Text>
              </Text>
            ))}
          </Box>
          <Box marginTop={1}>
            <Text color={preview.color.text} wrap="truncate-end">
              <Text color={preview.color.ok}>active</Text>
              {'  '}
              <Text color={preview.color.warn}>review</Text>
              {'  '}
              <Text color={preview.color.error}>alert</Text>
              {'  '}
              <Text color={preview.color.accent}>/command</Text>
            </Text>
          </Box>
        </Box>
      </Box>

      <Box marginTop={1}>
        <OverlayHint t={t}>
          {saving ? 'saving…' : '↑↓/jk browse · enter apply & save · esc cancel'}
        </OverlayHint>
      </Box>
    </Box>
  )
}
