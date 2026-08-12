import { EventEmitter } from 'node:events'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getGatewayLink,
  markLinkLive,
  markLinkLost,
  markLinkReconnecting,
  markLinkStarting,
  resetGatewayLink,
  takeResumeSid
} from '../app/gatewayLinkStore.js'
import { buildGatewayLostSections, gatewayFailureTail, reconnectingStatus } from '../content/gatewayLost.js'
import { GatewayClient, gatewayRestartDelayMs } from '../gatewayClient.js'

// ── Gateway death is recoverable ─────────────────────────────────────────────
//
// The failure this guards: the gateway process dies, the desk keeps rendering
// normally, every subsequent RPC rejects, and the only recovery is for the
// operator to KNOW to quit and relaunch. Under the shipped deploy story (ssh →
// tmux → a desk left running for days) that reads as alive-but-dead.
//
// Three separate contracts are pinned here, because each can regress on its own:
//   1. the ladder is BOUNDED and terminates (never an infinite respawn loop),
//   2. a deliberate quit is never mistaken for a crash,
//   3. a deliberate quit actually REAPS the child instead of orphaning it.

describe('restart backoff ladder', () => {
  it('grows exponentially from 500ms and caps at 8s', () => {
    expect(gatewayRestartDelayMs(1)).toBe(500)
    expect(gatewayRestartDelayMs(2)).toBe(1000)
    expect(gatewayRestartDelayMs(3)).toBe(2000)
    expect(gatewayRestartDelayMs(4)).toBe(4000)
    expect(gatewayRestartDelayMs(5)).toBe(8000)
    // Capped — a long-lived desk must not drift into minute-long waits.
    expect(gatewayRestartDelayMs(9)).toBe(8000)
    expect(gatewayRestartDelayMs(40)).toBe(8000)
  })

  it('never returns a negative or zero-attempt delay', () => {
    expect(gatewayRestartDelayMs(0)).toBe(500)
    expect(gatewayRestartDelayMs(-3)).toBe(500)
  })
})

// ── the link store: the visible state + the session-honesty bookkeeping ──────

describe('gateway link state', () => {
  beforeEach(() => resetGatewayLink())

  it('starts as "starting" with nothing to restore', () => {
    expect(getGatewayLink().phase).toBe('starting')
    expect(takeResumeSid()).toBeNull()
  })

  it('captures the live session when the transport dies', () => {
    markLinkReconnecting({ attempt: 1, detail: 'gateway exited (1)', max: 5, nextRetryMs: 500, sid: 'sess-7' })

    const link = getGatewayLink()

    expect(link.phase).toBe('reconnecting')
    expect(link.attempt).toBe(1)
    expect(link.nextRetryMs).toBe(500)
    expect(link.resumeSid).toBe('sess-7')
  })

  it('does not lose the captured session across later attempts in the same ladder', () => {
    markLinkReconnecting({ attempt: 1, detail: 'boom', max: 5, nextRetryMs: 500, sid: 'sess-7' })
    // Attempt 2 happens with sid already nulled in the UI — it must not clobber.
    markLinkReconnecting({ attempt: 2, detail: 'boom', max: 5, nextRetryMs: 1000, sid: null })

    expect(getGatewayLink().resumeSid).toBe('sess-7')
    expect(getGatewayLink().attempt).toBe(2)
  })

  it('hands the captured session out exactly ONCE', () => {
    markLinkReconnecting({ attempt: 1, detail: 'boom', max: 5, nextRetryMs: 500, sid: 'sess-7' })

    expect(takeResumeSid()).toBe('sess-7')
    // A later cold ready must not silently re-resume a session the user has
    // since moved on from.
    expect(takeResumeSid()).toBeNull()
  })

  it('markLinkLive reports whether this ready was a RECOVERY or a cold start', () => {
    // Cold start: starting → live, not a recovery.
    expect(markLinkLive()).toBe(false)
    expect(getGatewayLink().phase).toBe('live')
    expect(getGatewayLink().restarts).toBe(0)

    // A death, then a ready: that IS a recovery, and it is counted.
    markLinkReconnecting({ attempt: 1, detail: 'boom', max: 5, nextRetryMs: 500, sid: 'sess-1' })
    expect(markLinkLive()).toBe(true)
    expect(getGatewayLink().phase).toBe('live')
    expect(getGatewayLink().restarts).toBe(1)
  })

  it('lands in a terminal "lost" state that survives until a manual retry', () => {
    markLinkReconnecting({ attempt: 5, detail: 'boom', max: 5, nextRetryMs: 8000, sid: null })
    markLinkLost({ attempts: 5, detail: 'gateway exited (1)' })

    expect(getGatewayLink().phase).toBe('lost')
    expect(getGatewayLink().attempt).toBe(5)
    expect(getGatewayLink().nextRetryMs).toBe(0)

    markLinkStarting()
    expect(getGatewayLink().phase).toBe('starting')
  })
})

// ── the terminal panel: name the failure, show what it printed ───────────────

describe('gateway lost panel', () => {
  it('keeps only the tail of the captured stderr, blank lines dropped', () => {
    const raw = ['a', '', 'b', 'c', 'd', 'e'].join('\n')

    expect(gatewayFailureTail(raw, 3)).toEqual(['c', 'd', 'e'])
    expect(gatewayFailureTail('', 5)).toEqual([])
  })

  it('surfaces the cause, the attempt count and the remedy', () => {
    const sections = buildGatewayLostSections({
      attempts: 5,
      reason: 'gateway exited (1)',
      stderrTail: 'ModuleNotFoundError: No module named yaml'
    })

    const flat = JSON.stringify(sections)

    expect(flat).toContain('5 reconnect attempts')
    expect(flat).toContain('gateway exited (1)')
    // The stderr tail is the whole reason getLogTail exists for this case.
    expect(flat).toContain('ModuleNotFoundError')
    // Every action is a `/`-prefixed command, so Panel renders them clickable.
    expect(flat).toContain('/reconnect')
    expect(flat).toContain('/logs')
  })

  it('still renders a usable panel when nothing was captured', () => {
    const sections = buildGatewayLostSections({ attempts: 0, reason: '', stderrTail: '' })
    const flat = JSON.stringify(sections)

    expect(flat).toContain('could not be restarted')
    expect(flat).toContain('/reconnect')
    expect(flat).not.toContain('Gateway stderr')
  })

  it('says how long the next retry is, in seconds', () => {
    expect(reconnectingStatus(2, 5, 1000)).toBe('gateway lost · reconnecting 2/5 in 1s')
    expect(reconnectingStatus(5, 5, 8000)).toBe('gateway lost · reconnecting 5/5 in 8s')
    // Sub-second waits never render as "in 0s".
    expect(reconnectingStatus(1, 5, 400)).toContain('in 1s')
  })
})

// ── the supervisor itself, driven through a fake child process ───────────────

class FakeProc extends EventEmitter {
  exitCode: null | number = null
  signalCode: null | string = null
  killed = false
  signals: string[] = []
  stdin = { end: vi.fn() }
  stdout = new EventEmitter()
  stderr = new EventEmitter()
  /** When true the child ignores SIGTERM — only SIGKILL reaps it. */
  wedged = false

  kill(signal?: string) {
    const sig = signal ?? 'SIGTERM'

    this.signals.push(sig)
    this.killed = true

    if (sig === 'SIGKILL' || !this.wedged) {
      this.signalCode = sig
      queueMicrotask(() => this.emit('exit', null))
    }

    return true
  }
}

describe('deliberate stop reaps the child', () => {
  let proc: FakeProc

  beforeEach(() => {
    proc = new FakeProc()
  })

  afterEach(() => vi.useRealTimers())

  const clientWith = (child: FakeProc) => {
    const gw = new GatewayClient()

    // Inject the fake child directly: spawning a real python here would make the
    // test slow and machine-dependent, and the contract under test is purely
    // "what does kill() do to the child it holds".
    ;(gw as unknown as { proc: unknown }).proc = child

    return gw
  }

  it('EOFs stdin, SIGTERMs, and RESOLVES once the child is gone', async () => {
    const gw = clientWith(proc)

    await gw.kill()

    // stdin EOF first: the gateway's main loop is `for raw in sys.stdin`, so an
    // EOF ends it without going through its signal handler at all.
    expect(proc.stdin.end).toHaveBeenCalled()
    expect(proc.signals).toContain('SIGTERM')
  })

  it('escalates to SIGKILL when the child ignores SIGTERM', async () => {
    vi.useFakeTimers()
    proc.wedged = true

    const gw = clientWith(proc)
    const reaped = gw.kill()
    let settled = false

    void reaped.then(() => {
      settled = true
    })

    // Still hanging on the grace window — the child has not gone.
    await vi.advanceTimersByTimeAsync(1000)
    expect(proc.signals).toEqual(['SIGTERM'])
    expect(settled).toBe(false)

    // Past the deadline the supervisor escalates, and the promise settles.
    await vi.advanceTimersByTimeAsync(1000)
    expect(proc.signals).toContain('SIGKILL')
    await reaped
  })

  it('always settles, even if the child never emits exit at all', async () => {
    vi.useFakeTimers()

    const deaf = new FakeProc()

    deaf.kill = (signal?: string) => {
      deaf.signals.push(signal ?? 'SIGTERM')

      return true
    }

    const gw = clientWith(deaf)
    const reaped = gw.kill()

    await vi.advanceTimersByTimeAsync(5000)
    // The floor timer guarantees the quit path can never hang on a wedged child.
    await expect(reaped).resolves.toBeUndefined()
  })

  it('resolves immediately when there is no live child', async () => {
    const gw = new GatewayClient()

    await expect(gw.kill()).resolves.toBeUndefined()
  })

  it('a deliberate stop is NEVER treated as a crash', async () => {
    const gw = clientWith(proc)
    const reconnects: unknown[] = []

    gw.on('reconnecting', info => reconnects.push(info))
    gw.drain()

    await gw.kill()
    // Let the child's own exit event land.
    await new Promise(resolve => setTimeout(resolve, 20))

    expect(reconnects).toEqual([])
    expect(gw.isRestartPending()).toBe(false)
  })
})

describe('crash supervision', () => {
  afterEach(() => vi.useRealTimers())

  const crash = (gw: GatewayClient, reason = 'gateway exited (1)') =>
    (gw as unknown as { handleTransportExit: (c: null | number, r?: string) => void }).handleTransportExit(
      1,
      reason
    )

  it('schedules a bounded ladder and then declares the link lost', async () => {
    vi.useFakeTimers()

    const gw = new GatewayClient()
    const reconnects: { attempt: number; max: number }[] = []

    const exits: unknown[] = []

    // Neutralise the real respawn: we are testing the LADDER, not spawn().
    ;(gw as unknown as { start: () => void }).start = () => undefined
    gw.on('reconnecting', info => reconnects.push(info))
    gw.on('exit', (_code, info) => exits.push(info))
    gw.drain()

    for (let i = 0; i < gw.maxRestarts; i++) {
      crash(gw)
      await vi.advanceTimersByTimeAsync(gatewayRestartDelayMs(i + 1) + 10)
    }

    expect(reconnects.map(r => r.attempt)).toEqual([1, 2, 3, 4, 5])
    expect(exits).toHaveLength(0)

    // One more death walks off the end of the ladder — TERMINAL, not a loop.
    crash(gw, 'gateway exited (1)')
    expect(exits).toHaveLength(1)
    expect(exits[0]).toMatchObject({ attempts: gw.maxRestarts, reason: 'gateway exited (1)', unexpected: true })
    expect(gw.isRestartPending()).toBe(false)

    // And it STAYS terminal: further deaths never restart the ladder.
    crash(gw)
    expect(gw.isRestartPending()).toBe(false)
  })

  it('carries the captured stderr tail into the terminal exit', () => {
    const gw = new GatewayClient()

    ;(gw as unknown as { start: () => void }).start = () => undefined
    ;(gw as unknown as { restartAttempt: number }).restartAttempt = gw.maxRestarts

    const exits: { stderrTail?: string }[] = []

    gw.on('exit', (_code, info) => exits.push(info))
    gw.drain()
    ;(gw as unknown as { pushLog: (l: string) => void }).pushLog('ModuleNotFoundError: No module named yaml')

    crash(gw)

    expect(exits[0]?.stderrTail).toContain('ModuleNotFoundError')
  })

  it('replays a startup-time death once the UI subscribes', () => {
    const gw = new GatewayClient()

    ;(gw as unknown as { start: () => void }).start = () => undefined

    // Death BEFORE drain() — the UI mounts a tick after the transport starts, so
    // without the replay the desk would sit on a silent "starting…".
    crash(gw)

    const reconnects: unknown[] = []

    gw.on('reconnecting', info => reconnects.push(info))
    expect(reconnects).toHaveLength(0)

    gw.drain()
    expect(reconnects).toHaveLength(1)
  })

  it('a manual reconnect resets the ladder so the budget is available again', async () => {
    vi.useFakeTimers()

    const gw = new GatewayClient()

    let starts = 0

    ;(gw as unknown as { start: () => void }).start = () => {
      starts += 1
    }

    ;(gw as unknown as { restartAttempt: number }).restartAttempt = gw.maxRestarts
    gw.drain()

    crash(gw) // terminal — budget spent
    expect(gw.isRestartPending()).toBe(false)

    gw.reconnect()
    expect(starts).toBe(1)
    expect((gw as unknown as { restartAttempt: number }).restartAttempt).toBe(0)

    // The full ladder is available again after the manual retry.
    const reconnects: unknown[] = []

    gw.on('reconnecting', info => reconnects.push(info))
    crash(gw)
    expect(reconnects).toHaveLength(1)
  })

  it('a transport that stayed up long enough earns its retry budget back', () => {
    const gw = new GatewayClient()

    ;(gw as unknown as { start: () => void }).start = () => undefined
    gw.drain()

    // Simulate a long-lived, healthy connection that has already burned the
    // whole ladder earlier in the session.
    ;(gw as unknown as { restartAttempt: number }).restartAttempt = gw.maxRestarts
    ;(gw as unknown as { ready: boolean }).ready = true
    ;(gw as unknown as { readyAt: number }).readyAt = Date.now() - 60 * 60_000

    const reconnects: unknown[] = []
    const exits: unknown[] = []

    gw.on('reconnecting', info => reconnects.push(info))
    gw.on('exit', (_c, info) => exits.push(info))

    crash(gw)

    // A crash after an hour of healthy use must NOT inherit an exhausted ladder.
    expect(exits).toHaveLength(0)
    expect(reconnects).toHaveLength(1)
  })

  it('a gateway that dies instantly on every launch still terminates', () => {
    const gw = new GatewayClient()

    ;(gw as unknown as { start: () => void }).start = () => undefined
    gw.drain()

    const exits: unknown[] = []

    gw.on('exit', (_c, info) => exits.push(info))

    // Ready, then dead 50ms later — over and over. The stability window is never
    // met, so attempts accumulate rather than resetting.
    for (let i = 0; i < gw.maxRestarts + 1; i++) {
      ;(gw as unknown as { ready: boolean }).ready = true
      ;(gw as unknown as { readyAt: number }).readyAt = Date.now() - 50
      crash(gw)
    }

    expect(exits).toHaveLength(1)
  })
})
