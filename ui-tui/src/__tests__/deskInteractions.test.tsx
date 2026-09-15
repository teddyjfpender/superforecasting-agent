import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'node:stream'

import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import { waitForText, waitUntil } from '../testing/settle.js'

const roots: string[] = []
afterEach(async () => {
  const { resetOverlayState } = await import('../app/overlayStore.js')
  resetOverlayState()
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
  roots.splice(0).forEach(p => rmSync(p, { recursive: true, force: true }))
})

async function mount(view: React.ReactNode, cols = 100, rows = 32) {
  const { render, Box, Text } = await import('@superforecasting/ink')
  const { stripAnsi } = await import('../lib/text.js')
  const stdout = new PassThrough()
  Object.assign(stdout, { columns: cols, rows, isTTY: false })
  const stdin = new PassThrough()
  Object.assign(stdin, { isTTY: true, isRaw: false, setRawMode: () => {}, ref: () => stdin, unref: () => stdin })
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })

  const app = await render(
    React.createElement(
      Box,
      { width: cols, height: rows, flexDirection: 'column' },
      React.createElement(Text, {}, 'Desk'),
      view
    ),
    {
      stdout: stdout as never,
      stdin: stdin as never,
      debug: true,
      patchConsole: false,
      exitOnCtrlC: false
    }
  )

  return {
    read: () => stripAnsi(output),
    write: (text: string) => stdin.write(text),
    input: async (text: string) => {
      stdin.write(text)
      await new Promise(r => setTimeout(r, 60))
    },
    close: () => {
      app.unmount()
      app.cleanup()
      stdout.destroy()
      stdin.destroy()
    }
  }
}

function profile() {
  const dir = mkdtempSync(join(tmpdir(), 'desk-ui-'))
  roots.push(dir)
  vi.stubEnv('SUPERFORECASTING_AGENT_HOME', dir)
  vi.stubEnv('FORECAST_TUI_INLINE', '1')

  return dir
}

it('Docs selects the requested document and rejects stale async note replies', async () => {
  profile()
  const { DocumentDesk } = await import('../components/documentDesk.js')
  const { DARK_THEME } = await import('../theme.js')
  let finishFirst!: (v: unknown) => void

  const request = vi.fn((method: string, params: { rel_path?: string }) => {
    if (method === 'obsidian.status') {
      return Promise.resolve({
        exists: true,
        vault: '/fake/vault',
        notes: [
          { rel_path: 'a.md', title: 'Alpha' },
          { rel_path: 'b.md', title: 'Beta' }
        ]
      })
    }

    if (params.rel_path === 'a.md') {
      return new Promise(resolve => {
        finishFirst = resolve
      })
    }

    return Promise.resolve({ content: '# Beta\n\nSelected document body', rel_path: 'b.md' })
  })

  const app = await mount(<DocumentDesk gw={{ request } as never} onClose={() => {}} t={DARK_THEME} />)

  try {
    await waitForText(app.read, 'Alpha')
    await waitUntil(() => typeof finishFirst === 'function', { label: 'initial note request started' })
    const { $shareItem } = await import('../lib/messagingState.js')
    expect($shareItem.get()).toBeNull()
    await app.input('e')
    expect(app.read()).not.toContain('EDIT · Alpha')
    await app.input('\x1b[B')
    await waitForText(app.read, 'Selected document body')
    expect($shareItem.get()).toMatchObject({ title: 'Beta' })
    finishFirst({ content: 'STALE ALPHA BODY' })
    await new Promise(r => setTimeout(r, 80))
    expect(app.read()).not.toContain('STALE ALPHA BODY')
    await app.input('e')
    await app.input('?')
    const { $overlayState } = await import('../app/overlayStore.js')
    expect($overlayState.get().cheatSheet).toBe(false)
    app.write('!')
    app.write('\x1b')
    await new Promise(r => setTimeout(r, 60))
    const { readDocumentDraft } = await import('../lib/documentDrafts.js')
    expect(readDocumentDraft('markdown:/fake/vault:b.md')?.content).toContain('?')
    expect(readDocumentDraft('markdown:/fake/vault:b.md')?.content).toContain('!')
    await app.input('?')
    expect($overlayState.get().cheatSheet).toBe(true)
  } finally {
    app.close()
  }
}, 15000)

it('quick compose preserves edited text on dismiss without sending', async () => {
  profile()
  const { QuickMessage } = await import('../components/quickMessage.js')
  const { $quickMessage, openQuickMessage, loadMessagingState } = await import('../lib/messagingState.js')
  const { DARK_THEME } = await import('../theme.js')
  openQuickMessage()
  const app = await mount(<QuickMessage cols={100} rows={32} t={DARK_THEME} />)

  try {
    await waitForText(app.read, 'MESSAGE', { timeout: 1200, label: 'quick modal visible' })
    await app.input('+15550001111')
    await app.input('\r')
    await waitForText(app.read, 'Write a message', { timeout: 1200, label: 'recipient selected' })
    await app.input('A retained draft')
    app.write('!')
    app.write('\x1b')
    await waitUntil(() => $quickMessage.get() === null)
    expect($quickMessage.get()).toBeNull()
    expect(loadMessagingState()['+15550001111']?.draft).toBe('A retained draft!')
  } finally {
    app.close()
  }
})

it('quick compose finds saved drafts without a contact or message history', async () => {
  profile()
  const { QuickMessage } = await import('../components/quickMessage.js')
  const { $quickMessage, updateChatState, openQuickMessage } = await import('../lib/messagingState.js')
  const { DARK_THEME } = await import('../theme.js')
  updateChatState('+15559990000', { draft: 'Unsent research', category: 'Research' })
  openQuickMessage()
  const app = await mount(<QuickMessage cols={80} rows={24} t={DARK_THEME} />)

  try {
    await waitForText(app.read, 'MESSAGE')
    await app.input('Research')
    await waitForText(app.read, '+15559990000')
    await app.input('\r')
    await waitForText(app.read, 'Unsent research')
  } finally {
    $quickMessage.set(null)
    app.close()
  }
})
