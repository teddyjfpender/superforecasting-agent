import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { getUiState, resetUiState } from '../app/uiStore.js'
import type { ThemeListResponse } from '../gatewayTypes.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const themeList = (): ThemeListResponse => ({
  active: 'forecast',
  themes: [
    {
      branding: {},
      colors: { banner_accent: '#D6B85A', banner_title: '#8FE3CF', ui_primary: '#8FE3CF' },
      description: 'Forecasting desk — neutral research terminal',
      name: 'forecast',
      source: 'builtin'
    },
    {
      branding: {},
      colors: { banner_accent: '#8EA8FF', banner_title: '#7eb8f6', ui_primary: '#7eb8f6' },
      description: 'Cool blue — developer-focused',
      name: 'slate',
      source: 'builtin'
    },
    {
      branding: {},
      colors: { banner_accent: '#aaaaaa', banner_title: '#e6edf3', ui_primary: '#e6edf3' },
      description: 'Monochrome — clean grayscale',
      name: 'mono',
      source: 'builtin'
    }
  ]
})

const writeStream = (columns: number, rows: number, isTTY = false) => {
  const stream = new PassThrough() as PassThrough & {
    columns: number
    isRaw?: boolean
    isTTY: boolean
    ref?: () => PassThrough
    rows: number
    setRawMode?: (mode: boolean) => void
    unref?: () => PassThrough
  }

  let output = ''
  Object.assign(stream, {
    columns,
    isRaw: false,
    isTTY,
    rows,
    ref: () => stream,
    setRawMode: (mode: boolean) => {
      stream.isRaw = mode
    },
    unref: () => stream
  })
  stream.on('data', chunk => {
    output += chunk.toString()
  })

  return { stream, text: () => output, write: (s: string) => stream.emit('data', s) }
}

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const mountPicker = async (
  response: ThemeListResponse,
  configSet: (params: Record<string, unknown>) => Promise<unknown> = () => Promise.resolve({ value: 'ok' })
) => {
  process.env.FORECAST_TUI_INLINE = '1'
  resetUiState()

  const [{ render }, { ThemePicker }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/themePicker.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(110, 40)
  const stdin = writeStream(110, 40, true)
  const onClose = vi.fn()

  const fakeGw = {
    request: (method: string, params: Record<string, unknown>) =>
      method === 'config.set' ? configSet(params) : Promise.resolve(response)
  } as unknown as Parameters<typeof ThemePicker>[0]['gw']

  const instance = render(
    React.createElement(ThemePicker, { gw: fakeGw, onClose, t: DARK_THEME }),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  await tick(60)

  const read = () =>
    stripAnsi(stdout.text().replace(OSC_RE, '').replace(CSI_RE, ''))
      .replace(/[ \t]+\n/g, '\n')
      .trim()

  return {
    onClose,
    press: (seq: string) => stdin.stream.emit('data', seq),
    read,
    stop: () => {
      instance.unmount?.()
      instance.cleanup?.()
    }
  }
}

afterEach(() => {
  resetUiState()
})

describe('themeFromOption', () => {
  it('builds a live Theme from a skin color map (so preview == commit)', async () => {
    const { themeFromOption } = await import('../components/themePicker.js')
    const slate = themeList().themes!.find(theme => theme.name === 'slate')!
    const theme = themeFromOption(slate)
    // ui_primary from the skin map drives the theme's primary color.
    expect(theme.color.primary).toBe('#7eb8f6')
    // The severity triple is always present (falls back to defaults when the
    // skin doesn't override it) so the swatch can't render undefined.
    expect(theme.color.ok).toBeTruthy()
    expect(theme.color.error).toBeTruthy()
    expect(theme.color.info).toBeTruthy()
  })

  it('distinct skins yield distinct primaries — themes are visibly different', async () => {
    const { themeFromOption } = await import('../components/themePicker.js')
    const [forecast, slate, mono] = themeList().themes!
    const primaries = [forecast, slate, mono].map(option => themeFromOption(option).color.primary)
    expect(new Set(primaries).size).toBe(3)
  })
})

describe('ThemePicker', () => {
  it('renders all theme names and the active theme description after loading', async () => {
    const p = await mountPicker(themeList())
    const text = p.read()
    expect(text).toContain('forecast')
    expect(text).toContain('slate')
    expect(text).toContain('mono')
    // Opens on the active theme (forecast); its description shows in the
    // preview pane, and the swatch legend renders.
    expect(text).toContain('Forecasting desk')
    expect(text).toContain('browse')
    p.stop()
  })

  it('applies the active theme as a live preview on open', async () => {
    resetUiState()
    const before = getUiState().theme.color.primary
    const p = await mountPicker(themeList())
    await tick(30)
    // forecast skin's ui_primary (#8FE3CF) is applied as the live preview.
    expect(getUiState().theme.color.primary).toBe('#8FE3CF')
    expect(getUiState().theme.color.primary).not.toBe(before)
    p.stop()
  })
})
