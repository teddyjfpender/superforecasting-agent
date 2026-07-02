import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'stream'

// Point the persisted-flags store at a throwaway home dir BEFORE any import that
// hydrates $firstRunHintDismissed from disk, so the tests start from a genuine
// "fresh store" and a dismissal never writes to the developer's real
// ~/.superforecasting-agent/ui_flags.json.
process.env.SUPERFORECASTING_AGENT_HOME = mkdtempSync(join(tmpdir(), 'sf-uiflags-'))

import React from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

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

const mountHint = async (columns = 80) => {
  const [{ render }, { FirstRunHint }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/branding.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(columns, 40)
  const stdin = writeStream(columns, 40, true)

  const instance = render(React.createElement(FirstRunHint, { t: DARK_THEME }), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdin: stdin.stream,
    stdout: stdout.stream
  })

  await tick(40)

  return {
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    text: () => normalize(stdout.text(), stripAnsi)
  }
}

describe('FirstRunHint — the Home landing discovery nudge', () => {
  // Reset the module-level atom + overlay flags before every test so each starts
  // from a clean, modal-free landing regardless of ordering.
  beforeEach(async () => {
    const { $firstRunHintDismissed } = await import('../lib/uiFlagsStore.js')
    const { patchOverlayState } = await import('../app/overlayStore.js')

    $firstRunHintDismissed.set(false)
    patchOverlayState({ cheatSheet: false, palette: false })
  })

  afterEach(async () => {
    const { patchOverlayState } = await import('../app/overlayStore.js')

    patchOverlayState({ cheatSheet: false, palette: false })
  })

  it('renders one line teaching Ctrl+K, the Ctrl+G chord and ? on a fresh store', async () => {
    const hint = await mountHint()
    const text = hint.text()

    expect(text).toContain('New here?')
    expect(text).toContain('Ctrl+K')
    expect(text).toContain('commands')
    // The view chord is Ctrl+G (a bare `g` was hijacked out of the composer) — the
    // hint must advertise the REAL binding, not a bare key.
    expect(text).toContain('Ctrl+G')
    expect(text).toContain('views')
    expect(text).not.toContain('g+letter')
    expect(text).toContain('all keys')
    // One line: no interior newline in the rendered hint.
    expect(text.split('\n').filter(Boolean)).toHaveLength(1)
    hint.cleanup()
  })

  it('disappears once the discovery act (Ctrl+K / ? / g-chord) calls dismissFirstRunHint', async () => {
    const { $firstRunHintDismissed, dismissFirstRunHint } = await import('../lib/uiFlagsStore.js')

    const before = await mountHint()
    expect(before.text()).toContain('New here?')
    before.cleanup()

    // dismissFirstRunHint is exactly what the ? / Ctrl+K / g-chord keypaths call.
    dismissFirstRunHint()
    expect($firstRunHintDismissed.get()).toBe(true)

    const after = await mountHint()
    expect(after.text()).not.toContain('New here?')
    after.cleanup()
  })

  it('does not render when the dismissal flag is already set', async () => {
    const { $firstRunHintDismissed } = await import('../lib/uiFlagsStore.js')

    $firstRunHintDismissed.set(true)

    const hint = await mountHint()
    expect(hint.text()).not.toContain('New here?')
    hint.cleanup()
  })

  it('does not render while the command palette is open', async () => {
    const { patchOverlayState } = await import('../app/overlayStore.js')

    patchOverlayState({ palette: true })

    const hint = await mountHint()
    expect(hint.text()).not.toContain('New here?')
    hint.cleanup()
  })
})
