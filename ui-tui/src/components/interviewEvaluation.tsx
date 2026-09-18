import { randomUUID } from 'node:crypto'

import { Box, ScrollBox, type ScrollBoxHandle, Text, useInput } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type {
  InterviewEvaluateRequest,
  InterviewEvaluationStatusResponse,
  InterviewRecord
} from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'
import { TextInput } from './textInput.js'

const terminal = new Set(['done', 'error', 'cancelled'])

export function InterviewEvaluation({
  gw,
  record,
  cols,
  rows,
  t,
  blocked,
  onClose
}: {
  gw: GatewayClient
  record: InterviewRecord
  cols: number
  rows: number
  t: Theme
  blocked: boolean
  onClose: () => void
}) {
  const [selected, setSelected] = useState(record.document.scenarios.slice(0, 8).map(item => item.id))
  const [repetitions, setRepetitions] = useState(1)
  const [tokens, setTokens] = useState(4000)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [editing, setEditing] = useState<'provider' | 'model' | null>(null)
  const [text, setText] = useState('')
  const [field, setField] = useState(0)
  const [status, setStatus] = useState<InterviewEvaluationStatusResponse | null>(null)
  const [statusError, setStatusError] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [review, setReview] = useState(false)
  const alive = useRef(true)
  const locked = useRef(false)
  const epoch = useRef(0)
  const pending = useRef<InterviewEvaluateRequest | null>(null)
  const scroll = useRef<ScrollBoxHandle>(null)
  const estimate = status?.report?.results[0]?.estimate
  const probability = estimate?.outcome_type === 'binary' || estimate?.outcome_type === 'categorical'

  const metric = (value: number, delta = false) =>
    probability
      ? `${(value * 100).toFixed(1)}${delta ? ' pp' : '%'}`
      : `${value.toLocaleString(undefined, { maximumFractionDigits: 4 })}${estimate?.units ? ` ${estimate.units}` : ''}`

  const job = status?.job
  const running = !!job && !terminal.has(job.status)
  const scenarios = record.document.scenarios
  const calls = (selected.length + 1) * repetitions
  const height = Math.max(3, Math.min(rows - 2, 34) - 11)
  const visible = Math.max(2, height - 2)
  const first = Math.max(0, field - visible + 1)

  const fields = [
    ...scenarios.map(item => `${selected.includes(item.id) ? '[x]' : '[ ]'} ${item.name} · ${item.kind}`),
    `Repetitions: ${repetitions}`,
    `Output cap per call: ${tokens.toLocaleString()} tokens`,
    `Provider: ${provider || 'configured default'}`,
    `Model: ${model || 'configured default'}`,
    'Run comparison · uses model credits'
  ]

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
        const next = await gw.request('forecast.interview.evaluation_status', { interview_id: record.interview_id })

        if (active && version === epoch.current) {
          setStatus(next)
          setStatusError('')

          if (pending.current?.request_id === next.request_id) {
            pending.current = null
            setError('')
          }
        }
      } catch (cause) {
        if (active && version === epoch.current) {
          setStatusError(`Status unavailable: ${String(cause)}`)
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

  const act = async (cancel = false) => {
    if (locked.current) {
      return
    }

    locked.current = true
    const version = ++epoch.current
    setBusy(true)
    setError('')

    try {
      if (cancel && job) {
        await gw.request('jobs.cancel', { job_id: job.job_id })
      } else {
        if (!selected.length) {
          throw new Error('Select at least one saved scenario. Use Ctrl+O in the interview to create one.')
        }

        const fields = {
          interview_id: record.interview_id,
          revision: record.revision,
          options: {
            scenario_ids: selected,
            repetitions,
            model: {
              provider: provider || null,
              model: model || null,
              max_questions: 8,
              max_tokens: tokens,
              timeout_seconds: 90
            }
          }
        }

        const prior = pending.current

        const request =
          prior && JSON.stringify({ ...prior, request_id: '' }) === JSON.stringify({ ...fields, request_id: '' })
            ? prior
            : { ...fields, request_id: randomUUID() }

        pending.current = request
        await gw.request('forecast.interview.evaluate', request)
        pending.current = null
      }

      const next = await gw.request('forecast.interview.evaluation_status', { interview_id: record.interview_id })

      if (alive.current && version === epoch.current) {
        setStatus(next)
        setStatusError('')
      }
    } catch (cause) {
      if (alive.current && version === epoch.current) {
        setError(cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      locked.current = false

      if (alive.current && version === epoch.current) {
        setBusy(false)
      }
    }
  }

  useInput(
    (input, key, event) => {
      if (!editing || key.escape) {
        ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()
      }

      if (key.escape) {
        if (editing) {
          setEditing(null)
        } else if (review) {
          setReview(false)
        } else {
          onClose()
        }

        return
      }

      if (editing || busy) {
        return
      }

      if (review) {
        if (key.pageDown || key.downArrow) {
          scroll.current?.scrollBy(key.pageDown ? height : 1)
        }

        if (key.pageUp || key.upArrow) {
          scroll.current?.scrollBy(key.pageUp ? -height : -1)
        }

        return
      }

      if (!status || statusError) {
        return
      }

      if (key.ctrl && input === 'x' && running) {
        void act(true)

        return
      }

      if (key.ctrl && input === 'r' && status.report) {
        setReview(true)

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

        if (field === scenarios.length) {
          setRepetitions(value => Math.max(1, Math.min(3, value + delta)))
        }

        if (field === scenarios.length + 1) {
          setTokens(value => Math.max(1000, Math.min(12000, value + delta * 1000)))
        }
      }

      if (key.return || input === ' ') {
        if (field < scenarios.length) {
          const id = scenarios[field]!.id

          if (!selected.includes(id) && selected.length === 8) {
            setError('Choose at most eight scenarios.')

            return
          }

          setSelected(value => (value.includes(id) ? value.filter(item => item !== id) : [...value, id]))
        } else if (key.return && (field === scenarios.length + 2 || field === scenarios.length + 3)) {
          const target = field === scenarios.length + 2 ? 'provider' : 'model'
          setEditing(target)
          setText(target === 'provider' ? provider : model)
        } else if (key.return && field === fields.length - 1) {
          void act()
        }
      }
    },
    { isActive: !blocked }
  )

  return (
    <ModalOverlay
      cols={cols}
      footerHint={
        review
          ? '[↑↓ / PgUp/Dn Read] [Esc Settings]'
          : running
            ? '[Ctrl+X Cancel] [Esc Back; job continues]'
            : '[↑↓] [Space Toggle] [←→] [Enter] [^R Results] [Esc]'
      }
      maxHeight={34}
      maxWidth={110}
      rows={rows}
      t={t}
      title={review ? 'SCENARIO COMPARISON' : 'EVALUATE SCENARIOS'}
      verticalMargin={2}
    >
      <Box flexDirection="column" minHeight={0}>
        <Text color={t.color.muted} wrap="truncate-end">
          {record.document.title} · revision {record.revision}
        </Text>
        <Text color={t.color.accent} wrap="truncate-end">
          {!status
            ? 'Restoring saved evaluation…'
            : job
              ? `${job.cancel_requested && running ? 'Cancellation requested' : job.status} · ${job.done_count}/${job.total ?? '?'} calls${status.report ? ' · Ctrl+R results' : ''}`
              : 'Select scenarios to compare with an unconditional baseline.'}
        </Text>
        {review && status?.report ? (
          <ScrollBox
            decstbm={false}
            flexDirection="column"
            followContent={false}
            height={height}
            key="report"
            ref={scroll}
          >
            <Text color={t.color.accent}>
              {status.stale
                ? 'Historical result: interview or active baseline has changed.'
                : 'Model proposals · active forecast unchanged.'}
            </Text>
            <Text color={t.color.muted}>
              Baseline is unconditional. Conditional estimates assume selected states; ablations omit reasoning factors.
            </Text>
            {status.report.comparisons.map(comparison => (
              <Box flexDirection="column" key={comparison.variant_id} marginTop={1}>
                <Text bold color={t.color.primary}>
                  {status.report?.scenarios.find(item => item.id === comparison.variant_id)?.name ??
                    comparison.variant_id}{' '}
                  · {comparison.kind}
                </Text>
                {status.report?.scenarios
                  .filter(item => item.id === comparison.variant_id)
                  .flatMap(item =>
                    item.kind === 'conditional'
                      ? Object.entries(item.conditions).map(
                          ([id, state]) =>
                            `Assume ${status.report?.assumptions.find(a => a.id === id)?.statement ?? id}: ${state ? 'true' : 'false'}`
                        )
                      : item.excluded_assumption_ids.map(
                          id =>
                            `Exclude reasoning factor: ${status.report?.assumptions.find(a => a.id === id)?.statement ?? id}`
                        )
                  )
                  .map((label, index) => (
                    <Text color={t.color.muted} key={index}>
                      {label}
                    </Text>
                  ))}
                {Object.entries(comparison.dimensions).map(([key, value]) => (
                  <Text color={t.color.primary} key={key}>
                    {key}: {metric(value.mean)} · Δ baseline {value.paired_delta >= 0 ? '+' : ''}
                    {metric(value.paired_delta, true)} · dispersion{' '}
                    {value.model_dispersion === null ? 'not measured' : metric(value.model_dispersion, true)}
                  </Text>
                ))}
                {status.report?.results
                  .filter(item => item.variant_id === comparison.variant_id)
                  .map(item => (
                    <Box flexDirection="column" key={item.repetition}>
                      <Text color={t.color.primary}>
                        Run {item.repetition + 1}
                        {item.estimate.units ? ` · ${item.estimate.units}` : ''}: {item.estimate.rationale}
                      </Text>
                      {item.estimate.unresolved_questions.map((question, index) => (
                        <Text color={t.color.muted} key={index}>
                          Open: {question}
                        </Text>
                      ))}
                      <Text color={t.color.muted}>
                        Evidence: {item.estimate.evidence_refs.join(', ') || 'No cited evidence'} · model{' '}
                        {item.response_model}
                      </Text>
                    </Box>
                  ))}
              </Box>
            ))}
            <Text color={t.color.muted}>{status.report.limitation}</Text>
          </ScrollBox>
        ) : editing ? (
          <>
            <Text color={t.color.primary}>{editing} identifier (empty uses configured default)</Text>
            <TextInput
              columns={Math.max(20, Math.min(cols - 10, 100))}
              focus={!blocked}
              onChange={setText}
              onSubmit={value => {
                if (editing === 'provider') {
                  setProvider(value.trim())
                } else {
                  setModel(value.trim())
                }

                setEditing(null)
              }}
              value={text}
            />
          </>
        ) : (
          <Box flexDirection="column" height={height}>
            {!running ? (
              fields.slice(first, first + visible).map((label, offset) => (
                <Text
                  bold={field === first + offset}
                  color={field === first + offset ? t.color.accent : t.color.primary}
                  key={first + offset}
                  wrap="truncate-end"
                >
                  {field === first + offset ? '› ' : '  '}
                  {label}
                </Text>
              ))
            ) : (
              <Text color={t.color.muted}>
                {job?.status === 'awaiting_approval'
                  ? 'Approve this job in the Desk approval queue.'
                  : 'The frozen comparison runs in the background. Reopen to restore progress.'}
              </Text>
            )}
            {!scenarios.length ? (
              <Text color={t.color.muted}>Create scenarios with Ctrl+O in the interview first.</Text>
            ) : null}
          </Box>
        )}
        {!review ? (
          <Text color={t.color.muted}>
            {calls} calls · up to {(calls * tokens).toLocaleString()} output tokens · 90s per call
          </Text>
        ) : null}
        <Text color={error || statusError || job?.error ? t.color.error : t.color.muted} wrap="truncate-end">
          {statusError ||
            error ||
            job?.error ||
            (busy ? 'Saving request…' : 'No automatic probability updates. Model dispersion is not calibration.')}
        </Text>
      </Box>
    </ModalOverlay>
  )
}
