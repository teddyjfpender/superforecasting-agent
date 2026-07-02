import { EventEmitter } from 'events'
import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

// The global palette / cheat-sheet now STACK as absolute ModalOverlays above the
// still-mounted fullscreen views (Desk, Markets, Warnings, …) instead of
// REPLACING the body. Each view gates its own useInput (`isActive: !globalModal`)
// + its mouse handlers on the $globalModal flag so nothing double-handles keys
// beneath the overlay. These tests prove BOTH halves per view:
//   1. coexistence — the palette top + a view-specific body string in ONE frame.
//   2. key-trap    — a view key (`q` → onClose) does NOTHING while the palette is
//      open, but fires normally when it is closed (the control).

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

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

  return { stream, text: () => output }
}

const normalize = (value: string, stripAnsi: (input: string) => string) =>
  stripAnsi(value.replace(OSC_RE, '').replace(CSI_RE, ''))
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

// An EventEmitter-backed gateway: request()/rpc() resolve to null (each view then
// lands in its stable loading/error state — the header still renders — without the
// tier-tree/dashboard building from a malformed payload), while on/off come from
// EventEmitter so AlertsView's automode-event subscription doesn't crash on mount.
const fakeGw = () => {
  const gw = new EventEmitter() as EventEmitter & {
    request: () => Promise<unknown>
    rpc: () => Promise<unknown>
  }
  gw.setMaxListeners(50)
  gw.request = () => Promise.resolve(null)
  gw.rpc = () => Promise.resolve(null)

  return gw as never
}

describe('global palette / cheat-sheet gating over fullscreen views', () => {
  beforeEach(async () => {
    process.env.FORECAST_TUI_INLINE = '1'
    const [{ resetOverlayState }, { clearOverlayCache }] = await Promise.all([
      import('../app/overlayStore.js'),
      import('../lib/overlayCache.js')
    ])
    resetOverlayState()
    clearOverlayCache()
  })

  afterEach(async () => {
    const { resetOverlayState } = await import('../app/overlayStore.js')
    resetOverlayState()
    delete process.env.FORECAST_TUI_INLINE
  })

  // Render `view` as the body with the command palette stacked LAST above it —
  // exactly the sibling layout AppLayout now emits for a fullscreen view + the
  // global chrome. Returns the normalized single-frame text.
  const renderCoexistence = async (viewElement: React.ReactElement) => {
    const [{ Box, render }, { PaletteOverlay }, { DARK_THEME }, { stripAnsi }, { patchOverlayState }] =
      await Promise.all([
        import('@hermes/ink'),
        import('../components/paletteOverlay.js'),
        import('../theme.js'),
        import('../lib/text.js'),
        import('../app/overlayStore.js')
      ])

    // The palette open → $globalModal true → each view's useInput is inert.
    patchOverlayState({ palette: true })

    const stdout = writeStream(120, 40)
    const stdin = writeStream(120, 40, true)

    const instance = render(
      React.createElement(
        Box,
        { flexDirection: 'column', height: 40, width: 120 },
        viewElement,
        React.createElement(PaletteOverlay, {
          cols: 120,
          key: 'palette',
          onClose: () => undefined,
          onRun: () => undefined,
          rows: 40,
          t: DARK_THEME
        })
      ),
      { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
    )

    await tick(60)
    const text = normalize(stdout.text(), stripAnsi)
    instance.unmount?.()

    return text
  }

  // Mount `viewFactory(onClose)` alone with the palette either open or closed,
  // press `q`, and report whether the view's onClose fired. When the palette is
  // open the view's useInput is inert, so `q` must be swallowed.
  const pressQ = async (viewFactory: (onClose: () => void) => React.ReactElement, paletteOpen: boolean) => {
    const [{ render }, { patchOverlayState }] = await Promise.all([
      import('@hermes/ink'),
      import('../app/overlayStore.js')
    ])

    if (paletteOpen) {
      patchOverlayState({ palette: true })
    }

    let closed = false
    const stdout = writeStream(120, 40)
    const stdin = writeStream(120, 40, true)

    const instance = render(viewFactory(() => { closed = true }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdin: stdin.stream,
      stdout: stdout.stream
    })

    await tick(60)
    stdin.stream.write('q')
    await tick(60)
    instance.unmount?.()

    return closed
  }

  // ── Desk ──────────────────────────────────────────────────────────────────

  it('Desk: palette top coexists with the FORECASTS body in one frame', async () => {
    const { DeskView } = await import('../components/deskView.js')
    const { DARK_THEME } = await import('../theme.js')
    const text = await renderCoexistence(
      React.createElement(DeskView, { gw: fakeGw(), onClose: () => undefined, t: DARK_THEME })
    )

    expect(text).toContain('Command palette') // overlay top
    expect(text).toContain('FORECASTS') // desk body still mounted beneath
  })

  it('Desk: q is trapped while the palette is open, but closes the view otherwise', async () => {
    const { DeskView } = await import('../components/deskView.js')
    const { DARK_THEME } = await import('../theme.js')
    const view = (onClose: () => void) =>
      React.createElement(DeskView, { gw: fakeGw(), onClose, t: DARK_THEME })

    expect(await pressQ(view, true)).toBe(false) // palette open → view inert
    const { resetOverlayState } = await import('../app/overlayStore.js')
    resetOverlayState()
    expect(await pressQ(view, false)).toBe(true) // palette closed → q closes the desk
  })

  // ── Markets ─────────────────────────────────────────────────────────────────

  it('Markets: palette top coexists with the MARKETS body in one frame', async () => {
    const { MarketsView } = await import('../components/marketsView.js')
    const { DARK_THEME } = await import('../theme.js')
    const text = await renderCoexistence(
      React.createElement(MarketsView, {
        gw: fakeGw(),
        onAsk: () => undefined,
        onClose: () => undefined,
        sessionId: '',
        t: DARK_THEME
      })
    )

    expect(text).toContain('Command palette')
    expect(text).toContain('MARKETS')
  })

  it('Markets: q is trapped while the palette is open, but closes the view otherwise', async () => {
    const { MarketsView } = await import('../components/marketsView.js')
    const { DARK_THEME } = await import('../theme.js')
    const view = (onClose: () => void) =>
      React.createElement(MarketsView, { gw: fakeGw(), onAsk: () => undefined, onClose, sessionId: '', t: DARK_THEME })

    expect(await pressQ(view, true)).toBe(false)
    const { resetOverlayState } = await import('../app/overlayStore.js')
    resetOverlayState()
    expect(await pressQ(view, false)).toBe(true)
  })

  // ── Warnings / Alerts ────────────────────────────────────────────────────────

  it('Warnings: palette top coexists with the WARNINGS body in one frame', async () => {
    const { AlertsView } = await import('../components/alertsView.js')
    const { DARK_THEME } = await import('../theme.js')
    const text = await renderCoexistence(
      React.createElement(AlertsView, { gw: fakeGw(), onClose: () => undefined, sessionId: '', t: DARK_THEME })
    )

    expect(text).toContain('Command palette')
    expect(text).toContain('WARNINGS')
  })

  it('Warnings: q is trapped while the palette is open, but closes the view otherwise', async () => {
    const { AlertsView } = await import('../components/alertsView.js')
    const { DARK_THEME } = await import('../theme.js')
    const view = (onClose: () => void) =>
      React.createElement(AlertsView, { gw: fakeGw(), onClose, sessionId: '', t: DARK_THEME })

    expect(await pressQ(view, true)).toBe(false)
    const { resetOverlayState } = await import('../app/overlayStore.js')
    resetOverlayState()
    expect(await pressQ(view, false)).toBe(true)
  })
})
