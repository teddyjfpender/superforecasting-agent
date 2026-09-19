import { randomUUID } from 'node:crypto'

import { Box, ScrollBox, type ScrollBoxHandle, Text, useInput } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type { InterviewRecord, InterviewScenario, InterviewScenarioSaveRequest } from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { InterviewAssumptionEditor } from './interviewAssumptionEditor.js'
import { ModalOverlay } from './modalOverlay.js'
import { TextInput } from './textInput.js'

export function InterviewScenarios({
  gw,
  record,
  cols,
  rows,
  t,
  blocked,
  onClose,
  onSaved,
  onAssumptionSaved
}: {
  gw: Pick<GatewayClient, 'request'>
  record: InterviewRecord
  cols: number
  rows: number
  t: Theme
  blocked: boolean
  onClose: () => void
  onSaved: (record: InterviewRecord) => void
  onAssumptionSaved: (record: InterviewRecord) => void
}) {
  const [selection, setSelection] = useState(0)
  const [scenario, setScenario] = useState<InterviewScenario | null>(null)
  const [naming, setNaming] = useState(false)
  const [editing, setEditing] = useState(false)
  const [details, setDetails] = useState(false)
  const scroll = useRef<ScrollBoxHandle>(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const locked = useRef(false)
  const alive = useRef(true)
  const [deleting, setDeleting] = useState<InterviewScenario | null>(null)
  const deletion = useRef<{ scenario_id: string; request_id: string } | null>(null)
  useEffect(
    () => () => {
      alive.current = false
    },
    []
  )
  const pending = useRef<InterviewScenarioSaveRequest | null>(null)
  const saved = record.document.scenarios
  const assumptions = record.document.assumptions
  const menu = ['New conditional scenario', 'New factor ablation', ...saved.map(item => `${item.name} · ${item.kind}`)]
  const visibleRows = Math.max(2, Math.min(12, rows - 17))
  const start = Math.max(0, selection - visibleRows + 1)

  const save = async () => {
    if (!scenario || locked.current) {
      return
    }

    if (!Object.keys(scenario.conditions).length && !scenario.excluded_assumption_ids.length) {
      setError('Select at least one condition or excluded factor.')

      return
    }

    locked.current = true
    setBusy(true)
    setError('')
    const fields = { interview_id: record.interview_id, expected_revision: record.revision, scenario }
    const previous = pending.current

    const request =
      previous && JSON.stringify({ ...previous, request_id: '' }) === JSON.stringify({ ...fields, request_id: '' })
        ? previous
        : { ...fields, request_id: randomUUID() }

    pending.current = request

    try {
      const next = await gw.request('forecast.interview.scenario.save', request)

      if (alive.current) {
        onSaved(next)
      }
    } catch (cause) {
      if (alive.current) {
        setError(cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      locked.current = false

      if (alive.current) {
        setBusy(false)
      }
    }
  }

  const remove = async () => {
    if (!deleting || locked.current) {
      return
    }

    locked.current = true
    setBusy(true)
    setError('')

    if (deletion.current?.scenario_id !== deleting.id) {
      deletion.current = { scenario_id: deleting.id, request_id: randomUUID() }
    }

    try {
      const next = await gw.request('forecast.interview.scenario.delete', {
        interview_id: record.interview_id,
        expected_revision: record.revision,
        ...deletion.current
      })

      if (alive.current) {
        onSaved(next)
      }
    } catch (cause) {
      if (alive.current) {
        setError(cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      locked.current = false

      if (alive.current) {
        setBusy(false)
      }
    }
  }

  useInput(
    (input, key, event) => {
      if (!naming || key.escape) {
        ;(event as unknown as { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.()
      }

      if (key.escape) {
        if (details) {
          setDetails(false)

          return
        }

        if (busy) {
          onClose()

          return
        }

        if (deleting) {
          setDeleting(null)

          return
        }

        if (naming) {
          setNaming(false)
        } else if (scenario) {
          setScenario(null)
          setSelection(0)
        } else {
          onClose()
        }

        return
      }

      if (details) {
        if (input === 'e') {setEditing(true)}

        if (key.pageUp || key.pageDown) {
          scroll.current?.scrollBy(key.pageUp ? -5 : 5)
        }

        return
      }

      if (busy || naming) {
        return
      }

      if (deleting) {
        if (key.return) {
          void remove()
        }

        return
      }

      const count = scenario ? assumptions.length : menu.length

      if (key.upArrow) {
        setSelection(value => Math.max(0, value - 1))
      }

      if (key.downArrow) {
        setSelection(value => Math.min(count - 1, value + 1))
      }

      if (!scenario) {
        if (key.ctrl && input === 'd' && saved[selection - 2]) {
          setDeleting(saved[selection - 2]!)

          return
        }

        if (key.return && assumptions.length) {
          const existing = saved[selection - 2]
          setScenario(
            existing
              ? structuredClone(existing)
              : {
                  id: randomUUID(),
                  actor: 'user',
                  name:
                    selection === 0
                      ? `Conditional scenario ${saved.length + 1}`
                      : `Factor ablation ${saved.length + 1}`,
                  kind: selection === 0 ? 'conditional' : 'ablation',
                  conditions: {},
                  excluded_assumption_ids: []
                }
          )
          setSelection(0)
        }

        return
      }

      if (key.ctrl && key.return) {
        void save()

        return
      }

      if (key.return) {
        setDetails(true)

        return
      }

      if (input === 'n') {
        setName(scenario.name)
        setNaming(true)

        return
      }

      const assumption = assumptions[selection]

      if (!assumption) {
        return
      }

      if (scenario.kind === 'conditional' && ['t', 'f', 'u'].includes(input)) {
        const conditions = { ...scenario.conditions }

        if (input === 'u') {
          delete conditions[assumption.id]
        } else {
          conditions[assumption.id] = input === 't'
        }

        setScenario({ ...scenario, conditions })
      }

      if (scenario.kind === 'ablation' && input === ' ') {
        const ids = scenario.excluded_assumption_ids
        setScenario({
          ...scenario,
          excluded_assumption_ids: ids.includes(assumption.id)
            ? ids.filter(id => id !== assumption.id)
            : [...ids, assumption.id]
        })
      }
    },
    { isActive: !blocked && !editing }
  )

  const hint = deleting
    ? '[Enter Delete scenario] [Esc Keep]'
    : naming
      ? '[Enter Set name] [Esc Back]'
      : !scenario
        ? '[↑↓ Select] [Enter Open] [^D Delete] [Esc Back]'
        : scenario.kind === 'conditional'
          ? '[t True] [f False] [u Free] [^Enter Save] [Esc Back]'
          : '[Space Include/exclude] [^Enter Save] [Esc Back]'

  if (editing && assumptions[selection]) {
    return (
      <InterviewAssumptionEditor
        assumption={assumptions[selection]!}
        blocked={blocked}
        cols={cols}
        gw={gw}
        onClose={() => setEditing(false)}
        onSaved={next => {
          onAssumptionSaved(next)
          setEditing(false)
        }}
        record={record}
        rows={rows}
        t={t}
      />
    )
  }

  if (details && assumptions[selection]) {
    const item = assumptions[selection]!

    return (
      <ModalOverlay
        cols={cols}
        footerHint="[e Edit] [PgUp/Dn Read] [Esc Back]"
        maxHeight={34}
        maxWidth={100}
        rows={rows}
        t={t}
        title="ASSUMPTION DETAILS"
        verticalMargin={2}
      >
        <ScrollBox
          decstbm={false}
          flexDirection="column"
          followContent={false}
          height={Math.max(3, Math.min(rows - 2, 34) - 8)}
          ref={scroll}
        >
          <Text bold color={t.color.primary}>
            {item.statement}
          </Text>
          <Text color={t.color.muted}>
            Attributed to: {item.actor} · uncertainty: {item.uncertainty}
          </Text>
          <Text color={t.color.primary}>
            Assumption probability: {item.probability === null ? 'Unknown' : item.probability}
          </Text>
          <Text color={t.color.primary}>{item.rationale || 'No rationale recorded yet.'}</Text>
          <Text color={t.color.muted}>Evidence: {item.evidence_refs.join(', ') || 'No linked evidence'}</Text>
        </ScrollBox>
      </ModalOverlay>
    )
  }

  return (
    <ModalOverlay
      cols={cols}
      footerHint={hint}
      maxHeight={34}
      maxWidth={100}
      rows={rows}
      t={t}
      title="ASSUMPTIONS & SCENARIOS"
      verticalMargin={2}
    >
      <Box flexDirection="column" minHeight={0}>
        <Text color={t.color.muted} wrap="truncate-end">
          {record.document.title} · revision {record.revision}
        </Text>
        {deleting ? (
          <Text color={t.color.primary}>Delete “{deleting.name}”? Its earlier revisions remain in history.</Text>
        ) : !assumptions.length ? (
          <Text color={t.color.primary}>Add assumptions in the Drivers question, or generate follow-ups first.</Text>
        ) : naming ? (
          <TextInput
            columns={Math.max(20, Math.min(cols - 10, 90))}
            focus={!blocked}
            onChange={setName}
            onSubmit={input => {
              if (input.trim() && input.length <= 300 && scenario) {
                setScenario({ ...scenario, name: input.trim() })
                setNaming(false)
              } else {
                setError('Use a nonempty name of at most 300 characters.')
              }
            }}
            value={name}
          />
        ) : scenario ? (
          <>
            <Text bold color={t.color.primary} wrap="truncate-end">
              {scenario.name} · [n Rename] [Enter Assumption]
            </Text>
            <Text color={t.color.muted}>
              {scenario.kind === 'conditional'
                ? 'Fix selected states; unspecified factors remain uncertain.'
                : 'Exclude selected factors from analysis. Excluded does not mean false.'}
            </Text>
            {assumptions.slice(start, start + visibleRows).map((item, at) => {
              const marker =
                scenario.kind === 'ablation'
                  ? scenario.excluded_assumption_ids.includes(item.id)
                    ? 'exclude'
                    : 'include'
                  : item.id in scenario.conditions
                    ? String(scenario.conditions[item.id])
                    : 'free'

              return (
                <Text
                  color={selection === start + at ? t.color.accent : t.color.primary}
                  key={item.id}
                  wrap="truncate-end"
                >
                  {selection === start + at ? '›' : ' '} [{marker}] {item.statement}
                </Text>
              )
            })}
            <Text color={t.color.muted} wrap="truncate-end">
              {selection + 1}/{assumptions.length} · {assumptions[selection]?.actor} ·{' '}
              {assumptions[selection]?.uncertainty}
            </Text>
          </>
        ) : (
          <>
            <Text color={t.color.muted}>A condition fixes a state. An ablation removes a factor.</Text>
            {menu.slice(start, start + visibleRows).map((label, at) => (
              <Text
                color={selection === start + at ? t.color.accent : t.color.primary}
                key={start + at}
                wrap="truncate-end"
              >
                {selection === start + at ? '› ' : '  '}
                {label}
              </Text>
            ))}
            <Text color={t.color.muted}>
              {selection + 1}/{menu.length} · {assumptions.length} assumptions
            </Text>
          </>
        )}
        <Text color={error ? t.color.error : busy ? t.color.accent : t.color.muted} wrap="truncate-end">
          {error || (busy ? 'Saving scenario…' : 'Scenarios do not change the active forecast.')}
        </Text>
      </Box>
    </ModalOverlay>
  )
}
