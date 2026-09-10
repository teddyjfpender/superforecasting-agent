import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it, vi } from 'vitest'

import type * as BrandingModule from '../components/branding.js'
import type * as HomeLandingModule from '../components/homeLanding.js'

// STATUS-BAR LIVENESS + ISOLATION PIN.
//
// After the render-isolation arc killed the ambient re-renders the status line
// implicitly rode, the running bar FROZE: HomeStatusBar renders a static status
// string, so once a turn starts nothing animates. This test drives the REAL
// AppLayout with the REAL HomeStatusBar and pins:
//
//   1. LIVENESS (red before the heartbeat): while busy, the terminal keeps
//      receiving frames — each ~100ms tick writes the one status row. On the
//      frozen bar the busy window emits ZERO bytes.
//   2. ISOLATION: those ticks re-render the status row ALONE — transcript
//      and navbar render +0, and the per-tick byte damage is one small row.
//   3. IDLE: the instant the turn ends the ticker stops — zero bytes, zero
//      renders across a quiet window (no background churn from this fix).
//   4. No ERASE_SCREEN (CSI 2 J) full-repaint flash on any tick.

const counts: Record<string, number> = {}

const bump = (k: string) => {
  counts[k] = (counts[k] ?? 0) + 1

  return null
}

vi.mock('../components/streamingAssistant.js', () => ({
  LiveTodoPanel: () => null,
  StreamingAssistant: () => bump('transcript')
}))
vi.mock('../components/navBar.js', () => ({ NavBar: () => bump('navbar') }))
vi.mock('../components/branding.js', async importOriginal => {
  const actual = await importOriginal<typeof BrandingModule>()

  return { ...actual, HomeHero: () => bump('hero') }
})
// Keep the REAL HomeStatusBar (the component under test); mock only the tip.
vi.mock('../components/homeLanding.js', async importOriginal => {
  const actual = await importOriginal<typeof HomeLandingModule>()

  return { ...actual, HomeTip: () => bump('tip') }
})
vi.mock('../components/todayPanel.js', () => ({ TodayPanel: () => bump('today') }))
vi.mock('../components/scheduleStrip.js', () => ({ ScheduleStrip: () => bump('schedule') }))

process.env.FORECAST_TUI_INLINE = '1'

const ERASE_SCREEN = `${String.fromCharCode(27)}[2J`
// One status row (~120 cols) + colour codes + cursor moves. The frozen-bar
// baseline was 0 bytes/tick; a full-screen re-blit would be many KB.
const PER_TICK_CEILING = 1600

const writeStream = (columns: number, rows: number, isTTY = true) => {
  const stream = new PassThrough() as any
  let output = ''
  Object.assign(stream, {
    columns, isRaw: false, isTTY, rows,
    ref: () => stream,
    setRawMode: (m: boolean) => (stream.isRaw = m),
    unref: () => stream
  })
  stream.on('data', (c: Buffer) => (output += c.toString()))

  return { clear: () => (output = ''), stream, text: () => output }
}

const tick = (ms: number) => new Promise(r => setTimeout(r, ms))

const noop = () => {}

const actions: any = {
  answerApproval: noop, answerClarify: noop, answerSecret: noop, answerSudo: noop,
  clearSelection: noop, draftCommand: noop, onModelSelect: noop, resumeById: noop,
  runCommand: noop, setStickyPrompt: noop
}

const status: any = {
  cwdLabel: '~/x', forecastPulseTick: 0, sessionStartedAt: null, showStickyPrompt: false,
  statusColor: 'white', stickyPrompt: '', turnStartedAt: null, voiceLabel: ''
}

const progress: any = { showProgressArea: false }

const buildComposer = (cols: number): any => ({
  cols, compIdx: 0, completions: [], empty: false,
  handleTextPaste: async () => null, pagerPageSize: 10,
  queueEditIdx: null, queuedDisplay: [], submit: noop, updateInput: noop, voiceRecordKey: null
})

const ROWS = 30
const COLS = 120

const setup = async () => {
  const [{ AppLayout }, { GatewayProvider }, { Box, render }, { useVirtualHistory }] = await Promise.all([
    import('../components/appLayout.js'),
    import('../app/gatewayContext.js'),
    import('@superforecasting/ink'),
    import('../hooks/useVirtualHistory.js')
  ])

  const { resetOverlayState } = await import('../app/overlayStore.js')
  const { patchUiState, resetUiState } = await import('../app/uiStore.js')
  const { patchTurnState, resetTurnState } = await import('../app/turnStore.js')
  const { stopLiveTicker } = await import('../app/liveTickStore.js')
  const store = await import('../app/composerTextStore.js')
  resetOverlayState()
  resetUiState()
  resetTurnState()
  stopLiveTicker()
  store.resetComposerText()

  return { AppLayout, Box, GatewayProvider, patchTurnState, patchUiState, render, useVirtualHistory }
}

const mountBusyApp = async () => {
  for (const k of Object.keys(counts)) {
    delete counts[k]
  }

  const items = Array.from({ length: 40 }, (_, i) => ({
    role: (i % 2 ? 'assistant' : 'user') as const,
    text: `message number ${i} with several words to force some real height here`
  }))

  const virtualRows = items.map((m, i) => ({ index: i, key: `m${i}`, msg: m }))

  const { AppLayout, Box, GatewayProvider, patchTurnState, patchUiState, render, useVirtualHistory } =
    await setup()

  const gw: any = {
    off: noop, on: noop,
    request: async () => null,
    rpc: async () => null
  }

  const gwValue = { gw, rpc: gw.rpc }
  const composer = buildComposer(COLS)

  const App = () => {
    const scrollRef = React.useRef<any>(null)
    const rows = React.useMemo(() => virtualRows, [])
    const virtualHistory = useVirtualHistory(scrollRef, rows, COLS)

    const transcript = React.useMemo(
      () => ({ historyItems: items, scrollRef, virtualHistory, virtualRows: rows }),
      [virtualHistory, rows]
    )

    return React.createElement(Box, { flexDirection: 'column', height: ROWS, width: COLS },
      React.createElement(GatewayProvider, { value: gwValue },
        React.createElement(AppLayout, {
          actions, composer, mouseTracking: false, progress, status, transcript
        })))
  }

  const out = writeStream(COLS, ROWS)

  const instance: any = await render(React.createElement(App), {
    exitOnCtrlC: false, patchConsole: false, stdin: writeStream(COLS, ROWS, true).stream, stdout: out.stream
  })

  await tick(250)

  return { instance, out, patchTurnState, patchUiState }
}

// Sample the terminal across four ~one-tick windows, returning the bytes written
// per window and whether any full-repaint flash slipped through.
const sampleWindows = async (out: { clear: () => void; text: () => string }) => {
  const perWindow: number[] = []
  let sawEraseScreen = false

  for (let i = 0; i < 4; i++) {
    out.clear()
    await tick(110)
    const frame = out.text()

    if (frame.includes(ERASE_SCREEN)) {
      sawEraseScreen = true
    }

    perWindow.push(frame.length)
  }

  return { perWindow, sawEraseScreen }
}

describe('running status bar: liveness + isolation', () => {
  it('while busy the bar animates every tick — transcript/navbar render +0', async () => {
    const { instance, patchTurnState, patchUiState, out } = await mountBusyApp()

    // Enter a real running state; a concrete activity makes the verb deterministic.
    patchTurnState({ reasoningActive: true })
    patchUiState({ busy: true, status: 'running…' })
    await tick(150) // let the heartbeat install + paint the first busy frame

    // Measure only the steady heartbeat, not the busy-flip transition.
    for (const k of Object.keys(counts)) {
      delete counts[k]
    }

    const { perWindow, sawEraseScreen } = await sampleWindows(out)

    // LIVENESS: the busy window keeps writing frames (frozen bar wrote 0 bytes).
    expect(perWindow.reduce((a, b) => a + b, 0)).toBeGreaterThan(0)
    expect(sawEraseScreen).toBe(false)

    // ISOLATION: the chrome above the status row never re-renders on a tick, and
    // each tick's damage is one small row.
    expect(counts.transcript ?? 0).toBe(0)
    expect(counts.navbar ?? 0).toBe(0)

    for (const b of perWindow) {
      expect(b).toBeLessThan(PER_TICK_CEILING)
    }

    instance.unmount?.()
  })

  it('while idle the bar is static — zero ticks, zero renders', async () => {
    const { instance, patchUiState, out } = await mountBusyApp()

    patchUiState({ busy: false, status: 'ready' })
    await tick(150) // settle the idle transition

    for (const k of Object.keys(counts)) {
      delete counts[k]
    }

    out.clear()
    await tick(400)

    // Idle = the ticker is torn down: no bytes, no chrome re-renders.
    expect(out.text().length).toBe(0)
    expect(counts.transcript ?? 0).toBe(0)
    expect(counts.navbar ?? 0).toBe(0)

    instance.unmount?.()
  })
})
