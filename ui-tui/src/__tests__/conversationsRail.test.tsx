import { PassThrough } from 'stream'

import React from 'react'
import { describe, expect, it } from 'vitest'

const ws = (c: number, r: number) => {
  const s = new PassThrough() as any
  let o = ''
  Object.assign(s, { columns: c, isRaw: false, isTTY: true, rows: r, ref: () => s, setRawMode: () => {}, unref: () => s })
  s.on('data', (d: Buffer) => (o += d.toString()))

  return { s, t: () => o }
}

const stripEsc = (raw: string) => raw.replace(new RegExp(`${String.fromCharCode(27)}\\[[0-?]*[ -/]*[@-~]`, 'g'), '')
const tk = (ms: number) => new Promise(r => setTimeout(r, ms))

describe('ConversationsRail', () => {
  it('lists recent sessions and marks the current one', async () => {
    const now = Math.floor(Date.now() / 1000)

    const sessions = [
      { id: 'a1', message_count: 3, preview: '', source: 'tui', started_at: now - 3600, title: 'Fed cut September' },
      { id: 'b2', message_count: 2, preview: 'NY-12 primary', source: 'tui', started_at: now - 90_000, title: '' },
      { id: 'cur', message_count: 5, preview: '', source: 'tui', started_at: now - 200_000, title: 'CPI above 3' }
    ]

    let newChats = 0
    const gw: any = { request: async () => ({ sessions }) }

    const [{ render }, { ConversationsRail }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/conversationsRail.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const so = ws(48, 30)
    so.s.columns = 48
    const si = ws(48, 30)

    const inst: any = render(
      React.createElement(ConversationsRail, {
        currentSid: 'cur',
        gw,
        onNewChat: () => (newChats += 1),
        onSelect: () => {},
        t: DARK_THEME,
        width: 40
      }),
      { exitOnCtrlC: false, patchConsole: false, stdin: si.s, stdout: so.s }
    )

    await tk(120)
    // The render harness collapses inter-cell spacing, so compare on a
    // whitespace-stripped view.
    const flat = stripAnsi(stripEsc(so.t())).replace(/\s+/g, '')
    expect(flat).toContain('Newchat')
    expect(flat).toContain('FedcutSeptember')
    expect(flat).toContain('NY-12primary') // falls back to preview when no title
    expect(flat).toMatch(/▸CPIabove3/) // current session marked
    expect(newChats).toBe(0)
    inst.unmount?.()
    inst.cleanup?.()
  })
})
