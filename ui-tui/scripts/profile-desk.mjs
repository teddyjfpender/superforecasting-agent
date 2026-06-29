#!/usr/bin/env node
/* global Buffer, console, process, setImmediate */
// Desk-render micro-benchmark (task #198). Mounts the real DeskView with a large
// (~475) workspace payload behind a fake in-process gateway, then drives cursor
// moves ('j') and measures the wall-clock + React-commit cost of the steady-state
// re-renders (the path the user feels when scrolling the list). Run BEFORE and
// AFTER an optimisation to compare. Reuses the inspector-profiler pattern from
// profile-tui.mjs. Invoke: npx tsx scripts/profile-desk.mjs
import inspector from 'node:inspector'
import { performance } from 'node:perf_hooks'
import { PassThrough } from 'node:stream'

import React from 'react'
import { render } from '@hermes/ink'
import { DeskView } from '../src/components/deskView.tsx'
import { DARK_THEME } from '../src/theme.ts'
import { clearOverlayCache } from '../src/lib/overlayCache.ts'

const session = new inspector.Session()
session.connect()
const post = (method, params = {}) =>
  new Promise((resolve, reject) => session.post(method, params, (err, result) => (err ? reject(err) : resolve(result))))

const N = Number(process.env.N || 475)
const MOVES = Number(process.env.MOVES || 120)
const COLS = Number(process.env.COLS || 140)
const ROWS = Number(process.env.ROWS || 42)

// A real EventEmitter-backed TTY stream (PassThrough) so ink's input parser and
// every reconciler listener route correctly. Counts bytes/writes for the metric.
const mkTty = (isStdin = false) => {
  const s = new PassThrough()
  Object.assign(s, {
    columns: COLS,
    rows: ROWS,
    isTTY: true,
    isRaw: false,
    setRawMode(mode) { s.isRaw = mode; return s },
    ref() { return s },
    unref() { return s }
  })
  s.bytes = 0
  s.writes = 0
  if (!isStdin) {
    s.on('data', chunk => { s.bytes += Buffer.byteLength(chunk); s.writes++ })
  }
  return s
}

const mkItem = i => {
  const base = 0.3 + 0.4 * Math.sin(i / 7)
  const history = Array.from({ length: 32 }, (_, h) => ({
    as_of: new Date(Date.UTC(2026, 4, 1 + h)).toISOString(),
    headline_probability: Math.max(0.01, Math.min(0.99, base + 0.05 * Math.sin((i + h) / 3)))
  }))
  return {
    as_of: '2026-06-28T00:00:00Z',
    close_time: '2026-12-31T00:00:00Z',
    delta: 0.01 * Math.cos(i),
    domain: 'macro',
    evidence_count: i % 5,
    freshness: `${(i % 9) + 1}d old`,
    headline_kind: i % 4 === 0 ? 'distribution' : 'probability',
    headline_probability: base,
    history,
    id: `fq_${i}`,
    next_review_at: i % 3 === 0 ? new Date(Date.now() + (i % 10) * 3600000).toISOString() : undefined,
    probability: base,
    probability_display: base.toFixed(3),
    resolution_time: '2026-12-31T00:00:00Z',
    snapshot_count: (i % 12) + 1,
    status: 'active',
    title: `Forecast question number ${i} about some macro or political outcome`,
    topics: ['macro', i % 2 === 0 ? 'elections' : 'inflation'],
    units: i % 4 === 0 ? 'percent year-over-year' : undefined
  }
}

const payload = {
  active_count: N,
  closing_soon_count: 4,
  forecasts: Array.from({ length: N }, (_, i) => mkItem(i)),
  generated_at: '2026-06-28T14:00:00Z',
  open_alert_count: 7,
  product: 'Superforecasting Agent'
}

const rpcCalls = {}
const fakeGw = {
  request: (method, params = {}) => {
    rpcCalls[method] = (rpcCalls[method] ?? 0) + 1
    if (method === 'forecast.question') return Promise.resolve({ packet: { question: { id: params.id, title: 'pkt' } } })
    return Promise.resolve(payload)
  }
}

const flush = () => new Promise(r => setImmediate(r))

async function main() {
  clearOverlayCache()
  const stdout = mkTty(false)
  const stdin = mkTty(true)
  const inst = render(React.createElement(DeskView, { gw: fakeGw, onClose: () => {}, t: DARK_THEME }), {
    stdout,
    stdin,
    stderr: stdout,
    debug: false,
    exitOnCtrlC: false,
    patchConsole: false
  })

  // Let the workspace payload resolve + the list hydrate.
  for (let i = 0; i < 5; i++) await flush()
  await new Promise(r => setTimeout(r, 80))

  // Switch to the All tab (every question listed) so the list is the full N.
  stdin.write('\t')
  stdin.write('\t')
  await flush()

  const bytes0 = stdout.bytes
  const writes0 = stdout.writes
  const q0 = rpcCalls['forecast.question'] ?? 0
  await post('Profiler.enable')
  await post('Profiler.start')
  const t0 = performance.now()
  for (let i = 0; i < MOVES; i++) {
    stdin.write(i % 2 === 0 ? 'j' : 'k')
    await flush()
  }
  const elapsed = performance.now() - t0
  const prof = await post('Profiler.stop')

  inst.unmount?.()
  inst.cleanup?.()
  session.disconnect()

  const perMove = elapsed / MOVES
  console.log(JSON.stringify({
    n: N,
    moves: MOVES,
    totalMs: Math.round(elapsed),
    perMoveMs: Number(perMove.toFixed(3)),
    stdoutBytesPerMove: Math.round((stdout.bytes - bytes0) / MOVES),
    stdoutWritesPerMove: Number(((stdout.writes - writes0) / MOVES).toFixed(2)),
    forecastQuestionRpcsDuringMoves: (rpcCalls['forecast.question'] ?? 0) - q0,
    profileNodes: prof.profile.nodes.length
  }, null, 2))
}

main().catch(err => { console.error(err); process.exit(1) })
