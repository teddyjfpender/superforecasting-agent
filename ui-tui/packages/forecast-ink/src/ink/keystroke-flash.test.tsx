/**
 * Terminal-level "flash on every keypress" contract.
 *
 * The React layer was already reduced to ~110 B/key (03955c199), yet the
 * operator still saw the whole screen blank and repaint on each keystroke.
 * Root: whenever composer height crosses a wrap boundary (or an overlay
 * moves) the layout shifts, every transcript row moves, and the renderer
 * writes a FULL-frame repaint. On a fullReset it also emits clearTerminal
 * (ESC[2J ESC[3J ESC[H). On any terminal NOT in the DEC-2026 allowlist
 * (Apple_Terminal and friends) that repaint was written WITHOUT BSU/ESU
 * synchronized-output brackets, so the erase-then-repaint is visible — the
 * flash.
 *
 * These tests drive the REAL Ink render loop against a byte-capturing stdout
 * while forcing SYNC_OUTPUT_SUPPORTED=false (a non-allowlisted terminal), and
 * assert:
 *   1. a normal in-viewport keystroke stays incremental (no clearTerminal),
 *   2. every non-empty alt-screen frame write is bracketed in BSU/ESU, so
 *      even a full repaint / clearTerminal applies atomically — no flash —
 *      regardless of whether the terminal is in the sync allowlist.
 */
import { EventEmitter } from 'events'

import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

class FakeTty extends EventEmitter {
  chunks: string[] = []
  columns = 120
  rows = 30
  isTTY = true

  write(chunk: string | Uint8Array, cb?: (err?: Error | null) => void): boolean {
    this.chunks.push(typeof chunk === 'string' ? chunk : Buffer.from(chunk).toString('utf8'))
    cb?.()

    return true
  }
}

const tick = () => new Promise<void>(resolve => queueMicrotask(resolve))

// Far taller than the 30-row viewport, so the transcript ScrollBox clips and
// the frame fills the screen (the geometry that makes a shift a full rewrite).
const LINES = Array.from({ length: 100 }, (_, i) => `transcript line ${i + 1} lorem ipsum dolor sit amet`)

// Rebuilt per test after vi.resetModules so the module-level
// SYNC_OUTPUT_SUPPORTED is recomputed from the stubbed (non-sync) env.
async function loadHarness() {
  const { default: Ink } = await import('./ink.js')
  const { default: Box } = await import('./components/Box.js')
  const { default: ScrollBox } = await import('./components/ScrollBox.js')
  const { default: Text } = await import('./components/Text.js')
  const { SYNC_OUTPUT_SUPPORTED } = await import('./terminal.js')
  const { BSU, ESU } = await import('./termio/dec.js')
  const { ERASE_SCREEN } = await import('./termio/csi.js')

  const App = ({ composer }: { composer: string }) =>
    React.createElement(
      Box,
      { flexDirection: 'column', flexShrink: 0, height: 30, width: 120 },
      React.createElement(
        ScrollBox,
        { flexDirection: 'column', flexGrow: 1, flexShrink: 1 },
        React.createElement(
          Box,
          { flexDirection: 'column' },
          LINES.map(line => React.createElement(Text, { key: line }, line))
        )
      ),
      // width:20 so a few chars wrap the composer → composer height changes →
      // the ScrollBox resizes → layout shift → full-frame repaint.
      React.createElement(
        Box,
        { flexDirection: 'column', flexShrink: 0, width: 20 },
        React.createElement(Text, null, `> ${composer}`)
      )
    )

  const stdout = new FakeTty()

  const ink = new Ink({
    exitOnCtrlC: false,
    patchConsole: false,
    stderr: new FakeTty() as unknown as NodeJS.WriteStream,
    stdin: new FakeTty() as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream
  })

  ink.setAltScreenActive(true)

  return { ink, stdout, App, SYNC_OUTPUT_SUPPORTED, BSU, ESU, ERASE_SCREEN }
}

describe('keystroke flash: alt-screen frames apply atomically on a non-sync terminal', () => {
  beforeEach(() => {
    vi.resetModules()
    // Force isSynchronizedOutputSupported() -> false (mimic Apple_Terminal /
    // any terminal not in our allowlist). This is the environment where the
    // flash was visible.
    vi.stubEnv('TMUX', '')
    vi.stubEnv('TERM_PROGRAM', 'Apple_Terminal')
    vi.stubEnv('TERM', 'xterm-256color')
    vi.stubEnv('KITTY_WINDOW_ID', '')
    vi.stubEnv('ZED_TERM', '')
    vi.stubEnv('WT_SESSION', '')
    vi.stubEnv('VTE_VERSION', '')
  })

  it('confirms the harness runs in the non-sync regime', async () => {
    const { SYNC_OUTPUT_SUPPORTED, ink } = await loadHarness()
    expect(SYNC_OUTPUT_SUPPORTED).toBe(false)
    ink.unmount()
  })

  it('keeps a normal in-viewport keystroke incremental — no clearTerminal, tiny write', async () => {
    const { ink, stdout, App, ERASE_SCREEN } = await loadHarness()

    ink.render(React.createElement(App, { composer: '' }))
    ink.onRender()
    await tick()

    stdout.chunks = []
    ink.render(React.createElement(App, { composer: 'h' }))
    ink.onRender()
    await tick()

    const bytes = stdout.chunks.join('')
    expect(bytes.includes(ERASE_SCREEN)).toBe(false) // no full clear per key
    expect(Buffer.byteLength(bytes, 'utf8')).toBeLessThan(500) // changed cells only
  })

  it('brackets every non-empty alt-screen frame write in BSU/ESU', async () => {
    const { ink, stdout, App, BSU, ESU } = await loadHarness()

    ink.render(React.createElement(App, { composer: '' }))
    ink.onRender()
    await tick()

    // Type across a wrap boundary so at least one frame is a full-frame
    // repaint (composer grows → ScrollBox shrinks → every row shifts).
    let composer = ''

    for (let i = 0; i < 25; i++) {
      composer += 'x'
      stdout.chunks = []
      ink.render(React.createElement(App, { composer }))
      ink.onRender()
      await tick()

      const bytes = stdout.chunks.join('')

      if (bytes.length === 0) {
        continue // empty frame: nothing written, nothing to bracket
      }

      expect(bytes.startsWith(BSU)).toBe(true)
      expect(bytes.endsWith(ESU)).toBe(true)
    }

    ink.unmount()
  })

  it('wraps a fullReset (resize) repaint so the clearTerminal is atomic', async () => {
    const { ink, stdout, App, BSU, ESU, ERASE_SCREEN } = await loadHarness()

    ink.render(React.createElement(App, { composer: 'hi' }))
    ink.onRender()
    await tick()

    // A width change forces fullResetSequence_CAUSES_FLICKER — the very path
    // that emits clearTerminal (ESC[2J) + a full repaint.
    stdout.chunks = []
    stdout.columns = 100
    stdout.emit('resize')
    await tick()
    await tick()
    ink.render(React.createElement(App, { composer: 'hi' }))
    ink.onRender()
    await tick()

    const bytes = stdout.chunks.join('')
    const clearIdx = bytes.indexOf(ERASE_SCREEN)
    const bsuIdx = bytes.indexOf(BSU)
    const esuIdx = bytes.lastIndexOf(ESU)

    expect(clearIdx).toBeGreaterThanOrEqual(0) // the repaint did clear
    // The clear must sit INSIDE a synchronized-output block: BSU before it,
    // ESU after it — so the terminal applies erase+repaint as one atomic swap.
    expect(bsuIdx).toBeGreaterThanOrEqual(0)
    expect(bsuIdx).toBeLessThan(clearIdx)
    expect(esuIdx).toBeGreaterThan(clearIdx)

    ink.unmount()
  })
})
