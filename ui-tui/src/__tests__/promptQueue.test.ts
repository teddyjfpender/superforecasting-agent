import { beforeEach, describe, expect, it } from 'vitest'

import {
  $overlayState,
  clearPendingPrompts,
  patchOverlayState,
  pendingPromptCount,
  raisePrompt,
  resetFlowOverlays,
  resetOverlayState
} from '../app/overlayStore.js'

beforeEach(() => resetOverlayState())

const confirmReq = (title: string) => ({
  cancelLabel: 'No',
  confirmLabel: 'Yes',
  danger: true,
  detail: title,
  onConfirm: () => {},
  title
})

describe('prompt-overlay anti-clobber queue', () => {
  it('shows the first prompt and BUFFERS a second one instead of clobbering it', () => {
    raisePrompt({ confirm: confirmReq('clear session?') })
    // Second prompt raised while the confirm is still pending.
    raisePrompt({ approval: { command: 'rm -rf /', description: 'danger' } })

    const s = $overlayState.get()
    // The pending confirm is intact — NOT clobbered by the approval.
    expect(s.confirm?.title).toBe('clear session?')
    // The approval did not overwrite the visible overlay; it is buffered.
    expect(s.approval).toBeNull()
    expect(pendingPromptCount()).toBe(1)
  })

  it('re-raises the buffered prompt (FIFO) once the active one resolves', () => {
    raisePrompt({ confirm: confirmReq('clear session?') })
    raisePrompt({ approval: { command: 'rm -rf /', description: 'danger' } })

    // Resolve the confirm exactly as the UI does (appOverlays clears it).
    patchOverlayState({ confirm: null })

    const s = $overlayState.get()
    // The previously-buffered approval is now the active overlay.
    expect(s.confirm).toBeNull()
    expect(s.approval?.command).toBe('rm -rf /')
    expect(pendingPromptCount()).toBe(0)
  })

  it('drains multiple buffered prompts in FIFO order', () => {
    raisePrompt({ confirm: confirmReq('first') })
    raisePrompt({ sudo: { requestId: 'sudo-1' } })
    raisePrompt({ secret: { envVar: 'TOKEN', prompt: 'enter token', requestId: 'sec-1' } })
    expect(pendingPromptCount()).toBe(2)

    // Resolve confirm -> sudo surfaces first (it was queued first).
    patchOverlayState({ confirm: null })
    expect($overlayState.get().sudo?.requestId).toBe('sudo-1')
    expect($overlayState.get().secret).toBeNull()
    expect(pendingPromptCount()).toBe(1)

    // Resolve sudo -> secret surfaces next.
    patchOverlayState({ sudo: null })
    expect($overlayState.get().secret?.requestId).toBe('sec-1')
    expect(pendingPromptCount()).toBe(0)
  })

  it('single-prompt behaviour is byte-identical when the queue is empty', () => {
    // No prior prompt active: raisePrompt is exactly patchOverlayState.
    raisePrompt({ approval: { command: 'ls', description: 'list' } })
    expect($overlayState.get().approval?.command).toBe('ls')
    expect(pendingPromptCount()).toBe(0)

    // Clearing it with no buffer pumps nothing.
    patchOverlayState({ approval: null })
    expect($overlayState.get().approval).toBeNull()
    expect(pendingPromptCount()).toBe(0)
  })

  it('does not pump the queue while a DIFFERENT prompt is still active after a clear', () => {
    // Edge: clear a prompt key that was not the active one — the active prompt
    // remains, so nothing should be re-raised yet.
    raisePrompt({ confirm: confirmReq('keep me') })
    raisePrompt({ approval: { command: 'x', description: 'd' } })

    // Clearing approval (which is only buffered, not active) leaves confirm up
    // and must not pop the buffer.
    patchOverlayState({ approval: null })
    expect($overlayState.get().confirm?.title).toBe('keep me')
    expect(pendingPromptCount()).toBe(1)
  })

  it('turn teardown (resetFlowOverlays) drops buffered prompts so they do not resurface', () => {
    raisePrompt({ confirm: confirmReq('first') })
    raisePrompt({ approval: { command: 'x', description: 'd' } })
    expect(pendingPromptCount()).toBe(1)

    resetFlowOverlays()

    expect($overlayState.get().confirm).toBeNull()
    expect($overlayState.get().approval).toBeNull()
    expect(pendingPromptCount()).toBe(0)
  })

  it('clearPendingPrompts empties the buffer without touching the active overlay', () => {
    raisePrompt({ confirm: confirmReq('stay') })
    raisePrompt({ approval: { command: 'x', description: 'd' } })

    clearPendingPrompts()

    expect(pendingPromptCount()).toBe(0)
    expect($overlayState.get().confirm?.title).toBe('stay')
  })

  it('pager is PASSIVE: opening it does not make a later blocking prompt queue behind it', () => {
    // The pager is a passive viewer (not a blocking gateway worker) and is not
    // in PROMPT_KEYS, so a pager being open must NOT count as an active prompt.
    patchOverlayState({ pager: { lines: ['hello'], offset: 0, title: 'log' } })

    // A real blocking prompt raised while the pager is open surfaces
    // IMMEDIATELY — it is not deferred behind the passive pager.
    raisePrompt({ approval: { command: 'ls', description: 'list' } })

    const s = $overlayState.get()
    expect(s.pager?.title).toBe('log')
    expect(s.approval?.command).toBe('ls')
    expect(pendingPromptCount()).toBe(0)
  })

  it('a pager raised behind an active blocking prompt does not enter the queue', () => {
    raisePrompt({ confirm: confirmReq('blocking') })
    // The pager opens via patchOverlayState, not raisePrompt, so it never
    // buffers; it co-exists with the active confirm and the queue stays empty.
    patchOverlayState({ pager: { lines: ['x'], offset: 0, title: 'p' } })

    expect($overlayState.get().confirm?.title).toBe('blocking')
    expect($overlayState.get().pager?.title).toBe('p')
    expect(pendingPromptCount()).toBe(0)
  })

  it('pendingPrompts clears on session reset (clearPendingPrompts, as resetSession calls)', () => {
    // resetSession()/turnController.fullReset() do not touch the module-global
    // buffer, so the session-reset path now calls clearPendingPrompts() to stop
    // a prior session's buffered prompts leaking into the next session.
    raisePrompt({ confirm: confirmReq('old session') })
    raisePrompt({ approval: { command: 'x', description: 'd' } })
    expect(pendingPromptCount()).toBe(1)

    // The exact call resetSession() makes on /new / session switch.
    clearPendingPrompts()

    expect(pendingPromptCount()).toBe(0)
  })
})
