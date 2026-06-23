import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'
import { FooterChips } from './footerChips.js'
import { type GlossarySignal, HooksWizard } from './hooksWizard.js'
import { Rule, SectionTitle } from './textBlocks.js'

// Interactive MANAGER for the forecast saturation + style hooks: a two-pane
// master-detail view. Left = every rule with its resolved severity (color
// chips, grouped by category); right = an inspector explaining what the selected
// rule checks + WHY it is at this severity, or (reference mode) the signal
// glossary + reasoning taxonomy. Edits apply immediately against the GLOBAL desk
// policy (config.yaml) via the gateway write RPCs and re-fetch live; a footer
// flash reports what changed. User rules are authored/edited through the guided
// wizard. Only `remove` (irreversible) asks for confirmation.

interface HookIssue {
  field: string
  severity: string
  message: string
  fix: string
}

interface RuleRow {
  id: string
  severity: string
  is_user: boolean
  source: string
  blocks: boolean
  category?: string
  default?: string
  remediation?: string
  doc?: string
  check?: unknown
  valid?: boolean
  issues?: HookIssue[]
}

interface HooksData {
  enabled: boolean
  profile: string
  rules: RuleRow[]
  overrides: Record<string, string>
  glossary: GlossarySignal[]
  operators: string[]
  profiles: string[]
  reasoning_methods: { name: string; doc: string }[]
}

const CATEGORY_ORDER = ['saturation', 'output', 'quorum', 'confidence', 'reasoning', 'decision', 'calibration', 'style', 'custom']
const SEV_CYCLE = ['off', 'warn', 'error']

export function HooksView({ gw, onClose, t }: { gw?: GatewayClient; onClose: () => void; t: Theme }) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24
  const scrollRef = useRef<null | ScrollBoxHandle>(null)
  const [tick, setTick] = useState(0)
  const [data, setData] = useState<HooksData | null>(null)
  const [error, setError] = useState('')
  const [sel, setSel] = useState(0)
  const [focus, setFocus] = useState<'list' | 'inspector'>('list')
  const [reference, setReference] = useState(false)
  const [flash, setFlash] = useState('')
  const [confirmRemove, setConfirmRemove] = useState('')
  const [wizard, setWizard] = useState<null | { editId?: string; initial?: ReturnType<typeof ruleToInitial> }>(null)

  const contentHeight = Math.max(8, termRows - 5)
  const narrow = cols < 92
  const listW = narrow ? cols - 4 : Math.min(40, Math.max(28, Math.floor(cols * 0.34)))

  useEffect(() => {
    const id = setInterval(() => setTick(v => v + 1), 600)

    return () => clearInterval(id)
  }, [])

  const load = () => {
    if (!gw) {
      return
    }

    gw.request('forecast.hooks', {})
      .then(raw => setData((asRpcResult<HooksData>(raw) ?? (raw as { result?: HooksData })?.result ?? null) as HooksData | null))
      .catch((e: unknown) => setError(String(e)))
  }

  useEffect(load, [gw])

  // Ordered rules grouped by category (headers rendered between groups).
  const rules = data?.rules ?? []

  const ordered = [...rules].sort((a, b) => {
    const ca = CATEGORY_ORDER.indexOf(a.category ?? 'custom')
    const cb = CATEGORY_ORDER.indexOf(b.category ?? 'custom')

    return ca === cb ? 0 : (ca < 0 ? 99 : ca) - (cb < 0 ? 99 : cb)
  })

  const current = ordered[Math.min(sel, Math.max(0, ordered.length - 1))]

  const sevColor = (s: string): string => (s === 'error' ? t.color.error : s === 'warn' ? t.color.warn : t.color.muted)

  const mutate = (params: Record<string, unknown>, note: string) => {
    if (!gw) {
      return
    }

    gw.request('forecast.hooks.set', params)
      .then(() => {
        setFlash(note)
        load()
      })
      .catch((e: unknown) => setError(String(e)))
  }

  const cycleSeverity = () => {
    if (!current) {
      return
    }

    const nextSev = SEV_CYCLE[(SEV_CYCLE.indexOf(current.severity) + 1) % SEV_CYCLE.length]!
    mutate({ target: 'severity', rule_id: current.id, value: nextSev }, `${current.id} → ${nextSev}`)
  }

  const cycleProfile = () => {
    if (!data) {
      return
    }

    const profs = data.profiles
    const nextProf = profs[(profs.indexOf(data.profile) + 1) % profs.length]!
    mutate({ target: 'profile', value: nextProf }, `profile → ${nextProf}`)
  }

  useInput((ch, key) => {
    if (wizard) {
      return
    }

    if (confirmRemove) {
      if (ch === 'y' || ch === 'Y') {
        const id = confirmRemove
        setConfirmRemove('')
        gw?.request('forecast.hooks.remove_rule', { id })
          .then(() => {
            setFlash(`removed ${id}`)
            setSel(0)
            load()
          })
          .catch((e: unknown) => setError(String(e)))

        return
      }

      setConfirmRemove('')

      return
    }

    if (key.escape || ch === 'q') {
      if (reference) {
        return setReference(false)
      }

      return onClose()
    }

    if (key.tab) {
      return setFocus(f => (f === 'list' ? 'inspector' : 'list'))
    }

    if (focus === 'inspector') {
      if (key.upArrow || ch === 'k' || key.wheelUp) {
        return scrollRef.current?.scrollBy?.(-2)
      }

      if (key.downArrow || ch === 'j' || key.wheelDown) {
        return scrollRef.current?.scrollBy?.(2)
      }

      if (key.pageUp) {
        return scrollRef.current?.scrollBy?.(-(contentHeight - 2))
      }

      if (key.pageDown) {
        return scrollRef.current?.scrollBy?.(contentHeight - 2)
      }
    }

    // list-focused actions
    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setSel(s => Math.max(0, s - 1))
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setSel(s => Math.min(ordered.length - 1, s + 1))
    }

    if (ch === 'c' || key.leftArrow || key.rightArrow) {
      return cycleSeverity()
    }

    if (ch === 'p') {
      return cycleProfile()
    }

    if (ch === 'e' && current) {
      return mutate({ target: 'enable', rule_id: current.id }, `${current.id} enabled (profile severity)`)
    }

    if (ch === 'd' && current) {
      return mutate({ target: 'disable', rule_id: current.id }, `${current.id} disabled`)
    }

    if (ch === 'r') {
      return setReference(v => !v)
    }

    if (ch === 'n') {
      return setWizard({})
    }

    if (ch === 'E' && current?.is_user) {
      return setWizard({ editId: current.id, initial: ruleToInitial(current) })
    }

    if (ch === 'x' && current?.is_user) {
      return setConfirmRemove(current.id)
    }
  })

  if (wizard && data) {
    return (
      <HooksWizard
        cols={cols}
        editId={wizard.editId}
        glossary={data.glossary}
        gw={gw}
        initial={wizard.initial}
        onCancel={() => setWizard(null)}
        onSaved={id => {
          setWizard(null)
          setFlash(`saved ${id}`)
          load()
        }}
        rows={termRows}
        t={t}
      />
    )
  }

  const list = (
    <Box flexDirection="column" flexShrink={0} width={listW}>
      {(() => {
        let lastCat = ''
        const out: ReactNode[] = []
        ordered.forEach((r, i) => {
          const cat = r.category ?? 'custom'

          if (cat !== lastCat) {
            lastCat = cat
            out.push(
              <Text color={t.color.label} key={`h-${cat}`}>
                {cat}
              </Text>,
            )
          }

          const active = i === sel
          out.push(
            <Box flexDirection="row" key={r.id}>
              <Box flexShrink={0} width={2}>
                <Text color={t.color.accent}>{active ? '▸' : ' '}</Text>
              </Box>
              <Box flexShrink={0} width={6}>
                <Text color={sevColor(r.severity)}>{r.severity}</Text>
              </Box>
              <Text bold={active} color={active ? t.color.text : t.color.muted} wrap="truncate-end">
                {r.is_user ? `${r.valid === false ? '✗' : '✓'} ${r.id}` : r.id}
              </Text>
            </Box>,
          )
        })

        return out
      })()}
    </Box>
  )

  const inspector = (
    <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} ref={scrollRef}>
      <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
        {reference ? (
          <>
            <SectionTitle t={t}>signals a custom rule can test</SectionTitle>
            {(data?.glossary ?? []).map(g => (
              <Box flexDirection="column" key={g.name}>
                <Text wrap="truncate-end">
                  <Text color={t.color.label}>{g.name}</Text>
                  <Text color={t.color.muted}>{`  (${g.kind})`}</Text>
                </Text>
                <Box paddingLeft={2}>
                  <Text color={t.color.muted} wrap="wrap">
                    {g.doc}
                  </Text>
                </Box>
              </Box>
            ))}
            <Box marginTop={1}>
              <SectionTitle t={t}>reasoning methods</SectionTitle>
            </Box>
            {(data?.reasoning_methods ?? []).map(m => (
              <Text color={t.color.muted} key={m.name} wrap="truncate-end">
                <Text color={t.color.label}>{m.name}</Text>
                {`  ${m.doc}`}
              </Text>
            ))}
          </>
        ) : current ? (
          <>
            <Text wrap="truncate-end">
              <Text bold color={t.color.text}>
                {current.id}
              </Text>
              <Text color={sevColor(current.severity)}>{`  [${current.severity}]`}</Text>
              {current.blocks ? <Text color={t.color.error}>{'  (blocks commits)'}</Text> : null}
            </Text>
            <Text color={t.color.muted} wrap="truncate-end">
              {`${current.category ?? 'custom'} · ${current.is_user ? 'user rule' : 'built-in'} · set by ${current.source}`}
              {current.default ? ` · default ${current.default}` : ''}
            </Text>

            <Box marginTop={1} width={Math.max(20, cols - listW - 6)}>
              <Text color={t.color.text} wrap="wrap">
                {current.doc || '(no description)'}
              </Text>
            </Box>

            {current.remediation && current.remediation !== 'none' ? (
              <Box marginTop={1}>
                <Text color={t.color.muted} wrap="wrap">
                  {`remediation: ${current.remediation}`}
                </Text>
              </Box>
            ) : null}

            {current.is_user && current.check ? (
              <Box flexDirection="column" marginTop={1}>
                <Text color={t.color.label}>predicate</Text>
                <Box paddingLeft={2} width={Math.max(20, cols - listW - 8)}>
                  <Text color={t.color.muted} wrap="wrap">
                    {summarizeCheck(current.check)}
                  </Text>
                </Box>
              </Box>
            ) : null}

            {current.issues?.filter(i => i.severity !== 'info').length ? (
              <Box flexDirection="column" marginTop={1}>
                <Text color={t.color.label}>lint</Text>
                {current.issues
                  .filter(i => i.severity !== 'info')
                  .map((i, idx) => (
                    <Box key={idx} paddingLeft={2} width={Math.max(20, cols - listW - 8)}>
                      <Text color={i.severity === 'error' ? t.color.error : t.color.warn} wrap="wrap">
                        {`${i.severity}: ${i.message}${i.fix ? `  → ${i.fix}` : ''}`}
                      </Text>
                    </Box>
                  ))}
              </Box>
            ) : null}

            <Box marginTop={1}>
              <Rule t={t} width={Math.max(12, cols - listW - 6)} />
            </Box>
            <Text color={t.color.muted} wrap="wrap">
              {current.is_user
                ? 'c cycle severity · e enable · d disable · E edit · x remove'
                : 'c cycle severity · e enable (profile) · d disable'}
            </Text>
          </>
        ) : (
          <Text color={t.color.muted}>no rules</Text>
        )}
      </Box>
    </ScrollBox>
  )

  const footerChips = [
    { k: '↑↓', label: 'Select' },
    { k: 'c', label: 'Severity' },
    { k: 'p', label: 'Profile' },
    { k: 'n', label: 'New rule' },
    ...(current?.is_user ? [{ k: 'E', label: 'Edit' }, { k: 'x', label: 'Remove' }] : []),
    { k: 'r', label: reference ? 'Rules' : 'Reference' },
    { k: 'Esc', label: 'Back' },
  ]

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} width={cols}>
      <Text bold color={t.color.accent} wrap="truncate-end">
        FORECAST HOOKS
      </Text>
      <Text color={t.color.muted} wrap="truncate-end">
        {`profile: ${data?.profile ?? '…'}${data && !data.enabled ? ' (disabled)' : ''}`}
        {flash ? <Text color={t.color.ok}>{`   · ${flash}`}</Text> : null}
        {confirmRemove ? <Text color={t.color.error}>{`   · remove ${confirmRemove}? (y/n)`}</Text> : null}
      </Text>

      <Box flexDirection="row" height={contentHeight} marginTop={1} minHeight={0}>
        {error ? (
          <Text color={t.color.error} wrap="wrap">
            {error}
          </Text>
        ) : !data ? (
          <Text color={t.color.muted}>loading…</Text>
        ) : narrow && focus === 'list' && !reference ? (
          list
        ) : narrow ? (
          <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
            {inspector}
            <NoSelect flexShrink={0} marginLeft={1}>
              <OverlayScrollbar scrollRef={scrollRef} t={t} tick={tick} />
            </NoSelect>
          </Box>
        ) : (
          <>
            {list}
            <Box flexShrink={0} marginX={1}>
              <Text color={t.color.border}>{'│'}</Text>
            </Box>
            <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
              {inspector}
              <NoSelect flexShrink={0} marginLeft={1}>
                <OverlayScrollbar scrollRef={scrollRef} t={t} tick={tick} />
              </NoSelect>
            </Box>
          </>
        )}
      </Box>

      <FooterChips chips={footerChips} t={t} />
    </Box>
  )
}

export function ruleToInitial(r: RuleRow): { id: string; desc: string; conditions: { signal: string; op: string; value: string }[]; severity: string; remediation: string } {
  return {
    conditions: checkToConditions(r.check),
    desc: r.doc ?? '',
    id: r.id,
    remediation: r.remediation ?? 'none',
    severity: r.severity,
  }
}

function checkToConditions(check: unknown): { signal: string; op: string; value: string }[] {
  const leaf = (c: Record<string, unknown>) => ({ op: String(c.op ?? ''), signal: String(c.signal ?? ''), value: c.value === undefined ? '' : String(c.value) })

  if (!check || typeof check !== 'object') {
    return []
  }

  const obj = check as Record<string, unknown>

  if (Array.isArray(obj.all)) {
    return (obj.all as Record<string, unknown>[]).filter(c => c && c.signal).map(leaf)
  }

  return obj.signal ? [leaf(obj)] : []
}

export function summarizeCheck(check: unknown): string {
  const conds = checkToConditions(check)

  if (conds.length) {
    return conds.map(c => `${c.signal} ${c.op}${c.op.startsWith('is_') ? '' : ' ' + c.value}`).join('  AND  ')
  }

  return JSON.stringify(check)
}
