/** Durable editor state: acknowledged saves never imply confirmed answers. */
import { randomUUID } from 'node:crypto'

import type { GatewayClient } from '../gatewayClient.js'
import type { InterviewBufferSaveRequest, InterviewEditorBuffer, InterviewRecord } from '../protocol/generated.js'

type Entry = {
  revision: number
  version: number
  acknowledged: number
  buffer: InterviewEditorBuffer | null
  pending?: { request: InterviewBufferSaveRequest; version: number }
}

export class InterviewBuffers {
  private entries = new Map<string, Entry>()
  private record: Pick<InterviewRecord, 'interview_id' | 'revision'> | null = null
  private running: Promise<void> | null = null
  private timer: ReturnType<typeof setTimeout> | undefined
  private disposed = false
  private available = false

  constructor(private gw: Pick<GatewayClient, 'request'>, private status: (message: string) => void) {}

  async restore(record: Pick<InterviewRecord, 'interview_id' | 'revision'>) {
    if (this.running) { await this.running }
    clearTimeout(this.timer)
    this.entries.clear()
    this.available = false
    this.record = record

    try {
      const result = await this.gw.request('forecast.interview.buffers', { interview_id: record.interview_id })

      if (this.disposed) { return [] }
      this.available = true

      for (const item of result.buffers) {
        this.entries.set(item.question_id, {
          revision: item.buffer_revision, version: 0, acknowledged: 0, buffer: item.buffer
        })
      }

      this.emit(result.buffers.some(item => item.stale && item.buffer)
        ? 'Recovered drafts need review: interview changed.' : 'Draft storage ready')

      return result.buffers
    } catch {
      this.available = false
      this.emit('Draft storage unavailable · unconfirmed edits are not saved')

      return []
    }
  }

  stage(questionId: string, buffer: InterviewEditorBuffer | null) {
    if (!this.available || this.disposed) { return }
    const entry = this.entries.get(questionId) ?? { revision: 0, version: 0, acknowledged: 0, buffer: null }

    if (JSON.stringify(entry.buffer) === JSON.stringify(buffer) && entry.version > 0) { return }
    entry.buffer = buffer === null ? null : structuredClone(buffer)
    entry.version += 1
    this.entries.set(questionId, entry)
    this.emit('Unconfirmed edits · unsaved')
    clearTimeout(this.timer)
    this.timer = setTimeout(() => { void this.flush().catch(() => {}) }, 300)
  }

  /** Only after an acknowledged local answer transition, following flush. */
  advance(record: Pick<InterviewRecord, 'interview_id' | 'revision'>) {
    if (record.interview_id !== this.record?.interview_id) {
      throw new Error('Editor buffers belong to a different interview')
    }

    this.record = record
  }

  /** The backend retires pre-confirmation text atomically with the answer. */
  confirmed(questionId: string, record: Pick<InterviewRecord, 'interview_id' | 'revision'>) {
    this.advance(record)
    const entry = this.entries.get(questionId)

    if (entry) {
      entry.buffer = null
      entry.acknowledged = entry.version
      entry.pending = undefined
    }
  }

  async preserve() {
    if (!this.available) { throw new Error("Draft storage unavailable; confirm answers before closing") }
    await this.flush()
  }

  async discard(questionIds: string[]) {
    if (!this.available) { throw new Error('Draft storage unavailable; stored drafts could not be discarded') }

    for (const questionId of questionIds) { this.stage(questionId, null) }
    await this.flush()
  }

  flush(): Promise<void> {
    clearTimeout(this.timer)

    if (this.running) { return this.running }
    this.running = this.drain().finally(() => { this.running = null })

    return this.running
  }

  private async drain() {
    if (!this.available || this.disposed || !this.record) { return }

    while (!this.disposed) {
      const next = [...this.entries].find(([, entry]) => entry.version > entry.acknowledged)

      if (!next) {
        this.emit('Unconfirmed edits · saved locally')

        return
      }

      const [questionId, entry] = next
      entry.pending ??= {
        version: entry.version,
        request: {
          interview_id: this.record.interview_id, question_id: questionId,
          base_revision: this.record.revision, expected_buffer_revision: entry.revision,
          request_id: randomUUID(), buffer: entry.buffer
        }
      }
      this.emit('Unconfirmed edits · saving…')

      try {
        const receipt = await this.gw.request('forecast.interview.buffer.save', entry.pending.request)
        const expected = entry.pending.request

        if (receipt.interview_id !== expected.interview_id || receipt.question_id !== expected.question_id ||
          receipt.request_id !== expected.request_id || receipt.base_revision !== expected.base_revision ||
          receipt.buffer_revision !== expected.expected_buffer_revision + 1 || receipt.discarded !== (expected.buffer === null)) {
          throw new Error('Draft acknowledgement does not match the saved revision')
        }

        entry.revision = receipt.buffer_revision
        entry.acknowledged = entry.pending.version
        entry.pending = undefined
      } catch (cause) {
        this.emit(`Draft save failed · ${cause instanceof Error ? cause.message : String(cause)}`)
        // Preserve the exact request: the server may have committed before disconnect.
        throw cause
      }
    }
  }

  private emit(message: string) { if (!this.disposed) { this.status(message) } }

  dispose() {
    this.disposed = true
    clearTimeout(this.timer)
  }
}
