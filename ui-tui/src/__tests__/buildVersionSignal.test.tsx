import { PassThrough } from 'stream'

import React from 'react'
import { beforeEach, describe, expect, it } from 'vitest'

import type { BuildInfoPayload } from '../gatewayTypes.js'
import {
  buildSummaryLine,
  buildVersionLabel,
  isBuildStale,
  staleHeadline,
  staleRemedy
} from '../lib/buildInfo.js'

// ── The version + staleness signal ────────────────────────────────────────────
//
// Pins the whole path: the pure formatters, the two surfaces that render them
// (Home hero + Help overlay), and the store reducer that feeds both from
// gateway.ready / session.info. The regression being guarded is real — an
// operator ran a pipx-installed v0.17.0 for three weeks against a v0.19.0 repo
// because the TUI never named its own build.

const FRESH: BuildInfoPayload = {
  install_method: 'git',
  latest_version: '0.19.0',
  release_date: '2026.7.24',
  stale: false,
  version: '0.19.0'
}

const STALE: BuildInfoPayload = {
  behind: -1,
  install_method: 'pip',
  latest_version: '0.19.0',
  release_date: '2026.6.30',
  remedy: 'curl -fsSL https://example.invalid/install.sh | bash',
  stale: true,
  version: '0.17.0'
}

// What a box with no network (or a cold cache) actually receives: the version
// alone. Nothing else resolved, and crucially no error state.
const OFFLINE: BuildInfoPayload = { release_date: '2026.7.24', version: '0.19.0' }

describe('buildInfo formatters', () => {
  it('labels the version, with the release date when the build stamped one', () => {
    expect(buildVersionLabel(FRESH)).toBe('v0.19.0 (2026.7.24)')
    expect(buildVersionLabel({ version: '0.19.0' })).toBe('v0.19.0')
  })

  it('renders nothing at all when no build has landed yet', () => {
    for (const empty of [null, undefined, {} as BuildInfoPayload]) {
      expect(buildVersionLabel(empty)).toBe('')
      expect(buildSummaryLine(empty)).toBe('')
      expect(staleHeadline(empty)).toBe('')
      expect(isBuildStale(empty)).toBe(false)
    }
  })

  it('NEVER recomputes staleness client-side — it only echoes the server verdict', () => {
    // Older running version than "latest", but the server said not stale: the
    // TUI must not second-guess it (the server knows the install lane).
    expect(isBuildStale({ latest_version: '9.9.9', stale: false, version: '0.1.0' })).toBe(false)
    // ...and equally, a verdict with no versions to compare is still honoured.
    expect(isBuildStale({ stale: true, version: '0.1.0' })).toBe(true)
  })

  it('names both versions in the stale headline, and stays honest without them', () => {
    expect(staleHeadline(STALE)).toBe('Update available — running v0.17.0, latest is v0.19.0')
    expect(staleHeadline({ behind: 4, stale: true, version: '0.17.0' })).toBe(
      'Update available — running v0.17.0, 4 commits behind'
    )
    expect(staleHeadline({ behind: 1, stale: true, version: '0.17.0' })).toContain('1 commit behind')
    // behind = -1 means "behind, but the count is unknowable" — never print -1.
    expect(staleHeadline({ behind: -1, stale: true, version: '0.17.0' })).toBe('Update available — running v0.17.0')
  })

  it('surfaces the remedy only when stale', () => {
    expect(staleRemedy(STALE)).toBe(STALE.remedy)
    expect(staleRemedy({ ...FRESH, remedy: 'do not show me' })).toBe('')
  })

  it('summarises to one dense line for the help overlay', () => {
    expect(buildSummaryLine(FRESH)).toBe('v0.19.0 (2026.7.24)')
    expect(buildSummaryLine(STALE)).toBe('v0.17.0 (2026.6.30) · update available: v0.19.0')
    expect(buildSummaryLine({ stale: true, version: '0.17.0' })).toBe('v0.17.0 · update available')
  })

  it('degrades silently offline — a version, no warning, no error text', () => {
    expect(buildVersionLabel(OFFLINE)).toBe('v0.19.0 (2026.7.24)')
    expect(isBuildStale(OFFLINE)).toBe(false)
    expect(buildSummaryLine(OFFLINE)).toBe('v0.19.0 (2026.7.24)')
    expect(staleRemedy(OFFLINE)).toBe('')
  })
})

// ── The store reducer that feeds both surfaces ────────────────────────────────

describe('build state on the wire', () => {
  beforeEach(async () => {
    const { resetUiState } = await import('../app/uiStore.js')
    resetUiState()
  })

  it('starts null, and a build-less (older) gateway leaves it null', async () => {
    const { $uiBuild, patchUiState } = await import('../app/uiStore.js')

    expect($uiBuild.get()).toBeNull()
    // The reducer's guard: only a payload carrying a version is ever stored.
    patchUiState({ build: null })
    expect($uiBuild.get()).toBeNull()
  })

  it('session.info can UPGRADE a cold-cache verdict without blanking it', async () => {
    const { $uiBuild, patchUiState } = await import('../app/uiStore.js')

    // gateway.ready: version only (background check had not landed yet).
    patchUiState({ build: OFFLINE })
    expect(isBuildStale($uiBuild.get())).toBe(false)
    expect(buildVersionLabel($uiBuild.get())).toBe('v0.19.0 (2026.7.24)')

    // session.info a moment later: the check finished and says we're behind.
    patchUiState({ build: STALE })
    expect(isBuildStale($uiBuild.get())).toBe(true)
    expect(staleHeadline($uiBuild.get())).toContain('latest is v0.19.0')
  })
})

// ── The two surfaces ──────────────────────────────────────────────────────────

const writeStream = (columns: number, rows: number, isTTY = false) => {
  const stream = new PassThrough() as PassThrough & { columns: number; isTTY: boolean; rows: number }
  let output = ''

  Object.assign(stream, {
    columns,
    isTTY,
    rows,
    ref: () => stream,
    setRawMode: () => undefined,
    unref: () => stream
  })
  stream.on('data', chunk => {
    output += chunk.toString()
  })

  return { stream, text: () => output }
}

// HelpOverlay owns the keyboard (useInput), so it needs a raw-mode-capable
// stdin — hence the TTY fake rather than a bare PassThrough.
const paint = async (node: React.ReactElement, cols = 110, rows = 34): Promise<string> => {
  const { render } = await import('@superforecasting/ink')
  const stdout = writeStream(cols, rows)
  const stdin = writeStream(cols, rows, true)
  const stderr = writeStream(cols, rows)

  const inst = render(node, {
    exitOnCtrlC: false,
    patchConsole: false,
    stderr: stderr.stream as never,
    stdin: stdin.stream as never,
    stdout: stdout.stream as never
  })

  return new Promise(res =>
    setTimeout(() => {
      inst.unmount?.()
      res(stdout.text())
    }, 90)
  )
}

// HelpOverlay renders through ModalOverlay, which positions itself absolutely —
// it needs a SIZED body container beneath it to lay out against (the same
// framing modalOverlay.test.tsx uses).
const paintModal = async (node: React.ReactElement, cols = 110, rows = 34): Promise<string> => {
  const { Box } = await import('@superforecasting/ink')

  return paint(
    React.createElement(
      Box as never,
      { flexDirection: 'column', height: rows, width: cols } as never,
      React.createElement(Box as never, { key: 'body' } as never),
      node
    ),
    cols,
    rows
  )
}

describe('HomeHero names the running build', () => {
  beforeEach(async () => {
    const { resetUiState } = await import('../app/uiStore.js')
    resetUiState()
  })

  it('appends the version to the dim context line — no extra row, no fourth status item', async () => {
    const [{ HomeHero }, { DARK_THEME }, { patchUiState }, { stripAnsi }] = await Promise.all([
      import('../components/branding.js'),
      import('../theme.js'),
      import('../app/uiStore.js'),
      import('../lib/text.js')
    ])

    patchUiState({ build: FRESH })

    const out = stripAnsi(
      await paint(React.createElement(HomeHero as never, { info: { model: 'gpt-5.5' }, maxCols: 100, t: DARK_THEME } as never))
    )

    expect(out).toContain('v0.19.0 (2026.7.24)')
    // Up to date → the hero must be quiet: no warning glyph, no remedy.
    expect(out).not.toContain('⚠')
    expect(out).not.toContain('run:')
  })

  it('shouts, with the concrete remedy, when the gateway says the build is stale', async () => {
    const [{ HomeHero }, { DARK_THEME }, { patchUiState }, { stripAnsi }] = await Promise.all([
      import('../components/branding.js'),
      import('../theme.js'),
      import('../app/uiStore.js'),
      import('../lib/text.js')
    ])

    patchUiState({ build: STALE })

    const out = stripAnsi(
      await paint(React.createElement(HomeHero as never, { info: { model: 'gpt-5.5' }, maxCols: 100, t: DARK_THEME } as never))
    )

    expect(out).toContain('⚠')
    expect(out).toContain('running v0.17.0')
    expect(out).toContain('latest is v0.19.0')
    expect(out).toContain('run:')
  })

  it('is byte-identical to the pre-version hero when no build has landed', async () => {
    const [{ HomeHero }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('../components/branding.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const out = stripAnsi(
      await paint(React.createElement(HomeHero as never, { info: { model: 'gpt-5.5' }, maxCols: 100, t: DARK_THEME } as never))
    )

    expect(out).not.toContain('v0.')
    expect(out).not.toContain('⚠')
    expect(out).toContain('Ask a forecasting question to begin')
  })
})

describe('HelpOverlay names the running build', () => {
  beforeEach(async () => {
    const { resetUiState } = await import('../app/uiStore.js')
    resetUiState()
  })

  it('shows the version on the h/? modal — the one surface reachable from every view', async () => {
    const [{ HelpOverlay }, { DARK_THEME }, { patchUiState }, { stripAnsi }] = await Promise.all([
      import('../components/helpOverlay.js'),
      import('../theme.js'),
      import('../app/uiStore.js'),
      import('../lib/text.js')
    ])

    patchUiState({ build: FRESH })

    const out = stripAnsi(
      await paintModal(
        React.createElement(HelpOverlay as never, {
          activeView: 'desk',
          cols: 110,
          onClose: () => undefined,
          rows: 34,
          t: DARK_THEME
        } as never)
      )
    )

    expect(out).toContain('v0.19.0 (2026.7.24)')
    expect(out).not.toContain('update available')
  })

  it('flags the stale build and prints the remedy', async () => {
    const [{ HelpOverlay }, { DARK_THEME }, { patchUiState }, { stripAnsi }] = await Promise.all([
      import('../components/helpOverlay.js'),
      import('../theme.js'),
      import('../app/uiStore.js'),
      import('../lib/text.js')
    ])

    patchUiState({ build: STALE })

    const out = stripAnsi(
      await paintModal(
        React.createElement(HelpOverlay as never, {
          activeView: 'home',
          cols: 110,
          onClose: () => undefined,
          rows: 34,
          t: DARK_THEME
        } as never)
      )
    )

    expect(out).toContain('update available: v0.19.0')
    expect(out).toContain('run:')
  })

  it('renders no build row at all before gateway.ready lands one', async () => {
    const [{ HelpOverlay }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('../components/helpOverlay.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const out = stripAnsi(
      await paintModal(
        React.createElement(HelpOverlay as never, {
          activeView: 'home',
          cols: 110,
          onClose: () => undefined,
          rows: 34,
          t: DARK_THEME
        } as never)
      )
    )

    expect(out).not.toContain('update available')
    expect(out).toContain('Global keys')
  })
})
