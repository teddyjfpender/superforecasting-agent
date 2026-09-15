import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { expect, it, vi } from 'vitest'
const streams = vi.hoisted(() => [] as Array<{ message: (m: unknown) => void; status: (s: boolean) => void }>)
vi.mock('../lib/signalClient.js', () => ({
  openReceiveStream: (_cfg: unknown, message: (m: unknown) => void, status: (s: boolean) => void) => {
    streams.push({ message, status })

    return () => {}
  }
}))
it('rejects old receiver callbacks and preserves unread/read state on disk', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'signal-recovery-'))
  vi.stubEnv('SUPERFORECASTING_AGENT_HOME', dir)

  try {
    const live = await import('../lib/signalLive.js')
    const { loadMessagingState } = await import('../lib/messagingState.js')
    const cfg = { account: '+15550000001', httpUrl: 'http://local:8080' }
    live.startSignalReceiver(cfg)

    const msg = {
      chatId: '+15550000002',
      timestamp: 10,
      text: 'hello',
      fromMe: false,
      author: 'Test',
      attachments: 0,
      files: []
    }

    streams[0]!.message(msg)
    expect(live.signalUnread().has(msg.chatId)).toBe(true)
    expect(loadMessagingState()[msg.chatId]?.unread).toBe(true)
    live.markChatRead(msg.chatId)
    expect(loadMessagingState()[msg.chatId]?.unread).toBe(false)
    live.stopSignalReceiver()
    live.startSignalReceiver(cfg)
    streams[0]!.message({ ...msg, timestamp: 11, text: 'stale callback' })
    expect(live.signalCache()[msg.chatId]).toHaveLength(1)
    streams[1]!.message({ ...msg, timestamp: 12, text: 'new callback' })
    expect(live.signalCache()[msg.chatId]).toHaveLength(2)
    expect(loadMessagingState()[msg.chatId]?.unread).toBe(true)
    live.stopSignalReceiver()
  } finally {
    vi.unstubAllEnvs()
    rmSync(dir, { recursive: true, force: true })
  }
})
