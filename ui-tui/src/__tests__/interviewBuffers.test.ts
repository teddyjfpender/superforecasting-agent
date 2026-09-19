import { afterEach, describe, expect, it, vi } from 'vitest'

import { InterviewBuffers } from '../lib/interviewBuffers.js'
import { RpcFixtures } from '../testing/rpcFixtures.js'

const record = { interview_id: 'draft', revision: 1 }
const buffer = { text: 'Unconfirmed', note: '', choice: 0, selected: [], custom_editing: false }

afterEach(() => { vi.useRealTimers() })

describe('durable interview editor controller', () => {
  it('reports saved only after acknowledgement and coalesces later edits', async () => {
    vi.useFakeTimers()
    const status = vi.fn()
    const requests: string[] = []

    let release: () => void = () => {}
    const barrier = new Promise<void>(resolve => { release = resolve })

    const provider = new RpcFixtures()
      .handle('forecast.interview.buffers', () => ({ buffers: [] }))
      .handle('forecast.interview.buffer.save', async request => {
        requests.push(request.buffer?.text ?? '')

        if (requests.length === 1) { await barrier }

        return { ...request, buffer_revision: request.expected_buffer_revision + 1, saved_at: '2030-01-01', discarded: request.buffer === null }
      })

    const controller = new InterviewBuffers(provider, status)
    await controller.restore(record)
    controller.stage('title', buffer)
    const saving = controller.flush()
    expect(status).toHaveBeenLastCalledWith('Unconfirmed edits · saving…')
    controller.stage('title', { ...buffer, text: 'Latest edit' })
    expect(status).toHaveBeenLastCalledWith('Unconfirmed edits · unsaved')
    release()
    await saving
    expect(requests).toEqual(['Unconfirmed', 'Latest edit'])
    expect(status).toHaveBeenLastCalledWith('Unconfirmed edits · saved locally')
    controller.dispose()
  })

  it('retries the identical uncertain save before persisting a discard', async () => {
    vi.useFakeTimers()
    const seen: unknown[] = []

    const provider = new RpcFixtures()
      .handle('forecast.interview.buffers', () => ({ buffers: [] }))
      .handle('forecast.interview.buffer.save', request => {
        seen.push(structuredClone(request))

        if (seen.length === 1) { throw new Error('lost acknowledgement') }

        return { ...request, buffer_revision: request.expected_buffer_revision + 1, saved_at: '2030-01-01', discarded: request.buffer === null }
      })

    const controller = new InterviewBuffers(provider, () => {})
    await controller.restore(record)
    controller.stage('title', buffer)
    await expect(controller.flush()).rejects.toThrow('lost acknowledgement')
    await controller.discard(['title'])
    expect(seen[0]).toEqual(seen[1])
    expect(seen[2]).toMatchObject({ buffer: null, expected_buffer_revision: 1 })
    controller.dispose()
  })

  it('does not claim durability when storage is unavailable', async () => {
    const status = vi.fn()
    const controller = new InterviewBuffers(new RpcFixtures(), status)
    await controller.restore(record)
    controller.stage('title', buffer)
    await controller.flush()
    expect(status).toHaveBeenLastCalledWith('Draft storage unavailable · unconfirmed edits are not saved')
    controller.dispose()
  })
})

it('rejects an acknowledgement from another revision without claiming saved', async () => {
  const status = vi.fn()

  const provider = new RpcFixtures()
    .handle('forecast.interview.buffers', () => ({ buffers: [] }))
    .handle('forecast.interview.buffer.save', request => ({
      ...request, request_id: 'another-request', buffer_revision: 1,
      saved_at: '2030-01-01', discarded: false
    }))

  const controller = new InterviewBuffers(provider, status)
  await controller.restore(record)
  controller.stage('title', buffer)
  await expect(controller.preserve()).rejects.toThrow('acknowledgement does not match')
  expect(status.mock.calls.flat()).not.toContain('Unconfirmed edits · saved locally')
  controller.dispose()
})

it('treats buffers newer than the displayed interview as conflicts', async () => {
  const provider = new RpcFixtures().handle('forecast.interview.buffers', () => ({ buffers: [{
    interview_id: 'draft', question_id: 'title', base_revision: 2, buffer_revision: 1,
    request_id: 'newer', saved_at: '2030-01-01', buffer, discarded: false, stale: false
  }] }))

  const status = vi.fn()
  const controller = new InterviewBuffers(provider, status)
  const recovered = await controller.restore(record)
  expect(recovered[0].stale).toBe(true)
  expect(status).toHaveBeenLastCalledWith('Recovered drafts need review: interview changed.')
  controller.dispose()
})

it('ignores an older restore failure after a replacement restore succeeded', async () => {
  let rejectOld: (cause: Error) => void = () => {}
  const old = new Promise<never>((_, reject) => { rejectOld = reject })

  const provider = new RpcFixtures()
    .handle('forecast.interview.buffers', params => params.interview_id === 'draft' ? old : { buffers: [] })
    .handle('forecast.interview.buffer.save', request => ({ ...request,
      buffer_revision: request.expected_buffer_revision + 1, saved_at: '2030-01-01', discarded: request.buffer === null
    }))

  const status = vi.fn()
  const controller = new InterviewBuffers(provider, status)
  const first = controller.restore(record)
  await controller.restore({ interview_id: 'replacement', revision: 1 })
  rejectOld(new Error('old connection lost'))
  await first
  controller.stage('title', buffer)
  await controller.preserve()
  expect(status).toHaveBeenLastCalledWith('Unconfirmed edits · saved locally')
  controller.dispose()
})

it.each(['wrong-interview', 'duplicate-question'])('rejects %s restoration before enabling writes', async fault => {
  const item = { interview_id: fault === 'wrong-interview' ? 'other' : 'draft', question_id: 'title',
    base_revision: 1, buffer_revision: 1, request_id: 'saved', saved_at: '2030-01-01',
    buffer, discarded: false, stale: false }

  const provider = new RpcFixtures().handle('forecast.interview.buffers', () => ({
    buffers: fault === 'duplicate-question' ? [item, item] : [item]
  }))

  const status = vi.fn()
  const controller = new InterviewBuffers(provider, status)
  expect(await controller.restore(record)).toEqual([])
  controller.stage('title', buffer)
  await expect(controller.preserve()).rejects.toThrow('Draft storage unavailable')
  expect(status).toHaveBeenLastCalledWith('Draft storage unavailable · unconfirmed edits are not saved')
  controller.dispose()
})


it.each([1, 2])('only rewrites restored content when its base revision changed (%s)', async baseRevision => {
  const saves = vi.fn()

  const provider = new RpcFixtures()
    .handle('forecast.interview.buffers', () => ({ buffers: [{
      interview_id: 'draft', question_id: 'title', base_revision: baseRevision, buffer_revision: 3,
      request_id: 'old', saved_at: '2030-01-01', buffer, discarded: false, stale: baseRevision !== 1
    }] }))
    .handle('forecast.interview.buffer.save', request => {
      saves(request)

      return { ...request, buffer_revision: request.expected_buffer_revision + 1,
        saved_at: '2030-01-02', discarded: false }
    })

  const controller = new InterviewBuffers(provider, () => {})
  await controller.restore(record)
  // Wire object ordering may differ from the editor's construction order.
  controller.stage('title', { custom_editing: false, selected: [], choice: 0, note: '', text: buffer.text })
  controller.stage('title', buffer)
  await controller.flush()
  expect(saves).toHaveBeenCalledTimes(baseRevision === 1 ? 0 : 1)
  controller.stage('title', buffer)
  await controller.flush()
  expect(saves).toHaveBeenCalledTimes(baseRevision === 1 ? 0 : 1)
  controller.dispose()
})
