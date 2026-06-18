// Personal Signal client for the TUI Messaging view. Talks to the same
// signal-cli HTTP daemon the gateway's Signal adapter uses (so one linked
// device / account serves both your client view and the agent bridge):
//   - JSON-RPC 2.0 over POST {httpUrl}/api/v1/rpc
//   - Server-Sent Events over GET  {httpUrl}/api/v1/events?account=<account>
//   - health check GET {httpUrl}/api/v1/check
// This is YOU messaging as yourself — no allowlist/mention filtering; every
// conversation is surfaced. The agent bridge (gateway/platforms/signal.py) is a
// separate concern that runs in the full `gateway run` daemon.

export interface SignalConfig {
  account: string
  httpUrl: string
}

export interface SignalContact {
  id: string // number (preferred) or uuid — the send recipient
  name: string
}

export interface SignalGroup {
  id: string // base64 groupId; chatId is `group:<id>`
  memberCount: number
  name: string
}

export interface SignalMessage {
  attachments: number
  author: string // sender id (number/uuid) or 'me'
  chatId: string // contact id, or `group:<id>`
  fromMe: boolean
  text: string
  timestamp: number // epoch ms
}

// ---------------------------------------------------------------------------
// Pure parsers (unit-tested; no I/O)
// ---------------------------------------------------------------------------

const str = (v: unknown): string => (typeof v === 'string' ? v : '')

const contactName = (c: Record<string, unknown>): string => {
  const profile = (c.profile as Record<string, unknown> | undefined) ?? {}
  const given = str(profile.givenName)
  const family = str(profile.familyName)
  const full = `${given} ${family}`.trim()

  return (
    str(c.name) ||
    str(c.profileName) ||
    full ||
    str(c.username) ||
    str(c.number) ||
    str(c.uuid)
  )
}

export const parseContacts = (result: unknown, selfNumber = ''): SignalContact[] => {
  if (!Array.isArray(result)) {
    return []
  }

  const self = selfNumber.trim()
  const out: SignalContact[] = []

  for (const raw of result) {
    if (!raw || typeof raw !== 'object') {
      continue
    }

    const c = raw as Record<string, unknown>
    const id = str(c.number) || str(c.uuid)

    if (!id || id === self) {
      continue // skip self / unidentifiable
    }

    out.push({ id, name: contactName(c) })
  }

  return out
}

export const parseGroups = (result: unknown): SignalGroup[] => {
  if (!Array.isArray(result)) {
    return []
  }

  const out: SignalGroup[] = []

  for (const raw of result) {
    if (!raw || typeof raw !== 'object') {
      continue
    }

    const g = raw as Record<string, unknown>
    const id = str(g.id) || str(g.groupId)

    if (!id) {
      continue
    }

    const members = Array.isArray(g.members) ? g.members.length : 0
    out.push({ id, memberCount: members, name: str(g.name) || 'Signal group' })
  }

  return out
}

const groupIdOf = (dataMessage: Record<string, unknown>): string => {
  const v2 = dataMessage.groupV2 as Record<string, unknown> | undefined
  const v1 = dataMessage.groupInfo as Record<string, unknown> | undefined

  return str(v2?.id) || str(v1?.groupId)
}

const attachmentCount = (dataMessage: Record<string, unknown>): number =>
  Array.isArray(dataMessage.attachments) ? dataMessage.attachments.length : 0

// Turn a signal-cli SSE envelope into a SignalMessage, or null if it carries no
// displayable text/attachment (receipts, typing, empty syncs, etc.). Captures
// both inbound dataMessages and this account's own sends mirrored via
// syncMessage.sentMessage (sent from your phone/other linked devices).
export const parseEnvelope = (raw: unknown, selfId = ''): null | SignalMessage => {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const top = raw as Record<string, unknown>
  const env = (top.envelope as Record<string, unknown> | undefined) ?? top
  const self = selfId.trim()

  // Outbound mirrored from another of this account's devices.
  const sync = env.syncMessage as Record<string, unknown> | undefined
  const sent = sync?.sentMessage as Record<string, unknown> | undefined

  if (sent && typeof sent === 'object') {
    const gid = groupIdOf(sent)
    const dest = str(sent.destinationNumber) || str(sent.destination)
    const chatId = gid ? `group:${gid}` : dest
    const text = str(sent.message)
    const att = attachmentCount(sent)

    if (chatId && (text || att)) {
      return {
        attachments: att,
        author: 'me',
        chatId,
        fromMe: true,
        text,
        timestamp: Number(sent.timestamp) || Number(env.timestamp) || 0
      }
    }

    return null
  }

  const data = (env.dataMessage as Record<string, unknown> | undefined) ??
    ((env.editMessage as Record<string, unknown> | undefined)?.dataMessage as Record<string, unknown> | undefined)

  if (!data || typeof data !== 'object') {
    return null
  }

  const sender = str(env.sourceNumber) || str(env.sourceUuid) || str(env.source)

  if (!sender) {
    return null
  }

  const gid = groupIdOf(data)
  const chatId = gid ? `group:${gid}` : sender
  const text = str(data.message)
  const att = attachmentCount(data)

  if (!text && !att) {
    return null
  }

  return {
    attachments: att,
    author: sender,
    chatId,
    fromMe: Boolean(self) && sender === self,
    text,
    timestamp: Number(data.timestamp) || Number(env.timestamp) || 0
  }
}

// ---------------------------------------------------------------------------
// Network (signal-cli daemon)
// ---------------------------------------------------------------------------

let rpcSeq = 0

export const signalRpc = async (
  cfg: SignalConfig,
  method: string,
  params: Record<string, unknown>,
  timeoutMs = 15000
): Promise<{ error: null | string; result: unknown }> => {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    rpcSeq += 1

    const response = await fetch(`${cfg.httpUrl.replace(/\/+$/, '')}/api/v1/rpc`, {
      body: JSON.stringify({ id: `tui_${method}_${rpcSeq}`, jsonrpc: '2.0', method, params }),
      headers: { 'Content-Type': 'application/json' },
      method: 'POST',
      signal: controller.signal
    })

    if (!response.ok) {
      return { error: `HTTP ${response.status}`, result: null }
    }

    const data = (await response.json()) as Record<string, unknown>

    if (data.error) {
      const e = data.error as Record<string, unknown>

      return { error: str(e.message) || JSON.stringify(data.error), result: null }
    }

    return { error: null, result: data.result }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)

    return { error: message.includes('aborted') ? 'timed out' : message, result: null }
  } finally {
    clearTimeout(timer)
  }
}

export const checkHealth = async (cfg: SignalConfig, timeoutMs = 8000): Promise<boolean> => {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const r = await fetch(`${cfg.httpUrl.replace(/\/+$/, '')}/api/v1/check`, { signal: controller.signal })

    return r.ok
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

export const listContacts = async (cfg: SignalConfig): Promise<SignalContact[]> => {
  const { result } = await signalRpc(cfg, 'listContacts', { account: cfg.account })

  return parseContacts(result, cfg.account)
}

export const listGroups = async (cfg: SignalConfig): Promise<SignalGroup[]> => {
  const { result } = await signalRpc(cfg, 'listGroups', { account: cfg.account })

  return parseGroups(result)
}

export const sendSignalMessage = async (
  cfg: SignalConfig,
  chatId: string,
  text: string
): Promise<{ error: null | string; timestamp: number }> => {
  const params: Record<string, unknown> = { account: cfg.account, message: text }

  if (chatId.startsWith('group:')) {
    params.groupId = chatId.slice(6)
  } else {
    params.recipient = [chatId]
  }

  const { error, result } = await signalRpc(cfg, 'send', params)
  const ts = result && typeof result === 'object' ? Number((result as Record<string, unknown>).timestamp) : 0

  return { error, timestamp: Number.isFinite(ts) ? ts : 0 }
}

// Create a new group (signal-cli `updateGroup` with no groupId). Returns the
// new base64 groupId so the caller can open it as `group:<id>`.
export const createGroup = async (
  cfg: SignalConfig,
  name: string,
  members: string[]
): Promise<{ error: null | string; groupId: string }> => {
  const { error, result } = await signalRpc(cfg, 'updateGroup', {
    account: cfg.account,
    member: members,
    name
  })

  if (error) {
    return { error, groupId: '' }
  }

  const r = (result && typeof result === 'object' ? result : {}) as Record<string, unknown>
  const groupId = str(r.groupId) || str(r.id)

  return { error: groupId ? null : 'no group id returned', groupId }
}

// Open the SSE receive stream. Calls onMessage for each parsed message and
// onStatus(connected) on connect/drop. Returns a stop() function. Auto-
// reconnects with backoff until stopped.
export const openReceiveStream = (
  cfg: SignalConfig,
  onMessage: (msg: SignalMessage) => void,
  onStatus?: (connected: boolean) => void
): (() => void) => {
  let stopped = false
  let controller: AbortController | null = null

  const run = async () => {
    let backoff = 1000

    while (!stopped) {
      controller = new AbortController()

      try {
        const url = `${cfg.httpUrl.replace(/\/+$/, '')}/api/v1/events?account=${encodeURIComponent(cfg.account)}`
        const response = await fetch(url, { headers: { Accept: 'text/event-stream' }, signal: controller.signal })

        if (!response.ok || !response.body) {
          throw new Error(`HTTP ${response.status}`)
        }

        onStatus?.(true)
        backoff = 1000
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        for (;;) {
          const { done, value } = await reader.read()

          if (done || stopped) {
            break
          }

          buffer += decoder.decode(value, { stream: true })
          let nl = buffer.indexOf('\n')

          while (nl >= 0) {
            const line = buffer.slice(0, nl).trim()
            buffer = buffer.slice(nl + 1)

            if (line.startsWith('data:')) {
              const payload = line.slice(5).trim()

              if (payload) {
                try {
                  const msg = parseEnvelope(JSON.parse(payload), cfg.account)

                  if (msg) {
                    onMessage(msg)
                  }
                } catch {
                  /* ignore malformed event */
                }
              }
            }

            nl = buffer.indexOf('\n')
          }
        }
      } catch {
        /* fall through to reconnect */
      }

      onStatus?.(false)

      if (stopped) {
        break
      }

      await new Promise(resolve => setTimeout(resolve, backoff))
      backoff = Math.min(backoff * 2, 30000)
    }
  }

  void run()

  return () => {
    stopped = true
    controller?.abort()
  }
}
