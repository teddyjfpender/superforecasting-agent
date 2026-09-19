import { randomUUID } from 'node:crypto'

import { Box, Text, useInput } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type {
  InterviewGenerateRequest,
  InterviewGenerationOptions,
  InterviewRecord,
  JobRecordDTO
} from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'
import { TextInput } from './textInput.js'

const terminal = new Set(['done', 'error', 'cancelled'])
const counts = [4, 8, 12, 16]
const tokens = [1000, 2000, 4000, 8000, 12000]
const deadlines = [30, 60, 90, 180]

const shiftValue = (values: number[], value: number, delta: number) =>
  values[Math.max(0, Math.min(values.length - 1, values.indexOf(value) + delta))]!

export function InterviewGeneration({
  gw,
  record,
  cols,
  rows,
  t,
  blocked,
  onClose,
  onReview
}: {
  gw: Pick<GatewayClient, 'request'>
  record: InterviewRecord
  cols: number
  rows: number
  t: Theme
  blocked: boolean
  onClose: () => void
  onReview: (record: InterviewRecord) => void
}) {
  const [options, setOptions] = useState<InterviewGenerationOptions>({
    provider: null,
    model: null,
    max_questions: 8,
    max_tokens: 4000,
    timeout_seconds: 90
  })

  const [job, setJob] = useState<JobRecordDTO | null>(null)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [statusError, setStatusError] = useState('')
  const [field, setField] = useState(0)
  const [editing, setEditing] = useState<'provider' | 'model' | null>(null)
  const [text, setText] = useState('')
  const pending = useRef<InterviewGenerateRequest | null>(null)
  const alive = useRef(true)
  const locked = useRef(false)
  const epoch = useRef(0)
  const running = job !== null && !terminal.has(job.status)

  useEffect(() => {
    let active = true
    let inflight = false
    alive.current = true
    epoch.current++

    const poll = async () => {
      if (inflight || locked.current) {
        return
      }

      inflight = true
      const version = epoch.current

      try {
        const result = await gw.request('forecast.interview.generation_status', { interview_id: record.interview_id })

        if (active && version === epoch.current) {
          setJob(result.job)
          setLoading(false)
          setStatusError('')

          if (result.request_id && result.request_id === pending.current?.request_id) {
            pending.current = null
            setError('')
          }
        }
      } catch (cause) {
        if (active && version === epoch.current) {
          setStatusError(`Status unavailable: ${cause instanceof Error ? cause.message : String(cause)}`)
          setLoading(true)
        }
      } finally {
        inflight = false
      }
    }

    void poll()
    const timer = setInterval(() => void poll(), 1500)

    return () => {
      active = false
      alive.current = false
      clearInterval(timer)
    }
  }, [gw, record.interview_id])

  const act = async (action: 'start' | 'cancel' | 'review') => {
    if (locked.current) {
      return
    }

    locked.current = true
    const version = ++epoch.current
    setWorking(true)
    setError('')

    try {
      if (action === 'start') {
        const fields = { interview_id: record.interview_id, revision: record.revision, options }
        const old = pending.current

        const request =
          old && JSON.stringify({ ...old, request_id: '' }) === JSON.stringify({ ...fields, request_id: '' })
            ? old
            : { ...fields, request_id: randomUUID() }

        pending.current = request
        await gw.request('forecast.interview.generate', request)
        pending.current = null
      } else if (action === 'cancel' && job) {
        await gw.request('jobs.cancel', { job_id: job.job_id })
      } else if (action === 'review') {
        const next = await gw.request('forecast.interview.read', { interview_id: record.interview_id })

        if (alive.current && version === epoch.current) {
          onReview(next)
        }

        return
      }

      const result = await gw.request('forecast.interview.generation_status', { interview_id: record.interview_id })

      if (alive.current && version === epoch.current) {
        setJob(result.job)
      }
    } catch (cause) {
      if (alive.current && version === epoch.current) {
        setError(cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      locked.current = false

      if (alive.current && version === epoch.current) {
        setWorking(false)
      }
    }
  }

  const visibleCount = Math.max(3, Math.min(6, rows - 16))
  const firstField = Math.max(0, field - visibleCount + 1)

  const fields = [
    `Questions: up to ${options.max_questions}`,
    `Output budget: ${options.max_tokens.toLocaleString()} tokens`,
    `Deadline: ${options.timeout_seconds}s`,
    `Provider: ${options.provider ?? 'configured default'}`,
    `Model: ${options.model ?? 'configured default'}`,
    'Generate follow-ups · uses model credits'
  ]

  useInput(
    (input, key, event) => {
      if (!editing || key.escape) {
        ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()
      }

      if (key.escape) {
        if (editing) {
          setEditing(null)
        } else {
          onClose()
        }

        return
      }

      if (editing || working || loading) {
        return
      }

      if (key.ctrl && input === 'x' && running) {
        void act('cancel')

        return
      }

      if (key.ctrl && input === 'r' && job?.status === 'done') {
        void act('review')

        return
      }

      if (running) {
        return
      }

      if (key.upArrow) {
        setField(value => Math.max(0, value - 1))
      }

      if (key.downArrow) {
        setField(value => Math.min(fields.length - 1, value + 1))
      }

      if (key.leftArrow || key.rightArrow) {
        const delta = key.leftArrow ? -1 : 1
        setOptions(value => ({
          ...value,
          max_questions: field === 0 ? shiftValue(counts, value.max_questions ?? 8, delta) : value.max_questions,
          max_tokens: field === 1 ? shiftValue(tokens, value.max_tokens ?? 4000, delta) : value.max_tokens,
          timeout_seconds:
            field === 2 ? shiftValue(deadlines, value.timeout_seconds ?? 90, delta) : value.timeout_seconds
        }))
      }

      if (key.return) {
        if (field === 3 || field === 4) {
          const kind = field === 3 ? 'provider' : 'model'
          setEditing(kind)
          setText(options[kind] ?? '')
        } else if (field === 5) {
          void act('start')
        }
      }
    },
    { isActive: !blocked }
  )

  return (
    <ModalOverlay
      cols={cols}
      footerHint={
        running ? '[Ctrl+X Cancel job] [Esc Back; job continues]' : '[↑↓ Field] [←→ Budget] [Enter Select] [Esc Back]'
      }
      maxHeight={30}
      maxWidth={100}
      rows={rows}
      t={t}
      title="ADAPTIVE FOLLOW-UPS"
      verticalMargin={2}
    >
      <Box flexDirection="column" minHeight={0}>
        <Text color={t.color.muted} wrap="truncate-end">
          {record.document.title} · revision {record.revision}
        </Text>
        {loading ? <Text color={t.color.accent}>Restoring saved generation status…</Text> : null}
        {job ? (
          <Text color={t.color.accent}>
            {job.cancel_requested && running ? 'Cancellation requested; waiting for worker' : `Last job: ${job.status}`}
            {job.status === 'done' ? ' · [Ctrl+R Review new questions]' : ''}
          </Text>
        ) : null}
        {job?.status === 'awaiting_approval' ? (
          <Text color={t.color.muted}>Paused by your spend policy. Approve this job in the Desk approval queue.</Text>
        ) : null}
        {job?.error ? (
          <Text color={t.color.error} wrap="truncate-end">
            {job.error}
          </Text>
        ) : null}
        {!loading && !running && !editing
          ? fields.slice(firstField, firstField + visibleCount).map((label, offset) => (
              <Text
                bold={field === firstField + offset}
                color={field === firstField + offset ? t.color.accent : t.color.primary}
                key={label}
              >
                {field === firstField + offset ? '› ' : '  '}
                {label}
              </Text>
            ))
          : null}
        {editing ? (
          <>
            <Text color={t.color.primary}>{editing} identifier (empty uses configured default)</Text>
            <TextInput
              columns={Math.max(20, Math.min(cols - 10, 90))}
              focus={!blocked}
              onChange={setText}
              onSubmit={input => {
                setOptions(value => ({ ...value, [editing]: input.trim() || null }))
                setEditing(null)
              }}
              value={text}
            />
          </>
        ) : null}
        <Text color={t.color.muted}>
          {running
            ? 'Saved answers are safe. Reopen this panel to restore progress.'
            : 'Proposes optional questions and assumptions. Never answers for you or changes a forecast.'}
        </Text>
        {working ? <Text color={t.color.accent}>Saving request…</Text> : null}
        {statusError || error ? (
          <Text color={t.color.error} wrap="truncate-end">
            {statusError || error}
          </Text>
        ) : null}
      </Box>
    </ModalOverlay>
  )
}
