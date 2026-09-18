import { randomUUID } from 'node:crypto'

import { useStore } from '@nanostores/react'
import { Box, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import { $globalModal } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type {
  ForecastMarketSeed,
  InterviewAnswerRequest,
  InterviewPreviewResponse,
  InterviewRecord
} from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'
import { TextInput } from './textInput.js'

export function ForecastInterview({
  gw,
  questionId = null,
  seed = null,
  interviewId = null,
  onClose,
  onDone,
  t
}: {
  gw: GatewayClient
  questionId?: string | null
  seed?: ForecastMarketSeed | null
  interviewId?: string | null
  onClose: () => void
  onDone?: (id: string) => void
  t: Theme
}) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const rows = stdout?.rows ?? 24
  const blocked = useStore($globalModal)
  const [record, setRecord] = useState<InterviewRecord | null>(null)
  const [index, setIndex] = useState(0)
  const [text, setText] = useState('')
  const [choice, setChoice] = useState(0)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<InterviewPreviewResponse | null>(null)
  const pending = useRef<InterviewAnswerRequest | null>(null)
  const mounted = useRef(true)
  const saving = useRef(false)
  const id = useRef(randomUUID())
  const scroll = useRef<ScrollBoxHandle>(null)
  const drafts = useRef(new Map<string, string>())
  const questions = record?.document.questions ?? []
  const question = questions[index]
  const review = record !== null && index >= questions.length

  const select = (next: InterviewRecord, at: number) => {
    setRecord(next)
    setIndex(at)
    setPreview(null)
    const item = next.document.questions[at]
    const prior = next.document.answers.find(answer => answer.question_id === item?.id)
    const context = next.document.seed

    const suggested =
      item?.id === 'title' && context !== null && context !== undefined
        ? next.document.title
        : item?.id === 'source'
          ? (context?.source_url ?? '')
          : item?.id === 'units'
            ? (context?.units ?? '')
            : item?.id === 'deadline'
              ? (context?.close_time ?? '')
              : ''

    setText(
      drafts.current.get(item?.id ?? '') ??
        (prior?.value == null ? suggested : Array.isArray(prior.value) ? prior.value.join('\n') : String(prior.value))
    )
    setChoice(
      Math.max(
        0,
        item?.choices.findIndex(
          option =>
            option.id === (prior?.value ?? (item.id === 'outcome' && context?.kind === 'series' ? 'numeric' : null))
        ) ?? 0
      )
    )
  }

  useEffect(() => {
    let active = true
    mounted.current = true
    setBusy(true)

    const load = async () => {
      if (interviewId) {
        return gw.request('forecast.interview.read', { interview_id: interviewId })
      }

      if (!seed) {
        const result = await gw.request('forecast.interview.list', { question_id: questionId })

        if (result.interviews[0]) {
          return result.interviews[0]
        }
      }

      return gw.request('forecast.interview.begin', { interview_id: id.current, question_id: questionId, seed })
    }

    void load()
      .then(next => {
        if (!active) {
          return
        }

        const answered = new Set(next.document.answers.map(answer => answer.question_id))
        const unanswered = next.document.questions.findIndex(item => !answered.has(item.id))
        select(next, unanswered < 0 ? next.document.questions.length : unanswered)
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : String(cause))
        }
      })
      .finally(() => {
        if (active) {
          setBusy(false)
        }
      })

    return () => {
      active = false
      mounted.current = false
    }
  }, [gw, questionId, seed, interviewId])

  useEffect(() => {
    if (!review || !record) {
      return
    }

    let active = true
    void gw
      .request('forecast.interview.preview', { interview_id: record.interview_id, revision: record.revision })
      .then(result => {
        if (active) {
          setPreview(result)
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : String(cause))
        }
      })

    return () => {
      active = false
    }
  }, [gw, record, review])

  const save = async (status: InterviewAnswerRequest['status'] = 'answered') => {
    if (!record || !question || saving.current) {
      return
    }

    let value: InterviewAnswerRequest['value'] = null

    if (status === 'answered') {
      if (question.kind === 'single') {
        value = question.choices[choice]?.id ?? text
      } else if (question.kind === 'number' || question.kind === 'probability') {
        if (!text.trim() || !Number.isFinite(Number(text))) {
          setError('Enter a finite number, or choose Unknown.')

          return
        }

        value = Number(text)
      } else {
        value = text
      }
    }

    const fields = {
      interview_id: record.interview_id,
      expected_revision: record.revision,
      question_id: question.id,
      status,
      value,
      note: ''
    }

    const old = pending.current

    const request =
      old && JSON.stringify({ ...old, request_id: '' }) === JSON.stringify({ ...fields, request_id: '' })
        ? old
        : { ...fields, request_id: randomUUID() }

    pending.current = request
    saving.current = true
    setBusy(true)
    setError('')

    try {
      const next = await gw.request('forecast.interview.answer', request)

      if (mounted.current) {
        pending.current = null
        drafts.current.delete(question.id)
        select(next, Math.min(index + 1, next.document.questions.length))
      }
    } catch (cause) {
      if (mounted.current) {
        setError(cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      saving.current = false

      if (mounted.current) {
        setBusy(false)
      }
    }
  }

  const commit = async () => {
    if (!record || !preview?.committable || saving.current || record.document.mode !== 'create') {
      return
    }

    saving.current = true
    setBusy(true)
    setError('')

    try {
      const result = await gw.request('forecast.interview.commit', {
        interview_id: record.interview_id,
        revision: record.revision
      })

      if (mounted.current) {
        onDone?.(result.question_id)
        onClose()
      }
    } catch (cause) {
      if (mounted.current) {
        setError(cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      saving.current = false

      if (mounted.current) {
        setBusy(false)
      }
    }
  }

  useInput(
    (input, key, event) => {
      if (key.escape || key.tab || key.pageUp || key.pageDown || (key.ctrl && (input === 'u' || input === 's'))) {
        ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()
      }

      if (key.pageUp || key.pageDown) {
        scroll.current?.scrollBy(key.pageUp ? -5 : 5)

        return
      }

      if (key.escape) {
        onClose()

        return
      }

      if (busy || !record) {
        return
      }

      if (key.tab) {
        select(record, Math.max(0, Math.min(questions.length, index + (key.shift ? -1 : 1))))

        return
      }

      if (review) {
        if (key.return) {
          void commit()
        }

        return
      }

      if (key.ctrl && input === 'u') {
        void save('unknown')

        return
      }

      if (key.ctrl && input === 's') {
        void save('skipped')

        return
      }

      if (question?.kind === 'single') {
        if (key.upArrow) {
          setChoice(value => Math.max(0, value - 1))
        }

        if (key.downArrow) {
          setChoice(value => Math.min(question.choices.length - 1, value + 1))
        }

        if (key.return) {
          void save()
        }
      }
    },
    { isActive: !blocked }
  )

  const height = Math.max(3, Math.min(rows - 2, 34) - 12)

  return (
    <ModalOverlay
      cols={cols}
      footerHint="[Tab/⇧Tab Move] [^U Unknown] [^S Skip] [Esc Close]"
      maxHeight={34}
      maxWidth={100}
      rows={rows}
      t={t}
      title={`FORECAST INTERVIEW · ${record?.document.mode === 'update' ? 'Update beliefs' : 'New question'}`}
      verticalMargin={2}
    >
      <Box flexDirection="column" flexGrow={1} minHeight={0}>
        <Text color={t.color.muted} wrap="truncate-end">
          {record?.document.title ?? 'Opening saved interview…'}
        </Text>
        <Text color={t.color.accent}>
          {review
            ? 'Review answers'
            : `${index + 1}/${questions.length} · ${question?.section.replaceAll('_', ' ') ?? ''}`}
          {busy ? ' · saving…' : ''}
        </Text>
        <ScrollBox
          decstbm={false}
          flexDirection="column"
          followContent={false}
          height={height}
          key={`${index}:${record?.interview_id}`}
          ref={scroll}
        >
          {question ? (
            <>
              <Text bold color={t.color.primary}>
                {question.prompt}
                {question.required ? ' *' : ''}
              </Text>
              <Text color={t.color.muted}>{question.rationale}</Text>
              {question.kind === 'single' ? (
                question.choices.map((option, at) => (
                  <Text color={at === choice ? t.color.accent : t.color.primary} key={option.id}>
                    {at === choice ? '› ' : '  '}
                    {option.label}
                  </Text>
                ))
              ) : (
                <TextInput
                  columns={Math.max(20, Math.min(cols - 10, 90))}
                  focus={!busy && !blocked}
                  immediateChange
                  key={question.id}
                  multiline
                  onChange={value => {
                    drafts.current.set(question.id, value)
                    setText(value)
                  }}
                  onSubmit={() => void save()}
                  placeholder="Your answer; Unknown and Skip are always available"
                  value={text}
                />
              )}
            </>
          ) : review ? (
            <>
              <Text color={t.color.primary}>
                Answers are saved. Nothing has changed the active forecast probability.
              </Text>
              {record?.document.answers.map(answer => (
                <Text color={t.color.muted} key={answer.question_id}>
                  {answer.question_id}: {answer.status === 'answered' ? String(answer.value) : answer.status} ·{' '}
                  {answer.actor}
                </Text>
              ))}
              {preview?.unanswered.map(item => (
                <Text color={t.color.error} key={item}>
                  Required: {item}
                </Text>
              ))}
              {preview?.issues.map((issue, at) => (
                <Text color={t.color.error} key={at}>
                  {String(issue.message)}
                </Text>
              ))}
            </>
          ) : null}
        </ScrollBox>
        <Text color={t.color.accent}>
          {review
            ? record?.document.mode === 'create'
              ? '[Enter Create question] [PgUp/Dn Review]'
              : 'Review draft saved · [PgUp/Dn Review]'
            : question?.kind === 'single'
              ? '[↑↓ Choose] [Enter Confirm]'
              : '[Enter New line] [Ctrl+Enter Save answer]'}
        </Text>
        {error ? (
          <Text color={t.color.error} wrap="truncate-end">
            {error}
          </Text>
        ) : null}
      </Box>
    </ModalOverlay>
  )
}
