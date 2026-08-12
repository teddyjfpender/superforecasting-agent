import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { waitForText } from '../testing/settle.js'

// ── A dev-gated route must be ABSENT, not merely hidden ──────────────────────
//
// "Demo Vis" is scaffolding for the terminal chart engine, so it ships only when
// FORECAST_TUI_DEV_DEMO_VIZ is set. Off by default has to mean an operator who
// does not know the flag exists has NO way to land there: no tab, no Ctrl+G
// chord, no help entry, no other route.
//
// The gate is NAV_TABS — the single source of truth both the mouse (NavBar) and
// the keyboard (Ctrl+G → resolveViewChord → selectNavView) already funnel
// through. These tests assert that one gate from BOTH ends: with the flag off
// every entry point is inert, and with the flag on every one of them works
// exactly as it did before the gate existed.

const FLAG_ALIASES = [
  'SUPERFORECASTING_AGENT_TUI_DEV_DEMO_VIZ',
  'FORECAST_TUI_DEV_DEMO_VIZ',
  'HERMES_TUI_DEV_DEMO_VIZ'
] as const

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

/**
 * Load a FRESH module graph with the dev flag set to `alias`/`value`.
 *
 * The flag is read once at module load (the `config/env.ts` convention), so the
 * only honest way to exercise both states is to re-import the graph. Every piece
 * a test touches has to come from the SAME reset graph — `selectNavView` writes
 * to the store instance its own graph imported.
 */
const loadWithFlag = async (value?: string, alias: (typeof FLAG_ALIASES)[number] = 'FORECAST_TUI_DEV_DEMO_VIZ') => {
  for (const key of FLAG_ALIASES) {
    vi.stubEnv(key, key === alias ? (value ?? '') : '')
  }

  vi.resetModules()

  const [nav, overlay, keymaps] = await Promise.all([
    import('../app/navRoutes.js'),
    import('../app/overlayStore.js'),
    import('../content/keymaps.js')
  ])

  return { keymaps, nav, overlay }
}

/** Render the real NavBar from a freshly-loaded graph and return its text. */
const renderNavBar = async (value?: string) => {
  await loadWithFlag(value)

  const [{ renderSync }, { NavBar }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/navBar.js'),
    import('../lib/text.js')
  ])

  const sink = writeStream(200, 12)

  renderSync(React.createElement(NavBar as never, {} as never), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdout: sink.stream
  } as never)

  return stripAnsi(sink.text())
}

/**
 * Render the Help modal from a freshly-loaded graph, press Tab to expand it to
 * the exhaustive "all views" wall, and return that text. The wall is built from
 * NAV_TABS, so it is where a gated route would leak into help if the gate only
 * covered the nav bar.
 */
const renderExpandedHelp = async (value?: string) => {
  await loadWithFlag(value)
  vi.stubEnv('FORECAST_TUI_INLINE', '1')

  const [{ Box, render }, { HelpOverlay }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/helpOverlay.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(120, 44)
  const stdin = writeStream(120, 44, true)

  const instance = render(
    React.createElement(
      Box,
      { flexDirection: 'column', height: 44, width: 120 },
      React.createElement(HelpOverlay, {
        activeView: 'home',
        cols: 120,
        onClose: () => undefined,
        rows: 44,
        t: DARK_THEME
      })
    ),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  const read = () => stripAnsi(stdout.text())

  // Wait for the collapsed modal, then expand — never a fixed sleep, because a
  // frame that has not painted yet reads exactly like a frame with no Demo Vis
  // in it, and that would make the negative assertion below pass for free.
  await waitForText(read, 'Tab all views', { label: 'the collapsed Help modal' })
  stdin.stream.write('\t')
  await waitForText(read, 'Tab this view', { label: 'the expanded all-views wall' })

  const text = read()

  instance.unmount?.()

  return text
}

/** Every second key a user could type after Ctrl+G. */
const CHORD_LETTERS = 'abcdefghijklmnopqrstuvwxyz'.split('')

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('demoViz is absent while the dev flag is unset', () => {
  it('is not a NAV tab, so the top bar never offers it', async () => {
    const { nav } = await loadWithFlag()

    expect(nav.NAV_TABS.map(tab => tab.key)).not.toContain('demoViz')
    expect(nav.NAV_TABS.map(tab => tab.label)).not.toContain('Demo Vis')
    // Every OTHER route is untouched — this hides one tab, not a redesign.
    expect(nav.NAV_TABS.map(tab => tab.key)).toEqual([
      'home',
      'desk',
      'markets',
      'news',
      'messaging',
      'calendar',
      'warnings',
      'calibration',
      'obsidian',
      'agents',
      'hooks',
      'help'
    ])
  })

  it('resolves to no overlay patch, so a click cannot route there', async () => {
    const { nav, overlay } = await loadWithFlag()

    expect(nav.navPatchFor('demoViz')).toBeNull()
    expect(nav.selectNavView('demoViz')).toBe(false)
    expect(overlay.getOverlayState().demoViz).toBe(false)
  })

  it('has no Ctrl+G chord — no second key reaches it', async () => {
    const { keymaps, nav, overlay } = await loadWithFlag()

    for (const letter of CHORD_LETTERS) {
      // The exact sequence useInputHandlers runs for the second key of a chord.
      const route = keymaps.resolveViewChord(letter)

      expect(route).not.toBe('demoViz')

      if (route) {
        nav.selectNavView(route)
      }
    }

    expect(overlay.getOverlayState().demoViz).toBe(false)
  })

  it('leaves every OTHER chord working', async () => {
    const { keymaps, nav } = await loadWithFlag()

    for (const chord of keymaps.VIEW_CHORDS) {
      expect(keymaps.resolveViewChord(chord.key)).toBe(chord.nav)
      expect(nav.navPatchFor(chord.nav)).not.toBeNull()
    }
  })

  it('never becomes the active route', async () => {
    const { nav, overlay } = await loadWithFlag()

    nav.selectNavView('demoViz')
    expect(nav.activeNavKey(overlay.getOverlayState())).toBe('home')
  })

  it('does not render in the nav bar', async () => {
    const text = await renderNavBar()

    expect(text).not.toContain('Demo Vis')
    // A control that proves the bar really rendered (so the negative is real).
    expect(text).toContain('Agents')
    expect(text).toContain('Hooks')
  })

  it('does not appear in the Help modal, even in the expanded all-views wall', async () => {
    const text = await renderExpandedHelp()

    expect(text).not.toContain('Demo Vis')
    expect(text).not.toContain('chart engine')
    // The wall really did expand — neighbouring views are present.
    expect(text).toContain('Agents')
    expect(text).toContain('Hooks')
  })

  it('is not advertised in the Ctrl+G cheat-sheet line', async () => {
    const { keymaps } = await loadWithFlag()

    const chordLine = keymaps.GLOBAL_KEYS.map(([key, description]) => `${key} ${description}`).join('\n')

    expect(chordLine).toContain('Ctrl+G')
    expect(chordLine).not.toContain('Demo Vis')
  })
})

describe('demoViz works exactly as before once the dev flag is set', () => {
  it('rejoins NAV_TABS in its original slot between Agents and Hooks', async () => {
    const { nav } = await loadWithFlag('1')

    const keys = nav.NAV_TABS.map(tab => tab.key)

    expect(keys).toContain('demoViz')
    expect(keys.indexOf('demoViz')).toBe(keys.indexOf('agents') + 1)
    expect(keys.indexOf('hooks')).toBe(keys.indexOf('demoViz') + 1)
    expect(nav.NAV_TABS.find(tab => tab.key === 'demoViz')?.label).toBe('Demo Vis')
  })

  it('routes through the shared nav seam that a click and a chord both use', async () => {
    const { nav, overlay } = await loadWithFlag('1')

    expect(nav.navPatchFor('demoViz')).toMatchObject({ demoViz: true })
    expect(nav.selectNavView('demoViz')).toBe(true)
    expect(overlay.getOverlayState().demoViz).toBe(true)
    expect(nav.activeNavKey(overlay.getOverlayState())).toBe('demoViz')
  })

  it('renders in the nav bar', async () => {
    const text = await renderNavBar('1')

    expect(text).toContain('Demo Vis')
  })

  it('appears in the Help modal all-views wall with its registered rows', async () => {
    const text = await renderExpandedHelp('1')

    expect(text).toContain('Demo Vis')
    expect(text).toContain('close the view')
  })

  it('is honoured through every env alias, newest name first', async () => {
    for (const alias of FLAG_ALIASES) {
      const { nav } = await loadWithFlag('1', alias)

      expect(nav.NAV_TABS.map(tab => tab.key), `${alias} did not enable the route`).toContain('demoViz')
    }
  })

  it('accepts the same truthy vocabulary as every other TUI toggle', async () => {
    for (const value of ['1', 'true', 'yes', 'on', 'TRUE']) {
      const { nav } = await loadWithFlag(value)

      expect(nav.NAV_TABS.map(tab => tab.key), `'${value}' should enable the route`).toContain('demoViz')
    }

    for (const value of ['0', 'false', 'no', 'off', '', ' ']) {
      const { nav } = await loadWithFlag(value)

      expect(nav.NAV_TABS.map(tab => tab.key), `'${value}' should NOT enable the route`).not.toContain('demoViz')
    }
  })
})
