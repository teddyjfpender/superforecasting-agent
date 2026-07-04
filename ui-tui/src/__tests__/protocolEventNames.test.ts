import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { WIRE_EVENT_NAMES } from '../protocol/generated.js'

// ── the A2 grep-proof ─────────────────────────────────────────────────────────
// Goal gate: NO stringly-typed gateway event name survives in the TUI. Every
// gw.on / publish / switch-case comparison must reference a `WireEvent.<KEY>`
// constant from the generated protocol. This test IS that gate — if anyone
// reintroduces a raw `'pm.tick'` / `'review.sweep'` / … literal in a consumer,
// it fails here.

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..')

const isExcluded = (path: string): boolean =>
  path.endsWith('/protocol/generated.ts') ||
  path.includes('/__tests__/') ||
  path.endsWith('.test.ts') ||
  path.endsWith('.test.tsx')

const walk = (dir: string): string[] =>
  readdirSync(dir).flatMap(name => {
    const full = join(dir, name)

    if (statSync(full).isDirectory()) {
      return walk(full)
    }

    return /\.tsx?$/.test(full) && !isExcluded(full) ? [full] : []
  })

const SOURCES = walk(SRC).map(path => ({ path, text: readFileSync(path, 'utf8') }))

// 'error' is the ONE non-dotted event name; a global scan would collide with
// status-kind / log-level uses (`case 'error'` in icons.ts, `level: 'error'`,
// …). Its ONLY gateway-event dispatch sites are the two `switch (ev.type)`
// handlers, checked separately below.
const DOTTED = WIRE_EVENT_NAMES.filter(n => n.includes('.'))

describe('protocol event names (A2 grep-proof)', () => {
  it('registers every event name the TUI consumers dispatch', () => {
    // Sanity: the generated list is non-trivial and spans the A2 families.
    expect(DOTTED.length).toBeGreaterThan(30)
    for (const n of ['pm.tick', 'review.sweep', 'cron.fired', 'markets.model.progress', 'forecast.warnings.automode.progress']) {
      expect(WIRE_EVENT_NAMES).toContain(n)
    }
  })

  it.each(DOTTED)('has no raw "%s" string literal outside generated.ts', name => {
    const offenders = SOURCES.filter(f => f.text.includes(`'${name}'`) || f.text.includes(`"${name}"`)).map(f => f.path)

    expect(offenders, `raw '${name}' literal found — use WireEvent.<KEY>`).toEqual([])
  })

  it("has no raw 'error' event literal in the ev.type switch handlers", () => {
    const handlers = ['app/createGatewayEventHandler.ts', 'components/obsidianView.tsx']
    const rx = /case 'error':|\.type\s*(===|!==)\s*'error'/

    for (const rel of handlers) {
      const text = readFileSync(join(SRC, rel), 'utf8')

      expect(rx.test(text), `raw 'error' event dispatch in ${rel} — use WireEvent.ERROR`).toBe(false)
    }
  })
})

// ── the A4 grep-proof (the arc ENDGAME) ───────────────────────────────────────
// Goal gate: gatewayTypes.ts is thinned to a PURE re-export shim + the two
// irreducibly-TS-only aliases. NO hand-written wire-shape `interface` survives
// there — every RPC/event shape is generated from protocol/. If anyone
// reintroduces an `export interface XResponse {}` mirror instead of adding a
// pydantic model, it fails here.
describe('gatewayTypes.ts is a thin re-export shim (A4 grep-proof)', () => {
  const shim = readFileSync(join(SRC, 'gatewayTypes.ts'), 'utf8')

  it('declares NO hand-written wire-shape interface (all generated)', () => {
    const interfaces = [...shim.matchAll(/^export interface (\w+)/gm)].map(m => m[1])

    expect(interfaces, `hand-written wire interface(s) in gatewayTypes.ts — model them in protocol/`).toEqual([])
  })

  it('keeps EXACTLY the two TS-only type aliases that have no single pydantic-model form', () => {
    const aliases = [...shim.matchAll(/^export type (\w+) =/gm)].map(m => m[1]).sort()

    expect(aliases).toEqual(['CommandDispatchResponse', 'GatewayEvent'])
  })

  it('imports every re-exported wire shape from the generated protocol', () => {
    // The only value/type import sources are the generated protocol + ./types.js
    // (the app-internal composites). No sibling hand-written mirror module.
    // Match real import/export module specifiers only (a line beginning with
    // `import` / `export` / a closing `}` of a multi-line re-export) — never a
    // `from '...'` mention inside a comment.
    const froms = [...shim.matchAll(/^\s*(?:import|export|})[^\n]*from '([^']+)'/gm)].map(m => m[1])
    const external = froms.filter(f => f !== './protocol/generated.js' && f !== './types.js')

    expect(external, `gatewayTypes.ts should source shapes only from generated.js / types.js`).toEqual([])
  })
})
