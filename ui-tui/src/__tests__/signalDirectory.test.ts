import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, expect, it, vi } from 'vitest'

const rpc = vi.hoisted(() => ({ contacts: vi.fn(), groups: vi.fn(), sync: vi.fn() }))
vi.mock('../lib/signalClient.js', () => ({ listContacts: rpc.contacts, listGroups: rpc.groups, signalRpc: rpc.sync }))
const roots: string[] = []
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllEnvs()
  roots.splice(0).forEach(p => rmSync(p, { recursive: true, force: true }))
})

async function setup() {
  vi.resetModules()
  const root = mkdtempSync(join(tmpdir(), 'signal-directory-'))
  roots.push(root)
  vi.stubEnv('SUPERFORECASTING_AGENT_HOME', root)
  rpc.contacts.mockReset().mockResolvedValue([{ id: 'ada', name: 'Ada', aliases: ['Ada'] }])
  rpc.groups.mockReset().mockResolvedValue([])
  rpc.sync.mockReset().mockResolvedValue({ error: null, result: null })

  return import('../lib/signalDirectory.js')
}

const cfg = { account: '+15550000001', httpUrl: 'http://local' }
it('deduplicates concurrent refresh, preserves local edits made while RPC is pending and retains cache on errors', async () => {
  const d = await setup()
  let finish!: (contacts: { id: string; name: string }[]) => void
  rpc.contacts.mockReturnValueOnce(
    new Promise(resolve => {
      finish = resolve
    })
  )
  const first = d.refreshSignalDirectory(cfg)
  expect(d.refreshSignalDirectory(cfg)).toBe(first)
  d.saveDirectoryContact({ chatId: 'ada', name: 'My Ada' })
  finish([{ id: 'ada', name: 'Remote Ada' }])
  await first
  expect(d.$signalDirectory.get().ada.name).toBe('My Ada')
  rpc.contacts.mockRejectedValueOnce(new Error('offline'))
  await d.refreshSignalDirectory(cfg)
  expect(d.$signalDirectory.get().ada.name).toBe('My Ada')
  expect(d.$signalDirectoryStatus.get()).toContain('cached contacts retained')
})
it('shares one polling timer, requests phone sync once and tolerates repeated cleanup', async () => {
  const d = await setup()
  vi.useFakeTimers()
  const stop1 = d.watchSignalDirectory(cfg)
  const stop2 = d.watchSignalDirectory(cfg)
  await vi.advanceTimersByTimeAsync(0)
  expect(rpc.sync).toHaveBeenCalledTimes(1)
  expect(rpc.contacts).toHaveBeenCalledTimes(1)
  stop1()
  stop1()
  await vi.advanceTimersByTimeAsync(15000)
  expect(rpc.contacts).toHaveBeenCalledTimes(2)
  stop2()
  await vi.advanceTimersByTimeAsync(30000)
  expect(rpc.contacts).toHaveBeenCalledTimes(2)
})
it('rejects stale refresh results from a replaced daemon', async () => {
  const d = await setup()
  let finish!: (contacts: { id: string; name: string }[]) => void
  rpc.contacts.mockReturnValueOnce(
    new Promise(resolve => {
      finish = resolve
    })
  )
  const old = d.refreshSignalDirectory(cfg)
  await d.refreshSignalDirectory({ ...cfg, httpUrl: 'http://replacement' })
  finish([{ id: 'stale', name: 'Stale' }])
  await old
  expect(d.$signalDirectory.get().stale).toBeUndefined()
  expect(d.$signalDirectory.get().ada.name).toBe('Ada')
})
