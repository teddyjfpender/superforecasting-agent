import { PassThrough } from 'stream'

import React from 'react'
import { beforeAll, describe, expect, it, vi } from 'vitest'

import { waitForQuiet } from '../testing/settle.js'

// COMPLETION-OVERLAY FLASH CONTRACT.
//
// The operator, on post-flash-fix code, still saw the whole screen flash per
// keystroke and an "API KEYS" popup paint-then-vanish while typing. Root cause:
// `complete.path` auto-fired for ANY trailing token containing '/' or '@' —
// extremely common in prose ("and/or", "3/4", "@name") — so the FloatingOverlays
// completion dropdown MOUNTED for a frame and tore down on the next space. Each
// mount/teardown repaints a ~16-row region; on a terminal without DEC-2026
// synchronized output that erase-then-repaint is the visible flash.
//
// These tests drive the REAL useCompletion matcher + the REAL AppLayout /
// FloatingOverlays with real React input state (the existing budget tests
// fabricate `completions: []` and never exercise the matcher, so this class of
// bug was invisible to them). The fix: path/@ completion is EXPLICIT-TRIGGER
// only (Tab → armPath); slash commands still auto-complete.
//
// Pinned:
//   1. plain / '/'-in-prose / '@'-in-prose NEVER mount the overlay (no api-key /
//      file chrome in any frame), and each keystroke's frame stays localized
//      (well under a ceiling, no ERASE_SCREEN) — the non-2026 belt-and-braces.
//   2. a real slash command STILL mounts + filters the menu (api-key visible).
//   3. Tab (armPath) STILL opens path completion for a path-like token — the
//      feature is preserved, just no longer auto-firing.

vi.mock('../components/conversationsRail.js', () => ({ ConversationsRail: () => null }))
vi.mock('../components/streamingAssistant.js', () => ({
  LiveTodoPanel: () => null,
  StreamingAssistant: () => null
}))
vi.mock('../components/navBar.js', () => ({ NavBar: () => null }))

process.env.FORECAST_TUI_INLINE = '1'

const ERASE_SCREEN = `${String.fromCharCode(27)}[2J`
// Steady keystrokes localize to the composer (~135 B). A completion overlay
// mount/teardown spikes to ~700+ B. This ceiling sits well between the two;
// the one-time layout settle (first typed char) is dropped before measuring.
const PER_KEYSTROKE_CEILING = 400

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

const SLASH_ITEMS = [
  { text: '/api-key', display: '/api-key', meta: 'list / set / unset data-provider API keys' },
  { text: '/agents', display: '/agents', meta: 'spawn tree' },
  { text: '/alerts', display: '/alerts', meta: 'price alerts' }
]

const buildGw = () => ({
  off: noop,
  on: noop,
  request: async (method: string, params: any) => {
    if (method === 'complete.slash') {
      const text: string = params.text ?? ''

      return { items: SLASH_ITEMS.filter(i => i.text.startsWith(text.toLowerCase())), replace_from: 1 }
    }

    if (method === 'complete.path') {
      return { items: [{ text: '@file:src/foo.ts', display: 'foo.ts', meta: 'src' }] }
    }

    return null
  },
  rpc: async () => null
})

const OVERLAY_CHROME = /api-key|foo\.ts|API KEYS/i

interface RunResult {
  frames: string[]
  mountedOverlay: boolean
  perKey: number[]
  sawErase: boolean
}

const mount = async () => {
  const [{ AppLayout }, { GatewayProvider }, ink, comp, store] = await Promise.all([
    import('../components/appLayout.js'),
    import('../app/gatewayContext.js'),
    import('@hermes/ink'),
    import('../hooks/useCompletion.js'),
    import('../app/composerTextStore.js')
  ])

  const { resetOverlayState } = await import('../app/overlayStore.js')
  const { resetUiState } = await import('../app/uiStore.js')
  resetOverlayState()
  resetUiState()
  store.resetComposerText()

  const ROWS = 30
  const COLS = 120
  const gw = buildGw()
  const gwValue = { gw, rpc: gw.rpc }
  const msg = { role: 'user' as const, text: 'hello world' }

  const transcript: any = {
    historyItems: [msg],
    railScrollRef: React.createRef(),
    scrollRef: React.createRef(),
    virtualHistory: { bottomSpacer: 0, end: 1, measureRef: () => () => {}, offsets: [0], start: 0, topSpacer: 0 },
    virtualRows: [{ index: 0, key: 'm0', msg }]
  }

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

  const drive: { arm: () => void; set: (s: string) => void } = { arm: noop, set: noop }

  const Harness = () => {
    const [input, setInput] = React.useState('')
    const { armPath, completions, compIdx } = comp.useCompletion(input, false, gw as any)
    drive.set = setInput
    drive.arm = armPath
    React.useLayoutEffect(() => {
      store.syncComposerText(input, [])
    }, [input])

    const composer: any = {
      cols: COLS, compIdx, completions, empty: input === '',
      handleTextPaste: async () => null, pagerPageSize: 10,
      queueEditIdx: null, queuedDisplay: [], submit: noop,
      updateInput: setInput, voiceRecordKey: null
    }

    return React.createElement(ink.Box, { flexDirection: 'column', height: ROWS, width: COLS },
      React.createElement(GatewayProvider, { value: gwValue },
        React.createElement(AppLayout, { actions, composer, mouseTracking: false, progress, status, transcript })))
  }

  const out = writeStream(COLS, ROWS)

  const instance: any = await ink.render(React.createElement(Harness), {
    exitOnCtrlC: false, patchConsole: false, stdin: writeStream(COLS, ROWS, true).stream, stdout: out.stream
  })

  // Wait for the real AppLayout to have PAINTED rather than sleeping a flat
  // 200ms. Same principle as everywhere else in this suite, and it also buys
  // back ~150ms per mount — this file mounts the whole layout 9 times, and its
  // per-keystroke debounce waits leave it close to the default test budget.
  await waitForQuiet(() => out.text(), { quietFor: 40, timeout: 4000 })

  return { drive, instance, out }
}

const type = async (phrase: string): Promise<RunResult> => {
  const { drive, instance, out } = await mount()
  const frames: string[] = []
  const perKey: number[] = []
  let mountedOverlay = false
  let sawErase = false
  let v = ''

  for (const ch of phrase) {
    out.clear()
    v += ch
    drive.set(v)
    await tick(90) // > the 60ms completion debounce
    const frame = out.text()
    frames.push(frame)
    perKey.push(Buffer.byteLength(frame, 'utf8'))

    if (frame.includes(ERASE_SCREEN)) {
      sawErase = true
    }

    if (OVERLAY_CHROME.test(frame)) {
      mountedOverlay = true
    }
  }

  instance.unmount?.()

  return { frames, mountedOverlay, perKey, sawErase }
}

describe('composer completion-overlay flash: real matcher + real AppLayout', () => {
  // Cold start — resolving the module graph, the first AppLayout mount and Ink's
  // first render — costs ~4s, and it lands inside whichever test runs FIRST.
  // Measured: test 1 took 5.8s while the identical test 2 took 1.6s, so the
  // first test was timing out on setup it happened to be standing next to, not
  // on its own work. Pay it once here, where a hook timeout covers it.
  beforeAll(async () => {
    const warm = await mount()

    warm.instance.unmount?.()
  }, 60_000)

  it('plain prose never mounts the completion overlay', async () => {
    const r = await type('what is the base rate')
    expect(r.mountedOverlay).toBe(false)
  })

  it('a slash mid-prose ("a/b") never mounts the overlay — no auto path completion', async () => {
    const r = await type('compare a/b split')
    expect(r.mountedOverlay).toBe(false)
  })

  it('an @-mention mid-prose ("@foo") never mounts the overlay', async () => {
    const r = await type('ping @foo now')
    expect(r.mountedOverlay).toBe(false)
  })

  it('frame damage stays localized on plain/prose keystrokes (non-2026 belt-and-braces)', async () => {
    for (const phrase of ['what is the base rate', 'compare a/b split', 'ping @foo now']) {
      const r = await type(phrase)
      expect(r.sawErase).toBe(false)

      // Drop the one-time layout settle (first typed char); every steady key
      // must stay a localized composer diff — no overlay-mount region repaint.
      for (const bytes of r.perKey.slice(1)) {
        expect(bytes).toBeLessThan(PER_KEYSTROKE_CEILING)
      }
    }
  }, 30_000)

  it('a real slash command STILL mounts the menu (api-key visible)', async () => {
    // `mountedOverlay` = some frame's diff painted the menu chrome. The
    // per-keystroke capture clears between keys, so a stably-shown row doesn't
    // reappear in later diffs — mount detection is exactly what we want here.
    const r = await type('/api-key')
    expect(r.mountedOverlay).toBe(true)
  })

  it('Tab (armPath) STILL opens path completion for a path-like token', async () => {
    const { drive, instance, out } = await mount()

    // A path-like token does NOT auto-open the menu (the whole fix).
    drive.set('read @foo')
    await tick(90)
    expect(OVERLAY_CHROME.test(out.text())).toBe(false)

    // The explicit Tab trigger (armPath) opens it → the dropdown mounts for the
    // token, so path completion stays fully reachable — just no longer flashing
    // itself onto the screen on every keystroke of ordinary prose.
    out.clear()
    drive.arm()
    await tick(90)
    expect(OVERLAY_CHROME.test(out.text())).toBe(true)

    instance.unmount?.()
  })
})
