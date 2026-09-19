import { Box, Text, useInput } from '@superforecasting/ink'
import { useState } from 'react'

import type { InterviewRecord } from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'
import { windowOffset } from './overlayControls.js'

const sectionLabel = (section: string) => section.replaceAll('_', ' ')

export function InterviewRail({ record, index, t }: { record: InterviewRecord; index: number; t: Theme }) {
  const sections = [...new Set(record.document.questions.map(item => item.section))]
  const current = record.document.questions[index]?.section

  return (
    <Box flexDirection="column" flexShrink={0} marginRight={2} overflow="hidden" width={18}>
      <Text bold color={t.color.primary}>
        SECTIONS
      </Text>
      {sections.map(section => {
        const questions = record.document.questions.filter(item => item.section === section)

        const answered = questions.filter(item =>
          record.document.answers.some(answer => answer.question_id === item.id)
        ).length

        return (
          <Text color={current === section ? t.color.accent : t.color.muted} key={section} wrap="truncate-end">
            {current === section ? '›' : ' '} {sectionLabel(section)} {answered}/{questions.length}
          </Text>
        )
      })}
      <Text color={!current ? t.color.accent : t.color.muted}> Review</Text>
      <Text bold color={t.color.accent}>
        [Ctrl+L Outline]
      </Text>
    </Box>
  )
}

export function InterviewContext({ record, index, t }: { record: InterviewRecord; index: number; t: Theme }) {
  const question = record.document.questions[index]
  const answer = record.document.answers.find(item => item.question_id === question?.id)

  return (
    <Box flexDirection="column" flexShrink={0} marginLeft={2} overflow="hidden" width={24}>
      <Text bold color={t.color.primary}>
        SAVED CONTEXT
      </Text>
      <Text color={t.color.muted}>Revision {record.revision}</Text>
      <Text color={t.color.muted}>{record.document.evidence_refs.length} evidence items</Text>
      <Text color={t.color.muted}>{record.document.assumptions.length} assumptions</Text>
      <Text color={t.color.muted}>{record.document.scenarios.length} scenarios</Text>
      <Text color={t.color.primary}>{answer ? `${answer.status} · ${answer.actor}` : 'Not confirmed'}</Text>
      {answer ? (
        <Text color={t.color.muted} wrap="truncate-end">
          {answer.status === 'answered'
            ? [Array.isArray(answer.value) ? answer.value.join(', ') : answer.value, answer.custom_text]
                .filter(value => value != null)
                .join(' · ')
            : answer.note || 'No belief inferred'}
        </Text>
      ) : null}
      <Text color={t.color.muted}>Only confirmed answers are durable.</Text>
      <Text color={t.color.muted}>Scenarios do not change the active forecast.</Text>
    </Box>
  )
}

export function InterviewOutline({
  record,
  index,
  cols,
  rows,
  t,
  blocked,
  onSelect,
  onClose
}: {
  record: InterviewRecord
  index: number
  cols: number
  rows: number
  t: Theme
  blocked: boolean
  onSelect: (index: number) => void
  onClose: () => void
}) {
  const [selected, setSelected] = useState(index)
  const questions = record.document.questions
  const count = questions.length + 1
  const visible = Math.max(2, Math.min(20, rows - 12))
  const offset = windowOffset(count, selected, visible)
  useInput(
    (input, key, event) => {
      ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()

      if (key.escape) {
        onClose()
      } else if (key.return) {
        onSelect(selected)
      } else if (key.upArrow || key.downArrow || key.pageUp || key.pageDown) {
        const step = key.pageUp ? -visible : key.pageDown ? visible : key.upArrow ? -1 : 1
        setSelected(value => Math.max(0, Math.min(count - 1, value + step)))
      } else if (key.leftArrow || key.rightArrow) {
        const section = questions[selected]?.section
        const direction = key.leftArrow ? -1 : 1
        let target = selected + direction

        while (target >= 0 && target < questions.length && questions[target]?.section === section) {
          target += direction
        }

        setSelected(Math.max(0, Math.min(count - 1, target)))
      }
    },
    { isActive: !blocked }
  )

  return (
    <ModalOverlay
      cols={cols}
      footerHint="[↑↓] [←→ Section] [PgUp/Dn] [Enter Open] [Esc]"
      maxHeight={34}
      rows={rows}
      t={t}
      title="INTERVIEW OUTLINE"
      verticalMargin={2}
    >
      <Text color={t.color.muted} wrap="truncate-end">
        {record.document.title}
      </Text>
      <Text color={t.color.muted} wrap="truncate-end">
        Answered / Unknown / Skipped are saved states; — means unconfirmed.
      </Text>
      {Array.from({ length: count }, (_, at) => at)
        .slice(offset, offset + visible)
        .map(at => {
          const item = questions[at]
          const answer = record.document.answers.find(value => value.question_id === item?.id)

          return (
            <Text
              color={selected === at ? t.color.accent : t.color.primary}
              key={item?.id ?? 'review'}
              wrap="truncate-end"
            >
              {selected === at ? '›' : ' '}{' '}
              {item
                ? `[${answer?.status ?? '—'}] ${sectionLabel(item.section)} · ${item.prompt}`
                : 'Review answers and readiness'}
            </Text>
          )
        })}
      <Text color={t.color.muted} wrap="truncate-end">
        {selected + 1}/{count} · Opening a question never confirms an answer.
      </Text>
    </ModalOverlay>
  )
}
