import { randomUUID } from 'node:crypto'

import { useStore } from '@nanostores/react'
import { Box, ScrollBox, type ScrollBoxHandle, Text, useInput, useTerminalSize } from '@superforecasting/ink'
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

import { InterviewEvaluation } from './interviewEvaluation.js'
import { InterviewGeneration } from './interviewGeneration.js'
import { InterviewContext, InterviewOutline, InterviewRail } from './interviewNavigation.js'
import { InterviewScenarios } from './interviewScenarios.js'
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
  const { columns: cols, rows } = useTerminalSize()
  const blocked = useStore($globalModal)
  const [record, setRecord] = useState<InterviewRecord | null>(null)
  const [index, setIndex] = useState(0)
  const [text, setText] = useState('')
  const [note, setNote] = useState('')
  const [noteEditing, setNoteEditing] = useState(false)
  const [closeConfirm, setCloseConfirm] = useState(false)
  const noteDrafts = useRef(new Map<string, string>())
  const dirtyQuestions = useRef(new Set<string>())
  const [choice, setChoice] = useState(0)
  const [selected, setSelected] = useState<string[]>([])
  const [customEditing, setCustomEditing] = useState(false)
  const [pane, setPane] = useState<'answers' | 'generation' | 'scenarios' | 'evaluation' | 'outline'>('answers')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [freshConfirm, setFreshConfirm] = useState(false)
  const freshId = useRef<string | null>(null)
  const [preview, setPreview] = useState<InterviewPreviewResponse | null>(null)
  const pending = useRef<InterviewAnswerRequest | null>(null)
  const mounted = useRef(true)
  const saving = useRef(false)
  const id = useRef(randomUUID())
  const scroll = useRef<ScrollBoxHandle>(null)
  const drafts = useRef(new Map<string, string>())
  const choiceDrafts = useRef(new Map<string, { choice: number; selected: string[] }>())
  const questions = record?.document.questions ?? []
  const question = questions[index]
  const review = record !== null && index >= questions.length
  const choiceVisible = Math.max(2, Math.min(8, rows - 17))
  const choiceStart = Math.max(0, choice - choiceVisible + 1)

  const select = (next: InterviewRecord, at: number) => {
    setRecord(next)
    setIndex(at)
    setPreview(null)
    const item = next.document.questions[at]
    const prior = next.document.answers.find(answer => answer.question_id === item?.id)
    setNote(noteDrafts.current.get(item?.id ?? '') ?? prior?.note ?? '')
    setNoteEditing(false)
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

    const choiceQuestion = item?.kind === 'single' || item?.kind === 'multiple'
    const priorChoice = item?.choices.findIndex(option => option.id === prior?.value) ?? -1

    const custom =
      prior?.custom_text ??
      (item?.kind === 'single' && priorChoice < 0 && typeof prior?.value === 'string' ? prior.value : '')

    setText(
      drafts.current.get(item?.id ?? '') ??
        (choiceQuestion ? custom : prior?.value == null ? suggested : String(prior.value))
    )
    const remembered = choiceDrafts.current.get(item?.id ?? '')
    setChoice(
      remembered?.choice ??
        (custom
          ? (item?.choices.length ?? 0)
          : Math.max(
              0,
              priorChoice >= 0
                ? priorChoice
                : (item?.choices.findIndex(
                    option => option.id === (item.id === 'outcome' && context?.kind === 'series' ? 'numeric' : null)
                  ) ?? 0)
            ))
    )
    setSelected(remembered?.selected ?? (Array.isArray(prior?.value) ? prior.value : []))
    setCustomEditing(false)
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
        value = question.choices[choice]?.id ?? null

        if (value === null && !text.trim()) {
          setError('Write a custom answer, or choose Unknown.')

          return
        }
      } else if (question.kind === 'multiple') {
        value = selected

        if (!selected.length && !text.trim()) {
          setError('Select an option or write a custom answer, or choose Unknown.')

          return
        }
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
      note,
      custom_text:
        status === 'answered' &&
        question.allow_custom &&
        (question.kind === 'multiple' || (question.kind === 'single' && choice === question.choices.length))
          ? text.trim() || null
          : null
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
        noteDrafts.current.delete(question.id)
        dirtyQuestions.current.delete(question.id)
        drafts.current.delete(question.id)
        choiceDrafts.current.delete(question.id)
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

  const freshReview = async () => {
    if (!record?.document.question_id || saving.current) {
      return
    }

    saving.current = true
    setBusy(true)
    setError('')
    freshId.current ??= randomUUID()

    try {
      const next = await gw.request('forecast.interview.begin', {
        interview_id: freshId.current,
        question_id: record.document.question_id
      })

      if (mounted.current) {
        noteDrafts.current.clear()
        dirtyQuestions.current.clear()
        drafts.current.clear()
        choiceDrafts.current.clear()
        pending.current = null
        freshId.current = null
        select(next, 0)
        setFreshConfirm(false)
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
      if (
        key.escape ||
        key.tab ||
        key.pageUp ||
        key.pageDown ||
        (key.ctrl && ['u', 's', 'g', 'o', 'e', 'n', 'l', 't'].includes(input))
      ) {
        ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()
      }

      if (closeConfirm) {
        ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()

        if (key.escape) {
          setCloseConfirm(false)
        } else if (key.ctrl && input === 'x') {
          onClose()
        }

        return
      }

      if (freshConfirm) {
        ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()

        if (key.escape) {
          setFreshConfirm(false)
        } else if (key.return) {
          void freshReview()
        }

        return
      }

      if (key.ctrl && input === 'n' && record?.document.mode === 'update' && !busy) {
        setFreshConfirm(true)

        return
      }

      if (key.pageUp || key.pageDown) {
        scroll.current?.scrollBy(key.pageUp ? -5 : 5)

        return
      }

      if (key.escape) {
        if (busy) {
          return
        }

        if (noteEditing) {
          setNoteEditing(false)

          return
        }

        if (customEditing) {
          setCustomEditing(false)

          return
        }

        if (dirtyQuestions.current.size) {
          setCloseConfirm(true)
        } else {
          onClose()
        }

        return
      }

      if (busy || !record) {
        return
      }

      if (key.ctrl && (input === 'g' || input === 'o' || input === 'e' || input === 'l')) {
        if (question) {
          choiceDrafts.current.set(question.id, { choice, selected })
        }

        setPane(input === 'l' ? 'outline' : input === 'g' ? 'generation' : input === 'e' ? 'evaluation' : 'scenarios')

        return
      }

      if (key.tab) {
        if (question) {
          choiceDrafts.current.set(question.id, { choice, selected })
        }

        select(record, Math.max(0, Math.min(questions.length, index + (key.shift ? -1 : 1))))

        return
      }

      if (review) {
        if (key.return) {
          void commit()
        }

        return
      }

      if (key.ctrl && input === 't') {
        setNoteEditing(value => !value)

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

      if (noteEditing) {
        return
      }

      if (!customEditing && (question?.kind === 'single' || question?.kind === 'multiple')) {
        const last = question.choices.length - (question.allow_custom ? 0 : 1)

        if (key.upArrow) {
          if (choice > 0 && question.kind === 'single') {
            dirtyQuestions.current.add(question.id)
          }

          setChoice(value => Math.max(0, value - 1))
        }

        if (key.downArrow) {
          if (choice < last && question.kind === 'single') {
            dirtyQuestions.current.add(question.id)
          }

          setChoice(value => Math.min(last, value + 1))
        }

        if (key.return && key.ctrl && question.kind === 'multiple') {
          void save()
        } else if (key.return && choice === question.choices.length) {
          setCustomEditing(true)
        } else if (question.kind === 'multiple' && (input === ' ' || key.return)) {
          const id = question.choices[choice]?.id

          if (id) {
            dirtyQuestions.current.add(question.id)
            setSelected(values => (values.includes(id) ? values.filter(value => value !== id) : [...values, id]))
          }
        } else if (key.return && question.kind === 'single') {
          void save()
        }
      }
    },
    { isActive: !blocked && pane === 'answers' }
  )

  const wide = cols >= 120
  const contentWidth = (cols < 100 ? Math.max(40, cols - 2) : Math.min(cols - 6, wide ? 140 : 100)) - 6
  const questionWidth = contentWidth - (wide ? 46 : 0)
  const height = Math.max(3, Math.min(rows - 2, 34) - 12)

  if (closeConfirm) {
    return (
      <ModalOverlay
        cols={cols}
        footerHint="[Esc Keep editing] [Ctrl+X Discard and close]"
        maxHeight={14}
        rows={rows}
        t={t}
        title="UNSAVED INTERVIEW EDITS"
        verticalMargin={2}
      >
        <Text color={t.color.primary}>{dirtyQuestions.current.size} question(s) have unconfirmed edits.</Text>
        <Text color={t.color.muted}>
          Confirmed answers remain saved. Keep editing to confirm answers or save Unknown with a note.
        </Text>
      </ModalOverlay>
    )
  }

  if (freshConfirm) {
    return (
      <ModalOverlay
        cols={cols}
        footerHint="[Enter Start] [Esc Keep current]"
        maxHeight={16}
        rows={rows}
        t={t}
        title="START A FRESH REVIEW"
        verticalMargin={2}
      >
        <Text color={t.color.primary}>
          Capture the current forecast and latest evidence. Saved assumptions and scenarios carry forward with
          provenance; the earlier interview remains in history.
        </Text>
        <Text color={t.color.muted}>
          Unconfirmed text in this panel will be discarded. Save answers first if you want to keep them.
        </Text>
        {busy ? <Text color={t.color.accent}>Creating review…</Text> : null}
        {error ? <Text color={t.color.error}>{error}</Text> : null}
      </ModalOverlay>
    )
  }

  if (record && pane === 'generation') {
    return (
      <InterviewGeneration
        blocked={Boolean(blocked)}
        cols={cols}
        gw={gw}
        onClose={() => setPane('answers')}
        onReview={next => {
          const known = new Set(record.document.questions.map(item => item.id))
          const at = next.document.questions.findIndex(item => !known.has(item.id))
          select(next, at < 0 ? Math.min(index, next.document.questions.length) : at)
          setPane('answers')
        }}
        record={record}
        rows={rows}
        t={t}
      />
    )
  }

  if (record && pane === 'evaluation') {
    return (
      <InterviewEvaluation
        blocked={!!blocked}
        cols={cols}
        gw={gw}
        onClose={() => setPane('answers')}
        record={record}
        rows={rows}
        t={t}
      />
    )
  }

  if (record && pane === 'outline') {
    return (
      <InterviewOutline
        blocked={Boolean(blocked)}
        cols={cols}
        index={index}
        onClose={() => setPane('answers')}
        onSelect={at => {
          select(record, at)
          setPane('answers')
        }}
        record={record}
        rows={rows}
        t={t}
      />
    )
  }

  if (record && pane === 'scenarios') {
    return (
      <InterviewScenarios
        blocked={Boolean(blocked)}
        cols={cols}
        gw={gw}
        onAssumptionSaved={next => select(next, index)}
        onClose={() => setPane('answers')}
        onSaved={next => {
          select(next, index)
          setPane('answers')
        }}
        record={record}
        rows={rows}
        t={t}
      />
    )
  }

  return (
    <ModalOverlay
      cols={cols}
      footerHint={
        record?.document.mode === 'update'
          ? '[^G Ask] [^O Scenarios] [^E Run] [^N Fresh] [Esc]'
          : '[^G Ask] [^O Scenarios] [^E Compare] [Esc]'
      }
      maxHeight={34}
      maxWidth={wide ? 140 : 100}
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
          {!review && question ? '[^T Note] ' : ''}
          {review
            ? 'Review answers'
            : `${index + 1}/${questions.length} · ${question?.section.replaceAll('_', ' ') ?? ''}`}
          {busy ? ' · saving…' : ' · [Tab/⇧Tab] [^L List]'}
        </Text>
        <Box flexDirection="row" flexShrink={0} height={height} overflow="hidden">
          {wide && record ? <InterviewRail index={index} record={record} t={t} /> : null}
          <ScrollBox
            decstbm={false}
            flexDirection="column"
            flexShrink={0}
            followContent={false}
            height={height}
            key={`${index}:${record?.interview_id}`}
            ref={scroll}
            width={questionWidth}
          >
            {question ? (
              <>
                <Text bold color={t.color.primary} wrap={noteEditing ? 'truncate-end' : 'wrap'}>
                  {question.prompt}
                  {question.required ? ' *' : ''}
                </Text>
                {!noteEditing ? <Text color={t.color.muted}>{question.rationale}</Text> : null}
                {noteEditing ? (
                  <>
                    <Text color={t.color.accent}>REASONING / UNCERTAINTY NOTE</Text>
                    {rows >= 26 ? (
                      <Text color={t.color.muted}>
                        Record a source, reason, or what would resolve the uncertainty. This note is not a probability.
                      </Text>
                    ) : null}
                    <TextInput
                      columns={Math.max(20, questionWidth - 2)}
                      focus={!busy && !blocked}
                      immediateChange
                      key={`${question.id}:note`}
                      multiline
                      onChange={value => {
                        noteDrafts.current.set(question.id, value)
                        dirtyQuestions.current.add(question.id)
                        setNote(value)
                      }}
                      onSubmit={() => setNoteEditing(false)}
                      placeholder="Why uncertain? What evidence would help?"
                      value={note}
                    />
                  </>
                ) : (question.kind === 'single' || question.kind === 'multiple') && !customEditing ? (
                  [
                    ...question.choices,
                    ...(question.allow_custom
                      ? [{ id: '__custom', label: text ? `Other: ${text}` : 'Other — write your answer' }]
                      : [])
                  ]
                    .slice(choiceStart, choiceStart + choiceVisible)
                    .map((option, offset) => {
                      const at = choiceStart + offset

                      return (
                        <Text color={at === choice ? t.color.accent : t.color.primary} key={option.id}>
                          {at === choice ? '› ' : '  '}
                          {question.kind === 'multiple' && at < question.choices.length
                            ? selected.includes(option.id)
                              ? '[x] '
                              : '[ ] '
                            : ''}
                          {option.label}
                        </Text>
                      )
                    })
                ) : (
                  <TextInput
                    columns={Math.max(20, questionWidth - 2)}
                    focus={!busy && !blocked}
                    immediateChange
                    key={question.id}
                    multiline
                    onChange={value => {
                      dirtyQuestions.current.add(question.id)
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
                <Text color={t.color.muted}>
                  {record?.document.mode === 'create'
                    ? 'Creating a question saves the interview, not a scored forecast.'
                    : 'This review preserves the active forecast.'}{' '}
                  Compare scenarios, then explicitly promote an unconditional baseline if warranted.
                </Text>
                <Text color={t.color.muted}>
                  Answer coverage is not evidence quality. Use{' '}
                  <Text bold color={t.color.accent}>
                    [Ctrl+L Outline]
                  </Text>{' '}
                  to revisit gaps.
                </Text>
                {preview?.unanswered.map(item => (
                  <Text color={t.color.error} key={item}>
                    Required: {item}
                  </Text>
                ))}
                {preview?.issues.map((issue, at) => (
                  <Text color={issue.severity === 'error' ? t.color.error : t.color.muted} key={at}>
                    {String(issue.field)}: {String(issue.message)} {String(issue.fix ?? '')}
                  </Text>
                ))}
                {record?.document.answers.map(answer => (
                  <Text color={t.color.muted} key={answer.question_id}>
                    {answer.question_id}:{' '}
                    {answer.status === 'answered'
                      ? [Array.isArray(answer.value) ? answer.value.join(', ') : answer.value, answer.custom_text]
                          .filter(value => value !== null && value !== undefined)
                          .join(' · ')
                      : answer.status}{' '}
                    · {answer.actor}
                    {answer.note ? ` · Note: ${answer.note}` : ''}
                  </Text>
                ))}
              </>
            ) : null}
          </ScrollBox>
          {wide && record ? <InterviewContext index={index} record={record} t={t} /> : null}
        </Box>
        <Text color={t.color.accent}>
          {!review && question ? '[^T Note] ' : ''}
          {review
            ? record?.document.mode === 'create'
              ? '[Enter Create question] [PgUp/Dn Review]'
              : 'Review draft saved · [PgUp/Dn Review]'
            : customEditing
              ? '[^Enter Save custom answer] [Esc Choices]'
              : noteEditing
                ? '[^Enter Back] [^U Save Unknown] [^S Save Skipped]'
                : question?.kind === 'single'
                  ? '[↑↓ Choose] [Enter Confirm] [^U Unknown] [^S Skip]'
                  : question?.kind === 'multiple'
                    ? '[Space Toggle] [^Enter Save] [^U Unknown] [^S Skip]'
                    : '[Enter New line] [^Enter Save] [^U Unknown] [^S Skip]'}
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
