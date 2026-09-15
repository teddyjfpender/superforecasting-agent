import { expect, it, vi } from 'vitest'
const transport = vi.hoisted(() => vi.fn())
const record = vi.hoisted(() => vi.fn())
vi.mock('../lib/signalClient.js', () => ({ sendSignalMessage: transport }))
vi.mock('../lib/signalLive.js', () => ({ recordSignalMessage: record }))
import { $messageSendAttempts, messageSendKey, sendDeskMessage } from '../lib/messagingSend.js'

it('prevents overlapping sends and records only confirmed transport success', async () => {
  let finish!: (value: { error: null; timestamp: number }) => void
  transport.mockImplementationOnce(
    () =>
      new Promise(resolve => {
        finish = resolve
      })
  )
  const cfg = { account: '+15550000000', httpUrl: 'http://localhost:8080' }
  const key = messageSendKey(cfg, '+15550000001')
  const first = sendDeskMessage(cfg, '+15550000001', 'hello')
  expect($messageSendAttempts.get()[key]).toMatchObject({ text: 'hello', status: 'sending' })
  expect(await sendDeskMessage(cfg, '+15550000001', 'hello')).toContain('already sending')
  expect(transport).toHaveBeenCalledTimes(1)
  finish({ error: null, timestamp: 123 })
  expect(await first).toBeNull()
  expect($messageSendAttempts.get()[key]).toBeUndefined()
  expect(record).toHaveBeenCalledWith(expect.objectContaining({ timestamp: 123, text: 'hello' }))
  transport.mockResolvedValueOnce({ error: 'timeout', timestamp: 0 })
  expect(await sendDeskMessage(cfg, '+15550000001', 'retry manually')).toContain('unconfirmed')
  expect(record).toHaveBeenCalledTimes(1)
  expect($messageSendAttempts.get()[key]).toMatchObject({ text: 'retry manually', status: 'uncertain' })
})
