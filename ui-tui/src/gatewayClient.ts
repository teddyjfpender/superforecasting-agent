import { type ChildProcess, spawn } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { existsSync } from 'node:fs'
import { delimiter, resolve } from 'node:path'
import { createInterface } from 'node:readline'

import type { GatewayEvent } from './gatewayTypes.js'
import { CircularBuffer } from './lib/circularBuffer.js'
import { tuiEnvValue } from './lib/envAlias.js'
import { runtimeEnvValue } from './lib/runtimeEnv.js'
import { PROTOCOL_VERSION, WireEvent } from './protocol/generated.js'

export const REQUIRED_HOST_CAPABILITIES = ['forecast.operation', 'session.create', 'session.resume', 'session.branch_replace', 'session.status', 'session.interrupt', 'prompt.submit'] as const

const MAX_GATEWAY_LOG_LINES = 200
const MAX_LOG_LINE_BYTES = 4096
const MAX_BUFFERED_EVENTS = 2000
const MAX_LOG_PREVIEW = 240
const STARTUP_TIMEOUT_MS = Math.max(5000, parseInt(tuiEnvValue('STARTUP_TIMEOUT_MS') || '15000', 10) || 15000)
const REQUEST_TIMEOUT_MS = Math.max(30000, parseInt(tuiEnvValue('RPC_TIMEOUT_MS') || '120000', 10) || 120000)

// ── Transport supervision ────────────────────────────────────────────────────
// A gateway death used to be terminal: the desk kept rendering, every RPC
// rejected, and the only recovery was for the operator to KNOW to quit and
// relaunch. Under the shipped deploy story (a long-lived tmux session over ssh)
// that reads as a desk that is alive and is not.
//
// `start()` was already a complete, idempotent restart — it rejects in-flight
// RPCs with 'gateway restarting', tears down the old child/socket and re-spawns
// — and `gateway.ready` already drives the full session bootstrap. Nothing ever
// called it a second time. The supervisor below is that missing caller.
//
// BOUNDED on purpose. A gateway that dies instantly on every launch (bad config,
// corrupt ledger, port conflict) must walk off the end of the ladder into a
// clear terminal state naming the failure, not respawn forever.
const parsePositive = (raw: null | string | undefined, fallback: number) => {
  const value = parseInt(raw || '', 10)

  return Number.isFinite(value) && value >= 0 ? value : fallback
}

const GATEWAY_MAX_RESTARTS = parsePositive(tuiEnvValue('GATEWAY_MAX_RESTARTS'), 5)
const GATEWAY_RESTART_BASE_MS = 500
const GATEWAY_RESTART_CAP_MS = 8000
// Uptime that EARNS BACK the retry budget. A crash after hours of healthy use
// gets the full ladder; a gateway that dies 200ms after every ready keeps
// accumulating attempts and terminates. Without this, "crashes immediately,
// always" and "crashed once after a week" are indistinguishable.
const GATEWAY_STABLE_MS = parsePositive(tuiEnvValue('GATEWAY_STABLE_MS'), 30_000)

export const gatewayRestartDelayMs = (attempt: number) =>
  Math.min(GATEWAY_RESTART_CAP_MS, GATEWAY_RESTART_BASE_MS * 2 ** Math.max(0, attempt - 1))

// ── Reaping the child on a deliberate stop ───────────────────────────────────
// `kill()` used to be fire-and-forget: it sent a bare SIGTERM and returned, and
// every caller then ran `process.exit()` on the next line. But the gateway
// installs its OWN SIGTERM handler (tui_gateway/entry.py `_log_signal`) that
// dumps every thread's stack to the crash log, unwinds atexit, and only
// os._exit(0)s after a 1s grace — measured here at 0.6–1.1s to die. Node was
// gone microseconds after the signal, so the child got reparented to init and
// lingered, each one holding the WAL-mode ledger open. On a box where the
// shipped flow is ssh → tmux → TUI, every quit-and-relaunch stranded another.
//
// So: wait for the child, and escalate if it does not go. The deadline is
// deliberately just past the gateway's own 1s grace, because an operator
// pressing `q` has to get their terminal back promptly — callers restore the
// terminal FIRST and reap after, so this wait is never visible.
const GATEWAY_KILL_GRACE_MS = parsePositive(tuiEnvValue('GATEWAY_KILL_GRACE_MS'), 1500)
// After SIGKILL the kernel reaps promptly; this is only a floor so `kill()`
// always settles even if the 'exit' event somehow never arrives.
const GATEWAY_KILL_HARD_MS = 500

/** Payload of the `reconnecting` event — everything the UI needs to say why + how long. */
export interface GatewayReconnectInfo {
  attempt: number
  delayMs: number
  max: number
  reason: string
}

/** Payload of the terminal `exit` event. */
export interface GatewayExitInfo {
  attempts: number
  reason: string
  /** Captured gateway stderr — the whole point of getLogTail for this case. */
  stderrTail: string
  /** False when the transport was stopped deliberately (quit / OOM guard). */
  unexpected: boolean
}
const WS_CONNECTING = 0
const WS_OPEN = 1
const WS_CLOSING = 2
const WS_CLOSED = 3

const truncateLine = (line: string) =>
  line.length > MAX_LOG_LINE_BYTES ? `${line.slice(0, MAX_LOG_LINE_BYTES)}… [truncated ${line.length} bytes]` : line

const resolveGatewayAttachUrl = () => {
  const raw = tuiEnvValue('GATEWAY_URL')

  return raw ? raw : null
}

const resolveSidecarUrl = () => {
  const raw = tuiEnvValue('SIDECAR_URL')

  return raw ? raw : null
}

const resolvePython = (root: string) => {
  const configured = runtimeEnvValue('PYTHON') || process.env.PYTHON?.trim()

  if (configured) {
    return configured
  }

  const venv = process.env.VIRTUAL_ENV?.trim()

  const hit = [
    venv && resolve(venv, 'bin/python'),
    venv && resolve(venv, 'Scripts/python.exe'),
    resolve(root, '.venv/bin/python'),
    resolve(root, '.venv/bin/python3'),
    resolve(root, 'venv/bin/python'),
    resolve(root, 'venv/bin/python3')
  ].find(p => p && existsSync(p))

  return hit || (process.platform === 'win32' ? 'python' : 'python3')
}

const asGatewayEvent = (value: unknown): GatewayEvent | null =>
  value && typeof value === 'object' && !Array.isArray(value) && typeof (value as { type?: unknown }).type === 'string'
    ? (value as GatewayEvent)
    : null

// Hoisted decoder: attach mode can drive high-frequency binary frames
// (tool deltas, reasoning streams) and constructing a fresh TextDecoder
// per message creates avoidable GC pressure. One module-level instance
// is fine because UTF-8 is stateless and we always pass entire frames.
const _wireDecoder = new TextDecoder()

const asWireText = (raw: unknown): string | null => {
  if (typeof raw === 'string') {
    return raw
  }

  if (raw instanceof ArrayBuffer) {
    return _wireDecoder.decode(raw)
  }

  if (ArrayBuffer.isView(raw)) {
    return _wireDecoder.decode(raw)
  }

  return null
}

// Matches `<scheme>://user:pass@host…` style user-info segments in
// otherwise-malformed URLs that the WHATWG `URL` parser can't accept.
// Used by the `redactUrl` fallback so embedded credentials are
// scrubbed from log lines even when the URL is unparseable.
const _USERINFO_FALLBACK_RE = /^([a-z][a-z0-9+.-]*:\/\/)[^/?#@]*@/i

// Connection URLs (gateway, sidecar) often carry bearer tokens in the query
// string. We surface them in user-facing log lines and the
// `gateway.start_timeout` payload, so always strip the query string and any
// embedded user-info before logging.
const redactUrl = (raw: string): string => {
  if (!raw) {
    return raw
  }

  try {
    const url = new URL(raw)
    const userInfo = url.username || url.password ? '***@' : ''
    const query = url.search ? '?***' : ''

    return `${url.protocol}//${userInfo}${url.host}${url.pathname}${query}`
  } catch {
    // WHATWG URL rejected the input. Best-effort: strip an embedded
    // `user:pass@` segment AND the query string so a malformed token
    // bearer can never escape into the log tail.
    const noUserInfo = raw.replace(_USERINFO_FALLBACK_RE, '$1***@')
    const queryIdx = noUserInfo.indexOf('?')

    return queryIdx >= 0 ? `${noUserInfo.slice(0, queryIdx)}?***` : noUserInfo
  }
}

interface Pending {
  id: string
  method: string
  reject: (e: Error) => void
  resolve: (v: unknown) => void
  timeout: ReturnType<typeof setTimeout>
}

export class GatewayClient extends EventEmitter {
  private proc: ChildProcess | null = null
  private ws: WebSocket | null = null
  private wsConnectPromise: Promise<void> | null = null
  private sidecarWs: WebSocket | null = null
  private attachUrl: null | string = null
  private sidecarUrl: null | string = null
  private reqId = 0
  private logs = new CircularBuffer<string>(MAX_GATEWAY_LOG_LINES)
  private pending = new Map<string, Pending>()
  private bufferedEvents = new CircularBuffer<GatewayEvent>(MAX_BUFFERED_EVENTS)
  private pendingExit: number | null | undefined
  private pendingExitInfo: GatewayExitInfo | undefined
  private ready = false
  private readyTimer: ReturnType<typeof setTimeout> | null = null
  private subscribed = false
  private stdoutRl: ReturnType<typeof createInterface> | null = null
  private stderrRl: ReturnType<typeof createInterface> | null = null

  // ── supervision state ──────────────────────────────────────────────────────
  // Set by kill(): a deliberate stop (the user pressing `q`, the OOM guard) must
  // never respawn. This is the single flag that separates a quit from a crash.
  private stopped = false
  private restartAttempt = 0
  private restartTimer: ReturnType<typeof setTimeout> | null = null
  // When the current transport last reached gateway.ready — the clock behind the
  // "earned back the budget" rule above. 0 while not ready.
  private readyAt = 0
  // Replayed by drain() so a death DURING startup (before the UI subscribes) is
  // not swallowed; the UI mounts a tick after the transport starts.
  private pendingReconnect: GatewayReconnectInfo | undefined

  /** Max respawns before the link is declared lost. 0 disables supervision. */
  readonly maxRestarts = GATEWAY_MAX_RESTARTS

  constructor() {
    super()
    // useInput / createGatewayEventHandler can legitimately attach many
    // listeners. Default 10-cap triggers spurious warnings.
    this.setMaxListeners(0)
  }

  private publish(ev: GatewayEvent) {
    if (ev.type === WireEvent.GATEWAY_READY) {
      if (!this.checkHostCompatibility(ev.payload)) {
        return
      }

      this.ready = true
      // Start the stability clock: uptime measured from READY (not from spawn)
      // is what tells a healthy gateway apart from one that boots and dies.
      this.readyAt = Date.now()

      if (this.readyTimer) {
        clearTimeout(this.readyTimer)
        this.readyTimer = null
      }
    }

    if (this.subscribed) {
      return void this.emit('event', ev)
    }

    this.bufferedEvents.push(ev)
  }

  private clearReadyTimer() {
    if (this.readyTimer) {
      clearTimeout(this.readyTimer)
      this.readyTimer = null
    }
  }

  private closeSidecarSocket() {
    try {
      this.sidecarWs?.close()
    } catch {
      // best effort
    } finally {
      this.sidecarWs = null
    }
  }

  private closeGatewaySocket() {
    // Null the active reference BEFORE invoking close(): real WebSocket
    // implementations dispatch the 'close' event after a microtask hop,
    // so by the time the handler runs `this.ws` should already be null
    // and the identity guard will correctly classify the close as
    // belonging to a discarded socket. (Test fakes emit synchronously,
    // so doing the swap up front is also what makes the identity guard
    // match real timing in tests.)
    const ws = this.ws
    this.ws = null
    this.wsConnectPromise = null

    try {
      ws?.close()
    } catch {
      // best effort
    }
  }

  private resetStartupState() {
    // Reject any in-flight RPCs left over from the previous transport
    // before we swap. Otherwise the old transport's stale exit/close
    // handlers (now identity-gated to ignore unrelated transports)
    // never fire `rejectPending`, leaving callers hanging on promises
    // attached to a discarded child / socket.
    this.compatibilityError = null
    this.rejectPending(new Error('gateway restarting'))
    this.ready = false
    this.bufferedEvents.clear()
    this.pendingExit = undefined
    this.stdoutRl?.close()
    this.stderrRl?.close()
    this.stdoutRl = null
    this.stderrRl = null
    this.clearReadyTimer()
  }

  private startReadyTimer(python: string, cwd: string) {
    this.readyTimer = setTimeout(() => {
      if (this.ready) {
        return
      }

      // Append the most recent gateway stderr/log lines to the timeout
      // event so users can tell apart "wrong python", "missing dep",
      // and "config parse failure" from one glance instead of having
      // to dig through `/logs`.  Capped to keep the activity feed
      // readable on slow boots.
      const stderrTail = this.getLogTail(20)

      this.pushLog(`[startup] timed out waiting for gateway.ready (python=${python}, cwd=${cwd})`)
      this.publish({
        type: WireEvent.GATEWAY_START_TIMEOUT,
        payload: { cwd, python, stderr_tail: stderrTail }
      })
    }, STARTUP_TIMEOUT_MS)
  }

  private clearRestartTimer() {
    if (this.restartTimer) {
      clearTimeout(this.restartTimer)
      this.restartTimer = null
    }
  }

  /** Emit (or buffer) the TERMINAL exit — no further respawn will be attempted. */
  private emitExit(code: null | number, info: GatewayExitInfo) {
    if (this.subscribed) {
      this.emit('exit', code, info)
    } else {
      this.pendingExit = code
      this.pendingExitInfo = info
    }
  }

  private handleTransportExit(code: null | number, reason?: string) {
    this.clearReadyTimer()
    this.closeSidecarSocket()

    const message = reason || `gateway exited${code === null ? '' : ` (${code})`}`

    this.rejectPending(new Error(message))

    if (this.compatibilityError) {
      return
    }

    const wasReady = this.ready
    const uptimeMs = this.readyAt ? Date.now() - this.readyAt : 0

    this.ready = false
    this.readyAt = 0

    // A deliberate stop (`q`, the OOM guard, teardown) is NOT a crash.
    if (this.stopped || this.maxRestarts <= 0) {
      return this.emitExit(code, {
        attempts: this.restartAttempt,
        reason: message,
        stderrTail: this.getLogTail(20),
        unexpected: !this.stopped
      })
    }

    // A transport that stayed up long enough earns its retry budget back.
    if (wasReady && uptimeMs >= GATEWAY_STABLE_MS) {
      this.restartAttempt = 0
    }

    if (this.restartAttempt >= this.maxRestarts) {
      return this.emitExit(code, {
        attempts: this.restartAttempt,
        reason: message,
        stderrTail: this.getLogTail(20),
        unexpected: true
      })
    }

    const attempt = ++this.restartAttempt

    const info: GatewayReconnectInfo = {
      attempt,
      delayMs: gatewayRestartDelayMs(attempt),
      max: this.maxRestarts,
      reason: message
    }

    if (this.subscribed) {
      this.emit('reconnecting', info)
    } else {
      this.pendingReconnect = info
    }

    this.clearRestartTimer()
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null

      if (!this.stopped) {
        this.start()
      }
    }, info.delayMs)
    // Never let a scheduled respawn hold the Node event loop open — the process
    // must still be able to exit (including entry.tsx's OOM `process.exit(137)`)
    // while a backoff is pending.
    this.restartTimer.unref?.()
  }

  private connectSidecarMirror() {
    this.closeSidecarSocket()

    if (!this.sidecarUrl) {
      return
    }

    if (typeof WebSocket === 'undefined') {
      this.pushLog(`[sidecar] WebSocket unavailable; skipping mirror to ${redactUrl(this.sidecarUrl)}`)

      return
    }

    try {
      const ws = new WebSocket(this.sidecarUrl)

      this.sidecarWs = ws
      ws.addEventListener('close', () => {
        if (this.sidecarWs === ws) {
          this.sidecarWs = null
        }
      })
      ws.addEventListener('error', () => {
        this.pushLog('[sidecar] mirror connection error')
      })
    } catch (err) {
      this.pushLog(`[sidecar] failed to connect ${redactUrl(this.sidecarUrl)} (constructor error)`)
      this.sidecarWs = null
    }
  }

  private mirrorEventToSidecar(rawFrame: string) {
    const ws = this.sidecarWs

    if (!ws || ws.readyState !== WS_OPEN) {
      return
    }

    try {
      ws.send(rawFrame)
    } catch {
      // best effort
    }
  }

  private handleWebSocketFrame(raw: unknown) {
    const text = asWireText(raw)

    if (!text) {
      return
    }

    try {
      const frame = JSON.parse(text) as Record<string, unknown>

      if (frame.method === 'event') {
        this.mirrorEventToSidecar(text)
      }

      this.dispatch(frame)
    } catch {
      const preview = text.trim().slice(0, MAX_LOG_PREVIEW) || '(empty frame)'

      this.pushLog(`[protocol] malformed websocket frame: ${preview}`)
      this.publish({ type: WireEvent.GATEWAY_PROTOCOL_ERROR, payload: { preview } })
    }
  }

  private startSpawnedGateway(root: string) {
    const python = resolvePython(root)
    const cwd = runtimeEnvValue('CWD') || root
    const env = { ...process.env }
    const pyPath = env.PYTHONPATH?.trim()

    env.PYTHONPATH = pyPath ? `${root}${delimiter}${pyPath}` : root
    this.startReadyTimer(python, cwd)
    this.proc = spawn(python, ['-m', 'tui_gateway.entry'], { cwd, env, stdio: ['pipe', 'pipe', 'pipe'] })

    const ownedProc = this.proc
    this.stdoutRl = createInterface({ input: this.proc.stdout! })
    this.stdoutRl.on('line', raw => {
      if (this.proc !== ownedProc || this.stopped) {return}

      try {
        this.dispatch(JSON.parse(raw))
      } catch {
        const preview = raw.trim().slice(0, MAX_LOG_PREVIEW) || '(empty line)'

        this.pushLog(`[protocol] malformed stdout: ${preview}`)
        this.publish({ type: WireEvent.GATEWAY_PROTOCOL_ERROR, payload: { preview } })
      }
    })

    this.stderrRl = createInterface({ input: this.proc.stderr! })
    this.stderrRl.on('line', raw => {
      if (this.proc !== ownedProc || this.stopped) {return}
      const line = truncateLine(raw.trim())

      if (!line) {
        return
      }

      this.pushLog(line)
      this.publish({ type: WireEvent.GATEWAY_STDERR, payload: { line } })
    })

    this.proc.on('error', err => {
      // Skip stale errors on an already-replaced child.
      if (this.proc !== ownedProc) {
        return
      }

      const line = `[spawn] ${err.message}`

      this.pushLog(line)
      this.publish({ type: WireEvent.GATEWAY_STDERR, payload: { line } })
      // Detach the reference up front so the late `exit` event for
      // this same child is identity-skipped (we don't want to emit
      // 'exit' twice). Then run the full teardown — clears the
      // startup timer so we don't fire a misleading
      // `gateway.start_timeout`, rejects pending RPCs, and emits or
      // queues a single `exit`.
      this.proc = null
      this.handleTransportExit(1, `gateway error: ${err.message}`)
    })
    this.proc.on('exit', code => {
      // start() can replace `this.proc` while an old child is still
      // tearing down. Skip stale exits so we don't clear the new
      // startup timer or reject newly-issued pending requests.
      if (this.proc !== ownedProc) {
        return
      }

      this.handleTransportExit(code)
    })
  }

  private startAttachedGateway(attachUrl: string) {
    const safeAttachUrl = redactUrl(attachUrl)
    this.startReadyTimer('websocket', safeAttachUrl)

    if (typeof WebSocket === 'undefined') {
      const line = `[startup] WebSocket API unavailable; cannot attach to ${safeAttachUrl}`

      this.pushLog(line)
      this.publish({ type: WireEvent.GATEWAY_STDERR, payload: { line } })
      this.handleTransportExit(1, 'gateway websocket unavailable')

      return
    }

    try {
      const ws = new WebSocket(attachUrl)
      let settled = false

      this.ws = ws

      const connectPromise = new Promise<void>((resolve, reject) => {
        ws.addEventListener(
          'open',
          () => {
            if (!settled) {
              settled = true
              resolve()
            }

            if (this.ws === ws && !this.stopped) {this.connectSidecarMirror()}
          },
          { once: true }
        )

        ws.addEventListener(
          'error',
          () => {
            if (!settled) {
              this.pushLog('[startup] gateway websocket connect error')
              settled = true
              reject(new Error('gateway websocket connection failed'))
            }
          },
          { once: true }
        )
        ws.addEventListener(
          'close',
          ev => {
            if (!settled) {
              settled = true
              reject(new Error(`gateway websocket closed (${ev.code}) during connect`))
            }
          },
          { once: true }
        )
      })

      // The connect promise is only awaited by RPCs that arrive while
      // the socket is still connecting. If no request races the open
      // (or a teardown drops the reference before anyone observes it),
      // a connect-error / early-close rejection would surface as an
      // unhandled promise rejection in Node. Attach a no-op handler to
      // ensure the rejection is always observed.
      connectPromise.catch(() => {})
      this.wsConnectPromise = connectPromise

      ws.addEventListener('message', ev => {
        if (this.ws === ws && !this.stopped) {this.handleWebSocketFrame(ev.data)}
      })
      ws.addEventListener('close', ev => {
        // Skip close events from sockets that have already been
        // replaced — start() / closeGatewaySocket() can swap `this.ws`
        // before an in-flight close lands, and we must not clear the
        // new ready timer or reject the new pending requests on behalf
        // of a stale socket.
        if (this.ws !== ws) {
          return
        }

        this.ws = null
        this.wsConnectPromise = null
        this.handleTransportExit(ev.code, `gateway websocket closed${ev.code ? ` (${ev.code})` : ''}`)
      })
      ws.addEventListener('error', () => {
        if (this.ws !== ws || this.stopped) {return}
        const line = '[gateway] websocket transport error'

        this.pushLog(line)
        this.publish({ type: WireEvent.GATEWAY_STDERR, payload: { line } })
      })
    } catch (err) {
      this.pushLog(`[startup] failed to connect websocket gateway ${safeAttachUrl} (constructor error)`)
      this.handleTransportExit(1, 'gateway websocket startup failed')
    }
  }

  start() {
    const root = runtimeEnvValue('PYTHON_SRC_ROOT') || resolve(import.meta.dirname, '../../')
    const attachUrl = resolveGatewayAttachUrl()
    const sidecarUrl = resolveSidecarUrl()

    // Starting again supersedes any scheduled respawn (a manual /reconnect
    // during a backoff wait must not double-spawn) and re-arms supervision.
    this.clearRestartTimer()
    this.stopped = false
    this.attachUrl = attachUrl
    this.sidecarUrl = sidecarUrl
    this.resetStartupState()

    if (this.proc && !this.proc.killed && this.proc.exitCode === null) {
      this.proc.kill()
    }

    this.proc = null
    this.closeGatewaySocket()
    this.closeSidecarSocket()

    if (attachUrl) {
      this.startAttachedGateway(attachUrl)

      return
    }

    this.startSpawnedGateway(root)
  }

  /**
   * Operator-driven retry from the terminal `lost` state. Resets the ladder so
   * the full budget is available again — the user asking for a reconnect is
   * fresh evidence that a retry is worth attempting.
   */
  reconnect() {
    this.restartAttempt = 0
    this.start()
  }

  /** True while a respawn is scheduled — used by tests and the `/reconnect` guard. */
  isRestartPending() {
    return this.restartTimer !== null
  }

  private dispatch(msg: Record<string, unknown>) {
    const id = msg.id as string | undefined
    const p = id ? this.pending.get(id) : undefined

    if (p) {
      this.settle(p, msg.error ? this.toError(msg.error) : null, msg.result)

      return
    }

    if (msg.method === 'event') {
      const ev = asGatewayEvent(msg.params)

      if (ev) {
        this.publish(ev)
      }
    }
  }

  private toError(raw: unknown): Error {
    const err = raw as { message?: unknown } | null | undefined

    return new Error(typeof err?.message === 'string' ? err.message : 'request failed')
  }

  private settle(p: Pending, err: Error | null, result: unknown) {
    clearTimeout(p.timeout)
    this.pending.delete(p.id)

    if (err) {
      p.reject(err)
    } else {
      p.resolve(result)
    }
  }

  private pushLog(line: string) {
    this.logs.push(truncateLine(line))
  }

  private compatibilityError: Error | null = null

  private checkHostCompatibility(payload: { protocol_version?: number | null; min_protocol_version?: number | null; capabilities?: string[] | null } | undefined) {
    if (this.compatibilityError) {
      return false
    }

    const version = payload?.protocol_version
    const minimum = payload?.min_protocol_version ?? version
    const capabilities = payload?.capabilities
    let reason = ''

    if (!Number.isInteger(version) || !Number.isInteger(minimum) || minimum! > PROTOCOL_VERSION || version! < PROTOCOL_VERSION) {
      reason = `gateway wire version ${String(minimum)}..${String(version)} is incompatible with TUI ${PROTOCOL_VERSION}`
    } else {
      const missing = REQUIRED_HOST_CAPABILITIES.filter(name => !Array.isArray(capabilities) || !capabilities.includes(name))

      if (missing.length) {
        reason = `backend is missing required capabilities: ${missing.join(', ')}`
      }
    }

    if (!reason) {
      return true
    }

    const message = `[protocol] ${reason}. Install compatible TUI and backend versions.`

    this.compatibilityError = new Error(message)
    this.ready = false
    this.pushLog(message)
    this.rejectPending(this.compatibilityError)
    void this.kill()
    this.emitExit(1, { attempts: 0, reason: message, stderrTail: this.getLogTail(20), unexpected: true })

    return false
  }

  private rejectPending(err: Error) {
    for (const p of this.pending.values()) {
      clearTimeout(p.timeout)
      p.reject(err)
    }

    this.pending.clear()
  }

  // Arrow class-field — stable identity, so `setTimeout(this.onTimeout, …, id)`
  // doesn't allocate a bound function per request.
  private onTimeout = (id: string) => {
    const p = this.pending.get(id)

    if (p) {
      this.pending.delete(id)
      p.reject(new Error(`timeout: ${p.method}`))
    }
  }

  drain() {
    this.subscribed = true

    for (const ev of this.bufferedEvents.drain()) {
      this.emit('event', ev)
    }

    // A transport that died DURING startup supervises itself before the UI has
    // subscribed; replay that so the desk shows "reconnecting" rather than
    // sitting on a silent "starting…" until the respawn happens to succeed.
    if (this.pendingReconnect !== undefined) {
      const info = this.pendingReconnect

      this.pendingReconnect = undefined
      this.emit('reconnecting', info)
    }

    if (this.pendingExit !== undefined) {
      const code = this.pendingExit
      const info = this.pendingExitInfo

      this.pendingExit = undefined
      this.pendingExitInfo = undefined
      this.emit('exit', code, info)
    }
  }

  getLogTail(limit = 20): string {
    return this.logs.tail(Math.max(1, limit)).join('\n')
  }

  private async ensureAttachedWebSocket(method: string): Promise<WebSocket> {
    if (!this.attachUrl) {
      throw new Error('gateway not running')
    }

    if (!this.ws || this.ws.readyState === WS_CLOSED || this.ws.readyState === WS_CLOSING) {
      this.start()
    }

    if (this.ws?.readyState === WS_CONNECTING) {
      try {
        await this.wsConnectPromise
      } catch (err) {
        throw err instanceof Error ? err : new Error(String(err))
      }
    }

    if (!this.ws || this.ws.readyState !== WS_OPEN) {
      throw new Error(`gateway not connected: ${method}`)
    }

    return this.ws
  }

  private requestOverWebSocket<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    return this.ensureAttachedWebSocket(method).then(
      ws =>
        new Promise<T>((resolve, reject) => {
          const id = `r${++this.reqId}`
          const timeout = setTimeout(this.onTimeout, REQUEST_TIMEOUT_MS, id)

          timeout.unref?.()
          this.pending.set(id, {
            id,
            method,
            reject,
            resolve: v => resolve(v as T),
            timeout
          })

          try {
            ws.send(JSON.stringify({ id, jsonrpc: '2.0', method, params }))
          } catch (e) {
            const pending = this.pending.get(id)

            if (pending) {
              clearTimeout(pending.timeout)
              this.pending.delete(id)
            }

            reject(e instanceof Error ? e : new Error(String(e)))
          }
        })
    )
  }

  request<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (this.compatibilityError) {
      return Promise.reject(this.compatibilityError)
    }

    const attachUrl = resolveGatewayAttachUrl()

    if (attachUrl) {
      if (this.attachUrl !== attachUrl) {
        // The env var rotated at runtime — restart the transport so
        // switching from spawned-gateway mode to attach mode also
        // tears down the old Python child. Merely closing `this.ws`
        // would leave a previously spawned gateway process alive.
        this.rejectPending(new Error('gateway attach url changed'))
        this.start()
      }

      return this.requestOverWebSocket<T>(method, params)
    }

    if (!this.proc?.stdin || this.proc.killed || this.proc.exitCode !== null) {
      this.start()
    }

    if (!this.proc?.stdin) {
      return Promise.reject(new Error('gateway not running'))
    }

    const id = `r${++this.reqId}`

    return new Promise<T>((resolve, reject) => {
      const timeout = setTimeout(this.onTimeout, REQUEST_TIMEOUT_MS, id)

      timeout.unref?.()

      this.pending.set(id, {
        id,
        method,
        reject,
        resolve: v => resolve(v as T),
        timeout
      })

      try {
        this.proc!.stdin!.write(JSON.stringify({ id, jsonrpc: '2.0', method, params }) + '\n')
      } catch (e) {
        const pending = this.pending.get(id)

        if (pending) {
          clearTimeout(pending.timeout)
          this.pending.delete(id)
        }

        reject(e instanceof Error ? e : new Error(String(e)))
      }
    })
  }

  /**
   * Reap the child process: EOF its stdin, SIGTERM, and escalate to SIGKILL if
   * it has not gone by the deadline. Always settles — a wedged child can never
   * hang the quit path.
   */
  private reapChild(proc: ChildProcess): Promise<void> {
    return new Promise<void>(resolve => {
      let settled = false
      let escalate: null | ReturnType<typeof setTimeout> = null
      let floor: null | ReturnType<typeof setTimeout> = null

      const finish = () => {
        if (settled) {
          return
        }

        settled = true

        if (escalate) {
          clearTimeout(escalate)
        }

        if (floor) {
          clearTimeout(floor)
        }

        resolve()
      }

      proc.once('exit', finish)
      proc.once('close', finish)
      proc.once('error', finish)

      // Politest stop first: the gateway's main loop is `for raw in sys.stdin`,
      // so an EOF ends it without going through the signal handler at all.
      try {
        proc.stdin?.end()
      } catch {
        // best effort
      }

      try {
        proc.kill('SIGTERM')
      } catch {
        return finish()
      }

      escalate = setTimeout(() => {
        try {
          proc.kill('SIGKILL')
        } catch {
          finish()
        }
      }, GATEWAY_KILL_GRACE_MS)

      floor = setTimeout(finish, GATEWAY_KILL_GRACE_MS + GATEWAY_KILL_HARD_MS)
      // Neither timer may hold the event loop open — a caller that decides to
      // exit early must always be able to.
      escalate.unref?.()
      floor.unref?.()
    })
  }

  /**
   * Stop the gateway deliberately (quit, teardown, the OOM guard).
   *
   * Returns a promise that settles once the child is actually gone — callers
   * that `process.exit()` afterwards MUST await it, or the child is orphaned.
   * `entry.tsx`'s graceful-exit cleanup was already written as though this were
   * awaitable; now it is.
   */
  kill(): Promise<void> {
    // THE quit-vs-crash switch. Set before tearing anything down so the child's
    // own 'exit' event — which fires as a direct result of this kill — takes the
    // deliberate-stop branch in handleTransportExit and never respawns.
    this.stopped = true
    this.clearRestartTimer()

    const proc = this.proc
    const alive = !!proc && proc.exitCode === null && proc.signalCode === null
    const reaped = alive ? this.reapChild(proc!) : Promise.resolve()

    this.closeGatewaySocket()
    this.closeSidecarSocket()
    this.clearReadyTimer()
    // The ws 'close' handler is identity-gated on `this.ws === ws`
    // and we just nulled `this.ws`, so it will short-circuit and
    // skip handleTransportExit. Reject pending RPCs explicitly so
    // attach-mode promises do not hang after an intentional kill.
    this.rejectPending(new Error('gateway closed'))

    return reaped
  }
}
