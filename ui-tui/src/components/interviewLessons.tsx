import { Box, ScrollBox, type ScrollBoxHandle, Text, useInput } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type { InterviewLessonsResponse, InterviewRecord } from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'

export function InterviewLessons({
  gw,
  record,
  cols,
  rows,
  t,
  blocked,
  onClose
}: {
  gw: Pick<GatewayClient, 'request'>
  record: InterviewRecord
  cols: number
  rows: number
  t: Theme
  blocked: boolean
  onClose: () => void
}) {
  const [data, setData] = useState<InterviewLessonsResponse | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [selected, setSelected] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const scroll = useRef<ScrollBoxHandle>(null)
  const height = Math.max(3, Math.min(34, rows - 2) - 10)
  useEffect(() => {
    let live = true
    setData(null)
    setError('')
    setSelected(0)
    setExpanded(false)
    void gw
      .request('forecast.interview.lessons', { interview_id: record.interview_id, revision: record.revision })
      .then(result => {
        if (!live) {
          return
        }

        if (
          result.interview_id !== record.interview_id ||
          result.revision !== record.revision ||
          result.context_digest !== (record.document.context_digest ?? null)
        ) {
          setError('Guidance belongs to a different interview revision. Press r to retry.')

          return
        }

        setData(result)
      })
      .catch(cause => {
        if (live) {
          setError(`${String(cause)} · Press r to retry.`)
        }
      })

    return () => {
      live = false
    }
  }, [gw, record.interview_id, record.revision, record.document.context_digest, attempt])
  const lesson = data?.lessons[selected]
  useInput(
    (input, key, event) => {
      if ('stopImmediatePropagation' in event && typeof event.stopImmediatePropagation === 'function') {
        event.stopImmediatePropagation()
      }

      if (key.escape) {
        onClose()
      } else if (input === 'r' && error) {
        setAttempt(value => value + 1)
      } else if (key.return) {
        setExpanded(value => !value)
        scroll.current?.scrollTo(0)
      } else if (key.leftArrow || key.rightArrow) {
        setSelected(value => Math.max(0, Math.min((data?.lessons.length ?? 1) - 1, value + (key.rightArrow ? 1 : -1))))
        setExpanded(false)
        scroll.current?.scrollTo(0)
      } else if (key.upArrow || key.downArrow || key.pageUp || key.pageDown) {
        scroll.current?.scrollBy((key.upArrow || key.pageUp ? -1 : 1) * (key.pageUp || key.pageDown ? height : 1))
      }
    },
    { isActive: !blocked }
  )

  return (
    <ModalOverlay
      cols={cols}
      footerHint="[←→] [Enter Details] [↑↓ Read] [Esc]"
      maxHeight={34}
      rows={rows}
      t={t}
      title="FROZEN GUIDANCE"
      verticalMargin={2}
    >
      <Text color={t.color.muted}>Advisory only. Guidance never changes a forecast automatically.</Text>
      {error ? (
        <Text color={t.color.error}>{error}</Text>
      ) : !data ? (
        <Text color={t.color.muted}>Loading frozen guidance…</Text>
      ) : (
        <>
          <Text color={t.color.accent} wrap="truncate-end">
            {data.lessons.filter(item => item.included).length} included ·{' '}
            {data.lessons.filter(item => !item.included).length} excluded
            {lesson ? ` · ${selected + 1}/${data.lessons.length}` : ''}
          </Text>
          <ScrollBox
            decstbm={false}
            flexDirection="column"
            flexShrink={0}
            followContent={false}
            height={height}
            ref={scroll}
          >
            <Box flexDirection="column" flexShrink={0}>
              {!lesson ? (
                <Text color={t.color.primary}>
                  {data.policy
                    ? 'No lessons matched this frozen context.'
                    : 'This historical interview has no frozen lesson selection. No current guidance was added.'}
                </Text>
              ) : (
                <>
                  <Text bold color={lesson.included ? t.color.primary : t.color.muted}>
                    {lesson.included ? 'Included guidance' : 'Excluded guidance'} · {lesson.reason.replaceAll('_', ' ')}
                  </Text>
                  {!expanded && lesson.guidance ? <Text color={t.color.primary}>{lesson.guidance}</Text> : null}
                  {!expanded ? (
                    <>
                      <Text color={t.color.muted}>
                        {lesson.support_score_count} supporting scores · {lesson.distinct_outcome_count} distinct
                        outcomes
                      </Text>
                      <Text color={t.color.muted}>
                        Independent clusters: {lesson.independent_cluster_count ?? 'unknown'}. Outcome counts do not
                        establish independence.
                      </Text>
                      <Text color={t.color.muted}>Limited support is not proof of a reliable correction.</Text>
                    </>
                  ) : null}
                  {expanded ? (
                    <>
                      <Text color={t.color.primary}>
                        Scope: {lesson.scope_type}
                        {lesson.scope_ref ? ` · ${lesson.scope_ref}` : ''}
                      </Text>
                      <Text color={t.color.muted}>Applicability: {JSON.stringify(lesson.applicability)}</Text>
                      <Text color={t.color.muted}>
                        Lesson: {lesson.lesson_id} · revision {lesson.revision}
                      </Text>
                      <Text color={t.color.muted}>Lesson digest: {lesson.content_digest}</Text>
                      <Text color={t.color.muted}>
                        Score references: {lesson.source_score_ids.join(', ') || 'none'}
                      </Text>
                      <Text color={t.color.muted}>
                        Postmortem references: {lesson.source_postmortem_ids.join(', ') || 'none'}
                      </Text>
                      <Text color={t.color.muted}>
                        Policy: {data.policy} · cutoff {data.cutoff}
                      </Text>
                      <Text color={t.color.muted}>Context digest: {data.context_digest}</Text>
                    </>
                  ) : (
                    <Text color={t.color.accent}>[Enter] Inspect applicability and provenance</Text>
                  )}
                </>
              )}
            </Box>
          </ScrollBox>
        </>
      )}
    </ModalOverlay>
  )
}
