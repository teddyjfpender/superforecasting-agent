import type * as ReactModule from 'react'
import { beforeEach, expect, it, vi } from 'vitest'

import { getUiState, patchUiState, resetUiState } from '../app/uiStore.js'
import { useSubmission, type UseSubmissionOptions } from '../app/useSubmission.js'

// Test deferred callbacks directly; React rendering does not determine which
// session owns a pending request.
vi.mock('react', async importOriginal => {
  const actual = await importOriginal<typeof ReactModule>()

  return {
    ...actual,
    useCallback: <T>(fn: T) => fn,
    useEffect: () => undefined,
    useRef: <T>(value: T) => ({ current: value })
  }
})

function Harness() {
  const request = vi.fn(),
    appendMessage = vi.fn(),
    enqueue = vi.fn(),
    sys = vi.fn()

  const opts = {
    appendMessage,
    composerActions: { enqueue },
    composerRefs: {},
    composerState: { input: '', inputBuf: [], pasteSnips: [] },
    gw: { request },
    maybeForecastPulse: vi.fn(),
    setLastUserMsg: vi.fn(),
    slashRef: { current: vi.fn() },
    submitRef: { current: vi.fn() },
    sys
  } as unknown as UseSubmissionOptions

  return { ...useSubmission(opts), appendMessage, enqueue, request, sys }
}

beforeEach(() => {
  resetUiState()
  patchUiState({ sid: 'original' })
})

it.each(['resolved', 'rejected'])('does not send delayed file input into another session (%s)', async outcome => {
  const h = Harness()
  let resolve!: (value: unknown) => void
  let reject!: (error: Error) => void
  h.request.mockReturnValueOnce(
    new Promise((yes, no) => {
      resolve = yes
      reject = no
    })
  )
  h.request.mockResolvedValue({})
  h.send('/tmp/evidence.txt')
  expect(h.request).toHaveBeenCalledWith('input.detect_drop', { session_id: 'original', text: '/tmp/evidence.txt' })
  patchUiState({ sid: 'replacement', busy: true, status: 'replacement working' })

  if (outcome === 'resolved') {
    resolve({ matched: true, name: 'evidence.txt', text: 'contents' })
  } else {
    reject(new Error('disconnected'))
  }

  await Promise.resolve()
  await Promise.resolve()
  expect(h.request).toHaveBeenCalledTimes(1)
  expect(h.appendMessage).not.toHaveBeenCalled()
  expect(getUiState().status).toBe('replacement working')
})

it.each(['session busy', 'connection lost'])('ignores an old session failure (%s)', async message => {
  const h = Harness()
  let reject!: (error: Error) => void
  h.request.mockReturnValue(
    new Promise((_, no) => {
      reject = no
    })
  )
  h.send('forecast note')
  patchUiState({ sid: 'replacement', busy: true, status: 'replacement working' })
  reject(new Error(message))
  await Promise.resolve()
  expect(h.enqueue).not.toHaveBeenCalled()
  expect(h.sys).not.toHaveBeenCalled()
  expect(getUiState().status).toBe('replacement working')
  expect(getUiState().busy).toBe(true)
})

it('submits detected content when the originating session remains current', async () => {
  const h = Harness()
  h.request.mockResolvedValueOnce({ matched: true, name: 'evidence.txt', text: 'contents' })
  h.request.mockResolvedValue({})
  h.send('/tmp/evidence.txt')
  await Promise.resolve()
  expect(h.request).toHaveBeenLastCalledWith('prompt.submit', { session_id: 'original', text: 'contents' })
})

it('retains busy handling for a submission in the current session', async () => {
  const h = Harness()
  h.request.mockRejectedValue(new Error('session busy'))
  h.send('forecast note')
  await Promise.resolve()
  expect(h.enqueue).toHaveBeenCalledWith('forecast note')
  expect(getUiState().status).toBe('queued for next turn')
})
