import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { GatewayClient } from '../gatewayClient.js'
import { PROTOCOL_VERSION } from '../protocol/generated.js'

interface ListenerEntry {
  callback: (event: any) => void
  once: boolean
}

class FakeWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  static instances: FakeWebSocket[] = []

  readyState = FakeWebSocket.CONNECTING
  sent: string[] = []
  readonly url: string
  private listeners = new Map<string, ListenerEntry[]>()

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  static reset() {
    FakeWebSocket.instances = []
  }

  addEventListener(type: string, callback: (event: any) => void, options?: unknown) {
    const once =
      typeof options === 'object' &&
      options !== null &&
      'once' in options &&
      Boolean((options as { once?: unknown }).once)

    const entries = this.listeners.get(type) ?? []

    entries.push({ callback, once })
    this.listeners.set(type, entries)
  }

  removeEventListener(type: string, callback: (event: any) => void) {
    const entries = this.listeners.get(type)

    if (!entries) {
      return
    }

    this.listeners.set(
      type,
      entries.filter(entry => entry.callback !== callback)
    )
  }

  send(payload: string) {
    if (this.readyState !== FakeWebSocket.OPEN) {
      throw new Error('socket not open')
    }

    this.sent.push(payload)
  }

  close(code = 1000) {
    if (this.readyState === FakeWebSocket.CLOSED) {
      return
    }

    this.readyState = FakeWebSocket.CLOSED
    this.emit('close', { code })
  }

  open() {
    this.readyState = FakeWebSocket.OPEN
    this.emit('open', {})
  }

  message(data: string) {
    this.emit('message', { data })
  }

  private emit(type: string, event: any) {
    const entries = [...(this.listeners.get(type) ?? [])]

    for (const entry of entries) {
      entry.callback(event)

      if (entry.once) {
        this.removeEventListener(type, entry.callback)
      }
    }
  }
}

describe('GatewayClient websocket attach mode', () => {
  const originalWebSocket = globalThis.WebSocket

  const envKeys = [
    'SUPERFORECASTING_AGENT_TUI_GATEWAY_URL',
    'FORECAST_TUI_GATEWAY_URL',
    'HERMES_TUI_GATEWAY_URL',
    'SUPERFORECASTING_AGENT_TUI_SIDECAR_URL',
    'FORECAST_TUI_SIDECAR_URL',
    'HERMES_TUI_SIDECAR_URL'
  ] as const

  let originalEnv: Record<(typeof envKeys)[number], string | undefined>

  beforeEach(() => {
    originalEnv = {} as Record<(typeof envKeys)[number], string | undefined>

    for (const key of envKeys) {
      originalEnv[key] = process.env[key]
      delete process.env[key]
    }

    FakeWebSocket.reset()
    ;(globalThis as { WebSocket?: unknown }).WebSocket = FakeWebSocket as unknown as typeof WebSocket
  })

  afterEach(() => {
    for (const key of envKeys) {
      if (originalEnv[key] === undefined) {
        delete process.env[key]
      } else {
        process.env[key] = originalEnv[key]
      }
    }

    FakeWebSocket.reset()

    if (originalWebSocket) {
      globalThis.WebSocket = originalWebSocket
    } else {
      delete (globalThis as { WebSocket?: unknown }).WebSocket
    }
  })

  it('waits for websocket open and resolves RPC requests', async () => {
    process.env.HERMES_TUI_GATEWAY_URL = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient()

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    const req = gw.request<{ ok: boolean }>('session.create', { cols: 80 })

    expect(gatewaySocket.sent).toHaveLength(0)
    gatewaySocket.open()
    await vi.waitFor(() => expect(gatewaySocket.sent).toHaveLength(1))

    const frame = JSON.parse(gatewaySocket.sent[0] ?? '{}') as { id: string; method: string }
    expect(frame.method).toBe('session.create')

    gatewaySocket.message(JSON.stringify({ id: frame.id, jsonrpc: '2.0', result: { ok: true } }))
    await expect(req).resolves.toEqual({ ok: true })

    gw.kill()
  })

  it('accepts forecast-native websocket attach aliases', async () => {
    process.env.FORECAST_TUI_GATEWAY_URL = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient()

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    const req = gw.request<{ ok: boolean }>('session.create', { cols: 80 })

    gatewaySocket.open()
    await vi.waitFor(() => expect(gatewaySocket.sent).toHaveLength(1))

    const frame = JSON.parse(gatewaySocket.sent[0] ?? '{}') as { id: string }
    gatewaySocket.message(JSON.stringify({ id: frame.id, jsonrpc: '2.0', result: { ok: true } }))
    await expect(req).resolves.toEqual({ ok: true })

    gw.kill()
  })

  // ── A4 version handshake ─────────────────────────────────────────────────
  const ready = (payload: unknown): string =>
    JSON.stringify({ jsonrpc: '2.0', method: 'event', params: { type: 'gateway.ready', payload } })

  it('warns (once, never throws) when gateway.ready advertises a mismatched protocol_version', () => {
    process.env.HERMES_TUI_GATEWAY_URL = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient()

    gw.start()
    const sock = FakeWebSocket.instances[0]!
    sock.open()

    sock.message(ready({ protocol_version: 999 }))
    sock.message(ready({ protocol_version: 999 })) // second frame must NOT re-warn

    const tail = gw.getLogTail(50)
    expect(tail).toContain('[protocol]')
    expect(tail).toContain('gateway wire version 999')
    // warn-once: exactly one occurrence
    expect(tail.split('gateway wire version 999').length - 1).toBe(1)

    gw.kill()
  })

  it('does not warn when the advertised protocol_version matches or is absent', () => {
    process.env.HERMES_TUI_GATEWAY_URL = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient()

    gw.start()
    const sock = FakeWebSocket.instances[0]!
    sock.open()

    sock.message(ready({})) // older gateway: no protocol_version → tolerated
    sock.message(ready({ protocol_version: PROTOCOL_VERSION })) // matching → silent

    expect(gw.getLogTail(50)).not.toContain('gateway wire version')

    gw.kill()
  })

  it('mirrors event frames to sidecar websocket when configured', async () => {
    process.env.HERMES_TUI_GATEWAY_URL = 'ws://gateway.test/api/ws?token=abc'
    process.env.HERMES_TUI_SIDECAR_URL = 'ws://gateway.test/api/pub?token=abc&channel=demo'

    const gw = new GatewayClient()
    const seen: string[] = []

    gw.on('event', ev => seen.push(ev.type))
    gw.start()

    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))

    const sidecarSocket = FakeWebSocket.instances[1]!

    sidecarSocket.open()
    gw.drain()

    const eventFrame = JSON.stringify({
      jsonrpc: '2.0',
      method: 'event',
      params: { type: 'tool.start', payload: { tool_id: 't1' } }
    })

    gatewaySocket.message(eventFrame)

    expect(seen).toContain('tool.start')
    expect(sidecarSocket.sent).toContain(eventFrame)

    gw.kill()
  })

  // A closed socket is a CRASH, not a quit — so it now enters the bounded
  // reconnect ladder instead of going straight to a terminal `exit`. The desk
  // used to be told "gateway exited" and left there with no way back; see
  // gatewayRecovery.test.ts for the ladder itself.
  it('treats an attached-socket close as recoverable, then exits once the ladder is spent', () => {
    process.env.HERMES_TUI_GATEWAY_URL = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient()
    const exits: Array<null | number> = []
    const reconnects: { attempt: number }[] = []

    gw.on('exit', code => exits.push(code))
    gw.on('reconnecting', info => reconnects.push(info))
    gw.start()

    const gatewaySocket = FakeWebSocket.instances[0]!

    gatewaySocket.open()
    gw.drain()
    gatewaySocket.close(1011)

    // Recoverable: a respawn is scheduled, nothing terminal has been announced.
    expect(reconnects).toHaveLength(1)
    expect(exits).toEqual([])
    expect(gw.isRestartPending()).toBe(true)

    // With the budget already spent, the same close is terminal and carries the
    // close code through unchanged.
    const spent = new GatewayClient()

    const spentExits: Array<null | number> = []

    ;(spent as unknown as { restartAttempt: number }).restartAttempt = spent.maxRestarts
    spent.on('exit', code => spentExits.push(code))
    spent.start()

    const spentSocket = FakeWebSocket.instances[1]!

    spentSocket.open()
    spent.drain()
    spentSocket.close(1011)

    expect(spentExits).toEqual([1011])

    gw.kill()
    spent.kill()
  })

  it('rejects pending RPCs with websocket wording when the attached socket closes', async () => {
    process.env.HERMES_TUI_GATEWAY_URL = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient()

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!

    gatewaySocket.open()
    gw.drain()

    const req = gw.request('session.create', {})
    await vi.waitFor(() => expect(gatewaySocket.sent.length).toBeGreaterThan(0))

    gatewaySocket.close(1011)

    await expect(req).rejects.toThrow(/gateway websocket closed \(1011\)/)
  })

  it('rejects pending RPCs when kill() closes the attached websocket', async () => {
    process.env.HERMES_TUI_GATEWAY_URL = 'ws://gateway.test/api/ws?token=abc'
    const gw = new GatewayClient()

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!

    gatewaySocket.open()
    gw.drain()

    const req = gw.request('session.create', {})
    await vi.waitFor(() => expect(gatewaySocket.sent.length).toBeGreaterThan(0))

    gw.kill()

    await expect(req).rejects.toThrow(/gateway closed/)
  })

  it('reattaches when HERMES_TUI_GATEWAY_URL rotates between requests', async () => {
    process.env.HERMES_TUI_GATEWAY_URL = 'ws://gateway-old.test/api/ws?token=abc'
    const gw = new GatewayClient()

    gw.start()
    const firstSocket = FakeWebSocket.instances[0]!

    firstSocket.open()
    gw.drain()

    const stale = gw.request('session.create', {})
    await vi.waitFor(() => expect(firstSocket.sent.length).toBeGreaterThan(0))

    process.env.HERMES_TUI_GATEWAY_URL = 'ws://gateway-new.test/api/ws?token=xyz'
    const next = gw.request('session.create', {})

    await expect(stale).rejects.toThrow(/gateway attach url changed/)
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))

    const secondSocket = FakeWebSocket.instances[1]!
    expect(secondSocket.url).toContain('gateway-new.test')

    secondSocket.open()
    await vi.waitFor(() => expect(secondSocket.sent.length).toBeGreaterThan(0))

    const frame = JSON.parse(secondSocket.sent[0] ?? '{}') as { id: string }
    secondSocket.message(JSON.stringify({ id: frame.id, jsonrpc: '2.0', result: { ok: true } }))

    await expect(next).resolves.toEqual({ ok: true })
    gw.kill()
  })

  it('redacts query string secrets in attach failure logs and events', () => {
    process.env.HERMES_TUI_GATEWAY_URL = 'ws://gateway.test/api/ws?token=hunter2&channel=secret'
    delete (globalThis as { WebSocket?: unknown }).WebSocket

    const gw = new GatewayClient()
    const stderrLines: string[] = []

    gw.on('event', ev => {
      if (ev.type === 'gateway.stderr' && typeof ev.payload?.line === 'string') {
        stderrLines.push(ev.payload.line)
      }
    })
    gw.start()
    gw.drain()

    expect(stderrLines.length).toBeGreaterThan(0)

    for (const line of stderrLines) {
      expect(line).not.toContain('hunter2')
      expect(line).not.toContain('channel=secret')
    }

    expect(gw.getLogTail(20)).not.toContain('hunter2')
    expect(gw.getLogTail(20)).not.toContain('channel=secret')

    gw.kill()
  })

  it('redacts attach URL secrets when the WebSocket constructor throws', () => {
    const secretUrl = 'ws://gateway.test/api/ws?token=hunter2&channel=secret'

    process.env.HERMES_TUI_GATEWAY_URL = secretUrl
    ;(globalThis as { WebSocket?: unknown }).WebSocket = class ThrowingWebSocket extends FakeWebSocket {
      constructor(url: string) {
        throw new TypeError(`Invalid URL: ${url}`)
      }
    } as unknown as typeof WebSocket

    const gw = new GatewayClient()

    gw.start()
    gw.drain()

    const tail = gw.getLogTail(20)
    expect(tail).not.toContain('hunter2')
    expect(tail).not.toContain('channel=secret')
    expect(tail).not.toContain(secretUrl)
    expect(tail).toContain('ws://gateway.test/api/ws?***')

    gw.kill()
  })

  it('redacts sidecar URL secrets when the WebSocket constructor throws', async () => {
    const sidecarUrl = 'ws://gateway.test/api/pub?token=hunter2&channel=secret'

    process.env.HERMES_TUI_GATEWAY_URL = 'ws://gateway.test/api/ws?token=abc'
    process.env.HERMES_TUI_SIDECAR_URL = sidecarUrl
    ;(globalThis as { WebSocket?: unknown }).WebSocket = class ThrowingSidecarWebSocket extends FakeWebSocket {
      constructor(url: string) {
        if (url.includes('/api/pub')) {
          throw new TypeError(`Invalid URL: ${url}`)
        }

        super(url)
      }
    } as unknown as typeof WebSocket

    const gw = new GatewayClient()

    gw.start()
    const gatewaySocket = FakeWebSocket.instances[0]!
    gatewaySocket.open()
    await vi.waitFor(() => expect(gw.getLogTail(20)).toContain('[sidecar] failed to connect'))

    const tail = gw.getLogTail(20)
    expect(tail).not.toContain('hunter2')
    expect(tail).not.toContain('channel=secret')
    expect(tail).not.toContain(sidecarUrl)
    expect(tail).toContain('ws://gateway.test/api/pub?***')

    gw.kill()
  })

  it('redacts user-info credentials even on URLs the WHATWG parser rejects', () => {
    // Port 99999 is outside the WHATWG URL parser's valid 0–65535
    // range and survives `.trim()`, so the fixture deterministically
    // exercises `redactUrl()`'s fallback branch across Node versions.
    // (An earlier `%zz` user-info fixture did NOT actually throw in
    // recent Node — WHATWG accepts malformed percent escapes there —
    // which silently routed the test through the structured-URL path.)
    const fixture = 'ws://alice:hunter2@gateway.test:99999/api/ws?token=secret'
    expect(() => new URL(fixture)).toThrow()

    process.env.HERMES_TUI_GATEWAY_URL = fixture
    delete (globalThis as { WebSocket?: unknown }).WebSocket

    const gw = new GatewayClient()
    const stderrLines: string[] = []

    gw.on('event', ev => {
      if (ev.type === 'gateway.stderr' && typeof ev.payload?.line === 'string') {
        stderrLines.push(ev.payload.line)
      }
    })
    gw.start()
    gw.drain()

    expect(stderrLines.length).toBeGreaterThan(0)

    for (const line of stderrLines) {
      expect(line).not.toContain('alice')
      expect(line).not.toContain('hunter2')
      expect(line).not.toContain('token=secret')
    }

    const tail = gw.getLogTail(20)
    expect(tail).not.toContain('alice')
    expect(tail).not.toContain('hunter2')
    expect(tail).not.toContain('token=secret')

    gw.kill()
  })
})
