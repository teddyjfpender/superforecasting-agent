import { beforeEach, describe, expect, it, vi } from 'vitest'

import { sessionCommands } from '../app/slash/commands/session.js'
import type { SlashRunCtx } from '../app/slash/types.js'
import { getUiState, patchUiState } from '../app/uiStore.js'

const branch = sessionCommands.find(command => command.name === 'branch')!

function context(rpc: ReturnType<typeof vi.fn>) {
  return {
    gateway: { rpc },
    guarded: (callback: (result: unknown) => void) => callback,
    guardedErr: vi.fn(),
    session: { closeSession: vi.fn(), setSessionStartedAt: vi.fn() },
    sid: 'old',
    transcript: { setHistoryItems: vi.fn(), sys: vi.fn() }
  } as unknown as SlashRunCtx
}

describe('branch handoff', () => {
  beforeEach(() => patchUiState({ sid: 'old' }))

  it('switches only after the host finishes the coordinated handoff', async () => {
    let complete!: (value: unknown) => void
    const rpc = vi.fn(() => new Promise(resolve => { complete = resolve }))
    const ctx = context(rpc)
    branch.run('Alternative', ctx, 'branch')
    expect(rpc).toHaveBeenCalledWith('session.branch_replace', { name: 'Alternative', session_id: 'old' })
    expect(getUiState().sid).toBe('old')
    complete({ session_id: 'new', title: 'Alternative' })
    await vi.waitFor(() => expect(getUiState().sid).toBe('new'))
    expect(ctx.session.closeSession).not.toHaveBeenCalled()
  })

  it('keeps the current session and transcript when the host rejects replacement', async () => {
    const error = new Error('session is busy')
    const ctx = context(vi.fn().mockRejectedValue(error))
    branch.run('', ctx, 'branch')
    await vi.waitFor(() => expect(ctx.guardedErr).toHaveBeenCalledWith(error))
    expect(getUiState().sid).toBe('old')
    expect(ctx.transcript.setHistoryItems).not.toHaveBeenCalled()
    expect(ctx.session.closeSession).not.toHaveBeenCalled()
  })
})
