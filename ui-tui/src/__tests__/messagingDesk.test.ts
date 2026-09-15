import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, expect, it, vi } from 'vitest'

const roots: string[] = []
afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
  roots.splice(0).forEach(p => rmSync(p, { recursive: true, force: true }))
})

const profile = () => {
  const dir = mkdtempSync(join(tmpdir(), 'messaging-desk-'))
  roots.push(dir)
  vi.stubEnv('SUPERFORECASTING_AGENT_HOME', dir)

  return dir
}

it('persists organization, drafts and read state without losing sibling fields', async () => {
  const dir = profile()
  const { updateChatState, loadMessagingState } = await import('../lib/messagingState.js')
  expect(updateChatState('+15550000000', { category: 'Research', pinned: true, draft: 'Keep me', unread: true })).toBe(
    true
  )
  expect(updateChatState('+15550000000', { unread: false, readThrough: 123 })).toBe(true)
  const state = loadMessagingState()['+15550000000']
  expect(state).toMatchObject({ category: 'Research', pinned: true, draft: 'Keep me', unread: false, readThrough: 123 })
  expect(JSON.parse(readFileSync(join(dir, 'messaging_desk.json'), 'utf8'))).toHaveProperty('+15550000000')
})

it('freezes forwarding context when quick compose opens', async () => {
  profile()
  const { $shareItem, $quickMessage, openQuickMessage } = await import('../lib/messagingState.js')
  $shareItem.set({ title: 'CPI', text: 'https://example.com/release' })
  openQuickMessage()
  $shareItem.set({ title: 'Different row', text: 'No' })
  expect($quickMessage.get()?.item?.title).toBe('CPI')
})

it('restores document drafts independently for each source identity', async () => {
  profile()
  const { saveDocumentDraft, readDocumentDraft } = await import('../lib/documentDrafts.js')
  saveDocumentDraft('vault:a.md', { original: 'one', content: 'unsaved' })
  expect(readDocumentDraft('vault:a.md')).toEqual({ original: 'one', content: 'unsaved' })
  expect(readDocumentDraft('another-vault:a.md')).toBeNull()
})
